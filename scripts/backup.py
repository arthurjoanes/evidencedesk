"""Consistent local backup and closed, isolated restore verification."""

import argparse
import contextlib
import contextvars
import json
import re
import subprocess
import sys
import tempfile
import time
from datetime import UTC, datetime
from pathlib import Path
from uuid import uuid4

from ops import ROOT, compose_command, project_name
from ops import run as ops_run
from storage_snapshot import file_digest, inspect_archive

RESTORE_OVERRIDE = ROOT / "infra/compose/restore.yaml"
_DEADLINE = contextvars.ContextVar("backup_deadline", default=None)
REFERENCES_SQL = """
SELECT COALESCE(json_agg(ref), '[]') FROM (
  SELECT object_key, sha256 FROM import_entries WHERE object_key IS NOT NULL
  UNION SELECT original_key AS object_key, sha256 FROM evidence
    WHERE original_key IS NOT NULL AND tombstoned_at IS NULL
  UNION SELECT object_key, sha256 FROM exports WHERE object_key IS NOT NULL
  UNION SELECT result_key AS object_key, result_sha256 AS sha256 FROM result_artifacts
  UNION SELECT manifest_key AS object_key, manifest_sha256 AS sha256 FROM result_artifacts
) ref;
"""


@contextlib.contextmanager
def command_budget(seconds, *, cleanup=False):
    """Bound a probe/operation; cleanup uses its own explicit reserved budget."""
    if not 1 <= seconds <= 900:
        raise ValueError("Operation budget must be between 1 and 900 seconds.")
    deadline = time.monotonic() + seconds
    if not cleanup and _DEADLINE.get() is not None:
        deadline = min(deadline, _DEADLINE.get())
    token = _DEADLINE.set(deadline)
    try:
        yield
    finally:
        _DEADLINE.reset(token)


def command_timeout(maximum=180):
    remaining = maximum if _DEADLINE.get() is None else _DEADLINE.get() - time.monotonic()
    if remaining <= 0:
        raise TimeoutError("Operation exceeded its reserved execution window.")
    return min(maximum, remaining)


def run(command, *, capture=False):
    # Parse ownership tokens before any post-command deadline rejection, so finally
    # can release an enter that succeeded immediately before the deadline.
    return ops_run(command, capture=capture, timeout=command_timeout())


def maintenance(base, action, *extra, error_output=None):
    arguments = iter(extra)
    # URL-safe random ownership tokens can begin with '-'. Bind the value explicitly.
    flags = [f"--token={next(arguments)}" if value == "--token" else value for value in arguments]
    command = base + [
        "run",
        "--rm",
        "--no-deps",
        "-T",
        "api",
        "python",
        "-m",
        "evidencedesk.maintenance",
        action,
        *flags,
    ]
    try:
        output = run(command, capture=True)
    except subprocess.SubprocessError as error:
        # A timed-out enter returns its ownership token for explicit operator recovery.
        if error.stdout:
            value = (
                error.stdout.decode("utf-8", errors="replace")
                if isinstance(error.stdout, bytes)
                else error.stdout
            )
            if error_output is not None:
                with Path(error_output).open("x", encoding="utf-8", newline="\n") as stream:
                    stream.write(value)
            else:
                print(value, file=sys.stderr)
        raise ValueError(f"Maintenance {action} failed ({type(error).__name__}).") from None
    value = json.loads(output)
    if not isinstance(value, dict):
        raise TypeError("Invalid maintenance response.")
    return value


def acquire_maintenance(base):
    if maintenance(base, "status").get("maintenance") is not False:
        raise ValueError("Another operation owns maintenance; it will not be changed.")
    state = maintenance(base, "enter", "--timeout", "60")
    if (
        state.get("maintenance") is not True
        or state.get("drained") is not True
        or state.get("active_jobs") != 0
        or state.get("ledger_ready") is not True
        or not isinstance(state.get("maintenance_token"), str)
    ):
        raise ValueError("Maintenance did not drain safely. It remains enabled for inspection.")
    return state["maintenance_token"]


def helper(base, action, mount=None):
    command = base + [
        "run",
        "--rm",
        "--no-deps",
        "-T",
        "-v",
        f"{ROOT / 'scripts'}:/ops:ro",
    ]
    if mount:
        command += ["-v", f"{mount}:/backup:ro"]
    return command + ["api", "python", "/ops/storage_snapshot.py", action]


def binary_file(command, destination):
    with destination.open("xb") as stream:
        subprocess.run(command, cwd=ROOT, stdout=stream, check=True, timeout=command_timeout())
        command_timeout()


def outside_repository(path):
    result = path.resolve()
    if result.is_relative_to(ROOT) or "onedrive" in str(result).casefold():
        raise ValueError("Private backups must be outside the repository and OneDrive.")
    return result


