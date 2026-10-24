# SPDX-License-Identifier: AGPL-3.0-or-later
"""`P25-05` / `P25-06` — the agent browser: the person's own Firefox in their
workstation, driven by the agent over WebDriver BiDi, watched and taken over
in the app.

Driven, not read (`Law 20`): the real daemon (`tests/helpers/workstation_daemon`,
a `SingleUserSystem` under a temporary folder) starting a real Firefox,
headless, against a page served on this machine; the real client, the real
`agent_browser` tool through the real dispatcher, and the real window routes.
Without Firefox on the machine the browser half is skipped, said, and the
rest still runs.

**Measured before this file, on `386f80f`:** the agent's only browser was the
built-in Playwright server inside Pantheon's own container — one for everyone,
headless, nothing a person could watch or take over — or the `computer` tool's
clicks on a desktop screenshot.
"""

from __future__ import annotations

import asyncio
import base64
import json
import shutil
import socket
import threading
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

import pytest

from src.agent_tools import browser_tools as B
from workstation import protocol as P

FIREFOX = shutil.which("firefox")
needs_firefox = pytest.mark.skipif(FIREFOX is None, reason="Firefox is not installed here")

PAGE = b"""<html><head><title>Shop</title></head><body><h1>Hello shop</h1>
<a href='/two'>Second page</a>
<form action='/search'><input name=q placeholder='Search'><button>Go</button></form>
<input type=hidden name=secret value=x>
<button style='display:none'>Invisible</button></body></html>"""


class _Site(BaseHTTPRequestHandler):
    hits: list = []

    def log_message(self, *a):
        pass

    def do_GET(self):
        self.hits.append(self.path)
        body = PAGE if self.path == "/" else (f"<title>{self.path}</title><p>You are at {self.path}</p>").encode()
        self.send_response(200)
        self.send_header("Content-Type", "text/html; charset=utf-8")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)


@pytest.fixture(scope="module")
def site():
    srv = ThreadingHTTPServer(("127.0.0.1", 0), _Site)
    threading.Thread(target=srv.serve_forever, daemon=True).start()
    yield f"http://127.0.0.1:{srv.server_address[1]}"
    srv.shutdown()


def run(coro):
    return asyncio.run(coro)


# ── the pure parts ──────────────────────────────────────────────────────────

@pytest.mark.parametrize("raw,ok", [
    ("https://example.org/a?b=1", "https://example.org/a?b=1"),
    ("example.org", "https://example.org"),
    ("about:blank", "about:blank"),
])
def test_an_address_is_a_web_address(raw, ok):
    from workstation.browser import check_url
    assert check_url(raw) == ok


@pytest.mark.parametrize("raw", ["file:///etc/passwd", "javascript:alert(1)", "chrome://settings",
                                 "about:config", "data:text/html,<b>x</b>", ""])
def test_anything_else_is_refused_in_a_sentence(raw):
    from workstation.browser import BrowserError, check_url
    with pytest.raises(BrowserError) as e:
        check_url(raw)
    assert e.value.code == "bad_request" and e.value.message.endswith(".")


@pytest.mark.parametrize("action,effects", [
    ("read", {"read_public"}), ("screenshot", {"read_public"}), ("tabs", {"read_public"}),
    ("open", {"network_egress"}), ("navigate", {"network_egress"}), ("back", {"network_egress"}),
    ("click", {"network_egress", "external_side_effect"}),
    ("type", {"network_egress", "external_side_effect"}),
    ("press", {"network_egress", "external_side_effect"}),
    ("whatever", {"read_public", "network_egress", "external_side_effect"}),
])
def test_each_action_is_what_it_can_do(action, effects):
    from src.tool_capabilities import capabilities_for_action
    caps = capabilities_for_action("agent_browser", json.dumps({"action": action}))
    assert {e.value for e in caps.effects} == effects
    assert caps.result_integrity.value == "external_untrusted", "a page is a stranger's words"


def test_the_tool_is_registered_and_offered_only_with_a_workstation():
    from src.agent_tools import TOOL_HANDLERS, TOOL_TAGS
    from src.tool_security import plan_mode_disabled_tools
    assert "agent_browser" in TOOL_TAGS and "agent_browser" in TOOL_HANDLERS
    assert "agent_browser" in plan_mode_disabled_tools()
    assert B.parse_args('{"action": "goto", "url": "x"}')[0]["action"] == "open"
    assert "is not an `agent_browser` action" in B.parse_args('{"action": "hack"}')[1]


