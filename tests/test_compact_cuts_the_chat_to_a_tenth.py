# SPDX-License-Identifier: AGPL-3.0-or-later
"""`B1731` — *Compact* cuts the conversation hard, keeps what it can, and never
answers "failed" because a local model was slow.

Measured from the owner's context wheel, 2026-11-01: gpt-oss-20b on LM Studio,
a 6,000-token window, seven messages, the chat 1.1K of it, and *Compacting*
ending in *Compact failed*. The summary was asked of a reasoning model with 30
seconds, 1,024 tokens and three tries; the tail it kept was a fixed four to
eight messages, so a short chat hardly moved; and the template asked for up to
1,000 tokens whatever it replaced.

Driven: the planner and the summary source on real messages and the real
estimator; the summariser against a stand-in for `llm_call_async` that fails,
times out, or answers in harmony's inline channels; and the whole route in the
real app (`gated_app_probe`) against a real HTTP server that behaves like LM
Studio serving gpt-oss — once answering, once too slow to answer.
"""
from __future__ import annotations

import asyncio
import json
import threading
import time
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

import pytest

from core.models import ChatMessage
import src.context_compactor as cc
from src.model_context import estimate_tokens
from tests.helpers.gated_app import gated_app_probe


def _chat(n, words=40):
    return [ChatMessage("user" if i % 2 == 0 else "assistant",
                        f"message {i}: " + " ".join(f"w{i}x{j}" for j in range(words)))
            for i in range(n)]


def _tokens(rows):
    return sum(cc._row_tokens(r) for r in rows)


# ── the plan ────────────────────────────────────────────────────────────────

def test_the_owners_chat_is_cut_to_well_under_half():
    """Seven messages, ~1.1K tokens, a 6,000-token window: the old tail kept
    four of seven verbatim. The cut now leaves ~10% of the window at most, and
    never more than 40% of what the chat was."""
    rows = _chat(7, words=90)
    before = _tokens(rows)
    assert 900 < before < 1500
    plan = cc.plan_chat_compaction(rows, 6000)
    assert plan["ok"]
    assert plan["target_tokens"] <= min(600, int(before * 0.4))
    kept = _tokens(plan["recent"])
    assert kept + plan["summary_tokens"] <= plan["target_tokens"]
    assert len(plan["recent"]) < 4
    assert plan["older"] + plan["recent"] == rows


def test_a_long_chat_is_cut_to_a_tenth_of_its_window():
    rows = _chat(200, words=120)          # ~ 80K tokens
    window = 131072
    plan = cc.plan_chat_compaction(rows, window)
    assert plan["ok"]
    assert plan["target_tokens"] == int(window * cc.CHAT_TARGET_SHARE)
    assert plan["summary_tokens"] <= cc.SUMMARY_CAP_TOKENS
    after = plan["summary_tokens"] + _tokens(plan["recent"])
    assert after <= window * 0.10
    assert len(plan["recent"]) >= 10, "a big window keeps a real tail word for word"


def test_a_tool_result_never_starts_the_kept_tail():
    rows = _chat(10, words=60) + [
        ChatMessage("assistant", "checking"),
        ChatMessage("tool", "result " * 30),
        ChatMessage("assistant", "done"),
    ]
    plan = cc.plan_chat_compaction(rows, 6000)
    assert plan["ok"]
    assert not plan["recent"] or plan["recent"][0].role != "tool"


def test_a_chat_too_small_to_shrink_is_refused_in_words():
    plan = cc.plan_chat_compaction([ChatMessage("user", "hi"), ChatMessage("assistant", "hello")], 6000)
    assert plan == {"ok": False, "reason": plan["reason"]}
    assert "would not make it any smaller" in plan["reason"]


def test_nothing_new_since_the_last_compaction_is_refused():
    summary = ChatMessage("system", "[Conversation summary — 9 earlier messages were compacted]\n\n" + "fact " * 400,
                          {"compacted": True, "hidden": True})
    marker = ChatMessage("assistant", "**Chat compacted** — 9 messages summarized, 0 kept.", {"compacted": True})
    plan = cc.plan_chat_compaction([summary, marker], 131072)
    assert plan["ok"] is False
    assert plan["reason"].startswith("Nothing new to compact")


