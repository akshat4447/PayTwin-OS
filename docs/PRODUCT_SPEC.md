# Product Specification

## One-line pitch
PayTwin turns payment failures into measured recovered revenue: it detects degradation,
diagnoses why, quantifies the money at risk, simulates responses, executes the best safe
one through deterministic guardrails, and proves the incremental impact.

## The loop, mapped to screens
| Loop stage | Screen(s) |
|---|---|
| OBSERVE | Command Center (GMV, SR, RaR, protected, incidents), Checkout Funnel, Payment Health |
| UNDERSTAND | Incident War Room (timeline, evidence, cohorts) |
| PREDICT | Model Health (live metrics, calibration, drift) |
| DETECT/DIAGNOSE | War Room RCA (graph attribution, confidence, counterfactual) |
| SIMULATE | Twin Lab (seeded Monte-Carlo, scenario library, distributions) |
| DECIDE | War Room action candidates + EV, Benchmark |
| GOVERN | Policies (typed versioned rules, blocked-actions log, compliance predicates) |
| ACT | Executor via connectors (idempotent, audited) |
| MEASURE | Experiments & Recovery (control vs treatment, lift CI, batch report) |
| LEARN | Model lifecycle (shadow→canary→champion), merchant calibration |
| EXPLAIN | AI Commander (evidence-grounded chat w/ citation chips, refusals) |

## Users & tenancy
- Organization (Nova Commerce) → 4 merchants: Grocery (Mode 3 bounded autopilot),
  Fashion (Mode 2 approve-first), Travel (Mode 3), Subscriptions (Mode 1 recommend-only).
- Roles: org_admin, ops_oncall, finance_viewer, risk_admin.

## Flagship demo (§36, deterministic, seed 42)
Merchant Nova Grocery, baseline UPI SR ≈ 95%. Inject `issuer_outage` on
**HDFC × UPI-intent × Cashfree** for 25 minutes. System must: detect ≤ 3 windows,
rank HDFC×UPI-collect edge as Top-1 cause, estimate RaR with interval, simulate
{do_nothing, bounded reroute, retry burst, payment links, wait}, select argmax-EV
subject to policies, execute via simulator connector with rollback guardrail, measure
treatment vs control, and print incremental revenue protected + futile retries prevented
+ policy violations (must be 0).

## Graceful-failure demo (§37)
When retry-limit is exhausted, the commander's suggested retry is **blocked** by policy:
UI shows ACTION BLOCKED + reason + "no customer/payment action was executed" + next step.

## Functional requirements (v1)
FR-1 webhook ingestion (HMAC-verified) for ≥2 connector dialects + simulator
FR-2 canonical event store, idempotent, replayable, late/dup/out-of-order safe
FR-3 payment state machine incl. retry groups and eventual-success labels
FR-4 point-in-time feature engine (no leakage, tested)
FR-5 success-probability models (LR baseline, HistGB challenger) w/ calibration + registry
FR-6 merchant-specific anomaly detection (EWMA/CUSUM/robust-z ensemble)
FR-7 graph RCA with counterfactual mask; Top-1/Top-3 scored vs ground truth
FR-8 revenue-at-risk with 80% interval
FR-9 digital twin Monte-Carlo, 7 scenarios, seeded & reproducible
FR-10 EV optimizer over action candidates incl. NO_ACTION
FR-11 deterministic policy engine (typed predicates, versions, autonomy modes)
FR-12 idempotent action executor w/ state machine + connector capability checks
FR-13 experiments: assignment, outcomes, lift + bootstrap CI
FR-14 LinUCB offline policy eval vs fixed baseline
FR-15 AI commander: grounded answers w/ citations, tool traces, refusals, fallback
FR-16 audit: append-only hash chain, export JSONL + dossier
FR-17 frontend = prototype UI, live-bound, demo fallback, exports work
FR-18 observability: JSON logs, /metrics, health, SSE stream
