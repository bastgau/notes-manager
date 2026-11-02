"""The note writing tools: registered only when NOTES_WRITE is enabled.

Changes are committed with the configured identity and pushed straight to the main
branch, so the next read (and the next edit of the same note) sees them. Every tool
accepts ``dry_run`` to preview the diff without committing, and ``expected_revision``
(the ``revision`` returned by get_doc) to refuse the write if the note changed since.
"""

import uuid
from pathlib import Path

from mcp.server.fastmcp import FastMCP

from notes_manager.git_repo import Repo
from notes_manager.markdown import insert_in_section
from notes_manager.note import Note, blob_revision, bump_updated, replace_meta_line, split_note
from notes_manager.store import Store
from notes_manager.tools.common import check_revision, edit_note, finish
from notes_manager.utils import check_id
from notes_manager.validation import (
    validate_body,
    validate_new_note,
    validate_status,
    validate_tags,
)


def register_write_tools(mcp: FastMCP, store: Store, repo: Repo) -> None:
    @mcp.tool()
    def write_doc(title: str, description: str, tags: list[str], status: str, body: str,
                  id: str | None = None, expected_revision: str | None = None,
                  dry_run: bool = False) -> dict:
        """Create a note (no id) or replace a whole note (with its id).

        To change a few lines, prefer patch_doc or append_doc, which do not need the
        whole body. The change is committed and pushed straight to the main branch and
        is readable immediately. Tags and status must be declared (see list_tags /
        list_statuses). The text is refused if it looks like a secret. There is no way
        to delete a note. When replacing, pass `expected_revision` (from get_doc) to
        refuse the write if the note changed meanwhile. With `dry_run` the diff is
        returned and nothing is written.
        """
        snap = store.snapshot
        validate_new_note(snap, title, description, tags, status, body)
        if id is None:
            if expected_revision:
                raise ValueError("expected_revision only applies when replacing a note (id given)")
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
        info: dict = {}

        def mutate(work: Path) -> None:
            target = work / "notes" / f"{note_id}.md"
            before = b""
            if verb == "update":
                if not target.is_file():
                    raise ValueError("note not found on the main branch")
                before = target.read_bytes()
                check_revision(blob_revision(before), expected_revision)
                info["previous_revision"] = blob_revision(before)
            target.parent.mkdir(exist_ok=True)
            data = text.encode("utf-8")
            target.write_bytes(data)
            info.update(revision=blob_revision(data), bytes_before=len(before), bytes_after=len(data))

        published = repo.publish(f'docs: {verb} note "{title[:60]}"', mutate, dry_run=dry_run)
        return finish(store, repo, {"id": note_id, **info, **published}, dry_run)

    @mcp.tool()
    def patch_doc(id: str, old: str, new: str, replace_all: bool = False,
                  expected_revision: str | None = None, dry_run: bool = False) -> dict:
        """Replace an exact passage of a note's body, like an edit: no need to resend the note.

        `old` must appear in the body exactly once (add some surrounding context if it
        does not), unless `replace_all` is true. The front matter cannot be changed here:
        use set_doc_status, set_doc_tags or write_doc. The `updated` date is refreshed.
        Pass `expected_revision` to refuse the edit if the note changed since you read it.
        """
        if not old:
            raise ValueError("old must not be empty")
        if old == new:
            raise ValueError("old and new are identical")

        def transform(text: str) -> str:
            prefix, body = split_note(text)
            count = body.count(old)
            if count == 0:
                raise ValueError("old text not found in the body (it must match exactly, "
                                 "including spaces and line breaks; read the note again)")
            if count > 1 and not replace_all:
                raise ValueError(f"old text found {count} times; add surrounding context "
                                 "to make it unique, or pass replace_all=true")
            new_body = body.replace(old, new) if replace_all else body.replace(old, new, 1)
            validate_body(new_body)
            return bump_updated(prefix) + new_body

        return edit_note(store, repo, id, "docs: edit note", transform, expected_revision, dry_run)

    @mcp.tool()
    def append_doc(id: str, text: str, section: str | None = None,
                   expected_revision: str | None = None, dry_run: bool = False) -> dict:
        """Add text at the end of a note, or at the end of one of its sections.

        `section` is the title of a heading (case and accents ignored, '#' optional);
        the text goes just before the next heading of the same or a higher level. When
        the section is unknown or ambiguous, the error lists the headings. Headings
        inside code blocks are ignored. The `updated` date is refreshed.
        """
        if not text.strip():
            raise ValueError("text must not be empty")

        def transform(current: str) -> str:
            prefix, body = split_note(current)
            new_body = insert_in_section(body, text, section)
            validate_body(new_body)
            return bump_updated(prefix) + new_body

        message = "docs: append to note" + (f" ({section[:40]})" if section else "")
        return edit_note(store, repo, id, message, transform, expected_revision, dry_run)

    @mcp.tool()
    def set_doc_status(id: str, status: str, expected_revision: str | None = None,
                       dry_run: bool = False) -> dict:
        """Change the status of a note without touching its body.

        The status must be declared (see list_statuses; declare_status adds one).
        """
        validate_status(store.snapshot, status)
        current = store.snapshot.notes.get(check_id(id))
        if current and current.status == status:
            raise ValueError(f"the status is already '{status}'")

        def transform(text: str) -> str:
            prefix, body = split_note(text)
            return bump_updated(replace_meta_line(prefix, "status", status)) + body

        return edit_note(store, repo, id, f"docs: set status to {status}", transform,
                         expected_revision, dry_run)

    @mcp.tool()
    def set_doc_tags(id: str, tags: list[str], expected_revision: str | None = None,
                     dry_run: bool = False) -> dict:
        """Replace the tags of a note without touching its body.

        Tags must be declared (see list_tags; declare_tag adds one); 1 to 8 distinct tags.
        """
        validate_tags(store.snapshot, tags)
        current = store.snapshot.notes.get(check_id(id))
        if current and current.tags == tags:
            raise ValueError("the note already has these tags")

        def transform(text: str) -> str:
            prefix, body = split_note(text)
            return bump_updated(replace_meta_line(prefix, "tags", f"[{', '.join(tags)}]")) + body

        return edit_note(store, repo, id, "docs: set tags", transform, expected_revision, dry_run)
