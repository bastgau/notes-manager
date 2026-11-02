from helpers import IDS, call, note, run


def push_note(env, name, text):
    """Add or replace a file in the seed checkout, push it, and bring the mirror up to date."""
    _, store, repo, seed, _ = env
    (seed / name).parent.mkdir(exist_ok=True)
    (seed / name).write_text(text)
    run("add", "-A", cwd=seed)
    run("commit", "-m", f"change {name}", cwd=seed)
    run("push", "origin", "main", cwd=seed)
    repo.sync()
    store.reload()


def kinds(result):
    return [(w["kind"], w.get("name")) for w in result["warnings"]]


def test_a_clean_repository_has_only_the_expected_warning(client):
    result = call(client, "validate_notes")
    assert result["ok"] is True and result["problems"] == []
    # "unused" is declared in the fixture but no note uses it.
    assert kinds(result) == [("unused tag", "unused")]


def test_warnings_do_not_make_the_check_fail(client):
    call(client, "declare_status", status="archived", description="Old")
    result = call(client, "validate_notes")
    assert result["ok"] is True
    assert ("unused status", "archived") in kinds(result)


def test_unsorted_vocabulary_files_are_reported(env, client):
    push_note(env, "tags.yaml", "migration:\n  description: M\ndocker:\n  description: D\n"
                                "home-assistant:\n  description: H\nunused:\n  description: U\n")
    assert ("unsorted vocabulary", "tags.yaml") in kinds(call(client, "validate_notes"))


def test_duplicate_titles_are_reported(client):
    args = dict(title="Same title", description="d", tags=["docker"], status="todo", body="b")
    first, second = call(client, "write_doc", **args), call(client, "write_doc", **{**args, "title": "same TITLE"})
    duplicate = [w for w in call(client, "validate_notes")["warnings"] if w["kind"] == "duplicate title"]
    assert len(duplicate) == 1 and set(duplicate[0]["ids"]) == {first["id"], second["id"]}


def test_bad_dates_and_too_many_tags_are_errors(env, client):
    many = ["docker", "home-assistant", "migration", "unused"] * 3
    # An impossible date makes the front matter unreadable: the note is reported, the server keeps going.
    push_note(env, "notes/77777777-7777-4777-8777-777777777777.md",
              note("Impossible date", "d", ["docker"], "todo", "2026-13-45", "b"))
    push_note(env, "notes/66666666-6666-4666-8666-666666666666.md",
              note("Not a date", "d", ["docker"], "todo", "yesterday", "b"))
    push_note(env, "notes/44444444-4444-4444-8444-444444444444.md",
              note("Many tags", "d", many, "todo", "2026-11-01", "b"))
    result = call(client, "validate_notes")
    assert result["ok"] is False and result["notes"] == 6
    by_id = {p["id"]: p["problems"] for p in result["problems"]}
    assert any("invalid front matter" in p for p in by_id["77777777-7777-4777-8777-777777777777"])
    assert any("not a valid YYYY-MM-DD date" in p for p in by_id["66666666-6666-4666-8666-666666666666"])
    assert any("too many tags" in p for p in by_id["44444444-4444-4444-8444-444444444444"])
    # The other notes are still served.
    assert call(client, "get_doc", id=IDS[0])["title"] == "Migration du volume Docker"


def test_an_empty_description_is_an_error(env, client):
    push_note(env, "notes/55555555-5555-4555-8555-555555555555.md",
              note("No description", "", ["docker"], "todo", "2026-11-01", "b"))
    problems = call(client, "validate_notes")["problems"]
    assert any("missing field: description" in p for entry in problems for p in entry["problems"])


def test_old_fixtures_still_validate(client):
    assert {n for n in IDS} <= {d["id"] for d in call(client, "list_docs")}
    assert call(client, "validate_notes")["ok"] is True


def test_a_broken_vocabulary_file_does_not_stop_the_server(env, client):
    push_note(env, "tags.yaml", "docker: [unclosed\n")
    result = call(client, "validate_notes")
    assert result["ok"] is False and "undeclared tag: docker" in str(result["problems"])
    push_note(env, "status.yaml", "- just\n- a list\n")
    assert call(client, "list_statuses") == []
