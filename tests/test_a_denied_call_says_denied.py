# SPDX-License-Identifier: AGPL-3.0-or-later
"""`P23-04` — CHAT-M-3 (and its alias CHAT-M-24), CHAT-M-8, CHAT-M-21 and
COPY-U-8 / CHAT-U-4 / CHAT-U-5: a tool row says what happened to the call.

**What was wrong** (measured on `9560d50`, and again on this branch's base by
driving the showcase: Deny on *What the survey says*, then reload):

  * **CHAT-M-3 / M-24.** A call held for approval is persisted as a tool event
    with `ask_user` on it, and the server's one resolve path writes
    `ask_user.resolved` (`routes/chat_routes.py` `_mark_tool_approval_resolved`).
    The row read `ok` only (`exit_code` is null for a call that never ran), so
    it said **✓ done** while the card waited and for ever after a Deny, with the
    gate's "Waiting for an exact user approval." as its output. Live, the
    card's question "Allow this task to continue?" stayed under a tok/s footer
    as if it were the reply.
  * **CHAT-M-8.** After Allow, the call was drawn twice on reload — the row that
    asked, and the approved row in the continuation — and the approved one was
    grouped by the round it was *asked* in, so it could land after the answer
    that reports it.
  * **CHAT-M-21.** The reasoning a turn showed live was not drawn after a
    reload at all.
  * **COPY-U-8.** Rows were code names upper-cased: *MANAGE_DOCUMENTS*.
  * **CHAT-U-4 / U-5.** The header was a `<div>` (Tab never reached it), and an
    opened row showed the arguments with the output folded under them.

Driven under node (`Law 20`) through the real `chatRenderer.js` and
`agentThread.js`, in the sandbox `test_the_thread_reads_in_one_go_js.py` uses,
with the record's shape copied from the history the showcase saved.
"""

import json
import shutil

import pytest

from test_tool_effect_surfaces_js import _run
from test_the_thread_reads_in_one_go_js import _PREAMBLE, thread_sandbox  # noqa: F401

pytestmark = pytest.mark.skipif(not shutil.which("node"), reason="node binary not on PATH")

DIGEST = "de244404fad40aa8"
QUESTION = "Allow this task to continue?"
COMMAND = '{"action": "list", "search": "survey"}'


def _asked(resolved=None):
    q = {"kind": "tool_approval", "approval_id": "appr-1", "session_id": "s1",
         "question": QUESTION, "options": [{"label": "Allow for this task", "value": "approve_task"},
                                           {"label": "Deny", "value": "deny"}],
         "action": {"tool": "manage_documents", "content": COMMAND, "digest": DIGEST}}
    if resolved:
        q["resolved"] = resolved
    return q


def _paused(resolved=None):
    """The saved reply of a turn that stopped at the card: its question as the
    content, one empty round, the reasoning, and the held call."""
    return {"round_texts": [""], "thinking": "The survey is a CSV in the Research folder.",
            "tokens_per_second": 842.19,
            "tool_events": [{"round": 1, "tool": "manage_documents", "command": COMMAND,
                             "output": "Waiting for an exact user approval.", "exit_code": None,
                             "status": "ok", "ask_user": _asked(resolved)}]}


_READ = r"""
const rows = () => history.querySelectorAll('.agent-thread-node').map((n) => ({
  label: (/<span class="agent-thread-tool">([^<]*)<\/span>/.exec(n.innerHTML) || [])[1] || null,
  status: (/<span class="agent-thread-status">([^<]*)<\/span>/.exec(n.innerHTML) || [])[1] || null,
  icon: (/<span class="agent-thread-icon">([^<]*)<\/span>/.exec(n.innerHTML) || [])[1] || null,
  waitingOutput: n.innerHTML.includes('Waiting for an exact user approval'),
  approved: n.innerHTML.includes('agent-thread-approved'),
  cls: n.className,
}));
const footers = () => history.querySelectorAll('.msg-footer').length;
const bodyOf = (n) => (n.querySelectorAll ? n.querySelectorAll('.body') : []).map((b) => b.innerHTML || '').join(' ');
const thinking = () => bodyOf(history);
"""


