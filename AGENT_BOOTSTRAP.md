# AGENT_BOOTSTRAP.md — read this FIRST after any context loss

## WHAT THIS PRODUCT IS
PayTwin OS (`/Users/akshatkumar/Documents/PayTwin_OS`): a payments resilience
platform. It ingests provider webhooks into a canonical event store, models
payment health per merchant cohort, detects degradations, diagnoses root causes,
simulates counterfactuals in a seeded Digital Twin, decides recovery actions via a
deterministic policy engine, executes them idempotently, and measures causal impact.
Stack: FastAPI + SQLAlchemy (services/api), ML (services/ml), simulator
(services/sim), contracts (packages/contracts), single-file vanilla-JS frontend
(apps/web/index.html) served by the API at `/`.

## WHAT RELIABILITY LAB IS (added 2026-08-26)
A NATIVE module (`services/api/paytwin_api/reliability/` + UI page `#reliability`)
that proves payment integrations behave correctly under lifecycle failures:
deterministic scenario runner drives modeled provider events through merchant
"fixtures" (handler policies), then evaluates 7 executable business invariants.
Suites are traced to VERIFIED Razorpay requirements (docs/razorpay/, hashed
sources) or labeled PAYTWIN_INVARIANT. Findings feed a Release Gate
(READY/WARNING/BLOCKED — critical findings always block).

## WHAT IT IS NOT
Not a separate app. Not a Razorpay competitor/optimizer. Not live-money testing
(fixtures are modeled; chaos only via existing /api/chaos sandbox routes).
The AI never executes tests; it only explains results.

## CURRENT ARCHITECTURE (Reliability slice)
fixtures.py (policies incl. known-broken mutations) → engine.py (handle/run_scenario)
→ packs.py (generic/webhooks · razorpay/core · paytwin/isolation · paytwin/agentic)
→ router.py (/api/reliability/*) → store.py (data/reliability/runs.json evidence).
UI: pgReliability() + #reliability-app-js; Commander answers release-gate questions.

## NON-NEGOTIABLE SAFETY RULES
1. Never claim Razorpay behavior without a docs/razorpay/sources/* hash.
2. Never mark complete without a passing test/browser proof.
3. Never expose secrets to frontend/logs/LLM.
4. No real-money or third-party-production testing.
5. Existing PayTwin behavior must keep passing (182-test suite).

## SOURCE-OF-TRUTH ORDER
official razorpay.com docs → docs/razorpay/sources → registries in
project-memory → code → this file's claims.

## FILES TO READ AFTER COMPACTION
AGENT_BOOTSTRAP.md · project-memory/context-manifest.json · docs/CURRENT_STATE.md ·
docs/DECISIONS.md · project-memory/task-graph.json ·
project-memory/razorpay-doc-registry.json · docs/UI_REDESIGN_STATUS.md

## CURRENT IMPLEMENTATION PHASE
Reliability Lab v1 COMPLETE & committed (see git log; tests/test_reliability.py).
Next candidates: doc-drift refresh job, Integration Map from repo scan,
CLI `paytwin verify`, extended Razorpay packs (settlements/disputes/route).
