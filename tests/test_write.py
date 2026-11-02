import pytest
from helpers import IDS, call, git_out

from notes_manager.note import Note


def test_write_doc_creates_inbox_branch_and_never_touches_main(client, env):
    remote = env[4]
    main_before = git_out(remote, "rev-parse", "main")
    out = call(client, "write_doc", title="New: note", description="A description",
               tags=["docker"], status="todo", body="# Hello\n\nbody")
    assert out["branch"].startswith("inbox/")
    assert git_out(remote, "rev-parse", "main") == main_before
    show = git_out(remote, "show", f"{out['branch']}:notes/{out['id']}.md")
    assert show.startswith("---\ntitle: \"New: note\"") and "# Hello" in show
    author = git_out(remote, "log", "-1", "--format=%an <%ae>%n%B", out["branch"])
    assert author.splitlines()[0] == "Test User <test@example.com>"
    assert "Co-Authored-By" not in author
    assert Note.parse(out["id"], show).problems == []


def test_write_doc_update_existing(client, env):
    remote = env[4]
    out = call(client, "write_doc", id=IDS[1], title="Home Assistant conventions v2",
               description="Naming rules", tags=["home-assistant"], status="up-to-date", body="new")
    assert "v2" in git_out(remote, "show", f"{out['branch']}:notes/{IDS[1]}.md")
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
def test_write_doc_validation(client, kwargs, expected):
    args = dict(title="t", description="d", tags=["docker"], status="todo", body="b")
    args.update(kwargs)
    assert expected in call(client, "write_doc", **args)["error"]


def test_placeholder_secret_is_allowed(client):
    out = call(client, "write_doc", title="t", description="d", tags=["docker"], status="todo",
               body='github_api_authorization: "Bearer ghp_xxxxxxxxxxxxxxxxxxxx"')
    assert out["branch"].startswith("inbox/")


def test_rename_tag(client, env):
    remote = env[4]
    out = call(client, "rename_tag", old="migration", new="move")
    assert out["merged"] is False
    tags_yaml = git_out(remote, "show", f"{out['branch']}:tags.yaml")
    assert "move:\n  description: Migrations" in tags_yaml
    assert "# comment kept" in tags_yaml
    assert "tags: [docker, move]" in git_out(remote, "show", f"{out['branch']}:notes/{IDS[0]}.md")


def test_merge_tag_dedupes(client, env):
    remote = env[4]
    out = call(client, "rename_tag", old="docker", new="home-assistant")
    assert out["merged"] is True
    tags_yaml = git_out(remote, "show", f"{out['branch']}:tags.yaml")
    assert "docker:" not in tags_yaml and "Docker things" not in tags_yaml
    assert "tags: [home-assistant]" in git_out(remote, "show", f"{out['branch']}:notes/{IDS[2]}.md")
    assert "tags: [home-assistant, migration]" in git_out(
        remote, "show", f"{out['branch']}:notes/{IDS[0]}.md")


def test_rename_tag_validation(client):
    assert "unknown tag" in call(client, "rename_tag", old="zzz", new="x")["error"]
    assert "kebab" in call(client, "rename_tag", old="docker", new="Bad Name")["error"]
