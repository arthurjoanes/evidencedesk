"""Optional verified restore journey. Only the journey is read-only, not the API.

Called inside backup.verify_restore's owned source-maintenance window. Never reopen
a saved restore report independently: the deletion ledger could have advanced.
"""

import hashlib
import json
import os
import re
import socket
import subprocess
import time
from datetime import UTC, datetime
from pathlib import Path

import backup
from bounded_process import run_bounded
from ops import ROOT

SOURCE = re.compile(r"pf-evidencedesk-capacity-[a-z0-9][a-z0-9-]{0,25}\Z")
TARGET = re.compile(r"pf-evidencedesk-restore-[a-z0-9][a-z0-9-]{0,27}\Z")
IMAGE = re.compile(r"sha256:[a-f0-9]{64}\Z")
DOMAIN_TABLES = (
    "collections",
    "collection_grants",
    "evidence",
    "incidents",
    "dossiers",
    "dossier_revisions",
    "import_batches",
    "import_entries",
    "result_artifacts",
    "jobs",
    "investigation_runs",
    "revision_decisions",
    "exports",
    "evidence_snapshots",
    "snapshot_members",
    "snapshot_mappings",
    "incident_members",
)


def write_private(path, record):
    with Path(path).open("x", encoding="utf-8", newline="\n") as stream:
        json.dump(record, stream, ensure_ascii=False, indent=2)
        stream.write("\n")


def command_output(value):
    """Both text-mode Docker calls and byte-mode browser calls can fail here."""
    return value.decode("utf-8", errors="replace") if isinstance(value, bytes) else (value or "")


def runtime_sources():
    files = []
    for directory in (
        "backend/src",
        "backend/migrations",
        "frontend/src",
        "frontend/public",
        "frontend/scripts",
    ):
        files.extend(
            p for p in (ROOT / directory).rglob("*") if p.is_file() and "__pycache__" not in p.parts
        )
    files.extend(
        ROOT / name
        for name in (
            "backend/Dockerfile",
            "backend/.dockerignore",
            "backend/requirements.lock",
            "backend/pyproject.toml",
            "backend/alembic.ini",
            "frontend/Dockerfile",
            "frontend/.dockerignore",
            "frontend/package.json",
            "frontend/package-lock.json",
            "frontend/next.config.ts",
            "frontend/tsconfig.json",
        )
        if (ROOT / name).is_file()
    )
    return {
        p.relative_to(ROOT).as_posix(): hashlib.sha256(p.read_bytes()).hexdigest()
        for p in sorted(set(files))
    }


def operational_sources():
    names = [
        "scripts/ops.py",
        "scripts/backup.py",
        "scripts/restore_read_probe.py",
        "scripts/check_erasure_restore.py",
        "scripts/prepare_review_capture.py",
        "scripts/prove_restore_read.py",
        "scripts/capacity_http.py",
        "scripts/capacity_jobs.py",
        "scripts/storage_snapshot.py",
        "scripts/bounded_process.py",
        "frontend/e2e/restore-read.spec.ts",
        "frontend/playwright.config.ts",
    ]
    files = [ROOT / name for name in names]
    files.extend((ROOT / "infra/compose").glob("*.yaml"))
    return {
        p.relative_to(ROOT).as_posix(): hashlib.sha256(p.read_bytes()).hexdigest()
        for p in sorted(files)
    }


def runtime_proof(path):
    """Require a build/source association recorded by the build operator, not a mutable tag."""
    record = json.loads(backup.outside_repository(Path(path)).read_text(encoding="utf-8"))
    if (
        record.get("kind") != "local-build-source-proof"
        or record.get("source_files") != runtime_sources()
        or set(record.get("images", {})) != {"api", "frontend"}
        or any(
            not isinstance(value, str) or not IMAGE.fullmatch(value)
            for value in record["images"].values()
        )
    ):
        raise ValueError("A matching frozen source/build proof for both images is required.")
    return record


