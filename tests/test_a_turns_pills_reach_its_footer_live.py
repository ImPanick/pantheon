# SPDX-License-Identifier: AGPL-3.0-or-later
"""`B920` — the footer pills a turn's first bubble holds reach the footer, live.

The footer under an assistant reply can carry four pills: the memories that
were recalled (`memories_used`), the skills the agent was shown
(`skills_injected`, `P4-16`), the promotion to agent mode (`auto_escalated`,
`P4-18`) and the fallback chain (`fallback`, `P4-05`). `createMsgFooter`
(`static/js/chatRenderer.js`) draws them from properties of the element it is
handed. The live stream keeps them on the turn's first bubble (`holder`),
because they arrive before the reply does, and makes the footer on its last:
`_metricsTargetForTurn()` at the `metrics` event — the last visible step's
bubble, or the last tool thread on a turn that only ran tools — and
`footerTarget` at the end. Those are the first bubble only when the reply is one
bubble, so an agent turn that went round a tool drew none of its pills live.
A reload drew them, because the history renderer puts the saved ones on the
turn's last bubble.

Driven, not read (`Law 20`): the real `createMsgFooter` and `displayMetrics`
under node, fed by the live stream's own code cut out of `handleChatSubmit` —
the `metrics` arm with `_metricsTargetForTurn`, the end-of-stream footer, and
the two places a stopped reply is given one — and the history renderer's own
`addMessage` for the reload.
"""

import json
import shutil
import textwrap
from pathlib import Path

import pytest

from tests.helpers.esc_stub import ui_default_stub  # B874
from tests.helpers.js_source import js_binding, js_definition  # B876
from tests.helpers.source_text import blank  # B290
from test_tool_effect_surfaces_js import _CARD_SHIM, _CARD_STUBS, _make_sandbox, _run  # noqa: E402

ROOT = Path(__file__).resolve().parents[1]
CHAT_JS = ROOT / "static" / "js" / "chat.js"
CHAT_RENDERER = ROOT / "static" / "js" / "chatRenderer.js"

pytestmark = pytest.mark.skipif(not shutil.which("node"), reason="node binary not on PATH")

_STUBS = dict(_CARD_STUBS, **{
    # `B874`: the shipped `esc`.
    "ui.js": ui_default_stub(
        "showToast: () => {}, copyToClipboard: () => {},\n"
        "showError: (m) => { (globalThis.errors = globalThis.errors || []).push(String(m)); },\n"
        "el: (id) => document.getElementById(id), debounce: (f) => f,\n"
        "autoResize: () => {}, scrollHistory: () => {}, formatBytes: (n) => String(n),"),
})


@pytest.fixture(scope="module")
def sandbox(tmp_path_factory):
    return _make_sandbox(tmp_path_factory.mktemp("turnpills"), CHAT_RENDERER, _CARD_SHIM, _STUBS)


# ── the live handler, cut into the pieces that make a footer ────────────────


def _handler() -> str:
    """Comment-blanked `handleChatSubmit`: the live stream's arms are cut from
    here rather than the whole file, because `resumeStream` has look-alike arms."""
    code = blank(CHAT_JS)
    start = code.index("export async function handleChatSubmit(")
    return code[start:start + len(js_definition(CHAT_JS.read_text(encoding="utf-8"), start))]


def _between(opening: str, closing: str, *, keep_opening: bool = False) -> str:
    code = _handler()
    assert code.count(opening) == 1, f"{opening!r} is no longer a unique anchor in handleChatSubmit"
    at = code.index(opening)
    start = at if keep_opening else at + len(opening)
    return code[start:code.index(closing, start)]


def _module_helper() -> str:
    """`_withTurnPills` and its key list, at module scope in `chat.js`, or ''
    on a tree without them — so the cases fail on what they assert."""
    src = CHAT_JS.read_text(encoding="utf-8")
    code = blank(CHAT_JS)
    if "function _withTurnPills(" not in code:
        return ""
    return (js_binding(src, "_TURN_PILL_KEYS") + ";\n"
            + js_definition(src, code.index("function _withTurnPills(")))


def _metrics_target() -> str:
    code = _handler()
    return js_definition(code, code.index("function _metricsTargetForTurn("))


