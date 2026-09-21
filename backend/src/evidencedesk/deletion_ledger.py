"""Durable deletion intent, independent of the database snapshot being restored."""

import hashlib
import json
import os
import re
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path
from uuid import uuid4

from sqlalchemy import Connection, text

from evidencedesk.config import get_settings

MAX_LEDGER_BYTES = 16 * 1024**2


@dataclass(frozen=True)
class LedgerSnapshot:
    ledger_id: str
    records: tuple[dict, ...]
    prefixes: tuple[str, ...]

    @property
    def checkpoint(self) -> dict:
        return {
            "schema_version": 1,
            "ledger_id": self.ledger_id,
            "sequence": len(self.records),
            "sha256": self.prefixes[-1],
        }


def canonical_line(record: dict) -> bytes:
    return (
        json.dumps(record, ensure_ascii=False, sort_keys=True, separators=(",", ":")) + "\n"
    ).encode("utf-8")


def write_checkpoint(root: Path, checkpoint: dict) -> None:
    temporary = root / f".checkpoint-{uuid4().hex}.tmp"
    try:
        with temporary.open("xb") as output:
            output.write(canonical_line(checkpoint))
            output.flush()
            os.fsync(output.fileno())
        os.replace(temporary, root / "checkpoint.json")
    finally:
        temporary.unlink(missing_ok=True)


def read_ledger(root: Path | None = None, *, checkpoint_may_lag: bool = False) -> LedgerSnapshot:
    root = root or get_settings().deletion_ledger_root
    path, checkpoint_path = root / "ledger.jsonl", root / "checkpoint.json"
    if any(not item.is_file() or item.is_symlink() for item in (path, checkpoint_path)):
        raise ValueError("Deletion ledger or independent checkpoint is missing.")
    if path.stat().st_size > MAX_LEDGER_BYTES or checkpoint_path.stat().st_size > 1024:
        raise ValueError("Deletion ledger exceeds its bounded local format.")
    raw = path.read_bytes()
    if not raw.endswith(b"\n"):
        raise ValueError("Deletion ledger has an incomplete record.")
    lines = raw.splitlines(keepends=True)
    if not lines:
        raise ValueError("Deletion ledger identity is missing.")
    header = json.loads(lines[0])
    if (
        not isinstance(header, dict)
        or set(header) != {"schema_version", "kind", "ledger_id"}
        or type(header["schema_version"]) is not int
        or header["schema_version"] != 1
        or header["kind"] != "identity"
        or not isinstance(header["ledger_id"], str)
        or len(header["ledger_id"]) != 32
    ):
        raise ValueError("Invalid deletion ledger identity.")
    digest = hashlib.sha256(lines[0])
    prefixes = [digest.hexdigest()]
    records = []
    for index, line in enumerate(lines[1:], start=1):
        record = json.loads(line)
        base_fields = {"sequence", "tenant_id", "evidence_id", "object_key", "deleted_at"}
        if (
            not isinstance(record, dict)
            or set(record) not in (base_fields, base_fields | {"collection_id", "source_sha256"})
            or type(record["sequence"]) is not int
            or record["sequence"] != index
        ):
            raise ValueError("Invalid deletion ledger sequence.")
        if any(
            not isinstance(record[key], str) or not 1 <= len(record[key]) <= 256
            for key in ("tenant_id", "evidence_id")
        ):
            raise ValueError("Invalid deletion ledger identity fields.")
        if "collection_id" in record and (
            not isinstance(record["collection_id"], str)
            or not 1 <= len(record["collection_id"]) <= 256
            or not isinstance(record["source_sha256"], str)
            or not re.fullmatch(r"[a-f0-9]{64}", record["source_sha256"])
        ):
            raise ValueError("Invalid deletion source scope.")
        if record["object_key"] is not None and (
            not isinstance(record["object_key"], str) or not 1 <= len(record["object_key"]) <= 1024
        ):
            raise ValueError("Invalid deletion object key.")
        if (
            not isinstance(record["deleted_at"], str)
            or datetime.fromisoformat(record["deleted_at"]).tzinfo is None
        ):
            raise ValueError("Deletion time must include its timezone.")
        digest.update(line)
        prefixes.append(digest.hexdigest())
        records.append(record)
    snapshot = LedgerSnapshot(header["ledger_id"], tuple(records), tuple(prefixes))
    checkpoint = json.loads(checkpoint_path.read_text(encoding="utf-8"))
    if (
        not isinstance(checkpoint, dict)
        or set(checkpoint) != {"schema_version", "ledger_id", "sequence", "sha256"}
        or type(checkpoint["schema_version"]) is not int
        or checkpoint["schema_version"] != 1
        or type(checkpoint["sequence"]) is not int
        or not 0 <= checkpoint["sequence"] < len(prefixes)
        or checkpoint["ledger_id"] != snapshot.ledger_id
        or checkpoint["sha256"] != prefixes[checkpoint["sequence"]]
        or (not checkpoint_may_lag and checkpoint != snapshot.checkpoint)
    ):
        raise ValueError("Deletion ledger does not match its independent checkpoint.")
    return snapshot