# ── what the summariser reads ───────────────────────────────────────────────

def test_the_summariser_reads_whole_messages_when_they_fit():
    """The old route cut every message to 2,000 characters before the model saw it."""
    long = "detail " * 1000                      # 7,000 characters
    rows = [ChatMessage("user", long), ChatMessage("assistant", "ok")]
    source = cc.build_summary_source(rows, room_tokens=20000)
    assert long.strip() in source


def test_an_earlier_summary_is_merged_whole_and_tool_output_is_cut_first():
    earlier = "remember: port 8443, user ann, path /srv/app " * 40
    rows = [
        ChatMessage("system", "[Conversation summary — 4 earlier messages were compacted]\n\n" + earlier,
                    {"compacted": True, "hidden": True}),
        ChatMessage("assistant", "**Chat compacted** — 4 messages summarized, 1 kept.", {"compacted": True}),
        ChatMessage("user", "please list the files"),
        ChatMessage("tool", "file.txt\n" * 3000),
        ChatMessage("assistant", "There are 3,000 files."),
    ]
    source = cc.build_summary_source(rows, room_tokens=2500)
    assert source.startswith("EARLIER SUMMARY: " + earlier.strip())
    assert "**Chat compacted**" not in source, "the old marker is not conversation"
    assert "USER: please list the files" in source
    assert "ASSISTANT: There are 3,000 files." in source
    tool = source.split("TOOL RESULT: ", 1)[1].split("\n\nASSISTANT:", 1)[0]
    assert len(tool) <= cc.TOOL_RESULT_SOURCE_CHARS + 10


# ── the summariser ──────────────────────────────────────────────────────────

@pytest.fixture
def quiet_windows(monkeypatch):
    import src.model_context as model_context
    monkeypatch.setattr(model_context, "get_context_length_known", lambda url, model: (6000, True))
    monkeypatch.setattr(model_context, "is_local_endpoint", lambda url: True)


def test_utility_fails_then_the_chat_model_writes_it(monkeypatch, quiet_windows):
    import src.llm_core as llm_core
    asked = []

    async def call(url, model, messages, **kw):
        asked.append((model, kw["timeout"], kw["max_retries"], messages[0]["content"][:17]))
        if model == "utility":
            raise RuntimeError("utility model is not loaded")
        return "### User Goal\nShip the launch."

    monkeypatch.setattr(llm_core, "llm_call_async", call)
    out = asyncio.run(cc.summarize_for_compaction(
        _chat(6), 200, [("http://u/v1", "utility", {}), ("http://c/v1", "openai/gpt-oss-20b", {})]))
    assert out["by_model"] == "openai/gpt-oss-20b"
    assert out["summary"] == "### User Goal\nShip the launch."
    # One try each, with the time a local reasoning model needs; gpt-oss is
    # told to reason briefly.
    assert asked[0][1:3] == (cc.SUMMARY_TIMEOUT_LOCAL, 1)
    assert asked[1] == ("openai/gpt-oss-20b", cc.SUMMARY_TIMEOUT_LOCAL, 1, "Reasoning: low\n\nY")


def test_when_no_model_answers_pantheon_condenses_it_itself(monkeypatch, quiet_windows):
    import src.llm_core as llm_core

    async def call(*_a, **_k):
        raise TimeoutError("read timed out")

    monkeypatch.setattr(llm_core, "llm_call_async", call)
    rows = _chat(8, words=80)
    out = asyncio.run(cc.summarize_for_compaction(rows, 300, [("http://c/v1", "m", {})]))
    assert out["by_model"] is None
    assert "read timed out" in out["why_not"]
    assert out["summary"].count("\n- ") >= 6, "every older message keeps its opening"
    assert estimate_tokens([{"role": "system", "content": out["summary"]}]) <= 300 * 1.3