def create_backup(base, output, project):
    output = outside_repository(output)
    output.mkdir(parents=True, exist_ok=False)
    started = time.monotonic()
    token = acquire_maintenance(base)
    try:
        binary_file(
            base
            + [
                "exec",
                "-T",
                "db",
                "pg_dump",
                "-U",
                "postgres",
                "-d",
                "evidencedesk",
                "--format=custom",
            ],
            output / "database.dump",
        )
        references = run(
            base
            + [
                "exec",
                "-T",
                "db",
                "psql",
                "-U",
                "postgres",
                "-d",
                "evidencedesk",
                "-At",
                "-c",
                REFERENCES_SQL,
            ],
            capture=True,
        )
        (output / "references.json").write_text(
            json.dumps(json.loads(references), ensure_ascii=False),
            encoding="utf-8",
            newline="\n",
        )
        binary_file(
            helper(base, "snapshot", output) + ["--references", "/backup/references.json"],
            output / "objects.tar",
        )
        objects = inspect_archive(output / "objects.tar")
        manifest = {
            "schema_version": 1,
            "project": project,
            "created_at": datetime.now(UTC).isoformat(),
            "elapsed_seconds": round(time.monotonic() - started, 3),
            "maintenance_drained": True,
            "maintenance_token": token,
            "files": {
                name: {
                    "sha256": file_digest(output / name),
                    "bytes": (output / name).stat().st_size,
                }
                for name in ["database.dump", "objects.tar", "references.json"]
            },
            "objects": objects,
            "ledger": "Excluded intentionally; restore must acquire the current independent ledger.",
        }
        (output / "manifest.json").write_text(
            json.dumps(manifest, ensure_ascii=False, indent=2) + "\n",
            encoding="utf-8",
            newline="\n",
        )
        return {
            "backup": str(output),
            "files": len(objects),
            "elapsed_seconds": manifest["elapsed_seconds"],
        }
    finally:
        with command_budget(60, cleanup=True):
            maintenance(base, "leave", "--token", token)


def verify_backup(directory):
    directory = directory.resolve(strict=True)
    manifest = json.loads((directory / "manifest.json").read_text(encoding="utf-8"))
    if (
        not isinstance(manifest, dict)
        or type(manifest.get("schema_version")) is not int
        or manifest.get("schema_version") != 1
        or manifest.get("maintenance_drained") is not True
        or not isinstance(manifest.get("maintenance_token"), str)
        or not manifest.get("maintenance_token")
        or not isinstance(manifest.get("files"), dict)
        or set(manifest.get("files", {})) != {"database.dump", "objects.tar", "references.json"}
    ):
        raise ValueError("Unsupported or incomplete backup manifest.")
    for name, entry in manifest["files"].items():
        if (
            not isinstance(entry, dict)
            or type(entry.get("bytes")) is not int
            or entry["bytes"] < 0
            or not isinstance(entry.get("sha256"), str)
            or re.fullmatch(r"[a-f0-9]{64}", entry["sha256"]) is None
        ):
            raise ValueError("Invalid backup file metadata.")
        path = directory / name
        if (
            path.is_symlink()
            or path.stat().st_size != entry["bytes"]
            or file_digest(path) != entry["sha256"]
        ):
            raise ValueError("Backup checksum or size mismatch.")
    if inspect_archive(directory / "objects.tar") != manifest.get("objects"):
        raise ValueError("Object manifest differs from the archive.")
    return manifest


def target_is_new(project):
    for kind in ["container", "volume", "network"]:
        arguments = ["docker", kind, "ls"]
        if kind == "container":
            arguments.append("--all")
        arguments += [
            "--filter",
            f"label=com.docker.compose.project={project}",
            "--format",
            "{{.Name}}" if kind == "volume" else "{{.ID}}",
        ]
        if run(arguments, capture=True).strip():
            raise ValueError("Restore target already has resources; refusing to reuse it.")


