# CURRENT STATE

> **RELIABILITY LAB v1 SHIPPED (2026-08-26)** — native PayTwin module for payment
> integration assurance. See RELIABILITY LAB section below; the 2026-08-25 UI/audit
> matrix further down remains accurate.
>
> **RELEASE-BLOCKER SPRINT SHIPPED (2026-08-26)** — see that section below for the
> security/integrity fixes (rate limiting live, tenant-scoped uniques/FKs + audit
> fork guard, pseudonymization in all connectors, production gates). Suite now
> **182 passed**.

## RELIABILITY LAB

- **Research:** 9 official razorpay.com pages fetched & quoted; 7 hashed extracts in
  `docs/razorpay/sources/`; inventory classified CORE/EXTENDED/OUT-OF-SCOPE
  (`docs/razorpay/DOC_INVENTORY.md`). NEEDS_REVALIDATION items listed there.
- **Registries:** `project-memory/razorpay-doc-registry.json` (sha256+dates),
  `razorpay-requirements.jsonl` (14 requirements), `razorpay-traceability.json`,
  `razorpay-invariants.json` (7 PayTwin safety invariants).
- **Engine:** deterministic scenario runner (`reliability/engine.py`) driving modeled
  provider events through merchant fixture policies; 7 executable business invariants;
  dual-path admission calibrated against clean-vs-planted sweeps (see constants).
- **Suites:** generic/webhooks · razorpay/core · paytwin/isolation · paytwin/agentic —
  every Razorpay scenario traced to requirement ids; mutations prove detection.
- **API:** /api/reliability/{overview,suites,run,runs,runs/{id},findings,
  release-gate,webhook-lab/{fault}} — bearer auth, tenant-scoped.
- **UI:** `#reliability` page (gate banner, KPIs, suites table, findings, webhook lab,
  spec-registry card) using the Apple design system; Commander answers release-gate
  questions from live state.
- **Tests:** tests/test_reliability.py — 9 passing (engine determinism, mutation
  detection ≥6, unsigned-zero-effects, API surface, tenant isolation, BLOCKED gate).

## RELEASE-BLOCKER SPRINT (2026-08-26)

Every item landed **with a regression test** (`tests/test_release_blockers.py`,
`tests/test_connectors.py`, et al.):

1. **Rate limiting is LIVE:** sliding-window per-identity limiter on `/api/*`
   (default 240 req/min via `PAYTWIN_RATE_LIMIT_PER_MIN`; identity = bearer
   credential else client host). `/webhooks/*` + `/api/health` exempt; excess ⇒
   429 `rate_limited` + `Retry-After`; SSE-safe pure ASGI.
2. **Tenant-scoped integrity (migration `c7d2e8a41b90` on `b47531c6f9e6`):**
   payments UNIQUE per (merchant, provider, payment_ref); inbox/canonical
   idempotency per (provider, org, external id); FKs across core relations;
   audit fork guard UNIQUE(org, prev_hash) + `audit_heads` checkpoint — tail
   deletion is caught. PostgreSQL RLS companion: `infra/rls.sql`.
3. **Privacy enforcement:** `customer_ref` salted-hash pseudonymized at
   canonicalization in **all three connectors** (simulator, razorpay,
   mockprovider); DLQ payloads PII-redacted + size-capped (<8 KB).
4. **Production gates:** startup config validation (no sqlite datastore, no dev
   default secrets, no real-PSP execution in prod — fail fast); chaos routes 403
   in production; `allow_real_execution=False` by default everywhere.
5. **Pipeline correctness:** late `created` cannot regress `authorized`;
   Razorpay authorized/captured carry distinct event ids (capture no longer
   deduped away); cross-tenant same-ref deliveries never share/regress rows;
   SSE publishes only post-commit (rollback drops events); commander chat
   persists its audit record durably.

## FINAL COMPLETION MATRIX (2026-08-25 audit)

