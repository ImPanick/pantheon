# SPDX-License-Identifier: AGPL-3.0-or-later
r"""`B1833`, `B1834`, `B1836`, `B1839`…`B1843`, `B1845` — the Automations
canvas edits a workflow the way a node editor does.

**Measured before this file** (the canvas-editor and live-UX audits,
2026-11-07, in Chromium against the real server): Ctrl+Z, Ctrl+C/V/D,
Shift-click and Ctrl+S did nothing; a new step was added unjoined in the
corner under the start; removing a step that others read said nothing about
them; the bar had no Delete and no Duplicate, though the delete route was
there. Every step was the same grey box; Done on a step nobody touched made a
version; Close dropped what was typed without a word; a step just added left
the keyboard on the page behind the Workbench.

Each case drives the real room, canvas, panels, source and `workflowApi.js`
in node against the REAL server on a loopback port
(`tests/helpers/workflow_live.py`), and reads what was drawn, said and sent.
"""
from __future__ import annotations

import json
import shutil
import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parent))

from test_tool_effect_surfaces_js import _run  # noqa: E402
from test_the_workbench_canvas_js import _SHIM as _CANVAS_SHIM  # noqa: E402
from helpers.workflow_live import LIVE_PREAMBLE, LiveServer, build_sandbox  # noqa: E402
from tests.helpers.walker_harness import arrow, node, seed_workflow  # noqa: E402

pytestmark = pytest.mark.skipif(not shutil.which("node"), reason="node binary not on PATH")


@pytest.fixture(scope="module")
def box(tmp_path_factory):
    return build_sandbox(tmp_path_factory.mktemp("nodeeditor"), _CANVAS_SHIM)


@pytest.fixture()
def live(monkeypatch, tmp_path):
    from tests.helpers.assist_harness import build_world

    w = build_world(monkeypatch, tmp_path)
    seed_workflow(w.factory, [
        node("a", "Make it", "set", fields=[{"name": "title", "value": "Printer on fire"}]),
        node("b", "Shout it", "set", fields=[{"name": "loud", "value": "{{ steps.a.data.title }}"}]),
        node("w", "Pause", "wait", mode="for", minutes=5),
    ], [arrow("a", "b"), arrow("b", "w")], trigger_type="webhook")
    w.server = LiveServer(w.app)
    try:
        yield w
    finally:
        w.server.close()


_HELPERS = """
const viewportOf = (r) => r.querySelector('.wf-edit').querySelector('.wb-viewport');
// The shim's events do not bubble: a key the canvas takes anywhere is fired
// on the canvas's own root (the edit tab), from the empty canvas.
const key = (r, k, extra = {}) => fire(r.querySelector('.wf-edit'), 'keydown', { key: k, target: viewportOf(r), ...extra });
const ids = (r) => steps(r).map((n) => n.dataset.itemId);
const lastPut = () => { const c = calls('PUT', (u) => u.startsWith('/api/workflows/w-wf')); return c.length ? c[c.length - 1][1] : null; };
const kindButton = (r, kind) => r.querySelectorAll('.wf-palette-kind').find((b) => b.dataset.kind === kind) || null;
"""


def _case(box, live, script):
    return _run(box, LIVE_PREAMBLE(live.server.base) + _HELPERS, script)


def test_undo_and_redo_put_back_a_name_and_say_what_they_put_back(box, live):
    o = _case(box, live, """
        const { r } = await room({ workflowId: 'w-wf' });
        typed(by(r, 'wf-name'), 'Fire drill');
        await quiet();
        const dirty = by(r, 'wf-dirty').textContent;
        key(r, 'z', { ctrlKey: true }); await quiet();
        const undone = { name: by(r, 'wf-name').value, said: sayOf(r), dirty: by(r, 'wf-dirty').textContent };
        key(r, 'z', { ctrlKey: true, shiftKey: true }); await quiet();
        const redone = { name: by(r, 'wf-name').value, said: sayOf(r) };
        out({ dirty, undone, redone });
    """)
    assert o["dirty"] == "Unsaved changes"
    assert o["undone"]["name"] == "Morning digest", "Ctrl+Z put the name back"
    assert o["undone"]["said"] == "Undid the new name."
    assert o["undone"]["dirty"] != "Unsaved changes", "undone to the saved document: nothing to save"
    assert o["redone"] == {"name": "Fire drill", "said": "Redid the new name."}


