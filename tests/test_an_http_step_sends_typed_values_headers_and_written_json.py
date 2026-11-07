# SPDX-License-Identifier: AGPL-3.0-or-later
"""`B1885` (`http-body-strings-no-headers`) — an HTTP step sends its values as
their types, JSON its author writes whole, and hands on the answer's status and
headers when asked.

**Measured before the fix** (`data-expressions-audit`, re-run on `5e4c8ec`):
`render_call` of body fields `brightness='128'`, `enabled='true'`,
`text='{{ steps.fetch.data.n }}'` sent `{"brightness": "128", "enabled": "true",
"text": "5"}` — every value text, which Home Assistant, ntfy's priority and
JSON:API refuse. There was no body but fields, the step's `data` was only the
parsed body (no status, no headers), and a reply typed
`application/vnd.api+json` was read as plain text, so it had no fields.

Now a body field says what it is sent as (`type`: text — the default and what
a field with no type is — a number, yes/no, JSON), checked at save and coerced
at run; `body_mode` `raw` sends `raw_body`, JSON written whole, whose texts are
slots decided by the name they sit under exactly as a field's are; `response`
`full` hands on `{http_status, headers, body}`. Every name and every typed
value stays the author's — outside data never adds a name, an item or a header.

Driven (`Law 20`): the real rule (`validate_document`), the real renderer
(`render_call`), the real executor (`run_http_step` → `execute_tool_block` →
`execute_api_call`) against a real loopback server, the real picker
(`available_fields`).
"""
import asyncio
import json
import threading
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from types import SimpleNamespace

import pytest

from src import integrations
from src import workflow_document as wd
from src import workflow_effects as fx
from src import workflow_refs as wr
from src import workflow_slots as ws
from src.tool_capabilities import ToolRunSecurityContext
from tests.helpers.signed_in import signed_in
from tests.test_a_destination_is_never_mapped import RES, after_fetch, step
from tests.test_an_http_step_goes_through_an_integration import HOST, _resolve, _use_integration

CTX = wr.build_context({"fetch": {"text": "hello", "data": {
    "n": 5, "word": "five", "obj": {"to": "x@evil"}, "flag": "yes", "quote": '", "x": "'}}})


def _http(**config):
    base = {"integration": "miniflux", "method": "POST", "path": "/api/services/light"}
    base.update(config)
    return step("h", "http", **base)


def _sent(node, ctx=CTX):
    return json.loads(ws.render_call(node, ctx).content)


# ── typed body fields ────────────────────────────────────────────────────────

def test_a_body_field_is_sent_as_its_type():
    body = _sent(_http(body=[
        {"name": "brightness", "value": "128", "type": "number"},
        {"name": "enabled", "value": "true", "type": "yes/no"},
        {"name": "hs_color", "value": "[300, 70]", "type": "json"},
        {"name": "entity_id", "value": "light.kitchen"},
        {"name": "transition", "value": "2", "type": "text"},
    ]))["body"]
    assert body == {"brightness": 128, "enabled": True, "hs_color": [300, 70],
                    "entity_id": "light.kitchen", "transition": "2"}


def test_a_field_filled_from_another_step_is_coerced_to_its_type_or_not_sent():
    node = _http(body=[{"name": "details", "value": "{{ steps.fetch.data.n }}", "type": "number"},
                       {"name": "text", "value": "{{ steps.fetch.data.n }}"}])
    assert after_fetch(node) is None
    assert _sent(node)["body"] == {"details": 5, "text": "5"}, "text stays text, as before"
    with pytest.raises(ws.SlotError) as err:
        ws.render_call(_http(body=[{"name": "details", "value": "{{ steps.fetch.data.word }}",
                                    "type": "number"}]), CTX)
    assert "needs a number" in err.value.sentence


