# About Webhooks

Source: https://razorpay.com/docs/webhooks/
Verified: 2026-08-26 · OFFICIAL_DOC (fetched from razorpay.com)

## Verified extract

Webhooks are delivered asynchronously in near real-time. For critical user-facing flows that need instant confirmation, supplement webhooks with API verification.
Late authorisation is a primary use case: 'Sometimes, the communication between the bank and Razorpay or between you and Razorpay may not occur... leading to a payment being marked as Failed on the Dashboard but changed to Authorized at a later time.' Use payment.authorized notifications to decide whether to capture.
Webhook URLs must use ports 80 or 443 only. callback_url is a checkout parameter, not a webhook.
