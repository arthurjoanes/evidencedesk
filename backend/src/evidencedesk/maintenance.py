"""Owned maintenance windows and fail-closed reconciliation of deletion intent."""

import argparse
import hmac
import json
import secrets
import sys
import time
from pathlib import Path

from sqlalchemy import Connection, text

from evidencedesk.config import get_settings
from evidencedesk.database import lock_policy, transaction
from evidencedesk.deletion_ledger import (
    append_intent,
    assert_extends_database,
    initialize_files,
    read_ledger,
    save_database_checkpoint,
    write_checkpoint,
)


class MaintenanceFailure(ValueError):
    def __init__(self, message: str, state: dict | None = None):
        super().__init__(message)
        self.state = state or {}


def initialize_ledger() -> dict:
    """Seed/bootstrap only: never invent a replacement for a previously known ledger."""
    with transaction() as connection:
        connection.execute(text("SELECT id FROM operational_control WHERE id=1 FOR UPDATE"))
        state = (
            connection.execute(text("SELECT * FROM operational_ledger WHERE id=1 FOR UPDATE"))
            .mappings()
            .one()
        )
        if state["ledger_id"] is not None:
            snapshot = read_ledger()
            assert_extends_database(snapshot, state)
            if state["sequence"] != snapshot.checkpoint["sequence"]:
                raise MaintenanceFailure("Pending deletion intent must be reconciled.")
        else:
            snapshot = initialize_files(get_settings().deletion_ledger_root)
            if snapshot.records:
                raise MaintenanceFailure(
                    "A populated ledger cannot initialize a new database implicitly."
                )
            save_database_checkpoint(connection, snapshot)
        return snapshot.checkpoint


def active_operations() -> tuple[int, int]:
    with transaction() as connection:
        tenants = connection.execute(text("SELECT id FROM tenants ORDER BY id")).scalars().all()
    jobs = uploads = 0
    for tenant in tenants:
        # No cross-tenant jobs query under an application role; each scope is explicit.
        with transaction(tenant) as connection:
            jobs += connection.execute(
                text("SELECT count(*) FROM jobs WHERE state='running'")
            ).scalar_one()
            uploads += connection.execute(
                text("SELECT count(*) FROM import_entries WHERE state='uploading'")
            ).scalar_one()
    return jobs, uploads


def status() -> dict:
    with transaction() as connection:
        control = (
            connection.execute(text("SELECT maintenance FROM operational_control WHERE id=1"))
            .mappings()
            .one()
        )
        checkpoint = (
            connection.execute(text("SELECT * FROM operational_ledger WHERE id=1")).mappings().one()
        )
    ledger_ready = False
    try:
        snapshot = read_ledger()
        assert_extends_database(snapshot, checkpoint)
        ledger_ready = (
            checkpoint["ledger_id"] is not None
            and checkpoint["sequence"] == snapshot.checkpoint["sequence"]
        )
    except (OSError, ValueError):
        pass
    jobs, uploads = active_operations()
    return {
        "maintenance": control["maintenance"],
        "drained": jobs == 0 and uploads == 0,
        "active_jobs": jobs,
        "active_uploads": uploads,
        "ledger_ready": ledger_ready,
    }


def enter(timeout: float = 60) -> dict:
    if not 0 <= timeout <= 300:
        raise MaintenanceFailure("Maintenance timeout must be between 0 and 300 seconds.")
    token = secrets.token_urlsafe(32)
    with transaction() as connection:
        changed = connection.execute(
            text("""
            UPDATE operational_control SET maintenance=true,maintenance_token=:token,
              maintenance_started_at=now(),updated_at=now()
            WHERE id=1 AND NOT maintenance RETURNING id
        """),
            {"token": token},
        ).first()
        if changed is None:
            raise MaintenanceFailure("Maintenance already belongs to another operation.")
    deadline = time.monotonic() + timeout
    while True:
        state = status() | {"maintenance_token": token}
        if state["drained"]:
            if not state["ledger_ready"]:
                raise MaintenanceFailure("Ledger is not ready; maintenance remains enabled.", state)
            return state
        if time.monotonic() >= deadline:
            raise MaintenanceFailure("Drain timed out; maintenance remains enabled.", state)
        time.sleep(min(0.25, max(0, deadline - time.monotonic())))


def require_owner(connection: Connection, token: str) -> None:
    state = (
        connection.execute(
            text(
                "SELECT maintenance,maintenance_token FROM operational_control WHERE id=1 FOR UPDATE"
            )
        )
        .mappings()
        .one()
    )
    if (
        not state["maintenance"]
        or not isinstance(token, str)
        or not state["maintenance_token"]
        or not hmac.compare_digest(token, state["maintenance_token"])
    ):
        raise MaintenanceFailure("The maintenance ownership token is invalid.")


