# PayTwin OS — Master Reference

> **Single source of truth** for the product: functionality, specifications, architecture,
> data model, API, security/privacy, evaluation, operations. Consolidated 2026-08-26 from
> the former `docs/*` set (see `HISTORY.md` for the build chronology & decision log).
> Status: **205 pytest green** · migration head `d8e4c2a9b517`.

**PayTwin OS** is an autonomous **payment-resilience & revenue-intelligence platform**: it
watches payment traffic across merchants, detects degradation, diagnoses root causes,
quantifies revenue-at-risk, simulates candidate responses in a seeded digital twin, lets a
**deterministic policy engine** decide what autopilot may execute, executes idempotently,
and **measures incremental recovered revenue** against a control baseline.

Core loop: `OBSERVE → UNDERSTAND → PREDICT → DETECT → DIAGNOSE → SIMULATE → DECIDE → GOVERN → ACT → MEASURE → LEARN`

**Boundaries:** payment providers are *connectors only* (data in, execution out) — all
intelligence lives inside PayTwin. The LLM never authorizes or moves money: it investigates,
explains, drafts typed action requests. The **policy engine decides**, the **executor acts**,
the **hash-chained audit records everything**.
**Non-goals (v1):** being a PSP/gateway, processing payments, KYC, settlement ledgering,
billion-event streaming (designed-for, not benchmarked).

**Terminology:** Organization (customer, e.g. Nova Commerce) · Merchant (payment surface,
e.g. Nova Grocery) · Cohort (`issuer × method × PSP × gateway`) · Incident (correlated
anomalies w/ blast radius, RCA, RaR, lifecycle) · **RaR** (expected healthy GMV − incident
GMV, with interval) · Incremental recovery (P(success|action) − P(success|no action), vs
control) · Autonomy modes `0 Observe · 1 Recommend · 2 Approve-first · 3 Bounded autopilot ·
4 Autonomous` · Twin (merchant Monte-Carlo of outcomes under actions).

## Contents
§2 Quickstart · §3 Product surfaces · §4 Tenancy & roles · §5 Architecture · §6 Data model ·
§7 Events & state machine · §8 Intelligence (ML) · §9 Decide→Govern→Act→Measure ·
§10 AI Commander · §11 Reliability Lab · §12 API reference · §13 Security & privacy ·
§14 Measured evaluation · §15 Tests & CI · §16 Frontend & design system · §17 Runbook ·
§18 Configuration · §19 Known limitations · §20 Decision index · §21 Repo layout

## 2) Quickstart (fresh machine)

```bash
# 0) python 3.12 (+ docker optional, for postgres/redis)
git clone <this repo> && cd PayTwin_OS

# 1) virtualenv + editable monorepo install
python3 -m venv .venv && source .venv/bin/activate
pip install --upgrade pip
pip install -e packages/contracts -e services/sim -e services/ml -e services/api
pip install pytest httpx

# 2) tests (sqlite; no services needed)
make test                        # expect: 205 passed

# 3) flagship demo — seeds world, ingests 3h of traffic with an injected HDFC×UPI outage,
#    detects, decides, executes, measures, prints keys + writes DEMO_RUN.md
PAYTWIN_DATABASE_URL=sqlite:///./data/demo.db make demo

# 4) serve API + UI (local Test Mode API) — open with a risk_admin key printed by the demo
PAYTWIN_DATABASE_URL=sqlite:///./data/demo.db make api
open "http://localhost:8000/#key=<risk_admin key>"
```

Dev stack: `make dev` (compose postgres :5433 / redis :6380, migrate, api :8000) ·
`make worker` (30s detection/autopilot/outbox loop). Docker-only alt: `cd infra &&
docker compose up --build`. Demo refuses a dirty DB — re-run with `PAYTWIN_DEMO_RESET=1`.
A DB created before migration `d8e4c2a9b517` needs `alembic stamp b47531c6f9e6` once,
then `upgrade head`.

Make targets: `setup · dev · api · worker · migrate · seed · demo · razorpay-demo · razorpay-api · test · loadtest · verify · clean`.

