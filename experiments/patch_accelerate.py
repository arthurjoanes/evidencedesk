"""Apply/verify the narrowly scoped local fix for CVE-2026-69112.

Keep upstream package metadata intact: scanners must still report their version.
Source identity fails closed so an upgrade requires an explicit patch review.
"""

from __future__ import annotations

import argparse
import hashlib
import importlib.metadata
import json
from pathlib import Path

VERSION = "1.13.0"
SOURCE_SHA256 = "d6052abc0625740115176a4d2dfc0861a189a2dba94443c09cc8500254b57e2e"
PATCH_ID = "evidencedesk-accelerate-shards-v1"
ORIGINAL = """    if index_filename is not None:
        checkpoint_folder = os.path.split(index_filename)[0]
        with open(index_filename) as f:
            index = json.loads(f.read())

        if "weight_map" in index:
            index = index["weight_map"]
        checkpoint_files = sorted(list(set(index.values())))
        checkpoint_files = [os.path.join(checkpoint_folder, f) for f in checkpoint_files]
"""
REPLACEMENT = """    if index_filename is not None:
        # evidencedesk-accelerate-shards-v1: local CVE-2026-69112 backport.
        from pathlib import Path
        import stat

        checkpoint_folder = Path(index_filename).parent.resolve(strict=True)
        index_stat = os.stat(index_filename)
        if not stat.S_ISREG(index_stat.st_mode) or index_stat.st_size > 16 * 1024 * 1024:
            raise ValueError("Checkpoint index must be a regular file of at most 16 MiB")
        with open(index_filename, encoding="utf-8") as f:
            index = json.load(f)
        if not isinstance(index, dict):
            raise ValueError("Checkpoint index must be an object")
        index = index.get("weight_map", index)
        if not isinstance(index, dict) or not index:
            raise ValueError("Checkpoint weight_map must be a nonempty object")
        if any(not isinstance(name, str) or not name for name in index.values()):
            raise ValueError("Checkpoint shard names must be nonempty strings")
        checkpoint_files = []
        for name in sorted(set(index.values())):
            if Path(name).is_absolute():
                raise ValueError("Checkpoint shard must use a relative path")
            try:
                shard = (checkpoint_folder / name).resolve(strict=True)
                if not shard.is_relative_to(checkpoint_folder):
                    raise ValueError("Checkpoint shard escapes its directory")
                if not stat.S_ISREG(shard.stat().st_mode):
                    raise ValueError("Checkpoint shard must be a regular file")
            except OSError as error:
                raise ValueError("Checkpoint shard is unavailable") from error
            checkpoint_files.append(str(shard))
"""


def patched_source(source: str) -> str:
    if hashlib.sha256(source.encode()).hexdigest() != SOURCE_SHA256:
        raise RuntimeError("Accelerate source changed; review the backport before building")
    if source.count(ORIGINAL) != 1:
        raise RuntimeError("Expected exactly one sharded-checkpoint loader")
    return source.replace(ORIGINAL, REPLACEMENT, 1)


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--check", action="store_true")
    parser.add_argument(
        "--manifest", type=Path, default=Path("/opt/evidencedesk/accelerate-patch.json")
    )
    args = parser.parse_args()
    distribution = importlib.metadata.distribution("accelerate")
    if distribution.version != VERSION:
        raise RuntimeError("Accelerate version changed; review the backport")
    target = Path(distribution.locate_file("accelerate/utils/modeling.py"))
    source = target.read_text(encoding="utf-8")
    current_hash = hashlib.sha256(target.read_bytes()).hexdigest()
    if args.check:
        manifest = json.loads(args.manifest.read_text(encoding="utf-8"))
        if (
            manifest.get("patch_id") != PATCH_ID
            or manifest.get("upstream_sha256") != SOURCE_SHA256
            or manifest.get("patched_sha256") != current_hash
            or source.count(REPLACEMENT) != 1
        ):
            raise RuntimeError("Accelerate backport integrity verification failed")
    else:
        result = patched_source(source)
        target.write_text(result, encoding="utf-8")
        args.manifest.parent.mkdir(parents=True, exist_ok=True)
        args.manifest.write_text(
            json.dumps(
                {
                    "patch_id": PATCH_ID,
                    "cve": "CVE-2026-69112",
                    "upstream_version": VERSION,
                    "upstream_sha256": SOURCE_SHA256,
                    "patched_sha256": hashlib.sha256(target.read_bytes()).hexdigest(),
                    "package_metadata_preserved": True,
                },
                indent=2,
            )
            + "\n",
            encoding="utf-8",
        )
    print(json.dumps({"patch_id": PATCH_ID, "status": "verified" if args.check else "applied"}))


if __name__ == "__main__":
    main()
