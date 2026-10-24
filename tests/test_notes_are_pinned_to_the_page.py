# SPDX-License-Identifier: AGPL-3.0-or-later
"""`P26-01` … `P26-03` — notes pinned to the live page's elements, drawn on,
and read and closed by the agent.

Driven, not read (`Law 20`): the real daemon starting a real Firefox against a
page served on this machine that changes under the notes — a reflow, a
re-render, an element removed — and the real `agent_browser` tool reading
them. Without Firefox the browser half is skipped, said, and the rest runs.

**Measured before this file, on `1b63b44`:** there were no notes. To say
"make this button blue" the person typed a description of where the button
was, and the agent guessed which one.
"""

from __future__ import annotations

import json
import shutil
import threading
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

import pytest

from src.agent_tools import browser_tools as B
from workstation import page_notes as N

FIREFOX = shutil.which("firefox")
needs_firefox = pytest.mark.skipif(FIREFOX is None, reason="Firefox is not installed here")

PAGE = b"""<html><head><title>Shop</title><style>body{margin:0;font:16px sans-serif}
#hero{height:120px} button{display:block;margin:8px;width:200px;height:40px}</style></head>
<body><div id=hero>Hero</div>
<button id=buy>Buy now</button><button>Save for later</button>
<script>
window.grow = () => { document.getElementById('hero').style.height = '300px'; };
window.rerender = () => { const b = document.createElement('button'); b.textContent = 'Save for later';
  const old = document.querySelectorAll('button')[1]; old.replaceWith(b); };
window.drop = () => { document.getElementById('buy').remove(); };
</script></body></html>"""


class _Site(BaseHTTPRequestHandler):
    def log_message(self, *a):
        pass

    def do_GET(self):
        self.send_response(200)
        self.send_header("Content-Type", "text/html; charset=utf-8")
        self.send_header("Content-Length", str(len(PAGE)))
        self.end_headers()
        self.wfile.write(PAGE)


@pytest.fixture(scope="module")
def site():
    srv = ThreadingHTTPServer(("127.0.0.1", 0), _Site)
    threading.Thread(target=srv.serve_forever, daemon=True).start()
    yield f"http://127.0.0.1:{srv.server_address[1]}"
    srv.shutdown()


# ── the book ────────────────────────────────────────────────────────────────

def test_a_book_keeps_notes_per_page_and_across_a_restart(tmp_path):
    book = N.NoteBook(tmp_path)
    a = book.add("http://x/a#top", {"selector": "#buy", "tag": "button", "role": "", "text": "Buy now"},
                 "Make this blue", [10, 5])
    book.add("http://x/b", {"selector": "h1", "tag": "h1", "role": "", "text": "Hi"}, "Bigger", [0, 0])
    assert [n["text"] for n in book.for_page("http://x/a")] == ["Make this blue"], "the fragment is not a page"
    book.edit(a["id"], shapes=[{"kind": "arrow", "points": [[-40, 10], [5, 5], [9, 9]]}], width=1280, height=800)
    again = N.NoteBook(tmp_path)
    [kept] = again.for_page("http://x/a")
    assert kept["shapes"] == [{"kind": "arrow", "points": [[-40, 10], [9, 9]]}], "an arrow is its two ends"
    again.mark([1], "done", "Changed to blue.")
    assert again.for_page("http://x/a", open_only=True) == []
    assert again.add("http://x/a", kept["anchor"], "next", [0, 0])["n"] == 3, "numbers are not reused"


@pytest.mark.parametrize("shape,words", [
    ({"kind": "star", "points": [[0, 0], [1, 1]]}, "one of arrow"),
    ({"kind": "box", "points": [[0, 0]]}, "2 to"),
    ({"kind": "line", "points": [["a", 0], [1, 1]]}, "[x, y]"),
])
def test_a_bad_drawing_is_refused_in_a_sentence(tmp_path, shape, words):
    book = N.NoteBook(tmp_path)
    note = book.add("http://x/", {"selector": "p", "tag": "p", "text": ""}, "x", [0, 0])
    with pytest.raises(N.NoteRefused) as e:
        book.edit(note["id"], shapes=[shape], width=100, height=100)
    assert words in e.value.message


def test_the_model_reads_each_note_by_its_element_and_where_it_is():
    text = B.notes_text({"url": "http://x/a", "notes": [
        {"n": 1, "page": "http://x/a", "status": "open", "text": "Make this blue", "box": [8, 128, 200, 40],
         "where": "here", "anchor": {"tag": "button", "text": "Buy now"}, "shapes": [{"kind": "arrow"}]},
        {"n": 2, "page": "http://x/a", "status": "sent", "text": "Remove", "lost": True,
         "anchor": {"tag": "div", "text": "Promo"}, "shapes": []},
        {"n": 3, "page": "http://x/a", "status": "done", "text": "old", "anchor": {}, "shapes": []}]})
    assert "Note 1: on button “Buy now” (1 drawing): Make this blue" in text
    assert "Note 2: on div “Promo” — that element is no longer on the page: Remove" in text
    assert "Note 3" not in text, "a closed note is not listed"
    assert B.parse_args({"action": "note_add"})[1], "making a note is the person's"
    assert B.parse_args({"action": "note_done", "note": 1})[1] is None


# ── the daemon, with a real Firefox ─────────────────────────────────────────