### Credential-free Razorpay-compatible local Test Mode

```bash
# Builds the full intelligence story and then verifies the real PayTwin webhook
# pipeline with six synthetic Razorpay-shaped, HMAC-signed Test Mode deliveries.
make razorpay-demo

# Use the risk_admin key printed above. The UI clearly remains in Test Mode.
make razorpay-api
open "http://localhost:8000/#key=<risk_admin key>"
```

The local environment is deliberately **sandbox-only**: it never calls Razorpay, accepts no
provider secret through the UI/API, and never enables real payment execution. No Razorpay
account, credentials, secret keys, or public webhook URL are required. The Integrations
screen can create a local order, emit a raw-body HMAC-signed payment callback, verify the
Checkout proof, record exactly one fulfilment, and process a refund through the real
inbox, state-machine and audit paths. Every such response is labelled
LOCAL_RAZORPAY_TEST, so it cannot be mistaken for an account-backed provider feed. It proves
duplicate delivery, forged-signature rejection, out-of-order capture/authorization, late
authorization, partial-refund accounting, and failed-refund handling against PayTwin's real
ingestion and state-machine code. The resulting
`RAZORPAY_TEST_MODE_DEMO.md` is a short judge-facing capability tour.

## 3) Product surfaces — loop → screens
Single-page UI, 15 routes (`apps/web/index.html`), including a guided demo tour. It uses
seeded data by default and clearly labels a connected local API as Test Mode:

| Loop stage | Screen(s) | Backed by |
|---|---|---|
| OBSERVE | Command Center (GMV/SR/RaR/protected/incidents), Checkout Funnel, Payment Health | `/api/overview`, `/api/funnel`, `/api/healthmap` |
| UNDERSTAND | Incident War Room (timeline, evidence, cohorts) | `/api/incidents/{human_id}` |
| PREDICT / LEARN | Model Health (metrics, calibration, drift) | `/api/models` |
| DETECT/DIAGNOSE | War Room RCA (graph attribution, counterfactual) | incidents detail `causes` |
| SIMULATE | Twin Lab (seeded Monte-Carlo, scenario library, pre-incident surge forecast) | `/api/twin/simulate`, `/api/chaos/preview/{scenario}` |
| DECIDE | Candidates + EV + benchmark | candidates in incident detail |
| GOVERN | Policies, blocked-actions log | `/api/policies*` |
| ACT | Executor via connectors (idempotent, audited) | `POST …/execute` |
| MEASURE | Experiments & Recovery (lift CI, batch report) | `/api/experiments*`, `/api/reports/*` |
| EXPLAIN | AI Commander (citations, refusals) | `/api/commander/chat` |
| ASSURE | **Reliability Lab** (release gate, webhook lab, source traceability) | `/api/reliability/*` |

Demo stories: **Flagship** (deterministic seed 42): Nova Grocery baseline UPI SR ≈95%,
inject HDFC×UPI-intent×Cashfree outage 25 min → detect ≤3 windows, top-1 cause = that edge,
RaR interval, simulate {do_nothing, bounded reroute, retry burst, payment links, wait},
argmax-EV under policies, execute w/ rollback guardrail, measure lift vs control,
**policy violations must be 0**. **Graceful-failure**: retry-limit exhausted ⇒ commander's
suggestion BLOCKED with plain reason and "no customer/payment action was executed".

## 4) Tenancy, users, roles
Org → merchants. Seeded world "Nova Commerce": Grocery (Mode 3), Fashion (Mode 2),
Travel (Mode 3), Subscriptions (Mode 1). Roles: `org_admin · ops_oncall ·
finance_viewer · risk_admin`. RBAC: viewers read-only; only risk_admin promotes models /
edits live policies; chaos = admin-only; every query tenant-filtered (`organization_id`
+ scoped `merchant_id`); cross-tenant access ⇒ 404.

