"""A new observed event crosses existing contracts without inventing a business rule."""

from test_reconciliation import event, input_data

from evidencedesk.ingestion.processing import evidence_records
from evidencedesk.reconciliation import IdentityMapping, reconcile


def test_new_shipping_event_uses_existing_evidence_and_timeline_contracts():
    observation = event(source="shipping", kind="shipment.delivery_attempted")
    data = input_data(events=(observation,))
    data = data.model_copy(
        update={
            "mappings": (
                *data.mappings,
                IdentityMapping(
                    source_system="shipping",
                    source_order_reference="source-order",
                    order_reference="order-1",
                ),
            )
        }
    )
    result = reconcile(data)
    assert result.counts.observations == 1
    assert result.counts.logical_events == 1
    assert result.counts.orders == 1
    assert result.counts.divergences == 0
    assert result.timeline[0].event_type == "shipment.delivery_attempted"
    assert result.timeline[0].order_reference == "order-1"
    records = evidence_records(
        "tenant-a",
        "collection-a",
        {
            "sha256": "a" * 64,
            "object_key": "tenants/tenant-a/imports/shipping/events",
            "media_type": "application/x-ndjson",
            "byte_size": 500,
            "kind": "events",
        },
        {
            "rows": [
                {
                    "line_number": 1,
                    "value": observation.model_dump(
                        mode="json",
                        exclude={"evidence_id", "source_file_sha256", "line_number", "ingested_at"},
                    ),
                }
            ]
        },
    )
    assert len(records) == 1 and records[0]["kind"] == "source_event"
    assert records[0]["title"] == "shipment.delivery_attempted · source-order"