_TURN = r"""
import { document, Node, history } from './shim.js';
const chatRenderer = await import('./chatRenderer.js');
const { displayMetrics, createMsgFooter } = chatRenderer;
// A browser element knows whether it is on the page; the base shim does not,
// and `_metricsTargetForTurn` asks it of the turn's last thread.
Object.defineProperty(Node.prototype, 'isConnected', { configurable: true, get() {
  let n = this; while (n.parentNode) n = n.parentNode; return n.tagName === '#DOCUMENT';
} });
__HELPER__

// A turn that went round a tool: the first bubble wrote nothing and is hidden,
// the step's thread follows, and the answer is in step 2's bubble — or, on a
// tool-only turn, step 2 wrote nothing either.
const bubble = (cls, text) => {
  const n = history.appendChild(new Node('div'));
  n.className = cls;
  const body = n.appendChild(new Node('div'));
  body.className = 'body';
  if (text) body.textContent = text; else n.style.display = 'none';
  return n;
};
const toolOnly = __TOOL_ONLY__;
const holder = bubble('msg msg-ai', '');
const thread = history.appendChild(new Node('div'));
thread.className = 'agent-thread';
const second = bubble('msg msg-ai msg-continuation', toolOnly ? '' : 'Here it is.');
holder._memoriesUsed = [{ type: 'recalled', text: 'Prefers short answers', engine: 'vector' }];
holder._skillsInjected = [{ name: 'tidy-logs', category: 'ops' }];
holder._autoEscalated = { reasons: ['it asked for a file'], withheld: [] };
holder._fallbackChain = { selected_model: 'a', answered_by: 'b', failures: [{ model: 'a', status: 502 }] };
let roundHolder = second;
let lastToolThread = thread;
let currentHolder = holder;
const metricsData = { response_time: 3.2, tokens_per_second: 41, model: 'm' };

function pills(node) {
  const footers = node ? node.querySelectorAll('.msg-footer') : [];
  const f = footers[footers.length - 1];
  if (!f) return null;
  return ['memory-used-pill', 'skills-used-pill', 'promoted-pill', 'fallback-chain-pill']
    .filter((cls) => f.querySelector('.' + cls));
}
"""

_ALL = ["memory-used-pill", "skills-used-pill", "promoted-pill", "fallback-chain-pill"]


def _run_turn(sandbox, body: str, *, tool_only: bool = False) -> dict:
    script = (_TURN.replace("__HELPER__", _module_helper())
              .replace("__TOOL_ONLY__", "true" if tool_only else "false")
              + textwrap.dedent(body))
    return _run(sandbox, "", script)


@pytest.mark.parametrize("tool_only", [False, True], ids=["answer-in-a-later-step", "tool-only"])
def test_the_metrics_event_draws_the_pills_on_the_footer_it_makes(sandbox, tool_only):
    """The `metrics` arm, as the live stream runs it: the footer goes on
    `_metricsTargetForTurn()`, and it must carry the turn's pills."""
    arm = _between("} else if (json.type === 'metrics') {", "} else if (json.type === 'message_saved') {")
    out = _run_turn(sandbox, """
        const json = { type: 'metrics', data: metricsData };
        let metrics = null;
        const streamRunId = '', _isBg = false, modelName = 'm', streamSessionId = 's1';
        const _backgroundStreams = new Map();
        const _metricsCostRecordId = () => 'rec';
        const applyModelMetricsState = () => null;
        const refreshChatContextHeader = () => {};
        %s
        for (const _ of [0]) { %s }
        const target = toolOnly ? thread : second;
        console.log(JSON.stringify({ onTarget: pills(target), onHolder: pills(holder) }));
    """ % (_metrics_target(), arm), tool_only=tool_only)
    assert out["onTarget"] == _ALL, f"the footer the metrics event made is missing pills: {out}"


def test_the_footer_made_at_the_end_of_the_stream_carries_them(sandbox):
    """The end-of-stream footer on `footerTarget` — the last visible step's
    bubble, here the second — when the `metrics` event made none."""
    block = _between("const footerTarget =", "if (_generatedImagesForTurn.length", keep_opening=True)
    out = _run_turn(sandbox, """
        %s
        console.log(JSON.stringify({ target: footerTarget === second, pills: pills(second) }));
    """ % block)
    assert out["target"], "the end-of-stream footer went somewhere else"
    assert out["pills"] == _ALL, out


