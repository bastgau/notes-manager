import pytest
from helpers import IDS, call, git_out, git_raw, run, tool_names
from starlette.testclient import TestClient

from notes_manager.config import Config
from notes_manager.server import build_app

CONVENTIONS = IDS[1]
ORIGINAL_BODY = "# Conventions\n\nPrefix automations with the domain.\n"


@pytest.fixture
def edited(client):
    """The conventions note after two edits; returns (revision at seed time, [edit results])."""
    seed_revision = call(client, "get_doc", id=CONVENTIONS)["revision"]
    first = call(client, "patch_doc", id=CONVENTIONS, old="Prefix", new="Always prefix")
    second = call(client, "append_doc", id=CONVENTIONS, text="More.")
    return seed_revision, [first, second]


# --------------------------------------------------------------- history ----


def test_history_lists_commits_newest_first(client, edited):
    seed_revision, (first, second) = edited
    history = call(client, "get_doc_history", id=CONVENTIONS)
    assert [h["subject"] for h in history] == ["docs: append to note", "docs: edit note", "seed"]
    assert [h["revision"] for h in history] == [second["revision"], first["revision"], seed_revision]
    assert [h["current"] for h in history] == [True, False, False]
    assert history[0]["commit"] == second["commit"] and history[0]["author"] == "Test User"
    assert history[0]["date"].startswith("20")
    assert [h["commit"] for h in call(client, "get_doc_history", id=CONVENTIONS, limit=1)] == [second["commit"]]


def test_history_of_an_untouched_note_is_its_creation(client):
    assert [h["subject"] for h in call(client, "get_doc_history", id=IDS[0])] == ["seed"]
    assert "not found" in call(client, "get_doc_history", id="99999999-9999-4999-8999-999999999999")["error"]
    assert "uuid" in call(client, "get_doc_history", id="../x")["error"]


def test_get_doc_version_reads_an_old_version(client, edited):
    seed_commit = call(client, "get_doc_history", id=CONVENTIONS)[-1]["commit"]
    old = call(client, "get_doc_version", id=CONVENTIONS, commit=seed_commit)
    assert old["body"] == ORIGINAL_BODY and old["revision"] == edited[0] and old["commit"] == seed_commit
    assert "More." in call(client, "get_doc", id=CONVENTIONS)["body"]


def test_get_doc_version_errors(client, edited):
    assert "hexadecimal" in call(client, "get_doc_version", id=CONVENTIONS, commit="main; rm -rf")["error"]
    assert "unknown commit" in call(client, "get_doc_version", id=CONVENTIONS, commit="abcdef1")["error"]
    created = call(client, "write_doc", title="Later", description="d", tags=["docker"], status="todo", body="b")
    seed_commit = call(client, "get_doc_history", id=CONVENTIONS)[-1]["commit"]
    assert "does not exist at that commit" in call(
        client, "get_doc_version", id=created["id"], commit=seed_commit)["error"]


def test_history_tools_stay_available_without_write_mode(env):
    cfg, store, repo, *_ = env
    with TestClient(build_app(Config(**{**cfg.__dict__, "write": False}), store, repo)) as c:
        names = tool_names(c)
        assert {"get_doc_history", "get_doc_version"} <= names and "restore_doc" not in names
        assert len(call(c, "get_doc_history", id=CONVENTIONS)) == 1


# --------------------------------------------------------------- restore ----


def test_restore_doc_goes_back_as_a_new_commit(client, env, edited):
    remote = env[4]
    seed_commit = call(client, "get_doc_history", id=CONVENTIONS)[-1]["commit"]
    before = int(git_out(remote, "rev-list", "--count", "main"))
    out = call(client, "restore_doc", id=CONVENTIONS, commit=seed_commit)
    assert out["restored_from"] == seed_commit and out["branch"] == "main"
    assert int(git_out(remote, "rev-list", "--count", "main")) == before + 1  # history is kept
    subject = git_out(remote, "log", "-1", "--format=%s", "main")
    assert subject == f'docs: restore note "Home Assistant conventions" to {seed_commit[:7]}'
    assert call(client, "get_doc", id=CONVENTIONS)["body"] == ORIGINAL_BODY
    assert git_raw(remote, "show", f"main:notes/{CONVENTIONS}.md").endswith(ORIGINAL_BODY)
    assert len(call(client, "get_doc_history", id=CONVENTIONS)) == 4


def test_restore_doc_refuses_a_no_op_and_a_stale_revision(client, edited):
    seed_commit = call(client, "get_doc_history", id=CONVENTIONS)[-1]["commit"]
    head = call(client, "get_doc_history", id=CONVENTIONS)[0]["commit"]
    assert "already identical" in call(client, "restore_doc", id=CONVENTIONS, commit=head)["error"]
    assert "changed since" in call(client, "restore_doc", id=CONVENTIONS, commit=seed_commit,
                                   expected_revision="deadbeef0000")["error"]


def test_restore_doc_dry_run(client, env, edited):
    remote = env[4]
    tip = git_out(remote, "rev-parse", "main")
    seed_commit = call(client, "get_doc_history", id=CONVENTIONS)[-1]["commit"]
    out = call(client, "restore_doc", id=CONVENTIONS, commit=seed_commit, dry_run=True)
    assert out["dry_run"] is True and "-More." in out["diff"] and "-Always prefix" in out["diff"]
    assert git_out(remote, "rev-parse", "main") == tip


def test_restore_doc_needs_the_old_tags_to_be_declared_still(client):
    call(client, "declare_tag", tag="temp", description="Temporary")
    call(client, "set_doc_tags", id=CONVENTIONS, tags=["temp"])
    with_temp = call(client, "get_doc_history", id=CONVENTIONS)[0]["commit"]
    call(client, "set_doc_tags", id=CONVENTIONS, tags=["docker"])
    call(client, "remove_tag", tag="temp")
    assert "undeclared tag 'temp'" in call(client, "restore_doc", id=CONVENTIONS, commit=with_temp)["error"]


def test_restore_doc_keeps_the_links_of_that_version(client):
    call(client, "set_doc_related", id=CONVENTIONS, related=[IDS[0]])
    linked = call(client, "get_doc_history", id=CONVENTIONS)[0]["commit"]
    call(client, "set_doc_related", id=CONVENTIONS, related=[])
    assert call(client, "get_doc", id=CONVENTIONS)["related"] == []
    call(client, "restore_doc", id=CONVENTIONS, commit=linked)
    assert [r["id"] for r in call(client, "get_doc", id=CONVENTIONS)["related"]] == [IDS[0]]
