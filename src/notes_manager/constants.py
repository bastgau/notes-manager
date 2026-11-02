"""Patterns and limits shared by the whole package."""

import re

UUID_RE = re.compile(r"^[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}$")
NAME_RE = re.compile(r"^[a-z][a-z0-9]*(-[a-z0-9]+)*$")
FRONT_MATTER_RE = re.compile(r"\A---\r?\n(.*?)\r?\n---\r?\n?(.*)\Z", re.S)
CONTROL_RE = re.compile(r"[\x00-\x1f\x7f]")
SECRET_RE = re.compile(
    r"(ghp_[A-Za-z0-9]{20,}|gho_[A-Za-z0-9]{20,}|github_pat_[A-Za-z0-9_]{20,}"
    r"|AKIA[0-9A-Z]{16}|-----BEGIN [A-Z ]*PRIVATE KEY-----|xox[abp]-[A-Za-z0-9-]{10,}"
    r"|sk-[A-Za-z0-9]{20,})"
)

REQUIRED_FIELDS = ("title", "description", "tags", "status", "updated")

MAX_TITLE = 200
MAX_DESCRIPTION = 500
MAX_BODY_BYTES = 200_000
MAX_TAGS = 8
MAX_SEARCH_LIMIT = 50
