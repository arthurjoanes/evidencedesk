import hashlib
import os

import pytest
from sqlalchemy import text
from test_manual_workflow import create_incident, import_document

from evidencedesk.database import transaction
from evidencedesk.evidence.storage import PrivateStorage
from evidencedesk.jobs.service import acquire
from evidencedesk.maintenance import initialize_ledger
from evidencedesk.worker import execute_lease

pytestmark = pytest.mark.integration


def test_grant_revocation_hides_all_incident_surfaces_and_cancels_work(workspace):
    author = workspace["client"]()
    admin = workspace["client"](role="admin")
    outsider = workspace["client"](1, role="admin")
    tenant = workspace["tenants"][0]
    snapshot = import_document(author, tenant)
    incident = create_incident(author)
    assert author.get("/api/v1/admin/users").status_code == 403
    response = admin.put(
        f"/api/v1/admin/collections/collection/members/{tenant}-author", json={"granted": False}
    )
    assert response.status_code == 200, response.text
    assert author.get(f"/api/v1/incidents/{incident}").status_code == 404
    assert (
        author.get(
            f"/api/v1/incidents/{incident}/timeline", params={"evidence_snapshot_id": snapshot}
        ).status_code
        == 404
    )
    assert author.get("/api/v1/collections").json()["items"] == []
    assert (
        outsider.put(
            f"/api/v1/admin/collections/collection/members/{tenant}-author", json={"granted": True}
        ).status_code
        == 404
    )
    restored = admin.put(
        f"/api/v1/admin/collections/collection/members/{tenant}-author",
        json={"granted": True, "incident_ids": [incident]},
    )
    assert restored.status_code == 200, restored.text
    assert author.get(f"/api/v1/incidents/{incident}").status_code == 200


def test_tombstone_durable_purge_duplicate_copies_and_reimport_block(workspace):
    if os.environ.get("ED_MAINTENANCE_TEST_DATABASE_URL") != os.environ.get("ED_TEST_DATABASE_URL"):
        pytest.skip("Deletion test needs an explicitly isolated maintenance database.")
    with transaction() as connection:
        connection.execute(
            text("UPDATE operational_ledger SET ledger_id=NULL,sequence=0,sha256=NULL WHERE id=1")
        )
    initialize_ledger()
    author = workspace["client"]()
    admin = workspace["client"](role="admin")
    tenant = workspace["tenants"][0]
    import_document(author, tenant)
    snapshot = import_document(author, tenant)  # a second immutable object, same evidence identity
    incident = create_incident(author)
    with transaction(tenant) as connection:
        source = dict(
            connection.execute(text("SELECT id,sha256 FROM evidence WHERE kind='document_span'"))
            .mappings()
            .one()
        )
        keys = connection.execute(text("SELECT object_key FROM import_entries")).scalars().all()
        reserved = connection.execute(
            text("SELECT storage_reserved FROM tenant_policy")
        ).scalar_one()
    assert len(keys) == 2 and len(set(keys)) == 2 and reserved > 0
    dossier = author.post(
        f"/api/v1/incidents/{incident}/dossiers",
        json={
            "evidence_snapshot_id": snapshot,
            "summary": "Fonte a conferir",
            "outcome": "evidence_found",
            "claims": [
                {
                    "kind": "observed_fact",
                    "text": "Há um procedimento",
                    "evidence_links": [{"evidence_id": source["id"], "relation": "supports"}],
                }
            ],
        },
    )
    assert dossier.status_code == 201, dossier.text
    url = f"/api/v1/admin/evidence/{source['id']}"
    request = {"reason": "user_request"}
    assert (
        author.request(
            "DELETE", url, json=request, headers={"Idempotency-Key": "delete-fixture"}
        ).status_code
        == 403
    )
    response = admin.request(
        "DELETE", url, json=request, headers={"Idempotency-Key": "delete-fixture"}
    )
    assert response.status_code == 202, response.text
    deletion = response.json()
    assert (
        admin.request(
            "DELETE", url, json=request, headers={"Idempotency-Key": "delete-fixture"}
        ).json()["id"]
        == deletion["id"]
    )
    assert (
        author.get(
            f"/api/v1/evidence/{source['id']}", params={"evidence_snapshot_id": snapshot}
        ).status_code
        == 404
    )
    assert author.get(f"/api/v1/dossiers/{dossier.json()['id']}").status_code == 404
    assert all(
        PrivateStorage().path(key).exists() for key in keys
    )  # tombstone precedes durable deletion
    with transaction(tenant) as connection:
        connection.execute(
            text("UPDATE tenant_policy SET revision=revision+1 WHERE tenant_id=:tenant"),
            {"tenant": tenant},
        )
    lease = acquire(tenant, "deletion-fixture")
    assert lease is not None and lease.kind == "purge"
    execute_lease(lease)  # authorized deletion intent survives subsequent ACL revisions
    assert admin.get(f"/api/v1/admin/deletions/{deletion['id']}").json()["state"] == "succeeded"
    assert all(not PrivateStorage().path(key).exists() for key in keys)
    with transaction(tenant) as connection:
        assert (
            connection.execute(text("SELECT storage_reserved FROM tenant_policy")).scalar_one() == 0
        )
        assert (
            connection.execute(
                text("SELECT canonical_text FROM evidence WHERE id=:id"), {"id": source["id"]}
            ).scalar_one()
            == ""
        )
        assert connection.execute(text("SELECT claims FROM dossier_revisions")).scalar_one() == []
    content = "# Reconciliação\nConfirme o pagamento antes de processar o pedido.\n<script>privado</script>".encode()
    response = author.post(
        "/api/v1/imports",
        json={
            "collection_id": "collection",
            "manifest": {
                "schema_version": "1",
                "title": "Tentativa de reimportação",
                "source_tenant": tenant,
                "coverage": [],
                "entries": [
                    {
                        "entry_id": "copy",
                        "filename": "copy.md",
                        "kind": "document",
                        "media_type": "text/markdown",
                        "byte_size": len(content),
                        "sha256": hashlib.sha256(content).hexdigest(),
                    }
                ],
            },
        },
    )
    assert (
        response.status_code == 409
        and response.json()["error"]["code"] == "source_previously_deleted"
    )
