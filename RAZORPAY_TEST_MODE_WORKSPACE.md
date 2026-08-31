# PayTwin × Razorpay — Test Mode Workspace

> **SANDBOX ONLY.** Synthetic Razorpay-shaped, HMAC-signed events run through PayTwin's real ingestion and payment-state paths. No network call or money movement occurs.

## Razorpay Test Mode verification: READY

- **PASS** — Razorpay duplicate delivery is idempotent in the real ingress path
- **PASS** — Forged Razorpay webhook is rejected by the real ingress path
- **PASS** — Captured-before-authorized converges in the real payment state machine
- **PASS** — Late authorization after failure updates the real payment state
- **PASS** — Partial refund uses Razorpay's refund amount and preserves captured payment
- **PASS** — Failed refund never changes the captured payment aggregate

## Capability tour

1. **Observe and detect:** seeded payment traffic includes a controlled issuer/UPI outage.
2. **Diagnose and quantify:** PayTwin opens an incident, ranks the cohort root cause, and reports Revenue at Risk with an interval.
3. **Rehearse and govern:** the Digital Twin ranks safe responses; the versioned policy engine blocks or requires approval before the simulator executor acts.
4. **Measure and explain:** control/treatment outcomes, hash-chained audit, and the evidence-grounded Commander remain available in the UI.
5. **Assure Razorpay Test Mode:** duplicate, forged-signature, out-of-order, late-authorization, partial-refund, and failed-refund scenarios exercise the actual webhook pipeline.

Open the UI after starting the API with the development risk-admin key printed during workspace setup.
