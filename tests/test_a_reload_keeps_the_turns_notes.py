# SPDX-License-Identifier: AGPL-3.0-or-later
"""`B915` — the notes a turn draws beside its reply survive a reload.

Six events draw a line into the chat history beside the reply: the step limit
with its **Continue ▸** offer (`rounds_exhausted`), the tool budget
(`budget_exceeded`), a teacher taking over (`teacher_takeover`), and what
became of a skill (`skill_saved`, `escalation_failed`, `skill_save_failed`).
Each was drawn live by its own arm in `chat.js` and saved nowhere: the route
forwarded them and put none on the record it saves, and history replay
(`chatRenderer.addMessage`) drew none. So a reload dropped every one, and a run
that hit the step limit could not be continued from the button after a reload.

Now the route keeps them (`AgentNotes`, `src/agent_stops.py`) and saves them
with the reply as `agent_notes`, and one builder (`renderAgentNote`,
`static/js/agentStops.js`) draws them for the live stream, a resumed one and
history replay. Everything here runs code (`Law 20`):

  * the real `stream_agent_loop`, with a scripted model, hits its step limit;
    its frames go through `/api/chat_stream` and the real
    `save_assistant_response`; the record it saves is drawn by the real
    `addMessage`, and Continue ▸ is there and does what the live one does —
    the row's `Verify:` end to end;
  * a teacher's turn, which is saved from the teacher's own record, keeps the
    notes in the places they were drawn; a failed turn keeps them too;
  * each note is drawn in its round, as text, and a later message withdraws a
    step limit's offer.
"""

import asyncio
import json
import shutil
from pathlib import Path

import pytest

import routes.chat_routes as chat_routes
import src.agent_loop as agent_loop
from src.agent_stops import AGENT_NOTE_TYPES, AgentNotes
from tests.helpers.esc_stub import ui_default_stub  # B874
from test_foreground_model_routing import _RouteRequest, _chat_stream_endpoint  # noqa: E402
from test_tool_effect_surfaces_js import _CARD_SHIM, _CARD_STUBS, _make_sandbox, _run  # noqa: E402

ROOT = Path(__file__).resolve().parents[1]
CHAT_RENDERER = ROOT / "static" / "js" / "chatRenderer.js"

node_only = pytest.mark.skipif(not shutil.which("node"), reason="node binary not on PATH")


# ── the loop, the route and the save ────────────────────────────────────────


def _frame(obj) -> str:
    return f"data: {json.dumps(obj)}\n\n"


def _loop_chunks(monkeypatch, replies, *, max_rounds):
    """The frames the real `stream_agent_loop` sends, with a scripted model:
    one reply per round, the last repeated. Tools run and succeed."""
    monkeypatch.setattr(agent_loop, "get_setting", lambda k, d=None: d, raising=False)
    monkeypatch.setattr(agent_loop, "get_mcp_manager", lambda: None, raising=False)
    monkeypatch.setattr(agent_loop, "estimate_tokens", lambda *a, **k: 10, raising=False)
    queue = list(replies)

    async def fake_stream(*_a, **_k):
        text = queue.pop(0) if len(queue) > 1 else queue[0]
        yield _frame({"delta": text})
        yield "data: [DONE]\n\n"

    async def fake_execute(block, *_a, **_k):
        return (block.tool_type, {"output": "ok", "exit_code": 0})

    monkeypatch.setattr(agent_loop, "stream_llm_with_fallback", fake_stream, raising=False)
    monkeypatch.setattr(agent_loop, "execute_tool_block", fake_execute, raising=False)

    async def drain():
        return [c async for c in agent_loop.stream_agent_loop(
            "http://local.test/v1", "small-local-model",
            [{"role": "user", "content": "work through the list"}],
            max_rounds=max_rounds, relevant_tools={"update_plan"})]

    return asyncio.run(drain())