def _drive(sandbox, body):
    return _run(sandbox, _PREAMBLE, _READ + body)


def test_a_denied_call_says_denied_after_a_reload(thread_sandbox):
    out = _drive(thread_sandbox, """
        history.childNodes = [];
        addMessage('assistant', %s, 'm', %s);
        console.log(JSON.stringify({ rows: rows(), footers: footers(),
          cards: history.querySelectorAll('.ask-user-card').length }));
    """ % (json.dumps(QUESTION), json.dumps(_paused("deny"))))
    [row] = out["rows"]
    assert row["status"] == "denied" and row["icon"] == "⊘", row
    assert "error" not in row["cls"].split(), "a refusal is not a failure"
    assert not row["waitingOutput"], "the gate's own words are not the call's output"
    assert out["cards"] == 0
    assert out["footers"] == 0, "the question that stood in for the reply got a reply's footer"


def test_a_call_waiting_for_an_answer_says_waiting(thread_sandbox):
    out = _drive(thread_sandbox, """
        history.childNodes = [];
        addMessage('assistant', %s, 'm', %s);
        console.log(JSON.stringify({ rows: rows(), cards: history.querySelectorAll('.ask-user-card').length }));
    """ % (json.dumps(QUESTION), json.dumps(_paused())))
    [row] = out["rows"]
    assert row["status"] == "waiting" and row["icon"] == "…", row
    assert out["cards"] == 1, "the unanswered card is still drawn"


def test_an_allowed_call_is_one_row_and_opens_its_turn(thread_sandbox):
    continuation = {
        "round_texts": ["", "Reminders are the most divided question."],
        "tool_events": [
            # The approved call: asked in round 2 of the turn before, run first.
            {"round": 2, "tool": "manage_documents", "command": COMMAND, "output": "survey-results.csv",
             "exit_code": 0, "status": "ok", "approved": True, "approval_digest": DIGEST},
            {"round": 1, "tool": "manage_documents", "command": '{"action": "read", "id": 7}',
             "output": "rows", "exit_code": 0, "status": "ok"},
        ],
    }
    out = _drive(thread_sandbox, """
        history.childNodes = [];
        addMessage('assistant', %s, 'm', %s);
        const before = rows();
        addMessage('assistant', 'Reminders are the most divided question.', 'm', %s);
        const order = history.childNodes.map((n) => n.className.includes('agent-thread') ? 'thread'
          : bodyOf(n).includes('most divided') ? 'answer' : 'other');
        console.log(JSON.stringify({ before, after: rows(), order }));
    """ % (json.dumps(QUESTION), json.dumps(_paused("approve_task")), json.dumps(continuation)))
    assert [r["status"] for r in out["before"]] == ["allowed"]
    labels = [(r["label"], r["status"], r["approved"]) for r in out["after"]]
    assert labels == [("Documents · list", "done", True), ("Documents · read", "done", False)], labels
    # Both calls come before the answer that reports them.
    assert out["order"].index("thread") < out["order"].index("answer"), out["order"]


def test_the_reasoning_is_drawn_after_a_reload(thread_sandbox):
    per_round = {"round_texts": ["", "The answer."], "round_thinking": ["First look.", "Second look."],
                 "tool_events": [{"round": 1, "tool": "bash", "command": "ls", "output": "a", "exit_code": 0}]}
    out = _drive(thread_sandbox, """
        history.childNodes = [];
        addMessage('assistant', %s, 'm', %s);
        const one = thinking();
        history.childNodes = [];
        addMessage('assistant', 'The answer.', 'm', %s);
        console.log(JSON.stringify({ one, two: thinking() }));
    """ % (json.dumps(QUESTION), json.dumps(_paused("deny")), json.dumps(per_round)))
    assert "The survey is a CSV in the Research folder." in out["one"]
    assert "First look." in out["two"] and "Second look." in out["two"]
    assert out["two"].index("First look.") < out["two"].index("Second look.")


