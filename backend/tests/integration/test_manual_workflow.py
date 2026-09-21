"""Exercise the public API, real PostgreSQL RLS and actual private file publication."""

import hashlib
from concurrent.futures import ThreadPoolExecutor

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import text

from evidencedesk.database import transaction
from evidencedesk.errors import Problem
from evidencedesk.identity.service import actor_for_worker
from evidencedesk.investigations.streams import release_stream, reserve_stream
from evidencedesk.jobs.service import acquire, assert_publishable, cancel
from evidencedesk.worker import execute_lease

pytestmark = pytest.mark.integration
ORIGIN = "http://localhost:3106"
PASSWORD = "Fixture-only-password!"


def create_import(client, tenant, content):
    response = client.post(
        "/api/v1/imports",
        json={
            "collection_id": "collection",
            "manifest": {
                "schema_version": "1",
                "title": "Documento de operação",
                "source_tenant": tenant,
                "coverage": [],
                "entries": [
                    {
                        "entry_id": "manual",
                        "filename": "manual.md",
                        "kind": "document",
                        "media_type": "text/markdown",
                        "byte_size": len(content),
                        "sha256": hashlib.sha256(content).hexdigest(),
                        "metadata": {
                            "title": "Procedimento de reconciliação",
                            "version": "1",
                            "temporal_role": "historical_artifact",
                        },
                    }
                ],
            },
        },
    )
    assert response.status_code == 201, response.text
    return response.json()["id"]


def import_document(client, tenant):
    content = "# Reconciliação\nConfirme o pagamento antes de processar o pedido.\n<script>privado</script>".encode()
    import_id = create_import(client, tenant, content)
    response = client.put(
        f"/api/v1/imports/{import_id}/files/manual",
        content=content,
        headers={"Content-Type": "text/markdown"},
    )
    assert response.status_code == 200, response.text
    response = client.post(f"/api/v1/imports/{import_id}/finalize")
    assert response.status_code == 202, response.text
    lease = acquire(tenant, "api-workflow-test")
    assert lease is not None and lease.kind == "ingestion"
    execute_lease(lease)
    response = client.get(f"/api/v1/imports/{import_id}")
    assert response.json()["state"] == "ready", response.text
    return response.json()["evidence_snapshot_id"]


def create_incident(client):
    response = client.post(
        "/api/v1/incidents",
        json={
            "title": "Pagamentos sem correspondência",
            "collection_id": "collection",
            "window": {
                "from": "2026-08-01T10:00:00Z",
                "to": "2026-08-01T12:00:00Z",
                "time_zone": "UTC",
            },
        },
    )
    assert response.status_code == 201, response.text
    return response.json()["id"]


