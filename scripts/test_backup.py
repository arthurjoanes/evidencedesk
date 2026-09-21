import io
import json
import tarfile
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

import backup
import storage_snapshot as storage


class SnapshotBoundaryTests(unittest.TestCase):
    def test_unicode_objects_round_trip_and_hash(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            source, target = root / "source", root / "target"
            source.mkdir()
            target.mkdir()
            (source / "análise.txt").write_text("Conciliação de pedidos\n", encoding="utf-8")
            archive = root / "objects.tar"
            with archive.open("wb") as output:
                storage.snapshot(source, output)
            storage.restore(target, archive)
            self.assertEqual(
                (target / "análise.txt").read_bytes(),
                (source / "análise.txt").read_bytes(),
            )
            entry = storage.inspect_archive(archive)[0]
            self.assertEqual(entry["sha256"], storage.file_digest(source / "análise.txt"))

    def test_archive_traversal_links_and_duplicate_members_fail_before_write(self):
        for filename, kind in [
            ("../escape", tarfile.REGTYPE),
            ("/absolute", tarfile.REGTYPE),
            ("a\\b", tarfile.REGTYPE),
            ("a//b", tarfile.REGTYPE),
            ("link", tarfile.SYMTYPE),
            ("link", tarfile.LNKTYPE),
        ]:
            with (
                self.subTest(filename=filename, kind=kind),
                tempfile.TemporaryDirectory() as directory,
            ):
                root = Path(directory)
                target = root / "target"
                target.mkdir()
                archive = root / "bad.tar"
                with tarfile.open(archive, "w") as stream:
                    entry = tarfile.TarInfo(filename)
                    entry.type = kind
                    entry.linkname = "../escape"
                    stream.addfile(entry, io.BytesIO())
                with self.assertRaises(ValueError):
                    storage.restore(target, archive)
                self.assertEqual(list(target.iterdir()), [])

    def test_restore_refuses_existing_objects(self):
        with tempfile.TemporaryDirectory() as directory:
            target = Path(directory)
            (target / "existing").write_text("preserve", encoding="utf-8")
            with self.assertRaises(ValueError):
                storage.restore(target, target / "missing.tar")
            self.assertEqual((target / "existing").read_text(), "preserve")

    def test_parent_link_is_rejected_before_hashing_any_reference(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            (root / "linked").mkdir()
            (root / "linked" / "source").write_bytes(b"synthetic")
            original = Path.is_symlink

            def linked(path):
                return path.name == "linked" or original(path)

            with (
                patch.object(Path, "is_symlink", linked),
                patch.object(storage, "file_digest") as digest,
            ):
                with self.assertRaisesRegex(ValueError, "Symbolic links"):
                    storage.verify_references(
                        root, [{"object_key": "linked/source", "sha256": "0" * 64}]
                    )
                digest.assert_not_called()

    def test_real_parent_link_cannot_escape_the_volume(self):
        with tempfile.TemporaryDirectory() as directory:
            base = Path(directory)
            root, outside = base / "volume", base / "outside"
            root.mkdir()
            outside.mkdir()
            (outside / "source").write_bytes(b"synthetic")
            try:
                (root / "linked").symlink_to(outside, target_is_directory=True)
            except OSError:
                self.skipTest("This host cannot create symlinks; Linux CI exercises the real path.")
            with self.assertRaises(ValueError):
                storage.verify_references(
                    root,
                    [
                        {
                            "object_key": "linked/source",
                            "sha256": storage.file_digest(outside / "source"),
                        }
                    ],
                )

    def test_missing_ledger_and_missing_referenced_object_fail_closed(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            with self.assertRaises(ValueError):
                storage.validate_ledger(root / "ledger.jsonl")
            with self.assertRaises(ValueError):
                storage.verify_references(root, [{"object_key": "absent", "sha256": "0" * 64}])

    def test_foreign_maintenance_is_not_released(self):
        with patch.object(backup, "maintenance", return_value={"maintenance": True}) as maintenance:
            with self.assertRaises(ValueError):
                backup.acquire_maintenance(["docker", "compose"])
            maintenance.assert_called_once_with(["docker", "compose"], "status")

    def test_incomplete_drain_never_produces_backup(self):
        states = [
            {"maintenance": False},
            {
                "maintenance": True,
                "drained": False,
                "active_jobs": 1,
                "ledger_ready": True,
            },
        ]
        with patch.object(backup, "maintenance", side_effect=states) as maintenance:
            with self.assertRaises(ValueError):
                backup.acquire_maintenance([])
            self.assertEqual(
                [call.args[1] for call in maintenance.call_args_list],
                ["status", "enter"],
            )

    def test_modified_backup_is_rejected(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            (root / "database.dump").write_bytes(b"modified")
            (root / "objects.tar").write_bytes(b"")
            manifest = {
                "schema_version": 1,
                "maintenance_drained": True,
                "maintenance_token": "private-test-owner",
                "files": {
                    name: {"bytes": 0, "sha256": "0" * 64}
                    for name in ["database.dump", "objects.tar", "references.json"]
                },
            }
            (root / "manifest.json").write_text(json.dumps(manifest), encoding="utf-8")
            with self.assertRaisesRegex(ValueError, "checksum or size"):
                backup.verify_backup(root)

    def test_malformed_manifest_fails_cleanly_before_reading_archive(self):
        base = {
            "schema_version": 1,
            "maintenance_drained": True,
            "maintenance_token": "synthetic",
            "files": {
                name: {"bytes": 0, "sha256": "0" * 64}
                for name in ["database.dump", "objects.tar", "references.json"]
            },
        }
        for manifest in [
            None,
            [],
            {**base, "schema_version": True},
            {**base, "files": None},
            {
                **base,
                "files": {**base["files"], "database.dump": {"bytes": True, "sha256": "0" * 64}},
            },
            {
                **base,
                "files": {**base["files"], "database.dump": {"bytes": 0, "sha256": "not-a-hash"}},
            },
        ]:
            with self.subTest(manifest=manifest), tempfile.TemporaryDirectory() as directory:
                root = Path(directory)
                (root / "manifest.json").write_text(json.dumps(manifest), encoding="utf-8")
                with self.assertRaises(ValueError):
                    backup.verify_backup(root)


if __name__ == "__main__":
    unittest.main()