# ── the row itself ──────────────────────────────────────────────────────────

def test_a_row_names_the_tool_and_its_action_and_is_a_control(thread_sandbox):
    out = _drive(thread_sandbox, """
        const html = (o) => thread.agentThreadNodeHtml(Object.assign({ state: 'done', ok: true }, o));
        console.log(JSON.stringify({
          tasks: thread.toolActionLabel('manage_tasks', 'done', '{"action": "list"}'),
          cal: thread.toolActionLabel('manage_calendar', 'done', '{"action": "create_event", "title": "x"}'),
          shell: thread.toolActionLabel('bash', 'done', 'ls -la'),
          json: html({ tool: 'manage_tasks', command: '{"action": "list"}', output: '<details class="agent-tool-output" open>OUT</details>' }),
          bash: html({ tool: 'bash', command: 'ls -la', output: 'OUT' }),
          open: html({ tool: 'bash', command: 'ls', open: true }),
          panes: thread.toolOutputPanesHtml({ output: 'hello' }),
        }));
    """)
    assert out["tasks"] == "Tasks · list"
    assert out["cal"] == "Calendar · create event"
    assert out["shell"] == "Terminal"
    # CHAT-U-4: a tab stop, a button to assistive tech, and it says if it is open.
    assert 'role="button" tabindex="0" aria-expanded="false"' in out["bash"]
    assert 'aria-expanded="true"' in out["open"]
    # CHAT-U-5: the output first and open; JSON arguments folded beneath it,
    # while a command line stays above its output.
    assert out["json"].index("OUT") < out["json"].index("agent-thread-args")
    assert '<details class="agent-thread-args"><summary>Arguments</summary>' in out["json"]
    assert out["bash"].index("agent-thread-cmd") < out["bash"].index("OUT")
    assert out["panes"].startswith('<details class="agent-tool-output" open>')


def test_approval_outcome_reads_the_event_not_ok(thread_sandbox):
    out = _drive(thread_sandbox, """
        const ev = (r) => ({ exit_code: 0, ask_user: Object.assign({ kind: 'tool_approval' }, r ? { resolved: r } : {}) });
        console.log(JSON.stringify([
          thread.approvalOutcome(ev(null)), thread.approvalOutcome(ev('deny')),
          thread.approvalOutcome(ev('approve')), thread.approvalOutcome(ev('approve_task')),
          thread.approvalOutcome({ exit_code: 0 }),
          thread.approvalOutcome({ ask_user: { question: 'Which one?' } }),
        ]));
    """)
    assert out == ["waiting", "denied", "allowed", "allowed", None, None]


# ── the live screen while the card waits ────────────────────────────────────
#
# Driven on the showcase (`drive-card.png`): the reply bubble under the waiting
# card said "Allow this task to continue?" under the round's reasoning, with
# "1 memory, keyword only · 809 tok/s", copy and delete — a reply's footer on
# the server's stand-in, which a reload (above) does not draw.

from test_tool_effect_surfaces_js import _card, card_sandbox  # noqa: E402,F401
from test_a_turns_pills_reach_its_footer_live import _between, _handler, _metrics_target  # noqa: E402
from tests.helpers.js_source import js_definition  # noqa: E402

# The live shape, read off the showcase's DOM under a waiting card:
# `.body > .stream-content > [.thinking-section, div > p]`.
_LIVE_BUBBLE = r"""
const bubble = (thinkingText, replyText) => {
  const n = document.createElement('div');
  n.className = 'msg msg-ai';
  const body = n.appendChild(document.createElement('div'));
  body.className = 'body';
  const box = body.appendChild(document.createElement('div'));
  box.className = 'stream-content';
  if (thinkingText) {
    const t = box.appendChild(document.createElement('div'));
    t.className = 'thinking-section';
    t.textContent = thinkingText;
  }
  const reply = box.appendChild(document.createElement('div'));
  const p = reply.appendChild(document.createElement('p'));
  p.textContent = replyText;
  return n;
};
"""


