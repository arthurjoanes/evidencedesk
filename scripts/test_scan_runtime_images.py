"""The published security artifact must not inherit image env or secret findings."""

import hashlib
import io
import json
import tarfile
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from publish_vulnerability_report import main as publish_main
from scan_runtime_images import configuration_digest, redact


class RedactionTest(unittest.TestCase):
    def test_publication_rejects_a_report_from_a_different_image(self):
        content = json.dumps({"rootfs": {"type": "layers", "diff_ids": []}}).encode()
        identity = "sha256:" + hashlib.sha256(content).hexdigest()
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            archive = root / "image.tar"
            with tarfile.open(archive, "w") as saved:
                for name, data in (
                    ("manifest.json", json.dumps([{"Config": "config.json"}]).encode()),
                    ("config.json", content),
                ):
                    member = tarfile.TarInfo(name)
                    member.size = len(data)
                    saved.addfile(member, io.BytesIO(data))
            (root / "identity.json").write_text(json.dumps(identity))
            (root / "raw.json").write_text(
                json.dumps(
                    {
                        "SchemaVersion": 2,
                        "Metadata": {"ImageID": "sha256:another-image", "OS": {}},
                        "Results": [
                            {"Target": "os", "Class": "os-pkgs"},
                            {"Target": "application", "Class": "lang-pkgs"},
                        ],
                    }
                )
            )
            arguments = [
                "publish",
                str(root / "raw.json"),
                str(root / "published.json"),
                "--archive",
                str(archive),
                "--image-id-file",
                str(root / "identity.json"),
            ]
            with patch("sys.argv", arguments), self.assertRaisesRegex(ValueError, "does not match"):
                publish_main()
            self.assertFalse((root / "published.json").exists())

    def test_classic_docker_config_hash_is_bound_to_image_id(self):
        content = json.dumps({"rootfs": {"type": "layers", "diff_ids": []}}).encode()
        identity = "sha256:" + hashlib.sha256(content).hexdigest()
        manifest = json.dumps([{"Config": "config.json"}]).encode()
        with tempfile.TemporaryDirectory() as temporary:
            archive = Path(temporary) / "classic.tar"
            with tarfile.open(archive, "w") as saved:
                for name, data in (("manifest.json", manifest), ("config.json", content)):
                    member = tarfile.TarInfo(name)
                    member.size = len(data)
                    saved.addfile(member, io.BytesIO(data))
            self.assertEqual(configuration_digest(archive, identity), identity)
            with self.assertRaisesRegex(ValueError, "does not match"):
                configuration_digest(archive, "sha256:" + "0" * 64)

    def test_null_findings_have_consistent_empty_publication(self):
        report = {
            "SchemaVersion": 2,
            "Metadata": {"ImageID": "controlled", "OS": {}},
            "Results": [{"Target": "os", "Class": "os-pkgs", "Vulnerabilities": None}],
        }
        self.assertEqual(redact(report)["Results"][0]["Vulnerabilities"], [])

    def test_oci_index_resolves_and_verifies_configuration_hash(self):
        blobs = {}

        def put(value):
            data = json.dumps(value).encode()
            identity = "sha256:" + hashlib.sha256(data).hexdigest()
            blobs[identity] = data
            return identity

        config_id = put({"rootfs": {"type": "layers", "diff_ids": []}})
        manifest_id = put({"config": {"digest": config_id}})
        image_id = put(
            {
                "manifests": [
                    {"platform": {"architecture": "amd64", "os": "linux"}, "digest": manifest_id}
                ]
            }
        )
        with tempfile.TemporaryDirectory() as temporary:
            archive = Path(temporary) / "image.tar"
            for corrupt in (False, True):
                with tarfile.open(archive, "w") as saved:
                    for identity, value in blobs.items():
                        data = b"invalid" if corrupt and identity == config_id else value
                        member = tarfile.TarInfo("blobs/sha256/" + identity.split(":")[1])
                        member.size = len(data)
                        saved.addfile(member, io.BytesIO(data))
                if corrupt:
                    with self.assertRaisesRegex(ValueError, "does not match"):
                        configuration_digest(archive, image_id)
                else:
                    self.assertEqual(configuration_digest(archive, image_id), config_id)

    def test_only_vulnerability_fields_survive(self):
        report = {
            "SchemaVersion": 2,
            "Metadata": {
                "ImageID": "sha256:controlled",
                "OS": {"Family": "debian", "Name": "12"},
                "ImageConfig": {"config": {"Env": ["CONTROLLED_SECRET=not-a-real-key"]}},
            },
            "Results": [
                {
                    "Target": "controlled-target",
                    "Class": "os-pkgs",
                    "Type": "debian",
                    "Packages": [
                        {"Name": "sample", "Version": "1", "Description": "do-not-publish"}
                    ],
                    "Secrets": [{"Match": "controlled-secret-match"}],
                    "Vulnerabilities": [
                        {
                            "VulnerabilityID": "CVE-controlled",
                            "PkgName": "sample",
                            "Severity": "HIGH",
                            "FixedVersion": "2",
                            "InstalledVersion": "1",
                            "UnexpectedMetadata": "do-not-publish",
                        }
                    ],
                }
            ],
        }
        result = redact(report)
        encoded = json.dumps(result)
        for excluded in (
            "CONTROLLED_SECRET",
            "controlled-secret-match",
            "UnexpectedMetadata",
            "ImageConfig",
            "do-not-publish",
        ):
            self.assertNotIn(excluded, encoded)
        self.assertEqual(result["Results"][0]["Vulnerabilities"][0]["Severity"], "HIGH")
        self.assertEqual(result["Results"][0]["Vulnerabilities"][0]["FixedVersion"], "2")
        self.assertEqual(result["Results"][0]["Packages"], [{"Name": "sample", "Version": "1"}])


if __name__ == "__main__":
    unittest.main()
