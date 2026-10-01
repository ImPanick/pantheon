# SPDX-License-Identifier: AGPL-3.0-or-later
"""`B939` — a turn the teacher answered reloads as it streamed.

When the teacher takes over (`run_teacher_inline`), the student's run has
already sent its own `metrics`, and the teacher's run sends its own after it.
The chat route saved the last `metrics` it saw, so the reply was saved from the
teacher's record alone: after a reload its rounds, cards, models and stops were
the teacher's, the student's attempt was gone, and the reply's text — the
student's and the teacher's together — no longer matched the rounds drawn.

Now the route saves the turn as one reply of two runs (`merge_runs`,
`src/agent_stops.py`): the student's rounds, then the teacher's numbered after
them, with the takeover banner between, and the student's own figures kept as an
earlier run, which history replay heads the student's rounds from and draws the
student's footer from — as the live stream drew both.

Driven end to end (`Law 20`): the real `stream_agent_loop` for the student and,
through the real `run_teacher_inline`, for the teacher, with a scripted model
(the settings, the resolver and the skill writer stubbed); its frames through
`/api/chat_stream` and the real `save_assistant_response`. The same frames are
drawn by the live stream's own arms (`P4-24`'s harness, cut out of
`handleChatSubmit`), and the saved record by the real `addMessage`: the reload
must say what the live stream said.
"""

import asyncio
import json
import shutil
from pathlib import Path

import pytest

import src.agent_loop as agent_loop
from tests.helpers.esc_stub import ui_default_stub  # B874
from test_a_reload_keeps_the_turns_notes import _saved_through_route  # noqa: E402
from test_tool_effect_surfaces_js import _CARD_STUBS, _make_sandbox, _run  # noqa: E402
import test_a_resumed_stream_draws_what_the_live_one_drew as resumed  # noqa: E402

ROOT = Path(__file__).resolve().parents[1]
JS = ROOT / "static" / "js"

node_only = pytest.mark.skipif(not shutil.which("node"), reason="node binary not on PATH")

STUDENT = "small-local-model"
STUDENT_REPLIES = ["Let me look.\n```bash\nls /srv\n```", "I can't find it."]
TEACHER_REPLIES = ['Checking the mounts.\n```update_plan\n{"plan":"- [ ] read the mounts"}\n```',
                   "It is under /data."]


def recorded_takeover(monkeypatch, *, teacher="big-model", route=None, student_route=None):
    """The frames of one real turn the teacher took over. The student runs a
    command and gives up ("I can't find it." — a give-up the real
    `evaluate_turn_regex` flags); the teacher, on `route` when given (what
    `resolve_route_descriptor` answers), updates its plan and answers. The
    model is scripted by which model each request names."""
    import src.ai_interaction as ai_interaction
    import src.endpoint_resolver as endpoint_resolver
    import src.settings as settings
    import src.teacher_escalation as teacher_escalation
    import src.tool_index as tool_index

    monkeypatch.setattr(agent_loop, "get_setting", lambda k, d=None: d, raising=False)
    monkeypatch.setattr(agent_loop, "get_mcp_manager", lambda: None, raising=False)
    monkeypatch.setattr(agent_loop, "estimate_tokens", lambda *a, **k: 10, raising=False)
    monkeypatch.setattr(agent_loop, "blocked_tools_for_owner", lambda o: set(), raising=False)
    values = {"teacher_enabled": True, "teacher_model": teacher + "@lab"}
    monkeypatch.setattr(settings, "get_setting", lambda k, d=None: values.get(k, d))
    monkeypatch.setattr(ai_interaction, "_resolve_model",
                        lambda spec, owner=None: ("http://teacher.example/v1", teacher, {}))
    looked_up = []

    def resolve(url, model, headers=None, owner=None):
        looked_up.append((url, model, owner))
        return dict(route) if route else {"endpoint_id": None, "endpoint_label": "Selected route"}

    monkeypatch.setattr(endpoint_resolver, "resolve_route_descriptor", resolve)
    monkeypatch.setattr(teacher_escalation, "note_turn_outcome", lambda **k: None)

    class _Index:   # the teacher's run picks its tools; the student's are given
        def get_tools_for_query(self, query, k):
            return {"update_plan"}

    monkeypatch.setattr(tool_index, "get_tool_index", lambda: _Index())

    async def no_skill(*_a, **_k):
        return "NO_SKILL"

    monkeypatch.setattr(teacher_escalation, "_call_teacher", no_skill)
    queues = {STUDENT: list(STUDENT_REPLIES), teacher: list(TEACHER_REPLIES)}

    async def fake_stream(candidates, messages, **kwargs):
        queue = queues[candidates[0][1]]
        text = queue.pop(0) if len(queue) > 1 else queue[0]
        yield f"data: {json.dumps({'delta': text})}\n\n"
        yield "data: [DONE]\n\n"

    async def fake_execute(block, *_a, **_k):
        return (block.tool_type, {"output": "app.log", "exit_code": 0})

    monkeypatch.setattr(agent_loop, "stream_llm_with_fallback", fake_stream, raising=False)
    monkeypatch.setattr(agent_loop, "execute_tool_block", fake_execute, raising=False)

    async def drain():
        return [c async for c in agent_loop.stream_agent_loop(
            "http://student.local/v1", STUDENT,
            [{"role": "user", "content": "find the backups"}],
            max_rounds=4, relevant_tools={"bash"}, session_id="s1", owner="alice",
            route_descriptors=[student_route] if student_route else None)]

    chunks = asyncio.run(drain())
    recorded_takeover.looked_up = looked_up
    return chunks


