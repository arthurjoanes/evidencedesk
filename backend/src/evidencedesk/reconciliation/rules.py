"""Reconciliation rules never infer causality, payment effects, or missing identities."""

from __future__ import annotations

import hashlib
import json
from collections import defaultdict
from datetime import UTC, datetime, timedelta
from typing import Literal

from .contracts import (
    Divergence,
    EventObservation,
    ReconciliationCounts,
    ReconciliationInput,
    ReconciliationResult,
    TimelineRow,
)


def _identity(event: EventObservation) -> tuple[str, str]:
    return event.source_system, event.source_event_id


def _domain_fingerprint(event: EventObservation) -> str:
    # Delivery/observation timestamps describe transport, not domain event identity.
    return json.dumps(
        {
            "event_type": event.event_type,
            "order_reference": event.order_reference,
            "occurred_at": event.occurred_at.astimezone(UTC).isoformat()
            if event.occurred_at
            else None,
            "payload": event.payload,
        },
        sort_keys=True,
        separators=(",", ":"),
        ensure_ascii=False,
    )


def reconcile(data: ReconciliationInput) -> ReconciliationResult:
    """Evaluate one tenant's already authorized evidence at a fixed snapshot.

    Unknown event times remain visible but cannot establish ordering. All evidence
    must have been published into this snapshot by the caller.
    """
    mapping_targets: dict[tuple[str, str], set[str]] = defaultdict(set)
    for mapping in data.mappings:
        mapping_targets[(mapping.source_system, mapping.source_order_reference)].add(
            mapping.order_reference
        )

    def resolve(source: str, reference: str | None) -> str | None:
        targets = mapping_targets.get((source, reference or ""), set())
        return next(iter(targets)) if len(targets) == 1 else None

    facts: list[Divergence] = []

    def emit(
        code: str,
        status: Literal["divergence", "observation", "not_evaluable"],
        summary: str,
        order: str | None,
        ids: tuple[str, ...],
    ) -> None:
        identity = json.dumps(
            [
                data.tenant_id,
                data.evidence_snapshot_id,
                data.policy.revision,
                code,
                order,
                sorted(ids),
            ],
            separators=(",", ":"),
        )
        facts.append(
            Divergence(
                id="fact_" + hashlib.sha256(identity.encode()).hexdigest()[:24],
                order_reference=order,
                rule_code=code,
                rule_revision=data.policy.revision,
                status=status,
                summary=summary,
                evidence_ids=ids,
                evidence_snapshot_id=data.evidence_snapshot_id,
            )
        )

    groups: dict[tuple[str, str], list[EventObservation]] = defaultdict(list)
    for event in data.events:
        # Observation time selects an incident only when occurrence is unknown; it never replaces it.
        attribution_time = event.occurred_at or event.observed_at
        if (
            attribution_time is not None
            and data.window.start <= attribution_time <= data.window.end
        ):
            groups[_identity(event)].append(event)

    canonical: list[EventObservation] = []
    timeline: list[TimelineRow] = []
    conflicted_sources: set[str] = set()
    for key, observations in sorted(groups.items()):
        ordered = sorted(observations, key=lambda event: (event.ingested_at, event.evidence_id))
        first = ordered[0]
        ids = tuple(event.evidence_id for event in ordered)
        order = resolve(first.source_system, first.order_reference)
        conflict = len({_domain_fingerprint(event) for event in ordered}) > 1
        if conflict:
            conflicted_sources.add(first.source_system)
            emit(
                "event_identity_conflict",
                "not_evaluable",
                "A mesma identidade de evento possui conteúdo divergente; não foi consolidada.",
                order,
                ids,
            )
        else:
            canonical.append(first)
            if len(ordered) > 1:
                emit(
                    "event_redelivery",
                    "observation",
                    f"O evento possui {len(ordered)} observações; isso não comprova efeito de negócio duplicado.",
                    order,
                    ids,
                )
        if order is None:
            emit(
                "insufficient_correlation",
                "not_evaluable",
                "Não há mapeamento único declarado para o identificador de origem.",
                None,
                ids,
            )
        timeline.append(
            TimelineRow(
                id="event_"
                + hashlib.sha256(f"{data.tenant_id}|{key[0]}|{key[1]}".encode()).hexdigest()[:24],
                evidence_id=first.evidence_id,
                order_reference=order,
                source_system=first.source_system,
                event_type=first.event_type,
                occurred_at=None if conflict else first.occurred_at,
                observed_at=first.observed_at,
                ingested_at=first.ingested_at,
                temporal_quality="conflicting"
                if conflict
                else ("known" if first.occurred_at else "unknown"),
                delivery_count=len(ordered),
                observation_evidence_ids=ids,
            )
        )

    def uncertainty(source: str) -> int | None:
        values = [
            coverage.clock_uncertainty_ms
            for coverage in data.coverage
            if coverage.source_system == source
        ]
        if not values or any(value is None for value in values):
            return None
        return max(value for value in values if value is not None)

    def definitely_before(
        left: datetime | None, left_source: str, right: datetime | None, right_source: str
    ) -> bool | None:
        if left is None or right is None:
            return None
        left_uncertainty, right_uncertainty = uncertainty(left_source), uncertainty(right_source)
        if left_uncertainty is None or right_uncertainty is None:
            return None
        margin = timedelta(milliseconds=left_uncertainty + right_uncertainty)
        if left + margin < right:
            return True
        if right + margin < left:
            return False
        return None

    by_order: dict[str, list[EventObservation]] = defaultdict(list)
    for event in canonical:
        order = resolve(event.source_system, event.order_reference)
        if order is not None:
            by_order[order].append(event)

    snapshot_orders = set()
    for snapshot in data.snapshots:
        order = resolve(snapshot.source_system, snapshot.order_reference)
        if order is None:
            emit(
                "insufficient_correlation",
                "not_evaluable",
                "Snapshot sem mapeamento único declarado.",
                None,
                (snapshot.evidence_id,),
            )
            continue
        snapshot_orders.add(order)
        payments = [
            event
            for event in by_order[order]
            if event.source_system == data.policy.payment_system
            and event.event_type == data.policy.payment_event
        ]
        if snapshot.source_system != data.policy.order_system:
            continue
        for payment in payments:
            comparison = definitely_before(
                payment.occurred_at, payment.source_system, snapshot.as_of, snapshot.source_system
            )
            if comparison is None:
                emit(
                    "snapshot_temporal_comparison",
                    "not_evaluable",
                    "Não é possível ordenar confirmação e snapshot com a precisão temporal declarada.",
                    order,
                    (payment.evidence_id, snapshot.evidence_id),
                )
            elif comparison and snapshot.status in data.policy.incompatible_paid_statuses:
                emit(
                    "payment_snapshot_mismatch",
                    "divergence",
                    "A fonte de pagamento registra confirmação anterior a um snapshot ainda incompatível.",
                    order,
                    (payment.evidence_id, snapshot.evidence_id),
                )

    for order, events in sorted(by_order.items()):
        expirations = [
            event
            for event in events
            if event.source_system == data.policy.inventory_system
            and event.event_type == data.policy.reservation_expired_event
        ]
        confirmations = [
            event
            for event in events
            if event.source_system == data.policy.order_system
            and event.event_type == data.policy.domain_confirmation_event
        ]
        for expiration in expirations:
            for confirmation in confirmations:
                comparison = definitely_before(
                    expiration.occurred_at,
                    expiration.source_system,
                    confirmation.occurred_at,
                    confirmation.source_system,
                )
                if comparison:
                    emit(
                        "reservation_expired_before_confirmation",
                        "divergence",
                        "Expiração observada antes da confirmação no domínio; a sequência não prova a causa.",
                        order,
                        (expiration.evidence_id, confirmation.evidence_id),
                    )
                elif comparison is None:
                    emit(
                        "reservation_temporal_comparison",
                        "not_evaluable",
                        "Relógios ou horários insuficientes para comparar expiração e confirmação.",
                        order,
                        (expiration.evidence_id, confirmation.evidence_id),
                    )

        payments = [
            event
            for event in events
            if event.source_system == data.policy.payment_system
            and event.event_type == data.policy.payment_event
        ]
        for payment in payments:
            # Any domain confirmation cannot prove an on-time transition when time is unknown.
            if payment.occurred_at is None:
                emit(
                    "transition_not_observed",
                    "not_evaluable",
                    "Confirmação sem horário de ocorrência; o prazo não é calculável.",
                    order,
                    (payment.evidence_id,),
                )
                continue
            deadline = payment.occurred_at + timedelta(
                seconds=data.policy.expected_transition_seconds
            )
            order_mapping_known = any(
                source == data.policy.order_system and targets == {order}
                for (source, _), targets in mapping_targets.items()
            )
            complete = deadline <= min(data.window.end, data.watermark) and any(
                coverage.source_system == data.policy.order_system
                and coverage.covers(
                    payment.occurred_at, deadline, data.policy.domain_confirmation_event
                )
                for coverage in data.coverage
            )
            payment_uncertainty = uncertainty(payment.source_system)
            domain_uncertainty = uncertainty(data.policy.order_system)
            if (
                not complete
                or not order_mapping_known
                or data.policy.order_system in conflicted_sources
                or payment_uncertainty is None
                or domain_uncertainty is None
            ):
                emit(
                    "transition_not_observed",
                    "not_evaluable",
                    "O recorte, a cobertura ou a precisão temporal não permitem avaliar o prazo.",
                    order,
                    (payment.evidence_id,),
                )
                continue
            margin = timedelta(milliseconds=payment_uncertainty + domain_uncertainty)
            on_time = [
                event
                for event in confirmations
                if event.occurred_at is not None
                and payment.occurred_at - margin <= event.occurred_at <= deadline + margin
            ]
            if on_time:
                continue
            ambiguous = [event for event in confirmations if event.occurred_at is None]
            if ambiguous:
                emit(
                    "transition_not_observed",
                    "not_evaluable",
                    "Há confirmação sem horário; sua posição em relação ao prazo é desconhecida.",
                    order,
                    (payment.evidence_id, *(event.evidence_id for event in ambiguous)),
                )
            else:
                emit(
                    "transition_not_observed",
                    "divergence",
                    "A transição esperada não foi observada até o prazo neste recorte e cobertura.",
                    order,
                    (payment.evidence_id,),
                )

    # Stable tiebreaking is pagination order, not a claim of causal ordering.
    infinity = datetime.max.replace(tzinfo=UTC)
    timeline.sort(key=lambda row: (row.occurred_at is None, row.occurred_at or infinity, row.id))
    ties: dict[datetime, int] = defaultdict(int)
    for row in timeline:
        if row.occurred_at:
            ties[row.occurred_at] += 1
    timeline = [
        row.model_copy(update={"temporal_quality": "uncertain"})
        if row.occurred_at and ties[row.occurred_at] > 1
        else row
        for row in timeline
    ]
    facts.sort(key=lambda fact: (fact.order_reference or "", fact.rule_code, fact.id))
    return ReconciliationResult(
        evidence_snapshot_id=data.evidence_snapshot_id,
        rule_revision=data.policy.revision,
        window=data.window,
        watermark=data.watermark,
        coverage=data.coverage,
        timeline=tuple(timeline),
        divergences=tuple(facts),
        counts=ReconciliationCounts(
            observations=sum(len(group) for group in groups.values()),
            logical_events=len(groups),
            orders=len(set(by_order) | snapshot_orders),
            divergences=sum(fact.status == "divergence" for fact in facts),
            not_evaluable=sum(fact.status == "not_evaluable" for fact in facts),
        ),
    )
