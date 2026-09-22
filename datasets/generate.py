"""Generate original synthetic import packages; no external data or model calls.

Run from the repository root: python datasets/generate.py --output datasets/generated
Gold/evaluation files are generated separately and are never import manifest entries.
"""

from __future__ import annotations

import argparse
import csv
import hashlib
import io
import json
from datetime import UTC, datetime, timedelta
from pathlib import Path

FAMILIES = (
    "duplicate_webhook",
    "delayed_delivery",
    "out_of_order",
    "ambiguous_timeout",
    "expired_reservation",
    "stale_snapshot",
    "identity_mismatch",
    "obsolete_procedure",
    "partial_failure",
    "missing_coverage",
)
TITLES = {
    "duplicate_webhook": "Reentrega do webhook de pagamento",
    "delayed_delivery": "Confirmação recebida após a janela operacional",
    "out_of_order": "Eventos recebidos fora de ordem",
    "ambiguous_timeout": "Timeout sem confirmação de aceite",
    "expired_reservation": "Reserva expirada antes da confirmação",
    "stale_snapshot": "Snapshot anterior ao pagamento",
    "identity_mismatch": "Identificador sem correspondência declarada",
    "obsolete_procedure": "Procedimento antigo citado na operação",
    "partial_failure": "Pagamento confirmado e pedido pendente",
    "missing_coverage": "Intervalo sem coleta no serviço de pedidos",
}


def iso(value: datetime | None) -> str | None:
    return value.isoformat().replace("+00:00", "Z") if value is not None else None


def json_bytes(value: object) -> bytes:
    return (json.dumps(value, ensure_ascii=False, indent=2, sort_keys=True) + "\n").encode("utf-8")


def jsonl_bytes(rows: list[dict]) -> bytes:
    return (
        "\n".join(json.dumps(row, ensure_ascii=False, sort_keys=True) for row in rows) + "\n"
    ).encode("utf-8")


def incident_records(
    tenant: str,
    index: int,
    normal_orders: int,
    *,
    family_override: str | None = None,
    namespace: str = "demo",
) -> tuple[dict, list[dict], list[dict], list[dict], list[dict]]:
    family = family_override or FAMILIES[index % len(FAMILIES)]
    if family not in FAMILIES:
        raise ValueError("Família sintética desconhecida.")
    start = datetime(2026, 7, 1, 12, tzinfo=UTC) + timedelta(days=index)
    end = start + timedelta(minutes=30)
    case_id = f"{namespace}-{tenant}-{index + 1:02d}"
    case = {
        "id": case_id,
        "scenario_family": family,
        "scenario_instance": case_id,
        "tenant": tenant,
        "title": TITLES[family],
        "description": "Caso fictício para investigação. Horários, empresas e pedidos são sintéticos.",
        "question": "O que foi observado neste incidente e quais evidências ainda faltam?",
        "window": {
            "from": iso(start),
            "to": iso(end),
            "time_zone": "America/Sao_Paulo",
        },
        "focus_order": f"PED-{index + 1:03d}-000",
    }
    events, snapshots, mappings = [], [], []

    def event(
        order: str,
        source: str,
        event_type: str,
        at: int | None,
        observed: int | None = None,
        suffix: str = "",
        payload: dict | None = None,
    ) -> dict:
        source_reference = f"{source.upper()}-{order}"
        result = {
            "source_system": source,
            "source_event_id": f"{case_id}-{order}-{event_type}{suffix}",
            "delivery_id": f"delivery-{case_id}-{order}-{event_type}{suffix}",
            "order_reference": source_reference,
            "event_type": event_type,
            "occurred_at": iso(start + timedelta(seconds=at)) if at is not None else None,
            "observed_at": iso(start + timedelta(seconds=observed if observed is not None else at))
            if at is not None or observed is not None
            else None,
            "source_timezone": "UTC",
            "schema_version": "1",
            "payload": payload or {},
            "time_unknown_reason": "A fonte não registrou o horário de ocorrência."
            if at is None
            else None,
        }
        events.append(result)
        return result

    for order_index in range(normal_orders + 1):
        order = f"PED-{index + 1:03d}-{order_index:03d}"
        focus = order_index == 0
        for source in ("payments", "orders", "inventory"):
            if focus and family == "identity_mismatch" and source == "payments":
                continue
            mappings.append(
                {
                    "source_system": source,
                    "source_order_reference": f"{source.upper()}-{order}",
                    "order_reference": order,
                }
            )
        payment = event(order, "payments", "payment.confirmed", 30, 31)
        domain_time = 50
        status, as_of = "paid", 600
        if focus:
            if family == "duplicate_webhook":
                events.append(
                    {
                        **payment,
                        "delivery_id": payment["delivery_id"] + "-retry",
                        "observed_at": iso(start + timedelta(seconds=95)),
                    }
                )
            elif family == "delayed_delivery":
                payment["observed_at"] = iso(start + timedelta(seconds=480))
                domain_time = 490
            elif family == "out_of_order":
                event(order, "inventory", "inventory.reserved", 20, 100)
            elif family == "ambiguous_timeout":
                events.pop()
                event(
                    order,
                    "payments",
                    "payment.request_timeout",
                    None,
                    40,
                    payload={"acceptance": "unknown"},
                )
                domain_time, status = None, "pending_payment"
            elif family == "expired_reservation":
                event(order, "inventory", "inventory.reservation_expired", 60, 61)
                domain_time = 100
            elif family == "stale_snapshot":
                as_of, status = 10, "pending_payment"
            elif family == "obsolete_procedure":
                event(
                    order,
                    "orders",
                    "procedure.consulted",
                    45,
                    46,
                    payload={
                        "document_revision": "1",
                        "document_lineage": f"{case_id}-procedure",
                    },
                )
            elif family in {"partial_failure", "missing_coverage"}:
                domain_time, status = None, "pending_payment"
        if domain_time is not None:
            event(order, "orders", "order.payment_confirmed", domain_time, domain_time + 1)
        event(order, "inventory", "inventory.reserved", 15, 16, suffix="-normal")
        snapshots.append(
            {
                "source_system": "orders",
                "snapshot_id": f"snapshot-{case_id}-{order}",
                "order_reference": f"ORDERS-{order}",
                "status": status,
                "as_of": iso(start + timedelta(seconds=as_of)),
                "source_timezone": "UTC",
            }
        )
    coverage = [
        {
            "source_system": source,
            "status": "partial"
            if source == "orders" and family == "missing_coverage"
            else "complete",
            "from": iso(start),
            "to": iso(end),
            "gaps": ["Coleta indisponível entre 12:00:20Z e 12:06:00Z."]
            if source == "orders" and family == "missing_coverage"
            else [],
            "clock_uncertainty_ms": 500,
            "event_types": [],
        }
        for source in ("payments", "orders", "inventory")
    ]
    return case, events, snapshots, mappings, coverage


