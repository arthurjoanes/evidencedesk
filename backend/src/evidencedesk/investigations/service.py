import json
from uuid import uuid4

from sqlalchemy import Connection, text

from evidencedesk.config import get_settings
from evidencedesk.errors import Problem, not_found
from evidencedesk.evidence.service import authorize_snapshot
from evidencedesk.identity.service import Actor, authorize_incident
from evidencedesk.jobs.service import enqueue, idempotent_resource
from evidencedesk.model_runtime.release import freeze_release


def authorize_run(connection: Connection, actor: Actor, run_id: str) -> dict:
    row = (
        connection.execute(
            text("SELECT * FROM investigation_runs WHERE tenant_id=:tenant AND id=:id"),
            {"tenant": actor.tenant_id, "id": run_id},
        )
        .mappings()
        .first()
    )
    if row is None or row.get("tombstoned_at") is not None:
        raise not_found()
    authorize_incident(connection, actor, row["incident_id"])
    if row["dossier_id"]:
        from evidencedesk.reviews.service import authorize_dossier

        authorize_dossier(connection, actor, row["dossier_id"])
    return dict(row)


def run_payload(connection: Connection, actor: Actor, run_id: str) -> dict:
    run = authorize_run(connection, actor, run_id)
    job = (
        connection.execute(
            text(
                "SELECT * FROM jobs WHERE tenant_id=:tenant AND kind='investigation' AND resource_id=:id"
            ),
            {"tenant": actor.tenant_id, "id": run_id},
        )
        .mappings()
        .one()
    )
    return {
        "id": run_id,
        "state": job["state"],
        "stage": job["stage"],
        "outcome": run["outcome"],
        "created_at": run["created_at"],
        "steps": run["steps"],
        "cancel_requested": job["cancel_requested"],
        "last_event_id": run["last_event_id"],
        "evidence_snapshot_id": run["snapshot_id"],
        "dossier_id": run["dossier_id"],
        "revision_id": run["revision_id"],
        "error": job["error"],
        "started_at": job["started_at"],
        "completed_at": job["completed_at"],
        "usage": run["usage"],
    }


def create_run(
    connection: Connection,
    actor: Actor,
    incident_id: str,
    snapshot_id: str,
    question: str,
    key: str | None,
    policy: int,
) -> str:
    incident = authorize_incident(connection, actor, incident_id)
    authorize_snapshot(connection, actor, snapshot_id, incident["collection_id"])
    run_id, created = idempotent_resource(
        connection,
        actor,
        f"run:{incident_id}",
        key,
        {"evidence_snapshot_id": snapshot_id, "question": question},
        uuid4().hex,
    )
    if not created:
        authorize_run(connection, actor, run_id)
        return run_id
    if not get_settings().generation_enabled:
        raise Problem(
            503,
            "generator_unavailable",
            "O gerador não está configurado. Continue com a investigação manual.",
        )
    active = connection.execute(
        text(
            "SELECT count(*) FROM jobs WHERE tenant_id=:tenant AND actor_id=:actor AND kind='investigation' AND state IN('queued','running','retry_wait')"
        ),
        {"tenant": actor.tenant_id, "actor": actor.id},
    ).scalar_one()
    if active:
        raise Problem(
            429,
            "investigation_in_progress",
            "Aguarde ou cancele sua investigação atual antes de iniciar outra.",
            retryable=True,
        )
    release = freeze_release(get_settings()).model_dump(mode="json")
    connection.execute(
        text("""
        INSERT INTO investigation_runs(tenant_id,id,incident_id,snapshot_id,created_by,question,policy_revision,model_release)
        VALUES(:tenant,:id,:incident,:snapshot,:actor,:question,:policy,CAST(:release AS jsonb))
    """),
        {
            "tenant": actor.tenant_id,
            "id": run_id,
            "incident": incident_id,
            "snapshot": snapshot_id,
            "actor": actor.id,
            "question": question,
            "policy": policy,
            "release": json.dumps(release),
        },
    )
    enqueue(connection, actor, "investigation", run_id, policy)
    append_event(
        connection, actor.tenant_id, run_id, "progress", {"state": "queued", "stage": "queued"}
    )
    return run_id


def append_event(
    connection: Connection, tenant_id: str, run_id: str, event_type: str, payload: dict
) -> int:
    seq = connection.execute(
        text(
            "UPDATE investigation_runs SET last_event_id=last_event_id+1 WHERE tenant_id=:tenant AND id=:id RETURNING last_event_id"
        ),
        {"tenant": tenant_id, "id": run_id},
    ).scalar_one()
    connection.execute(
        text(
            "INSERT INTO run_events(tenant_id,run_id,seq,type,payload) VALUES(:tenant,:id,:seq,:type,CAST(:payload AS jsonb))"
        ),
        {
            "tenant": tenant_id,
            "id": run_id,
            "seq": seq,
            "type": event_type,
            "payload": json.dumps(payload),
        },
    )
    return seq
