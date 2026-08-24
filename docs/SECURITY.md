# Security

## AuthN / AuthZ
- Dev: API keys (`Authorization: Bearer ptw_…`), stored hashed (sha256), scoped to
  org + role; roles: org_admin, ops_oncall, finance_viewer, risk_admin.
- RBAC: read roles (finance_viewer) cannot execute/approve; only risk_admin promotes
  models / edits live policies. Enforced per-route via dependency; tested.
- Tenant isolation: every query filters organization_id (+merchant_id when scoped);
  cross-tenant object access returns 404; isolation tests prove it.

## Input & injection
- Webhooks: HMAC-SHA256 constant-time verify; bad signature ⇒ 401 + dead-letter.
- All payloads validated by Pydantic (types, lengths, enums). SQL only via SQLAlchemy
  bound params (no string SQL). UI renders through the prototype's `esc()` for
  interpolation; API returns JSON (no server-side HTML injection surface).
- Rate limiting: token-bucket per API key on mutating routes (Redis or in-memory fallback).

## Secrets
- `.env` only; `.env.example` documents every var; no secrets in code/repo (scan in CI).
- Connector secrets referenced by `secret_ref`, resolved from env at runtime; never logged,
  never sent to any LLM, never returned by API (masked).

## Autonomy safety
- Money-moving actions require: policy ALLOW (deterministic) + (autonomy mode gate)
  + idempotency key. Policy engine unavailable ⇒ executor refuses autonomous actions
  (fail-safe). LLM output is never a credential path.

## Audit
- Append-only `audit_records` with per-org SHA-256 hash chain; `GET /api/audit/verify`
  recomputes chain; exports include hashes.

## Checks (CI)
pip-audit (dep scan), bandit (static), grep-based secret scan, plus the authz test suite.

## Threat model (summary)
| Threat | Mitigation |
|---|---|
| Cross-tenant read/write | mandatory tenant filters + 404 + tests |
| Forged webhook | HMAC + replay-safe idempotency |
| Prompt injection via event fields | structured evidence, sanitized text, no instruction-following from tool output (evaluated) |
| Rogue autonomous action | policy engine + autonomy ladder + idempotency + audit chain |
| Secret leak via LLM | credentials never in prompts; secret_ref indirection |
