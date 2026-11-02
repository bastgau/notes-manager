"""Running external commands without leaving processes behind."""

import os
import signal
import subprocess
from pathlib import Path


class CommandTimeout(Exception):
    pass


def run_command(cmd: list[str], *, cwd: Path, env: dict[str, str], timeout: int) -> subprocess.CompletedProcess:
    """Run a command and wait for it; on timeout, kill the command and everything it started.

    The command gets its own process group, so that a ``git`` killed after a timeout does not
    leave the ``ssh`` it launched running (an orphan that nobody would ever collect).
    """
    proc = subprocess.Popen(cmd, cwd=cwd, env=env, stdout=subprocess.PIPE, stderr=subprocess.PIPE,
                            text=True, start_new_session=True)
    try:
        stdout, stderr = proc.communicate(timeout=timeout)
    except subprocess.TimeoutExpired:
        try:
            os.killpg(proc.pid, signal.SIGKILL)
        except ProcessLookupError:
            pass
        proc.communicate()
        raise CommandTimeout(f"timed out after {timeout}s") from None
    return subprocess.CompletedProcess(cmd, proc.returncode, stdout, stderr)


def count_zombies() -> int:
    """Number of terminated processes nobody has collected yet, in this PID namespace."""
    zombies = 0
    try:
        entries = list(Path("/proc").iterdir())
    except OSError:
        return 0
    for entry in entries:
        if not entry.name.isdigit():
            continue
        try:
            for line in (entry / "status").read_text().splitlines():
                if line.startswith("State:"):
                    zombies += line.split()[1] == "Z"
                    break
        except OSError:
            continue
    return zombies
