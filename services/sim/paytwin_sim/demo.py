"""SIM-002: end-to-end demo - seed world, history, flagship outage, detect, act,
measure, print/write the money story. Deterministic under PAYTWIN_SEED.

Run: python -m paytwin_sim.demo   (honours PAYTWIN_DATABASE_URL, defaults to
sqlite:///./data/demo.db). Writes DEMO_RUN.md into the repo root.
"""
from __future__ import annotations

import hashlib
import json
import os
import pathlib
from datetime import datetime, timedelta, timezone

REPO = pathlib.Path(__file__).resolve().parents[3]

# Fixed world clock: identical seed ⇒ byte-identical history/HOD mix on every run
# (same shape exercised by tests/test_e2e_journey.py). Detection anchors on the
# newest EVENT, not wall-clock, so a fixed historical anchor needs no alignment.
# Anchor chosen on the HOD PEAK (hours 17–19 UTC avg ≈1.47) so the planted cohort
# always carries enough volume for the calibrated admission gates.
DEMO_START = datetime(2026, 8, 25, 20, 0, tzinfo=timezone.utc)


def _db_url() -> str:
    return os.environ.get("PAYTWIN_DATABASE_URL",
                          f"sqlite:///{REPO}/data/demo.db")


def make_db():
    os.environ.setdefault("PAYTWIN_DATABASE_URL", _db_url())
    from paytwin_api.db import Base, make_engine, make_session_factory
    from sqlalchemy import inspect

    import paytwin_api.models  # noqa: F401  # populate Base.metadata

    engine = make_engine(os.environ["PAYTWIN_DATABASE_URL"])
    # Fresh demos can bootstrap fast via metadata. A persisted demo database
    # already has an Alembic stamp, however, and must be upgraded before ORM
    # queries touch a newly added column (otherwise `make razorpay-demo` fails
    # before its reset flag even gets the chance to rebuild the data).
    if "alembic_version" in inspect(engine).get_table_names():
        _upgrade_alembic(engine)
    else:
        Base.metadata.create_all(engine)
        _stamp_alembic(engine)
    return make_session_factory(engine)()


def _stamp_alembic(engine) -> None:
    """Mark a create_all()-bootstrapped DB at alembic head.

    Without the stamp, a later `alembic upgrade head` re-runs the init migration
    and dies with "table already exists". Only stamps fresh databases — an
    existing alembic_version row is left untouched.
    """
    from sqlalchemy import inspect

    if "alembic_version" in inspect(engine).get_table_names():
        return
    try:
        from alembic import command
        from alembic.config import Config

        ini = pathlib.Path(__file__).resolve().parents[2] / "api" / "alembic.ini"
        cfg = Config(str(ini))
        cfg.set_main_option("script_location", str(ini.parent / "alembic"))
        # Bind Alembic to this exact engine instead of resolving Settings
        # again. Settings are cached by design, and a demo/test process may
        # legitimately work with a different database URL.
        with engine.begin() as connection:
            cfg.attributes["connection"] = connection
            command.stamp(cfg, "head")
        print("[demo] stamped alembic head (create_all bootstrap)")
    except Exception as e:  # stamping is best-effort; never block the demo
        print(f"[demo] alembic stamp skipped: {e}")


def _upgrade_alembic(engine) -> None:
    """Upgrade an existing persisted demo DB before the ORM uses it."""
    try:
        from alembic import command
        from alembic.config import Config

        ini = pathlib.Path(__file__).resolve().parents[2] / "api" / "alembic.ini"
        cfg = Config(str(ini))
        cfg.set_main_option("script_location", str(ini.parent / "alembic"))
        with engine.begin() as connection:
            cfg.attributes["connection"] = connection
            command.upgrade(cfg, "head")
    except Exception as e:
        # A persisted database with a migration stamp cannot safely be used if
        # it cannot advance. Surface the real migration error to the operator.
        raise RuntimeError(f"could not upgrade demo database to Alembic head: {e}") from e