def leave(token: str) -> dict:
    with transaction() as connection:
        require_owner(connection, token)
        checkpoint = (
            connection.execute(text("SELECT * FROM operational_ledger WHERE id=1 FOR UPDATE"))
            .mappings()
            .one()
        )
        snapshot = read_ledger()
        assert_extends_database(snapshot, checkpoint)
        if (
            checkpoint["ledger_id"] is None
            or checkpoint["sequence"] != snapshot.checkpoint["sequence"]
        ):
            raise MaintenanceFailure(
                "Unreconciled ledger: reads remain closed on a restored target."
            )
        jobs, uploads = active_operations()
        if jobs or uploads:
            raise MaintenanceFailure("Active operations remain; the maintenance window stays open.")
        connection.execute(
            text(
                "UPDATE operational_control SET maintenance=false,maintenance_token=NULL,maintenance_started_at=NULL,updated_at=now() WHERE id=1"
            )
        )
    return status()


def _redact_record(connection: Connection, record: dict) -> dict:
    from evidencedesk.retention.cleanup import enqueue_cleanup

    tenant = record["tenant_id"]
    # New intents retain file identity even when the referenced row is absent from an old backup.
    # Legacy intents infer the same scope from the restored source before redaction.
    source = (
        connection.execute(
            text("SELECT collection_id,sha256 FROM evidence WHERE tenant_id=:tenant AND id=:id"),
            {"tenant": tenant, "id": record["evidence_id"]},
        )
        .mappings()
        .first()
    )
    parameters = {
        "tenant": tenant,
        "evidence": record["evidence_id"],
        "key": record["object_key"],
        "collection": record.get("collection_id") or (source["collection_id"] if source else None),
        "source_sha256": record.get("source_sha256") or (source["sha256"] if source else None),
    }
    sources = (
        connection.execute(
            text("""
        SELECT id,original_key FROM evidence WHERE tenant_id=:tenant AND collection_id=:collection
          AND (id=:evidence OR original_key=:key OR sha256=:source_sha256)
    """),
            parameters,
        )
        .mappings()
        .all()
    )
    object_keys = {record["object_key"]} if record["object_key"] else set()
    object_keys.update(item["original_key"] for item in sources if item["original_key"])
    affected = [item["id"] for item in sources]
    parameters["ids"] = affected
    snapshots = (
        connection.execute(
            text(
                "SELECT DISTINCT snapshot_id FROM snapshot_members WHERE tenant_id=:tenant AND evidence_id=ANY(:ids)"
            ),
            parameters,
        )
        .scalars()
        .all()
    )
    parameters["snapshots"] = snapshots
    derived = (
        connection.execute(
            text("""
        SELECT id FROM evidence WHERE tenant_id=:tenant AND collection_id=:collection
          AND kind='reconciliation_result' AND
          (record->>'snapshot_id'=ANY(:snapshots)
           OR jsonb_exists_any(record->'source_ids',CAST(:ids AS text[])))
    """),
            parameters,
        )
        .scalars()
        .all()
    )
    affected = sorted(set(affected) | set(derived))
    parameters["ids"] = affected
    # A derived evidence may have been included in another immutable snapshot.
    snapshots = sorted(
        set(snapshots)
        | set(
            connection.execute(
                text(
                    "SELECT DISTINCT snapshot_id FROM snapshot_members WHERE tenant_id=:tenant AND evidence_id=ANY(:ids)"
                ),
                parameters,
            ).scalars()
        )
    )
    parameters["snapshots"] = snapshots
    imports = (
        connection.execute(
            text("""
        SELECT e.batch_id,e.id,e.object_key FROM import_entries e
        JOIN import_batches b ON b.tenant_id=e.tenant_id AND b.id=e.batch_id
        WHERE e.tenant_id=:tenant AND b.collection_id=:collection
          AND (e.sha256=:source_sha256 OR e.object_key=:key)
    """),
            parameters,
        )
        .mappings()
        .all()
    )
    object_keys.update(item["object_key"] for item in imports if item["object_key"])
    parameters["import_batches"] = sorted({item["batch_id"] for item in imports})
    dossiers = (
        connection.execute(
            text("""
        UPDATE dossiers SET tombstoned_at=coalesce(tombstoned_at,now())
        WHERE tenant_id=:tenant AND snapshot_id=ANY(:snapshots) RETURNING id
    """),
            parameters,
        )
        .scalars()
        .all()
    )
    parameters["dossiers"] = dossiers
    exports = (
        connection.execute(
            text(
                "SELECT id,object_key FROM exports WHERE tenant_id=:tenant AND dossier_id=ANY(:dossiers)"
            ),
            parameters,
        )
        .mappings()
        .all()
    )
    object_keys.update(item["object_key"] for item in exports if item["object_key"])
    parameters["export_ids"] = [item["id"] for item in exports]
    connection.execute(
        text(
            "UPDATE exports SET object_key=NULL,sha256=NULL,expires_at=now() WHERE tenant_id=:tenant AND dossier_id=ANY(:dossiers)"
        ),
        parameters,
    )
    runs = (
        connection.execute(
            text("""
        UPDATE investigation_runs SET tombstoned_at=coalesce(tombstoned_at,now()),
          question='Investigação removida por exclusão de fonte.',steps='[]'
        WHERE tenant_id=:tenant AND snapshot_id=ANY(:snapshots) RETURNING id
    """),
            parameters,
        )
        .scalars()
        .all()
    )
    parameters["runs"] = runs
    artifacts = (
        connection.execute(
            text(
                "SELECT result_key,manifest_key FROM result_artifacts WHERE tenant_id=:tenant AND run_id=ANY(:runs)"
            ),
            parameters,
        )
        .mappings()
        .all()
    )
    for artifact in artifacts:
        object_keys.update((artifact["result_key"], artifact["manifest_key"]))
    connection.execute(
        text("DELETE FROM result_artifacts WHERE tenant_id=:tenant AND run_id=ANY(:runs)"),
        parameters,
    )
    connection.execute(
        text(
            "UPDATE run_events SET payload=jsonb_build_object('redacted',true) WHERE tenant_id=:tenant AND run_id=ANY(:runs)"
        ),
        parameters,
    )
    connection.execute(
        text("""
        UPDATE jobs SET state='cancelled',cancel_requested=true,fencing_token=fencing_token+1,
          lease_until=NULL,completed_at=coalesce(completed_at,now()),stage='cancelled'
        WHERE tenant_id=:tenant AND ((kind='investigation' AND resource_id=ANY(:runs))
          OR (kind='ingestion' AND resource_id=ANY(:import_batches))
          OR (kind='export' AND resource_id=ANY(:export_ids))) AND state IN('queued','running','retry_wait')
    """),
        parameters,
    )
    connection.execute(
        text("""
        UPDATE evidence SET tombstoned_at=coalesce(tombstoned_at,now()),canonical_text='',record='{}',
          embedding=NULL,original_key=NULL,title='Fonte excluída',locator='{}'
        WHERE tenant_id=:tenant AND id=ANY(:ids)
    """),
        parameters,
    )
    cleanup_id = enqueue_cleanup(
        connection,
        tenant,
        "deletion:" + record["evidence_id"],
        "source_deleted",
        object_keys,
        ((item["batch_id"], item["id"]) for item in imports),
    )
    connection.execute(
        text(
            """UPDATE import_entries e SET object_key=NULL,upload_token=NULL,upload_until=NULL,
              state='rejected',error=jsonb_build_object('code','source_deleted')
            FROM import_batches b WHERE b.tenant_id=e.tenant_id AND b.id=e.batch_id
              AND e.tenant_id=:tenant AND b.collection_id=:collection
              AND (e.sha256=:source_sha256 OR e.object_key=:key)"""
        ),
        parameters,
    )
    connection.execute(text("SELECT public.redact_tombstoned_revisions(:tenant)"), parameters)
    connection.execute(
        text("UPDATE tenant_policy SET revision=revision+1 WHERE tenant_id=:tenant"), parameters
    )
    return {
        "evidence": len(affected),
        "dossiers": len(dossiers),
        "object_keys": sorted(object_keys),
        "cleanup_id": cleanup_id,
    }


