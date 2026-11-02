"""Read-only tools: always available."""

from mcp.server.fastmcp import FastMCP

from notes_manager.constants import MAX_SEARCH_LIMIT
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
        an exact tag and/or status. Returns summaries with a snippet; use get_doc
        for the full text.
        """
        limit = max(1, min(limit, MAX_SEARCH_LIMIT))
        return store.search(query, tag, status, limit)

    @mcp.tool()
    def get_doc(id: str) -> dict:
        """Return a whole note (front matter fields and Markdown body) by its uuid."""
        note = store.snapshot.notes.get(check_id(id))
        if not note:
            raise ValueError("note not found")
        return {**note.summary(), "body": note.body, "source": f"notes/{note.id}.md"}

    @mcp.tool()
    def list_docs(tag: str | None = None, status: str | None = None) -> list[dict]:
        """List note summaries, most recently updated first, optionally filtered."""
        return store.list_docs(tag, status)

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
        """Check every note: required front matter fields, declared tags and statuses."""
        problems = store.snapshot.problems()
        return {"notes": len(store.snapshot.notes), "ok": not problems, "problems": problems}
