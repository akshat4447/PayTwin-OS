"""ML-002: supervised success-probability training + model registry artifacts.

Point-in-time dataset from payment dicts (no leakage: rolling cohort features use
STRICTLY EARLIER payments only), LogisticRegression baseline + HistGradientBoosting,
each isotonic-calibrated on a time-separated slice, scored on a later holdout
(ROC-AUC / PR-AUC / Brier / ECE). Deterministic under a fixed seed.
"""
from __future__ import annotations

import hashlib
import json
import pathlib
from dataclasses import dataclass, field

import joblib
import numpy as np
from sklearn.ensemble import HistGradientBoostingClassifier
from sklearn.isotonic import IsotonicRegression
from sklearn.linear_model import LogisticRegression
from sklearn.metrics import average_precision_score, brier_score_loss, roc_auc_score
from sklearn.pipeline import Pipeline
from sklearn.preprocessing import StandardScaler

FEATURE_VERSION = "fv2"
WINDOWS = (5, 15, 60)
LEVELS = ("full", "issuer_method", "method", "issuer")
ARTIFACT_DIR = pathlib.Path(__file__).resolve().parents[1] / "artifacts"
SEED_DEFAULT = 42


def _level_key(level: str, p: dict) -> tuple:
    m, i, ps, g = p.get("method"), p.get("issuer"), p.get("psp"), p.get("gateway")
    return {"full": (m, i, ps, g), "issuer_method": (i, m),
            "method": (m,), "issuer": (i,)}[level]


def _ece(y: np.ndarray, p: np.ndarray, bins: int = 10) -> float:
    """Expected calibration error over equal-width confidence bins."""
    idx = np.clip((p * bins).astype(int), 0, bins - 1)
    ece = 0.0
    for b in range(bins):
        m = idx == b
        if not m.any():
            continue
        ece += (m.sum() / len(y)) * abs(y[m].mean() - p[m].mean())
    return float(ece)


def build_dataset(payments: list[dict], windows=WINDOWS):
    """X, y, feature_names, epochs for every TERMINAL payment row.

    Rolling cohort features are computed at FOUR granularities (full
    issuer×method×psp×gateway, issuer×method, method, issuer) from strictly earlier
    payments only — coarse levels keep degradation bursts visible when the fine
    cohort is too sparse. Plus static cohort one-hots and log-amount.
    """
    term = [p for p in payments if p.get("terminal", True)]
    term = sorted(term, key=lambda p: (int(p["epoch"]), str(p.get("ref", ""))))
    methods = ["upi_intent", "upi_collect", "card", "netbanking", "mandate"]
    issuers = ["HDFC", "ICICI", "SBI", "AXIS", "KOTAK"]
    psps = ["cashfree", "razorpay", "payu"]
    gateways = ["gw1", "gw2"]
    names: list[str] = []
    for lvl in LEVELS:  # same grouping as the writes below: n*, fail*, fr*
        names += [f"{lvl}_n_{w}m" for w in windows]
        names += [f"{lvl}_fail_{w}m" for w in windows]
        names += [f"{lvl}_fr_{w}m" for w in windows]
    names += ([f"m_{m}" for m in methods] + [f"i_{i}" for i in issuers]
              + [f"p_{p}" for p in psps] + [f"g_{g}" for g in gateways]
              + ["amount_log"])

    n = len(term)
    n_roll = len(names) - (len(methods) + len(issuers) + len(psps)
                           + len(gateways) + 1)
    X = np.zeros((n, len(names)))
    y = np.zeros(n)
    epochs = np.zeros(n)

    for li, lvl in enumerate(("full", "issuer_method", "method", "issuer")):
        groups: dict[tuple, list[int]] = {}
        for i, p in enumerate(term):
            groups.setdefault(_level_key(lvl, p), []).append(i)
        col0 = li * 3 * len(windows)
        for idxs in groups.values():
            ep = np.array([int(term[i]["epoch"]) for i in idxs])
            fl = np.array([1 if term[i]["failed"] else 0 for i in idxs])
            att_pref = np.concatenate([[0.0], np.arange(1, len(idxs) + 1)])
            fail_pref = np.concatenate([[0.0], np.cumsum(fl)]).astype(float)
            for j, i in enumerate(idxs):
                hi_strict = j  # STRICTLY earlier rows only (no self-leakage)
                for wi, w in enumerate(windows):
                    lo_w = min(int(np.searchsorted(ep, ep[j] - w * 60, side="left")),
                               hi_strict)
                    n_w = att_pref[hi_strict] - att_pref[lo_w]
                    f_w = fail_pref[hi_strict] - fail_pref[lo_w]
                    X[i, col0 + wi] = n_w
                    X[i, col0 + len(windows) + wi] = f_w
                    X[i, col0 + 2 * len(windows) + wi] = (
                        (f_w / n_w) if n_w >= 3 else -1.0)

    # static cohort one-hots + amount + label
    base = n_roll
    for i, p in enumerate(term):
        if p.get("method") in methods:
            X[i, base + methods.index(p["method"])] = 1.0
        if p.get("issuer") in issuers:
            X[i, base + len(methods) + issuers.index(p["issuer"])] = 1.0
        if p.get("psp") in psps:
            X[i, base + len(methods) + len(issuers) + psps.index(p["psp"])] = 1.0
        if p.get("gateway") in gateways:
            X[i, base + len(methods) + len(issuers) + len(psps)
              + gateways.index(p["gateway"])] = 1.0
        X[i, -1] = np.log1p(float(p.get("amount", 0)) / 100.0)
        y[i] = 1 if p["failed"] else 0
        epochs[i] = int(p["epoch"])
    return X, y, names, epochs


