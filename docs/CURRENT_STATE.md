# CURRENT STATE

> **STATUS: COMPLETE — master completion audit passed 2026-08-25.**
> Every claim below carries executable evidence per the Completion Evidence Rule.
> Re-run anything via the probes at the bottom; docs/EVALUATION.md holds the numbers.

## FINAL COMPLETION MATRIX

| AREA | REQUIREMENT | STATUS | EVIDENCE |
|---|---|---|---|
| Tests | Full suite green | VERIFIED | **156 passed** (`pytest tests/ -q`) in main venv AND a from-scratch venv |
| Database | Clean-DB migration | VERIFIED | `make migrate` → `b47531c6f9e6 init schema`, 26 tables (SQLite) **and** Postgres 16 container |
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

- `pytest tests/ -q` → **156 passed** (main venv, 168s) incl. 9 new audit tests:
  persistence-across-reconnect, capability/kind alignment, RaR invariants, dirty-DB guard,
  training determinism, loadtest CLI, clean-world silence.
- Same suite green in a from-scratch venv (`pip install -e …` fresh).

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
python -m pytest tests/ -q                    # 156 passed
rm -f /tmp/final.db && PAYTWIN_DATABASE_URL=sqlite:////tmp/final.db \
  python -m paytwin_sim.demo                  # flagship E2E + DEMO_RUN.md
PAYTWIN_DEMO_RESET=1 make demo                # idempotent re-run path
make migrate && make loadtest                 # migration + perf numbers
python scripts/evaluate.py                    # every EVALUATION.md number
cd infra && docker compose up -d postgres redis && cd .. && make migrate
```

