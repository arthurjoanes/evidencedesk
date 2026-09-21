import json
import os
from concurrent.futures import ThreadPoolExecutor
from uuid import uuid4

import pytest
from sqlalchemy import create_engine, text

from evidencedesk import maintenance
from evidencedesk.config import get_settings
from evidencedesk.database import get_engine, lock_policy, transaction
from evidencedesk.deletion_ledger import append_intent, read_ledger

pytestmark = pytest.mark.integration


@pytest.fixture
def isolated_ledger(tmp_path, monkeypatch):
    url = os.environ.get("ED_MAINTENANCE_TEST_DATABASE_URL")
    if not url:
        pytest.skip("Requires an explicitly isolated maintenance test database.")
    monkeypatch.setenv("ED_DATABASE_URL", url)
    monkeypatch.setenv("ED_STORAGE_ROOT", str(tmp_path / "objects"))
    monkeypatch.setenv("ED_DELETION_LEDGER_ROOT", str(tmp_path / "ledger"))
    get_engine.cache_clear()
    get_settings.cache_clear()
    (tmp_path / "objects").mkdir()
    with transaction() as connection:
        connection.execute(
            text(
                "UPDATE operational_control SET maintenance=false,maintenance_token=NULL WHERE id=1"
            )
        )
        connection.execute(
            text("UPDATE operational_ledger SET ledger_id=NULL,sequence=0,sha256=NULL WHERE id=1")
        )
    maintenance.initialize_ledger()
    yield tmp_path
    with transaction() as connection:
        connection.execute(
            text(
                "UPDATE operational_control SET maintenance=false,maintenance_token=NULL WHERE id=1"
            )
        )
    get_engine().dispose()
    get_engine.cache_clear()
    get_settings.cache_clear()


def fixture_tenant():
    tenant = uuid4().hex
    user = uuid4().hex
    owner = create_engine(os.environ["ED_MAINTENANCE_TEST_OWNER_URL"])
    with owner.begin() as connection:
        connection.execute(
            text("INSERT INTO tenants(id,name) VALUES(:tenant,'Maintenance test')"),
            {"tenant": tenant},
        )
        connection.execute(
            text(
                "INSERT INTO users(id,tenant_id,email,name,password_hash,role) VALUES(:user,:tenant,:email,'Test','disabled','analyst')"
            ),
            {"user": user, "tenant": tenant, "email": f"{user}@test.invalid"},
        )
    owner.dispose()
    with transaction(tenant) as connection:
        connection.execute(
            text("INSERT INTO tenant_policy(tenant_id) VALUES(:tenant)"), {"tenant": tenant}
        )
        connection.execute(
            text("INSERT INTO collections(tenant_id,id,name) VALUES(:tenant,'collection','Test')"),
            {"tenant": tenant},
        )
        connection.execute(
            text(
                "INSERT INTO evidence_snapshots(tenant_id,id,collection_id,coverage) VALUES(:tenant,'snapshot','collection','[]')"
            ),
            {"tenant": tenant},
        )
        connection.execute(
            text("""
            INSERT INTO evidence(tenant_id,id,collection_id,kind,title,version,sha256,source_system,temporal_role,canonical_text,original_key)
            VALUES(:tenant,'source','collection','document_span','Private','1',:sha,'orders','observed','private text',:key)
        """),
            {"tenant": tenant, "sha": "a" * 64, "key": f"{tenant}/source.txt"},
        )
        connection.execute(
            text(
                "INSERT INTO snapshot_members(tenant_id,snapshot_id,evidence_id) VALUES(:tenant,'snapshot','source')"
            ),
            {"tenant": tenant},
        )
        connection.execute(
            text("""
            INSERT INTO incidents(tenant_id,id,collection_id,title,window_from,window_to,time_zone,snapshot_id,created_by)
            VALUES(:tenant,'incident','collection','Test',now()-interval '1 day',now(),'UTC','snapshot',:user)
        """),
            {"tenant": tenant, "user": user},
        )
        connection.execute(
            text(
                "INSERT INTO dossiers(tenant_id,id,incident_id,snapshot_id,origin,created_by) VALUES(:tenant,'dossier','incident','snapshot','manual',:user)"
            ),
            {"tenant": tenant, "user": user},
        )
        connection.execute(
            text("""
            INSERT INTO dossier_revisions(tenant_id,id,dossier_id,number,summary,claims,outcome,created_by)
            VALUES(:tenant,'revision','dossier',1,'private derived text','[]','insufficient_evidence',:user)
        """),
            {"tenant": tenant, "user": user},
        )
    return tenant, user


