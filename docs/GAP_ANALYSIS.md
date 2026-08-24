# GAP ANALYSIS — Phase 0 findings

Scope: repository state before the production build (2 planning docs + `paytwin-os-v2.html`
prototype). Benchmark: master build prompt phases 0–52 + the prototype's own UX bar.

## What exists
| Artifact | State |
|---|---|
| `paytwin-os-v2.html` | Fully working single-file SPA: 13 pages, live 1s-tick sim engine, seeded 400-trial Monte-Carlo twin lab, streaming AI commander w/ citation chips + refusal, working file exports, chaos console, org switcher (1 org × 4 merchants), dark/light, ⌘K palette. **All data is in-page constants; no backend.** |
| `DEEP_ANALYSIS_AND_UPGRADE_PLAN.md` | Blueprint-vs-judging-bar gap analysis (G1–G12), model stack recs, roadmap. |
| `PROTOTYPE_AUDIT_AND_UPGRADE_PLAN.md` | Page-by-page redesign plan + target architecture + DDL sketch. |

## Gap matrix → production system
| # | Gap | Severity | Resolution in this build |
|---|---|---|---|
| 1 | Every number is an in-page constant; no persistence | Critical | FastAPI + Postgres; UI bound to live API (ADR-002), demo fallback kept honest |
| 2 | No event ingestion (no webhooks, no canonical events) | Critical | Connector framework + canonical pipeline w/ idempotency/inbox/outbox/DLQ/replay |
| 3 | No real ML — "models" are UI labels | Critical | LR + HistGB + isotonic calibration trained on simulator data; registry w/ lifecycle + measured metrics |
| 4 | Twin = linear toy formula | Critical | Seeded merchant Monte-Carlo (400+ trials), distributions, reproducibility tests |
| 5 | No detection/RCA/RaR computation | Critical | EWMA+CUSUM+robust-z ensemble; graph attribution + counterfactual mask; RaR w/ intervals — all scored vs simulator ground truth |
| 6 | No policy engine / executor / audit | Critical | Deterministic versioned policy engine, idempotent executor, hash-chained audit |
| 7 | Commander = 2 canned if/else answers | High | Tool-grounded orchestrator: intent → read-only tools → evidence pack → cited answer; typed write-intents; refusal path; deterministic offline composer |
| 8 | No multi-tenancy enforcement | High | org/merchant scoping in schema + authz + isolation tests |
| 9 | No experiments / causal measurement | High | Assignment + outcome storage, control/treatment lift + CI, T-learner uplift, LinUCB offline eval |
| 10 | No tests anywhere | High | 130+ pytest suite (unit/integration/security/ML/E2E journey) |
| 11 | No deployment story | Medium | docker-compose, Dockerfiles, Makefile, CI, .env.example |
| 12 | No docs/memory system | Medium | Full docs/ set + project-memory/*.json (this build's spine) |

## Deliberate substitutions (honest, documented)
| Prompt asks | This machine allows | Decision |
|---|---|---|
| PyTorch FT-Transformer / TabPFN / TimesFM / GNN | 7.9 GB free disk; CPU-only | Not installable ⇒ **not claimed**. Baselines (LR, HistGB) + statistical ensemble + deterministic graph RCA + T-learner uplift + LinUCB are real and measured. Neural interfaces stubbed behind `ModelBackend` protocol (ADR-004). |
| Redpanda/Kafka | Docker OK but 1-node dev | Postgres-backed outbox queue with Kafka-compatible `EventBus` interface (ADR-005) |
| ClickHouse | overkill for v1 | Postgres rollups; analytics interface isolated |
| Temporal | overkill for v1 | Worker loop w/ durable DB state; Temporal-compatible task naming |

## Prototype issues found during audit (fixed in this build)
- Missing `#app` mount div crashed real browsers (fixed pre-build; smoke harness masked it).
- `pt_check.py` was a one-shot repair script, not a checker (replaced with read-only checker).
- No content after `</html>`; single script block — clean base to bind API onto.
