from fastapi import APIRouter
from fastapi.responses import FileResponse

from evidencedesk.api import CurrentActor
from evidencedesk.database import transaction
from evidencedesk.errors import Problem
from evidencedesk.evidence.service import evidence_payload, resolve_evidence
from evidencedesk.evidence.storage import PrivateStorage

router = APIRouter(prefix="/evidence", tags=["Evidências"])


@router.get("/{evidence_id}")
def get_evidence(evidence_id: str, evidence_snapshot_id: str, actor: CurrentActor) -> dict:
    with transaction(actor.tenant_id) as connection:
        return evidence_payload(
            resolve_evidence(connection, actor, evidence_id, evidence_snapshot_id),
            evidence_snapshot_id,
        )


@router.get("/{evidence_id}/content")
def original_content(
    evidence_id: str, evidence_snapshot_id: str, actor: CurrentActor
) -> FileResponse:
    with transaction(actor.tenant_id) as connection:
        evidence = resolve_evidence(connection, actor, evidence_id, evidence_snapshot_id)
    if not evidence["original_key"]:
        raise Problem(404, "no_original", "Esta evidência não possui arquivo original.")
    path = PrivateStorage().path(evidence["original_key"])
    if not path.is_file():
        raise Problem(
            503,
            "storage_unavailable",
            "O original está temporariamente indisponível.",
            retryable=True,
        )
    return FileResponse(
        path,
        media_type=evidence["media_type"],
        headers={
            "X-Content-Type-Options": "nosniff",
            "Content-Security-Policy": "default-src 'none'; sandbox",
        },
    )
