from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

from fastapi import APIRouter, Query
from pydantic import Field, field_validator
from sqlalchemy import text

from evidencedesk.api import CurrentActor, Input, PageLimit
from evidencedesk.database import lock_policy, transaction
from evidencedesk.evidence.service import authorize_snapshot
from evidencedesk.identity.service import authorize_incident
from evidencedesk.incidents.service import create_incident, incident_payload, load_reconciliation
from evidencedesk.pagination import decode_cursor, decode_recent_cursor, page, recent_page
from evidencedesk.reconciliation.contracts import TimeWindow

router = APIRouter(tags=["Incidentes"])


class IncidentWindow(TimeWindow):
    time_zone: str = "America/Sao_Paulo"

    @field_validator("time_zone")
    @classmethod
    def known_timezone(cls, value: str) -> str:
        try:
            ZoneInfo(value)
        except ZoneInfoNotFoundError:
            raise ValueError("Fuso horário desconhecido") from None
        return value


class IncidentInput(Input):
    title: str = Field(min_length=3, max_length=200)
    description: str = Field(default="", max_length=4000)
    collection_id: str = Field(min_length=1, max_length=200)
    window: IncidentWindow


@router.get("/collections")
def list_collections(actor: CurrentActor) -> dict:
    with transaction(actor.tenant_id) as connection:
        rows = (
            connection.execute(
                text("""
            SELECT c.id,c.name,c.description,c.active_snapshot_id FROM collections c
            JOIN collection_grants g ON g.tenant_id=c.tenant_id AND g.collection_id=c.id
            WHERE c.tenant_id=:tenant AND g.user_id=:user AND c.tombstoned_at IS NULL ORDER BY c.name,c.id LIMIT 100
        """),
                {"tenant": actor.tenant_id, "user": actor.id},
            )
            .mappings()
            .all()
        )
        return {"items": [dict(row) for row in rows], "next_cursor": None, "total": len(rows)}


@router.post("/incidents", status_code=201)
def new_incident(body: IncidentInput, actor: CurrentActor) -> dict:
    with transaction(actor.tenant_id) as connection:
        lock_policy(connection, actor.tenant_id, mutation=True)
        incident_id = create_incident(
            connection,
            actor,
            body.title,
            body.collection_id,
            body.window.model_dump(mode="json", by_alias=True),
            body.description,
        )
        return incident_payload(connection, actor, incident_id)


@router.get("/incidents")
def list_incidents(
    actor: CurrentActor,
    q: str = Query(default="", max_length=200),
    status: str = Query(default="", max_length=40),
    cursor: str | None = None,
    limit: PageLimit = 30,
) -> dict:
    context = {
        "tenant": actor.tenant_id,
        "user": actor.id,
        "q": q,
        "status": status,
        "operation": "incidents",
        "ordering": "created_at_desc_id_desc_v1",
    }
    after_date, after_id = decode_recent_cursor(cursor, context)
    with transaction(actor.tenant_id) as connection:
        rows = (
            connection.execute(
                text("""
            SELECT i.id,i.created_at FROM incidents i JOIN incident_members m ON m.tenant_id=i.tenant_id AND m.incident_id=i.id
            JOIN collection_grants g ON g.tenant_id=i.tenant_id AND g.collection_id=i.collection_id AND g.user_id=m.user_id
            JOIN collections c ON c.tenant_id=i.tenant_id AND c.id=i.collection_id
            WHERE i.tenant_id=:tenant AND m.user_id=:user AND c.tombstoned_at IS NULL
              AND (:q='' OR i.title ILIKE :pattern) AND (:status='' OR i.status=:status)
              AND (CAST(:after_date AS timestamptz) IS NULL OR (i.created_at,i.id)<(:after_date,:after_id))
            ORDER BY i.created_at DESC,i.id DESC LIMIT :limit
        """),
                {
                    "tenant": actor.tenant_id,
                    "user": actor.id,
                    "q": q,
                    "pattern": f"%{q[:200]}%",
                    "status": status,
                    "after_date": after_date,
                    "after_id": after_id,
                    "limit": limit + 1,
                },
            )
            .mappings()
            .all()
        )
        result = recent_page([dict(row) for row in rows], limit, context)
        result["items"] = [
            incident_payload(connection, actor, item["id"]) for item in result["items"]
        ]
        return result


