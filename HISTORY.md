# PayTwin OS — History & Build Chronicle

> The full story of how this system was built: starting point, every build phase,
> decision log (ADRs), audit sprints, and the state transitions between them.
> For what the product IS and its specs, read `README.md`. This file is the record
> of how we got here and why.

## 1) How it was built (methodology)
- **Honesty rules:** never claim a model/number that wasn't trained/measured in-repo;
  simulated data is labeled simulated; recovery claims must come from experiments/control
  baselines or simulator counterfactual ground truth (ADR-009).
- **Ground-truth-driven ML:** the seeded simulator emits counterfactual truth
  (`sim_scenarios`), so detection/RCA/RaR/uplift are scored, not asserted.
- **Prototype-first UI contract:** the approved prototype's look/interactions were frozen;
  engineering added an additive LIVE data layer without touching its behavior (ADR-002).
- **Safety-first autonomy:** deterministic policy engine is the sole money authority;
  LLM strictly read-only; idempotent executor; hash-chained audit on everything.
- **Every fix lands with a regression test**; suite grew 9 → 46 → … → 156 → **182 green**.
- **Decision records:** numbered ADRs below; code comments and tests reference them.

## 2) Phase 0 — Discovery & prototype (pre-build)
Starting artifacts before any backend existed:
- `paytwin-os-v2.html` — fully working single-file SPA: 13 pages, 1s-tick sim engine,
  seeded 400-trial Monte-Carlo twin lab, streaming AI commander w/ citation chips +
  refusals, file exports, chaos console, org switcher (1 org × 4 merchants), dark/light,
  ⌘K palette. **All numbers were in-page constants; no backend.**
- `DEEP_ANALYSIS_AND_UPGRADE_PLAN.md` — blueprint-vs-bar gap analysis (G1–G12), model-stack
  recommendations, roadmap.
- `PROTOTYPE_AUDIT_AND_UPGRADE_PLAN.md` — page-by-page redesign plan + target architecture
  + DDL sketch.

Gap matrix that drove the build (all closed): constants→persistence · no ingestion→connector
framework + canonical pipeline · fake models→trained LR/HistGB+calibration+registry · toy
twin→seeded Monte-Carlo · no detection/RCA/RaR→ensemble+graph RCA+intervals vs ground truth ·
no policy/executor/audit→full governance chain · canned commander→tool-grounded agent ·
no tenancy→org/merchant scoping proven by tests · no experiments→assignments/outcomes/lift/CI ·
no tests→pytest suite · no deployment story→compose/Dockerfile/Makefile/CI · no docs/memory
system→(former docs/ set + project-memory registries).

Audit fixes inherited from the prototype era: missing `#app` mount crashed real browsers
(fixed pre-build); one-shot repair script replaced by read-only checker; stray content after
`</html>` removed.

## 3) Build chronology (25 commits, suite 9 → 182)