## 5) Architecture
**Modular monolith + event-driven worker + ML library boundary** (ADR-001); every seam
extractable: `EventBus` (outbox→Kafka later), `Connector`, `ModelBackend`, `LlmProvider`,
`Cache`.

```
providers --signed webhooks--> /webhooks/{provider} --> HMAC verify --> event_inbox (idempotent)
  --> canonicalizer --> canonical_events (append-only) --> outbox --> worker
      ├─ payments state machine        ├─ feature engine ─ success model
      ├─ detectors (EWMA/CUSUM/z) ─ incidents ─ graph RCA + RaR ─ action candidates
      ├─ EV optimizer ─ policy engine ─ ALLOW→ idempotent executor ─ connector dispatch
      │                                └─ BLOCK/APPROVAL ─┐
      └─ audit hash chain  ←—————————————— every decision —┘
FastAPI :8000 → REST + SSE + serves apps/web ; Commander = read-only tools → evidence → composer
```

| Package | Responsibility |
|---|---|
| `packages/contracts` (`paytwin_contracts`) | canonical schemas, enums, money, versions |
| `services/sim` (`paytwin_sim`) | seeded world gen, scenario injection, webhook emitter, ground truth, demo builder |
| `services/ml` (`paytwin_ml`) | features, training, metrics, detectors, graph RCA, RaR, twin, uplift, LinUCB |
| `services/api` (`paytwin_api`) | REST/SSE, authN/Z, ingest/state machine, policy engine, optimizer, executor, audit, commander, reliability lab, worker |
| `apps/web` | prototype UI (single file) bound to live API, DEMO fallback |

