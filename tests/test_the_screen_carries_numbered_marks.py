# SPDX-License-Identifier: AGPL-3.0-or-later
"""Screen grounding — `D-2026-11-01-04`, Phase 1 of the frontier game plan.

The owner (2026-11-01): *"Those top 3 you selected should be first up"*, the
first being this: every screenshot the agent is shown carries a numbered box
on each thing it can click, the list in words beside it, and `computer`
takes `"mark": N` where it took a point.

What is driven here:

  * `G2` — the desktop's accessibility tree, read by the shipped reader
    (`workstation/a11y_marks.py`) from a stand-in of AT-SPI's own shape:
    controls kept, containers and covered controls left out, a row of cells
    one mark, reading order; and the daemon's `marks` route, through the real
    daemon, passing only boxes on the screen and the fields the protocol names;
  * `G3` — the picture-reading fallback: an icon on a quiet ground is found, a
    busy pattern is not, and no OCR program is simply no text;
  * `G4` — through the real dispatcher and the real daemon: a screenshot comes
    back with its marks drawn and listed, `mark` clicks the middle of that
    mark on that person's display, `type` with a mark clicks the field first,
    a number that is not on the last screenshot (or is another person's) is
    refused with nothing sent, a daemon without the route still gets marks
    from the picture, and switched off everything is as before;
  * `G1` — the agent browser's screenshot numbered by the page's own `read`,
    so a mark is the `ref` a click takes.

The real AT-SPI against a real XFCE is an opt-in check
(`PANTHEON_A11Y_E2E=1` with `DISPLAY` set to a running XFCE session).
"""
from __future__ import annotations

import asyncio
import base64
import io
import json
import os
import shutil
import subprocess
import sys
from types import SimpleNamespace

import pytest

import core.auth
import src.agent_tools  # noqa: F401 — enters the tool-module cycle the right way round
import src.tool_security as tool_security
import src.workstation_client as wc
from src import screen_marks
from src.agent_tools import ToolBlock
from src.tool_execution import NO_TOOL_SECURITY_CONTEXT, execute_tool_block
from src.workstation_client import WorkstationClient, WorkstationError, account_for
from tests.helpers.workstation_daemon import PictureScreen, running_workstation
from workstation import a11y_marks
from workstation import protocol as P

PERSON = "ann"
OTHER = "bob"


def run(coro):
    return asyncio.run(coro)


def _picture(draw=None) -> bytes:
    from PIL import Image, ImageDraw
    img = Image.new("RGB", (P.SCREEN_WIDTH, P.SCREEN_HEIGHT), (236, 236, 236))
    if draw:
        draw(ImageDraw.Draw(img))
    out = io.BytesIO()
    img.save(out, format="PNG")
    return out.getvalue()


# ── `G2`: the reader, against AT-SPI's shape ─────────────────────────────────

class _States:
    def __init__(self, *names):
        self.names = set(names)

    def contains(self, s):
        return s in self.names


class _Node:
    def __init__(self, role, name="", box=(0, 0, 0, 0), children=(), states=("SHOWING",)):
        self.role, self.name, self.box = role, name, box
        self.children = list(children)
        self.states = _States(*states)

    def get_state_set(self):
        return self.states

    def get_role_name(self):
        return self.role

    def get_child_count(self):
        return len(self.children)

    def get_child_at_index(self, i):
        return self.children[i]

    def get_name(self):
        return self.name

    def get_description(self):
        return ""

    def get_extents(self, _coord):
        x, y, w, h = self.box
        return SimpleNamespace(x=x, y=y, width=w, height=h)


def _atspi(apps):
    desktop = _Node("desktop frame", children=apps)
    return SimpleNamespace(
        get_desktop=lambda n: desktop, set_timeout=lambda a, b: None,
        CoordType=SimpleNamespace(SCREEN="screen"),
        StateType=SimpleNamespace(SHOWING="SHOWING", ACTIVE="ACTIVE", EDITABLE="EDITABLE"))


