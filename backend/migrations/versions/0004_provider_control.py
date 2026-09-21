"""Admissão global do provedor, artefatos e leases de streams."""
from alembic import op

revision = "0004"
down_revision = "0003"


def upgrade() -> None:
    op.execute("CREATE TABLE provider_control(id integer PRIMARY KEY CHECK(id=1),call_id text,lease_until timestamptz,failures integer NOT NULL DEFAULT 0,open_until timestamptz)")
    op.execute("INSERT INTO provider_control(id) VALUES(1)")
    op.execute("GRANT SELECT,UPDATE ON provider_control TO ed_app")
    op.execute("""
        CREATE TABLE result_artifacts (
            tenant_id text NOT NULL, run_id text NOT NULL, attempt_token bigint NOT NULL,
            result_key text NOT NULL, result_sha256 text NOT NULL, manifest_key text NOT NULL, manifest_sha256 text NOT NULL,
            PRIMARY KEY(tenant_id,run_id,attempt_token),
            FOREIGN KEY(tenant_id,run_id) REFERENCES investigation_runs(tenant_id,id)
        )
    """)
    op.execute("CREATE TABLE stream_leases(token text PRIMARY KEY,user_id text NOT NULL REFERENCES users(id),expires_at timestamptz NOT NULL)")
    op.execute("GRANT SELECT,INSERT,UPDATE,DELETE ON stream_leases,result_artifacts TO ed_app")
    op.execute("ALTER TABLE result_artifacts ENABLE ROW LEVEL SECURITY")
    op.execute("ALTER TABLE result_artifacts FORCE ROW LEVEL SECURITY")
    op.execute("CREATE POLICY tenant_isolation ON result_artifacts USING (tenant_id=nullif(current_setting('ed.tenant_id',true),'')) WITH CHECK (tenant_id=nullif(current_setting('ed.tenant_id',true),''))")


def downgrade() -> None:
    raise RuntimeError("Reversão destrutiva exige restore verificado.")
