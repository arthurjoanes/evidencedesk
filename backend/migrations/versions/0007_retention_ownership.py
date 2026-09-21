"""Bounded retention with durable object ownership and idempotent quota release."""

from alembic import op
from sqlalchemy import text

revision = "0007"
down_revision = "0006"


def upgrade() -> None:
    op.execute("ALTER TABLE tenant_policy ADD retention_scan_cursor text NOT NULL DEFAULT ''")
    op.execute("ALTER TABLE import_batches ADD updated_at timestamptz NOT NULL DEFAULT now()")
    op.execute("""
        ALTER TABLE import_entries ADD quota_bytes bigint NOT NULL DEFAULT 0 CHECK(quota_bytes>=0),
          ADD quota_released_at timestamptz, ADD cleanup_id text
    """)
    op.execute("ALTER TABLE deletion_requests ADD cleanup_id text")
    op.execute("""
        CREATE TABLE storage_cleanup (
          tenant_id text NOT NULL REFERENCES tenants(id), id text NOT NULL,
          reason text NOT NULL CHECK(reason IN('source_deleted','import_expired','export_expired','orphan')),
          object_keys jsonb NOT NULL CHECK(jsonb_typeof(object_keys)='array'),
          state text NOT NULL DEFAULT 'pending' CHECK(state IN('pending','completed')),
          attempts integer NOT NULL DEFAULT 0 CHECK(attempts>=0), error_code text,
          released_bytes bigint NOT NULL DEFAULT 0 CHECK(released_bytes>=0),
          created_at timestamptz NOT NULL DEFAULT now(), completed_at timestamptz,
          PRIMARY KEY(tenant_id,id)
        )
    """)
    op.execute(
        "CREATE INDEX storage_cleanup_pending ON storage_cleanup(tenant_id,state,created_at)"
    )
    op.execute("ALTER TABLE storage_cleanup ENABLE ROW LEVEL SECURITY")
    op.execute("ALTER TABLE storage_cleanup FORCE ROW LEVEL SECURITY")
    op.execute(
        "CREATE POLICY tenant_isolation ON storage_cleanup USING (tenant_id=nullif(current_setting('ed.tenant_id',true),'')) WITH CHECK (tenant_id=nullif(current_setting('ed.tenant_id',true),''))"
    )
    op.execute("GRANT SELECT,INSERT,UPDATE,DELETE ON storage_cleanup TO ed_app")
    connection = op.get_bind()
    for tenant in connection.execute(text("SELECT id FROM tenants ORDER BY id")).scalars().all():
        connection.execute(
            text("SELECT set_config('ed.tenant_id',:tenant,true)"), {"tenant": tenant}
        )
        connection.execute(
            text("UPDATE import_batches SET updated_at=created_at WHERE tenant_id=:tenant"),
            {"tenant": tenant},
        )
        connection.execute(
            text("UPDATE import_entries SET quota_bytes=byte_size WHERE tenant_id=:tenant"),
            {"tenant": tenant},
        )
        connection.execute(
            text("""
        INSERT INTO storage_cleanup(tenant_id,id,reason,object_keys,state,completed_at)
        SELECT tenant_id,'deletion:'||evidence_id,'source_deleted',object_keys,
          CASE WHEN completed_at IS NULL THEN 'pending' ELSE 'completed' END,completed_at
        FROM deletion_requests WHERE tenant_id=:tenant
        """),
            {"tenant": tenant},
        )
        connection.execute(
            text(
                "UPDATE deletion_requests SET cleanup_id='deletion:'||evidence_id WHERE tenant_id=:tenant"
            ),
            {"tenant": tenant},
        )
        connection.execute(
            text("""
        UPDATE import_entries e SET cleanup_id=d.cleanup_id,quota_released_at=d.completed_at
        FROM import_batches b,deletion_requests d,evidence s
        WHERE e.tenant_id=b.tenant_id AND e.batch_id=b.id AND d.tenant_id=e.tenant_id
          AND s.tenant_id=d.tenant_id AND s.id=d.evidence_id
          AND b.collection_id=s.collection_id AND e.sha256=s.sha256
          AND e.error->>'code'='source_deleted' AND e.tenant_id=:tenant
        """),
            {"tenant": tenant},
        )
        # Entry ownership, not a repeatedly subtracted deletion estimate, is authoritative.
        connection.execute(
            text("""
        UPDATE tenant_policy p SET storage_reserved=(
          SELECT coalesce(sum(e.quota_bytes),0) FROM import_entries e
          WHERE e.tenant_id=p.tenant_id AND e.quota_released_at IS NULL
        ) WHERE p.tenant_id=:tenant
        """),
            {"tenant": tenant},
        )
    connection.execute(text("SELECT set_config('ed.tenant_id','',true)"))
    op.execute("""
        CREATE FUNCTION public.expire_audit_events(target_tenant text, retention_days integer, batch_limit integer)
        RETURNS bigint LANGUAGE plpgsql SECURITY DEFINER SET search_path=pg_catalog AS $$
        DECLARE affected bigint;
        BEGIN
          IF target_tenant IS DISTINCT FROM nullif(current_setting('ed.tenant_id',true),'') THEN
            RAISE EXCEPTION 'tenant context required' USING ERRCODE='42501';
          END IF;
          IF retention_days<90 OR retention_days>3650 OR batch_limit<1 OR batch_limit>1000 THEN
            RAISE EXCEPTION 'invalid retention bound';
          END IF;
          DELETE FROM public.audit_events WHERE (tenant_id,id) IN (
            SELECT tenant_id,id FROM public.audit_events
            WHERE tenant_id=target_tenant AND created_at<now()-make_interval(days=>retention_days)
            ORDER BY created_at,id LIMIT batch_limit
          );
          GET DIAGNOSTICS affected = ROW_COUNT;
          RETURN affected;
        END $$
    """)
    op.execute(
        "REVOKE ALL ON FUNCTION public.expire_audit_events(text,integer,integer) FROM PUBLIC"
    )
    op.execute(
        "GRANT EXECUTE ON FUNCTION public.expire_audit_events(text,integer,integer) TO ed_app"
    )


def downgrade() -> None:
    raise RuntimeError("Reversão destrutiva exige restore verificado.")
