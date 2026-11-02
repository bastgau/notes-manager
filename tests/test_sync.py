import pytest
from helpers import note, run

from notes_manager.config import Config


def test_sync_picks_up_new_commits(env):
    cfg, store, repo, seed, _ = env
    assert repo.sync() is False
    new_id = "55555555-5555-4555-8555-555555555555"
    (seed / "notes" / f"{new_id}.md").write_text(
        note("Fresh", "Fresh note", ["docker"], "todo", "2026-11-01", "fresh body"))
    run("add", "-A", cwd=seed)
    run("commit", "-m", "add", cwd=seed)
    run("push", "origin", "main", cwd=seed)
    assert repo.sync() is True
    store.reload()
    assert new_id in store.snapshot.notes
    assert repo.sync() is False


def test_config_requires_strong_token_and_identity():
    with pytest.raises(SystemExit):
        Config.from_env({"MCP_TOKEN": "short"})
    with pytest.raises(SystemExit):
        Config.from_env({"MCP_TOKEN": "x" * 40, "NOTES_WRITE": "true"})
    cfg = Config.from_env({"MCP_TOKEN": "x" * 40})
    assert cfg.write is False and cfg.port == 8000
