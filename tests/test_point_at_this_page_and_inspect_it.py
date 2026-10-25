# SPDX-License-Identifier: AGPL-3.0-or-later
"""`P25-10` … `P25-12` — the person browses, points at what they mean, and
watches the agent look at it.

The owner, 2026-10-25: *"Give the users control of the in-application's
browser too. So that way the user can navigate freely and tell the agent 'This
is the page I am talking about. Reference the design aspects (or whatever,
content etc..)' - The user should be able to watch the LLM inspect etc be it in
browser control or via the internal thoughts laid bare by the LLM."*

Driven, not read (`Law 20`): the real daemon starting a real Firefox against a
page served on this machine, the person pointing, and the real `agent_browser`
tool's `inspect` reading what they pointed at — on that page and after they
browsed on. Without Firefox the browser half is skipped, said, and the rest runs.

**Measured before this file, on `03790be`:** the agent could `read` a page's
words and numbered controls, and nothing of how it looked — no colour, font,
size or spacing. To say "this one" the person pasted an address, and a click on
the page did nothing until *Take over*.
"""

from __future__ import annotations

import shutil
import threading
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

import pytest

from src.agent_tools import browser_tools as B

FIREFOX = shutil.which("firefox")
needs_firefox = pytest.mark.skipif(FIREFOX is None, reason="Firefox is not installed here")

PAGES = {
    "/": b"""<html lang=en><head><title>Wool &amp; Co</title>
<meta name=description content="Warm socks, knitted in Yorkshire.">
<style>:root{--accent:#8a4b2a;--gap:16px} body{margin:0;font:16px Georgia,serif;color:#333333;background:#fdf6ec}
h1{font-size:32px;font-weight:700;color:#8a4b2a;margin:24px} main{display:flex;gap:var(--gap);padding:24px}
.card{background:#ffffff;border-radius:10px;padding:16px} @media (max-width: 600px){main{display:block}}</style></head>
<body><h1 id=brand>Wool &amp; Co</h1><main><div class=card><h2>Hiking socks</h2><p>Merino, cushioned.</p></div>
<div class=card><h2>Bed socks</h2><img src="data:image/gif;base64,R0lGODlhAQABAAAAACw=" width=40 height=40></div></main></body></html>""",
    "/other": b"<html><head><title>Other</title></head><body><p>Somewhere else.</p></body></html>",
}


class _Site(BaseHTTPRequestHandler):
    def log_message(self, *a):
        pass

    def do_GET(self):
        body = PAGES.get(self.path.split("?")[0], b"")
        self.send_response(200 if body else 404)
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


@pytest.fixture(scope="module")
def station(tmp_path_factory):
    if FIREFOX is None:
        pytest.skip("Firefox is not installed here")
    from workstation.agentd import SingleUserSystem, Workstation
    ws = Workstation(SingleUserSystem(tmp_path_factory.mktemp("point-home")), "tok")
    yield ws
    ws.browsers.stop_all()


ACCOUNT = "pw-ann-0123abcd"


def _call(station, action, who="person", **body):
    return station.browser(ACCOUNT, {"action": action, "holder": who, **body})


@needs_firefox
def test_the_person_points_and_the_agent_inspects_it(station, site):
    from workstation.agentd import WorkstationError
    _call(station, "open", url=site + "/")
    got = _call(station, "point", x=60, y=45)                  # on the h1
    p = got["pointed"]
    assert p["anchor"]["tag"] == "h1" and p["anchor"]["text"] == "Wool & Co" and p["anchor"]["selector"] == "#brand"
    assert p["facts"]["styles"]["color"] == "#8a4b2a" and p["facts"]["styles"]["font-size"] == "32px"

    with pytest.raises(WorkstationError) as e:
        _call(station, "point", who="agent", x=60, y=45)
    assert "person's" in e.value.message, "pointing is how the person says which one"

    seen = _call(station, "inspect", who="agent", pointed=True, why="To match the heading type.")
    el = seen["element"]
    assert el["tag"] == "h1" and el["styles"]["font-family"].startswith("Georgia")
    assert el["on_background"] == "#fdf6ec"
    text = B.inspect_text(seen)
    assert "The person pointed at <h1> “Wool & Co”" in text and "color: #8a4b2a" in text

    b = station.browsers.get(ACCOUNT)
    last = [a for a in b.activity if a["action"] == "inspect"][-1]
    assert last["who"] == "agent" and last["why"] == "To match the heading type."
    assert len(last["box"]) == 4 and last["label"].startswith("Inspecting <h1> “Wool & Co” — Georgia 32px #8a4b2a")
    assert [a for a in b.activity if a["action"] == "point"][-1]["who"] == "person"


