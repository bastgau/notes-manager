"""The note writing tool: registered only when NOTES_WRITE is enabled.

Changes are committed with the configured identity and pushed straight to the main
branch, so the next read (and the next edit of the same note) sees them.
"""

import uuid
from pathlib import Path

from mcp.server.fastmcp import FastMCP

from notes_manager.git_repo import Repo
from notes_manager.note import Note
from notes_manager.store import Store
from notes_manager.tools.common import refresh
from notes_manager.utils import check_id
from notes_manager.validation import validate_new_note


def register_write_tools(mcp: FastMCP, store: Store, repo: Repo) -> None:
    @mcp.tool()
    def write_doc(title: str, description: str, tags: list[str], status: str, body: str,
                  id: str | None = None) -> dict:
        """Create a note (no id) or replace one (with its id).

        The change is committed and pushed straight to the main branch and is readable
        immediately. Tags and status must be declared (see list_tags / list_statuses).
        The text is refused if it looks like a secret. There is no way to delete a note.
        """
        snap = store.snapshot
        validate_new_note(snap, title, description, tags, status, body)
        if id is None:
            note_id, verb = str(uuid.uuid4()), "add"
        else:
            note_id, verb = check_id(id), "update"
            if note_id not in snap.notes:
                raise ValueError("note not found; omit id to create a new note")
        text = Note.render(title, description, tags, status, body)
        check = Note.parse(note_id, text)
        if (check.title, check.description, check.tags, check.status) != (
            title, description, tags, status
        ) or check.problems:
            raise ValueError("could not serialize the note safely; simplify the title/description")

        def mutate(work: Path) -> None:
            target = work / "notes" / f"{note_id}.md"
            if verb == "update" and not target.is_file():
                raise ValueError("note not found on the main branch")
            target.parent.mkdir(exist_ok=True)
            target.write_text(text, encoding="utf-8")

        result = repo.publish(f'docs: {verb} note "{title[:60]}"', mutate)
        return refresh(store, repo, {"id": note_id, **result})
