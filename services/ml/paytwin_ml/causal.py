"""CAUSAL-002: T-learner uplift + LinUCB offline policy evaluation (numpy/sklearn).

Uplift: two heads estimate E[recover | x, treated] and E[recover | x, control];
uplift(x) = mu1(x) - mu0(x). Honest about what it is: a T-learner, not a causal
discovery method; validity rests on the experiment's randomized assignment.

LinUCB (disjoint linear models per arm) is evaluated OFFLINE against fixed baselines
via logged-bandit replay: a policy earns a stream row's reward only when its choice
matches the logged assignment (standard counterfactual evaluation).
"""
from __future__ import annotations

from dataclasses import dataclass

import numpy as np
from sklearn.ensemble import HistGradientBoostingRegressor


@dataclass
class UpliftModel:
    head_t: object
    head_c: object
    feature_names: list[str] | None = None

    def predict_uplift(self, X: np.ndarray) -> np.ndarray:
        return self.head_t.predict(X) - self.head_c.predict(X)


def fit_t_learner(X: np.ndarray, treated: np.ndarray, recovered: np.ndarray,
                  seed: int = 42) -> UpliftModel:
    """Fit one regressor per arm on the outcome (recovered as 0/1)."""
    treated = np.asarray(treated).astype(bool)
    recovered = np.asarray(recovered).astype(float)

    def _head():
        return HistGradientBoostingRegressor(
            learning_rate=0.08, max_iter=150, max_leaf_nodes=15,
            l2_regularization=0.1, early_stopping=False,
            random_state=seed)

    m1 = _head()
    m0 = _head()
    m1.fit(X[treated], recovered[treated])
    m0.fit(X[~treated], recovered[~treated])
    return UpliftModel(head_t=m1, head_c=m0)


def segment_uplift(model: UpliftModel, X: np.ndarray) -> float:
    """Mean predicted uplift over a context set (used for direction sanity)."""
    preds = model.predict_uplift(X)
    return float(np.mean(preds))


class LinUCB:
    """Disjoint LinUCB over k arms; contexts are real-valued vectors."""

    def __init__(self, n_arms: int, dim: int, alpha: float = 0.6):
        self.k = n_arms
        self.d = dim
        self.alpha = alpha
        self.A = [np.eye(dim) for _ in range(n_arms)]
        self.b = [np.zeros(dim) for _ in range(n_arms)]

    def _theta(self, a: int) -> np.ndarray:
        return np.linalg.solve(self.A[a], self.b[a])

    def choose(self, x: np.ndarray) -> int:
        x = np.asarray(x, dtype=float)
        best_a, best_p = 0, -np.inf
        for a in range(self.k):
            theta = self._theta(a)
            p = float(theta @ x + self.alpha * np.sqrt(float(x @ np.linalg.solve(
                self.A[a], x))))
            if p > best_p:
                best_a, best_p = a, p
        return best_a

    def update(self, x: np.ndarray, arm: int, reward: float) -> None:
        x = np.asarray(x, dtype=float)
        self.A[arm] += np.outer(x, x)
        self.b[arm] += reward * x


class FixedPolicy:
    """Baseline: always pick one arm regardless of context."""

    def __init__(self, arm: int, n_arms: int = 2):
        self.arm = arm
        self.n_arms = n_arms

    def choose(self, x: np.ndarray) -> int:
        return self.arm

    def update(self, x: np.ndarray, arm: int, reward: float) -> None:
        return None


def offline_replay(stream: list[dict], policies: dict) -> dict:
    """Logged-bandit replay over rows {x, arm, reward} (arms are ints).

    Each policy earns row reward iff its choice equals the logged arm; learning
    updates happen only on matched rows (importance-free conservative estimator).
    Returns {policy_name: {"reward": float, "matched": int}}.
    """
    scores = {name: {"reward": 0.0, "matched": 0} for name in policies}
    for row in stream:
        x = np.asarray(row["x"], dtype=float)
        for name, pol in policies.items():
            a = pol.choose(x)
            if a == row["arm"]:
                scores[name]["reward"] += float(row["reward"])
                scores[name]["matched"] += 1
                pol.update(x, a, float(row["reward"]))
    return scores