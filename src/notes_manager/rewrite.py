"""Text rewriting of notes and of the vocabulary files (tags.yaml, status.yaml).

The vocabulary files are edited as text, not re-dumped, so that comments and the
order of the entries are preserved.
"""

import json
import re

_RESERVED = {"yes", "no", "true", "false", "null", "on", "off", "y", "n", "~"}


def rewrite_tag_in_text(text: str, old: str, new: str) -> str:
    """Replace ``old`` by ``new`` in the ``tags: [...]`` line of a note front matter."""

    def repl(m: re.Match) -> str:
        items = [t.strip() for t in m.group(1).split(",") if t.strip()]
        out: list[str] = []
        for t in items:
            t = new if t == old else t
            if t not in out:
                out.append(t)
        return f"tags: [{', '.join(out)}]"

    head, sep, rest = text.partition("\n---\n")
    return re.sub(r"^tags: \[(.*)\]$", repl, head, count=1, flags=re.M) + sep + rest


def rewrite_status_in_text(text: str, old: str, new: str) -> str:
    """Replace ``old`` by ``new`` in the ``status:`` line of a note front matter."""
    head, sep, rest = text.partition("\n---\n")
    head = re.sub(rf"^status: {re.escape(old)}\s*$", f"status: {new}", head, count=1, flags=re.M)
    return head + sep + rest


def yaml_scalar(value: str) -> str:
    """Return ``value`` as a YAML scalar: plain when that is safe, double-quoted otherwise."""
    plain = (re.fullmatch(r"[A-Za-z0-9(][^#:\n\"']*", value) is not None
             and value == value.strip() and value.lower() not in _RESERVED)
    return value if plain else json.dumps(value, ensure_ascii=False)


def drop_vocab_entry(text: str, name: str) -> str:
    """Remove the ``name:`` key of a vocabulary file together with its indented block."""
    out: list[str] = []
    skipping = False
    for line in text.split("\n"):
        if line == f"{name}:":
            skipping = True
            continue
        if skipping and (line.startswith(" ") or line.startswith("\t")):
            continue
        skipping = False
        out.append(line)
    return "\n".join(out)


def rename_vocab_key(text: str, old: str, new: str, merge: bool) -> str:
    """Rename the ``old`` key of a vocabulary file, or drop its block when merging into ``new``."""
    if merge:
        return drop_vocab_entry(text, old)
    return re.sub(rf"^{re.escape(old)}:\s*$", f"{new}:", text, count=1, flags=re.M)


def upsert_vocab_entry(text: str, name: str, description: str) -> str:
    """Set the description of ``name``; a new entry goes to its alphabetical place.

    An existing entry is rewritten in place. A new entry is inserted before the first
    entry whose key sorts after it (and before the comment lines that sit right above
    that entry, unless they are the file header), or at the end of the file when there is none.
    """
    block = f"{name}:\n  description: {yaml_scalar(description)}".split("\n")
    lines = text.split("\n")
    if f"{name}:" in lines:
        start = lines.index(f"{name}:")
        end = start + 1
        while end < len(lines) and lines[end][:1] in (" ", "\t"):
            end += 1
        return "\n".join(lines[:start] + block + lines[end:])
    for index, line in enumerate(lines):
        if re.fullmatch(r"[A-Za-z0-9][^\s:#]*:", line) and line[:-1] > name:
            top = index
            while top > 0 and lines[top - 1].startswith("#"):
                top -= 1
            if top > 0:  # comments right above an entry belong to it, but not the file header
                index = top
            return "\n".join(lines[:index] + block + lines[index:])
    return text.rstrip("\n") + ("\n" if text.strip() else "") + "\n".join(block) + "\n"
