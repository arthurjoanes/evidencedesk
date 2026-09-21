from sqlalchemy import Connection, text

from evidencedesk.errors import not_found
from evidencedesk.identity.service import Actor, authorize_collection


def authorize_snapshot(
    connection: Connection, actor: Actor, snapshot_id: str, collection_id: str | None = None
) -> dict:
    row = (
        connection.execute(
            text("SELECT * FROM evidence_snapshots WHERE tenant_id=:tenant AND id=:id"),
            {"tenant": actor.tenant_id, "id": snapshot_id},
        )
        .mappings()
        .first()
    )
    if row is None or (collection_id is not None and row["collection_id"] != collection_id):
        raise not_found()
    authorize_collection(connection, actor, row["collection_id"])
    return dict(row)


def resolve_evidence(
    connection: Connection, actor: Actor, evidence_id: str, snapshot_id: str
) -> dict:
    authorize_snapshot(connection, actor, snapshot_id)
    row = (
        connection.execute(
            text("""
        SELECT e.* FROM evidence e
        WHERE e.tenant_id=:tenant AND e.id=:id AND e.tombstoned_at IS NULL AND (
          EXISTS(SELECT 1 FROM snapshot_members m WHERE m.tenant_id=e.tenant_id AND m.evidence_id=e.id AND m.snapshot_id=:snapshot)
          OR (e.kind='reconciliation_result' AND e.record->>'snapshot_id'=:snapshot))
    """),
            {"tenant": actor.tenant_id, "id": evidence_id, "snapshot": snapshot_id},
        )
        .mappings()
        .first()
    )
    if row is None:
        raise not_found()
    authorize_collection(connection, actor, row["collection_id"])
    if row["kind"] == "reconciliation_result":
        source_ids = row["record"].get("source_ids", [])
        if source_ids:
            visible = connection.execute(
                text("""
                SELECT count(*) FROM evidence e JOIN collection_grants g ON g.tenant_id=e.tenant_id AND g.collection_id=e.collection_id
                WHERE e.tenant_id=:tenant AND e.id=ANY(:ids) AND g.user_id=:user AND e.tombstoned_at IS NULL
            """),
                {"tenant": actor.tenant_id, "ids": source_ids, "user": actor.id},
            ).scalar_one()
            if visible != len(set(source_ids)):
                raise not_found()
    return dict(row)


def evidence_payload(row: dict, snapshot_id: str) -> dict:
    return {
        "id": row["id"],
        "kind": row["kind"],
        "title": row["title"],
        "version": row["version"],
        "sha256": row["sha256"],
        "source_system": row["source_system"],
        "temporal_role": row["temporal_role"],
        "valid_from": row["valid_from"],
        "valid_until": row["valid_until"],
        "canonical_text": row["canonical_text"],
        "locator": row["locator"],
        "original": None
        if not row["original_key"]
        else {
            "media_type": row["media_type"],
            "byte_size": row["byte_size"],
            "content_url": f"/api/v1/evidence/{row['id']}/content?evidence_snapshot_id={snapshot_id}",
        },
    }
