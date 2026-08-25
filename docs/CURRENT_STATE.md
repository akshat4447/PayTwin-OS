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
- [x] PHASE 14 AGENT-001: services/api/paytwin_api/services/commander.py — intent
      classifier (refusal patterns first, then action verbs, then info intents),
      read-only tenant-scoped tools (get_incident, query_metrics, get_twin,
      get_experiment, explain_decision, get_audit), evidence pack E1..En with
      resolvable refs, deterministic composer (works with PAYTWIN_LLM_PROVIDER=none),
      action-intent -> typed draft -> POLICY EVALUATION ONLY (never dispatches;
      reply states "No customer or payment action was executed."), tool traces
      persisted to the hash-chained audit log (actor_role=agent).
- [x] PHASE 15 API-001: routers {overview(+funnel/healthmap/merchants), incidents
      (list/detail/execute@202/resolve), twin (byte-identical same-seed over HTTP),
      policies (create/PATCH-versioning/blocked-log/historical preview), commander,
      experiments, models (+risk_admin promote), audit (verify + jsonl/dossier export),
      reports (recovery-batch markdown), chaos (seeded scenario injection via real
      webhook ingest), stream (SSE per-org fan-out)}. Bearer auth via deps; RBAC
      helpers require_write/require_admin; execute publishes policy_decision/action
      on the bus; idempotent replay returns decision=duplicate.
- [x] PHASE 16 CAUSAL-002: services/ml/paytwin_ml/causal.py — T-learner uplift
      (two HistGB regressor heads; uplift = mu1 − mu0), deterministic per seed,
      direction sanity on seeded heterogeneous-treatment data; LinUCB (disjoint
      linear models per arm) evaluated OFFLINE via logged-bandit replay against
      fixed always-control/always-treat baselines — beats both on the seeded stream.

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
API-001 routers+SSE, CAUSAL-002 uplift/LinUCB, WEB-001 frontend binding,
SIM-002 demo builder + worker entrypoint, OPS-001/002 compose+Makefile+CI,
QA-001 loadtest+EVALUATION numbers.

## BLOCKERS
- None.

## LAST TEST RESULTS
- pytest tests/ -q → **144 passed** (4 new causal tests: uplift direction sanity on
  heterogeneous treatment effect, per-seed determinism, LinUCB offline replay ≥ both
  fixed baselines with >30% log coverage, replay accounting exactness).

## LAST STABLE COMMIT
- 6ca860c "API-001: REST routers + SSE over httpx ASGI ..." (CAUSAL-002 lands in
  the next commit)

## NEXT TASK
- WEB-001 frontend binding: cp paytwin-os-v2.html apps/web/index.html + surgical
  data-layer block (fetch /api/meta → LIVE mode hydrating overview/incidents/
  policies/policies/chat/twin/SSE; DEMO fallback when API absent); verify headless
  Chrome renders sidebar+topbar with zero console errors.

