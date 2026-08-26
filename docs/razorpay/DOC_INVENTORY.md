# Razorpay Documentation Inventory

All entries FETCHED from razorpay.com on 2026-08-26 (OFFICIAL_DOC).
Verbatim extracts + sha256 hashes: docs/razorpay/sources/.

| source_id | Category | Title | Status |
|---|---|---|---|
| RZPDOC-WEBHOOKS-001 | webhooks | About Webhooks | CURRENT |
| RZPDOC-WEBHOOKS-002 | webhooks | Webhooks Best Practices | CURRENT |
| RZPDOC-REFUNDS-001 | refunds | Refunds API | CURRENT |
| RZPDOC-PAYMENTS-001 | payments | Payments API | CURRENT |
| RZPDOC-SUBSCRIPTIONS-001 | subscriptions | Subscription States | CURRENT |
| RZPDOC-ERRORS-001 | errors | About Errors | CURRENT |
| RZPDOC-ORDERS-001 | orders | Orders APIs | CURRENT |

## Classification
CORE: webhooks, payments, orders, refunds, errors, subscriptions.
EXTENDED (inventory-only): settlements, disputes, route, smart collect, payment links,
TPV, tokenisation, offers, optimizer, international, RazorpayX payouts.
OUT-OF-SCOPE: POS / Engage / Billing (no integration-correctness surface for PayTwin v1).
NEEDS_REVALIDATION: exact signature-algorithm page slug, order/payment state enum pages,
rate-limit error codes — family facts verified above; entity slugs pending re-fetch.
