"""One bounded sweep. It never deletes published source or dossier content by age."""

import hashlib
from collections.abc import Iterator
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from pathlib import Path

from sqlalchemy import Connection, text

from evidencedesk.database import lock_policy, transaction
from evidencedesk.evidence.storage import PrivateStorage
from evidencedesk.retention.cleanup import (
    complete_cleanup,
    enqueue_cleanup,
    object_has_producer,
    object_is_referenced,
)


@dataclass(frozen=True)
class RetentionPolicy:
    temporary_hours: int = 24
    progress_days: int = 7
    audit_days: int = 90
    batch_limit: int = 100
    scan_limit: int = 1000

    def __post_init__(self):
        bounds = (
            (self.temporary_hours, 24, 8760),
            (self.progress_days, 7, 3650),
            (self.audit_days, 90, 3650),
            (self.batch_limit, 1, 1000),
            (self.scan_limit, 1, 10000),
        )
        if any(type(value) is not int or not low <= value <= high for value, low, high in bounds):
            raise ValueError(
                "Retention values must respect the documented minimum and batch bounds."
            )


def plan_expired_imports(connection: Connection, tenant: str, policy: RetentionPolicy) -> int:
    rows = (
        connection.execute(
            text("""
        SELECT b.id FROM import_batches b
        WHERE b.tenant_id=:tenant AND b.state<>'ready' AND b.updated_at<now()-make_interval(hours=>:hours)
          AND EXISTS(SELECT 1 FROM import_entries e WHERE e.tenant_id=b.tenant_id AND e.batch_id=b.id
            AND e.quota_released_at IS NULL AND e.cleanup_id IS NULL)
          AND NOT EXISTS(SELECT 1 FROM import_entries e WHERE e.tenant_id=b.tenant_id AND e.batch_id=b.id
            AND e.state='uploading' AND e.upload_until>now())
          AND NOT EXISTS(SELECT 1 FROM jobs j WHERE j.tenant_id=b.tenant_id AND j.resource_id=b.id
            AND j.kind='ingestion' AND j.state IN('queued','running','retry_wait'))
        ORDER BY b.updated_at,b.id LIMIT :limit FOR UPDATE
    """),
            {"tenant": tenant, "hours": policy.temporary_hours, "limit": policy.batch_limit},
        )
        .scalars()
        .all()
    )
    for identity in rows:
        entries = (
            connection.execute(
                text("""
            SELECT id,object_key,upload_token FROM import_entries WHERE tenant_id=:tenant AND batch_id=:id
              AND quota_released_at IS NULL AND cleanup_id IS NULL FOR UPDATE
        """),
                {"tenant": tenant, "id": identity},
            )
            .mappings()
            .all()
        )
        keys = {entry["object_key"] for entry in entries if entry["object_key"]}
        # A crash can leave complete bytes before the DB publication. The token is durable.
        keys.update(
            f"tenants/{tenant}/imports/{identity}/{entry['id']}/{entry['upload_token']}"
            for entry in entries
            if entry["upload_token"]
        )
        enqueue_cleanup(
            connection,
            tenant,
            "import:" + identity,
            "import_expired",
            keys,
            ((identity, entry["id"]) for entry in entries),
        )
        connection.execute(
            text("""
            UPDATE import_batches SET state=CASE WHEN state IN('receiving','sealed','processing') THEN 'cancelled' ELSE state END,
              error=coalesce(error,'{"code":"import_expired"}'::jsonb),updated_at=now()
            WHERE tenant_id=:tenant AND id=:id
        """),
            {"tenant": tenant, "id": identity},
        )
        connection.execute(
            text("""
            UPDATE import_entries SET state='rejected',upload_until=NULL,error=coalesce(error,'{"code":"import_expired"}'::jsonb)
            WHERE tenant_id=:tenant AND batch_id=:id AND cleanup_id=:cleanup
        """),
            {"tenant": tenant, "id": identity, "cleanup": "import:" + identity},
        )
    return len(rows)


def plan_expired_exports(connection: Connection, tenant: str, policy: RetentionPolicy) -> int:
    rows = (
        connection.execute(
            text("""
        SELECT e.id,e.object_key FROM exports e WHERE e.tenant_id=:tenant AND e.expires_at<=now()
          AND e.object_key IS NOT NULL AND NOT EXISTS(SELECT 1 FROM jobs j WHERE j.tenant_id=e.tenant_id
            AND j.kind='export' AND j.resource_id=e.id AND j.state IN('queued','running','retry_wait'))
        ORDER BY e.expires_at,e.id LIMIT :limit FOR UPDATE
    """),
            {"tenant": tenant, "limit": policy.batch_limit},
        )
        .mappings()
        .all()
    )
    for row in rows:
        enqueue_cleanup(
            connection, tenant, "export:" + row["id"], "export_expired", [row["object_key"]]
        )
        connection.execute(
            text(
                "UPDATE exports SET object_key=NULL,sha256=NULL WHERE tenant_id=:tenant AND id=:id"
            ),
            {"tenant": tenant, "id": row["id"]},
        )
    return len(rows)


