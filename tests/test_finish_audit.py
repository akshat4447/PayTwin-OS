"""Post-audit regression tests — every fix lands here with disk-level evidence.

Covers: candidate-kind/connector-capability alignment, RaR interval containment,
flagship artifact persistence ACROSS connection boundaries, demo dirty-DB guard,
deterministic training anchor, and tooling CLI health.
"""
from __future__ import annotations

import sqlite3
import subprocess
import sys
from datetime import datetime, timedelta, timezone
from pathlib import Path

import pytest
from sqlalchemy.orm import sessionmaker

from paytwin_api.db import Base, make_engine
from paytwin_api.models import (
    ActionCandidate,
    AuditRecord,
    Experiment,
    Incident,
    Merchant,
    Organization,
    Payment,
)
import paytwin_api.models  # noqa: F401

REPO = Path(__file__).resolve().parents[1]


def _build_world(url: Path):
    engine = make_engine(f"sqlite:///{url}")
    Base.metadata.create_all(engine)
    return engine, sessionmaker(bind=engine, autoflush=False,
                                expire_on_commit=False, future=True)


# ---------------------------------------------------------------- capability gate
def test_payment_link_kind_is_dispatchable():
    """B7c regression: canonical kind 'payment_link' must pass the capability gate."""
    from paytwin_api.connectors import get_connector
    from paytwin_api.connectors.execution import execute_action

    out = execute_action(get_connector("simulator"), "payment_link",
                         {"count": 3, "p_success": 0.5, "avg_amount_paise": 100},
                         idempotency_key="finish-audit-payment-link", secret="x")
    assert out["attempted"] == 3 and out["recovered"] >= 0


def test_candidate_kinds_are_canonical(db):
    """Every ActionCandidate written by _propose_candidates uses a contracts kind."""
    from paytwin_contracts import ActionKind

    from paytwin_api.services.incident_service import _propose_candidates

    db.add(Organization(id="org1", name="N"))
    m = Merchant(id="mer1", organization_id="org1", name="M", short_code="M",
                 autonomy_mode=4,
                 config={"industry": "grocery", "policy_rules": {}})
    db.add(m)
    inc = Incident(organization_id="org1", merchant_id="mer1", human_id="INC-9001",
                   sev="P2", title="t", state="DIAGNOSED")
    db.add(inc)
    db.commit()
    failed = [{"epoch": 0, "failed": True, "amount": 80_000} for _ in range(40)]
    _propose_candidates(db, inc, m, failed, failed)
    kinds = {c.kind for c in
             db.query(ActionCandidate).filter_by(incident_id=inc.id).all()}
    assert kinds <= {k.value for k in ActionKind}, kinds


# ---------------------------------------------------------------- RaR invariants
def test_rar_interval_contains_point_estimate_adversarial_cohorts():
    """B7b regression: point estimate must lie inside [lo, hi] for any cohort size."""
    from paytwin_ml.rar import revenue_at_risk

    t0 = 1_000_000
    cases = [
        # tiny cohort, wildly varied amounts (old p10 index picked amounts[-1])
        [{"epoch": t0 + i, "failed": True, "issuer": "HDFC", "method": "upi_intent",
          "amount": a} for i, a in enumerate([100, 100, 100, 990_000, 990_000])],
        # single failure
        [{"epoch": t0, "failed": True, "issuer": "X", "method": "m",
          "amount": 500_000}],
        # healthy cohort (zero excess)
        [{"epoch": t0 + i, "failed": False, "issuer": "Y", "method": "m",
          "amount": 80_000} for i in range(50)],
    ]
    for coh in cases:
        rar = revenue_at_risk(coh, (t0, t0 + 3600), {"issuer": None}, 0.97)
        assert rar.lo_paise <= rar.expected_paise <= rar.hi_paise, (
            f"n={len(coh)} expected={rar.expected_paise} "
            f"interval=[{rar.lo_paise},{rar.hi_paise}]")
        assert rar.lo_paise <= rar.hi_paise


