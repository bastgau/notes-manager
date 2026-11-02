"""Read-only tools: always available."""

from mcp.server.fastmcp import FastMCP

from notes_manager.constants import MAX_SEARCH_LIMIT
from notes_manager.markdown import parse_headings, pick_section, section_text
from notes_manager.store import Store
from notes_manager.utils import check_id, suggest


def register_read_tools(mcp: FastMCP, store: Store) -> None:
    def check_tag(tag: str) -> str:
        if tag not in store.snapshot.tags:
            raise ValueError(f"unknown tag '{tag}'.{suggest(tag, store.snapshot.tags)}")
        return tag

    @mcp.tool()
    def search(query: str, tag: str | None = None, status: str | None = None,
               limit: int = 10) -> list[dict]:
        """Full-text search (case and accent insensitive, all words must match).

        Titles weigh more than descriptions, tags and bodies. Optionally filter by
        an exact tag and/or status. Each result has a `snippet` (the passage of the
        body that best matches, cut at a word), the `section` (heading) it belongs to,
        its `line` in the body and `matched_in` (title, description, tags, body). To read
        only that part, call get_doc with the `section`; get_outline lists a note's headings.
        """
        limit = max(1, min(limit, MAX_SEARCH_LIMIT))
        return store.search(query, tag, status, limit)

    def find_note(note_id: str):
        note = store.snapshot.notes.get(check_id(note_id))
        if not note:
            raise ValueError("note not found")
        return note

    @mcp.tool()
    def get_doc(id: str, section: str | None = None) -> dict:
        """Return a note (front matter fields and Markdown body) by its uuid.

        With `section` (the title of a heading, case and accents ignored, '#' optional),
        only that section is returned, sub-sections included: it saves reading a long
        note to find one command. The `revision` is what write tools expect in
        `expected_revision`. Use get_outline to see the headings.
        """
        note = find_note(id)
        snap = store.snapshot
        links = lambda ids: [{"id": i, "title": snap.title_of(i)} for i in ids]  # noqa: E731
        result = {**note.summary(), "source": f"notes/{note.id}.md", "related": links(note.related),
                  "linked_from": links(snap.linked_from.get(note.id, []))}
        if section is None:
            return {**result, "body": note.body}
        lines = note.body.split("\n")
        headings = parse_headings(lines)
        position = pick_section(lines, headings, section)
        return {**result, "section": headings[position].title, "line": headings[position].line + 1,
                "body": section_text(lines, headings, position), "full_chars": len(note.body)}

    @mcp.tool()
    def get_outline(id: str) -> dict:
        """List the headings of a note with their level, line and size, without its text.

        `line` is the 1-based line in the body and `chars` the size of the section
        (sub-sections included), so you can decide what to read with get_doc(section).
        Headings inside code blocks are ignored.
        """
        note = find_note(id)
        lines = note.body.split("\n")
        headings = parse_headings(lines)
        rows = [{"level": h.level, "title": h.title, "line": h.line + 1,
                 "chars": len(section_text(lines, headings, i))} for i, h in enumerate(headings)]
        return {"id": note.id, "title": note.title, "revision": note.revision,
                "chars": len(note.body), "headings": rows}

    @mcp.tool()
    def list_docs(tag: str | None = None, status: str | None = None,
                  updated_since: str | None = None, updated_until: str | None = None,
                  sort: str = "updated", limit: int | None = None) -> list[dict]:
        """List note summaries, optionally filtered.

        Filter by `tag`, `status`, and by update date with `updated_since` and
        `updated_until` (YYYY-MM-DD, both inclusive). `sort` is "updated" (most recent
        first, the default) or "title"; `limit` keeps the first N.
        """
        return store.list_docs(tag, status, updated_since, updated_until, sort, limit)

    @mcp.tool()
    def list_by_tag(tag: str) -> list[dict]:
        """List the notes carrying a tag. Unknown tags are rejected with suggestions."""
        return store.list_docs(check_tag(tag), None)

    @mcp.tool()
    def list_tags() -> list[dict]:
        """List declared tags with their description and the number of notes using them."""
        snap = store.snapshot
        counts: dict[str, int] = {}
        for n in snap.notes.values():
            for t in n.tags:
                counts[t] = counts.get(t, 0) + 1
        rows = [{"tag": t, "description": d, "count": counts.get(t, 0)} for t, d in snap.tags.items()]
        rows += [{"tag": t, "description": "(undeclared)", "count": c}
                 for t, c in counts.items() if t not in snap.tags]
        return sorted(rows, key=lambda r: (-r["count"], r["tag"]))

    @mcp.tool()
    def list_statuses() -> list[dict]:
        """List declared status values with their description and note counts."""
        snap = store.snapshot
        counts: dict[str, int] = {}
        for n in snap.notes.values():
            counts[n.status] = counts.get(n.status, 0) + 1
        return [{"status": s, "description": d, "count": counts.get(s, 0)}
                for s, d in snap.statuses.items()]

    @mcp.tool()
    def validate_notes() -> dict:
        """Check every note and the vocabulary files.

        `problems` are errors (they make `ok` false): missing front matter fields, undeclared
        tags or statuses, a bad `updated` date, broken `related` links. `warnings` are things
        worth tidying: declared tags or statuses no note uses, unsorted tags.yaml or
        status.yaml, notes with the same title, over-long descriptions.
        """
        problems = store.snapshot.problems()
        return {"notes": len(store.snapshot.notes), "ok": not problems, "problems": problems,
                "warnings": store.snapshot.warnings()}