def test_a_step_added_on_a_port_is_joined_beside_it_and_one_undo_takes_it_all_back(box, live):
    o = _case(box, live, """
        const { r } = await room({ workflowId: 'w-wf' });
        const port = nodeEl(r, 'w').querySelector('.wb-port-add');
        fire(port, 'click'); await quiet();
        const title = by(r, 'wf-palette-head').textContent;
        fire(kindButton(r, 'set'), 'click'); await quiet();
        const added = ids(r).filter((i) => !['a', 'b', 'w'].includes(i));
        const panelOpen = !by(r, 'wb-panel').hidden;
        fire(by(r, 'wb-panel-close'), 'click'); await quiet();
        // Save sends the draft: the new step and the arrow into it.
        fire(by(r, 'wf-save'), 'click'); await quiet();
        const sent = lastPut();
        key(r, 'z', { ctrlKey: true }); await quiet();
        out({ title, added, panelOpen, sentEdges: sent && sent.graph.edges, afterUndo: ids(r), said: sayOf(r) });
    """)
    assert o["title"] == "Add a step after “Pause”", "the picker says where the step goes"
    assert len(o["added"]) == 1 and o["panelOpen"] is True
    new = o["added"][0]
    assert {"from": "w", "port": "success", "to": new} in [
        {k: e[k] for k in ("from", "port", "to")} for e in o["sentEdges"]], "the new step is joined to the port"
    assert o["afterUndo"] == ["a", "b", "w"], "one Ctrl+Z takes the step, its arrow and its place back"
    assert o["said"].startswith("Undid adding “")


def test_duplicating_two_steps_points_the_copy_at_the_copy(box, live):
    o = _case(box, live, """
        const { r } = await room({ workflowId: 'w-wf' });
        fire(nodeEl(r, 'a'), 'click', { shiftKey: true }); await quiet();
        fire(nodeEl(r, 'b'), 'click', { shiftKey: true }); await quiet();
        const picked = r.querySelectorAll('.wb-node-picked').map((n) => n.dataset.itemId).sort();
        key(r, 'd', { ctrlKey: true }); await quiet();
        const said = sayOf(r);
        fire(by(r, 'wf-save'), 'click'); await quiet();
        const sent = lastPut();
        out({ picked, said, nodes: sent.graph.nodes, edges: sent.graph.edges });
    """)
    assert o["picked"] == ["a", "b"]
    assert o["said"].startswith("Duplicated 2 steps")
    copies = [n for n in o["nodes"] if n["id"] not in ("a", "b", "w")]
    assert sorted(n["label"] for n in copies) == ["Make it (copy)", "Shout it (copy)"]
    a2 = next(n for n in copies if n["label"] == "Make it (copy)")
    b2 = next(n for n in copies if n["label"] == "Shout it (copy)")
    assert json.dumps(b2["config"]).count(f"steps.{a2['id']}.data.title") == 1, (
        "the copied step reads the copied step, not the original")
    assert {"from": a2["id"], "port": "success", "to": b2["id"]} in [
        {k: e[k] for k in ("from", "port", "to")} for e in o["edges"]], "the arrow between them is copied"


def test_removing_a_step_another_reads_names_the_one_that_reads_it(box, live):
    o = _case(box, live, """
        const { r } = await room({ workflowId: 'w-wf' });
        const el = nodeEl(r, 'a');
        fire(el, 'keydown', { key: 'Delete', target: el });
        await quiet();
        out({ said: sayOf(r), still: ids(r) });
    """)
    assert o["said"].startswith("Remove “Make it”?") or o["said"].startswith("Remove Make it?")
    assert "“Shout it” uses what it makes" in o["said"]
    assert o["still"] == ["a", "b", "w"], "said first: nothing is removed yet"


def test_delete_asks_then_deletes_and_duplicate_makes_a_switched_off_copy(box, live):
    o = _case(box, live, """
        const { r } = await room({ workflowId: 'w-wf' });
        fire(by(r, 'wf-duplicate'), 'click'); await quiet();
        const copyName = by(r, 'wf-name').value;
        const copyOn = by(r, 'wf-switch').textContent;
        const listed = (await ask('/api/workflows')).workflows.map((w) => w.name).sort();
        fire(by(r, 'wf-delete'), 'click'); await quiet();
        const asked = sayOf(r);
        const left = (await ask('/api/workflows')).workflows.length;
        fire(sayButton(r), 'click'); await quiet();
        const after = (await ask('/api/workflows')).workflows.map((w) => w.name);
        out({ copyName, copyOn, listed, asked, left, after, said: sayOf(r) });
    """)
    assert o["copyName"] == "Morning digest (copy)" and o["copyOn"] == "Off"
    assert o["listed"] == ["Morning digest", "Morning digest (copy)"]
    assert o["asked"].startswith("Delete “Morning digest (copy)”?") and "cannot be undone" in o["asked"]
    assert o["left"] == 2, "said first: nothing is deleted on the first press"
    assert o["after"] == ["Morning digest"]
    assert o["said"].startswith("Deleted “Morning digest (copy)”.")