def _desktop():
    panel = _Node("application", "xfce4-panel", children=[
        _Node("frame", "", (0, 760, 1280, 40), children=[
            _Node("panel", "", (0, 760, 1280, 40), children=[
                _Node("push button", "Terminal Emulator", (40, 762, 40, 36)),
                _Node("filler", "", (80, 762, 4, 36)),
            ])])])
    files = _Node("application", "thunar", children=[
        _Node("frame", "home - Thunar", (100, 100, 600, 400), states=("SHOWING", "ACTIVE"), children=[
            _Node("menu bar", "", (100, 120, 600, 24), children=[
                _Node("menu", "File", (102, 120, 40, 24)),
                _Node("menu", "Edit", (142, 120, 40, 24)),
            ]),
            _Node("text", "", (300, 150, 380, 30), states=("SHOWING", "EDITABLE")),
            _Node("table row", "", (102, 200, 180, 24), children=[
                _Node("table cell", "", (102, 200, 12, 24)),
                _Node("table cell", "", (116, 200, 24, 24)),
                _Node("table cell", "Desktop", (142, 200, 140, 24)),
            ]),
            _Node("push button", "Hidden", (500, 300, 40, 20), states=()),
            _Node("push button", "Tiny", (500, 330, 2, 2)),
            _Node("push button", "Off screen", (1400, 330, 40, 20)),
        ])])
    behind = _Node("application", "mousepad", children=[
        _Node("frame", "Untitled - Mousepad", (0, 0, 900, 600), children=[
            _Node("menu", "Under Thunar", (300, 300, 40, 20)),
            _Node("menu", "Beside Thunar", (800, 550, 60, 20)),
        ])])
    return [panel, files, behind]


def test_the_tree_gives_each_control_once_in_reading_order_and_nothing_hidden():
    got = a11y_marks.read(_atspi(_desktop()))
    names = [(m["role"], m["name"]) for m in got["marks"]]
    assert names == [
        ("menu", "File"), ("menu", "Edit"), ("text", ""), ("table cell", "Desktop"),
        ("menu", "Beside Thunar"), ("push button", "Terminal Emulator")]
    row = next(m for m in got["marks"] if m["name"] == "Desktop")
    assert row["box"] == [102, 200, 180, 24], "the named cell spans its row"
    assert next(m for m in got["marks"] if m["role"] == "text")["editable"] is True
    by_app = {w["app"]: w for w in got["windows"]}
    assert by_app["thunar"]["active"] and by_app["thunar"]["marks"] == 4
    assert by_app["mousepad"]["marks"] == 1


def test_the_reader_says_why_when_it_cannot_read_a_tree():
    env = {k: v for k, v in os.environ.items() if k != "DISPLAY"}
    done = subprocess.run([sys.executable, "-I", "-"], input=open(a11y_marks.__file__, "rb").read(),
                          capture_output=True, env=env, timeout=60)
    got = json.loads(done.stdout)
    assert isinstance(got.get("why"), str) and got["why"]


# ── the daemon's route ───────────────────────────────────────────────────────

class _MarkedScreen(PictureScreen):
    """A display with an accessibility tree: one panel button, one field, one
    box off the screen and fields the protocol does not name."""

    TREE = {
        "marks": [
            {"role": "push button", "name": "Terminal Emulator", "box": [40, 762, 40, 36],
             "app": "xfce4-panel", "window": 0, "secret": "never passes"},
            {"role": "text", "name": "  Search   files ", "box": [300, 150, 380, 30], "app": "thunar",
             "window": 1, "editable": True},
            {"role": "menu", "name": "Off", "box": [1270, 10, 40, 20], "app": "x"},
            {"role": "menu", "name": "Bad", "box": "0,0,1,1"},
        ],
        "windows": [{"app": "xfce4-panel", "name": "", "box": [0, 760, 1280, 40], "role": "frame",
                     "active": False, "id": 0, "marks": 1},
                    {"app": "thunar", "name": "home", "box": [100, 100, 600, 400], "role": "frame",
                     "active": True, "id": 1, "marks": 1}],
    }

    def marks(self):
        return json.loads(json.dumps(self.TREE))

    def grab(self, fmt):
        def draw(d):
            for m in self.TREE["marks"][:2]:
                x, y, w, h = m["box"]
                d.rectangle([x, y, x + w, y + h], outline=(60, 60, 60), width=1)
        return _picture(draw), "image/png"


class _Auth:
    is_configured = True

    def get_privileges(self, owner):
        return {"can_use_workstation": True} if owner in (PERSON, OTHER) else {}


@pytest.fixture
def station(tmp_path, monkeypatch):
    with running_workstation(tmp_path, screen_factory=_MarkedScreen) as ws:
        settings = {"workstation_enabled": True, "workstation_url": ws.url,
                    "workstation_token": ws.token}
        monkeypatch.setattr(wc, "_setting", lambda key, default="": settings.get(key, default))
        monkeypatch.delenv(P.URL_ENV, raising=False)
        monkeypatch.setattr(tool_security, "owner_is_admin", lambda owner: False)
        monkeypatch.setattr(core.auth, "AuthManager", _Auth)
        monkeypatch.setattr(screen_marks, "ENABLED", True)
        # The picture's text is the a11y marks' business here; OCR stays out
        # so each case is about one source.
        monkeypatch.setattr(screen_marks, "text_lines", lambda png: [])
        for owner in (PERSON, OTHER):
            screen_marks.forget(owner, "desktop")
        yield ws


