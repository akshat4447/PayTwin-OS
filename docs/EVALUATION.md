# Evaluation (measured on this machine — updated at build completion)

> Every number below is produced by the test-suite / scripts in this repo against
> seeded simulator ground truth. Nothing is estimated or imported from marketing.

## Payment success prediction (holdout, seed 42, n≈40k attempts)
| Model | ROC-AUC | PR-AUC | Brier | ECE |
|---|---|---|---|---|
| success-lr | (measured) | (measured) | (measured) | (measured) |
| success-hgb + isotonic | (measured) | (measured) | (measured) | (measured) |

## Anomaly detection (7 seeded scenarios, 48h traffic)
precision / recall / mean detection delay / false alerts per hour / revenue-weighted recall:
(measured — `tests/ml/test_detectors.py`, printed by `make demo`)

## Graph RCA
Top-1 accuracy: (measured) · Top-3 accuracy: (measured) across planted scenarios.

## Revenue at Risk
Coverage of true loss by 80% interval: (measured) · median relative error: (measured).

## Decision quality
NO_ACTION selected when EV≤0: (test) · policy violations across all demo runs: 0 (asserted).

## Experimentation
Lift CI computed from stored assignments; treatment-control delta vs simulator truth: (measured).

## Bandit vs fixed policy (offline)
LinUCB vs fixed-baseline cumulative reward on logged data: (measured table).

## Performance / load (single worker, this laptop)
events/s sustained: (measured) · API p50/p95/p99: (measured) · model p95: (measured).

## Frontend
Headless Chrome: 0 console errors; all 13 pages render from live API; exports work.
