# SPDX-License-Identifier: AGPL-3.0-or-later
"""`B1572` — an Agent-mode turn whose context was trimmed to fit says what the
trim left out, where the person reads the reply.

`D-2026-10-29-01` §4, the owner: *"Keep 24k, name the cut."* An unproven
window keeps the 24,000-character attachment allowance (`D-2026-08-26-06`);
when the trim then drops memory or retrieved context to fit, it says which.

**Measured on the tree before this row**, through `/api/chat_stream`: a model
whose window nothing proves, one saved memory, and 24,000 characters of
attachments in Agent mode. The loop trimmed the request to its 6,000-token
input budget — five messages to two, 10,190 tokens to 4,964: the saved memory,
the uploads' list and the turn's note dropped, the instructions cut to 2,000
characters, the message itself to 14,478 of its 24,261 — and the stream carried
no `context_trimmed` event and the saved reply no trim at all; the turn's
`memories_used` still named the memory. The only trace was a log line.

Now the loop's trim sends the `context_trimmed` event the chat already draws
(`trimNoticeText`), naming what it left out (`context_compactor.trim_left_out`),
and saves it on the reply (`context_trim_left_out`), so the reload draws the
same line (`trimFromRecord`); live, the line is drawn above the reply as well
as said in the toast.

Driven (`Law 20`): `capture.Server` boots this checkout's `app.py`; the model
is `demo_model.DemoModel` under a name no table knows, keeping every request;
the saved reply is read back through `GET /api/history/{id}`; the sentence is
the real `agentStops.js`, and the reloaded line the real `addMessage`, and the
live line `chat.js`'s own `context_trimmed` arm, under node.
"""
from __future__ import annotations

import json
import re
import secrets
import shutil
import sys
from pathlib import Path

import pytest

from tests.helpers.source_text import blank  # B290
from test_a_chat_turns_compaction_survives_a_reload import _STUBS, CHAT_RENDERER  # noqa: E402
from test_tool_effect_surfaces_js import _CARD_SHIM, _make_sandbox, _run  # noqa: E402

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "scripts" / "showcase"))

import demo_model  # noqa: E402
import seed  # noqa: E402

#: A name no table of known windows matches, so nothing proves its window.
MODEL = "plain-unknown-model"
WORDS = "Use what I gave you and tell me the code word."
MEMORY = "MEMWORDQ7"
SCRIPT = [{"key": "c", "title": "Ctx", "turns": [{"user": WORDS, "steps": [{"say": "OK."}]}]}]
LEFT_OUT = ["your saved memory", "the middle of your message"]

node_only = pytest.mark.skipif(not shutil.which("node"), reason="node binary not on PATH")


@pytest.fixture(scope="module")
def world(tmp_path_factory):
    import capture
    import httpx

    work = tmp_path_factory.mktemp("b1572")
    data = work / "data"
    data.mkdir()
    server = capture.Server(sys.executable, data, capture._free_port(),
                            extra_env={"PANTHEON_DISABLE_MCP": "1", "PANTHEON_UPLOAD_BURST_LIMIT": "100"})
    try:
        server.start(timeout=150)
    except RuntimeError as e:
        server.stop()
        pytest.fail(f"{e}\n{server.log_path.read_text(encoding='utf-8', errors='replace')[-3000:]}")
    log: list = []
    try:
        client = httpx.Client(base_url=server.base, timeout=180)
        seed.setup_admin(client, secrets.token_urlsafe(18))
        seed._ok(client.post("/api/memory/add", json={
            "text": f"The code word for the garden shed is {MEMORY}.", "category": "fact",
            "source": "user"}), "memory")
        with demo_model.DemoModel(log=log, conversations=SCRIPT, model_id=MODEL) as m:
            ep = seed._ok(client.post("/api/model-endpoints", data={
                "name": "Box", "base_url": m.base_url, "supports_tools": "true",
                "require_models": "true"}), "endpoint")["id"]
            yield client, ep, log
    finally:
        server.stop()


