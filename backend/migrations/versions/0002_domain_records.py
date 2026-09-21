"""Mapeamentos e informações de abstenção persistidos sem misturar com documentos."""
from alembic import op

revision = "0002"
down_revision = "0001"


def upgrade() -> None:
    op.execute("""
        CREATE TABLE snapshot_mappings (
            tenant_id text NOT NULL, snapshot_id text NOT NULL, source_system text NOT NULL,
            source_order_reference text NOT NULL, order_reference text NOT NULL,
            PRIMARY KEY(tenant_id,snapshot_id,source_system,source_order_reference),
            FOREIGN KEY(tenant_id,snapshot_id) REFERENCES evidence_snapshots(tenant_id,id)
        )
    """)
    op.execute("ALTER TABLE snapshot_mappings ENABLE ROW LEVEL SECURITY")
    op.execute("ALTER TABLE snapshot_mappings FORCE ROW LEVEL SECURITY")
    op.execute("CREATE POLICY tenant_isolation ON snapshot_mappings USING (tenant_id=nullif(current_setting('ed.tenant_id',true),'')) WITH CHECK (tenant_id=nullif(current_setting('ed.tenant_id',true),''))")
    op.execute("GRANT SELECT,INSERT,UPDATE,DELETE ON snapshot_mappings TO ed_app")
    op.execute("ALTER TABLE dossier_revisions ADD missing_information jsonb NOT NULL DEFAULT '[]'")
    op.execute("ALTER TABLE dossier_revisions ADD suggested_checks jsonb NOT NULL DEFAULT '[]'")


def downgrade() -> None:
    raise RuntimeError("Use um restore verificado para reversão destrutiva.")
