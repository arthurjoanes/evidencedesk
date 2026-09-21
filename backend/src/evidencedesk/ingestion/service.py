import hashlib
import json
from uuid import uuid4

from sqlalchemy import Connection, text

from evidencedesk.config import get_settings
from evidencedesk.database import lock_policy, transaction
from evidencedesk.errors import Problem, not_found
from evidencedesk.evidence.storage import PrivateStorage
from evidencedesk.identity.service import Actor, authorize_collection
from evidencedesk.ingestion.contracts import ImportInput
from evidencedesk.jobs.service import enqueue
from evidencedesk.retention.cleanup import complete_cleanup, enqueue_cleanup


def import_payload(connection: Connection, actor: Actor, import_id: str) -> dict:
    batch = (
        connection.execute(
            text(
                "SELECT b.*,j.state AS job_state,j.error AS job_error FROM import_batches b LEFT JOIN jobs j ON j.tenant_id=b.tenant_id AND j.resource_id=b.id AND j.kind='ingestion' WHERE b.tenant_id=:tenant AND b.id=:id"
            ),
            {"tenant": actor.tenant_id, "id": import_id},
        )
        .mappings()
        .first()
    )
    if batch is None:
        raise not_found()
    authorize_collection(connection, actor, batch["collection_id"])
    entries = (
        connection.execute(
            text(
                "SELECT id AS entry_id,filename,kind,byte_size,sha256,state,error FROM import_entries WHERE tenant_id=:tenant AND batch_id=:id ORDER BY id"
            ),
            {"tenant": actor.tenant_id, "id": import_id},
        )
        .mappings()
        .all()
    )
    state = batch["state"]
    if state in {"sealed", "processing"} and batch["job_state"] in {"failed", "cancelled"}:
        state = batch["job_state"]
    return {
        "id": batch["id"],
        "collection_id": batch["collection_id"],
        "title": batch["title"],
        "state": state,
        "created_at": batch["created_at"],
        "evidence_snapshot_id": batch["snapshot_id"],
        "entries": [dict(entry) for entry in entries],
        "error": batch["error"] or batch["job_error"],
    }


def create_import(connection: Connection, actor: Actor, body: ImportInput) -> str:
    authorize_collection(connection, actor, body.collection_id)
    if body.manifest.source_tenant not in {None, actor.tenant_id}:
        raise Problem(422, "tenant_mismatch", "O manifesto pertence a outra organização.")
    reject_deleted_hashes(
        connection,
        actor.tenant_id,
        body.collection_id,
        [entry.sha256 for entry in body.manifest.entries],
    )
    total = sum(entry.byte_size for entry in body.manifest.entries)
    count = connection.execute(
        text("""
        UPDATE tenant_policy SET storage_reserved=storage_reserved+:bytes
        WHERE tenant_id=:tenant AND storage_reserved+:bytes<=:maximum
    """),
        {
            "tenant": actor.tenant_id,
            "bytes": total,
            "maximum": get_settings().max_tenant_storage_bytes,
        },
    ).rowcount
    if count != 1:
        raise Problem(429, "storage_quota", "A organização atingiu a quota de armazenamento.")
    import_id = uuid4().hex
    connection.execute(
        text("""
        INSERT INTO import_batches(tenant_id,id,collection_id,created_by,title,manifest,state)
        VALUES(:tenant,:id,:collection,:actor,:title,CAST(:manifest AS jsonb),'receiving')
    """),
        {
            "tenant": actor.tenant_id,
            "id": import_id,
            "collection": body.collection_id,
            "actor": actor.id,
            "title": body.manifest.title,
            "manifest": body.manifest.model_dump_json(by_alias=True),
        },
    )
    connection.execute(
        text("""
        INSERT INTO import_entries(tenant_id,batch_id,id,filename,kind,media_type,byte_size,sha256,metadata,state,quota_bytes)
        VALUES(:tenant,:batch,:id,:filename,:kind,:media_type,:byte_size,:sha256,CAST(:metadata AS jsonb),'pending',:byte_size)
    """),
        [
            {
                "tenant": actor.tenant_id,
                "batch": import_id,
                "id": entry.entry_id,
                **entry.model_dump(exclude={"entry_id", "metadata"}),
                "metadata": json.dumps(entry.metadata),
            }
            for entry in body.manifest.entries
        ],
    )
    return import_id


