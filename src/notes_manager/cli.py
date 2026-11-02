"""Command line entry point: ``notes-manager`` or ``python -m notes_manager``."""

import logging
import threading

import uvicorn

from notes_manager import __version__
from notes_manager.config import Config
from notes_manager.git_repo import Repo
from notes_manager.server import build_app
from notes_manager.store import Store
from notes_manager.sync import sync_loop

log = logging.getLogger("notes-manager")


def main() -> None:
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")
    cfg = Config.from_env()
    repo = Repo(cfg)
    repo.ensure_clone()
    repo.sync()
    store = Store(cfg.notes_dir)
    log.info("notes-manager %s: indexed %d notes (write tools %s)", __version__,
             len(store.snapshot.notes), "enabled" if cfg.write else "disabled")
    if cfg.sync_interval > 0:
        threading.Thread(target=sync_loop, args=(repo, store, cfg.sync_interval, threading.Event()),
                         daemon=True).start()
    uvicorn.run(build_app(cfg, store, repo), host=cfg.host, port=cfg.port,
                log_level="info", access_log=False)