def validate_gate(record, target_state, source_state):
    validate_namespaces(record)
    references = record.get("objects", {}).get("verified_references")
    if (
        record.get("status") != "passed"
        or record.get("target_opened") is not False
        or type(references) is not int
        or references < 1
        or not re.fullmatch(r"[a-f0-9]{64}", record.get("current_ledger_sha256", ""))
    ):
        raise ValueError("Restore objects and current ledger must be verified before opening.")
    for state in (record.get("reconciliation", {}), target_state, source_state):
        if (
            state.get("maintenance") is not True
            or state.get("ledger_ready") is not True
            or state.get("drained") is not True
            or state.get("active_jobs") != 0
            or state.get("active_uploads") != 0
        ):
            raise ValueError("Both owned maintenance windows must remain drained and ready.")


def validate_namespaces(record):
    if (
        not SOURCE.fullmatch(record.get("source_project", ""))
        or not TARGET.fullmatch(record.get("target_project", ""))
        or record["source_project"] == record["target_project"]
    ):
        raise ValueError("Only separate isolated source/restore namespaces are allowed.")


def new_private_directory(path):
    path = backup.outside_repository(Path(path))
    path.mkdir(parents=True, exist_ok=False, mode=0o700)
    if os.name == "nt":
        script = r"""
$ErrorActionPreference='Stop'
$path=$env:ED_RESTORE_PRIVATE_DIR
$owner=[System.Security.Principal.WindowsIdentity]::GetCurrent().User
$system=[System.Security.Principal.SecurityIdentifier]::new('S-1-5-18')
$acl=[System.Security.AccessControl.DirectorySecurity]::new()
$acl.SetOwner($owner); $acl.SetAccessRuleProtection($true,$false)
foreach($sid in @($owner,$system)) {
 $acl.AddAccessRule([System.Security.AccessControl.FileSystemAccessRule]::new(
   $sid,'FullControl','ContainerInherit,ObjectInherit','None','Allow'))
}
[System.IO.Directory]::SetAccessControl($path,$acl)
$actual=[System.IO.Directory]::GetAccessControl($path)
$rules=@($actual.GetAccessRules($true,$true,[System.Security.Principal.SecurityIdentifier]))
if(!$actual.AreAccessRulesProtected -or $rules.Count -ne 2){throw 'Private directory ACL failed'}
foreach($rule in $rules){
 if($rule.IdentityReference.Value -notin @($owner.Value,$system.Value) -or
    $rule.AccessControlType -ne 'Allow'){throw 'Unexpected private directory principal'}
}
"""
        subprocess.run(
            ["powershell", "-NoProfile", "-NonInteractive", "-Command", script],
            env={**os.environ, "ED_RESTORE_PRIVATE_DIR": str(path)},
            capture_output=True,
            check=True,
            timeout=30,
        )
    else:
        path.chmod(0o700)
    return path


def free_ports():
    sockets = [socket.socket(), socket.socket()]
    try:
        for listener in sockets:
            listener.bind(("127.0.0.1", 0))
        return tuple(listener.getsockname()[1] for listener in sockets)
    finally:
        for listener in sockets:
            listener.close()


def override_text(api_port, frontend_port, images):
    if (
        any(
            type(port) is not int or not 1024 <= port <= 65535 for port in (api_port, frontend_port)
        )
        or api_port == frontend_port
        or set(images) != {"api", "frontend"}
        or any(not IMAGE.fullmatch(image) for image in images.values())
    ):
        raise ValueError("Two distinct loopback ports and immutable image IDs are required.")
    return f"""services:
  db:
    ports: !reset []
  api:
    image: {images["api"]}
    ports: !override ["127.0.0.1:{api_port}:8106"]
    environment:
      ED_AI_PROVIDER: disabled
      AZURE_OPENAI_API_KEY: ""
      AZURE_OPENAI_BASE_URL: ""
      AZURE_OPENAI_DEPLOYMENT: ""
      ED_RETRIEVAL_MODE: lexical
      ED_MODEL_SERVICE_TOKEN: ""
      OTEL_EXPORTER_OTLP_ENDPOINT: ""
      ED_ALLOWED_ORIGINS: http://127.0.0.1:{frontend_port}
      ED_COOKIE_SECURE: "false"
  frontend:
    image: {images["frontend"]}
    profiles: !reset []
    ports: !override ["127.0.0.1:{frontend_port}:3106"]
  worker:
    profiles: !override [disabled-in-restore-read]
  models:
    profiles: !override [disabled-in-restore-read]
"""


