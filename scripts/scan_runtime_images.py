"""Inspect current local runtime images offline; retain only vulnerability report fields."""

import argparse
import hashlib
import json
import re
import subprocess
import tarfile
import time
from datetime import UTC, datetime
from pathlib import Path

from check_vulnerability_report import evaluate

ROOT = Path(__file__).resolve().parents[1]
SCANNER = (
    "aquasec/trivy:0.74.0@sha256:62b1e65e8869bc4b4c6aa4fa2b21595256c7c2f6018a9d9ad61caf87187c1969"
)
IMAGES = {"api": "pf-evidencedesk-backend:local", "frontend": "pf-evidencedesk-frontend:local"}


def run(arguments: list[str]) -> str:
    return subprocess.run(arguments, check=True, capture_output=True, text=True).stdout


def digest(path: Path) -> str:
    with path.open("rb") as stream:
        return "sha256:" + hashlib.file_digest(stream, "sha256").hexdigest()


def configuration_digest(archive: Path, image_id: str) -> str:
    """Resolve Docker's OCI index/manifest identity to Trivy's image config identity."""
    with tarfile.open(archive) as saved:
        # Classic Docker stores config.json at the root, with ImageID equal to its hash.
        if "blobs/sha256/" + image_id.removeprefix("sha256:") not in saved.getnames():
            manifest_source = saved.extractfile("manifest.json")
            if manifest_source is None:
                raise ValueError("Missing Docker archive manifest.")
            manifests = json.load(manifest_source)
            if len(manifests) != 1:
                raise ValueError("Expected one frozen image in the Docker archive.")
            source = saved.extractfile(manifests[0]["Config"])
            if source is None:
                raise ValueError("Missing Docker configuration.")
            content = source.read()
            if "sha256:" + hashlib.sha256(content).hexdigest() != image_id:
                raise ValueError("Docker configuration does not match the frozen image.")
            if "rootfs" not in json.loads(content):
                raise ValueError("Invalid Docker configuration.")
            return image_id

        def blob(identity: str) -> dict:
            algorithm, checksum = identity.split(":", 1)
            if (
                algorithm != "sha256"
                or len(checksum) != 64
                or any(c not in "0123456789abcdef" for c in checksum)
            ):
                raise ValueError("Invalid image digest.")
            source = saved.extractfile("blobs/sha256/" + checksum)
            if source is None:
                raise ValueError("Missing OCI blob.")
            content = source.read()
            if hashlib.sha256(content).hexdigest() != checksum:
                raise ValueError("OCI blob does not match its digest.")
            return json.loads(content)

        current = image_id
        for _ in range(3):
            document = blob(current)
            if "config" in document:
                configuration = document["config"]["digest"]
                blob(configuration)
                return configuration
            if "rootfs" in document:
                return current
            platforms = [
                item
                for item in document.get("manifests", [])
                if item.get("platform") == {"architecture": "amd64", "os": "linux"}
            ]
            if len(platforms) != 1:
                raise ValueError("Expected one Linux amd64 manifest in the saved image.")
            current = platforms[0]["digest"]
        raise ValueError("Unsupported image manifest nesting.")


