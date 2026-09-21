import json
from uuid import uuid4

from sqlalchemy import Connection, text

from evidencedesk.errors import Problem, not_found
from evidencedesk.evidence.service import authorize_snapshot, resolve_evidence
from evidencedesk.identity.service import Actor, authorize_incident
from evidencedesk.incidents.service import load_reconciliation
from evidencedesk.model_runtime.contracts import GeneratedDossier


def authorize_dossier(connection: Connection, actor: Actor, dossier_id: str) -> dict:
    row = (
        connection.execute(
            text("SELECT * FROM dossiers WHERE tenant_id=:tenant AND id=:id"),
            {"tenant": actor.tenant_id, "id": dossier_id},
        )
        .mappings()
        .first()
    )
    if row is None or row.get("tombstoned_at") is not None:
        raise not_found()
    authorize_incident(connection, actor, row["incident_id"])
    # Protect every derived version, not merely the link next to a revoked source.
    revisions = connection.execute(
        text(
            "SELECT claims,impact_summary FROM dossier_revisions WHERE tenant_id=:tenant AND dossier_id=:id"
        ),
        {"tenant": actor.tenant_id, "id": dossier_id},
    ).mappings()
    for revision in revisions:
        source_ids = revision["impact_summary"].get("source_evidence_ids", [])
        if source_ids:
            count = connection.execute(
                text("""
                SELECT count(*) FROM evidence e JOIN collection_grants g ON g.tenant_id=e.tenant_id AND g.collection_id=e.collection_id
                WHERE e.tenant_id=:tenant AND e.id=ANY(:ids) AND e.tombstoned_at IS NULL AND g.user_id=:user
            """),
                {"tenant": actor.tenant_id, "ids": source_ids, "user": actor.id},
            ).scalar_one()
            if count != len(set(source_ids)):
                raise not_found()
        for claim in revision["claims"]:
            for link in claim["evidence_links"]:
                resolve_evidence(connection, actor, link["evidence_id"], row["snapshot_id"])
    return dict(row)


def dossier_payload(connection: Connection, actor: Actor, dossier_id: str) -> dict:
    row = authorize_dossier(connection, actor, dossier_id)
    revisions = (
        connection.execute(
            text("""
        SELECT r.id,r.number,u.name AS author,r.created_at,d.status AS review_status
        FROM dossier_revisions r JOIN users u ON u.id=r.created_by AND u.tenant_id=r.tenant_id
        JOIN revision_decisions d ON d.tenant_id=r.tenant_id AND d.revision_id=r.id
        WHERE r.tenant_id=:tenant AND r.dossier_id=:id ORDER BY r.number DESC
    """),
            {"tenant": actor.tenant_id, "id": dossier_id},
        )
        .mappings()
        .all()
    )
    return {
        "id": row["id"],
        "incident_id": row["incident_id"],
        "origin": row["origin"],
        "evidence_snapshot_id": row["snapshot_id"],
        "current_revision_id": row["current_revision_id"],
        "approved_revision_id": row["approved_revision_id"],
        "revisions": [dict(item) for item in revisions],
        "permissions": actor.permissions,
    }


def revision_payload(
    connection: Connection, actor: Actor, dossier_id: str, revision_id: str
) -> dict:
    authorize_dossier(connection, actor, dossier_id)
    row = (
        connection.execute(
            text("""
        SELECT r.*,d.status AS review_status,d.submitted_by,d.reviewed_by,d.reason,d.claim_ids AS reviewed_claim_ids,d.updated_at AS decision_updated_at FROM dossier_revisions r JOIN revision_decisions d ON d.tenant_id=r.tenant_id AND d.revision_id=r.id
        WHERE r.tenant_id=:tenant AND r.dossier_id=:dossier AND r.id=:revision
    """),
            {"tenant": actor.tenant_id, "dossier": dossier_id, "revision": revision_id},
        )
        .mappings()
        .first()
    )
    if row is None:
        raise not_found()
    result = {
        key: row[key]
        for key in (
            "id",
            "number",
            "base_revision_id",
            "summary",
            "claims",
            "outcome",
            "created_by",
            "created_at",
            "review_status",
            "missing_information",
            "suggested_checks",
            "impact_summary",
        )
    } | {"etag": f'"{revision_id}"'}
    result["impact_summary"] = {
        key: value for key, value in row["impact_summary"].items() if key != "source_evidence_ids"
    } or None
    result["review"] = {
        "submitted_by": row["submitted_by"],
        "reviewed_by": row["reviewed_by"],
        "reason": row["reason"],
        "claim_ids": row["reviewed_claim_ids"],
        "updated_at": row["decision_updated_at"],
    }
    if row["review_status"] in {"approved", "changes_requested"}:
        reviewed = set(row["reviewed_claim_ids"])
        result["claims"] = [
            claim
            | {"support_status": "reviewed" if row["review_status"] == "approved" else "contested"}
            if claim["claim_id"] in reviewed
            else claim
            for claim in row["claims"]
        ]
    return result