def assert_extends_database(snapshot: LedgerSnapshot, state) -> None:
    if state["ledger_id"] is None:
        return
    sequence = state["sequence"]
    if (
        snapshot.ledger_id != state["ledger_id"]
        or sequence >= len(snapshot.prefixes)
        or snapshot.prefixes[sequence] != state["sha256"]
    ):
        raise ValueError("Current ledger is older than, or diverges from, the database checkpoint.")


def save_database_checkpoint(connection: Connection, snapshot: LedgerSnapshot) -> None:
    connection.execute(
        text(
            "UPDATE operational_ledger SET ledger_id=:ledger_id,sequence=:sequence,sha256=:sha256,reconciled_at=now() WHERE id=1"
        ),
        snapshot.checkpoint,
    )


def initialize_files(root: Path) -> LedgerSnapshot:
    root.mkdir(parents=True, exist_ok=True)
    ledger_path = root / "ledger.jsonl"
    if ledger_path.exists() or (root / "checkpoint.json").exists():
        return read_ledger(root)
    header = {"schema_version": 1, "kind": "identity", "ledger_id": uuid4().hex}
    with ledger_path.open("xb") as output:
        output.write(canonical_line(header))
        output.flush()
        os.fsync(output.fileno())
    checkpoint = {
        "schema_version": 1,
        "ledger_id": header["ledger_id"],
        "sequence": 0,
        "sha256": hashlib.sha256(canonical_line(header)).hexdigest(),
    }
    write_checkpoint(root, checkpoint)
    return read_ledger(root)


def append_intent(
    connection: Connection,
    tenant_id: str,
    evidence_id: str,
    object_key: str | None,
    *,
    collection_id: str,
    source_sha256: str,
) -> dict:
    # Caller holds maintenance SHARE + tenant policy; serialize only ledger writers here.
    state = (
        connection.execute(text("SELECT * FROM operational_ledger WHERE id=1 FOR UPDATE"))
        .mappings()
        .one()
    )
    root = get_settings().deletion_ledger_root
    snapshot = read_ledger(root)
    assert_extends_database(snapshot, state)
    if state["sequence"] != len(snapshot.records):
        raise ValueError("Pending deletion intent requires reconciliation before another deletion.")
    record = {
        "sequence": len(snapshot.records) + 1,
        "tenant_id": tenant_id,
        "evidence_id": evidence_id,
        "object_key": object_key,
        "collection_id": collection_id,
        "source_sha256": source_sha256,
        "deleted_at": datetime.now(UTC).isoformat(),
    }
    line = canonical_line(record)
    if (root / "ledger.jsonl").stat().st_size + len(line) > MAX_LEDGER_BYTES:
        raise ValueError("Deletion ledger reached the local size limit.")
    with (root / "ledger.jsonl").open("ab") as output:
        output.write(line)
        output.flush()
        os.fsync(output.fileno())
    digest = hashlib.sha256((root / "ledger.jsonl").read_bytes()).hexdigest()
    write_checkpoint(
        root,
        {
            "schema_version": 1,
            "ledger_id": snapshot.ledger_id,
            "sequence": record["sequence"],
            "sha256": digest,
        },
    )
    save_database_checkpoint(connection, read_ledger(root))
    return record
