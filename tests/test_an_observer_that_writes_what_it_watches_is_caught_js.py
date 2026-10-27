# SPDX-License-Identifier: AGPL-3.0-or-later
"""`B924` — an observer that writes inside what it watches is caught in node.

`B923` was a `MutationObserver` on `document.body` whose callback wrote into
its own subtree. `syncThreadToggleAll` assigned the button's `textContent`
every time — and assigning `textContent` replaces the text node even when the
words are the same, which is a childList mutation inside the thread, which
called the observer, which called `syncThreadToggleAll`. The loop ran in
microtasks, so the event loop never got a turn back: two tool cards froze the
tab so hard the browser could not close it. No test could have seen it,
because the node DOM shim the JS suite runs on had no `MutationObserver` and
delivered no records.

Now it does, opt-in (`installMutationObserver` in
`tests/test_tool_effect_surfaces_js.py`'s shim, next to `installHtmlParsing`):
records for the writes the standard says make records — a same-text
`textContent` and a `classList.add` of a token already there among them —
delivered a microtask at a time, with a **runaway check** that stops a burst
of deliveries with no macrotask between them and reports it, where a browser
would have frozen.

Driven on the real `agentThread.js` and on the real observer cut out of
`chat.js` (`_sweepThreads`, `_startThreadToolbars`), and, to show the harness
and the rule can go red, on `syncThreadToggleAll` as it stood before `B923`
(`3069a92b^`).

The audit of every observer under `static/js/` — 68, each with what it
watches and what its callback writes — is `B924`'s table on the row; it found
no other callback that writes, unguarded, what its own observer watches.
"""
import json
import re
import shutil
import subprocess
import textwrap
from pathlib import Path

import pytest

from tests.helpers.esc_stub import ui_default_stub
from tests.helpers.js_source import js_definition
from test_tool_effect_surfaces_js import _DOM, _copy_unstubbed_imports  # noqa: E402

ROOT = Path(__file__).resolve().parents[1]
JS = ROOT / "static" / "js"
AGENT_THREAD = JS / "agentThread.js"
CHAT = (JS / "chat.js").read_text(encoding="utf-8")

pytestmark = pytest.mark.skipif(not shutil.which("node"), reason="node binary not on PATH")

# `syncThreadToggleAll`'s body before `B923` (`git show 3069a92b^`): it wrote
# the label and the attribute whether or not they had changed.
PRE_B923_SYNC = """export function syncThreadToggleAll(thread) {
  const btn = thread && typeof thread.querySelector === 'function'
    ? thread.querySelector('.agent-thread-expand-all') : null;
  if (!btn) return null;
  const allOpen = threadIsAllOpen(thread);
  btn.textContent = allOpen ? COLLAPSE_ALL_LABEL : EXPAND_ALL_LABEL;
  btn.setAttribute('aria-expanded', allOpen ? 'true' : 'false');
  return btn;
}"""

_SHIM = """
import { installDom, installHtmlParsing, installMutationObserver } from './dom.js';
export const document = installDom();
installHtmlParsing();
export const mo = installMutationObserver({ maxRounds: 200 });
export const settle = () => new Promise((r) => setTimeout(r, 5));
"""


def _with_old_sync(source: str) -> str:
    start = source.index("export function syncThreadToggleAll(")
    end = start + len(js_definition(source, start))
    return source[:start] + PRE_B923_SYNC + source[end:]


@pytest.fixture(scope="module")
def sandbox(tmp_path_factory):
    d = tmp_path_factory.mktemp("b924")
    (d / "dom.js").write_text(_DOM, encoding="utf-8")
    (d / "shim.js").write_text(_SHIM, encoding="utf-8")
    (d / "ui.js").write_text(ui_default_stub(), encoding="utf-8")
    source = AGENT_THREAD.read_text(encoding="utf-8")
    (d / "agentThread.js").write_text(source, encoding="utf-8")
    (d / "agentThreadPreB923.js").write_text(_with_old_sync(source), encoding="utf-8")
    _copy_unstubbed_imports(d, AGENT_THREAD, {"ui.js"})
    return d


def _run(sandbox: Path, script: str) -> dict:
    case = sandbox / "case.mjs"
    case.write_text("import { document, mo, settle } from './shim.js';\n"
                    + textwrap.dedent(script), encoding="utf-8")
    proc = subprocess.run(["node", str(case)], cwd=sandbox, capture_output=True,
                          text=True, timeout=60)
    assert proc.returncode == 0, proc.stderr
    return json.loads([ln for ln in proc.stdout.splitlines() if ln.strip()][-1])


def _the_observer(*, guarded: bool = True) -> str:
    """`chat.js`'s thread-toolbar observer, as it ships — or with its own
    second guard (skip the toolbar's writes) taken out."""
    sweep = js_definition(CHAT, CHAT.index("const _sweepThreads = (root) => {"))
    start = js_definition(CHAT, CHAT.index("const _startThreadToolbars = () => {"))
    if not guarded:
        start, n = re.subn(r"\n\s*if \(m\.target && m\.target\.closest && "
                           r"m\.target\.closest\('\.agent-thread-toolbar'\)\) continue;", "", start)
        assert n == 1, "the observer's toolbar guard moved"
    return f"{sweep}\n{start}\n"


