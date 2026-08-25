# CURRENT STATE

## CURRENT PHASE
PHASE 2/3 — FOUNDATION & DOMAIN MODEL (implementation underway)

## COMPLETED (verified in repo)
- [x] PHASE 0 Discovery + docs (GAP_ANALYSIS.md, this file) — commit edd79ae
- [x] PHASE 1 design doc set (ARCHITECTURE, DATA_MODEL, API_CONTRACTS, EVENT_CONTRACTS,
      ML_ARCHITECTURE, AGENT_ARCHITECTURE, SECURITY, TEST_STRATEGY, DEPLOYMENT, DECISIONS,
      KNOWN_LIMITATIONS, RUNBOOK, PRIVACY, THREAT_MODEL, MODEL_CARD, EVALUATION skeleton)
      + project-memory/*.json — commit edd79ae
- [x] Monorepo scaffold dirs + .venv (FastAPI 0.141, SQLAlchemy 2.0.52, Pydantic 2.13, sklearn 1.9)
- [x] packages/contracts written (enums, money, CanonicalEvent) — verification pending

## IN PROGRESS
- [ ] FOUNDATION-002 verify: editable install + import/round-trip test of paytwin_contracts
- [ ] FOUNDATION-003: services/api DB models (24 tables) + Alembic initial migration + tests

## NOT STARTED (dependency-ordered; authoritative list = project-memory/task-graph.json)
TENANCY-001, CONN-001, PIPE-001/002, SIM-001/002, ML-001..005, TWIN-001, CAUSAL-001/002,
DECIDE-001, GOV-001, EXEC-001, AGENT-001, AUDIT-001, API-001, WEB-001, OPS-001/002, QA-001

> NOTE: task-graph.json previously marked all tasks "complete" aspirationally before any
> code existed. Corrected per resume rule §2 (implementation is the source of truth).

## BLOCKERS
- None.

## KNOWN BUGS
- None yet (no runtime code exercised).

## LAST TEST RESULTS
- None run yet (first pytest run due with FOUNDATION-002/003).

## LAST STABLE COMMIT
- edd79ae (docs + memory + scaffold)

## NEXT TASK
- FOUNDATION-003 (models + alembic + migration/constraint tests), then TENANCY-001.

## IMPORTANT ARCHITECTURAL CONSTRAINTS (unchanged — see PROJECT_CONTEXT.md)
- Money = integer paise. Policy engine is sole authority for money actions. Connectors at
  the edge only. Tenant columns on every row. Frontend = prototype UI, no redesign.