def record_deletion(connection: Connection, tenant_id: str, evidence_id: str) -> dict:
    """Caller authorizes deletion and holds lock_policy(..., mutation=True)."""
    if (
        connection.execute(text("SELECT current_setting('ed.tenant_id',true)")).scalar_one()
        != tenant_id
    ):
        raise MaintenanceFailure("Deletion requires the same tenant context as its transaction.")
    source = connection.execute(
        text(
            "SELECT original_key,collection_id,sha256 FROM evidence WHERE tenant_id=:tenant AND id=:id"
        ),
        {"tenant": tenant_id, "id": evidence_id},
    ).first()
    if source is None:
        raise MaintenanceFailure("The deletion source does not exist in this tenant.")
    uploading = connection.execute(
        text("""
        SELECT EXISTS(SELECT 1 FROM import_entries e JOIN import_batches b
          ON b.tenant_id=e.tenant_id AND b.id=e.batch_id
          WHERE e.tenant_id=:tenant AND b.collection_id=:collection
            AND e.sha256=:sha256 AND e.state='uploading')
    """),
        {"tenant": tenant_id, "collection": source.collection_id, "sha256": source.sha256},
    ).scalar_one()
    if uploading:
        raise MaintenanceFailure("Deletion must wait for matching uploads to finish.")
    record = append_intent(
        connection,
        tenant_id,
        evidence_id,
        source.original_key,
        collection_id=source.collection_id,
        source_sha256=source.sha256,
    )
    return _redact_record(connection, record) | {"sequence": record["sequence"]}


