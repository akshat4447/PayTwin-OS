# PayTwin OS

Autonomous payment-resilience & revenue-intelligence platform: watches payment
traffic across merchants, detects degradation, diagnoses root causes, quantifies
revenue-at-risk, simulates candidate responses in a seeded digital twin, and lets a
**deterministic policy engine** decide what an autopilot may execute — with every
action idempotent, audited, and measured against a control baseline.

> Prototype UI first (ADR-002): `apps/web/index.html` is the approved single-page
> prototype bound to this API. Without an API key it runs its local deterministic
> engine and badges **DEMO**; with one it goes **LIVE**.

## Fresh-machine quickstart

```bash
# 0) system: python 3.12 + (optional for dev stack) docker
git clone <this repo> && cd PayTwin_OS

# 1) virtualenv + editable monorepo install
python3 -m venv .venv && source .venv/bin/activate
pip install --upgrade pip
pip install -e packages/contracts -e services/sim -e services/ml -e services/api
pip install pytest httpx

# 2) run the test suite (sqlite; no services needed)
make test                       # expect: NNN passed

# 3) full flagship demo — seeds world, ingests 3h of traffic with an injected
#    HDFC×UPI outage, detects, decides, executes, measures, writes DEMO_RUN.md
PAYTWIN_DATABASE_URL=sqlite:///./data/demo.db make demo

# 4) serve API + the UI (LIVE mode)
PAYTWIN_DATABASE_URL=sqlite:///./data/demo.db make api
open "http://localhost:8000/?key=<risk_admin key printed by the demo>"
```

## Dev stack (postgres + redis)

```bash
make dev        # compose up postgres(:5433)/redis(:6380), migrate, api :8000
make worker     # detection sweep + policy-gated autopilot + outbox dispatch (30s)
```

## Layout

| Path | What |
|---|---|
| `packages/contracts` | canonical events/enums/money (provider-neutral core) |
| `services/sim` | seeded payment generator, scenario library, demo builder |
| `services/ml` | features, detectors, RCA, RaR, twin, training, causal |
| `services/api` | FastAPI app, connectors, ingest/state machine, policy engine, executor, audit, commander, routers, worker |
| `apps/web` | the prototype UI bound to the live API |
| `docs/` | architecture/data-model/API contracts/decisions/evaluation |
| `project-memory/` | task graph + session memory |

## Safety model (short version)

- Money = integer paise everywhere.
- The LLM/commander is **read-only**; it can draft a typed action request and ask the
  policy engine for a verdict, but never executes anything.
- The policy engine (typed hard guardrails + autonomy ladder 0–4) is the only
  authority that allows money-moving actions; the executor is idempotent and audited;
  every decision lands on an append-only hash-chained audit log (`GET /api/audit/verify`).
- All claims about recovery are measured against experiments/control baselines or the
  simulator's counterfactual ground truth.

## Configuration

Copy `.env.example` → `.env`. Key variables: `PAYTWIN_DATABASE_URL`,
`PAYTWIN_REDIS_URL`, `PAYTWIN_SECRET_KEY`, `PAYTWIN_WEBHOOK_SECRET_{SIMULATOR,
MOCKPROVIDER,RAZORPAY}`, `PAYTWIN_LLM_PROVIDER=none|openai|anthropic`,
`PAYTWIN_WORKER_INTERVAL`.

## Reliability Lab (native module)

Prove payment integrations behave correctly under real lifecycle failures before
production — duplicates, forged callbacks, out-of-order events, refund overruns,
agent-mandate replays — traced to verified Razorpay requirements. Open the
**Reliability Lab** page in the sidebar, then press **Run verification**.

## Operations

- `make migrate` · `make seed` · `make demo` · `make verify` (audit chain)
- `make demo` refuses a dirty DB — re-run with `PAYTWIN_DEMO_RESET=1` to wipe & rebuild,
  or point `PAYTWIN_DATABASE_URL` at a fresh file.
- `python scripts/evaluate.py` re-measures every number in docs/EVALUATION.md.
- Docker: `cd infra && docker compose up --build` (api :8000, worker, postgres :5433, redis :6380)
- CI: `.github/workflows/ci.yml` — pytest + bandit + pip-audit + naive secret scan.