def test_a_page_reads_as_text_then_numbered_elements():
    out = B.page_text({"title": "Shop", "url": "https://x.org/", "text": "Hello", "cut": True,
                       "elements": [{"ref": 1, "tag": "a", "label": "Next", "href": "https://x.org/2"},
                                    {"ref": 2, "tag": "input", "type": "email", "label": "Mail"},
                                    {"ref": 3, "tag": "button", "label": "Send", "disabled": True}]})
    assert out.splitlines()[0] == "Page: Shop — https://x.org/"
    assert "[1] a “Next” → https://x.org/2" in out and "[2] input email “Mail”" in out
    assert "[3] button “Send” (disabled)" in out and "scroll and read again" in out


# ── the daemon, with a real Firefox ─────────────────────────────────────────

@pytest.fixture(scope="module")
def station(tmp_path_factory):
    if FIREFOX is None:
        pytest.skip("Firefox is not installed here")
    from workstation.agentd import SingleUserSystem, Workstation
    ws = Workstation(SingleUserSystem(tmp_path_factory.mktemp("browser-home")), "tok")
    yield ws
    ws.browsers.stop_all()


ACCOUNT = "pw-ann-0123abcd"


@needs_firefox
def test_the_agent_opens_reads_types_and_clicks_like_a_hand(station, site):
    from workstation.agentd import WorkstationError
    got = station.browser(ACCOUNT, {"action": "open", "url": site + "/"})
    assert got["title"] == "Shop" and got["url"] == site + "/"
    page = station.browser(ACCOUNT, {"action": "read"})
    assert "Hello shop" in page["text"]
    assert [(e["ref"], e["tag"], e["label"]) for e in page["elements"]] == [
        (1, "a", "Second page"), (2, "input", "Search"), (3, "button", "Go")], \
        "visible elements only, numbered in document order"
    typed = station.browser(ACCOUNT, {"action": "type", "ref": 2, "text": "wool socks", "submit": True})
    assert typed["url"] == site + "/search?q=wool+socks", "typed into the box and submitted with Enter"
    assert station.browser(ACCOUNT, {"action": "back"})["url"] == site + "/"
    station.browser(ACCOUNT, {"action": "open", "url": site + "/two"})
    station.browser(ACCOUNT, {"action": "open", "url": site + "/"})   # a page loaded afresh
    with pytest.raises(WorkstationError) as gone:
        station.browser(ACCOUNT, {"action": "click", "ref": 1})
    assert "read the page again" in gone.value.message, "numbers belong to one reading"
    station.browser(ACCOUNT, {"action": "read"})
    assert station.browser(ACCOUNT, {"action": "click", "ref": 1})["title"] == "/two"


@needs_firefox
def test_tabs_frames_and_the_one_holder(station, site):
    from workstation.agentd import WorkstationError
    station.browser(ACCOUNT, {"action": "open", "url": site + "/"})
    tabs = station.browser(ACCOUNT, {"action": "tab_new", "url": site + "/three"})["tabs"]
    assert [t["url"] for t in tabs][-1] == site + "/three" and tabs[-1]["current"]
    back = station.browser(ACCOUNT, {"action": "tab_switch", "tab": 1})
    assert back["url"] == site + "/"
    station.browser(ACCOUNT, {"action": "tab_close", "tab": 2})
    frame = station.browser(ACCOUNT, {"action": "frame"})
    assert base64.b64decode(frame["data_b64"])[:8] == b"\x89PNG\r\n\x1a\n"
    assert (frame["width"], frame["height"]) == (P.BROWSER_WIDTH, P.BROWSER_HEIGHT)
    assert station.browser(ACCOUNT, {"action": "frame", "if_none_match": frame["digest"]}) is None

    station.control(ACCOUNT, {"holder": "person"})
    try:
        with pytest.raises(WorkstationError) as busy:
            station.browser(ACCOUNT, {"action": "read"})
        assert busy.value.code == "busy"
        assert station.browser(ACCOUNT, {"action": "reload", "holder": "person"})["ok"] is True
        assert station.browser(ACCOUNT, {"action": "frame"})["digest"], "watching is never refused"
    finally:
        station.control(ACCOUNT, {"holder": "agent"})
    with pytest.raises(WorkstationError) as bad:
        station.browser(ACCOUNT, {"action": "open", "url": "file:///etc/passwd"})
    assert bad.value.code == "bad_request"