def test_import_review_conflict_independent_approval_and_escaped_export(workspace):
    client = workspace["client"]()
    tenant = workspace["tenants"][0]
    snapshot = import_document(client, tenant)
    incident = create_incident(client)
    with transaction(tenant) as connection:
        evidence = connection.execute(
            text("SELECT id FROM evidence WHERE kind='document_span'")
        ).scalar_one()
    body = {
        "evidence_snapshot_id": snapshot,
        "summary": "<script>alert('unsafe')</script> Verificação manual.",
        "outcome": "evidence_found",
        "claims": [
            {
                "kind": "observed_fact",
                "text": "O procedimento exige confirmação de pagamento.",
                "evidence_links": [{"evidence_id": evidence, "relation": "supports"}],
            }
        ],
        "missing_information": ["Estado atual do processador"],
        "suggested_checks": ["Conferir o extrato"],
    }
    response = client.post(f"/api/v1/incidents/{incident}/dossiers", json=body)
    assert response.status_code == 201, response.text
    dossier = response.json()
    first = dossier["current_revision_id"]
    url = f"/api/v1/dossiers/{dossier['id']}"
    revision = client.get(f"{url}/revisions/{first}").json()
    assert revision["impact_summary"]["source"] == "deterministic_reconciliation"
    assert revision["missing_information"] == body["missing_information"]
    assert (
        client.post(
            f"{url}/exports",
            json={"revision_id": first},
            headers={"Idempotency-Key": "before-approval"},
        ).status_code
        == 409
    )
    edit = {key: value for key, value in body.items() if key != "evidence_snapshot_id"}
    edit["claims"] = revision["claims"]
    edit["base_revision_id"] = first
    changed = client.post(f"{url}/revisions", json=edit, headers={"If-Match": revision["etag"]})
    assert changed.status_code == 201, changed.text
    second = changed.json()
    assert second["claims"][0]["claim_id"] == revision["claims"][0]["claim_id"]
    assert (
        client.post(
            f"{url}/revisions", json=edit, headers={"If-Match": revision["etag"]}
        ).status_code
        == 409
    )
    response = client.post(
        f"{url}/submit",
        json={"target_revision_id": second["id"]},
        headers={"If-Match": second["etag"]},
    )
    assert response.status_code == 200, response.text
    decision = {
        "target_revision_id": second["id"],
        "claim_ids": [second["claims"][0]["claim_id"]],
        "decision": "approved",
        "reason": "Conferi a fonte e o recorte.",
    }
    assert (
        client.post(
            f"{url}/reviews", json=decision, headers={"If-Match": second["etag"]}
        ).status_code
        == 403
    )
    reviewer = workspace["client"](role="reviewer")
    response = reviewer.post(f"{url}/reviews", json=decision, headers={"If-Match": second["etag"]})
    assert response.status_code == 200, response.text
    assert response.json()["claims"][0]["support_status"] == "reviewed"
    exported = client.post(
        f"{url}/exports",
        json={"revision_id": second["id"]},
        headers={"Idempotency-Key": "approved-export"},
    )
    assert exported.status_code == 202, exported.text
    export_id = exported.json()["id"]
    assert (
        client.post(
            f"{url}/exports",
            json={"revision_id": second["id"]},
            headers={"Idempotency-Key": "approved-export"},
        ).json()["id"]
        == export_id
    )
    lease = acquire(tenant, "api-workflow-test")
    assert lease is not None and lease.kind == "export"
    execute_lease(lease)
    download = client.get(f"/api/v1/exports/{export_id}/download")
    assert download.status_code == 200, download.text
    assert "<script>" not in download.text and "&lt;script&gt;" in download.text
    assert "Estado atual do processador" in download.text
    assert "Conferi a fonte e o recorte." in download.text
    assert "default-src 'none'" in download.headers["Content-Security-Policy"]
    assert client.get(f"{url}/revisions/{first}").json()["summary"] == body["summary"]
    assert (
        client.get(f"/api/v1/incidents/{incident}/dossiers").json()["items"][0]["id"]
        == dossier["id"]
    )


def test_cross_tenant_http_rls_connection_reuse_and_revoked_derived_data(workspace):
    client = workspace["client"]()
    other = workspace["client"](1)
    tenant, other_tenant = workspace["tenants"]
    snapshot = import_document(client, tenant)
    incident = create_incident(client)
    assert other.get(f"/api/v1/incidents/{incident}").status_code == 404
    with transaction(tenant) as connection:
        evidence = connection.execute(
            text("SELECT id FROM evidence WHERE kind='document_span'")
        ).scalar_one()
    with transaction(other_tenant) as connection:
        assert (
            connection.execute(
                text("SELECT count(*) FROM evidence WHERE id=:id"), {"id": evidence}
            ).scalar_one()
            == 0
        )
    with transaction() as connection:
        assert (
            connection.execute(
                text("SELECT count(*) FROM evidence WHERE id=:id"), {"id": evidence}
            ).scalar_one()
            == 0
        )
    response = client.post(
        f"/api/v1/incidents/{incident}/dossiers",
        json={
            "evidence_snapshot_id": snapshot,
            "summary": "Fonte inicial",
            "outcome": "evidence_found",
            "claims": [
                {
                    "kind": "observed_fact",
                    "text": "Procedimento disponível",
                    "evidence_links": [{"evidence_id": evidence, "relation": "supports"}],
                }
            ],
        },
    )
    assert response.status_code == 201, response.text
    dossier_id = response.json()["id"]
    assert other.get(f"/api/v1/dossiers/{dossier_id}").status_code == 404
    with workspace["admin"].begin() as connection:
        connection.execute(
            text("UPDATE evidence SET tombstoned_at=now() WHERE tenant_id=:tenant AND id=:id"),
            {"tenant": tenant, "id": evidence},
        )
    assert client.get(f"/api/v1/dossiers/{dossier_id}").status_code == 404
    assert client.get(f"/api/v1/incidents/{incident}/dossiers").json()["items"] == []


