"""Write tools: registered only when NOTES_WRITE is enabled.

Every change goes to a new ``inbox/*`` branch, never to the main branch.
"""

import uuid
from pathlib import Path

from mcp.server.fastmcp import FastMCP

from notes_manager.constants import NAME_RE
from notes_manager.git_repo import Repo
from notes_manager.note import Note
from notes_manager.rewrite import rewrite_tag_in_text, rewrite_tags_yaml
from notes_manager.store import Store
from notes_manager.utils import check_id, suggest
from notes_manager.validation import validate_new_note

NEXT_STEP = "Review and merge the branch on GitHub; it is not on main yet."


def register_write_tools(mcp: FastMCP, store: Store, repo: Repo) -> None:
    @mcp.tool()
    def write_doc(title: str, description: str, tags: list[str], status: str, body: str,
                  id: str | None = None) -> dict:
        """Create a note (no id) or replace one (with its id).

        The change is committed to a new inbox/* branch and never to main: the
        owner reviews and merges it. Tags and status must be declared (see
        list_tags / list_statuses). The text is refused if it looks like a secret.
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

        result = repo.push_inbox(title, f'docs: {verb} note "{title[:60]}"', mutate)
        return {"id": note_id, **result, "next": NEXT_STEP}

    @mcp.tool()
    def rename_tag(old: str, new: str) -> dict:
        """Rename a tag everywhere, or merge it into an existing tag.

        Rewrites tags.yaml and every note using the old tag, in one commit on a
        new inbox/* branch (never main). If `new` already exists, `old` is merged
        into it and removed from tags.yaml.
        """
        snap = store.snapshot
        if old not in snap.tags:
            raise ValueError(f"unknown tag '{old}'.{suggest(old, snap.tags)}")
        if not NAME_RE.match(new):
            raise ValueError("new tag must be lowercase kebab-case")
        if old == new:
            raise ValueError("old and new are identical")
        merge = new in snap.tags

        def mutate(work: Path) -> None:
            vocab = work / "tags.yaml"
            vocab.write_text(
                rewrite_tags_yaml(vocab.read_text(encoding="utf-8"), old, new, merge),
                encoding="utf-8",
            )
            for path in (work / "notes").glob("*.md"):
                text = path.read_text(encoding="utf-8")
                updated = rewrite_tag_in_text(text, old, new)
                if updated != text:
                    path.write_text(updated, encoding="utf-8")

        if merge:
            verb, message = "merge", f"refactor: merge tag {old} into {new}"
        else:
            verb, message = "rename", f"refactor: rename tag {old} to {new}"
        result = repo.push_inbox(f"{verb}-{old}-{new}", message, mutate)
        return {"old": old, "new": new, "merged": merge, **result, "next": NEXT_STEP}