def frames(chunks):
    return [json.loads(c[6:]) for c in chunks if c.startswith("data: {")]


# ── the saved record ────────────────────────────────────────────────────────


def test_the_saved_reply_is_the_students_rounds_then_the_teachers(monkeypatch):
    chunks = recorded_takeover(monkeypatch)
    sent = frames(chunks)
    assert any(f.get("type") == "teacher_takeover" for f in sent), "the teacher did not take over"
    [student] = [f["data"] for f in sent if f.get("type") == "metrics" and not f.get("teacher")]
    [teacher] = [f["data"] for f in sent if f.get("type") == "metrics" and f.get("teacher")]
    [saved] = _saved_through_route(monkeypatch, chunks)

    assert saved["round_texts"] == student["round_texts"] + teacher["round_texts"] == [
        "Let me look.", "I can't find it.", "Checking the mounts.", "It is under /data."]
    assert saved["round_models"] == [STUDENT, STUDENT, "big-model", "big-model"]
    assert [(e["round"], e["tool"]) for e in saved["tool_events"]] == [(1, "bash"), (3, "update_plan")]
    # The banner after the student's last round, the teacher's note at the end.
    assert [(n["type"], n.get("round")) for n in saved["agent_notes"]] == [
        ("teacher_takeover", 2), ("skill_save_failed", None)]
    # The reply's figures are the teacher's — the footer the turn ends on —
    # and the student's are kept as the run before it.
    assert saved["model"] == "big-model" and saved["requested_model"] == "big-model"
    assert saved["usage_buckets"] == teacher["usage_buckets"]
    [earlier] = saved["earlier_runs"]
    assert earlier["last_round"] == 2
    assert earlier["model"] == STUDENT and earlier["requested_model"] == STUDENT
    assert earlier["usage_buckets"] == student["usage_buckets"]
    assert "round_texts" not in earlier and "tool_events" not in earlier


def test_a_turn_the_teacher_never_answered_is_saved_as_before(monkeypatch):
    """No teacher record: one run, no earlier one."""
    from test_a_reload_keeps_the_turns_notes import _STUDENT, _frame
    saved = _saved_through_route(monkeypatch, _STUDENT + [
        _frame({"type": "escalation_failed", "reason": "teacher endpoint not resolvable: x"}),
        "data: [DONE]\n\n"])
    assert saved[0]["round_texts"] == ["Let me look.", "I can't find it."]
    assert "earlier_runs" not in saved[0]


