"""A single note: parsing and serialization of its front matter."""

import datetime
import hashlib
import json
import re
from dataclasses import dataclass, field

import yaml

from notes_manager.constants import FRONT_MATTER_RE, REQUIRED_FIELDS


def blob_revision(data: bytes) -> str:
    """Git blob hash of a file's bytes, shortened: it changes if and only if the file changes."""
    return hashlib.sha1(b"blob %d\0" % len(data) + data).hexdigest()[:12]


def split_note(text: str) -> tuple[str, str]:
    """Split a note file into (front matter including its delimiters, body)."""
    match = FRONT_MATTER_RE.match(text)
    if not match:
        raise ValueError("the note has no front matter")
    return text[: match.start(2)], match.group(2)


def today() -> str:
    return datetime.datetime.now(datetime.UTC).date().isoformat()


def bump_updated(prefix: str) -> str:
    """Set the ``updated`` field of a front matter to today's UTC date."""
    return re.sub(r"^updated: .*$", f"updated: {today()}", prefix, count=1, flags=re.M)


def replace_meta_line(prefix: str, name: str, value: str) -> str:
    """Replace the ``name: ...`` line of a front matter."""
    return re.sub(rf"^{re.escape(name)}: .*$", lambda _: f"{name}: {value}", prefix, count=1, flags=re.M)


@dataclass
class Note:
    id: str
    title: str = ""
    description: str = ""
    tags: list[str] = field(default_factory=list)
    status: str = ""
    updated: str = ""
    body: str = ""
    revision: str = ""
    problems: list[str] = field(default_factory=list)

    def summary(self) -> dict:
        return {
            "id": self.id,
            "revision": self.revision,
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
        updated = today()
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