def _turn(world, files=0):
    """One Agent-mode turn, with `files` text attachments of 12,000 characters
    each; the frames, what the model was sent, and the saved reply's record."""
    client, ep, log = world
    sess = seed._ok(client.post("/api/session", data={"endpoint_id": ep, "model": MODEL}), "chat")
    sid = sess.get("session_id") or sess.get("id")
    form = {"message": WORDS, "session": sid, "mode": "agent", "plan_mode": "false",
            "selected_model": MODEL, "selected_endpoint_id": ep,
            "allow_bash": "false", "allow_web_search": "false"}
    if files:
        parts = [("files", (f"part{i}.txt", (f"FILE{i}:" + chr(65 + i) * 11_993).encode(), "text/plain"))
                 for i in range(files)]
        up = seed._ok(client.post("/api/upload", files=parts, data={"session_id": sid}), "upload")
        form["attachments"] = json.dumps([f["id"] for f in up["files"]])
    start = len(log)
    resp = client.post("/api/chat_stream", data=form)
    assert resp.status_code == 200, resp.text[:300]
    events = list(seed._sse_events(resp.text))
    asked = [e for e in log[start:] if e.get("stream")]
    assert asked, "the model was never asked"
    sent = "\n".join(demo_model._text(m.get("content")) for m in asked[0]["messages"])
    history = seed._ok(client.get(f"/api/history/{sid}"), "history")["history"]
    [reply] = [h.get("metadata") or {} for h in history if h.get("role") == "assistant"]
    return events, sent, reply


@pytest.fixture(scope="module")
def plain(world):
    return _turn(world)


@pytest.fixture(scope="module")
def crowded(world):
    return _turn(world, files=2)


def _trims(events):
    return [e for e in events if e.get("type") == "context_trimmed"]


def test_the_premise_a_turn_with_room_keeps_the_memory_and_says_nothing(plain):
    events, sent, reply = plain
    assert MEMORY in sent, "the saved memory reached the model"
    assert _trims(events) == [] and not reply.get("context_trimmed")


def test_an_unproven_window_keeps_the_24000_character_allowance(crowded):
    """The owner's "keep 24k": two 12,000-character files fill the 24,000
    characters, the first read whole and the second all but its last few
    dozen (its own header line is in the allowance too) — a window scaled
    down to 6,000 tokens would have given both together under 12,000."""
    events, _sent, _reply = crowded
    [attached] = [e for e in events if e.get("type") == "attachments"]
    first, second = attached["data"]
    assert not first.get("reach_note"), first
    given = int(re.search(r"\(([\d,]+) characters\)", second["reach_note"]).group(1).replace(",", ""))
    assert 11_800 < given < 12_000, second["reach_note"]


def test_the_trim_that_left_out_the_memory_says_so_in_the_stream(crowded):
    """The row's `Verify:`: *or the reply says what was cut*."""
    events, sent, _reply = crowded
    assert MEMORY not in sent, "the premise: the trim made room by dropping the memory"
    [trim] = _trims(events)
    data = trim["data"]
    assert data["left_out"] == LEFT_OUT, data
    assert data["messages_after"] < data["messages_before"]
    assert data["tokens_after"] < data["tokens_before"]
    first_step = next(i for i, e in enumerate(events) if e.get("type") in ("agent_step", "delta")
                      or "delta" in e)
    assert events.index(trim) < first_step, "said before the reply it shaped"


def test_the_saved_reply_keeps_what_was_left_out(crowded):
    events, _sent, reply = crowded
    [trim] = _trims(events)
    assert reply.get("context_trimmed") is True
    assert reply.get("context_trim_left_out") == LEFT_OUT
    assert reply.get("context_messages_before_trim") == trim["data"]["messages_before"]
    assert reply.get("context_messages_after_trim") == trim["data"]["messages_after"]


# ── where the person reads it ───────────────────────────────────────────────

@pytest.fixture(scope="module")
def sandbox(tmp_path_factory):
    if not shutil.which("node"):
        pytest.skip("node binary not on PATH")
    return _make_sandbox(tmp_path_factory.mktemp("b1572js"), CHAT_RENDERER, _CARD_SHIM, _STUBS)


_TRIM_ARM = "} else if (json.type === 'context_trimmed') {"


def _live_arm() -> str:
    """`chat.js`' own `context_trimmed` arm, comments blanked (`B290`), cut to
    the next arm — the way `tests/test_compaction_notice_js.py` cuts it."""
    src = blank(ROOT / "static" / "js" / "chat.js")
    start = src.index(_TRIM_ARM)
    assert src.count(_TRIM_ARM) == 1
    end = src.index("} else if (", start + len(_TRIM_ARM))
    return "if (false) {\n" + src[start:end] + "}\n"