def _saved_through_route(monkeypatch, chunks):
    """Push `chunks` out of a stubbed loop, through the route and the REAL
    `save_assistant_response`. Returns the metadata of every reply saved."""
    import core.database as database
    from routes.chat_helpers import save_assistant_response

    captured = {}
    endpoint = _chat_stream_endpoint(monkeypatch, "agent", captured, agent_chunks=chunks)
    monkeypatch.setattr(chat_routes, "save_assistant_response", save_assistant_response)
    monkeypatch.setattr(database, "update_session_last_accessed", lambda sid: None, raising=False)

    async def go():
        response = await endpoint(_RouteRequest("agent"))
        async for _ in response.body_iterator:
            pass

    asyncio.run(go())
    return [m.metadata for m in captured.get("added_messages", [])]


def _plan(n):
    return '```update_plan\n{"plan":"- [ ] step %d"}\n```' % n


def test_a_run_that_hit_the_step_limit_is_saved_with_its_offer(monkeypatch):
    chunks = _loop_chunks(monkeypatch, [_plan(1), _plan(2)], max_rounds=2)
    assert any('"rounds_exhausted"' in c for c in chunks), "the scripted run did not reach the limit"
    saved = _saved_through_route(monkeypatch, chunks)
    assert len(saved) == 1
    assert saved[0]["agent_notes"] == [{"type": "rounds_exhausted", "rounds": 2, "round": 2}]


def test_a_turn_that_drew_no_note_saves_none(monkeypatch):
    chunks = _loop_chunks(monkeypatch, ["All done, nothing to change."], max_rounds=3)
    saved = _saved_through_route(monkeypatch, chunks)
    assert len(saved) == 1 and "agent_notes" not in saved[0]


_STUDENT = [
    _frame({"delta": "Let me look."}),
    _frame({"type": "tool_start", "tool": "bash", "command": "ls /srv", "round": 1}),
    _frame({"type": "tool_output", "tool": "bash", "command": "ls /srv", "round": 1,
            "exit_code": 2, "output": "no such file"}),
    _frame({"type": "skill_saved", "name": "list-dirs", "category": "files", "status": "draft"}),
    _frame({"type": "agent_step", "round": 2}),
    _frame({"delta": "I can't find it."}),
    _frame({"type": "metrics", "data": {"round_texts": ["Let me look.", "I can't find it."],
                                        "tool_events": [{"round": 1, "tool": "bash"}]}}),
]


def test_a_teachers_turn_keeps_its_notes_where_they_were_drawn(monkeypatch):
    """A turn the teacher answered is saved as one reply of two runs (`B939`):
    the student's rounds, then the teacher's numbered after them. What the
    student's run drew stays in its rounds; the banner follows the student's
    last round; what the teacher's run drew goes in its rounds, moved after the
    student's two; what came after it, at the end. (`B915` saved the teacher's
    record alone, and put the student's notes and the banner before it.)"""
    teacher = [
        _frame({"type": "teacher_takeover", "teacher_model": "big-model@lab", "model": "big-model",
                "student_failure": "agent reply matched give-up pattern"}),
        _frame({"type": "tool_start", "tool": "bash", "command": "mount", "round": 1, "teacher": True}),
        _frame({"type": "tool_output", "tool": "bash", "command": "mount", "round": 1,
                "exit_code": 0, "output": "/dev/sdb1 on /data", "teacher": True}),
        _frame({"type": "skill_saved", "name": "read-mounts", "category": "ops", "teacher": True}),
        _frame({"type": "agent_step", "round": 2, "teacher": True}),
        _frame({"type": "skill_saved", "name": "find-mounts", "category": "ops", "teacher": True}),
        _frame({"delta": "It is under /data.", "teacher": True}),
        _frame({"type": "metrics", "teacher": True,
                "data": {"round_texts": ["", "It is under /data."],
                         "tool_events": [{"round": 1, "tool": "bash"}]}}),
        _frame({"type": "skill_save_failed", "reason": "teacher said NO_SKILL"}),
        "data: [DONE]\n\n",
    ]
    saved = _saved_through_route(monkeypatch, _STUDENT + teacher)
    notes = [(n["type"], n.get("round")) for n in saved[0]["agent_notes"]]
    # The teacher's run numbers its own rounds: its first note is in its round 1,
    # which is the reply's round 3.
    assert notes == [("skill_saved", 1), ("teacher_takeover", 2), ("skill_saved", 3),
                     ("skill_saved", 4), ("skill_save_failed", None)], notes
    assert saved[0]["round_texts"] == ["Let me look.", "I can't find it.", "", "It is under /data."]
    takeover = saved[0]["agent_notes"][1]
    assert takeover["teacher_model"] == "big-model@lab"
    assert takeover["student_failure"] == "agent reply matched give-up pattern"


