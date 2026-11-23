# SPDX-License-Identifier: AGPL-3.0-or-later
"""Apollo's orb (phase 6), driven under node: the real `apolloOrb.js` and
`apolloOrbModel.js` on the shared DOM shim.

It shows only while Apollo's chat is open and "Show the orb" is on; its mood
follows the page (dictation, a reply read aloud, a busy chat, a task that needs
the person), most pressing first; the person's place for it is kept; and a
`show` from the model points it at the composer, a task in the pane, a line
range in a code block or a registered code view, then sends it back.

The server half (`ui_control show`) is in
`test_apollos_orb_is_pointed_by_ui_control`.
"""
from __future__ import annotations

import shutil
import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parent))

from test_apollos_pane_shows_the_work_and_what_it_knows_js import _SHIM  # noqa: E402
from test_tool_effect_surfaces_js import _make_sandbox, _run  # noqa: E402

ROOT = Path(__file__).resolve().parents[1]
ORB = ROOT / "static" / "js" / "apolloOrb.js"

pytestmark = pytest.mark.skipif(not shutil.which("node"), reason="node binary not on PATH")

# The pane and spaces are the pane's own tests; here they only need to draw a
# task row the orb can find.
_STUBS = {
    "apolloPane.js": (
        "import { document } from './shim.js';\n"
        "let open = false;\n"
        "export function isApolloPaneOpen() { return open; }\n"
        "export function openApolloPane() {\n"
        "  open = true;\n"
        "  const m = document.createElement('div'); m.id = 'apollo-pane-modal';\n"
        "  const row = document.createElement('li'); row.setAttribute('data-task-id', 't7'); row.dataset.taskId = 't7';\n"
        "  row.getBoundingClientRect = () => ({ left: 700, top: 300, width: 280, height: 40 });\n"
        "  m.appendChild(row); document.body.appendChild(m); globalThis.paneOpened = (globalThis.paneOpened || 0) + 1;\n"
        "  return true;\n"
        "}\n"
    ),
    "apolloSpaces.js": "export function spaceParam() { return ''; }\n",
}

_PREAMBLE = (
    "import { document, Node, routes, settle, sent } from './shim.js';\n"
    "globalThis.innerWidth = 1200; globalThis.innerHeight = 800;\n"
    # The window is globalThis in the shim; give it the event target a browser has.
    "{ const on = {}; globalThis.addEventListener = (t, f) => { (on[t] = on[t] || []).push(f); };\n"
    "  globalThis.dispatchEvent = (ev) => { (on[ev.type] || []).slice().forEach((f) => f(ev)); return true; }; }\n"
    # Text nodes and a Range that lays a code block out 20px a line from y=100,
    # so the orb's offset-to-line mapping can be checked without a browser.
    "Object.defineProperty(Node.prototype, 'nodeValue', { get() { return this.textContent; } });\n"
    "document.createTreeWalker = (root) => { const list = root._walk([]).filter((n) => n.tagName === '#TEXT');\n"
    "  let i = -1; return { nextNode: () => list[++i] || null }; };\n"
    "document.createRange = () => { const r = { setStart(n, o) { r.a = [n, o]; }, setEnd(n, o) { r.b = [n, o]; },\n"
    "  getClientRects() { const nodes = r.a[0].parentNode._walk([]).filter((n) => n.tagName === '#TEXT');\n"
    "    const abs = ([n, o]) => nodes.slice(0, nodes.indexOf(n)).reduce((s, x) => s + x.textContent.length, 0) + o;\n"
    "    const all = nodes.map((n) => n.textContent).join('');\n"
    "    const lineOf = (off) => all.slice(0, off).split('\\n').length - 1;\n"
    "    const out = []; for (let l = lineOf(abs(r.a)); l <= lineOf(abs(r.b)); l++) out.push({ left: 60, top: 100 + l * 20, width: 300, height: 20 });\n"
    "    return out; } }; return r; };\n"
    "routes['GET /api/apollo/state'] = () => [200, { status: { state: 'idle' } }];\n"
    "const O = await import('./apolloOrb.js');\n"
    "const orb = () => document.getElementById('apollo-orb');\n"
    "const pos = () => { const m = /translate\\((-?\\d+)px, (-?\\d+)px\\)/.exec(orb().style.transform); return m ? [Number(m[1]), Number(m[2])] : null; };\n"
    "const say = () => document._walk([]).find((n) => n.className === 'apollo-orb-say');\n"
    "const spot = () => document._walk([]).find((n) => n.className === 'apollo-orb-spot');\n"
    "const fire = (target, type, detail) => target.dispatchEvent(new CustomEvent(type, { detail }));\n"
    "const out = (o) => console.log(JSON.stringify(o));\n"
)


