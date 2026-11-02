"""Minimal Markdown structure: headings and sections, ignoring fenced code blocks."""

import re
from dataclasses import dataclass

from notes_manager.utils import normalize

FENCE_RE = re.compile(r"^ {0,3}(`{3,}|~{3,})")
HEADING_RE = re.compile(r"^(#{1,6})[ \t]+(.+?)(?:[ \t]+#+)?[ \t]*$")


@dataclass(frozen=True)
class Heading:
    level: int
    title: str
    line: int  # 0-based index in the list of lines of the body


def parse_headings(lines: list[str]) -> list[Heading]:
    """Headings of a body; lines inside fenced code blocks (for example shell comments) are skipped."""
    headings: list[Heading] = []
    fence = ""
    for index, line in enumerate(lines):
        match = FENCE_RE.match(line)
        if match:
            marker = match.group(1)
            if not fence:
                fence = marker
            elif marker[0] == fence[0] and len(marker) >= len(fence) and not line.strip().strip(marker[0]):
                fence = ""
            continue
        if fence:
            continue
        heading = HEADING_RE.match(line)
        if heading:
            headings.append(Heading(len(heading.group(1)), heading.group(2).strip(), index))
    return headings


def section_end(lines: list[str], headings: list[Heading], position: int) -> int:
    """Index of the first line after the section that starts at ``headings[position]``."""
    level = headings[position].level
    for later in headings[position + 1:]:
        if later.level <= level:
            return later.line
    return len(lines)


def find_sections(headings: list[Heading], name: str) -> list[int]:
    """Positions in ``headings`` whose title equals ``name`` (case, accents and leading '#' ignored)."""
    wanted = normalize(name.strip().lstrip("#").strip())
    return [i for i, h in enumerate(headings) if normalize(h.title) == wanted]


def describe_headings(headings: list[Heading]) -> str:
    return "; ".join(f"{'#' * h.level} {h.title} (line {h.line + 1})" for h in headings) or "(no headings)"


def pick_section(lines: list[str], headings: list[Heading], name: str) -> int:
    """Position of the single heading called ``name``; raise a helpful error otherwise."""
    found = find_sections(headings, name)
    if not found:
        raise ValueError(f"section '{name}' not found. Headings: {describe_headings(headings)}")
    if len(found) > 1:
        where = ", ".join(f"line {headings[i].line + 1}" for i in found)
        raise ValueError(f"section '{name}' is ambiguous ({where}); use a more specific heading")
    return found[0]


def insert_in_section(body: str, text: str, section: str | None) -> str:
    """Append ``text`` at the end of the body, or at the end of the named section."""
    new_lines = text.strip("\n").split("\n")
    if section is None:
        return body.rstrip("\n") + "\n\n" + "\n".join(new_lines) + "\n"
    lines = body.split("\n")
    headings = parse_headings(lines)
    position = pick_section(lines, headings, section)
    end = section_end(lines, headings, position)
    while end > headings[position].line + 1 and lines[end - 1].strip() == "":
        end -= 1
    before, after = lines[:end], lines[end:]
    separator = [""] if after and after[0].strip() != "" else []
    return "\n".join(before + [""] + new_lines + separator + after)
