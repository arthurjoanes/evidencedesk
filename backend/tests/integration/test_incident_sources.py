import hashlib
import json

import pytest
from sqlalchemy import text
from test_manual_workflow import create_incident, import_document

pytestmark = pytest.mark.integration


def test_operational_source_list_matches_timeline_time_fallback(workspace):
    client = workspace["client"]()
    tenant = workspace["tenants"][0]
    snapshot = import_document(client, tenant)
    incident = create_incident(client)
    within = "2026-08-01T11:00:00Z"
    outside = "2026-08-02T11:00:00Z"
    examples = [
        ("observed-inside", None, within),
        ("observed-outside", None, outside),
        ("occurred-inside-observed-late", within, outside),
        ("occurred-outside-observed-inside", outside, within),
        ("unassigned-time", None, None),
    ]
    with workspace["admin"].begin() as connection:
        for evidence_id, occurred, observed in examples:
            digest = hashlib.sha256(evidence_id.encode()).hexdigest()
            record = {
                "evidence_id": evidence_id,
                "source_system": "payments",
                "source_event_id": evidence_id,
                "event_type": "payment.confirmed",
                "order_reference": evidence_id,
                "occurred_at": occurred,
                "observed_at": observed,
                "ingested_at": outside,
                "source_file_sha256": digest,
                "line_number": 1,
            }
            connection.execute(
                text("""
                INSERT INTO evidence(tenant_id,id,collection_id,kind,title,version,sha256,source_system,
                                     temporal_role,canonical_text,record)
                VALUES(:tenant,:id,'collection','source_event',:id,'1',:hash,'payments',
                       'historical_artifact',:id,CAST(:record AS jsonb))
                """),
                {"tenant": tenant, "id": evidence_id, "hash": digest, "record": json.dumps(record)},
            )
            connection.execute(
                text(
                    "INSERT INTO snapshot_members(tenant_id,snapshot_id,evidence_id) VALUES(:tenant,:snapshot,:id)"
                ),
                {"tenant": tenant, "snapshot": snapshot, "id": evidence_id},
            )
    expected = {"observed-inside", "occurred-inside-observed-late"}
    sources = client.get(f"/api/v1/incidents/{incident}/evidence")
    assert sources.status_code == 200, sources.text
    operational = {item["id"] for item in sources.json()["items"] if item["kind"] == "source_event"}
    assert operational == expected
    assert any(item["kind"] == "document_span" for item in sources.json()["items"])
    timeline = client.get(f"/api/v1/incidents/{incident}/timeline")
    assert timeline.status_code == 200, timeline.text
    assert {item["evidence_id"] for item in timeline.json()["items"]} == expected