def test_a_turn_the_teacher_never_answered_keeps_the_students_rounds(monkeypatch):
    """No teacher record came — its endpoint could not be resolved — so the
    saved rounds are the student's: its notes stay in them, and the failure
    follows the student's last round, where it was drawn."""
    failed = [_frame({"type": "escalation_failed", "reason": "teacher endpoint not resolvable: x"}),
              "data: [DONE]\n\n"]
    saved = _saved_through_route(monkeypatch, _STUDENT + failed)
    notes = [(n["type"], n.get("round")) for n in saved[0]["agent_notes"]]
    assert notes == [("skill_saved", 1), ("escalation_failed", 2)], notes


def test_a_failed_turn_is_saved_with_its_notes(monkeypatch):
    """A turn whose model request failed is saved at `agent_terminal`, not at
    the end of the stream. What it drew before it failed is on that record."""
    chunks = _STUDENT[:5] + [
        _frame({"type": "agent_terminal", "data": {
            "failed": True, "failure": {"status": 502, "message": "Model request failed (HTTP 502)"},
            "round_texts": ["Let me look.", "[Agent stopped: Model request failed (HTTP 502)]"],
            "tool_events": [{"round": 1, "tool": "bash"}]}}),
        "data: [DONE]\n\n",
    ]
    saved = _saved_through_route(monkeypatch, chunks)
    assert saved and saved[0]["agent_notes"] == [
        {"type": "skill_saved", "name": "list-dirs", "category": "files", "status": "draft", "round": 1}]


def test_the_collector_keeps_only_notes_and_survives_junk():
    notes = AgentNotes()
    for frame in (None, "text", 7, {"type": "tool_output"}, {"type": "agent_step", "round": "x"},
                  {"type": "agent_step", "round": -3}, {"type": "budget_exceeded", "limit": 1, "used": 1}):
        notes.observe(frame)
    assert notes.saved() == [{"type": "budget_exceeded", "limit": 1, "used": 1, "round": 1}]


def test_the_server_and_the_browser_name_the_same_notes(tmp_path):
    """Two copies because one is Python and one is a browser; held equal here,
    by running the browser's."""
    if not shutil.which("node"):
        pytest.skip("node binary not on PATH")
    import subprocess
    shutil.copy(ROOT / "static" / "js" / "agentStops.js", tmp_path / "agentStops.js")
    (tmp_path / "case.mjs").write_text(
        "import { AGENT_NOTE_TYPES } from './agentStops.js';\n"
        "console.log(JSON.stringify(AGENT_NOTE_TYPES));\n", encoding="utf-8")
    out = subprocess.run(["node", "case.mjs"], cwd=tmp_path, capture_output=True, text=True, timeout=30)
    assert out.returncode == 0, out.stderr
    assert json.loads(out.stdout) == list(AGENT_NOTE_TYPES)


# ── the reload draws them ───────────────────────────────────────────────────

_STUBS = dict(_CARD_STUBS, **{
    "ui.js": ui_default_stub(
        "showToast: () => {}, copyToClipboard: () => {},\n"
        "showError: (m) => { (globalThis.errors = globalThis.errors || []).push(String(m)); },\n"
        "el: (id) => document.getElementById(id), debounce: (f) => f,\n"
        "autoResize: () => {}, scrollHistory: () => {}, formatBytes: (n) => String(n),"),
})


@pytest.fixture(scope="module")
def sandbox(tmp_path_factory):
    return _make_sandbox(tmp_path_factory.mktemp("turnnotes"), CHAT_RENDERER, _CARD_SHIM, _STUBS)