def project_containers(project):
    if not TARGET.fullmatch(project):
        raise ValueError("Refusing to inspect or stop a foreign project.")
    ids = backup.run(
        [
            "docker",
            "ps",
            "--quiet",
            "--filter",
            "label=com.docker.compose.project=" + project,
        ],
        capture=True,
    ).split()
    if any(not re.fullmatch(r"[a-f0-9]{12,64}", value) for value in ids):
        raise ValueError("Invalid scoped container identity.")
    return ids


def service_inventory(project):
    rows = []
    for identifier in project_containers(project):
        raw = json.loads(backup.run(["docker", "inspect", identifier], capture=True))[0]
        rows.append(
            {
                "id": raw["Id"],
                "image": raw["Image"],
                "service": raw["Config"]["Labels"]["com.docker.compose.service"],
                "ports": raw["NetworkSettings"]["Ports"],
            }
        )
    return rows  # Never record Config.Env or other credentials from inspect.


def validate_services(rows, images, api_port, frontend_port):
    if len(rows) != 3 or {r["service"] for r in rows} != {"db", "api", "frontend"}:
        raise ValueError("Only database, API and frontend may run during restore reading.")
    for row in rows:
        expected = (
            {"8106/tcp": api_port}
            if row["service"] == "api"
            else {"3106/tcp": frontend_port}
            if row["service"] == "frontend"
            else {}
        )
        bound = {key: value for key, value in row["ports"].items() if value}
        if set(bound) != set(expected):
            raise ValueError("Unexpected published restore port.")
        if row["service"] in images and row["image"] != images[row["service"]]:
            raise ValueError("Running image differs from the frozen source proof.")
        for container_port, host_port in expected.items():
            if bound[container_port] != [{"HostIp": "127.0.0.1", "HostPort": str(host_port)}]:
                raise ValueError("Restore binding is not the requested loopback endpoint.")


def stop_target(project):
    with backup.command_budget(45, cleanup=True):
        ids = project_containers(project)
        if ids:
            backup.run(["docker", "stop", "--time", "10", *ids])
        if project_containers(project):
            raise RuntimeError("Restore containers remain active after cleanup.")


def database_snapshot(base):
    def row_digest(table):
        # Hash each row before aggregation: canonical_text remains per-row, not
        # one unbounded JSON document containing the entire restored corpus.
        return (
            "(SELECT encode(sha256(convert_to(coalesce(string_agg(row_hash,'' "
            "ORDER BY row_hash),''),'UTF8')),'hex') FROM (SELECT "
            "encode(sha256(convert_to(to_jsonb(t)::text,'UTF8')),'hex') row_hash "
            f"FROM {table} t) hashed_rows)"
        )

    terms = [f"'{table}',{row_digest(table)}" for table in DOMAIN_TABLES]
    terms += [
        "'provider_calls',(SELECT count(*) FROM provider_calls)",
        f"'provider_call_rows',{row_digest('provider_calls')}",
        "'ledger',(SELECT jsonb_build_object('ledger_id',ledger_id,'sequence',sequence,'sha256',sha256) FROM operational_ledger WHERE id=1)",
    ]
    statement = "SELECT jsonb_build_object(" + ",".join(terms) + ")"
    result = backup.run(
        base
        + [
            "exec",
            "-T",
            "db",
            "psql",
            "-v",
            "ON_ERROR_STOP=1",
            "-U",
            "postgres",
            "-d",
            "evidencedesk",
            "-At",
            "-c",
            statement,
        ],
        capture=True,
    )
    return json.loads(result)


def browser_proof(directory, case, expected_url):
    record = json.loads((directory / "restore-read-proof.json").read_text(encoding="utf-8"))
    if (
        record.get("status") != "passed"
        or record.get("base_url") != expected_url
        or any(
            record.get(key) != case[key] for key in ("run_id", "target_project", "ledger_sequence")
        )
        or record.get("generation_post_attempts") != []
        or record.get("blocked_requests") != []
    ):
        raise ValueError("Browser proof is absent, failed or belongs to another restore.")
    return record


