"""QA-001 evaluation harness — prints every number that appears in README.md §14.

All values are MEASURED here against simulator ground truth; nothing is estimated.
Usage: python scripts/evaluate.py   (writes /tmp/eval_numbers.json too)
"""
from __future__ import annotations

import json
from datetime import datetime, timedelta, timezone

import numpy as np

START = datetime(2026, 8, 25, 9, 0, tzinfo=timezone.utc)
T0 = int(START.timestamp())
OFF = 60          # scenario start minute
DUR = 25          # scenario duration minutes
PLANTED = {
    "issuer_outage": {"issuer": "HDFC", "method": "upi_intent"},
    "psp_degradation": {"psp": "cashfree"},
    "checkout_regression": {"method": "card"},
    "auth_failures": {"method": "netbanking"},
    "rate_limit": {"issuer": "SBI"},
}


def payments(res):
    return [{"epoch": e.epoch, "failed": e.etype in ("failed", "timeout"),
             "method": e.method, "issuer": e.issuer, "psp": e.psp,
             "gateway": e.gateway, "amount": e.amount}
            for e in res.events if e.etype != "created"]


def section(title):
    print(f"\n## {title}")


# ---------------------------------------------------------------- success model
def success_model():
    from paytwin_ml.train import train
    from paytwin_sim.generator import generate

    END = datetime(2026, 8, 25, 12, 0, tzinfo=timezone.utc)
    pays = []
    for k in range(3):
        st = END - timedelta(hours=48 - k * 8)
        res = generate("mgro", hours=8.0, seed=100 + k, start=st,
                       scenarios=["issuer_outage", "auth_failures"],
                       scenario_start_offset_min=120)
        for e in res.events:
            if e.etype == "created":
                continue
            pays.append({"epoch": e.epoch,
                         "failed": e.etype in ("failed", "timeout"),
                         "method": e.method, "issuer": e.issuer, "psp": e.psp,
                         "gateway": e.gateway, "amount": e.amount,
                         "ref": e.ext_id, "terminal": True})
    r1 = train(pays, seed=42)
    r2 = train(pays, seed=42)
    m = r1.champion_metrics
    return {"rows": len(pays), "n_test": m["n"], "roc_auc": round(m["roc_auc"], 4),
            "pr_auc": round(m["pr_auc"], 4), "brier": round(m["brier"], 4),
            "ece": round(m["ece"], 4),
            "reproducible": r1.champion_metrics == r2.champion_metrics}


# ------------------------------------------------------- detection / RCA / RaR
def detection_blocks():
    from paytwin_ml.detectors import detect
    from paytwin_ml.features import cohort_series
    from paytwin_ml.rca import rca_accuracy, rank_root_causes
    from paytwin_ml.rar import revenue_at_risk
    from paytwin_sim.generator import generate

    det_rows, rca_hits1, rca_hits3, rar_rows = [], 0, 0, []
    for kind, planted in PLANTED.items():
        res = generate("mgro", 3, seed=42, start=START, scenarios=[kind],
                       scenario_start_offset_min=OFF)
        pays = payments(res)
        pre = [p for p in pays if p["epoch"] < T0 + OFF * 60]
        bsr = 1 - sum(p["failed"] for p in pre) / max(1, len(pre))
        win = (T0 + OFF * 60, T0 + (OFF + DUR) * 60)

        dims = {}
        for k in ("issuer", "method", "psp"):
            if res.truth and all(t["cohort"][k] == res.truth[0]["cohort"][k]
                                 for t in res.truth):
                dims[k] = res.truth[0]["cohort"][k]
        ser = cohort_series(pays, dims, T0, T0 + 180 * 60)
        d = detect(ser, baseline_minutes=45, bucket_min=5, k_consecutive=2)
        delay = (d.first_minute - OFF) if d.fired else None
        det_rows.append({"scenario": kind, "detected": bool(d.fired),
                         "delay_min": delay})

        cands = rank_root_causes(pays, win, baseline_sr=bsr, top_k=3)
        rca_hits1 += int(rca_accuracy(planted, cands, k=1))
        rca_hits3 += int(rca_accuracy(planted, cands, k=3))

        rar = revenue_at_risk(pays, win, planted, bsr)
        true_rar = sum(t["amount_paise"] for t in res.truth)
        covered = rar.lo_paise <= true_rar * 1.05 and rar.hi_paise >= true_rar * 0.95
        rel_err = abs(rar.expected_paise - true_rar) / max(1, true_rar)
        contained = rar.lo_paise <= rar.expected_paise <= rar.hi_paise
        rar_rows.append({"scenario": kind, "covered": bool(covered),
                         "rel_err": round(rel_err, 3),
                         "point_in_interval": bool(contained)})
    return det_rows, rca_hits1, rca_hits3, rar_rows


# ------------------------------------------------------------------- bandit
class _Fixed:
    def __init__(self, arm, n_arms=2):
        self.arm = arm

    def choose(self, x):
        return self.arm

    def update(self, x, arm, reward):
        pass


def bandit():
    from paytwin_ml.causal import LinUCB, offline_replay

    rng = np.random.default_rng(7)
    stream = []
    for _ in range(400):
        x = [1.0, float(rng.random())]
        arm = int(rng.random() < 0.5)          # random logging policy
        base = 0.10 + 0.25 * x[1]              # both arms benefit from context
        reward = float(rng.random() < base + (0.15 if arm == 1 else 0.0))
        stream.append({"x": x, "arm": arm, "reward": reward})
    policies = {"fixed_arm0": _Fixed(0), "linucb": LinUCB(n_arms=2, dim=2)}
    scores = offline_replay(stream, policies)
    return {k: round(v["reward"], 1) for k, v in scores.items()}


def main():
    out = {}
    section("Success model (holdout, seed 42)")
    out["success_model"] = m = success_model()
    print(json.dumps(m, indent=2))

    section("Anomaly detection (planted scenarios vs ground truth)")
    det, r1hits, r3hits, rar_rows = detection_blocks()
    out["detection"] = det
    for r in det:
        print(f"  {r['scenario']:<22} detected={r['detected']} "
              f"delay={r['delay_min']}min")

    out["rca"] = {"top1": r1hits, "top3": r3hits, "scenarios": len(PLANTED)}
    section(f"Graph RCA: top-1 {r1hits}/{len(PLANTED)} · top-3 {r3hits}/{len(PLANTED)}")

    section("Revenue-at-risk vs simulator truth")
    cov = sum(r["covered"] for r in rar_rows)
    med = float(np.median([r["rel_err"] for r in rar_rows]))
    pip = all(r["point_in_interval"] for r in rar_rows)
    out["rar"] = {"coverage80": f"{cov}/{len(rar_rows)}",
                  "median_rel_err": med, "point_in_interval_all": pip}
    print(json.dumps(out["rar"], indent=2))

    section("LinUCB vs fixed-arm offline replay (400 logged rows)")
    out["bandit"] = b = bandit()
    print(b)

    with open("/tmp/eval_numbers.json", "w") as fh:
        json.dump(out, fh, indent=2)
    print("\nwrote /tmp/eval_numbers.json")


if __name__ == "__main__":
    main()

