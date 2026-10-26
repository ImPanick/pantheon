# SPDX-License-Identifier: AGPL-3.0-or-later
"""`B733` — `_initScrollDismiss` said "Retry once" and retried forever.

`static/js/ui.js` binds a scroll listener to `#chat-history` (it closes
floating dropdowns and context popups so they do not drift), and when the
element was absent it called `setTimeout(_initScrollDismiss, 500)` —
recursively, with no cap, under a comment reading *"Retry once if element
doesn't exist yet."* On the shipped page the element is in the markup and the
first call binds; on any page that loads `ui.js` without a chat history (every
test sandbox — `tests/test_empty_states_js.py` adds a `#chat-history` to its
shim for exactly this reason) it was a live 500 ms timer forever.

Driven: the real `ui.js` is imported under node in the empty-state sandbox
(its stubs and shim, imported — minus the `#chat-history` that shim adds), with
`setTimeout` recording the 500 ms timers instead of waiting for them, and each
one run by hand: the module retries once, then stops. A page that has the
element binds on the first call and arms nothing.
"""
import json
import shutil

import pytest

from test_tool_effect_surfaces_js import _make_sandbox, _run  # noqa: E402
from test_empty_states_js import UI_JS, _SHIM, _STUBS  # noqa: E402

pytestmark = pytest.mark.skipif(not shutil.which("node"), reason="node binary not on PATH")

_CHAT_HISTORY = "document.body.appendChild(new Node('div')).setAttribute('id', 'chat-history');"

# Installed before `ui.js` is imported, so its load-time call is the first one
# recorded. Only 500 ms timers are held; everything else runs as it would.
_PREAMBLE = """
import { document, Node } from './shim.js';
const _realSetTimeout = globalThis.setTimeout;
const armed = [];
globalThis.setTimeout = (fn, ms, ...rest) => {
  if (ms === 500) { armed.push(fn); return armed.length; }
  return _realSetTimeout(fn, ms, ...rest);
};
"""


def _sandbox(tmp_path_factory, with_history: bool):
    assert _CHAT_HISTORY in _SHIM, "the empty-state shim moved its #chat-history"
    shim = _SHIM if with_history else _SHIM.replace(_CHAT_HISTORY, "")
    return _make_sandbox(tmp_path_factory.mktemp("b733"), UI_JS, shim, _STUBS)


_DRIVE = """
await import('./ui.js');
const atLoad = armed.length;
let ran = 0;
while (armed.length && ran < 20) { armed.shift()(); ran += 1; }
console.log(JSON.stringify({ atLoad, ran, stillArmed: armed.length }));
"""


def test_without_a_chat_history_it_retries_once_and_stops(tmp_path_factory):
    """The row's `Verify:` — the retry stops after the number of attempts its
    comment claims."""
    out = _run(_sandbox(tmp_path_factory, False), _PREAMBLE, _DRIVE)
    assert out["atLoad"] == 1, out
    assert out["ran"] == 1, f"retried {out['ran']} times (capped at 20 by this test)"
    assert out["stillArmed"] == 0, out


def test_with_a_chat_history_it_binds_at_once_and_arms_nothing(tmp_path_factory):
    out = _run(_sandbox(tmp_path_factory, True), _PREAMBLE, _DRIVE)
    assert out == {"atLoad": 0, "ran": 0, "stillArmed": 0}