def test_a_teacher_that_failed_is_saved_with_the_students_rounds_too(monkeypatch):
    """A teacher whose own model failed ends in its `agent_terminal`, which the
    route saves from — the same merge."""
    from test_a_reload_keeps_the_turns_notes import _STUDENT, _frame
    saved = _saved_through_route(monkeypatch, _STUDENT + [
        _frame({"type": "teacher_takeover", "teacher_model": "big", "model": "big"}),
        _frame({"delta": "Checking", "teacher": True}),
        _frame({"type": "agent_terminal", "teacher": True, "data": {
            "failed": True, "failure": {"status": 502}, "model": "big",
            "round_texts": ["Checking\n\n[Agent stopped: Model request failed (HTTP 502)]"]}}),
    ])
    assert saved[0]["round_texts"] == [
        "Let me look.", "I can't find it.", "Checking\n\n[Agent stopped: Model request failed (HTTP 502)]"]
    assert saved[0]["failed"] is True and saved[0]["earlier_runs"][0]["last_round"] == 2


# ── live and reloaded, side by side ─────────────────────────────────────────

_VIEW = r"""
const _words = (n) => (n ? n.textContent.replace(/\s+/g, ' ').trim() : '');
const _NOTES = ['rounds-exhausted', 'budget-exceeded-note', 'teacher-takeover-banner', 'skill-saved-note',
                'escalation-failed-note', 'context-compacted-note'];
/** What a person reads, top to bottom: text, cards (and the step each names),
 *  notes and stop lines.
 *  Hidden bubbles and wait spinners are not read; a tool fence in a step's
 *  text is not shown by either stream. */
function view(box) {
  const out = [];
  for (const n of box.children) {
    const cls = n._classes();
    if ((n.style && n.style.display === 'none') || cls.includes('agent-thinking-dots')) continue;
    if (cls.includes('agent-thread')) {
      // Each card: what it ran, and the step its badge names.
      out.push(['thread', n.querySelectorAll('.agent-thread-node').map((c) =>
        _words(c.querySelector('.agent-thread-tool')) + ' #' + _words(c.querySelector('.agent-thread-round')))]);
    } else if (cls.includes('agent-stop')) {
      out.push(['stop', _words(n.querySelector('.agent-stop-headline'))]);
    } else if (_NOTES.some((k) => cls.includes(k))) {
      out.push([_NOTES.find((k) => cls.includes(k)), _words(n)]);
    } else if (cls.includes('msg')) {
      const t = _words(n.querySelector('.stream-content') || n.querySelector('.body'))
        .replace(/```[\s\S]*?```/g, '').replace(/\s+/g, ' ').trim();
      if (t) out.push(['text', t]);
    }
  }
  return out;
}
"""


@pytest.fixture(scope="module")
def live_sandbox(tmp_path_factory):
    if not shutil.which("node"):
        pytest.skip("node binary not on PATH")
    d = _make_sandbox(tmp_path_factory.mktemp("teacherlive"), JS / "agentThread.js",
                      resumed._SHIM, resumed._STUBS)
    for name in ("agentMeter.js", "agentStops.js", "spinner.js", "agentTurn.js",
                 "chatModelProvenance.js", "chatStreamErrors.js"):
        shutil.copy(JS / name, d / name)
    return d


_RELOAD_STUBS = dict(_CARD_STUBS, **{
    "ui.js": ui_default_stub(
        "showToast: () => {}, copyToClipboard: () => {},\n"
        "showError: (m) => { (globalThis.errors = globalThis.errors || []).push(String(m)); },\n"
        "el: (id) => document.getElementById(id), debounce: (f) => f,\n"
        "autoResize: () => {}, scrollHistory: () => {}, formatBytes: (n) => String(n),"),
})


@pytest.fixture(scope="module")
def reload_sandbox(tmp_path_factory):
    """The real `chatRenderer.js` over the shim that parses markup, so a card's
    words can be read the way the live view's are."""
    if not shutil.which("node"):
        pytest.skip("node binary not on PATH")
    return _make_sandbox(tmp_path_factory.mktemp("teacherreload"), JS / "chatRenderer.js",
                         resumed._SHIM, _RELOAD_STUBS)


def live_view(sandbox, events) -> list:
    return resumed._page(sandbox, _VIEW + """
        const events = %s;
        runLive(events, []);
        console.log(JSON.stringify(view(history)));
    """ % json.dumps(events))