@needs_firefox
def test_the_page_counted_and_the_pointed_page_kept_after_browsing_on(station, site):
    _call(station, "open", url=site + "/")
    page = _call(station, "inspect", who="agent")["page"]
    assert page["variables"]["--accent"] == "#8a4b2a" and page["variables"]["--gap"] == "16px"
    assert page["fonts"][0]["value"] == "Georgia"
    assert {r["value"] for r in page["backgrounds"]} >= {"#fdf6ec", "#ffffff"}
    assert any("max-width: 600px" in m for m in page["media"])
    assert [h["text"] for h in page["headings"]] == ["Wool & Co", "Hiking socks", "Bed socks"]
    assert page["images"] == 1 and page["images_without_alt"] == 1 and page["landmarks"] == ["main"]
    assert page["description"] == "Warm socks, knitted in Yorkshire."

    _call(station, "point", page=True)
    _call(station, "open", url=site + "/other")                 # the person browses on
    later = _call(station, "inspect", who="agent", pointed=True)
    assert later["elsewhere"] is True and later["page"]["fonts"][0]["value"] == "Georgia", \
        "what they pointed at then travels with it"
    text = B.inspect_text(later)
    assert "the whole page" in text and "moved on from that page" in text and "Fonts: Georgia" in text


@needs_firefox
def test_an_element_by_its_number_and_a_selector_that_is_not_there(station, site):
    from workstation.agentd import WorkstationError
    _call(station, "open", url=site + "/")
    seen = _call(station, "inspect", who="agent", selector="main > div:nth-of-type(2)")
    assert seen["element"]["styles"]["border-radius"] == "10px" and seen["element"]["children"] == 2
    with pytest.raises(WorkstationError) as e:
        _call(station, "inspect", who="agent", selector="#nope")
    assert "no longer on the page" in e.value.message


@needs_firefox
def test_the_agent_waits_while_the_person_browses(station, site):
    from workstation.agentd import WorkstationError
    station.control(ACCOUNT, {"holder": "person"})
    try:
        with pytest.raises(WorkstationError) as e:
            _call(station, "inspect", who="agent")
        assert e.value.code == "busy"
        assert _call(station, "point", x=60, y=45)["pointed"]["anchor"]["tag"] == "h1", \
            "the person points while they hold it"
    finally:
        station.control(ACCOUNT, {"holder": "agent"})


def test_the_tool_offers_inspect_and_keeps_pointing_the_persons():
    from src.tool_capabilities import _ACTION_CAPABILITIES
    from src.tool_schemas import FUNCTION_TOOL_SCHEMAS
    assert "inspect" in B.ACTIONS and "point" not in B.ACTIONS
    args, problem = B.parse_args({"action": "inspect", "pointed": "true", "why": "Matching it."})
    assert problem is None and args["pointed"] is True and B.describe(args) == "inspect what the person pointed at"
    assert B.parse_args({"action": "point"})[1], "the agent cannot point"
    assert _ACTION_CAPABILITIES["agent_browser"]["inspect"] == _ACTION_CAPABILITIES["agent_browser"]["read"], \
        "inspecting only looks"
    schema = next(s for s in FUNCTION_TOOL_SCHEMAS if s["function"]["name"] == "agent_browser")["function"]
    props = schema["parameters"]["properties"]
    assert "inspect" in props["action"]["enum"] and {"why", "pointed", "selector"} <= set(props)


def test_the_window_is_given_only_what_it_draws():
    from routes.workstation_routes import _activity, _pointed
    a = _activity({"id": 1, "seq": 2, "who": "agent", "action": "inspect", "label": "Inspecting",
                   "phase": "done", "why": "Because.", "box": [1, 2, 3, 4], "x": 2, "y": 4, "secret": "x"})
    assert a["why"] == "Because." and a["box"] == [1, 2, 3, 4] and "secret" not in a
    assert "box" not in _activity({"box": [1, 2, "3", 4]})
    p = _pointed({"url": "https://a.example/", "title": "A", "anchor": {"tag": "h1", "text": "Hi", "selector": "#x"},
                  "facts": {"box": [1, 2, 3, 4], "styles": {"color": "#000"}}})
    assert p == {"url": "https://a.example/", "title": "A", "page": False, "tag": "h1", "text": "Hi",
                 "box": [1, 2, 3, 4]}, "the facts stay with the daemon, for the agent"
    assert _pointed({"url": "u", "title": "t", "anchor": None})["page"] is True
