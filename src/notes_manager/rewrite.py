"""Text rewriting used when a tag is renamed or merged."""

import re


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


def rewrite_tags_yaml(text: str, old: str, new: str, merge: bool) -> str:
    """Rename the ``old`` key of tags.yaml, or drop its block when merging into ``new``.

    The file is edited as text so that comments and ordering are preserved.
    """
    if not merge:
        return re.sub(rf"^{re.escape(old)}:\s*$", f"{new}:", text, count=1, flags=re.M)
    out: list[str] = []
    skipping = False
    for line in text.split("\n"):
        if line == f"{old}:":
            skipping = True
            continue
        if skipping and (line.startswith(" ") or line.startswith("\t")):
            continue
        skipping = False
        out.append(line)
    return "\n".join(out)
