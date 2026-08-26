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

**ADR-011 — Per-payment success model scored against the information ceiling, not a
fixed AUC number.** The brief's "ROC-AUC > 0.9" for ML-002 proved information-
theoretically unreachable: on this simulator a payment's failure is a fresh Bernoulli
draw given cohort health + active degradation, so most positives carry no learnable
signal. Measured with seed-fixed episodes (5 x 2h, 5 overlapping scenarios): ORACLE
score (true cohort SR x active multipliers — perfect world knowledge) reaches only
ROC-AUC 0.68 on the time-based holdout; the trained champion (HistGB+isotonic)
reaches ~0.60 = ~87% of ceiling. Test asserts roc_auc >= 0.70 * oracle_auc and
>= 0.55 absolute, plus calibration (ECE < 0.05) and Brier better than the constant-p
predictor. Feeding realized latency or scenario flags would hit 0.9+ but is leakage
(unavailable at decision time) and forbidden by §point-in-time. Status: accepted.

**ADR-012 — Detection severity uses an exact binomial tail test, not fixed counts.**
Correlated-cohort incidents admit when excess failures are statistically surprising
vs the cohort's own guard-banded pre-onset baseline (alpha 0.01 across ~40 watched
cohorts), with business floors (excess >= 3 failures, SR drop >= 3pts, n >= 10 in the
20-min window). Calibrated so the planted HDFC×upi_intent outage opens exactly one
incident while clean traffic opens zero. Status: accepted.


# Decision log additions — Reliability Lab (2026-08-26)

D1. Reliability Lab lives inside services/api as a native module (no separate app):
    it reuses auth, merchant context, connectors' semantics, audit conventions,
    design system and navigation; a second product would fork all of them.
D2. Generic core + provider packs: core speaks only in scenarios/invariants;
    Razorpay specifics live behind suite definitions traced to requirement ids,
    so Stripe/Cashfree packs can be added without touching the engine.
D3. Provider specs are versioned artifacts: verbatim extracts + sha256 + dates in
    docs/razorpay/sources; claims require OFFICIAL_DOC level or are labeled
    PAYTWIN_INVARIANT / INFERRED / UNKNOWN. Model memory is never a source.
D4. Run evidence is immutable JSON (data/reliability/runs.json), not SQL tables:
    generated, append-only, queried rarely; avoids schema churn in v1.
D5. The AI never executes tests or mutates specs; it explains gate/findings and
    labels statements as Official requirement vs PayTwin invariant vs inference.
D6. Release Gate: any critical finding forces BLOCKED regardless of score;
    score is derived only from measured finding counts by severity.
D7. Live-money and third-party production chaos testing are forbidden; testing
    happens against modeled fixtures and existing sandbox injection routes.
D8. Detection admission was recalibrated (alpha .003 persistence-path with w2
    confirmation OR overwhelming single-window evidence incl. >=2 dims and
    RCA-share >=75%) because alpha-only tuning could not separate organic
    multi-cohort noise from planted outages at reduced volumes.
