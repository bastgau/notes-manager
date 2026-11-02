"""Shared constants and helpers for the tests."""

import json
import subprocess

TOKEN = "t" * 40
ACCEPT = "application/json, text/event-stream"
IDS = [
    "11111111-1111-4111-8111-111111111111",
    "22222222-2222-4222-8222-222222222222",
    "33333333-3333-4333-8333-333333333333",
]

TAGS_YAML = """\
# comment kept
docker:
  description: Docker things
home-assistant:
  description: Home Assistant things
migration:
  description: Migrations
unused:
  description: Nothing uses this
"""
STATUS_YAML = """\
todo:
  description: Not done
up-to-date:
  description: Fine
"""


def note(title, desc, tags, status, updated, body):
    return (f'---\ntitle: "{title}"\ndescription: "{desc}"\ntags: [{", ".join(tags)}]\n'
            f"status: {status}\nupdated: {updated}\n---\n\n{body}\n")


NOTES = {
    IDS[0]: note("Migration du volume Docker", "Déplacer le volume vers un montage bind",
                 ["docker", "migration"], "todo", "2026-10-26",
                 "# Migration\n\nLe volume nommé est lent. Utiliser un montage bind."),
    IDS[1]: note("Home Assistant conventions", "Naming rules", ["home-assistant"],
                 "up-to-date", "2026-10-12", "# Conventions\n\nPrefix automations with the domain."),
    IDS[2]: note("Résumé des incidents", "Incident summary", ["docker", "home-assistant"],
                 "up-to-date", "2026-10-30", ("# Incidents\n\nDocker timeouts hit Home Assistant.\n\n## Cause\n\nSlow disk scan.\n\n"
                 "## Fix\n\n```bash\n# not a heading\ndocker system df\n```\n\n### Detail\n\nOne step.\n\n## Notes\n\nNothing else.")),
}


def run(*args, cwd):
    subprocess.run(["git", *args], cwd=cwd, check=True, capture_output=True, text=True)


def git_out(repo_dir, *args):
    return subprocess.run(["git", *args], cwd=repo_dir, check=True, capture_output=True,
                          text=True).stdout.strip()


def git_raw(repo_dir, *args):
    """Like git_out, but keeps the output exactly as it is (trailing newline included)."""
    return subprocess.run(["git", *args], cwd=repo_dir, check=True, capture_output=True,
                          text=True).stdout


def rpc(client, method, params=None):
    """Send a JSON-RPC request to the MCP endpoint with the valid token."""
    body = {"jsonrpc": "2.0", "id": 1, "method": method, "params": params or {}}
    return client.post("/mcp", json=body, headers={
        "Authorization": f"Bearer {TOKEN}", "Accept": ACCEPT})


def tool_names(client):
    return {t["name"] for t in rpc(client, "tools/list").json()["result"]["tools"]}


def call(client, tool, **arguments):
    """Call a tool and return its data, or ``{"error": message}`` on a tool error."""
    r = rpc(client, "tools/call", {"name": tool, "arguments": arguments})
    assert r.status_code == 200, r.text
    result = r.json()["result"]
    if result.get("isError"):
        return {"error": result["content"][0]["text"]}
    data = result.get("structuredContent")
    if data is None:
        data = json.loads(result["content"][0]["text"])
    return data.get("result", data) if isinstance(data, dict) and list(data) == ["result"] else data
