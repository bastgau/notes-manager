import logging
import os
import subprocess
import threading
import time
from pathlib import Path

import pytest

from notes_manager import git_repo, sync
from notes_manager.git_repo import GitError
from notes_manager.processes import CommandTimeout, count_zombies, run_command


def alive(pid: int) -> bool:
    """A zombie is a dead process whose exit status was not collected."""
    try:
        for line in Path(f"/proc/{pid}/status").read_text().splitlines():
            if line.startswith("State:"):
                return line.split()[1] != "Z"
    except OSError:
        return False
    return False


def wait_until(condition, seconds=3.0):
    deadline = time.monotonic() + seconds
    while time.monotonic() < deadline:
        if condition():
            return True
        time.sleep(0.05)
    return condition()


def test_run_command_returns_status_and_output(tmp_path):
    done = run_command(["sh", "-c", "echo out; echo err >&2; exit 3"], cwd=tmp_path,
                       env=dict(os.environ), timeout=10)
    assert (done.returncode, done.stdout, done.stderr) == (3, "out\n", "err\n")


def test_a_timeout_kills_the_command_and_what_it_started(tmp_path):
    """git killed on a timeout must not leave the ssh it launched running."""
    pidfile = tmp_path / "child.pid"
    command = ["sh", "-c", f"sleep 20 & echo $! > {pidfile}; wait"]
    started = time.monotonic()
    with pytest.raises(CommandTimeout):
        run_command(command, cwd=tmp_path, env=dict(os.environ), timeout=1)
    # A grandchild that survives keeps the output pipes open and blocks the caller until it ends.
    assert time.monotonic() - started < 8, "the timeout did not release the caller"
    child = int(pidfile.read_text())
    assert wait_until(lambda: not alive(child)), "the grandchild survived the timeout"


def test_git_runs_without_background_maintenance(env, monkeypatch):
    """A detached "git gc --auto" is what left hundreds of zombies behind."""
    repo = env[2]
    seen = []
    real = git_repo.run_command
    monkeypatch.setattr(git_repo, "run_command", lambda cmd, **kw: (seen.append(cmd), real(cmd, **kw))[1])
    repo.git("rev-parse", "HEAD")
    assert "gc.auto=0" in seen[0] and "maintenance.auto=false" in seen[0]


def test_a_git_timeout_is_reported(env, monkeypatch):
    repo = env[2]
    monkeypatch.setattr(git_repo, "GIT_TIMEOUT", 1)
    with pytest.raises(GitError, match="timed out"):
        repo.git("slow", config=("alias.slow=!sleep 30",))


def test_ssh_gives_up_instead_of_hanging():
    from notes_manager.config import Config
    from notes_manager.git_repo import Repo

    repo = Repo(Config(notes_dir=Path("/tmp"), token="x" * 40, ssh_key="/key"))
    ssh = repo._env["GIT_SSH_COMMAND"]
    assert "ConnectTimeout=15" in ssh and "ServerAliveInterval=10" in ssh and "ServerAliveCountMax=3" in ssh


def test_count_zombies_sees_an_uncollected_child():
    base = count_zombies()
    child = subprocess.Popen(["true"])
    try:
        assert wait_until(lambda: count_zombies() > base), "a finished, uncollected child is a zombie"
    finally:
        child.wait()
    assert wait_until(lambda: count_zombies() <= base)


def test_the_sync_loop_warns_when_zombies_pile_up(env, monkeypatch, caplog):
    _, store, repo, *_ = env
    monkeypatch.setattr(sync, "count_zombies", lambda: 7)
    stop = threading.Event()
    worker = threading.Thread(target=sync.sync_loop, args=(repo, store, 0.05, stop))
    with caplog.at_level(logging.WARNING, logger="notes-manager"):
        worker.start()
        assert wait_until(lambda: "7 terminated processes" in caplog.text)
    stop.set()
    worker.join(timeout=5)