_RELOAD = r"""
import { document, Node } from './shim.js';
// A browser keeps an element's text when a child is appended after it (the
// heading's model name, then its time); the base shim drops it.
const _append = Node.prototype.appendChild;
Node.prototype.appendChild = function (n) {
  if (this.childNodes.length === 0 && this._text && this.tagName !== '#TEXT') {
    const t = new Node('#text');
    t._text = this._text;
    this._text = '';
    t.parentNode = this;
    this.childNodes.push(t);
  }
  return _append.call(this, n);
};
const history = document.body.appendChild(new Node('div'));
history.setAttribute('id', 'chat-history');
const { addMessage } = await import('./chatRenderer.js');
globalThis.errors = [];
""" + _VIEW + r"""
/** Each bubble: its heading (without the time) and the figure its footer shows. */
function bubbles(box) {
  return box.children.filter((n) => n._classes().includes('msg')).map((n) => {
    const role = n.querySelector('.role');
    const heading = !role ? '' : (role.childNodes.length
      ? role.childNodes.filter((c) => !(c._classes && c._classes().includes('role-timestamp')))
        .map((c) => c.textContent).join('').trim()
      : role.textContent.trim());
    const footer = n.querySelector('.msg-footer');
    return { text: _words(n.querySelector('.body')), heading,
             footer: footer ? _words(footer.querySelector('.response-metrics')) : null };
  });
}
"""


def reload_view(sandbox, content, metadata) -> dict:
    return _run(sandbox, _RELOAD, """
        addMessage('assistant', %s, %s, %s);
        console.log(JSON.stringify({ view: view(history), bubbles: bubbles(history), errors: globalThis.errors }));
    """ % (json.dumps(content), json.dumps(STUDENT), json.dumps(metadata)))


@node_only
def test_a_reloaded_takeover_says_what_the_live_stream_said(monkeypatch, live_sandbox, reload_sandbox):
    """The row's `Verify:`. One real takeover: the live stream's arms draw its
    frames; the saved record is drawn by the history renderer. The student's
    attempt, the banner and the teacher's answer, in the order they streamed —
    the same on both."""
    chunks = recorded_takeover(monkeypatch)
    [saved] = _saved_through_route(monkeypatch, chunks)
    live = live_view(live_sandbox, frames(chunks) + ["[DONE]"])
    reloaded = reload_view(reload_sandbox, "reply", saved)
    assert reloaded["errors"] == []
    kinds = [kind for kind, _ in live]
    assert kinds == ["text", "thread", "text", "teacher-takeover-banner",
                     "text", "thread", "text", "escalation-failed-note"], live
    assert [words for kind, words in live if kind == "text"] == [
        "Let me look.", "I can't find it.", "Checking the mounts.", "It is under /data."]
    assert live[3][1].startswith("Teacher takeover: escalating to big-model@lab — agent reply matched give-up")
    # The teacher's run numbers its own steps, on its cards as on its meter.
    assert [words for kind, words in live if kind == "thread"] == [["Terminal #1"], ["update_plan #1"]]
    assert reloaded["view"] == live


@node_only
def test_the_students_rounds_are_headed_and_footed_from_the_students_record(monkeypatch, reload_sandbox):
    """Live, the student's bubbles are headed with the student's model and its
    last one has the footer its `metrics` drew; the teacher's are headed with
    the teacher's (`B922`) and end on the teacher's footer. Headed from the
    teacher's record, a student's round read *big-model -> small-local-model*."""
    chunks = recorded_takeover(monkeypatch)
    [saved] = _saved_through_route(monkeypatch, chunks)
    # Figures a person can tell apart: each footer says its own run's speed.
    saved["earlier_runs"][0]["tokens_per_second"] = 11
    saved["tokens_per_second"] = 99
    out = reload_view(reload_sandbox, "reply", saved)
    assert out["errors"] == []
    assert [(b["text"], b["heading"], b["footer"]) for b in out["bubbles"]] == [
        ("Let me look.", STUDENT, None),
        ("I can't find it.", STUDENT, "11 tok/s"),
        ("Checking the mounts.", "big-model", None),
        ("It is under /data.", "big-model", "99 tok/s"),
    ], out["bubbles"]