def test_the_marks_route_passes_only_boxes_on_the_screen_and_named_fields(station):
    got = run(WorkstationClient(station.url, station.token).marks(account_for(PERSON)))
    assert got["source"] == "a11y" and (got["width"], got["height"]) == (P.SCREEN_WIDTH, P.SCREEN_HEIGHT)
    assert [m["name"] for m in got["marks"]] == ["Terminal Emulator", "Search files"]
    assert all("secret" not in m for m in got["marks"])
    assert got["marks"][1]["editable"] is True
    assert [w["app"] for w in got["windows"]] == ["xfce4-panel", "thunar"]


def test_a_screen_without_a_tree_says_so(tmp_path):
    with running_workstation(tmp_path) as ws:
        with pytest.raises(WorkstationError) as e:
            run(WorkstationClient(ws.url, ws.token).marks("pw-local-e3b0c442"))
    assert e.value.code == "unavailable" and "picture" in e.value.message


def test_the_route_is_in_the_protocol_and_every_backend_has_it():
    from workstation.agentd import Workstation
    from workstation.vm import VmStation
    assert P.ROUTES["marks"] == ("GET", "/v1/users/{account}/marks")
    assert VmStation.marks is not Workstation.marks, "the VM's machine reads its own desktop"


# ── `G4`: through the dispatcher ─────────────────────────────────────────────

def call(args, owner=PERSON):
    content = args if isinstance(args, str) else json.dumps(args)
    return run(execute_tool_block(ToolBlock("computer", content), owner=owner,
                                  security_context=NO_TOOL_SECURITY_CONTEXT))


def test_a_screenshot_comes_back_with_its_marks_drawn_and_listed(station):
    plain = run(WorkstationClient(station.url, station.token).screenshot(account_for(PERSON)))
    _desc, result = call({"action": "screenshot"})
    assert result["exit_code"] == 0
    lines = result["output"].splitlines()
    assert any(line.startswith("[1] text field") and "(490, 165)" in line for line in lines), lines
    assert any(line.startswith("[2] button “Terminal Emulator”") and "(60, 780)" in line
               for line in lines), lines
    assert '"mark": N' in result["output"]
    [image] = result["images"]
    assert image["data"] != plain["data_b64"], "the marks are drawn on the picture"
    from PIL import Image
    assert Image.open(io.BytesIO(base64.b64decode(image["data"]))).size == (P.SCREEN_WIDTH, P.SCREEN_HEIGHT)


def test_a_mark_clicks_its_middle_on_that_persons_display(station):
    call({"action": "screenshot"})
    desc, result = call({"action": "click", "mark": 2})
    assert result["exit_code"] == 0, result
    assert desc == "computer: click mark 2"
    assert station.screen(account_for(PERSON)).actions == [{"action": "click", "x": 60, "y": 780}]
    assert "Did: click mark 2 “Terminal Emulator” at (60, 780)." in result["output"]


def test_type_with_a_mark_clicks_the_field_first(station):
    call({"action": "screenshot"})
    _desc, result = call({"action": "type", "mark": "[1]", "text": "notes"})
    assert result["exit_code"] == 0, result
    assert station.screen(account_for(PERSON)).actions == [
        {"action": "click", "x": 490, "y": 165}, {"action": "type", "text": "notes"}]


def test_a_drag_goes_from_mark_to_mark(station):
    call({"action": "screenshot"})
    call({"action": "drag", "mark": 1, "to_mark": 2})
    assert station.screen(account_for(PERSON)).actions == [
        {"action": "drag", "x": 490, "y": 165, "to_x": 60, "to_y": 780}]


@pytest.mark.parametrize("args, words", [
    ({"action": "click", "mark": 9}, "no mark 9"),
    ({"action": "click", "mark": 0}, "number of a mark"),
    ({"action": "key", "keys": "Return", "mark": 1}, "goes with a click"),
])
def test_a_mark_that_is_not_on_the_last_screenshot_is_refused_and_nothing_is_sent(station, args, words):
    call({"action": "screenshot"})
    before = list(station.screen(account_for(PERSON)).actions)
    _desc, result = call(args)
    assert result["exit_code"] == 1 and words in result["error"], result
    assert station.screen(account_for(PERSON)).actions == before


