import pytest
from helpers import IDS, call, git_raw, note, run

MIGRATION, CONVENTIONS, INCIDENTS = IDS[0], IDS[1], IDS[2]


def on_main(remote, note_id):
    return git_raw(remote, "show", f"main:notes/{note_id}.md")


def related_ids(client, note_id):
    return [r["id"] for r in call(client, "get_doc", id=note_id)["related"]]


def test_set_doc_related_links_both_ways(client, env):
    remote = env[4]
    out = call(client, "set_doc_related", id=MIGRATION, related=[INCIDENTS])
    text = on_main(remote, MIGRATION)
    assert f"related: [{INCIDENTS}]\n" in text and text.index("related:") < text.index("updated:")
    assert "Le volume nommé est lent." in text  # the body is untouched
    assert out["changes"][0]["path"] == f"notes/{MIGRATION}.md"
    doc = call(client, "get_doc", id=MIGRATION)
    assert doc["related"] == [{"id": INCIDENTS, "title": "Résumé des incidents"}]
    assert call(client, "get_doc", id=INCIDENTS)["linked_from"] == [
        {"id": MIGRATION, "title": "Migration du volume Docker"}]
    assert call(client, "validate_notes")["ok"] is True


def test_set_doc_related_replaces_and_clears(client, env):
    remote = env[4]
    call(client, "set_doc_related", id=MIGRATION, related=[INCIDENTS])
    call(client, "set_doc_related", id=MIGRATION, related=[INCIDENTS, CONVENTIONS])
    assert related_ids(client, MIGRATION) == [INCIDENTS, CONVENTIONS]
    call(client, "set_doc_related", id=MIGRATION, related=[])
    assert "related" not in on_main(remote, MIGRATION) and related_ids(client, MIGRATION) == []
    assert call(client, "get_doc", id=INCIDENTS)["linked_from"] == []


@pytest.mark.parametrize("related,expected", [
    ([MIGRATION], "itself"),
    (["99999999-9999-4999-8999-999999999999"], "does not exist"),
    ([INCIDENTS, INCIDENTS], "distinct"),
    ([f"{i:08d}-0000-4000-8000-000000000000" for i in range(21)], "at most 20"),
])
def test_set_doc_related_validation(client, related, expected):
    assert expected in call(client, "set_doc_related", id=MIGRATION, related=related)["error"]


def test_set_doc_related_same_links_is_refused(client):
    call(client, "set_doc_related", id=MIGRATION, related=[INCIDENTS])
    assert "already" in call(client, "set_doc_related", id=MIGRATION, related=[INCIDENTS])["error"]


def test_other_edits_keep_the_links(client, env):
    remote = env[4]
    call(client, "set_doc_related", id=MIGRATION, related=[INCIDENTS])
    call(client, "patch_doc", id=MIGRATION, old="lent", new="très lent")
    call(client, "append_doc", id=MIGRATION, text="Suite.")
    call(client, "set_doc_status", id=MIGRATION, status="up-to-date")
    call(client, "set_doc_tags", id=MIGRATION, tags=["docker"])
    assert related_ids(client, MIGRATION) == [INCIDENTS]
    assert f"related: [{INCIDENTS}]" in on_main(remote, MIGRATION)


def test_write_doc_keeps_links_unless_told_otherwise(client):
    call(client, "set_doc_related", id=MIGRATION, related=[INCIDENTS])
    args = dict(id=MIGRATION, title="Renamed", description="d", tags=["docker"], status="todo", body="b")
    call(client, "write_doc", **args)
    assert related_ids(client, MIGRATION) == [INCIDENTS]
    call(client, "write_doc", related=[CONVENTIONS], **args)
    assert related_ids(client, MIGRATION) == [CONVENTIONS]
    call(client, "write_doc", related=[], **args)
    assert related_ids(client, MIGRATION) == []


def test_write_doc_can_create_a_linked_note(client):
    created = call(client, "write_doc", title="New", description="d", tags=["docker"], status="todo",
                   body="b", related=[MIGRATION])
    assert related_ids(client, created["id"]) == [MIGRATION]
    assert call(client, "get_doc", id=MIGRATION)["linked_from"][0]["id"] == created["id"]
    assert "does not exist" in call(client, "write_doc", title="x", description="d", tags=["docker"],
                                    status="todo", body="b",
                                    related=["99999999-9999-4999-8999-999999999999"])["error"]


def test_dry_run_of_a_link_change(client, env):
    out = call(client, "set_doc_related", id=MIGRATION, related=[INCIDENTS], dry_run=True)
    assert f"+related: [{INCIDENTS}]" in out["diff"]
    assert related_ids(client, MIGRATION) == []


def test_a_broken_link_is_reported_by_validate_notes(env):
    cfg, store, repo, seed, _ = env
    text = note("Linked", "d", ["docker"], "todo", "2026-11-01", "b").replace(
        "updated:", "related: [99999999-9999-4999-8999-999999999999, not-an-id]\nupdated:")
    (seed / "notes" / "88888888-8888-4888-8888-888888888888.md").write_text(text)
    run("add", "-A", cwd=seed)
    run("commit", "-m", "linked note", cwd=seed)
    run("push", "origin", "main", cwd=seed)
    repo.sync()
    store.reload()
    problems = store.snapshot.problems()
    assert len(problems) == 1
    assert any("broken link" in p for p in problems[0]["problems"])
    assert any("not a note id" in p for p in problems[0]["problems"])
