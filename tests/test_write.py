import pytest
from helpers import IDS, call, git_out, note, run

from notes_manager.note import Note


def count_commits(remote):
    return int(git_out(remote, "rev-list", "--count", "main"))


def test_write_doc_pushes_to_main_and_is_readable_at_once(client, env):
    remote = env[4]
    before = count_commits(remote)
    out = call(client, "write_doc", title="New: note", description="A description",
               tags=["docker"], status="todo", body="# Hello\n\nbody with zebra")
    assert out["branch"] == "main"
    assert count_commits(remote) == before + 1
    # No side branch is created.
    assert git_out(remote, "branch", "--format=%(refname:short)") == "main"
    show = git_out(remote, "show", f"main:notes/{out['id']}.md")
    assert show.startswith('---\ntitle: "New: note"') and "# Hello" in show
    assert Note.parse(out["id"], show).problems == []
    # Commit identity, and no AI trailer.
    log = git_out(remote, "log", "-1", "--format=%an <%ae>%n%B", "main")
    assert log.splitlines()[0] == "Test User <test@example.com>"
    assert "Co-Authored-By" not in log
    # The index was refreshed: the new note can be searched immediately.
    assert [h["id"] for h in call(client, "search", query="zebra")] == [out["id"]]


def test_two_edits_of_the_same_note_see_each_other(client, env):
    remote = env[4]
    common = dict(id=IDS[1], description="Naming rules", tags=["home-assistant"], status="up-to-date")
    call(client, "write_doc", title="Conventions v2", body="first edit", **common)
    # The second edit starts from the first one, not from the original note.
    assert call(client, "get_doc", id=IDS[1])["body"].strip() == "first edit"
    call(client, "write_doc", title="Conventions v3", body="second edit", **common)
    doc = call(client, "get_doc", id=IDS[1])
    assert doc["title"] == "Conventions v3" and doc["body"].strip() == "second edit"
    assert "second edit" in git_out(remote, "show", f"main:notes/{IDS[1]}.md")
    assert git_out(remote, "log", "--format=%s", "-2", "main").splitlines() == [
        'docs: update note "Conventions v3"', 'docs: update note "Conventions v2"']


def test_write_doc_unknown_id(client):
    assert "not found" in call(client, "write_doc", id="99999999-9999-4999-8999-999999999999",
                               title="t", description="d", tags=["docker"], status="todo",
                               body="b")["error"]


@pytest.mark.parametrize("kwargs,expected", [
    ({"tags": ["nope"]}, "undeclared tag"),
    ({"status": "weird"}, "undeclared status"),
    ({"tags": []}, "tags must be"),
    ({"title": "two\nlines"}, "single line"),
    ({"body": "token ghp_Ab3dE5gH7jK9mN1pQ3sT5vX7zB9dF1"}, "secret"),
])
def test_write_doc_validation_does_not_touch_main(client, env, kwargs, expected):
    remote = env[4]
    before = git_out(remote, "rev-parse", "main")
    args = dict(title="t", description="d", tags=["docker"], status="todo", body="b")
    args.update(kwargs)
    assert expected in call(client, "write_doc", **args)["error"]
    assert git_out(remote, "rev-parse", "main") == before


def test_placeholder_secret_is_allowed(client):
    out = call(client, "write_doc", title="t", description="d", tags=["docker"], status="todo",
               body='github_api_authorization: "Bearer ghp_xxxxxxxxxxxxxxxxxxxx"')
    assert out["branch"] == "main"


def test_rename_tag_updates_main_and_index(client, env):
    remote = env[4]
    out = call(client, "rename_tag", old="migration", new="move")
    assert out["merged"] is False and out["branch"] == "main"
    tags_yaml = git_out(remote, "show", "main:tags.yaml")
    assert "move:\n  description: Migrations" in tags_yaml and "# comment kept" in tags_yaml
    assert "tags: [docker, move]" in git_out(remote, "show", f"main:notes/{IDS[0]}.md")
    tags = {t["tag"] for t in call(client, "list_tags")}
    assert "move" in tags and "migration" not in tags
    assert call(client, "validate_notes")["ok"] is True


def test_merge_tag_dedupes(client, env):
    remote = env[4]
    out = call(client, "rename_tag", old="docker", new="home-assistant")
    assert out["merged"] is True
    tags_yaml = git_out(remote, "show", "main:tags.yaml")
    assert "docker:" not in tags_yaml and "Docker things" not in tags_yaml
    assert "tags: [home-assistant]" in git_out(remote, "show", f"main:notes/{IDS[2]}.md")
    assert "tags: [home-assistant, migration]" in git_out(remote, "show", f"main:notes/{IDS[0]}.md")


def test_rename_tag_validation(client):
    assert "unknown tag" in call(client, "rename_tag", old="zzz", new="x")["error"]
    assert "kebab" in call(client, "rename_tag", old="docker", new="Bad Name")["error"]


def test_push_is_retried_when_main_moved_in_between(client, env):
    """Someone pushes to main between our fetch and our push: the change is re-applied."""
    _, _, repo, seed, remote = env
    original = repo.git
    raced = []

    def racing_git(*args, **kwargs):
        if args and args[0] == "push" and not raced:
            raced.append(True)
            competitor = "66666666-6666-4666-8666-666666666666"
            (seed / "notes" / f"{competitor}.md").write_text(
                note("Competitor", "Pushed meanwhile", ["docker"], "todo", "2026-11-02", "x"))
            run("add", "-A", cwd=seed)
            run("commit", "-m", "competing commit", cwd=seed)
            run("push", "origin", "main", cwd=seed)
        return original(*args, **kwargs)

    repo.git = racing_git
    out = call(client, "write_doc", title="Mine", description="d", tags=["docker"], status="todo",
               body="b")
    assert raced and out["branch"] == "main"
    history = git_out(remote, "log", "--format=%s", "-3", "main").splitlines()
    assert history[0] == 'docs: add note "Mine"' and history[1] == "competing commit"
    # Both notes are in the index after the refresh.
    titles = {d["title"] for d in call(client, "list_docs")}
    assert {"Mine", "Competitor"} <= titles
