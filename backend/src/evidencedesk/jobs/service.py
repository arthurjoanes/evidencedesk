import json
import random
from dataclasses import dataclass, field
from uuid import uuid4

from opentelemetry.propagate import inject
from sqlalchemy import Connection, text

from evidencedesk.config import get_settings
from evidencedesk.database import lock_policy, transaction
from evidencedesk.errors import Problem, not_found
from evidencedesk.identity.service import Actor
from evidencedesk.jobs.progress import update_steps
from evidencedesk.pagination import fingerprint


@dataclass(frozen=True)
class Lease:
    tenant_id: str
    job_id: str
    resource_id: str
    actor_id: str
    kind: str
    token: int
    policy_revision: int
    trace_context: dict[str, str] = field(default_factory=dict)


def enqueue(
    connection: Connection, actor: Actor, kind: str, resource_id: str, policy_revision: int
) -> str:
    queued = connection.execute(
        text(
            "SELECT count(*) FROM jobs WHERE tenant_id=:tenant AND state IN ('queued','running','retry_wait')"
        ),
        {"tenant": actor.tenant_id},
    ).scalar_one()
    if queued >= get_settings().max_queued_jobs:
        raise Problem(
            429,
            "queue_full",
            "A fila da organização atingiu o limite. Aguarde uma conclusão.",
            retryable=True,
        )
    job_id = uuid4().hex
    trace_context: dict[str, str] = {}
    inject(trace_context)
    connection.execute(
        text("""
        INSERT INTO jobs(tenant_id,id,kind,resource_id,actor_id,deadline,policy_revision,trace_context)
        VALUES(:tenant,:id,:kind,:resource,:actor,now()+interval '15 minutes',:policy,CAST(:trace AS jsonb))
    """),
        {
            "tenant": actor.tenant_id,
            "id": job_id,
            "kind": kind,
            "resource": resource_id,
            "actor": actor.id,
            "policy": policy_revision,
            "trace": json.dumps(
                {
                    key: value
                    for key, value in trace_context.items()
                    if key in {"traceparent", "tracestate"}
                }
            ),
        },
    )
    return job_id


def idempotent_resource(
    connection: Connection,
    actor: Actor,
    operation: str,
    key: str | None,
    body: dict,
    resource_id: str,
) -> tuple[str, bool]:
    if not key or len(key) > 128:
        raise Problem(
            422,
            "idempotency_key_required",
            "Informe uma chave de idempotência de até 128 caracteres.",
        )
    digest = fingerprint(body)
    row = connection.execute(
        text("""
        INSERT INTO idempotency_keys(tenant_id,user_id,operation,key,fingerprint,resource_id)
        VALUES(:tenant,:user,:operation,:key,:fingerprint,:resource)
        ON CONFLICT DO NOTHING RETURNING resource_id
    """),
        {
            "tenant": actor.tenant_id,
            "user": actor.id,
            "operation": operation,
            "key": key,
            "fingerprint": digest,
            "resource": resource_id,
        },
    ).first()
    if row:
        return resource_id, True
    existing = (
        connection.execute(
            text("""
        SELECT fingerprint,resource_id FROM idempotency_keys WHERE tenant_id=:tenant AND user_id=:user AND operation=:operation AND key=:key
    """),
            {"tenant": actor.tenant_id, "user": actor.id, "operation": operation, "key": key},
        )
        .mappings()
        .one()
    )
    if existing["fingerprint"] != digest:
        raise Problem(
            409, "idempotency_conflict", "Esta chave já identifica um pedido com outro conteúdo."
        )
    return existing["resource_id"], False