@needs_firefox
def test_nobody_else_can_attach_to_the_persons_browser(station, site):
    """Firefox's remote agent listens on loopback, which every account on the
    machine reaches. BiDi allows one session, and the daemon holds it."""
    from workstation.bidi import BidiError, Session
    station.browser(ACCOUNT, {"action": "open", "url": site + "/"})
    b = station.browsers.get(ACCOUNT)
    port = b.session._ws.sock.getpeername()[1]
    other = Session("127.0.0.1", port)
    try:
        with pytest.raises(BidiError, match="Maximum number of active sessions"):
            other.start()
    finally:
        other.close()
    assert station.browser(ACCOUNT, {"action": "read"})["title"] == "Shop", "and ours still works"


# ── the tool, through the dispatcher ────────────────────────────────────────

@pytest.fixture
def daemon_up(tmp_path, monkeypatch):
    if FIREFOX is None:
        pytest.skip("Firefox is not installed here")
    from tests.helpers.workstation_daemon import running_workstation
    from tests.test_the_agent_works_the_workstation_screen import configure
    with running_workstation(tmp_path) as ws:
        configure(monkeypatch, ws)
        yield ws


@needs_firefox
def test_the_tool_reads_a_page_and_shows_it(daemon_up, site):
    from src.agent_tools import ToolBlock
    from src.tool_execution import NO_TOOL_SECURITY_CONTEXT, execute_tool_block
    from tests.test_the_agent_works_the_workstation_screen import PERMITTED

    def call(args):
        return run(execute_tool_block(ToolBlock("agent_browser", json.dumps(args)), owner=PERMITTED,
                                      security_context=NO_TOOL_SECURITY_CONTEXT))

    try:
        desc, opened = call({"action": "open", "url": site + "/"})
        assert desc == f"agent_browser: open {site}/" and opened["exit_code"] == 0
        assert "Now at Shop" in opened["output"]
        _, read = call({"action": "read"})
        assert "[2] input text “Search”" in read["output"]
        _, shot = call({"action": "screenshot"})
        assert shot["images"][0]["mimeType"] == "image/png" and shot["ran_in"] == "workstation"
    finally:
        daemon_up.station.browsers.stop_all()


# ── the window's two routes ─────────────────────────────────────────────────

from test_the_workstation_is_admin_controlled import (  # noqa: E402,F401 — fixtures
    ADMIN, ALLOWED, ALSO, PLAIN, app, as_user, auth, datadir, switch_on, ws)


@needs_firefox
def test_the_window_sees_and_drives_the_callers_own_browser(app, ws, site):
    switch_on(app, ws)
    me = as_user(app, ALLOWED)
    opened = me.post("/api/workstation/browser", json={"action": "open", "url": site + "/two"})
    assert opened.status_code == 200, opened.text
    assert opened.json() == {"ok": True, "action": "open", "url": site + "/two", "title": "/two"}
    frame = me.get("/api/workstation/browser")
    assert frame.status_code == 200 and frame.headers["cache-control"] == "no-store"
    f = frame.json()
    assert set(f) == {"mime", "data_b64", "width", "height", "digest", "url", "title", "tabs"}
    assert f["url"] == site + "/two" and f["tabs"] == [{"tab": 1, "url": site + "/two", "current": True}]
    assert ws.token not in frame.text
    assert me.get(f"/api/workstation/browser?if_none_match={f['digest']}").status_code == 304
    theirs = as_user(app, ALSO).get("/api/workstation/browser").json()
    assert theirs["url"] != f["url"], "another person's browser is their own"
    bad = me.post("/api/workstation/browser", json={"action": "read"})
    assert bad.status_code == 400, "reading the page as text is the agent's, not the window's"
    assert me.post("/api/workstation/browser", json={"action": "open", "url": "file:///etc/passwd"}).status_code == 400
    assert as_user(app, PLAIN).get("/api/workstation/browser").status_code == 403
    ws.station.browsers.stop_all()
