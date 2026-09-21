"""Actual files, SQL transactions, API admission and application-role RLS on a disposable DB."""

import hashlib
import os
from concurrent.futures import ThreadPoolExecutor
from datetime import UTC, datetime, timedelta

import pytest
from sqlalchemy import text
from sqlalchemy.exc import DBAPIError
from test_manual_workflow import create_import, create_incident, import_document

from evidencedesk import maintenance
from evidencedesk.database import lock_policy, transaction
from evidencedesk.errors import Problem
from evidencedesk.evidence.storage import PrivateStorage
from evidencedesk.identity.service import actor_for_worker
from evidencedesk.ingestion.service import finish_upload, reserve_upload
from evidencedesk.jobs.service import acquire
from evidencedesk.retention.cleanup import complete_cleanup, enqueue_cleanup
from evidencedesk.retention.service import RetentionPolicy, sweep
from evidencedesk.worker import execute_lease

pytestmark = pytest.mark.integration


def age_batch(tenant, batch):
    with transaction(tenant) as connection:
        connection.execute(
            text("UPDATE import_batches SET updated_at=now()-interval '25 hours' WHERE id=:id"),
            {"id": batch},
        )


def reserved(tenant):
    with transaction(tenant) as connection:
        return connection.execute(text("SELECT storage_reserved FROM tenant_policy")).scalar_one()


def upload(client, batch, content):
    response = client.put(
        f"/api/v1/imports/{batch}/files/manual",
        content=content,
        headers={"Content-Type": "text/markdown"},
    )
    assert response.status_code == 200, response.text


def old_file(key):
    storage = PrivateStorage()
    storage.put(key, b"orphan fixture")
    yesterday = (datetime.now(UTC) - timedelta(hours=25)).timestamp()
    os.utime(storage.path(key), (yesterday, yesterday))


def test_abandoned_manifest_releases_exactly_once_and_cannot_be_resumed(workspace):
    tenant = workspace["tenants"][0]
    client = workspace["client"]()
    content = b"never uploaded"
    batch = create_import(client, tenant, content)
    assert reserved(tenant) == len(content)
    assert sweep(tenant)["released_bytes"] == 0
    age_batch(tenant, batch)
    assert sweep(tenant)["released_bytes"] == len(content)
    assert reserved(tenant) == 0
    assert sweep(tenant)["released_bytes"] == 0
    response = client.put(
        f"/api/v1/imports/{batch}/files/manual",
        content=content,
        headers={"Content-Type": "text/markdown"},
    )
    assert response.status_code == 409


def test_repeat_put_keeps_object_and_reservation_then_rejected_batch_expires(workspace):
    tenant = workspace["tenants"][0]
    client = workspace["client"]()
    content = b"same immutable source"
    batch = create_import(client, tenant, content)
    upload(client, batch, content)
    with transaction(tenant) as connection:
        key = connection.execute(
            text("SELECT object_key FROM import_entries WHERE batch_id=:id"), {"id": batch}
        ).scalar_one()
    upload(client, batch, content)
    assert reserved(tenant) == len(content)
    with transaction(tenant) as connection:
        assert (
            connection.execute(
                text("SELECT object_key FROM import_entries WHERE batch_id=:id"), {"id": batch}
            ).scalar_one()
            == key
        )
        connection.execute(
            text("UPDATE import_batches SET state='rejected' WHERE id=:id"), {"id": batch}
        )
    age_batch(tenant, batch)
    assert sweep(tenant)["released_bytes"] == len(content)
    assert not PrivateStorage().path(key).exists()
    assert reserved(tenant) == 0


def test_active_upload_is_preserved_and_late_writer_cannot_recreate_cleaned_bytes(workspace):
    tenant = workspace["tenants"][0]
    client = workspace["client"]()
    content = b"bounded upload body"
    batch = create_import(client, tenant, content)
    with transaction(tenant) as connection:
        actor = actor_for_worker(connection, tenant, tenant + "-author")
    entry = reserve_upload(actor, batch, "manual")
    age_batch(tenant, batch)
    assert sweep(tenant)["released_bytes"] == 0
    assert reserved(tenant) == len(content)
    with transaction(tenant) as connection:
        connection.execute(
            text(
                "UPDATE import_entries SET upload_until=now()-interval '1 second' WHERE batch_id=:id"
            ),
            {"id": batch},
        )
    assert sweep(tenant)["released_bytes"] == len(content)
    with pytest.raises(Problem) as failure:
        finish_upload(actor, batch, entry, content)
    assert failure.value.status == 409
    key = f"tenants/{tenant}/imports/{batch}/manual/{entry['upload_token']}"
    assert not PrivateStorage().path(key).exists()