## 6) Data model (26 tables, SQLite-portable)
Conventions: money = **BigInteger paise** (`*_paise`), UTC timestamps, `organization_id`
everywhere (+`merchant_id` where scoped). Groups:
- **Tenancy/identity:** organizations · merchants(autonomy_mode 0-4, stage, sr_base_bp, config JSON) · users · api_keys(key_hash sha256, scopes)
- **Pipeline:** event_inbox UNIQUE(provider,**organization**,external_event_id) · canonical_events append-only UNIQUE(org,provider,external_event_id) · dead_letters · outbox(transactional) · payments UNIQUE(**merchant,provider,payment_ref**) · **orders** (one business order across attempts) · **refunds** (provider id + partial amount) · **fulfilments** (one per order) · **checkout_verifications** (server-side proof)
- **Intelligence:** predictions(model/feature version) · incidents(human_id INC-####, RaR lo/hi) · incident_evidence · root_cause_candidates(edge,score,counterfactual_share) · simulations UNIQUE(incident,scenario,seed,params_hash) · action_candidates(ev_paise…) · policies(RP-### versioned rules) · policy_decisions(decision,failed_rules,**policy_version carries contributing versions**) · action_executions(ACT-####, idempotency_key UNIQUE, state machine)
- **Measurement:** experiments · experiment_assignments UNIQUE(exp,group) · outcomes UNIQUE(assignment)
- **Models:** model_versions(stage trained→validated→shadow→canary→champion→retired, metrics, artifact)
- **Audit:** audit_records(seq, prev_hash, hash=sha256(prev+canonical_json)) append-only + **audit_heads checkpoint(org,last_seq,last_hash,count)** — fork guard UNIQUE(org,prev_hash)
- **Sim ground truth:** sim_scenarios(true_excess_failures, true_rar_paise, true_top_cause)

Migration `d8e4c2a9b517` adds order/refund/fulfilment/Checkout-proof integrity records and
per-integration secret-rotation metadata on top of the tenant-scoped FKs and audit checkpoint;
Postgres deployments can layer `infra/rls.sql` row-level security.

## 7) Event contracts & payment state machine
Ingress: `POST /webhooks/{provider}` + `X-PayTwin-Signature: sha256=HMAC(secret,body)`.
Providers: `simulator` · `mockprovider` · `razorpay` (dialect maps live only in
connectors). Bad signature ⇒ 401 + DLQ; malformed ⇒ 422 + **PII-redacted, size-capped**
DLQ payload; duplicate external id ⇒ 200 `{duplicate:true}`.

Canonical event (v1): `schema_version, id, type(payment.created|authorized|failed|success|
timeout|refund.created|refund.failed|refund.updated|order.paid|connector.health), organization_id, merchant_id, provider,
external_event_id, occurred_at, ingested_at, payment_ref, amount_paise, currency=INR,
cohort{issuer,method,psp,gateway}, payload{failure_class,latency_ms,customer_ref(pseudonym),order_ref,attempt_no,group_id}, late`.

Rules: canonicalize once at the edge; `late = occurred_at < last_seen − 60s`; out-of-order
never regresses state (forward-only by rank); late events still count at original timestamp
(point-in-time correctness). State machine:
```
created → authorized → success
created → failed                    failure_class: issuer_decline|timeout|auth|
created → timeout → success(late)   rate_limit|psp_error|checkout_error|insufficient_funds
```
Outbox topics: `payment.updated · incident.opened · incident.state_changed ·
policy.decided · action.requested · action.executed · prediction.made · audit.appended ·
metric.snapshot`. Guarantees: effectively-once processing via inbox unique key; outbox
retries w/ backoff, poison→DLQ; admin replay idempotent. SSE publishes **only after commit**.

## 8) Intelligence stack (implemented & measured — nothing claimed that isn't trained here)
| Layer | Implementation |
|---|---|
| Success prediction | LogisticRegression baseline + HistGradientBoosting challenger, isotonic calibration; time-based holdout; scored vs ORACLE information ceiling (ADR-011) |
| Probability quality | ROC-AUC, PR-AUC, log-loss, Brier, ECE(10-bin) per model |
| Temporal anomaly | EWMA + CUSUM + robust-z ensemble on merchant×cohort baselines (hour-of-week seasonal profile); admission = statistical persistence OR overwhelming single-window evidence (ADR-012 binomial tail) |
| Forecast band | seasonal-naïve + residual quantiles (honest label; not TimesFM) |
| Graph RCA | heterogeneous attribution (issuer×method×psp×gateway) + counterfactual mask share |
| Revenue at Risk | counterfactual expected GMV with residual-quantile 80% interval |
| Digital twin | seeded merchant Monte-Carlo (400+ trials), 7 scenarios; same seed ⇒ identical output |
| Causal uplift | T-learner (two HistGB heads) + design-based lift w/ bootstrap CI |
| Policy optimization | LinUCB offline eval vs fixed arm; hard constraints stay outside the bandit |

Feature groups (point-in-time, `occurred_at ≤ t` enforced + leakage-tested): transaction ·
merchant · customer(pseudonymous streaks) · issuer · PSP · gateway · method · temporal ·
historical · incident · recovery. Lifecycle `TRAINED→VALIDATED→SHADOW→CANARY→CHAMPION→
RETIRED` (risk_admin-gated); every prediction stores model/feature/policy versions.
Personalization ladder: global → industry prior → merchant embedding(shrinkage) → merchant
isotonic calibration → real-time context. Training reproducible: fixed seed ⇒ byte-identical
metrics; dataset fingerprint stored.

## 9) Decide → Govern → Act → Measure
- **EV optimizer:** `EV(a,x) = P(incr_success|a,x)·value·clv·decay − costs − risk_penalty`;
  argmax subject to policies; explicit NO_ACTION floor when EV ≤ 0.
- **Policy engine:** typed validated rules (amount_cap, max_attempts, dnd_window_ok,
  consent_on_file, provider_down…), versioned (`RP-###:vN`), draft/live/archived; verdicts
  ALLOW / REQUIRE_APPROVAL / BLOCK with failed_rules; decisions record the exact enforcing
  policy version. Autonomy ladder gates dispatch per merchant mode.
- **Executor:** idempotency-keyed state machine (created→validated→approved→scheduled→
  executing→succeeded/failed_retryable/failed_final/rejected_by_policy); duplicate request ⇒
  same execution; capability-checked connector dispatch; policy engine unavailable ⇒ refuses
  autonomous action (fail-safe). Real-PSP execution disabled by default
  (`allow_real_execution=false`; production can never enable it).
- **Measure:** experiment assignment control/treatment w/ propensity; outcomes join ⇒ lift +
  95% CI + incremental paise; batch report endpoint (markdown download).

## 10) AI Commander (incident commander assistant)
Path: message → deterministic intent classifier → **read-only tenant-scoped tools**
(get_incident, list_incidents, query_metrics, get_twin_run, get_experiment, get_policy,
explain_decision, get_audit) → evidence pack E1..En → composer → answer + citation chips.
Write-intents become typed ActionRequests evaluated by the policy engine — chat never
executes. Providers via `LlmProvider`: `none` (default deterministic grounded composer),
openai/anthropic opt-in (temp 0, must cite evidence ids; ungrounded sentences dropped).
Safety: tool outputs are data-not-instructions; credentials never enter prompts; every turn
audited (tools, latency, citations, mode); 6-prompt refusal set + 12-QA golden grounding eval tested.

## 11) Reliability Lab (native module, shipped 2026-08-26)
Proves a payment integration behaves correctly under lifecycle failures **before production**:
duplicates, forged callbacks, out-of-order events, fulfil-on-authorized, refund-over-capture,
cross-tenant blindness, mandate-limit bypass.
Module map: `fixtures.py` (correct + known-broken mutation policies) → `engine.py`
(deterministic Event→handler→World ledger→invariant evaluation, no I/O) → `packs.py`
(suites = clean base + mutations that MUST violate exactly their listed invariants —
"test the tester" by construction) → `invariants.py` PTWIN-INV-001..007 → `router.py`
(`/api/reliability/*`, bearer auth, tenant-scoped) → `store.py` immutable JSON run artifacts
(`data/reliability/runs.json`). **Release gate:** any critical finding ⇒ BLOCKED regardless
of score; else WARNING on high/medium; else READY. Razorpay scenarios trace to requirement
ids resolving through `project-memory/razorpay-requirements.jsonl` into sha256-hashed
sources in `docs/razorpay/sources/` (claims require OFFICIAL_DOC level or are labeled
PAYTWIN_INVARIANT / INFERRED / UNKNOWN). UI page `#reliability` + Commander answers
release-gate questions from live state.

## 12) API reference (v1)
Base `http://localhost:8000` · auth `Authorization: Bearer <api_key>` · errors
`{"error":{"code","message","details"}}` · list endpoints accept `?scope=org|<merchant_id>`
(tenant-filtered) · OpenAPI `/api/openapi.json`, swagger `/api/docs` · **Rate limit:** all
`/api/*` allow `PAYTWIN_RATE_LIMIT_PER_MIN` (default 240) req/min per credential — excess ⇒
429 `rate_limited` + `Retry-After`; `/webhooks/*` & `/api/health` exempt.

| Area | Endpoints |
|---|---|
| System | GET /api/health {status,db,version,env} (no auth) · GET /api/meta {org,role,merchants[],feature_flags} · GET /api/stream?scope= (SSE: heartbeat/incident/policy_decision/action/metric) |
| Dashboard | GET /api/overview · /api/funnel · /api/healthmap |
| Merchants | GET /api/merchants · /api/merchants/{id} |
| Incidents | GET /api/incidents?scope=&state= · GET /api/incidents/{human_id} (timeline,causes,candidates,evidence,cohorts,rar) · POST …/execute {candidate_id}→202 {decision,execution_id,state,failed_rules} · POST …/resolve |
| Twin | POST /api/twin/simulate {scope,scenario,alloc_pct,duration_min,seed?} → p50/lo/hi, lift_pct, traj[], trials, seed, policy_compat; same input+seed ⇒ byte-identical |
| Policies | GET/POST /api/policies · PATCH /api/policies/{human_id} (new version) · GET /api/policies/blocked · POST /api/policies/preview (historical replay projection) |
| Commander | POST /api/commander/chat {scope,incident?,message} → reply_md,citations,tools[],mode,action_request? — never executes directly |
| Experiments/Reports | GET /api/experiments[/{id}] · GET /api/reports/recovery-batch?hours= (markdown download) |
| Models | GET /api/models · POST /api/models/{id}/promote {stage} (risk_admin) |
| Audit | GET /api/audit?scope=&actor=&type= · GET /api/audit/verify → chain integrity incl. checkpoint · GET /api/audit/export?fmt=jsonl\|dossier |
| Chaos | POST /api/chaos/{scenario} {scope,duration_min?} — psp_degradation, issuer_outage, gateway_latency, checkout_regression, webhook_lag, auth_failures, rate_limit. Admin-only; 403 in production |
| Webhooks | POST /webhooks/{provider} (HMAC; 401+DLQ bad sig; 422+redacted DLQ malformed) |
| Reliability Lab | GET /api/reliability/{overview,suites,runs,runs/{id},findings,release-gate} · POST /api/reliability/run · POST /api/reliability/webhook-lab/{fault} |

## 13) Security & privacy
**AuthN/AuthZ:** hashed API keys (sha256, prefix-display), org+role scoped, JWT-ready seam
(ADR-010); RBAC per-route; tenant filters everywhere, isolation tests prove denial.
**Input/injection:** constant-time HMAC webhooks; Pydantic validation; SQLAlchemy bound
params only; UI escapes interpolation; API is JSON-only.
**Rate limiting:** pure-ASGI sliding-window on every `/api/*` route; identity = bearer
credential else client host; default 240/min (`PAYTWIN_RATE_LIMIT_PER_MIN`); webhooks +
health exempt; 429 + `Retry-After`; SSE-safe. Tested (`TestRateLimiting`) and verified live.
**Deployment gates:** startup config validation fails fast in production (no sqlite
datastore, no dev-default secrets, no short secret_key, no real-PSP execution); chaos
routes 403 in production.
**Schema hardening:** tenant-scoped unique constraints + FKs (migration `c7d2e8a41b90`);
optional Postgres row-level security companion (`infra/rls.sql`,
`SET app.current_org`).
**Audit:** append-only per-org SHA-256 chain; UNIQUE(org, prev_hash) fork guard +
`audit_heads` checkpoint make tail-deletion detectable; verify endpoint + JSONL/dossier exports;
`make verify`.
**Privacy:** no card/PAN/UPI credentials/CVV/tokens/bank logins ever stored (rejected at
canonicalization); customers pseudonymous — every connector maps customer id to
`c_`+salted-SHA-256-prefix via `pseudonymize_ref` (regression-tested through ingest);
contact-bearing actions pass recipient refs through the connector at execution time (store
only ref + consent result); consent predicates are policy inputs (missing consent ⇒ blocked);
right-to-erasure = delete rows by ref (mapping lives merchant-side); LLM prompts carry
aggregates + refs only; DLQ payloads PII-redacted + <8KB; retention: canonical events 400d,
audit retained.
**Secrets:** `.env` only, `.env.example` documents all; connector secrets via `secret_ref`
resolved at runtime — never logged, never sent to LLMs, masked in API responses.

Threat model (residual): cross-tenant access **low** (filters+404+RLS+tests) · forged
webhook **low** (HMAC+idempotency) · unsafe autonomous action **low** (policy+ladder+
idempotency+audit) · prompt injection **med/defense-in-depth** (structured evidence,
refusal eval) · secret exfiltration via LLM **low** (secret_ref indirection) · audit
tampering **low** (chain+checkpoint+verify) · ingest DoS **med** (rate limit+DLQ+
backpressure) · model poisoning via replay **med** (simulator-only training v1).

## 14) Measured evaluation (this machine, seeded ground truth — re-run everything)
```bash
python scripts/evaluate.py      # every number below
make loadtest && make verify    # perf + audit chain
```
- **Success model** (25,503 rows, holdout): champion LR/HistGB+isotonic — ROC-AUC **0.604**,
  ECE **0.0023**, reproducible. Scored vs ORACLE ceiling 0.68 (ADR-011) ⇒ ~87% of ceiling;
  asserted `≥0.70×oracle`, calibration ECE<0.05.
- **Detection** (5 planted scenarios): all detected; delays issuer_outage 5m · psp 20m ·
  checkout 0m · auth 5m · rate_limit 0m. Clean worlds (seeds 42 & 7, ~40 cohorts × 4
  merchants): **zero incidents** (regression-tested).
- **Graph RCA:** top-1 **4/5**, top-3 **5/5**. **RaR:** interval covers truth **5/5**,
  point∈interval 5/5, median rel-error 0.219.
- **Decision quality:** NO_ACTION whenever EV≤0 (unit-tested); executed policy violations
  across demo runs: **0**.
- **Bandit vs fixed:** LinUCB 75.0 vs 56.0 (seed 7 replay).
- **Load (single worker):** ingest **1,030.9 ev/s**, p95 31.3ms · health p95 8.2ms ·
  overview p95 601ms.
- **Frontend binding:** headless Chrome against live API shows LIVE hydration markers +
  incident refs end-to-end.

## 15) Tests & CI
`make test` → **205 passed** (sqlite, portable schema). Layers: unit · API integration
(httpx ASGI: auth/RBAC/isolation/rate-limit/SSE) · pipeline (dup/late/malformed/out-of-order/
replay/DLQ/state machine) · ML (determinism/calibration/leakage/registry) · detection/RCA/RaR
vs ground truth · decisioning (optimizer floor, policy blocks, duplicate execution, autonomy
gates) · commander (grounding/refusal/fallback) · E2E journey (ingest→incident→RCA→simulate→
decide→policy→execute→outcome→lift→dashboard) · security · frontend (headless Chrome + static).
Release-blocker suite covers safety gates, tenant isolation, pipeline correctness, policy
enforcement, audit/outbox semantics, rate limiting.
CI (`.github/workflows/ci.yml`): pytest + fresh-DB migration drift check → bandit + pip-audit +
secret scan (`*.py/*.md/*.yml/*.html` — never commit keys) → ui-smoke headless Chrome.

## 16) Frontend & design system (PayTwin DS v3)
Single-file vanilla-JS app (`apps/web/index.html`), no build step, 15 routes (#tour …
#reliability). With a key it hydrates org/merchants/incidents/policies/models from `/api/*`,
intercepts backed actions/chat/exports, and labels the connection **TEST MODE API**; without
a key it runs the local deterministic engine labeled **DEMO**. DS v3 = shadcn-style semantic tokens (dark-first
+ light/system), Linear-grade dark precision, Geist-style restraint (Inter + JetBrains Mono):
4-base spacing, radii 8/12/16/pill, hairline separation + two ambient glows, translucent
sidebar/topbar materials, tabular-nums for money, ⌘K palette, toasts, sheets/modals,
skeleton loading, responsive icon-rail ≤1080 / off-canvas drawer ≤768, reduced-motion
honored, focus-visible everywhere. Functional contract: all data-act/data-live hooks and the
LIVE layer byte-preserved across redesigns. Visual captures: `docs/ui-shots/{before,after}/`.

## 17) Operations runbook
Health: `/api/health`; tenant readiness: `/api/operations/status`; admin local repair:
`POST /api/operations/reconcile`. The repair sweep only settles already-recorded, held refunds
after their payment is captured and retires expired webhook-secret grace references—it makes no
provider call, fulfilment, or money movement. Symptom→action: UI blank/DEMO ⇒ API down (`make api`)
· no incidents ⇒ worker lag / outbox undispatched · webhook 401 ⇒ secret mismatch · events stuck ⇒
inspect dead_letters · pending refund ⇒ run the reconciler and inspect the canonical event chain ·
twin numbers differ ⇒ seed/params differ (else bug) · action stuck ⇒ check executions state + outbox
retry (idempotent) · chain invalid ⇒ verify returns first bad seq, restore from export. Failure drills
(safe by design): kill postgres ⇒ health degrades, UI falls back DEMO; kill worker ⇒ outbox grows,
restart drains. Repairs: admin local reconciliation, model promote (risk_admin, audited), bounded
webhook-secret reference rotation via `/api/integrations/webhook-secret/rotate`.

## 18) Configuration (`.env.example`)
`PAYTWIN_ENV` development|production · `PAYTWIN_DATABASE_URL` · `PAYTWIN_REDIS_URL` ·
`PAYTWIN_SECRET_KEY` · `PAYTWIN_WEBHOOK_SECRET_{SIMULATOR|MOCKPROVIDER|RAZORPAY}` ·
`PAYTWIN_HASH_SALT` (customer_ref pseudonym salt) · `PAYTWIN_LLM_PROVIDER=none|openai|
anthropic` (+`PAYTWIN_LLM_API_KEY`) · `PAYTWIN_WORKER_INTERVAL=30` ·
`PAYTWIN_RATE_LIMIT_PER_MIN=240` · `PAYTWIN_ALLOW_REAL_EXECUTION=false` ·
`PAYTWIN_RAZORPAY_KEY_SECRET` (server-only Checkout verifier secret) ·
`PAYTWIN_DEMO_RESET` / `PAYTWIN_SEED` / `PAYTWIN_DEMO_URL` (demo controls).

## 19) Known limitations (honest)
Neural backbones (FT-Transformer/TabPFN/TimesFM/GNN) stubbed behind ModelBackend — CPU-only
box; measured baselines shipped instead. Single-node scale measured (~1.2k ev/s); 10K-merchant
design documented, not benchmarked. Razorpay connector sandbox-ready (no production keys).
Auth is API-key based; SSO/OIDC future. Postgres rollups (ClickHouse path documented).
Razorpay support is Test Mode ingress and verification only: external order creation, refund creation,
Downtime API polling, settlement reconciliation, and any real money execution are intentionally out
of scope for this build.
Hosted LLM optional; deterministic composer default. Headless-Chrome smoke instead of full
Playwright suite. All product metrics are simulator-derived and labeled SIMULATION in-app.
Demo admission is time-aware: IST quiet hours can approval-gate the best candidate (reported
honestly in DEMO_RUN.md).

## 20) Decision index (full narratives in HISTORY.md)
ADR-001 modular monolith first · ADR-002 prototype UI stays, API-bound · ADR-003 outbox/inbox
over Kafka v1 · ADR-004 no neural nets v1, measured baselines · ADR-005 SQLite-portable test
schema · ADR-006 integer paise · ADR-007 deterministic composer default LLM · ADR-008 SSE over
WebSockets · ADR-009 simulator = evaluation ground truth · ADR-010 hashed API-key auth ·
ADR-011 success model scored vs information ceiling, not absolute AUC · ADR-012 detection
admission via exact binomial tail + business floors. Reliability Lab D1–D8 (native module,
generic core + provider packs, hashed spec registry, immutable JSON evidence, AI never
executes tests, critical-blocks gate, no live-money testing, recalibrated dual-path detection).

## 21) Repo layout
| Path | What |
|---|---|
| `packages/contracts` | canonical events/enums/money |
| `services/sim` | generator, scenarios, demo builder |
| `services/ml` | features/detectors/RCA/RaR/twin/training/causal |
| `services/api` | FastAPI app, connectors, pipeline, intelligence glue, reliability lab, worker |
| `services/api/alembic` | migrations (`b47531c6f9e6` init → `c7d2e8a41b90` hardening) |
| `apps/web` | the single-file UI (DS v3) |
| `infra/` | Dockerfile.api, docker-compose.yml, rls.sql |
| `scripts/` | evaluate.py · loadtest.py · ui_smoke.py · verify_audit.py |
| `tests/` | 182-test pytest suite incl. release blockers |
| `docs/razorpay/` | hashed provider-spec sources + inventory (Reliability Lab provenance) |
| `project-memory/` | registries (requirements/invariants/traceability), task graph |
| `data/` | local DBs, reliability run evidence, load results (gitignored artifacts) |