@pytest.fixture(scope="module")
def box(tmp_path_factory):
    return _make_sandbox(tmp_path_factory.mktemp("apolloorb"), ORB, _SHIM, _STUBS)


def _case(box, script):
    return _run(box, _PREAMBLE, script + "\nO.setApolloChat(false);\n")


def test_it_shows_only_in_apollos_chat_and_only_while_switched_on(box):
    o = _case(box, """
        const before = !!orb();
        O.setApolloChat(true);
        const inChat = !!orb();
        O.setOrbShown(false);
        const off = !!orb();
        O.setOrbShown(true);
        const back = !!orb();
        O.setApolloChat(false);
        out({ before, inChat, off, back, left: !!orb(), label: null });
    """)
    assert o == {"before": False, "inChat": True, "off": False, "back": True, "left": False, "label": None}


def test_its_mood_follows_the_page_most_pressing_first(box):
    o = _case(box, """
        O.setApolloChat(true);
        await settle();
        const seen = [orb().dataset.mood];
        fire(document, 'pantheon:apollo-state', { tone: 'needs' }); seen.push(orb().dataset.mood);
        fire(window, 'pantheon:chat-busy-change', { active: true }); seen.push(orb().dataset.mood);
        fire(window, 'pantheon:speaking', { active: true }); seen.push(orb().dataset.mood);
        fire(window, 'pantheon:dictation', { state: 'listening' }); seen.push(orb().dataset.mood);
        fire(window, 'pantheon:dictation', { state: '' });
        fire(window, 'pantheon:speaking', { active: false });
        fire(window, 'pantheon:chat-busy-change', { active: false }); seen.push(orb().dataset.mood);
        out({ seen, label: orb().getAttribute('aria-label') });
    """)
    assert o["seen"] == ["idle", "needs", "thinking", "speaking", "listening", "needs"]
    assert o["label"].startswith("Apollo, something needs you.")


def test_a_shut_pane_still_lets_needs_you_turn_it_amber(box):
    o = _case(box, """
        routes['GET /api/apollo/state'] = () => [200, { status: { state: 'needs_you' } }];
        O.setApolloChat(true);
        await settle();
        out({ mood: orb().dataset.mood, asked: sent.filter((s) => s.url.startsWith('/api/apollo/state')).length });
    """)
    assert o == {"mood": "needs", "asked": 1}


def test_where_the_person_puts_it_is_kept_and_it_goes_back_there(box):
    o = _case(box, """
        O.setApolloChat(true);
        const home = pos();
        orb().dispatchEvent(Object.assign(new Event('keydown'), { key: 'ArrowLeft', shiftKey: true, preventDefault() {} }));
        const moved = pos();
        O.setApolloChat(false); O.setApolloChat(true);
        const kept = pos();
        await O.show({ place: 'chat_input', label: 'Type here' });
        out({ home, moved, kept, pointing: pos() });
    """)
    assert o["home"] == [1200 - 56 - 28, 800 - 56 - 132]
    assert o["moved"] == [o["home"][0] - 48, o["home"][1]]
    assert o["kept"] == o["moved"]


def test_a_show_points_at_the_composer_with_words_and_escape_sends_it_back(box):
    o = _case(box, """
        const input = document.createElement('textarea'); input.id = 'message';
        input.getBoundingClientRect = () => ({ left: 300, top: 700, width: 600, height: 60 });
        document.body.appendChild(input);
        O.setOrbStill(true);
        O.setApolloChat(true);
        const rest = pos();
        const ok = await O.show({ place: 'chat_input', label: 'Type your reply here' });
        const at = pos();
        const shown = { spot: !spot().hidden, size: [spot().style.width, spot().style.height], words: say().textContent, hidden: say().hidden };
        orb().dispatchEvent(Object.assign(new Event('keydown'), { key: 'Escape', preventDefault() {} }));
        out({ ok, at, shown, back: pos(), rest, cleared: spot().hidden && say().hidden, scrolled: input.scrolledIntoView });
        O.setOrbStill(false);
    """)
    assert o["ok"] is True
    assert o["at"] == [300 - 56 - 14, 700 + 30 - 28]   # beside it on the left, centred
    assert o["shown"] == {"spot": True, "size": ["608px", "68px"], "words": "Type your reply here", "hidden": False}
    assert o["back"] == o["rest"] and o["cleared"] is True and o["scrolled"] is True