def test_maintenance_has_exactly_one_owner_and_wrong_token_cannot_release(isolated_ledger):
    def attempt():
        try:
            return maintenance.enter(0)
        except maintenance.MaintenanceFailure:
            return None

    with ThreadPoolExecutor(max_workers=2) as executor:
        attempts = list(executor.map(lambda _: attempt(), range(2)))
    owners = [state for state in attempts if state]
    assert len(owners) == 1
    assert "maintenance_token" not in maintenance.status()
    with pytest.raises(maintenance.MaintenanceFailure, match="ownership"):
        maintenance.leave("wrong")
    assert maintenance.status()["maintenance"] is True
    assert maintenance.leave(owners[0]["maintenance_token"])["maintenance"] is False


def test_active_job_keeps_timeout_closed_and_preserves_recovery_token(isolated_ledger):
    tenant, user = fixture_tenant()
    with transaction(tenant) as connection:
        connection.execute(
            text("""
            INSERT INTO jobs(tenant_id,id,kind,resource_id,actor_id,deadline,policy_revision,state,lease_until)
            VALUES(:tenant,'job','ingestion','resource',:user,now()+interval '1 minute',1,'running',now()-interval '1 second')
        """),
            {"tenant": tenant, "user": user},
        )
    with pytest.raises(maintenance.MaintenanceFailure, match="timed out") as failure:
        maintenance.enter(0)
    assert failure.value.state["active_jobs"] == 1
    token = failure.value.state["maintenance_token"]
    assert maintenance.status()["maintenance"] is True
    with transaction(tenant) as connection:
        connection.execute(text("UPDATE jobs SET state='failed' WHERE id='job'"))
    maintenance.leave(token)


def test_missing_checkpoint_blocks_leave_without_disabling_maintenance(isolated_ledger):
    token = maintenance.enter(0)["maintenance_token"]
    checkpoint = isolated_ledger / "ledger/checkpoint.json"
    data = checkpoint.read_bytes()
    checkpoint.unlink()
    with pytest.raises(ValueError, match="missing"):
        maintenance.leave(token)
    assert maintenance.status()["maintenance"] is True
    checkpoint.write_bytes(data)
    maintenance.leave(token)


def test_deletion_redacts_derived_content_without_broad_update_permission(isolated_ledger):
    tenant, _ = fixture_tenant()
    other, _ = fixture_tenant()
    with transaction(tenant) as connection:
        lock_policy(connection, tenant, mutation=True)
        result = maintenance.record_deletion(connection, tenant, "source")
    assert result["evidence"] == 1
    assert result["dossiers"] == 1
    with transaction(tenant) as connection:
        assert (
            connection.execute(
                text("SELECT has_table_privilege(current_user,'dossier_revisions','UPDATE')")
            ).scalar_one()
            is False
        )
        row = connection.execute(
            text("SELECT canonical_text,tombstoned_at,original_key FROM evidence WHERE id='source'")
        ).one()
        assert row.canonical_text == "" and row.tombstoned_at and row.original_key is None
        assert (
            connection.execute(
                text("SELECT summary FROM dossier_revisions WHERE id='revision'")
            ).scalar_one()
            == "Conteúdo removido por exclusão de fonte."
        )
    with transaction(other) as connection:
        assert (
            connection.execute(
                text("SELECT canonical_text FROM evidence WHERE id='source'")
            ).scalar_one()
            == "private text"
        )
    assert read_ledger().checkpoint["sequence"] == 1
    assert maintenance.status()["ledger_ready"] is True


