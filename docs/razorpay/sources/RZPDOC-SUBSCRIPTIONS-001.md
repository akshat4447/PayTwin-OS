# Subscription States

Source: https://razorpay.com/docs/payments/subscriptions/states/
Verified: 2026-08-26 · OFFICIAL_DOC (fetched from razorpay.com)

## Verified extract

States: created, authenticated, active, pending, halted, paused, cancelled, expired, completed.
pending: auto-charge unsuccessful, retries continue. halted: 'all retries are exhausted'; invoices continue, no auto-charge; halted->active does NOT re-attempt previous charges. Pausing an authenticated subscription cancels it. Expired when start_at passes unauthenticated. Methods: Cards, UPI AutoPay, Emandate; tokenised per RBI.
