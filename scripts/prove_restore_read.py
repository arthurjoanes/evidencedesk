"""Build and prove ED01-03 in new disposable projects; keep private evidence and volumes.

Requires Docker Compose, frontend npm dependencies, a Playwright browser, and the
Python operational dependencies already installed. Does not use paid providers.
This is scripted role testing, not a human evaluation or an off-host recovery.
"""

import argparse
import hashlib
import json
import os
import re
import sys
import time
from datetime import UTC, datetime
from pathlib import Path
from uuid import uuid4

from backup import RESTORE_OVERRIDE, command_budget, target_is_new
from bounded_process import run_bounded
from capacity_http import compose
from check_erasure_restore import close_attempt
from ops import COMPOSE, ROOT, compose_command
from restore_read_probe import (
    command_output,
    free_ports,
    new_private_directory,
    operational_sources,
    runtime_sources,
    write_private,
)


def source_unchanged(before, after):
    if before != after:
        raise ValueError("Sources changed during the proof; no success can be published.")


def build_association(before, after, images):
    source_unchanged(before, after)
    if set(images) != {"api", "frontend"} or any(
        not re.fullmatch(r"sha256:[a-f0-9]{64}", image) for image in images.values()
    ):
        raise ValueError("Build outputs must be immutable image IDs for both services.")
    return {"kind": "local-build-source-proof", "source_files": before, "images": images}


def seed_input_sources():
    files = [ROOT / "infra/init.sql"]
    files.extend(path for path in (ROOT / "datasets/generated").rglob("*") if path.is_file())
    if len(files) < 2 or any(path.is_symlink() for path in files):
        raise ValueError("A real generated corpus and regular initialization files are required.")
    return {
        path.relative_to(ROOT).as_posix(): hashlib.sha256(path.read_bytes()).hexdigest()
        for path in sorted(files)
    }


