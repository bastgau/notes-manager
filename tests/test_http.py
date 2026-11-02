import pytest
from helpers import IDS, TOKEN, call, tool_names
from starlette.testclient import TestClient

from notes_manager.config import Config
from notes_manager.server import build_app


def test_auth(client):
    assert client.get("/healthz").text == "ok"
    for headers in ({}, {"Authorization": "Bearer wrong"}, {"Authorization": f"Basic {TOKEN}"}):
        r = client.post("/mcp", json={}, headers=headers)
        assert r.status_code == 401 and r.headers["www-authenticate"] == "Bearer"


def test_tools_over_http(client):
    assert {"search", "get_doc", "list_docs", "list_by_tag", "list_tags", "list_statuses",
            "validate_notes", "write_doc", "rename_tag", "rename_status", "declare_tag", "declare_status",
            "remove_tag", "remove_status"} <= tool_names(client)
    tags = {t["tag"]: t["count"] for t in call(client, "list_tags")}
    assert tags["docker"] == 2 and tags["unused"] == 0
    assert call(client, "get_doc", id=IDS[1])["title"] == "Home Assistant conventions"
    assert len(call(client, "list_by_tag", tag="docker")) == 2
    assert "Did you mean" in call(client, "list_by_tag", tag="dockr")["error"]
    assert call(client, "validate_notes")["ok"] is True


@pytest.mark.parametrize("bad", ["../../etc/passwd", "11111111-1111-4111-8111-11111111111", ""])
def test_get_doc_rejects_bad_ids(client, bad):
    assert "uuid" in call(client, "get_doc", id=bad)["error"]


def test_write_tools_absent_when_disabled(env):
    cfg, store, repo, *_ = env
    read_only = Config(**{**cfg.__dict__, "write": False})
    with TestClient(build_app(read_only, store, repo)) as c:
        names = tool_names(c)
    assert not names & {"write_doc", "rename_tag", "declare_tag", "remove_status"} and "search" in names
