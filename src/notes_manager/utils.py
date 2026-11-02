"""Small helpers with no state."""

import difflib
import unicodedata

from notes_manager.constants import SECRET_RE, UUID_RE


def normalize(text: str) -> str:
    """Lowercase and strip accents so that 'Résumé' matches 'resume'."""
    decomposed = unicodedata.normalize("NFD", text)
    return "".join(c for c in decomposed if not unicodedata.combining(c)).lower()


def find_secret(text: str) -> str | None:
    """Return the start of the first thing that looks like a secret, if any."""
    for match in SECRET_RE.finditer(text):
        value = match.group(0)
        # Placeholders such as ghp_xxxxxxxxxxxxxxxxxxxx are fine.
        if len(set(value.split("_", 1)[-1])) > 3:
            return value[:6] + "..."
    return None


def suggest(value: str, choices: dict[str, str]) -> str:
    """Return a ' Did you mean: ...?' hint, or an empty string."""
    close = difflib.get_close_matches(value, list(choices), n=3)
    return f" Did you mean: {', '.join(close)}?" if close else ""


def check_id(note_id: str) -> str:
    """Normalize a note id and reject anything that is not a lowercase uuid."""
    note_id = note_id.strip().lower()
    if not UUID_RE.match(note_id):
        raise ValueError("id must be a lowercase uuid, as returned by search or list_docs")
    return note_id
