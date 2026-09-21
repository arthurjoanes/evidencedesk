import json
import subprocess
import tempfile
import unittest
from pathlib import Path
from unittest.mock import call, patch

from check_erasure_restore import close_attempt


class RestoreCleanupTests(unittest.TestCase):
    def test_target_stop_failure_still_stops_source_and_saves_failed_evidence(self):
        with tempfile.TemporaryDirectory() as directory:
            output = Path(directory) / "attempt.json"
            with (
                patch("builtins.print"),
                patch(
                    "check_erasure_restore.execute",
                    side_effect=[subprocess.CalledProcessError(1, ["synthetic"]), None],
                ) as execute,
            ):
                with self.assertRaisesRegex(RuntimeError, "cleanup was incomplete"):
                    close_attempt({"status": "passed"}, output, ["source"], ["target"])
            self.assertEqual(
                execute.call_args_list, [call(["target", "stop"]), call(["source", "stop"])]
            )
            record = json.loads(output.read_text(encoding="utf-8"))
            self.assertEqual(record["status"], "failed")
            self.assertFalse(record["containers_stopped"])
            self.assertEqual(record["cleanup_failures"][0]["project_role"], "target")
