"""Document metadata must survive publication without silently changing meaning."""

import hashlib
import json

import pytest
from sqlalchemy import text

from evidencedesk.database import transaction
from evidencedesk.jobs.service import acquire
from evidencedesk.worker import execute_lease

pytestmark = pytest.mark.integration

CONTENT = b"Confirm the payment before processing the order."
METADATA = {
    "title": "Payment procedure",
    "version": "1",
    "source_system": "knowledge",
    "document_lineage": "payment-procedure",
    "temporal_role": "applicable_procedure",
    "valid_from": "2026-01-01T00:00:00Z",
    "valid_until": "2026-12-01T00:00:00Z",
}


def entry(metadata, *, identity="manual", content=CONTENT):
    return {
        "entry_id": identity,
        "filename": identity + ".txt",
        "kind": "document",
        "media_type": "text/plain",
        "byte_size": len(content),
        "sha256": hashlib.sha256(content).hexdigest(),
        "metadata": metadata,
    }


def create(client, entries):
    return client.post(
        "/api/v1/imports",
        json={
            "collection_id": "collection",
            "manifest": {
                "schema_version": "1",
                "title": "Metadata contract",
                "coverage": [],
                "entries": entries,
            },
        },
    )


def upload(client, entries, contents=None):
    response = create(client, entries)
    assert response.status_code == 201, response.text
    batch = response.json()["id"]
    for item in entries:
        body = (contents or {}).get(item["entry_id"], CONTENT)
        response = client.put(
            f"/api/v1/imports/{batch}/files/{item['entry_id']}",
            content=body,
            headers={"Content-Type": "text/plain"},
        )
        assert response.status_code == 200, response.text
    return batch


def publish(client, tenant, batch):
    response = client.post(f"/api/v1/imports/{batch}/finalize")
    assert response.status_code == 202, response.text
    lease = acquire(tenant, "document-metadata-test")
    assert lease is not None and lease.kind == "ingestion"
    execute_lease(lease)
    response = client.get(f"/api/v1/imports/{batch}")
    assert response.status_code == 200, response.text
    return response.json()


@pytest.mark.parametrize(
    "changed",
    [
        {"title": "Different title"},
        {"version": "2"},
        {"source_system": "other-knowledge"},
        {"document_lineage": "other-procedure"},
        {"temporal_role": "retrospective_context"},
        {"valid_from": "2026-02-01T00:00:00Z"},
        {"valid_until": "2026-11-01T00:00:00Z"},
    ],
)
def test_reimport_conflict_preserves_old_snapshot_and_rejects_entire_batch(workspace, changed):
    client, tenant = workspace["client"](), workspace["tenants"][0]
    first = publish(client, tenant, upload(client, [entry(METADATA)]))
    assert first["state"] == "ready"
    with transaction(tenant) as connection:
        original = dict(connection.execute(text("SELECT * FROM evidence")).mappings().one())
    new_content = b"Another document must not become partially visible."
    second = publish(
        client,
        tenant,
        upload(
            client,
            [
                entry(METADATA, identity="another", content=new_content),
                entry(METADATA | changed),
            ],
            {"another": new_content},
        ),
    )
    assert second["state"] == "rejected"
    assert second["error"]["code"] == "document_metadata_conflict"
    assert second["evidence_snapshot_id"] is None
    with transaction(tenant) as connection:
        assert (
            connection.execute(
                text("SELECT state FROM import_batches WHERE id=:id"), {"id": second["id"]}
            ).scalar_one()
            == "rejected"
        )
        assert (
            connection.execute(text("SELECT active_snapshot_id FROM collections")).scalar_one()
            == first["evidence_snapshot_id"]
        )
        assert connection.execute(text("SELECT count(*) FROM evidence_snapshots")).scalar_one() == 1
        assert dict(connection.execute(text("SELECT * FROM evidence")).mappings().one()) == original


