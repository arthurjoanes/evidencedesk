"""Export small, synthetic experiment evidence. Model weights stay in Docker volumes."""

import hashlib
import json
import shutil
from pathlib import Path

FILES = (
    "preflight.json",
    "download-manifest.json",
    "model-service-smoke.json",
    "chunk-policy-tokenizers.json",
    "candidate-files.json",
    "environment-check-previous.json",
    "environment-check-locked.json",
    "model-service-smoke-locked.json",
    "retrieval-dev.json",
    "retrieval-dev-lexical-v2.json",
    "reranker-comparison.json",
    "reranker-comparison-lexical-v2.json",
)


def main():
    source, target = Path("/runs"), Path("/reports")
    target.mkdir(parents=True, exist_ok=True)
    exported = []
    for name in FILES:
        shutil.copyfile(source / name, target / name)
        exported.append(name)
    for run in sorted(source.glob("*-*")):
        if (run / "manifest.json").is_file():
            name = run.name + "-manifest.json"
            shutil.copyfile(run / "manifest.json", target / name)
            exported.append(name)
    previous = (
        json.loads((target / "index.json").read_text())
        if (target / "index.json").is_file()
        else {}
    )
    exported = list(dict.fromkeys([*previous, *exported]))
    index = {
        name: hashlib.sha256((target / name).read_bytes()).hexdigest()
        for name in exported
    }
    (target / "index.json").write_text(json.dumps(index, indent=2) + "\n")
    print(json.dumps({"exported": len(exported), "weights_exported": False}))


if __name__ == "__main__":
    main()
