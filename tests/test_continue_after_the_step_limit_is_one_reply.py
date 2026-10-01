# SPDX-License-Identifier: AGPL-3.0-or-later
"""`B941` — Continue ▸ after the step limit reads as one reply, live and after a
reload, with no stray prompt.

Three things were wrong, each found by `B915` and read, not driven, until now:

  * **Live.** Continue ▸ hands the continuation the turn's first bubble, and the
    end of the continuation merged its text into that bubble, as a stopped
    reply's Continue does. In an agent turn the first bubble is usually hidden
    (it wrote nothing before its first tool), so the old and the new text were
    rendered into a hidden bubble, the continuation's own last bubble was
    removed, and the continued answer left the screen until a reload.
  * **Server.** `merge-last-assistant` removed the message between the two
    replies only when it said *previous response was interrupted*. The step
    limit's prompt (*You hit the step limit before finishing…*) does not, so after
    a reload it was a user bubble below the merged reply.
  * **Metadata.** The merge was `{**meta1, **meta2}`: the continuation's rounds
    replaced the first run's, and the first run's stops and notes — its step
    limit and its Continue among them — survived only when the continuation had
    none, placed by the first run's round numbers among the continuation's.

Now the continuation stays where it was drawn and its first bubble becomes a step
of the reply (`_joinContinuedSteps`); the server joins the two runs as one reply
(`merge_runs`, the merge `B939` saves a teacher's turn with) and removes the
prompt; a prompt no merge removed is hidden on reload like the interrupted
reply's.

Driven (`Law 20`): the real loop's records through the real route and save; the
real merge route; the real Continue button, `setPendingContinue`, the end of the
live stream's final render and `_joinContinuedSteps` cut out of `chat.js`; the
real `addMessage`; `sessions.js`'s own history drawing.
"""

import asyncio
import json
import shutil
from pathlib import Path
from types import SimpleNamespace

import pytest

from core.models import ChatMessage
import routes.history_routes as history_routes
from src.agent_stops import STEP_LIMIT_CONTINUE_PROMPT
from tests.helpers.esc_stub import ui_default_stub  # B874
from tests.helpers.js_source import js_binding, js_definition  # B876
from tests.helpers.source_text import blank_text  # B290
from test_a_reload_keeps_the_turns_notes import _loop_chunks, _plan, _saved_through_route  # noqa: E402
from test_tool_effect_surfaces_js import _CARD_SHIM, _CARD_STUBS, _make_sandbox, _run  # noqa: E402

ROOT = Path(__file__).resolve().parents[1]
JS = ROOT / "static" / "js"
CHAT_JS = JS / "chat.js"
SESSIONS_JS = JS / "sessions.js"

node_only = pytest.mark.skipif(not shutil.which("node"), reason="node binary not on PATH")


# ── the server: one reply from two runs ─────────────────────────────────────


class _Session:
    def __init__(self, history):
        self.history = history


class _Manager:
    def __init__(self, session):
        self.session = session

    def get_session(self, session_id):
        return self.session

    def save_sessions(self):
        pass


class _Rows:
    """The database's copy of the conversation, mirrored from the in-memory
    one, so the merge's deletions there can be seen too."""

    def __init__(self, history):
        self.rows = [SimpleNamespace(role=m.role, content=m.content, meta_data=json.dumps(m.metadata or {}),
                                     timestamp=i) for i, m in enumerate(history)]
        self.deleted = []

    def __call__(self):
        return self

    def query(self, *_a):
        return self

    def filter(self, *_a):
        return self

    def order_by(self, *_a):
        return self

    def all(self):
        return [r for r in self.rows if r not in self.deleted]

    def delete(self, row):
        self.deleted.append(row)

    def commit(self):
        pass

    def close(self):
        pass


def _merge(monkeypatch, history):
    """`POST /api/session/{id}/merge-last-assistant`, the real handler."""
    monkeypatch.setattr(history_routes, "_verify_session_owner", lambda *a, **k: None)
    rows = _Rows(history)
    monkeypatch.setattr(history_routes, "SessionLocal", rows)
    session = _Session(history)
    router = history_routes.setup_history_routes(_Manager(session))
    [handler] = [r.endpoint for r in router.routes if getattr(r, "path", "").endswith("/merge-last-assistant")]

    async def body():
        return {"separator": "\n\n"}

    result = asyncio.run(handler(request=SimpleNamespace(json=body), session_id="s1"))
    return result, session.history, rows


