"""Periodic synchronization of the mirror with the remote repository."""

import logging
import threading

from notes_manager.git_repo import Repo
from notes_manager.processes import count_zombies
from notes_manager.store import Store

log = logging.getLogger("notes-manager")

ZOMBIE_WARNING = 5


def sync_loop(repo: Repo, store: Store, interval: int, stop: threading.Event) -> None:
    """Fetch every ``interval`` seconds and re-index when the mirror moved."""
    while not stop.wait(interval):
        try:
            if repo.sync():
                store.reload()
        except Exception:  # keep serving the last good snapshot
            log.exception("sync failed")
        zombies = count_zombies()
        if zombies >= ZOMBIE_WARNING:
            log.warning("%d terminated processes were never collected: the container needs an init", zombies)