@pytest.fixture(scope="module")
def station(tmp_path_factory):
    if FIREFOX is None:
        pytest.skip("Firefox is not installed here")
    from workstation.agentd import SingleUserSystem, Workstation
    ws = Workstation(SingleUserSystem(tmp_path_factory.mktemp("notes-home")), "tok")
    yield ws
    ws.browsers.stop_all()


ACCOUNT = "pw-ann-0123abcd"


def _call(station, action, who="person", **body):
    return station.browser(ACCOUNT, {"action": action, "holder": who, **body})


def _eval(station, js):
    b = station.browsers.get(ACCOUNT)
    with b.lock:
        b._eval(b._ctx(), f"() => {{ {js}; return ''; }}")


@needs_firefox
def test_a_note_follows_its_element_and_says_lost_when_it_is_gone(station, site):
    from workstation.agentd import WorkstationError
    _call(station, "open", url=site + "/")
    got = _call(station, "note_add", x=50, y=150, text="Make this blue")    # on “Buy now”
    [note] = got["notes"]
    assert note["anchor"]["selector"] == "#buy" and note["anchor"]["text"] == "Buy now"
    assert note["box"][1] == 128 and note["lost"] is False
    second = _call(station, "note_add", x=50, y=200, text="Smaller")["notes"][1]
    assert second["anchor"]["text"] == "Save for later" and ":nth-of-type(2)" in second["anchor"]["selector"]

    _eval(station, "grow()")                     # the page reflows: both move down 180px
    boxes = [n["box"][1] for n in _call(station, "notes")["notes"]]
    assert boxes == [308, 356], "each note followed its element"
    _eval(station, "rerender()")                 # the second button is a new element now
    assert _call(station, "notes")["notes"][1]["lost"] is False, "found again by its place and text"
    _eval(station, "drop()")                     # “Buy now” is gone
    first, then = _call(station, "notes")["notes"]
    assert first["lost"] is True and "box" not in first
    assert then["lost"] is False and then["anchor"]["text"] == "Save for later", \
        "the second note did not jump onto whatever now sits where the first was"

    with pytest.raises(WorkstationError) as nothing:
        _call(station, "note_add", x=5, y=790, text="nothing here")
    assert "nothing on the page there" in nothing.value.message


@needs_firefox
def test_drawings_and_the_agent_closing_notes(station, site):
    from workstation.agentd import WorkstationError
    _call(station, "open", url=site + "/")
    notes = _call(station, "notes")["notes"]
    open_ = [n for n in notes if n["status"] == "open"]
    target = open_[-1]
    drawn = _call(station, "note_edit", note=target["id"],
                  shapes=[{"kind": "circle", "points": [[-10, -10], [210, 50]]}])
    assert [n for n in drawn["notes"] if n["id"] == target["id"]][0]["shapes"][0]["kind"] == "circle"
    with pytest.raises(WorkstationError):
        _call(station, "note_add", who="agent", x=50, y=150, text="the agent may not")
    _call(station, "notes_sent", notes=[n["id"] for n in open_])
    closed = _call(station, "note_done", who="agent", note=target["n"], said="Made it smaller.")
    mine = [n for n in closed["notes"] if n["id"] == target["id"]][0]
    assert mine["status"] == "done" and mine["said"] == "Made it smaller."
    assert "Smaller" not in B.notes_text(closed), "a closed note leaves the agent's list"


# ── the window's own words, under node ──────────────────────────────────────

def test_the_message_and_the_crops_the_window_sends(tmp_path):
    import subprocess
    from pathlib import Path
    node = shutil.which("node")
    if not node:
        pytest.skip("node is not installed here")
    js = Path(__file__).resolve().parents[1] / "static" / "js"
    case = tmp_path / "case.mjs"
    case.write_text(f"""
const {{ notesMessage, cropBox, describeNote }} = await import('{(js / "pageNotes.js").as_uri()}');
const notes = [
  {{ n: 1, text: 'Make this blue', anchor: {{ tag: 'button', text: 'Buy now' }}, shapes: [{{ kind: 'arrow' }}] }},
  {{ n: 2, text: '', anchor: {{ tag: 'div', text: 'Promo' }}, lost: true, shapes: [] }},
];
console.log(JSON.stringify({{
  msg: notesMessage(notes, {{ title: 'Shop', url: 'http://x/' }}),
  lost: describeNote(notes[1]),
  mid: cropBox([600, 400, 80, 30], 1280, 800),
  corner: cropBox([0, 0, 20, 20], 1280, 800),
  wide: cropBox([0, 100, 2000, 40], 1280, 800),
  none: cropBox(null, 1280, 800),
}}));
""")
    out = json.loads(subprocess.run([node, str(case)], capture_output=True, text=True, timeout=60, check=True).stdout)
    assert out["msg"].startswith("I left 2 notes on Shop (http://x/).")
    assert "agent_browser notes" in out["msg"] and "note_done" in out["msg"]
    assert "Note 1 — on button “Buy now” [1 mark drawn]: Make this blue" in out["msg"]
    assert "Note 2 — on div “Promo” — no longer on the page: (no words — see the picture)" in out["msg"]
    assert out["mid"] == {"x": 460, "y": 305, "w": 360, "h": 220}, "the element in the middle of its crop"
    assert out["corner"]["x"] == 0 and out["corner"]["y"] == 0, "a crop stays on the page"
    assert out["wide"]["w"] == 1280 and out["wide"]["x"] == 0
    assert out["none"] == {"x": 0, "y": 0, "w": 800, "h": 500}