@pytest.mark.parametrize("conflicting", [False, True])
def test_duplicate_document_entries_in_one_batch_are_checked_before_publication(
    workspace, conflicting
):
    client, tenant = workspace["client"](), workspace["tenants"][0]
    other = METADATA | ({"version": "2"} if conflicting else {})
    result = publish(
        client, tenant, upload(client, [entry(METADATA), entry(other, identity="copy")])
    )
    assert result["state"] == ("rejected" if conflicting else "ready")
    if conflicting:
        assert result["error"]["code"] == "document_metadata_conflict"
    with transaction(tenant) as connection:
        assert connection.execute(text("SELECT count(*) FROM evidence")).scalar_one() == (
            0 if conflicting else 1
        )
        assert connection.execute(text("SELECT count(*) FROM evidence_snapshots")).scalar_one() == (
            0 if conflicting else 1
        )


def test_equivalent_timezones_and_extra_metadata_preserve_idempotent_reimport(workspace):
    client, tenant = workspace["client"](), workspace["tenants"][0]
    first = publish(client, tenant, upload(client, [entry(METADATA)]))
    metadata = METADATA | {
        "valid_from": "2025-12-31T21:00:00-03:00",
        "valid_until": "2026-11-30T21:00:00-03:00",
        "external_reference": {"ticket": "fixture-42", "labels": ["preserve"]},
    }
    second_batch = upload(client, [entry(metadata)])
    second = publish(client, tenant, second_batch)
    assert first["state"] == second["state"] == "ready"
    assert first["evidence_snapshot_id"] != second["evidence_snapshot_id"]
    with transaction(tenant) as connection:
        assert connection.execute(text("SELECT count(*) FROM evidence")).scalar_one() == 1
        assert (
            connection.execute(
                text("SELECT count(DISTINCT evidence_id) FROM snapshot_members")
            ).scalar_one()
            == 1
        )
        stored = connection.execute(
            text("SELECT metadata FROM import_entries WHERE batch_id=:id"), {"id": second_batch}
        ).scalar_one()
        assert stored == metadata


@pytest.mark.parametrize(
    "changed",
    [
        {"temporal_role": "unexpected_role"},
        {"valid_from": "2026-01-01T00:00:00"},
        {"valid_until": "2026-12-01T00:00:00"},
        {"valid_until": "2026-01-01T00:00:00Z"},
        {"document_lineage": ["not-a-string"]},
        {"title": "a" * 301},
    ],
)
def test_invalid_known_metadata_is_rejected_before_reserving_storage(workspace, changed):
    client, tenant = workspace["client"](), workspace["tenants"][0]
    response = create(client, [entry(METADATA | changed)])
    assert response.status_code == 422, response.text
    assert response.json()["error"]["code"] == "validation_error"
    assert response.json()["error"]["field_errors"]
    with transaction(tenant) as connection:
        assert (
            connection.execute(text("SELECT storage_reserved FROM tenant_policy")).scalar_one() == 0
        )
        assert connection.execute(text("SELECT count(*) FROM import_batches")).scalar_one() == 0


@pytest.mark.parametrize(
    "changed", [{"temporal_role": "unexpected_role"}, {"valid_from": "2026-01-01T00:00:00"}]
)
def test_worker_rechecks_invalid_metadata_from_preexisting_imports(workspace, changed):
    client, tenant = workspace["client"](), workspace["tenants"][0]
    batch = upload(client, [entry(METADATA)])
    # Simulate a receiving package admitted by the previous contract, not an HTTP bypass.
    with workspace["admin"].begin() as connection:
        connection.execute(
            text(
                "UPDATE import_entries SET metadata=CAST(:metadata AS jsonb) WHERE tenant_id=:tenant AND batch_id=:batch"
            ),
            {"tenant": tenant, "batch": batch, "metadata": json.dumps(METADATA | changed)},
        )
    result = publish(client, tenant, batch)
    assert result["state"] == "rejected"
    assert result["error"]["code"] == "invalid_document_metadata"
    with transaction(tenant) as connection:
        assert connection.execute(text("SELECT count(*) FROM evidence_snapshots")).scalar_one() == 0
