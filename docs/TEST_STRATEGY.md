# Test Strategy

Runner: `pytest` (`.venv/bin/pytest -q`). DB for tests: portable schema on SQLite
(`PAYTWIN_DATABASE_URL=sqlite:///./data/test.db`); same models/migrations; PG used in dev/demo.

## Layers
1. **Unit** — money helpers, canonicalizer, policy predicates, EV optimizer, detector math,
   twin RNG determinism, audit hashing.
2. **Integration (API)** — httpx ASGI: auth, RBAC, tenancy isolation, CRUD, overview,
   SSE smoke, rate limit.
3. **Pipeline** — webhook dup / late / malformed / out-of-order / replay; DLQ; state machine.
4. **ML** — training determinism, metrics sanity (AUC>0.85 on seeded data), calibration
   (ECE bound), leakage (shift test + point-in-time SQL check), registry lifecycle.
5. **Detection/RCA/RaR** — vs simulator ground truth: detection delay ≤3 windows,
   Top-1 RCA accuracy, RaR inside interval, precision/recall.
6. **Decisioning** — optimizer picks NO_ACTION when EV≤0; policy blocks (retry-limit,
   DND, amount cap, provider-down); executor duplicate ⇒ exactly one action; autonomy gates.
7. **Commander** — grounding (citations resolve), refusal set, fallback mode works w/o LLM.
8. **E2E journey** — ingest → incident → RCA → simulate → decide → policy → execute →
   outcome → experiment lift → dashboard numbers reflect it (single test, seeded).
9. **Security** — isolation (cross-tenant), bad signature, injection strings in fields,
   rate limit, role gates.
10. **Frontend** — static checks (`/tmp/pt_check.py` pattern) + headless Chrome dump-dom:
    zero console errors, key UI present, API-bound markers.

## Fixtures
`seeded_world` (org, 4 merchants, keys, policies, 48h history, 1 active incident),
`api_client` (authenticated), `sim` (deterministic generator). No network access in tests;
LLM provider forced to `none`.

## Gates
CI fails on: any test failure, coverage of core services < 80% (configured), bandit high
findings, pip-audit criticals, secret-scan hits, frontend console errors.
