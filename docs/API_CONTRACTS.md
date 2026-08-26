# API Contracts (v1)

Base: `http://localhost:8000`. Auth: `Authorization: Bearer <api_key>` (dev keys seeded).
Errors: `{"error": {"code", "message", "details"}}`. All list endpoints accept
`?scope=org|<merchant_id>` and are tenant-filtered. OpenAPI at `/api/openapi.json`
(swagger UI at `/api/docs`). Rate limit: `/api/*` allows `PAYTWIN_RATE_LIMIT_PER_MIN`
(default 240) requests/min per credential — excess ⇒ 429 `rate_limited` + `Retry-After`;
`/webhooks/*` and `/api/health` are exempt.

## System
- `GET /api/health` → {status, db, version, env} (no auth required)
- `GET /api/meta` → {org, role, merchants[{id,name,short,color,mode,stage,sr_base,gmv,protected}], feature_flags{llm,env}}
- `GET /metrics` → Prometheus text format
- `GET /api/stream?scope=` → SSE: `heartbeat`, `incident`, `policy_decision`, `action`, `metric` events

## Dashboard
- `GET /api/overview?scope=` → {metrics{gmv_mtd_paise, sr_bp, rar_paise, protected_paise,
  active_incidents, retries_avoided}, pulse[int16], series{labels,values}, incidents[teaser],
  stream_rows[], notifs[], lvl{network,merchant,payment}}
- `GET /api/funnel?scope=` → checkout funnel stages
- `GET /api/healthmap?scope=` → per-provider/issuer/psp/method health rows

## Merchants
- `GET /api/merchants` · `GET /api/merchants/{id}` (stages, mode, sr, gmv, protected)

## Incidents
- `GET /api/incidents?scope=&state=` → list w/ risk, cohort, state
- `GET /api/incidents/{human_id}` → {header, timeline[], causes[[edge,score,flag]],
  candidates[{id,kind,label,detail,ev_paise,win_prob,policy}], evidence[], cohorts[], rar{}}
- `POST /api/incidents/{human_id}/execute` {candidate_id} → policy decision + execution
  (202; returns {decision, execution_id, state, failed_rules})
- `POST /api/incidents/{human_id}/resolve`

## Twin
- `POST /api/twin/simulate` {scope, scenario, alloc_pct, duration_min, seed?} →
  {p50_paise, lo_paise, hi_paise, lift_pct, traj[], trials, seed, policy_compat, per_scenario[]}
  Same inputs + same seed ⇒ byte-identical result (tested).

## Policies
- `GET /api/policies?scope=` · `POST /api/policies` (typed rules; validated)
- `PATCH /api/policies/{human_id}` {rules, status} → new version
- `GET /api/policies/blocked?scope=` → blocked-action log (real rejections)
- `POST /api/policies/preview` {merchant_id, draft_rules} → historical replay projection

## Commander
- `POST /api/commander/chat` {scope, incident?, message} → {reply_md, citations[],
  tools[{name,latency_ms,args}], mode: hosted|fallback, action_request?}
- Action-like intents return typed `action_request` + policy verdict; never execute directly.

## Experiments & reports
- `GET /api/experiments?scope=` · `GET /api/experiments/{id}` → arms, lift, CI, incremental ₹
- `GET /api/reports/recovery-batch?scope=&hours=` → text/markdown batch report (download)

## Models
- `GET /api/models` → registry rows (name, version, stage, metrics, trained_at, drift)
- `POST /api/models/{id}/promote` {stage} (risk_admin only)

## Audit
- `GET /api/audit?scope=&actor=&type=` · `GET /api/audit/verify` → chain integrity
- `GET /api/audit/export?fmt=jsonl|dossier` → file download

## Chaos (demo control)
- `POST /api/chaos/{scenario}` {scope, duration_min?} — scenario ∈ psp_degradation,
  issuer_outage, gateway_latency, checkout_regression, webhook_lag, auth_failures, rate_limit.
  Admin roles only; **disabled in production (403)**.
- `POST /webhooks/{provider}` — connector ingress (HMAC `X-PayTwin-Signature: sha256=...`;
  bad signature ⇒ 401 + dead-letter; malformed ⇒ 422 + PII-redacted DLQ)

## Reliability Lab
- `GET /api/reliability/overview` · `GET /api/reliability/suites` · `POST /api/reliability/run`
- `GET /api/reliability/runs` · `GET /api/reliability/runs/{id}` · `GET /api/reliability/findings`
- `GET /api/reliability/release-gate` → READY/WARNING/BLOCKED · `POST /api/reliability/webhook-lab/{fault}`
- Deterministic integration-assurance runs traced to hashed Razorpay requirements
  (docs/razorpay/sources); critical findings always block the gate.

## Frontend binding rule
The UI keeps its exact look; every screen's data comes from the endpoints above. If the API
is unreachable the UI falls back to its local deterministic engine and shows the DEMO badge.
