import argparse
import contextlib
import io
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

import ops


class OperationsBoundaryTests(unittest.TestCase):
    def test_only_project_namespace_is_accepted(self):
        for value in ["pf-evidencedesk", "pf-evidencedesk-restore-a19"]:
            self.assertEqual(ops.project_name(value), value)
        for value in [
            "containerops",
            "pf-evidencedesk/../../",
            "pf-evidencedesk;whoami",
            "pf-evidencedesk-",
            "PF-EVIDENCEDESK",
            "pf-evidencedesk\n",
        ]:
            with (
                self.subTest(value=value),
                self.assertRaises(argparse.ArgumentTypeError),
            ):
                ops.project_name(value)

    def test_environment_path_with_spaces_remains_one_argument(self):
        with tempfile.TemporaryDirectory(prefix="ed env ") as directory:
            path = Path(directory) / "runtime.env"
            path.write_text("ED_AI_PROVIDER=disabled\n", encoding="utf-8")
            args = ops.parser().parse_args(["--env-file", str(path), "config"])
            command = ops.compose_command(args)
            self.assertEqual(command[command.index("--env-file") + 1], str(path.resolve()))

    def test_profile_is_opt_in(self):
        base = ops.compose_command(ops.parser().parse_args(["config"]))
        observed = ops.compose_command(ops.parser().parse_args(["--observability", "config"]))
        self.assertNotIn("--profile", base)
        self.assertIn(str(ops.OBSERVABILITY), observed)

    def test_browser_profile_rejects_main_and_shared_observability(self):
        for arguments in [
            ["--e2e", "config"],
            ["--project", "pf-evidencedesk-e2e-ci", "--e2e", "--observability", "config"],
        ]:
            with self.subTest(arguments=arguments), self.assertRaises(ValueError):
                ops.compose_command(ops.parser().parse_args(arguments))
        command = ops.compose_command(
            ops.parser().parse_args(["--project", "pf-evidencedesk-e2e-ci", "--e2e", "config"])
        )
        self.assertIn(str(ops.E2E), command)

    def test_no_destructive_command_is_exposed(self):
        with contextlib.redirect_stderr(io.StringIO()), self.assertRaises(SystemExit):
            ops.parser().parse_args(["purge"])

    def test_build_defaults_to_both_images_and_validates_targets(self):
        self.assertEqual(ops.parser().parse_args(["build"]).services, [])
        self.assertEqual(ops.parser().parse_args(["build", "api"]).services, ["api"])
        with contextlib.redirect_stderr(io.StringIO()), self.assertRaises(SystemExit):
            ops.parser().parse_args(["build", "foreign"])

    def test_start_refuses_accidental_credential_removal_without_printing_it(self):
        with patch.object(
            ops,
            "run",
            side_effect=[
                "a" * 12,
                "present",
                "",
                '{"services":{"api":{"environment":{"AZURE_OPENAI_API_KEY":""}}}}',
            ],
        ):
            with self.assertRaisesRegex(ValueError, "would remove an existing Azure credential"):
                ops.safeguard_runtime_credentials(["docker", "compose"])

    def test_start_accepts_new_install_and_existing_protected_configuration(self):
        with patch.object(ops, "run", side_effect=["", ""]) as run:
            ops.safeguard_runtime_credentials([])
            self.assertEqual(run.call_count, 2)
        with patch.object(
            ops,
            "run",
            side_effect=[
                "a" * 12,
                "present",
                "",
                '{"services":{"api":{"environment":{"AZURE_OPENAI_API_KEY":"synthetic-not-a-secret"}}}}',
            ],
        ):
            ops.safeguard_runtime_credentials([])

    def test_stop_selects_exact_project_containers_including_optional_profiles(self):
        with patch.object(ops, "run", side_effect=["a" * 12 + "\n" + "b" * 12, ""]) as run:
            ops.stop_project("pf-evidencedesk-e2e-ci")
            self.assertEqual(
                run.call_args_list[0].args[0],
                [
                    "docker",
                    "ps",
                    "--quiet",
                    "--filter",
                    "label=com.docker.compose.project=pf-evidencedesk-e2e-ci",
                ],
            )
            self.assertEqual(run.call_args_list[1].args[0], ["docker", "stop", "a" * 12, "b" * 12])
        with patch.object(ops, "run", return_value="foreign-name") as run:
            with self.assertRaises(ValueError):
                ops.stop_project("pf-evidencedesk-e2e-ci")
            self.assertEqual(run.call_count, 1)


if __name__ == "__main__":
    unittest.main()
