"""ML-002: point-in-time dataset (no leakage), determinism, model quality measured
against the INFORMATION CEILING of the label, and the model_versions registry row.

Why not ROC-AUC > 0.9? Per-payment failure on this simulator is a fresh Bernoulli
draw given cohort health — most positives are irreducible noise. The ORACLE score
(true cohort SR x active scenario multipliers, i.e. perfect knowledge of the world)
measures ROC-AUC ~0.68 on the holdout. We therefore assert the champion reaches a
high fraction of the oracle ceiling instead of an unreachable absolute number
(recorded in docs/DECISIONS.md ADR-011).
"""
from __future__ import annotations

import os
import pathlib
from datetime import datetime, timedelta, timezone

os.environ.setdefault("PAYTWIN_DATABASE_URL", "sqlite:///./data/test.db")

import numpy as np  # noqa: E402
import pytest  # noqa: E402
from sklearn.metrics import roc_auc_score  # noqa: E402

from paytwin_ml.train import build_dataset, train  # noqa: E402
from paytwin_sim import world  # noqa: E402
from paytwin_sim.generator import generate  # noqa: E402
from paytwin_sim.scenarios import SCENARIOS, matches  # noqa: E402

START = datetime(2026, 8, 25, 9, 0, tzinfo=timezone.utc)
SCENARIO_NAMES = ["issuer_outage", "auth_failures", "psp_degradation",
                  "checkout_regression", "gateway_latency"]
N_EPISODES = 5
SPACING_MIN = 100          # episodes overlap slightly -> interleaved traffic
SCEN_OFFSET = 10


def _episode(k: int) -> list[dict]:
    start = START + timedelta(minutes=SPACING_MIN * k)
    ep_start = int(start.timestamp())
    res = generate("mgro", hours=2.0, seed=200 + k, start=start,
                   scenarios=SCENARIO_NAMES, scenario_start_offset_min=SCEN_OFFSET)
    out = []
    for e in res.events:
        if e.etype == "created":
            continue  # terminal events carry the label
        out.append({"epoch": e.epoch, "failed": e.etype in ("failed", "timeout"),
                    "method": e.method, "issuer": e.issuer, "psp": e.psp,
                    "gateway": e.gateway, "amount": e.amount, "ref": e.ext_id,
                    "terminal": True, "_ep_start": ep_start})
    return out


def _oracle_fail_prob(p: dict) -> float:
    """True P(fail): cohort SR x every active scenario multiplier at that minute."""
    cfg = world.MERCHANTS["mgro"]
    sr = min(0.995, cfg["sr_base"] * world.METHODS[p["method"]]["sr"]
             * world.ISSUERS[p["issuer"]]["sr"] * world.PSPS[p["psp"]]["sr"] / 0.9)
    minute = (p["epoch"] - p["_ep_start"]) // 60
    for name in SCENARIO_NAMES:
        sc = SCENARIOS[name]
        if SCEN_OFFSET <= minute < SCEN_OFFSET + sc.duration_min:
            dims = {"method": p["method"], "issuer": p["issuer"],
                    "psp": p["psp"], "gateway": p["gateway"]}
            if matches(dims, sc.cohort):
                sr = 1.0 - min(0.92, (1.0 - sr) * sc.failure_multiplier)
    return 1.0 - sr


@pytest.fixture(scope="module")
def episodes():
    pays: list[dict] = []
    for k in range(N_EPISODES):
        pays += _episode(k)
    return pays


@pytest.fixture(scope="module")
def trained(episodes):
    return train(episodes, seed=42)