def test_current_ledger_reapplies_deletion_to_a_rolled_back_database_checkpoint(isolated_ledger):
    tenant, _ = fixture_tenant()
    original_checkpoint = read_ledger().checkpoint
    source_path = isolated_ledger / "objects" / tenant / "source.txt"
    source_path.parent.mkdir()
    source_path.write_text("private text", encoding="utf-8")
    with transaction(tenant) as connection:
        lock_policy(connection, tenant, mutation=True)
        maintenance.record_deletion(connection, tenant, "source")
    # Model the relevant restored DB rows; the full pg_dump path has a separate ops test.
    with transaction(tenant) as connection:
        connection.execute(
            text(
                "UPDATE evidence SET tombstoned_at=NULL,canonical_text='restored private text',original_key=:key WHERE id='source'"
            ),
            {"key": f"{tenant}/source.txt"},
        )
        connection.execute(
            text("UPDATE operational_ledger SET sequence=:sequence,sha256=:sha256 WHERE id=1"),
            original_checkpoint,
        )
        connection.execute(
            text(
                "UPDATE operational_control SET maintenance=true,maintenance_token='restore-owner' WHERE id=1"
            )
        )
    assert maintenance.status()["ledger_ready"] is False
    with pytest.raises(maintenance.MaintenanceFailure, match="explicit"):
        maintenance.reconcile_ledger("restore-owner", restore_mode=False)
    result = maintenance.reconcile_ledger("restore-owner", restore_mode=True)
    assert result["ledger_ready"] is True and result["maintenance"] is True
    assert not source_path.exists()
    with transaction(tenant) as connection:
        assert (
            connection.execute(
                text("SELECT canonical_text FROM evidence WHERE id='source'")
            ).scalar_one()
            == ""
        )
    maintenance.leave("restore-owner")


def test_redaction_function_requires_matching_rls_context(isolated_ledger):
    tenant, _ = fixture_tenant()
    other, _ = fixture_tenant()
    with (
        pytest.raises(Exception, match="tenant context required"),
        transaction(tenant) as connection,
    ):
        connection.execute(
            text("SELECT public.redact_tombstoned_revisions(:tenant)"), {"tenant": other}
        )


def fixture_copies(tenant, user, *, collection="collection", state="uploaded"):
    keys = [f"{tenant}/{collection}-copy-{number}.txt" for number in (1, 2)]
    with transaction(tenant) as connection:
        connection.execute(
            text("""
            INSERT INTO import_batches(tenant_id,id,collection_id,created_by,title,manifest,state)
            VALUES(:tenant,:collection,:collection,:user,'Repeated file','{}','receiving')
        """),
            {"tenant": tenant, "collection": collection, "user": user},
        )
        for number, key in enumerate(keys):
            connection.execute(
                text("""
                INSERT INTO import_entries(tenant_id,batch_id,id,filename,kind,media_type,byte_size,sha256,state,object_key)
                VALUES(:tenant,:collection,:id,'source.txt','document','text/plain',12,:sha,:state,:key)
            """),
                {
                    "tenant": tenant,
                    "collection": collection,
                    "id": str(number),
                    "sha": "a" * 64,
                    "state": state,
                    "key": key,
                },
            )
    return keys


