# SPDX-License-Identifier: AGPL-3.0-or-later
r"""`B1136` — an Integration (or MCP server) added through a step's door is
offered on that step without reopening the Workbench.

Measured by `integrate-e` (P22-24, dark 1400 and dark 390): the import's
"Open MCP & Integrations" opened the room, Miniflux was added there, and back
in Automations the step's Integration select offered only "Choose one…" until
the Workbench was reloaded. The step form read the palette fetched once when
the workflow opened (`workflowSource.loadPalette`).

Now the Automations room's `shown()` — which `workbench.js` `_showRoom` calls
when the room is shown again — reads the palette again, and the open step's
form offers what was added, in place: what was typed stays.

Driven end to end: the real room in node against the REAL server on a loopback
port (`tests/helpers/workflow_live.py`, wb-assist's world): the palette is the
real `GET /api/workflows/palette`. What a person does in the other room — add
an Integration, connect an MCP server — is the harness's stand-in store
changing (its Integration list, its chat server's tools), reached through one
test route, because that room is `settings.js`'s form and its own tests.
"""

from __future__ import annotations

import shutil
import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parent))

from test_tool_effect_surfaces_js import _run  # noqa: E402
from test_the_workbench_canvas_js import _SHIM as _CANVAS_SHIM  # noqa: E402
from test_a_workflow_file_js import POST, ToggleChat, _make  # noqa: E402
from helpers.workflow_live import LIVE_PREAMBLE, LiveServer, as_js, build_sandbox  # noqa: E402

pytestmark = pytest.mark.skipif(not shutil.which("node"), reason="node binary not on PATH")


# The shim's opt-in parser also gives `select.value` a browser's rules — a
# value no option has is not kept — which is what "the step's saved choice is
# chosen again once it is offered again" is about. Without it a select keeps
# whatever was assigned, and that case passed for the wrong reason (a mutation
# run found it).
_PARSED_SHIM = _CANVAS_SHIM + "\nimport { installHtmlParsing } from './dom.js';\ninstallHtmlParsing();\n"


@pytest.fixture(scope="module")
def box(tmp_path_factory):
    return build_sandbox(tmp_path_factory.mktemp("doorpalette"), _PARSED_SHIM)


@pytest.fixture()
def world(monkeypatch, tmp_path):
    """No Integration, the chat server not connected; a workflow whose HTTP
    step and MCP step were saved before an admin removed both."""
    from tests.helpers.assist_harness import build_world, miniflux

    chat = ToggleChat()
    w = build_world(monkeypatch, tmp_path, integrations=[miniflux()], chat=chat)
    w.chat = chat
    w.wid = _make(w, "Post the feed", {"v": 1, "nodes": [
        {"id": "fetch", "kind": "http", "label": "Fetch it",
         "config": {"integration": "intg-miniflux", "method": "GET", "path": "/v1/entries"}},
        {"id": "post", "kind": "mcp", "label": "Post it",
         "config": {"tool": POST, "args": {"channel": "#dev", "text": "{{ steps.fetch.text }}"}}}],
        "edges": [{"from": "fetch", "port": "success", "to": "post"}]})
    chat.on = False
    w.integrations.clear()

    # What the person does in the MCP & Integrations room the door opened.
    @w.app.post("/__test/added-in-the-room")
    async def _added(what: str):
        if what == "integration":
            w.integrations.append(miniflux())
        elif what == "mcp":
            chat.on = True
        return {"ok": True}

    w.server = LiveServer(w.app)
    try:
        yield w
    finally:
        w.server.close()


_HELPERS = (
    "const byField = (root, f) => root.querySelectorAll('[data-field]').find((n) => n.dataset.field === f) || null;\n"
    "const offered = (sel) => sel ? sel.querySelectorAll('option').map((o) => o.textContent) : null;\n"
    "const changed = (el, v) => { el.value = v; el.dispatchEvent({ type: 'change', target: el, stopPropagation() {}, preventDefault() {} }); };\n"
    "const doorWarn = (root) => root.querySelectorAll('.wf-sf-warn').find((x) => x.querySelector('.wf-sf-door')) || null;\n"
    "const addInRoom = (what) => net('/__test/added-in-the-room?what=' + what, { method: 'POST' });\n"
    "const palettes = () => calls('GET', (u) => u === '/api/workflows/palette').length;\n"
)


def _case(box, w, script, **consts):
    head = "".join(f"const {k} = {as_js(v)};\n" for k, v in consts.items())
    return _run(box, LIVE_PREAMBLE(w.server.base) + _HELPERS + head, script)


