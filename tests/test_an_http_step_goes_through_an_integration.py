# SPDX-License-Identifier: AGPL-3.0-or-later
"""`P22-13` — an HTTP step is one `api_call` through a registered Integration.

Two halves, both driven for real (`Law 20`):

* **`execute_api_call` is paced.** It sent through a bare `httpx` client — one
  of the 110 calls `check-outbound.py` counted — and a workflow fires it on a
  schedule with nobody watching (`FORBIDDEN.md` Part 2: `OutboundHostLimiter`
  on every third-party call). It now goes through `paced_http.request(...,
  client=<the pinned client>)`: the limiter is asked before and told after,
  and a host that said *stop* is not asked again — while the SSRF check and
  the pinned transport are untouched (the request below reaches a name that
  resolves, through the guard, to a loopback server, and the socket goes to
  the address the guard approved).
* **`workflow_effects.run_http_step`** dispatches the rendered call through
  the real `execute_tool_block`, so the disabled lists, the non-admin refusal
  and the trust rung apply — and nothing it is handed can move the request:
  § 5's injection cases send hostile values through it to a real server and
  read what the server received.

The local server is real (`ThreadingHTTPServer` on 127.0.0.1); the integration
store is the one seam (`load_integrations`), because the real one reads an
encrypted file in the data directory. The call each step is handed is the one
the real `workflow_slots.render_call` builds from an HTTP step's settings, its
body values arriving from outside BY REFERENCE (§ 5's path: the adversary's
words reach a `value` slot); only the deliberately malformed calls that test
the executor's own guards are made by hand, from the real `RenderedCall`
(`integrate-d`: on `wf-effects`' branch every call was a stand-in's).
"""
import asyncio
import json
import threading
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

import pytest

from src import integrations
from src import workflow_effects as fx
from src.tool_capabilities import ToolRunSecurityContext, TrustRung
from src.tool_execution import format_tool_result
from src.workflow_slots import RenderedCall, render_call
from tests.helpers.signed_in import signed_in

HOST = "miniflux.lan"          # a name, so the pin is exercised: it resolves to the loopback
KEY = "sekret-api-key-123"


class _Server:
    """A loopback HTTP server that records every request and answers JSON."""

    def __init__(self):
        self.requests = []
        self.status = 200
        self.payload = {"total": 2, "entries": [{"id": 1, "title": "One"}, {"id": 2, "title": "Two"}]}
        self.content_type = "application/json"
        server = self

        class Handler(BaseHTTPRequestHandler):
            def _answer(self):
                length = int(self.headers.get("Content-Length") or 0)
                body = self.rfile.read(length) if length else b""
                server.requests.append({
                    "method": self.command, "path": self.path,
                    "headers": {k.lower(): v for k, v in self.headers.items()},
                    "body": body.decode("utf-8"),
                })
                raw = (json.dumps(server.payload) if not isinstance(server.payload, bytes)
                       else server.payload)
                data = raw.encode("utf-8") if isinstance(raw, str) else raw
                self.send_response(server.status)
                self.send_header("Content-Type", server.content_type)
                self.send_header("Content-Length", str(len(data)))
                self.end_headers()
                self.wfile.write(data)

            do_GET = do_POST = do_PUT = do_DELETE = _answer

            def log_message(self, *a):
                pass

        self.httpd = ThreadingHTTPServer(("127.0.0.1", 0), Handler)
        self.port = self.httpd.server_address[1]
        self.thread = threading.Thread(target=self.httpd.serve_forever, daemon=True)
        self.thread.start()

    def close(self):
        self.httpd.shutdown()
        self.httpd.server_close()


@pytest.fixture
def server(monkeypatch, tmp_path):
    srv = _Server()
    # The name resolves to the loopback through the SSRF guard's own resolver,
    # so the guard approves it and the transport is pinned to what it approved.
    monkeypatch.setattr("src.url_safety._default_resolver", _resolve)
    monkeypatch.delenv("INTEGRATION_API_BLOCK_PRIVATE_IPS", raising=False)
    # The single-user owner: its one account, an admin, signed in as `local`
    # (`D-2026-10-07-02` §2 — it was `AUTH_ENABLED=false` and nobody).
    signed_in(monkeypatch, tmp_path / "auth", admin="local", members=())
    _use_integration(monkeypatch, f"http://{HOST}:{srv.port}")
    yield srv
    srv.close()


