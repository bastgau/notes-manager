import datetime

import pytest
from helpers import IDS, call, git_out, git_raw, run

TODAY = datetime.datetime.now(datetime.UTC).date().isoformat()
CONVENTIONS, MIGRATION, INCIDENTS = IDS[1], IDS[0], IDS[2]


def on_main(remote, note_id):
    return git_raw(remote, "show", f"main:notes/{note_id}.md")


def revision(client, note_id):
    return call(client, "get_doc", id=note_id)["revision"]


def commits(remote):
    return int(git_out(remote, "rev-list", "--count", "main"))


# ----------------------------------------------------------------- patch ----


def test_patch_doc_replaces_one_passage(client, env):
    remote = env[4]
    before = commits(remote)
    out = call(client, "patch_doc", id=CONVENTIONS, old="Prefix automations with the domain.",
               new="Always prefix automations with the domain.")
    text = on_main(remote, CONVENTIONS)
    assert "Always prefix automations" in text and f"updated: {TODAY}" in text
    assert 'title: "Home Assistant conventions"' in text and "tags: [home-assistant]" in text
    assert commits(remote) == before + 1
    assert git_out(remote, "log", "-1", "--format=%s", "main") == "docs: edit note"
    # The result says what changed, and the revision is the one get_doc now reports.
    assert out["changes"][0]["path"] == f"notes/{CONVENTIONS}.md"
    assert out["bytes_after"] > out["bytes_before"] and out["revision"] != out["previous_revision"]
    assert out["revision"] == revision(client, CONVENTIONS)
    assert [h["id"] for h in call(client, "search", query="always prefix")] == [CONVENTIONS]


def test_patch_doc_errors_leave_main_untouched(client, env):
    remote = env[4]
    tip = git_out(remote, "rev-parse", "main")
    cases = [
        ({"old": "not in the note", "new": "x"}, "not found"),
        ({"old": "## ", "new": "### "}, "found 4 times"),
        ({"old": "x", "new": "x"}, "identical"),
        ({"old": "", "new": "x"}, "must not be empty"),
        ({"old": "Nothing else.", "new": "token ghp_Ab3dE5gH7jK9mN1pQ3sT5vX7zB9dF1"}, "secret"),
    ]
    for args, expected in cases:
        assert expected in call(client, "patch_doc", id=INCIDENTS, **args)["error"], args
    # The front matter cannot be reached through the body.
    assert "not found" in call(client, "patch_doc", id=MIGRATION, old="tags: [docker, migration]",
                               new="tags: [docker]")["error"]
    assert "not found" in call(client, "patch_doc", id="99999999-9999-4999-8999-999999999999",
                               old="a", new="b")["error"]
    assert git_out(remote, "rev-parse", "main") == tip


def test_patch_doc_replace_all(client, env):
    remote = env[4]
    call(client, "patch_doc", id=INCIDENTS, old="## ", new="### ", replace_all=True)
    text = on_main(remote, INCIDENTS)
    assert "### Cause" in text and "### Fix" in text and "#### Detail" in text


# ---------------------------------------------------------------- append ----


def test_append_doc_at_the_end(client, env):
    remote = env[4]
    call(client, "append_doc", id=CONVENTIONS, text="Added at the end.\n")
    text = on_main(remote, CONVENTIONS)
    assert text.endswith("Prefix automations with the domain.\n\nAdded at the end.\n")
    assert f"updated: {TODAY}" in text


def test_append_doc_to_a_section(client, env):
    remote = env[4]
    call(client, "append_doc", id=INCIDENTS, section="cause", text="Second cause.")
    assert "Slow disk scan.\n\nSecond cause.\n\n## Fix" in on_main(remote, INCIDENTS)
    # A section includes its sub-sections: the text goes after them.
    call(client, "append_doc", id=INCIDENTS, section="## Fix", text="Appended in fix.")
    assert "One step.\n\nAppended in fix.\n\n## Notes" in on_main(remote, INCIDENTS)
    # The last section ends at the end of the note.
    call(client, "append_doc", id=INCIDENTS, section="Notes", text="Tail.")
    assert on_main(remote, INCIDENTS).endswith("Nothing else.\n\nTail.\n")


def test_append_doc_section_errors(client):
    error = call(client, "append_doc", id=INCIDENTS, section="Missing", text="x")["error"]
    assert "not found" in error and "Cause" in error and "Fix" in error
    # A shell comment inside a code block is not a heading.
    assert "not found" in call(client, "append_doc", id=INCIDENTS, section="not a heading",
                               text="x")["error"]
    assert "must not be empty" in call(client, "append_doc", id=INCIDENTS, text="  ")["error"]


# ------------------------------------------------------------------ meta ----


def test_set_doc_status_changes_only_the_front_matter(client, env):
    remote = env[4]
    out = call(client, "set_doc_status", id=MIGRATION, status="up-to-date")
    text = on_main(remote, MIGRATION)
    assert "status: up-to-date" in text and f"updated: {TODAY}" in text
    assert [c["added"] for c in out["changes"]] == [2] and out["changes"][0]["removed"] == 2
    assert "Le volume nommé est lent." in text
    assert "already" in call(client, "set_doc_status", id=MIGRATION, status="up-to-date")["error"]
    assert "undeclared status" in call(client, "set_doc_status", id=MIGRATION, status="weird")["error"]


def test_set_doc_tags(client, env):
    remote = env[4]
    call(client, "set_doc_tags", id=CONVENTIONS, tags=["home-assistant", "docker"])
    assert "tags: [home-assistant, docker]" in on_main(remote, CONVENTIONS)
    assert call(client, "get_doc", id=CONVENTIONS)["tags"] == ["home-assistant", "docker"]
    assert "undeclared tag" in call(client, "set_doc_tags", id=CONVENTIONS, tags=["nope"])["error"]
    assert "already" in call(client, "set_doc_tags", id=CONVENTIONS,
                             tags=["home-assistant", "docker"])["error"]
    assert "tags must be" in call(client, "set_doc_tags", id=CONVENTIONS, tags=[])["error"]