def test_retry_cleans_uncommitted_old_token_before_another_object_is_written(workspace):
    tenant = workspace["tenants"][0]
    client = workspace["client"]()
    content = b"publication happened before a simulated transaction crash"
    batch = create_import(client, tenant, content)
    with transaction(tenant) as connection:
        actor = actor_for_worker(connection, tenant, tenant + "-author")
    first = reserve_upload(actor, batch, "manual")
    old = f"tenants/{tenant}/imports/{batch}/manual/{first['upload_token']}"
    PrivateStorage().put(old, content)
    with transaction(tenant) as connection:
        connection.execute(
            text(
                "UPDATE import_entries SET upload_until=now()-interval '1 second' WHERE batch_id=:id"
            ),
            {"id": batch},
        )
    second = reserve_upload(actor, batch, "manual")
    assert second["upload_token"] != first["upload_token"]
    assert not PrivateStorage().path(old).exists()
    finish_upload(actor, batch, second, content)
    assert reserved(tenant) == len(content)
    with pytest.raises(Problem):
        finish_upload(actor, batch, first, content)
    assert not PrivateStorage().path(old).exists()


def test_partial_unlink_failure_preserves_durable_keys_and_quota_for_retry(workspace, monkeypatch):
    tenant = workspace["tenants"][0]
    client = workspace["client"]()
    batches = [create_import(client, tenant, value) for value in (b"one", b"two")]
    for batch, value in zip(batches, (b"one", b"two"), strict=True):
        upload(client, batch, value)
        age_batch(tenant, batch)
    original = PrivateStorage.delete
    calls = []

    def fail_second(self, key):
        calls.append(key)
        if len(calls) == 2:
            raise OSError("controlled disk failure")
        original(self, key)

    with monkeypatch.context() as patch:
        patch.setattr(PrivateStorage, "delete", fail_second)
        first = sweep(tenant)
    assert first["blocked_or_failed"] == 1
    assert first["released_bytes"] == 3 and reserved(tenant) == 3
    with transaction(tenant) as connection:
        queue = (
            connection.execute(
                text("SELECT object_keys,error_code FROM storage_cleanup WHERE state='pending'")
            )
            .mappings()
            .one()
        )
        assert queue["object_keys"] and queue["error_code"] == "storage_unavailable"
    assert sweep(tenant)["released_bytes"] == 3
    assert reserved(tenant) == 0


def test_live_reference_and_other_tenant_namespace_are_never_unlinked(workspace):
    tenant, other = workspace["tenants"]
    client = workspace["client"]()
    import_document(client, tenant)
    with transaction(tenant) as connection:
        key = connection.execute(text("SELECT object_key FROM import_entries")).scalar_one()
        lock_policy(connection, tenant)
        enqueue_cleanup(connection, tenant, "guard-test", "orphan", [key])
        result = complete_cleanup(connection, tenant, "guard-test")
        assert result["error_code"] == "object_in_use"
    private = f"tenants/{other}/exports/unreferenced/result.html"
    old_file(private)
    with transaction(tenant) as connection:
        lock_policy(connection, tenant)
        enqueue_cleanup(connection, tenant, "cross-tenant", "orphan", [private])
        assert complete_cleanup(connection, tenant, "cross-tenant")["state"] == "pending"
    assert PrivateStorage().path(key).exists()
    assert PrivateStorage().path(private).exists()


def test_orphan_scan_is_bounded_preserves_recent_objects_and_unrelated_namespaces(workspace):
    tenant = workspace["tenants"][0]
    old = f"tenants/{tenant}/runs/abandoned/attempts/1/result.json"
    recent = f"tenants/{tenant}/runs/recent/attempts/1/result.json"
    unrelated = f"tenants/{tenant}/unknown/keep/file.json"
    old_file(old)
    old_file(unrelated)
    PrivateStorage().put(recent, b"not old enough")
    result = sweep(tenant)
    assert result["planned_orphans"] == 1
    assert not PrivateStorage().path(old).exists()
    assert PrivateStorage().path(recent).exists() and PrivateStorage().path(unrelated).exists()
    assert sweep(tenant, RetentionPolicy(scan_limit=1))["scanned_files"] <= 1


