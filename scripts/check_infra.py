"""Validate the exact pinned tools without starting application services."""

import argparse
import json
import subprocess
import sys
from datetime import UTC, datetime
from pathlib import Path

from ops import ROOT, compose_command, parser


def main():
    cli = argparse.ArgumentParser(description=__doc__)
    cli.add_argument("--output", type=Path, default=ROOT / "docs/evidence/infra-config-check.json")
    args = cli.parse_args()
    base = compose_command(parser().parse_args(["--observability", "config"]))
    checks = [
        ("compose", base + ["config", "--quiet"]),
        (
            "collector",
            base
            + [
                "run",
                "--rm",
                "--no-deps",
                "collector",
                "validate",
                "--config=/etc/otelcol/config.yaml",
            ],
        ),
        (
            "prometheus",
            base
            + [
                "run",
                "--rm",
                "--no-deps",
                "--entrypoint",
                "/bin/promtool",
                "prometheus",
                "check",
                "config",
                "/etc/prometheus/prometheus.yaml",
            ],
        ),
        (
            "alert-rules",
            base
            + [
                "run",
                "--rm",
                "--no-deps",
                "--entrypoint",
                "/bin/promtool",
                "-v",
                f"{ROOT / 'infra/observability'}:/checks:ro",
                "prometheus",
                "test",
                "rules",
                "/checks/alerts.test.yaml",
            ],
        ),
        (
            "alertmanager",
            base
            + [
                "run",
                "--rm",
                "--no-deps",
                "--entrypoint",
                "/bin/amtool",
                "alertmanager",
                "check-config",
                "/etc/alertmanager/config.yaml",
            ],
        ),
        (
            "loki",
            base
            + [
                "run",
                "--rm",
                "--no-deps",
                "loki",
                "-config.file=/etc/loki/config.yaml",
                "-verify-config=true",
            ],
        ),
        (
            "tempo",
            base
            + [
                "run",
                "--rm",
                "--no-deps",
                "tempo",
                "-config.file=/etc/tempo/config.yaml",
                "-config.verify=true",
            ],
        ),
    ]
    results = []
    for name, command in checks:
        result = subprocess.run(
            command,
            cwd=ROOT,
            text=True,
            encoding="utf-8",
            errors="replace",
            capture_output=True,
            timeout=120,
        )
        results.append(
            {
                "check": name,
                "exit_code": result.returncode,
                "output": (result.stdout + result.stderr)[-12000:],
            }
        )
        print(f"{name}: {'passed' if result.returncode == 0 else 'FAILED'}")
    record = {
        "recorded_at": datetime.now(UTC).isoformat(),
        "kind": "configuration-validation",
        "runtime_journey": False,
        "checks": results,
    }
    destination = args.output
    destination.parent.mkdir(parents=True, exist_ok=True)
    destination.write_text(
        json.dumps(record, ensure_ascii=False, indent=2) + "\n", encoding="utf-8"
    )
    return int(any(result["exit_code"] for result in results))


if __name__ == "__main__":
    sys.exit(main())