def main():
    cli = argparse.ArgumentParser(description=__doc__)
    cli.add_argument(
        "--artifacts", required=True, type=Path, help="New directory outside repo/OneDrive."
    )
    cli.add_argument(
        "--run-id", default=uuid4().hex[:12], help="New suffix: 1-16 lowercase letters/digits."
    )
    cli.add_argument("--browser-channel", choices=("msedge", "chrome"))
    args = cli.parse_args()
    if not re.fullmatch(r"[a-z0-9]{1,16}", args.run_id):
        raise ValueError("Run ID must contain 1-16 lowercase letters/digits.")
    browser_cli = ROOT / "frontend/node_modules/@playwright/test/cli.js"
    if not browser_cli.is_file():
        raise ValueError(
            "Install the frontend's locked npm dependencies and Playwright browser first."
        )
    directory = new_private_directory(args.artifacts)
    run_id = "edread-" + args.run_id
    source = "pf-evidencedesk-capacity-" + run_id
    target = "pf-evidencedesk-restore-" + run_id
    backend_tag = "pf-evidencedesk-backend:" + run_id
    frontend_tag = "pf-evidencedesk-frontend:" + run_id
    environment = {
        **os.environ,
        "ED_BACKEND_IMAGE": backend_tag,
        "ED_CAPACITY_IMAGE": backend_tag,
        "ED_FRONTEND_IMAGE": frontend_tag,
        "ED_AI_PROVIDER": "disabled",
        "AZURE_OPENAI_API_KEY": "",
        "AZURE_OPENAI_BASE_URL": "",
        "AZURE_OPENAI_DEPLOYMENT": "",
        "ED_RETRIEVAL_MODE": "lexical",
        "ED_MODEL_SERVICE_TOKEN": "",
        "OTEL_EXPORTER_OTLP_ENDPOINT": "",
    }
    if args.browser_channel:
        environment["ED_E2E_BROWSER_CHANNEL"] = args.browser_channel
    base = compose(source)
    target_base = compose_command(
        argparse.Namespace(project=target, env_file=None, observability=False)
    ) + ["--file", str(RESTORE_OVERRIDE)]
    record = {
        "status": "running",
        "started_at": datetime.now(UTC).isoformat(),
        "source_project": source,
        "target_project": target,
        "steps": [],
        "operational_sources_before": operational_sources(),
        "human_evaluation": False,
    }
    # Work is bounded to 30 minutes; cleanup has its own reserved allowance.
    deadline = time.monotonic() + 1800
    owned = False

    def phase(name, command, maximum, *, env=None, cwd=ROOT):
        remaining = deadline - time.monotonic()
        if remaining <= 0:
            raise TimeoutError("The proof exhausted its 30-minute work window.")
        started = time.monotonic()
        try:
            result = run_bounded(
                command, cwd=cwd, env=env or environment, timeout=min(maximum, remaining)
            )
        except BaseException as error:
            write_private(
                directory / (name + "-failed-private.json"),
                {
                    "error_type": type(error).__name__,
                    "stdout": command_output(getattr(error, "output", None)),
                    "stderr": command_output(getattr(error, "stderr", None)),
                    "process_tree_cleanup_complete": getattr(error, "cleanup_complete", None),
                },
            )
            raise
        write_private(
            directory / (name + "-command.json"),
            {
                "command": command,
                "exit_code": result.returncode,
                "stdout": command_output(result.stdout),
                "stderr": command_output(result.stderr),
            },
        )
        record["steps"].append({"step": name, "seconds": round(time.monotonic() - started, 3)})
        return command_output(result.stdout).strip()

    try:
        with command_budget(30):
            target_is_new(source)
            target_is_new(target)
        before = runtime_sources()
        phase(
            "build",
            [
                "docker",
                "compose",
                "--project-name",
                source,
                "--file",
                str(COMPOSE),
                "build",
                "api",
                "frontend",
            ],
            1200,
        )
        images = {
            name: phase(
                "image-" + name, ["docker", "image", "inspect", "--format", "{{.Id}}", tag], 20
            )
            for name, tag in (("api", backend_tag), ("frontend", frontend_tag))
        }
        association = build_association(before, runtime_sources(), images)
        write_private(directory / "runtime-proof.json", association)
        record["images"] = images
        environment.update(
            ED_BACKEND_IMAGE=images["api"],
            ED_CAPACITY_IMAGE=images["api"],
            ED_FRONTEND_IMAGE=images["frontend"],
        )
        _, port = free_ports()
        frontend_url = f"http://127.0.0.1:{port}"
        environment.update(
            ED_FRONTEND_PORT=str(port), ED_ALLOWED_ORIGINS="http://localhost:3106," + frontend_url
        )
        # Reuse the existing generator/partial-data guard, in a bounded child tree.
        phase(
            "prepare-dataset",
            [
                sys.executable,
                "-c",
                "import sys; sys.path.insert(0, 'scripts'); from ops import ensure_demo_dataset; ensure_demo_dataset()",
            ],
            60,
        )
        seed_inputs = seed_input_sources()
        write_private(directory / "seed-inputs-before.json", seed_inputs)
        phase("config", base + ["config", "--quiet"], 30)
        owned = True
        for name, arguments, maximum in (
            (
                "database",
                ["up", "-d", "--wait", "--wait-timeout", "90", "--pull", "never", "db"],
                120,
            ),
            ("migrate", ["run", "--rm", "--no-deps", "--pull", "never", "migrate"], 120),
            ("seed", ["run", "--rm", "--no-deps", "--pull", "never", "seed"], 360),
            (
                "services",
                [
                    "up",
                    "-d",
                    "--no-deps",
                    "--no-build",
                    "--pull",
                    "never",
                    "--wait",
                    "--wait-timeout",
                    "90",
                    "api",
                    "worker",
                    "frontend",
                ],
                120,
            ),
        ):
            phase(name, base + arguments, maximum)
        phase(
            "prepare-reviews",
            [
                sys.executable,
                "scripts/prepare_review_capture.py",
                "--project",
                source,
                "--runtime-proof",
                str(directory / "runtime-proof.json"),
                "--artifacts",
                str(directory / "review-cases"),
            ],
            150,
        )
        case = json.loads((directory / "review-cases/review-case.json").read_text(encoding="utf-8"))
        captures = new_private_directory(directory / "review-captures")
        browser_env = {
            **environment,
            "ED_REVIEW_CAPTURE_CASE_PATH": str(directory / "review-cases/review-case.json"),
            "ED_REVIEW_CAPTURE_ALLOW_WRITE": "1",
            "ED_E2E_BASE_URL": frontend_url,
            "ED_E2E_ARTIFACT_DIR": str(captures),
        }
        browser_env.pop("ED_RESTORE_CASE_PATH", None)
        phase(
            "review-browser",
            ["node", str(browser_cli), "test", "restore-read.spec.ts", "--grep", "ED03"],
            150,
            env=browser_env,
            cwd=ROOT / "frontend",
        )
        for name in ("ed03-approved-proof.json", "ed03-conflict-proof.json"):
            proof = json.loads((captures / name).read_text(encoding="utf-8"))
            if proof["status"] != "passed" or proof["run_id"] != case["run_id"]:
                raise ValueError("The two real review browser proofs must match this run.")
        phase(
            "restore-read",
            [
                sys.executable,
                "scripts/check_erasure_restore.py",
                "--project",
                source,
                "--target",
                target,
                "--backup",
                str(directory / "backup"),
                "--output",
                str(directory / "erasure-restore.json"),
                "--reopen-read",
                "--runtime-proof",
                str(directory / "runtime-proof.json"),
                "--read-artifacts",
                str(directory / "restore-captures"),
            ],
            1000,
        )
        result = json.loads((directory / "erasure-restore.json").read_text(encoding="utf-8"))
        if (
            result["status"] != "passed"
            or not result["containers_stopped"]
            or result["provider_calls"] != 0
        ):
            raise ValueError("The physical erasure/restore proof did not pass and close safely.")
        source_unchanged(before, runtime_sources())
        seed_after = seed_input_sources()
        write_private(directory / "seed-inputs-after.json", seed_after)
        source_unchanged(seed_inputs, seed_after)
        record["seed_inputs_unchanged"] = True
        record["operational_sources_after"] = operational_sources()
        source_unchanged(record["operational_sources_before"], record["operational_sources_after"])
        if time.monotonic() > deadline:
            raise TimeoutError("The proof exhausted its 30-minute work window.")
        record.update(status="passed", source_unchanged=True)
    except BaseException as error:
        record.update(status="failed", error_type=type(error).__name__)
        raise
    finally:
        close_attempt(
            record,
            directory / "final-attempt.json",
            base if owned else None,
            target_base if owned else None,
        )


if __name__ == "__main__":
    main()