def test_the_stand_in_reply_leaves_the_live_bubble_and_the_reasoning_stays(card_sandbox):
    out = _card(_LIVE_BUBBLE + """
        const m = await import('./chatRenderer.js');
        const withThinking = bubble('The survey is a CSV.', %(q)s);
        const bare = bubble('', %(q)s);
        const said = bubble('', 'I found it. ' + %(q)s);
        const r = [m.dropApprovalPlaceholder(withThinking, %(q)s), m.dropApprovalPlaceholder(bare, %(q)s),
                   m.dropApprovalPlaceholder(said, %(q)s)];
        console.log(JSON.stringify({ dropped: r,
          thinkingKept: withThinking.querySelector('.thinking-section').textContent,
          thinkingReply: m.bubbleReplyText(withThinking), thinkingHidden: withThinking.style.display === 'none',
          bareHidden: bare.style.display === 'none', bareReply: m.bubbleReplyText(bare),
          saidReply: m.bubbleReplyText(said) }));
    """ % {"q": json.dumps(QUESTION)}, card_sandbox)
    assert out["dropped"] == [True, True, False], "only the stand-in alone is taken; a reply that said more stays"
    assert out["thinkingKept"] == "The survey is a CSV."
    assert out["thinkingReply"] == "" and out["thinkingHidden"] is False
    assert out["bareHidden"] is True and out["bareReply"] == ""
    assert out["saidReply"] == "I found it. " + QUESTION


def _end_blocks() -> str:
    code = _handler()
    blocks = []
    for anchor in ("if (holder.dataset?.approvalPaused) {",
                   "if (holder.dataset?.approvalPaused && !chatRenderer.bubbleReplyText(footerTarget)) {"):
        assert code.count(anchor) == 1, f"{anchor!r} is not the end of the stream's one block"
        blocks.append(js_definition(code, code.index(anchor)))
    return blocks


@pytest.mark.parametrize("kind", ["tool_approval", None], ids=["approval-card", "question-card"])
def test_a_turn_paused_at_the_card_draws_no_reply_and_no_footer_live(card_sandbox, kind):
    """The live stream's own pieces, cut out of `handleChatSubmit` (`Law 20`):
    the `ask_user` arm, `_metricsTargetForTurn`, and the two places the end of
    the stream reads what the arm marked. A question card (`ask_user` the tool,
    no approval) is the agent's own words and keeps its footer."""
    arm = _between("} else if (json.type === 'ask_user') {", "} else if (json.type === 'plan_update') {")
    drop, hide = _end_blocks()
    payload = {"question": QUESTION, "options": []}
    if kind:
        payload.update(kind=kind, approval_id="ap-1")
    out = _card(_LIVE_BUBBLE + """
        const chatRenderer = await import('./chatRenderer.js');
        const _isBg = false, _cancelThinkingTimer = () => {}, _removeThinkingSpinner = () => {};
        const json = { type: 'ask_user', data: %(payload)s };
        const holder = bubble('The survey is a CSV.', %(q)s);
        holder.dataset = {};
        let roundHolder = holder, lastToolThread = null;
        const _withTurnPills = (n) => n;
        %(target)s
        for (const _ of [0]) { %(arm)s }
        const targetDuring = _metricsTargetForTurn();
        %(drop)s
        const footerTarget = holder;
        const footer = footerTarget.appendChild(document.createElement('div'));
        footer.className = 'msg-footer';
        %(hide)s
        console.log(JSON.stringify({ marked: holder.dataset.approvalPaused || null,
          metricsTarget: targetDuring ? 'bubble' : null,
          reply: chatRenderer.bubbleReplyText(holder), footerShown: footer.style.display !== 'none' }));
    """ % {"payload": json.dumps(payload), "q": json.dumps(QUESTION), "target": _metrics_target(),
           "arm": arm, "drop": drop, "hide": hide}, card_sandbox)
    if kind:
        assert out == {"marked": QUESTION, "metricsTarget": None, "reply": "", "footerShown": False}, out
    else:
        assert out == {"marked": None, "metricsTarget": "bubble", "reply": QUESTION, "footerShown": True}, out
