"""Graph RCA (ML-004): heterogeneous cohort attribution + counterfactual mask.

Deterministic graph evidence — NOT a trained GNN (honest label; see MODEL_CARD).
Builds the issuer×method×psp failure graph for the incident window, scores edges by
excess-failure concentration, and validates each candidate with a counterfactual mask:
"remove this edge's failures — how much of the merchant's excess failure disappears?"
"""
from __future__ import annotations

from dataclasses import dataclass

import numpy as np


@dataclass
class RcaCandidate:
    edge: dict            # e.g. {"issuer": "HDFC", "method": "upi_intent"}
    score: float          # concentration score 0..1
    rank: int
    counterfactual_share: float  # share of excess failures explained when masked
    excess_failures: int
    at_risk_paise: int


def rank_root_causes(payments: list[dict], window: tuple[int, int],
                     baseline_sr: float, top_k: int = 3) -> list[RcaCandidate]:
    """Rank candidate root-cause edges for payments in `window` [t0, t1)."""
    t0, t1 = window
    win = [p for p in payments if t0 <= int(p["epoch"]) < t1]
    if not win:
        return []
    fails = [p for p in win if p["failed"]]
    total = len(win)
    expected_fails = total * (1.0 - baseline_sr)
    excess = max(1.0, len(fails) - expected_fails)

    # build heterogeneous edge candidates at 2 granularities
    edges: dict[tuple, list[dict]] = {}
    for p in fails:
        for dims in (
            {"issuer": p.get("issuer"), "method": p.get("method")},
            {"issuer": p.get("issuer"), "method": p.get("method"), "psp": p.get("psp")},
            {"psp": p.get("psp")},
            {"method": p.get("method")},
        ):
            key = tuple(sorted((k, v) for k, v in dims.items() if v))
            edges.setdefault(key, []).append(p)

    cands: list[RcaCandidate] = []
    for key, plist in edges.items():
        # concentration: excess share of this edge vs its traffic share
        edge_fails = len(plist)
        dims = dict(key)
        edge_total = sum(1 for p in win if all(p.get(k) == v for k, v in dims.items()))
        if edge_total < 5:
            continue
        edge_expected = edge_total * (1.0 - baseline_sr)
        edge_excess = edge_fails - edge_expected
        # candidacy gate: need real excess mass (≥3 failures AND ≥10% of merchant excess)
        # — otherwise hundreds of candidate edges guarantee a lucky-looking one
        if edge_excess < max(3.0, 0.10 * excess):
            continue
        concentration = edge_excess / excess
        lift = (edge_fails / edge_total) / max(1e-9, (len(fails) / total))

        # significance gate: excess must clear 2σ of binomial noise, else it's luck
        sig = float(np.clip((edge_excess - 2.0 * np.sqrt(max(edge_expected, 1.0)))
                            / max(excess, 1.0), 0.0, 1.0))
        score = float(np.clip(concentration * sig * np.log1p(lift), 0, 1))

        # counterfactual mask: remove this edge's failures from merchant excess
        remaining_excess = max(0.0, excess - edge_excess)
        cf_share = float(np.clip((excess - remaining_excess) / excess, 0, 1))

        cands.append(RcaCandidate(
            edge=dims, score=score, rank=0, counterfactual_share=cf_share,
            excess_failures=int(edge_excess),
            at_risk_paise=int(sum(p["amount"] for p in plist))))

    cands.sort(key=lambda c: (-c.score, -c.counterfactual_share))
    for i, c in enumerate(cands[:top_k]):
        c.rank = i + 1
    return cands[:top_k]


def rca_accuracy(planted: dict, ranked: list[RcaCandidate], k: int = 1) -> bool:
    """Top-k accuracy: does the planted cohort's dims appear in the top-k edge?"""
    for c in ranked[:k]:
        if all(c.edge.get(d) == v for d, v in planted.items() if v):
            return True
    return False
