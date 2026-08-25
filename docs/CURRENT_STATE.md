# CURRENT STATE

## CURRENT PHASE
PHASE 13 — ML-002 TRAINING + REGISTRY (complete); next: AGENT-001 commander.

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
      selection; flagship E2E journey green (tests/test_e2e_journey.py) — commit 08ef7ef
- [x] PHASE 13 ML-002: services/ml/paytwin_ml/train.py — point-in-time dataset at 4
      cohort granularities (leakage-tested), LogisticRegression + HistGradientBoosting
      each isotonic-calibrated on time-separated fit/cal/test slices, ROC-AUC/PR-AUC/
      Brier/ECE, deterministic under seed, joblib artifacts in services/ml/artifacts/;
      services/api/paytwin_api/services/model_registry.py writes model_versions rows
      (stage TRAINED, get-or-create idempotent). Quality asserted against the ORACLE
      information ceiling (ADR-011) instead of an unreachable absolute AUC.

## KEY BUGS FIXED IN PHASES 12–13 (root causes, not symptoms)
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
7. train.py feature names interleaved per-window while writes grouped per-stat —
   columns silently mislabeled; caught by probing impossible column stats (a rate
   column with std 180). Names now follow write order.

## IN PROGRESS
- (nothing)

## NOT STARTED (dependency order)
AGENT-001 commander, API-001 routers+SSE, CAUSAL-002 uplift/LinUCB, WEB-001 frontend
binding, SIM-002 demo builder + worker entrypoint, OPS-001/002 compose+Makefile+CI,
QA-001 loadtest+EVALUATION numbers.

## BLOCKERS
- None.

## LAST TEST RESULTS
- pytest tests/ -q → **101 passed** (7 new ML-002 tests: leakage, shapes, ceiling-
  fraction vs oracle, determinism, artifacts, registry row idempotent, loaded-champion
  ranking; measured champion ~0.60 ROC-AUC vs 0.68 oracle ceiling on holdout).

## LAST STABLE COMMIT
- 08ef7ef "PHASE 12: incident engine — correlated detection w/ anti-noise gates, E2E
  journey green" (ML-002 lands in the next commit)

## NEXT TASK
- AGENT-001 commander: services/api/paytwin_api/services/commander.py (intent
  classify, tenant-scoped read-only tools, evidence pack E1..En, deterministic
  composer w/ PAYTWIN_LLM_PROVIDER=none, action-intent -> policy -> ALLOWED/BLOCKED,
  refusal set, tool trace) + tests/test_commander.py.