| AREA | REQUIREMENT | STATUS | EVIDENCE |
|---|---|---|---|
| Tests | Full suite green | VERIFIED | **182 passed** (`pytest tests/ -q`, main venv) incl. the release-blocker suite (+26 tests vs the 156 of this audit) |
| Database | Clean-DB migration | VERIFIED | `make migrate` → `c7d2e8a41b90` (tenant-scoped uniques/FKs/audit guard, on `b47531c6f9e6 init schema`), 26 tables incl. `audit_heads` (SQLite **and** Postgres 16 container) |
| Backend | Webhook ingest (HMAC/idempotency/DLQ/outbox) | VERIFIED | suite: test_pipeline, test_connectors |
| Backend | Payment state machine | VERIFIED | suite: test_models/test_pipeline |
| ML | Success model train+registry | VERIFIED | evaluate.py: ROC-AUC .604 / ECE .0023 / reproducible; registry rows written by demo |
| ML | Detector ensemble | VERIFIED | 5/5 planted detected (delays 0–20 min); clean worlds open **0** incidents (regression-tested) |
| ML | Graph RCA | VERIFIED | top-1 4/5 · top-3 5/5 vs truth |
| ML | Revenue-at-risk intervals | VERIFIED | coverage 5/5; point∈interval 5/5 (+adversarial unit test) |
| Decisions | EV optimizer + NO_ACTION floor | VERIFIED | suite: test_governance |
| Governance | Policy engine + autonomy ladder | VERIFIED | demo: 2 blocked / 2 approval-gated / violations 0 |
| Executor | Idempotent policy-gated dispatch | VERIFIED | duplicate-request test returns same execution; demo executions persisted |
| Audit | SHA-256 hash chain + verify/export | VERIFIED | demo chain ok with **5 records**; tamper test flips seq=3 |
| Causal | Experiments + uplift + LinUCB | VERIFIED | offline replay: LinUCB 75.0 vs fixed 56.0 |
| Agent | Commander read-only tools/refusal | VERIFIED | suite: test_commander (never dispatches; audited) |
| API | REST routers + SSE + RBAC | VERIFIED | live curl: health 200; overview 401 w/o key → 200 w/ risk_admin key |
| Frontend | UI bound to live API | VERIFIED | headless Chrome DOM: LIVE-hydration markers + 15 incident refs against demo DB |
| Demo | Flagship E2E persists artifacts | VERIFIED | fresh run: incidents=1 (mgro HDFC×upi_intent P1), executions=4, audit=5 after process exit |
| Demo hygiene | Dirty-DB guard | VERIFIED | refuses without PAYTWIN_DEMO_RESET=1 (unit-tested) |
| Tooling | loadtest CLI | VERIFIED | measured 1,030.9 ev/s · p95 31.3 ms (`make loadtest`) |
| Ops | Compose stack | VERIFIED | config valid; postgres+redis healthy; PG migration green |
| CI | Pipeline config | VERIFIED | ci.yml YAML-valid; bandit/pip-audit/secret-scan all clean locally (CI parity) |

## FIXES LANDED IN THIS AUDIT (each with a regression test)

1. **Demo persistence (was P0):** `run_flagship()` now commits — artifacts survived
   reconnect; previously incidents/audit rolled back on exit and "chain ok" was vacuous.
2. **Candidate-kind mismatch:** twin label `payment_links` → canonical
   `ActionKind.PAYMENT_LINK` before writing candidates (Payment Links no longer FAILED_FINAL).
3. **RaR interval math:** index-safe empirical p10/p90 + point∈interval invariant.
4. **Deterministic training anchor:** episodes anchored on newest payment, not wall clock.
5. **loadtest CLI:** missing `--url` + missing ASGI `base_url` fixed; real numbers captured.
6. **Makefile migrate:** CWD-relative alembic path fixed (works from repo root, sqlite+pg).
7. **Dirty-DB demo guard:** refuses without `PAYTWIN_DEMO_RESET=1`; adaptive scenario
   offset (⅓ of span) keeps the persistence window observable at any span.
8. **Detection false positives (P1s on healthy merchants):** admission is now dual-path —
   statistical persistence into the next window OR overwhelming single-window evidence
   (≥6 fails · drop≥8pts · RCA share≥75% · ≥2 dims) — plus MIN_N 25. Calibrated on
   clean-vs-planted sweeps (seeds 42/7 × scales); clean worlds open zero incidents.

## REGRESSION STATUS

- `pytest tests/ -q` → **182 passed** (main venv, ~351s): the previous 156 plus the
  26-test release-blocker suite — safety gates (chaos RBAC/prod, real-PSP refusal,
  prod-config validation), tenant isolation (shared payment refs, per-org inbox
  dedupe), pipeline correctness (late-event monotonicity, Razorpay lifecycle ids,
  DLQ redaction, ledger pseudonymization), policy enforcement (live-policy block +
  version attribution, rule type validation), audit/outbox semantics (fork guard,
  checkpoint tail detection, SSE post-commit), and rate limiting (429s + exemptions).
- `make verify` re-checks the demo DB audit chain incl. checkpoints (exit ≠ 0 on break).

## KNOWN LIMITATIONS (non-critical, documented)

- Neural backends (FT-Transformer/TabPFN/TimesFM/GNN) stubbed behind ModelBackend — CPU-only
  build machine; measured baselines shipped instead (docs/KNOWN_LIMITATIONS.md).
- Demo action admission is time-aware: IST quiet-hours can approval-gate the demo's best
  candidate (honestly reported in DEMO_RUN.md as approval-gated rather than executed).
- Razorpay connector sandbox-ready only (no production keys available anywhere in this build).
- Playwright browser suite skipped (disk headroom); journey covered by backend E2E +
  headless-Chrome DOM hydration checks.

## RE-RUN THE EVIDENCE

```bash
source .venv/bin/activate
python -m pytest tests/ -q                    # 182 passed
rm -f /tmp/final.db && PAYTWIN_DATABASE_URL=sqlite:////tmp/final.db \
  python -m paytwin_sim.demo                  # flagship E2E + DEMO_RUN.md
PAYTWIN_DEMO_RESET=1 make demo                # idempotent re-run path
make migrate && make loadtest && make verify  # migration + perf + audit chain
python scripts/evaluate.py                    # every EVALUATION.md number
cd infra && docker compose up -d postgres redis && cd .. && make migrate
```

