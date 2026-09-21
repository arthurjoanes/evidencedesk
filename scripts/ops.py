"""Small, project-scoped entry point for local operations (Python 3.11+)."""

from __future__ import annotations

import argparse
import json
import re
import subprocess
import sys
from datetime import UTC, datetime
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
COMPOSE = ROOT / "infra" / "compose" / "compose.yaml"
OBSERVABILITY = ROOT / "infra" / "compose" / "observability.yaml"
E2E = ROOT / "infra" / "compose" / "e2e.yaml"
PROJECT_PATTERN = re.compile(r"pf-evidencedesk(?:-[a-z0-9][a-z0-9-]{0,38})?\Z")


def project_name(value: str) -> str:
    if not PROJECT_PATTERN.fullmatch(value):
        raise argparse.ArgumentTypeError("Use pf-evidencedesk or pf-evidencedesk-<suffix>.")
    return value


def build_service(value: str) -> str:
    if value not in {"api", "frontend"}:
        raise argparse.ArgumentTypeError("Build service must be api or frontend.")
    return value


def compose_command(args: argparse.Namespace) -> list[str]:
    command = ["docker", "compose", "--project-name", args.project]
    if args.env_file:
        path = args.env_file.resolve(strict=True)
        if not path.is_file():
            raise ValueError("The environment file must be a regular file.")
        command.extend(["--env-file", str(path)])
    command.extend(["--file", str(COMPOSE)])
    if getattr(args, "e2e", False):
        if not args.project.startswith("pf-evidencedesk-e2e-"):
            raise ValueError("Browser QA requires a pf-evidencedesk-e2e-<run> project.")
        if args.observability:
            raise ValueError("Browser QA does not start the shared observability profile.")
        command.extend(["--file", str(E2E)])
    if args.observability:
        command.extend(["--file", str(OBSERVABILITY), "--profile", "observability"])
    return command


def run(command: list[str], *, capture: bool = False) -> str:
    result = subprocess.run(
        command,
        cwd=ROOT,
        check=True,
        text=True,
        encoding="utf-8",
        errors="replace",
        stdout=subprocess.PIPE if capture else None,
    )
    return result.stdout if capture else ""


def safeguard_runtime_credentials(base: list[str]) -> None:
    """Reject an accidental secret loss without returning its value from Docker."""
    presence = '{{range .Config.Env}}{{if and (eq (index (split . "=") 0) "AZURE_OPENAI_API_KEY") (ne . "AZURE_OPENAI_API_KEY=")}}present{{end}}{{end}}'
    protected = []
    for service in ("api", "worker"):
        identifiers = run(base + ["ps", "--all", "--quiet", service], capture=True).split()
        if identifiers and "present" in run(
            ["docker", "inspect", "--format", presence, *identifiers], capture=True
        ):
            protected.append(service)
    if not protected:
        return
    # Resolved values stay in memory; never log or persist the rendered configuration.
    configuration = json.loads(run(base + ["config", "--format", "json"], capture=True))
    if any(
        not configuration["services"][service].get("environment", {}).get("AZURE_OPENAI_API_KEY")
        for service in protected
    ):
        raise ValueError(
            "Start would remove an existing Azure credential. Use azure_runtime.ps1 or supply the protected runtime environment."
        )


def stop_project(project: str) -> None:
    """Include opt-in services and old Compose definitions, preserving every volume."""
    identifiers = run(
        [
            "docker",
            "ps",
            "--quiet",
            "--filter",
            f"label=com.docker.compose.project={project_name(project)}",
        ],
        capture=True,
    ).split()
    if any(not re.fullmatch(r"[a-f0-9]{12,64}", identifier) for identifier in identifiers):
        raise ValueError("Docker returned an invalid container identity.")
    if identifiers:
        run(["docker", "stop", *identifiers])


def ensure_demo_dataset() -> None:
    """Prepare synthetic fixtures on a fresh clone, preserving an existing dataset."""
    output = ROOT / "datasets" / "generated"
    if (output / "index.json").is_file():
        return
    if output.exists() and any(output.iterdir()):
        raise ValueError(
            "The demo dataset is incomplete. Inspect datasets/generated, then explicitly "
            "regenerate it with: python datasets/generate.py --output datasets/generated"
        )
    run([sys.executable, str(ROOT / "datasets" / "generate.py"), "--output", str(output)])


def parser() -> argparse.ArgumentParser:
    cli = argparse.ArgumentParser(description=__doc__)
    cli.add_argument("--project", type=project_name, default="pf-evidencedesk")
    cli.add_argument("--env-file", type=Path, help="Protected runtime environment file.")
    cli.add_argument("--observability", action="store_true")
    cli.add_argument("--e2e", action="store_true", help="Isolated browser QA on ports 3107/8107.")
    commands = cli.add_subparsers(dest="action", required=True)
    commands.add_parser("config", help="Validate configuration without printing secrets.")
    build = commands.add_parser("build")
    build.add_argument("services", nargs="*", type=build_service, metavar="api|frontend")
    commands.add_parser("start", help="Migrate and start the local application.")
    commands.add_parser("db", help="Start only PostgreSQL.")
    commands.add_parser("seed", help="Run the idempotent synthetic demo seed.")
    commands.add_parser("status")
    commands.add_parser("stop", help="Stop this project, preserving its volumes.")
    commands.add_parser("versions", help="Show image identity and runtime versions.")
    logs = commands.add_parser("logs")
    logs.add_argument("service", choices=["api", "worker", "db", "frontend", "migrate"])
    logs.add_argument("--tail", type=int, choices=range(1, 501), default=80, metavar="1..500")
    return cli


def main(argv: list[str] | None = None) -> int:
    args = parser().parse_args(argv)
    try:
        base = compose_command(args)
        run(base + ["config", "--quiet"])
        match args.action:
            case "config":
                print("Configuration valid; no environment values printed.")
            case "build":
                run(base + ["build", *(args.services or ["api", "frontend"])])
            case "db":
                run(base + ["up", "-d", "--wait", "--wait-timeout", "90", "db"])
            case "start":
                safeguard_runtime_credentials(base)
                services = ["api", "worker", "frontend"]
                if args.observability:
                    services += [
                        "collector",
                        "prometheus",
                        "loki",
                        "tempo",
                        "grafana",
                        "alertmanager",
                        "receiver",
                        "probe",
                    ]
                run(base + ["up", "-d", "--wait", "--wait-timeout", "180", *services])
            case "seed":
                ensure_demo_dataset()
                run(base + ["run", "--rm", "--no-deps", "seed"])
            case "status":
                run(base + ["ps", "--all"])
            case "stop":
                stop_project(args.project)
            case "logs":
                run(base + ["logs", "--tail", str(args.tail), args.service])
            case "versions":
                identities = run(base + ["images", "--format", "json"], capture=True)
                print(
                    json.dumps(
                        {
                            "observed_at": datetime.now(UTC).isoformat(),
                            "project": args.project,
                            "images": identities,
                        },
                        ensure_ascii=False,
                    )
                )
        return 0
    except (subprocess.CalledProcessError, OSError, ValueError) as exc:
        # Commands contain flags and resource names, never environment values.
        print(f"Operation failed: {exc}", file=sys.stderr)
        return 1


if __name__ == "__main__":
    sys.exit(main())
