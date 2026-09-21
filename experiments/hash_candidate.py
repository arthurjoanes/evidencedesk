"""Record a trained candidate's files without exporting weights or loading a model."""

import argparse
import hashlib
import json
from pathlib import Path


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--run", required=True, type=Path)
    args = parser.parse_args()
    directory = args.run / "candidate"
    weights = directory / "model.safetensors"
    if not weights.is_file():
        raise ValueError("Candidate safetensors checkpoint is missing.")
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
    report = {
        "run": args.run.name,
        "status": "trained_not_promoted",
        "files": files,
        "weights_exported": False,
        "signature": "unsigned_local_hash_inventory",
    }
    (args.run.parent / "candidate-files.json").write_text(
        json.dumps(report, indent=2) + "\n"
    )
    print(
        json.dumps(
            {
                "run": args.run.name,
                "files_hashed": len(files),
                "weights_exported": False,
            }
        )
    )


if __name__ == "__main__":
    main()
