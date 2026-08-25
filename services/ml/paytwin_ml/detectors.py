"""Temporal anomaly detection (ML-003): EWMA + CUSUM + robust-z ensemble.

Merchant-specific baselines: every statistic is computed AGAINST THE COHORT'S OWN
history — never a universal threshold (§10). Alert fires when ≥2 detectors breach
for `k` consecutive minutes.
"""
from __future__ import annotations

from dataclasses import dataclass, field

import numpy as np

from paytwin_ml.features import CohortSeries, baseline_sr


@dataclass
class Detection:
    fired: bool
    first_minute: int | None = None
    score: float = 0.0
    votes: int = 0
    baseline_sr: float = 0.0
    window_sr: float = 0.0
    detail: dict = field(default_factory=dict)


def ewma_stat(x: np.ndarray, lam: float = 0.3) -> np.ndarray:
    """EWMA of the failure-rate series."""
    if len(x) == 0:
        return np.array([])
    z = np.empty_like(x, dtype=float)
    acc = x[0]
    for i, v in enumerate(x):
        acc = lam * v + (1 - lam) * acc
        z[i] = acc
    return z


def cusum_stat(x: np.ndarray, target: float, k: float = 0.005, h: float = 0.06) -> np.ndarray:
    """One-sided CUSUM for upward shifts in failure rate."""
    s = 0.0
    out = np.empty_like(x, dtype=float)
    for i, v in enumerate(x):
        s = max(0.0, s + (v - target - k))
        out[i] = s
    return (out >= h).astype(float)


def robust_z(x: np.ndarray, baseline: np.ndarray) -> np.ndarray:
    """|z| using median/MAD of the baseline window (robust to the incident itself)."""
    med = np.median(baseline) if len(baseline) else 0.0
    mad = np.median(np.abs(baseline - med)) if len(baseline) else 1.0
    if mad < 1e-9:
        mad = np.std(baseline) if len(baseline) > 1 and np.std(baseline) > 1e-9 else 1.0
    return np.abs((x - med) / (1.4826 * mad))


def pooled_window_z(rate: np.ndarray, att: np.ndarray, base_rate: float,
                    window: int = 3) -> np.ndarray:
    """Binomial z for the trailing `window`-bucket pooled rate vs baseline rate."""
    n = len(rate)
    out = np.zeros(n)
    for i in range(n):
        w0 = max(0, i - window + 1)
        n_i = att[w0 : i + 1].sum()
        f_i = rate[w0 : i + 1] * att[w0 : i + 1]
        p = np.clip(base_rate, 1e-4, 0.999)
        sigma = np.sqrt(p * (1 - p) / max(n_i, 1))
        out[i] = (f_i.sum() / max(n_i, 1) - p) / max(sigma, 1e-9)
    return out


def detect(series: CohortSeries, baseline_minutes: int = 60, bucket_min: int = 5,
           k_consecutive: int = 2, ewma_sigma: float = 3.0, z_thresh: float = 3.5,
           pooled_thresh: float = 3.5) -> Detection:
    """Run the ensemble on `bucket_min`-minute buckets (low-volume cohorts need pooling).

    Baseline = the first `baseline_minutes` of buckets. Fires after `k_consecutive`
    buckets with ≥2/3 detector votes and real traffic (≥3 attempts/bucket).
    """
    n_raw = len(series.attempts)
    n = n_raw // bucket_min
    if n < 6:
        return Detection(fired=False, baseline_sr=baseline_sr(series, min_attempts=1))
    att = series.attempts[: n * bucket_min].reshape(n, bucket_min).sum(axis=1)
    fail = series.failures[: n * bucket_min].reshape(n, bucket_min).sum(axis=1)
    rate = np.divide(fail, np.maximum(att, 1), out=np.zeros(n), where=att > 0)

    base_n = max(3, baseline_minutes // bucket_min)
    bsr = baseline_sr(series, min_attempts=1)

    ew = ewma_stat(rate)
    b_mean = float(np.mean(ew[:base_n]))
    b_std = float(np.std(ew[:base_n]))
    b_std = b_std if b_std > 1e-6 else max(0.005, abs(b_mean) * 0.5 + 0.005)
    ewma_fire = (ew - b_mean) / b_std > ewma_sigma

    cusum_fire = cusum_stat(rate, target=float(np.mean(rate[:base_n]))) > 0

    z = robust_z(rate, rate[:base_n])
    z_fire = z > z_thresh

    base_rate = float(np.mean(rate[:base_n]))
    pz = pooled_window_z(rate, att, base_rate)
    pooled_fire = pz > pooled_thresh

    votes = (ewma_fire.astype(int) + cusum_fire.astype(int)
             + z_fire.astype(int) + pooled_fire.astype(int))

    fired_bucket = None
    confirmed_bucket = None
    ge2 = (att >= 3) & (votes >= 2)
    for i in range(base_n, n):
        w0 = max(base_n, i - 3)
        if ge2[w0 : i + 1].sum() >= 3:  # 3 firing buckets within any 4 — tolerant of 1-dip
            confirmed_bucket = i
            fired_bucket = int(np.argmax(ge2[w0 : i + 1])) + w0
            break

    if fired_bucket is None:
        return Detection(fired=False, votes=int(votes.max()), baseline_sr=bsr,
                         detail={"ewma": bool(ewma_fire[-1]), "cusum": bool(cusum_fire[-1]),
                                 "robust_z": float(z[-1])})
    w_slice = slice(fired_bucket, min(n, fired_bucket + 3))
    w_att = att[w_slice].sum() or 1
    w_fail = fail[w_slice].sum()
    return Detection(
        fired=True,
        first_minute=int(fired_bucket * bucket_min),
        score=float(votes[fired_bucket] / 4),
        votes=int(votes[fired_bucket]),
        baseline_sr=bsr,
        window_sr=1.0 - float(w_fail / w_att),
        detail={"confirmed_minute": int(confirmed_bucket * bucket_min),
                "ewma": bool(ewma_fire[fired_bucket]), "cusum": bool(cusum_fire[fired_bucket]),
                "robust_z": float(z[fired_bucket]), "pooled_z": float(pz[fired_bucket])},
    )
