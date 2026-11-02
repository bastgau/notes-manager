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
related: [3f0c8e0a-9c1d-4b7e-8a52-1d2e3f4a5b6c]   # optional: ids of related notes
updated: 2026-11-02
---

# Body in Markdown
```

## How it works

- The server keeps a **read-only mirror** of the main branch and fast-forwards it every
  `NOTES_SYNC_INTERVAL` seconds.
- The front matter of every note is indexed in memory when the mirror changes. Search is case and accent
  insensitive, all words must match, and a trailing plural `s` is tolerated.
- Transport is streamable HTTP (stateless) on `/mcp`. Two routes answer without authentication: `/healthz` (`ok`) and `/version`.

## Tools

| Tool | Purpose |
|---|---|
| `search(query, tag?, status?, limit?)` | Ranked full-text search (title > tags > description > body). Each result has the best matching passage (`snippet`, cut at words, centred on the match), its `section` and `line`, and the fields it matched (`matched_in`) |
| `get_doc(id, section?)` | A note: front matter fields, `revision`, the notes it is `related` to and those that link to it (`linked_from`), and the Markdown body; with `section`, only that section (sub-sections included) |
| `get_outline(id)` | The headings of a note with their level, line and size, without its text |
| `list_docs(tag?, status?, updated_since?, updated_until?, sort?, limit?)` | Note summaries, most recently updated first; dates are `YYYY-MM-DD`, both inclusive; `sort` is `updated` or `title` |
| `list_by_tag(tag)` | Notes carrying a tag; an unknown tag is rejected with suggestions |
| `list_tags()` / `list_statuses()` | Declared values with their description and note count |
| `server_info()` | The running server: `version` and `commit` of the build, whether write tools are enabled, notes indexed, the commit the mirror is at, uptime and `zombie_processes` (should stay at 0) |
| `validate_notes()` | Errors (`problems`): missing fields, undeclared tags or statuses, bad dates, broken links. Warnings: unused tags or statuses, unsorted vocabulary files, duplicate titles |
| `get_doc_history(id, limit?)` | The commits that changed a note, newest first, with the `revision` each produced |
| `get_doc_version(id, commit)` | A note as it was at a commit, without changing anything |
| `write_doc(title, description, tags, status, body, id?)` | Create a note, or replace a whole one (write mode only) |
| `patch_doc(id, old, new, replace_all?)` | Replace an exact passage of the body, without resending the note (write mode only) |
| `append_doc(id, text, section?)` | Add text at the end of a note or of one of its sections (write mode only) |
| `set_doc_status(id, status)` / `set_doc_tags(id, tags)` | Change the metadata of a note, leaving its body alone (write mode only) |
| `set_doc_related(id, related)` | Set the notes related to a note (their ids); an empty list removes the links (write mode only) |
| `restore_doc(id, commit)` | Go back to an earlier version of a note, as a new commit; the history is kept (write mode only) |
| `declare_tag(tag, description)` / `declare_status(status, description)` | Declare a tag or a status in `tags.yaml` / `status.yaml`, or update its description; a new entry is inserted in alphabetical order. No note is changed (write mode only) |
| `remove_tag(tag)` / `remove_status(status)` | Remove an entry that no note uses; refused otherwise (write mode only) |
| `rename_tag(old, new)` / `rename_status(old, new)` | Rename a tag or a status everywhere, or merge it into an existing one (write mode only) |

Note contents are untrusted data. The server instructions tell the AI never to follow instructions found in a
note.

### Safe edits

Every write tool takes the same two options:

- **`dry_run`**: nothing is committed; the result holds the `diff` and the lines added and removed per file.
- **`expected_revision`** (note tools): the `revision` returned by `get_doc`, `search` and `list_docs` is the Git hash of the note file, so it changes exactly when the note changes. If the note was modified since you read it (by another session, for instance), the write is refused. The check is made against the freshly fetched `main`, not against the mirror, which can be a few seconds late. A prefix of 7 characters or more is enough.

A write returns the new `revision`, the `previous_revision`, the sizes before and after (`bytes_before`, `bytes_after`) and the `changes` per file.

To change a few lines, prefer `patch_doc` or `append_doc`: they cost a few dozen tokens instead of resending the whole note.

## Security model

| Layer | Measure |
|---|---|
| Network | The compose file publishes no port. Only containers on `notes-network` can reach the server. |
| Authentication | Every request needs `Authorization: Bearer <MCP_TOKEN>` (at least 32 characters, compared in constant time). Only `/healthz` is open. |
| Git access | A read-only deploy key is enough for reading. For write mode, use a deploy key with write access to the notes repository only. Do not require pull requests on the main branch, or the pushes of the write tools are refused. |
| Writes | Disabled by default (`NOTES_WRITE=false`). When enabled, each change is one commit pushed straight to the main branch, so the next read and the next edit of the same note see it. Every change stays in the Git history and can be reverted. No tool deletes a note; `remove_tag` and `remove_status` only drop vocabulary entries that no note uses. |
| Input checks | Note ids must be lowercase uuids (no path traversal), tags and statuses must be declared, sizes are capped, and text that looks like a secret (GitHub tokens, private keys, AWS keys…) is refused. |
| Container | Non-root user, read-only root filesystem, all capabilities dropped, `no-new-privileges`, memory and process limits. `tini` is process 1, so that the processes `git` and `ssh` leave orphaned are collected instead of piling up as zombies. |

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
| `NOTES_WRITE` | `false` | Enable the write tools (`write_doc`, `patch_doc`, `append_doc`, `set_doc_*`, and the tag and status tools) |
| `GIT_AUTHOR_NAME`, `GIT_AUTHOR_EMAIL` | | Commit identity, required in write mode |
| `HOST`, `PORT` | `0.0.0.0`, `8000` | Listen address |

## Deploy

1. Create a deploy key for the notes repository (add write access only if you enable write mode):
   `ssh-keygen -t ed25519 -N "" -f deploy_key`, then add `deploy_key.pub` in the repository settings.
2. Make the key readable by the container user only: `chmod 600 deploy_key`, owned by uid `10001`.
3. Copy `.env.example` to `.env` and fill it in. The notes directory must be a bind mount owned by
   uid `10001`, the user of the image (it has to be a fixed one: `ssh` refuses to run for a uid without a
   passwd entry).
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
- The version is built into the image, and the commit it was built from too (`GIT_COMMIT`, set by the release workflow). To know what is running, without a token:

  ```bash
  curl http://notes-manager:8000/version
  # {"name": "notes-manager", "version": "1.2.4", "commit": "56c04f1…"}
  ```

  Inside the container, `docker exec notes-manager python -c "import notes_manager; print(notes_manager.__version__)"` gives the same version. The `server_info` tool adds the health of the server.
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
  sync.py         periodic sync loop (warns when zombie processes pile up)
  processes.py    running commands without leaving processes behind; counting zombies
  auth.py         BearerAuth middleware
  server.py       FastMCP assembly and ASGI app (public routes: /healthz, /version)
  buildinfo.py    version and commit of the build
  validation.py   checks on notes submitted by write tools
  rewrite.py      text editing of notes and of tags.yaml / status.yaml
  utils.py        normalize, find_secret, suggest, check_id
  constants.py    patterns and limits
  tools/read.py   read-only tools
  markdown.py     headings and sections (code blocks are skipped)
  tools/info.py     server_info
  tools/history.py  get_doc_history, get_doc_version
  tools/write.py  write_doc, patch_doc, append_doc, set_doc_status, set_doc_tags, set_doc_related, restore_doc (NOTES_WRITE=true)
  tools/vocabulary.py  set / remove / rename for tags.yaml and status.yaml (NOTES_WRITE=true)
  tools/common.py     helpers shared by the write tools
tests/            pytest suite
```
