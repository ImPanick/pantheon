# SPDX-License-Identifier: AGPL-3.0-or-later
"""`P22-21` / `integrate-e` — the room MCP servers, APIs, mail and calendars are
added in has one name, and every sentence that sends a person there says it.

**Measured on the merged tree `0b9adaa`:** the room was named five ways — the
tab ("MCP & Integrations"), the scaffold's check hint, both READMEs and both
registrations' `where` ("Settings → Integrations → + → MCP Tool Server"), an
import's missing line ("Add it in Integrations"), the HTTP step's two hints
and the calendar's CalDAV link ("Settings → Integrations"), the assistant's
`app_api` refusal ("Settings → MCP", a place that never existed) and the Google
mail hint ("Settings → Integrations"). Settings → Integrations is a door to the
room since `P22-21`; the words now name the room, from one place on each side
(`Law 7`): `src/workbench_rooms.py` and `static/js/workbench/rooms.js`, held
equal here by importing the module, not reading it.

Driven (`Law 20`): each sentence is the value the code hands a person — the
constant, the function's answer, the refusal `do_app_api` returns. The one
file read is `index.html`'s door card, scoped to its element: markup cannot
import the table (`workbench`'s glyph precedent).
"""
from __future__ import annotations

import asyncio
import json
import shutil
import subprocess
from html.parser import HTMLParser
from pathlib import Path

import pytest

from src import workbench_rooms as rooms

ROOT = Path(__file__).resolve().parents[1]
ROOMS_JS = ROOT / "static" / "js" / "workbench" / "rooms.js"
STALE = ("Settings → Integrations", "Settings → MCP", "Add it in Integrations")


def _browser_names() -> dict:
    if not shutil.which("node"):
        pytest.skip("node binary not on PATH")
    script = (f"const m = await import({json.dumps(ROOMS_JS.as_uri())});\n"
              "console.log(JSON.stringify(m.ROOM_NAMES));\n")
    proc = subprocess.run(["node", "--input-type=module", "-e", script], capture_output=True,
                          text=True, timeout=30)
    assert proc.returncode == 0, proc.stderr
    return json.loads(proc.stdout)


def test_the_browser_and_the_server_name_the_rooms_alike():
    names = _browser_names()
    assert names["integrations"] == rooms.INTEGRATIONS_ROOM == "MCP & Integrations"
    assert names["skills"] == rooms.SKILLS_ROOM
    assert rooms.INTEGRATIONS_ROOM in rooms.INTEGRATIONS_PLACE
    assert rooms.ADD_MCP_SERVER_PATH.startswith(f"Workbench → {rooms.INTEGRATIONS_ROOM} →")


def _sentences() -> dict:
    import src.agent_tools  # noqa: F401 — `tool_schemas` imports it first (`B1118`)
    from src import mail_auth, mcp_scaffold, workflow_effects, workstation_mcp
    from src.tools.system import do_app_api

    pin = "0" * 64
    relayed = workstation_mcp.ws_registration("ann", "weather", pin)
    local = mcp_scaffold.registration_for("weather", data_dir="/tmp/nowhere")
    refused = asyncio.run(do_app_api(json.dumps({
        "action": "call", "method": "POST", "path": "/api/mcp/servers", "body": {}}), owner="ann"))
    return {
        "the scaffold's check hint": mcp_scaffold.CHECK_HINT_WORKSTATION,
        "the relay's registration": relayed["where"],
        "the CLI's registration": local["where"],
        "the workstation README": mcp_scaffold.render_workstation_readme(
            "weather", ["get_forecast"], "", relayed, "refused"),
        "the CLI README": mcp_scaffold.render_readme("weather", ["get_forecast"], "", local, "refused"),
        "the palette's no-Integrations line": workflow_effects.NO_INTEGRATIONS_SENTENCE,
        "the palette's no-MCP line": workflow_effects.NO_MCP_TOOLS_SENTENCE,
        "the Google mail hint": mail_auth.RECONNECT_HINT,
        "the assistant's refusal": refused["error"],
    }


@pytest.mark.parametrize("which", [
    "the scaffold's check hint", "the relay's registration", "the CLI's registration",
    "the workstation README", "the CLI README", "the palette's no-Integrations line",
    "the palette's no-MCP line", "the Google mail hint", "the assistant's refusal",
])
def test_every_sentence_that_sends_a_person_to_the_room_names_it(which):
    said = _sentences()[which]
    assert rooms.INTEGRATIONS_ROOM in said, said
    assert not any(stale in said for stale in STALE), said


def test_an_imports_missing_line_names_the_room_its_door_opens(tmp_path, monkeypatch):
    """The server's missing line and the browser's door (`NEED_DOORS`, "Open
    MCP & Integrations") name one place — `B1135`."""
    from tests.helpers.assist_harness import PERSON, build_world, miniflux
    from tests.helpers.walker_harness import client_for

    graph = {"v": 1, "nodes": [{"id": "fetch", "kind": "http", "label": "Fetch unread",
                                "config": {"integration": "intg-miniflux", "method": "GET",
                                           "path": "/v1/entries"}}], "edges": []}

    async def go():
        one = build_world(monkeypatch, tmp_path, integrations=[miniflux()], name="one.db")
        async with client_for(one.app) as client:
            made = (await client.post("/api/workflows", headers=PERSON, json={"name": "Feeds"})).json()
            wid = made["workflow"]["id"]
            await client.put(f"/api/workflows/{wid}", headers=PERSON,
                             json={"graph": graph, "base_version": 1})
            file = (await client.get(f"/api/workflows/{wid}/export", headers=PERSON)).json()
        two = build_world(monkeypatch, tmp_path, integrations=[], name="two.db")
        async with client_for(two.app) as client:
            return (await client.post("/api/workflows", headers=PERSON, json={"file": file})).json()

    reply = asyncio.run(go())
    [line] = reply["missing"]
    assert line == ("“Fetch unread” uses an Integration called “Miniflux” (miniflux). Add it in "
                    f"{rooms.INTEGRATIONS_ROOM}, then pick it on the step.")


class _ById(HTMLParser):
    def __init__(self, wanted):
        super().__init__()
        self.wanted, self.depth, self.text = wanted, 0, []

    def handle_starttag(self, tag, attrs):
        if self.depth:
            self.depth += 1
        elif dict(attrs).get("id") == self.wanted:
            self.depth = 1

    def handle_endtag(self, tag):
        if self.depth:
            self.depth -= 1

    def handle_data(self, data):
        if self.depth:
            self.text.append(data)


def test_the_settings_door_card_names_the_room():
    parser = _ById("settings-open-integrations-room")
    parser.feed((ROOT / "static" / "index.html").read_text(encoding="utf-8"))
    assert "".join(parser.text).strip() == f"Open {_browser_names()['integrations']}"
