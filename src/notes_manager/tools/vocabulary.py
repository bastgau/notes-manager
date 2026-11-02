"""Tools that maintain tags.yaml and status.yaml: registered only when NOTES_WRITE is enabled.

Tags and statuses share the same structure, so the operations are written once and
parameterized by a :class:`Vocabulary`.
"""

from dataclasses import dataclass
from pathlib import Path
from typing import Callable

from mcp.server.fastmcp import FastMCP

from notes_manager.constants import NAME_RE
from notes_manager.git_repo import Repo
from notes_manager.note import Note
from notes_manager.rewrite import (
    drop_vocab_entry,
    rename_vocab_key,
    rewrite_status_in_text,
    rewrite_tag_in_text,
    upsert_vocab_entry,
)
from notes_manager.snapshot import Snapshot, parse_vocabulary
from notes_manager.store import Store
from notes_manager.tools.common import refresh
from notes_manager.utils import suggest
from notes_manager.validation import validate_vocab_entry


@dataclass(frozen=True)
class Vocabulary:
    kind: str  # "tag" or "status"
    file: str
    declared: Callable[[Snapshot], dict[str, str]]
    used_by: Callable[[Note], list[str]]
    rename_in_note: Callable[[str, str, str], str]


TAGS = Vocabulary("tag", "tags.yaml", lambda s: s.tags, lambda n: n.tags, rewrite_tag_in_text)
STATUSES = Vocabulary("status", "status.yaml", lambda s: s.statuses, lambda n: [n.status],
                      rewrite_status_in_text)


def _users(work: Path, vocab: Vocabulary, name: str) -> list[str]:
    """Ids of the notes that use ``name``, read from the freshly fetched worktree."""
    found = []
    for path in sorted((work / "notes").glob("*.md")):
        note = Note.parse(path.stem, path.read_text(encoding="utf-8"))
        if name in vocab.used_by(note):
            found.append(path.stem)
    return found


def _require_declared(vocab: Vocabulary, store: Store, name: str) -> None:
    declared = vocab.declared(store.snapshot)
    if name not in declared:
        raise ValueError(f"unknown {vocab.kind} '{name}'.{suggest(name, declared)}")


def set_entry(vocab: Vocabulary, store: Store, repo: Repo, name: str, description: str) -> dict:
    validate_vocab_entry(vocab.kind, name, description)
    existed = name in vocab.declared(store.snapshot)

    def mutate(work: Path) -> None:
        path = work / vocab.file
        before = path.read_text(encoding="utf-8") if path.is_file() else ""
        after = upsert_vocab_entry(before, name, description)
        if parse_vocabulary(after) != {**parse_vocabulary(before), name: description}:
            raise ValueError(f"could not edit {vocab.file} safely; simplify the description")
        path.write_text(after, encoding="utf-8")

    verb = "describe" if existed else "declare"
    result = repo.publish(f"docs: {verb} {vocab.kind} {name}", mutate)
    return refresh(store, repo, {vocab.kind: name, "created": not existed, **result})


def remove_entry(vocab: Vocabulary, store: Store, repo: Repo, name: str) -> dict:
    _require_declared(vocab, store, name)

    def mutate(work: Path) -> None:
        users = _users(work, vocab, name)
        if users:
            raise ValueError(
                f"{vocab.kind} '{name}' is used by {len(users)} note(s); rename it or merge it "
                f"into another one with rename_{vocab.kind} instead")
        path = work / vocab.file
        path.write_text(drop_vocab_entry(path.read_text(encoding="utf-8"), name), encoding="utf-8")

    result = repo.publish(f"docs: remove unused {vocab.kind} {name}", mutate)
    return refresh(store, repo, {vocab.kind: name, "removed": True, **result})


def rename_entry(vocab: Vocabulary, store: Store, repo: Repo, old: str, new: str) -> dict:
    _require_declared(vocab, store, old)
    if not NAME_RE.match(new):
        raise ValueError(f"new {vocab.kind} must be lowercase kebab-case")
    if old == new:
        raise ValueError("old and new are identical")
    merge = new in vocab.declared(store.snapshot)

    def mutate(work: Path) -> None:
        path = work / vocab.file
        path.write_text(rename_vocab_key(path.read_text(encoding="utf-8"), old, new, merge),
                        encoding="utf-8")
        for note_path in (work / "notes").glob("*.md"):
            text = note_path.read_text(encoding="utf-8")
            updated = vocab.rename_in_note(text, old, new)
            if updated != text:
                note_path.write_text(updated, encoding="utf-8")

    verb = "merge" if merge else "rename"
    message = (f"refactor: merge {vocab.kind} {old} into {new}" if merge
               else f"refactor: rename {vocab.kind} {old} to {new}")
    result = repo.publish(message, mutate)
    return refresh(store, repo, {"old": old, "new": new, "merged": merge, **result})


def register_vocabulary_tools(mcp: FastMCP, store: Store, repo: Repo) -> None:
    @mcp.tool()
    def set_tag(tag: str, description: str) -> dict:
        """Declare a tag in tags.yaml, or update the description of an existing one.

        The tag must be lowercase kebab-case, singular and in English. The change is
        pushed to the main branch and can be used by write_doc right away.
        """
        return set_entry(TAGS, store, repo, tag, description)

    @mcp.tool()
    def set_status(status: str, description: str) -> dict:
        """Declare a status in status.yaml, or update the description of an existing one."""
        return set_entry(STATUSES, store, repo, status, description)

    @mcp.tool()
    def remove_tag(tag: str) -> dict:
        """Remove a tag from tags.yaml. Refused while any note still uses it.

        Use rename_tag to merge a tag that is in use into another one.
        """
        return remove_entry(TAGS, store, repo, tag)

    @mcp.tool()
    def remove_status(status: str) -> dict:
        """Remove a status from status.yaml. Refused while any note still uses it."""
        return remove_entry(STATUSES, store, repo, status)

    @mcp.tool()
    def rename_tag(old: str, new: str) -> dict:
        """Rename a tag everywhere, or merge it into an existing tag.

        Rewrites tags.yaml and every note using the old tag, in one commit pushed to
        the main branch. If `new` already exists, `old` is merged into it and removed
        from tags.yaml.
        """
        return rename_entry(TAGS, store, repo, old, new)

    @mcp.tool()
    def rename_status(old: str, new: str) -> dict:
        """Rename a status everywhere, or merge it into an existing status.

        Rewrites status.yaml and every note using the old status, in one commit pushed
        to the main branch. If `new` already exists, `old` is merged into it.
        """
        return rename_entry(STATUSES, store, repo, old, new)