@dataclass
class TrainingResult:
    name: str
    version: str
    feature_version: str
    dataset_fingerprint: str
    champion: str                      # "lr" | "histgb"
    metrics: dict = field(default_factory=dict)
    artifact_paths: dict = field(default_factory=dict)

    @property
    def champion_kind(self) -> str:
        return {"lr": "LogisticRegression+Isotonic",
                "histgb": "HistGradientBoostingClassifier+Isotonic"}[self.champion]

    @property
    def champion_metrics(self) -> dict:
        return self.metrics[self.champion]


def _isotonic_calibrate(model, X_fit, y_fit, X_cal, y_cal):
    """Fit base model on train slice, wrap with isotonic on the calibration slice."""
    model.fit(X_fit, y_fit)
    raw = model.predict_proba(X_cal)[:, 1]
    iso = IsotonicRegression(out_of_bounds="clip")
    iso.fit(raw, y_cal)
    return model, iso


def _metrics(y_true, p_hat) -> dict:
    out = {
        "roc_auc": float(roc_auc_score(y_true, p_hat)),
        "pr_auc": float(average_precision_score(y_true, p_hat)),
        "brier": float(brier_score_loss(y_true, p_hat)),
        "ece": _ece(np.asarray(y_true, dtype=float), np.asarray(p_hat)),
        "n": int(len(y_true)),
    }
    return {k: (round(v, 6) if isinstance(v, float) else v) for k, v in out.items()}


def _fingerprint(payments: list[dict]) -> str:
    payload = sorted(
        [str(p.get("ref", "")), int(p["epoch"]), 1 if p["failed"] else 0]
        for p in payments if p.get("terminal", True))
    blob = json.dumps(payload, separators=(",", ":")).encode()
    return hashlib.sha256(blob).hexdigest()[:16]


def train(payments: list[dict], seed: int = SEED_DEFAULT,
          name: str = "success_prob") -> TrainingResult:
    """Train both candidates + isotonic calibration; pick champion by test PR-AUC.

    Time-based split by epoch: first 60% fit, next 20% calibration, last 20% test.
    Same seed + same payments ⇒ identical metrics and fingerprint (tested).
    """
    X, y, feat_names, epochs = build_dataset(payments)
    order = np.argsort(epochs, kind="stable")
    X, y, epochs = X[order], y[order], epochs[order]
    n = len(y)
    if n < 200 or y.sum() < 20:
        raise ValueError(f"dataset too small: n={n}, positives={int(y.sum())}")
    t1, t2 = int(n * 0.60), int(n * 0.80)
    slices = {"fit": slice(0, t1), "cal": slice(t1, t2), "test": slice(t2, n)}
    Xf, yf = X[slices["fit"]], y[slices["fit"]]
    Xc, yc = X[slices["cal"]], y[slices["cal"]]
    Xt, yt = X[slices["test"]], y[slices["test"]]
    if len(np.unique(yf)) < 2 or len(np.unique(yc)) < 2 or len(np.unique(yt)) < 2:
        raise ValueError("each time slice needs both classes")

    lr_base = Pipeline([
        ("scaler", StandardScaler()),
        ("lr", LogisticRegression(C=1.0, max_iter=2000, random_state=seed)),
    ])
    hist_base = HistGradientBoostingClassifier(
        learning_rate=0.08, max_iter=200, max_leaf_nodes=15, l2_regularization=0.1,
        early_stopping=False, random_state=seed)

    fitted = {}
    for key, base in (("lr", lr_base), ("histgb", hist_base)):
        model, iso = _isotonic_calibrate(base, Xf, yf, Xc, yc)
        p_test = np.clip(iso.predict(model.predict_proba(Xt)[:, 1]), 1e-6, 1 - 1e-6)
        fitted[key] = (model, iso, p_test)

    metrics = {key: _metrics(yt, p_test) for key, (_, _, p_test) in fitted.items()}
    champion = max(metrics, key=lambda k: (metrics[k]["pr_auc"], metrics[k]["roc_auc"],
                                           k == "histgb"))

    fingerprint = _fingerprint(payments)
    version = f"{FEATURE_VERSION}-{fingerprint[:12]}-s{seed}"
    ARTIFACT_DIR.mkdir(parents=True, exist_ok=True)
    paths = {}
    for key, (model, iso, _) in fitted.items():
        path = ARTIFACT_DIR / f"{name}_{version}_{key}.joblib"
        joblib.dump({"model": model, "isotonic": iso,
                     "feature_names": feat_names, "feature_version": FEATURE_VERSION,
                     "champion": champion, "seed": seed}, path)
        paths[key] = str(path)

    return TrainingResult(name=name, version=version, feature_version=FEATURE_VERSION,
                          dataset_fingerprint=fingerprint, champion=champion,
                          metrics={"split": {"fit": int(t1), "cal": int(t2 - t1),
                                             "test": int(n - t2)},
                                   **metrics},
                          artifact_paths=paths)


def predict_success(model_dir_path: str, X) -> np.ndarray:
    """Load an artifact and produce calibrated P(success) = 1 − P(fail)."""
    art = joblib.load(model_dir_path)
    raw = art["model"].predict_proba(X)[:, 1]
    p_fail = np.clip(art["isotonic"].predict(raw), 0.0, 1.0)
    return 1.0 - p_fail
