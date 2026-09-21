import html
import json

from sqlalchemy import text

from evidencedesk.database import transaction
from evidencedesk.errors import Problem
from evidencedesk.evidence.service import resolve_evidence
from evidencedesk.evidence.storage import PrivateStorage
from evidencedesk.identity.service import actor_for_worker
from evidencedesk.jobs.service import Lease, assert_publishable, complete
from evidencedesk.reviews.service import authorize_dossier, revision_payload


def process_export(lease: Lease) -> None:
    with transaction(lease.tenant_id) as connection:
        assert_publishable(connection, lease)
        actor = actor_for_worker(connection, lease.tenant_id, lease.actor_id)
        export = (
            connection.execute(
                text("SELECT * FROM exports WHERE tenant_id=:tenant AND id=:id"),
                {"tenant": lease.tenant_id, "id": lease.resource_id},
            )
            .mappings()
            .one()
        )
        dossier = authorize_dossier(connection, actor, export["dossier_id"])
        revision = revision_payload(connection, actor, dossier["id"], export["revision_id"])
        if revision["review_status"] != "approved":
            raise Problem(409, "approval_required", "A revisão não está aprovada para exportação.")
        sources = {}
        for claim in revision["claims"]:
            for link in claim["evidence_links"]:
                evidence_id = link["evidence_id"]
                sources[evidence_id] = resolve_evidence(
                    connection, actor, evidence_id, dossier["snapshot_id"]
                )
    content = render_export(dossier, revision, sources)
    key = f"tenants/{lease.tenant_id}/exports/{lease.resource_id}/{lease.token}.html"
    checksum = PrivateStorage().put(key, content)
    with transaction(lease.tenant_id) as connection:
        assert_publishable(connection, lease)
        actor = actor_for_worker(connection, lease.tenant_id, lease.actor_id)
        authorize_dossier(connection, actor, dossier["id"])
        connection.execute(
            text(
                "UPDATE exports SET object_key=:key,sha256=:hash,expires_at=now()+interval '24 hours' WHERE tenant_id=:tenant AND id=:id"
            ),
            {"tenant": lease.tenant_id, "id": lease.resource_id, "key": key, "hash": checksum},
        )
        complete(connection, lease)


def render_export(dossier: dict, revision: dict, sources: dict) -> bytes:
    esc = html.escape
    sections = []
    for claim in revision["claims"]:
        links = "".join(
            f'<li>{esc(link["relation"])} — <a href="#{esc(link["evidence_id"])}">{esc(sources[link["evidence_id"]]["title"])}</a></li>'
            for link in claim["evidence_links"]
        )
        sections.append(
            f"<section><h2>{'Fato observado' if claim['kind'] == 'observed_fact' else 'Hipótese'}</h2><p>{esc(claim['text'])}</p><p>Alegação {esc(claim['claim_id'])} · {esc(claim['support_status'])}</p><ul>{links}</ul>{render_list('Lacunas desta alegação', claim['missing_information'])}{render_list('Verificações desta alegação', claim['suggested_checks'])}</section>"
        )
    evidence_html = "".join(
        f'<section id="{esc(key)}"><h3>{esc(value["title"])}</h3><p>Evidência {esc(key)} · Versão {esc(value["version"])} · SHA256 {esc(value["sha256"])}</p><p>Localizador: {esc(json.dumps(value["locator"], ensure_ascii=False))}</p><pre>{esc(value["canonical_text"])}</pre></section>'
        for key, value in sources.items()
    )
    provenance = esc(
        json.dumps(
            {
                "incident_id": dossier["incident_id"],
                "evidence_snapshot_id": dossier["snapshot_id"],
                "impact_summary": revision["impact_summary"],
                "review": revision["review"],
            },
            ensure_ascii=False,
            indent=2,
            default=str,
        )
    )
    return f'<!doctype html><html lang="pt-BR"><meta charset="utf-8"><meta name="viewport" content="width=device-width"><meta http-equiv="Content-Security-Policy" content="default-src \'none\'; style-src \'unsafe-inline\'"><title>EvidenceDesk — dossiê revisado</title><style>body{{font:17px/1.6 system-ui;max-width:900px;margin:40px auto;padding:24px;color:#202c37;overflow-wrap:anywhere}}pre{{white-space:pre-wrap;overflow-wrap:anywhere}}section{{border-top:1px solid #ccd2d8;padding-block:16px}}</style><main><h1>Dossiê revisado</h1><p>Origem: {esc(dossier["origin"])}. Revisão {revision["number"]} — {esc(revision["id"])}</p><p>{esc(revision["summary"])}</p>{"".join(sections)}{render_list("Lacunas da investigação", revision["missing_information"])}{render_list("Próximas verificações", revision["suggested_checks"])}<h2>Recorte, impacto calculado e revisão</h2><pre>{provenance}</pre><h2>Fontes verificáveis</h2>{evidence_html}</main></html>'.encode()


def render_list(title: str, items: list[str]) -> str:
    if not items:
        return ""
    return (
        f"<h3>{html.escape(title)}</h3><ul>"
        + "".join(f"<li>{html.escape(item)}</li>" for item in items)
        + "</ul>"
    )
