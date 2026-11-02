"""Git operations: the read-only mirror and the publication of changes on main."""

import logging
import os
import re
import shutil
import tempfile
import threading
from pathlib import Path
from typing import Callable

from notes_manager.config import Config
from notes_manager.constants import COMMIT_RE
from notes_manager.processes import CommandTimeout, run_command

log = logging.getLogger("notes-manager")

MAX_PUSH_ATTEMPTS = 3
MAX_DIFF_CHARS = 20_000
GIT_TIMEOUT = 120
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
                f"-o UserKnownHostsFile={cfg.known_hosts} -o StrictHostKeyChecking=yes "
                "-o ConnectTimeout=15 -o ServerAliveInterval=10 -o ServerAliveCountMax=3"
            )
        self._env = env

    def git(self, *args: str, cwd: Path | None = None, config: tuple[str, ...] = (),
            strip: bool = True) -> str:
        # No background maintenance: a detached "git gc" would be an orphan of this process.
        cmd = ["git", "-c", "safe.directory=*", "-c", "gc.auto=0", "-c", "maintenance.auto=false"]
        for item in config:
            cmd += ["-c", item]
        cmd += list(args)
        try:
            proc = run_command(cmd, cwd=cwd or self.root, env=self._env, timeout=GIT_TIMEOUT)
        except CommandTimeout as exc:
            raise GitError(f"git {args[0]} {exc}") from None
        if proc.returncode != 0:
            raise GitError(f"git {args[0]} failed: {proc.stderr.strip()[:500]}")
        return proc.stdout.strip() if strip else proc.stdout

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

    def history(self, rel_path: str, limit: int) -> list[dict]:
        """The commits that changed a file, newest first, with the file revision each one produced."""
        out = self.git("log", f"-n{limit}", "--no-abbrev", "--raw", "--format=%x1e%H%x1f%an%x1f%aI%x1f%s",
                       f"origin/{self.cfg.branch}", "--", rel_path)
        commits = []
        for chunk in out.split("\x1e"):
            if not chunk.strip():
                continue
            header, _, raw = chunk.partition("\n")
            sha, author, date, subject = header.split("\x1f", 3)
            revision = ""
            for line in raw.splitlines():
                if line.startswith(":"):
                    revision = line.split()[3][:12]
            commits.append({"commit": sha[:12], "date": date, "author": author, "subject": subject,
                            "revision": revision})
        return commits

    def resolve_commit(self, ref: str) -> str:
        """Full id of a commit that belongs to the history of the main branch."""
        if not COMMIT_RE.match(ref.strip()):
            raise ValueError("commit must be a hexadecimal id of 7 to 40 characters, "
                             "as returned by get_doc_history")

        def verify() -> str:
            full = self.git("rev-parse", "--verify", "--quiet", f"{ref.strip()}^{{commit}}")
            self.git("merge-base", "--is-ancestor", full, f"origin/{self.cfg.branch}")
            return full

        try:
            return verify()
        except GitError:
            self.git("fetch", "--quiet", "origin", self.cfg.branch)  # the mirror may be late
        try:
            return verify()
        except GitError:
            raise ValueError("unknown commit, or not part of the history of the main branch") from None

    def read_at(self, commit: str, rel_path: str) -> str:
        """The text of a file as it was at a commit."""
        try:
            return self.git("show", f"{commit}:{rel_path}", strip=False)
        except GitError:
            raise ValueError("the note does not exist at that commit") from None

    def publish(self, message: str, mutate: Callable[[Path], None], dry_run: bool = False) -> dict:
        """Commit the change made by ``mutate`` and push it straight to the main branch.

        The change is made on a throw-away worktree based on the freshly fetched tip,
        so the mirror is never touched here. When the branch moved between the fetch
        and the push, the change is applied again on the new tip. With ``dry_run`` the
        change is only previewed: nothing is committed or pushed.
        """
        with self._write_lock:
            for attempt in range(1, MAX_PUSH_ATTEMPTS + 1):
                try:
                    return self._apply(message, mutate, dry_run)
                except GitError as exc:
                    if dry_run or attempt == MAX_PUSH_ATTEMPTS or not PUSH_RACE_RE.search(str(exc)):
                        raise
                    log.info("push rejected (attempt %d), retrying on the new tip", attempt)
        raise AssertionError("unreachable")

    def _apply(self, message: str, mutate: Callable[[Path], None], dry_run: bool) -> dict:
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
            changes = self._numstat(work)
            if dry_run:
                diff = self.git("diff", "--cached", "--no-color", cwd=work)
                if len(diff) > MAX_DIFF_CHARS:
                    diff = diff[:MAX_DIFF_CHARS] + "\n... (diff truncated)"
                return {"dry_run": True, "changes": changes, "diff": diff}
            self.git("commit", "--quiet", "-m", message, cwd=work, config=identity)
            sha = self.git("rev-parse", "HEAD", cwd=work)
            self.git("push", "--quiet", "origin", f"HEAD:refs/heads/{self.cfg.branch}", cwd=work)
            return {"branch": self.cfg.branch, "commit": sha[:12], "changes": changes}
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

    def _numstat(self, work: Path) -> list[dict]:
        """Lines added and removed per file in the staged change."""
        out = []
        for line in self.git("diff", "--cached", "--numstat", cwd=work).splitlines():
            added, removed, path = line.split("\t", 2)
            out.append({"path": path, "added": int(added) if added.isdigit() else None,
                        "removed": int(removed) if removed.isdigit() else None})
        return out