def test_a_json_field_is_never_filled_whatever_its_name():
    """An object from outside data would be structure the author did not write."""
    node = _http(body=[{"name": "text", "value": "{{ steps.fetch.data.obj }}", "type": "json"}])
    assert ws.slot_for(node, ("body", 0, "value")).mapping == ws.MAPPING_NEVER
    refusal = after_fetch(node)
    assert refusal is not None and refusal.reason == wd.REFUSE_MAPPED_NEVER
    assert refusal.field == "body[0].value"
    with pytest.raises(ws.SlotError):
        ws.render_call(node, CTX)


@pytest.mark.parametrize("entry, words", [
    ({"name": "brightness", "value": "bright", "type": "number"}, "is sent as a number"),
    ({"name": "enabled", "value": "maybe", "type": "yes/no"}, "is sent as yes or no"),
    ({"name": "hs", "value": "[300,", "type": "json"}, "is sent as JSON"),
    ({"name": "x", "value": "1", "type": "float"}, "is sent as"),
])
def test_a_typed_field_that_does_not_read_as_its_type_is_refused_at_save(entry, words):
    refusal = after_fetch(_http(body=[entry]))
    assert refusal is not None and words in refusal.sentence, refusal
    if entry["type"] != "float":
        assert refusal.field == "body[0].value"


def test_the_plan_says_what_each_field_is_sent_as():
    lines = wd.plan_lines(_http(body=[{"name": "brightness", "value": "128", "type": "number"},
                                      {"name": "text", "value": "{{ steps.fetch.text }}"}],
                                response="full"), RES)
    assert "Body brightness (a number): 128" in lines
    assert "Body text: {{ steps.fetch.text }}" in lines
    assert any("status, headers and body" in line for line in lines)


# ── JSON written whole ───────────────────────────────────────────────────────

WRITTEN = {"title": "Daily brief", "text": "{{ steps.fetch.text }}", "priority": 4,
           "message": {"text": "{{ steps.fetch.data.n }}", "markdown": "said {{ steps.fetch.data.word }}"},
           "notes": ["{{ steps.fetch.data.obj }}", "plain"], "tags": ["x", 1, True, None]}


def test_written_json_is_sent_as_written_with_its_word_values_filled():
    node = _http(body_mode="raw", raw_body=WRITTEN)
    assert after_fetch(node) is None
    call = ws.render_call(node, CTX)
    assert json.loads(call.content)["body"] == {
        "title": "Daily brief", "text": "hello", "priority": 4,
        "message": {"text": 5, "markdown": "said five"},
        "notes": ['{"to": "x@evil"}', "plain"], "tags": ["x", 1, True, None]}
    assert set(call.value_paths) == {"raw_body.text", "raw_body.message.text",
                                     "raw_body.message.markdown", "raw_body.notes[0]"}


def test_a_quote_from_outside_stays_inside_its_value():
    body = _sent(_http(body_mode="raw", raw_body={"text": "{{ steps.fetch.data.quote }}"}))["body"]
    assert body == {"text": '", "x": "'}


@pytest.mark.parametrize("written, field", [
    ({"url": "{{ steps.fetch.text }}"}, "raw_body.url"),
    ({"message": {"to": "{{ steps.fetch.text }}"}}, "raw_body.message.to"),
    (["{{ steps.fetch.text }}"], "raw_body[0]"),
    ({"entity_id": "light.{{ steps.fetch.text }}"}, "raw_body.entity_id"),
])
def test_a_reference_under_a_name_that_is_not_words_is_refused_at_save_and_at_run(written, field):
    node = _http(body_mode="raw", raw_body=written)
    refusal = after_fetch(node)
    assert refusal is not None and refusal.reason == wd.REFUSE_MAPPED_NEVER, refusal
    assert refusal.field == field
    with pytest.raises(ws.SlotError) as err:
        ws.render_call(node, CTX)
    assert "nothing was sent" in err.value.sentence