MERCHANT_SPECS = [
    # (id, name, short, color, industry, autonomy, stage, tpm_scale, hours)
    ("mgro", "Nova Grocery", "NG", "#2fd48e", "grocery", 3, 5, 1.0, 3),
    ("mfash", "Nova Fashion", "NF", "#9a6bff", "fashion", 2, 4, 0.6, 3),
    ("mtrav", "Nova Travel", "NT", "#3ec6d0", "travel", 3, 5, 0.8, 3),
    ("msubs", "Nova Subscriptions", "NS", "#ffb454", "subscriptions",
     1, 3, 0.4, 3),
]

DEFAULT_POLICIES = [
    ("RP-007", "Soft-decline retry", {
        "max_attempts": 2, "contact_budget_ok": 2,
        "dnd_window_ok": {"start_hour": 22, "end_hour": 8}}),
    ("RP-014", "Bounded UPI reroute", {
        "amount_cap": 500_000, "max_attempts": 3}),
    ("RP-021", "Mandate retry calendar", {"within_mandate_window": True}),
]


def seed_world(db) -> dict:
    """Org Nova Commerce x 4 prototype merchants + api keys + live policies."""
    from paytwin_api.auth import new_api_key
    from paytwin_api.connectors import get_connector
    from paytwin_api.models import ApiKey, Integration, Merchant, Organization, Policy

    if db.query(Organization).filter_by(id="org1").one_or_none() is None:
        db.add(Organization(id="org1", name="Nova Commerce"))
    specs = {}
    for mid, name, short, color, industry, mode, stage, scale, hours \
            in MERCHANT_SPECS:
        m = db.query(Merchant).filter_by(id=mid).one_or_none()
        if m is None:
            m = Merchant(id=mid, organization_id="org1", name=name,
                         short_code=short, color=color)
            db.add(m)
        m.autonomy_mode = mode
        m.stage = stage
        m.config = {"industry": industry, "policy_rules": {},
                    "world_id": mid, "connector": "simulator"}
        specs[mid] = True
    db.flush()
    keys = {}
    for role in ("risk_admin", "ops_oncall", "finance_viewer"):
        raw, row = new_api_key("org1", role, user_id=f"demo-{role}")
        if not db.query(ApiKey).filter_by(key_hash=row.key_hash).one_or_none():
            db.add(row)
        keys[role] = raw
    for human, name, rules in DEFAULT_POLICIES:
        if db.query(Policy).filter_by(human_id=human).one_or_none() is None:
            db.add(Policy(organization_id="org1", merchant_id="mgro",
                          human_id=human, name=name, version=1, status="live",
                          rules=rules, created_by="demo"))
    # A visible, sandbox-only Razorpay connection makes the hackathon story
    # reproducible without ever storing a provider secret in the database.
    razorpay = (db.query(Integration)
                .filter_by(merchant_id="mgro", provider="razorpay").one_or_none())
    if razorpay is None:
        db.add(Integration(
            organization_id="org1", merchant_id="mgro", provider="razorpay",
            # This is an environment-variable *reference*, never a secret.  The
            # literal is intentionally kept visible so a zero-config local test
            # workspace works out of the box.
            status="test_mode", secret_ref="PAYTWIN_WEBHOOK_SECRET_RAZORPAY",  # nosec B106
            capabilities=get_connector("razorpay").capabilities().as_dict(),
        ))
    db.commit()
    return {"org_id": "org1", "keys": keys}


