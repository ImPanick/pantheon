# SPDX-License-Identifier: AGPL-3.0-or-later
"""`B1871` — a workflow file's Integration id, or MCP tool id, is never bound to
one of the importer's own just because the ids are equal.

`import_file` rebinds a missing resource by what the file SAYS it is (an
Integration by preset then name, an MCP tool by server and tool name). When
nothing matched, it put a stand-in at the file's own id for the import-time
check and left `config.integration` as that id. If the importer had a real
Integration with that id, the stand-in hid it for the check only: the stored
step was bound to the real one, with its real key and base URL, while the
import's reply and banner named the file's Integration and asked the person to
add it. **Measured on `5e4c8ec`** (the audit's own probe, reproduced here):
an Integration "Home" with id `victim01`; a file whose step calls `victim01`
and says it is "Weather Service" — the reply said "sends POST … to Weather
Service" and "Add it", the stored step called `victim01`, and the check plan
said "Would call Home". `MISSING_TASK_ID` already closed this exact door for a
Run task step; Integrations and MCP tools were left open.

The adversary (`Law 17`): whoever wrote the file (§ 5.3), who can aim an id
at an Integration the importer has — ids were client-chosen at
`POST /api/auth/integrations`, and the palette lists shared ones to every
member. Now each missing Integration and MCP tool is checked and stored under
an id no real one has, the step says which to pick, and an Integration's id is
always the server's own.

Real (`Law 20`): the workflow routes over an ASGI client on a real SQLite file,
the store, the rule, `import_file`, and the real `add_integration`.
"""

import json

import pytest

from src import workflow_share as ws
from tests.helpers.assist_harness import PERSON, POST, Chat, build_world, marks_of, stored
from tests.helpers.walker_harness import client_for

pytestmark = pytest.mark.asyncio

HOME = {"id": "victim01", "name": "Home", "enabled": True,
        "base_url": "http://192.168.1.50:8123", "auth_type": "bearer", "api_key": "home-key-0451",
        "auth_header": "", "auth_param": "", "description": "My house", "preset": ""}


def _file(nodes, *, integrations=(), mcp_tools=()):
    edges = [{"from": a["id"], "port": "success", "to": b["id"]} for a, b in zip(nodes, nodes[1:])]
    return {"pantheon_workflow": 1, "name": "Forecast", "trigger": {"trigger_type": "webhook"},
            "graph": {"v": 1, "nodes": nodes, "edges": edges},
            "requires": {"integrations": list(integrations), "mcp_tools": list(mcp_tools)}}


def _http(node_id, label, ref, path="/api/services/lock/unlock"):
    return {"id": node_id, "kind": "http", "label": label,
            "config": {"integration": ref, "method": "POST", "path": path}}


async def _import(w, data):
    async with client_for(w.app) as client:
        return await client.post("/api/workflows", headers=PERSON, json={"file": data})


async def test_a_files_integration_id_that_is_one_of_yours_is_not_bound_to_yours(monkeypatch, tmp_path):
    w = build_world(monkeypatch, tmp_path, name="aim.db", integrations=[HOME])
    data = _file([_http("get", "Get forecast", "victim01")],
                 integrations=[{"ref": "victim01", "name": "Weather Service", "preset": ""}])
    res = await _import(w, data)
    assert res.status_code == 200, res.text
    body = res.json()
    doc = body["workflow"]
    _wf, graph, _trigger = stored(w.factory, doc["id"])
    bound = graph["nodes"][0]["config"]["integration"]
    assert bound != "victim01", "the stored step must not call the importer's Home"
    assert bound == ws.MISSING_INTEGRATION_ID
    # What the person reads and what the step does agree: both are the file's
    # Integration, which this install does not have.
    assert body["destinations"] == [
        "“Get forecast” sends POST /api/services/lock/unlock to Weather Service."]
    assert body["missing"] == [
        "“Get forecast” uses an Integration called “Weather Service”. Add it in "
        "MCP & Integrations, then pick it on the step."]
    assert marks_of(graph)["get"]["needs"] == [
        {"field": "integration", "name": "Weather Service"}]
    said = json.dumps({k: doc.get(k) for k in ("plans", "plans_declined")})
    assert "Home" not in said and "192.168.1.50" not in said, said
    # Checked and switched on, it still does not run against Home: the engine
    # has no Integration under that id.
    async with client_for(w.app) as client:
        checked = await client.put(f"/api/workflows/{doc['id']}", headers=PERSON,
                                   json={"checked": ["get"]})
        assert checked.status_code == 200, checked.text
        on = await client.post(f"/api/workflows/{doc['id']}/switch", headers=PERSON,
                               json={"on": True})
    assert on.status_code == 400, on.text
    assert on.json()["reason"] == "unknown_integration" and on.json()["node_ids"] == ["get"]
    assert stored(w.factory, doc["id"])[2].status == "paused"


