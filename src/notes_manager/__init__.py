"""notes-manager: an MCP server over a Git-synced folder of Markdown notes.

The notes live in a Git repository laid out as:

    notes/<uuid>.md   one note per file, with a YAML front matter
    tags.yaml         allowed tags and their descriptions
    status.yaml       allowed status values and their descriptions

The server keeps a read-only mirror of the main branch, indexes the front
matter in memory and exposes search tools over streamable HTTP, protected by a
bearer token. Write tools are disabled by default; when enabled they never
touch the main branch: every change is pushed to an ``inbox/*`` branch.
"""

from importlib.metadata import PackageNotFoundError, version

try:
    __version__ = version("notes-manager")
except PackageNotFoundError:  # running from a source tree that is not installed
    __version__ = "0.0.0"