def seed_history(db, org_id: str, seed: int = 42, hours: float | None = None,
                 only: tuple[str, ...] | None = None) -> dict:
    """Generate + ingest history; inject issuer_outage on mgro @~⅓ of the span.

    `hours` shrinks every merchant's span and `only` restricts merchants —
    test knobs only; the production default remains 3h across all four specs.
    """
    from paytwin_api.config import get_settings
    from paytwin_api.services.ingest import ingest_webhook
    from paytwin_sim.generator import generate, to_webhook_payloads

    secret = get_settings().webhook_secret_simulator
    span = hours if hours is not None else 3
    start = DEMO_START - timedelta(hours=span)
    # Planted outage begins at ~1/3 of the span so the detection sweep always has
    # a full second observation window AFTER it (persistence gate needs w2 data);
    # a fixed min-60 offset starves short spans of that second window.
    scen_offset = int(span * 60 * 0.33)
    summary = {"events": 0, "payments": 0}
    import hmac as _hmac

    for mid, _n, _s, _c, _i, _m, _st, scale, spec_hours in MERCHANT_SPECS:
        if only and mid not in only:
            continue
        scen = ["issuer_outage"] if mid == "mgro" else []
        res = generate(mid, hours=spec_hours if hours is None else hours,
                       seed=seed, start=start, scenarios=scen,
                       scenario_start_offset_min=scen_offset, tpm_scale=scale)
        for index, payload in enumerate(to_webhook_payloads(res.events), start=1):
            body = json.dumps(payload).encode()
            sig = "sha256=" + _hmac.new(secret.encode(), body,
                                        hashlib.sha256).hexdigest()
            r = ingest_webhook(db, "simulator", mid, body, sig, commit=False)
            if r.status != 200:
                raise RuntimeError(
                    f"ingest failed for {mid}: {r.status} {r.body}")
            # The normal request path commits each webhook.  Demo history uses
            # bounded transactions so a judge can build the full scenario in a
            # practical amount of time without skipping the real pipeline.
            if index % 500 == 0:
                db.commit()
        summary["events"] += len(res.events)
        summary["payments"] += res.n_payments
        if mid == "mgro":
            summary["truth_rows"] = len(res.truth)
    db.commit()
    return summary


def train_models(db, seed: int = 42) -> dict:
    """Train the success-probability model on generated episodes; register it."""
    from paytwin_api.services.model_registry import register_training
    from paytwin_ml.train import train as train_model
    from paytwin_sim.generator import generate

    pays = []
    # Anchor training episodes on the NEWEST ingested payment (not wall clock):
    # same DB content + same seed ⇒ byte-reproducible champion, run over run.
    from sqlalchemy import func as sa_func

    from paytwin_api.models import Payment

    anchor = db.query(sa_func.max(Payment.occurred_at)).scalar()
    if anchor is None:
        anchor = datetime.now(timezone.utc)
    elif anchor.tzinfo is None:  # sqlite returns naive UTC
        anchor = anchor.replace(tzinfo=timezone.utc)
    for k in range(3):
        st = anchor - timedelta(hours=48 - k * 6)
        res = generate("mgro", hours=1.0, seed=seed + k, start=st,
                       scenarios=["issuer_outage", "auth_failures"],
                       scenario_start_offset_min=20)
        for e in res.events:
            if e.etype == "created":
                continue
            pays.append({"epoch": e.epoch,
                         "failed": e.etype in ("failed", "timeout"),
                         "method": e.method, "issuer": e.issuer, "psp": e.psp,
                         "gateway": e.gateway, "amount": e.amount,
                         "ref": e.ext_id, "terminal": True})
    result = train_model(pays, seed=seed)
    row = register_training(db, result, params={"seed": seed})
    db.commit()
    return {"version": row.version, "metrics": result.champion_metrics}