def _resolve(host):
    """`getaddrinfo`'s answer, for the two hosts these tests name: the
    fixture's name is the loopback; an address literal is itself."""
    import ipaddress
    if host == HOST:
        return ["127.0.0.1"]
    try:
        return [str(ipaddress.ip_address(host))]
    except ValueError:
        return []


def _use_integration(monkeypatch, base_url):
    intg = {"id": "intg-miniflux", "name": "Miniflux", "enabled": True,
            "base_url": base_url, "auth_type": "header", "api_key": KEY,
            "auth_header": "X-Auth-Token", "auth_param": "", "description": "My feeds",
            "preset": ""}
    monkeypatch.setattr(integrations, "load_integrations", lambda: [dict(intg)])


def _run(coro):
    return asyncio.run(coro)


def _call(path="/v1/entries", *, method="GET", params=None, body=None, missing=(),
          structured=True):
    """The call `render_call` builds for an HTTP step to Miniflux: the query
    values typed by the author (`never`: verbatim), each body value read from
    the start by reference (`{{ steps.start.data.<name> }}` — so a hostile
    value travels exactly the adversary's path), and `missing` references that
    reach nothing. A call that does not ask for its body (`structured`) cannot
    come out of `render_call`, which always asks: that one is made by hand,
    to test the executor's own refusal."""
    if structured is not True:
        payload = {"integration": "Miniflux", "method": method, "path": path}
        if params is not None:
            payload["params"] = params
        if body is not None:
            payload["body"] = body
        if structured is not None:
            payload["structured"] = structured
        return RenderedCall("http", "api_call", json.dumps(payload), (), tuple(missing))
    config = {"integration": "Miniflux", "method": method, "path": path}
    if params:
        config["query"] = [{"name": k, "value": v} for k, v in params.items()]
    data, entries = {}, []
    for name, value in (body or {}).items():
        entries.append({"name": name, "value": "{{ steps.start.data.%s }}" % name})
        data[name] = value
    for ref in missing:
        entries.append({"name": "text", "value": ref})
    if entries:
        config["body"] = entries
    node = {"id": "fetch", "kind": "http", "label": "Fetch", "config": config}
    return render_call(node, {"steps": {"start": {"data": data, "text": "", "status": "success"}}})


def _step(call, *, owner="local", ctx=None, exact_approval=None):
    return _run(fx.run_http_step(call, owner=owner,
                                 security_context=ctx or ToolRunSecurityContext(),
                                 exact_approval=exact_approval))


# ── execute_api_call is paced ─────────────────────────────────────────────────

def test_the_call_is_paced_before_and_its_answer_observed_after(server, monkeypatch):
    from src.rate_limiter import outbound
    seen = []
    real_acquire, real_observe = outbound.acquire_async, outbound.observe

    async def acquire(host, **kw):
        seen.append(("acquire", host, len(server.requests)))
        return await real_acquire(host, **kw)

    def observe(host, status, headers=None, **kw):
        seen.append(("observe", host, status, len(server.requests)))
        return real_observe(host, status, headers, **kw)

    monkeypatch.setattr(outbound, "acquire_async", acquire)
    monkeypatch.setattr(outbound, "observe", observe)

    result = _run(integrations.execute_api_call("Miniflux", "GET", "/v1/entries",
                                                params={"status": "unread"}))

    assert result["exit_code"] == 0, result
    assert seen == [("acquire", HOST, 0), ("observe", HOST, 200, 1)]
    # The pin still holds: the socket went to the approved loopback address and
    # the request still names the integration's host.
    req = server.requests[0]
    assert req["headers"]["host"] == f"{HOST}:{server.port}"
    assert req["path"] == "/v1/entries?status=unread"
    assert req["headers"]["x-auth-token"] == KEY


def test_a_host_that_said_stop_is_not_asked_again(server):
    from src.rate_limiter import outbound
    outbound.observe(HOST, 429, {"Retry-After": "7200"})

    result = _run(integrations.execute_api_call("Miniflux", "GET", "/v1/entries"))

    assert result["exit_code"] == 1
    assert result["error"].startswith("Miniflux: ")
    assert "rate-limited" in result["error"] and "minutes" in result["error"]
    assert server.requests == []


