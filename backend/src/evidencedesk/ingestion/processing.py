import base64
import hashlib
import json
import os
import subprocess
import sys
from datetime import UTC, datetime
from uuid import uuid4

from pydantic import ValidationError
from sqlalchemy import Connection, text

from evidencedesk.config import get_settings
from evidencedesk.database import transaction
from evidencedesk.errors import Problem
from evidencedesk.evidence.storage import PrivateStorage
from evidencedesk.identity.service import actor_for_worker, authorize_collection
from evidencedesk.ingestion.contracts import DocumentMetadata
from evidencedesk.ingestion.limits import ExtractionBudget
from evidencedesk.jobs.service import Lease, assert_publishable, complete, enqueue
from evidencedesk.retrieval.chunking import (
    DOCUMENT_CHUNK_MAX_BYTES,
    DOCUMENT_CHUNK_REVISION,
    chunk_text,
)


def parse_isolated(entry: dict, content: bytes) -> dict:
    # No provider/session secrets are inherited by the parsing process.
    environment = {
        key: value
        for key, value in os.environ.items()
        if key in {"PATH", "SYSTEMROOT", "WINDIR", "PYTHONPATH", "LANG"}
    }
    command = [sys.executable, "-m", "evidencedesk.ingestion.parser"]
    result = subprocess.run(
        command,
        input=json.dumps(
            {
                "kind": entry["kind"],
                "media_type": entry["media_type"],
                "content": base64.b64encode(content).decode(),
            }
        ).encode(),
        capture_output=True,
        timeout=25,
        env=environment,
        check=False,
    )
    if len(result.stdout) > 60 * 1024 * 1024:
        raise Problem(422, "parser_output_limit", "A extração excedeu o limite permitido.")
    if result.returncode != 0:
        raise Problem(
            422,
            "invalid_file",
            "Arquivo inválido ou extração interrompida pelo limite de recursos.",
        )
    output = json.loads(result.stdout)
    if not output.get("ok"):
        raise Problem(422, "invalid_file", "Arquivo inválido para o schema declarado.")
    if output["result"].get("requires_ocr"):
        raise Problem(
            422, "requires_ocr", "O PDF não contém texto extraível. O pacote exige o perfil OCR."
        )
    return output["result"]