def reserve_upload(actor: Actor, import_id: str, entry_id: str) -> dict:
    with transaction(actor.tenant_id) as connection:
        lock_policy(connection, actor.tenant_id, mutation=True)
        batch = import_payload(connection, actor, import_id)
        if batch["state"] != "receiving":
            raise Problem(409, "import_sealed", "O pacote já foi fechado para alterações.")
        row = (
            connection.execute(
                text(
                    "SELECT * FROM import_entries WHERE tenant_id=:tenant AND batch_id=:batch AND id=:id FOR UPDATE"
                ),
                {"tenant": actor.tenant_id, "batch": import_id, "id": entry_id},
            )
            .mappings()
            .first()
        )
        if row is None:
            raise not_found()
        if row["cleanup_id"] is not None or row["quota_released_at"] is not None:
            raise Problem(409, "import_expired", "A reserva deste arquivo já foi encerrada.")
        if row["state"] == "uploaded" and row["object_key"]:
            return dict(row) | {"already_uploaded": True}
        active = connection.execute(
            text(
                "SELECT count(*) FROM import_entries WHERE tenant_id=:tenant AND state='uploading' AND upload_until>now()"
            ),
            {"tenant": actor.tenant_id},
        ).scalar_one()
        if active >= 2:
            raise Problem(
                429,
                "tenant_upload_capacity",
                "Dois arquivos da organização já estão sendo enviados. Aguarde a conclusão.",
                retryable=True,
            )
        busy = connection.execute(
            text(
                "SELECT upload_until>now() FROM import_entries WHERE tenant_id=:tenant AND batch_id=:batch AND id=:id"
            ),
            {"tenant": actor.tenant_id, "batch": import_id, "id": entry_id},
        ).scalar_one()
        if row["state"] == "uploading" and busy:
            raise Problem(
                409, "upload_in_progress", "Já existe um envio deste arquivo em andamento."
            )
        if row["upload_token"] and not row["object_key"]:
            old_key = (
                f"tenants/{actor.tenant_id}/imports/{import_id}/{entry_id}/{row['upload_token']}"
            )
            cleanup = enqueue_cleanup(
                connection,
                actor.tenant_id,
                f"upload:{import_id}:{entry_id}:{row['upload_token']}",
                "orphan",
                [old_key],
            )
            result = complete_cleanup(connection, actor.tenant_id, cleanup)
            if result["state"] != "completed":
                raise Problem(
                    503,
                    "storage_unavailable",
                    "O envio anterior ainda precisa ser limpo.",
                    retryable=True,
                )
        token = uuid4().hex
        connection.execute(
            text(
                "UPDATE import_entries SET state='uploading',upload_token=:token,upload_until=now()+interval '2 minutes' WHERE tenant_id=:tenant AND batch_id=:batch AND id=:id"
            ),
            {"tenant": actor.tenant_id, "batch": import_id, "id": entry_id, "token": token},
        )
        connection.execute(
            text("UPDATE import_batches SET updated_at=now() WHERE tenant_id=:tenant AND id=:id"),
            {"tenant": actor.tenant_id, "id": import_id},
        )
        return dict(row) | {"upload_token": token}