def test_a_structured_call_hands_back_the_parsed_body_and_its_status(server):
    plain = _run(integrations.execute_api_call("Miniflux", "GET", "/v1/entries"))
    shaped = _run(integrations.execute_api_call("Miniflux", "GET", "/v1/entries",
                                                structured=True))

    assert "body_json" not in plain and "http_status" not in plain      # Law 1
    assert shaped["body_json"] == server.payload
    assert shaped["http_status"] == 200
    assert shaped["output"] == plain["output"]

    server.status, server.payload = 404, {"error_message": "no such feed"}
    failed = _run(integrations.execute_api_call("Miniflux", "GET", "/v1/feeds/9",
                                                structured=True))
    assert failed["exit_code"] == 1 and failed["untrusted_content"] is True
    assert failed["http_status"] == 404
    assert failed["body_json"] == {"error_message": "no such feed"}


def test_a_body_over_the_cap_is_handed_back_as_text_only(server, monkeypatch):
    monkeypatch.setattr(integrations, "API_CALL_BODY_JSON_MAX_BYTES", 10)
    result = _run(integrations.execute_api_call("Miniflux", "GET", "/v1/entries",
                                                structured=True))
    assert result["exit_code"] == 0
    assert result["http_status"] == 200
    assert "body_json" not in result
    assert '"total": 2' in result["output"]


def test_a_text_reply_has_a_status_and_no_parsed_body(server):
    server.content_type, server.payload = "text/plain", b"pong"
    result = _run(integrations.execute_api_call("Miniflux", "GET", "/ping", structured=True))
    assert result["output"] == "HTTP 200\npong"
    assert result["http_status"] == 200 and "body_json" not in result


def test_the_tool_asks_for_structure_only_on_a_literal_true(server):
    from src.tools.system import do_api_call
    as_word = _run(do_api_call(json.dumps({"integration": "Miniflux", "path": "/v1/entries",
                                           "structured": "true"})))
    as_true = _run(do_api_call(json.dumps({"integration": "Miniflux", "path": "/v1/entries",
                                           "structured": True})))
    assert "body_json" not in as_word
    assert as_true["body_json"] == server.payload


def test_a_model_is_not_handed_the_body_twice():
    result = {"output": "HTTP 200\n{\"total\": 2}", "exit_code": 0,
              "body_json": {"total": 2, "secret_marker": "only-once"}, "http_status": 200}
    text = format_tool_result("api_call: Miniflux", result)
    assert "only-once" not in text
    assert "http_status" not in text and "**data:**" not in text


# ── run_http_step: the real dispatcher ────────────────────────────────────────

def test_an_http_step_runs_through_the_dispatcher_and_hands_on_the_body(server):
    out = _step(_call(params={"status": "unread"}))

    assert out.status == "success", out
    assert out.data == server.payload
    assert out.text.startswith("HTTP 200")
    assert [r["path"] for r in server.requests] == ["/v1/entries?status=unread"]
    assert server.requests[0]["headers"]["x-auth-token"] == KEY


def test_a_metadata_base_url_is_still_refused(server, monkeypatch):
    _use_integration(monkeypatch, "http://169.254.169.254")
    out = _step(_call())
    assert out.status == "error"
    assert "URL rejected" in out.text and "169.254.169.254" in out.text
    assert server.requests == []


def test_a_person_who_is_not_an_admin_is_refused(server, monkeypatch):
    monkeypatch.setattr("src.tool_execution.owner_is_admin_or_single_user", lambda owner: False)
    out = _step(_call(), owner="bob")
    assert out.status == "error"
    assert "restricted to admin users" in out.text
    assert server.requests == []


def test_a_tool_switched_off_for_everyone_is_refused(server, monkeypatch):
    import src.settings as settings
    real = settings.get_setting
    monkeypatch.setattr(settings, "get_setting",
                        lambda key, default=None: ["api_call"] if key == "disabled_tools"
                        else real(key, default))
    out = _step(_call())
    assert out.status == "error" and "disabled" in out.text
    assert server.requests == []


