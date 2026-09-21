from datetime import UTC, datetime, timedelta

import pytest
from pydantic import ValidationError

from evidencedesk.reconciliation import (
    EventObservation,
    IdentityMapping,
    OrderSnapshot,
    ReconciliationInput,
    SourceCoverage,
    TimeWindow,
    reconcile,
)
from evidencedesk.reconciliation.parsing import parse_snapshot_csv

BASE = datetime(2026, 1, 1, tzinfo=UTC)
HASH = "a" * 64


def event(
    evidence_id="payment-a",
    *,
    source="payments",
    kind="payment.confirmed",
    at=10,
    source_event_id="evt-1",
    observed=11,
    payload=None,
):
    return EventObservation(
        evidence_id=evidence_id,
        source_system=source,
        source_event_id=source_event_id,
        order_reference="source-order",
        event_type=kind,
        occurred_at=BASE + timedelta(seconds=at) if at is not None else None,
        observed_at=BASE + timedelta(seconds=observed) if observed is not None else None,
        ingested_at=BASE + timedelta(days=20),
        source_file_sha256=HASH,
        line_number=1,
        payload=payload or {},
    )


def snapshot(*, as_of=400, status="pending_payment"):
    return OrderSnapshot(
        evidence_id="snapshot-a",
        source_system="orders",
        snapshot_id="snapshot-1",
        order_reference="source-order",
        status=status,
        as_of=BASE + timedelta(seconds=as_of) if as_of is not None else None,
        source_file_sha256=HASH,
        line_number=2,
    )


def input_data(
    events=(),
    snapshots=(),
    *,
    coverage_status="complete",
    window_end=600,
    mappings=True,
    uncertainty=0,
):
    return ReconciliationInput(
        tenant_id="tenant-a",
        evidence_snapshot_id="snapshot-version-1",
        window=TimeWindow(start=BASE, end=BASE + timedelta(seconds=window_end)),
        watermark=BASE + timedelta(seconds=window_end),
        events=events,
        snapshots=snapshots,
        mappings=tuple(
            IdentityMapping(
                source_system=source,
                source_order_reference="source-order",
                order_reference="order-1",
            )
            for source in ("payments", "orders", "inventory")
        )
        if mappings
        else (),
        coverage=tuple(
            SourceCoverage(
                source_system=source,
                status=coverage_status,
                start=BASE,
                end=BASE + timedelta(seconds=window_end),
                clock_uncertainty_ms=uncertainty,
            )
            for source in ("payments", "orders", "inventory")
        ),
    )


def facts(result, code):
    return [item for item in result.divergences if item.rule_code == code]


def test_incident_attribution_does_not_replace_unknown_occurrence_or_use_old_events():
    result = reconcile(
        input_data(
            events=(
                event("old-observation", at=None, observed=-100, source_event_id="old"),
                event("in-window-observation", at=None, observed=40, source_event_id="unknown"),
                event("late-observation", at=20, observed=9000, source_event_id="late"),
                event("old-occurrence", at=-100, observed=30, source_event_id="prior"),
                event("unassigned", at=None, observed=None, source_event_id="undated"),
            )
        )
    )
    assert {row.evidence_id for row in result.timeline} == {
        "in-window-observation",
        "late-observation",
    }
    unknown = next(row for row in result.timeline if row.evidence_id == "in-window-observation")
    assert unknown.occurred_at is None


def test_redelivery_does_not_duplicate_logical_event_or_orders():
    result = reconcile(input_data([event(), event("payment-b", observed=70)], [snapshot()]))
    assert result.counts.observations == 2
    assert result.counts.logical_events == 1
    assert result.counts.orders == 1
    assert result.timeline[0].delivery_count == 2
    assert facts(result, "event_redelivery")[0].status == "observation"
    assert len(facts(result, "payment_snapshot_mismatch")) == 1


def test_same_identity_with_changed_domain_content_is_not_consolidated():
    result = reconcile(
        input_data([event(), event("payment-b", payload={"different": True})], [snapshot()])
    )
    assert facts(result, "event_identity_conflict")[0].status == "not_evaluable"
    assert not facts(result, "payment_snapshot_mismatch")
    assert result.timeline[0].temporal_quality == "conflicting"


@pytest.mark.parametrize(("as_of", "expected"), [(400, True), (5, False)])
def test_snapshot_comparison_uses_as_of_and_not_import_time(as_of, expected):
    result = reconcile(input_data([event()], [snapshot(as_of=as_of)]))
    assert bool(facts(result, "payment_snapshot_mismatch")) is expected


def test_unknown_clock_precision_prevents_confident_cross_source_ordering():
    result = reconcile(input_data([event()], [snapshot()], uncertainty=None))
    assert not facts(result, "payment_snapshot_mismatch")
    assert facts(result, "snapshot_temporal_comparison")[0].status == "not_evaluable"