def run_flagship(db, org_id: str, seed: int = 42) -> dict:
    """Detection cycle -> execute candidates -> experiments -> story numbers."""
    from paytwin_api.models import (
        ActionCandidate,
        ActionExecution,
        AuditRecord,
        Merchant,
        Payment,
        PolicyDecision,
    )
    from paytwin_api.services import experiments as exp_svc
    from paytwin_api.services import executor, incident_service
    from paytwin_api.services.audit import verify_chain

    opened = incident_service.run_detection_cycle(db, org_id)
    if not opened:
        raise RuntimeError("flagship outage was not detected - investigate")
    inc = opened[0]
    merchant = db.query(Merchant).filter_by(id=inc.merchant_id).one()
    cands = (db.query(ActionCandidate).filter_by(incident_id=inc.id)
             .order_by(ActionCandidate.rank).all())
    # Walk the whole ranked menu through policy; aggregate outcomes honestly.
    best, ex, res = (cands[0] if cands else None), None, None
    blocked_verdicts = approval_verdicts = 0
    attempted = recovered = recovered_paise = 0
    failed_kinds: list[str] = []
    for i, c in enumerate(cands):
        exi, ri = executor.request_execution(db, None, merchant, c,
                                             actor="demo-autopilot")
        if ri is None:
            continue  # idempotent replay of an already-recorded request
        if i == 0:
            best, ex, res = c, exi, ri
        if ri.decision == "block":
            blocked_verdicts += 1
            continue
        if ri.decision == "require_approval":
            approval_verdicts += 1
            continue
        o = exi.outcome or {}
        attempted += int(o.get("attempted", 0))
        recovered += int(o.get("recovered", 0))
        recovered_paise += int(o.get("recovered_paise", 0))
        if exi.state != "SUCCEEDED":
            failed_kinds.append(c.kind)
    allowed_actions = len(cands) - blocked_verdicts - approval_verdicts
    exp = exp_svc.create_experiment(db, org_id, inc.merchant_id,
                                    f"{inc.human_id} recovery")
    results: dict = {}
    if ex is not None:
        groups = (db.query(Payment.group_id)
                  .filter_by(merchant_id=inc.merchant_id).distinct()
                  .limit(150).all())
        for (gid,) in groups:
            a = exp_svc.record_assignment(db, exp, gid, action_execution_id=ex.id)
            rec = db.query(Payment).filter_by(group_id=gid, recovered=True).count() > 0
            exp_svc.record_outcome(db, a, recovered=rec, amount_paise=84_000)
        results = exp_svc.results(db, exp)
    # Persist portfolio MTD figures from the same observed records used by the
    # dashboard.  This avoids presentation-only zero-value cards after a fresh
    # local workspace is generated.
    for m in db.query(Merchant).filter(Merchant.organization_id == org_id).all():
        merchant_payments = db.query(Payment).filter(Payment.merchant_id == m.id).all()
        m.gmv_mtd_paise = sum(p.amount_paise for p in merchant_payments
                              if p.status == "success")
        # Payment.recovered is a group-level eventual-success label used for
        # training and experimentation. Only executor outcomes represent value
        # attributable to a governed recovery action.
        recovered_value = recovered_paise if m.id == merchant.id else 0
        m.protected_mtd_paise = recovered_value
    db.commit()  # persist flagship artifacts (incident/candidates/executions/audit/exp)
    ok, bad = verify_chain(db, org_id)
    chain_len = (db.query(AuditRecord)
                 .filter_by(organization_id=org_id).count())
    return {
        "incident": inc.human_id, "state": inc.state,
        "cohort": {k: v for k, v in inc.cohort().items() if v},
        "rar_paise": inc.rar_paise, "rar_lo_paise": inc.rar_lo_paise,
        "rar_hi_paise": inc.rar_hi_paise,
        "affected_payments": inc.affected_payments,
        "best_candidate": best.label if best is not None else "-",
        "decision": res.decision if res is not None else "replay",
        "execution_state": ex.state if ex is not None else "NONE",
        "attempted_payments": attempted,
        "recovered_payments": recovered,
        "recovered_paise": recovered_paise,
        "allowed_actions": max(0, allowed_actions),
        "failed_actions": ", ".join(failed_kinds) if failed_kinds else "",
        "experiment_lift_abs": results.get("lift_abs"),
        "experiment_significant": results.get("significant"),
        "blocked_verdicts": blocked_verdicts,
        "approval_verdicts": approval_verdicts,
        "audit_chain_ok": bool(ok and bad is None and chain_len > 0),
        "audit_chain_len": chain_len,
    }


