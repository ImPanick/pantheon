# SPDX-License-Identifier: AGPL-3.0-or-later
"""`audit-P1-tours`. A tour's tip and glowing outline must not linger over a
destination the tour no longer points at.

GPT-6.1's UX audit (2026-10-24): *"Open Library or Theme, close it, then open
another tool. The previous tour tip and glowing outline can remain over the new
destination. Multiple onboarding elements can overlap."*

Two parts, each run under node:

  * `window.cancelActiveTour` fires the running tour's abort hook AND sweeps the
    DOM — the halo, the tooltip, the highlight classes and any hint popover —
    so nothing it drew survives, whether or not the tour registered a hook;
  * `tourAutoplay.js` ends the active tour when its anchor modal closes, and
    when another tool opens over it.
"""

import re
import shutil
import subprocess
import textwrap
from pathlib import Path

import pytest

_REPO = Path(__file__).resolve().parent.parent
_SLASH = _REPO / "static" / "js" / "slashCommands.js"
_AUTOPLAY = _REPO / "static" / "js" / "tourAutoplay.js"
_HAS_NODE = shutil.which("node") is not None
pytestmark = pytest.mark.skipif(not _HAS_NODE, reason="node binary not on PATH")


def _cancel_fn() -> str:
    text = _SLASH.read_text(encoding="utf-8")
    m = re.search(r"window\.cancelActiveTour = function cancelActiveTour\(_why\) \{", text)
    assert m, "cancelActiveTour not found"
    start, i, depth = m.start(), m.end(), 1
    while i < len(text) and depth:
        if text[i] == "{":
            depth += 1
        elif text[i] == "}":
            depth -= 1
        i += 1
    return text[start:i]


def _run(js: str) -> str:
    out = subprocess.run(["node", "--input-type=module", "-e", js],
                         capture_output=True, text=True, timeout=30)
    assert out.returncode == 0, out.stderr
    return out.stdout.strip()


def test_cancel_fires_the_abort_hook_and_sweeps_the_dom():
    cancel = _cancel_fn()
    js = textwrap.dedent(f"""
    // A tiny DOM: a halo, a tooltip, a hint, a highlighted element.
    const removed = [];
    function node(cls, id) {{
      const classes = new Set((cls || '').split(' ').filter(Boolean));
      return {{ id: id || '', classList: {{
          contains: (c) => classes.has(c), add: (c) => classes.add(c), remove: (c) => classes.delete(c),
        }}, remove() {{ removed.push(id || [...classes][0]); }} }};
    }}
    const halo = node('tour-halo', 'halo');
    const tip = node('', 'tour-tooltip');
    const hint = node('tour-hint', 'hint');
    const hl = node('pantheon-highlight', 'hl');
    const body = node('tour-active', 'body');
    const byClass = {{ '.tour-halo': [halo], '.tour-hint': [hint],
                      '.pantheon-highlight, .pantheon-highlight-click': [hl] }};
    let aborted = null;
    globalThis.window = globalThis;
    globalThis.__tourAbort = (why) => {{ aborted = why; }};
    globalThis.document = {{
      querySelectorAll: (sel) => byClass[sel] || [],
      getElementById: (id) => (id === 'tour-tooltip' ? tip : null),
      body,
    }};
    {cancel}
    window.cancelActiveTour('anchor-closed');
    console.log(JSON.stringify({{ aborted, tipGone: removed.includes('tour-tooltip'),
      haloGone: removed.includes('halo'), hintGone: removed.includes('hint'),
      highlightCleared: !hl.classList.contains('pantheon-highlight'),
      bodyFlagCleared: !body.classList.contains('tour-active') }}));
    """)
    import json
    got = json.loads(_run(js))
    assert got == {"aborted": "anchor-closed", "tipGone": True, "haloGone": True,
                   "hintGone": True, "highlightCleared": True, "bodyFlagCleared": True}


def test_autoplay_cancels_on_anchor_close_and_on_another_modal_opening():
    src = _AUTOPLAY.read_text(encoding="utf-8")
    # The fire path records the anchor; the cancel observer ends the tour on
    # the anchor closing or another tool opening over it.
    assert "_activeTourModalId = id;" in src, "the tour's anchor is recorded"
    assert "cancelObserver" in src and "subtree: true" in src, "a document-wide visibility watcher"
    assert "anchor-closed" in src and "other-modal-opened" in src, "both cancel reasons"
    # It only cancels while a tour is actually running.
    cancel_block = src[src.index("const cancelObserver"):src.index("cancelObserver.observe")]
    assert "if (!_tourActive())" in cancel_block, "cancels only a running tour"
