"""Validate Terraform locally; no plan, apply, Azure login or management request."""

import argparse
import hashlib
import json
import os
import subprocess
from datetime import UTC, datetime
from pathlib import Path

from ops import ROOT


def main():
    cli = argparse.ArgumentParser(description=__doc__)
    cli.add_argument("--terraform", type=Path, required=True)
    cli.add_argument(
        "--data-root",
        type=Path,
        required=True,
        help="Provider/work cache outside the repository and OneDrive.",
    )
    cli.add_argument(
        "--output", type=Path, default=ROOT / "docs/evidence/azure-iac-validation.json"
    )
    args = cli.parse_args()
    cache = args.data_root.resolve()
    if cache.is_relative_to(ROOT) or any("onedrive" in part.lower() for part in cache.parts):
        raise ValueError("Terraform provider cache must be outside the repository and OneDrive.")
    cache.mkdir(parents=True, exist_ok=True)
    plugin_cache = cache / "plugins"
    plugin_cache.mkdir(exist_ok=True)
    results = []
    for name, folder in [
        ("foundation", ROOT / "infra/azure"),
        ("runtime-contract", ROOT / "infra/azure/runtime-contract"),
    ]:
        environment = dict(
            os.environ,
            TF_DATA_DIR=str(cache / name),
            TF_PLUGIN_CACHE_DIR=str(plugin_cache),
            TF_IN_AUTOMATION="true",
            CHECKPOINT_DISABLE="1",
        )
        commands = [
            ("format", ["fmt", "-check", "-no-color"]),
            ("init", ["init", "-backend=false", "-input=false", "-lockfile=readonly", "-no-color"]),
            ("validate", ["validate", "-json"]),
        ]
        for label, command in commands:
            result = subprocess.run(
                [str(args.terraform), "-chdir=" + str(folder), *command],
                env=environment,
                capture_output=True,
                text=True,
                encoding="utf-8",
                errors="replace",
            )
            item = {"root": name, "check": label, "exit_code": result.returncode}
            if label == "validate":
                item["result"] = json.loads(result.stdout)
            else:
                item["output"] = result.stdout + result.stderr
            results.append(item)
    valid = all(
        item["exit_code"] == 0
        and (
            item["check"] != "validate"
            or (item["result"]["valid"] and item["result"]["warning_count"] == 0)
        )
        for item in results
    )
    record = {
        "recorded_at": datetime.now(UTC).isoformat(),
        "status": "passed" if valid else "failed",
        "scope": "terraform-format-provider-schema-validation",
        "azure_resource_validation": False,
        "plan_executed": False,
        "deployment_executed": False,
        "terraform_version": json.loads(
            subprocess.check_output([str(args.terraform), "version", "-json"], text=True)
        )["terraform_version"],
        "terraform_executable_sha256": hashlib.sha256(args.terraform.read_bytes()).hexdigest(),
        "checks": results,
        "sources": {
            path.relative_to(ROOT).as_posix(): hashlib.sha256(path.read_bytes()).hexdigest()
            for path in sorted((ROOT / "infra/azure").rglob("*"))
            if path.is_file() and (path.suffix == ".tf" or path.name == ".terraform.lock.hcl")
        },
    }
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(json.dumps(record, ensure_ascii=False, indent=2), encoding="utf-8")
    print(json.dumps({"status": record["status"], "checks": results}, ensure_ascii=False, indent=2))
    if not valid:
        raise SystemExit(1)


if __name__ == "__main__":
    main()
