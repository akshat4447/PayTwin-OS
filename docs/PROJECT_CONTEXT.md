# PayTwin OS — Project Context (Canonical Truth)

> This file is the single source of truth for what PayTwin IS and IS NOT.
> Re-read this before any task. If code contradicts this file, the code is wrong.

## Purpose
PayTwin OS is an **autonomous payment-resilience & revenue-intelligence platform**.
It watches payment traffic across merchants, understands each merchant's normal
behavior, detects degradation, diagnoses root causes, quantifies revenue at risk,
simulates candidate responses, selects the highest-value **safe** response through a
deterministic policy engine, executes it, and **measures the incremental revenue
impact** against a control baseline.

## Core product loop
```
OBSERVE → UNDERSTAND → PREDICT → DETECT → DIAGNOSE → SIMULATE
→ DECIDE → GOVERN → ACT → MEASURE → LEARN
```

## Primary users
1. **Payments/Ops on-call engineer** — war room, incidents, actions.
2. **Merchant finance/growth leader** — recovered revenue, protected GMV.
3. **Platform/Risk admin** — policies, autonomy modes, audit, model health.

## Terminology (fixed)
- **Organization** — customer of PayTwin; owns merchants. e.g. "Nova Commerce".
- **Merchant** — a payment surface (site/app) with its own baseline, calibration,
  cost model and policies. e.g. "Nova Grocery".
- **Cohort** — a slice: `issuer × method × PSP × gateway` (e.g. HDFC × UPI-intent × Cashfree).
- **Incident** — correlated anomalies with blast radius, RCA, revenue-at-risk, lifecycle.
- **Revenue at Risk (RaR)** — expected healthy GMV − incident-state GMV, with interval.
- **Incremental recovery** — P(success|action) − P(success|no action), measured vs control.
- **Autonomy modes** — 0 Observe, 1 Recommend, 2 Approve-first, 3 Bounded autopilot, 4 Autonomous.
- **Twin** — merchant-specific Monte-Carlo simulator of payment outcomes under actions.

## System boundaries
- Payment providers (Razorpay, Stripe, Cashfree, PayU, Adyen, internal rails) are
  **connectors only** (data in, execution out). ALL intelligence lives inside PayTwin.
- The LLM **never** authorizes or executes money-moving actions. It investigates,
  explains, and drafts typed action requests. The **policy engine** decides; the
  **executor** acts; the **audit chain** records everything.

## Non-goals (v1)
- Being a PSP/gateway. Processing payments. KYC. Ledgering settlement money.
- Real-time streaming at billions of events (designed-for, not benchmarked — see
  KNOWN_LIMITATIONS.md).

## Architectural principles
1. Provider independence via connector capability contracts.
2. Canonical event model; providers normalize at the edge, never in the core.
3. Idempotency + inbox + outbox + DLQ on every boundary.
4. Money is **integer minor units** (paise). Never floats.
5. Tenant isolation is enforced in the data layer and proven by tests.
6. Merchant intelligence = global priors + industry prior + merchant calibration.
7. Deterministic, versioned, replayable decisions. Every decision auditable end-to-end.
8. Honesty: only measured claims. Models are named what they are. Simulated data is
   labeled simulated.
9. Fail safe: LLM down → deterministic answers; deep model down → baseline;
   policy engine down → **no autonomous execution**.

## Expected behavior (provable)
- Duplicate/late/malformed/out-of-order webhooks never corrupt state.
- Same incident + same seed ⇒ identical twin simulation output.
- Unsafe action (retry-limit exhausted, DND window, amount cap) ⇒ blocked, audited.
- Duplicate execution request ⇒ exactly one business action.
- Cross-tenant access ⇒ denied (404/403), proven by automated tests.
