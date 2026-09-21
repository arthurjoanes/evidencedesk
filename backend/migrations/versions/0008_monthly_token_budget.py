"""Monthly UTC token balances with an append-only accounting history."""

from alembic import op
from sqlalchemy import text

revision = "0008"
down_revision = "0007"


def upgrade() -> None:
    op.execute("""
        CREATE TABLE token_budget_periods (
          tenant_id text NOT NULL REFERENCES tenants(id) ON DELETE CASCADE,
          period_start date NOT NULL CHECK(extract(day FROM period_start)=1),
          reserved_tokens bigint NOT NULL DEFAULT 0 CHECK(reserved_tokens>=0),
          reported_tokens bigint NOT NULL DEFAULT 0 CHECK(reported_tokens>=0),
          created_at timestamptz NOT NULL DEFAULT now(),
          PRIMARY KEY(tenant_id,period_start)
        )
    """)
    op.execute("""
        CREATE TABLE provider_budget_events (
          tenant_id text NOT NULL REFERENCES tenants(id) ON DELETE CASCADE,
          id text NOT NULL, call_id text, period_start date NOT NULL,
          kind text NOT NULL CHECK(kind IN('opening_balance','reserved','reported','unknown')),
          reserved_delta bigint NOT NULL, reported_delta bigint NOT NULL CHECK(reported_delta>=0),
          created_at timestamptz NOT NULL DEFAULT now(),
          PRIMARY KEY(tenant_id,id),
          FOREIGN KEY(tenant_id,period_start) REFERENCES token_budget_periods(tenant_id,period_start)
        )
    """)
    op.execute("ALTER TABLE provider_calls ADD budget_period date")
    connection = op.get_bind()
    for tenant in connection.execute(text("SELECT id FROM tenants ORDER BY id")).scalars().all():
        parameters = {"tenant": tenant}
        connection.execute(text("SELECT set_config('ed.tenant_id',:tenant,true)"), parameters)
        connection.execute(
            text("""
            UPDATE provider_calls SET budget_period=date_trunc('month',created_at AT TIME ZONE 'UTC')::date
            WHERE tenant_id=:tenant
        """),
            parameters,
        )
        connection.execute(
            text("""
            INSERT INTO token_budget_periods(tenant_id,period_start,reserved_tokens,reported_tokens)
            SELECT tenant_id,budget_period,
              sum(CASE WHEN status='released' OR (status='reported' AND input_tokens IS NOT NULL AND output_tokens IS NOT NULL)
                  THEN 0 ELSE reserved_tokens END),
              sum(CASE WHEN status='reported' AND input_tokens IS NOT NULL AND output_tokens IS NOT NULL
                  THEN input_tokens::bigint+output_tokens ELSE 0 END)
            FROM provider_calls WHERE tenant_id=:tenant GROUP BY tenant_id,budget_period
        """),
            parameters,
        )
        # Preserve any legacy amount that cannot be attributed from retained call metadata.
        # It belongs to the migration month conservatively, never silently resets quota.
        connection.execute(
            text("""
            INSERT INTO token_budget_periods(tenant_id,period_start,reserved_tokens,reported_tokens)
            SELECT p.tenant_id,date_trunc('month',now() AT TIME ZONE 'UTC')::date,
              greatest(p.token_reserved-coalesce(t.reserved,0),0),
              greatest(p.token_reported-coalesce(t.reported,0),0)
            FROM tenant_policy p
            LEFT JOIN (SELECT tenant_id,sum(reserved_tokens) reserved,sum(reported_tokens) reported
              FROM token_budget_periods GROUP BY tenant_id) t ON t.tenant_id=p.tenant_id
            WHERE p.tenant_id=:tenant
            ON CONFLICT(tenant_id,period_start) DO UPDATE SET
              reserved_tokens=token_budget_periods.reserved_tokens+excluded.reserved_tokens,
              reported_tokens=token_budget_periods.reported_tokens+excluded.reported_tokens
        """),
            parameters,
        )
        connection.execute(
            text("""
            INSERT INTO provider_budget_events(tenant_id,id,period_start,kind,reserved_delta,reported_delta)
            SELECT tenant_id,'opening:'||period_start,period_start,'opening_balance',reserved_tokens,reported_tokens
            FROM token_budget_periods WHERE tenant_id=:tenant
        """),
            parameters,
        )
        connection.execute(
            text("""
            UPDATE tenant_policy SET
              token_reserved=(SELECT coalesce(sum(reserved_tokens),0) FROM token_budget_periods WHERE tenant_id=:tenant),
              token_reported=(SELECT coalesce(sum(reported_tokens),0) FROM token_budget_periods WHERE tenant_id=:tenant)
            WHERE tenant_id=:tenant
        """),
            parameters,
        )
    connection.execute(text("SELECT set_config('ed.tenant_id','',true)"))
    op.execute("ALTER TABLE provider_calls ALTER COLUMN budget_period SET NOT NULL")
    op.execute("""
        ALTER TABLE provider_calls ADD CONSTRAINT provider_call_budget_period
        FOREIGN KEY(tenant_id,budget_period) REFERENCES token_budget_periods(tenant_id,period_start)
    """)
    for table in ("token_budget_periods", "provider_budget_events"):
        op.execute(f"ALTER TABLE {table} ENABLE ROW LEVEL SECURITY")
        op.execute(f"ALTER TABLE {table} FORCE ROW LEVEL SECURITY")
        op.execute(
            f"CREATE POLICY tenant_isolation ON {table} USING (tenant_id=nullif(current_setting('ed.tenant_id',true),'')) WITH CHECK (tenant_id=nullif(current_setting('ed.tenant_id',true),''))"
        )
    op.execute("GRANT SELECT,INSERT,UPDATE ON token_budget_periods TO ed_app")
    op.execute("GRANT SELECT,INSERT ON provider_budget_events TO ed_app")
    op.execute("REVOKE DELETE ON token_budget_periods FROM ed_app")
    op.execute("REVOKE UPDATE,DELETE ON provider_budget_events FROM ed_app")
    op.execute("""
        CREATE FUNCTION public.keep_provider_budget_period() RETURNS trigger
        LANGUAGE plpgsql AS $$ BEGIN
          IF NEW.budget_period IS DISTINCT FROM OLD.budget_period THEN
            RAISE EXCEPTION 'provider budget period is immutable' USING ERRCODE='23514';
          END IF;
          RETURN NEW;
        END $$
    """)
    op.execute("""
        CREATE TRIGGER provider_budget_period_immutable BEFORE UPDATE ON provider_calls
        FOR EACH ROW EXECUTE FUNCTION public.keep_provider_budget_period()
    """)


def downgrade() -> None:
    raise RuntimeError("Reversão de orçamento exige restore e reconciliação contábil verificados.")