class TestDataset:
    def test_point_in_time_no_leakage(self):
        # A failure burst starting minute 30 must NOT appear in earlier rows' features.
        t0 = int(START.timestamp())
        pays = []
        for m in range(60):
            for j in range(3):
                pays.append({"epoch": t0 + m * 60 + j,
                             "failed": m >= 30 and j == 0,
                             "method": "card", "issuer": "HDFC", "psp": "cashfree",
                             "gateway": "gw1", "amount": 50_000,
                             "ref": f"p{m}_{j}", "terminal": True})
        X, y, names, _ = build_dataset(pays)
        i_n, i_f = names.index("full_n_5m"), names.index("full_fail_5m")
        before = [k for k in range(len(y)) if pays[k]["epoch"] < t0 + 30 * 60]
        after = [k for k in range(len(y)) if pays[k]["epoch"] >= t0 + 33 * 60]
        assert all(X[k][i_f] == 0 for k in before), "future failures leaked backwards"
        assert all(X[k][i_f] >= 1 for k in after[:10])
        assert X[0][i_n] == 0  # first row has no history

    def test_shapes_and_labels(self, episodes):
        X, y, names, epochs = build_dataset(episodes)
        n_roll = len(names) - 16  # minus 5 methods + 5 issuers + 3 psps + 2 gw + amount
        assert n_roll == 4 * 3 * 3  # 4 granularities x {n,fail,rate} x 3 windows
        assert X.shape[0] == y.shape[0] == len(epochs) > 5000
        assert set(np.unique(y)) <= {0.0, 1.0} and 0.01 < y.mean() < 0.5


class TestTraining:
    def test_beats_ceiling_fraction(self, episodes, trained):
        """Champion AUC must approach what PERFECT WORLD-KNOWLEDGE achieves."""
        rows = sorted(episodes, key=lambda p: (int(p["epoch"]), str(p.get("ref", ""))))
        n = len(rows)
        test_rows = rows[int(n * 0.80):]  # mirror train()'s time-based holdout
        y_true = np.array([1 if p["failed"] else 0 for p in test_rows])
        oracle = np.array([_oracle_fail_prob(p) for p in test_rows])
        auc_oracle = roc_auc_score(y_true, oracle)
        champ = trained.champion_metrics
        assert auc_oracle > 0.60, f"fixture lost its signal: oracle={auc_oracle}"
        assert champ["roc_auc"] >= 0.70 * auc_oracle, (
            f"model {champ['roc_auc']:.3f} vs oracle {auc_oracle:.3f}")
        assert champ["roc_auc"] >= 0.55  # absolute sanity floor
        base = float(y_true.mean())
        assert champ["pr_auc"] > base, "no precision lift over the base rate"
        assert champ["brier"] <= base * (1 - base)  # beats a constant-p predictor
        assert champ["ece"] < 0.05  # isotonic calibration actually calibrated

    def test_determinism_same_seed(self, episodes, trained):
        again = train(episodes, seed=42)
        assert again.dataset_fingerprint == trained.dataset_fingerprint
        assert again.version == trained.version
        assert again.champion == trained.champion
        assert again.metrics["lr"] == trained.metrics["lr"]
        assert again.metrics["histgb"] == trained.metrics["histgb"]

    def test_artifacts_written(self, episodes):
        r = train(episodes, seed=7)
        for path in r.artifact_paths.values():
            assert pathlib.Path(path).exists(), path


class TestRegistry:
    def test_row_written_and_idempotent(self, db, episodes, trained):
        from paytwin_api.models import ModelVersion
        from paytwin_api.services.model_registry import register_training

        row = register_training(db, trained)
        db.commit()
        assert row.id and row.stage == "TRAINED"
        assert row.kind == trained.champion_kind
        assert row.dataset_fingerprint == trained.dataset_fingerprint
        assert row.metrics["roc_auc"] == trained.champion_metrics["roc_auc"]
        assert pathlib.Path(row.artifact_path).exists()
        again = register_training(db, trained)
        assert again.id == row.id  # get-or-create: no duplicate version rows
        assert db.query(ModelVersion).filter_by(
            name=trained.name, version=trained.version).count() == 1

    def test_loaded_champion_ranks_failures_higher(self, episodes, trained):
        from paytwin_ml.train import predict_success

        tail = sorted(episodes, key=lambda p: int(p["epoch"]))[-800:]
        X, y, _, _ = build_dataset(tail)
        p_succ = predict_success(trained.artifact_paths[trained.champion], X)
        assert np.all((p_succ >= 0) & (p_succ <= 1))
        p_fail = 1.0 - p_succ
        assert p_fail[y == 1].mean() > p_fail[y == 0].mean()