def acquire(tenant_id: str, worker_id: str) -> Lease | None:
    settings = get_settings()
    with transaction(tenant_id) as connection:
        try:
            lock_policy(connection, tenant_id, mutation=True)
        except Problem as error:
            if error.code == "maintenance":
                return None
            raise
        # Even reported usage does not prove the result was committed. A process may
        # die after accounting but before publication; never repeat paid work for it.
        paid_expired = (
            connection.execute(
                text("""
            UPDATE jobs j SET state='failed',stage='failed',completed_at=now(),lease_until=NULL,
                error='{"code":"provider_result_unpublished","message":"A tentativa terminou após chamar o provedor sem confirmar a publicação. Não houve nova chamada automática."}'
            WHERE j.tenant_id=:tenant AND j.state='running' AND j.lease_until<=now()
            AND EXISTS(SELECT 1 FROM provider_calls p WHERE p.tenant_id=j.tenant_id AND p.run_id=j.resource_id AND p.status NOT IN('reserved','released'))
            RETURNING j.kind,j.resource_id,j.error
        """),
                {"tenant": tenant_id},
            )
            .mappings()
            .all()
        )
        record_expired_runs(connection, tenant_id, paid_expired)
        active = connection.execute(
            text(
                "SELECT count(*) FROM jobs WHERE tenant_id=:tenant AND state='running' AND lease_until>now()"
            ),
            {"tenant": tenant_id},
        ).scalar_one()
        if active >= settings.max_active_jobs_per_tenant:
            return None
        expired = (
            connection.execute(
                text("""
            UPDATE jobs SET state='failed',stage='failed',completed_at=now(),lease_until=NULL,error='{"code":"deadline_exceeded","message":"O prazo de execução terminou."}'
            WHERE tenant_id=:tenant AND state IN('queued','running','retry_wait') AND deadline<=now()
            RETURNING kind,resource_id,error
        """),
                {"tenant": tenant_id},
            )
            .mappings()
            .all()
        )
        record_expired_runs(connection, tenant_id, expired)
        row = (
            connection.execute(
                text("""
            SELECT * FROM jobs WHERE tenant_id=:tenant AND deadline>now() AND NOT cancel_requested
            AND ((state IN('queued','retry_wait') AND available_at<=now()) OR (state='running' AND lease_until<=now()))
            ORDER BY created_at,id FOR UPDATE SKIP LOCKED LIMIT 1
        """),
                {"tenant": tenant_id},
            )
            .mappings()
            .first()
        )
        if row is None:
            return None
        token = row["fencing_token"] + 1
        connection.execute(
            text("""
            UPDATE jobs SET state='running',stage='starting',attempt=attempt+1,fencing_token=:token,
            worker_id=:worker,lease_until=now()+make_interval(secs=>:lease),started_at=coalesce(started_at,now())
            WHERE tenant_id=:tenant AND id=:id
        """),
            {
                "tenant": tenant_id,
                "id": row["id"],
                "token": token,
                "worker": worker_id,
                "lease": settings.job_lease_seconds,
            },
        )
        return Lease(
            tenant_id,
            row["id"],
            row["resource_id"],
            row["actor_id"],
            row["kind"],
            token,
            row["policy_revision"],
            row["trace_context"],
        )


def record_expired_runs(connection: Connection, tenant_id: str, rows) -> None:
    from evidencedesk.investigations.service import append_event

    for row in rows:
        if row["kind"] == "investigation":
            update_steps(connection, tenant_id, row["resource_id"], "failed")
            append_event(
                connection,
                tenant_id,
                row["resource_id"],
                "terminal",
                {"state": "failed", "stage": "failed", "error": row["error"]},
            )


def assert_publishable(connection: Connection, lease: Lease) -> None:
    current_policy = lock_policy(connection, lease.tenant_id)
    row = connection.execute(
        text("""
        SELECT id FROM jobs WHERE tenant_id=:tenant AND id=:id AND fencing_token=:token
        AND state='running' AND lease_until>now() AND deadline>now() AND NOT cancel_requested FOR UPDATE
    """),
        {"tenant": lease.tenant_id, "id": lease.job_id, "token": lease.token},
    ).first()
    if row is None:
        raise Problem(409, "lease_lost", "A execução perdeu a autorização para publicar.")
    # A committed deletion intent remains authorized after later ACL changes.
    # Its worker can only remove the object keys saved by that intent, never read/publish content.
    if current_policy != lease.policy_revision and lease.kind != "purge":
        raise Problem(
            409,
            "policy_changed",
            "As permissões mudaram durante a execução. Inicie uma nova investigação.",
        )


def renew(lease: Lease) -> bool:
    with transaction(lease.tenant_id) as connection:
        count = connection.execute(
            text("""
            UPDATE jobs SET lease_until=now()+make_interval(secs=>:lease)
            WHERE tenant_id=:tenant AND id=:id AND fencing_token=:token AND state='running'
              AND lease_until>now() AND deadline>now() AND NOT cancel_requested
        """),
            {
                "tenant": lease.tenant_id,
                "id": lease.job_id,
                "token": lease.token,
                "lease": get_settings().job_lease_seconds,
            },
        ).rowcount
        if count == 1:
            connection.execute(
                text("""
                INSERT INTO worker_heartbeats(worker_id,observed_at)
                SELECT worker_id,now() FROM jobs WHERE tenant_id=:tenant AND id=:id AND worker_id IS NOT NULL
                ON CONFLICT(worker_id) DO UPDATE SET observed_at=excluded.observed_at
            """),
                {"tenant": lease.tenant_id, "id": lease.job_id},
            )
        return count == 1