def test_harmony_channels_left_inline_are_not_the_summary(monkeypatch, quiet_windows):
    import src.llm_core as llm_core

    async def call(*_a, **_k):
        return ("<|channel|>analysis<|message|>We need to summarize.<|end|>"
                "<|start|>assistant<|channel|>final<|message|>### User Goal\nShip it.")

    monkeypatch.setattr(llm_core, "llm_call_async", call)
    out = asyncio.run(cc.summarize_for_compaction(_chat(6), 200, [("http://c/v1", "gpt-oss-20b", {})]))
    assert out["summary"] == "### User Goal\nShip it."


def test_a_summary_that_overruns_cannot_undo_the_cut(monkeypatch, quiet_windows):
    import src.llm_core as llm_core

    async def call(*_a, **_k):
        return "\n".join(f"- fact {i} " + "x" * 60 for i in range(400))

    monkeypatch.setattr(llm_core, "llm_call_async", call)
    out = asyncio.run(cc.summarize_for_compaction(_chat(6), 200, [("http://c/v1", "m", {})]))
    assert estimate_tokens([{"role": "system", "content": out["summary"]}]) <= 200 * 1.6


# ── the whole route, in the real app, against a stand-in LM Studio ──────────

class _LMStudio(BaseHTTPRequestHandler):
    """LM Studio serving gpt-oss-20b loaded with 6,000 tokens: its native
    model list, and a chat completion that either answers in harmony's split
    fields or takes longer than the summary may."""
    protocol_version = "HTTP/1.1"
    slow = 0.0
    posts: list = []

    def _send(self, body, status=200):
        raw = json.dumps(body).encode()
        self.send_response(status)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(raw)))
        self.end_headers()
        self.wfile.write(raw)

    def do_GET(self):
        if self.path == "/api/v1/models":
            self._send({"models": [{
                "type": "llm", "key": "openai/gpt-oss-20b", "display_name": "gpt-oss-20b",
                "architecture": "gpt-oss", "max_context_length": 131072,
                "loaded_instances": [{"id": "openai/gpt-oss-20b",
                                      "config": {"context_length": 6000}}],
                "capabilities": {"vision": False, "trained_for_tool_use": True}}]})
        elif self.path == "/v1/models":
            self._send({"object": "list", "data": [{"id": "openai/gpt-oss-20b", "object": "model"}]})
        else:
            self._send({"error": "not found"}, 404)

    def do_POST(self):
        length = int(self.headers.get("Content-Length") or 0)
        body = json.loads(self.rfile.read(length) or b"{}")
        type(self).posts.append(body)
        if type(self).slow:
            time.sleep(type(self).slow)
        self._send({"id": "x", "object": "chat.completion", "model": "openai/gpt-oss-20b",
                    "choices": [{"index": 0, "finish_reason": "stop", "message": {
                        "role": "assistant",
                        "reasoning_content": "We need to summarize the launch plan.",
                        "content": "### User Goal\nPlan the launch week.\n\n### Key Facts and Decisions\n- Venue: hall B"}}]})

    def log_message(self, *a):
        pass


@pytest.fixture(scope="module")
def lmstudio():
    srv = ThreadingHTTPServer(("127.0.0.1", 0), _LMStudio)
    threading.Thread(target=srv.serve_forever, daemon=True).start()
    try:
        yield f"http://127.0.0.1:{srv.server_address[1]}/v1"
    finally:
        srv.shutdown()
        srv.server_close()


