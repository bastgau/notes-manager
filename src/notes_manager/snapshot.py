"""An immutable view of the notes and of the tag / status vocabularies."""

import datetime
import logging
from dataclasses import dataclass, field
from pathlib import Path

import yaml

from notes_manager.constants import MAX_DESCRIPTION, MAX_TAGS, UUID_RE
from notes_manager.note import Note, blob_revision
from notes_manager.utils import normalize

log = logging.getLogger("notes-manager")


def parse_vocabulary(text: str) -> dict[str, str]:
    """Parse the text of tags.yaml / status.yaml into ``{name: description}``."""
    data = yaml.safe_load(text) or {}
    if not isinstance(data, dict):
        raise ValueError("a vocabulary file must be a mapping of names to descriptions")
    out: dict[str, str] = {}
    for name, value in data.items():
        out[str(name)] = str(value.get("description", "")) if isinstance(value, dict) else ""
    return out


def load_vocabulary(path: Path) -> dict[str, str]:
    """Read tags.yaml / status.yaml from disk.

    A missing or unreadable file is an empty vocabulary: the server keeps running and
    validate_notes reports every tag or status as undeclared.
    """
    if not path.is_file():
        return {}
    try:
        return parse_vocabulary(path.read_text(encoding="utf-8"))
    except (yaml.YAMLError, ValueError) as exc:
        log.error("cannot read %s: %s", path.name, exc)
        return {}


@dataclass
class Snapshot:
    notes: dict[str, Note]
    tags: dict[str, str]
    statuses: dict[str, str]
    # Normalized (title, description, tags, body) per note id, for searching.
    normalized: dict[str, tuple[str, str, str, str]] = field(default_factory=dict)
    # Note id -> ids of the notes whose ``related`` field points to it.
    linked_from: dict[str, list[str]] = field(default_factory=dict)

    def __post_init__(self) -> None:
        for n in self.notes.values():
            for target in n.related:
                if target in self.notes and target != n.id:
                    self.linked_from.setdefault(target, []).append(n.id)
            self.normalized[n.id] = (
                normalize(n.title),
                normalize(n.description),
                normalize(" ".join(n.tags)),
                normalize(n.body),
            )

    @classmethod
    def load(cls, root: Path) -> "Snapshot":
        """Read every ``notes/<uuid>.md`` plus the vocabularies from a checkout."""
        notes: dict[str, Note] = {}
        folder = root / "notes"
        if folder.is_dir():
            for path in sorted(folder.glob("*.md")):
                if not UUID_RE.match(path.stem):
                    log.warning("ignoring %s: file name is not a lowercase uuid", path.name)
                    continue
                data = path.read_bytes()
                note = Note.parse(path.stem, data.decode("utf-8", errors="replace"))
                note.revision = blob_revision(data)
                notes[path.stem] = note
        return cls(
            notes=notes,
            tags=load_vocabulary(root / "tags.yaml"),
            statuses=load_vocabulary(root / "status.yaml"),
        )

    def title_of(self, note_id: str) -> str | None:
        note = self.notes.get(note_id)
        return note.title if note else None

    def problems(self) -> list[dict]:
        """Errors: notes with missing fields, undeclared tags / statuses or broken links."""
        found: list[dict] = []
        for n in self.notes.values():
            issues = list(n.problems)
            issues += [f"undeclared tag: {t}" for t in n.tags if t not in self.tags]
            if len(n.tags) > MAX_TAGS:
                issues.append(f"too many tags ({len(n.tags)}, at most {MAX_TAGS})")
            if n.status and n.status not in self.statuses:
                issues.append(f"undeclared status: {n.status}")
            if n.updated and not _is_date(n.updated):
                issues.append(f"updated is not a valid YYYY-MM-DD date: {n.updated}")
            for target in n.related:
                if target == n.id:
                    issues.append("related: the note links to itself")
                elif UUID_RE.match(target) and target not in self.notes:
                    issues.append(f"broken link: related note {target} does not exist")
            if len(set(n.related)) != len(n.related):
                issues.append("related: duplicate ids")
            if issues:
                found.append({"id": n.id, "title": n.title, "problems": issues})
        return found

    def warnings(self) -> list[dict]:
        """Things worth tidying that do not make a note invalid."""
        found: list[dict] = []
        used_tags = {t for n in self.notes.values() for t in n.tags}
        used_statuses = {n.status for n in self.notes.values()}
        for name in self.tags:
            if name not in used_tags:
                found.append({"kind": "unused tag", "name": name, "hint": "remove_tag, or use it"})
        for name in self.statuses:
            if name not in used_statuses:
                found.append({"kind": "unused status", "name": name, "hint": "remove_status, or use it"})
        for label, names in (("tags.yaml", list(self.tags)), ("status.yaml", list(self.statuses))):
            if names != sorted(names):
                found.append({"kind": "unsorted vocabulary", "name": label,
                              "hint": "entries should be in alphabetical order"})
        by_title: dict[str, list[str]] = {}
        for n in self.notes.values():
            by_title.setdefault(normalize(n.title.strip()), []).append(n.id)
        for ids in by_title.values():
            if len(ids) > 1 and self.notes[ids[0]].title.strip():
                found.append({"kind": "duplicate title", "name": self.notes[ids[0]].title, "ids": ids})
        for n in self.notes.values():
            if len(n.description) > MAX_DESCRIPTION:
                found.append({"kind": "long description", "id": n.id, "name": n.title,
                              "hint": f"{len(n.description)} characters, at most {MAX_DESCRIPTION}"})
        return found


def _is_date(value: str) -> bool:
    try:
        datetime.date.fromisoformat(value)
    except ValueError:
        return False
    return len(value) == 10
