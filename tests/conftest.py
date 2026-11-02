import pytest
from helpers import NOTES, STATUS_YAML, TAGS_YAML, TOKEN, run
from starlette.testclient import TestClient

from notes_manager.config import Config
from notes_manager.git_repo import Repo
from notes_manager.server import build_app
from notes_manager.store import Store


@pytest.fixture
def env(tmp_path):
    """A bare remote, a seed checkout used to push, and the clone the server mirrors."""
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
    cfg = Config(notes_dir=clone, token=TOKEN, repo_url=str(remote), write=True,
                 git_name="Test User", git_email="test@example.com")
    return cfg, Store(clone), Repo(cfg), seed, remote


@pytest.fixture
def client(env):
    cfg, store, repo, *_ = env
    with TestClient(build_app(cfg, store, repo)) as c:
        yield c