@pytest.mark.parametrize("config, words", [
    ({"body_mode": "raw"}, "none is written"),
    ({"body_mode": "raw", "raw_body": {"text": "x"}, "body": [{"name": "text", "value": "y"}]},
     "not both"),
    ({"raw_body": {"text": "x"}}, "only when the body is set to it"),
    ({"body_mode": "raw", "raw_body": "{}"}, "JSON object or list"),
    ({"body_mode": "raw", "raw_body": {"{{ steps.fetch.text }}": "x"}}, "a name is typed"),
    ({"response": "everything"}, "status, headers and body"),
])
def test_the_body_is_its_fields_or_written_json_and_the_rule_says_which(config, words):
    refusal = after_fetch(_http(**config))
    assert refusal is not None and words in refusal.sentence, refusal


# ── what it hands on ─────────────────────────────────────────────────────────

class _Answering:
    """A loopback service that answers with headers of its own and a cookie."""

    def __init__(self):
        self.content_type = "application/json"
        self.payload = {"total": 1}
        self.status = 200
        me = self

        class Handler(BaseHTTPRequestHandler):
            def _answer(self):
                length = int(self.headers.get("Content-Length") or 0)
                self.rfile.read(length) if length else b""
                data = (json.dumps(me.payload) if not isinstance(me.payload, bytes)
                        else me.payload)
                data = data.encode() if isinstance(data, str) else data
                self.send_response(me.status)
                self.send_header("Content-Type", me.content_type)
                self.send_header("X-Total-Count", "41")
                self.send_header("Link", '<https://x/?page=2>; rel="next"')
                self.send_header("Link", '<https://x/?page=9>; rel="last"')
                self.send_header("Set-Cookie", "session=SESSION-SECRET-9; HttpOnly")
                self.send_header("Content-Length", str(len(data)))
                self.end_headers()
                self.wfile.write(data)

            do_GET = do_POST = _answer

            def log_message(self, *a):
                pass

        self.httpd = ThreadingHTTPServer(("127.0.0.1", 0), Handler)
        self.port = self.httpd.server_address[1]
        threading.Thread(target=self.httpd.serve_forever, daemon=True).start()


@pytest.fixture
def service(monkeypatch, tmp_path):
    srv = _Answering()
    monkeypatch.setattr("src.url_safety._default_resolver", _resolve)
    monkeypatch.delenv("INTEGRATION_API_BLOCK_PRIVATE_IPS", raising=False)
    signed_in(monkeypatch, tmp_path / "auth", admin="local", members=())
    _use_integration(monkeypatch, f"http://{HOST}:{srv.port}")
    yield srv
    srv.httpd.shutdown()
    srv.httpd.server_close()


def _run_step(response=None, **config):
    node = step("h", "http", integration="Miniflux", method="GET", path="/v1/entries", **config)
    call = ws.render_call(node, CTX)
    more = {"response": response} if response else {}
    return asyncio.run(fx.run_http_step(call, owner="local", security_context=ToolRunSecurityContext(),
                                        **more))


def test_a_step_hands_on_its_status_headers_and_body_when_asked(service):
    plain = _run_step()
    assert plain.status == "success" and plain.data == {"total": 1}, "as before"
    full = _run_step(response="full")
    assert full.status == "success"
    assert full.data["http_status"] == 200 and full.data["body"] == {"total": 1}
    headers = full.data["headers"]
    assert headers["x-total-count"] == "41" and headers["content-type"] == "application/json"
    assert headers["link"] == '<https://x/?page=2>; rel="next", <https://x/?page=9>; rel="last"'
    assert "set-cookie" not in headers and "SESSION-SECRET-9" not in json.dumps(full.data), \
        "a cookie the service sets is not handed on"
    service.content_type, service.payload = "text/plain", b"pong"
    text = _run_step(response="full")
    assert text.data == {"http_status": 200, "headers": text.data["headers"], "body": "pong"}


def test_a_json_api_reply_is_read_as_json(service):
    service.content_type = "application/vnd.api+json"
    service.payload = {"data": [{"type": "issues", "id": "7"}]}
    out = _run_step()
    assert out.data == {"data": [{"type": "issues", "id": "7"}]}


