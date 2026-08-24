# Data Model (v1)

Conventions: `id` UUID or prefixed string (e.g. `INC-2481` human id + uuid pk).
Money: **BigInteger minor units (paise)**, columns suffixed `_paise`. Timestamps: UTC.
Tenant columns: `organization_id` everywhere; `merchant_id` on merchant-scoped tables.
All tables: `created_at`, updated `updated_at` where mutable.

## Tenancy & identity
- **organizations**(id, name, plan)
- **merchants**(id, organization_id→, name, short_code, color, industry, autonomy_mode int 0–4,
  stage int 1–5, sr_base_bp int (basis points), config JSON)
- **users**(id, organization_id→, email, name, role) — dev auth via API keys
- **api_keys**(id, organization_id→, user_id→, key_hash, scopes[], revoked_at)

## Integrations
- **integrations**(id, organization_id→, merchant_id→, provider, status, capabilities JSON,
  secret_ref, created_by) — secret stored HMAC-hashed reference; actual secret from env/vault.

## Event pipeline
- **event_inbox**(id, organization_id→, provider, external_event_id, signature_ok bool,
  status enum(received,processed,dead,duplicate), payload JSON, received_at, processed_at)
  UNIQUE(provider, external_event_id)  ← idempotency
- **canonical_events**(id, organization_id→, merchant_id→, type enum, occurred_at, ingested_at,
  provider, external_event_id UNIQUE, payment_ref, cohort JSON {issuer,method,psp,gateway},
  amount_paise, currency, payload JSON, late bool, schema_version) append-only
- **dead_letters**(id, organization_id→, reason, payload JSON, error, created_at)
- **outbox**(id, organization_id→, topic, payload JSON, created_at, dispatched_at NULL)
  ← transactional outbox; worker dispatches
- **payments**(id, organization_id→, merchant_id→, group_id (retry group), attempt_no int,
  order_ref, customer_ref (pseudonymous), amount_paise, currency, method, issuer, psp, gateway,
  status enum(created,authorized,failed,success,timeout,refunded), occurred_at,
  final_status_at NULL, recovered bool, failure_class, latency_ms, cohort JSON)
  INDEX(merchant_id, occurred_at) · INDEX(group_id)

## Intelligence
- **predictions**(id, organization_id→, merchant_id→, payment_id→, model_version,
  feature_version, p_success float, failure_class, uncertainty float, features_hash, created_at)
- **incidents**(id, organization_id→, merchant_id→, human_id UNIQUE (INC-####), sev, title,
  cohort JSON, state enum lifecycle, detected_at, resolved_at, baseline_sr_bp, current_sr_bp,
  rar_paise, rar_lo_paise, rar_hi_paise, affected_payments int, affected_customers int, confidence)
- **incident_evidence**(id, incident_id→, kind, ref, summary, weight, created_at)
- **root_cause_candidates**(id, incident_id→, edge JSON (issuer×method×psp), score, rank,
  counterfactual_share, created_at)
- **simulations**(id, organization_id→, merchant_id→, incident_id→, scenario, seed int,
  trials int, params JSON, result JSON (p50,lo,hi,lift,traj,cost), created_at)
  UNIQUE(incident_id, scenario, seed, params_hash) ← reproducibility
- **action_candidates**(id, incident_id→, kind, params JSON, ev_paise, p_succ_delta float,
  cost_paise, risk_paise, rank, twin_ref)
- **policies**(id, organization_id→, merchant_id→, human_id (RP-###), name, version int,
  status enum(draft,live,archived), rules JSON (typed predicates), created_by, created_at)
  UNIQUE(merchant_id, human_id, version)
- **policy_decisions**(id, organization_id→, merchant_id→, action_execution_id→, policy_id→,
  policy_version, decision enum(allow,require_approval,block), failed_rules JSON, context JSON,
  created_at)
- **action_executions**(id, organization_id→, merchant_id→, incident_id→, candidate_id→,
  human_id (ACT-####), kind, params JSON, idempotency_key UNIQUE, state enum(created,validated,
  approved,scheduled,executing,succeeded,failed_retryable,failed_final,rejected_by_policy),
  approved_by, executed_at, outcome JSON, connector, connector_ref)

## Measurement
- **experiments**(id, organization_id→, merchant_id→, incident_id→, name, status, started_at,
  stopped_at, config JSON)
- **experiment_assignments**(id, experiment_id→, payment_group_id, arm enum(control,treatment),
  propensity float, action_execution_id→, UNIQUE(experiment_id, payment_group_id))
- **outcomes**(id, organization_id→, experiment_id→, assignment_id→, payment_group_id,
  recovered bool, recovered_at, amount_paise, reward_paise, UNIQUE(assignment_id))

## Models
- **model_versions**(id, name, version, stage enum(trained,validated,shadow,canary,champion,retired),
  metrics JSON, params JSON, artifact_path, feature_version, trained_at, promoted_at, parent_version)

## Audit
- **audit_records**(seq BIGSERIAL PK, id UUID, organization_id→, actor, actor_role, action_type,
  object_type, object_id, incident_id, summary, details JSON, policy_version, prev_hash, hash)
  append-only; hash = sha256(prev_hash + canonical_json(details)); per-org chain verified by API.

## Simulator ground truth
- **sim_scenarios**(id, organization_id→, merchant_id→, kind, seed, start_at, end_at,
  cohort JSON, params JSON, true_excess_failures int, true_rar_paise, true_top_cause JSON)

## Index/tenant policy
Every merchant-scoped query filters `(organization_id, merchant_id)`; composite indexes on
(merchant_id, occurred_at) for events/payments; (incident_id) on children; unique constraints
as listed. SQLite test DBs use identical schema via portable types.
