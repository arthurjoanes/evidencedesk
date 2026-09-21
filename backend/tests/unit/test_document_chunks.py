import json

from evidencedesk.ingestion.processing import DOCUMENT_CHUNK_REVISION, evidence_records


def test_document_chunk_policy_preserves_unicode_offsets_and_all_characters():
    content = "Evidência: ação, retenção, pagamento. 👩🏽‍💻 ﷽ ﬃ\n\n" * 180 + " \n  "
    entry = {
        "sha256": "a" * 64,
        "object_key": "fixture/document.txt",
        "media_type": "text/plain",
        "byte_size": len(content.encode()),
        "kind": "document",
        "filename": "document.txt",
        "metadata": {"document_lineage": "fixture-v2"},
    }
    records = evidence_records("tenant", "collection", entry, {"pages": [content]})
    assert "".join(row["canonical_text"] for row in records) == content
    assert len(records) > 20
    assert len({row["id"] for row in records}) == len(records)
    for row in records:
        locator, record = json.loads(row["locator"]), json.loads(row["record"])
        assert content[locator["char_start"] : locator["char_end"]] == row["canonical_text"]
        assert len(row["canonical_text"].encode()) <= 352
        assert record["chunk_policy"] == DOCUMENT_CHUNK_REVISION
        assert record["token_count"] is None  # byte policy must not pretend to measure tokens


def test_document_chunk_revision_changes_identity_without_changing_existing_sources():
    from hashlib import sha256

    content = "Evidência curta."
    entry = {
        "sha256": "b" * 64,
        "object_key": "fixture/doc",
        "media_type": "text/plain",
        "byte_size": len(content.encode()),
        "kind": "document",
        "filename": "doc",
        "metadata": {},
    }
    row = evidence_records("tenant", "collection", entry, {"pages": [content]})[0]
    old_identity = (
        "ev_"
        + sha256(
            f"collection:{entry['sha256']}:document:parser-v1:1:0:{len(content)}".encode()
        ).hexdigest()[:32]
    )
    assert row["id"] != old_identity
