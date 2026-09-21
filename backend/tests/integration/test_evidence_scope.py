"""Incident authority applies to derived evidence and direct tool reads too."""

import hashlib
import json

import pytest
from sqlalchemy import text
from test_investigation_workflow import prepare_run
from test_manual_workflow import create_incident

from evidencedesk.errors import Problem
from evidencedesk.investigations.processing import investigation_context
from evidencedesk.investigations.tools import ExecutionContext, ReadArguments, ReadTools
from evidencedesk.jobs.service import acquire

pytestmark = pytest.mark.integration


def test_derived_evidence_requires_origin_incident_membership_and_matching_claim_scope(
    workspace, monkeypatch
):
    client, tenant, run = prepare_run(workspace, monkeypatch)
    lease = acquire(tenant, "derived-scope-test")
    assert lease is not None
    # Executes deterministic reconciliation/retrieval only; no provider dispatch.
    details, sources = investigation_context(lease)
    aggregate = next(source for source in sources if source.kind == "reconciliation_result")
    source = next(source for source in sources if source.kind == "document_span")
    params = {"evidence_snapshot_id": run["evidence_snapshot_id"]}
    reviewer = workspace["client"](role="reviewer")
    derived_url = f"/api/v1/evidence/{aggregate.evidence_id}"
    assert reviewer.get(derived_url, params=params).status_code == 200
    body = {
        **params,
        "summary": "Conciliação da investigação original",
        "outcome": "evidence_found",
        "claims": [
            {
                "kind": "observed_fact",
                "text": "A conciliação registra o recorte deste incidente.",
                "evidence_links": [{"evidence_id": aggregate.evidence_id, "relation": "supports"}],
            }
        ],
    }
    original = client.post(f"/api/v1/incidents/{details['incident_id']}/dossiers", json=body)
    assert original.status_code == 201, original.text
    other_incident = create_incident(client)
    wrong_scope = client.post(f"/api/v1/incidents/{other_incident}/dossiers", json=body)
    assert wrong_scope.status_code == 422, wrong_scope.text
    assert wrong_scope.json()["error"]["code"] == "evidence_outside_incident"

    with workspace["admin"].begin() as connection:
        connection.execute(
            text(
                "DELETE FROM incident_members WHERE tenant_id=:tenant AND incident_id=:incident AND user_id=:user"
            ),
            {
                "tenant": tenant,
                "incident": details["incident_id"],
                "user": tenant + "-reviewer",
            },
        )
    # The collection grant still permits its original documents, but not aggregates
    # or dossiers from an incident the reviewer can no longer access.
    assert reviewer.get(f"/api/v1/evidence/{source.evidence_id}", params=params).status_code == 200
    assert reviewer.get(derived_url, params=params).status_code == 404
    assert reviewer.get(f"/api/v1/runs/{run['id']}").status_code == 404
    assert reviewer.get(f"/api/v1/dossiers/{original.json()['id']}").status_code == 404


@pytest.mark.parametrize(
    ("occurred", "observed", "allowed"),
    [
        (None, "2026-08-01T11:00:00Z", True),
        ("2026-08-01T11:00:00Z", "2026-08-02T11:00:00Z", True),
        ("2026-08-02T11:00:00Z", "2026-08-01T11:00:00Z", False),
        (None, "2026-08-02T11:00:00Z", False),
        (None, None, False),
    ],
)
def test_direct_tool_read_enforces_operational_window(
    workspace, monkeypatch, occurred, observed, allowed
):
    _, tenant, run = prepare_run(workspace, monkeypatch)
    lease = acquire(tenant, "tool-window-test")
    assert lease is not None
    context = ExecutionContext.from_lease(lease)
    content = "A source that must remain inside the authorized incident window."
    with workspace["admin"].begin() as connection:
        connection.execute(
            text("""
                INSERT INTO evidence(tenant_id,id,collection_id,kind,title,version,sha256,
                                     source_system,temporal_role,canonical_text,record)
                VALUES(:tenant,'scoped-event','collection','source_event','Scoped event','1',:hash,
                       'payments','historical_artifact',:content,CAST(:record AS jsonb))
            """),
            {
                "tenant": tenant,
                "hash": hashlib.sha256(content.encode()).hexdigest(),
                "content": content,
                "record": json.dumps({"occurred_at": occurred, "observed_at": observed}),
            },
        )
        connection.execute(
            text("""
                INSERT INTO snapshot_members(tenant_id,snapshot_id,evidence_id)
                VALUES(:tenant,:snapshot,'scoped-event')
            """),
            {"tenant": tenant, "snapshot": run["evidence_snapshot_id"]},
        )
    if allowed:
        result = ReadTools(context).read_span(ReadArguments(evidence_id="scoped-event"))
        assert result["text"] == content
    else:
        with pytest.raises(Problem) as denied:
            ReadTools(context).read_span(ReadArguments(evidence_id="scoped-event"))
        assert denied.value.code == "evidence_outside_window"
