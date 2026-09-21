import json
from collections.abc import Iterable

from sqlalchemy import Connection, text

from evidencedesk.evidence.storage import PrivateStorage


def enqueue_cleanup(
    connection: Connection,
    tenant: str,
    identity: str,
    reason: str,
    keys: Iterable[str],
    entries: Iterable[tuple[str, str]] = (),
) -> str:
    """Caller owns the tenant policy lock; record keys before clearing references."""
    previous = connection.execute(
        text(
            "SELECT object_keys FROM storage_cleanup WHERE tenant_id=:tenant AND id=:id FOR UPDATE"
        ),
        {"tenant": tenant, "id": identity},
    ).scalar_one_or_none()
    object_keys = sorted(set(previous or []) | {key for key in keys if key})
    connection.execute(
        text("""
        INSERT INTO storage_cleanup(tenant_id,id,reason,object_keys)
        VALUES(:tenant,:id,:reason,CAST(:keys AS jsonb))
        ON CONFLICT(tenant_id,id) DO UPDATE SET object_keys=excluded.object_keys,
          state='pending',completed_at=NULL,error_code=NULL
    """),
        {"tenant": tenant, "id": identity, "reason": reason, "keys": json.dumps(object_keys)},
    )
    for batch, entry in entries:
        connection.execute(
            text("""
            UPDATE import_entries SET cleanup_id=:cleanup
            WHERE tenant_id=:tenant AND batch_id=:batch AND id=:entry
              AND quota_released_at IS NULL AND (cleanup_id IS NULL OR cleanup_id=:cleanup)
        """),
            {"tenant": tenant, "batch": batch, "entry": entry, "cleanup": identity},
        )
    return identity


def object_is_referenced(
    connection: Connection, tenant: str, key: str, cleanup_id: str | None = None
) -> bool:
    return connection.execute(
        text("""
        SELECT EXISTS(SELECT 1 FROM evidence WHERE tenant_id=:tenant AND original_key=:key AND tombstoned_at IS NULL)
          OR EXISTS(SELECT 1 FROM import_entries WHERE tenant_id=:tenant AND object_key=:key
            AND (cleanup_id IS NULL OR cleanup_id IS DISTINCT FROM :cleanup))
          OR EXISTS(SELECT 1 FROM exports WHERE tenant_id=:tenant AND object_key=:key AND expires_at>now())
          OR EXISTS(SELECT 1 FROM result_artifacts WHERE tenant_id=:tenant AND (result_key=:key OR manifest_key=:key))
    """),
        {"tenant": tenant, "key": key, "cleanup": cleanup_id},
    ).scalar_one()


def object_has_producer(connection: Connection, tenant: str, key: str) -> bool:
    parts = key.split("/")
    if len(parts) < 5 or parts[:2] != ["tenants", tenant]:
        return False
    family, resource = parts[2:4]
    if family == "imports":
        uploading = connection.execute(
            text("""
            SELECT EXISTS(SELECT 1 FROM import_entries WHERE tenant_id=:tenant AND batch_id=:id
              AND state='uploading' AND upload_until>now())
        """),
            {"tenant": tenant, "id": resource},
        ).scalar_one()
        if uploading:
            return True
    kind = {"imports": "ingestion", "exports": "export", "runs": "investigation"}.get(family)
    if not kind:
        return True  # Unknown namespaces are never candidates for a cleanup guess.
    return connection.execute(
        text("""
        SELECT EXISTS(SELECT 1 FROM jobs WHERE tenant_id=:tenant AND resource_id=:id
          AND kind=:kind AND state IN('queued','running','retry_wait'))
    """),
        {"tenant": tenant, "id": resource, "kind": kind},
    ).scalar_one()


def complete_cleanup(connection: Connection, tenant: str, identity: str) -> dict:
    """Idempotent unlink under policy lock; failed I/O keeps durable keys and quota."""
    row = (
        connection.execute(
            text("SELECT * FROM storage_cleanup WHERE tenant_id=:tenant AND id=:id FOR UPDATE"),
            {"tenant": tenant, "id": identity},
        )
        .mappings()
        .one()
    )
    if row["state"] == "completed":
        return {"id": identity, "state": "completed", "released_bytes": 0}
    problem = None
    for key in row["object_keys"]:
        if object_is_referenced(connection, tenant, key, identity) or object_has_producer(
            connection, tenant, key
        ):
            problem = "object_in_use"
            break
    if not problem:
        try:
            storage = PrivateStorage()
            for key in row["object_keys"]:
                if not key.startswith((f"tenants/{tenant}/", f"{tenant}/")):
                    raise ValueError("Object does not belong to the cleanup tenant")
                candidate = storage.root / key
                if any(
                    path.is_symlink()
                    for path in (candidate, *candidate.parents)
                    if path != storage.root
                ):
                    raise ValueError("Symlinks are not cleanup targets")
                storage.delete(key)
        except (OSError, ValueError):
            problem = "storage_unavailable"
    if problem:
        connection.execute(
            text("""
            UPDATE storage_cleanup SET attempts=attempts+1,error_code=:error WHERE tenant_id=:tenant AND id=:id
        """),
            {"tenant": tenant, "id": identity, "error": problem},
        )
        return {"id": identity, "state": "pending", "error_code": problem, "released_bytes": 0}
    released = connection.execute(
        text("""
        WITH released AS (
          UPDATE import_entries SET quota_released_at=now(),object_key=NULL,upload_token=NULL,upload_until=NULL
          WHERE tenant_id=:tenant AND cleanup_id=:id AND quota_released_at IS NULL RETURNING quota_bytes
        ) SELECT coalesce(sum(quota_bytes),0) FROM released
    """),
        {"tenant": tenant, "id": identity},
    ).scalar_one()
    connection.execute(
        text(
            "UPDATE tenant_policy SET storage_reserved=storage_reserved-:bytes WHERE tenant_id=:tenant"
        ),
        {"tenant": tenant, "bytes": released},
    )
    connection.execute(
        text("""
        UPDATE storage_cleanup SET state='completed',completed_at=now(),error_code=NULL,
          attempts=attempts+1,released_bytes=released_bytes+:bytes WHERE tenant_id=:tenant AND id=:id
    """),
        {"tenant": tenant, "id": identity, "bytes": released},
    )
    return {"id": identity, "state": "completed", "released_bytes": released}