def test_an_unreadable_switched_off_list_runs_nothing(server, monkeypatch):
    import src.settings as settings

    def broken(key, default=None):
        raise OSError("settings.json is unreadable")

    monkeypatch.setattr(settings, "get_setting", broken)
    out = _step(_call())
    assert out.status == "error" and "switched off" in out.text
    assert server.requests == []


def test_a_call_that_does_not_ask_for_its_body_is_not_sent(server):
    out = _step(_call(structured=None))
    assert out.status == "error" and "structured" in out.text
    assert server.requests == []


def test_a_reference_that_found_nothing_is_not_sent(server):
    out = _step(_call(missing=("{{ steps.fetch.data.id }}",)))
    assert out.status == "error"
    assert "{{ steps.fetch.data.id }}" in out.text
    assert server.requests == []


def test_only_a_rendered_call_is_run(server):
    with pytest.raises(TypeError):
        _step({"kind": "http", "tool": "api_call", "content": "{}"})
    with pytest.raises(TypeError):
        # A kind `render_call` would never pair with this tool: made by hand.
        _step(RenderedCall("mcp", "api_call",
                           json.dumps({"integration": "Miniflux", "structured": True}), (), ()))
    assert server.requests == []


def test_a_strict_rung_asks_and_an_allow_runs_the_sealed_call_once(server):
    from src.tool_approvals import ToolApprovalStore
    from src.tool_capabilities import capabilities_for_action

    call = _call(method="POST", path="/v1/entries", body={"title": "Hello"})
    strict = ToolRunSecurityContext(rung=TrustRung.ASK_EVERY_TIME)
    asked = _step(call, ctx=strict)
    assert asked.status == "error" and asked.result.get("blocked") is True
    assert server.requests == []

    store = ToolApprovalStore()
    pending = store.create(owner="local", session_id="", origin_run_id="run-1:post:",
                           tool_name="api_call", content=call.content, workspace=None,
                           external_untrusted_context_seen=False,
                           capabilities=capabilities_for_action("api_call", call.content))
    approval = store.consume(pending.approval_id, decision="approve_task", owner="local",
                             session_id="", allow_continuation=False)
    assert approval is not None

    ran = _step(call, ctx=ToolRunSecurityContext(rung=TrustRung.ASK_EVERY_TIME),
                exact_approval=approval)
    assert ran.status == "success", ran
    again = _step(call, ctx=ToolRunSecurityContext(rung=TrustRung.ASK_EVERY_TIME),
                  exact_approval=approval)
    assert again.status == "error" and again.result.get("blocked") is True
    assert len(server.requests) == 1                     # single use


# ── § 5: nothing a value holds can move the request ───────────────────────────

def test_a_value_shaped_like_json_does_not_change_the_path(server):
    hostile = '", "path": "/admin", "x": "'
    out = _step(_call(method="POST", params={"q": hostile}, body={"text": hostile}))
    assert out.status == "success"
    req = server.requests[0]
    assert req["path"].split("?")[0] == "/v1/entries"
    assert json.loads(req["body"]) == {"text": hostile}


def test_an_object_mapped_into_text_arrives_as_text_with_no_new_key(server):
    smuggled = json.dumps({"to": "x@evil", "path": "/admin"})
    out = _step(_call(method="POST", body={"text": smuggled}))
    assert out.status == "success"
    sent = json.loads(server.requests[0]["body"])
    assert sent == {"text": smuggled} and "to" not in sent


def test_a_reference_inside_a_value_arrives_literally(server):
    nested = "see {{ steps.secret.data.x }} and {{steps.start.data.body}}"
    out = _step(_call(method="POST", body={"text": nested}))
    assert out.status == "success"
    assert json.loads(server.requests[0]["body"]) == {"text": nested}


def test_a_metadata_url_in_a_value_leaves_the_destination_alone(server):
    meta = "http://169.254.169.254/latest/meta-data/iam"
    out = _step(_call(method="POST", params={"next": meta}, body={"text": meta}))
    assert out.status == "success"
    req = server.requests[0]
    assert req["headers"]["host"] == f"{HOST}:{server.port}"
    assert req["path"].startswith("/v1/entries?")
    assert json.loads(req["body"]) == {"text": meta}
