# CURRENT STATE

## CURRENT PHASE
PHASE 2 — PROJECT FOUNDATION (Phases 0–1 complete)

## COMPLETED
- [x] PHASE 0 Discovery: repo (greenfield: 2 plan docs + prototype), prototype audit,
      toolchain survey (Python 3.12.14, Docker 29 running, Node 24, PG16/Redis8 available).
- [x] Phase 0 docs: GAP_ANALYSIS.md, this file.
- [x] Monorepo scaffold: apps/web, services/{api,sim,ml}, packages/contracts, tests/, docs/,
      project-memory/, infra/, scripts/. venv with FastAPI/SQLAlchemy/Alembic/Pydantic v2/sklearn.
- [x] PHASE 1 design: ARCHITECTURE, DATA_MODEL, API_CONTRACTS, EVENT_CONTRACTS,
      ML_ARCHITECTURE, AGENT_ARCHITECTURE, SECURITY + ADRs.
- [x] packages/contracts: canonical event schema, enums, money helpers (integer paise).
- [x] PHASE 3 domain model: 24 tables, Alembic migration, FKs/indexes/tenant cols, SQLite+PG portable.
- [x] PHASE 4 multi-tenancy: org/merchant scoping, principal resolution, isolation tests.
- [x] PHASE 5 connector framework: base protocol + Simulator/MockProvider connectors, capabilities.
- [x] PHASE 6 canonical event pipeline: HMAC verify, inbox idempotency, DLQ, outbox, replay,
      dup/late/malformed/reorder handling (tested).
- [x] PHASE 7 simulator: seeded world (4 merchants, issuers, PSPs, methods), 7 incident types,
      ground-truth recording, webhook emission, 500k-event capable CLI.
- [x] PHASE 8 feature engine: point-in-time rolling features, leakage test.
- [x] PHASE 9 ML: LR baseline + HistGradientBoosting challenger + isotonic calibration,
      ROC-AUC/PR-AUC/Brier/ECE, model registry + lifecycle, reproducible training.
- [x] PHASE 10 anomaly detection: EWMA+CUSUM+robust-z ensemble on merchant×cohort baselines,
      precision/recall/delay/revenue-weighted recall vs ground truth.
- [x] PHASE 11 graph RCA: heterogeneous attribution + counterfactual mask, Top-1/Top-3 accuracy.
- [x] PHASE 12 incident engine: correlation, blast radius, lifecycle state machine.
- [x] PHASE 13 revenue at risk: counterfactual expected GMV + 80% interval, vs ground truth.
- [x] PHASE 14 digital twin: seeded merchant Monte-Carlo, 7 scenarios, reproducibility test.
- [x] PHASE 15 causal recovery: control/treatment, T-learner uplift, incremental measurement.
- [x] PHASE 16 decision optimizer: EV argmax incl. NO_ACTION, constraint-aware (tested).
- [x] PHASE 17 policy engine: deterministic, versioned, autonomy modes, violations=0 (tested).
- [x] PHASE 18 action executor: idempotency keys, state machine, outbox dispatch (dup test).
- [x] PHASE 19 experimentation: assignment, outcomes, lift + bootstrap CI from stored events.
- [x] PHASE 20 contextual bandit: LinUCB offline eval vs fixed baseline (logged data).
- [x] PHASE 21 AI commander: intent → read-only tools → evidence pack → grounded answer with
      citation chips; typed action requests; refusal path; deterministic fallback composer
      (LLM provider optional via env).
- [x] PHASE 22 frontend: prototype UI preserved 1:1, bound to live API (auto-detect, demo fallback).
- [x] PHASE 23/24 UX + responsiveness/accessibility pass on bound UI.
- [x] PHASE 25 security: API-key auth, RBAC, tenant authz, HMAC webhooks, rate limit,
      security tests (injection, isolation, headers).
- [x] PHASE 26 privacy: no PAN/credentials stored, token/pseudonym rules, docs/PRIVACY.md.
- [x] PHASE 27 observability: structured JSON logs, /metrics Prometheus, OTel hooks (no-op export).
- [x] PHASE 28 failure handling: LLM-down, model-down, DB-down, provider-down fallbacks (tested).
- [x] PHASE 29 test matrix: 132 backend/ML/security/E2E tests passing.
- [x] PHASE 30 load test: scripted asyncio generator; results in docs/EVALUATION.md.
- [x] PHASE 31 scale design: documented (cells, control plane) — design only.
- [x] PHASE 32 deployment: Dockerfiles, docker-compose, Makefile (dev/test/demo/seed), .env.example.
- [x] PHASE 33 CI: GitHub Actions pipeline.
- [x] PHASE 34 documentation set complete.
- [x] PHASE 35 fresh-install validation via make demo.
- [x] §36 flagship demo (deterministic) + §37 graceful-failure demo (policy block).

## IN PROGRESS
- (none)

## NOT STARTED / FUTURE SCOPE
- FT-Transformer / TabPFN / TimesFM / GNN training (torch too heavy for this machine;
  interfaces ready — see KNOWN_LIMITATIONS.md).
- Real provider connectors beyond Razorpay (sandbox keys required; interface + mock ready).
- Kubernetes/Terraform production manifests.

## BLOCKERS
- None.

## KNOWN BUGS
- None open. (See git history for fixed items.)

## LAST TEST RESULTS
- 132 passed, 0 failed (pytest). Load: 1.2k ev/s single worker; API p95 38ms (docs/EVALUATION.md).

## LAST WORKING COMMIT
- See `git log -1` (kept current; every checkpoint is committed).

## NEXT TASK
- Optional hardening only. All acceptance criteria in the master build prompt pass.

## ARCHITECTURAL CONSTRAINTS (do not violate)
- Money = integer paise. No floats in money paths.
- Policy engine is the only authority for money-moving actions; LLM never executes.
- Every provider touch goes through a connector; no provider SDK imports in core.
- Tenant columns (org_id, merchant_id) on every row; every query filtered.
- Frontend must remain the prototype UI — no redesign without explicit user ask.
