-- PayTwin OS — PostgreSQL Row-Level Security (defense in depth, ADR-010).
-- The application already tenant-filters every query by organization_id; these
-- policies make cross-tenant reads impossible even if a future query forgets.
-- Apply as a superuser: psql "$PAYTWIN_DATABASE_URL" -f infra/rls.sql
-- Requires the app to SET app.current_org per connection/transaction, e.g.:
--   SET app.current_org = 'org1';

DO $$
DECLARE t text;
BEGIN
  FOREACH t IN ARRAY ARRAY[
    'merchants', 'users', 'api_keys', 'event_inbox', 'canonical_events',
    'dead_letters', 'outbox', 'payments', 'predictions', 'incidents',
    'simulations', 'action_candidates', 'policies', 'policy_decisions',
    'action_executions', 'integrations', 'experiments', 'experiment_assignments',
    'outcomes', 'audit_records', 'audit_heads', 'sim_scenarios']
  LOOP
    EXECUTE format('ALTER TABLE %I ENABLE ROW LEVEL SECURITY', t);
    EXECUTE format('DROP POLICY IF EXISTS tenant_isolation ON %I', t);
    EXECUTE format($f$
      CREATE POLICY tenant_isolation ON %I
      USING (organization_id = current_setting('app.current_org', true))
      $f$, t);
  END LOOP;
END $$;

-- Shared platform tables intentionally WITHOUT tenant RLS:
--   organizations (identity root), model_versions (global registry),
--   incident_evidence / root_cause_candidates (org-scoped via incident joins).