@router.get("/incidents/{incident_id}")
def get_incident(incident_id: str, actor: CurrentActor) -> dict:
    with transaction(actor.tenant_id) as connection:
        return incident_payload(connection, actor, incident_id)


def reconciliation_page(
    incident_id: str,
    actor,
    evidence_snapshot_id: str | None,
    order_reference: str,
    cursor: str | None,
    limit: int,
    *,
    timeline: bool,
) -> dict:
    with transaction(actor.tenant_id) as connection:
        result = load_reconciliation(connection, actor, incident_id, evidence_snapshot_id)
    context = {
        "tenant": actor.tenant_id,
        "user": actor.id,
        "incident": incident_id,
        "snapshot": result.evidence_snapshot_id,
        "order": order_reference,
        "operation": "timeline" if timeline else "reconciliation",
    }
    after = decode_cursor(cursor, context)
    rows = [
        item.model_dump(mode="json")
        for item in (result.timeline if timeline else result.divergences)
        if not order_reference or item.order_reference == order_reference
    ]
    total = len(rows)
    if after:
        position = next((index for index, item in enumerate(rows) if item["id"] == after), None)
        if position is None:
            from evidencedesk.errors import Problem

            raise Problem(
                409, "cursor_context_changed", "Os dados deste recorte mudaram. Recarregue a lista."
            )
        rows = rows[position + 1 :]
    payload = page(rows[: limit + 1], limit, context, total)
    payload["coverage"] = [item.model_dump(mode="json", by_alias=True) for item in result.coverage]
    if timeline:
        payload["ordering"] = result.ordering
    return payload


@router.get("/incidents/{incident_id}/timeline")
def timeline(
    incident_id: str,
    actor: CurrentActor,
    evidence_snapshot_id: str | None = None,
    order_reference: str = "",
    cursor: str | None = None,
    limit: PageLimit = 30,
) -> dict:
    return reconciliation_page(
        incident_id, actor, evidence_snapshot_id, order_reference, cursor, limit, timeline=True
    )


@router.get("/incidents/{incident_id}/reconciliation")
def divergences(
    incident_id: str,
    actor: CurrentActor,
    evidence_snapshot_id: str | None = None,
    order_reference: str = "",
    cursor: str | None = None,
    limit: PageLimit = 30,
) -> dict:
    return reconciliation_page(
        incident_id, actor, evidence_snapshot_id, order_reference, cursor, limit, timeline=False
    )


@router.get("/incidents/{incident_id}/evidence")
def incident_evidence(
    incident_id: str,
    actor: CurrentActor,
    evidence_snapshot_id: str | None = None,
    q: str = Query(default="", max_length=300),
    cursor: str | None = None,
    limit: PageLimit = 30,
) -> dict:
    with transaction(actor.tenant_id) as connection:
        incident = authorize_incident(connection, actor, incident_id)
        snapshot = evidence_snapshot_id or incident["snapshot_id"]
        authorize_snapshot(connection, actor, snapshot, incident["collection_id"])
        context = {
            "tenant": actor.tenant_id,
            "user": actor.id,
            "incident": incident_id,
            "snapshot": snapshot,
            "q": q,
            "operation": "evidence",
        }
        after = decode_cursor(cursor, context)
        rows = (
            connection.execute(
                text("""
            SELECT e.id,e.kind,e.title,e.version,e.source_system,e.temporal_role,left(e.canonical_text,350) AS excerpt
            FROM evidence e JOIN snapshot_members m ON m.tenant_id=e.tenant_id AND m.evidence_id=e.id
            WHERE e.tenant_id=:tenant AND m.snapshot_id=:snapshot AND e.tombstoned_at IS NULL AND e.id>:after
              AND (:q='' OR e.search_vector @@ websearch_to_tsquery('portuguese',:q) OR e.title ILIKE :pattern)
              AND (e.kind='document_span' OR
                CAST(coalesce(e.record->>'occurred_at',e.record->>'observed_at',e.record->>'as_of') AS timestamptz)
                    BETWEEN :start AND :end)
            ORDER BY e.id LIMIT :limit
        """),
                {
                    "tenant": actor.tenant_id,
                    "snapshot": snapshot,
                    "after": after,
                    "q": q[:300],
                    "pattern": f"%{q[:300]}%",
                    "start": incident["window_from"],
                    "end": incident["window_to"],
                    "limit": limit + 1,
                },
            )
            .mappings()
            .all()
        )
        return page([dict(row) for row in rows], limit, context)