_THREAD = """
const thread = document.createElement('div'); thread.className = 'agent-thread';
document.body.appendChild(thread);
const card = (open) => { const n = document.createElement('div');
  n.className = 'agent-thread-node' + (open ? ' open' : ''); return n; };
"""


# ── the harness says what a browser says ─────────────────────────────────────

def test_the_shim_delivers_the_records_a_browser_does(sandbox):
    out = _run(sandbox, """
        const seen = [];
        const host = document.createElement('div'); document.body.appendChild(host);
        const btn = document.createElement('button'); host.appendChild(btn);
        btn.textContent = 'Expand all';
        await settle();
        const obs = new MutationObserver((rs) => rs.forEach((r) => seen.push(
          r.type + ':' + (r.attributeName || r.addedNodes.length + '/' + r.removedNodes.length))));
        obs.observe(host, { childList: true, subtree: true, attributes: true });
        btn.textContent = 'Expand all';          // the same words: still a record
        btn.classList.add('x'); btn.classList.add('x');   // the second is a record too
        btn.setAttribute('aria-expanded', 'false');
        await settle();
        obs.disconnect();
        btn.textContent = 'gone';
        await settle();
        console.log(JSON.stringify({ seen }));
    """)
    assert out["seen"] == ["childList:1/1", "attributes:class", "attributes:class",
                           "attributes:aria-expanded"]


def test_the_shim_reports_a_loop_a_browser_would_freeze_on(sandbox):
    out = _run(sandbox, """
        const box = document.createElement('div'); document.body.appendChild(box);
        new MutationObserver(() => { box.textContent = 'again'; })
          .observe(box, { childList: true });
        box.textContent = 'start';
        await settle();
        console.log(JSON.stringify({ runaway: mo.runaway() }));
    """)
    assert out["runaway"] and out["runaway"]["rounds"] >= 200


# ── `B923`, held by behaviour ────────────────────────────────────────────────

@pytest.mark.parametrize("module,writes", [
    ("agentThread.js", 0),           # as it ships: nothing changed, nothing written
    ("agentThreadPreB923.js", 2),    # before `B923`: the label and the attribute anyway
])
def test_a_thread_already_in_step_is_not_written_to(sandbox, module, writes):
    """The row's `Verify:` — this goes red when `B923`'s old
    `syncThreadToggleAll` is put back: the old one writes on every call."""
    out = _run(sandbox, f"""
        const m = await import('./{module}');
        {_THREAD}
        thread.appendChild(card(false)); thread.appendChild(card(false));
        m.ensureThreadToggleAll(thread);
        await settle();
        let records = 0;
        const watch = new MutationObserver((rs) => {{ records += rs.length; }});
        watch.observe(document.body, {{ childList: true, subtree: true, attributes: true }});
        m.syncThreadToggleAll(thread);
        await settle();
        console.log(JSON.stringify({{ records }}));
    """)
    assert out["records"] == writes


def test_the_shipped_observer_and_the_thread_settle(sandbox):
    """Cards arrive and are opened by hand; the control appears, reads true,
    and the observer goes quiet — no runaway."""
    out = _run(sandbox, f"""
        const {{ ensureThreadToggleAll, syncThreadToggleAll }} = await import('./agentThread.js');
        {_the_observer()}
        _startThreadToolbars();
        {_THREAD}
        thread.appendChild(card(false));
        await settle();
        const before = !!thread.querySelector('.agent-thread-toolbar');
        thread.appendChild(card(false));
        await settle();
        thread.querySelectorAll('.agent-thread-node').forEach((n) => n.classList.add('open'));
        syncThreadToggleAll(thread);
        await settle();
        const btn = thread.querySelector('.agent-thread-expand-all');
        console.log(JSON.stringify({{ before, label: btn && btn.textContent,
                                      runaway: mo.runaway() }}));
    """)
    assert out == {"before": False, "label": "Collapse all", "runaway": None}


def test_the_freeze_is_reproduced_when_both_guards_are_gone(sandbox):
    """`B923` itself, in node: the pre-`B923` writer under the observer with
    its toolbar guard removed. The harness reports what froze the tab."""
    out = _run(sandbox, f"""
        const {{ ensureThreadToggleAll }} = await import('./agentThreadPreB923.js');
        {_the_observer(guarded=False)}
        _startThreadToolbars();
        {_THREAD}
        thread.appendChild(card(false));
        thread.appendChild(card(false));
        await settle();
        console.log(JSON.stringify({{ runaway: mo.runaway() }}));
    """)
    assert out["runaway"] is not None


def test_either_guard_alone_keeps_the_tab_alive(sandbox):
    """Two guards, each sufficient: the shipped writer without the observer's
    skip, and the observer's skip over the old writer."""
    results = {}
    for module, guarded in (("agentThread.js", False), ("agentThreadPreB923.js", True)):
        out = _run(sandbox, f"""
            const {{ ensureThreadToggleAll }} = await import('./{module}');
            {_the_observer(guarded=guarded)}
            _startThreadToolbars();
            {_THREAD}
            thread.appendChild(card(false)); thread.appendChild(card(false));
            await settle();
            console.log(JSON.stringify({{ runaway: mo.runaway() }}));
        """)
        results[module] = out["runaway"]
    assert results == {"agentThread.js": None, "agentThreadPreB923.js": None}
