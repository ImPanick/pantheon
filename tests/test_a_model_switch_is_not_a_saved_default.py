# SPDX-License-Identifier: AGPL-3.0-or-later
"""`B701` (p7trust) — a switch the model makes is not written into the
person's stored preferences as their own.

`handleUIControl` handled `ui_control toggle` and `set_mode` by moving the
control **and then** writing the stored toggles, so a per-turn flip the model
asked for became a standing setting — research and RAG are restored from those
keys on the next load. A preference changed by something other than the
person; and the person's yes to a self-switch is for that one switch, not a
standing grant (`D-2026-10-25-01`).

Now a toggle moves the live control and writes nothing. A mode switch is
written for the page — the composer sends with the stored mode — with the
person's own mode kept beside it, which the next load puts back
(`restorePersonsMode`) unless the person has since picked a mode themselves.

Driven under node: the REAL `chatStream.js` over the DOM shim, with a storage
module that keeps what is written (as `localStorage` would across a reload).
"""

import json
import shutil
from pathlib import Path

import pytest

from tests.helpers.motion_stub import motion_stub
from test_tool_effect_surfaces_js import _make_sandbox, _run  # noqa: E402

ROOT = Path(__file__).resolve().parents[1]
CHAT_STREAM = ROOT / "static" / "js" / "chatStream.js"
pytestmark = pytest.mark.skipif(not shutil.which("node"), reason="node binary not on PATH")

_SHIM = r"""
import { installDom, Node } from './dom.js';
export const document = installDom();
export { Node };
globalThis.addEventListener = () => {};
globalThis.dispatchEvent = () => true;
for (const id of ['research-toggle', 'rag-toggle', 'bash-toggle', 'web-toggle']) {
  const c = document.body.appendChild(document.createElement('input')); c.id = id; c.checked = false;
}
for (const id of ['bash-toggle-btn', 'web-toggle-btn', 'mode-agent-btn', 'mode-chat-btn']) {
  const b = document.body.appendChild(document.createElement('button')); b.id = id;
}
"""

_STUBS = {
    # What is written survives "a reload": a fresh `node` run seeded with it.
    "storage.js": """
const mem = globalThis.__stored || {};
globalThis.__stored = mem;
export default {
  KEYS: { TOGGLES: 'toggles' },
  getJSON: (k, d) => (k in mem ? JSON.parse(JSON.stringify(mem[k])) : d),
  setJSON: (k, v) => { mem[k] = JSON.parse(JSON.stringify(v)); },
  remove: (k) => { delete mem[k]; },
};
""",
    "ui.js": "export default { esc: (s) => String(s), showToast: () => {}, el: (id) => document.getElementById(id) };\n",
    "theme.js": "export default {};\n",
    "markdown.js": "export default {};\n",
    "sessions.js": "export default { getCurrentSessionId: () => '' };\n",
    "document.js": "export default {};\n",
    "motion.js": motion_stub(),
}


@pytest.fixture(scope="module")
def sandbox(tmp_path_factory):
    return _make_sandbox(tmp_path_factory.mktemp("modelswitch"), CHAT_STREAM, _SHIM, _STUBS)


def _page(sandbox, stored, script):
    return _run(sandbox, "globalThis.__stored = %s;\nimport { document } from './shim.js';\n" % json.dumps(stored),
                "const cs = await import('./chatStream.js');\n" + script)


@pytest.mark.parametrize("name, box", [("bash", "bash-toggle"), ("research", "research-toggle"),
                                       ("web", "web-toggle")])
def test_a_toggle_the_model_flips_moves_the_control_and_writes_nothing(sandbox, name, box):
    stored = {"toggles": {"mode": "agent", "research": False, "bash_agent": False}}
    out = _page(sandbox, stored, """
        cs.handleUIControl({ ui_event: 'toggle', toggle_name: %s, state: true });
        console.log(JSON.stringify({ live: document.getElementById(%s).checked, stored: globalThis.__stored }));
    """ % (json.dumps(name), json.dumps(box)))
    assert out["live"] is True, "the control did not move for this turn"
    assert out["stored"] == stored, "the person's saved toggles were written"


def test_a_mode_the_model_sets_is_the_pages_and_the_next_load_puts_the_persons_back(sandbox):
    out = _page(sandbox, {"toggles": {"mode": "chat"}}, """
        cs.handleUIControl({ ui_event: 'set_mode', mode: 'agent' });
        console.log(JSON.stringify({ stored: globalThis.__stored,
          agentActive: document.getElementById('mode-agent-btn').classList.contains('active') }));
    """)
    assert out["agentActive"] is True
    # This page sends in Agent mode (the composer reads `mode`) …
    assert out["stored"]["toggles"]["mode"] == "agent"
    # … and the reload is a new page, seeded with what was stored.
    after = _page(sandbox, out["stored"], "console.log(JSON.stringify(globalThis.__stored));")
    assert after == {"toggles": {"mode": "chat"}}


def test_two_switches_keep_the_persons_own_mode_not_the_models_first(sandbox):
    out = _page(sandbox, {"toggles": {"mode": "chat"}}, """
        cs.handleUIControl({ ui_event: 'set_mode', mode: 'agent' });
        cs.handleUIControl({ ui_event: 'set_mode', mode: 'chat' });
        cs.handleUIControl({ ui_event: 'set_mode', mode: 'agent' });
        console.log(JSON.stringify(globalThis.__stored));
    """)
    after = _page(sandbox, out, "console.log(JSON.stringify(globalThis.__stored));")
    assert after == {"toggles": {"mode": "chat"}}


def test_a_mode_the_person_picks_afterwards_is_theirs(sandbox):
    """A click of their own on a mode button drops the marker, and app.js's
    `setMode` stores their choice; the next load keeps it."""
    out = _page(sandbox, {"toggles": {"mode": "chat"}}, """
        cs.handleUIControl({ ui_event: 'set_mode', mode: 'agent' });
        const btn = document.getElementById('mode-agent-btn');
        btn.closest = () => btn;
        document.dispatchEvent({ type: 'click', isTrusted: true, target: btn });
        console.log(JSON.stringify(globalThis.__stored));
    """)
    assert out == {"toggles": {"mode": "agent"}}
    after = _page(sandbox, out, "console.log(JSON.stringify(globalThis.__stored));")
    assert after == {"toggles": {"mode": "agent"}}


def test_a_mode_changed_since_by_something_else_is_left_alone(sandbox):
    """Nobody mode, Compare or a slash command set the mode after the model
    did: the next load does not undo theirs."""
    after = _page(sandbox, {"toggles": {"mode": "chat", "mode_set_by_assistant": {"own": "agent", "set": "agent"}}},
                  "console.log(JSON.stringify(globalThis.__stored));")
    assert after == {"toggles": {"mode": "chat"}}
