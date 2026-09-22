import os
import signal
import subprocess
import unittest
from unittest.mock import Mock, patch

import bounded_process as bounded


class BoundedProcessTests(unittest.TestCase):
    def child(self):
        process = Mock()
        process.pid = 424242
        process.returncode = 0
        process.communicate.return_value = (b"captured stdout", b"captured stderr")
        return process

    def test_normal_result_captures_bytes_and_owns_a_posix_session(self):
        process = self.child()
        with (
            patch.object(bounded, "_WINDOWS", False),
            patch.object(bounded.subprocess, "Popen", return_value=process) as popen,
        ):
            result = bounded.run_bounded(["node", "private-argument"], timeout=12)
        self.assertEqual(result.stdout, b"captured stdout")
        self.assertEqual(result.stderr, b"captured stderr")
        self.assertNotIn("private-argument", repr(result))
        self.assertTrue(popen.call_args.kwargs["start_new_session"])
        self.assertFalse(popen.call_args.kwargs["shell"])
        process.communicate.assert_called_once_with(timeout=12)
        process.kill.assert_not_called()

    def test_nonzero_failure_does_not_render_arguments_or_captured_output(self):
        process = self.child()
        process.returncode = 2
        process.communicate.return_value = (b"private stdout", b"private stderr")
        with (
            patch.object(bounded.subprocess, "Popen", return_value=process),
            self.assertRaises(subprocess.CalledProcessError) as caught,
        ):
            bounded.run_bounded(["node", "private-secret"], timeout=12)
        self.assertEqual(caught.exception.returncode, 2)
        self.assertEqual(caught.exception.stdout, b"private stdout")
        self.assertNotIn("private", str(caught.exception))
        self.assertNotIn("private", repr(caught.exception))

    def test_windows_timeout_kills_only_its_validated_pid_tree_and_drains(self):
        process = self.child()
        process.communicate.side_effect = [
            subprocess.TimeoutExpired(["private-secret"], 2, output=b"partial"),
            (b"complete private output", b"complete error"),
        ]
        with (
            patch.object(bounded, "_WINDOWS", True),
            patch.object(bounded.subprocess, "Popen", return_value=process) as popen,
            patch.object(bounded.subprocess, "run", return_value=Mock(returncode=0)) as taskkill,
            self.assertRaises(bounded.BoundedProcessTimeout) as caught,
        ):
            bounded.run_bounded(["node", "private-secret"], timeout=2, cleanup_timeout=3)
        command = taskkill.call_args.args[0]
        self.assertEqual(command[1:], ["/T", "/F", "/PID", "424242"])
        self.assertNotIn("/IM", command)
        self.assertGreater(popen.call_args.kwargs["creationflags"], 0)
        self.assertNotIn("start_new_session", popen.call_args.kwargs)
        self.assertTrue(caught.exception.cleanup_complete)
        self.assertEqual(caught.exception.output, b"complete private output")
        self.assertNotIn("private", str(caught.exception))
        self.assertNotIn("private", repr(caught.exception))
        self.assertLessEqual(taskkill.call_args.kwargs["timeout"], 3)
        self.assertEqual(process.communicate.call_count, 2)

    def test_posix_timeout_kills_only_the_session_it_created(self):
        process = self.child()
        process.communicate.side_effect = [subprocess.TimeoutExpired("secret", 2), (b"out", b"err")]
        with (
            patch.object(bounded, "_WINDOWS", False),
            patch.object(bounded.subprocess, "Popen", return_value=process),
            patch.object(bounded.os, "getpgrp", return_value=123, create=True),
            patch.object(bounded.os, "killpg", create=True) as killpg,
            self.assertRaises(bounded.BoundedProcessTimeout) as caught,
        ):
            bounded.run_bounded(["node"], timeout=2)
        killpg.assert_called_once_with(424242, getattr(signal, "SIGKILL", 9))
        self.assertTrue(caught.exception.cleanup_complete)

    def test_cleanup_failure_remains_explicit_even_if_direct_child_can_be_killed(self):
        process = self.child()
        process.communicate.side_effect = [subprocess.TimeoutExpired("secret", 2), (b"out", b"err")]
        with (
            patch.object(bounded, "_WINDOWS", True),
            patch.object(bounded.subprocess, "Popen", return_value=process),
            patch.object(bounded.subprocess, "run", return_value=Mock(returncode=1)),
            self.assertRaises(bounded.BoundedProcessTimeout) as caught,
        ):
            bounded.run_bounded(["node"], timeout=2)
        process.kill.assert_called_once_with()
        self.assertFalse(caught.exception.cleanup_complete)
        self.assertIn("not confirmed", str(caught.exception))

    def test_cleanup_drain_is_bounded_and_preserves_partial_output(self):
        process = self.child()
        process.communicate.side_effect = subprocess.TimeoutExpired("secret", 2, output=b"partial")
        with (
            patch.object(bounded, "_WINDOWS", True),
            patch.object(bounded.subprocess, "Popen", return_value=process),
            patch.object(bounded.subprocess, "run", return_value=Mock(returncode=0)),
            self.assertRaises(bounded.BoundedProcessTimeout) as caught,
        ):
            bounded.run_bounded(["node"], timeout=2, cleanup_timeout=3)
        self.assertFalse(caught.exception.cleanup_complete)
        self.assertEqual(caught.exception.output, b"partial")
        self.assertLessEqual(process.communicate.call_args.kwargs["timeout"], 3)

    def test_invalid_pid_never_reaches_a_kill_operation(self):
        for pid in [0, -1, True, "424242", os.getpid()]:
            with self.subTest(pid=pid):
                process = self.child()
                process.pid = pid
                process.communicate.side_effect = subprocess.TimeoutExpired("secret", 2)
                with (
                    patch.object(bounded.subprocess, "Popen", return_value=process),
                    patch.object(bounded.subprocess, "run") as taskkill,
                    self.assertRaises(bounded.BoundedProcessTimeout) as caught,
                ):
                    bounded.run_bounded(["node"], timeout=2)
                taskkill.assert_not_called()
                process.kill.assert_not_called()
                self.assertFalse(caught.exception.cleanup_complete)

    def test_spawn_failure_and_invalid_inputs_are_redacted(self):
        with (
            patch.object(bounded.subprocess, "Popen", side_effect=OSError("private-secret")),
            self.assertRaisesRegex(RuntimeError, "could not be started") as caught,
        ):
            bounded.run_bounded(["node", "private-secret"], timeout=2)
        self.assertNotIn("private", str(caught.exception))
        for timeout in [0, -1, True, float("inf"), float("nan")]:
            with (
                self.subTest(timeout=timeout),
                patch.object(bounded.subprocess, "Popen") as popen,
                self.assertRaises(ValueError),
            ):
                bounded.run_bounded(["node"], timeout=timeout)
            popen.assert_not_called()
        with patch.object(bounded.subprocess, "Popen") as popen, self.assertRaises(ValueError):
            bounded.run_bounded("node private-secret", timeout=2)
        popen.assert_not_called()


if __name__ == "__main__":
    unittest.main()