def validate_claims(
    connection: Connection,
    actor: Actor,
    incident: dict,
    snapshot_id: str,
    body: GeneratedDossier,
    base_claims: list[dict] | None = None,
) -> list[dict]:
    base_ids = {claim["claim_id"] for claim in base_claims or []}
    claims: list[dict] = []
    seen: set[str] = set()
    for claim in body.claims:
        if claim.claim_id and claim.claim_id not in base_ids:
            raise Problem(422, "unknown_claim", "A alegação não pertence à revisão de origem.")
        claim_id = claim.claim_id or uuid4().hex
        if claim_id in seen:
            raise Problem(422, "duplicate_claim", "A mesma alegação foi enviada duas vezes.")
        seen.add(claim_id)
        for link in claim.evidence_links:
            resolve_evidence(
                connection, actor, link.evidence_id, snapshot_id, incident_id=incident["id"]
            )
        data = claim.model_dump(mode="json")
        data["claim_id"] = claim_id
        # Editing never carries forward a semantic approval of previous wording.
        data["support_status"] = (
            "contested" if claim.support_status == "contested" else "pending_review"
        )
        claims.append(data)
    return claims


def write_revision(
    connection: Connection,
    actor: Actor,
    dossier: dict,
    body: GeneratedDossier,
    base: dict | None = None,
) -> str:
    incident = authorize_incident(connection, actor, dossier["incident_id"])
    claims = validate_claims(
        connection, actor, incident, dossier["snapshot_id"], body, base["claims"] if base else None
    )
    revision_id = uuid4().hex
    reconciliation = load_reconciliation(connection, actor, incident["id"], dossier["snapshot_id"])
    source_ids = (
        connection.execute(
            text("""
        SELECT e.id FROM evidence e JOIN snapshot_members m ON m.tenant_id=e.tenant_id AND m.evidence_id=e.id
        WHERE e.tenant_id=:tenant AND m.snapshot_id=:snapshot AND e.tombstoned_at IS NULL
          AND e.kind IN ('source_event','order_snapshot')
          AND CAST(coalesce(e.record->>'occurred_at',e.record->>'observed_at',e.record->>'as_of') AS timestamptz) BETWEEN :start AND :end
        ORDER BY e.id
    """),
            {
                "tenant": actor.tenant_id,
                "snapshot": dossier["snapshot_id"],
                "start": incident["window_from"],
                "end": incident["window_to"],
            },
        )
        .scalars()
        .all()
    )
    impact = reconciliation.counts.model_dump() | {
        "evidence_snapshot_id": dossier["snapshot_id"],
        "rule_revision": reconciliation.rule_revision,
        "source": "deterministic_reconciliation",
    }
    impact["source_evidence_ids"] = list(source_ids)
    valid_orders = {
        item.order_reference for item in reconciliation.timeline if item.order_reference
    }
    if any(order not in valid_orders for claim in body.claims for order in claim.order_references):
        raise Problem(
            422,
            "unknown_order_reference",
            "A alegação aponta um pedido fora do recorte autorizado.",
        )
    connection.execute(
        text("""
        INSERT INTO dossier_revisions(tenant_id,id,dossier_id,number,base_revision_id,summary,claims,outcome,created_by,missing_information,suggested_checks,impact_summary)
        VALUES(:tenant,:id,:dossier,:number,:base,:summary,CAST(:claims AS jsonb),:outcome,:actor,CAST(:missing AS jsonb),CAST(:checks AS jsonb),CAST(:impact AS jsonb))
    """),
        {
            "tenant": actor.tenant_id,
            "id": revision_id,
            "dossier": dossier["id"],
            "number": base["number"] + 1 if base else 1,
            "base": base["id"] if base else None,
            "summary": body.summary,
            "claims": json.dumps(claims),
            "outcome": body.outcome,
            "actor": actor.id,
            "missing": json.dumps(body.missing_information),
            "checks": json.dumps(body.suggested_checks),
            "impact": json.dumps(impact),
        },
    )
    connection.execute(
        text(
            "INSERT INTO revision_decisions(tenant_id,revision_id,status) VALUES(:tenant,:id,'draft')"
        ),
        {"tenant": actor.tenant_id, "id": revision_id},
    )
    connection.execute(
        text(
            "UPDATE dossiers SET current_revision_id=:revision WHERE tenant_id=:tenant AND id=:id"
        ),
        {"tenant": actor.tenant_id, "id": dossier["id"], "revision": revision_id},
    )
    return revision_id


