CREATE EXTENSION IF NOT EXISTS vector;

CREATE TABLE tenants (
  id text PRIMARY KEY, name text NOT NULL, enabled boolean NOT NULL DEFAULT true
);
CREATE TABLE users (
  id text PRIMARY KEY, tenant_id text NOT NULL REFERENCES tenants(id),
  email text NOT NULL UNIQUE, name text NOT NULL, password_hash text NOT NULL,
  role text NOT NULL CHECK(role IN ('tenant_admin','analyst','reviewer')),
  enabled boolean NOT NULL DEFAULT true, UNIQUE(tenant_id,id)
);
CREATE TABLE sessions (
  token_hash text PRIMARY KEY, user_id text NOT NULL REFERENCES users(id),
  csrf_token text NOT NULL, expires_at timestamptz NOT NULL, created_at timestamptz NOT NULL DEFAULT now()
);
CREATE TABLE login_limits (
  key_hash text PRIMARY KEY, failures integer NOT NULL, window_start timestamptz NOT NULL
);
CREATE TABLE operational_control (
  id integer PRIMARY KEY CHECK(id=1), maintenance boolean NOT NULL DEFAULT false,
  updated_at timestamptz NOT NULL DEFAULT now(), circuit_failures integer NOT NULL DEFAULT 0,
  circuit_until timestamptz, probe_until timestamptz
);
INSERT INTO operational_control(id) VALUES(1);

