"""Information about the running server."""

import time

from mcp.server.fastmcp import FastMCP

from notes_manager.buildinfo import STARTED, build_info
from notes_manager.config import Config
from notes_manager.git_repo import GitError, Repo
from notes_manager.processes import count_zombies
from notes_manager.store import Store


def register_info_tools(mcp: FastMCP, cfg: Config, store: Store, repo: Repo | None) -> None:
    @mcp.tool()
    def server_info() -> dict:
        """Which notes-manager is this, and is it healthy?

        Returns the `version` (the release it was built from) and the `commit`, whether write
        tools are enabled, how many notes are indexed, the commit the mirror is at, the uptime,
        and `zombie_processes` (terminated processes nobody collected: it should stay at 0).
        """
        mirror = None
        if repo is not None:
            try:
                mirror = repo.git("rev-parse", "--short=12", "HEAD")
            except GitError:
                pass
        return {
            **build_info(),
            "write_enabled": cfg.write,
            "branch": cfg.branch,
            "notes": len(store.snapshot.notes),
            "mirror_commit": mirror,
            "uptime_seconds": int(time.time() - STARTED),
            "zombie_processes": count_zombies(),
        }