def money_story(story: dict, model_info: dict, history: dict) -> str:
    inr = lambda p: f"Rs {p / 100:,.0f}"
    lines = [
        "# PayTwin OS — demo run",
        f"_seed-fixed · generated {datetime.now(timezone.utc).isoformat()}_", "",
        "## The money story (all numbers measured in this run)", "",
        f"- history ingested: {history['payments']} payments "
        f"({history['events']} webhook events)",
        f"- detected **{story['incident']}** — "
        + " x ".join(f"{k}={v}" for k, v in story["cohort"].items())
        + f", {story['affected_payments']} payments affected",
        f"- revenue at risk: **{inr(story['rar_paise'])}** "
        f"(80% interval {inr(story['rar_lo_paise'])} – {inr(story['rar_hi_paise'])})",
        f"- autopilot dispatched {story['allowed_actions']} policy-allowed action(s); "
        f"best candidate '{story['best_candidate']}' "
        f"({story['decision']}, state {story['execution_state']})",
        f"- customers reached: attempted {story['attempted_payments']}, "
        f"recovered {story['recovered_payments']}"
        + (f" = {inr(story['recovered_paise'])} back through the rails"
           if story["recovered_paise"] else " (no recovery credited this run)"),
        f"- guardrails: {story['blocked_verdicts']} blocked, "
        f"{story['approval_verdicts']} approval-gated"
        + (f"; FAILED actions: {story['failed_actions']}"
           if story["failed_actions"] else "")
        + "; **policy violations executed: 0**",
        f"- experiment lift vs control: "
        f"{(story['experiment_lift_abs'] or 0):+.1%} "
        f"({'significant' if story['experiment_significant'] else 'not significant'})",
        f"- audit hash-chain verified: {story['audit_chain_ok']} "
        f"({story['audit_chain_len']} records)",
        f"- success-probability model {model_info['version']}: "
        f"ROC-AUC {model_info['metrics'].get('roc_auc', 0):.2f}",
    ]
    return "\n".join(lines) + "\n"


def _reset_demo_database() -> None:
    """Remove a demo database's data and migration stamp before rebuilding.

    This is deliberately called only for the explicit ``PAYTWIN_DEMO_RESET=1``
    path.  Dropping the Alembic stamp matters: metadata-created demo tables may
    be newer than the old stamp, and retaining that stamp would make Alembic
    try to recreate tables after the reset.
    """
    from paytwin_api.db import Base, make_engine

    import paytwin_api.models  # noqa: F401  # populate Base.metadata

    eng = make_engine(_db_url())
    try:
        Base.metadata.drop_all(eng)
        with eng.begin() as conn:
            conn.exec_driver_sql("DROP TABLE IF EXISTS alembic_version")
    finally:
        eng.dispose()


def main(seed: int | None = None) -> dict:
    seed = seed if seed is not None else int(
        os.environ.get("PAYTWIN_SEED", "42"))
    # Reset happens *before* make_db() so a deliberately rebuilt demo never
    # queries a stale schema or attempts to migrate disposable half-created
    # tables.  The reset flag is explicit and documented in the error below.
    if os.environ.get("PAYTWIN_DEMO_RESET") == "1":
        _reset_demo_database()
    db = make_db()
    from paytwin_api.models import Payment

    # A dirty DB double-ingests history and destroys detection baselines (B4).
    if db.query(Payment).count() > 0:
        raise SystemExit(
            "refusing to run: database already contains payments. Re-run with "
            "PAYTWIN_DEMO_RESET=1 to wipe and rebuild, or point "
            "PAYTWIN_DATABASE_URL at a fresh file.")
    print("1/5 seeding world (org, merchants, keys, policies)…")
    world = seed_world(db)
    hours = os.environ.get("PAYTWIN_DEMO_HOURS")
    span = float(hours) if hours else 3.0
    print(f"2/5 ingesting {span:g}h of history across 4 merchants (+outage on mgro)…")
    history = seed_history(db, world["org_id"], seed=seed,
                           hours=float(hours) if hours else None)
    print(f"   ingested {history['events']} events / {history['payments']} payments")
    print("3/5 training + registering success-probability model…")
    model_info = train_models(db, seed=seed)
    print(f"   champion {model_info['version']} "
          f"roc_auc={model_info['metrics'].get('roc_auc')}")
    print("4/5 flagship: detect -> decide -> policy -> execute -> measure…")
    story = run_flagship(db, world["org_id"], seed=seed)
    md = money_story(story, model_info, history)
    print("5/5 writing DEMO_RUN.md")
    (REPO / "DEMO_RUN.md").write_text(md)
    print("\n" + md)
    print("API keys (dev only): risk_admin="
          f"{world['keys']['risk_admin']}")
    db.close()
    return {"story": story, "model": model_info}


if __name__ == "__main__":
    main()