_PROBE = r'''
import src.agent_runs as agent_runs
import src.endpoint_resolver as endpoint_resolver
import src.context_compactor as cc
from core.models import ChatMessage

agent_runs.is_active = lambda sid: False
endpoint_resolver.resolve_endpoint = lambda kind, owner=None: (None, None, {})
cc.SUMMARY_TIMEOUT_LOCAL = TIMEOUT

manager = app_module.session_manager
manager.create_session("c1", "Launch week", URL, "openai/gpt-oss-20b", owner=ADMIN)
# The last reply (the sixth message) carries its own measurement of what it was sent with, as the
# agent loop saves it: 2.3K of instructions, 425 of tools, 1.7K retrieved.
MEASURED = {"context_breakdown": {"categories": [
    {"key": "system", "tokens": 2300, "items": []},
    {"key": "tools", "tokens": 425, "items": [], "count": 3},
    {"key": "retrieved", "tokens": 1700, "items": []}]}}
for i in range(7):
    manager.add_message("c1", ChatMessage("user" if i % 2 == 0 else "assistant",
                                          f"message {i}: " + "the launch week plan for hall B " * 18,
                                          MEASURED if i == 5 else None))

me = client(ADMIN)
RESULT["wheel_before"] = me.get("/api/session/c1/context?mode=chat").json()
answer = me.post("/api/session/c1/compact?mode=chat")
RESULT["status"] = answer.status_code
RESULT["answer"] = answer.json()
RESULT["wheel_after"] = me.get("/api/session/c1/context?mode=chat").json()
RESULT["drawn"] = [e["content"] for e in me.get("/api/history/c1").json()["history"]]
RESULT["context"] = [(m["role"], m["content"]) for m in manager.get_session("c1").get_context_messages()]
'''


def _run(tmp_path_factory, lmstudio, *, slow, timeout):
    _LMStudio.slow, _LMStudio.posts = slow, []
    body = f"URL = {lmstudio!r}\nTIMEOUT = {timeout!r}\n" + _PROBE
    result = gated_app_probe(tmp_path_factory.mktemp("b1727"), body)
    result["posts"] = list(_LMStudio.posts)
    return result


@pytest.fixture(scope="module")
def answered(tmp_path_factory, lmstudio):
    return _run(tmp_path_factory, lmstudio, slow=0.0, timeout=30)


@pytest.fixture(scope="module")
def too_slow(tmp_path_factory, lmstudio):
    return _run(tmp_path_factory, lmstudio, slow=3.0, timeout=1)


def test_the_window_is_what_lm_studio_loaded_the_model_with(answered):
    """`B1732`: not "unknown, so 6K" — LM Studio's own list says 6,000."""
    wheel = answered["wheel_before"]
    assert wheel["window_known"] is True
    assert wheel["window_tokens"] == 6000


def test_compacting_through_the_real_app_cuts_the_chat_and_keeps_the_overhead(answered):
    assert answered["status"] == 200, answered["answer"]
    answer = answered["answer"]
    assert answer["summarized_by"] == "openai/gpt-oss-20b"
    assert answer["chat_tokens_after"] <= 0.45 * answer["chat_tokens_before"]
    assert answer["after"] < answer["before"]
    # The wheel still counts the instructions, tools and retrieved context the
    # next request carries — it does not drop to the chat alone.
    after = answered["wheel_after"]["breakdown"]
    by_key = {c["key"]: c["tokens"] for c in after["categories"]}
    assert by_key["system"] == 2300 and by_key["tools"] == 425 and by_key["retrieved"] == 1700
    assert answered["wheel_after"]["breakdown"]["context_percent"] == pytest.approx(answer["after"], abs=0.2)


def test_the_model_reads_its_summary_and_not_its_reasoning(answered):
    role, summary = answered["context"][0]
    assert role == "system"
    assert "### User Goal\nPlan the launch week." in summary
    assert "We need to summarize" not in summary
    post = answered["posts"][0]
    assert post["messages"][0]["content"].startswith("Reasoning: low")
    # Whole messages, not 2,000-character slices.
    assert "message 0: " + "the launch week plan for hall B " * 17 in post["messages"][1]["content"]


def test_a_model_too_slow_to_answer_does_not_fail_the_compaction(too_slow):
    assert too_slow["status"] == 200, too_slow["answer"]
    answer = too_slow["answer"]
    assert answer["summarized_by"] == "pantheon"
    assert answer["chat_tokens_after"] <= 0.5 * answer["chat_tokens_before"]
    assert too_slow["drawn"][0].startswith("**Chat compacted** — ")
    assert "The model did not answer in time, so Pantheon condensed them itself." in too_slow["drawn"][0]
    role, summary = too_slow["context"][0]
    assert "(condensed by Pantheon — no model wrote a summary)" in summary
