import pytest
from sqlalchemy import text
from test_manual_workflow import create_incident, import_document

from evidencedesk.incidents import service

pytestmark = pytest.mark.integration


def test_warm_summary_reuses_work_but_policy_revision_and_authorization_stay_current(
    workspace, monkeypatch
):
    author = workspace["client"]()
    admin = workspace["client"](role="admin")
    tenant = workspace["tenants"][0]
    import_document(author, tenant)
    original, calls = service.load_reconciliation, []

    def counted(*args, **kwargs):
        calls.append(1)
        return original(*args, **kwargs)

    monkeypatch.setattr(service, "load_reconciliation", counted)
    incident = create_incident(author)
    for _ in range(3):
        assert author.get(f"/api/v1/incidents/{incident}").status_code == 200
    assert len(calls) == 1
    with workspace["admin"].begin() as connection:
        connection.execute(
            text("UPDATE tenant_policy SET revision=revision+1 WHERE tenant_id=:tenant"),
            {"tenant": tenant},
        )
    assert author.get(f"/api/v1/incidents/{incident}").status_code == 200
    assert len(calls) == 2
    assert (
        admin.put(
            f"/api/v1/admin/collections/collection/members/{tenant}-author", json={"granted": False}
        ).status_code
        == 200
    )
    assert author.get(f"/api/v1/incidents/{incident}").status_code == 404
    assert len(calls) == 2


def test_latest_dossier_never_exposes_derived_id_after_source_tombstone(workspace):
    author = workspace["client"]()
    tenant = workspace["tenants"][0]
    snapshot = import_document(author, tenant)
    incident = create_incident(author)
    with workspace["admin"].begin() as connection:
        source = connection.execute(
            text("SELECT id FROM evidence WHERE tenant_id=:tenant AND kind='document_span'"),
            {"tenant": tenant},
        ).scalar_one()
    response = author.post(
        f"/api/v1/incidents/{incident}/dossiers",
        json={
            "evidence_snapshot_id": snapshot,
            "summary": "Procedimento observado",
            "outcome": "evidence_found",
            "claims": [
                {
                    "kind": "observed_fact",
                    "text": "Existe um procedimento.",
                    "evidence_links": [{"evidence_id": source, "relation": "supports"}],
                }
            ],
        },
    )
    assert response.status_code == 201, response.text
    dossier = response.json()["id"]
    assert author.get(f"/api/v1/incidents/{incident}").json()["dossier_id"] == dossier
    # Deliberately leave dossier live: authorization must inspect its dependency, not only its own flag.
    with workspace["admin"].begin() as connection:
        connection.execute(
            text("UPDATE evidence SET tombstoned_at=now() WHERE tenant_id=:tenant AND id=:id"),
            {"tenant": tenant, "id": source},
        )
    assert author.get(f"/api/v1/dossiers/{dossier}").status_code == 404
    assert author.get(f"/api/v1/incidents/{incident}").json()["dossier_id"] is None
    assert author.get("/api/v1/incidents").json()["items"][0]["dossier_id"] is None
