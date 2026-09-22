import argparse
import contextlib
import io
import json
import subprocess
import tempfile
import unittest
from pathlib import Path
from unittest.mock import Mock, patch

import backup
import restore_read_probe as probe

STATE = {
    "maintenance": True,
    "ledger_ready": True,
    "drained": True,
    "active_jobs": 0,
    "active_uploads": 0,
    "ledger_sequence": 1,
}
IMAGES = {"api": "sha256:" + "a" * 64, "frontend": "sha256:" + "b" * 64}


def record():
    return {
        "source_project": "pf-evidencedesk-capacity-host-test",
        "target_project": "pf-evidencedesk-restore-host-test",
        "status": "passed",
        "target_opened": False,
        "objects": {"verified_references": 1},
        "current_ledger_sha256": "c" * 64,
        "reconciliation": STATE.copy(),
    }


class RestoreReadGuardsTests(unittest.TestCase):
    def test_main_foreign_or_same_namespace_is_refused(self):
        for key, value in [
            ("source_project", "pf-evidencedesk"),
            ("target_project", "pf-evidencedesk-capacity-host-test"),
            ("target_project", "foreign"),
        ]:
            with self.subTest(key=key, value=value), self.assertRaises(ValueError):
                probe.validate_gate({**record(), key: value}, STATE, STATE)

    def test_incomplete_restore_or_unready_source_cannot_open(self):
        for change in [
            {"status": "running"},
            {"target_opened": True},
            {"objects": {"verified_references": 0}},
            {"current_ledger_sha256": ""},
        ]:
            with self.subTest(change=change), self.assertRaises(ValueError):
                probe.validate_gate({**record(), **change}, STATE, STATE)
        for changed in [
            {**STATE, "ledger_ready": False},
            {**STATE, "active_jobs": 1},
            {**STATE, "active_uploads": 1},
            {**STATE, "maintenance": False},
        ]:
            with self.subTest(state=changed), self.assertRaises(ValueError):
                probe.validate_gate(record(), STATE, changed)
        probe.validate_gate(record(), STATE, STATE)

    def test_overlay_refuses_tag_ports_and_keeps_optional_services_out(self):
        for api, frontend, images in [
            (8108, 8108, IMAGES),
            (False, 3108, IMAGES),
            (80, 3108, IMAGES),
            (8108, 3108, {**IMAGES, "api": "backend:latest"}),
        ]:
            with (
                self.subTest(api=api, frontend=frontend),
                self.assertRaises(ValueError),
            ):
                probe.override_text(api, frontend, images)
        value = probe.override_text(8108, 3108, IMAGES)
        self.assertIn("127.0.0.1:8108:8106", value)
        self.assertIn("127.0.0.1:3108:3106", value)
        self.assertIn("ED_ALLOWED_ORIGINS: http://127.0.0.1:3108", value)
        self.assertIn("ED_AI_PROVIDER: disabled", value)
        self.assertIn("ED_RETRIEVAL_MODE: lexical", value)

    def test_runtime_inventory_rejects_extra_worker_external_port_and_wrong_image(self):
        rows = [
            {"service": "db", "image": "database", "ports": {"5432/tcp": None}},
            {
                "service": "api",
                "image": IMAGES["api"],
                "ports": {"8106/tcp": [{"HostIp": "127.0.0.1", "HostPort": "8108"}]},
            },
            {
                "service": "frontend",
                "image": IMAGES["frontend"],
                "ports": {"3106/tcp": [{"HostIp": "127.0.0.1", "HostPort": "3108"}]},
            },
        ]
        probe.validate_services(rows, IMAGES, 8108, 3108)
        bad = json.loads(json.dumps(rows))
        bad[1]["ports"]["8106/tcp"][0]["HostIp"] = "0.0.0.0"
        wrong = json.loads(json.dumps(rows))
        wrong[1]["image"] = "old-image"
        for invalid in [rows + [{"service": "worker"}], bad, wrong]:
            with self.assertRaises(ValueError):
                probe.validate_services(invalid, IMAGES, 8108, 3108)

    def test_cleanup_never_targets_main_and_detects_survivors(self):
        with patch.object(backup, "run") as command:
            with self.assertRaises(ValueError):
                probe.stop_target("pf-evidencedesk")
            command.assert_not_called()
        with (
            patch.object(probe, "project_containers", side_effect=[["a" * 12], ["a" * 12]]),
            patch.object(backup, "run"),
            self.assertRaises(RuntimeError),
        ):
            probe.stop_target(record()["target_project"])

    def test_foreign_browser_proof_cannot_approve_the_restore(self):
        with tempfile.TemporaryDirectory() as temporary:
            directory = Path(temporary)
            case = {"run_id": "run-1", "target_project": "target", "ledger_sequence": 1}
            proof = {
                **case,
                "status": "passed",
                "base_url": "http://127.0.0.1:3108",
                "generation_post_attempts": [],
                "blocked_requests": [],
            }
            path = directory / "restore-read-proof.json"
            probe.write_private(path, proof)
            self.assertEqual(
                probe.browser_proof(directory, case, proof["base_url"])["run_id"],
                "run-1",
            )
            for field, value in [
                ("run_id", "other"),
                ("ledger_sequence", 0),
                ("generation_post_attempts", ["unexpected"]),
                ("status", "failed"),
            ]:
                path.write_text(json.dumps({**proof, field: value}), encoding="utf-8")
                with self.subTest(field=field), self.assertRaises(ValueError):
                    probe.browser_proof(directory, case, proof["base_url"])

    def test_private_records_are_immutable_and_lf(self):
        with tempfile.TemporaryDirectory() as temporary:
            path = Path(temporary) / "proof.json"
            probe.write_private(path, {"text": "ação"})
            self.assertNotIn(b"\r", path.read_bytes())
            with self.assertRaises(FileExistsError):
                probe.write_private(path, {})

    def test_text_mode_command_failure_keeps_original_error_and_private_diagnostics(self):
        with tempfile.TemporaryDirectory() as temporary:
            directory = Path(temporary)
            build = directory / "build.json"
            build.write_text("{}", encoding="utf-8")
            with (
                patch.object(probe, "new_private_directory", return_value=directory),
                patch.object(
                    probe, "runtime_proof", return_value={"images": IMAGES, "source_files": {}}
                ),
            ):
                journey = probe.ReadJourney(
                    ["docker", "compose", "--project-name", record()["source_project"]],
                    {},
                    directory,
                    build,
                )
            failure = subprocess.CalledProcessError(
                1, ["private-command"], output="diagnóstico privado", stderr="erro original"
            )
            with (
                patch.object(probe, "runtime_sources", return_value={}),
                patch.object(backup, "maintenance", side_effect=failure),
                self.assertRaises(subprocess.CalledProcessError) as caught,
            ):
                journey(base=[], manifest={}, record=record())
            self.assertIs(caught.exception, failure)
            diagnostic = json.loads(
                (directory / "command-failure-private.json").read_text(encoding="utf-8")
            )
            self.assertEqual(diagnostic["stdout"], "diagnóstico privado")
            self.assertEqual(
                json.loads((directory / "read-window.json").read_text())["status"], "failed"
            )

    def test_expired_work_budget_still_allows_reserved_cleanup_budget(self):
        clock = [0]
        with (
            patch.object(backup.time, "monotonic", side_effect=lambda: clock[0]),
            backup.command_budget(1),
        ):
            clock[0] = 2
            with self.assertRaises(TimeoutError):
                backup.command_timeout()
            with backup.command_budget(30, cleanup=True):
                self.assertEqual(backup.command_timeout(), 30)
            with self.assertRaises(TimeoutError):
                backup.command_timeout()

    def test_nested_work_cannot_extend_the_outer_deadline(self):
        clock = [0]
        with (
            patch.object(backup.time, "monotonic", side_effect=lambda: clock[0]),
            backup.command_budget(10),
        ):
            clock[0] = 8
            with backup.command_budget(240):
                self.assertEqual(backup.command_timeout(), 2)
                clock[0] = 11
                with self.assertRaises(TimeoutError):
                    backup.command_timeout()

    def test_maintenance_failure_keeps_new_owner_token_private(self):
        with tempfile.TemporaryDirectory() as temporary:
            path = Path(temporary) / "failure.json"
            output = io.StringIO()
            failure = subprocess.CalledProcessError(
                1, ["private-command"], output='{"maintenance_token":"private-owner"}'
            )
            with (
                patch.object(backup, "run", side_effect=failure),
                contextlib.redirect_stderr(output),
                self.assertRaises(ValueError) as caught,
            ):
                backup.maintenance([], "enter", error_output=path)
            self.assertNotIn("private-owner", output.getvalue() + str(caught.exception))
            self.assertEqual(json.loads(path.read_text())["maintenance_token"], "private-owner")

    def test_changed_runtime_sources_refuse_build_proof(self):
        with tempfile.TemporaryDirectory() as temporary:
            path = Path(temporary) / "build-proof.json"
            path.write_text(
                json.dumps(
                    {
                        "kind": "local-build-source-proof",
                        "images": IMAGES,
                        "source_files": {"backend/src/app.py": "old"},
                    }
                )
            )
            with (
                patch.object(probe, "runtime_sources", return_value={"backend/src/app.py": "new"}),
                self.assertRaises(ValueError),
            ):
                probe.runtime_proof(path)