def storage_files(root: Path) -> Iterator[Path]:
    if not root.exists() or root.is_symlink():
        return
    for path in sorted(root.iterdir(), key=lambda item: item.name):
        if path.is_symlink():
            continue
        if path.is_dir():
            yield from storage_files(path)
        elif path.is_file():
            yield path


def plan_orphans(connection: Connection, tenant: str, policy: RetentionPolicy) -> dict:
    storage = PrivateStorage()
    root = storage.path(f"tenants/{tenant}")
    cutoff = (datetime.now(UTC) - timedelta(hours=policy.temporary_hours)).timestamp()
    scanned = planned = 0
    truncated = False
    cursor = connection.execute(
        text("SELECT retention_scan_cursor FROM tenant_policy WHERE tenant_id=:tenant"),
        {"tenant": tenant},
    ).scalar_one()
    last = cursor
    # No symlink traversal; no sweep outside this tenant's known producer namespaces.
    for path in storage_files(root):
        key = path.relative_to(storage.root).as_posix()
        if cursor and tuple(key.split("/")) <= tuple(cursor.split("/")):
            continue
        if scanned >= policy.scan_limit or planned >= policy.batch_limit:
            truncated = True
            break
        scanned += 1
        last = key
        parts = key.split("/")
        if len(parts) < 5 or parts[2] not in {"imports", "exports", "runs"}:
            continue
        try:
            old = path.stat().st_mtime <= cutoff
        except FileNotFoundError:
            continue
        if (
            not old
            or object_is_referenced(connection, tenant, key)
            or object_has_producer(connection, tenant, key)
        ):
            continue
        pending = connection.execute(
            text("""
                SELECT EXISTS(SELECT 1 FROM storage_cleanup WHERE tenant_id=:tenant
                  AND state='pending' AND object_keys ? :key)
            """),
            {"tenant": tenant, "key": key},
        ).scalar_one()
        if pending:
            continue
        enqueue_cleanup(
            connection,
            tenant,
            "orphan:" + hashlib.sha256(key.encode()).hexdigest(),
            "orphan",
            [key],
        )
        planned += 1
    next_cursor = last if truncated else ""
    connection.execute(
        text("UPDATE tenant_policy SET retention_scan_cursor=:cursor WHERE tenant_id=:tenant"),
        {"tenant": tenant, "cursor": next_cursor},
    )
    return {
        "scanned_files": scanned,
        "planned_orphans": planned,
        "scan_truncated": truncated,
        "scan_cursor": next_cursor,
    }


def prune_history(connection: Connection, tenant: str, policy: RetentionPolicy) -> dict:
    progress = connection.execute(
        text("""
        DELETE FROM run_events WHERE (tenant_id,run_id,seq) IN (
          SELECT e.tenant_id,e.run_id,e.seq FROM run_events e JOIN jobs j
            ON j.tenant_id=e.tenant_id AND j.resource_id=e.run_id AND j.kind='investigation'
          WHERE e.tenant_id=:tenant AND e.created_at<now()-make_interval(days=>:days)
            AND j.state IN('succeeded','failed','cancelled') AND j.completed_at<now()-make_interval(days=>:days)
          ORDER BY e.created_at,e.run_id,e.seq LIMIT :limit
        )
    """),
        {"tenant": tenant, "days": policy.progress_days, "limit": policy.batch_limit},
    ).rowcount
    audit = connection.execute(
        text("SELECT public.expire_audit_events(:tenant,:days,:limit)"),
        {"tenant": tenant, "days": policy.audit_days, "limit": policy.batch_limit},
    ).scalar_one()
    return {"progress_events_removed": progress, "audit_events_removed": audit}


def sweep(tenant: str, policy: RetentionPolicy | None = None) -> dict:
    policy = policy or RetentionPolicy()
    with transaction(tenant) as connection:
        lock_policy(connection, tenant, mutation=True)
        imports = plan_expired_imports(connection, tenant, policy)
        exports = plan_expired_exports(connection, tenant, policy)
        orphans = plan_orphans(connection, tenant, policy)
        history = prune_history(connection, tenant, policy)
        identities = (
            connection.execute(
                text("""
            SELECT id FROM storage_cleanup WHERE tenant_id=:tenant AND state='pending'
            ORDER BY attempts,created_at,id LIMIT :limit
        """),
                {"tenant": tenant, "limit": policy.batch_limit},
            )
            .scalars()
            .all()
        )
    # A crash here leaves every planned key and ownership claim available to the next sweep.
    outcomes = []
    for identity in identities:
        with transaction(tenant) as connection:
            lock_policy(connection, tenant, mutation=True)
            outcomes.append(complete_cleanup(connection, tenant, identity))
    return {
        "tenant_id": tenant,
        "planned_imports": imports,
        "planned_exports": exports,
        **orphans,
        **history,
        "cleanup": outcomes,
        "released_bytes": sum(item["released_bytes"] for item in outcomes),
        "blocked_or_failed": sum(item["state"] != "completed" for item in outcomes),
    }
