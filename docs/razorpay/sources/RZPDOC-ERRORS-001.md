# About Errors

Source: https://razorpay.com/docs/errors/
Verified: 2026-08-26 · OFFICIAL_DOC (fetched from razorpay.com)

## Verified extract

Error object fields exactly: code, description, field, source, step, reason, metadata{payment_id, order_id}. Sample: {"error":{"code":"BAD_REQUEST_ERROR","description":"Authentication failed due to incorrect otp","field":null,"source":"customer","step":"payment_authentication","reason":"invalid_otp","metadata":{}}}. source = customer/Razorpay/Gateway/Bank/Network; step varies by method.
