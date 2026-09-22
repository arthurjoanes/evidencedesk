"""Captured child execution with bounded, process-owned timeout cleanup."""

import math
import os
import signal
import subprocess
import time
from pathlib import Path

_WINDOWS = os.name == "nt"
_REDACTED_COMMAND = "<bounded child>"
_SIGKILL = getattr(signal, "SIGKILL", 9)


class BoundedProcessTimeout(subprocess.TimeoutExpired):
    def __init__(self, timeout, *, stdout, stderr, cleanup_complete):
        super().__init__(_REDACTED_COMMAND, timeout, output=stdout, stderr=stderr)
        self.cleanup_complete = cleanup_complete

    def __str__(self):
        result = "confirmed" if self.cleanup_complete else "not confirmed"
        return f"Bounded child timed out after {self.timeout:g} seconds; tree cleanup {result}."


def _duration(value, name):
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        raise ValueError(f"{name} must be a finite positive number.")
    if not math.isfinite(value) or value <= 0:
        raise ValueError(f"{name} must be a finite positive number.")
    return float(value)


def _remaining(deadline):
    return max(0, deadline - time.monotonic())


def _stop_owned_tree(process, timeout):
    """Never accept an external PID or select processes by image/project name."""
    pid = process.pid
    if type(pid) is not int or not 0 < pid <= 0xFFFFFFFF or pid == os.getpid():
        return False, None, None
    deadline = time.monotonic() + timeout
    tree_stopped = False
    try:
        if _WINDOWS:
            # Retain the Popen handle while addressing this child by PID.
            taskkill = str(
                Path(os.environ.get("SystemRoot", r"C:\Windows")) / "System32" / "taskkill.exe"
            )
            stopped = subprocess.run(
                [taskkill, "/T", "/F", "/PID", str(pid)],
                stdin=subprocess.DEVNULL,
                capture_output=True,
                shell=False,
                check=False,
                timeout=_remaining(deadline),
                creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0x08000000),
            )
            tree_stopped = stopped.returncode == 0
        else:
            # start_new_session below makes the child's own PID its process group.
            if pid == os.getpgrp():
                return False, None, None
            try:
                os.killpg(pid, _SIGKILL)
            except ProcessLookupError:
                pass  # No processes remain in the group we created.
            tree_stopped = True
    except (OSError, subprocess.SubprocessError):
        pass
    if not tree_stopped:
        try:
            process.kill()  # Own handle only; this is not proof that descendants stopped.
        except OSError:
            pass
    try:
        stdout, stderr = process.communicate(timeout=_remaining(deadline))
    except (OSError, subprocess.SubprocessError):
        # Do not close pipes held by reader threads: close() itself may block.
        return False, None, None
    return tree_stopped, stdout, stderr


def run_bounded(command, *, cwd=None, env=None, timeout, cleanup_timeout=15):
    """Return captured bytes or raise a redacted subprocess failure/timeout.

    The timeout covers communicate; timeout cleanup has its own small allowance.
    Captured output is available on results/exceptions for private diagnostics, but
    neither arguments, environment nor output are rendered in exception messages.
    """
    timeout = _duration(timeout, "timeout")
    cleanup_timeout = _duration(cleanup_timeout, "cleanup_timeout")
    if isinstance(command, (str, bytes)):
        raise ValueError("Command must be a nonempty argument sequence.")
    try:
        arguments = [os.fspath(value) for value in command]
    except (TypeError, ValueError):
        raise ValueError("Command must be a nonempty argument sequence.") from None
    if (
        not arguments
        or not arguments[0]
        or any(not isinstance(value, str) or "\0" in value for value in arguments)
    ):
        raise ValueError("Command must contain valid string arguments.")
    launch = (
        {
            "creationflags": getattr(subprocess, "CREATE_NEW_PROCESS_GROUP", 0x00000200)
            | getattr(subprocess, "CREATE_NO_WINDOW", 0x08000000)
        }
        if _WINDOWS
        else {"start_new_session": True}
    )
    try:
        process = subprocess.Popen(
            arguments,
            cwd=cwd,
            env=env,
            stdin=subprocess.DEVNULL,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            shell=False,
            **launch,
        )
    except OSError:
        raise RuntimeError("Bounded child could not be started.") from None
    try:
        stdout, stderr = process.communicate(timeout=timeout)
    except subprocess.TimeoutExpired as error:
        complete, stdout, stderr = _stop_owned_tree(process, cleanup_timeout)
        raise BoundedProcessTimeout(
            timeout,
            stdout=stdout if stdout is not None else error.output,
            stderr=stderr if stderr is not None else error.stderr,
            cleanup_complete=complete,
        ) from None
    except BaseException as error:
        complete, _, _ = _stop_owned_tree(process, cleanup_timeout)
        if isinstance(error, (KeyboardInterrupt, SystemExit)):
            raise
        result = "confirmed" if complete else "not confirmed"
        raise RuntimeError(f"Bounded child capture failed; tree cleanup {result}.") from None
    if process.returncode:
        raise subprocess.CalledProcessError(
            process.returncode, _REDACTED_COMMAND, output=stdout, stderr=stderr
        )
    return subprocess.CompletedProcess(_REDACTED_COMMAND, process.returncode, stdout, stderr)