class VerifiedRestoreCallbackTests(unittest.TestCase):
    def exercise(self, callback):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            repository = root / "repository"
            repository.mkdir()
            directory = root / "backup"
            directory.mkdir()
            (directory / "database.dump").write_bytes(b"synthetic")
            args = argparse.Namespace(
                backup=directory,
                project=record()["source_project"],
                target=record()["target_project"],
                env_file=None,
            )
            source = ["docker", "compose", "--project-name", args.project]
            events = []

            def maintenance(base, action, *extra):
                events.append(("source" if base == source else "target", action))
                return STATE.copy()

            def called(**kwargs):
                self.assertNotIn(("source", "leave"), events)
                self.assertIn(("target", "claimed"), events)
                if callback == "fail":
                    raise RuntimeError("browser failed")
                return {"status": "passed", "target_closed": True}

            def claim_target(base):
                self.assertEqual(base[base.index("--project-name") + 1], args.target)
                events.append(("target", "claimed"))

            with (
                patch.object(backup, "ROOT", repository),
                patch.object(
                    backup,
                    "verify_backup",
                    return_value={
                        "project": args.project,
                        "maintenance_token": "owner",
                    },
                ),
                patch.object(backup, "target_is_new"),
                patch.object(backup, "acquire_maintenance", return_value="source-owner"),
                patch.object(backup, "binary_file"),
                patch.object(backup, "file_digest", return_value="a" * 64),
                patch.object(backup, "maintenance", side_effect=maintenance),
                patch.object(backup, "run", return_value="[]"),
                patch.object(
                    backup.subprocess,
                    "run",
                    return_value=Mock(stdout='{"verified_references":1}'),
                ),
            ):
                if callback == "fail":
                    with self.assertRaisesRegex(RuntimeError, "browser failed"):
                        backup.verify_restore(
                            source, args, verified_probe=called, target_claimed=claim_target
                        )
                    self.assertFalse((repository / "docs/evidence").exists())
                else:
                    value = backup.verify_restore(
                        source,
                        args,
                        verified_probe=called if callback else None,
                        target_claimed=claim_target,
                    )
                    self.assertEqual(value["target_opened"], bool(callback))
                    self.assertEqual("read_journey" in value, bool(callback))
                self.assertEqual(events[-1], ("source", "leave"))

    def test_default_restore_remains_closed(self):
        self.exercise(None)

    def test_optional_callback_runs_before_source_is_released(self):
        self.exercise("pass")

    def test_callback_failure_releases_source_without_publishing_success(self):
        self.exercise("fail")

    def test_existing_target_never_grants_cleanup_ownership(self):
        with tempfile.TemporaryDirectory() as temporary:
            args = argparse.Namespace(
                backup=Path(temporary),
                project=record()["source_project"],
                target=record()["target_project"],
                env_file=None,
            )
            claim_target = Mock()
            with (
                patch.object(backup, "verify_backup", return_value={"project": args.project}),
                patch.object(backup, "target_is_new", side_effect=ValueError("existing target")),
                patch.object(backup, "acquire_maintenance") as acquire,
                patch.object(backup, "run") as command,
                self.assertRaises(ValueError),
            ):
                backup.verify_restore([], args, target_claimed=claim_target)
            claim_target.assert_not_called()
            acquire.assert_not_called()
            command.assert_not_called()


if __name__ == "__main__":
    unittest.main()
