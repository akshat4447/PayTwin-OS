"""Revenue at Risk (ML-005) with uncertainty, validated against simulator truth.

RaR = expected healthy GMV − incident-state expected GMV over the affected cohort,
with an 80% interval from binomial variance + empirical residual quantiles.
"""
from __future__ import annotations

from dataclasses import dataclass
from math import sqrt


@dataclass
class RaR:
    expected_paise: int
    lo_paise: int      # 10th percentile
    hi_paise: int      # 90th percentile
    affected: int
    excess_failures: int
    baseline_sr: float
    window_sr: float


def revenue_at_risk(payments: list[dict], window: tuple[int, int], cohort: dict,
                    baseline_sr: float) -> RaR:
    t0, t1 = window
    coh = [p for p in payments
           if t0 <= int(p["epoch"]) < t1 and all(p.get(k) == v for k, v in cohort.items() if v)]
    n = len(coh)
    fails = [p for p in coh if p["failed"]]
    nf = len(fails)
    window_sr = 1.0 - nf / n if n else baseline_sr
    excess = max(0, nf - int(round(n * (1.0 - baseline_sr))))
    amounts = sorted(p["amount"] for p in fails) or [0]

    # expected loss: excess failures × mean failed amount
    mean_amt = sum(amounts) / len(amounts)
    expected = excess * mean_amt

    # interval: binomial uncertainty on excess + amount spread (empirical p10/p90)
    sigma_n = sqrt(max(n * baseline_sr * (1 - baseline_sr), 1.0))
    lo_n = max(0.0, excess - 1.28 * sigma_n)
    hi_n = excess + 1.28 * sigma_n

    def _pctl(q: float) -> int:
        """Empirical q-quantile of failed amounts (index-safe for any n)."""
        if not amounts:
            return 0
        i = min(len(amounts) - 1, max(0, round(q * (len(amounts) - 1))))
        return int(amounts[i])

    lo = lo_n * _pctl(0.10)
    hi = hi_n * _pctl(0.90)
    # invariant: the point estimate must lie inside its own reported interval
    lo = min(lo, expected)
    hi = max(hi, expected)
    return RaR(expected_paise=int(expected), lo_paise=int(lo), hi_paise=int(hi),
               affected=n, excess_failures=excess, baseline_sr=baseline_sr,
               window_sr=window_sr)
