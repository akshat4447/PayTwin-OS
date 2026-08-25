"""ML-001/003: point-in-time feature correctness + detector ensemble vs seeded scenarios."""
from __future__ import annotations

from datetime import datetime, timezone

import numpy as np

from paytwin_ml.detectors import detect
from paytwin_ml.features import baseline_sr, cohort_series, feature_vector
from paytwin_sim.generator import generate
from paytwin_sim.world import MERCHANTS

START = datetime(2026, 8, 25, 9, 0, tzinfo=timezone.utc)
T0 = int(START.timestamp())


def _payments(res):
    """Terminal events → payment dicts for the feature/detector layer."""
    out = []
    for e in res.events:
        if e.etype == "created":
            continue
        out.append({"epoch": e.epoch, "failed": e.etype in ("failed", "timeout"),
                    "method": e.method, "issuer": e.issuer, "psp": e.psp,
                    "gateway": e.gateway, "amount": e.amount})
    return out


class TestFeaturesPointInTime:
    def test_series_buckets_only_matching_dims(self):
        pays = [
            {"epoch": T0 + 30, "failed": True, "method": "upi_intent", "issuer": "HDFC"},
            {"epoch": T0 + 40, "failed": False, "method": "card", "issuer": "HDFC"},
            {"epoch": T0 + 90, "failed": False, "method": "upi_intent", "issuer": "HDFC"},
        ]
        s = cohort_series(pays, {"method": "upi_intent", "issuer": "HDFC"}, T0, T0 + 180)
        assert s.attempts.tolist() == [1.0, 1.0, 0.0]
        assert s.failures.tolist() == [1.0, 0.0, 0.0]

    def test_no_future_leakage_in_window(self):
        pays = [
            {"epoch": T0 + 30, "failed": True, "method": "upi_intent", "issuer": "HDFC"},
            {"epoch": T0 + 3600, "failed": True, "method": "upi_intent", "issuer": "HDFC"},  # 60m later
        ]
        fv = feature_vector(pays, as_of_epoch=T0 + 600, dims={"method": "upi_intent", "issuer": "HDFC"})
        assert fv["n_60m"] == 1 and fv["fail_60m"] == 1  # the 3600s event is future → excluded

    def test_merchant_specific_baselines_differ(self):
        """§10 example: same 82% SR is an anomaly for A, healthy for B."""
        rng = np.random.default_rng(5)
        a = [{"epoch": T0 + i * 60, "failed": bool(rng.random() < 0.05),
              "method": "upi", "issuer": "X"} for i in range(120)]
        b = [{"epoch": T0 + i * 60, "failed": bool(rng.random() < 0.18),
              "method": "upi", "issuer": "Y"} for i in range(120)]
        sa = cohort_series(a, {"method": "upi", "issuer": "X"}, T0, T0 + 120 * 60)
        sb = cohort_series(b, {"method": "upi", "issuer": "Y"}, T0, T0 + 120 * 60)
        assert baseline_sr(sa) > 0.93
        assert baseline_sr(sb) < 0.90


class TestDetectorOnScenarios:
    def test_fires_on_issuer_outage_with_delay_le_10min(self):
        res = generate("mgro", 3, seed=42, start=START, scenarios=["issuer_outage"],
                       scenario_start_offset_min=60)
        pays = _payments(res)
        s = cohort_series(pays, {"issuer": "HDFC", "method": "upi_intent"}, T0, T0 + 180 * 60)
        det = detect(s, baseline_minutes=45, bucket_min=5, k_consecutive=2)
        assert det.fired
        delay = det.first_minute - 60
        assert 0 <= delay <= 10, f"detection delay {delay} min"
        assert det.window_sr < det.baseline_sr - 0.03

    def test_silent_on_clean_traffic(self):
        res = generate("mgro", 3, seed=42, start=START)
        pays = _payments(res)
        s = cohort_series(pays, {"issuer": "HDFC", "method": "upi_intent"}, T0, T0 + 180 * 60)
        det = detect(s, baseline_minutes=45, bucket_min=5, k_consecutive=2)
        assert not det.fired

    def test_healthy_high_baseline_merchant_not_flagged(self):
        """mtrav baseline 97.4% — normal noise must not alert (no universal thresholds)."""
        res = generate("mtrav", 2, seed=8, start=START)
        pays = _payments(res)
        s = cohort_series(pays, {"psp": "razorpay"}, T0, T0 + 120 * 60)
        det = detect(s, baseline_minutes=40, bucket_min=5, k_consecutive=2)
        assert not det.fired

    def test_precision_recall_across_scenarios(self):
        """Every injectable degradation scenario is detected on its planted cohort."""
        results = {}
        for kind in ("issuer_outage", "psp_degradation", "checkout_regression",
                     "auth_failures", "rate_limit"):
            res = generate("mgro", 3, seed=42, start=START, scenarios=[kind],
                           scenario_start_offset_min=60)
            pays = _payments(res)
            dims = {}
            for k in ("issuer", "method", "psp"):
                if res.truth and all(t["cohort"][k] == res.truth[0]["cohort"][k] for t in res.truth):
                    dims[k] = res.truth[0]["cohort"][k]
            s = cohort_series(pays, dims, T0, T0 + 180 * 60)
            results[kind] = detect(s, baseline_minutes=45, bucket_min=5,
                                   k_consecutive=2).fired
        assert all(results.values()), results
