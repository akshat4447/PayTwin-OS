"""DECIDE-001 + GOV-001: EV optimizer and the deterministic policy engine."""
from __future__ import annotations

from datetime import datetime

from paytwin_api.services.optimizer import NO_ACTION, ActionOption, rank_options, select_best
from paytwin_api.services.policy import PolicyContext, evaluate, merge_rules


class TestOptimizer:
    def test_positive_ev_selected(self):
        opts = [ActionOption(kind="retry_burst", label="r", p_succ_delta=0.2,
                             value_paise=100_000, cost_paise=1_800, risk_paise=0)]
        best = select_best(opts)
        assert best.kind == "retry_burst"
        assert best.ev_paise == 20_000 - 1_800

    def test_no_action_when_all_negative(self):
        opts = [ActionOption(kind="retry_burst", label="r", p_succ_delta=0.01,
                             value_paise=100_000, cost_paise=5_000),
                ActionOption(kind="payment_link", label="l", p_succ_delta=0.02,
                             value_paise=50_000, cost_paise=4_000)]
        assert select_best(opts).kind == "do_nothing"

    def test_rank_includes_no_action_and_orders(self):
        opts = [ActionOption(kind="a", label="a", p_succ_delta=0.1, value_paise=100_000),
                ActionOption(kind="b", label="b", p_succ_delta=0.3, value_paise=100_000,
                             cost_paise=25_000)]
        ranked = rank_options(opts)
        assert [o.kind for o in ranked] == ["a", "b", "do_nothing"]
        assert ranked[-1].kind == "do_nothing" and NO_ACTION.ev_paise == 0


class TestPolicyEngine:
    def _ctx(self, **over):
        base = dict(merchant_id="mer1", autonomy_mode=3, action_kind="retry_burst",
                    amount_paise=100_000, attempts_used=1)
        base.update(over)
        return PolicyContext(**base)

    def test_healthy_candidate_allowed_bounded(self):
        r = evaluate(merge_rules({}), self._ctx(amount_paise=100_000))
        assert r.decision == "allow" and not r.failed_rules

    def test_retry_limit_blocks(self):
        r = evaluate(merge_rules({}), self._ctx(attempts_used=3))
        assert r.decision == "block"
        assert any("max_attempts" in f for f in r.failed_rules)

    def test_amount_cap_blocks(self):
        r = evaluate(merge_rules({}), self._ctx(amount_paise=9_000_000))
        assert r.decision == "block" and any("amount_cap" in f for f in r.failed_rules)

    def test_dnd_blocks_contact_actions(self):
        night = PolicyContext(merchant_id="m", autonomy_mode=3, action_kind="payment_link",
                              amount_paise=1000, now=datetime(2026, 8, 25, 23, 0))
        r = evaluate(merge_rules({}), night)
        assert r.decision == "block" and any("dnd_window_ok" in f for f in r.failed_rules)

    def test_contact_budget_blocks(self):
        r = evaluate(merge_rules({}), self._ctx(action_kind="notify_customer", contacts_24h=2))
        assert r.decision == "block" and any("contact_budget_ok" in f for f in r.failed_rules)

    def test_provider_down_blocks(self):
        r = evaluate(merge_rules({}), self._ctx(provider_healthy=False))
        assert r.decision == "block" and any("provider_healthy" in f for f in r.failed_rules)

    def test_no_consent_blocks(self):
        r = evaluate(merge_rules({}), self._ctx(consent_on_file=False))
        assert r.decision == "block" and any("consent_on_file" in f for f in r.failed_rules)

    def test_autonomy_ladder(self):
        assert evaluate(merge_rules({}), self._ctx(autonomy_mode=1)).decision == "require_approval"
        assert evaluate(merge_rules({}), self._ctx(autonomy_mode=2)).decision == "require_approval"
        assert evaluate(merge_rules({}), self._ctx(autonomy_mode=4)).decision == "allow"
        big = evaluate(merge_rules({}), self._ctx(autonomy_mode=3, amount_paise=400_000))
        assert big.decision == "require_approval"  # bounded autopilot: > cap/2 needs human

    def test_hard_violation_beats_autonomy(self):
        r = evaluate(merge_rules({}), self._ctx(autonomy_mode=4, attempts_used=5))
        assert r.decision == "block"