def test_two_sweepers_and_purge_share_entry_ownership_without_double_release(workspace):
    if os.environ.get("ED_MAINTENANCE_TEST_DATABASE_URL") != os.environ.get("ED_TEST_DATABASE_URL"):
        pytest.skip("Requires explicitly isolated ledger/test database")
    tenant = workspace["tenants"][0]
    client = workspace["client"]()
    admin = workspace["client"](role="admin")
    with transaction() as connection:
        connection.execute(
            text("UPDATE operational_ledger SET ledger_id=NULL,sequence=0,sha256=NULL WHERE id=1")
        )
    maintenance.initialize_ledger()
    import_document(client, tenant)
    with transaction(tenant) as connection:
        source = connection.execute(text("SELECT id FROM evidence")).scalar_one()
    before = reserved(tenant)
    deletion = admin.request(
        "DELETE",
        f"/api/v1/admin/evidence/{source}",
        json={"reason": "user_request"},
        headers={"Idempotency-Key": "retention-race"},
    )
    assert deletion.status_code == 202, deletion.text
    lease = acquire(tenant, "retention-race")
    assert lease and lease.kind == "purge"
    with ThreadPoolExecutor(max_workers=3) as pool:
        futures = [
            pool.submit(sweep, tenant),
            pool.submit(sweep, tenant),
            pool.submit(execute_lease, lease),
        ]
        results = [future.result() for future in futures]
    assert reserved(tenant) == 0
    with transaction(tenant) as connection:
        assert (
            connection.execute(text("SELECT sum(released_bytes) FROM storage_cleanup")).scalar_one()
            == before
        )
        assert (
            connection.execute(
                text("SELECT count(*) FROM import_entries WHERE quota_released_at IS NULL")
            ).scalar_one()
            == 0
        )
    assert all(result["blocked_or_failed"] == 0 for result in results[:2])
    assert sweep(tenant)["released_bytes"] == 0


def test_export_expiry_removes_only_export_and_keeps_revision(workspace):
    tenant = workspace["tenants"][0]
    client = workspace["client"]()
    snapshot = import_document(client, tenant)
    incident = create_incident(client)
    response = client.post(
        f"/api/v1/incidents/{incident}/dossiers",
        json={
            "evidence_snapshot_id": snapshot,
            "summary": "Retenção sem conclusão automática.",
            "claims": [],
            "outcome": "insufficient_evidence",
        },
    )
    assert response.status_code == 201, response.text
    dossier = response.json()
    key = f"tenants/{tenant}/exports/expired/1.html"
    PrivateStorage().put(key, b"private export")
    with transaction(tenant) as connection:
        connection.execute(
            text("""
            INSERT INTO exports(tenant_id,id,dossier_id,revision_id,created_by,object_key,sha256,expires_at)
            VALUES(:tenant,'expired',:dossier,:revision,:actor,:key,:hash,now()-interval '1 second')
        """),
            {
                "tenant": tenant,
                "dossier": dossier["id"],
                "revision": dossier["current_revision_id"],
                "actor": tenant + "-author",
                "key": key,
                "hash": hashlib.sha256(b"private export").hexdigest(),
            },
        )
    before = reserved(tenant)
    assert sweep(tenant)["planned_exports"] == 1
    assert not PrivateStorage().path(key).exists()
    assert reserved(tenant) == before
    assert client.get(f"/api/v1/dossiers/{dossier['id']}").status_code == 200


def test_audit_retention_has_90_day_floor_and_tenant_scope(workspace):
    tenant, other = workspace["tenants"]
    with workspace["admin"].begin() as connection:
        for identity in (tenant, other):
            connection.execute(
                text("""
                INSERT INTO audit_events(tenant_id,id,action,resource_id,policy_revision,created_at)
                VALUES(:tenant,'old','fixture','fixture',1,now()-interval '91 days'),
                  (:tenant,'recent','fixture','fixture',1,now()-interval '89 days')
            """),
                {"tenant": identity},
            )
    assert sweep(tenant)["audit_events_removed"] == 1
    with transaction(tenant) as connection:
        assert connection.execute(text("SELECT id FROM audit_events")).scalars().all() == ["recent"]
    with transaction(other) as connection:
        assert connection.execute(text("SELECT count(*) FROM audit_events")).scalar_one() == 2
    with (
        pytest.raises(DBAPIError, match="tenant context required"),
        transaction(tenant) as connection,
    ):
        connection.execute(
            text("SELECT public.expire_audit_events(:other,90,10)"), {"other": other}
        )
    with (
        pytest.raises(DBAPIError, match="invalid retention bound"),
        transaction(tenant) as connection,
    ):
        connection.execute(
            text("SELECT public.expire_audit_events(:tenant,89,10)"), {"tenant": tenant}
        )
    with pytest.raises(ValueError):
        RetentionPolicy(temporary_hours=1)