# ------------------------------------------------- flagship persistence (B1/B4)
def test_flagship_artifacts_persist_to_disk(tmp_path):
    """THE B1 regression: after run_flagship returns, artifacts survive reconnect."""
    from paytwin_api.services.audit import verify_chain
    from paytwin_sim.demo import run_flagship, seed_history, seed_world

    f = tmp_path / "flagship.db"
    engine, factory = _build_world(f)
    s = factory()
    seed_world(s)
    seed_history(s, "org1", seed=7, hours=1.5, only=("mgro",))
    story = run_flagship(s, "org1", seed=7)
    assert story["cohort"] == {"issuer": "HDFC", "method": "upi_intent"}
    assert story["execution_state"] == "SUCCEEDED"
    assert story["recovered_payments"] > 0
    assert story["net_incremental_paise"] > 0
    assert story["blocked_execution_state"] == "REJECTED_BY_POLICY"
    assert story["rollback_execution_state"] == "ROLLED_BACK"
    from paytwin_api.services.experiments import results as experiment_results
    measured = experiment_results(db=s, experiment=s.query(Experiment).one())
    assert measured["intervention_cost_paise"] > 0
    assert measured["audit_refs"]
    assert s.query(Experiment).one().config["eligibility"] == \
        "failed_or_timeout_payment_groups"
    s.close()
    engine.dispose()

    # fresh connection, raw driver: nothing may live only in the old session
    con = sqlite3.connect(f)
    counts = {t: con.execute(f"select count(*) from {t}").fetchone()[0]
              for t in ("incidents", "action_candidates", "action_executions",
                        "policy_decisions", "audit_records", "experiments")}
    con.close()
    assert counts["incidents"] >= 1, counts
    assert counts["action_candidates"] >= 3, counts
    assert counts["action_executions"] >= 1, counts
    assert counts["policy_decisions"] >= 1, counts
    assert counts["audit_records"] >= 2, counts      # opened + executed/blocked
    assert counts["experiments"] >= 1, counts

    engine2 = make_engine(f"sqlite:///{f}")
    s2 = sessionmaker(bind=engine2, expire_on_commit=False)()
    ok, bad = verify_chain(s2, "org1")
    n = s2.query(AuditRecord).filter_by(organization_id="org1").count()
    s2.close()
    engine2.dispose()
    assert ok and bad is None and n > 0              # non-vacuous chain check
    assert story["audit_chain_ok"] is True


def test_demo_main_refuses_dirty_db_without_reset(tmp_path, monkeypatch):
    from paytwin_sim import demo

    f = tmp_path / "dirty.db"
    monkeypatch.setenv("PAYTWIN_DATABASE_URL", f"sqlite:///{f}")
    engine, factory = _build_world(f)
    s = factory()
    s.add(Payment(organization_id="org1", merchant_id="mgro", group_id="g0",
                  provider="simulator", payment_ref="p0", amount_paise=100,
                  status="failed", method="upi_intent", issuer="HDFC",
                  psp="cashfree", occurred_at=datetime.now(timezone.utc)))
    s.commit()
    s.close()
    engine.dispose()

    monkeypatch.delenv("PAYTWIN_DEMO_RESET", raising=False)
    with pytest.raises(SystemExit) as ei:
        demo.main(seed=1)
    assert "PAYTWIN_DEMO_RESET" in str(ei.value)


