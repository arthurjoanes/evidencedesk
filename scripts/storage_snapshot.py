"""Container-side file operations. Application admission must already be drained."""

import argparse
import hashlib
import json
import shutil
import sys
import tarfile
from pathlib import Path, PurePosixPath

MAX_FILES = 50_000
MAX_BYTES = 4 * 1024**3


def safe_relative(value: str) -> Path:
    path = PurePosixPath(value)
    if (
        not value
        or path.is_absolute()
        or any(part in {"", ".", ".."} for part in value.split("/"))
        or "\\" in value
        or ":" in value
    ):
        raise ValueError("Unsafe archive path.")
    return Path(*path.parts)


def file_digest(path: Path) -> str:
    with path.open("rb") as stream:
        return hashlib.file_digest(stream, "sha256").hexdigest()


def object_path(root: Path, key: str) -> Path:
    """A regular leaf is insufficient: an ancestor may redirect outside the volume."""
    relative = safe_relative(key)
    path = root / relative
    current = root
    for part in (None, *relative.parts):
        if part is not None:
            current /= part
        if current.is_symlink():
            raise ValueError("Symbolic links cannot be backed up.")
    if not path.resolve().is_relative_to(root.resolve()):
        raise ValueError("Object resolves outside the private volume.")
    return path


def snapshot(root: Path, output, references: list[dict] | None = None):
    total = count = 0
    if references is not None:
        verify_references(root, references)
        paths = sorted({object_path(root, item["object_key"]) for item in references})
    else:
        paths = sorted(root.rglob("*"))
    with tarfile.open(fileobj=output, mode="w|") as archive:
        for path in paths:
            if path.is_symlink():
                raise ValueError("Symbolic links cannot be backed up.")
            if path.is_dir():
                continue
            if not path.is_file():
                raise ValueError("Only regular objects can be backed up.")
            total += path.stat().st_size
            count += 1
            if count > MAX_FILES or total > MAX_BYTES:
                raise ValueError("Snapshot exceeds the local backup budget.")
            name = path.relative_to(root).as_posix()
            safe_relative(name)
            archive.add(path, arcname=name, recursive=False)


def inspect_archive(archive_path: Path) -> list[dict]:
    entries = []
    names = set()
    total = 0
    with tarfile.open(archive_path, mode="r:") as archive:
        for member in archive:
            safe_relative(member.name)
            if not member.isfile() or member.name in names:
                raise ValueError("Duplicate or non-regular archive entry.")
            names.add(member.name)
            total += member.size
            if len(names) > MAX_FILES or total > MAX_BYTES:
                raise ValueError("Snapshot exceeds the local restore budget.")
            source = archive.extractfile(member)
            if source is None:
                raise ValueError("Archive entry has no bytes.")
            with source:
                digest = hashlib.file_digest(source, "sha256").hexdigest()
            entries.append({"path": member.name, "bytes": member.size, "sha256": digest})
    return entries


def restore(root: Path, archive_path: Path):
    if any(root.iterdir()):
        raise ValueError("Restore requires an empty object volume.")
    # Complete validation precedes every filesystem write.
    inspect_archive(archive_path)
    with tarfile.open(archive_path, mode="r:") as archive:
        for member in archive:
            destination = root / safe_relative(member.name)
            destination.parent.mkdir(parents=True, exist_ok=True)
            source = archive.extractfile(member)
            with source, destination.open("xb") as output:
                shutil.copyfileobj(source, output)


def validate_ledger(path: Path):
    if not path.is_file() or path.is_symlink():
        raise ValueError("Current deletion ledger is missing.")
    if path.stat().st_size > 16 * 1024**2:
        raise ValueError("Ledger exceeds the local restore budget.")
    with path.open(encoding="utf-8") as stream:
        for line in stream:
            if not isinstance(json.loads(line), dict):
                raise ValueError("Invalid deletion ledger record.")


def verify_references(root: Path, references: list[dict]):
    for reference in references:
        path = object_path(root, reference["object_key"])
        if not path.is_file() or path.is_symlink() or file_digest(path) != reference["sha256"]:
            raise ValueError("A referenced object is missing or has a different checksum.")
    return {"verified_references": len(references)}


def main():
    cli = argparse.ArgumentParser(description=__doc__)
    cli.add_argument(
        "action",
        choices=[
            "snapshot",
            "restore",
            "ledger-export",
            "ledger-install",
            "checkpoint-export",
            "checkpoint-install",
            "verify-references",
        ],
    )
    cli.add_argument("--archive", type=Path)
    cli.add_argument("--references", type=Path)
    args = cli.parse_args()
    root, ledger = Path("/data"), Path("/ledger/ledger.jsonl")
    if args.action == "snapshot":
        references = (
            json.loads(args.references.read_text(encoding="utf-8")) if args.references else None
        )
        snapshot(root, sys.stdout.buffer, references)
    elif args.action == "restore":
        restore(root, args.archive)
    elif args.action in {"ledger-export", "checkpoint-export"}:
        if args.action == "checkpoint-export":
            ledger = ledger.with_name("checkpoint.json")
        validate_ledger(ledger)
        with ledger.open("rb") as source:
            shutil.copyfileobj(source, sys.stdout.buffer)
    elif args.action in {"ledger-install", "checkpoint-install"}:
        if args.action == "checkpoint-install":
            ledger = ledger.with_name("checkpoint.json")
        validate_ledger(args.archive)
        ledger.parent.mkdir(parents=True, exist_ok=True)
        with args.archive.open("rb") as source, ledger.open("xb") as destination:
            shutil.copyfileobj(source, destination)
    else:
        print(json.dumps(verify_references(root, json.load(sys.stdin))))


if __name__ == "__main__":
    main()