_PAGE = r"""
import { document, history, Node } from './shim.js';
const { addMessage } = await import('./chatRenderer.js');
const { trimNoticeText, renderAgentNote } = await import('./agentStops.js');
Object.defineProperty(Node.prototype, 'previousElementSibling', { get() {
  const kids = this.parentNode ? this.parentNode.children : [];
  const at = kids.indexOf(this);
  return at > 0 ? kids[at - 1] : null;
} });
const text = (n) => n.textContent.replace(/\s+/g, ' ').trim();
const shape = () => history.children.map((n) => {
  const cls = String(n.className || '');
  if (cls.includes('context-trimmed-note')) return 'trim:' + text(n);
  if (cls.includes('reply-holder')) return 'reply';
  return cls.includes('msg') ? 'msg' : cls;
});
"""


@node_only
def test_the_line_names_the_cut_live_and_after_a_reload(crowded, sandbox):
    events, _sent, reply = crowded
    [trim] = _trims(events)
    out = _run(sandbox, "", _PAGE + """
        const toasts = [];
        const uiModule = { showToast: (m) => toasts.push(String(m)) };
        const holder = history.appendChild(new Node('div'));
        holder.className = 'reply-holder';
        function draw(json, _isBg) {
        %s
        }
        draw(%s, false);
        draw(%s, false);   // a later notice in the same turn replaces the line
        const live = shape();
        history.children.slice().forEach((n) => n.remove());
        addMessage('assistant', 'OK.', 'plain-unknown-model', %s);
        console.log(JSON.stringify({ toasts, live, reloaded: shape(),
                                     said: trimNoticeText(%s) }));
    """ % (_live_arm(), json.dumps(trim), json.dumps(trim), json.dumps(reply), json.dumps(trim)))
    d = trim["data"]
    said = (f"Context trimmed for this model ({d['messages_after']}/{d['messages_before']} "
            "messages sent) — left out to fit: your saved memory and the middle of your message")
    assert out["said"] == said
    assert out["toasts"] == [said, said]
    assert out["live"] == ["trim:" + said, "reply"], "drawn once, above the reply it shaped"
    assert "trim:" + said in out["reloaded"], out["reloaded"]


# ── the words, and what is never named ─────────────────────────────────────

def test_retrieved_documents_and_memory_are_named_by_the_block_not_the_role():
    """Through the real `trim_for_context`, over the real envelopes the chat
    builds its context with."""
    from src.context_compactor import trim_for_context, trim_left_out
    from src.prompt_security import own_context_message, untrusted_context_message

    memory = own_context_message("saved memory: pinned context", "The dog is called Rex.")
    documents = untrusted_context_message("retrieved documents", "Relevant documents:\n" + "d" * 2000)
    mine = {"role": "user", "content": "What is my dog called?"}
    before = [{"role": "system", "content": "You are a helpful assistant."}, memory, documents, mine]
    after = trim_for_context(before, 400, reserve_tokens=0)
    assert memory not in after and documents not in after and mine in after
    assert trim_left_out(before, after) == ["your saved memory", "the documents retrieved for it"]
    assert trim_left_out(before, before) == [], "a trim that kept everything names nothing"


def test_a_chat_mode_trim_carries_the_same_words_to_its_frame_and_record():
    """Chat mode trims in `build_chat_context` (`routes/chat_helpers.py`), and
    its frame and saved record go through the same builders, with what the
    agent loop's own trim already put on an agent turn's record kept beside
    it, each said once."""
    from types import SimpleNamespace
    from routes.chat_routes import _apply_shaping_metrics, _ctx_shaping
    from src.context_compactor import trimmed_frame

    ctx = SimpleNamespace(context_trimmed=True, context_length=8192,
                          context_messages_before_trim=6, context_messages_after_trim=3,
                          context_tokens_before_trim=9000, context_tokens_after_trim=4000,
                          context_trim_left_out=["the documents retrieved for it"],
                          was_compacted=False)
    frame = trimmed_frame(ctx.context_length, _ctx_shaping(ctx, "trim"), ctx.context_trim_left_out)
    assert frame == {"type": "context_trimmed", "data": {
        "context_length": 8192, "messages_before": 6, "messages_after": 3,
        "tokens_before": 9000, "tokens_after": 4000,
        "left_out": ["the documents retrieved for it"]}}
    metrics = _apply_shaping_metrics(
        {"context_trimmed": True, "context_trim_left_out": ["your saved memory",
                                                            "the documents retrieved for it"]}, ctx)
    assert metrics["context_trim_left_out"] == ["your saved memory", "the documents retrieved for it"]
    assert metrics["context_messages_after_trim"] == 3
    bare = trimmed_frame(8192, _ctx_shaping(ctx, "trim"))
    assert "left_out" not in bare["data"], "a trim that left out nothing names nothing"
