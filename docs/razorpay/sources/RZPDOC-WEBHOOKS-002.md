# Webhooks Best Practices

Source: https://razorpay.com/docs/webhooks/best-practices/
Verified: 2026-08-26 · OFFICIAL_DOC (fetched from razorpay.com)

## Verified extract

Delivery: 'Every event that receives a non-2xx response is considered an event delivery failure.' 'If there is a delivery failure, we retry the delivery in exponential backoff policy for 24 hours after event creation timestamp.' After 24h of failures the webhook is disabled.
Duplicates: 'your endpoint might receive the same webhook event multiple times. This is an expected behaviour'; 'Razorpay follows at-least-once delivery semantics'; 'Check the value of the x-razorpay-event-id in the webhook request header. The value for this header is unique per event.'
Timeout: 'fails to respond in 5 seconds... the session is marked timeout... sent again.'
Ordering: 'you may not always receive the webhooks in order.'
Security: verify webhook signatures; TLS 1.2+; whitelist webhook IPs.