CREATE TABLE tenant_policy (
  tenant_id text PRIMARY KEY REFERENCES tenants(id), revision bigint NOT NULL DEFAULT 1,
  storage_reserved bigint NOT NULL DEFAULT 0 CHECK(storage_reserved>=0),
  token_reserved bigint NOT NULL DEFAULT 0 CHECK(token_reserved>=0),
  token_reported bigint NOT NULL DEFAULT 0 CHECK(token_reported>=0)
);
CREATE TABLE collections (
  tenant_id text NOT NULL REFERENCES tenants(id), id text NOT NULL,
  name text NOT NULL, description text NOT NULL DEFAULT '', active_snapshot_id text,
  tombstoned_at timestamptz, PRIMARY KEY(tenant_id,id)
);
CREATE TABLE collection_grants (
  tenant_id text NOT NULL, collection_id text NOT NULL, user_id text NOT NULL,
  PRIMARY KEY(tenant_id,collection_id,user_id),
  FOREIGN KEY(tenant_id,collection_id) REFERENCES collections(tenant_id,id),
  FOREIGN KEY(tenant_id,user_id) REFERENCES users(tenant_id,id)
);
CREATE TABLE import_batches (
  tenant_id text NOT NULL, id text NOT NULL, collection_id text NOT NULL,
  created_by text NOT NULL, title text NOT NULL, manifest jsonb NOT NULL,
  state text NOT NULL CHECK(state IN('receiving','sealed','processing','ready','rejected','failed','cancelled')),
  error jsonb, snapshot_id text, created_at timestamptz NOT NULL DEFAULT now(),
  PRIMARY KEY(tenant_id,id), FOREIGN KEY(tenant_id,collection_id) REFERENCES collections(tenant_id,id),
  FOREIGN KEY(tenant_id,created_by) REFERENCES users(tenant_id,id)
);
CREATE TABLE import_entries (
  tenant_id text NOT NULL, batch_id text NOT NULL, id text NOT NULL,
  filename text NOT NULL, kind text NOT NULL, media_type text NOT NULL, byte_size bigint NOT NULL CHECK(byte_size>=0),
  sha256 text NOT NULL, metadata jsonb NOT NULL DEFAULT '{}',
  state text NOT NULL CHECK(state IN('pending','uploading','uploaded','valid','rejected','requires_ocr')),
  upload_token text, upload_until timestamptz, object_key text, error jsonb,
  PRIMARY KEY(tenant_id,batch_id,id), FOREIGN KEY(tenant_id,batch_id) REFERENCES import_batches(tenant_id,id)
);
CREATE TABLE evidence_snapshots (
  tenant_id text NOT NULL, id text NOT NULL, collection_id text NOT NULL,
  coverage jsonb NOT NULL, published_at timestamptz NOT NULL DEFAULT now(),
  PRIMARY KEY(tenant_id,id), FOREIGN KEY(tenant_id,collection_id) REFERENCES collections(tenant_id,id)
);
CREATE TABLE evidence (
  tenant_id text NOT NULL, id text NOT NULL, collection_id text NOT NULL,
  kind text NOT NULL CHECK(kind IN('document_span','source_event','delivery_attempt','order_snapshot','reconciliation_result')),
  title text NOT NULL, version text NOT NULL, sha256 text NOT NULL, source_system text NOT NULL,
  temporal_role text NOT NULL, valid_from timestamptz, valid_until timestamptz,
  canonical_text text NOT NULL, locator jsonb NOT NULL DEFAULT '{}', record jsonb NOT NULL DEFAULT '{}',
  original_key text, media_type text, byte_size bigint, tombstoned_at timestamptz,
  search_vector tsvector GENERATED ALWAYS AS (to_tsvector('portuguese',canonical_text)) STORED,
  embedding vector(384), embedding_revision text,
  PRIMARY KEY(tenant_id,id), FOREIGN KEY(tenant_id,collection_id) REFERENCES collections(tenant_id,id)
);
CREATE INDEX evidence_fts ON evidence USING gin(search_vector);
CREATE INDEX evidence_collection ON evidence(tenant_id,collection_id,kind);
CREATE TABLE snapshot_members (
  tenant_id text NOT NULL, snapshot_id text NOT NULL, evidence_id text NOT NULL,
  PRIMARY KEY(tenant_id,snapshot_id,evidence_id),
  FOREIGN KEY(tenant_id,snapshot_id) REFERENCES evidence_snapshots(tenant_id,id),
  FOREIGN KEY(tenant_id,evidence_id) REFERENCES evidence(tenant_id,id)
);
CREATE TABLE incidents (
  tenant_id text NOT NULL, id text NOT NULL, collection_id text NOT NULL, title text NOT NULL,
  description text NOT NULL DEFAULT '', status text NOT NULL DEFAULT 'open',
  window_from timestamptz NOT NULL, window_to timestamptz NOT NULL, time_zone text NOT NULL,
  snapshot_id text NOT NULL, created_by text NOT NULL,
  created_at timestamptz NOT NULL DEFAULT now(), updated_at timestamptz NOT NULL DEFAULT now(),
  PRIMARY KEY(tenant_id,id), CHECK(window_to>window_from),
  FOREIGN KEY(tenant_id,collection_id) REFERENCES collections(tenant_id,id),
  FOREIGN KEY(tenant_id,snapshot_id) REFERENCES evidence_snapshots(tenant_id,id),
  FOREIGN KEY(tenant_id,created_by) REFERENCES users(tenant_id,id)
);
CREATE TABLE incident_members (
  tenant_id text NOT NULL, incident_id text NOT NULL, user_id text NOT NULL,
  PRIMARY KEY(tenant_id,incident_id,user_id),
  FOREIGN KEY(tenant_id,incident_id) REFERENCES incidents(tenant_id,id),
  FOREIGN KEY(tenant_id,user_id) REFERENCES users(tenant_id,id)
);
CREATE TABLE investigation_runs (
  tenant_id text NOT NULL, id text NOT NULL, incident_id text NOT NULL, snapshot_id text NOT NULL,
  created_by text NOT NULL, question text NOT NULL, policy_revision bigint NOT NULL,
  model_release jsonb NOT NULL, outcome text, dossier_id text, revision_id text,
  steps jsonb NOT NULL DEFAULT '[]', last_event_id integer NOT NULL DEFAULT 0,
  usage jsonb NOT NULL DEFAULT '{"status":"not_called","input_tokens":null,"output_tokens":null}',
  created_at timestamptz NOT NULL DEFAULT now(),
  PRIMARY KEY(tenant_id,id), FOREIGN KEY(tenant_id,incident_id) REFERENCES incidents(tenant_id,id),
  FOREIGN KEY(tenant_id,snapshot_id) REFERENCES evidence_snapshots(tenant_id,id),
  FOREIGN KEY(tenant_id,created_by) REFERENCES users(tenant_id,id)
);
CREATE TABLE jobs (
  tenant_id text NOT NULL, id text NOT NULL, kind text NOT NULL, resource_id text NOT NULL,
  actor_id text NOT NULL, state text NOT NULL DEFAULT 'queued'
    CHECK(state IN('queued','running','retry_wait','succeeded','failed','cancelled')),
  stage text NOT NULL DEFAULT 'queued', attempt integer NOT NULL DEFAULT 0,
  fencing_token bigint NOT NULL DEFAULT 0, lease_until timestamptz, worker_id text,
  cancel_requested boolean NOT NULL DEFAULT false, deadline timestamptz NOT NULL,
  available_at timestamptz NOT NULL DEFAULT now(), created_at timestamptz NOT NULL DEFAULT now(),
  started_at timestamptz, completed_at timestamptz, error jsonb,
  trace_context jsonb NOT NULL DEFAULT '{}', policy_revision bigint NOT NULL,
  PRIMARY KEY(tenant_id,id), UNIQUE(tenant_id,kind,resource_id),
  FOREIGN KEY(tenant_id,actor_id) REFERENCES users(tenant_id,id)
);
CREATE INDEX jobs_acquire ON jobs(tenant_id,state,available_at);
CREATE TABLE run_events (
  tenant_id text NOT NULL, run_id text NOT NULL, seq integer NOT NULL,
  type text NOT NULL, payload jsonb NOT NULL, created_at timestamptz NOT NULL DEFAULT now(),
  PRIMARY KEY(tenant_id,run_id,seq), FOREIGN KEY(tenant_id,run_id) REFERENCES investigation_runs(tenant_id,id)
);
CREATE TABLE dossiers (
  tenant_id text NOT NULL, id text NOT NULL, incident_id text NOT NULL, snapshot_id text NOT NULL,
  origin text NOT NULL CHECK(origin IN('manual','ai')), run_id text,
  current_revision_id text, approved_revision_id text, created_by text NOT NULL,
  created_at timestamptz NOT NULL DEFAULT now(),
  PRIMARY KEY(tenant_id,id), FOREIGN KEY(tenant_id,incident_id) REFERENCES incidents(tenant_id,id),
  FOREIGN KEY(tenant_id,snapshot_id) REFERENCES evidence_snapshots(tenant_id,id),
  FOREIGN KEY(tenant_id,run_id) REFERENCES investigation_runs(tenant_id,id),
  FOREIGN KEY(tenant_id,created_by) REFERENCES users(tenant_id,id)
);
CREATE TABLE dossier_revisions (
  tenant_id text NOT NULL, id text NOT NULL, dossier_id text NOT NULL, number integer NOT NULL,
  base_revision_id text, summary text NOT NULL, claims jsonb NOT NULL, outcome text NOT NULL,
  created_by text NOT NULL, created_at timestamptz NOT NULL DEFAULT now(),
  PRIMARY KEY(tenant_id,id), UNIQUE(tenant_id,dossier_id,number),
  FOREIGN KEY(tenant_id,dossier_id) REFERENCES dossiers(tenant_id,id),
  FOREIGN KEY(tenant_id,base_revision_id) REFERENCES dossier_revisions(tenant_id,id),
  FOREIGN KEY(tenant_id,created_by) REFERENCES users(tenant_id,id)
);
CREATE TABLE revision_decisions (
  tenant_id text NOT NULL, revision_id text NOT NULL,
  status text NOT NULL CHECK(status IN('draft','submitted','approved','changes_requested')),
  submitted_by text, reviewed_by text, reason text, claim_ids jsonb NOT NULL DEFAULT '[]',
  updated_at timestamptz NOT NULL DEFAULT now(),
  PRIMARY KEY(tenant_id,revision_id), FOREIGN KEY(tenant_id,revision_id) REFERENCES dossier_revisions(tenant_id,id),
  FOREIGN KEY(tenant_id,submitted_by) REFERENCES users(tenant_id,id),
  FOREIGN KEY(tenant_id,reviewed_by) REFERENCES users(tenant_id,id)
);
CREATE TABLE exports (
  tenant_id text NOT NULL, id text NOT NULL, dossier_id text NOT NULL, revision_id text NOT NULL,
  created_by text NOT NULL, object_key text, sha256 text, expires_at timestamptz,
  PRIMARY KEY(tenant_id,id), FOREIGN KEY(tenant_id,dossier_id) REFERENCES dossiers(tenant_id,id),
  FOREIGN KEY(tenant_id,revision_id) REFERENCES dossier_revisions(tenant_id,id),
  FOREIGN KEY(tenant_id,created_by) REFERENCES users(tenant_id,id)
);
CREATE TABLE idempotency_keys (
  tenant_id text NOT NULL, user_id text NOT NULL, operation text NOT NULL, key text NOT NULL,
  fingerprint text NOT NULL, resource_id text NOT NULL, created_at timestamptz NOT NULL DEFAULT now(),
  PRIMARY KEY(tenant_id,user_id,operation,key), FOREIGN KEY(tenant_id,user_id) REFERENCES users(tenant_id,id)
);
CREATE TABLE provider_calls (
  tenant_id text NOT NULL, id text NOT NULL, run_id text NOT NULL, job_token bigint NOT NULL,
  status text NOT NULL CHECK(status IN('reserved','dispatched','reported','estimated','unknown','released')),
  reserved_tokens integer NOT NULL, input_tokens integer, output_tokens integer, response_id text,
  deployment text NOT NULL, error_code text, created_at timestamptz NOT NULL DEFAULT now(),
  PRIMARY KEY(tenant_id,id), FOREIGN KEY(tenant_id,run_id) REFERENCES investigation_runs(tenant_id,id)
);
CREATE TABLE audit_events (
  tenant_id text NOT NULL, id text NOT NULL, actor_id text, action text NOT NULL,
  resource_id text NOT NULL, policy_revision bigint NOT NULL, metadata jsonb NOT NULL DEFAULT '{}',
  created_at timestamptz NOT NULL DEFAULT now(), PRIMARY KEY(tenant_id,id)
);
CREATE TABLE deletion_requests (
  tenant_id text NOT NULL, id text NOT NULL, evidence_id text NOT NULL,
  requested_by text NOT NULL, state text NOT NULL, created_at timestamptz NOT NULL DEFAULT now(),
  PRIMARY KEY(tenant_id,id), FOREIGN KEY(tenant_id,evidence_id) REFERENCES evidence(tenant_id,id)
);
CREATE TABLE worker_heartbeats (
  worker_id text PRIMARY KEY, observed_at timestamptz NOT NULL DEFAULT now()
);