def finish_upload(actor: Actor, import_id: str, entry: dict, content: bytes) -> None:
    if len(content) != entry["byte_size"] or hashlib.sha256(content).hexdigest() != entry["sha256"]:
        raise Problem(
            422, "checksum_mismatch", "O tamanho ou hash do arquivo não corresponde ao manifesto."
        )
    if entry.get("already_uploaded"):
        with transaction(actor.tenant_id) as connection:
            lock_policy(connection, actor.tenant_id, mutation=True)
            import_payload(connection, actor, import_id)
        try:
            actual = PrivateStorage().checksum(entry["object_key"])
        except OSError:
            raise Problem(
                503,
                "storage_unavailable",
                "O original está temporariamente indisponível.",
                retryable=True,
            ) from None
        if actual != entry["sha256"]:
            raise Problem(
                503, "storage_corrupted", "O objeto precisa de recuperação antes de continuar."
            )
        return
    key = f"tenants/{actor.tenant_id}/imports/{import_id}/{entry['id']}/{entry['upload_token']}"
    with transaction(actor.tenant_id) as connection:
        lock_policy(connection, actor.tenant_id, mutation=True)
        batch = import_payload(connection, actor, import_id)
        if batch["state"] != "receiving":
            raise Problem(409, "import_sealed", "O pacote já foi fechado para alterações.")
        valid = connection.execute(
            text("""
            SELECT id FROM import_entries WHERE tenant_id=:tenant AND batch_id=:batch AND id=:id
              AND upload_token=:token AND state='uploading' AND upload_until>now()
              AND cleanup_id IS NULL AND quota_released_at IS NULL FOR UPDATE
        """),
            {
                "tenant": actor.tenant_id,
                "batch": import_id,
                "id": entry["id"],
                "token": entry["upload_token"],
            },
        ).first()
        if valid is None:
            raise Problem(409, "upload_expired", "O envio expirou. Reenvie o arquivo.")
        # The bounded body has already been received. Never wait for client network
        # while owning the policy lock; this protects only local publication and commit.
        PrivateStorage().put(key, content)
        count = connection.execute(
            text("""
            UPDATE import_entries SET state='uploaded',object_key=:key,upload_until=NULL,error=NULL
            WHERE tenant_id=:tenant AND batch_id=:batch AND id=:id AND upload_token=:token AND state='uploading' AND upload_until>now()
        """),
            {
                "tenant": actor.tenant_id,
                "batch": import_id,
                "id": entry["id"],
                "token": entry["upload_token"],
                "key": key,
            },
        ).rowcount
        if count != 1:
            raise Problem(409, "upload_expired", "O envio expirou. Reenvie o arquivo.")
        connection.execute(
            text("UPDATE import_batches SET updated_at=now() WHERE tenant_id=:tenant AND id=:id"),
            {"tenant": actor.tenant_id, "id": import_id},
        )


def abandon_upload(actor: Actor, import_id: str, entry: dict) -> None:
    with transaction(actor.tenant_id) as connection:
        connection.execute(
            text("""
            UPDATE import_entries SET state=CASE WHEN object_key IS NULL THEN 'pending' ELSE 'uploaded' END,upload_until=NULL
            WHERE tenant_id=:tenant AND batch_id=:batch AND id=:id AND upload_token=:token AND state='uploading'
        """),
            {
                "tenant": actor.tenant_id,
                "batch": import_id,
                "id": entry["id"],
                "token": entry["upload_token"],
            },
        )


def finalize_import(connection: Connection, actor: Actor, import_id: str, policy: int) -> None:
    batch = import_payload(connection, actor, import_id)
    if batch["state"] in {"sealed", "processing", "ready"}:
        return
    if batch["state"] != "receiving" or any(
        entry["state"] != "uploaded" for entry in batch["entries"]
    ):
        raise Problem(
            409, "import_incomplete", "Envie todos os arquivos antes de finalizar o pacote."
        )
    reject_deleted_hashes(
        connection,
        actor.tenant_id,
        batch["collection_id"],
        [entry["sha256"] for entry in batch["entries"]],
    )
    connection.execute(
        text(
            "UPDATE import_batches SET state='sealed',updated_at=now() WHERE tenant_id=:tenant AND id=:id"
        ),
        {"tenant": actor.tenant_id, "id": import_id},
    )
    enqueue(connection, actor, "ingestion", import_id, policy)


def reject_deleted_hashes(
    connection: Connection, tenant_id: str, collection_id: str, hashes: list[str]
) -> None:
    deleted = connection.execute(
        text(
            "SELECT EXISTS(SELECT 1 FROM evidence WHERE tenant_id=:tenant AND collection_id=:collection AND sha256=ANY(:hashes) AND tombstoned_at IS NOT NULL)"
        ),
        {"tenant": tenant_id, "collection": collection_id, "hashes": hashes},
    ).scalar_one()
    if deleted:
        raise Problem(
            409,
            "source_previously_deleted",
            "Este pacote contém uma fonte excluída da coleção. A importação não pode restaurá-la implicitamente.",
        )
