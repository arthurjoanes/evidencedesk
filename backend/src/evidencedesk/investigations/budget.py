from datetime import date
from uuid import uuid4

from pydantic import BaseModel, ConfigDict
from sqlalchemy import Connection, text

from evidencedesk.config import get_settings
from evidencedesk.database import transaction
from evidencedesk.errors import Problem
from evidencedesk.identity.service import actor_for_worker
from evidencedesk.investigations.service import authorize_run
from evidencedesk.jobs.service import Lease, assert_publishable
from evidencedesk.model_runtime.contracts import TokenUsage
from evidencedesk.model_runtime.release import FrozenModelRelease, load_release


class BudgetPosition(BaseModel):
    model_config = ConfigDict(frozen=True)
    period_start: date
    current_reported_tokens: int
    current_reserved_tokens: int
    carried_reserved_tokens: int

    @property
    def committed_tokens(self) -> int:
        return (
            self.current_reported_tokens
            + self.current_reserved_tokens
            + self.carried_reserved_tokens
        )


def current_budget_period(connection: Connection) -> date:
    # Database time is authoritative; process restarts and local time zones cannot reset a period.
    return connection.execute(
        text("SELECT date_trunc('month',now() AT TIME ZONE 'UTC')::date")
    ).scalar_one()


def budget_position(
    connection: Connection, tenant_id: str, period: date | None = None
) -> BudgetPosition:
    period = period or current_budget_period(connection)
    row = (
        connection.execute(
            text("""
        SELECT coalesce(sum(reported_tokens) FILTER (WHERE period_start=:period),0) AS reported,
          coalesce(sum(reserved_tokens) FILTER (WHERE period_start=:period),0) AS reserved,
          coalesce(sum(reserved_tokens) FILTER (WHERE period_start<>:period),0) AS carried
        FROM token_budget_periods WHERE tenant_id=:tenant
    """),
            {"tenant": tenant_id, "period": period},
        )
        .mappings()
        .one()
    )
    return BudgetPosition(
        period_start=period,
        current_reported_tokens=row["reported"],
        current_reserved_tokens=row["reserved"],
        carried_reserved_tokens=row["carried"],
    )


def _record_budget_event(
    connection: Connection,
    *,
    tenant_id: str,
    call_id: str,
    period: date,
    kind: str,
    reserved_delta: int,
    reported_delta: int,
) -> None:
    connection.execute(
        text("""
        INSERT INTO provider_budget_events(tenant_id,id,call_id,period_start,kind,reserved_delta,reported_delta)
        VALUES(:tenant,:id,:call,:period,:kind,:reserved,:reported)
    """),
        {
            "tenant": tenant_id,
            "id": call_id + ":" + kind,
            "call": call_id,
            "period": period,
            "kind": kind,
            "reserved": reserved_delta,
            "reported": reported_delta,
        },
    )


def authorize_dispatch(lease: Lease, release: FrozenModelRelease, input_estimate: int) -> str:
    settings = get_settings()
    # A queued release fixes model behavior, but cannot override the operator's
    # current ability to disable paid generation or remove its credential.
    if not settings.generation_enabled:
        raise Problem(
            503,
            "generator_unavailable",
            "O gerador está desabilitado ou sem credencial. Continue com a investigação manual.",
        )
    if not 0 < input_estimate <= release.limits.max_input_tokens:
        raise Problem(
            422, "input_budget_exceeded", "A entrada excede o limite congelado da execução."
        )
    reserved = release.limits.max_input_tokens + release.limits.max_output_tokens
    call_id = uuid4().hex
    with transaction(lease.tenant_id) as connection:
        assert_publishable(connection, lease)
        actor = actor_for_worker(connection, lease.tenant_id, lease.actor_id)
        run = authorize_run(connection, actor, lease.resource_id)
        if load_release(run["model_release"]) != release:
            raise Problem(
                409, "model_release_changed", "A configuração da execução mudou antes do despacho."
            )
        calls = connection.execute(
            text("SELECT count(*) FROM provider_calls WHERE tenant_id=:tenant AND run_id=:run"),
            {"tenant": lease.tenant_id, "run": lease.resource_id},
        ).scalar_one()
        if calls >= release.limits.max_generation_calls:
            raise Problem(
                429, "generation_call_limit", "A execução atingiu o limite de chamadas gerativas."
            )
        slot = (
            connection.execute(
                text("""
            SELECT (lease_until>now()) AS occupied,(open_until>now()) AS circuit_open FROM provider_control WHERE id=1 FOR UPDATE
        """)
            )
            .mappings()
            .one()
        )
        if slot["circuit_open"]:
            raise Problem(
                503,
                "provider_circuit_open",
                "O gerador está em recuperação. Continue a investigação manual.",
                retryable=True,
            )
        if slot["occupied"]:
            raise Problem(
                503,
                "provider_capacity",
                "A capacidade de geração está ocupada. Tente novamente em instantes.",
                retryable=True,
            )
        period = current_budget_period(connection)
        position = budget_position(connection, lease.tenant_id, period)
        if position.committed_tokens + reserved > settings.ai_period_token_budget:
            raise Problem(
                429,
                "token_budget_exhausted",
                "O orçamento mensal de tokens, incluindo reservas ainda sem confirmação, foi atingido.",
            )
        connection.execute(
            text("""
            INSERT INTO token_budget_periods(tenant_id,period_start,reserved_tokens)
            VALUES(:tenant,:period,:reserved)
            ON CONFLICT(tenant_id,period_start) DO UPDATE
            SET reserved_tokens=token_budget_periods.reserved_tokens+excluded.reserved_tokens
        """),
            {"tenant": lease.tenant_id, "period": period, "reserved": reserved},
        )
        connection.execute(
            text("""
            UPDATE tenant_policy SET token_reserved=token_reserved+:reserved
            WHERE tenant_id=:tenant
        """),
            {
                "tenant": lease.tenant_id,
                "reserved": reserved,
            },
        )
        connection.execute(
            text("""
            INSERT INTO provider_calls(tenant_id,id,run_id,job_token,status,reserved_tokens,deployment,budget_period)
            VALUES(:tenant,:id,:run,:token,'dispatched',:reserved,:deployment,:period)
        """),
            {
                "tenant": lease.tenant_id,
                "id": call_id,
                "run": lease.resource_id,
                "token": lease.token,
                "reserved": reserved,
                "deployment": release.deployment,
                "period": period,
            },
        )
        _record_budget_event(
            connection,
            tenant_id=lease.tenant_id,
            call_id=call_id,
            period=period,
            kind="reserved",
            reserved_delta=reserved,
            reported_delta=0,
        )
        connection.execute(
            text("""
                UPDATE investigation_runs SET usage=jsonb_build_object(
                    'status','reserved','input_tokens',NULL,'output_tokens',NULL,
                    'budget_period',CAST(:period AS text),'budget_policy','calendar_month_utc_carry_unresolved',
                    'input_token_estimate',CAST(:estimate AS integer),'input_estimation_method',CAST(:method AS text))
                WHERE tenant_id=:tenant AND id=:run
            """),
            {
                "tenant": lease.tenant_id,
                "run": lease.resource_id,
                "estimate": input_estimate,
                "method": release.estimation_method,
                "period": period.isoformat(),
            },
        )
        connection.execute(
            text(
                "UPDATE provider_control SET call_id=:id,lease_until=now()+interval '120 seconds' WHERE id=1"
            ),
            {"id": call_id},
        )
    return call_id


