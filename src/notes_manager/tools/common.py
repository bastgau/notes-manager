"""Helpers shared by the write tools."""

from collections.abc import Callable
from pathlib import Path

from notes_manager.git_repo import Repo
from notes_manager.note import Note, blob_revision
from notes_manager.store import Store
from notes_manager.utils import check_id


def refresh(store: Store, repo: Repo, result: dict) -> dict:
    """Refresh the mirror and the index after a push, so the change is readable right away."""
    if repo.sync():
        store.reload()
    return result


def finish(store: Store, repo: Repo, result: dict, dry_run: bool) -> dict:
    """A previewed change leaves everything as it was; a pushed one refreshes the index."""
    return result if dry_run else refresh(store, repo, result)


def check_revision(current: str, expected: str | None) -> None:
    """Refuse the write when the note is no longer the version the caller has read."""
    if not expected:
        return
    expected = expected.strip().lower()
    if len(expected) < 7 or not current.startswith(expected):
        raise ValueError(
            f"the note changed since you read it (revision {current}, you expected {expected}); "
            "read it again with get_doc and redo your change")


def edit_note(store: Store, repo: Repo, note_id: str, message: str,
              transform: Callable[[str], str], expected_revision: str | None = None,
              dry_run: bool = False) -> dict:
    """Apply ``transform`` to the text of an existing note and publish the result.

    The note is re-read from the freshly fetched tip of the main branch, so the
    revision check and the edit see the latest version even if the mirror is late.
    """
    note_id = check_id(note_id)
    if note_id not in store.snapshot.notes:
        raise ValueError("note not found")
    info: dict = {}

    def mutate(work: Path) -> None:
        path = work / "notes" / f"{note_id}.md"
        if not path.is_file():
            raise ValueError("note not found on the main branch")
        data = path.read_bytes()
        current = blob_revision(data)
        check_revision(current, expected_revision)
        try:
            text = data.decode("utf-8")
        except UnicodeDecodeError:
            raise ValueError("the note is not valid UTF-8") from None
        new_text = transform(text)
        if new_text == text:
            raise ValueError("nothing to change")
        problems = Note.parse(note_id, new_text).problems
        if problems:
            raise ValueError("the change would make the note invalid: " + "; ".join(problems))
        new_data = new_text.encode("utf-8")
        path.write_bytes(new_data)
        info.update(previous_revision=current, revision=blob_revision(new_data),
                    bytes_before=len(data), bytes_after=len(new_data))

    published = repo.publish(message, mutate, dry_run=dry_run)
    return finish(store, repo, {"id": note_id, **info, **published}, dry_run)