def verify_restore(source, args, *, verified_probe=None, target_claimed=None):
    directory = outside_repository(args.backup).resolve(strict=True)
    manifest = verify_backup(directory)
    if manifest["project"] != args.project:
        raise ValueError("Backup does not belong to the selected source project.")
    target = args.target or f"pf-evidencedesk-restore-{uuid4().hex[:10]}"
    if (
        not re.fullmatch(r"pf-evidencedesk-restore-[a-z0-9][a-z0-9-]{0,27}", target)
        or target == args.project
    ):
        raise ValueError(
            "Restore target must use a separate pf-evidencedesk-restore-<id> namespace."
        )
    target_is_new(target)
    target_args = argparse.Namespace(project=target, env_file=args.env_file, observability=False)
    base = compose_command(target_args) + ["--file", str(RESTORE_OVERRIDE)]
    started = time.monotonic()
    source_token = acquire_maintenance(source)
    try:
        with tempfile.TemporaryDirectory(prefix="ed-restore-", dir=directory.parent) as temporary:
            temporary = Path(temporary)
            # Freeze the source through reconciliation; no deletion can race this copy.
            binary_file(helper(source, "ledger-export"), temporary / "ledger.jsonl")
            binary_file(helper(source, "checkpoint-export"), temporary / "checkpoint.json")
            if target_claimed is not None:
                # The caller may retry scoped cleanup even if this operation fails.
                # This notification is never sent for a rejected existing target.
                target_claimed(base)
            run(base + ["up", "-d", "--wait", "--wait-timeout", "90", "db"])
            with (directory / "database.dump").open("rb") as dump:
                subprocess.run(
                    base
                    + [
                        "exec",
                        "-T",
                        "db",
                        "pg_restore",
                        "-U",
                        "postgres",
                        "-d",
                        "evidencedesk",
                        "--clean",
                        "--if-exists",
                        "--exit-on-error",
                    ],
                    cwd=ROOT,
                    stdin=dump,
                    check=True,
                    timeout=command_timeout(),
                )
                command_timeout()
            run(helper(base, "restore", directory) + ["--archive", "/backup/objects.tar"])
            run(helper(base, "ledger-install", temporary) + ["--archive", "/backup/ledger.jsonl"])
            run(
                helper(base, "checkpoint-install", temporary)
                + ["--archive", "/backup/checkpoint.json"]
            )
            reconciliation = maintenance(
                base,
                "reconcile-ledger",
                "--restore-mode",
                "--token",
                manifest["maintenance_token"],
                "--ledger-root",
                "/ledger",
            )
            references = run(
                base
                + [
                    "exec",
                    "-T",
                    "db",
                    "psql",
                    "-U",
                    "postgres",
                    "-d",
                    "evidencedesk",
                    "-At",
                    "-c",
                    REFERENCES_SQL,
                ],
                capture=True,
            )
            checked = subprocess.run(
                helper(base, "verify-references"),
                input=references,
                cwd=ROOT,
                check=True,
                text=True,
                encoding="utf-8",
                capture_output=True,
                timeout=command_timeout(),
            )
            command_timeout()
            status = maintenance(base, "status")
            if status.get("maintenance") is not True or status.get("ledger_ready") is not True:
                raise ValueError("Restored target is not closed with a reconciled ledger.")
            record = {
                "recorded_at": datetime.now(UTC).isoformat(),
                "source_project": args.project,
                "target_project": target,
                "status": "passed",
                "elapsed_seconds": round(time.monotonic() - started, 3),
                "manifest_sha256": file_digest(directory / "manifest.json"),
                "current_ledger_sha256": file_digest(temporary / "ledger.jsonl"),
                "objects": json.loads(checked.stdout),
                "reconciliation": reconciliation,
                "target_opened": False,
            }
            if verified_probe is not None:
                # The source remains owned and closed throughout the optional read journey.
                # Never reopen from a saved report after releasing the current ledger window.
                opened = verified_probe(base=base, manifest=manifest, record=record)
                if opened.get("status") != "passed" or opened.get("target_closed") is not True:
                    raise ValueError("The optional restore journey did not close safely.")
                record["target_opened"] = True
                record["read_journey"] = opened
    finally:
        # Only resources created above, with a validated namespace, are stopped.
        try:
            with command_budget(45, cleanup=True):
                run(base + ["stop"])
        finally:
            with command_budget(60, cleanup=True):
                maintenance(source, "leave", "--token", source_token)
    record["source_reopened"] = True
    record["target_stopped"] = True
    record["elapsed_seconds"] = round(time.monotonic() - started, 3)
    destination = (
        ROOT / "docs/evidence" / f"restore-{target.removeprefix('pf-evidencedesk-restore-')}.json"
    )
    destination.parent.mkdir(parents=True, exist_ok=True)
    destination.write_text(
        json.dumps(record, ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8",
        newline="\n",
    )
    return record


def main():
    cli = argparse.ArgumentParser(description=__doc__)
    cli.add_argument("--project", type=project_name, default="pf-evidencedesk")
    cli.add_argument("--env-file", type=Path)
    cli.set_defaults(observability=False)
    commands = cli.add_subparsers(dest="action", required=True)
    create = commands.add_parser("create")
    create.add_argument("output", type=Path, help="New private directory outside OneDrive.")
    restore = commands.add_parser("verify-restore")
    restore.add_argument("backup", type=Path)
    restore.add_argument("--target", type=project_name)
    args = cli.parse_args()
    try:
        base = compose_command(args)
        run(base + ["config", "--quiet"])
        result = (
            create_backup(base, args.output, args.project)
            if args.action == "create"
            else verify_restore(base, args)
        )
        print(json.dumps(result, ensure_ascii=False, indent=2))
        return 0
    except (OSError, ValueError, subprocess.CalledProcessError) as exc:
        print(f"Backup operation failed: {exc}", file=sys.stderr)
        return 1


if __name__ == "__main__":
    sys.exit(main())
