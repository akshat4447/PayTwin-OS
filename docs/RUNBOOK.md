# Runbook

## Start / stop
```bash
make dev        # compose up + api + worker (logs: make logs)
make stop       # compose down (data volume persists)
make reset-db   # drop volume, migrate, seed
```

## Health
- `curl :8000/api/health` → check db/redis/worker_lag.
- `GET /metrics` → `paytwin_worker_lag_seconds`, `paytwin_events_total`,
  `paytwin_policy_blocks_total`, `paytwin_action_failures_total`.

## Common operations
| Symptom | Check | Action |
|---|---|---|
| UI blank / DEMO badge | API up? `curl :8000/api/meta` | `make api`; check browser console |
| No incidents appearing | worker running? lag? | `make worker`; inspect `outbox` undispatched |
| Webhook 401 | signature secret mismatch | compare `PAYTWIN_WEBHOOK_SECRET_SIMULATOR` on emitter |
| Events stuck received | canonicalizer error | `SELECT reason FROM dead_letters`; fix, then replay via admin endpoint |
| Twin returns different numbers | seed/params differ | same seed+params ⇒ identical (else bug: file issue) |
| Action stuck executing | connector dispatch failed | `action_executions.state`, outbox retry; executor is retry-safe (idempotency key) |
| Audit chain invalid | tampering or bug | `GET /api/audit/verify` returns first bad seq; restore from export |

## Failure drills (all safe by design)
- Kill postgres → API health degrades, UI shows DEMO fallback; restart → recovers.
- Kill worker → outbox grows, `worker_lag` climbs; restart drains.
- `POST /api/chaos/…` → controlled degradation for demos; ground truth recorded.

## Data repairs
- Replay events: `POST /api/admin/replay {inbox_ids[]}` (org_admin) — idempotent.
- Promote model: `POST /api/models/{id}/promote {stage}` (risk_admin) — audited.
- Rotate webhook secret: update env + integrations row; old signatures rejected (401).
