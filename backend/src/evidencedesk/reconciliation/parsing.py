"""Strict file parsing; record IDs and import time are supplied by the caller."""

import csv
import io

from .contracts import SnapshotInput


def parse_snapshot_csv(text: str) -> list[SnapshotInput]:
    return [row for _, _, row in parse_snapshot_csv_with_locations(text)]


def parse_snapshot_csv_with_locations(text: str) -> list[tuple[int, int, SnapshotInput]]:
    reader = csv.reader(io.StringIO(text, newline=""), strict=True)
    expected = {
        "source_system",
        "snapshot_id",
        "order_reference",
        "status",
        "as_of",
        "source_timezone",
    }
    rows: list[tuple[int, int, SnapshotInput]] = []
    try:
        columns = next(reader, None)
        if columns is None or set(columns) != expected or len(columns) != len(expected):
            raise ValueError("Cabeçalho de snapshots inválido.")
        while True:
            line_start = reader.line_num + 1
            values = next(reader, None)
            if values is None:
                break
            if not values:
                continue
            if len(rows) >= 100_000:
                raise ValueError("Arquivo de snapshots excede o limite de registros.")
            if len(values) != len(columns):
                raise ValueError("Linha de snapshot possui quantidade inválida de colunas.")
            row = dict(zip(columns, values, strict=True))
            snapshot = SnapshotInput.model_validate({**row, "as_of": row["as_of"] or None})
            rows.append((line_start, reader.line_num, snapshot))
    except csv.Error as error:
        raise ValueError("CSV de snapshots malformado.") from error
    return rows
