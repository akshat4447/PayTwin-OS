# Reliability Lab Architecture

```
Existing PayTwin core (orgs, merchants, connectors, ingest, twin,
incidents, policy/executor, audit, commander, Apple-DS UI)
        │
        ▼
services/api/paytwin_api/reliability/
  fixtures.py   App-under-test policies ("fixtures"): correct() +
                known-broken mutations (no_verify, no_dedupe,
                fulfil_on_authorized, refund_over_capture,
                cross_tenant_blind, mandate_limits_off, forged_callback)
  engine.py     Event -> handler -> World ledger -> invariant evaluation.
                Deterministic; no I/O; captured is TERMINAL state.
  packs.py      Suites = base scenario (correct fixture must be clean)
                + mutations (broken fixture must produce EXACTLY the listed
                invariant violations). "Test the tester" by construction.
  invariants.py PTWIN-INV-001..007 evaluators over the World.
  router.py     /api/reliability/{overview,suites,run,runs,findings,
                release-gate,webhook-lab/{fault}} — bearer auth via deps;
                tenant-scoped by org_id.
  store.py      Immutable JSON run artifacts (data/reliability/runs.json).
```

## Data flow
POST /run → for each suite: correct-fixture pass must yield zero violations;
each mutation must yield exactly its expected set → findings on any mismatch →
gate = BLOCKED if any critical, else WARNING on high/medium, else READY.

## Tracing
Every Razorpack scenario carries requirement_ids resolving into
project-memory/razorpay-requirements.jsonl → sources with sha256 in
docs/razorpay/sources/. Generic scenarios cite PAYTWIN_INVARIANT ids.

## Extension points (provider packs / app-under-test)
- New provider pack = new module exposing suite dicts (no core changes).
- New app-under-test kind = new FixturePolicy-like adapter implementing handle().
- Future: OpenAPI/repo-scan Integration Map feeds richer Worlds; doc-refresh job
  diffs sources/ hashes and flags NEEDS_REVALIDATION requirements.
