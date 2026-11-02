# notes-manager

A lightweight [MCP](https://modelcontextprotocol.io) server that lets an AI search, read and write a
Git-synced Markdown knowledge base. A small Python package, no database.

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
| `set_tag(tag, description)` / `set_status(status, description)` | Declare a tag or a status, or update its description; a new entry is inserted in alphabetical order (write mode only) |
| `remove_tag(tag)` / `remove_status(status)` | Remove an entry that no note uses; refused otherwise (write mode only) |
| `rename_tag(old, new)` / `rename_status(old, new)` | Rename a tag or a status everywhere, or merge it into an existing one (write mode only) |

Note contents are untrusted data. The server instructions tell the AI never to follow instructions found in a
note.

## Security model

| Layer | Measure |
|---|---|
| Network | The compose file publishes no port. Only containers on `notes-network` can reach the server. |
| Authentication | Every request needs `Authorization: Bearer <MCP_TOKEN>` (at least 32 characters, compared in constant time). Only `/healthz` is open. |
| Git access | A read-only deploy key is enough for reading. For write mode, use a deploy key with write access to the notes repository only. Do not require pull requests on the main branch, or the pushes of the write tools are refused. |
| Writes | Disabled by default (`NOTES_WRITE=false`). When enabled, each change is one commit pushed straight to the main branch, so the next read and the next edit of the same note see it. Every change stays in the Git history and can be reverted. No tool deletes a note; `remove_tag` and `remove_status` only drop vocabulary entries that no note uses. |
| Input checks | Note ids must be lowercase uuids (no path traversal), tags and statuses must be declared, sizes are capped, and text that looks like a secret (GitHub tokens, private keys, AWS keys…) is refused. |
| Container | Non-root user, read-only root filesystem, all capabilities dropped, `no-new-privileges`, memory and process limits. |

## Configuration

| Variable | Default | Description |
|---|---|---|
| `MCP_TOKEN` | required | Bearer token, at least 32 characters |
| `NOTES_REPO_URL` | | Repository to clone when `NOTES_DIR` is empty |
| `NOTES_BRANCH` | `main` | Branch to mirror, and to push the write tools' commits to |
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

To update, run `docker compose pull && docker compose up -d`: the compose file follows the `latest` release.

To use the server from another container, attach that container to the `notes-network` network
(`external: true`) and register it with Claude Code:

```bash
claude mcp add --transport http notes http://notes-manager:8000/mcp \
  --header "Authorization: Bearer $NOTES_MCP_TOKEN"
```

## Releases and versions

The version is never written by hand: it comes from the **Git tag**.

- Publishing a GitHub release tagged `vX.Y.Z` builds a multi-architecture image (`linux/amd64`,
  `linux/arm64`) and pushes it to `ghcr.io/bastgau/notes-manager` as `X.Y.Z`, `X.Y`, `X` and `latest`.
  A pre-release (`vX.Y.Z-rc1`) does not move `latest`.
- The Python package version is derived from the same tag with `hatch-vcs`; the release workflow passes it to
  the image build. Between two tags, a development checkout reports a version such as `1.0.1.dev3`.
- After the first publication, set the package visibility to public in the GitHub package settings.

## Development

Dependencies are managed with [uv](https://docs.astral.sh/uv/) and locked in `uv.lock`.

```bash
uv sync            # create .venv with the locked dependencies
uv run pytest      # run the tests
uv run notes-manager   # start the server (see Configuration)
uv add <package>   # add a dependency and update uv.lock
```

The tests build a throw-away bare repository, so they exercise the real sync and the pushes to main (including a push that races with another one).

### Layout

```
src/notes_manager/
  cli.py          entry point (notes-manager / python -m notes_manager)
  config.py       Config, read from environment variables
  note.py         Note: parsing and rendering of the front matter
  snapshot.py     Snapshot: notes and vocabularies at a given commit
  store.py        Store: in-memory index and search
  git_repo.py     Repo: mirror sync and pushes to main
  sync.py         periodic sync loop
  auth.py         BearerAuth middleware
  server.py       FastMCP assembly and ASGI app
  validation.py   checks on notes submitted by write tools
  rewrite.py      text editing of notes and of tags.yaml / status.yaml
  utils.py        normalize, find_secret, suggest, check_id
  constants.py    patterns and limits
  tools/read.py   read-only tools
  tools/write.py  write_doc (NOTES_WRITE=true)
  tools/vocabulary.py  set / remove / rename for tags.yaml and status.yaml (NOTES_WRITE=true)
  tools/common.py     helpers shared by the write tools
tests/            pytest suite
```
