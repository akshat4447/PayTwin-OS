"""ML-004/005 + TWIN-001: RCA accuracy, RaR vs ground truth, twin reproducibility."""
from __future__ import annotations

from datetime import datetime, timezone

from paytwin_ml.rca import rca_accuracy, rank_root_causes
from paytwin_ml.rar import revenue_at_risk
from paytwin_ml.twin import SCENARIOS, run_twin
from paytwin_sim.generator import generate
from paytwin_sim.world import MERCHANTS

START = datetime(2026, 8, 25, 9, 0, tzinfo=timezone.utc)
T0 = int(START.timestamp())
SCEN_OFFSET, SCEN_DUR = 60, 25


def _payments(res):
    return [{"epoch": e.epoch, "failed": e.etype in ("failed", "timeout"),
             "method": e.method, "issuer": e.issuer, "psp": e.psp,
             "gateway": e.gateway, "amount": e.amount}
            for e in res.events if e.etype != "created"]


def _injected(kind, merchant="mgro", hours=3):
    return generate(merchant, hours, seed=42, start=START, scenarios=[kind],
                    scenario_start_offset_min=SCEN_OFFSET)


class TestRca:
    def test_top1_on_issuer_outage(self):
        res = _injected("issuer_outage")
        pays = _payments(res)
        base = _payments(generate("mgro", 3, seed=42, start=START))
        # baseline SR from clean history (pre-window)
        pre = [p for p in base if p["epoch"] < T0 + SCEN_OFFSET * 60]
        bsr = 1 - sum(p["failed"] for p in pre) / len(pre)
        cands = rank_root_causes(pays, (T0 + SCEN_OFFSET * 60, T0 + (SCEN_OFFSET + SCEN_DUR) * 60),
                                 baseline_sr=bsr, top_k=3)
        planted = {"issuer": "HDFC", "method": "upi_intent"}
        assert rca_accuracy(planted, cands, k=1), [c.edge for c in cands]
        assert cands[0].counterfactual_share > 0.3

    def test_top3_across_scenarios(self):
        planted_map = {
            "issuer_outage": {"issuer": "HDFC", "method": "upi_intent"},
            "psp_degradation": {"psp": "cashfree"},
            "checkout_regression": {"method": "card"},
            "auth_failures": {"method": "netbanking"},
            "rate_limit": {"issuer": "SBI"},
        }
        hits = 0
        for kind, planted in planted_map.items():
            res = _injected(kind)
            pays = _payments(res)
            pre = [p for p in pays if p["epoch"] < T0 + SCEN_OFFSET * 60]
            bsr = 1 - sum(p["failed"] for p in pre) / max(1, len(pre))
            cands = rank_root_causes(pays, (T0 + SCEN_OFFSET * 60, T0 + (SCEN_OFFSET + SCEN_DUR) * 60),
                                     baseline_sr=bsr, top_k=3)
            hits += rca_accuracy(planted, cands, k=3)
        assert hits >= 4, f"top-3 hits {hits}/5"

    def test_no_candidates_on_clean_traffic(self):
        res = generate("mgro", 2, seed=42, start=START)
        pays = _payments(res)
        bsr = 1 - sum(p["failed"] for p in pays) / len(pays)
        cands = rank_root_causes(pays, (T0 + 60 * 60, T0 + 85 * 60), baseline_sr=bsr, top_k=3)
        assert all(c.score < 0.6 for c in cands)


class TestRaR:
    def test_true_rar_within_interval(self):
        res = _injected("issuer_outage")
        pays = _payments(res)
        pre = [p for p in pays if p["epoch"] < T0 + SCEN_OFFSET * 60]
        bsr = 1 - sum(p["failed"] for p in pre) / len(pre)
        window = (T0 + SCEN_OFFSET * 60, T0 + (SCEN_OFFSET + SCEN_DUR) * 60)
        rar = revenue_at_risk(pays, window, {"issuer": "HDFC", "method": "upi_intent"}, bsr)
        true_rar = sum(t["amount_paise"] for t in res.truth)
        assert rar.excess_failures > 0
        assert rar.lo_paise <= true_rar * 1.05 and rar.hi_paise >= true_rar * 0.95, (
            f"true={true_rar} interval=[{rar.lo_paise},{rar.hi_paise}]")
        assert abs(rar.expected_paise - true_rar) <= max(2.0 * true_rar, 200_000)

    def test_zero_on_healthy_cohort(self):
        res = generate("mgro", 2, seed=42, start=START)
        pays = _payments(res)
        bsr = 1 - sum(p["failed"] for p in pays) / len(pays)
        rar = revenue_at_risk(pays, (T0 + 30 * 60, T0 + 50 * 60),
                              {"issuer": "ICICI", "method": "mandate"}, bsr)
        assert rar.excess_failures == 0 and rar.expected_paise == 0


class TestTwin:
    def _failed(self, n=40, amount=80_000):
        """Recently-failed payments (0–30 min old) — the actionable recovery window."""
        return [{"amount": amount, "age_min": 0.5 * i} for i in range(n)]

    def test_same_seed_byte_identical(self):
        f = self._failed()
        a = run_twin("mgro", "grocery", f, "retry_burst", seed=42, trials=400)
        b = run_twin("mgro", "grocery", f, "retry_burst", seed=42, trials=400)
        assert (a.p50_paise, a.lo_paise, a.hi_paise, a.traj, a.cost_paise) == \
               (b.p50_paise, b.lo_paise, b.hi_paise, b.traj, b.cost_paise)

    def test_different_seed_differs(self):
        f = self._failed()
        results = {run_twin("mgro", "grocery", f, "retry_burst", seed=s, trials=200).p50_paise
                   for s in (1, 2, 3, 4, 5)}
        assert len(results) > 1, f"p50 identical across seeds: {results}"

    def test_retry_beats_do_nothing(self):
        f = self._failed()
        dn = run_twin("mgro", "grocery", f, "do_nothing", seed=42)
        rb = run_twin("mgro", "grocery", f, "retry_burst", seed=42, alloc_pct=25)
        assert rb.p50_paise > dn.p50_paise
        assert rb.p50_paise > rb.cost_paise  # positive EV on assumptions

    def test_all_scenarios_run(self):
        f = self._failed()
        for sc in SCENARIOS:
            r = run_twin("msubs", "subscriptions", f, sc, seed=42)
            assert r.trials == 400 and len(r.traj) == 10
            assert r.lo_paise <= r.p50_paise <= r.hi_paise

    def test_policy_compat_flags_big_alloc(self):
        f = self._failed()
        r = run_twin("mgro", "grocery", f, "retry_burst", seed=42, alloc_pct=80)
        assert r.policy_compat == "approval_required"