async def test_two_missing_integrations_keep_their_own_names(monkeypatch, tmp_path):
    w = build_world(monkeypatch, tmp_path, name="two.db", integrations=[HOME])
    data = _file([_http("a", "Ask weather", "victim01", "/forecast"),
                  _http("b", "Ask tides", "tides-9", "/tides"),
                  _http("c", "Ask weather again", "victim01", "/hourly")],
                 integrations=[{"ref": "victim01", "name": "Weather Service", "preset": ""},
                               {"ref": "tides-9", "name": "Tide Tables", "preset": ""}])
    res = await _import(w, data)
    assert res.status_code == 200, res.text
    body = res.json()
    graph = stored(w.factory, body["workflow"]["id"])[1]
    ids = [n["config"]["integration"] for n in graph["nodes"]]
    assert "victim01" not in ids and "tides-9" not in ids
    assert ids[0] == ids[2] != ids[1], "one stand-in per Integration the file names"
    assert body["destinations"] == [
        "“Ask weather” sends POST /forecast to Weather Service.",
        "“Ask tides” sends POST /tides to Tide Tables.",
        "“Ask weather again” sends POST /hourly to Weather Service."]
    # Every step that uses a missing Integration says so on itself — the third
    # step too, which before matched the first step's stand-in and said nothing.
    marks = marks_of(graph)
    assert [marks[n]["needs"] for n in ("a", "b", "c")] == [
        [{"field": "integration", "name": "Weather Service"}],
        [{"field": "integration", "name": "Tide Tables"}],
        [{"field": "integration", "name": "Weather Service"}]]


async def test_a_files_mcp_tool_id_that_is_one_of_yours_is_not_bound_to_yours(monkeypatch, tmp_path):
    """The importer's Chat server has `mcp__chat__send_message`; the file's step
    names that id and says it is `send_message` on a server called “Evil”."""
    w = build_world(monkeypatch, tmp_path, name="mcp.db", chat=Chat())
    data = _file([{"id": "post", "kind": "mcp", "label": "Post it",
                   "config": {"tool": POST, "args": {"channel": "#dev", "text": "hi"}}}],
                 mcp_tools=[{"ref": POST, "server": "Evil", "tool": "send_message",
                             "input_schema": {"type": "object", "properties": {
                                 "channel": {"type": "string"}, "text": {"type": "string"}}}}])
    res = await _import(w, data)
    assert res.status_code == 200, res.text
    body = res.json()
    graph = stored(w.factory, body["workflow"]["id"])[1]
    tool = graph["nodes"][0]["config"]["tool"]
    assert tool != POST, "the stored step must not call the importer's Chat"
    assert tool == ws.MISSING_MCP_TOOL_ID
    assert body["missing"] == [
        "“Post it” calls the tool “send_message” on an MCP server called “Evil”. Add that "
        "server in MCP & Integrations, then pick the tool on the step."]
    assert any("Evil: send_message" in line for line in body["destinations"]), body["destinations"]
    assert not any("Chat" in line for line in body["destinations"])


async def test_a_new_integrations_id_is_always_the_servers_own(monkeypatch):
    """The other half of the aim: a person (or anything with their session)
    could pick an Integration's id at `POST /api/auth/integrations`. The id
    is minted here, whatever the body says."""
    import src.integrations as integrations_mod
    saved = []
    monkeypatch.setattr(integrations_mod, "load_integrations", lambda: [dict(i) for i in saved])
    monkeypatch.setattr(integrations_mod, "save_integrations",
                        lambda items: saved.__setitem__(slice(None), [dict(i) for i in items]))
    made = integrations_mod.add_integration(
        {"id": "victim01", "name": "Weather Service", "base_url": "http://weather.lan"},
        owner="alice")
    assert made["id"] != "victim01"
    again = integrations_mod.add_integration(
        {"id": made["id"], "name": "Copy", "base_url": "http://copy.lan"}, owner="alice")
    assert again["id"] != made["id"], "never a second Integration under one id"
    assert [i["id"] for i in saved] == [made["id"], again["id"]]
