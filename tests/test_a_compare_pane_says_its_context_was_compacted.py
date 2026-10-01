# SPDX-License-Identifier: AGPL-3.0-or-later
"""`B954` — a compare pane says when its model's history was summarised away.

A pane streams `/api/chat_stream` as the main chat does, so it gets the route's
`compacted` notice (and, with the foreground fallback policy on, the agent
loop's own). `static/js/compare/stream.js` had no arm for it, so a pane whose
conversation was compacted said nothing while the main chat said *Context
compacted — older messages summarized (12/40 messages kept, 31,000 → 6,400
tokens)* — the family of `B916` and `B918`: a pane should say what the chat
says.

Now it does, as the quiet line the main chat's reload draws (`agentNoteNode`,
`static/js/agentStops.js`), in the toast's words. Before any of the reply is
drawn the line goes above the reply in the pane's message — the first words
clear the pane's body, and would take it with them — and later, when the loop
compacts for a step, where the run is, above the spinner that step waits on.

Driven under node (`Law 20`): the real `streamToPane` with the real
`agentStops.js`, `agentTurn.js`, `agentMeter.js` and `spinner.js`, in the page
`B916`'s file lays a pane into.
"""

import json
import shutil

import pytest

from test_tool_effect_surfaces_js import _run  # noqa: E402
from test_a_compare_pane_counts_its_steps import _PREAMBLE as _STEP_PREAMBLE  # noqa: E402
from test_a_compare_pane_draws_the_card_the_chat_draws import sandbox  # noqa: E402,F401

pytestmark = pytest.mark.skipif(not shutil.which("node"), reason="node binary not on PATH")

# The route's notice, as `compacted_frame` builds it (`P4-13` / `B921`).
COMPACTED = {"type": "compacted", "context_length": 8192,
             "data": {"context_length": 8192, "messages_before": 40, "messages_after": 12,
                      "tokens_before": 31000, "tokens_after": 6400}}
SAID = "Context compacted — older messages summarized (12/40 messages kept, 31,000 → 6,400 tokens)"

_PANE = _STEP_PREAMBLE + r"""
/** The pane's message as a person reads it: a line above the reply, if there
 *  is one, and the reply's own parts. */
function paneMessage() {
  const part = (n) => {
    const cls = n._classes();
    if (cls.includes('context-compacted-note')) return 'line: ' + words(n);
    if (cls.includes('agent-thread-node')) return 'card';
    if (cls.includes('compare-text-content')) return 'text: ' + words(n);
    if (cls.includes('compare-sources-box')) return 'sources';
    return n.className;
  };
  return ai.children.filter((n) => !n._classes().includes('role') && !n._classes().includes('msg-footer'))
    .map((n) => (n._classes().includes('body') ? { body: n.children.map(part) } : part(n)));
}
"""


def _pane(sandbox, script: str) -> dict:
    return _run(sandbox, _PANE, script)


def test_a_compacted_conversation_says_so_above_the_reply(sandbox):
    """The row's `Verify:` — with the counts. The line is still there after the
    reply's first words clear the pane, and the reply stays the pane's last
    text (what grading and the HTML preview read)."""
    out = _pane(sandbox, """
        await run([%s, { delta: 'Here is the summary.' }, '[DONE]']);
        console.log(JSON.stringify({ pane: paneMessage(), previews }));
    """ % json.dumps(COMPACTED))
    assert out["pane"] == ["line: " + SAID, {"body": ["text: Here is the summary."]}], out["pane"]
    assert out["previews"] == ["Here is the summary."]


def test_the_line_outlasts_the_sources_box_that_clears_the_pane(sandbox):
    out = _pane(sandbox, """
        await run([%s, { type: 'web_sources', data: [{ title: 'a', url: 'https://a.example' }] },
                   { delta: 'From the web.' }, '[DONE]']);
        console.log(JSON.stringify({ pane: paneMessage() }));
    """ % json.dumps(COMPACTED))
    assert out["pane"] == ["line: " + SAID, {"body": ["sources", "text: From the web."]}], out["pane"]


def test_a_compaction_for_a_later_step_is_said_where_the_run_is(sandbox):
    """The agent loop compacts before the request of the step it shapes: the
    line follows the work before it and comes before that step's answer."""
    out = _pane(sandbox, """
        await run([
          budget(1, 0),
          [budget(1, 1), { type: 'tool_start', tool: 'bash', command: 'ls', round: 1 }],
          { type: 'tool_output', tool: 'bash', command: 'ls', round: 1, exit_code: 0, output: 'a b' },
          [{ type: 'agent_step', round: 2 }, budget(2, 1)],
          %s,
          () => seen.push(paneMessage()),
          { delta: 'There are two files.' },
          '[DONE]',
        ]);
        console.log(JSON.stringify({ waiting: seen[0], pane: paneMessage() }));
    """.replace("await run([", "const seen = [];\n        await run([") % json.dumps(COMPACTED))
    waiting = out["waiting"][0]["body"]
    assert waiting == ["card", "line: " + SAID, "ai-spinner", "agent-meter"], (
        f"the line is not above the spinner its step waits on: {waiting}")
    assert out["pane"] == [{"body": ["card", "line: " + SAID, "text: There are two files."]}], out["pane"]


def test_a_compaction_nothing_measured_is_said_without_figures(sandbox):
    out = _pane(sandbox, """
        await run([{ type: 'compacted', context_length: 4096 }, { delta: 'Hi.' }, '[DONE]']);
        console.log(JSON.stringify({ pane: paneMessage() }));
    """)
    assert out["pane"] == ["line: Context compacted — older messages summarized", {"body": ["text: Hi."]}]
