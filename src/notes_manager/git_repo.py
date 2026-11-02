"""Git operations: the read-only mirror and the inbox branches."""

import datetime
import os
import re
import shutil
import subprocess
import tempfile
import threading
import uuid
from pathlib import Path
from typing import Callable

from notes_manager.config import Config
from notes_manager.utils import normalize


class GitError(RuntimeError):
    pass


class Repo:
    """Thin wrapper around the git CLI for the notes mirror and inbox branches."""

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

    def compare_url(self, branch: str) -> str:
        match = re.search(r"github\.com[:/](.+?)(?:\.git)?$", self.cfg.repo_url)
        if not match:
            return ""
        return f"https://github.com/{match.group(1)}/compare/{self.cfg.branch}...{branch}"

    def push_inbox(self, hint: str, message: str, mutate: Callable[[Path], None]) -> dict:
        """Apply ``mutate`` on a throw-away worktree and push it to an inbox branch."""
        slug = re.sub(r"[^a-z0-9]+", "-", normalize(hint)).strip("-")[:40] or "note"
        stamp = datetime.datetime.now(datetime.UTC).strftime("%Y%m%d-%H%M%S")
        branch = f"inbox/{stamp}-{slug}-{uuid.uuid4().hex[:4]}"
        assert branch.startswith("inbox/")
        identity = (f"user.name={self.cfg.git_name}", f"user.email={self.cfg.git_email}")
        with self._write_lock:
            self.git("fetch", "--quiet", "origin", self.cfg.branch)
            tmp = Path(tempfile.mkdtemp(prefix="notes-wt-"))
            work = tmp / "wt"
            try:
                self.git("worktree", "add", "--quiet", "--detach", str(work),
                         f"origin/{self.cfg.branch}")
                mutate(work)
                self.git("add", "-A", cwd=work)
                if not self.git("status", "--porcelain", cwd=work):
                    raise ValueError("nothing to change")
                self.git("commit", "--quiet", "-m", message, cwd=work, config=identity)
                sha = self.git("rev-parse", "HEAD", cwd=work)
                self.git("push", "--quiet", "origin", f"HEAD:refs/heads/{branch}", cwd=work)
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
        return {"branch": branch, "commit": sha[:12], "compare_url": self.compare_url(branch)}
