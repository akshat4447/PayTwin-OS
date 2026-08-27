"""SIM-001: determinism, scenario effect, ground truth integrity, throughput headroom."""
from __future__ import annotations

from datetime import datetime, timezone

from paytwin_sim.generator import generate, to_webhook_payloads
from paytwin_sim.scenarios import SCENARIOS
from paytwin_sim.world import MERCHANTS

START = datetime(2026, 8, 25, 9, 0, tzinfo=timezone.utc)


class TestDeterminism:
    def test_same_seed_identical_events(self):
        a = generate("mgro", 2, seed=42, start=START)
        b = generate("mgro", 2, seed=42, start=START)
        assert a.n_payments == b.n_payments > 0
        assert [(e.ext_id, e.etype) for e in a.events] == [(e.ext_id, e.etype) for e in b.events]
        assert [t["amount_paise"] for t in a.truth] == [t["amount_paise"] for t in b.truth]

    def test_different_seed_differs(self):
        a = generate("mgro", 1, seed=1, start=START)
        b = generate("mgro", 1, seed=2, start=START)
        assert [e.ext_id for e in a.events] != [e.ext_id for e in b.events]


class TestScenarioInjection:
    def _window_rate(self, res, window_min, s_start):
        """Aggregate failure rate for the planted cohort inside vs outside the window."""
        win = [0, 0]
        base = [0, 0]
        start_ts = int(START.timestamp())
        for e in res.events:
            if e.etype == "created" or not (e.method == "upi_intent" and e.issuer == "HDFC"):
                continue
            minute = (e.epoch - start_ts) // 60
            bucket = win if s_start <= minute < s_start + window_min else base
            bucket[1] += 1
            bucket[0] += e.etype in ("failed", "timeout")
        wr = win[0] / win[1] if win[1] else 0.0
        br = base[0] / base[1] if base[1] else 0.0
        return wr, br, win[1]

    def test_issuer_outage_raises_windowed_cohort_failure_rate(self):
        inj = generate("mgro", 3, seed=42, start=START, scenarios=["issuer_outage"],
                       scenario_start_offset_min=60)
        wr, br, n = self._window_rate(inj, 25, 60)
        assert n >= 30, f"cohort too thin in window: {n}"
        assert wr > 0.10 and wr > br * 3, f"window={wr} base={br}"

    def test_truth_records_exist_and_match_planted_cohort(self):
        inj = generate("mgro", 3, seed=42, start=START, scenarios=["issuer_outage"],
                       scenario_start_offset_min=60)
        assert len(inj.truth) >= 5
        assert {t["kind"] for t in inj.truth} == {"issuer_outage"}
        for t in inj.truth:
            assert t["cohort"]["issuer"] == "HDFC" and t["cohort"]["method"] == "upi_intent"

    def test_truth_rar_is_quantified(self):
        inj = generate("mgro", 3, seed=42, start=START, scenarios=["issuer_outage"],
                       scenario_start_offset_min=60)
        true_rar = sum(t["amount_paise"] for t in inj.truth)
        assert true_rar > 100_000  # meaningful revenue at risk (paise)

    def test_no_scenario_no_truth(self):
        r = generate("mgro", 1, seed=7, start=START)
        assert r.truth == []

    def test_surge_plus_bank_failure_scales_traffic_and_keeps_attribution(self):
        base = generate("mgro", 2, seed=42, start=START,
                        scenario_start_offset_min=60)
        stressed = generate("mgro", 2, seed=42, start=START,
                            scenarios=["surge_bank_failure"],
                            scenario_start_offset_min=60)
        # The active 20-minute 4× window lifts overall volume substantially;
        # exact equality is intentionally not expected from Poisson traffic.
        base_terminal = [e for e in base.events
                         if e.etype != "created" and 60 <= (e.epoch - int(START.timestamp())) // 60 < 80]
        stress_terminal = [e for e in stressed.events
                           if e.etype != "created" and 60 <= (e.epoch - int(START.timestamp())) // 60 < 80]
        assert len(stress_terminal) > len(base_terminal) * 2.5
        assert stressed.truth
        assert {row["kind"] for row in stressed.truth} == {"surge_bank_failure"}
        assert all(row["cohort"]["issuer"] == "HDFC"
                   and row["cohort"]["method"] == "upi_intent"
                   for row in stressed.truth)


class TestScaleAndContracts:
    def test_500k_capability(self):
        # 4 merchants × ~24h ≈ 120k payments; scale check on one merchant slice
        import time

        t0 = time.time()
        r = generate("mtrav", 6, seed=9, start=START, tpm_scale=3.0)
        dt = time.time() - t0
        assert r.n_payments > 3000
        assert dt < 30  # generation speed ⇒ 500k events/day feasible (measured in EVALUATION)

    def test_webhook_payloads_match_connector_dialect(self):
        r = generate("mgro", 0.5, seed=3, start=START)
        payloads = to_webhook_payloads(r.events)
        assert payloads[0]["event"] == "created"
        assert payloads[1]["event"] in ("success", "failed", "timeout")
        for p in payloads[:5]:
            assert set(p) == {"event", "id", "created_at", "data"}
            assert "payment_id" in p["data"] and "amount" in p["data"]

    def test_all_merchants_generate(self):
        for mid in MERCHANTS:
            r = generate(mid, 1, seed=11, start=START)
            assert r.n_payments > 100, mid
