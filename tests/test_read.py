import pytest
from helpers import IDS, call

MIGRATION, CONVENTIONS, INCIDENTS = IDS[0], IDS[1], IDS[2]


# --------------------------------------------------------------- outline ----


def test_outline_lists_headings_and_ignores_code_blocks(client):
    out = call(client, "get_outline", id=INCIDENTS)
    rows = [(h["level"], h["title"], h["line"]) for h in out["headings"]]
    # "# not a heading" is a shell comment inside a code block.
    assert rows == [(1, "Incidents", 1), (2, "Cause", 5), (2, "Fix", 9), (3, "Detail", 16), (2, "Notes", 20)]
    sizes = {h["title"]: h["chars"] for h in out["headings"]}
    assert sizes["Incidents"] == max(sizes.values()) and sizes["Fix"] > sizes["Detail"] > 0
    assert out["revision"] == call(client, "get_doc", id=INCIDENTS)["revision"]
    assert call(client, "get_outline", id=CONVENTIONS)["headings"] == [
        {"level": 1, "title": "Conventions", "line": 1, "chars": out_chars(client, CONVENTIONS)}]


def out_chars(client, note_id):
    return len(call(client, "get_doc", id=note_id)["body"].rstrip())


# ------------------------------------------------------------ get_doc ----


def test_get_doc_returns_the_whole_note_without_a_section(client):
    doc = call(client, "get_doc", id=INCIDENTS)
    assert "Nothing else." in doc["body"] and "section" not in doc and doc["revision"]


def test_get_doc_returns_only_the_requested_section(client):
    full = call(client, "get_doc", id=INCIDENTS)
    fix = call(client, "get_doc", id=INCIDENTS, section="fix")
    assert fix["body"].startswith("## Fix") and "docker system df" in fix["body"]
    assert "### Detail" in fix["body"] and "One step." in fix["body"]
    assert "## Notes" not in fix["body"] and "Slow disk scan." not in fix["body"]
    assert fix["section"] == "Fix" and fix["line"] == 9 and fix["full_chars"] == len(full["body"])
    assert call(client, "get_doc", id=INCIDENTS, section="## Detail")["body"] == "### Detail\n\nOne step."
    assert call(client, "get_doc", id=INCIDENTS, section="Notes")["body"].endswith("Nothing else.")


def test_get_doc_section_errors(client):
    error = call(client, "get_doc", id=INCIDENTS, section="Nope")["error"]
    assert "not found" in error and "Cause" in error and "Detail" in error
    assert "not found" in call(client, "get_doc", id=INCIDENTS, section="not a heading")["error"]
    note = call(client, "write_doc", title="Twins", description="d", tags=["docker"], status="todo",
                body="# T\n\n## Same\n\none\n\n## Same\n\ntwo")
    assert "ambiguous" in call(client, "get_doc", id=note["id"], section="same")["error"]


# --------------------------------------------------------------- search ----


def test_search_returns_the_passage_its_section_and_where_it_matched(client):
    hit = call(client, "search", query="slow disk")[0]
    assert hit["id"] == INCIDENTS and hit["snippet"] == "Slow disk scan."
    assert hit["section"] == "Cause" and hit["line"] == 7 and "body" in hit["matched_in"]
    assert hit["revision"]
    # The best line is the one with the most search words.
    hit = call(client, "search", query="docker timeouts")[0]
    assert hit["snippet"] == "Docker timeouts hit Home Assistant." and hit["section"] == "Incidents"
    # A match inside a code block belongs to the heading above it.
    hit = call(client, "search", query="system df")[0]
    assert "docker system df" in hit["snippet"] and hit["section"] == "Fix"


def test_search_matching_only_the_title_has_no_passage(client):
    hit = call(client, "search", query="résumé")[0]
    assert hit["snippet"] == "" and hit["section"] == "" and hit["line"] is None
    assert hit["matched_in"] == ["title"]


def test_search_window_is_centred_on_the_match_and_cut_at_words(client):
    body = "alpha " * 150 + "needle " + "omega " * 150
    note = call(client, "write_doc", title="Long", description="d", tags=["docker"], status="todo", body=body)
    hit = call(client, "search", query="needle")[0]
    assert hit["id"] == note["id"] and "needle" in hit["snippet"]
    assert hit["snippet"].startswith("…") and hit["snippet"].endswith("…") and len(hit["snippet"]) < 320
    assert set(hit["snippet"].strip("…").split()) <= {"alpha", "needle", "omega"}


# ------------------------------------------------------------ list_docs ----
# Updated dates of the fixtures: migration 2026-10-26, conventions 2026-10-12, incidents 2026-10-30.


def ids(client, **args):
    return [d["id"] for d in call(client, "list_docs", **args)]


def test_list_docs_filters_by_date_inclusively(client):
    assert ids(client) == [INCIDENTS, MIGRATION, CONVENTIONS]
    assert ids(client, updated_since="2026-10-26") == [INCIDENTS, MIGRATION]
    assert ids(client, updated_until="2026-10-26") == [MIGRATION, CONVENTIONS]
    assert ids(client, updated_since="2026-10-13", updated_until="2026-10-29") == [MIGRATION]
    assert ids(client, updated_since="2026-10-26", status="todo") == [MIGRATION]
    assert ids(client, updated_since="2026-11-01") == []


def test_list_docs_sort_and_limit(client):
    assert ids(client, sort="title") == [CONVENTIONS, MIGRATION, INCIDENTS]
    assert ids(client, limit=2) == [INCIDENTS, MIGRATION]
    assert ids(client, tag="docker", sort="title", limit=1) == [MIGRATION]


@pytest.mark.parametrize("args,expected", [
    ({"updated_since": "yesterday"}, "YYYY-MM-DD"),
    ({"updated_until": "2026-1-5"}, "YYYY-MM-DD"),
    ({"sort": "size"}, "sort must be"),
])
def test_list_docs_rejects_bad_arguments(client, args, expected):
    assert expected in call(client, "list_docs", **args)["error"]
