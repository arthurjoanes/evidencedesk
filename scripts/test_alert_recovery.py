import json
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

import check_alert_recovery as probe


class RecoveryEvidenceTests(unittest.TestCase):
    def exercise(self, scenario, query):
        directory = tempfile.TemporaryDirectory()
        self.addCleanup(directory.cleanup)
        target = Path(directory.name) / "record.json"
        with (
            patch("builtins.print"),
            patch("sys.argv", ["probe", "--scenario", scenario, "--output", str(target)]),
            patch.object(
                probe.subprocess, "check_output", return_value='[{"State":{"Running":true}}]'
            ),
            patch.object(probe, "sql", side_effect=query),
            patch.object(probe, "docker") as docker,
            patch.object(probe, "wait_for_alerts", return_value=[{"observed": True}]),
        ):
            with self.assertRaises(RuntimeError):
                probe.main()
        return json.loads(target.read_text(encoding="utf-8")), docker

    def test_cleanup_failure_still_restarts_existing_containers_and_records_failure(self):
        def query(statement):
            if "DELETE FROM jobs" in statement:
                raise RuntimeError("injected cleanup failure")
            return "1"

        record, docker = self.exercise("worker-queue-collector", query)
        docker.assert_any_call("start", "worker", "collector")
        self.assertEqual(record["status"], "failed")
        self.assertEqual(record["error_code"], "recovery_verification_failed")

    def test_unexpected_provider_count_cannot_leave_a_passed_record(self):
        answers = iter(["1", "2"])
        record, docker = self.exercise("model", lambda _: next(answers))
        docker.assert_any_call("start", "models")
        self.assertEqual(record["status"], "failed")
        self.assertEqual(record["provider_calls_after"], 2)