@pytest.mark.parametrize("opening, holder_name", [
    ("if (!_stoppedViewHolder.querySelector('.msg-footer')) {", "_stoppedViewHolder"),
    ("if (!_catchViewHolder.querySelector('.msg-footer')) {", "_catchViewHolder"),
], ids=["stopped", "interrupted"])
def test_a_stopped_reply_gets_the_pills_with_its_footer(sandbox, opening, holder_name):
    """Stopped by the person, or cut off: the footer goes on the bubble the
    reply ended in, which is the second step's here."""
    block = _between(opening, "uiModule.scrollHistory();", keep_opening=True)
    out = _run_turn(sandbox, """
        const %s = second;
        const stoppedContent = 'Here it is.';
        %s
        console.log(JSON.stringify({ pills: pills(second) }));
    """ % (holder_name, block))
    assert out["pills"] == _ALL, out


def test_a_reload_draws_them_on_the_same_bubble(sandbox):
    """The other half of the row's `Verify`: after a reload the saved pills are
    on the turn's last bubble — where the live footer now has them too."""
    out = _run(sandbox, "", """
        import { document, history } from './shim.js';
        const { addMessage } = await import('./chatRenderer.js');
        addMessage('assistant', 'Here it is.', 'm', {
          round_texts: ['', 'Here it is.'],
          tool_events: [{ round: 1, tool: 'bash', command: 'ls', output: 'ok', exit_code: 0 }],
          memories_used: [{ type: 'recalled', text: 'Prefers short answers', engine: 'vector' }],
          skills_injected: [{ name: 'tidy-logs', category: 'ops' }],
          response_time: 3.2,
        });
        const last = history.children[history.children.length - 1];
        const f = last.querySelector('.msg-footer');
        console.log(JSON.stringify({
          text: last.querySelector('.body').textContent,
          pills: ['memory-used-pill', 'skills-used-pill'].filter((c) => f && f.querySelector('.' + c)),
        }));
    """)
    assert out == {"text": "Here it is.", "pills": ["memory-used-pill", "skills-used-pill"]}, out


@pytest.mark.parametrize("key, value, pill", [
    ("skills_injected", [{"name": "tidy-logs", "category": "ops"}], "skills-used-pill"),
    ("fallback_chain", {"selected_model": "a", "answered_by": "b",
                        "failures": [{"model": "a", "status": 502}]}, "fallback-chain-pill"),
    ("auto_escalated", {"reasons": ["it asked for a file"], "withheld": []}, "promoted-pill"),
], ids=["skills", "fallback", "promotion"])
def test_a_saved_reply_carrying_the_pill_is_drawn_on_reload(sandbox, key, value, pill):
    """`createMsgFooter` wrote these three labels through an `esc` its module
    never bound, so each threw `ReferenceError: esc is not defined`: a saved
    reply carrying one was not drawn at all (one bubble) or lost its footer
    (several), with a "Failed to add message" toast either way."""
    out = _run(sandbox, "", """
        import { document, history } from './shim.js';
        const { addMessage } = await import('./chatRenderer.js');
        const extra = { %s: %s, response_time: 1 };
        const drawn = (meta) => {
          history.childNodes = []; globalThis.errors = [];
          addMessage('assistant', 'The answer.', 'm', Object.assign({}, meta, extra));
          const last = history.children[history.children.length - 1];
          const f = last && last.querySelector('.msg-footer');
          return { bubbles: history.children.filter((n) => n.classList.contains('msg')).length,
                   pill: !!(f && f.querySelector('.%s')), errors: globalThis.errors };
        };
        console.log(JSON.stringify({
          one: drawn({}),
          steps: drawn({ round_texts: ['', 'The answer.'],
                         tool_events: [{ round: 1, tool: 'bash', command: 'ls', output: 'ok', exit_code: 0 }] }),
        }));
    """ % (key, json.dumps(value), pill))
    assert out["one"] == {"bubbles": 1, "pill": True, "errors": []}, out
    assert out["steps"] == {"bubbles": 1, "pill": True, "errors": []}, out


def test_a_one_bubble_reply_is_unchanged(sandbox):
    """The helper hands nothing to the first bubble itself, and a turn whose
    reply is that bubble draws its pills there as it always did."""
    out = _run_turn(sandbox, """
        second.remove();
        holder.style.display = '';
        holder.querySelector('.body').textContent = 'One bubble.';
        roundHolder = holder;
        lastToolThread = null;
        %s
        displayMetrics(_metricsTargetForTurn(), metricsData);
        console.log(JSON.stringify({ pills: pills(holder) }));
    """ % _metrics_target())
    assert out["pills"] == _ALL, out