def reconcile_usage(
    lease: Lease,
    call_id: str,
    usage: TokenUsage | None,
    response_id: str | None,
    *,
    failed: bool,
    error_code: str | None = None,
) -> None:
    with transaction(lease.tenant_id) as connection:
        # Usage survives cancellation/revocation and does not publish any generated text.
        connection.execute(
            text("SELECT tenant_id FROM tenant_policy WHERE tenant_id=:tenant FOR UPDATE"),
            {"tenant": lease.tenant_id},
        )
        row = (
            connection.execute(
                text(
                    "SELECT status,reserved_tokens,budget_period,run_id FROM provider_calls WHERE tenant_id=:tenant AND id=:id FOR UPDATE"
                ),
                {"tenant": lease.tenant_id, "id": call_id},
            )
            .mappings()
            .one()
        )
        if row["run_id"] != lease.resource_id:
            raise Problem(
                409, "provider_call_mismatch", "A chamada não pertence à execução informada."
            )
        if row["status"] not in {"dispatched", "reserved", "unknown", "estimated"}:
            return
        known = (
            usage is not None
            and usage.status == "reported"
            and usage.input_tokens is not None
            and usage.output_tokens is not None
        )
        if row["status"] in {"unknown", "estimated"} and not known:
            return
        consumed = 0
        if known:
            assert (
                usage is not None
                and usage.input_tokens is not None
                and usage.output_tokens is not None
            )
            consumed = usage.input_tokens + usage.output_tokens
            connection.execute(
                text("""
                UPDATE token_budget_periods SET reserved_tokens=reserved_tokens-:reserved,
                  reported_tokens=reported_tokens+:consumed
                WHERE tenant_id=:tenant AND period_start=:period
            """),
                {
                    "tenant": lease.tenant_id,
                    "period": row["budget_period"],
                    "reserved": row["reserved_tokens"],
                    "consumed": consumed,
                },
            )
            connection.execute(
                text(
                    "UPDATE tenant_policy SET token_reserved=token_reserved-:reserved,token_reported=token_reported+:consumed WHERE tenant_id=:tenant"
                ),
                {
                    "tenant": lease.tenant_id,
                    "reserved": row["reserved_tokens"],
                    "consumed": consumed,
                },
            )
        _record_budget_event(
            connection,
            tenant_id=lease.tenant_id,
            call_id=call_id,
            period=row["budget_period"],
            kind="reported" if known else "unknown",
            reserved_delta=-row["reserved_tokens"] if known else 0,
            reported_delta=consumed,
        )
        connection.execute(
            text("""
            UPDATE provider_calls SET status=:status,input_tokens=:input,output_tokens=:output,response_id=:response,error_code=coalesce(:error,error_code)
            WHERE tenant_id=:tenant AND id=:id
        """),
            {
                "tenant": lease.tenant_id,
                "id": call_id,
                "status": "reported" if known else "unknown",
                "input": usage.input_tokens if usage else None,
                "output": usage.output_tokens if usage else None,
                "response": response_id,
                "error": error_code,
            },
        )
        connection.execute(
            text("""
            UPDATE investigation_runs SET usage=usage || jsonb_build_object(
                'status',CAST(:status AS text),'input_tokens',CAST(:input AS integer),
                'output_tokens',CAST(:output AS integer))
            WHERE tenant_id=:tenant AND id=:run
        """),
            {
                "tenant": lease.tenant_id,
                "run": lease.resource_id,
                "status": "reported" if known else "unknown",
                "input": usage.input_tokens if usage else None,
                "output": usage.output_tokens if usage else None,
            },
        )
        connection.execute(
            text("""
            UPDATE provider_control SET lease_until=NULL,call_id=NULL,failures=CASE WHEN :failed THEN failures+1 ELSE 0 END,
            open_until=CASE WHEN :failed AND failures>=2 THEN now()+interval '60 seconds' ELSE NULL END
            WHERE id=1 AND call_id=:id
        """),
            {"id": call_id, "failed": failed},
        )
