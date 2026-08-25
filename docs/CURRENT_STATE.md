# CURRENT STATE

## CURRENT PHASE
PHASE 12 — INCIDENT ENGINE + E2E JOURNEY (complete); next: ML-002 training + registry.

## COMPLETED (verified in repo)
- [x] PHASE 0/1 docs + project memory — commit edd79ae
- [x] Monorepo scaffold, editable installs (contracts/sim/ml/api) — FOUNDATION-001..003
      (25-table models + Alembic init migration, roundtrip verified)
- [x] TENANCY-001 API-key auth + RBAC (paytwin_api/auth.py)
- [x] CONN-001 connector framework: simulator/mockprovider/razorpay dialects + HMAC +
      capabilities + deterministic perform_action
- [x] PIPE-001/002 webhook ingest pipeline (verify → inbox idempotency → canonicalize →
      late flags → outbox) + payment state machine
- [x] FastAPI shell (/api/health, /api/meta, /webhooks/{provider})
- [x] SIM-001 seeded generator with counterfactual ground truth (7 scenarios);
      SIM-002 webhook emitter (demo builder still pending)
- [x] ML-001 point-in-time features; ML-003 detector ensemble EWMA/CUSUM/robust-z/
      pooled-z (5/5 scenarios detected, clean silent); ML-004 graph RCA w/ significance
      gate + counterfactual mask; ML-005 RaR w/ 80% interval vs truth
- [x] TWIN-001 seeded twin Monte-Carlo (7 scenarios); DECIDE-001 EV optimizer with
      NO_ACTION floor; GOV-001 policy engine (7 hard guardrails + autonomy ladder);
      EXEC-001 idempotent policy-gated audited executor; AUDIT-001 SHA-256 hash chain;
      CAUSAL-001 experiments (deterministic assignment, lift+CI)
- [x] PHASE 12 incident engine (incident_service.py): correlated detection w/ anti-noise
      gates — window-overlap hierarchical corroboration, guard-banded binomial-tail
      severity (alpha 0.01, excess>=3, SR drop>=3pts), most-specific-wins family
      selection; flagship E2E journey green (tests/test_e2e_journey.py)

## KEY BUGS FIXED THIS PHASE (root causes, not symptoms)
1. Naive-datetime mixing: SQLite returns naive UTC values; `_payments_dicts` read them
   via `.timestamp()` (= LOCAL interpretation on non-UTC hosts). Now normalized to
   aware-UTC explicitly (`_aware_utc`).
2. Wall-clock sweep anchoring: window was `[now−3h, now)` so replayed/fixed-time history
   misaligned (planted outage landed inside the detector baseline ⇒ never fired). Window
   now anchors on the newest event.
3. `_related()` demanded identical dim dicts (wildcards rejected) ⇒ family corroboration
   could never match. Fixed to wildcard-consistency + 20-min window overlap.
4. Severity used whole-series baseline (polluted by the anomaly itself); replaced with
   guard-banded pre-onset cohort baseline capped at 99.5% + exact binomial tail test.
5. DND quiet hours evaluated UTC hour against IST window (policy.py); IST is explicit now.
6. Executor presented whole-cohort GMV to AMOUNT_CAP; candidates now carry canary-slice
   count/value (`slice_value_paise`) matching the twin's alloc_pct rollout.

## IN PROGRESS
- (nothing)

## NOT STARTED (dependency order)
ML-002 (train.py LR+HistGB+isotonic+registry), AGENT-001 commander, API-001 routers+SSE,
CAUSAL-002 uplift/LinUCB, WEB-001 frontend binding, SIM-002 demo builder + worker,
OPS-001/002 compose+Makefile+CI, QA-001 loadtest+EVALUATION numbers.

## BLOCKERS
- None.

## LAST TEST RESULTS
- pytest tests/ -q → **94 passed** (incl. test_e2e_journey: one outage ⇒ one incident
  HDFC×upi_intent, clean traffic ⇒ zero incidents).

## LAST STABLE COMMIT
- 3b664f4 ("DECIDE/GOV/EXEC/AUDIT/CAUSAL ...") — incident engine lands in next commit.

## NEXT TASK
- ML-002: services/ml/paytwin_ml/train.py (LR + HistGB + isotonic, time-based holdout,
  ROC-AUC/PR-AUC/Brier/ECE, joblib artifact + model_versions row, deterministic seed),
  tests/test_training.py, then AGENT-001 commander.

