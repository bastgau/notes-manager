"""A single note: parsing and serialization of its front matter."""

import datetime
import json
from dataclasses import dataclass, field

import yaml

from notes_manager.constants import FRONT_MATTER_RE, REQUIRED_FIELDS


@dataclass
class Note:
    id: str
    title: str = ""
    description: str = ""
    tags: list[str] = field(default_factory=list)
    status: str = ""
    updated: str = ""
    body: str = ""
    problems: list[str] = field(default_factory=list)

    def summary(self) -> dict:
        return {
            "id": self.id,
            "title": self.title,
            "description": self.description,
            "tags": self.tags,
            "status": self.status,
            "updated": self.updated,
        }

    @classmethod
    def parse(cls, note_id: str, text: str) -> "Note":
        """Parse a note file; problems are recorded on the note instead of raised."""
        note = cls(id=note_id)
        match = FRONT_MATTER_RE.match(text)
        if not match:
            note.problems.append("missing front matter")
            note.body = text
            return note
        try:
            meta = yaml.safe_load(match.group(1)) or {}
        except yaml.YAMLError as exc:
            note.problems.append(f"invalid front matter: {exc}")
            note.body = match.group(2)
            return note
        if not isinstance(meta, dict):
            note.problems.append("front matter is not a mapping")
            meta = {}
        for name in REQUIRED_FIELDS:
            if meta.get(name) in (None, "", []):
                note.problems.append(f"missing field: {name}")
        note.title = str(meta.get("title") or "")
        note.description = str(meta.get("description") or "")
        tags = meta.get("tags") or []
        note.tags = [str(t) for t in tags] if isinstance(tags, list) else []
        if not isinstance(tags, list):
            note.problems.append("tags must be a list")
        note.status = str(meta.get("status") or "")
        note.updated = str(meta.get("updated") or "")
        note.body = match.group(2).lstrip("\n")
        return note

    @staticmethod
    def render(title: str, description: str, tags: list[str], status: str, body: str) -> str:
        """Serialize a note to file text, stamping ``updated`` with today's UTC date."""
        updated = datetime.datetime.now(datetime.UTC).date().isoformat()
        return (
            "---\n"
            f"title: {json.dumps(title, ensure_ascii=False)}\n"
            f"description: {json.dumps(description, ensure_ascii=False)}\n"
            f"tags: [{', '.join(tags)}]\n"
            f"status: {status}\n"
            f"updated: {updated}\n"
            "---\n\n"
            f"{body.strip(chr(10))}\n"
        )
