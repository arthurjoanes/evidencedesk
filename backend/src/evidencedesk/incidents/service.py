from uuid import uuid4

from sqlalchemy import Connection, text

from evidencedesk.errors import Problem
from evidencedesk.evidence.service import authorize_snapshot
from evidencedesk.identity.service import Actor, authorize_collection, authorize_incident
from evidencedesk.incidents.summaries import summaries
from evidencedesk.reconciliation import (
    EventObservation,
    IdentityMapping,
    OrderSnapshot,
    ReconciliationInput,
    ReconciliationResult,
    SourceCoverage,
    TimeWindow,
    reconcile,
)


def load_reconciliation(
    connection: Connection, actor: Actor, incident_id: str, snapshot_id: str | None = None
) -> ReconciliationResult:
    incident = authorize_incident(connection, actor, incident_id)
    snapshot_id = snapshot_id or incident["snapshot_id"]
    snapshot = authorize_snapshot(connection, actor, snapshot_id, incident["collection_id"])
    rows = (
        connection.execute(
            text("""
        SELECT e.kind,e.record FROM evidence e
        JOIN snapshot_members m ON m.tenant_id=e.tenant_id AND m.evidence_id=e.id
        WHERE e.tenant_id=:tenant AND m.snapshot_id=:snapshot AND e.tombstoned_at IS NULL
          AND e.kind IN ('source_event','order_snapshot')
          AND CAST(coalesce(e.record->>'occurred_at',e.record->>'observed_at',e.record->>'as_of') AS timestamptz)
              BETWEEN :start AND :end
    """),
            {
                "tenant": actor.tenant_id,
                "snapshot": snapshot_id,
                "start": incident["window_from"],
                "end": incident["window_to"],
            },
        )
        .mappings()
        .all()
    )
    mappings = (
        connection.execute(
            text(
                "SELECT source_system,source_order_reference,order_reference FROM snapshot_mappings WHERE tenant_id=:tenant AND snapshot_id=:snapshot"
            ),
            {"tenant": actor.tenant_id, "snapshot": snapshot_id},
        )
        .mappings()
        .all()
    )
    return reconcile(
        ReconciliationInput(
            tenant_id=actor.tenant_id,
            evidence_snapshot_id=snapshot_id,
            window=TimeWindow.model_validate(
                {"from": incident["window_from"], "to": incident["window_to"]}
            ),
            watermark=incident["window_to"],
            events=tuple(
                EventObservation.model_validate(row["record"])
                for row in rows
                if row["kind"] == "source_event"
            ),
            snapshots=tuple(
                OrderSnapshot.model_validate(row["record"])
                for row in rows
                if row["kind"] == "order_snapshot"
            ),
            mappings=tuple(IdentityMapping.model_validate(dict(row)) for row in mappings),
            coverage=tuple(
                coverage
                for item in snapshot["coverage"]
                if (coverage := SourceCoverage.model_validate(item)).start < incident["window_to"]
                and coverage.end > incident["window_from"]
            ),
        )
    )


def create_incident(
    connection: Connection,
    actor: Actor,
    title: str,
    collection_id: str,
    window: dict,
    description: str = "",
    *,
    incident_id: str | None = None,
) -> str:
    collection = authorize_collection(connection, actor, collection_id)
    if collection["active_snapshot_id"] is None:
        raise Problem(
            409, "collection_empty", "Importe um pacote válido antes de abrir o incidente."
        )
    incident_id = incident_id or uuid4().hex
    connection.execute(
        text("""
        INSERT INTO incidents(tenant_id,id,collection_id,title,description,window_from,window_to,time_zone,snapshot_id,created_by)
        VALUES(:tenant,:id,:collection,:title,:description,:start,:end,:timezone,:snapshot,:actor)
    """),
        {
            "tenant": actor.tenant_id,
            "id": incident_id,
            "collection": collection_id,
            "title": title,
            "description": description,
            "start": window["from"],
            "end": window["to"],
            "timezone": window.get("time_zone", "America/Sao_Paulo"),
            "snapshot": collection["active_snapshot_id"],
            "actor": actor.id,
        },
    )
    # The demo shares incidents with explicitly granted collection members, not all tenant users.
    connection.execute(
        text("""
        INSERT INTO incident_members(tenant_id,incident_id,user_id)
        SELECT tenant_id,:incident,user_id FROM collection_grants WHERE tenant_id=:tenant AND collection_id=:collection
    """),
        {"tenant": actor.tenant_id, "incident": incident_id, "collection": collection_id},
    )
    return incident_id