def test_hash_sealing_csrf_and_cancelled_worker_cannot_publish(workspace):
    client = workspace["client"]()
    tenant = workspace["tenants"][0]
    content = b"abcd"
    import_id = create_import(client, tenant, content)
    url = f"/api/v1/imports/{import_id}"
    assert client.post(url + "/finalize").status_code == 409
    assert (
        client.put(
            url + "/files/manual", content=b"bad!", headers={"Content-Type": "text/markdown"}
        ).status_code
        == 422
    )
    response = client.put(
        url + "/files/manual", content=content, headers={"Content-Type": "text/markdown"}
    )
    assert response.status_code == 200, response.text
    assert client.post(url + "/finalize", headers={"X-CSRF-Token": "invalid"}).status_code == 403
    assert client.post(url + "/finalize").status_code == 202
    assert (
        client.put(
            url + "/files/manual", content=content, headers={"Content-Type": "text/markdown"}
        ).status_code
        == 409
    )
    lease = acquire(tenant, "fencing-test")
    assert lease is not None
    with transaction(tenant) as connection:
        actor = actor_for_worker(connection, tenant, tenant + "-author")
        cancel(connection, actor, import_id)
    with transaction(tenant) as connection, pytest.raises(Problem, match="lease_lost"):
        assert_publishable(connection, lease)
    with transaction(tenant) as connection:
        assert connection.execute(text("SELECT count(*) FROM evidence_snapshots")).scalar_one() == 0


def test_concurrent_password_attempts_reserve_limit_before_verification(workspace, monkeypatch):
    from evidencedesk.config import get_settings

    # Isolate the per-email quota; the smaller default CPU admission has its own test.
    monkeypatch.setenv("ED_LOGIN_PASSWORD_CONCURRENCY", "6")
    get_settings.cache_clear()
    email = workspace["tenants"][0] + "-author@fixture.invalid"

    def attempt(_):
        with TestClient(workspace["app"], base_url=ORIGIN) as client:
            return client.post(
                "/api/v1/auth/login",
                json={"email": email, "password": "incorrect"},
                headers={"Origin": ORIGIN},
            ).status_code

    with ThreadPoolExecutor(max_workers=6) as pool:
        statuses = list(pool.map(attempt, range(16)))
    assert statuses.count(401) == 10
    assert statuses.count(429) == 6


def test_stream_admission_is_shared_across_concurrent_connections_and_released(workspace):
    user = workspace["tenants"][0] + "-author"

    def attempt(_):
        try:
            return reserve_stream(user)
        except Problem as error:
            assert error.code == "stream_limit"
            return None

    with ThreadPoolExecutor(max_workers=5) as pool:
        tokens = [token for token in pool.map(attempt, range(5)) if token]
    assert len(tokens) == 2
    release_stream(tokens.pop())
    tokens.append(reserve_stream(user))
    for token in tokens:
        release_stream(token)
    with transaction() as connection:
        assert (
            connection.execute(
                text("SELECT count(*) FROM stream_leases WHERE user_id=:user"), {"user": user}
            ).scalar_one()
            == 0
        )
