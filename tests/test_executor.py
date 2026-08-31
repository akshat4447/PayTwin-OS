"""EXEC-001 + AUDIT-001 + CAUSAL-001: executor idempotency, audit chain, experiments."""
from __future__ import annotations

from paytwin_api.models import (
    ActionCandidate,
    ActionExecution,
    AuditRecord,
    Merchant,
    Organization,
    PaymentLink,
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
    evidence = {
        "provider_healthy": True,
        "consent_on_file": True,
        "within_mandate_window": True,
        "agent_authority_verified": True,
        "contacts_24h": 0,
        "minutes_since_last_action": 60,
    }
    c = ActionCandidate(incident_id="inc1", kind=kind, label=kind,
                        params={"count": 10, "p_success": 0.4, "avg_amount_paise": 50_000,
                                "attempts_used": 1, "evidence": evidence, **params},
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

    def test_capability_gap_fails_final(self, db, monkeypatch):
        m = _seed(db, autonomy=4)
        m2 = Merchant(id="mer2", organization_id="org1", name="X", short_code="X2",
                      autonomy_mode=4, config={"connector": "mockprovider"})
        db.add(m2)
        db.commit()
        c = _cand(db, m2)
        # sandbox gate first: real-PSP execution is disabled by default
        ex, _ = executor.request_execution(db, None, m2, c)
        assert ex.state == "FAILED_FINAL" and "disabled" in ex.outcome.get("error", "")
        # with the sandbox flag explicitly on AND the connector secret configured,
        # the capability gap is the failure
        from paytwin_api.config import get_settings

        monkeypatch.setattr(get_settings(), "allow_real_execution", True)
        monkeypatch.setenv("PAYTWIN_MOCKPROVIDER_SECRET", "test-secret")
        db.expire_all()
        c2 = _cand(db, m2, count=7)  # distinct params → distinct idempotency key
        ex2, _ = executor.request_execution(db, None, m2, c2)
        # mockprovider lacks direct_retry → FAILED_FINAL, audited, no fake success
        assert ex2.state == "FAILED_FINAL" and "capability" in ex2.outcome.get("error", "")

    def test_missing_policy_evidence_fails_closed(self, db):
        m = _seed(db, autonomy=4)
        c = ActionCandidate(incident_id="inc1", kind="retry_burst", label="unproven",
                            params={"count": 1, "avg_amount_paise": 50_000,
                                    "attempts_used": 1}, value_paise=50_000)
        db.add(c)
        db.commit()
        ex, result = executor.request_execution(db, None, m, c)
        assert ex.state == "REJECTED_BY_POLICY"
        assert result.decision == "block"
        assert any("provider_healthy" in reason for reason in result.failed_rules)
        assert any("agent_authority" in reason for reason in result.failed_rules)

    def test_retryable_and_partial_provider_failures_are_controlled(self, db):
        m = _seed(db, autonomy=4)
        transient = _cand(db, m, failure_mode="timeout", retry_after_sec=0,
                          stopping_rules={"max_provider_retries": 2})
        ex, result = executor.request_execution(db, None, m, transient)
        assert result.decision == "allow" and ex.state == "FAILED_RETRYABLE"
        # The runtime consumes the recorded retry and succeeds once the injected
        # provider fault is cleared; no duplicate execution row is created.
        assert executor.monitor_execution(db, ex) == "SUCCEEDED"
        assert ex.outcome["attempted"] == 10

        partial = _cand(db, m, failure_mode="partial_success",
                        stopping_rules={"rollback_on_partial_success": True})
        partial_ex, _ = executor.request_execution(db, None, m, partial)
        assert partial_ex.state == "MONITORING"
        assert executor.monitor_execution(db, partial_ex) == "ROLLED_BACK"
        assert partial_ex.outcome["stop_reason"] == "partial_provider_success"

    def test_local_payment_link_halt_cancels_open_links(self, db):
        m = _seed(db, autonomy=4)
        m.config = {"connector": "razorpay"}
        evidence = {"provider_healthy": True, "consent_on_file": True,
                    "within_mandate_window": True, "agent_authority_verified": True,
                    "contacts_24h": 0, "minutes_since_last_action": 60,
                    "local_test_mode": True,
                    "policy_evaluated_at": "2026-08-31T12:00:00+05:30"}
        c = _cand(db, m, kind="payment_link", treatment_group_ids=["g1", "g2"],
                  avg_amount_paise=10_000, slice_value_paise=10_000, evidence=evidence,
                  stopping_rules={"max_duration_min": 30,
                                  "max_campaign_value_paise": 20_000})
        ex, result = executor.request_execution(db, None, m, c)
        assert result.decision == "allow" and ex.state == "MONITORING"
        assert db.query(PaymentLink).filter_by(action_execution_id=ex.id,
                                               status="issued").count() == 2
        halted = executor.halt_execution(db, ex, reason="operator_cancel", actor="operator")
        assert halted.state == "HALTED"
        assert db.query(PaymentLink).filter_by(action_execution_id=ex.id,
                                               status="cancelled").count() == 2


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
        # Assignment is deterministic for a particular experiment but its
        # UUID is intentionally random. Check the planted uplift's robust
        # bounds instead of assuming every fresh hash split has the exact
        # population rate (the old narrow bounds made this test flaky).
        assert 0.20 < r["recovery_rate"]["treatment"] < 0.45
        assert 0.03 < r["recovery_rate"]["control"] < 0.18
        assert r["lift_abs"] > 0.1 and r["significant"]
        assert r["ci95"][0] > 0

    def test_controls_have_no_action_and_money_is_counterfactual(self, db):
        m = _seed(db)
        e = exp_svc.create_experiment(db, "org1", "mer1", "balanced value")
        action = ActionExecution(organization_id="org1", merchant_id=m.id,
                                 human_id="ACT-9000", kind="payment_link",
                                 idempotency_key="measurement-action",
                                 state="SUCCEEDED", outcome={"gross_action_cost_paise": 500})
        db.add(action)
        db.flush()
        for i in range(200):
            assignment = exp_svc.record_assignment(db, e, f"value_group_{i}",
                                                   action_execution_id=action.id)
            # Identical recovery in both arms: differing arm sizes must not
            # fabricate monetary lift from a raw-total subtraction.
            exp_svc.record_outcome(db, assignment, recovered=True, amount_paise=10_000)
            if assignment.arm == "control":
                assert assignment.action_execution_id is None
            else:
                assert assignment.action_execution_id == action.id
        measured = exp_svc.results(db, e)
        assert measured["incremental_gross_paise"] == 0
        assert measured["intervention_cost_paise"] == 500
        assert measured["net_incremental_paise"] == -500
        assert measured["audit_refs"] == [action.human_id]