def incident_summary(connection: Connection, actor: Actor, row: dict) -> dict:
    # Snapshot membership is immutable. Deletion/revocation increments tenant_policy.revision.
    # Never cache an authorization decision: both checks run before every lookup.
    authorize_snapshot(connection, actor, row["snapshot_id"], row["collection_id"])
    revision = connection.execute(
        text("SELECT revision FROM tenant_policy WHERE tenant_id=:tenant"),
        {"tenant": actor.tenant_id},
    ).scalar_one()
    key = (actor.tenant_id, row["snapshot_id"], row["window_from"], row["window_to"], revision)

    def compute() -> dict:
        result = load_reconciliation(connection, actor, row["id"])
        return {
            "counts": {"orders": result.counts.orders, "divergences": result.counts.divergences},
            "coverage": [item.model_dump(mode="json", by_alias=True) for item in result.coverage],
        }

    return summaries.get(key, compute)


def latest_authorized(connection: Connection, actor: Actor, incident_id: str) -> tuple:
    from evidencedesk.investigations.service import authorize_run
    from evidencedesk.reviews.service import authorize_dossier

    params = {"tenant": actor.tenant_id, "id": incident_id}
    runs = (
        connection.execute(
            text("""
        SELECT r.id,j.state,j.stage,r.outcome,r.created_at FROM investigation_runs r
        JOIN jobs j ON j.tenant_id=r.tenant_id AND j.resource_id=r.id AND j.kind='investigation'
        WHERE r.tenant_id=:tenant AND r.incident_id=:id AND r.tombstoned_at IS NULL
        ORDER BY r.created_at DESC,r.id DESC LIMIT 20
    """),
            params,
        )
        .mappings()
        .all()
    )
    dossiers = (
        connection.execute(
            text("""
        SELECT id FROM dossiers WHERE tenant_id=:tenant AND incident_id=:id AND tombstoned_at IS NULL
        ORDER BY created_at DESC,id DESC LIMIT 20
    """),
            params,
        )
        .scalars()
        .all()
    )
    selected_run = None
    for run in runs:
        try:
            authorize_run(connection, actor, run["id"])
        except Problem as error:
            if error.status != 404:
                raise
        else:
            selected_run = dict(run)
            break
    selected_dossier = None
    for dossier in dossiers:
        try:
            authorize_dossier(connection, actor, dossier)
        except Problem as error:
            if error.status != 404:
                raise
        else:
            selected_dossier = dossier
            break
    return selected_run, selected_dossier


def incident_payload(connection: Connection, actor: Actor, incident_id: str) -> dict:
    row = authorize_incident(connection, actor, incident_id)
    snapshots = (
        connection.execute(
            text("""
        SELECT id,published_at FROM evidence_snapshots
        WHERE tenant_id=:tenant AND collection_id=:collection
        ORDER BY (id=:current) DESC,published_at DESC,id LIMIT 51
    """),
            {
                "tenant": actor.tenant_id,
                "collection": row["collection_id"],
                "current": row["snapshot_id"],
            },
        )
        .mappings()
        .all()
    )
    summary = incident_summary(connection, actor, row)
    run, dossier_id = latest_authorized(connection, actor, incident_id)
    return {
        "id": row["id"],
        "title": row["title"],
        "description": row["description"],
        "status": row["status"],
        "collection_id": row["collection_id"],
        "window": {
            "from": row["window_from"],
            "to": row["window_to"],
            "time_zone": row["time_zone"],
        },
        "created_at": row["created_at"],
        "updated_at": row["updated_at"],
        "evidence_snapshot_id": row["snapshot_id"],
        "available_snapshots": [dict(item) for item in snapshots[:50]],
        "available_snapshots_truncated": len(snapshots) > 50,
        "coverage": summary["coverage"],
        "counts": summary["counts"],
        "latest_run": run,
        "dossier_id": dossier_id,
        "permissions": actor.permissions,
    }