| Commit | Phase | Highlights | Tests |
|---|---|---|---|
| `edd79ae` | checkpoint 0+1 | discovery docs, architecture set, project memory | — |
| `88b4c39` | FOUNDATION-002 | contracts package verified + memory corrected to repo truth | 12 |
| `e0c5be3` | FOUNDATION-003 | 25-table domain model, Alembic init migration, schema constraint tests | — |
| `f551137` | TENANCY-001 + CONN-001 | API-key principals w/ RBAC; connector framework (3 dialects) | 37 |
| `ed35f9f` | PIPE-001/002 | webhook ingest (idempotency+DLQ+late flags), payment state machine, FastAPI shell | 46 |
| `109e076` | SIM-001 | seeded generator w/ counterfactual ground truth, 7 scenarios, emitter | 9→ |
| `876ed8e` | ML-001/003 | point-in-time features + EWMA/CUSUM/robust-z/pooled-z ensemble; 5/5 scenarios detected, clean silent | 72* |
| `fcf64b4` | ML-004/005 + TWIN-001 | graph RCA w/ significance gate + counterfactual mask; RaR intervals vs truth; seeded twin Monte-Carlo | 72 |
| `3b664f4` | DECIDE/GOV/EXEC/AUDIT/CAUSAL | EV optimizer, policy engine w/ autonomy ladder, idempotent executor, hash-chained audit, experiments | 92 |
| `08ef7ef` | PHASE 12 | incident engine — correlated detection w/ anti-noise gates, E2E journey green | →101 |
| `7d01bec` | ML-002 | training + registry: LR & HistGB w/ isotonic calibration, oracle-ceiling scoring | 101 |
| `5f198b7` | AGENT-001 | commander grounded in tenant-scoped tools; chat never executes | 140→ |
| `6ca860c` | API-001 | REST routers + SSE over httpx ASGI | 140 |
| `388895f` | CAUSAL-002 | T-learner uplift + LinUCB offline eval | 144 |
| `177bbd2` | WEB-001 | prototype UI bound to live API with DEMO fallback; headless-verified | — |
| `d312187` | SIM-002 / worker | end-to-end demo + autopilot worker loop | 148 |
| `42c1e68` | ops | infra/CI/Makefile landed + loadtest & evaluate tooling | — |
| `7806537` | audit-fix sprint | persistence, kind alignment, RaR math, deterministic training, detection FP gates | →156 |
| `ffb0427` | docs | measured EVALUATION numbers, final completion matrix, memory sync | — |
| `8469db2` | ops fix | deterministic demo world clock + make demo URL | — |
| `0cea520` | UI DS v1 | Apple-inspired design system across all 13 pages | — |
| `eb1fba8` | Reliability Lab | native payment-integration assurance module (+UI page) | +9 |
| `0dcddf9` `9d66e6c` | UI fixes | RELDBG probe removed; session-terminal load failures vs rotated keys | — |
| `3ce16a9` | UI DS v3 | PayTwin DS v3 redesign — shadcn tokens, Linear dark precision, Geist restraint | — |
| `56165af` | release-blocker sprint | rate limiting live, tenant-scoped uniques/FKs + audit fork guard/checkpoint, pseudonymization in all connectors, production config gates, RLS companion, DLQ redaction; docs refreshed | **182** |

\* test counters in early messages reflect cumulative-at-commit as recorded.

Phase narrative: foundations (contracts → schema/migrations → tenancy/connectors) →
pipeline correctness → intelligence (features/detectors → RCA/RaR/twin → decisioning/
governance/audit/causal → training+registry) → serving (commander → REST/SSE → uplift/LinUCB)
→ product surface (UI binding → worker/demo loop → infra/CI) → hardening sprints
(2026-08-25 audit fixes → Reliability Lab → DS v3 → release-blocker sprint).

## 4) Audit sprint — 2026-08-25 (final completion matrix, historical record)

| Area | Requirement | Evidence |
|---|---|---|
| Database | clean-DB migration | `make migrate` → init schema, 26 tables on SQLite **and** Postgres 16 |
| Backend | webhook ingest | HMAC/idempotency/DLQ/outbox suites green |
| ML | success model | ROC-AUC .604 / ECE .0023, reproducible; registry rows written by demo |
| ML | detector ensemble | 5/5 planted detected; clean worlds open **0** incidents (regression-tested) |
| ML | graph RCA | top-1 4/5 · top-3 5/5 vs truth |
| ML | RaR intervals | coverage 5/5; point∈interval 5/5 (+adversarial unit test) |
| Governance | policy engine + ladder | demo: 2 blocked / 2 approval-gated / violations 0 |
| Executor | idempotent dispatch | duplicate-request ⇒ same execution; executions persisted |
| Audit | hash chain + verify/export | demo chain ok (5 records); tamper test flips seq |
| Causal | experiments + uplift + LinUCB | offline replay: LinUCB 75.0 vs fixed 56.0 |
| Agent | commander read-only/refusal | never dispatches; audited turns |
| API | REST + SSE + RBAC | live curl: health 200; overview 401 w/o key → 200 w/ key |
| Frontend | UI bound to live API | headless Chrome LIVE-hydration markers + incident refs |
| Demo | flagship E2E persists | fresh run: INC-2481 P1, executions=4, audit=5 after exit |
| Demo hygiene | dirty-DB guard | refuses without PAYTWIN_DEMO_RESET=1 (unit-tested) |
| Tooling | loadtest CLI | 1,030.9 ev/s · p95 31.3ms measured |
| Ops/CI | compose + pipeline | config valid; bandit/pip-audit/secret-scan clean |

Fixes landed that day (each with a regression test): demo persistence (P0 — artifacts
survived reconnect); candidate-kind mismatch (payment_links no longer FAILED_FINAL);
RaR interval math (index-safe p10/p90); deterministic training anchor (newest payment, not
wall clock); loadtest CLI flags; Makefile migrate path; dirty-DB demo guard + adaptive
scenario offset; detection false-positive gates (dual-path admission, MIN_N 25).

