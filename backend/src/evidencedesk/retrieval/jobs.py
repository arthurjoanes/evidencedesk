"""Durable, authorized indexing; the HTTP process never loads model weights."""

import httpx
from fastapi import APIRouter, Header
from sqlalchemy import Connection, text

from evidencedesk.api import CurrentActor
from evidencedesk.audit import record_action
from evidencedesk.config import get_settings
from evidencedesk.database import get_engine, lock_policy, transaction
from evidencedesk.errors import Problem
from evidencedesk.evidence.service import authorize_snapshot
from evidencedesk.identity.service import Actor, actor_for_worker
from evidencedesk.jobs.service import (
    Lease,
    assert_publishable,
    complete,
    enqueue,
    idempotent_resource,
)
from evidencedesk.retrieval.http_client import MODEL_SERVICE_URL, RemoteModels
from evidencedesk.retrieval.http_contracts import ModelServiceError
from evidencedesk.retrieval.local_models import EMBEDDING_REVISION
from evidencedesk.retrieval.repository import index_snapshot

router = APIRouter(prefix="/evidence-snapshots", tags=["Índice documental"])


def index_payload(connection: Connection, actor: Actor, snapshot_id: str) -> dict:
    authorize_snapshot(connection, actor, snapshot_id)
    counts = (
        connection.execute(
            text("""
        SELECT count(*) AS total_documents,
               count(*) FILTER(WHERE e.embedding IS NOT NULL AND e.embedding_revision=:revision) AS indexed_documents
        FROM evidence e JOIN snapshot_members sm ON sm.tenant_id=e.tenant_id AND sm.evidence_id=e.id
        WHERE e.tenant_id=:tenant AND sm.snapshot_id=:snapshot AND e.kind='document_span' AND e.tombstoned_at IS NULL
    """),
            {"tenant": actor.tenant_id, "snapshot": snapshot_id, "revision": EMBEDDING_REVISION},
        )
        .mappings()
        .one()
    )
    job = (
        connection.execute(
            text("""
        SELECT id,state,stage,error,attempt FROM jobs
        WHERE tenant_id=:tenant AND kind='index_snapshot' AND resource_id=:snapshot
    """),
            {"tenant": actor.tenant_id, "snapshot": snapshot_id},
        )
        .mappings()
        .first()
    )
    return {
        "evidence_snapshot_id": snapshot_id,
        "indexing_enabled": len(get_settings().model_service_token.get_secret_value()) >= 24,
        "disabled_reason": None
        if len(get_settings().model_service_token.get_secret_value()) >= 24
        else "O serviço privado de modelos não está configurado.",
        "embedding_revision": EMBEDDING_REVISION,
        **dict(counts),
        "complete": counts["total_documents"] == counts["indexed_documents"],
        "job": dict(job) if job else None,
    }


@router.get("/{snapshot_id}/index")
def get_index(snapshot_id: str, actor: CurrentActor) -> dict:
    with transaction(actor.tenant_id) as connection:
        return index_payload(connection, actor, snapshot_id)


@router.post("/{snapshot_id}/index", status_code=202)
def request_index(
    snapshot_id: str, actor: CurrentActor, idempotency_key: str | None = Header(default=None)
) -> dict:
    with transaction(actor.tenant_id) as connection:
        policy = lock_policy(connection, actor.tenant_id, mutation=True)
        state = index_payload(connection, actor, snapshot_id)
        idempotent_resource(
            connection,
            actor,
            "index_snapshot",
            idempotency_key,
            {"snapshot_id": snapshot_id, "revision": EMBEDDING_REVISION},
            snapshot_id,
        )
        if state["complete"] or state["job"] is not None:
            return state
        if len(get_settings().model_service_token.get_secret_value()) < 24:
            raise Problem(
                503, "model_service_configuration", "Configure o perfil privado de modelos."
            )
        enqueue(connection, actor, "index_snapshot", snapshot_id, policy)
        return index_payload(connection, actor, snapshot_id)


def process_index(lease: Lease) -> None:
    with transaction(lease.tenant_id) as connection:
        assert_publishable(connection, lease)
        actor = actor_for_worker(connection, lease.tenant_id, lease.actor_id)
        authorize_snapshot(connection, actor, lease.resource_id)
    token = get_settings().model_service_token.get_secret_value()
    if len(token) < 24:
        raise Problem(503, "model_service_configuration", "Configure o perfil privado de modelos.")
    try:
        with httpx.Client(
            base_url=MODEL_SERVICE_URL,
            trust_env=False,
            limits=httpx.Limits(max_connections=1, max_keepalive_connections=1),
        ) as client:
            result = index_snapshot(
                get_engine(),
                actor,
                lease.resource_id,
                RemoteModels(client, token=token),
                guard=lambda connection: assert_publishable(connection, lease),
            )
    except ModelServiceError as error:
        raise Problem(
            422 if error.code in {"model_query_too_long", "evidence_requires_rechunking"} else 503,
            error.code,
            "Divida a fonte em trechos menores e importe uma nova versão."
            if error.code == "evidence_requires_rechunking"
            else "A indexação aguarda o serviço privado de modelos.",
            retryable=error.retryable,
        ) from None
    with transaction(lease.tenant_id) as connection:
        assert_publishable(connection, lease)
        record_action(
            connection,
            actor,
            "index.completed",
            lease.resource_id,
            lease.policy_revision,
            result.model_dump(),
        )
        complete(connection, lease)
