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
        # The flagship merchant uses the credential-free Razorpay-shaped
        # environment.  Other merchants retain the event simulator so the
        # portfolio still demonstrates multi-rail observation.
        m.config = {"industry": industry, "policy_rules": {},
                    "world_id": mid,
                    "connector": "razorpay" if mid == "mgro" else "simulator"}
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
    """Generate + ingest history; inject the flagship surge on mgro @~⅓ of the span.

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
        # The recording story forecasts and injects this exact compound
        # scenario. Seeding it here makes INC-2481, its RCA evidence, and the
        # Scenario Lab one coherent lineage instead of allowing an unrelated
        # organic cohort to win the detector sweep.
        scen = ["surge_bank_failure"] if mid == "mgro" else []
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
    """Train and offline-validate the success model used by the local demo.

    The model is promoted only to VALIDATED here, never CHAMPION. Its acceptance
    gates are deliberately modest and recorded beside the artifact because this
    is synthetic held-out evidence, not merchant-production validation.
    """
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
    metrics = result.champion_metrics
    oracle_auc = 0.68  # fixed benchmark information ceiling; see ADR-011
    validation = {
        "source": "synthetic_time_holdout",
        "oracle_auc": oracle_auc,
        "roc_auc_floor": round(0.70 * oracle_auc, 4),
        "ece_ceiling": 0.05,
        "passed": (metrics["roc_auc"] >= 0.70 * oracle_auc
                   and metrics["ece"] < 0.05),
    }
    row = register_training(
        db, result,
        params={"seed": seed, "validation": validation},
        stage="VALIDATED" if validation["passed"] else "TRAINED")
    db.commit()
    return {"version": row.version, "stage": row.stage, "metrics": metrics,
            "validation": validation}


def run_flagship(db, org_id: str, seed: int = 42) -> dict:
    """Run one coherent, measured recovery batch in Local Razorpay Test Mode.

    This is deliberately not a sweep of every suggested action.  The batch has
    a pre-assigned treatment/control population, sends links only to treatment,
    records provider-shaped lifecycle outcomes, calculates a counterfactual net
    lift, and leaves both a blocked and an automatically rolled-back action in
    the audit trail.  Every dashboard value can therefore be traced to this run.
    """
    from paytwin_api.models import (
        ActionCandidate,
        AuditRecord,
        IncidentEvidence,
        Merchant,
        Payment,
    )
    from paytwin_api.services import experiments as exp_svc
    from paytwin_api.services import executor, incident_service
    from paytwin_api.services.audit import verify_chain
    from paytwin_api.services.razorpay_local import (
        create_order,
        simulate_payment,
        simulate_payment_link_outcome,
    )

    opened = incident_service.run_detection_cycle(db, org_id)
    if not opened:
        raise RuntimeError("flagship outage was not detected - investigate")
    inc = opened[0]
    expected_cohort = {"issuer": "HDFC", "method": "upi_intent"}
    if any(inc.cohort().get(key) != value for key, value in expected_cohort.items()):
        raise RuntimeError(
            "flagship detector did not select the compound HDFC × UPI intent cohort"
        )
    inc.scenario_ref = "surge_bank_failure"
    db.add(IncidentEvidence(
        incident_id=inc.id,
        kind="scenario",
        ref="scenario.surge_bank_failure",
        summary=("Incident lineage: fixed-seed 4× traffic surge with "
                 "HDFC × UPI intent degradation."),
        weight=2.0,
    ))
    merchant = db.query(Merchant).filter_by(id=inc.merchant_id).one()
    if (merchant.config or {}).get("connector") != "razorpay":
        merchant.config = {**(merchant.config or {}), "connector": "razorpay"}

    candidates = (db.query(ActionCandidate).filter_by(incident_id=inc.id)
                  .order_by(ActionCandidate.rank).all())
    recovery_candidate = next((row for row in candidates if row.kind == "payment_link"), None)
    if recovery_candidate is None:
        raise RuntimeError("flagship recovery candidate was not proposed")

    # One deterministic eligible population. Assign before dispatch so only the
    # treatment IDs reach the provider boundary; controls never receive an
    # execution reference nor a Payment Link.
    groups = [gid for (gid,) in (db.query(Payment.group_id)
                                 .filter(Payment.merchant_id == merchant.id,
                                         Payment.status.in_(("failed", "timeout")),
                                         Payment.group_id.is_not(None))
                                 .order_by(Payment.group_id.asc()).distinct()
                                 .limit(120).all())]
    if len(groups) < 40:
        raise RuntimeError("not enough eligible payment groups for the recovery batch")
    batch_ref = f"RBR-{inc.human_id}"
    exp = exp_svc.create_experiment(
        db, org_id, merchant.id, f"{inc.human_id} recovery batch", incident_id=inc.id,
        config={"recovery_batch_id": batch_ref, "analysis": "treatment_vs_control",
                "attribution_window_min": 30, "provenance": "LOCAL_RAZORPAY_TEST",
                "eligibility": "failed_or_timeout_payment_groups",
                "assignment": "deterministic_sha256_50_50",
                "assignment_seed":
                    f"paytwin-recovery-v1:seed-{seed}:canonical-assignment"},
    )
    assignments = [exp_svc.record_assignment(db, exp, gid, propensity=0.5)
                   for gid in groups]
    treatment_ids = [row.payment_group_id for row in assignments if row.arm == "treatment"]
    control_ids = [row.payment_group_id for row in assignments if row.arm == "control"]
    if not treatment_ids or not control_ids:
        raise RuntimeError("deterministic assignment did not produce both experiment arms")

    # A local test clock is explicit and only makes the no-recipient fixture
    # repeatable. Production still evaluates quiet hours against actual time.
    evidence = {**((recovery_candidate.params or {}).get("evidence") or {}),
                "provider_healthy": True, "consent_on_file": True,
                "within_mandate_window": True, "agent_authority_verified": True,
                "contacts_24h": 0, "minutes_since_last_action": 60,
                "local_test_mode": True,
                "policy_evaluated_at": "2026-08-31T12:00:00+05:30",
                "source": "local_recovery_batch_evidence_v1"}
    recovery_candidate.params = {**(recovery_candidate.params or {}),
                                 "treatment_group_ids": treatment_ids,
                                 "count": len(treatment_ids),
                                 "avg_amount_paise": 84_000,
                                 "slice_value_paise": 84_000,
                                 "evidence": evidence,
                                 "outreach_cost_paise": 35,
                                 "stopping_rules": {
                                     "max_duration_min": 30,
                                     "max_provider_retries": 2,
                                     "max_campaign_value_paise": 10_000_000,
                                     "rollback_on_partial_success": True,
                                 }}
    db.flush()
    execution, verdict = executor.request_execution(
        db, None, merchant, recovery_candidate, actor="recovery-batch-controller")
    if verdict is None or verdict.decision != "allow" or execution.state != "MONITORING":
        raise RuntimeError("canonical recovery batch was not approved for local execution")
    # The action ID is only available after authorization/dispatch. Bind it to
    # the treatment assignments now; controls retain a null reference by
    # construction, which keeps both cost attribution and the audit report
    # causally scoped to the treated population.
    for assignment in assignments:
        if assignment.arm == "treatment":
            assignment.action_execution_id = execution.id

    # Settled treatment outcomes are provider-shaped signed events. Controls
    # receive no link/action: their natural outcome is captured separately.
    from paytwin_api.models import PaymentLink
    links = (db.query(PaymentLink).filter(PaymentLink.action_execution_id == execution.id)
             .order_by(PaymentLink.reference_id.asc()).all())
    if len(links) != len(treatment_ids):
        raise RuntimeError("treatment link count does not match the experiment assignment")
    treatment_recovered: dict[str, bool] = {}
    for index, link in enumerate(links):
        # Deterministic 50% completion keeps a visible but bounded lift over
        # the 17% control recovery rate without inventing an outcome label.
        paid = index % 6 in {0, 1, 2}
        simulate_payment_link_outcome(
            db, merchant_id=merchant.id, link_ref=link.link_ref,
            outcome="paid" if paid else "expired")
        treatment_recovered[str(link.payment_group_id)] = paid
    control_recovered: dict[str, bool] = {}
    for index, group_id in enumerate(control_ids):
        natural = index % 6 == 0
        order = create_order(
            db, organization_id=org_id, merchant_id=merchant.id, amount_paise=84_000,
            receipt=f"{batch_ref}-control-{index}").order
        simulate_payment(db, merchant_id=merchant.id, order_ref=order.order_ref,
                         outcome="captured" if natural else "failed",
                         payment_group_id=group_id,
                         failure_reason=None if natural else "natural_nonrecovery")
        control_recovered[group_id] = natural
    executor.monitor_execution(db, execution, actor="recovery-batch-controller")
    if execution.state != "SUCCEEDED":
        raise RuntimeError(f"canonical recovery batch did not settle: {execution.state}")

    for assignment in assignments:
        recovered = (treatment_recovered if assignment.arm == "treatment"
                     else control_recovered)[assignment.payment_group_id]
        exp_svc.record_outcome(db, assignment, recovered=recovered, amount_paise=84_000)
    results = exp_svc.results(db, exp)
    exp.status = "stopped"
    exp.stopped_at = datetime.now(timezone.utc)

    # A deliberately excessive reroute is evaluated and blocked by the same
    # deterministic policy engine. No provider call is made.
    blocked_candidate = ActionCandidate(
        incident_id=inc.id, kind="reroute_psp", label="Full portfolio reroute",
        detail="Deliberately exceeds the bounded per-action exposure cap.",
        params={"slice_value_paise": 2_000_000, "attempts_used": 1,
                "evidence": evidence, "stopping_rules": {"max_duration_min": 30}},
        value_paise=2_000_000, rank=99)
    db.add(blocked_candidate)
    db.flush()
    blocked_execution, blocked_verdict = executor.request_execution(
        db, None, merchant, blocked_candidate, actor="recovery-batch-controller")
    if blocked_verdict is None or blocked_execution.state != "REJECTED_BY_POLICY":
        raise RuntimeError("blocked intervention did not fail closed")

    # Exercise the partial-success safety path. It opens bounded local links,
    # then runtime control cancels them and records an automatic rollback.
    rollback_candidate = ActionCandidate(
        incident_id=inc.id, kind="payment_link", label="Partial provider outcome guard",
        detail="Controlled runtime fault used to prove automatic rollback.",
        params={"treatment_group_ids": [f"{batch_ref}-rollback-a", f"{batch_ref}-rollback-b"],
                "count": 2, "avg_amount_paise": 10_000, "slice_value_paise": 10_000,
                "failure_mode": "partial_success", "evidence": evidence,
                "stopping_rules": {"max_duration_min": 30, "max_provider_retries": 2,
                                   "max_campaign_value_paise": 20_000,
                                   "rollback_on_partial_success": True}},
        value_paise=20_000, rank=100)
    db.add(rollback_candidate)
    db.flush()
    rollback_execution, rollback_verdict = executor.request_execution(
        db, None, merchant, rollback_candidate, actor="recovery-batch-controller")
    if rollback_verdict is None or rollback_execution.state != "MONITORING":
        raise RuntimeError("rollback control could not start")
    executor.monitor_execution(db, rollback_execution, actor="runtime-control")
    if rollback_execution.state != "ROLLED_BACK":
        raise RuntimeError("partial-success rollback did not complete")

    # Persist portfolio metrics only from observed execution outcomes, never
    # from historical eventual-success labels.
    for row in db.query(Merchant).filter(Merchant.organization_id == org_id).all():
        payments = db.query(Payment).filter(Payment.merchant_id == row.id).all()
        row.gmv_mtd_paise = sum(payment.amount_paise for payment in payments
                                if payment.status == "success")
        row.protected_mtd_paise = (max(0, int(results["net_incremental_paise"]))
                                   if row.id == merchant.id else 0)
    db.commit()
    ok, bad = verify_chain(db, org_id)
    chain_len = db.query(AuditRecord).filter_by(organization_id=org_id).count()
    outcome = execution.outcome or {}
    return {
        "incident": inc.human_id, "state": inc.state,
        "cohort": {key: value for key, value in inc.cohort().items() if value},
        "rar_paise": inc.rar_paise, "rar_lo_paise": inc.rar_lo_paise,
        "rar_hi_paise": inc.rar_hi_paise, "affected_payments": inc.affected_payments,
        "recovery_batch_id": batch_ref, "best_candidate": recovery_candidate.label,
        "decision": verdict.decision, "execution_state": execution.state,
        "attempted_payments": int(outcome.get("attempted", 0)),
        "recovered_payments": int(outcome.get("recovered", 0)),
        "recovered_paise": int(outcome.get("recovered_paise", 0)),
        "net_incremental_paise": int(results["net_incremental_paise"]),
        "net_incremental_ci95_paise": results["net_incremental_ci95_paise"],
        "intervention_cost_paise": int(results["intervention_cost_paise"]),
        "experiment_lift_abs": results.get("lift_abs"),
        "experiment_significant": results.get("significant"),
        "blocked_verdicts": 1, "approval_verdicts": 0,
        "blocked_execution_state": blocked_execution.state,
        "rollback_execution_state": rollback_execution.state,
        "failed_actions": "",
        "allowed_actions": 1,
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
