# Razorpay Integration Boundary

PayTwin's Buildathon implementation is a credential-free, local,
Razorpay-shaped test harness. This distinction is intentional and visible in
the UI and reports.

| Verified locally | Not claimed |
|---|---|
| Raw-body HMAC verification | A connected Razorpay account |
| Durable inbox and event idempotency | Razorpay Test Mode API calls |
| Out-of-order and duplicate delivery handling | Production payment execution |
| Server-side Checkout proof | Public webhook delivery from Razorpay |
| One-fulfilment invariant | Settlement reconciliation |
| Refund accounting controls | Live money movement |

The local harness follows documented lifecycle concerns such as signature
verification, duplicate delivery, event ordering, and payment-state handling.
It exists to make safety controls reproducible without exposing credentials or
claiming an account-backed integration.

To connect a real Razorpay Test Mode account after the Buildathon demo, provide
server-side test credentials, configure a secure public webhook endpoint,
validate the webhook signature against the raw body, retain idempotency by
event ID, and run the same sandbox validation suite before enabling any
provider-facing action.
