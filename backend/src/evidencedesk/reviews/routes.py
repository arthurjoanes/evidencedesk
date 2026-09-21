from typing import Literal
from uuid import uuid4

from fastapi import APIRouter, Header, Response
from fastapi.responses import FileResponse
from pydantic import Field
from sqlalchemy import text

from evidencedesk.api import CurrentActor, Input, PageLimit
from evidencedesk.audit import record_action
from evidencedesk.database import lock_policy, transaction
from evidencedesk.errors import Problem, not_found
from evidencedesk.evidence.storage import PrivateStorage
from evidencedesk.identity.service import authorize_incident
from evidencedesk.jobs.service import enqueue, idempotent_resource
from evidencedesk.pagination import decode_cursor, encode_cursor, page
from evidencedesk.reviews.contracts import ManualDossierInput, RevisionInput
from evidencedesk.reviews.service import (
    assert_base_revision,
    authorize_dossier,
    create_dossier,
    dossier_payload,
    review_revision,
    revision_payload,
    submit_revision,
    write_revision,
)

router = APIRouter(tags=["Dossiês e revisão"])


class RevisionTarget(Input):
    target_revision_id: str = Field(min_length=1, max_length=200)


class ReviewInput(RevisionTarget):
    claim_ids: list[str] = Field(max_length=30)
    decision: Literal["approved", "changes_requested"]
    reason: str = Field(min_length=5, max_length=3000)


class ExportInput(Input):
    revision_id: str = Field(min_length=1, max_length=200)


@router.get("/incidents/{incident_id}/dossiers")
def list_dossiers(
    incident_id: str, actor: CurrentActor, cursor: str | None = None, limit: PageLimit = 30
) -> dict:
    context = {
        "tenant": actor.tenant_id,
        "user": actor.id,
        "incident": incident_id,
        "operation": "dossiers",
    }
    after = decode_cursor(cursor, context)
    with transaction(actor.tenant_id) as connection:
        authorize_incident(connection, actor, incident_id)
        visible = []
        exhausted = False
        # Bound each scan, but keep a continuation even when revoked results fill it.
        # Otherwise an empty filtered page would silently hide later visible dossiers.
        for _ in range(5):
            rows = (
                connection.execute(
                    text("""
                SELECT id,origin,created_at,approved_revision_id,current_revision_id FROM dossiers
                WHERE tenant_id=:tenant AND incident_id=:incident AND id>:after AND tombstoned_at IS NULL
                ORDER BY id LIMIT :limit
            """),
                    {
                        "tenant": actor.tenant_id,
                        "incident": incident_id,
                        "after": after,
                        "limit": limit + 1,
                    },
                )
                .mappings()
                .all()
            )
            exhausted = len(rows) < limit + 1
            for row in rows:
                after = row["id"]
                try:
                    authorize_dossier(connection, actor, row["id"])
                    visible.append(dict(row))
                except Problem as error:
                    if error.status != 404:
                        raise
                if len(visible) > limit:
                    return page(visible, limit, context)
            if exhausted:
                break
        result = page(visible, limit, context)
        if not exhausted:
            result["next_cursor"] = encode_cursor(context, after)
        return result


@router.post("/incidents/{incident_id}/dossiers", status_code=201)
def new_manual_dossier(incident_id: str, body: ManualDossierInput, actor: CurrentActor) -> dict:
    with transaction(actor.tenant_id) as connection:
        policy = lock_policy(connection, actor.tenant_id, mutation=True)
        dossier_id, _ = create_dossier(
            connection, actor, incident_id, body.evidence_snapshot_id, body
        )
        record_action(
            connection, actor, "dossier.created", dossier_id, policy, {"origin": "manual"}
        )
        return dossier_payload(connection, actor, dossier_id)


@router.get("/dossiers/{dossier_id}")
def get_dossier(dossier_id: str, actor: CurrentActor) -> dict:
    with transaction(actor.tenant_id) as connection:
        return dossier_payload(connection, actor, dossier_id)


@router.get("/dossiers/{dossier_id}/revisions/{revision_id}")
def get_revision(
    dossier_id: str, revision_id: str, actor: CurrentActor, response: Response
) -> dict:
    with transaction(actor.tenant_id) as connection:
        result = revision_payload(connection, actor, dossier_id, revision_id)
        response.headers["ETag"] = result["etag"]
        return result


@router.post("/dossiers/{dossier_id}/revisions", status_code=201)
def new_revision(
    dossier_id: str,
    body: RevisionInput,
    actor: CurrentActor,
    response: Response,
    if_match: str | None = Header(default=None),
) -> dict:
    with transaction(actor.tenant_id) as connection:
        policy = lock_policy(connection, actor.tenant_id, mutation=True)
        base = assert_base_revision(connection, actor, dossier_id, body.base_revision_id, if_match)
        dossier = authorize_dossier(connection, actor, dossier_id)
        revision_id = write_revision(connection, actor, dossier, body, base)
        record_action(
            connection,
            actor,
            "revision.created",
            revision_id,
            policy,
            {"base_revision_id": body.base_revision_id},
        )
        result = revision_payload(connection, actor, dossier_id, revision_id)
        response.headers["ETag"] = result["etag"]
        return result