_PAGE = r"""
import { document, Node, history } from './shim.js';
const { addMessage } = await import('./chatRenderer.js');
// The composer and its send button, and the chat module's two setters, which
// Continue ▸ goes through as the live one does.
const composer = document.body.appendChild(new Node('textarea'));
composer.setAttribute('id', 'message');
const send = document.body.appendChild(new Node('button'));
send.className = 'send-btn';
const sent = [];
send.click = () => sent.push(composer.value);
const calls = [];
window.chatModule = {
  setHideUserBubble() { calls.push('hide'); },
  setPendingContinue(el) { calls.push(['continue', el ? el.querySelector('.body').textContent : null]); },
};
globalThis.errors = [];
const text = (n) => n.textContent.replace(/\s+/g, ' ').trim();
function shape() {
  return history.children.map((n) => {
    const cls = String(n.className || '');
    if (cls.includes('rounds-exhausted')) {
      return 'limit:' + text(n.querySelector('.rounds-exhausted-label'))
        + (n.querySelector('.continue-btn') ? ' [Continue]' : '');
    }
    for (const k of ['budget-exceeded-note', 'teacher-takeover-banner', 'skill-saved-note', 'escalation-failed-note']) {
      if (cls.includes(k)) return k + ':' + text(n);
    }
    if (cls.includes('agent-stop')) return 'stop';
    if (cls.includes('agent-thread')) return 'thread';
    if (cls.includes('msg-user')) return 'user:' + text(n.querySelector('.body'));
    if (cls.includes('msg')) return 'msg:' + text(n.querySelector('.body'));
    return cls;
  });
}
"""


def _page(sandbox, body: str) -> dict:
    return _run(sandbox, "", _PAGE + body)


def _tool(round_):
    return {"round": round_, "tool": "update_plan", "command": '{"plan":"- [ ] go"}',
            "output": "ok", "exit_code": 0}


@node_only
def test_a_run_that_hit_the_step_limit_reloaded_still_offers_continue(monkeypatch, sandbox):
    """The row's `Verify:`, end to end: the real loop hits its limit, the route
    saves the reply, the reload draws it — and Continue ▸ is there, and does
    what the live one does: the note goes, the next send continues the turn's
    first bubble, its prompt is hidden, and it is sent."""
    chunks = _loop_chunks(monkeypatch, ["Working through it.\n\n" + _plan(1), _plan(2)], max_rounds=2)
    metadata = _saved_through_route(monkeypatch, chunks)[0]
    out = _page(sandbox, """
        addMessage('assistant', 'Working through it.', 'small-local-model', %s);
        const before = shape();
        const btn = history.querySelectorAll('.continue-btn')[0];
        btn.listeners.click.forEach((fn) => fn({}));
        console.log(JSON.stringify({ before, after: shape(), calls, sent, errors: globalThis.errors }));
    """ % json.dumps(metadata))
    assert out["errors"] == []
    assert out["before"][-1] == "limit:Reached the 2-step limit — not finished. [Continue]", out["before"]
    assert out["before"][0] == "msg:Working through it."
    assert not any(s.startswith("limit:") for s in out["after"]), "the note stayed after Continue"
    assert out["calls"] == ["hide", ["continue", "Working through it."]]
    assert out["sent"] and out["sent"][0].startswith("You hit the step limit before finishing")


@node_only
def test_each_note_is_drawn_after_the_round_it_followed(sandbox):
    out = _page(sandbox, """
        addMessage('assistant', 'reply', 'm', {
          round_texts: ['Step one.', '', 'Here it is.'],
          tool_events: [
            { round: 1, tool: 'bash', command: 'ls', output: 'ok', exit_code: 0 },
            { round: 2, tool: 'bash', command: 'ls b', output: 'ok', exit_code: 0 },
          ],
          agent_notes: [
            { type: 'skill_saved', name: 'list-dirs', category: 'files', round: 1 },
            { type: 'budget_exceeded', limit: 2, used: 2, round: 3 },
            { type: 'escalation_failed', reason: 'teacher endpoint not resolvable' },
          ],
        });
        console.log(JSON.stringify({ shape: shape(), errors: globalThis.errors }));
    """)
    assert out["errors"] == []
    assert out["shape"] == [
        "msg:Step one.", "thread", "skill-saved-note:Skill learned: list-dirs [files]", "thread",
        "msg:Here it is.", "budget-exceeded-note:Tool budget reached (2/2 calls). Agent stopped.",
        "escalation-failed-note:Teacher could not solve it: teacher endpoint not resolvable",
    ], out["shape"]