def test_demo_reset_recovers_stale_metadata_created_schema(tmp_path, monkeypatch):
    """Explicit reset works even if tables are ahead of an old Alembic stamp.

    This reproduces a pre-release Razorpay-demo failure: a previous
    ``create_all`` had created current tables while ``alembic_version`` still
    said c7.  Reset must happen before the demo bootstrap attempts migration.
    """
    from paytwin_sim import demo

    f = tmp_path / "stale-demo.db"
    url = f"sqlite:///{f}"
    monkeypatch.setenv("PAYTWIN_DATABASE_URL", url)
    engine, _factory = _build_world(f)  # current metadata, including orders
    with engine.begin() as conn:
        conn.exec_driver_sql("CREATE TABLE alembic_version (version_num VARCHAR(32))")
        conn.exec_driver_sql(
            "INSERT INTO alembic_version (version_num) VALUES ('c7d2e8a41b90')")
    engine.dispose()

    demo._reset_demo_database()
    db = demo.make_db()
    try:
        assert db.query(Payment).count() == 0
    finally:
        db.close()
    check = make_engine(url)
    try:
        # Reset stamps the database at the installed migration head.  Resolve it
        # from this checkout instead of pinning the test to a past revision.
        from alembic.config import Config
        from alembic.script import ScriptDirectory

        cfg = Config(str(REPO / "services/api/alembic.ini"))
        cfg.set_main_option("script_location", str(REPO / "services/api/alembic"))
        expected_head = ScriptDirectory.from_config(cfg).get_current_head()
        with check.connect() as conn:
            assert conn.exec_driver_sql(
                "SELECT version_num FROM alembic_version").scalar() == expected_head
    finally:
        check.dispose()


# ------------------------------------------------------- determinism / tooling
def test_train_models_deterministic_champion(db):
    """Same DB content + same seed ⇒ identical registered champion (B7a anchor fix)."""
    from paytwin_sim.demo import train_models

    base = datetime(2026, 8, 25, 12, 0, tzinfo=timezone.utc)
    for i in range(120):
        db.add(Payment(
            organization_id="org1", merchant_id="mgro", group_id=f"g{i}",
            provider="simulator", payment_ref=f"p{i}", amount_paise=80_000,
            status="success" if i % 9 else "failed", method="upi_intent",
            issuer="HDFC", psp="cashfree",
            occurred_at=base - timedelta(minutes=i)))
    db.commit()
    r1 = train_models(db, seed=42)
    r2 = train_models(db, seed=42)
    assert r1["version"] == r2["version"]
    assert r1["metrics"] == r2["metrics"]
    assert r1["metrics"]["n"] > 0


def test_clean_world_opens_no_incidents(tmp_path, monkeypatch):
    """Org-wide silence guarantee: i.i.d. noise clusters must NOT open incidents.

    Regression for the mtrav/netbanking false positives (P1s opened on healthy
    merchants). Uses the real ingest path on all four merchants, no scenario.
    """
    import hashlib
    import hmac as _hmac
    import json as _json
    from datetime import datetime, timedelta, timezone as tz

    from paytwin_api.config import get_settings
    from paytwin_api.services.ingest import ingest_webhook
    from paytwin_sim.demo import DEMO_START, MERCHANT_SPECS, seed_world
    from paytwin_sim.generator import generate, to_webhook_payloads

    f = tmp_path / "clean.db"
    monkeypatch.setenv("PAYTWIN_DATABASE_URL", f"sqlite:///{f}")
    engine, factory = _build_world(f)
    s = factory()
    seed_world(s)
    secret = get_settings().webhook_secret_simulator
    start = DEMO_START - timedelta(hours=1.5)
    for mid, _n, _s2, _c, _i, _m, _st, scale, h in MERCHANT_SPECS:
        res = generate(mid, hours=h, seed=42, start=start, scenarios=None,
                       tpm_scale=scale)
        for payload in to_webhook_payloads(res.events):
            body = _json.dumps(payload).encode()
            sig = "sha256=" + _hmac.new(secret.encode(), body,
                                        hashlib.sha256).hexdigest()
            r = ingest_webhook(s, "simulator", mid, body, sig)
            assert r.status == 200
    s.commit()

    from paytwin_api.services.incident_service import run_detection_cycle

    opened = run_detection_cycle(s, "org1")
    s.close()
    engine.dispose()
    assert opened == [], [f"{i.merchant_id}:{i.cohort_issuer}:"
                          f"{i.cohort_method}" for i in opened]


def test_loadtest_cli_parses_url_flag():
    """B2 regression: the CLI accepts --url (previously crashed on args.url)."""
    out = subprocess.run([sys.executable, "scripts/loadtest.py", "--help"],
                         cwd=REPO, capture_output=True, text=True, timeout=60)
    assert out.returncode == 0
    assert "--url" in out.stdout