# ── `B1833`, `B1834`, `B1836`, `B1841`, `B1842`, `B1843` ────────────────────
# The shim's `input` does not bubble either: what the panel's own listener
# hears (`.wb-panel-host`) is fired on it, as a keystroke in its form would be.
_PANEL = """
const panelHost = (r) => r.querySelector('.wf-edit').querySelector('.wb-panel-host');
const field = (r, f) => panelHost(r).querySelectorAll('[data-field]').find((x) => x.dataset.field === f) || null;
const typeIn = (r, f, value) => { const el = field(r, f); typed(el, value); fire(panelHost(r), 'input', { target: el }); };
const open = async (r, id) => { fire(nodeEl(r, id), 'click'); await quiet(); };
// The shim's `click()` records a download; a button's is its click listeners,
// as a browser's is (Close presses the form's own Done through it).
const shimClick = Node.prototype.click;
Node.prototype.click = function click() {
  if (this.tagName === 'BUTTON') { fire(this, 'click'); return; }
  return shimClick.call(this);
};
"""


def _panel_case(box, live, script):
    return _run(box, LIVE_PREAMBLE(live.server.base) + _HELPERS + _PANEL, script)


def test_each_step_wears_its_kinds_glyph_on_its_familys_tile(box, live):
    o = _case(box, live, """
        const { r } = await room({ workflowId: 'w-wf' });
        const face = (id) => { const n = nodeEl(r, id); const i = n.querySelector('.wb-node-icon');
          return { cat: n.dataset.cat, tile: i ? i.dataset.cat : null,
                   glyph: !!(i && i.childNodes.length && i.childNodes[0].tagName === 'SVG'), inPort: !!n.querySelector('.wb-port-in') }; };
        out({ a: face('a'), w: face('w'), start: face('__start__') });
    """)
    assert o["a"] == {"cat": "logic", "tile": "logic", "glyph": True, "inPort": True}
    assert o["w"]["cat"] == "flow" and o["w"]["glyph"] is True
    assert o["start"]["cat"] == "trigger" and o["start"]["inPort"] is False, "nothing comes into the start"


def test_done_on_a_step_nobody_changed_is_not_a_change(box, live):
    o = _panel_case(box, live, """
        const { r } = await room({ workflowId: 'w-wf' });
        await open(r, 'a');
        fire(panelHost(r).querySelector('.wf-step-done'), 'click'); await quiet();
        out({ dirty: by(r, 'wf-dirty').textContent, said: sayOf(r), puts: calls('PUT').length });
    """)
    assert o["dirty"] != "Unsaved changes", "Done on an unchanged step changes nothing"


def test_close_keeps_what_was_typed(box, live):
    o = _panel_case(box, live, """
        const { r } = await room({ workflowId: 'w-wf' });
        await open(r, 'a');
        typeIn(r, 'label', 'Light it');
        fire(by(r, 'wb-panel-close'), 'click'); await quiet();
        const title = nodeEl(r, 'a').querySelector('.wb-node-title').textContent;
        out({ title, open: !by(r, 'wb-panel').hidden, dirty: by(r, 'wf-dirty').textContent });
    """)
    assert o["title"] == "Light it", "Close applied the form, as Done does"
    assert o["open"] is False and o["dirty"] == "Unsaved changes"


def test_a_step_just_added_has_the_keyboard_on_its_name(box, live):
    o = _panel_case(box, live, """
        const { r } = await room({ workflowId: 'w-wf' });
        fire(nodeEl(r, 'w').querySelector('.wb-port-add'), 'click'); await quiet();
        fire(kindButton(r, 'set'), 'click'); await quiet();
        const name = field(r, 'label');
        out({ focused: !!(name && name.focused), value: name && name.value });
    """)
    assert o["focused"] is True, "the new step's Name has the keyboard"
    assert o["value"] == "Set fields"