def retry_transient(lease: Lease, code: str) -> bool:
    """Only failures before paid dispatch may repeat automatically, at most three times."""
    if code not in {
        "provider_capacity",
        "provider_circuit_open",
        "storage_unavailable",
        "model_service_busy",
        "model_service_timeout",
        "model_service_unavailable",
    }:
        return False
    with transaction(lease.tenant_id) as connection:
        assert_publishable(connection, lease)
        dispatched = connection.execute(
            text(
                "SELECT EXISTS(SELECT 1 FROM provider_calls WHERE tenant_id=:tenant AND run_id=:run AND status NOT IN('reserved','released'))"
            ),
            {"tenant": lease.tenant_id, "run": lease.resource_id},
        ).scalar_one()
        if dispatched:
            return False
        row = (
            connection.execute(
                text(
                    "SELECT attempt,deadline>now()+interval '65 seconds' AS time_left FROM jobs WHERE tenant_id=:tenant AND id=:id"
                ),
                {"tenant": lease.tenant_id, "id": lease.job_id},
            )
            .mappings()
            .one()
        )
        if row["attempt"] >= 3 or not row["time_left"]:
            return False
        delay = min(60, 2 ** row["attempt"] + random.uniform(0.1, 1.0))
        connection.execute(
            text("""
            UPDATE jobs SET state='retry_wait',stage='retry_wait',lease_until=NULL,available_at=now()+make_interval(secs=>:delay),error=CAST(:error AS jsonb)
            WHERE tenant_id=:tenant AND id=:id AND fencing_token=:token
        """),
            {
                "tenant": lease.tenant_id,
                "id": lease.job_id,
                "token": lease.token,
                "delay": delay,
                "error": json.dumps(
                    {"code": code, "message": "Aguardando uma nova tentativa dentro do prazo."}
                ),
            },
        )
        if lease.kind == "investigation":
            from evidencedesk.investigations.service import append_event

            update_steps(connection, lease.tenant_id, lease.resource_id, "retry_wait")

            append_event(
                connection,
                lease.tenant_id,
                lease.resource_id,
                "progress",
                {"state": "retry_wait", "stage": "retry_wait"},
            )
        return True


def complete(connection: Connection, lease: Lease) -> None:
    assert_publishable(connection, lease)
    connection.execute(
        text(
            "UPDATE jobs SET state='succeeded',stage='complete',completed_at=now(),lease_until=NULL WHERE tenant_id=:tenant AND id=:id"
        ),
        {"tenant": lease.tenant_id, "id": lease.job_id},
    )
    if lease.kind == "investigation":
        update_steps(connection, lease.tenant_id, lease.resource_id, "succeeded")


def fail(lease: Lease, code: str, message: str) -> None:
    with transaction(lease.tenant_id) as connection:
        lock_policy(connection, lease.tenant_id)
        changed = connection.execute(
            text("""
            UPDATE jobs SET state='failed',stage='failed',completed_at=now(),lease_until=NULL,error=CAST(:error AS jsonb)
            WHERE tenant_id=:tenant AND id=:id AND fencing_token=:token AND state='running'
        """),
            {
                "tenant": lease.tenant_id,
                "id": lease.job_id,
                "token": lease.token,
                "error": json.dumps({"code": code, "message": message}),
            },
        ).rowcount
        if changed and lease.kind == "investigation":
            from evidencedesk.investigations.service import append_event

            update_steps(connection, lease.tenant_id, lease.resource_id, "failed")
            append_event(
                connection,
                lease.tenant_id,
                lease.resource_id,
                "terminal",
                {"state": "failed", "stage": "failed", "error": {"code": code, "message": message}},
            )


def cancel(connection: Connection, actor: Actor, resource_id: str) -> None:
    row = (
        connection.execute(
            text("SELECT * FROM jobs WHERE tenant_id=:tenant AND resource_id=:resource FOR UPDATE"),
            {"tenant": actor.tenant_id, "resource": resource_id},
        )
        .mappings()
        .first()
    )
    if row is None:
        raise not_found()
    if row["state"] in {"succeeded", "failed", "cancelled"}:
        return
    connection.execute(
        text("""
        UPDATE jobs SET state='cancelled',cancel_requested=true,stage='cancelled',completed_at=now(),
        fencing_token=fencing_token+1,lease_until=NULL WHERE tenant_id=:tenant AND id=:id
    """),
        {"tenant": actor.tenant_id, "id": row["id"]},
    )
    if row["kind"] == "investigation":
        update_steps(connection, actor.tenant_id, resource_id, "cancelled")
