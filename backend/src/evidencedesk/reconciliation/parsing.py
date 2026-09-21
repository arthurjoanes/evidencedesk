"""Strict file parsing; record IDs and import time are supplied by the caller."""

import csv
import io

from .contracts import SnapshotInput


def parse_snapshot_csv(text: str) -> list[SnapshotInput]:
    reader = csv.DictReader(io.StringIO(text))
    expected = {
        "source_system",
        "snapshot_id",
        "order_reference",
        "status",
        "as_of",
        "source_timezone",
    }
    if (
        reader.fieldnames is None
        or set(reader.fieldnames) != expected
        or len(reader.fieldnames) != len(expected)
    ):
        raise ValueError("Cabeçalho de snapshots inválido.")
    rows: list[SnapshotInput] = []
    for row in reader:
        if len(rows) >= 100_000:
            raise ValueError("Arquivo de snapshots excede o limite de registros.")
        if None in row:
            raise ValueError("Linha de snapshot possui colunas excedentes.")
        rows.append(SnapshotInput.model_validate({**row, "as_of": row["as_of"] or None}))
    return rows
