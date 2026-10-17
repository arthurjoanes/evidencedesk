import json
from hashlib import sha256

import pytest

from evidencedesk.errors import Problem
from evidencedesk.ingestion.parser import parse_content
from evidencedesk.ingestion.processing import evidence_records, parse_isolated
from evidencedesk.reconciliation.parsing import parse_snapshot_csv

HEADER = "source_system,snapshot_id,order_reference,status,as_of,source_timezone\n"


@pytest.mark.parametrize("newline", ["\n", "\r\n", "\r"])
def test_snapshot_source_locations_follow_physical_csv_lines(newline):
    content = (
        (
            HEADER
            + "\norders,s1,PED-1,paid,,UTC\n"
            + 'orders,s2,"PED\n2",paid,,UTC\n'
            + "orders,s3,PED-3,paid,,UTC\n"
        )
        .replace("\n", newline)
        .encode()
    )
    parsed = parse_content("snapshots", "text/csv", content)
    entry = {
        "sha256": "a" * 64,
        "object_key": "fixture/snapshots.csv",
        "media_type": "text/csv",
        "byte_size": len(content),
        "kind": "snapshots",
    }
    records = evidence_records("tenant", "collection", entry, parsed)
    assert [row["id"] for row in records] == [
        "ev_"
        + sha256(
            f"collection:{entry['sha256']}:snapshots:parser-v1:{index + 2}".encode()
        ).hexdigest()[:32]
        for index in range(3)
    ]
    assert [
        (json.loads(row["locator"])["line_start"], json.loads(row["locator"])["line_end"])
        for row in records
    ] == [(3, 3), (4, 5), (6, 6)]
    assert [row.order_reference for row in parse_snapshot_csv(content.decode())] == [
        "PED-1",
        f"PED{newline}2",
        "PED-3",
    ]


@pytest.mark.parametrize("last_field", ['"UTC', '"UTC"extra'])
def test_snapshot_csv_rejects_malformed_quoting(last_field):
    with pytest.raises(ValueError):
        parse_snapshot_csv(HEADER + "orders,s1,PED-1,paid,," + last_field)


def test_malformed_snapshot_is_a_controlled_error_from_the_isolated_parser():
    entry = {"kind": "snapshots", "media_type": "text/csv"}
    content = (HEADER + 'orders,s1,PED-1,paid,,"UTC').encode()
    with pytest.raises(Problem, match="invalid_file"):
        parse_isolated(entry, content)
