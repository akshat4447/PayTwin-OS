# Model Card — PayTwin v1 intelligence stack

## Models actually trained in this repo (see EVALUATION.md for measured numbers)
1. **success-lr** — LogisticRegression on point-in-time features. Baseline.
2. **success-hgb** — HistGradientBoostingClassifier ("XGBoost-class"), isotonic-calibrated. Champion candidate.
3. **detector-ensemble** — EWMA(α tuned) + CUSUM(k,h) + robust-z on merchant×cohort SR baselines.
4. **graph-rca** — deterministic heterogeneous attribution + counterfactual mask scorer.
5. **uplift-tlearner** — two HistGB heads (control/treatment) for P(success|arm).
6. **bandit-linucb** — offline policy evaluator on logged data.

## Intended use / out-of-scope use
Operational payment-resilience decisions for onboarded merchants on simulator or
consented merchant data. NOT for credit decisions, fraud prosecution, or individual
customer scoring.

## Training data
Seeded simulator (deterministic, ground-truth-labeled). Feature version `fv1`.
Dataset fingerprint stored per model_version. No real customer data used.

## Metrics & evaluation
Time-based holdout (last 20% by occurred_at). ROC-AUC, PR-AUC, log-loss, Brier, ECE.
Calibration: isotonic on validation split. Detection: precision/recall/delay/revenue-weighted
recall vs seeded scenarios. RCA: Top-1/Top-3 vs planted cause. All numbers in EVALUATION.md.

## Honest labels
"graph scorer" ≠ GNN (no message passing trained). Forecast band is seasonal-naïve +
residual quantiles, **not** TimesFM. These labels are used verbatim in the product UI.

## Re-training / rollback
`python -m paytwin_ml.train --seed N`; promote via API (risk_admin); rollback = previous
champion version re-promotion; every prediction stores model_version for forensics.