def test_progress_retention_keeps_recent_events_and_active_job_history(workspace):
    tenant = workspace["tenants"][0]
    client = workspace["client"]()
    snapshot = import_document(client, tenant)
    incident = create_incident(client)
    with transaction(tenant) as connection:
        for run, state in (("terminal", "succeeded"), ("active", "running")):
            values = {
                "tenant": tenant,
                "run": run,
                "state": state,
                "snapshot": snapshot,
                "incident": incident,
                "actor": tenant + "-author",
            }
            connection.execute(
                text("""
                INSERT INTO investigation_runs(tenant_id,id,incident_id,snapshot_id,created_by,question,policy_revision,model_release)
                VALUES(:tenant,:run,:incident,:snapshot,:actor,'Fixture',1,'{}')
            """),
                values,
            )
            connection.execute(
                text("""
                INSERT INTO jobs(tenant_id,id,kind,resource_id,actor_id,state,deadline,policy_revision,completed_at)
                VALUES(:tenant,:run,'investigation',:run,:actor,:state,now()+interval '1 hour',1,
                  CASE WHEN :state='succeeded' THEN now()-interval '8 days' ELSE NULL END)
            """),
                values,
            )
            connection.execute(
                text("""
                INSERT INTO run_events(tenant_id,run_id,seq,type,payload,created_at)
                VALUES(:tenant,:run,1,'progress','{}',now()-interval '8 days'),
                  (:tenant,:run,2,'progress','{}',now()-interval '6 days')
            """),
                values,
            )
    assert sweep(tenant)["progress_events_removed"] == 1
    with transaction(tenant) as connection:
        remaining = connection.execute(
            text("SELECT run_id,seq FROM run_events ORDER BY run_id,seq")
        ).all()
        assert remaining == [("active", 1), ("active", 2), ("terminal", 2)]


def test_ledger_replay_releases_real_reservation_once_after_rolled_back_tombstone(workspace):
    if os.environ.get("ED_MAINTENANCE_TEST_DATABASE_URL") != os.environ.get("ED_TEST_DATABASE_URL"):
        pytest.skip("Requires explicitly isolated ledger/test database")
    from evidencedesk.deletion_ledger import append_intent

    tenant = workspace["tenants"][0]
    client = workspace["client"]()
    with transaction() as connection:
        connection.execute(
            text("UPDATE operational_ledger SET ledger_id=NULL,sequence=0,sha256=NULL WHERE id=1")
        )
    maintenance.initialize_ledger()
    import_document(client, tenant)
    before = reserved(tenant)
    with transaction(tenant) as connection:
        source = (
            connection.execute(text("SELECT id,collection_id,sha256,original_key FROM evidence"))
            .mappings()
            .one()
        )
    with pytest.raises(RuntimeError, match="commit"), transaction(tenant) as connection:
        lock_policy(connection, tenant)
        append_intent(
            connection,
            tenant,
            source["id"],
            source["original_key"],
            collection_id=source["collection_id"],
            source_sha256=source["sha256"],
        )
        raise RuntimeError("crash before DB commit")
    with pytest.raises(maintenance.MaintenanceFailure) as failure:
        maintenance.enter(0)
    token = failure.value.state["maintenance_token"]
    maintenance.reconcile_ledger(token, restore_mode=True)
    assert reserved(tenant) == 0
    assert not PrivateStorage().path(source["original_key"]).exists()
    maintenance.reconcile_ledger(token, restore_mode=True)
    assert reserved(tenant) == 0
    with transaction(tenant) as connection:
        assert (
            connection.execute(text("SELECT sum(released_bytes) FROM storage_cleanup")).scalar_one()
            == before
        )
    maintenance.leave(token)


def test_scan_cursor_advances_past_recent_files_to_old_orphans(workspace):
    tenant = workspace["tenants"][0]
    recent = f"tenants/{tenant}/runs/aaa/attempts/1/result.json"
    orphan = f"tenants/{tenant}/runs/zzz/attempts/1/result.json"
    PrivateStorage().put(recent, b"recent")
    old_file(orphan)
    first = sweep(tenant, RetentionPolicy(scan_limit=1))
    assert first["scan_truncated"] and first["scan_cursor"] == recent
    assert PrivateStorage().path(orphan).exists()
    second = sweep(tenant, RetentionPolicy(scan_limit=1))
    assert second["planned_orphans"] == 1
    assert not PrivateStorage().path(orphan).exists()
    assert PrivateStorage().path(recent).exists()
