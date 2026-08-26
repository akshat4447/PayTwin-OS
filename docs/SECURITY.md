# Security

## AuthN / AuthZ
- Dev: API keys (`Authorization: Bearer ptw_…`), stored hashed (sha256), scoped to
  org + role; roles: org_admin, ops_oncall, finance_viewer, risk_admin.
- RBAC: read roles (finance_viewer) cannot execute/approve; only risk_admin promotes
  models / edits live policies. Enforced per-route via dependency; tested.
- Tenant isolation: every query filters organization_id (+merchant_id when scoped);
  cross-tenant object access returns 404; isolation tests prove it.
- Defense in depth at the schema level: payments unique per
  (merchant, provider, payment_ref) and inbox/canonical idempotency scoped per
  (provider, organization, external id) via migration `c7d2e8a41b90`, plus FKs across
  core relations; optional PostgreSQL row-level security companion policies ship in
  `infra/rls.sql` so a future unfiltered query still cannot read cross-tenant rows.

## Deployment gates
- Production startup validation fails fast: rejects sqlite datastores, dev-default
  secrets / short secret_key, and `allow_real_execution=true` in production (tested).
- Chaos injection routes are disabled in production (403); real-PSP execution is
  off by default everywhere — sandbox/demo-only until a provider is certified.

## Input & injection
- Webhooks: HMAC-SHA256 constant-time verify; bad signature ⇒ 401 + dead-letter.
- All payloads validated by Pydantic (types, lengths, enums). SQL only via SQLAlchemy
  bound params (no string SQL). UI renders through the prototype's `esc()` for
  interpolation; API returns JSON (no server-side HTML injection surface).
- Rate limiting: sliding-window limiter on every `/api/*` route — identity is the
  bearer credential when present, else the client host; default 240 req/min
  (`PAYTWIN_RATE_LIMIT_PER_MIN`). Webhook ingress (`/webhooks/*` — HMAC machine
  traffic, bursty by design) and `/api/health` are exempt. Excess requests get
  `429 {"error":{"code":"rate_limited"}}` + `Retry-After`. Pure-ASGI, so SSE
  streams pass through untouched. Tested (`TestRateLimiting`).

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
  recomputes chain; exports include hashes. A per-org `audit_heads` checkpoint
  (seq/hash/count) plus UNIQUE(organization_id, prev_hash) fork guard make tail
  deletion and chain forks detectable (`make verify`, tested).

## Checks (CI)
pip-audit (dep scan), bandit (static), grep-based secret scan, plus the authz test suite.

## Threat model (summary)
| Threat | Mitigation |
|---|---|
| Cross-tenant read/write | mandatory tenant filters + 404 + tests |
| Cross-tenant corruption via reused provider refs | tenant-scoped unique constraints + FKs + RLS companion (`infra/rls.sql`) |
| Forged webhook | HMAC + replay-safe idempotency |
| Prompt injection via event fields | structured evidence, sanitized text, no instruction-following from tool output (evaluated) |
| Rogue autonomous action | policy engine + autonomy ladder + idempotency + audit chain |
| Secret leak via LLM | credentials never in prompts; secret_ref indirection |