@router.post("/dossiers/{dossier_id}/submit")
def submit(
    dossier_id: str,
    body: RevisionTarget,
    actor: CurrentActor,
    if_match: str | None = Header(default=None),
) -> dict:
    with transaction(actor.tenant_id) as connection:
        policy = lock_policy(connection, actor.tenant_id, mutation=True)
        submit_revision(connection, actor, dossier_id, body.target_revision_id, if_match)
        record_action(connection, actor, "revision.submitted", body.target_revision_id, policy)
        return revision_payload(connection, actor, dossier_id, body.target_revision_id)


@router.post("/dossiers/{dossier_id}/reviews")
def decide(
    dossier_id: str,
    body: ReviewInput,
    actor: CurrentActor,
    if_match: str | None = Header(default=None),
) -> dict:
    with transaction(actor.tenant_id) as connection:
        policy = lock_policy(connection, actor.tenant_id, mutation=True)
        review_revision(
            connection,
            actor,
            dossier_id,
            body.target_revision_id,
            if_match,
            body.decision,
            body.reason,
            body.claim_ids,
        )
        record_action(
            connection,
            actor,
            "revision.reviewed",
            body.target_revision_id,
            policy,
            {"decision": body.decision},
        )
        return revision_payload(connection, actor, dossier_id, body.target_revision_id)


def export_payload(connection, actor, export_id: str) -> dict:
    row = (
        connection.execute(
            text("""
        SELECT e.*,j.state,j.error,e.expires_at>now() AS valid FROM exports e
        JOIN jobs j ON j.tenant_id=e.tenant_id AND j.resource_id=e.id AND j.kind='export'
        WHERE e.tenant_id=:tenant AND e.id=:id
    """),
            {"tenant": actor.tenant_id, "id": export_id},
        )
        .mappings()
        .first()
    )
    if row is None:
        raise not_found()
    authorize_dossier(connection, actor, row["dossier_id"])
    ready = row["state"] == "succeeded" and row["valid"]
    return {
        "id": row["id"],
        "state": row["state"] if row["valid"] is not False else "expired",
        "revision_id": row["revision_id"],
        "download_url": f"/api/v1/exports/{export_id}/download" if ready else None,
        "expires_at": row["expires_at"],
        "error": row["error"],
    }


@router.post("/dossiers/{dossier_id}/exports", status_code=202)
def new_export(
    dossier_id: str,
    body: ExportInput,
    actor: CurrentActor,
    idempotency_key: str | None = Header(default=None),
) -> dict:
    with transaction(actor.tenant_id) as connection:
        policy = lock_policy(connection, actor.tenant_id, mutation=True)
        revision = revision_payload(connection, actor, dossier_id, body.revision_id)
        if revision["review_status"] != "approved":
            raise Problem(409, "approval_required", "A exportação exige uma revisão aprovada.")
        export_id, created = idempotent_resource(
            connection,
            actor,
            f"export:{dossier_id}",
            idempotency_key,
            body.model_dump(),
            uuid4().hex,
        )
        if created:
            connection.execute(
                text(
                    "INSERT INTO exports(tenant_id,id,dossier_id,revision_id,created_by) VALUES(:tenant,:id,:dossier,:revision,:actor)"
                ),
                {
                    "tenant": actor.tenant_id,
                    "id": export_id,
                    "dossier": dossier_id,
                    "revision": body.revision_id,
                    "actor": actor.id,
                },
            )
            enqueue(connection, actor, "export", export_id, policy)
            record_action(connection, actor, "export.requested", export_id, policy)
        return export_payload(connection, actor, export_id)


@router.get("/exports/{export_id}")
def get_export(export_id: str, actor: CurrentActor) -> dict:
    with transaction(actor.tenant_id) as connection:
        return export_payload(connection, actor, export_id)


@router.get("/exports/{export_id}/download")
def download_export(export_id: str, actor: CurrentActor) -> FileResponse:
    with transaction(actor.tenant_id) as connection:
        payload = export_payload(connection, actor, export_id)
        if payload["download_url"] is None:
            raise Problem(
                409, "export_unavailable", "A exportação ainda não está disponível ou expirou."
            )
        key = connection.execute(
            text("SELECT object_key FROM exports WHERE tenant_id=:tenant AND id=:id"),
            {"tenant": actor.tenant_id, "id": export_id},
        ).scalar_one()
    path = PrivateStorage().path(key)
    if not path.is_file():
        raise Problem(
            503,
            "storage_unavailable",
            "O arquivo está temporariamente indisponível.",
            retryable=True,
        )
    return FileResponse(
        path,
        media_type="text/html",
        filename=f"evidencedesk-{export_id}.html",
        headers={
            "Content-Security-Policy": "default-src 'none'; style-src 'unsafe-inline'",
            "X-Content-Type-Options": "nosniff",
        },
    )
