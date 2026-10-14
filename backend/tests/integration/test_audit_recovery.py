from datetime import UTC, datetime

import pytest
from sqlalchemy import text
from test_manual_workflow import create_import, create_incident, import_document

pytestmark = pytest.mark.integration


def test_returned_revision_requires_a_new_draft_before_resubmission(workspace):
    author = workspace["client"]()
    reviewer = workspace["client"](role="reviewer")
    snapshot = import_document(author, workspace["tenants"][0])
    incident = create_incident(author)
    body = {
        "summary": "Ainda faltam informações para concluir.",
        "claims": [],
        "outcome": "insufficient_evidence",
    }
    dossier = author.post(
        f"/api/v1/incidents/{incident}/dossiers", json=body | {"evidence_snapshot_id": snapshot}
    ).json()
    url = "/api/v1/dossiers/" + dossier["id"]
    original = author.get(url + "/revisions/" + dossier["current_revision_id"]).json()
    assert (
        author.post(
            url + "/submit",
            json={"target_revision_id": original["id"]},
            headers={"If-Match": original["etag"]},
        ).status_code
        == 200
    )
    returned = reviewer.post(
        url + "/reviews",
        json={
            "target_revision_id": original["id"],
            "claim_ids": [],
            "decision": "changes_requested",
            "reason": "Detalhe a informação que falta.",
        },
        headers={"If-Match": original["etag"]},
    )
    assert returned.status_code == 200, returned.text
    rejected = author.post(
        url + "/submit",
        json={"target_revision_id": original["id"]},
        headers={"If-Match": original["etag"]},
    )
    assert rejected.status_code == 409
    assert rejected.json()["error"]["code"] == "revision_not_draft"
    next_revision = author.post(
        url + "/revisions",
        json=body
        | {
            "base_revision_id": original["id"],
            "missing_information": ["Estado atual do processador"],
        },
        headers={"If-Match": original["etag"]},
    )
    assert next_revision.status_code == 201, next_revision.text
    fresh = next_revision.json()
    assert fresh["id"] != original["id"] and fresh["review_status"] == "draft"
    assert (
        author.post(
            url + "/submit",
            json={"target_revision_id": fresh["id"]},
            headers={"If-Match": fresh["etag"]},
        ).status_code
        == 200
    )


def test_replay_after_committed_import_preserves_one_reservation(workspace):
    client = workspace["client"]()
    tenant = workspace["tenants"][0]
    content = b"synthetic import replay"
    client.headers["Idempotency-Key"] = "same-manifest"
    first = create_import(client, tenant, content)
    assert create_import(client, tenant, content) == first
    with workspace["admin"].connect() as connection:
        assert (
            connection.execute(
                text("SELECT count(*) FROM import_batches WHERE tenant_id=:tenant"),
                {"tenant": tenant},
            ).scalar_one()
            == 1
        )
        assert connection.execute(
            text("SELECT storage_reserved FROM tenant_policy WHERE tenant_id=:tenant"),
            {"tenant": tenant},
        ).scalar_one() == len(content)
    # The helper's response body was committed. A changed body must not reuse its key.
    body = {
        "collection_id": "collection",
        "manifest": {"schema_version": "1", "title": "changed", "coverage": [], "entries": []},
    }
    # Use a valid manifest from the existing batch for a fingerprint-only conflict.
    with workspace["admin"].connect() as connection:
        body["manifest"] = connection.execute(
            text("SELECT manifest FROM import_batches WHERE tenant_id=:tenant AND id=:id"),
            {"tenant": tenant, "id": first},
        ).scalar_one()
    body["manifest"]["title"] = "changed"
    response = client.post("/api/v1/imports", json=body)
    assert response.status_code == 409
    assert response.json()["error"]["code"] == "idempotency_conflict"


def test_snapshots_paginate_timestamp_ties_and_recheck_access(workspace):
    client = workspace["client"]()
    tenant = workspace["tenants"][0]
    import_document(client, tenant)
    incident = create_incident(client)
    ids = [f"snapshot-{index:03}" for index in range(55)]
    with workspace["admin"].begin() as connection:
        connection.execute(
            text(
                "INSERT INTO evidence_snapshots(tenant_id,id,collection_id,coverage,published_at) VALUES(:tenant,:id,'collection','[]',:date)"
            ),
            [
                {"tenant": tenant, "id": item, "date": datetime(2026, 1, 1, tzinfo=UTC)}
                for item in ids
            ],
        )
    assert client.get(f"/api/v1/incidents/{incident}").json()["available_snapshots_truncated"]
    url = f"/api/v1/incidents/{incident}/snapshots"
    first = client.get(url).json()
    second = client.get(url, params={"cursor": first["next_cursor"]}).json()
    visible = [item["id"] for item in first["items"] + second["items"]]
    assert len(visible) == len(set(visible)) == 56
    assert set(ids).issubset(visible)
    assert second["next_cursor"] is None
    assert (
        workspace["client"](tenant_index=1)
        .get(url, params={"cursor": first["next_cursor"]})
        .status_code
        == 409
    )
    with workspace["admin"].begin() as connection:
        connection.execute(
            text("DELETE FROM collection_grants WHERE tenant_id=:tenant AND user_id=:user"),
            {"tenant": tenant, "user": tenant + "-author"},
        )
    assert client.get(url, params={"cursor": first["next_cursor"]}).status_code == 404