def test_the_headers_reach_no_model():
    from src.tool_execution import format_tool_result
    text = format_tool_result("api_call: Miniflux", {
        "output": "HTTP 200\n{}", "exit_code": 0, "http_status": 200, "body_json": {},
        "response_headers": {"x-marker": "only-for-the-step"}})
    assert "only-for-the-step" not in text


def test_the_picker_offers_the_three_before_any_run(tmp_path):
    graph = {"v": 1, "nodes": [step("h", "http", integration="i", method="GET", path="/x",
                                    response="full"),
                               step("s", "set", fields=[{"name": "n", "value": "x"}])],
             "edges": [{"from": "h", "port": "success", "to": "s"}]}
    trigger = SimpleNamespace(id="t", trigger_type="schedule", trigger_event=None)
    sources = fx.available_fields(None, SimpleNamespace(id="wf"), trigger, graph, "s",
                                  recorded={})["sources"]
    declared = [s for s in sources if s["node_id"] == "h" and s["origin"] == "declared"]
    assert declared and [f["ref"] for f in declared[0]["fields"]] == [
        "{{ steps.h.data.http_status }}", "{{ steps.h.data.headers }}", "{{ steps.h.data.body }}"]


@pytest.mark.asyncio
async def test_a_run_hands_the_next_step_the_status_and_a_header(monkeypatch, tmp_path):
    """Through the real walker: the step's `response` reaches the executor
    (`_dispatch_authored`), and the step after reads the status and a header
    by reference. The dispatcher is the one seam — it answers as
    `execute_api_call` does for a structured call."""
    from src.event_bus import TRIGGER_SOURCE_WEBHOOK, WEBHOOK_PAYLOAD_FIELDS, build_trigger
    from tests.helpers.walker_harness import (
        arrow, make_db, node, records_of, recording_scheduler, runs_of, seed_workflow)

    factory = make_db(monkeypatch, tmp_path / "full.db")
    signed_in(monkeypatch, tmp_path / "auth", admin="root", members=())
    monkeypatch.setattr(integrations, "load_integrations", lambda: [
        {"id": "int1", "name": "Miniflux", "enabled": True, "base_url": "http://miniflux.lan",
         "api_key": "k", "preset": "miniflux", "description": ""}])
    sent = []

    async def answer(tool, content, **_kw):
        sent.append(json.loads(content))
        return "api_call", {"output": "HTTP 201\n{\"id\": 7}", "exit_code": 0, "http_status": 201,
                            "response_headers": {"x-total-count": "41"}, "body_json": {"id": 7}}

    monkeypatch.setattr(fx, "_dispatch", answer)
    nodes = [node("h", "Create it", "http", integration="int1", method="POST", path="/v1/entries",
                  body=[{"name": "priority", "value": "4", "type": "number"}], body_mode="json",
                  response="full"),
             node("s", "Read it", "set", fields=[
                 {"name": "status", "value": "{{ steps.h.data.http_status }}"},
                 {"name": "total", "value": '{{ steps.h.data.headers["x-total-count"] }}'},
                 {"name": "id", "value": "{{ steps.h.data.body.id }}"}])]
    seed_workflow(factory, nodes, [arrow("start", "h"), arrow("h", "s")], trigger_type="webhook",
                  owner="root")
    s = recording_scheduler()
    await s._execute_task("wf", trigger=build_trigger(
        TRIGGER_SOURCE_WEBHOOK, "webhook", {"json": {}}, fields=WEBHOOK_PAYLOAD_FIELDS))
    [run] = runs_of(factory, "wf")
    assert run["status"] == "success", run
    by = {r["node_id"]: r for r in records_of(factory, run["id"])}
    assert sent == [{"integration": "int1", "method": "POST", "path": "/v1/entries",
                     "body": {"priority": 4}, "structured": True}]
    assert by["h"]["output"]["data"] == {"http_status": 201, "headers": {"x-total-count": "41"},
                                         "body": {"id": 7}}
    assert by["s"]["output"]["data"] == {"status": 201, "total": "41", "id": 7}