DO $$
DECLARE tab text;
BEGIN
  FOREACH tab IN ARRAY ARRAY[
    'tenant_policy','collections','collection_grants','import_batches','import_entries',
    'evidence_snapshots','evidence','snapshot_members','incidents','incident_members',
    'investigation_runs','jobs','run_events','dossiers','dossier_revisions','revision_decisions',
    'exports','idempotency_keys','provider_calls','audit_events','deletion_requests'
  ] LOOP
    EXECUTE format('ALTER TABLE %I ENABLE ROW LEVEL SECURITY',tab);
    EXECUTE format('ALTER TABLE %I FORCE ROW LEVEL SECURITY',tab);
    EXECUTE format('CREATE POLICY tenant_isolation ON %I USING (tenant_id = nullif(current_setting(''ed.tenant_id'',true),'''')) WITH CHECK (tenant_id = nullif(current_setting(''ed.tenant_id'',true),''''))',tab);
  END LOOP;
END $$;
GRANT USAGE ON SCHEMA public TO ed_app;
GRANT SELECT,INSERT,UPDATE,DELETE ON ALL TABLES IN SCHEMA public TO ed_app;
REVOKE INSERT,UPDATE,DELETE ON tenants,users FROM ed_app;
REVOKE UPDATE,DELETE ON dossier_revisions,audit_events FROM ed_app;
REVOKE ALL ON alembic_version FROM ed_app;