## 5) Reliability Lab ship — 2026-08-26 (+9 tests)
Research: 9 official razorpay.com pages fetched & quoted; 7 hashed extracts in
`docs/razorpay/sources/`; inventory CORE/EXTENDED/OUT-OF-SCOPE with NEEDS_REVALIDATION list.
Registries: doc registry (sha256+dates), 14 requirements, traceability map, 7 PayTwin
safety invariants. Engine/fixtures/packs/router/store per README §11; suites generic/webhooks ·
razorpay/core · paytwin/isolation · paytwin/agentic; mutations prove detection; gate =
BLOCKED on any critical finding.

Decision record D1–D8: D1 native module inside services/api (reuse auth/context/design;
no forked second product). D2 generic core + provider packs (Stripe/Cashfree later without
engine changes). D3 provider specs are versioned hashed artifacts; model memory is never a
source. D4 run evidence = immutable JSON documents, not SQL tables. D5 the AI never executes
tests or mutates specs — it explains results. D6 critical findings always force BLOCKED.
D7 no real-money or third-party-production testing; fixtures + sandbox chaos only.
D8 detection admission recalibrated to dual-path because alpha-only tuning could not
separate organic multi-cohort noise from planted outages at reduced volumes.

## 6) UI redesigns — 2026-08-26
Two in-place passes on the single-file app, both honoring the functional-preservation
contract (all `data-act`/`data-live` hooks and the LIVE layer byte-identical):
1. **Apple-inspired DS** (`0cea520`) across all 13 pages.
2. **PayTwin DS v3** (`3ce16a9`) — shadcn-style semantic tokens (dark-first + light/system),
   Linear-grade dark precision, Geist restraint (Inter/JetBrains Mono); added #pagename deep
   links, responsive icon-rail ≤1080 / off-canvas drawer ≤768, `.is-loading`, skeletons,
   theme override. Verified by 23-capture headless-Chrome pass (14 routes dark, 2 light,
   3 responsive widths, drawer/palette/toast/modal states) + zero console errors;
   captures in `docs/ui-shots/`. Plus reliability-lab UI fixes (session-terminal load
   failures vs rotated keys).

## 7) Release-blocker sprint — 2026-08-26 (156 → 182 tests)
Every item shipped with a regression test:
1. **Rate limiting LIVE:** pure-ASGI sliding window on `/api/*` (identity = bearer key else
   client host; default 240/min via `PAYTWIN_RATE_LIMIT_PER_MIN`; `/webhooks/*` +
   `/api/health` exempt; 429 + Retry-After; SSE-safe).
2. **Tenant-scoped integrity:** migration `c7d2e8a41b90` — payments UNIQUE(merchant,
   provider, payment_ref); inbox/canonical idempotency per (provider, org, external id);
   FKs across core relations; audit fork guard UNIQUE(org, prev_hash) + `audit_heads`
   checkpoint (tail deletion detectable). Postgres RLS companion `infra/rls.sql`.
3. **Privacy enforcement:** customer_ref salted-hash pseudonymized in ALL connectors
   (simulator, razorpay, mockprovider); DLQ payloads PII-redacted + size-capped <8KB.
4. **Production gates:** startup config validation (no sqlite/dev secrets/real-PSP exec in
   prod); chaos 403 in production.
5. **Pipeline correctness:** late created cannot regress authorized; Razorpay authorized/
   captured carry distinct event ids (capture no longer deduped); cross-tenant same-ref
   deliveries never share rows; SSE publishes only post-commit; commander chat persists audit.

Live verification performed post-sprint: health 200 · 401 w/o key → 200 w/ risk_admin key ·
UI hydrated (INC-2481 ×10 in DOM) · audit chain OK via API + script · rate-limit flood
= exactly 240×401 then 10×429 · legacy demo DB stamped+migrated to `c7d2e8a41b90`
(fixed a real live 500 on /api/audit/verify from missing `audit_heads`); data intact
(18,033 payments / 1 incident / 5 audit records).

