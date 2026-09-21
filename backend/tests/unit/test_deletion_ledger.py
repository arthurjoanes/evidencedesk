import hashlib
import json

import pytest

from evidencedesk.deletion_ledger import (
    LedgerSnapshot,
    assert_extends_database,
    canonical_line,
    initialize_files,
    read_ledger,
    write_checkpoint,
)


def test_initialization_is_idempotent_and_never_replaces_a_lost_checkpoint(tmp_path):
    first = initialize_files(tmp_path)
    assert initialize_files(tmp_path) == first
    (tmp_path / "checkpoint.json").unlink()
    with pytest.raises(ValueError, match="missing"):
        initialize_files(tmp_path)
    assert (tmp_path / "ledger.jsonl").exists()


def test_partial_append_or_changed_bytes_fail_closed(tmp_path):
    initialize_files(tmp_path)
    with (tmp_path / "ledger.jsonl").open("ab") as stream:
        stream.write(b'{"sequence":1')
    with pytest.raises(ValueError, match="incomplete"):
        read_ledger(tmp_path)


def test_checkpoint_cannot_silently_mask_truncation(tmp_path):
    initial = initialize_files(tmp_path)
    value = initial.checkpoint | {"sequence": 1, "sha256": "f" * 64}
    write_checkpoint(tmp_path, value)
    with pytest.raises(ValueError, match="checkpoint"):
        read_ledger(tmp_path)


def test_database_checkpoint_detects_older_or_divergent_independent_copy():
    snapshot = LedgerSnapshot("a" * 32, (), ("1" * 64,))
    assert_extends_database(snapshot, {"ledger_id": "a" * 32, "sequence": 0, "sha256": "1" * 64})
    for checkpoint in [
        {"ledger_id": "b" * 32, "sequence": 0, "sha256": "1" * 64},
        {"ledger_id": "a" * 32, "sequence": 1, "sha256": "1" * 64},
        {"ledger_id": "a" * 32, "sequence": 0, "sha256": "2" * 64},
    ]:
        with pytest.raises(ValueError, match="older than, or diverges"):
            assert_extends_database(snapshot, checkpoint)


def test_ledger_refuses_unbounded_or_unstructured_identity(tmp_path):
    initialize_files(tmp_path)
    (tmp_path / "ledger.jsonl").write_bytes(
        canonical_line({"kind": "identity", "ledger_id": [], "schema_version": 1})
    )
    with pytest.raises(ValueError, match="identity"):
        read_ledger(tmp_path)


def test_canonical_bytes_preserve_unicode_without_ambiguous_spacing():
    value = {"tenant_id": "organização", "sequence": 1}
    assert json.loads(canonical_line(value)) == value
    assert canonical_line(value).endswith(b"\n")


def test_complete_durable_tail_needs_explicit_replay_before_checkpoint_advance(tmp_path):
    before = initialize_files(tmp_path)
    record = {
        "sequence": 1,
        "tenant_id": "tenant",
        "evidence_id": "source",
        "object_key": None,
        "deleted_at": "2026-09-21T00:00:00+00:00",
    }
    path = tmp_path / "ledger.jsonl"
    with path.open("ab") as stream:
        stream.write(canonical_line(record))
    with pytest.raises(ValueError, match="checkpoint"):
        read_ledger(tmp_path)
    recovered = read_ledger(tmp_path, checkpoint_may_lag=True)
    assert recovered.records == (record,)
    assert recovered.checkpoint["sha256"] == hashlib.sha256(path.read_bytes()).hexdigest()
    assert json.loads((tmp_path / "checkpoint.json").read_text()) == before.checkpoint
