import pytest
from helpers import IDS, STATUS_YAML, TAGS_YAML, call, git_out, note, run


def main_file(remote, name):
    return git_out(remote, "show", f"main:{name}")


# ------------------------------------------------------------------ set ----


def test_set_tag_declares_a_tag_that_write_doc_can_use_at_once(client, env):
    remote = env[4]
    out = call(client, "declare_tag", tag="networking", description="Network and DNS")
    assert out["created"] is True and out["branch"] == "main"
    tags_yaml = main_file(remote, "tags.yaml")
    assert "networking:\n  description: Network and DNS" in tags_yaml
    assert "# comment kept" in tags_yaml
    assert {"tag": "networking", "description": "Network and DNS", "count": 0} in call(client, "list_tags")
    written = call(client, "write_doc", title="DNS", description="d", tags=["networking"],
                   status="todo", body="b")
    assert written["branch"] == "main"
    assert call(client, "validate_notes")["ok"] is True


def test_set_tag_updates_only_the_description(client, env):
    remote = env[4]
    out = call(client, "declare_tag", tag="docker", description="Containers and images")
    assert out["created"] is False
    assert main_file(remote, "tags.yaml") == TAGS_YAML.replace("Docker things", "Containers and images").strip()
    assert git_out(remote, "log", "-1", "--format=%s", "main") == "docs: describe tag docker"


def test_new_tag_is_inserted_in_alphabetical_order(client, env):
    remote = env[4]
    call(client, "declare_tag", tag="git", description="Git usage")
    call(client, "declare_tag", tag="zzz-last", description="Sorts last")
    keys = [line[:-1] for line in main_file(remote, "tags.yaml").splitlines() if line.endswith(":") and line[0] != " "]
    assert keys == ["docker", "git", "home-assistant", "migration", "unused", "zzz-last"]


def test_description_with_special_characters_round_trips(client):
    description = 'Time: 10:30 # not a comment "quoted"'
    call(client, "declare_tag", tag="timing", description=description)
    assert {"tag": "timing", "description": description, "count": 0} in call(client, "list_tags")


def test_set_identical_description_is_nothing_to_change(client):
    assert "nothing to change" in call(client, "declare_tag", tag="docker", description="Docker things")["error"]


@pytest.mark.parametrize("kwargs,expected", [
    ({"tag": "Bad Name"}, "kebab-case"),
    ({"description": ""}, "description must be"),
    ({"description": "x" * 201}, "description must be"),
    ({"description": "token ghp_Ab3dE5gH7jK9mN1pQ3sT5vX7zB9dF1"}, "secret"),
])
def test_set_tag_validation_does_not_touch_main(client, env, kwargs, expected):
    remote = env[4]
    before = git_out(remote, "rev-parse", "main")
    args = {"tag": "newtag", "description": "A description", **kwargs}
    assert expected in call(client, "declare_tag", **args)["error"]
    assert git_out(remote, "rev-parse", "main") == before


def test_set_status_declares_and_updates(client, env):
    remote = env[4]
    assert call(client, "declare_status", status="archived", description="No longer maintained")["created"]
    assert "archived:\n  description: No longer maintained" in main_file(remote, "status.yaml")
    assert not call(client, "declare_status", status="todo", description="Still to do")["created"]
    # "archived" sorts first, and the untouched entries are left as they were.
    assert main_file(remote, "status.yaml") == (
        "archived:\n  description: No longer maintained\n"
        + STATUS_YAML.replace("Not done", "Still to do")).strip()
    assert {s["status"] for s in call(client, "list_statuses")} == {"up-to-date", "todo", "archived"}


# --------------------------------------------------------------- remove ----


def test_remove_unused_tag(client, env):
    remote = env[4]
    out = call(client, "remove_tag", tag="unused")
    assert out["removed"] is True
    tags_yaml = main_file(remote, "tags.yaml")
    assert "unused" not in tags_yaml and "Nothing uses this" not in tags_yaml
    assert "# comment kept" in tags_yaml and "migration:" in tags_yaml
    assert "unused" not in {t["tag"] for t in call(client, "list_tags")}


def test_remove_used_tag_is_refused(client, env):
    remote = env[4]
    before = git_out(remote, "rev-parse", "main")
    error = call(client, "remove_tag", tag="docker")["error"]
    assert "used by 2 note" in error and "rename_tag" in error
    assert git_out(remote, "rev-parse", "main") == before


def test_remove_checks_the_remote_and_not_the_stale_mirror(client, env):
    """A note using the tag was pushed after the last sync: the removal must still be refused."""
    seed, remote = env[3], env[4]
    (seed / "notes" / "77777777-7777-4777-8777-777777777777.md").write_text(
        note("Late", "Pushed after the sync", ["unused"], "todo", "2026-11-02", "x"))
    run("add", "-A", cwd=seed)
    run("commit", "-m", "late note", cwd=seed)
    run("push", "origin", "main", cwd=seed)
    assert "used by 1 note" in call(client, "remove_tag", tag="unused")["error"]
    assert "unused:" in main_file(remote, "tags.yaml")


def test_remove_status(client, env):
    assert "used by" in call(client, "remove_status", status="todo")["error"]
    call(client, "declare_status", status="archived", description="Old")
    assert call(client, "remove_status", status="archived")["removed"] is True
    assert {s["status"] for s in call(client, "list_statuses")} == {"up-to-date", "todo"}


def test_unknown_names_are_rejected_with_a_hint(client):
    assert "Did you mean" in call(client, "remove_tag", tag="dockr")["error"]
    assert "unknown status" in call(client, "remove_status", status="zzz")["error"]
    assert "unknown status" in call(client, "rename_status", old="zzz", new="x")["error"]


# --------------------------------------------------------------- rename ----


def test_rename_status_updates_the_notes(client, env):
    remote = env[4]
    out = call(client, "rename_status", old="todo", new="pending")
    assert out["merged"] is False
    assert "pending:\n  description: Not done" in main_file(remote, "status.yaml")
    assert "status: pending" in main_file(remote, f"notes/{IDS[0]}.md")
    assert {s["status"] for s in call(client, "list_statuses")} == {"up-to-date", "pending"}
    assert call(client, "validate_notes")["ok"] is True


def test_merge_status_into_an_existing_one(client, env):
    remote = env[4]
    out = call(client, "rename_status", old="todo", new="up-to-date")
    assert out["merged"] is True
    assert "todo" not in main_file(remote, "status.yaml")
    assert "status: up-to-date" in main_file(remote, f"notes/{IDS[0]}.md")
    assert call(client, "validate_notes")["ok"] is True


def test_rename_validation(client):
    assert "kebab-case" in call(client, "rename_status", old="todo", new="Bad Name")["error"]
    assert "identical" in call(client, "rename_tag", old="docker", new="docker")["error"]
