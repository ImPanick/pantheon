# SPDX-License-Identifier: AGPL-3.0-or-later
"""`B1334` (fx6-export) — the fallback transcript keeps a tool's whole output and
the turn's reasoning.

`_serializeChatTranscript` (`static/app.js`) is the transcript *Copy Chat* and
the Word export fall back to when the server's whole-chat export
(`/api/session/{id}/export`, `B1320`) cannot be reached. It cut each tool's
output at 2,000 characters with `…` and read no thinking fold at all — so what
somebody pasted from it had lost the end of every long output and all of the
model's reasoning. Now the output is written whole (the clipboard is not a
context window), and each reply's folds are read — one `[THINKING step i]` per
step when the turn's fold holds its steps (`.thinking-round`), `[THINKING]` for
a fold of one — as the server's own `txt` export writes them; a `<think>` copy
in the raw text is not written a second time.

Driven (`Law 20`): the real function, cut out of `app.js` and run in the export
menu's sandbox (`tests/test_the_export_menu_asks_the_server_js.py`), over a
page with a 12,000-character tool output and a reply carrying a two-step fold.
"""

import json
import subprocess

import pytest

from test_the_export_menu_asks_the_server_js import _PRE, _TURN, _cut, dom_dir  # noqa: F401

# The shared shim matches one selector at a time; the function asks for one
# descendant (`.agent-tool-output pre`), as a browser answers it.
_DESCENDANT = r"""
import { Node as _N } from './dom.js';
const _qsa = _N.prototype.querySelectorAll;
_N.prototype.querySelectorAll = function (sel) {
  const steps = String(sel).trim().split(/\s+/);
  if (steps.length < 2 || String(sel).includes(',')) return _qsa.call(this, sel);
  let found = [this];
  for (const step of steps) found = [...new Set(found.flatMap((n) => _qsa.call(n, step)))];
  return found;
};
_N.prototype.querySelector = function (sel) { return this.querySelectorAll(sel)[0] || null; };
"""


def _run(dom_dir, script: str) -> dict:  # noqa: F811
    body = _PRE.replace("__SOURCE__", _cut("function _serializeChatTranscript(")) + _DESCENDANT + _TURN + script
    out = subprocess.run(["node", "--input-type=module"], input=body, capture_output=True,
                         text=True, cwd=dom_dir, timeout=30)
    assert out.returncode == 0, out.stderr
    return json.loads(out.stdout.strip().splitlines()[-1])


_PAGE = r"""
const el = (tag, cls, text) => { const n = document.createElement(tag); if (cls) n.className = cls; if (text != null) n.textContent = text; return n; };
box.appendChild(mk('msg msg-user', 'Read the log', ''));
// The tool's rows, with an output of 12,000 characters ending in a marker.
const thread = box.appendChild(el('div', 'agent-thread'));
const node = thread.appendChild(el('div', 'agent-thread-node'));
node.appendChild(el('div', 'agent-thread-tool', 'Read file'));
node.appendChild(el('div', 'agent-thread-cmd', 'app.log'));
const out = node.appendChild(el('div', 'agent-tool-output'));
const LONG = 'x'.repeat(11990) + 'END-OF-LOG';
out.appendChild(el('pre', '', LONG));
// The reply: its raw text carries its reasoning as `<think>`, and its fold
// holds the turn's two steps.
const reply = box.appendChild(mk('msg msg-ai', '<think>Looking first.</think>The log ends cleanly.', 'scripted'));
const fold = reply.querySelector('.body').appendChild(el('div', 'thinking-section'));
const inner = fold.appendChild(el('div', 'thinking-content')).appendChild(el('div', 'thinking-content-inner'));
inner.appendChild(el('div', 'thinking-round', 'Looking first.'));
inner.appendChild(el('div', 'thinking-round', 'Then reading to the end.'));
"""


def test_a_long_tool_output_is_written_whole(dom_dir):  # noqa: F811
    out = _run(dom_dir, _PAGE + "console.log(JSON.stringify({ t: _serializeChatTranscript() }));")
    t = out["t"]
    assert "x" * 11990 + "END-OF-LOG" in t, "the output was cut"
    assert "…" not in t


def test_the_turns_reasoning_is_in_it_once_per_step(dom_dir):  # noqa: F811
    out = _run(dom_dir, _PAGE + "console.log(JSON.stringify({ t: _serializeChatTranscript() }));")
    t = out["t"]
    assert "scripted: [THINKING step 1]\nLooking first.\n\n[THINKING step 2]\nThen reading to the end.\n\nThe log ends cleanly." in t
    assert t.count("Looking first.") == 1, "the <think> copy was written as well as the fold"
    assert "<think>" not in t


def test_a_fold_of_one_is_plain_thinking_and_a_reply_without_one_is_as_before(dom_dir):  # noqa: F811
    out = _run(dom_dir, r"""
        const el = (tag, cls, text) => { const n = document.createElement(tag); if (cls) n.className = cls; if (text != null) n.textContent = text; return n; };
        const one = box.appendChild(mk('msg msg-ai', 'Short answer.', 'm'));
        one.querySelector('.body').appendChild(el('div', 'thinking-section'))
          .appendChild(el('div', 'thinking-content-inner', 'A thought.'));
        box.appendChild(mk('msg msg-ai', 'No fold here.', 'm'));
        console.log(JSON.stringify({ t: _serializeChatTranscript() }));
    """)
    assert out["t"] == "m: [THINKING]\nA thought.\n\nShort answer.\n\nm: No fold here."
