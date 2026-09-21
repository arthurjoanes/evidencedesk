"""Owned maintenance windows and deletion-ledger checkpoints."""

from alembic import op

revision = "0003"
down_revision = "0002"


def upgrade() -> None:
    op.execute("ALTER TABLE operational_control ADD maintenance_token text")
    op.execute("ALTER TABLE operational_control ADD maintenance_started_at timestamptz")
    op.execute("""
        CREATE TABLE operational_ledger (
            id integer PRIMARY KEY CHECK(id=1), ledger_id text,
            sequence bigint NOT NULL DEFAULT 0 CHECK(sequence>=0), sha256 text,
            reconciled_at timestamptz
        )
    """)
    op.execute("INSERT INTO operational_ledger(id) VALUES(1)")
    op.execute("GRANT SELECT,UPDATE ON operational_ledger TO ed_app")
    op.execute("ALTER TABLE dossiers ADD tombstoned_at timestamptz")
    op.execute("ALTER TABLE investigation_runs ADD tombstoned_at timestamptz")
    op.execute("""
        CREATE FUNCTION public.redact_tombstoned_revisions(target_tenant text)
        RETURNS bigint LANGUAGE plpgsql SECURITY DEFINER SET search_path=pg_catalog AS $$
        DECLARE affected bigint;
        BEGIN
          IF target_tenant IS DISTINCT FROM nullif(current_setting('ed.tenant_id',true),'') THEN
            RAISE EXCEPTION 'tenant context required' USING ERRCODE='42501';
          END IF;
          UPDATE public.dossier_revisions r
          SET summary='Conteúdo removido por exclusão de fonte.', claims='[]'::jsonb,
              missing_information='[]'::jsonb, suggested_checks='[]'::jsonb
          WHERE r.tenant_id=target_tenant AND EXISTS (
            SELECT 1 FROM public.dossiers d WHERE d.tenant_id=r.tenant_id
              AND d.id=r.dossier_id AND d.tombstoned_at IS NOT NULL
          );
          GET DIAGNOSTICS affected = ROW_COUNT;
          RETURN affected;
        END
        $$
    """)
    op.execute("REVOKE ALL ON FUNCTION public.redact_tombstoned_revisions(text) FROM PUBLIC")
    op.execute("GRANT EXECUTE ON FUNCTION public.redact_tombstoned_revisions(text) TO ed_app")


def downgrade() -> None:
    raise RuntimeError("Use a verified restore for destructive rollback.")