class ReadJourney:
    """Single-use callback for verify_restore; the source remains closed until it returns."""

    def __init__(self, source_base, case, artifacts, build_proof):
        self.source_base = source_base
        self.case = case
        self.directory = new_private_directory(artifacts)
        frozen = runtime_proof(build_proof)
        self.images = frozen["images"]
        self.runtime_files = frozen["source_files"]
        self.build_proof_sha256 = hashlib.sha256(Path(build_proof).read_bytes()).hexdigest()
        self.used = False

    def __call__(self, *, base, manifest, record):
        if self.used:
            raise ValueError("Restore read callback cannot be replayed.")
        self.used = True
        started = time.monotonic()
        result = {
            "status": "running",
            "started_at": datetime.now(UTC).isoformat(),
            "journey_only_read_only": True,
            "api_is_read_only": False,
            "volumes_preserved": True,
            "target_closed": False,
            "build_proof_sha256": self.build_proof_sha256,
            "domain_tables_checked": list(DOMAIN_TABLES),
            "excluded_from_domain_equality": [
                "sessions",
                "login_limits",
                "audit_events",
                "operational_control",
                "worker_heartbeats",
                "stream_leases",
            ],
        }
        target = record.get("target_project")
        ownership_confirmed = False
        released_target = False
        try:
            with backup.command_budget(240):
                if runtime_sources() != self.runtime_files:
                    raise ValueError("Runtime sources changed since build-proof validation.")
                validate_namespaces(record)
                if (
                    self.source_base[self.source_base.index("--project-name") + 1]
                    != record["source_project"]
                ):
                    raise ValueError("Compose source differs from the verified restore.")
                validate_gate(
                    record,
                    backup.maintenance(base, "status"),
                    backup.maintenance(self.source_base, "status"),
                )
                if base[base.index("--project-name") + 1] != target:
                    raise ValueError("Compose target differs from the verified restore.")
                existing = service_inventory(target)
                if len(existing) != 1 or existing[0]["service"] != "db":
                    raise ValueError("Restore must still have only its closed database running.")
                ownership_confirmed = True
                result["operational_sources"] = operational_sources()
                before = database_snapshot(self.source_base)
                target_before = database_snapshot(base)
                if before["provider_calls"] != 0 or target_before["provider_calls"] != 0:
                    raise ValueError("Only a source and restore without provider calls may open.")
                if target_before["ledger"] != before["ledger"]:
                    raise ValueError(
                        "The target checkpoint differs from the held source checkpoint."
                    )
                api_port, frontend_port = free_ports()
                override = self.directory / "restore-read.yaml"
                override.write_text(
                    override_text(api_port, frontend_port, self.images),
                    encoding="utf-8",
                    newline="\n",
                )
                opened = base + ["--file", str(override)]
                backup.run(opened + ["config", "--quiet"])
                state = backup.maintenance(base, "leave", "--token", manifest["maintenance_token"])
                if state.get("maintenance") is not False or state.get("ledger_ready") is not True:
                    raise ValueError("Target did not leave owned maintenance with a ready ledger.")
                released_target = True
                backup.run(
                    opened
                    + [
                        "up",
                        "-d",
                        "--wait",
                        "--wait-timeout",
                        "90",
                        "--no-deps",
                        "--no-build",
                        "--pull",
                        "never",
                        "api",
                        "frontend",
                    ]
                )
                inventory = service_inventory(target)
                validate_services(inventory, self.images, api_port, frontend_port)
                case = {
                    **self.case,
                    "target_project": target,
                    "ledger_sequence": record["reconciliation"]["ledger_sequence"],
                }
                case_path = self.directory / "restore-case.json"
                write_private(case_path, case)
                result.update(
                    services=inventory,
                    frontend_url=f"http://127.0.0.1:{frontend_port}",
                    verified_before_open=record["recorded_at"],
                    ready_after_seconds=round(time.monotonic() - started, 3),
                )
                environment = {
                    **os.environ,
                    "ED_RESTORE_CASE_PATH": str(case_path),
                    "ED_E2E_BASE_URL": result["frontend_url"],
                    "ED_E2E_ARTIFACT_DIR": str(self.directory),
                    "ED_REVIEW_CAPTURE_ALLOW_WRITE": "0",
                }
                environment.pop("ED_REVIEW_CAPTURE_CASE_PATH", None)
                browser_result = run_bounded(
                    [
                        "node",
                        str(ROOT / "frontend/node_modules/@playwright/test/cli.js"),
                        "test",
                        "restore-read.spec.ts",
                        "--grep",
                        "restore read:",
                    ],
                    cwd=ROOT / "frontend",
                    env=environment,
                    timeout=backup.command_timeout(120),
                )
                write_private(
                    self.directory / "browser-command.json",
                    {
                        "exit_code": browser_result.returncode,
                        "stdout": browser_result.stdout.decode("utf-8", errors="replace"),
                        "stderr": browser_result.stderr.decode("utf-8", errors="replace"),
                    },
                )
                backup.command_timeout()
                browser = browser_proof(self.directory, case, result["frontend_url"])
                after = database_snapshot(self.source_base)
                target_after = database_snapshot(base)
                if before != after:
                    raise ValueError("Source domain or deletion checkpoint changed during reading.")
                if target_before["provider_calls"] != target_after["provider_calls"]:
                    raise ValueError("The restored read journey admitted a provider call.")
                if target_before != target_after:
                    raise ValueError(
                        "Restored domain or deletion checkpoint changed during reading."
                    )
                if operational_sources() != result["operational_sources"]:
                    raise ValueError("Operational sources changed during the restore journey.")
                if runtime_sources() != self.runtime_files:
                    raise ValueError("Runtime sources changed during the restore journey.")
                backup.command_timeout()
                result.update(
                    source_domain_preserved=True,
                    provider_calls_before=target_before["provider_calls"],
                    provider_calls_after=target_after["provider_calls"],
                    provider_calls_delta=0,
                    target_domain_preserved=True,
                    source_snapshot=before,
                    target_ledger=target_after["ledger"],
                    browser_proof_sha256=hashlib.sha256(
                        (self.directory / "restore-read-proof.json").read_bytes()
                    ).hexdigest(),
                    browser_run_id=browser["run_id"],
                    source_unchanged=True,
                    status="passed",
                )
        except BaseException as error:
            result.update(status="failed", error_type=type(error).__name__)
            if isinstance(error, subprocess.SubprocessError):
                result["browser_tree_cleanup_complete"] = getattr(error, "cleanup_complete", None)
                write_private(
                    self.directory / "command-failure-private.json",
                    {
                        "stdout": command_output(getattr(error, "output", None)),
                        "stderr": command_output(getattr(error, "stderr", None)),
                    },
                )
            raise
        finally:
            try:
                if ownership_confirmed:
                    try:
                        if released_target:
                            with backup.command_budget(45, cleanup=True):
                                closed = backup.maintenance(
                                    base,
                                    "enter",
                                    "--timeout",
                                    "30",
                                    error_output=self.directory
                                    / "target-maintenance-failure-private.json",
                                )
                                if (
                                    closed.get("maintenance") is not True
                                    or closed.get("ledger_ready") is not True
                                    or closed.get("drained") is not True
                                ):
                                    raise ValueError("Target maintenance did not close safely.")
                                # This ownership token is intentionally private, for inspection.
                                write_private(
                                    self.directory / "target-maintenance-private.json",
                                    closed,
                                )
                                result["target_maintenance_reclosed"] = True
                    finally:
                        stop_target(target)
                        result["target_closed"] = True
            except BaseException as error:
                result.update(status="failed", cleanup_error_type=type(error).__name__)
                raise
            finally:
                result.update(
                    completed_at=datetime.now(UTC).isoformat(),
                    total_seconds=round(time.monotonic() - started, 3),
                )
                write_private(self.directory / "read-window.json", result)
        return result
