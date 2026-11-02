import json
import subprocess
from pathlib import Path

import pytest
from starlette.testclient import TestClient

import notes_manager as nm

TOKEN = "t" * 40
IDS = [
    "11111111-1111-4111-8111-111111111111",
    "22222222-2222-4222-8222-222222222222",
    "33333333-3333-4333-8333-333333333333",
]

TAGS_YAML = """\
# comment kept
docker:
  description: Docker things
home-assistant:
  description: Home Assistant things
migration:
  description: Migrations
unused:
  description: Nothing uses this
"""
STATUS_YAML = """\
up-to-date:
  description: Fine
todo:
  description: Not done
"""


def note(title, desc, tags, status, updated, body):
    return (f'---\ntitle: "{title}"\ndescription: "{desc}"\ntags: [{", ".join(tags)}]\n'
            f"status: {status}\nupdated: {updated}\n---\n\n{body}\n")


NOTES = {
    IDS[0]: note("Migration du volume Docker", "Déplacer le volume vers un montage bind",
                 ["docker", "migration"], "todo", "2026-10-26",
                 "# Migration\n\nLe volume nommé est lent. Utiliser un montage bind."),
    IDS[1]: note("Home Assistant conventions", "Naming rules", ["home-assistant"],
                 "up-to-date", "2026-10-12", "# Conventions\n\nPrefix automations with the domain."),
    IDS[2]: note("Résumé des incidents", "Incident summary", ["docker", "home-assistant"],
                 "up-to-date", "2026-10-30", "# Incidents\n\nDocker timeouts hit Home Assistant."),
}


def run(*args, cwd):
    subprocess.run(["git", *args], cwd=cwd, check=True, capture_output=True, text=True)


@pytest.fixture
def env(tmp_path):
    remote, seed, clone = tmp_path / "remote.git", tmp_path / "seed", tmp_path / "clone"
    run("init", "--bare", "-b", "main", str(remote), cwd=tmp_path)
    seed.mkdir()
    run("init", "-b", "main", cwd=seed)
    run("config", "user.name", "Seed", cwd=seed)
    run("config", "user.email", "seed@example.com", cwd=seed)
    (seed / "notes").mkdir()
    (seed / "tags.yaml").write_text(TAGS_YAML)
    (seed / "status.yaml").write_text(STATUS_YAML)
    for note_id, text in NOTES.items():
        (seed / "notes" / f"{note_id}.md").write_text(text)
    run("add", "-A", cwd=seed)
    run("commit", "-m", "seed", cwd=seed)
    run("remote", "add", "origin", str(remote), cwd=seed)
    run("push", "origin", "main", cwd=seed)
    run("clone", str(remote), str(clone), cwd=tmp_path)
    cfg = nm.Config(notes_dir=clone, token=TOKEN, repo_url=str(remote), write=True,
                    git_name="Test User", git_email="test@example.com")
    return cfg, nm.Store(clone), nm.Repo(cfg), seed, remote


@pytest.fixture
def client(env):
    cfg, store, repo, *_ = env
    with TestClient(nm.build_app(cfg, store, repo)) as c:
        yield c


def call(client, tool, **arguments):
    body = {"jsonrpc": "2.0", "id": 1, "method": "tools/call",
            "params": {"name": tool, "arguments": arguments}}
    r = client.post("/mcp", json=body, headers={
        "Authorization": f"Bearer {TOKEN}",
        "Accept": "application/json, text/event-stream"})
    assert r.status_code == 200, r.text
    result = r.json()["result"]
    if result.get("isError"):
        return {"error": result["content"][0]["text"]}
    data = result.get("structuredContent")
    if data is None:
        data = json.loads(result["content"][0]["text"])
    return data.get("result", data) if isinstance(data, dict) and list(data) == ["result"] else data


def git_out(repo_dir, *args):
    return subprocess.run(["git", *args], cwd=repo_dir, check=True, capture_output=True,
                          text=True).stdout.strip()


# ----------------------------------------------------------------- store ----


def test_search_is_accent_and_case_insensitive(env):
    store = env[1]
    assert [r["id"] for r in store.search("resume", None, None, 10)] == [IDS[2]]
    assert [r["id"] for r in store.search("MIGRATION", None, None, 10)] == [IDS[0]]


def test_search_tolerates_plurals(env):
    store = env[1]
    assert [r["id"] for r in store.search("volumes", None, None, 10)] == [IDS[0]]
    assert [r["id"] for r in store.search("incident", None, None, 10)] == [IDS[2]]
    assert [r["id"] for r in store.search("incidents", None, None, 10)] == [IDS[2]]


def test_search_requires_all_words_and_ranks_title_first(env):
    store = env[1]
    assert store.search("docker zzz", None, None, 10) == []
    ids = [r["id"] for r in store.search("home assistant", None, None, 10)]
    assert ids[0] == IDS[1] and IDS[2] in ids


