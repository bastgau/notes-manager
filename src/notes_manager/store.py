"""The in-memory index of the notes and the search over it."""

import logging
import re
from pathlib import Path

from notes_manager.note import Note
from notes_manager.snapshot import Snapshot
from notes_manager.utils import normalize

log = logging.getLogger("notes-manager")


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
                # Tolerate a plural: 'pollens' also matches 'pollen'.
                forms = (token, token[:-1]) if len(token) > 3 and token.endswith("s") else (token,)
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
            item = note.summary()
            item["score"] = score
            item["snippet"] = self._snippet(note, tokens)
            out.append(item)
        return out

    def _snippet(self, note: Note, tokens: list[str]) -> str:
        norm_body = self.snapshot.normalized[note.id][3]
        for token in tokens:
            pos = norm_body.find(token)
            if pos >= 0:
                start = max(0, pos - 80)
                return " ".join(note.body[start : pos + 120].split())
        return ""

    def list_docs(self, tag: str | None, status: str | None) -> list[dict]:
        notes = [
            n
            for n in self.snapshot.notes.values()
            if (not tag or tag in n.tags) and (not status or status == n.status)
        ]
        notes.sort(key=lambda n: (n.updated, n.title), reverse=True)
        return [n.summary() for n in notes]
