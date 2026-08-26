# Reliability Lab — Gap Analysis (existing PayTwin vs required capability)

Verdict up front: **~80% of the needed substrate already existed.** The build was
integration + a small deterministic engine, not a new platform.

| Capability | Existing implementation | Can reuse? | Missing work | Priority |
|---|---|---|---|---|
| Merchant context | Organization/Merchant models, API-key RBAC, tenant-scoped routers | ✅ direct | findings scoped by org_id | P1 (done) |
| Provider connectors | simulator/mockprovider/razorpay dialects + HMAC verify | ✅ semantics | modeled fixtures for scenario engine | P1 (done) |
| Payment events | ingest pipeline: HMAC→inbox dedupe→canonicalize→outbox; payment state machine | ✅ concepts | event-sequence model inside runner | P1 (done) |
| Digital Twin | seeded Monte-Carlo twin (`run_twin`) | ✅ reused for recovery sims | fault-campaign bridge (Phase 10 candidate) | P2 |
| Incident engine | correlated detection w/ calibrated gates | ✅ reused as-is | none (gates re-validated) | — |
| Audit | SHA-256 hash chain + exports | ✅ direct | reliability actions logged via existing append_audit when DB-backed | P3 |
| AI Commander | tool-grounded assistant | ✅ extended | release-gate grounding branch (frontend) | P1 (done UI-side) |
| Test runner | none | ❌ new | deterministic ScenarioRunner + evidence store | P0 (done) |
| State modeling | payment state machine in pipeline | ✅ concepts | multi-dimension World model in engine | P1 (done) |
| Chaos testing | /api/chaos sandbox injection routes | ✅ reuse for live path | fixture-level faults in runner | P1 (done) |
| Release gate | none | ❌ new | verdict/score from findings; critical-blocks rule | P0 (done) |
| Razorpay spec registry | none | ❌ new | hashed source registry + 14 requirements | P0 (done) |
| Webhook Lab UI | none | ❌ new | fault buttons → API → toast/evidence | P1 (done) |
| Known-broken fixtures | none | ❌ new | 6 mutation presets, all detected | P0 (done) |
| Doc drift detection | none | ❌ future | refresh job spec'd in DECISIONS | P3 |

## Reuse decisions
- Runner does NOT hit the live ingest HTTP path: it drives an isolated world model so
  runs are hermetic, seed-reproducible, and side-effect free; the LIVE chaos path
  (/api/chaos) remains the production-pipeline injector.
- Evidence stored as JSON documents (data/reliability/runs.json), not SQL tables:
  generated artifacts, immutable per run, zero-migration v1.
