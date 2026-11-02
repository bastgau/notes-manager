"""Server configuration, read from environment variables."""

import os
from dataclasses import dataclass
from pathlib import Path


@dataclass(frozen=True)
class Config:
    notes_dir: Path
    token: str
    repo_url: str = ""
    branch: str = "main"
    sync_interval: int = 60
    ssh_key: str = ""
    known_hosts: str = "/app/known_hosts"
    write: bool = False
    git_name: str = ""
    git_email: str = ""
    host: str = "0.0.0.0"
    port: int = 8000

    @staticmethod
    def from_env(env: dict[str, str] | None = None) -> "Config":
        e = os.environ if env is None else env
        token = e.get("MCP_TOKEN", "")
        if len(token) < 32:
            raise SystemExit("MCP_TOKEN is required and must be at least 32 characters long")
        cfg = Config(
            notes_dir=Path(e.get("NOTES_DIR", "/data/notes")),
            token=token,
            repo_url=e.get("NOTES_REPO_URL", ""),
            branch=e.get("NOTES_BRANCH", "main"),
            sync_interval=int(e.get("NOTES_SYNC_INTERVAL", "60")),
            ssh_key=e.get("NOTES_SSH_KEY", ""),
            known_hosts=e.get("NOTES_KNOWN_HOSTS", "/app/known_hosts"),
            write=e.get("NOTES_WRITE", "false").lower() in ("1", "true", "yes"),
            git_name=e.get("GIT_AUTHOR_NAME", ""),
            git_email=e.get("GIT_AUTHOR_EMAIL", ""),
            host=e.get("HOST", "0.0.0.0"),
            port=int(e.get("PORT", "8000")),
        )
        if cfg.write and not (cfg.git_name and cfg.git_email):
            raise SystemExit("NOTES_WRITE=true requires GIT_AUTHOR_NAME and GIT_AUTHOR_EMAIL")
        return cfg
