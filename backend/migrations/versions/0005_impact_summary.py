"""Impacto numérico é cálculo do servidor, nunca campo preenchido pelo gerador."""

from alembic import op

revision = "0005"
down_revision = "0004"


def upgrade() -> None:
    op.execute("ALTER TABLE dossier_revisions ADD impact_summary jsonb NOT NULL DEFAULT '{}'")
    op.execute("""
        CREATE OR REPLACE FUNCTION public.redact_tombstoned_revisions(target_tenant text)
        RETURNS bigint LANGUAGE plpgsql SECURITY DEFINER SET search_path=pg_catalog AS $$
        DECLARE affected bigint;
        BEGIN
          IF target_tenant IS DISTINCT FROM nullif(current_setting('ed.tenant_id',true),'') THEN
            RAISE EXCEPTION 'tenant context required' USING ERRCODE='42501';
          END IF;
          UPDATE public.dossier_revisions r
          SET summary='Conteúdo removido por exclusão de fonte.', claims='[]'::jsonb,
              missing_information='[]'::jsonb, suggested_checks='[]'::jsonb,
              impact_summary='{}'::jsonb
          WHERE r.tenant_id=target_tenant AND EXISTS (
            SELECT 1 FROM public.dossiers d WHERE d.tenant_id=r.tenant_id
              AND d.id=r.dossier_id AND d.tombstoned_at IS NOT NULL
          );
          GET DIAGNOSTICS affected = ROW_COUNT;
          RETURN affected;
        END
        $$
    """)


def downgrade() -> None:
    raise RuntimeError("Reversão destrutiva exige restore verificado.")
