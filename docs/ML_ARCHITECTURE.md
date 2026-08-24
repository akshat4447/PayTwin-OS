# ML Architecture

## Intelligence stack (implemented & measured)
| Layer | Implementation | Why honest |
|---|---|---|
| Success prediction | LogisticRegression (baseline) + HistGradientBoostingClassifier (XGBoost-class challenger) + isotonic calibration | Both trained/evaluated on simulator data with held-out time split; metrics reported (EVALUATION.md) |
| Probability quality | ROC-AUC, PR-AUC, log-loss, Brier, ECE (10-bin) | Reported per model; calibration checked |
| Temporal anomaly | EWMA + CUSUM + robust-z ensemble on merchant×cohort baselines (hour-of-week seasonal profile) | Merchant-specific (no universal thresholds); precision/recall/delay/revenue-weighted-recall measured vs ground truth |
| Forecast band | seasonal-naïve + residual quantiles (q10/q90) | Replaces TimesFM (torch not installable) — same interface, honest label |
| Graph RCA | Heterogeneous attribution (issuer×method×psp×gateway concentration) + counterfactual mask share | Top-1/Top-3 accuracy measured vs seeded ground truth; GNN documented as future (ADR-004) |
| Revenue at Risk | counterfactual expected GMV (baseline rate × cohort volume − observed) with residual-quantile interval | Validated against simulator truth within interval |
| Digital twin | seeded merchant Monte-Carlo: traffic, mix, cohort failure multipliers, recovery curves, costs; 7 scenarios | Same seed ⇒ identical output (tested); distributions not point estimates |
| Causal uplift | T-learner (HistGB) + honest split; experiments give design-based lift w/ bootstrap CI | Control vs treatment measured from stored assignments/outcomes |
| Policy optimization | LinUCB offline eval on logged data vs fixed baseline | Comparison table in EVALUATION.md; hard constraints stay OUTSIDE the bandit |

## Feature groups (point-in-time)
transaction · merchant · customer (pseudonymous streaks) · issuer · PSP · gateway ·
method · temporal (hod/dow) · historical · incident · recovery.
Correctness: features at time t use only events with `occurred_at ≤ t` — leakage test
trains on shifted labels and must show degradation, plus a direct "no future rows" SQL check.

## Model lifecycle
`TRAINED → VALIDATED → SHADOW → CANARY → CHAMPION → RETIRED` (API-gated promotion,
risk_admin role). Every prediction stores `model_version` + `feature_version` +
`policy_version` at decision time. Monitoring: PSI feature drift, calibration drift
(ECE over trailing windows), prediction distribution, latency, missing-feature rate.

## Personalization ladder (cold-start safe)
global model → industry prior → merchant embedding (one-hot + shrinkage) → merchant
calibration (isotonic on merchant data) → real-time context. New merchants start on
global priors + calibration; dedicated models only when volume justifies (measured).

## Training reproducibility
`python -m paytwin_ml.train --seed 42` → deterministic split, fixed hyperparameters,
artifact + metrics JSON + dataset fingerprint (hash of training query) stored in
model_versions. Re-running produces identical metrics (tested).