def purge_objects(keys: list[str]) -> None:
    """After the DB commit: deletion is idempotent; inaccessible orphan cleanup may retry."""
    root = get_settings().storage_root.resolve()
    for key in keys:
        path = root / key
        if (
            not key
            or Path(key).is_absolute()
            or path.is_symlink()
            or not path.resolve().is_relative_to(root)
        ):
            raise MaintenanceFailure("Object key escapes private storage.")
        path.unlink(missing_ok=True)


def reconcile_ledger(token: str, *, restore_mode: bool, ledger_root: Path | None = None) -> dict:
    if not restore_mode:
        raise MaintenanceFailure(
            "Ledger replay requires explicit --restore-mode and a closed target."
        )
    root = ledger_root or get_settings().deletion_ledger_root
    if root.resolve() != get_settings().deletion_ledger_root.resolve():
        raise MaintenanceFailure("Reconciliation must use the configured independent ledger root.")
    with transaction() as connection:
        require_owner(connection, token)
        checkpoint = (
            connection.execute(text("SELECT * FROM operational_ledger WHERE id=1 FOR UPDATE"))
            .mappings()
            .one()
        )
        snapshot = read_ledger(root, checkpoint_may_lag=True)
        assert_extends_database(snapshot, checkpoint)
        existing_tenants = set(connection.execute(text("SELECT id FROM tenants")).scalars())
    if any(active_operations()):
        raise MaintenanceFailure("Reconciliation requires drained operations.")
    affected = 0
    for record in snapshot.records:
        # Deletions in a tenant created after the backup have no rows in this snapshot.
        if record["tenant_id"] not in existing_tenants:
            continue
        with transaction(record["tenant_id"]) as connection:
            # Global maintenance lock first, then tenant policy; application RLS remains enabled.
            control = connection.execute(
                text(
                    "SELECT maintenance_token FROM operational_control WHERE id=1 AND maintenance FOR SHARE"
                )
            ).scalar_one_or_none()
            if control != token:
                raise MaintenanceFailure("Maintenance ownership changed during reconciliation.")
            lock_policy(connection, record["tenant_id"])
            result = _redact_record(connection, record)
            # The target is closed. Keep references if unlink fails so a retry can
            # discover every duplicate/artifact again; already deleted files are harmless.
            from evidencedesk.retention.cleanup import complete_cleanup

            cleaned = complete_cleanup(connection, record["tenant_id"], result["cleanup_id"])
            if cleaned["state"] != "completed":
                raise MaintenanceFailure("Object cleanup is blocked; restore remains closed.")
            affected += result["evidence"]
    with transaction() as connection:
        require_owner(connection, token)
        current = read_ledger(root, checkpoint_may_lag=True)
        if current.checkpoint != snapshot.checkpoint:
            raise MaintenanceFailure("Deletion ledger changed during reconciliation.")
        # An fsynced, complete tail may survive a crash before checkpoint replacement.
        # Only explicit, owned reconciliation can advance that independently verified prefix.
        write_checkpoint(root, current.checkpoint)
        save_database_checkpoint(connection, snapshot)
    return status() | {
        "replayed_records": len(snapshot.records),
        "redacted_evidence": affected,
        "ledger_sequence": len(snapshot.records),
    }


def main() -> int:
    cli = argparse.ArgumentParser(description=__doc__)
    commands = cli.add_subparsers(dest="action", required=True)
    commands.add_parser("status")
    start = commands.add_parser("enter")
    start.add_argument("--timeout", type=float, default=60)
    finish = commands.add_parser("leave")
    finish.add_argument("--token", required=True)
    replay = commands.add_parser("reconcile-ledger")
    replay.add_argument("--token", required=True)
    replay.add_argument("--restore-mode", action="store_true")
    replay.add_argument("--ledger-root", type=Path)
    args = cli.parse_args()
    try:
        if args.action == "status":
            result = status()
        elif args.action == "enter":
            result = enter(args.timeout)
        elif args.action == "leave":
            result = leave(args.token)
        else:
            result = reconcile_ledger(
                args.token, restore_mode=args.restore_mode, ledger_root=args.ledger_root
            )
        print(json.dumps(result, ensure_ascii=False))
        return 0
    except (ValueError, OSError) as error:
        result = {"error": str(error)} | (
            error.state if isinstance(error, MaintenanceFailure) else {}
        )
        print(json.dumps(result, ensure_ascii=False))
        return 1


if __name__ == "__main__":
    sys.exit(main())
