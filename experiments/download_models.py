"""Explicit public model download, pinned revisions, no provider credentials."""

import hashlib
import json
from pathlib import Path

from evidencedesk.retrieval.local_models import (
    EMBEDDING_MODEL,
    EMBEDDING_REVISION,
    RERANKER_MODEL,
    RERANKER_REVISION,
)
from huggingface_hub import snapshot_download

FILES = [
    "config.json",
    "model.safetensors",
    "modules.json",
    "1_Pooling/config.json",
    "sentence_bert_config.json",
    "sentencepiece.bpe.model",
    "special_tokens_map.json",
    "tokenizer.json",
    "tokenizer_config.json",
    "README.md",
]


def main() -> None:
    reports = []
    for model, revision in (
        (EMBEDDING_MODEL, EMBEDDING_REVISION),
        (RERANKER_MODEL, RERANKER_REVISION),
    ):
        directory = Path(
            snapshot_download(
                model,
                revision=revision,
                allow_patterns=FILES,
                max_workers=2,
                token=False,
            )
        )
        files = []
        for path in sorted(directory.rglob("*")):
            if path.is_file():
                digest = hashlib.sha256()
                with path.open("rb") as stream:
                    for block in iter(lambda: stream.read(1024 * 1024), b""):
                        digest.update(block)
                files.append(
                    {
                        "path": str(path.relative_to(directory)),
                        "bytes": path.stat().st_size,
                        "sha256": digest.hexdigest(),
                    }
                )
        reports.append({"model": model, "revision": revision, "files": files})
        print(
            json.dumps(
                {
                    "model": model,
                    "revision": revision,
                    "files": len(files),
                    "status": "downloaded_and_hashed",
                }
            ),
            flush=True,
        )
    Path("/runs/download-manifest.json").write_text(
        json.dumps(reports, indent=2) + "\n"
    )


if __name__ == "__main__":
    main()
