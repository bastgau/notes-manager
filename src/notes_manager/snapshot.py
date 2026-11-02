"""An immutable view of the notes and of the tag / status vocabularies."""

import logging
from dataclasses import dataclass, field
from pathlib import Path

import yaml

from notes_manager.constants import UUID_RE
from notes_manager.note import Note
from notes_manager.utils import normalize

log = logging.getLogger("notes-manager")


def parse_vocabulary(text: str) -> dict[str, str]:
    """Parse the text of tags.yaml / status.yaml into ``{name: description}``."""
    data = yaml.safe_load(text) or {}
    out: dict[str, str] = {}
    for name, value in data.items():
        out[str(name)] = str(value.get("description", "")) if isinstance(value, dict) else ""
    return out


def load_vocabulary(path: Path) -> dict[str, str]:
    """Read tags.yaml / status.yaml from disk; a missing file is an empty vocabulary."""
    return parse_vocabulary(path.read_text(encoding="utf-8")) if path.is_file() else {}


@dataclass
class Snapshot:
    notes: dict[str, Note]
    tags: dict[str, str]
    statuses: dict[str, str]
    # Normalized (title, description, tags, body) per note id, for searching.
    normalized: dict[str, tuple[str, str, str, str]] = field(default_factory=dict)

    def __post_init__(self) -> None:
        for n in self.notes.values():
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
                notes[path.stem] = Note.parse(path.stem, path.read_text(encoding="utf-8"))
        return cls(
            notes=notes,
            tags=load_vocabulary(root / "tags.yaml"),
            statuses=load_vocabulary(root / "status.yaml"),
        )

    def problems(self) -> list[dict]:
        """Notes with missing fields or with tags / statuses that are not declared."""
        found: list[dict] = []
        for n in self.notes.values():
            issues = list(n.problems)
            issues += [f"undeclared tag: {t}" for t in n.tags if t not in self.tags]
            if n.status and n.status not in self.statuses:
                issues.append(f"undeclared status: {n.status}")
            if issues:
                found.append({"id": n.id, "title": n.title, "problems": issues})
        return found