def redact(report: dict) -> dict:
    """Whitelist vulnerability metadata; never copy secret Matches, env or image history."""
    allowed = (
        "VulnerabilityID",
        "PkgName",
        "PkgPath",
        "InstalledVersion",
        "FixedVersion",
        "Severity",
        "SeveritySource",
        "CVSS",
        "Status",
        "Title",
        "PrimaryURL",
        "DataSource",
    )
    return {
        "SchemaVersion": report["SchemaVersion"],
        "Metadata": {key: report["Metadata"][key] for key in ("ImageID", "OS")},
        "Results": [
            {
                "Target": target["Target"],
                "Class": target.get("Class"),
                "Type": target.get("Type"),
                "Packages": [
                    {key: package[key] for key in ("Name", "Version")}
                    for package in (target.get("Packages") or [])
                ],
                "Vulnerabilities": [
                    {key: finding[key] for key in allowed if key in finding}
                    for finding in (target.get("Vulnerabilities") or [])
                ],
            }
            for target in report["Results"]
        ],
    }


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--cache-db", type=Path, required=True)
    parser.add_argument("--services", nargs="+", choices=tuple(IMAGES), default=list(IMAGES))
    parser.add_argument("--image-tag", default="local", help="Tag of both local runtime images.")
    parser.add_argument("--evidence-name", default="security-final-2026-09-21")
    args = parser.parse_args()
    if not re.fullmatch(r"[a-zA-Z0-9_][a-zA-Z0-9_.-]{0,127}", args.image_tag):
        parser.error("Invalid Docker image tag.")
    if not args.evidence_name.replace("-", "").isalnum():
        parser.error("Evidence name must contain letters, digits and hyphens only.")
    cache = args.cache_db.resolve(strict=True)
    database = json.loads((cache / "metadata.json").read_text(encoding="utf-8"))
    age = (datetime.now(UTC) - datetime.fromisoformat(database["UpdatedAt"])).total_seconds() / 3600
    if database.get("Version") != 2 or not -1 <= age <= 72:
        raise ValueError("Cached vulnerability database must be schema 2 and at most 72h old.")
    database_digest = digest(cache / "trivy.db")
    output = ROOT / "docs" / "evidence" / args.evidence_name
    runtime = ROOT / "runtime" / args.evidence_name
    if output.exists() and any(output.iterdir()):
        parser.error("Evidence directory already contains a previous attempt; choose a new name.")
    output.mkdir(parents=True, exist_ok=True)
    runtime.mkdir(parents=True, exist_ok=True)
    version = run(
        ["docker", "run", "--rm", "--pull", "never", "--network", "none", SCANNER, "--version"]
    ).strip()
    summary = {
        "started_at": datetime.now(UTC).isoformat(),
        "scanner_image": SCANNER,
        "scanner_version": version,
        "offline": True,
        "scanners": ["vuln"],
        "database": database,
        "database_sha256": database_digest,
        "database_age_hours_at_start": round(age, 2),
        "images": [],
        "scope": "local runtime images; no hosted deployment or GitHub runner",
    }
    for service in dict.fromkeys(args.services):
        reference = IMAGES[service].rsplit(":", 1)[0] + ":" + args.image_tag
        image_id = run(["docker", "image", "inspect", reference, "--format", "{{.Id}}"]).strip()
        started = time.monotonic()
        archive = runtime / f"{service}.tar"
        raw = runtime / f"{service}-raw.json"
        run(["docker", "save", image_id, "-o", str(archive)])
        config_id = configuration_digest(archive, image_id)
        command = [
            "docker",
            "run",
            "--rm",
            "--pull",
            "never",
            "--network",
            "none",
            "--read-only",
            "--cap-drop",
            "ALL",
            "--security-opt",
            "no-new-privileges:true",
            "--memory",
            "1g",
            "--cpus",
            "1",
            "--pids-limit",
            "128",
            "--tmpfs",
            "/tmp:rw,noexec,nosuid,size=268435456",
            "--tmpfs",
            "/cache:rw,nosuid,size=268435456",
            "--mount",
            f"type=bind,src={cache},dst=/cache/db,readonly",
            "--mount",
            f"type=bind,src={runtime},dst=/scan",
            "--env",
            "GOMAXPROCS=1",
            "--env",
            "TRIVY_DISABLE_VEX_NOTICE=true",
            SCANNER,
            "--cache-dir",
            "/cache",
            "image",
            "--input",
            f"/scan/{service}.tar",
            "--skip-db-update",
            "--skip-java-db-update",
            "--offline-scan",
            "--scanners",
            "vuln",
            "--ignorefile",
            "/dev/null",
            "--parallel",
            "1",
            "--timeout",
            "15m",
            "--no-progress",
            "--format",
            "json",
            "--output",
            f"/scan/{service}-raw.json",
            "--exit-code",
            "0",
        ]
        process = subprocess.run(command, capture_output=True, text=True)
        (output / f"{service}-scanner.log").write_text(process.stderr, encoding="utf-8")
        process.check_returncode()
        report = json.loads(raw.read_text(encoding="utf-8"))
        if report["Metadata"]["ImageID"] != config_id:
            raise ValueError("Scanner image identity differs from the frozen local image.")
        if not {"os-pkgs", "lang-pkgs"}.issubset({item.get("Class") for item in report["Results"]}):
            raise ValueError("Scanner must inspect OS and language packages.")
        safe_report = redact(report)
        (output / f"{service}-vulnerabilities.json").write_text(
            json.dumps(safe_report, indent=2), encoding="utf-8"
        )
        result = evaluate(safe_report)
        result.update(
            {
                "service": service,
                "reference": reference,
                "image_id": image_id,
                "config_digest": config_id,
                "duration_seconds": round(time.monotonic() - started, 3),
                "report": f"{service}-vulnerabilities.json",
            }
        )
        summary["images"].append(result)
        print(json.dumps(result), flush=True)
    if digest(cache / "trivy.db") != database_digest:
        raise ValueError("Vulnerability database changed during the scan.")
    summary["completed_at"] = datetime.now(UTC).isoformat()
    summary["passed"] = all(item["passed"] for item in summary["images"])
    (output / "summary.json").write_text(json.dumps(summary, indent=2), encoding="utf-8")
    return 0 if summary["passed"] else 1


if __name__ == "__main__":
    raise SystemExit(main())
