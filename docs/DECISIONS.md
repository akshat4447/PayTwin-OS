# Decision Log (ADR index)

**ADR-001 — Modular monolith first.** Services as packages with extractable seams
(EventBus, Connector, ModelBackend, LlmProvider protocols). Rationale: demo+build speed,
single deployable, no distributed-system tax; boundaries prevent rewrite later. Status: accepted.

**ADR-002 — Frontend stays the prototype single-page UI, API-bound.** The prototype's
information architecture, visuals and interactions are preserved 1:1 (user requirement).
Instead of a Next.js rewrite (high regression risk, zero UX gain), the same file gains a
data layer: live API hydration + async actions, with deterministic local fallback + DEMO
badge when API is absent. Migration path to Next.js documented but not taken. Status: accepted.

**ADR-003 — Postgres-backed outbox/inbox instead of Kafka/Redpanda in v1.** Same
transactional guarantees, zero extra infra; `EventBus` interface keeps Kafka swap-in
trivial. Status: accepted.

**ADR-004 — No neural nets in v1; measured baselines only.** 7.9 GB disk / CPU-only box
cannot host torch honestly. LR + HistGB + isotonic calibration + statistical ensemble +
deterministic graph RCA + T-learner uplift + LinUCB are implemented and measured.
`ModelBackend` protocol + registry make FT-Transformer/TabPFN/TimesFM/GNN drop-in future
work. No model is claimed that isn't trained here. Status: accepted.

**ADR-005 — SQLite-compatible schema for tests.** Portable column types; Postgres in
dev/demo. Rationale: tests run anywhere without Docker; identical models/migrations.
Status: accepted.

**ADR-006 — Money as integer paise (BigInteger).** No floats anywhere in money paths;
UI formats via compact INR formatter. Status: accepted.

**ADR-007 — Deterministic composer as default LLM provider.** `PAYTWIN_LLM_PROVIDER=none`
gives fully offline, grounded, template-composed answers with citations; hosted providers
opt-in via env. Guarantees the commander works in air-gapped demos and tests. Status: accepted.

**ADR-008 — SSE over WebSockets for live updates.** One-way fan-out is sufficient
(heartbeat, incident, decision, action, metric events); simpler auth/proxy story; UI keeps
1s local tick + SSE refresh. Status: accepted.

**ADR-009 — Simulator is the source of truth for evaluation.** All detection/RCA/RaR/
uplift claims are scored against seeded ground truth (`sim_scenarios`), never asserted.
Status: accepted.

**ADR-010 — Dev auth via hashed API keys (JWT-ready seam).** Real SSO/OIDC is future
scope; key model carries org+role so middleware is the only swap point. Status: accepted.