def test_marks_are_the_persons_own(station):
    call({"action": "screenshot"}, owner=PERSON)
    _desc, result = call({"action": "click", "mark": 1}, owner=OTHER)
    assert result["exit_code"] == 1 and "screenshot first" in result["error"]
    assert station.screen(account_for(OTHER)).actions == []


def test_a_point_beside_a_mark_wins(station):
    call({"action": "screenshot"})
    call({"action": "click", "mark": 2, "x": 5, "y": 6})
    assert station.screen(account_for(PERSON)).actions == [{"action": "click", "x": 5, "y": 6}]


def test_an_action_answers_with_fresh_marks(station):
    call({"action": "screenshot"})
    _desc, result = call({"action": "move", "mark": 1})
    assert "Numbered marks on the screenshot" in result["output"]


def test_switched_off_the_screenshot_is_plain_and_a_mark_is_refused(station, monkeypatch):
    monkeypatch.setattr(screen_marks, "ENABLED", False)
    plain = run(WorkstationClient(station.url, station.token).screenshot(account_for(PERSON)))
    _desc, result = call({"action": "screenshot"})
    assert "Numbered marks" not in result["output"]
    assert result["images"][0]["data"] == plain["data_b64"]
    _desc, result = call({"action": "click", "mark": 1})
    assert result["exit_code"] == 1 and "Marks are off" in result["error"]
    assert station.screen(account_for(PERSON)).actions == []


def test_a_daemon_without_the_route_still_gets_marks_from_the_picture(station, monkeypatch):
    async def older(self, account):
        raise WorkstationError("not_found", "No such workstation route.")
    monkeypatch.setattr(WorkstationClient, "marks", older)
    monkeypatch.setattr(screen_marks, "text_lines",
                        lambda png: [{"role": "seen-text", "name": "Search", "box": [300, 150, 80, 30]}])
    _desc, result = call({"action": "screenshot"})
    assert "[1] text “Search” at (340, 165) (seen)" in result["output"], result["output"]
    call({"action": "click", "mark": 1})
    assert station.screen(account_for(PERSON)).actions == [{"action": "click", "x": 340, "y": 165}]


def test_the_rules_tell_the_model_to_point_by_number_only_while_marks_are_on():
    from src.agent_loop import COMPUTER_USE_MARKS_RULE
    assert '"mark": 7' in COMPUTER_USE_MARKS_RULE
    from src.tool_schemas import FUNCTION_TOOL_SCHEMAS
    [computer] = [s["function"] for s in FUNCTION_TOOL_SCHEMAS if s["function"]["name"] == "computer"]
    assert computer["parameters"]["properties"]["mark"]["type"] == "integer"
    assert "numbered" in computer["description"]


# ── `G3`: the picture ────────────────────────────────────────────────────────

def test_an_icon_on_a_quiet_ground_is_found_and_a_busy_pattern_is_not():
    import numpy as np
    from PIL import Image

    def draw(d):
        # An icon: a framed square with strokes inside, on the plain ground.
        d.rectangle([200, 200, 232, 232], outline=(30, 30, 30), width=2)
        d.line([206, 216, 226, 216], fill=(30, 30, 30), width=2)
        d.line([216, 206, 216, 226], fill=(30, 30, 30), width=2)
        # A wallpaper: dense criss-crossing lines over a region.
        for i in range(0, 300, 7):
            d.line([600 + i, 400, 600, 400 + i], fill=(20, 60, 120), width=1)
            d.line([600 + i, 700, 900, 400 + i], fill=(200, 120, 40), width=1)
    gray = np.asarray(Image.open(io.BytesIO(_picture(draw))).convert("L"))
    found = screen_marks.shapes(gray)
    assert any(f["box"][0] <= 216 <= f["box"][0] + f["box"][2] and
               f["box"][1] <= 216 <= f["box"][1] + f["box"][3] for f in found), found
    assert not any(600 <= f["box"][0] <= 900 and 400 <= f["box"][1] <= 700 for f in found), found


def test_without_an_ocr_program_there_is_simply_no_text(monkeypatch):
    monkeypatch.setattr(shutil, "which", lambda name: None)
    assert screen_marks.text_lines(_picture()) == []