def test_a_task_opens_the_pane_and_points_at_its_row(box):
    o = _case(box, """
        O.setOrbStill(true);
        O.setApolloChat(true);
        const ok = await O.show({ place: 'task', target: 't7' });
        const at = pos();
        const missing = await O.show({ place: 'task', target: 'nope' });
        out({ ok, opened: globalThis.paneOpened, at, words: say().textContent, missing });
        O.setOrbStill(false);
    """)
    assert o["ok"] is True and o["opened"] == 1
    assert o["at"] == [700 - 56 - 14, 300 + 20 - 28]
    # A task not in the list points at the pane and says so.
    assert o["missing"] is True and o["words"] == "That task isn't in the list right now."


def test_a_line_range_in_a_code_block_is_marked_whole_lines_wide(box):
    o = _case(box, """
        const pre = document.createElement('pre');
        const code = document.createElement('code');
        code.appendChild(document.createTextNode('def a():\\n    return 1\\n'));
        code.appendChild(document.createTextNode('\\ndef b():\\n    return 2\\n'));
        pre.appendChild(code); document.body.appendChild(pre);
        code.closest = () => pre;
        pre.getBoundingClientRect = () => ({ left: 40, top: 80, width: 640, height: 200 });
        O.setOrbStill(true);
        O.setApolloChat(true);
        const ok = O.highlightCode(code, 4, 5);
        out({ ok, band: O.codeRange(code, 4, 5), words: say().textContent, past: O.codeRange(code, 40, 41) });
        O.setOrbStill(false);
    """)
    assert o["ok"] is True
    assert o["band"] == {"left": 40, "top": 160, "width": 640, "height": 40}
    assert o["words"] == "Lines 4 to 5"
    assert o["past"] is None


def test_a_registered_code_view_is_pointed_at_by_name(box):
    o = _case(box, """
        const asked = [];
        const off = O.registerCodeView('editor', {
          reveal: async (a, b) => { asked.push(['reveal', a, b]); },
          rangeRects: (a, b) => { asked.push(['rects', a, b]); return [{ left: 500, top: 200, width: 400, height: 18 }, { left: 500, top: 218, width: 380, height: 18 }]; },
        });
        O.setOrbStill(true);
        O.setApolloChat(true);
        const ok = await O.show({ place: 'view', target: 'editor', lines: [12, 13], label: 'This loop never ends' });
        const views = O.codeViews();
        off();
        const gone = await O.show({ place: 'view', target: 'editor', lines: [12, 13] });
        out({ ok, asked: asked.slice(0, 2), views, gone, words: say().textContent, at: pos() });
        O.setOrbStill(false);
    """)
    assert o["ok"] is True and o["gone"] is False
    assert o["asked"] == [["reveal", 12, 13], ["rects", 12, 13]]
    assert o["views"] == ["editor"]
    assert o["at"] == [500 - 56 - 14, 200 + 18 - 28]


def test_an_unknown_place_or_a_show_while_hidden_does_nothing(box):
    o = _case(box, """
        const hidden = await O.show({ place: 'chat_input' });
        O.setApolloChat(true);
        const odd = await O.show({ place: 'elsewhere' });
        const noId = await O.show({ place: 'task' });
        out({ hidden, odd, noId, spot: spot().hidden });
    """)
    assert o == {"hidden": False, "odd": False, "noId": False, "spot": True}


def test_the_model_reads_moods_places_and_lines(box):
    o = _case(box, """
        const M = await import('./apolloOrbModel.js');
        out({
          moods: [M.mood({}), M.mood({ needs: true, thinking: true }), M.mood({ speaking: true, listening: true })],
          still: M.glow('thinking', 3.3, null, true),
          loud: M.glow('speaking', 0, 1) > M.glow('speaking', 0, 0),
          beside: [M.besideRect({ left: 10, top: 300, width: 100, height: 40 }, 56, 1200, 800).side,
                   M.besideRect({ left: 0, top: 10, width: 1200, height: 40 }, 56, 1200, 800).side],
          clamp: M.clamp({ x: -50, y: 5000 }, 56, 1200, 800),
          span: [M.lineSpan('a\\nbb\\nccc', 2, 3), M.lineSpan('a\\nbb', 1, 1), M.lineSpan('a\\n', 5, 6)],
          read: [M.readShow({ place: 'code', lines: [9, 3] }), M.readShow({ place: 'view' }), M.readShow({ place: 'x' })],
          words: [M.showWords({ lines: [4, 4] }), M.showWords({ label: '  Here  ' })],
        });
    """)
    assert o["moods"] == ["idle", "thinking", "listening"]
    assert o["still"] == 1 and o["loud"] is True
    assert o["beside"] == ["right", "below"]
    assert o["clamp"] == {"x": 8, "y": 800 - 56 - 8}
    assert o["span"] == [[2, 8], [0, 1], None]
    assert o["read"] == [{"place": "code", "lines": [3, 9], "words": "Lines 3 to 9"}, None, None]
    assert o["words"] == ["Line 4", "Here"]
