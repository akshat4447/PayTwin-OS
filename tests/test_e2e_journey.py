"""E2E journey (§Checkpoint 29): ingest → detect → incident → RCA → twin → decide →
policy → execute → outcome → experiment → dashboard numbers. Deterministic seed."""
from __future__ import annotations

import hashlib
import hmac as _hmac
import json
from datetime import datetime, timezone

from paytwin_api.models import (
    ActionCandidate,
    ActionExecution,
    AuditRecord,
    Incident,
    IncidentEvidence,
    Merchant,
    Organization,
    Payment,
    Prediction,
)
from paytwin_api.services import experiments as exp_svc
from paytwin_api.services import executor, incident_service
from paytwin_api.services.audit import verify_chain
from paytwin_api.services.ingest import ingest_webhook
from paytwin_sim.generator import generate, to_webhook_payloads

SECRET = "sim-secret-dev"
START = datetime(2026, 8, 25, 9, 0, tzinfo=timezone.utc)


def _seed(db):
    db.add(Organization(id="org1", name="Nova Commerce"))
    m = Merchant(id="mer1", organization_id="org1", name="Nova Grocery", short_code="NG",
                 autonomy_mode=4, config={"industry": "grocery", "policy_rules": {}})
    db.add(m)
    db.commit()
    return m


def _ingest_history(db, hours=3, scenarios=None):
    res = generate("mgro", hours, seed=42, start=START, scenarios=scenarios,
                   scenario_start_offset_min=int(hours * 60 * 0.33))
    for payload in to_webhook_payloads(res.events):
        body = json.dumps(payload).encode()
        sig = "sha256=" + _hmac.new(SECRET.encode(), body, hashlib.sha256).hexdigest()
        r = ingest_webhook(db, "simulator", "mer1", body, sig)
        assert r.status == 200, r.body
    return res


class TestFlagshipJourney:
    def test_full_loop(self, db):
        m = _seed(db)
        truth = _ingest_history(db, hours=3, scenarios=["issuer_outage"])

        # ---- DETECT + DIAGNOSE + PROPOSE (one sweep) ----
        opened = incident_service.run_detection_cycle(db, "org1")
        assert len(opened) == 1, "one outage ⇒ one incident"
        inc = opened[0]
        assert inc.state == "ACTION_PROPOSED"
        assert inc.cohort_issuer == "HDFC" and inc.cohort_method == "upi_intent"
        assert inc.rar_paise > 0 and inc.affected_payments > 0
        assert db.query(ActionCandidate).filter_by(incident_id=inc.id).count() >= 3

        # ---- DECIDE: best-EV candidate ranks first ----
        cands = (db.query(ActionCandidate).filter_by(incident_id=inc.id)
                 .order_by(ActionCandidate.rank).all())
        assert cands[0].ev_paise >= cands[1].ev_paise

        # ---- POLICY + EXECUTE (mode 4 = autonomous, within caps) ----
        ex, res = executor.request_execution(db, None, m, cands[0], actor="autopilot")
        assert res.decision == "allow"
        assert ex.state == "SUCCEEDED"
        assert ex.outcome["recovered"] >= 0 and ex.outcome["attempted"] > 0

        # ---- duplicate execution request ⇒ same execution, no second action ----
        ex2, _ = executor.request_execution(db, None, m, cands[0])
        assert ex2.id == ex.id

        # ---- MEASURE: experiment with control/treatment from stored outcomes ----
        exp = exp_svc.create_experiment(db, "org1", "mer1", f"{inc.human_id} recovery",
                                        incident_id=inc.id)
        treated = {ex.id}
        groups = db.query(Payment.group_id).filter_by(merchant_id="mer1").distinct().limit(200).all()
        for (gid,) in groups:
            a = exp_svc.record_assignment(db, exp, gid,
                                          action_execution_id=ex.id if gid in treated else None)
            rec = db.query(Payment).filter_by(group_id=gid, recovered=True).count() > 0
            exp_svc.record_outcome(db, a, recovered=rec, amount_paise=84_000)
        r = exp_svc.results(db, exp)
        assert r["n"]["control"] > 0 and r["n"]["treatment"] > 0

        # ---- AUDIT: full chain intact, incident + action recorded ----
        ok, bad = verify_chain(db, "org1")
        assert ok and bad is None
        types = {t for (t,) in db.query(AuditRecord.action_type).all()}
        assert {"incident.opened", "action.executed"} <= types

        # ---- lifecycle: resolve ----
        incident_service.resolve(db, inc)
        assert db.query(Incident).filter_by(id=inc.id).one().state == "RESOLVED"

    def test_clean_traffic_opens_no_incident(self, db):
        _seed(db)
        _ingest_history(db, hours=3, scenarios=None)
        opened = incident_service.run_detection_cycle(db, "org1")
        assert opened == []

    def test_validated_model_scores_and_traces_recovery_cohort(self, db):
        """A validated artifact must affect proposals, not just sit in the registry."""
        _seed(db)
        _ingest_history(db, hours=3, scenarios=["issuer_outage"])
        from paytwin_sim.demo import train_models

        trained = train_models(db, seed=42)
        assert trained["stage"] == "VALIDATED"
        opened = incident_service.run_detection_cycle(db, "org1")
        assert len(opened) == 1
        inc = opened[0]
        predictions = db.query(Prediction).filter_by(merchant_id="mer1").all()
        assert predictions, "failed incident payments must receive persisted model scores"
        assert {p.model_version for p in predictions} == {trained["version"]}
        assert all(0.0 <= p.p_success <= 1.0 and p.features_hash for p in predictions)
        candidate = (db.query(ActionCandidate).filter_by(incident_id=inc.id)
                     .order_by(ActionCandidate.rank).first())
        assert candidate is not None
        model = candidate.params["model"]
        assert model["status"] == "scored"
        assert model["model_version"] == trained["version"]
        assert candidate.params["p_success"] == model["p_success"]
        assert candidate.params["ranking_formula"].startswith("twin_incremental_rate")
        evidence = db.query(IncidentEvidence).filter_by(incident_id=inc.id, kind="model").all()
        assert len(evidence) == 1 and trained["version"] in evidence[0].ref