def test_search_filters_and_snippet(env):
    store = env[1]
    hits = store.search("docker", "migration", None, 10)
    assert [h["id"] for h in hits] == [IDS[0]]
    assert "docker" in hits[0]["snippet"].lower() or hits[0]["snippet"] == ""
    assert store.search("docker", None, "up-to-date", 10)[0]["id"] == IDS[2]
    with pytest.raises(ValueError):
        store.search("   ", None, None, 10)


def test_validate_flags_undeclared_values(env):
    cfg, store, *_ = env
    (cfg.notes_dir / "notes" / "44444444-4444-4444-8444-444444444444.md").write_text(
        note("Bad", "bad", ["nope"], "weird", "2026-01-01", "x"))
    (cfg.notes_dir / "notes" / "not-a-uuid.md").write_text("ignored")
    store.reload()
    problems = store.snapshot.problems()
    assert len(problems) == 1
    assert {"undeclared tag: nope", "undeclared status: weird"} <= set(problems[0]["problems"])


# ------------------------------------------------------------------ http ----


def test_auth(client):
    assert client.get("/healthz").text == "ok"
    for headers in ({}, {"Authorization": "Bearer wrong"}, {"Authorization": f"Basic {TOKEN}"}):
        r = client.post("/mcp", json={}, headers=headers)
        assert r.status_code == 401 and r.headers["www-authenticate"] == "Bearer"


def test_tools_over_http(client):
    names = {t["name"] for t in client.post("/mcp", json={
        "jsonrpc": "2.0", "id": 1, "method": "tools/list"}, headers={
        "Authorization": f"Bearer {TOKEN}",
        "Accept": "application/json, text/event-stream"}).json()["result"]["tools"]}
    assert {"search", "get_doc", "list_docs", "list_by_tag", "list_tags", "list_statuses",
            "validate_notes", "write_doc", "rename_tag"} <= names
    tags = {t["tag"]: t["count"] for t in call(client, "list_tags")}
    assert tags["docker"] == 2 and tags["unused"] == 0
    assert call(client, "get_doc", id=IDS[1])["title"] == "Home Assistant conventions"
    assert len(call(client, "list_by_tag", tag="docker")) == 2
    assert "Did you mean" in call(client, "list_by_tag", tag="dockr")["error"]


@pytest.mark.parametrize("bad", ["../../etc/passwd", "11111111-1111-4111-8111-11111111111", ""])
def test_get_doc_rejects_bad_ids(client, bad):
    assert "uuid" in call(client, "get_doc", id=bad)["error"]


def test_write_tools_absent_when_disabled(env):
    cfg, store, repo, *_ = env
    ro = nm.Config(**{**cfg.__dict__, "write": False})
    with TestClient(nm.build_app(ro, store, repo)) as c:
        names = {t["name"] for t in c.post("/mcp", json={
            "jsonrpc": "2.0", "id": 1, "method": "tools/list"}, headers={
            "Authorization": f"Bearer {TOKEN}",
            "Accept": "application/json, text/event-stream"}).json()["result"]["tools"]}
    assert "write_doc" not in names and "rename_tag" not in names and "search" in names


# ----------------------------------------------------------------- write ----


def test_write_doc_creates_inbox_branch_and_never_touches_main(client, env):
    _, _, _, seed, remote = env
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
    assert nm.parse_note(out["id"], show).problems == []


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
    assert "move:\n  description: Migrations" in git_out(remote, "show", f"{out['branch']}:tags.yaml")
    assert "# comment kept" in git_out(remote, "show", f"{out['branch']}:tags.yaml")
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


# ------------------------------------------------------------------ sync ----


def test_sync_picks_up_new_commits(env):
    cfg, store, repo, seed, _ = env
    assert repo.sync() is False
    (seed / "notes" / "55555555-5555-4555-8555-555555555555.md").write_text(
        note("Fresh", "Fresh note", ["docker"], "todo", "2026-11-01", "fresh body"))
    run("add", "-A", cwd=seed)
    run("commit", "-m", "add", cwd=seed)
    run("push", "origin", "main", cwd=seed)
    assert repo.sync() is True
    store.reload()
    assert "55555555-5555-4555-8555-555555555555" in store.snapshot.notes
    assert repo.sync() is False


def test_config_requires_strong_token_and_identity():
    with pytest.raises(SystemExit):
        nm.Config.from_env({"MCP_TOKEN": "short"})
    with pytest.raises(SystemExit):
        nm.Config.from_env({"MCP_TOKEN": "x" * 40, "NOTES_WRITE": "true"})
    cfg = nm.Config.from_env({"MCP_TOKEN": "x" * 40})
    assert cfg.write is False and cfg.port == 8000