def test_file_deletion_removes_duplicate_imports_and_derived_bytes_but_preserves_other_collection(
    isolated_ledger,
):
    tenant, user = fixture_tenant()
    copies = fixture_copies(tenant, user)
    with transaction(tenant) as connection:
        connection.execute(
            text("INSERT INTO collections(tenant_id,id,name) VALUES(:tenant,'other','Keep')"),
            {"tenant": tenant},
        )
        for evidence_id, collection, kind, sha, record in [
            (
                "derived",
                "collection",
                "reconciliation_result",
                "b" * 64,
                {"source_ids": ["source"], "snapshot_id": "snapshot"},
            ),
            ("protected", "other", "document_span", "a" * 64, {}),
        ]:
            connection.execute(
                text("""
                INSERT INTO evidence(tenant_id,id,collection_id,kind,title,version,sha256,source_system,temporal_role,canonical_text,record)
                VALUES(:tenant,:id,:collection,:kind,'Fixture','1',:sha,'orders','observed','content to inspect',CAST(:record AS jsonb))
            """),
                {
                    "tenant": tenant,
                    "id": evidence_id,
                    "collection": collection,
                    "kind": kind,
                    "sha": sha,
                    "record": json.dumps(record),
                },
            )
    protected_copies = fixture_copies(tenant, user, collection="other")
    for key in copies + protected_copies + [f"{tenant}/source.txt"]:
        path = isolated_ledger / "objects" / key
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text("private data", encoding="utf-8")
    with transaction(tenant) as connection:
        lock_policy(connection, tenant, mutation=True)
        result = maintenance.record_deletion(connection, tenant, "source")
    assert result["evidence"] == 2
    assert set(copies).issubset(result["object_keys"])
    assert not set(protected_copies).intersection(result["object_keys"])
    maintenance.purge_objects(result["object_keys"])
    with transaction(tenant) as connection:
        derived = connection.execute(
            text("SELECT canonical_text,record,tombstoned_at FROM evidence WHERE id='derived'")
        ).one()
        assert derived.canonical_text == "" and derived.record == {} and derived.tombstoned_at
        assert (
            connection.execute(
                text("SELECT canonical_text FROM evidence WHERE id='protected'")
            ).scalar_one()
            == "content to inspect"
        )
        assert (
            connection.execute(
                text(
                    "SELECT count(*) FROM import_entries WHERE batch_id='collection' AND object_key IS NOT NULL"
                )
            ).scalar_one()
            == 0
        )
    assert all(not (isolated_ledger / "objects" / key).exists() for key in copies)
    assert all((isolated_ledger / "objects" / key).exists() for key in protected_copies)
    intent = read_ledger().records[0]
    assert intent["collection_id"] == "collection" and intent["source_sha256"] == "a" * 64


def test_delete_waits_for_upload_producer_before_writing_durable_intent(isolated_ledger):
    tenant, user = fixture_tenant()
    fixture_copies(tenant, user, state="uploading")
    try:
        with (
            pytest.raises(maintenance.MaintenanceFailure, match="uploads"),
            transaction(tenant) as connection,
        ):
            lock_policy(connection, tenant, mutation=True)
            maintenance.record_deletion(connection, tenant, "source")
        assert read_ledger().records == ()
    finally:
        with transaction(tenant) as connection:
            connection.execute(
                text("UPDATE import_entries SET state='uploaded' WHERE state='uploading'")
            )


def test_replay_retains_duplicate_references_after_unlink_failure_and_works_without_original_row(
    isolated_ledger, monkeypatch
):
    tenant, user = fixture_tenant()
    copies = fixture_copies(tenant, user)
    for key in copies:
        path = isolated_ledger / "objects" / key
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text("private data", encoding="utf-8")
    # Durable intent exists in today's ledger, but its originating evidence row was
    # created after the restored database. Older copies still share hash+collection.
    with pytest.raises(RuntimeError), transaction(tenant) as connection:
        lock_policy(connection, tenant, mutation=True)
        append_intent(
            connection,
            tenant,
            "created-after-backup",
            None,
            collection_id="collection",
            source_sha256="a" * 64,
        )
        raise RuntimeError("crash before database commit")
    with pytest.raises(maintenance.MaintenanceFailure) as failure:
        maintenance.enter(0)
    token = failure.value.state["maintenance_token"]
    from evidencedesk.evidence.storage import PrivateStorage

    original_delete = PrivateStorage.delete
    deleted = []

    def incomplete_purge(self, key):
        if deleted:
            raise OSError("simulated failed unlink")
        original_delete(self, key)
        deleted.append(key)

    with monkeypatch.context() as context:
        context.setattr(PrivateStorage, "delete", incomplete_purge)
        with pytest.raises(maintenance.MaintenanceFailure, match="cleanup"):
            maintenance.reconcile_ledger(token, restore_mode=True)
    assert maintenance.status()["maintenance"] is True
    assert maintenance.status()["ledger_ready"] is False
    with transaction(tenant) as connection:
        assert (
            connection.execute(
                text("SELECT count(*) FROM import_entries WHERE object_key IS NOT NULL")
            ).scalar_one()
            == 2
        )
    result = maintenance.reconcile_ledger(token, restore_mode=True)
    assert result["ledger_ready"] is True and result["redacted_evidence"] == 1
    assert all(not (isolated_ledger / "objects" / key).exists() for key in copies)
    maintenance.leave(token)
