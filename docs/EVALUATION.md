# Evaluation (measured on this machine — 2026-08-25)

> Every number below is produced by `scripts/evaluate.py`, `scripts/loadtest.py`,
> `make demo`, or the pytest suite in this repo against seeded simulator ground truth.
> Nothing is estimated or imported from marketing. Re-run any line yourself; commands noted.

## Payment success prediction (holdout, seed 42)
`python scripts/evaluate.py` → generated dataset 25,503 terminal rows; isotonic-calibrated champion:

| Model | ROC-AUC | PR-AUC | Brier | ECE | n_test |
|---|---|---|---|---|---|
| success champion (LR/HistGB + isotonic) | **0.604** | 0.0468 | 0.0346 | **0.0023** | 5,101 |

Determinism: two same-seed trainings produce byte-identical metrics (`reproducible: true`).
Quality is asserted against the ORACLE information ceiling (ADR-011), not an absolute AUC bar.

## Anomaly detection (5 planted scenarios, 48h-equivalent traffic)
`scripts/evaluate.py` — EWMA/CUSUM/robust-z/pooled-z ensemble on the planted cohort:

| Scenario | Detected | Detection delay |
|---|---|---|
| issuer_outage | ✅ | 5 min |
| psp_degradation | ✅ | 20 min |
| checkout_regression | ✅ | 0 min |
| auth_failures | ✅ | 5 min |
| rate_limit | ✅ | 0 min |

False alarms: clean worlds (no scenario, seeds 42 & 7, org-wide sweep over ~40 watched
cohorts × 4 merchants) open **zero** incidents — enforced by the dual-path admission gate
(statistical persistence OR overwhelming single-window evidence) and regression-tested in
`tests/test_finish_audit.py::test_clean_world_opens_no_incidents`.

## Graph RCA
Top-1 accuracy: **4/5** · Top-3 accuracy: **5/5** across the five planted scenarios,
with counterfactual-mask shares reported per incident.

## Revenue at Risk
80% interval covers simulator-true loss: **5/5 scenarios** · median relative error of the
point estimate: **0.219** · point estimate lies inside its own interval in **5/5** runs
(interval-containment invariant is unit-tested on adversarial tiny cohorts).

## Decision quality
NO_ACTION selected whenever EV≤0 (unit-tested); policy violations executed across all demo
runs: **0** (asserted by tests; demo story prints the guardrail tally every run).

## Experimentation
Lift + CI computed from stored assignments (control vs treatment) — exercised end-to-end by
the flagship journey test and the live demo; today's demo measured −0.4% (honestly reported
"not significant" rather than embellished).

## Bandit vs fixed policy (offline)
LinUCB vs fixed-arm cumulative reward on 400 logged rows (importance-free conservative
replay): **75.0 vs 56.0** in LinUCB's favor (`scripts/evaluate.py`, seed 7).

## Performance / load (single worker, this laptop)
`make loadtest` — signed-webhook flood + API latency, in-process ASGI:
- Webhook ingest: **1,030.9 events/s**, 200/200 HTTP 200, p50 15.9 ms · p95 31.3 ms · p99 31.9 ms
- `GET /api/health`: p50 2.9 ms · p95 8.2 ms
- `GET /api/overview` (full aggregate): p50 494 ms · p95 601 ms

10K-merchant / billion-event design is documented (ARCHITECTURE.md scale path), not benchmarked.

## Frontend
Headless Chrome against the live API: root serves HTTP 200; DOM shows LIVE-hydration markers
("LIVE · synced", 15 incident references) with the risk_admin key — UI↔API binding verified
end-to-end (not a static-page check).

## Deployment / security evidence (2026-08-25)
- Fresh-venv install from scratch → **155→156/156 pytest green** in that venv.
- `make migrate` on empty SQLite (**26 tables**) AND on healthy Postgres 16 container.
- `docker compose config` valid; postgres+redis up healthy.
- bandit: no findings · pip-audit: no known vulnerabilities · secret scan: clean (CI parity).