def create_dossier(
    connection: Connection,
    actor: Actor,
    incident_id: str,
    snapshot_id: str,
    body: GeneratedDossier,
    *,
    origin: str = "manual",
    run_id: str | None = None,
) -> tuple[str, str]:
    incident = authorize_incident(connection, actor, incident_id)
    authorize_snapshot(connection, actor, snapshot_id, incident["collection_id"])
    dossier = {"id": uuid4().hex, "incident_id": incident_id, "snapshot_id": snapshot_id}
    connection.execute(
        text("""
        INSERT INTO dossiers(tenant_id,id,incident_id,snapshot_id,origin,run_id,created_by)
        VALUES(:tenant,:id,:incident,:snapshot,:origin,:run,:actor)
    """),
        {
            "tenant": actor.tenant_id,
            "id": dossier["id"],
            "incident": incident_id,
            "snapshot": snapshot_id,
            "origin": origin,
            "run": run_id,
            "actor": actor.id,
        },
    )
    revision_id = write_revision(connection, actor, dossier, body)
    return dossier["id"], revision_id


def assert_base_revision(
    connection: Connection, actor: Actor, dossier_id: str, revision_id: str, etag: str | None
) -> dict:
    dossier = authorize_dossier(connection, actor, dossier_id)
    connection.execute(
        text("SELECT id FROM dossiers WHERE tenant_id=:tenant AND id=:id FOR UPDATE"),
        {"tenant": actor.tenant_id, "id": dossier_id},
    )
    if dossier["current_revision_id"] != revision_id or etag != f'"{revision_id}"':
        raise Problem(
            409,
            "revision_conflict",
            "Existe uma revisão mais recente. Compare as alterações antes de salvar.",
        )
    return revision_payload(connection, actor, dossier_id, revision_id)


def submit_revision(
    connection: Connection, actor: Actor, dossier_id: str, revision_id: str, etag: str | None
) -> None:
    revision = assert_base_revision(connection, actor, dossier_id, revision_id, etag)
    if revision["review_status"] != "draft":
        raise Problem(
            409,
            "revision_not_draft",
            "Esta revisão já foi submetida. Crie uma nova versão para alterá-la.",
        )
    connection.execute(
        text(
            "UPDATE revision_decisions SET status='submitted',submitted_by=:actor,updated_at=now() WHERE tenant_id=:tenant AND revision_id=:id"
        ),
        {"tenant": actor.tenant_id, "id": revision_id, "actor": actor.id},
    )
    connection.execute(
        text(
            "UPDATE incidents SET status='in_review',updated_at=now() WHERE tenant_id=:tenant AND id=(SELECT incident_id FROM dossiers WHERE tenant_id=:tenant AND id=:dossier)"
        ),
        {"tenant": actor.tenant_id, "dossier": dossier_id},
    )


def review_revision(
    connection: Connection,
    actor: Actor,
    dossier_id: str,
    revision_id: str,
    etag: str | None,
    decision: str,
    reason: str,
    claim_ids: list[str],
) -> None:
    if actor.role not in {"reviewer", "tenant_admin"}:
        raise Problem(403, "reviewer_required", "A decisão exige um revisor autorizado.")
    revision = assert_base_revision(connection, actor, dossier_id, revision_id, etag)
    row = (
        connection.execute(
            text(
                "SELECT * FROM revision_decisions WHERE tenant_id=:tenant AND revision_id=:id FOR UPDATE"
            ),
            {"tenant": actor.tenant_id, "id": revision_id},
        )
        .mappings()
        .one()
    )
    if row["status"] != "submitted":
        raise Problem(
            409,
            "revision_not_submitted",
            "A revisão precisa estar submetida para receber uma decisão.",
        )
    if actor.id in {revision["created_by"], row["submitted_by"]}:
        raise Problem(
            403, "independent_reviewer_required", "Outra pessoa deve revisar esta submissão."
        )
    valid_ids = {claim["claim_id"] for claim in revision["claims"]}
    if not set(claim_ids).issubset(valid_ids):
        raise Problem(422, "unknown_claim", "A decisão aponta uma alegação de outra revisão.")
    if decision == "approved" and set(claim_ids) != valid_ids:
        raise Problem(
            422, "incomplete_review", "Revise todas as alegações antes de aprovar o dossiê."
        )
    connection.execute(
        text("""
        UPDATE revision_decisions SET status=:status,reviewed_by=:actor,reason=:reason,claim_ids=CAST(:claims AS jsonb),updated_at=now()
        WHERE tenant_id=:tenant AND revision_id=:id
    """),
        {
            "tenant": actor.tenant_id,
            "id": revision_id,
            "status": decision,
            "actor": actor.id,
            "reason": reason,
            "claims": json.dumps(claim_ids),
        },
    )
    if decision == "approved":
        connection.execute(
            text(
                "UPDATE dossiers SET approved_revision_id=:revision WHERE tenant_id=:tenant AND id=:id"
            ),
            {"tenant": actor.tenant_id, "id": dossier_id, "revision": revision_id},
        )
        connection.execute(
            text(
                "UPDATE incidents SET status='resolved',updated_at=now() WHERE tenant_id=:tenant AND id=(SELECT incident_id FROM dossiers WHERE tenant_id=:tenant AND id=:dossier)"
            ),
            {"tenant": actor.tenant_id, "dossier": dossier_id},
        )
