import json
from typing import Literal
from uuid import uuid4

from fastapi import APIRouter, Header
from pydantic import Field
from sqlalchemy import text

from evidencedesk.api import CurrentActor, Input, PageLimit
from evidencedesk.audit import record_action
from evidencedesk.database import lock_policy, transaction
from evidencedesk.errors import Problem, not_found
from evidencedesk.identity.service import Actor, authorize_collection
from evidencedesk.jobs.service import cancel, enqueue, idempotent_resource
from evidencedesk.maintenance import MaintenanceFailure, record_deletion
from evidencedesk.pagination import decode_cursor, page

router = APIRouter(prefix="/admin", tags=["Administração da organização"])


def require_admin(actor: Actor) -> None:
    if actor.role != "tenant_admin":
        raise Problem(
            403, "tenant_admin_required", "A operação exige um administrador da organização."
        )


class CollectionInput(Input):
    name: str = Field(min_length=3, max_length=120)
    description: str = Field(default="", max_length=1000)


class GrantInput(Input):
    granted: bool
    incident_ids: list[str] = Field(default_factory=list, max_length=100)


class DeletionInput(Input):
    reason: Literal["user_request", "expired", "incorrect_source", "security"]


@router.get("/users")
def users(actor: CurrentActor) -> dict:
    require_admin(actor)
    with transaction(actor.tenant_id) as connection:
        rows = (
            connection.execute(
                text(
                    "SELECT id,name,email,role,enabled FROM users WHERE tenant_id=:tenant ORDER BY name,id LIMIT 100"
                ),
                {"tenant": actor.tenant_id},
            )
            .mappings()
            .all()
        )
        return {"items": [dict(row) for row in rows], "next_cursor": None, "total": len(rows)}


@router.post("/collections", status_code=201)
def create_collection(body: CollectionInput, actor: CurrentActor) -> dict:
    require_admin(actor)
    with transaction(actor.tenant_id) as connection:
        policy = lock_policy(connection, actor.tenant_id, mutation=True)
        identity = uuid4().hex
        connection.execute(
            text(
                "INSERT INTO collections(tenant_id,id,name,description) VALUES(:tenant,:id,:name,:description)"
            ),
            {"tenant": actor.tenant_id, "id": identity, **body.model_dump()},
        )
        connection.execute(
            text(
                "INSERT INTO collection_grants(tenant_id,collection_id,user_id) VALUES(:tenant,:id,:user)"
            ),
            {"tenant": actor.tenant_id, "id": identity, "user": actor.id},
        )
        record_action(connection, actor, "collection.created", identity, policy)
        return {"id": identity, **body.model_dump(), "active_snapshot_id": None}


@router.put("/collections/{collection_id}/members/{user_id}")
def change_grant(collection_id: str, user_id: str, body: GrantInput, actor: CurrentActor) -> dict:
    require_admin(actor)
    with transaction(actor.tenant_id) as connection:
        lock_policy(connection, actor.tenant_id, mutation=True)
        authorize_collection(connection, actor, collection_id)
        user = connection.execute(
            text("SELECT id FROM users WHERE tenant_id=:tenant AND id=:user AND enabled"),
            {"tenant": actor.tenant_id, "user": user_id},
        ).first()
        if user is None:
            raise not_found()
        if body.granted:
            visible = (
                connection.execute(
                    text(
                        "SELECT id FROM incidents WHERE tenant_id=:tenant AND collection_id=:collection AND id=ANY(:ids)"
                    ),
                    {
                        "tenant": actor.tenant_id,
                        "collection": collection_id,
                        "ids": body.incident_ids,
                    },
                )
                .scalars()
                .all()
            )
            if set(visible) != set(body.incident_ids):
                raise not_found()
            connection.execute(
                text(
                    "INSERT INTO collection_grants(tenant_id,collection_id,user_id) VALUES(:tenant,:collection,:user) ON CONFLICT DO NOTHING"
                ),
                {"tenant": actor.tenant_id, "collection": collection_id, "user": user_id},
            )
            if visible:
                connection.execute(
                    text(
                        "INSERT INTO incident_members(tenant_id,incident_id,user_id) VALUES(:tenant,:incident,:user) ON CONFLICT DO NOTHING"
                    ),
                    [
                        {"tenant": actor.tenant_id, "incident": identity, "user": user_id}
                        for identity in visible
                    ],
                )
        else:
            connection.execute(
                text(
                    "DELETE FROM collection_grants WHERE tenant_id=:tenant AND collection_id=:collection AND user_id=:user"
                ),
                {"tenant": actor.tenant_id, "collection": collection_id, "user": user_id},
            )
            connection.execute(
                text(
                    "DELETE FROM incident_members WHERE tenant_id=:tenant AND user_id=:user AND incident_id IN(SELECT id FROM incidents WHERE tenant_id=:tenant AND collection_id=:collection)"
                ),
                {"tenant": actor.tenant_id, "collection": collection_id, "user": user_id},
            )
            resources = (
                connection.execute(
                    text(
                        "SELECT resource_id FROM jobs WHERE tenant_id=:tenant AND actor_id=:user AND kind<>'purge' AND state IN('queued','running','retry_wait')"
                    ),
                    {"tenant": actor.tenant_id, "user": user_id},
                )
                .scalars()
                .all()
            )
            for resource in resources:
                cancel(connection, actor, resource)
        policy = connection.execute(
            text(
                "UPDATE tenant_policy SET revision=revision+1 WHERE tenant_id=:tenant RETURNING revision"
            ),
            {"tenant": actor.tenant_id},
        ).scalar_one()
        record_action(
            connection,
            actor,
            "collection.grant_changed",
            collection_id,
            policy,
            {"user_id": user_id, "granted": body.granted},
        )
        return {
            "collection_id": collection_id,
            "user_id": user_id,
            "granted": body.granted,
            "policy_revision": policy,
        }