def test_near_timestamps_inside_uncertainty_do_not_establish_order():
    result = reconcile(input_data([event(at=10)], [snapshot(as_of=11)], uncertainty=1000))
    assert facts(result, "snapshot_temporal_comparison")[0].status == "not_evaluable"


@pytest.mark.parametrize(("status", "end"), [("partial", 600), ("unknown", 600), ("complete", 100)])
def test_missing_transition_requires_complete_deadline_coverage(status, end):
    result = reconcile(input_data([event()], coverage_status=status, window_end=end))
    assert facts(result, "transition_not_observed")[0].status == "not_evaluable"


def test_missing_transition_with_coverage_is_observation_of_absence_in_window():
    result = reconcile(input_data([event()]))
    fact = facts(result, "transition_not_observed")[0]
    assert fact.status == "divergence"
    assert "neste recorte" in fact.summary
    assert fact.evidence_snapshot_id == "snapshot-version-1"


def test_late_confirmation_does_not_erase_missed_deadline():
    result = reconcile(
        input_data(
            [
                event(),
                event("domain-a", source="orders", kind="order.payment_confirmed", at=450),
            ]
        )
    )
    assert facts(result, "transition_not_observed")[0].status == "divergence"


def test_unknown_confirmation_time_cannot_prove_missing_transition():
    result = reconcile(
        input_data(
            [
                event(),
                event("domain-a", source="orders", kind="order.payment_confirmed", at=None),
            ]
        )
    )
    assert facts(result, "transition_not_observed")[0].status == "not_evaluable"


def test_expiration_sequence_does_not_claim_cause():
    result = reconcile(
        input_data(
            [
                event(
                    "expiration", source="inventory", kind="inventory.reservation_expired", at=20
                ),
                event("confirmation", source="orders", kind="order.payment_confirmed", at=40),
            ]
        )
    )
    assert (
        "não prova a causa" in facts(result, "reservation_expired_before_confirmation")[0].summary
    )


def test_no_fuzzy_order_join_without_mapping():
    result = reconcile(input_data([event()], [snapshot()], mappings=False))
    assert result.counts.orders == 0
    assert result.timeline[0].order_reference is None
    assert not facts(result, "payment_snapshot_mismatch")


def test_unknown_time_remains_null_even_with_ingestion_timestamp():
    result = reconcile(input_data([event(at=None)]))
    assert result.timeline[0].occurred_at is None
    assert result.timeline[0].temporal_quality == "unknown"


def test_stable_fact_identity_depends_on_snapshot_and_tenant():
    original = input_data([event()], [snapshot()])
    first = reconcile(original)
    second = reconcile(original)
    other = reconcile(original.model_copy(update={"tenant_id": "tenant-b"}))
    assert first == second
    assert {fact.id for fact in first.divergences}.isdisjoint(fact.id for fact in other.divergences)


def test_file_contract_rejects_tenant_and_naive_time():
    values = event().model_dump()
    with pytest.raises(ValidationError):
        EventObservation.model_validate({**values, "tenant_id": "attacker"})
    with pytest.raises(ValidationError):
        EventObservation.model_validate({**values, "occurred_at": datetime(2026, 1, 1)})


def test_snapshot_parser_preserves_missing_timestamp_and_rejects_extra_columns():
    content = "source_system,snapshot_id,order_reference,status,as_of,source_timezone\norders,s1,o1,paid,,UTC\n"
    assert parse_snapshot_csv(content)[0].as_of is None
    with pytest.raises(ValueError):
        parse_snapshot_csv(content.replace("source_timezone", "source_timezone,tenant"))


def test_ambiguous_mapping_is_not_used():
    data = input_data([event()])
    conflicting = IdentityMapping(
        source_system="payments",
        source_order_reference="source-order",
        order_reference="other-order",
    )
    result = reconcile(data.model_copy(update={"mappings": (*data.mappings, conflicting)}))
    assert result.timeline[0].order_reference is None


def test_conflicting_confirmation_does_not_turn_into_proof_of_absence():
    data = input_data(
        [
            event(),
            event("confirmation-a", source="orders", kind="order.payment_confirmed", at=20),
            event(
                "confirmation-b",
                source="orders",
                kind="order.payment_confirmed",
                at=20,
                payload={"conflicting": True},
            ),
        ]
    )
    result = reconcile(data)
    assert facts(result, "transition_not_observed")[0].status == "not_evaluable"


def test_missing_domain_mapping_prevents_absence_claim():
    data = input_data([event()])
    data = data.model_copy(
        update={"mappings": tuple(item for item in data.mappings if item.source_system != "orders")}
    )
    result = reconcile(data)
    assert facts(result, "transition_not_observed")[0].status == "not_evaluable"
