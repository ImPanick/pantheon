# SPDX-License-Identifier: AGPL-3.0-or-later
"""`B1033` — a turn whose context was trimmed says so after a reload, and in a
compare pane.

`P4-13` saves `context_trimmed` and its four `context_*_trim` figures on the
turn's record (`_apply_shaping_metrics`); the live stream said *Context trimmed
for this model (9/12 messages sent)* as a toast, and nothing under
`static/js` read the saved keys, and `compare/stream.js` had no arm for the
event — `B953`/`B954`'s split, for the other shaping step. Now one sentence
builder (`trimNoticeText`) says it for the toast and the line; `addMessage`
draws the line from the record (`trimFromRecord`), above a chat reply and
before an agent turn's first step; a pane draws it from its stream.

Driven (`Law 20`): a chat turn through `/api/chat_stream` and the real save;
the toast's words from the real builder over the frame the route sent; the
saved record drawn by the real `addMessage`; the real `streamToPane`.
"""

import json
import shutil

import pytest

from test_a_chat_turns_compaction_survives_a_reload import _STUBS, _chat_turn  # noqa: E402
from test_a_compare_pane_counts_its_steps import _PREAMBLE as _STEP_PREAMBLE  # noqa: E402
from test_a_compare_pane_draws_the_card_the_chat_draws import sandbox as pane_sandbox  # noqa: E402,F401
from test_tool_effect_surfaces_js import _CARD_SHIM, _make_sandbox, _run  # noqa: E402
from test_a_chat_turns_compaction_survives_a_reload import CHAT_RENDERER  # noqa: E402

node_only = pytest.mark.skipif(not shutil.which("node"), reason="node binary not on PATH")

TRIMMED = {
    "context_trimmed": True,
    "context_messages_before_trim": 12,
    "context_messages_after_trim": 9,
    "context_tokens_before_trim": 9000,
    "context_tokens_after_trim": 4000,
}
SAID = "Context trimmed for this model (9/12 messages sent)"


@pytest.fixture(scope="module")
def sandbox(tmp_path_factory):
    if not shutil.which("node"):
        pytest.skip("node binary not on PATH")
    return _make_sandbox(tmp_path_factory.mktemp("chattrim"), CHAT_RENDERER, _CARD_SHIM, _STUBS)


_PAGE = r"""
import { document, history } from './shim.js';
const { addMessage } = await import('./chatRenderer.js');
const { trimNoticeText } = await import('./agentStops.js');
const text = (n) => n.textContent.replace(/\s+/g, ' ').trim();
function shape() {
  return history.children.map((n) => {
    const cls = String(n.className || '');
    if (cls.includes('context-trimmed-note')) return 'trim:' + text(n);
    if (cls.includes('context-compacted-note')) return 'compact:' + text(n);
    if (cls.includes('msg')) return 'msg:' + text(n.querySelector('.body'));
    return cls;
  });
}
"""


@node_only
def test_a_trimmed_chat_turn_says_so_after_a_reload(monkeypatch, sandbox):
    """The row's `Verify:`. The toast's words, live, from the frame the route
    sent; the line above the reloaded reply, from the record it saved."""
    frames, saved = _chat_turn(monkeypatch, TRIMMED)
    [trimmed] = [f for f in frames if f.get("type") == "context_trimmed"]
    assert len(saved) == 1 and saved[0]["context_trimmed"] is True
    out = _run(sandbox, "", _PAGE + """
        const toast = trimNoticeText(%s);
        addMessage('assistant', 'Here you are.', 'selected-model', %s);
        console.log(JSON.stringify({ toast, shape: shape() }));
    """ % (json.dumps(trimmed), json.dumps(saved[0])))
    assert out["toast"] == SAID
    assert out["shape"] == ["trim:" + SAID, "msg:Here you are."], out["shape"]


@node_only
def test_a_turn_that_was_compacted_and_trimmed_says_both_in_order(sandbox):
    out = _run(sandbox, "", _PAGE + """
        addMessage('assistant', 'Hello.', 'm', %s);
        console.log(JSON.stringify({ shape: shape() }));
    """ % json.dumps(dict(TRIMMED, context_compacted=True, context_messages_before_compact=40,
                          context_messages_after_compact=12)))
    assert out["shape"] == ["compact:Context compacted — older messages summarized (12/40 messages kept)",
                            "trim:" + SAID, "msg:Hello."]


@node_only
def test_an_agent_turn_says_it_before_its_first_step(sandbox):
    out = _run(sandbox, "", _PAGE + """
        addMessage('assistant', 'Done.', 'm', %s);
        console.log(JSON.stringify({ shape: shape() }));
    """ % json.dumps(dict(TRIMMED, round_texts=["Looking.", "Done."],
                          tool_events=[{"round": 1, "tool": "bash", "command": "ls", "output": "a"}])))
    lines = [s for s in out["shape"] if s.startswith(("trim:", "msg:"))]
    assert lines[0] == "trim:" + SAID and lines.count("trim:" + SAID) == 1, out["shape"]


@node_only
def test_a_turn_trimmed_with_nothing_measured_says_the_bare_sentence(sandbox):
    out = _run(sandbox, "", _PAGE + """
        addMessage('assistant', 'Hi.', 'm', { context_trimmed: true });
        addMessage('assistant', 'Again.', 'm', { context_trimmed: false });
        console.log(JSON.stringify({ shape: shape() }));
    """)
    assert out["shape"] == ["trim:Context trimmed for this model", "msg:Hi.", "msg:Again."]


_PANE = _STEP_PREAMBLE + r"""
function paneMessage() {
  const part = (n) => {
    const cls = n._classes();
    if (cls.includes('context-trimmed-note')) return 'line: ' + words(n);
    if (cls.includes('compare-text-content')) return 'text: ' + words(n);
    return n.className;
  };
  return ai.children.filter((n) => !n._classes().includes('role') && !n._classes().includes('msg-footer'))
    .map((n) => (n._classes().includes('body') ? { body: n.children.map(part) } : part(n)));
}
"""


@node_only
def test_a_trimmed_compare_pane_says_so(pane_sandbox):  # noqa: F811
    frame = {"type": "context_trimmed", "data": {"context_length": 8192, "messages_before": 12,
                                                 "messages_after": 9, "tokens_before": 9000,
                                                 "tokens_after": 4000}}
    out = _run(pane_sandbox, _PANE, """
        await run([%s, { delta: 'Here you are.' }, '[DONE]']);
        console.log(JSON.stringify({ pane: paneMessage() }));
    """ % json.dumps(frame))
    assert out["pane"] == ["line: " + SAID, {"body": ["text: Here you are."]}], out["pane"]
