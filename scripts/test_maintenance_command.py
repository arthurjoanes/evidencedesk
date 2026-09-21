import subprocess
import unittest
from unittest.mock import patch

from backup import maintenance


class MaintenanceCommandTests(unittest.TestCase):
    def test_dash_prefixed_owner_token_is_a_value_and_not_a_flag(self):
        with patch("backup.run", return_value='{"maintenance": false}') as run:
            self.assertEqual(
                maintenance(["docker"], "leave", "--token", "-private-owner"),
                {"maintenance": False},
            )
        self.assertEqual(run.call_args.args[0][-1], "--token=-private-owner")

    def test_subprocess_failure_does_not_render_command_with_owner_token(self):
        failure = subprocess.CalledProcessError(2, ["--token=private-owner"])
        with patch("backup.run", side_effect=failure), self.assertRaises(ValueError) as caught:
            maintenance(["docker"], "leave", "--token", "private-owner")
        self.assertNotIn("private-owner", str(caught.exception))


if __name__ == "__main__":
    unittest.main()