def _merged(monkeypatch, meta1, meta2):
    """The metadata the real merge route leaves on the joined reply."""
    _, after, _ = _merge(monkeypatch, [
        ChatMessage("user", "work through the list"),
        ChatMessage("assistant", "first", metadata=dict(meta1)),
        ChatMessage("user", STEP_LIMIT_CONTINUE_PROMPT),
        ChatMessage("assistant", "second", metadata=dict(meta2))])
    return [m for m in after if m.role == "assistant"][-1].metadata


def _two_runs(monkeypatch):
    """Two real replies, saved as the route saves them: a run that hit its
    two-step limit, and the run Continue ▸ started."""
    first = _saved_through_route(monkeypatch, _loop_chunks(
        monkeypatch, ["Working through the list.\n\n" + _plan(1), _plan(2)], max_rounds=2))[0]
    second = _saved_through_route(monkeypatch, _loop_chunks(
        monkeypatch, ["Picking up at step three.\n\n" + _plan(3), "All three are done."], max_rounds=4))[0]
    return first, second


def test_continue_joins_the_two_runs_into_one_reply_without_its_prompt(monkeypatch):
    first, second = _two_runs(monkeypatch)
    assert first["agent_notes"] == [{"type": "rounds_exhausted", "rounds": 2, "round": 2}]
    history = [ChatMessage("user", "work through the list"),
               ChatMessage("assistant", "Working through the list.", metadata=dict(first)),
               ChatMessage("user", STEP_LIMIT_CONTINUE_PROMPT),
               ChatMessage("assistant", "Picking up at step three.\n\nAll three are done.", metadata=dict(second))]
    continuation = history[3].content
    result, after, rows = _merge(monkeypatch, history)
    assert result == {"status": "ok", "merged": True}
    # No prompt left between them, here or in the database.
    assert [m.role for m in after] == ["user", "assistant"]
    assert {r.content for r in rows.deleted} == {STEP_LIMIT_CONTINUE_PROMPT, continuation}
    meta = after[1].metadata
    # The first run's rounds, then the continuation's, numbered after them.
    assert meta["round_texts"] == first["round_texts"] + second["round_texts"]
    assert [e["round"] for e in meta["tool_events"]] == [1, 2, 3]
    # The step limit's offer was what Continue took; it is not drawn again.
    assert not any(n.get("type") == "rounds_exhausted" for n in meta.get("agent_notes", []))
    # The first run's figures, for the footer the live stream drew under it.
    [earlier] = meta["earlier_runs"]
    assert earlier["last_round"] == 2 and earlier["usage_buckets"] == first["usage_buckets"]
    assert meta["usage_buckets"] == second["usage_buckets"]


def test_the_continuations_own_notes_move_with_its_rounds(monkeypatch):
    first = {"round_texts": ["a", "b"], "agent_notes": [
        {"type": "skill_saved", "name": "x", "round": 1},
        {"type": "rounds_exhausted", "rounds": 2, "round": 2}]}
    second = {"round_texts": ["c"], "tool_events": [{"round": 1, "tool": "bash"}], "agent_notes": [
        {"type": "compacted", "data": {}, "round": 0},
        {"type": "budget_exceeded", "limit": 3, "used": 3}]}
    meta = _merged(monkeypatch, first, second)
    assert [(n["type"], n.get("round")) for n in meta["agent_notes"]] == [
        ("skill_saved", 1), ("compacted", 2), ("budget_exceeded", None)]
    assert meta["tool_events"] == [{"round": 3, "tool": "bash"}]


def test_a_stopped_replys_continue_merges_as_it_always_did(monkeypatch):
    """Two replies that are not agent runs: every key as it was, the second's
    where both have one, and no longer stopped (`Law 1`)."""
    meta = _merged(monkeypatch,
                   {"stopped": True, "model": "m", "web_sources": [1], "round_texts": ["only one"]},
                   {"model": "m2", "response_time": 3})
    assert meta == {"model": "m2", "web_sources": [1], "round_texts": ["only one"], "response_time": 3}


@pytest.mark.parametrize("prompt, removed", [
    (STEP_LIMIT_CONTINUE_PROMPT, True),
    ("Your previous response was interrupted. It ended with:\n\nfoo", True),
    ("a question the person typed in between", False),
])
def test_only_a_continue_prompt_between_the_two_is_removed(prompt, removed):
    a1, between, a2 = (SimpleNamespace(role="assistant", content="a1"), SimpleNamespace(role="user", content=prompt),
                       SimpleNamespace(role="assistant", content="a2"))
    rows = history_routes._merge_continue_rows_to_delete([a1, between, a2], a1, a2)
    assert (between in rows) is removed and a2 in rows


