"""Validation of the fields of a note submitted through a write tool."""

from notes_manager.constants import (
    CONTROL_RE,
    MAX_BODY_BYTES,
    MAX_DESCRIPTION,
    MAX_TAGS,
    MAX_TITLE,
    MAX_VOCAB_DESCRIPTION,
    NAME_RE,
)
from notes_manager.snapshot import Snapshot
from notes_manager.utils import find_secret, suggest


def validate_new_note(snap: Snapshot, title: str, description: str, tags: list[str],
                      status: str, body: str) -> None:
    """Raise ``ValueError`` with an actionable message if the note is not acceptable."""
    if not title.strip() or len(title) > MAX_TITLE or CONTROL_RE.search(title):
        raise ValueError(f"title must be 1-{MAX_TITLE} characters on a single line")
    if not description.strip() or len(description) > MAX_DESCRIPTION or CONTROL_RE.search(description):
        raise ValueError(f"description must be 1-{MAX_DESCRIPTION} characters on a single line")
    if not tags or len(tags) > MAX_TAGS or len(set(tags)) != len(tags):
        raise ValueError(f"tags must be a list of 1-{MAX_TAGS} distinct values")
    for tag in tags:
        if tag not in snap.tags:
            raise ValueError(f"undeclared tag '{tag}'.{suggest(tag, snap.tags)} See list_tags.")
    if status not in snap.statuses:
        raise ValueError(f"undeclared status '{status}'.{suggest(status, snap.statuses)} "
                         f"Allowed: {', '.join(snap.statuses)}")
    if len(body.encode("utf-8")) > MAX_BODY_BYTES:
        raise ValueError(f"body is larger than {MAX_BODY_BYTES} bytes")
    secret = find_secret(f"{title}\n{description}\n{body}")
    if secret:
        raise ValueError(f"refused: the text looks like it contains a secret ({secret})")


def validate_vocab_entry(kind: str, name: str, description: str) -> None:
    """Check a tag / status name and its description before writing them to the vocabulary."""
    if not NAME_RE.match(name):
        raise ValueError(f"{kind} must be lowercase kebab-case (letters, digits and single dashes)")
    if not description.strip() or len(description) > MAX_VOCAB_DESCRIPTION or CONTROL_RE.search(description):
        raise ValueError(f"description must be 1-{MAX_VOCAB_DESCRIPTION} characters on a single line")
    if find_secret(description):
        raise ValueError("refused: the description looks like it contains a secret")
