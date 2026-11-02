# notes-manager

A lightweight [MCP](https://modelcontextprotocol.io) server that lets an AI search, read and write a
Git-synced Markdown knowledge base. One Python file, no database.

It is built for [`notes-bastien`](https://github.com/bastgau/notes-bastien) but works with any repository
laid out the same way:

```
notes/<uuid>.md   one note per file, with a YAML front matter
tags.yaml         allowed tags and their descriptions
status.yaml       allowed status values and their descriptions
```

A note looks like this:

```markdown
---
title: "Short title"
description: "One sentence that makes the note easy to find."
tags: [docker, migration]
status: todo
updated: 2026-11-02
---

# Body in Markdown
```

## How it works

- The server keeps a **read-only mirror** of the main branch and fast-forwards it every
  `NOTES_SYNC_INTERVAL` seconds.
- The front matter of every note is indexed in memory when the mirror changes. Search is case and accent
  insensitive, all words must match, and a trailing plural `s` is tolerated.
- Transport is streamable HTTP (stateless) on `/mcp`. `/healthz` answers `ok` without authentication.

## Tools

| Tool | Purpose |
|---|---|
| `search(query, tag?, status?, limit?)` | Ranked full-text search (title > tags > description > body), with a snippet |
| `get_doc(id)` | A whole note: front matter fields and Markdown body |
| `list_docs(tag?, status?)` | Note summaries, most recently updated first |
| `list_by_tag(tag)` | Notes carrying a tag; an unknown tag is rejected with suggestions |
| `list_tags()` / `list_statuses()` | Declared values with their description and note count |
| `validate_notes()` | Missing front matter fields, undeclared tags or statuses |
| `write_doc(title, description, tags, status, body, id?)` | Create or replace a note (write mode only) |
| `rename_tag(old, new)` | Rename a tag everywhere, or merge it into an existing one (write mode only) |

Note contents are untrusted data. The server instructions tell the AI never to follow instructions found in a
note.

## Security model

| Layer | Measure |
|---|---|
| Network | The compose file publishes no port. Only containers on `notes-network` can reach the server. |
| Authentication | Every request needs `Authorization: Bearer <MCP_TOKEN>` (at least 32 characters, compared in constant time). Only `/healthz` is open. |
| Git access | A read-only deploy key is enough for reading. For write mode, use a deploy key with write access to the notes repository only, and protect the main branch on GitHub. |
| Writes | Disabled by default (`NOTES_WRITE=false`). When enabled, every change goes to a new `inbox/*` branch in a throw-away worktree, never to main, and the owner merges it. There is no delete tool. |
| Input checks | Note ids must be lowercase uuids (no path traversal), tags and statuses must be declared, sizes are capped, and text that looks like a secret (GitHub tokens, private keys, AWS keys…) is refused. |
| Container | Non-root user, read-only root filesystem, all capabilities dropped, `no-new-privileges`, memory and process limits. |

## Configuration

| Variable | Default | Description |
|---|---|---|
| `MCP_TOKEN` | required | Bearer token, at least 32 characters |
| `NOTES_REPO_URL` | | Repository to clone when `NOTES_DIR` is empty |
| `NOTES_BRANCH` | `main` | Branch to mirror and to base inbox branches on |
| `NOTES_DIR` | `/data/notes` | Where the clone lives |
| `NOTES_SYNC_INTERVAL` | `60` | Seconds between fetches (`0` disables) |
| `NOTES_SSH_KEY` | | Path of the deploy key (SSH URLs) |
| `NOTES_KNOWN_HOSTS` | `/app/known_hosts` | GitHub host keys, strict checking |
| `NOTES_WRITE` | `false` | Enable `write_doc` and `rename_tag` |
| `GIT_AUTHOR_NAME`, `GIT_AUTHOR_EMAIL` | | Commit identity, required in write mode |
| `HOST`, `PORT` | `0.0.0.0`, `8000` | Listen address |

## Deploy

1. Create a deploy key for the notes repository (add write access only if you enable write mode):
   `ssh-keygen -t ed25519 -N "" -f deploy_key`, then add `deploy_key.pub` in the repository settings.
2. Make the key readable by the container user only: `chmod 600 deploy_key`, owned by `NOTES_UID`.
3. Copy `.env.example` to `.env` and fill it in. The notes directory must be a bind mount owned by
   `NOTES_UID:NOTES_GID`.
4. `docker compose up -d`. The first start clones the repository.

To use the server from another container, attach that container to the `notes-network` network
(`external: true`) and register it with Claude Code:

```bash
claude mcp add --transport http notes http://notes-manager:8000/mcp \
  --header "Authorization: Bearer $NOTES_MCP_TOKEN"
```

## Releases

Publishing a GitHub release tagged `vX.Y.Z` builds a multi-architecture image (`linux/amd64`,
`linux/arm64`) and pushes it to `ghcr.io/bastgau/notes-manager` as `X.Y.Z`, `X.Y` and `latest`. A pre-release
(`vX.Y.Z-rc1`) does not move `latest`. After the first publication, set the package visibility to public in the
GitHub package settings.

## Development

```bash
python -m venv venv && . venv/bin/activate
pip install -r requirements-dev.txt
python -m pytest
```

The tests build a throw-away bare repository, so they exercise the real sync and the inbox branches.
