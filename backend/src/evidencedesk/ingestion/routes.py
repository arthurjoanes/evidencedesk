import asyncio
from threading import BoundedSemaphore

from fastapi import APIRouter, Request
from sqlalchemy import text

from evidencedesk.api import CurrentActor, PageLimit
from evidencedesk.audit import record_action
from evidencedesk.database import lock_policy, transaction
from evidencedesk.errors import Problem
from evidencedesk.ingestion.contracts import ImportInput
from evidencedesk.ingestion.service import (
    abandon_upload,
    create_import,
    finalize_import,
    finish_upload,
    import_payload,
    reserve_upload,
)
from evidencedesk.pagination import decode_recent_cursor, recent_page

router = APIRouter(prefix="/imports", tags=["Importação"])
UPLOAD_SLOTS = BoundedSemaphore(4)


@router.post("", status_code=201)
def new_import(body: ImportInput, actor: CurrentActor) -> dict:
    with transaction(actor.tenant_id) as connection:
        policy = lock_policy(connection, actor.tenant_id, mutation=True)
        import_id = create_import(connection, actor, body)
        record_action(connection, actor, "import.created", import_id, policy)
        return import_payload(connection, actor, import_id)


@router.get("")
def list_imports(actor: CurrentActor, cursor: str | None = None, limit: PageLimit = 30) -> dict:
    context = {
        "tenant": actor.tenant_id,
        "user": actor.id,
        "operation": "imports",
        "ordering": "created_at_desc_id_desc_v1",
    }
    after_date, after_id = decode_recent_cursor(cursor, context)
    with transaction(actor.tenant_id) as connection:
        rows = (
            connection.execute(
                text("""
            SELECT b.id,b.created_at FROM import_batches b
            JOIN collection_grants g ON g.tenant_id=b.tenant_id AND g.collection_id=b.collection_id
            JOIN collections c ON c.tenant_id=b.tenant_id AND c.id=b.collection_id
            WHERE b.tenant_id=:tenant AND g.user_id=:user AND c.tombstoned_at IS NULL
              AND (CAST(:after_date AS timestamptz) IS NULL OR (b.created_at,b.id)<(:after_date,:after_id))
            ORDER BY b.created_at DESC,b.id DESC LIMIT :limit
        """),
                {
                    "tenant": actor.tenant_id,
                    "user": actor.id,
                    "after_date": after_date,
                    "after_id": after_id,
                    "limit": limit + 1,
                },
            )
            .mappings()
            .all()
        )
        result = recent_page([dict(row) for row in rows], limit, context)
        result["items"] = [
            import_payload(connection, actor, item["id"]) for item in result["items"]
        ]
        return result


@router.get("/{import_id}")
def get_import(import_id: str, actor: CurrentActor) -> dict:
    with transaction(actor.tenant_id) as connection:
        return import_payload(connection, actor, import_id)


@router.put("/{import_id}/files/{entry_id}")
async def upload_file(import_id: str, entry_id: str, actor: CurrentActor, request: Request) -> dict:
    if not UPLOAD_SLOTS.acquire(blocking=False):
        raise Problem(
            503,
            "upload_capacity",
            "A capacidade de envio está ocupada. Tente novamente em instantes.",
            retryable=True,
        )
    try:
        return await receive_file(import_id, entry_id, actor, request)
    finally:
        UPLOAD_SLOTS.release()


async def receive_file(
    import_id: str, entry_id: str, actor: CurrentActor, request: Request
) -> dict:
    entry = await asyncio.to_thread(reserve_upload, actor, import_id, entry_id)
    try:
        if request.headers.get("content-type", "").split(";")[0] != entry["media_type"]:
            raise Problem(
                422, "media_type_mismatch", "O tipo do envio não corresponde ao manifesto."
            )
        content = bytearray()
        async with asyncio.timeout(90):
            async for chunk in request.stream():
                content.extend(chunk)
                if len(content) > entry["byte_size"]:
                    raise Problem(
                        413, "upload_too_large", "O envio excede o tamanho declarado no manifesto."
                    )
        await asyncio.to_thread(finish_upload, actor, import_id, entry, bytes(content))
    except BaseException:
        await asyncio.to_thread(abandon_upload, actor, import_id, entry)
        raise
    return await asyncio.to_thread(get_import, import_id, actor)


@router.post("/{import_id}/finalize", status_code=202)
def finalize(import_id: str, actor: CurrentActor) -> dict:
    with transaction(actor.tenant_id) as connection:
        policy = lock_policy(connection, actor.tenant_id, mutation=True)
        finalize_import(connection, actor, import_id, policy)
        record_action(connection, actor, "import.sealed", import_id, policy)
        return import_payload(connection, actor, import_id)
