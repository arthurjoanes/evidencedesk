"""Compare the running image to its frozen lock without network or importing Torch."""

import argparse
import hashlib
import importlib.metadata
import json
import re
import subprocess
import sys
from pathlib import Path
from urllib.parse import unquote, urlsplit

from packaging.requirements import Requirement
from packaging.utils import canonicalize_name, parse_wheel_filename


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--lock", type=Path, default=Path("experiments/requirements-ml.lock"))
    parser.add_argument("--output", type=Path, default=Path("/runs/environment-check-locked.json"))
    args = parser.parse_args()
    subprocess.run([sys.executable, "/opt/evidencedesk/patch_accelerate.py", "--check"], check=True)
    installed = {
        canonicalize_name(row.metadata["Name"]): row.version
        for row in importlib.metadata.distributions()
    }
    packages, mismatches = [], []
    for line in args.lock.read_text().splitlines():
        if not line.strip() or line.startswith("#"):
            continue
        requirement = Requirement(line)
        name = canonicalize_name(requirement.name)
        actual = installed.get(name)
        expected = str(requirement.specifier)
        if requirement.url:
            parsed = urlsplit(requirement.url)
            _, version, _, _ = parse_wheel_filename(unquote(parsed.path.rsplit("/", 1)[-1]))
            expected = "==" + str(version)
            assert actual == str(version)
            expected_hash = re.fullmatch(r"sha256=([a-f0-9]{64})", parsed.fragment)
            if expected_hash:
                raw = importlib.metadata.distribution(name).read_text("direct_url.json")
                origin = json.loads(raw or "{}")
                assert (
                    origin.get("archive_info", {}).get("hashes", {}).get("sha256")
                    == expected_hash[1]
                )
        elif actual is None or actual not in requirement.specifier:
            mismatches.append(name)
        packages.append({"name": name, "expected": expected, "installed": actual})
    report = {
        "status": "passed" if not mismatches else "failed",
        "mismatches": mismatches,
        "lock_sha256": hashlib.sha256(args.lock.read_bytes()).hexdigest(),
        "packages": packages,
        "accelerate_patch": "evidencedesk-accelerate-shards-v1",
        "network_used": False,
        "weights_loaded": False,
    }
    args.output.write_text(json.dumps(report, indent=2) + "\n")
    print(
        json.dumps(
            {key: value for key, value in report.items() if key != "packages"}
            | {"packages_checked": len(packages)}
        )
    )
    assert not mismatches


if __name__ == "__main__":
    main()