def test_the_server_and_the_browser_send_the_same_prompt(tmp_path):
    if not shutil.which("node"):
        pytest.skip("node binary not on PATH")
    import subprocess
    shutil.copy(JS / "agentStops.js", tmp_path / "agentStops.js")
    (tmp_path / "case.mjs").write_text(
        "import { STEP_LIMIT_CONTINUE_PROMPT } from './agentStops.js';\n"
        "console.log(JSON.stringify(STEP_LIMIT_CONTINUE_PROMPT));\n", encoding="utf-8")
    out = subprocess.run(["node", "case.mjs"], cwd=tmp_path, capture_output=True, text=True, timeout=30)
    assert out.returncode == 0, out.stderr
    assert json.loads(out.stdout) == STEP_LIMIT_CONTINUE_PROMPT


# ── the browser ─────────────────────────────────────────────────────────────

_STUBS = dict(_CARD_STUBS, **{
    "ui.js": ui_default_stub(
        "showToast: () => {}, copyToClipboard: () => {},\n"
        "showError: (m) => { (globalThis.errors = globalThis.errors || []).push(String(m)); },\n"
        "el: (id) => document.getElementById(id), debounce: (f) => f,\n"
        "autoResize: () => {}, scrollHistory: () => {}, formatBytes: (n) => String(n),"),
})


@pytest.fixture(scope="module")
def sandbox(tmp_path_factory):
    if not shutil.which("node"):
        pytest.skip("node binary not on PATH")
    return _make_sandbox(tmp_path_factory.mktemp("continuesteps"), JS / "chatRenderer.js", _CARD_SHIM, _STUBS)


def _chat():
    return CHAT_JS.read_text(encoding="utf-8")


def _module_function(name: str) -> str:
    src = _chat()
    code = blank_text(src, "js")
    for prefix in ("export function ", "function "):
        if f"{prefix}{name}(" in code:
            at = code.index(f"{prefix}{name}(")
            return js_definition(src, at).replace("export function", "function", 1)
    return ""


def _end_of_stream_merge() -> str:
    """The continue merge at the end of `handleChatSubmit`'s final render. On
    a tree without `B941` it is the one text merge."""
    src = _chat()
    code = blank_text(src, "js")
    start = code.index("export async function handleChatSubmit(")
    handler = js_definition(src, start)
    hcode = code[start:start + len(handler)]
    steps = "if (_pendingContinue && _pendingContinueSteps) {"
    if steps in hcode:
        first = js_definition(handler, hcode.index(steps))
        rest = js_definition(handler, hcode.index("else if (_pendingContinue) {"))
        return first + " " + rest
    return js_definition(handler, hcode.index("if (_pendingContinue) {"))


_PAGE = r"""
import { document, Node, history } from './shim.js';
const chatRenderer = await import('./chatRenderer.js');
const { addMessage, createMsgFooter } = chatRenderer;
const { renderAgentNote } = await import('./agentStops.js');
const markdownModule = (await import('./markdown.js')).default;
globalThis.errors = [];
const composer = document.body.appendChild(new Node('textarea'));
composer.setAttribute('id', 'message');
const send = document.body.appendChild(new Node('button'));
send.className = 'send-btn';
const sent = [];
send.click = () => sent.push(composer.value);
const posted = [];
globalThis.fetch = (url, opts) => { posted.push({ url, body: JSON.parse(opts.body) }); return Promise.resolve({}); };
const API_BASE = '';
const sessionModule = { getCurrentSessionId: () => 's1' };
const text = (n) => n.textContent.replace(/\s+/g, ' ').trim();
/** What a person reads: visible bubbles (with a footer under them or not),
 *  threads, and notes. */
function view(box) {
  return box.children.filter((n) => !(n.style && n.style.display === 'none')).map((n) => {
    const cls = String(n.className || '');
    if (cls.includes('agent-thread')) return 'thread';
    if (cls.includes('msg-user')) return 'user:' + text(n.querySelector('.body'));
    if (cls.includes('msg')) return 'text:' + text(n.querySelector('.body')) + (n.querySelector('.msg-footer') ? ' +footer' : '');
    return cls;
  });
}
"""


