"""Git operations: the read-only mirror and the publication of changes on main."""

import logging
import os
import re
import shutil
import subprocess
import tempfile
import threading
from pathlib import Path
from typing import Callable

from notes_manager.config import Config

log = logging.getLogger("notes-manager")

MAX_PUSH_ATTEMPTS = 3
# What git prints when the remote branch moved since our fetch.
PUSH_RACE_RE = re.compile(r"rejected|non-fast-forward|fetch first")


class GitError(RuntimeError):
    pass


class Repo:
    """Thin wrapper around the git CLI: mirror of the main branch and publication of changes."""

    def __init__(self, cfg: Config) -> None:
        self.cfg = cfg
        self.root = cfg.notes_dir
        self._write_lock = threading.Lock()
        env = dict(os.environ)
        env["GIT_TERMINAL_PROMPT"] = "0"
        env.setdefault("HOME", tempfile.gettempdir())
        if cfg.ssh_key:
            env["GIT_SSH_COMMAND"] = (
                f"ssh -i {cfg.ssh_key} -o IdentitiesOnly=yes -o BatchMode=yes "
                f"-o UserKnownHostsFile={cfg.known_hosts} -o StrictHostKeyChecking=yes"
            )
        self._env = env

    def git(self, *args: str, cwd: Path | None = None, config: tuple[str, ...] = ()) -> str:
        cmd = ["git", "-c", "safe.directory=*"]
        for item in config:
            cmd += ["-c", item]
        cmd += list(args)
        proc = subprocess.run(
            cmd, cwd=cwd or self.root, env=self._env, capture_output=True, text=True, timeout=120
        )
        if proc.returncode != 0:
            raise GitError(f"git {args[0]} failed: {proc.stderr.strip()[:500]}")
        return proc.stdout.strip()

    def ensure_clone(self) -> None:
        if (self.root / ".git").exists():
            return
        if not self.cfg.repo_url:
            raise SystemExit(f"{self.root} is not a git clone and NOTES_REPO_URL is not set")
        self.root.parent.mkdir(parents=True, exist_ok=True)
        self.git("clone", "--branch", self.cfg.branch, self.cfg.repo_url, str(self.root),
                 cwd=self.root.parent)

    def sync(self) -> bool:
        """Fast-forward the read-only mirror; return True when it changed."""
        branch = self.cfg.branch
        before = self.git("rev-parse", "HEAD")
        self.git("fetch", "--quiet", "origin", branch)
        after = self.git("rev-parse", f"origin/{branch}")
        if before == after:
            return False
        self.git("reset", "--quiet", "--hard", f"origin/{branch}")
        return True

    def publish(self, message: str, mutate: Callable[[Path], None]) -> dict:
        """Commit the change made by ``mutate`` and push it straight to the main branch.

        The change is made on a throw-away worktree based on the freshly fetched tip,
        so the mirror is never touched here. When the branch moved between the fetch
        and the push, the change is applied again on the new tip.
        """
        with self._write_lock:
            for attempt in range(1, MAX_PUSH_ATTEMPTS + 1):
                try:
                    sha = self._commit_and_push(message, mutate)
                    break
                except GitError as exc:
                    if attempt == MAX_PUSH_ATTEMPTS or not PUSH_RACE_RE.search(str(exc)):
                        raise
                    log.info("push rejected (attempt %d), retrying on the new tip", attempt)
        return {"branch": self.cfg.branch, "commit": sha[:12]}

    def _commit_and_push(self, message: str, mutate: Callable[[Path], None]) -> str:
        identity = (f"user.name={self.cfg.git_name}", f"user.email={self.cfg.git_email}")
        self.git("fetch", "--quiet", "origin", self.cfg.branch)
        tmp = Path(tempfile.mkdtemp(prefix="notes-wt-"))
        work = tmp / "wt"
        try:
            self.git("worktree", "add", "--quiet", "--detach", str(work), f"origin/{self.cfg.branch}")
            mutate(work)
            self.git("add", "-A", cwd=work)
            if not self.git("status", "--porcelain", cwd=work):
                raise ValueError("nothing to change")
            self.git("commit", "--quiet", "-m", message, cwd=work, config=identity)
            sha = self.git("rev-parse", "HEAD", cwd=work)
            self.git("push", "--quiet", "origin", f"HEAD:refs/heads/{self.cfg.branch}", cwd=work)
            return sha
        finally:
            try:
                self.git("worktree", "remove", "--force", str(work))
            except GitError:
                pass
            shutil.rmtree(tmp, ignore_errors=True)
            try:
                self.git("worktree", "prune")
            except GitError:
                pass
