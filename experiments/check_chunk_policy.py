"""Audit current demo chunk lengths with pinned, cached tokenizers; never opens eval gold."""

import hashlib
import json
from pathlib import Path

from evidencedesk.retrieval.chunking import (
    DOCUMENT_CHUNK_MAX_BYTES,
    DOCUMENT_CHUNK_REVISION,
    chunk_text,
)
from evidencedesk.retrieval.local_models import (
    EMBEDDING_MODEL,
    EMBEDDING_REVISION,
    RERANKER_MODEL,
    RERANKER_REVISION,
)
from transformers import AutoTokenizer


def main():
    encoder = AutoTokenizer.from_pretrained(
        EMBEDDING_MODEL,
        revision=EMBEDDING_REVISION,
        local_files_only=True,
        trust_remote_code=False,
    )
    reranker = AutoTokenizer.from_pretrained(
        RERANKER_MODEL,
        revision=RERANKER_REVISION,
        local_files_only=True,
        trust_remote_code=False,
    )
    query = "O que foi observado neste incidente e quais evidências ainda faltam?"
    paths = sorted(Path("datasets/generated").glob("*/*.md"))
    if not paths:
        raise RuntimeError("Generate the synthetic demonstration corpus first.")
    cases = [(str(path), path.read_text(encoding="utf-8")) for path in paths]
    cases.extend(
        (f"unicode-probe-{index}", content * 500)
        for index, content in enumerate(
            ("ação retenção 👩🏽‍💻\n", "ﬃ﷽", "\u0301" * 8, "東京 pagamento ")
        )
    )
    rows = []
    for name, content in cases:
        encoded = content.encode()
        entry = {
            "sha256": hashlib.sha256(encoded).hexdigest(),
            "object_key": "synthetic-probe",
            "media_type": "text/plain",
            "byte_size": len(encoded),
            "kind": "document",
            "filename": "probe.txt",
            "metadata": {},
        }
        records = [
            {"canonical_text": chunk.text}
            for chunk in chunk_text(
                content,
                lambda value: len(value.encode("utf-8")),
                max_tokens=DOCUMENT_CHUNK_MAX_BYTES,
            )
        ]
        assert "".join(row["canonical_text"] for row in records) == content
        lengths = [
            (
                len(
                    encoder.encode(
                        "passage: " + row["canonical_text"], add_special_tokens=True
                    )
                ),
                len(
                    reranker.encode(
                        query, row["canonical_text"], add_special_tokens=True
                    )
                ),
            )
            for row in records
        ]
        rows.append(
            {
                "name": name,
                "source_sha256": entry["sha256"],
                "chunks": len(records),
                "max_bytes": max(
                    len(row["canonical_text"].encode()) for row in records
                ),
                "max_e5_tokens": max(pair[0] for pair in lengths),
                "max_reranker_pair_tokens": max(pair[1] for pair in lengths),
                "over_512": sum(a > 512 or b > 512 for a, b in lengths),
            }
        )
    demo = rows[: len(paths)]
    report = {
        "chunk_policy": DOCUMENT_CHUNK_REVISION,
        "embedding_revision": EMBEDDING_REVISION,
        "reranker_revision": RERANKER_REVISION,
        "weights_loaded": False,
        "reserved_evaluation_used": False,
        "demo_documents": len(demo),
        "demo_chunks": sum(row["chunks"] for row in demo),
        "demo_over_512": sum(row["over_512"] for row in demo),
        "max_demo_e5_tokens": max(row["max_e5_tokens"] for row in demo),
        "max_demo_reranker_pair_tokens": max(
            row["max_reranker_pair_tokens"] for row in demo
        ),
        "unicode_probes_are_not_a_universal_bound": True,
        "documents": rows,
    }
    Path("/runs/chunk-policy-tokenizers.json").write_text(
        json.dumps(report, indent=2) + "\n"
    )
    print(
        json.dumps({key: value for key, value in report.items() if key != "documents"})
    )
    assert report["demo_over_512"] == 0


if __name__ == "__main__":
    main()