def test_an_integration_added_through_the_steps_door_is_offered_on_the_open_step(box, world):
    o = _case(box, world, """
        const { r, handle } = await room({ workflowId: WID });
        fire(nodeEl(r, 'fetch'), 'click'); await quiet();
        const before = offered(byField(r, 'integration'));
        const warn = doorWarn(r);
        // The kind's own line (the palette's `why` for HTTP) — a warning with no door.
        const kindLine = r.querySelectorAll('.wf-sf-warn').find((x) => !x.querySelector('.wf-sf-door')) || null;
        const kindBefore = kindLine ? [kindLine.textContent, !!kindLine.hidden] : null;
        typed(byField(r, 'path'), '/v1/entries?status=unread');      // typed before leaving
        fire(warn.querySelector('.wf-sf-door'), 'click'); await quiet();
        await addInRoom('integration');                               // Miniflux, added in the room
        const shownAgain = typeof handle.shown === 'function';
        if (shownAgain) { await handle.shown(); await quiet(); }      // workbench.js: _showRoom → handle.shown()
        const sel = byField(r, 'integration');
        const after = offered(sel);
        changed(sel, 'intg-miniflux');
        fire(by(r, 'wf-step-done'), 'click'); await quiet();
        out({ before, after, shownAgain, doors: doors.opened, warnHidden: warn.hidden, kindBefore,
              kindAfter: kindLine ? !!kindLine.hidden : null,
              path: byField(r, 'path') ? byField(r, 'path').value : null, palettes: palettes(), say: sayOf(r) });
    """, WID=world.wid)
    assert o["before"] == ["Choose one…"]
    assert o["doors"] == [{"room": "integrations"}]
    assert o["shownAgain"] is True
    assert o["after"] == ["Choose one…", "Miniflux (miniflux)"], o
    assert o["warnHidden"] is True, "it no longer says no integration is set up"
    # Measured in Chromium: the kind's own line still said none was switched on.
    assert o["kindBefore"] is not None and o["kindBefore"][1] is False
    assert "Integration" in o["kindBefore"][0]
    assert o["kindAfter"] is True
    assert o["palettes"] == 2, "read once when the workflow opened, again when the room was shown"
    assert o["say"] == "Changed “Fetch it”. Save the workflow to keep it."


def test_what_was_typed_stays_and_a_reopened_step_offers_it_too(box, world):
    """The form is not redrawn: the path typed before the door keeps its text.
    And a step opened after coming back reads the palette read on the way in."""
    o = _case(box, world, """
        const { r, handle } = await room({ workflowId: WID });
        fire(nodeEl(r, 'fetch'), 'click'); await quiet();
        typed(byField(r, 'path'), '/v1/entries?status=unread');
        await addInRoom('integration');
        await handle.shown(); await quiet();
        const kept = byField(r, 'path').value;
        fire(by(r, 'wf-step-cancel'), 'click'); await quiet();
        fire(nodeEl(r, 'post'), 'click'); await quiet();
        fire(by(r, 'wf-step-cancel'), 'click'); await quiet();
        fire(nodeEl(r, 'fetch'), 'click'); await quiet();
        out({ kept, reopened: offered(byField(r, 'integration')), chosen: byField(r, 'integration').value });
    """, WID=world.wid)
    assert o["kept"] == "/v1/entries?status=unread"
    assert o["reopened"] == ["Choose one…", "Miniflux (miniflux)"]
    # The step was saved naming this Integration's id; it is offered again, so
    # it is chosen again.
    assert o["chosen"] == "intg-miniflux"


def test_an_mcp_server_connected_through_the_door_offers_its_tool_on_the_open_step(box, world):
    o = _case(box, world, """
        const { r, handle } = await room({ workflowId: WID });
        fire(nodeEl(r, 'post'), 'click'); await quiet();
        const before = offered(byField(r, 'tool'));
        const warn = doorWarn(r);
        fire(warn.querySelector('.wf-sf-door'), 'click'); await quiet();
        await addInRoom('mcp');
        await handle.shown(); await quiet();
        out({ before, after: offered(byField(r, 'tool')), chosen: byField(r, 'tool').value,
              warnHidden: warn.hidden });
    """, WID=world.wid)
    assert o["before"] == ["Choose one…"]
    assert o["after"][0] == "Choose one…" and any(x.endswith("send_message") for x in o["after"]), o
    assert o["chosen"] == POST, "the tool the step was saved with is there again, and chosen"
    assert o["warnHidden"] is True


def test_shown_with_no_workflow_open_asks_nothing(box, world):
    o = _case(box, world, """
        const { r, handle } = await room();
        const before = palettes();
        await handle.shown(); await quiet();
        out({ before, after: palettes() });
    """)
    assert o["after"] == o["before"]