@node_only
def test_a_teachers_record_draws_the_banner_above_the_teachers_rounds(sandbox):
    out = _page(sandbox, """
        addMessage('assistant', 'reply', 'big-model', {
          round_texts: ['Checking the mounts.', 'It is under /data.'],
          tool_events: [{ round: 1, tool: 'bash', command: 'mount', output: 'ok', exit_code: 0 }],
          agent_notes: [
            { type: 'teacher_takeover', teacher_model: 'big-model@lab', student_failure: 'gave up', round: 0 },
            { type: 'skill_save_failed', reason: 'teacher said NO_SKILL' },
          ],
        });
        console.log(JSON.stringify({ shape: shape() }));
    """)
    assert out["shape"] == [
        "teacher-takeover-banner:Teacher takeover: escalating to big-model@lab — gave up",
        "msg:Checking the mounts.", "thread", "msg:It is under /data.",
        "escalation-failed-note:Skill not saved: teacher said NO_SKILL",
    ], out["shape"]


@node_only
def test_a_one_round_reply_with_only_a_note_still_shows_it(sandbox):
    out = _page(sandbox, """
        addMessage('assistant', 'I could not do that.', 'm', {
          round_texts: ['I could not do that.'],
          agent_notes: [{ type: 'escalation_failed', reason: 'teacher also failed' }],
        });
        console.log(JSON.stringify({ shape: shape() }));
    """)
    assert out["shape"] == ["msg:I could not do that.",
                            "escalation-failed-note:Teacher could not solve it: teacher also failed"]


@node_only
def test_a_later_message_withdraws_the_offer_and_a_later_limit_replaces_it(sandbox):
    """Continue carries on the latest reply — the server merges the last two
    — so offered under an earlier turn it would merge the wrong ones. A later
    message takes the button away and leaves the words; a later step limit
    takes the earlier box away, as the live stream always did."""
    out = _page(sandbox, """
        const turn = (n) => addMessage('assistant', 'Turn ' + n, 'm', {
          round_texts: ['Turn ' + n], tool_events: [{ round: 1, tool: 'bash', command: 'ls', output: 'ok', exit_code: 0 }],
          agent_notes: [{ type: 'rounds_exhausted', rounds: 20, round: 1 }] });
        turn(1);
        const offered = shape();
        addMessage('user', 'Something else instead', null, null);
        const withdrawn = shape();
        turn(2);
        console.log(JSON.stringify({ offered, withdrawn, again: shape() }));
    """)
    assert out["offered"][-1] == "limit:Reached the 20-step limit — not finished. [Continue]"
    assert "limit:Reached the 20-step limit — not finished." in out["withdrawn"]
    limits = [s for s in out["again"] if s.startswith("limit:")]
    assert limits == ["limit:Reached the 20-step limit — not finished. [Continue]"]
    assert out["again"][-1] == limits[0], "the offer is not under the latest turn"


@node_only
def test_a_reloaded_note_is_text(sandbox):
    """A skill's name, a teacher's model and the reason a student failed —
    which can quote a tool's output — are somebody else's words."""
    out = _page(sandbox, """
        addMessage('assistant', 'reply', 'm', {
          round_texts: ['reply'],
          agent_notes: [
            { type: 'teacher_takeover', teacher_model: '<img src=x onerror=alert(1)>',
              student_failure: '<script>alert(2)</script>', round: 1 },
            { type: 'skill_saved', name: '<b>x</b>', category: '<i>y</i>', round: 1 },
            { type: 'skill_save_failed', reason: '<svg onload=alert(3)>', round: 1 },
          ],
        });
        const notes = history.children.slice(1);
        console.log(JSON.stringify({
          markup: notes.flatMap((n) => n._walk([]).filter((c) => c._html).map((c) => c._html)),
          text: notes.map((n) => n.textContent),
        }));
    """)
    assert out["markup"] == [], "a part of a note was assigned as markup"
    assert out["text"] == [
        "Teacher takeover: escalating to <img src=x onerror=alert(1)> — <script>alert(2)</script>",
        "Skill learned: <b>x</b> [<i>y</i>]",
        "Skill not saved: <svg onload=alert(3)>",
    ]
