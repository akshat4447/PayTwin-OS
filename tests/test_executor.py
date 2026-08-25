"""EXEC-001 + AUDIT-001 + CAUSAL-001: executor idempotency, audit chain, experiments."""
from __future__ import annotations

from paytwin_api.models import (
    ActionCandidate,
    ActionExecution,
    AuditRecord,
    Merchant,
    Organization,
)
from paytwin_api.services import experiments as exp_svc
from paytwin_api.services import executor
from paytwin_api.services.audit import append_audit, verify_chain


def _seed(db, autonomy=3):
    db.add(Organization(id="org1", name="Nova Commerce"))
    m = Merchant(id="mer1", organization_id="org1", name="Nova Grocery", short_code="NG",
                 autonomy_mode=autonomy, config={"policy_rules": {}})
    db.add(m)
    db.commit()
    return m


def _cand(db, m, kind="retry_burst", **params):
    c = ActionCandidate(incident_id="inc1", kind=kind, label=kind,
                        params={"count": 10, "p_success": 0.4, "avg_amount_paise": 50_000,
                                "attempts_used": 1, **params},
                        value_paise=params.get("value_paise", 500_000))
    db.add(c)
    db.commit()
    return c


class TestExecutor:
    def test_allow_executes_once_and_idempotent(self, db):
        m = _seed(db, autonomy=4)
        c = _cand(db, m)
        ex1, res1 = executor.request_execution(db, None, m, c)
        assert ex1.state == "SUCCEEDED" and res1.decision == "allow"
        assert ex1.outcome["attempted"] == 10
        n_exec = db.query(ActionExecution).count()
        ex2, _ = executor.request_execution(db, None, m, c)  # duplicate request
        assert ex2.id == ex1.id
        assert db.query(ActionExecution).count() == n_exec  # exactly one business action

    def test_policy_block_rejected_and_audited(self, db):
        m = _seed(db, autonomy=4)
        c = _cand(db, m, attempts_used=3)  # at retry limit
        ex, res = executor.request_execution(db, None, m, c)
        assert ex.state == "REJECTED_BY_POLICY"
        assert ex.outcome == {} and ex.executed_at is None  # nothing executed
        blocks = db.query(AuditRecord).filter_by(action_type="action.blocked").all()
        assert len(blocks) == 1 and "max_attempts" in blocks[0].summary

    def test_approval_flow(self, db):
        m = _seed(db, autonomy=2)  # approve-first
        c = _cand(db, m)
        ex, res = executor.request_execution(db, None, m, c)
        assert ex.state == "VALIDATED" and res.decision == "require_approval"
        ex2 = executor.approve_and_execute(db, None, ex.id, actor="akshat")
        assert ex2.state == "SUCCEEDED" and ex2.approved_by == "akshat"

    def test_capability_gap_fails_final(self, db):
        m = _seed(db, autonomy=4)
        m2 = Merchant(id="mer2", organization_id="org1", name="X", short_code="X2",
                      autonomy_mode=4, config={"connector": "mockprovider"})
        db.add(m2)
        db.commit()
        c = _cand(db, m2)
        ex, _ = executor.request_execution(db, None, m2, c)
        # mockprovider lacks direct_retry → FAILED_FINAL, audited, no fake success
        assert ex.state == "FAILED_FINAL" and "capability" in ex.outcome.get("error", "")


class TestAuditChain:
    def test_chain_verifies_and_detects_tamper(self, db):
        _seed(db)
        for i in range(5):
            append_audit(db, "org1", actor="system", actor_role="executor",
                         action_type="action.executed", object_type="t", object_id=f"o{i}",
                         summary=f"s{i}", details={"i": i})
        ok, bad = verify_chain(db, "org1")
        assert ok and bad is None
        rec = db.query(AuditRecord).filter_by(seq=3).one()
        rec.details["i"] = 999  # tamper
        ok, bad = verify_chain(db, "org1")
        assert not ok and bad == 3

    def test_chains_are_per_org(self, db):
        _seed(db)
        db.add(Organization(id="org2", name="Other"))
        db.commit()
        append_audit(db, "org1", "a", "system", "t", "o", "1", "s")
        append_audit(db, "org2", "b", "system", "t", "o", "2", "s")
        assert verify_chain(db, "org1")[0] and verify_chain(db, "org2")[0]


class TestExperiments:
    def test_assignment_deterministic_and_split(self, db):
        arms = [exp_svc.assign_arm("exp1", f"grp_{i}") for i in range(200)]
        assert arms == [exp_svc.assign_arm("exp1", f"grp_{i}") for i in range(200)]
        assert 0.3 < arms.count("treatment") / 200 < 0.7

    def test_lift_from_stored_events(self, db):
        _seed(db)
        e = exp_svc.create_experiment(db, "org1", "mer1", "INC recovery A/B")
        for i in range(400):
            a = exp_svc.record_assignment(db, e, f"grp_{i}")
            recovered = (a.arm == "treatment" and i % 10 < 3) or \
                        (a.arm == "control" and i % 10 < 1)
            exp_svc.record_outcome(db, a, recovered=recovered, amount_paise=50_000)
        r = exp_svc.results(db, e)
        assert r["n"]["control"] + r["n"]["treatment"] == 400
        assert abs(r["recovery_rate"]["treatment"] - 0.30) < 0.06
        assert abs(r["recovery_rate"]["control"] - 0.10) < 0.06
        assert r["lift_abs"] > 0.1 and r["significant"]
        assert r["ci95"][0] > 0
