import pytest
from helpers import call, tool_names
from starlette.testclient import TestClient

import notes_manager
from notes_manager.config import Config
from notes_manager.server import build_app


def test_version_route_needs_no_token_and_reports_the_build(monkeypatch, client_factory):
    monkeypatch.setenv("NOTES_MANAGER_COMMIT", "0123abc")
    with client_factory() as client:
        response = client.get("/version")
    assert response.status_code == 200 and response.headers["content-type"] == "application/json"
    assert response.json() == {"name": "notes-manager", "version": notes_manager.__version__,
                               "commit": "0123abc"}


def test_commit_is_unknown_when_the_image_was_built_without_it(monkeypatch, client_factory):
    monkeypatch.delenv("NOTES_MANAGER_COMMIT", raising=False)
    with client_factory() as client:
        assert client.get("/version").json()["commit"] == "unknown"


def test_only_healthz_and_version_are_open(client):
    assert client.get("/healthz").text == "ok"
    assert client.get("/version").status_code == 200
    for path in ("/mcp", "/", "/versions", "/version/x"):
        assert client.post(path, json={}).status_code == 401


def test_server_info_tool(client):
    info = call(client, "server_info")
    assert info["name"] == "notes-manager" and info["version"] == notes_manager.__version__
    assert info["write_enabled"] is True and info["branch"] == "main" and info["notes"] == 3
    assert len(info["mirror_commit"]) == 12 and info["uptime_seconds"] >= 0
    assert isinstance(info["zombie_processes"], int)


def test_server_info_is_available_and_accurate_without_write_mode(env):
    cfg, store, repo, *_ = env
    with TestClient(build_app(Config(**{**cfg.__dict__, "write": False}), store, repo)) as c:
        assert "server_info" in tool_names(c)
        assert call(c, "server_info")["write_enabled"] is False


@pytest.fixture
def client_factory(env):
    cfg, store, repo, *_ = env
    return lambda: TestClient(build_app(cfg, store, repo))
