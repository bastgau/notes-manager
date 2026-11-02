"""What this server is: the version and the commit it was built from."""

import os
import time

from notes_manager import __version__

STARTED = time.time()


def build_info() -> dict:
    """The version comes from the release tag (see the Dockerfile); the commit from a build argument."""
    return {
        "name": "notes-manager",
        "version": __version__,
        "commit": os.environ.get("NOTES_MANAGER_COMMIT", "unknown"),
    }
