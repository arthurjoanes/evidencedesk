"""Record the final locked image and completed smoke from Docker's observed metadata."""

import argparse
import hashlib
import json
import subprocess
from pathlib import Path


def docker_json(*arguments):
    result = subprocess.run(
        ["docker", *arguments], check=True, capture_output=True, text=True
    )
    return json.loads(result.stdout)


def digest(path):
    return hashlib.sha256(path.read_bytes()).hexdigest()


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--image", required=True)
    parser.add_argument("--previous-image", required=True)
    parser.add_argument("--container", required=True)
    args = parser.parse_args()
    root = Path(__file__).resolve().parents[1]
    reports = root / "experiments/reports"
    current = docker_json("image", "inspect", args.image)[0]
    previous = docker_json("image", "inspect", args.previous_image)[0]
    container = docker_json("inspect", args.container)[0]
    assert current["Id"] != previous["Id"]
    assert container["Image"] == current["Id"]
    history = subprocess.run(
        ["docker", "history", "--no-trunc", "--format", "{{.CreatedBy}}", args.image],
        check=True,
        capture_output=True,
        text=True,
    ).stdout
    install_command = "pip install --no-deps -r /tmp/requirements-ml.lock"
    assert install_command in history
    environment = json.loads((reports / "environment-check-locked.json").read_text())
    previous_environment = json.loads(
        (reports / "environment-check-previous.json").read_text()
    )
    assert previous_environment["packages"] == environment["packages"]
    smoke = json.loads((reports / "model-service-smoke-locked.json").read_text())
    first = json.loads((reports / "model-service-smoke.json").read_text())
    assert environment["status"] == smoke["status"] == "passed"
    assert environment["lock_sha256"] == digest(
        root / "experiments/requirements-ml.lock"
    )
    assert first["health"] == smoke["health"]
    assert first["dimensions"] == smoke["dimensions"] == 384
    pip_check = subprocess.run(
        ["docker", "exec", args.container, "python", "-m", "pip", "check"],
        check=True,
        capture_output=True,
        text=True,
    ).stdout.strip()
    stats = docker_json(
        "stats", "--no-stream", "--format", "{{json .}}", args.container
    )
    report = {
        "status": "built_from_final_lock_and_smoke_passed",
        "image": {
            "tag": args.image,
            "id": current["Id"],
            "created_at": current["Created"],
        },
        "previous_image_preserved": {"tag": args.previous_image, "id": previous["Id"]},
        "dockerfile_sha256": digest(root / "experiments/Dockerfile"),
        "lock_sha256": environment["lock_sha256"],
        "locked_packages_checked": len(environment["packages"]),
        "install_command_observed_in_image_history": install_command,
        "pip_check": pip_check,
        "runtime": {
            "container_image_id": container["Image"],
            "memory_limit_bytes": container["HostConfig"]["Memory"],
            "nano_cpus": container["HostConfig"]["NanoCpus"],
            "read_only_root": container["HostConfig"]["ReadonlyRootfs"],
            "health": container["State"]["Health"]["Status"],
            "observed_memory_usage": stats["MemUsage"],
            "observed_cpu_percent": stats["CPUPerc"],
        },
        "environment_report_sha256": digest(reports / "environment-check-locked.json"),
        "http_smoke_report_sha256": digest(reports / "model-service-smoke-locked.json"),
        "same_model_revisions_and_dimensions_as_previous_smoke": True,
        "same_locked_packages_as_previous_image": True,
        "model_weights_downloaded": False,
        "training_performed": False,
        "azure_calls": 0,
        "dependency_network": "Exact locked dependencies were allowed; initial network-none build failed URL resolution.",
        "interpretation": "Build and functional HTTP verification only; not a new quality or capacity benchmark.",
    }
    target = reports / "ml-final-build.json"
    target.write_text(json.dumps(report, indent=2) + "\n")
    index_path = reports / "index.json"
    index = json.loads(index_path.read_text())
    index[target.name] = digest(target)
    index_path.write_text(json.dumps(index, indent=2) + "\n")
    print(
        json.dumps(
            {
                "status": report["status"],
                "image_id": current["Id"],
                "lock_sha256": environment["lock_sha256"],
            }
        )
    )


if __name__ == "__main__":
    main()