def _live_page(body: str) -> str:
    return (_PAGE + "let _pendingContinue = null;\nlet _pendingContinueSteps = false;\n"
            + _module_function("setPendingContinue") + "\n"
            + (_module_function("_joinContinuedSteps") or "function _joinContinuedSteps() {}") + "\n"
            + "window.chatModule = { setHideUserBubble() {}, setPendingContinue };\n"
            + body.replace("__MERGE__", _end_of_stream_merge()))


# The two runs as the live stream draws them, and their saved records.
FIRST = {"round_texts": ["", "Step two checked b."], "round_models": ["m", "m"],
         "tool_events": [{"round": 1, "tool": "update_plan", "command": "{}", "output": "ok", "exit_code": 0}],
         "agent_notes": [{"type": "rounds_exhausted", "rounds": 2, "round": 2}],
         "model": "m", "response_time": 4.0, "_db_id": "a-1"}
SECOND = {"round_texts": ["Picking up at step three.", "All three are done."], "round_models": ["m", "m"],
          "tool_events": [{"round": 1, "tool": "update_plan", "command": "{}", "output": "ok", "exit_code": 0}],
          "model": "m", "response_time": 2.0, "_db_id": "c-9"}

_LIVE = r"""
const bubble = (cls, words, { hidden = false, footer = false, id = '' } = {}) => {
  const b = history.appendChild(new Node('div'));
  b.className = cls;
  const role = b.appendChild(new Node('div'));
  role.className = 'role';
  const stamp = role.appendChild(new Node('span'));
  stamp.className = 'role-timestamp';
  const body = b.appendChild(new Node('div'));
  body.className = 'body';
  if (words) { body.textContent = words; b.dataset.raw = words; }
  if (hidden) b.style.display = 'none';
  if (id) b.dataset.dbId = id;
  if (footer) b.appendChild(createMsgFooter(b));
  return b;
};
const thread = () => { const t = history.appendChild(new Node('div')); t.className = 'agent-thread'; return t; };
// The run that hit the limit, as its final render left it: the first bubble
// wrote nothing and is hidden; step 2's bubble has the answer so far and the
// footer; the step limit's note offers Continue, from the first bubble.
const first = bubble('msg msg-ai', '', { hidden: true, id: 'a-1' });
thread();
bubble('msg msg-ai msg-continuation', 'Step two checked b.', { footer: true });
const note = renderAgentNote(history, { type: 'rounds_exhausted', rounds: 2 }, { reply: first });
note.querySelector('.continue-btn').listeners.click.forEach((fn) => fn({}));
// The continuation, as the live stream drew it, up to the end of its render.
const holder = bubble('msg msg-ai', 'Picking up at step three.', { id: 'c-9' });
thread();
const footerTarget = bubble('msg msg-ai msg-continuation', 'All three are done.', { footer: true });
__MERGE__
console.log(JSON.stringify({
  view: view(history), sent, posted, errors: globalThis.errors,
  firstBody: first.querySelector('.body').textContent, footerOnPage: !!footerTarget.parentNode,
  holder: { cls: holder.className, stamp: !!holder.querySelector('.role-timestamp'), id: holder.dataset.dbId || null },
}));
"""


@node_only
def test_continued_steps_stay_on_screen_and_read_as_the_reply_they_carry_on(sandbox):
    out = _run(sandbox, "", _live_page(_LIVE))
    assert out["errors"] == []
    assert out["sent"] == [STEP_LIMIT_CONTINUE_PROMPT]
    # The continued answer is on the screen, where it was drawn.
    assert out["footerOnPage"], "the continuation's last bubble was removed"
    assert out["view"] == ["thread", "text:Step two checked b. +footer", "text:Picking up at step three.",
                           "thread", "text:All three are done. +footer"], out["view"]
    assert out["firstBody"] == "", "the continuation was merged into the hidden first bubble"
    # Its first bubble is a step of the reply it carries on: no time of its own,
    # and it edits and deletes the reply the server joined it to.
    assert "msg-continuation" in out["holder"]["cls"].split()
    assert out["holder"]["stamp"] is False and out["holder"]["id"] == "a-1"
    # And the server is asked to join the two replies.
    assert [p["url"] for p in out["posted"]] == ["/api/session/s1/merge-last-assistant"]


