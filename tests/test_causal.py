"""CAUSAL-002: T-learner uplift direction sanity + LinUCB offline replay beating
fixed baselines on a seeded logged stream."""
from __future__ import annotations

import numpy as np
import pytest

from paytwin_ml.causal import (
    FixedPolicy,
    LinUCB,
    fit_t_learner,
    offline_replay,
)

RNG = np.random.default_rng(42)


def _logged_stream(n: int = 4000, seed: int = 42):
    """Contexts x=[recoverable, noise1, noise2]; treatment helps ONLY when
    recoverable=1. Logged arms are randomized 50/50 (experiment assignment)."""
    rng = np.random.default_rng(seed)
    rows = []
    for _ in range(n):
        x0 = int(rng.random() < 0.5)
        x = [x0, float(rng.integers(0, 4)), float(rng.integers(0, 4))]
        p_treat_effective = 0.25 + (0.55 if x0 == 1 else 0.0)
        p_control = 0.25
        arm = int(rng.random() < 0.5)
        prob = p_treat_effective if arm == 1 else p_control
        recovered = float(rng.random() < prob)
        rows.append({"x": x, "arm": arm, "reward": recovered})
    return rows


@pytest.fixture(scope="module")
def causal_data():
    rows = _logged_stream(6000, seed=7)
    X = np.array([r["x"] for r in rows], dtype=float)
    t = np.array([r["arm"] for r in rows])
    y = np.array([r["reward"] for r in rows])
    return X, t, y


class TestTLearner:
    def test_uplift_direction_on_target_segment(self, causal_data):
        X, t, y = causal_data
        m = fit_t_learner(X, t, y, seed=42)
        target = np.array([[1, 0, 0], [1, 1, 2], [1, 3, 3], [1, 2, 1]],
                          dtype=float)
        other = np.array([[0, 0, 0], [0, 1, 2], [0, 3, 3], [0, 2, 1]],
                         dtype=float)
        up_target = float(np.mean(m.predict_uplift(target)))
        up_other = float(np.mean(m.predict_uplift(other)))
        assert up_target > up_other, (up_target, up_other)
        assert up_target > 0.05  # treatment effect is large on recoverable=1

    def test_deterministic_per_seed(self, causal_data):
        X, t, y = causal_data
        a = fit_t_learner(X, t, y, seed=42).predict_uplift(X[:50])
        b = fit_t_learner(X, t, y, seed=42).predict_uplift(X[:50])
        assert np.allclose(a, b)


class TestLinUCB:
    def test_beats_fixed_baselines_offline(self):
        stream = _logged_stream(3000, seed=11)
        policies = {
            "linucb": LinUCB(n_arms=2, dim=3, alpha=0.6),
            "always_control": FixedPolicy(arm=0),
            "always_treat": FixedPolicy(arm=1),
        }
        scores = offline_replay(stream, policies)
        lu = scores["linucb"]["reward"]
        assert lu >= scores["always_control"]["reward"], scores
        assert lu >= scores["always_treat"]["reward"], scores
        # and it should actually match a healthy share of the log to learn
        assert scores["linucb"]["matched"] > len(stream) * 0.3

    def test_replay_counts_match_log(self):
        stream = [{"x": [0, 0, 0], "arm": a, "reward": 1.0}
                  for a in (0, 1, 0, 1)]
        pol = {"always_control": FixedPolicy(arm=0)}
        s = offline_replay(stream, pol)["always_control"]
        assert s["matched"] == 2 and abs(s["reward"] - 2.0) < 1e-9