@pytest.mark.skipif(not shutil.which("tesseract"), reason="Tesseract is not installed here")
def test_text_on_the_picture_is_read_into_lines():
    from PIL import ImageFont

    def draw(d):
        try:
            font = ImageFont.truetype("/usr/share/fonts/truetype/dejavu/DejaVuSans.ttf", 18)
        except OSError:
            pytest.skip("no DejaVu font here")
        d.text((100, 100), "Open Settings", fill=(20, 20, 20), font=font)
    lines = screen_marks.text_lines(_picture(draw))
    assert any("Settings" in t["name"] for t in lines), lines


def test_a_seen_mark_on_a_described_one_is_dropped_and_numbers_read_in_order():
    described = screen_marks.normalise([{"role": "menu", "name": "File", "box": [10, 40, 40, 20]}],
                                       1280, 800, "a11y")
    seen = screen_marks.normalise([{"role": "seen-text", "name": "File", "box": [12, 42, 30, 16]},
                                   {"role": "seen-shape", "name": "", "box": [500, 10, 24, 24]}],
                                  1280, 800, "seen")
    merged = screen_marks.merge(described, seen)
    assert [(m["n"], m["source"]) for m in merged] == [(1, "seen"), (2, "a11y")]


def test_marks_are_forgotten_after_a_while(monkeypatch):
    screen_marks.remember("x", "desktop", [{"n": 1, "box": [0, 0, 10, 10]}])
    assert screen_marks.resolve("x", "desktop", 1)[0] is not None
    monkeypatch.setattr(screen_marks, "MARKS_TTL_S", -1)
    assert "screenshot first" in screen_marks.resolve("x", "desktop", 1)[1]


# ── `G1`: the agent browser ──────────────────────────────────────────────────

class _FakeBrowserClient:
    def __init__(self):
        self.calls = []

    async def browser(self, account, action, **fields):
        self.calls.append((action, fields))
        if action == "frame":
            return {"mime": "image/png", "data_b64": base64.b64encode(_picture()).decode(),
                    "width": P.SCREEN_WIDTH, "height": P.SCREEN_HEIGHT, "url": "https://x.test/",
                    "title": "X", "tabs": []}
        if action == "read":
            return {"viewport": [P.SCREEN_WIDTH, P.SCREEN_HEIGHT], "elements": [
                {"ref": 1, "tag": "a", "label": "Home", "box": [10, 10, 60, 20]},
                {"ref": 2, "tag": "input", "type": "email", "label": "Email"},
                {"ref": 3, "tag": "button", "label": "Sign in", "box": [100, 300, 90, 32]}]}
        return {"url": "https://x.test/", "title": "X", "tabs": []}


def test_the_browsers_screenshot_is_numbered_by_the_pages_own_refs(monkeypatch):
    from src.agent_tools import browser_tools
    import src.local_browser as lb
    client = _FakeBrowserClient()

    async def ready(owner):
        return client, "acct"

    async def no_names(*a, **k):
        return None
    monkeypatch.setattr(lb, "ready_browser", ready)
    monkeypatch.setattr(browser_tools, "sync_names", no_names)
    monkeypatch.setattr(screen_marks, "ENABLED", True)
    result = run(browser_tools.BrowserTool().execute(json.dumps({"action": "screenshot"}), {"owner": PERSON}))
    assert "[1] link “Home” at (40, 20)" in result["output"], result["output"]
    assert "[3] button “Sign in” at (145, 316)" in result["output"]
    assert "[2]" not in result["output"], "an element out of view is not drawn"
    assert result["images"][0]["data"] != base64.b64encode(_picture()).decode(), "the marks are drawn"
    run(browser_tools.BrowserTool().execute(json.dumps({"action": "click", "mark": 3}), {"owner": PERSON}))
    assert client.calls[-1] == ("click", {"ref": 3})


def test_a_browser_mark_is_a_ref():
    from src.agent_tools.browser_tools import parse_args
    assert parse_args({"action": "click", "mark": "7"})[0]["ref"] == 7


# ── opt-in: the real tree on a real desktop ──────────────────────────────────

@pytest.mark.skipif(os.environ.get("PANTHEON_A11Y_E2E") != "1" or not os.environ.get("DISPLAY"),
                    reason="needs PANTHEON_A11Y_E2E=1 and DISPLAY on a running XFCE session")
def test_a_real_xfce_desktop_describes_its_panel():
    python = os.environ.get("PANTHEON_A11Y_PYTHON", "/usr/bin/python3")
    done = subprocess.run([python, "-I", "-"], input=open(a11y_marks.__file__, "rb").read(),
                          capture_output=True, timeout=60)
    got = json.loads(done.stdout)
    assert not got.get("why"), got
    assert any(m["app"] == "xfce4-panel" for m in got["marks"]), got
