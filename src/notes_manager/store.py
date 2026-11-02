"""The in-memory index of the notes and the search over it."""

import logging
import re
from pathlib import Path

from notes_manager.constants import DATE_RE
from notes_manager.markdown import parse_headings, section_of_line
from notes_manager.note import Note
from notes_manager.snapshot import Snapshot
from notes_manager.utils import normalize

log = logging.getLogger("notes-manager")

SNIPPET_CHARS = 240


def token_forms(token: str) -> tuple[str, ...]:
    """A search word and its singular: 'pollens' also matches 'pollen'."""
    return (token, token[:-1]) if len(token) > 3 and token.endswith("s") else (token,)


class Store:
    """Holds the current immutable snapshot of the notes."""

    def __init__(self, root: Path) -> None:
        self.root = root
        self.snapshot = Snapshot.load(root)

    def reload(self) -> None:
        self.snapshot = Snapshot.load(self.root)
        log.info("indexed %d notes", len(self.snapshot.notes))

    def search(self, query: str, tag: str | None, status: str | None, limit: int) -> list[dict]:
        snap = self.snapshot
        tokens = re.findall(r"\w+", normalize(query))
        if not tokens:
            raise ValueError("query must contain at least one word")
        results: list[tuple[int, str, Note]] = []
        for note in snap.notes.values():
            if tag and tag not in note.tags:
                continue
            if status and status != note.status:
                continue
            title, desc, tags, body = snap.normalized[note.id]
            score = 0
            for token in tokens:
                forms = token_forms(token)
                token_score = 0
                if any(f in title for f in forms):
                    token_score += 5
                if any(f in desc for f in forms):
                    token_score += 3
                if any(f in tags for f in forms):
                    token_score += 4
                if any(f in body for f in forms):
                    token_score += 1
                if token_score == 0:
                    score = 0
                    break
                score += token_score
            if score:
                results.append((score, note.updated, note))
        results.sort(key=lambda r: (r[0], r[1]), reverse=True)
        out = []
        for score, _, note in results[:limit]:
            out.append({**note.summary(), "score": score, "matched_in": self._matched_in(note, tokens),
                        **self._passage(note, tokens)})
        return out

    def _matched_in(self, note: Note, tokens: list[str]) -> list[str]:
        """The fields (title, description, tags, body) where at least one search word occurs."""
        fields = dict(zip(("title", "description", "tags", "body"), self.snapshot.normalized[note.id]))
        return [name for name, text in fields.items()
                if any(f in text for t in tokens for f in token_forms(t))]

    def _passage(self, note: Note, tokens: list[str]) -> dict:
        """The part of the body that best answers the query, and where it sits in the note.

        The best line is the one containing the most search words; the passage is that
        line and the lines that follow it up to the next blank line, cut at a word.
        """
        lines = note.body.split("\n")
        best, best_score = -1, 0
        for index, line in enumerate(lines):
            normalized = normalize(line)
            score = sum(1 for t in tokens if any(f in normalized for f in token_forms(t)))
            if score > best_score:
                best, best_score = index, score
        if best < 0:
            return {"snippet": "", "section": "", "line": None}
        parts = []
        for line in lines[best:]:
            if not line.strip():
                break
            parts.append(line.strip())
            if sum(len(p) + 1 for p in parts) >= SNIPPET_CHARS:
                break
        heading = section_of_line(parse_headings(lines), best)
        return {"snippet": self._window(" ".join(parts), tokens),
                "section": heading.title if heading else "", "line": best + 1}

    @staticmethod
    def _window(text: str, tokens: list[str]) -> str:
        """``text`` as is when short; otherwise a window around the first match, cut at words."""
        if len(text) <= SNIPPET_CHARS:
            return text
        normalized = normalize(text)
        found = [normalized.find(f) for t in tokens for f in token_forms(t)]
        match = min((i for i in found if i >= 0), default=0)
        start = max(0, match - SNIPPET_CHARS // 4)
        if start > 0:
            start = text.rfind(" ", 0, start) + 1
        end = start + SNIPPET_CHARS
        if end < len(text):
            cut = text.rfind(" ", start, end)
            end = cut if cut > match else end
        return ("…" if start > 0 else "") + text[start:end].strip() + ("…" if end < len(text) else "")

    def list_docs(self, tag: str | None = None, status: str | None = None,
                  updated_since: str | None = None, updated_until: str | None = None,
                  sort: str = "updated", limit: int | None = None) -> list[dict]:
        for name, value in (("updated_since", updated_since), ("updated_until", updated_until)):
            if value and not DATE_RE.match(value):
                raise ValueError(f"{name} must be a date written YYYY-MM-DD")
        if sort not in ("updated", "title"):
            raise ValueError("sort must be 'updated' (most recent first) or 'title'")
        notes = [
            n
            for n in self.snapshot.notes.values()
            if (not tag or tag in n.tags) and (not status or status == n.status)
            and (not updated_since or n.updated >= updated_since)
            and (not updated_until or n.updated <= updated_until)
        ]
        if sort == "title":
            notes.sort(key=lambda n: normalize(n.title))
        else:
            notes.sort(key=lambda n: (n.updated, n.title), reverse=True)
        return [n.summary() for n in (notes[:limit] if limit else notes)]
