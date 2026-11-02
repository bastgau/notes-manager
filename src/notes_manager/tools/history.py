"""Read-only access to the Git history of the notes."""

from mcp.server.fastmcp import FastMCP

from notes_manager.git_repo import Repo
from notes_manager.note import Note, blob_revision
from notes_manager.store import Store
from notes_manager.utils import check_id

MAX_HISTORY = 100


def register_history_tools(mcp: FastMCP, store: Store, repo: Repo) -> None:
    def note_path(note_id: str) -> tuple[str, str]:
        note_id = check_id(note_id)
        if note_id not in store.snapshot.notes:
            raise ValueError("note not found")
        return note_id, f"notes/{note_id}.md"

    @mcp.tool()
    def get_doc_history(id: str, limit: int = 20) -> list[dict]:
        """List the commits that changed a note, newest first.

        Each entry has the `commit`, its `date`, `author`, `subject` and the `revision` of
        the note it produced; `current` marks the one that is the note now. Read an old
        version with get_doc_version and go back to it with restore_doc.
        """
        note_id, path = note_path(id)
        current = store.snapshot.notes[note_id].revision
        history = repo.history(path, max(1, min(limit, MAX_HISTORY)))
        return [{**entry, "current": entry["revision"] == current} for entry in history]

    @mcp.tool()
    def get_doc_version(id: str, commit: str) -> dict:
        """Return a note as it was at a given commit (from get_doc_history), without changing anything."""
        note_id, path = note_path(id)
        full = repo.resolve_commit(commit)
        text = repo.read_at(full, path)
        note = Note.parse(note_id, text)
        note.revision = blob_revision(text.encode("utf-8"))
        return {**note.summary(), "commit": full[:12], "related": note.related, "body": note.body}