@node_only
def test_the_reload_reads_as_the_live_stream_did(monkeypatch, sandbox):
    """The row's `Verify:`. The same two runs: the live stream after Continue,
    and the reply the real merge saved, drawn by the history renderer — the
    same reply, with no prompt and no second offer."""
    live = _run(sandbox, "", _live_page(_LIVE))["view"]
    merged = _merged(monkeypatch, FIRST, SECOND)
    out = _run(sandbox, "", _PAGE + """
        addMessage('assistant', 'reply', 'm', %s);
        console.log(JSON.stringify({ view: view(history), errors: globalThis.errors }));
    """ % json.dumps(merged))
    assert out["errors"] == []
    assert out["view"] == live, (out["view"], live)


# ── a prompt no merge removed ───────────────────────────────────────────────


def _history_drawing() -> str:
    """`sessions.js`'s own drawing of one saved message, and what it reads."""
    src = SESSIONS_JS.read_text(encoding="utf-8")
    code = blank_text(src, "js")
    parts = [js_binding(src, "HISTORY_DISPLAY_CHAR_LIMIT") + ";",
             js_binding(src, "HISTORY_DISPLAY_TAIL_CHARS") + ";"]
    for name in ("_displayHistoryContent", "_stripUserVisionBlocks", "_renderHistoryMessage"):
        parts.append(js_definition(src, code.index(f"function {name}(")))
    return "\n".join(parts)


@node_only
def test_a_continuation_that_was_never_merged_shows_no_prompt_and_no_offer(sandbox):
    """Stopped or failed, the continuation never reached the merge, and the
    prompt stays in the conversation. A reload hides it, as it hides the
    interrupted reply's, and it still withdraws the offer it answered."""
    out = _run(sandbox, "", _PAGE + """
        const { STEP_LIMIT_CONTINUE_PROMPT, withdrawContinueOffers } = await import('./agentStops.js');
        const _addHistoryMessageWithFullRenderer = (role, content, model, meta) =>
          [chatRenderer.addMessage(role, content, model, meta)];
        %s
        for (const msg of %s) _renderHistoryMessage(msg, 'm');
        // The step limit's offer (a stopped reply's own Continue is another button).
        const offers = history.querySelectorAll('.rounds-exhausted')
          .reduce((n, note) => n + note.querySelectorAll('.continue-btn').length, 0);
        console.log(JSON.stringify({ view: view(history), offers, errors: globalThis.errors }));
    """ % (_history_drawing(), json.dumps([
        {"role": "user", "content": "work through the list"},
        {"role": "assistant", "content": "Step two checked b.", "metadata": FIRST},
        {"role": "user", "content": STEP_LIMIT_CONTINUE_PROMPT},
        {"role": "assistant", "content": "Picking up at step three.", "metadata": {"model": "m", "stopped": True}},
    ])))
    assert out["errors"] == []
    assert not any(v.startswith("user:You hit the step limit") for v in out["view"]), out["view"]
    assert out["offers"] == 0, "the offer the prompt answered is still offered"


# ── the step a card names ───────────────────────────────────────────────────


@node_only
def test_a_continuations_cards_name_its_own_steps(monkeypatch):
    """Live, the continuation's run numbers its steps from 1 — its cards and
    its meter say step 1, 2 — and the merge places them after the first run's
    rounds. A reloaded card names the step it named live, whatever round of
    the reply it is placed in: a tool's, a refused call's and a verdict's."""
    import test_a_teachers_turn_reloads_as_it_streamed as teacher_file
    import test_a_resumed_stream_draws_what_the_live_one_drew as resumed
    import tempfile
    second = dict(SECOND, round_texts=["Picking up at step three.", "", "All three are done."],
                  tool_events=SECOND["tool_events"] + [
                      {"round": 2, "tool": "bash", "command": "rm -rf /tmp/x", "output": "refused", "blocked": True}],
                  verifier_findings=[{"round": 2, "outcome": "pass"}])
    merged = _merged(monkeypatch, FIRST, second)
    with tempfile.TemporaryDirectory() as d:
        sandbox = _make_sandbox(Path(d), JS / "chatRenderer.js", resumed._SHIM, teacher_file._RELOAD_STUBS)
        out = teacher_file.reload_view(sandbox, "reply", merged)
    assert out["errors"] == []
    cards = [words for kind, words in out["view"] if kind == "thread"]
    assert [[c.rsplit(" #", 1)[1] for c in thread] for thread in cards] == [["1"], ["1", "2", "2"]], cards