## 8) Documentation consolidation — 2026-08-26
The former 26-file `docs/*` set plus root planning docs were consolidated into exactly two
masters: `README.md` (product/spec/architecture/API/security/evaluation/runbook) and this
`HISTORY.md` (chronicle + decision log). Deleted: both upgrade-plan analyses, old prototype
html, AGENT_BOOTSTRAP, DEMO_RUN artifact copy (regenerated by `make demo`), and all
superseded docs/*.md. Kept as evidence/data (not prose): `docs/razorpay/**` hashed sources,
`docs/ui-shots/**` captures, `project-memory/**` registries. Pointer updates:
`scripts/evaluate.py` docstring → README §14; reliability store comment → this file.

## 9) Deliberate substitutions (honest engineering record)
| Ask | Machine allowed | Decision |
|---|---|---|
| PyTorch FT-Transformer/TabPFN/TimesFM/GNN | 7.9GB free disk, CPU-only | Not installable ⇒ not claimed; baselines + statistical methods real & measured; interfaces stubbed behind ModelBackend (ADR-004) |
| Redpanda/Kafka | 1-node dev | Postgres outbox w/ Kafka-compatible EventBus seam (ADR-003) |
| ClickHouse | overkill v1 | Postgres rollups, isolated analytics interface |
| Temporal | overkill v1 | worker loop w/ durable DB state |

## 10) Decision log (ADR-001 … ADR-012)
- **ADR-001 — Modular monolith first.** Packages with extractable seams (EventBus,
  Connector, ModelBackend, LlmProvider). Demo/build speed, single deployable; boundaries
  prevent a later rewrite. *Accepted.*
- **ADR-002 — Frontend stays the prototype single-page UI, API-bound.** Prototype IA/visuals/
  interactions preserved 1:1; same file gains a data layer (live hydration + async actions),
  deterministic local fallback + DEMO badge when API absent. Next.js migration documented,
  not taken. *Accepted.*
- **ADR-003 — Postgres outbox/inbox instead of Kafka in v1.** Same transactional guarantees,
  zero extra infra; EventBus interface keeps Kafka swap trivial. *Accepted.*
- **ADR-004 — No neural nets in v1.** CPU-only box can't host torch honestly. LR + HistGB +
  isotonic + statistical ensemble + deterministic graph RCA + T-learner uplift + LinUCB are
  implemented and measured; ModelBackend protocol makes neural drop-in future work. No model
  claimed that isn't trained here. *Accepted.*
- **ADR-005 — SQLite-compatible schema for tests.** Portable types; identical models and
  migrations; tests run anywhere without Docker. *Accepted.*
- **ADR-006 — Money as integer paise (BigInteger).** No floats anywhere in money paths;
  UI formats via compact INR formatter. *Accepted.*
- **ADR-007 — Deterministic composer as default LLM provider.** `PAYTWIN_LLM_PROVIDER=none`
  = fully offline grounded template answers with citations; hosted providers opt-in via env.
  Commander works air-gapped. *Accepted.*
- **ADR-008 — SSE over WebSockets.** One-way fan-out suffices (heartbeat/incident/decision/
  action/metric); simpler auth/proxy story; UI keeps 1s local tick + SSE refresh. *Accepted.*
- **ADR-009 — Simulator is the source of truth for evaluation.** All detection/RCA/RaR/uplift
  claims scored against seeded ground truth (`sim_scenarios`), never asserted. *Accepted.*
- **ADR-010 — Dev auth via hashed API keys (JWT-ready seam).** Real SSO/OIDC future scope;
  key carries org+role so middleware is the only swap point. *Accepted.*
- **ADR-011 — Success model scored against the information ceiling, not a fixed AUC bar.**
  The "ROC-AUC > 0.9" target proved information-theoretically unreachable: failure is a fresh
  Bernoulli draw given cohort health + active degradation, so most positives carry no learnable
  signal. ORACLE score reaches only 0.68 on the holdout; champion ~0.60 ≈ 87% of ceiling.
  Test asserts roc_auc ≥ 0.70×oracle and ≥ 0.55 absolute, ECE < 0.05, Brier beats constant-p.
  Feeding realized latency/scenario flags would hit 0.9+ but is leakage (unavailable at
  decision time), forbidden by point-in-time rules. *Accepted.*
- **ADR-012 — Detection admission via exact binomial tail, not fixed counts.** Incidents admit
  when excess failures are statistically surprising vs the cohort's guard-banded pre-onset
  baseline (α .01 across ~40 watched cohorts) with business floors (excess ≥3, SR drop ≥3pts,
  n ≥10 in-window); calibrated so the planted HDFC×upi_intent outage opens exactly one incident
  and clean traffic opens zero. Later extended by D8 dual-path admission. *Accepted.*

---
*Maintainers: update this file with every sprint; keep README.md for what the system IS.*



