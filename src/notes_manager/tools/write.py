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
from notes_manager.note import (
    Note,
    blob_revision,
    bump_updated,
    replace_meta_line,
    set_related_line,
    split_note,
)
from notes_manager.store import Store
from notes_manager.tools.common import check_revision, edit_note, finish
from notes_manager.utils import check_id
from notes_manager.validation import (
    validate_body,
    validate_new_note,
    validate_related,
    validate_status,
    validate_tags,
)


def register_write_tools(mcp: FastMCP, store: Store, repo: Repo) -> None:
    @mcp.tool()
    def write_doc(title: str, description: str, tags: list[str], status: str, body: str,
                  id: str | None = None, related: list[str] | None = None,
                  expected_revision: str | None = None, dry_run: bool = False) -> dict:
        """Create a note (no id) or replace a whole note (with its id).

        To change a few lines, prefer patch_doc or append_doc, which do not need the
        whole body. The change is committed and pushed straight to the main branch and
        is readable immediately. Tags and status must be declared (see list_tags /
        list_statuses). The text is refused if it looks like a secret. There is no way
        to delete a note. `related` is a list of ids of related notes; when replacing a
        note, leave it out to keep the existing links. When replacing, pass
        `expected_revision` (from get_doc) to refuse the write if the note changed
        meanwhile. With `dry_run` the diff is returned and nothing is written.
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
        if related is not None:
            validate_related(snap, note_id, related)
        info: dict = {}

        def mutate(work: Path) -> None:
            target = work / "notes" / f"{note_id}.md"
            before = b""
            links = related
            if verb == "update":
                if not target.is_file():
                    raise ValueError("note not found on the main branch")
                before = target.read_bytes()
                check_revision(blob_revision(before), expected_revision)
                info["previous_revision"] = blob_revision(before)
                if links is None:  # replacing a note keeps its links unless told otherwise
                    links = Note.parse(note_id, before.decode("utf-8", errors="replace")).related
            text = Note.render(title, description, tags, status, body, links)
            check = Note.parse(note_id, text)
            if (check.title, check.description, check.tags, check.status, check.related) != (
                title, description, tags, status, links or []
            ) or check.problems:
                raise ValueError("could not serialize the note safely; simplify the title/description")
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

    @mcp.tool()
    def set_doc_related(id: str, related: list[str], expected_revision: str | None = None,
                        dry_run: bool = False) -> dict:
        """Set the notes related to this one (their ids), without touching its body.

        Replaces the whole list; an empty list removes the links. The linked notes must
        exist. get_doc shows `related` and, for the other direction, `linked_from`.
        """
        note_id = check_id(id)
        validate_related(store.snapshot, note_id, related)
        current = store.snapshot.notes.get(note_id)
        if current and current.related == related:
            raise ValueError("the note already has these links")

        def transform(text: str) -> str:
            prefix, body = split_note(text)
            return bump_updated(set_related_line(prefix, related)) + body

        return edit_note(store, repo, note_id, "docs: set related notes", transform,
                         expected_revision, dry_run)

    @mcp.tool()
    def restore_doc(id: str, commit: str, expected_revision: str | None = None,
                    dry_run: bool = False) -> dict:
        """Go back to an earlier version of a note, as a new commit (the history is kept).

        `commit` comes from get_doc_history; get_doc_version shows what it contains. The
        tags and status of that version must still be declared. Use `dry_run` to see the
        diff first.
        """
        note_id = check_id(id)
        if note_id not in store.snapshot.notes:
            raise ValueError("note not found")
        full = repo.resolve_commit(commit)
        old_text = repo.read_at(full, f"notes/{note_id}.md")
        old = Note.parse(note_id, old_text)
        if old.problems:
            raise ValueError("that version is not a valid note: " + "; ".join(old.problems))
        validate_tags(store.snapshot, old.tags)
        validate_status(store.snapshot, old.status)

        def transform(current: str) -> str:
            old_prefix, old_body = split_note(old_text)
            cur_prefix, cur_body = split_note(current)
            restored = bump_updated(old_prefix) + old_body
            if restored == bump_updated(cur_prefix) + cur_body:
                raise ValueError("the note is already identical to that version")
            return restored

        message = f'docs: restore note "{old.title[:50]}" to {full[:7]}'
        result = edit_note(store, repo, note_id, message, transform, expected_revision, dry_run)
        return {**result, "restored_from": full[:12]}
