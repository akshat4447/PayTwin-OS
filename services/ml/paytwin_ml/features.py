"""Point-in-time cohort series (ML-001). No future information ever enters a window.

A "payment" dict needs: epoch (int, seconds), failed (bool), and cohort dims
(method/issuer/psp/gateway). Series are built per merchant by the caller.
"""
from __future__ import annotations

from dataclasses import dataclass

import numpy as np


@dataclass
class CohortSeries:
    dims: dict
    minutes: np.ndarray          # absolute minute index per bucket
    attempts: np.ndarray         # attempts per bucket
    failures: np.ndarray         # failures per bucket

    def sr(self) -> np.ndarray:
        """Success rate per bucket (0 where no attempts)."""
        with np.errstate(invalid="ignore", divide="ignore"):
            return np.where(self.attempts > 0,
                            (self.attempts - self.failures) / np.maximum(self.attempts, 1),
                            0.0)


def cohort_series(payments: list[dict], dims: dict, t_start: int, t_end: int) -> CohortSeries:
    """Bucket payments matching `dims` into 1-minute buckets in [t_start, t_end).

    Point-in-time: a payment at epoch e belongs ONLY to bucket floor((e-t_start)/60) —
    no rolling look-ahead is possible by construction.
    """
    n_min = int(t_end - t_start) // 60
    attempts = np.zeros(n_min)
    failures = np.zeros(n_min)
    for p in payments:
        if not _matches(p, dims):
            continue
        b = (int(p["epoch"]) - t_start) // 60
        if 0 <= b < n_min:
            attempts[b] += 1
            failures[b] += 1 if p["failed"] else 0
    minutes = np.arange(n_min)
    return CohortSeries(dims=dims, minutes=minutes, attempts=attempts, failures=failures)


def _matches(p: dict, dims: dict) -> bool:
    return all(p.get(k) == v for k, v in dims.items() if v is not None)


def baseline_sr(series: CohortSeries, exclude_minutes: set[int] | None = None,
                min_attempts: int = 5) -> float:
    """Merchant/cohort expected SR from history (excludes any given window)."""
    exclude = exclude_minutes or set()
    mask = np.array([m not in exclude and a >= min_attempts
                     for m, a in zip(series.minutes, series.attempts)])
    if mask.sum() == 0:
        mask = series.attempts >= max(1, min_attempts // 5)
    if mask.sum() == 0:
        return 0.95  # uninformative prior
    ok = (series.attempts[mask] - series.failures[mask]).sum()
    tot = series.attempts[mask].sum()
    return float(ok / tot)


def feature_vector(payments: list[dict], as_of_epoch: int, dims: dict,
                   windows=(5, 15, 60)) -> dict:
    """Point-in-time features for a cohort as of `as_of_epoch` (inclusive of past only)."""
    out = {"feature_version": "fv1"}
    for w in windows:
        t0 = as_of_epoch - w * 60
        past = [p for p in payments
                if int(p["epoch"]) < as_of_epoch and int(p["epoch"]) >= t0 and _matches(p, dims)]
        n = len(past)
        f = sum(1 for p in past if p["failed"])
        out[f"n_{w}m"] = n
        out[f"fail_{w}m"] = f
        out[f"fail_rate_{w}m"] = f / n if n else 0.0
    return out
