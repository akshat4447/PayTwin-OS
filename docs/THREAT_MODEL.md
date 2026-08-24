# Threat Model (abridged; full controls in SECURITY.md)

Assets: payment event data, merchant configs, policy decisions, action authority, audit chain.
Trust boundaries: provider webhooks → API; user → API; LLM → core; connector → provider.

| ID | Threat | Vector | Impact | Controls | Residual |
|---|---|---|---|---|---|
| T1 | Cross-tenant data access | forged/ guessed ids | data leak | tenant filter everywhere, 404, isolation tests, rate limit | low |
| T2 | Forged webhook | replay/unsigned | false state | HMAC constant-time, unique ext id, DLQ | low |
| T3 | Unsafe autonomous action | buggy model/agent | money loss | deterministic policy engine, autonomy ladder, idempotency, audit | low |
| T4 | Prompt injection | hostile text in events/fields | rogue recommendation | structured evidence, no instruction role for tool output, refusal eval set | med (defense-in-depth) |
| T5 | Secret exfiltration via LLM/logs | prompt/log crafting | credential leak | secrets never in prompts/logs, secret_ref indirection | low |
| T6 | Audit tampering | DB write access | cover-up | hash chain + verify endpoint + exports | low |
| T7 | DoS on ingest | webhook flood | availability | rate limit, DLQ, worker backpressure | med |
| T8 | Model poisoning via replay | adversarial events | skewed decisions | simulator-only training in v1; provenance on training data | med |