def evidence_records(tenant_id: str, collection_id: str, entry: dict, parsed: dict) -> list[dict]:
    records = []
    now = datetime.now(UTC).isoformat()
    common = {
        "tenant": tenant_id,
        "collection": collection_id,
        "sha256": entry["sha256"],
        "original_key": entry["object_key"],
        "media_type": entry["media_type"],
        "byte_size": entry["byte_size"],
    }

    def identity(position: str) -> str:
        parser_revision = DOCUMENT_CHUNK_REVISION if entry["kind"] == "document" else "parser-v1"
        return (
            "ev_"
            + hashlib.sha256(
                f"{collection_id}:{entry['sha256']}:{entry['kind']}:{parser_revision}:{position}".encode()
            ).hexdigest()[:32]
        )

    if entry["kind"] in {"events", "snapshots"}:
        for row in parsed["rows"]:
            data = row["value"]
            evidence_id = identity(str(row["line_number"]))
            record = data | {
                "evidence_id": evidence_id,
                "source_file_sha256": entry["sha256"],
                "line_number": row["line_number"],
            }
            if entry["kind"] == "events":
                record["ingested_at"] = now
            kind = "source_event" if entry["kind"] == "events" else "order_snapshot"
            label = data.get("event_type") or data.get("status")
            records.append(
                common
                | {
                    "id": evidence_id,
                    "kind": kind,
                    "title": f"{label} · {data.get('order_reference') or 'sem correspondência'}",
                    "version": "1",
                    "source_system": data["source_system"],
                    "temporal_role": "historical_artifact",
                    "valid_from": None,
                    "valid_until": None,
                    "canonical_text": json.dumps(data, ensure_ascii=False, indent=2),
                    "record": json.dumps(record),
                    "locator": json.dumps(
                        {
                            "line_start": row["line_number"],
                            "line_end": row["line_number"],
                            **({"as_of": data["as_of"]} if data.get("as_of") else {}),
                        }
                    ),
                }
            )
    elif entry["kind"] == "document":
        # Recheck persisted/queued imports too, not only new HTTP requests.
        try:
            metadata = DocumentMetadata.model_validate(entry["metadata"])
        except ValidationError:
            raise Problem(
                422,
                "invalid_document_metadata",
                "Os metadados temporais ou documentais são inválidos.",
            ) from None
        for page_number, content in enumerate(parsed["pages"], 1):
            # Byte limits are an offline admission policy, not a tokenizer measurement.
            # The pinned model tokenizer still checks every input (Unicode may normalize).
            for chunk in chunk_text(
                content,
                lambda value: len(value.encode("utf-8")),
                max_tokens=DOCUMENT_CHUNK_MAX_BYTES,
            ):
                start, end, canonical = chunk.char_start, chunk.char_end, chunk.text
                records.append(
                    common
                    | {
                        "id": identity(f"{page_number}:{start}:{end}"),
                        "kind": "document_span",
                        "title": metadata.title or entry["filename"],
                        "version": metadata.version or "1",
                        "source_system": metadata.source_system or "knowledge",
                        "temporal_role": metadata.temporal_role or "historical_artifact",
                        "valid_from": metadata.valid_from,
                        "valid_until": metadata.valid_until,
                        "canonical_text": canonical,
                        "record": json.dumps(
                            {
                                "parser": "text-pdf-v2",
                                "chunk_policy": DOCUMENT_CHUNK_REVISION,
                                "canonical_bytes": len(canonical.encode("utf-8")),
                                "token_count": None,
                                "document_lineage": metadata.document_lineage,
                            }
                        ),
                        "locator": json.dumps(
                            {
                                "page": page_number,
                                "line_start": content[:start].count("\n") + 1,
                                "line_end": content[:end].count("\n") + 1,
                                "char_start": start,
                                "char_end": end,
                            }
                        ),
                    }
                )
    return records


def reject_document_metadata_conflicts(
    connection: Connection, tenant_id: str, records: list[dict]
) -> None:
    """Same document identity may repeat, but its interpreted metadata is immutable."""
    fields = ("title", "version", "source_system", "temporal_role", "valid_from", "valid_until")
    expected: dict[str, tuple] = {}

    def conflict() -> Problem:
        return Problem(
            422,
            "document_metadata_conflict",
            "Os mesmos bytes documentais têm metadados incompatíveis. O snapshot anterior foi preservado.",
        )

    for row in records:
        if row["kind"] != "document_span":
            continue
        signature = tuple(row[field] for field in fields) + (
            json.loads(row["record"]).get("document_lineage"),
        )
        if row["id"] in expected and expected[row["id"]] != signature:
            raise conflict()
        expected[row["id"]] = signature

    identities = list(expected)
    for start in range(0, len(identities), 400):
        existing = connection.execute(
            text("""
                SELECT id,title,version,source_system,temporal_role,valid_from,valid_until,
                       record->>'document_lineage' AS document_lineage
                FROM evidence WHERE tenant_id=:tenant AND id=ANY(:ids)
            """),
            {"tenant": tenant_id, "ids": identities[start : start + 400]},
        ).mappings()
        for persisted in existing:
            signature = tuple(persisted[field] for field in fields) + (
                persisted["document_lineage"],
            )
            if expected[persisted["id"]] != signature:
                raise conflict()