def test_a_step_added_on_an_arrow_stands_between_its_ends(box, live):
    o = _case(box, live, """
        const { r } = await room({ workflowId: 'w-wf' });
        const edge = r.querySelector('.wf-edit').querySelectorAll('g')
          .find((g) => g.getAttribute('data-from') === 'a' && g.getAttribute('data-to') === 'b');
        const plus = edge.childNodes.find((n) => n.getAttribute('class') === 'wb-edge-add');   // an SVG node: its class is an attribute
        fire(plus, 'click'); await quiet();
        const title = by(r, 'wf-palette-head').textContent;
        fire(kindButton(r, 'set'), 'click'); await quiet();
        fire(by(r, 'wb-panel-close'), 'click'); await quiet();
        fire(by(r, 'wf-save'), 'click'); await quiet();
        out({ label: plus.getAttribute('aria-label'), title, edges: lastPut().graph.edges });
    """)
    assert o["label"] == "Add a step between Make it and Shout it"
    assert o["title"] == "Add a step between “Make it” and “Shout it”"
    joined = [(e["from"], e["to"]) for e in o["edges"]]
    new = next(t for f, t in joined if f == "a")
    assert new not in ("b", "w") and (new, "b") in joined, joined
    assert ("a", "b") not in joined, "the arrow it was put on is taken away"


def test_ctrl_a_picks_every_step_and_a_right_click_offers_the_steps_own_menu(box, live):
    o = _case(box, live, """
        const { r } = await room({ workflowId: 'w-wf' });
        key(r, 'a', { ctrlKey: true }); await quiet();
        const picked = r.querySelectorAll('.wb-node-picked').map((n) => n.dataset.itemId).sort();
        fire(nodeEl(r, 'b'), 'contextmenu', { clientX: 40, clientY: 40 }); await quiet();
        const words = r.querySelectorAll('.wb-menu-word').map((w) => w.textContent);
        out({ picked, words });
    """)
    assert o["picked"] == ["a", "b", "w"], "the start is not a step that can be picked"
    for word in ("Duplicate", "Copy", "Remove"):
        assert any(w.startswith(word) for w in o["words"]), o["words"]


# ── `B1894`: the draft is checked without an error per edit ─────────────────

def test_an_unfinished_draft_is_checked_without_a_refused_request_and_a_loop_on_it_is_still_refused(box, live):
    """`PUT ?check=true` answered every unfinished draft with an HTTP 400 —
    nine console errors for a five-step build (the live-UX audit) — and an
    arrow was judged by the FIRST refusal alone, so a loop drawn while a step
    was unfinished was let through (the unfinished step was named first with
    and without it). The problems route answers 200 with every problem; an
    arrow is refused when it adds one."""
    o = _case(box, live, """
        const { r } = await room({ workflowId: 'w-wf' });
        fire(nodeEl(r, 'w').querySelector('.wb-port-add'), 'click'); await quiet();
        fire(kindButton(r, 'set'), 'click'); await quiet();
        fire(by(r, 'wb-panel-close'), 'click'); await quiet();
        fire(by(r, 'wb-panel-close'), 'click'); await quiet();
        const marked = r.querySelector('.wf-edit').querySelectorAll('.wb-node').filter((n) => n.dataset.problem === 'true').map((n) => n.dataset.itemId);
        const refusedBefore = wire.filter((c) => c.status >= 400).length;
        // A loop: "Pause" back to "Make it".
        fire(nodeEl(r, 'w').querySelector('.wb-node-connect'), 'click');
        const cbox = r.querySelector('.wb-connect');
        const to = cbox.querySelector('.wb-connect-to');
        to.value = 'a';
        fire(cbox.querySelector('.wb-connect-go'), 'click'); await quiet();
        const loopSaid = sayOf(r);
        const arrows = r.querySelector('.wf-edit').querySelectorAll('g').filter((g) => g.getAttribute('data-from') === 'w' && g.getAttribute('data-to') === 'a').length;
        out({ marked, refusedBefore, refused: wire.filter((c) => c.status >= 400).map((c) => c.method + ' ' + c.url),
              checks: calls('PUT', (u) => u.includes('check=true')).length,
              problems: calls('POST', (u) => u.endsWith('/problems')).length, loopSaid, arrows,
              button: by(r, 'wf-problems').textContent });
    """)
    assert len(o["marked"]) == 1, "the unfinished step is marked where it stands"
    assert o["button"] == "1 problem"
    assert o["refused"] == [], "no request is answered with an error for a draft that is not finished yet"
    assert o["checks"] == 0 and o["problems"] >= 1
    assert o["arrows"] == 0, "the loop is refused although another step is unfinished"
    assert "again" in o["loopSaid"] or "loop" in o["loopSaid"].lower(), o["loopSaid"]