def documents(case: dict) -> list[tuple[str, str, dict]]:
    start = datetime.fromisoformat(case["window"]["from"].replace("Z", "+00:00"))
    lineage = case["id"] + "-procedure"
    current = (
        f"# Procedimento de conciliação — {case['tenant'].title()}\n\n"
        f"Procedimento sintético do caso {case['id']}: {case['title']}.\n\n"
        "Revisão 2. A confirmação de pagamento deve ser observada no domínio de pedidos em até 300 segundos.\n\n"
        "Esse prazo pertence a este laboratório fictício. Mensagens repetidas representam reentrega; "
        "não demonstram cobrança duplicada. Compare identidades de operação antes de discutir efeito financeiro.\n\n"
        "Considere cobertura de coleta e precisão dos relógios. Ausência no recorte significa apenas "
        "evento não observado. Em timeout, o aceite pode ser desconhecido. Não reenvie pagamentos.\n\n"
        "Uma reserva expirada antes da confirmação é uma sequência observável, não causa raiz comprovada.\n"
    )
    historical = (
        "# Procedimento arquivado\n\nRevisão 1. Este procedimento foi substituído antes deste incidente.\n\n"
        f"Procedimento sintético arquivado do caso {case['id']}: {case['title']}.\n\n"
        "A orientação antiga usava prazo de 900 segundos. Ela não deve ser aplicada retroativamente "
        "como norma válida. Se um registro mostrar que foi consultada, documente o uso como artefato histórico.\n"
    )
    postmortem = (
        f"# Nota retrospectiva: {case['title']}\n\n"
        f"Documento fictício redigido um dia após o caso {case['id']}.\n\n"
        "A equipe registrou a necessidade de comparar horários de ocorrência e observação, consultar a "
        "cobertura e manter hipóteses separadas de fatos. Esta nota não confirma a causa deste incidente.\n\n"
        "Verificações pendentes: examinar o identificador da operação e obter confirmação independente da origem.\n"
    )
    base = {"source_system": "knowledge", "document_lineage": lineage}
    return [
        (
            case["id"] + "-procedure-v2.md",
            current,
            {
                **base,
                "title": "Procedimento de conciliação vigente",
                "version": "2",
                "valid_from": iso(start - timedelta(days=1)),
                "valid_until": None,
                "temporal_role": "applicable_procedure",
            },
        ),
        (
            case["id"] + "-procedure-v1.md",
            historical,
            {
                **base,
                "title": "Procedimento arquivado",
                "version": "1",
                "valid_from": iso(start - timedelta(days=100)),
                "valid_until": iso(start - timedelta(days=1)),
                "temporal_role": "historical_artifact",
            },
        ),
        (
            case["id"] + "-retrospective.md",
            postmortem,
            {
                **base,
                "document_lineage": case["id"] + "-retrospective",
                "title": "Nota retrospectiva",
                "version": "1",
                "valid_from": iso(start + timedelta(days=1)),
                "valid_until": None,
                "temporal_role": "retrospective_context",
            },
        ),
    ]


