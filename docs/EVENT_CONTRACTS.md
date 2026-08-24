# Event Contracts

## Raw webhook (provider dialect)
```
POST /webhooks/{provider}
X-PayTwin-Signature: sha256=HMAC_SHA256(secret, body)
{ "event": "payment.failed", "id": "evt_...", "created_at": 1730000000, "data": {...} }
```
Providers: `simulator`, `mockprovider`, `razorpay` (dialect map in connectors).
Verification failures → 401, recorded in `event_inbox(status=dead)` + `dead_letters`.

## Canonical event (internal, versioned)
```json
{
  "schema_version": 1,
  "id": "uuid",
  "type": "payment.created|payment.authorized|payment.failed|payment.success|
           payment.timeout|refund.created|connector.health",
  "organization_id": "org_uuid",
  "merchant_id": "mer_uuid",
  "provider": "simulator",
  "external_event_id": "evt_...",           // unique per provider — idempotency
  "occurred_at": "2026-08-25T04:41:00Z",     // provider clock
  "ingested_at": "2026-08-25T04:41:02Z",
  "payment_ref": "pay_...",
  "amount_paise": 129900,
  "currency": "INR",
  "cohort": {"issuer": "HDFC", "method": "upi_intent", "psp": "cashfree", "gateway": "gw1"},
  "payload": { },                            // provider-normalized extras
  "late": false
}
```
Rules: canonicalization happens once at the edge (connector); core never sees provider
dialects. `late = occurred_at < last_seen(occurred_at) - 60s`. Out-of-order events update
payments only forward by `occurred_at` guard; late events are still counted in aggregates
with their original timestamp (point-in-time correctness).

## Payment state machine
```
created → authorized → success
created → failed                     (failure_class: issuer_decline|timeout|auth|rate_limit|
created → timeout → success(late)     psp_error|checkout_error|insufficient_funds)
```
Retry group: `group_id` links attempts; `recovered = any(success within window)`.
Labels: failure (attempt), eventual success (group ≤10m / ≤24h), recovered (post-action).

## Internal topics (outbox)
`payment.updated` · `incident.opened` · `incident.state_changed` · `policy.decided` ·
`action.requested` · `action.executed` · `prediction.made` · `audit.appended` ·
`metric.snapshot` — consumed by SSE fan-out and the worker loops.

## Delivery guarantees
- At-least-once into inbox (unique key makes it effectively-once for processing).
- Outbox dispatched with `dispatched_at` marker; retries with backoff; poison → dead_letters.
- Replay: admin re-injects inbox rows (idempotent by external_event_id).