# ------------------------------------------------------ expected_revision ----

EDITS = {
    "patch_doc": {"old": "Prefix", "new": "Always prefix"},
    "append_doc": {"text": "More."},
    "set_doc_status": {"status": "todo"},
    "set_doc_tags": {"tags": ["docker"]},
    "write_doc": {"title": "t", "description": "d", "tags": ["docker"], "status": "todo", "body": "b"},
}


@pytest.mark.parametrize("tool", sorted(EDITS))
def test_a_stale_revision_is_refused(client, env, tool):
    remote = env[4]
    tip = git_out(remote, "rev-parse", "main")
    error = call(client, tool, id=CONVENTIONS, expected_revision="deadbeef0000", **EDITS[tool])["error"]
    assert "changed since you read it" in error
    assert git_out(remote, "rev-parse", "main") == tip


def test_the_right_revision_is_accepted_and_changes_after_each_write(client):
    first = revision(client, CONVENTIONS)
    out = call(client, "patch_doc", id=CONVENTIONS, old="Prefix", new="Always prefix",
               expected_revision=first)
    assert out["previous_revision"] == first and out["revision"] != first
    # The old revision is now stale; a prefix of seven characters or more is enough.
    assert "changed since" in call(client, "append_doc", id=CONVENTIONS, text="x",
                                   expected_revision=first)["error"]
    assert "changed since" in call(client, "append_doc", id=CONVENTIONS, text="x",
                                   expected_revision=first[:4])["error"]
    assert call(client, "append_doc", id=CONVENTIONS, text="x",
                expected_revision=out["revision"][:7])["id"] == CONVENTIONS


def test_expected_revision_needs_an_id_when_creating(client):
    assert "only applies" in call(client, "write_doc", expected_revision="deadbeef0000",
                                  **EDITS["write_doc"])["error"]


def test_the_revision_is_checked_against_the_remote_not_the_stale_mirror(client, env):
    """Someone else edited the note after the last sync: the mirror still shows the old revision."""
    seed = env[3]
    seen = revision(client, CONVENTIONS)
    path = seed / "notes" / f"{CONVENTIONS}.md"
    path.write_text(path.read_text().replace("Prefix", "Someone else prefixed"))
    run("add", "-A", cwd=seed)
    run("commit", "-m", "edit elsewhere", cwd=seed)
    run("push", "origin", "main", cwd=seed)
    assert revision(client, CONVENTIONS) == seen
    assert "changed since" in call(client, "patch_doc", id=CONVENTIONS, old="domain", new="area",
                                   expected_revision=seen)["error"]


# --------------------------------------------------------------- dry run ----


def test_dry_run_shows_the_diff_and_writes_nothing(client, env):
    remote = env[4]
    tip, before = git_out(remote, "rev-parse", "main"), revision(client, CONVENTIONS)
    out = call(client, "patch_doc", id=CONVENTIONS, old="Prefix", new="Always prefix", dry_run=True)
    assert out["dry_run"] is True and "commit" not in out
    assert "-Prefix automations" in out["diff"] and "+Always prefix automations" in out["diff"]
    assert out["changes"][0]["path"] == f"notes/{CONVENTIONS}.md"
    assert out["revision"] != before and revision(client, CONVENTIONS) == before
    assert git_out(remote, "rev-parse", "main") == tip


@pytest.mark.parametrize("tool,args", [
    ("write_doc", EDITS["write_doc"]),
    ("append_doc", {"id": CONVENTIONS, "text": "More."}),
    ("set_doc_status", {"id": MIGRATION, "status": "up-to-date"}),
    ("declare_tag", {"tag": "networking", "description": "Network"}),
    ("remove_tag", {"tag": "unused"}),
    ("rename_tag", {"old": "migration", "new": "move"}),
    ("declare_status", {"status": "archived", "description": "Old"}),
    ("rename_status", {"old": "todo", "new": "pending"}),
])
def test_every_write_tool_supports_dry_run(client, env, tool, args):
    remote = env[4]
    tip = git_out(remote, "rev-parse", "main")
    out = call(client, tool, dry_run=True, **args)
    assert out["dry_run"] is True and out["diff"] and out["changes"]
    assert git_out(remote, "rev-parse", "main") == tip
    assert git_out(remote, "branch", "--format=%(refname:short)") == "main"


def test_dry_run_still_reports_errors(client):
    assert "undeclared tag" in call(client, "write_doc", dry_run=True,
                                    **{**EDITS["write_doc"], "tags": ["nope"]})["error"]
    assert "used by" in call(client, "remove_tag", tag="docker", dry_run=True)["error"]
    assert "nothing to change" in call(client, "declare_tag", tag="docker",
                                       description="Docker things", dry_run=True)["error"]


# ----------------------------------------------------------- write result ----


def test_write_doc_reports_sizes_and_revision(client):
    created = call(client, "write_doc", **EDITS["write_doc"])
    assert created["bytes_before"] == 0 and created["bytes_after"] > 0
    assert created["revision"] == revision(client, created["id"])
    updated = call(client, "write_doc", id=created["id"], expected_revision=created["revision"],
                   **{**EDITS["write_doc"], "body": "a longer body than before"})
    assert updated["previous_revision"] == created["revision"]
    assert updated["bytes_before"] == created["bytes_after"] and updated["bytes_after"] > updated["bytes_before"]
