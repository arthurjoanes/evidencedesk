import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

import prove_restore_read as proof


class ProofOrchestratorGuardsTests(unittest.TestCase):
    def test_source_change_between_build_boundaries_refuses_association(self):
        with self.assertRaises(ValueError):
            proof.build_association(
                {"app": "before"},
                {"app": "after"},
                {
                    "api": "sha256:" + "a" * 64,
                    "frontend": "sha256:" + "b" * 64,
                },
            )

    def test_mutable_image_tag_cannot_be_a_build_association(self):
        with self.assertRaises(ValueError):
            proof.build_association(
                {"app": "same"},
                {"app": "same"},
                {
                    "api": "backend:local",
                    "frontend": "frontend:local",
                },
            )

    def test_existing_source_refuses_before_build_and_never_claims_cleanup(self):
        with tempfile.TemporaryDirectory() as temporary:
            with (
                patch("sys.argv", ["prove_restore_read.py", "--artifacts", temporary]),
                patch.object(Path, "is_file", return_value=True),
                patch.object(proof, "new_private_directory", return_value=Path(temporary)),
                patch.object(proof, "operational_sources", return_value={}),
                patch.object(proof, "target_is_new", side_effect=ValueError("existing source")),
                patch.object(proof, "run_bounded") as command,
                patch.object(proof, "close_attempt") as close,
                self.assertRaises(ValueError),
            ):
                proof.main()
            command.assert_not_called()
            self.assertEqual(close.call_args.args[-2:], (None, None))
            self.assertEqual(close.call_args.args[0]["status"], "failed")


if __name__ == "__main__":
    unittest.main()
