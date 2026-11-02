"""Helpers shared by the write tools."""

from notes_manager.git_repo import Repo
from notes_manager.store import Store


def refresh(store: Store, repo: Repo, result: dict) -> dict:
    """Refresh the mirror and the index after a push, so the change is readable right away."""
    if repo.sync():
        store.reload()
    return result