def process_import(lease: Lease) -> None:
    with transaction(lease.tenant_id) as connection:
        assert_publishable(connection, lease)
        actor = actor_for_worker(connection, lease.tenant_id, lease.actor_id)
        batch = dict(
            connection.execute(
                text("SELECT * FROM import_batches WHERE tenant_id=:tenant AND id=:id"),
                {"tenant": lease.tenant_id, "id": lease.resource_id},
            )
            .mappings()
            .one()
        )
        authorize_collection(connection, actor, batch["collection_id"])
        entries = [
            dict(row)
            for row in connection.execute(
                text(
                    "SELECT * FROM import_entries WHERE tenant_id=:tenant AND batch_id=:id ORDER BY id"
                ),
                {"tenant": lease.tenant_id, "id": lease.resource_id},
            ).mappings()
        ]
        connection.execute(
            text("UPDATE import_batches SET state='processing' WHERE tenant_id=:tenant AND id=:id"),
            {"tenant": lease.tenant_id, "id": lease.resource_id},
        )
    storage = PrivateStorage()
    budget = ExtractionBudget()
    records: list[dict] = []
    new_mappings: list[dict] = []
    for entry in entries:
        try:
            content = storage.read(entry["object_key"])
            if hashlib.sha256(content).hexdigest() != entry["sha256"]:
                raise Problem(
                    422,
                    "storage_corrupted",
                    "O arquivo armazenado não passou na verificação de integridade.",
                )
            parsed = parse_isolated(entry, content)
            budget.include(parsed)
            extracted = evidence_records(lease.tenant_id, batch["collection_id"], entry, parsed)
            budget.include({}, len(extracted))
            records.extend(extracted)
            if entry["kind"] == "mappings":
                new_mappings.extend(row["value"] for row in parsed["rows"])
        except (Problem, subprocess.TimeoutExpired, OSError) as error:
            code = error.code if isinstance(error, Problem) else "parser_failed"
            message = (
                error.message
                if isinstance(error, Problem)
                else "Não foi possível extrair o arquivo dentro dos limites."
            )
            with transaction(lease.tenant_id) as connection:
                assert_publishable(connection, lease)
                details = json.dumps({"code": code, "message": message})
                connection.execute(
                    text(
                        "UPDATE import_entries SET state=:state,error=CAST(:error AS jsonb) WHERE tenant_id=:tenant AND batch_id=:batch AND id=:entry"
                    ),
                    {
                        "tenant": lease.tenant_id,
                        "batch": lease.resource_id,
                        "entry": entry["id"],
                        "state": "requires_ocr" if code == "requires_ocr" else "rejected",
                        "error": details,
                    },
                )
                connection.execute(
                    text(
                        "UPDATE import_batches SET state='rejected',error=CAST(:error AS jsonb) WHERE tenant_id=:tenant AND id=:id"
                    ),
                    {"tenant": lease.tenant_id, "id": lease.resource_id, "error": details},
                )
            raise Problem(422, code, message) from None
    snapshot_id = uuid4().hex
    with transaction(lease.tenant_id) as connection:
        assert_publishable(connection, lease)
        actor = actor_for_worker(connection, lease.tenant_id, lease.actor_id)
        collection = authorize_collection(connection, actor, batch["collection_id"])
        # Policy locking serializes this check with all publication in the tenant.
        # Check both incoming duplicates and existing identities before any snapshot.
        reject_document_metadata_conflicts(connection, lease.tenant_id, records)
        coverage = batch["manifest"]["coverage"]
        previous = collection["active_snapshot_id"]
        if previous:
            old = connection.execute(
                text("SELECT coverage FROM evidence_snapshots WHERE tenant_id=:tenant AND id=:id"),
                {"tenant": lease.tenant_id, "id": previous},
            ).scalar_one()
            unique = {json.dumps(item, sort_keys=True): item for item in old + coverage}
            coverage = list(unique.values())
        connection.execute(
            text(
                "INSERT INTO evidence_snapshots(tenant_id,id,collection_id,coverage) VALUES(:tenant,:id,:collection,CAST(:coverage AS jsonb))"
            ),
            {
                "tenant": lease.tenant_id,
                "id": snapshot_id,
                "collection": batch["collection_id"],
                "coverage": json.dumps(coverage),
            },
        )
        if records:
            statement = text("""
                INSERT INTO evidence(tenant_id,id,collection_id,kind,title,version,sha256,source_system,temporal_role,valid_from,valid_until,canonical_text,locator,record,original_key,media_type,byte_size)
                VALUES(:tenant,:id,:collection,:kind,:title,:version,:sha256,:source_system,:temporal_role,:valid_from,:valid_until,:canonical_text,CAST(:locator AS jsonb),CAST(:record AS jsonb),:original_key,:media_type,:byte_size)
                ON CONFLICT(tenant_id,id) DO NOTHING
            """)
            for start in range(0, len(records), 400):
                connection.execute(statement, records[start : start + 400])
        if previous:
            connection.execute(
                text(
                    "INSERT INTO snapshot_members(tenant_id,snapshot_id,evidence_id) SELECT tenant_id,:new,evidence_id FROM snapshot_members WHERE tenant_id=:tenant AND snapshot_id=:old"
                ),
                {"tenant": lease.tenant_id, "new": snapshot_id, "old": previous},
            )
            connection.execute(
                text(
                    "INSERT INTO snapshot_mappings SELECT tenant_id,:new,source_system,source_order_reference,order_reference FROM snapshot_mappings WHERE tenant_id=:tenant AND snapshot_id=:old"
                ),
                {"tenant": lease.tenant_id, "new": snapshot_id, "old": previous},
            )
        if records:
            connection.execute(
                text(
                    "INSERT INTO snapshot_members(tenant_id,snapshot_id,evidence_id) VALUES(:tenant,:snapshot,:evidence) ON CONFLICT DO NOTHING"
                ),
                [
                    {"tenant": lease.tenant_id, "snapshot": snapshot_id, "evidence": item["id"]}
                    for item in records
                ],
            )
        existing_mappings = {
            (row["source_system"], row["source_order_reference"]): row["order_reference"]
            for row in connection.execute(
                text(
                    "SELECT source_system,source_order_reference,order_reference FROM snapshot_mappings WHERE tenant_id=:tenant AND snapshot_id=:snapshot"
                ),
                {"tenant": lease.tenant_id, "snapshot": snapshot_id},
            ).mappings()
        }
        for mapping in new_mappings:
            identity = (mapping["source_system"], mapping["source_order_reference"])
            existing = existing_mappings.get(identity)
            if existing is not None and existing != mapping["order_reference"]:
                raise Problem(
                    422,
                    "mapping_conflict",
                    "O pacote contém correspondência incompatível com o corpus atual.",
                )
            existing_mappings[identity] = mapping["order_reference"]
        if new_mappings:
            connection.execute(
                text(
                    "INSERT INTO snapshot_mappings(tenant_id,snapshot_id,source_system,source_order_reference,order_reference) VALUES(:tenant,:snapshot,:source_system,:source_order_reference,:order_reference) ON CONFLICT DO NOTHING"
                ),
                [
                    {"tenant": lease.tenant_id, "snapshot": snapshot_id, **item}
                    for item in new_mappings
                ],
            )
        connection.execute(
            text(
                "UPDATE collections SET active_snapshot_id=:snapshot WHERE tenant_id=:tenant AND id=:id"
            ),
            {"tenant": lease.tenant_id, "id": batch["collection_id"], "snapshot": snapshot_id},
        )
        connection.execute(
            text(
                "UPDATE import_batches SET state='ready',snapshot_id=:snapshot WHERE tenant_id=:tenant AND id=:id"
            ),
            {"tenant": lease.tenant_id, "id": lease.resource_id, "snapshot": snapshot_id},
        )
        connection.execute(
            text(
                "UPDATE import_entries SET state='valid' WHERE tenant_id=:tenant AND batch_id=:id"
            ),
            {"tenant": lease.tenant_id, "id": lease.resource_id},
        )
        complete(connection, lease)
        if get_settings().retrieval_mode != "lexical":
            enqueue(connection, actor, "index_snapshot", snapshot_id, lease.policy_revision)