def deletion_payload(connection, actor: Actor, request_id: str) -> dict:
    row = (
        connection.execute(
            text("""
        SELECT d.id,d.evidence_id,d.created_at,d.completed_at,j.state,j.error FROM deletion_requests d
        JOIN jobs j ON j.tenant_id=d.tenant_id AND j.resource_id=d.id AND j.kind='purge'
        WHERE d.tenant_id=:tenant AND d.id=:id
    """),
            {"tenant": actor.tenant_id, "id": request_id},
        )
        .mappings()
        .first()
    )
    if row is None:
        raise not_found()
    return dict(row)


@router.delete("/evidence/{evidence_id}", status_code=202)
def delete_evidence(
    evidence_id: str,
    body: DeletionInput,
    actor: CurrentActor,
    idempotency_key: str | None = Header(default=None),
) -> dict:
    require_admin(actor)
    with transaction(actor.tenant_id) as connection:
        policy = lock_policy(connection, actor.tenant_id, mutation=True)
        source = (
            connection.execute(
                text(
                    "SELECT collection_id,sha256,tombstoned_at,kind FROM evidence WHERE tenant_id=:tenant AND id=:id"
                ),
                {"tenant": actor.tenant_id, "id": evidence_id},
            )
            .mappings()
            .first()
        )
        if source is None:
            raise not_found()
        authorize_collection(connection, actor, source["collection_id"])
        identity, created = idempotent_resource(
            connection,
            actor,
            f"delete:{evidence_id}",
            idempotency_key,
            body.model_dump(),
            uuid4().hex,
        )
        if not created:
            return deletion_payload(connection, actor, identity)
        if source["tombstoned_at"] is not None:
            raise Problem(409, "evidence_already_deleted", "Esta fonte já está excluída.")
        if source["kind"] == "reconciliation_result":
            raise Problem(
                409,
                "derived_evidence",
                "Este cálculo é derivado. A exclusão começa nas fontes originais que o compõem.",
            )
        # Admission and all expected constraint checks precede the independent ledger
        # append. A full queue must not leave a deletion intent for a rejected request.
        connection.execute(
            text(
                "INSERT INTO deletion_requests(tenant_id,id,evidence_id,requested_by,state) VALUES(:tenant,:id,:evidence,:user,'pending')"
            ),
            {
                "tenant": actor.tenant_id,
                "id": identity,
                "evidence": evidence_id,
                "user": actor.id,
            },
        )
        enqueue(connection, actor, "purge", identity, policy)
        try:
            deletion = record_deletion(connection, actor.tenant_id, evidence_id)
        except MaintenanceFailure:
            raise Problem(
                409,
                "deletion_not_ready",
                "A exclusão depende da conclusão de uploads ou da integridade do registro de exclusões.",
            ) from None
        connection.execute(
            text(
                "UPDATE deletion_requests SET object_keys=CAST(:keys AS jsonb),cleanup_id=:cleanup WHERE tenant_id=:tenant AND id=:id"
            ),
            {
                "tenant": actor.tenant_id,
                "id": identity,
                "evidence": evidence_id,
                "user": actor.id,
                "keys": json.dumps(deletion["object_keys"]),
                "cleanup": deletion["cleanup_id"],
            },
        )
        policy = connection.execute(
            text("SELECT revision FROM tenant_policy WHERE tenant_id=:tenant"),
            {"tenant": actor.tenant_id},
        ).scalar_one()
        record_action(
            connection,
            actor,
            "evidence.deleted",
            evidence_id,
            policy,
            {
                "deletion_request_id": identity,
                "ledger_sequence": deletion["sequence"],
                "reason_code": body.reason,
            },
        )
        return deletion_payload(connection, actor, identity)


@router.get("/deletions")
def list_deletions(actor: CurrentActor, cursor: str | None = None, limit: PageLimit = 30) -> dict:
    require_admin(actor)
    context = {"tenant": actor.tenant_id, "user": actor.id, "operation": "deletions"}
    after = decode_cursor(cursor, context)
    with transaction(actor.tenant_id) as connection:
        ids = (
            connection.execute(
                text(
                    "SELECT id FROM deletion_requests WHERE tenant_id=:tenant AND id>:after ORDER BY id LIMIT :limit"
                ),
                {"tenant": actor.tenant_id, "after": after, "limit": limit + 1},
            )
            .scalars()
            .all()
        )
        return page(
            [deletion_payload(connection, actor, identity) for identity in ids], limit, context
        )


@router.get("/deletions/{request_id}")
def get_deletion(request_id: str, actor: CurrentActor) -> dict:
    require_admin(actor)
    with transaction(actor.tenant_id) as connection:
        return deletion_payload(connection, actor, request_id)
