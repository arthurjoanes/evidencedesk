"""Pure domain contracts; the caller owns authorization and persistence."""

from __future__ import annotations

from datetime import datetime
from typing import Annotated, Literal
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

from pydantic import (
    AwareDatetime,
    BaseModel,
    ConfigDict,
    Field,
    JsonValue,
    field_validator,
    model_validator,
)

Identifier = Annotated[str, Field(min_length=1, max_length=200)]
CoverageStatus = Literal["complete", "partial", "unknown"]


class Record(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True, populate_by_name=True)


class TimeWindow(Record):
    start: AwareDatetime = Field(alias="from")
    end: AwareDatetime = Field(alias="to")

    @model_validator(mode="after")
    def chronological(self) -> TimeWindow:
        if self.end <= self.start:
            raise ValueError("O fim do recorte deve ser posterior ao início.")
        return self


class SourceCoverage(TimeWindow):
    source_system: Identifier
    status: CoverageStatus
    gaps: tuple[str, ...] = ()
    event_types: tuple[str, ...] = ()
    clock_uncertainty_ms: int | None = Field(default=None, ge=0, le=86_400_000)

    def covers(self, start: datetime, end: datetime, event_type: str) -> bool:
        return (
            self.status == "complete"
            and not self.gaps
            and self.start <= start
            and self.end >= end
            and (not self.event_types or event_type in self.event_types)
        )


class EventInput(Record):
    source_system: Identifier
    source_event_id: Identifier
    delivery_id: Identifier | None = None
    order_reference: Identifier | None = None
    event_type: Identifier
    occurred_at: AwareDatetime | None
    observed_at: AwareDatetime | None = None
    source_timezone: str = Field(default="UTC", max_length=80)
    schema_version: Literal["1"] = "1"
    payload: dict[str, JsonValue] = Field(default_factory=dict)
    time_unknown_reason: str | None = Field(default=None, max_length=300)

    @field_validator("source_timezone")
    @classmethod
    def timezone_exists(cls, value: str) -> str:
        try:
            ZoneInfo(value)
        except ZoneInfoNotFoundError as exc:
            raise ValueError("Fuso horário IANA desconhecido.") from exc
        return value

    @field_validator("payload")
    @classmethod
    def bounded_payload(cls, value: dict[str, JsonValue]) -> dict[str, JsonValue]:
        import json

        if len(json.dumps(value, ensure_ascii=False).encode("utf-8")) > 16_384:
            raise ValueError("Payload do evento excede 16 KiB.")
        return value


class EventObservation(EventInput):
    evidence_id: Identifier
    ingested_at: AwareDatetime
    source_file_sha256: str = Field(pattern=r"^[a-f0-9]{64}$")
    line_number: int = Field(ge=1)


class SnapshotInput(Record):
    source_system: Identifier
    snapshot_id: Identifier
    order_reference: Identifier
    status: Identifier
    as_of: AwareDatetime | None
    source_timezone: str = "UTC"


class OrderSnapshot(SnapshotInput):
    evidence_id: Identifier
    source_file_sha256: str = Field(pattern=r"^[a-f0-9]{64}$")
    line_number: int = Field(ge=1)


class IdentityMapping(Record):
    source_system: Identifier
    source_order_reference: Identifier
    order_reference: Identifier


class ReconciliationPolicy(Record):
    revision: str = "commerce-demo-v1"
    payment_system: str = "payments"
    order_system: str = "orders"
    inventory_system: str = "inventory"
    payment_event: str = "payment.confirmed"
    domain_confirmation_event: str = "order.payment_confirmed"
    reservation_expired_event: str = "inventory.reservation_expired"
    incompatible_paid_statuses: tuple[str, ...] = ("pending_payment", "payment_failed")
    expected_transition_seconds: int = Field(default=300, ge=1, le=86_400)


class ReconciliationInput(Record):
    tenant_id: Identifier
    evidence_snapshot_id: Identifier
    window: TimeWindow
    watermark: AwareDatetime
    events: tuple[EventObservation, ...]
    snapshots: tuple[OrderSnapshot, ...]
    mappings: tuple[IdentityMapping, ...]
    coverage: tuple[SourceCoverage, ...]
    policy: ReconciliationPolicy = Field(default_factory=ReconciliationPolicy)

    @model_validator(mode="after")
    def distinct_evidence(self) -> ReconciliationInput:
        ids = [event.evidence_id for event in self.events]
        ids.extend(snapshot.evidence_id for snapshot in self.snapshots)
        if len(ids) != len(set(ids)):
            raise ValueError("Cada observação e snapshot exige evidence_id distinto.")
        return self


class TimelineRow(Record):
    id: str
    evidence_id: str
    order_reference: str | None
    source_system: str
    event_type: str
    occurred_at: AwareDatetime | None
    observed_at: AwareDatetime | None
    ingested_at: AwareDatetime
    temporal_quality: Literal["known", "unknown", "uncertain", "conflicting"]
    delivery_count: int = Field(ge=1)
    observation_evidence_ids: tuple[str, ...]


class Divergence(Record):
    id: str
    order_reference: str | None
    rule_code: str
    rule_revision: str
    status: Literal["divergence", "observation", "not_evaluable"]
    summary: str
    evidence_ids: tuple[str, ...]
    evidence_snapshot_id: str


class ReconciliationCounts(Record):
    observations: int
    logical_events: int
    orders: int
    divergences: int
    not_evaluable: int


class ReconciliationResult(Record):
    evidence_snapshot_id: str
    rule_revision: str
    window: TimeWindow
    watermark: AwareDatetime
    coverage: tuple[SourceCoverage, ...]
    ordering: Literal["occurred_at_nulls_last"] = "occurred_at_nulls_last"
    timeline: tuple[TimelineRow, ...]
    divergences: tuple[Divergence, ...]
    counts: ReconciliationCounts