def write_entry(
    packet_dir: Path,
    entries: list[dict],
    filename: str,
    kind: str,
    media_type: str,
    data: bytes,
    metadata: dict | None = None,
) -> None:
    if len(data) > 10 * 1024 * 1024:
        raise ValueError("Arquivo gerado excede 10 MiB; reduza --normal-orders.")
    (packet_dir / filename).write_bytes(data)
    entry = {
        "entry_id": f"entry-{len(entries) + 1:03d}",
        "filename": filename,
        "kind": kind,
        "media_type": media_type,
        "byte_size": len(data),
        "sha256": hashlib.sha256(data).hexdigest(),
    }
    if metadata:
        entry["metadata"] = metadata
    entries.append(entry)


def generate(output: Path, normal_orders: int = 221) -> dict:
    output.mkdir(parents=True, exist_ok=True)
    index = {
        "schema_version": "1",
        "origin": "original_synthetic",
        "packages": [],
        "incidents": [],
        "counts": {"events": 0, "snapshots": 0, "documents": 0},
    }
    for tenant in ("aurora", "horizonte"):
        for packet_index in range(3):
            packet_name = f"{tenant}-{packet_index + 1:02d}"
            packet_dir = output / packet_name
            packet_dir.mkdir(exist_ok=True)
            all_events, all_snapshots, all_mappings, all_coverage, entries = (
                [],
                [],
                [],
                [],
                [],
            )
            cases = []

            for index_in_packet in range(5):
                case_index = packet_index * 5 + index_in_packet
                # Alternate family sequence across tenants while preserving repeated order IDs.
                case, events, snapshots, mappings, coverage = incident_records(
                    tenant, case_index, normal_orders
                )
                cases.append(case)
                all_events.extend(events)
                all_snapshots.extend(snapshots)
                all_mappings.extend(mappings)
                all_coverage.extend(coverage)
                for filename, text, metadata in documents(case):
                    write_entry(
                        packet_dir,
                        entries,
                        filename,
                        "document",
                        "text/markdown",
                        text.encode("utf-8"),
                        metadata,
                    )
            write_entry(
                packet_dir,
                entries,
                "events.jsonl",
                "events",
                "application/x-ndjson",
                jsonl_bytes(all_events),
            )
            snapshot_csv = io.StringIO(newline="")
            writer = csv.DictWriter(
                snapshot_csv,
                fieldnames=[
                    "source_system",
                    "snapshot_id",
                    "order_reference",
                    "status",
                    "as_of",
                    "source_timezone",
                ],
            )
            writer.writeheader()
            writer.writerows(all_snapshots)
            write_entry(
                packet_dir,
                entries,
                "snapshots.csv",
                "snapshots",
                "text/csv",
                snapshot_csv.getvalue().encode("utf-8"),
            )
            write_entry(
                packet_dir,
                entries,
                "mappings.jsonl",
                "mappings",
                "application/x-ndjson",
                jsonl_bytes(all_mappings),
            )
            manifest = {
                "schema_version": "1",
                "title": f"Laboratório {tenant.title()} — lote {packet_index + 1}",
                "source_tenant": tenant,
                "coverage": all_coverage,
                "entries": entries,
            }
            if sum(entry["byte_size"] for entry in entries) > 40 * 1024 * 1024:
                raise ValueError("Pacote excede 40 MiB.")
            (packet_dir / "manifest.json").write_bytes(json_bytes(manifest))
            (packet_dir / "incidents.json").write_bytes(json_bytes(cases))
            index["packages"].append(
                {
                    "tenant": tenant,
                    "directory": packet_name,
                    "manifest": f"{packet_name}/manifest.json",
                }
            )
            index["incidents"].extend({**case, "package": packet_name} for case in cases)
            index["counts"]["events"] += len(all_events)
            index["counts"]["snapshots"] += len(all_snapshots)
            index["counts"]["documents"] += 15
    (output / "index.json").write_bytes(json_bytes(index))
    return index


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output", type=Path, default=Path("datasets/generated"))
    parser.add_argument("--normal-orders", type=int, default=221)
    options = parser.parse_args()
    if not 0 <= options.normal_orders <= 1000:
        parser.error("--normal-orders deve estar entre 0 e 1000.")
    result = generate(options.output, options.normal_orders)
    print(
        json.dumps(
            {
                "packages": len(result["packages"]),
                "incidents": len(result["incidents"]),
                **result["counts"],
            },
            ensure_ascii=False,
        )
    )
