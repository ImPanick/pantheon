# SPDX-License-Identifier: AGPL-3.0-or-later
"""`B1653` — a memory the trim left out is not counted as used.

`uses` is the count the Brain shows as *injected into chat context N times*
(`memoryFacts.js`), and `P13-04`'s fading reads `last_used` beside it.

**Measured on the tree before this row**, through `/api/chat_stream` on
`B1650`'s tight turn (Agent mode, one saved memory, 24,000 characters attached,
a 3,000-token input budget): the trim left the memory out, the turn named no
memory as used (`B1650`), and the memory's `uses` still went from 0 to 1 —
`ChatProcessor.build_context_preface` raised it while it built the preface,
before any trim had run.

Now nothing is counted while the preface is built. The route counts the turn's
settled `memories_used` (`ChatProcessor.count_memory_uses`, through
`routes.chat_helpers.count_turn_memories`) once it is settled: the stream when
it ends, after the loop's `context_trimmed` notices and the answering
fallback's trim have taken off what no request carried; `/api/chat` once a
candidate has answered, without what its trim left out.

Driven (`Law 20`): the Agent-mode turn through `capture.Server` booting this
checkout's `app.py` and `demo_model.DemoModel` (`B1572`'s world), the count read
back through `GET /api/memory`; `/api/chat` through the real route with a
fallback chain, its real request factory and `trim_for_context`, and a real
`MemoryManager` on a temporary directory.
"""
from __future__ import annotations

import asyncio
from types import SimpleNamespace

import pytest

from src.chat_processor import ChatProcessor, _attach_memory_facts
from src.memory import MemoryManager
from src.prompt_security import own_context_message
from test_a_trim_keeps_the_instructions_and_names_only_the_memories_it_sent import TIGHT, _turn
from test_an_agent_turn_trimmed_to_fit_says_what_it_left_out import MEMORY, world  # noqa: F401

import seed  # noqa: E402  (on the path the B1572 module put it on)


def _uses(client):
    rows = seed._ok(client.get("/api/memory"), "memory")["memory"]
    [row] = [r for r in rows if MEMORY in str(r.get("text"))]
    return int(row.get("uses") or 0)


def _sent_text(sent):
    return "\n".join(m["text"] for m in sent)


# ── the row's turn, through the booted app ──────────────────────────────────

def test_after_a_turn_whose_trim_left_out_the_memory_its_use_count_is_unchanged(world):  # noqa: F811
    """The row's `Verify:`, with the turn that sent the memory as the control:
    the same memory, the same attachments, a budget with room."""
    client = world[0]
    before = _uses(client)
    _events, sent, reply = _turn(world, files=2, budget=TIGHT)
    assert MEMORY not in _sent_text(sent), "premise: the trim left the memory out"
    assert not reply.get("memories_used"), "premise: the turn names it as not used (`B1650`)"
    assert _uses(client) == before, "a memory the model never received was counted as used"

    _events, sent, reply = _turn(world, files=2)
    assert MEMORY in _sent_text(sent), "control: this turn sent it"
    assert _uses(client) == before + 1, "control: a memory that was sent is counted, once"


# ── `/api/chat`: the answering candidate's own trim ─────────────────────────

def _store(tmp_path):
    manager = MemoryManager(str(tmp_path))
    entry = manager.add_entry(f"The code word is {MEMORY}.", source="user", category="fact")
    entries = manager.load_all_for_update()
    entries.append(entry)
    manager.save(entries)
    return manager, entry


def _stored_uses(manager, entry):
    return next(int(e.get("uses") or 0) for e in manager.load() if e["id"] == entry["id"])


class _Docs:
    rag_manager = None


def _nonstream_chat(monkeypatch, processor, entry, window):
    """`/api/chat` with a fallback chain, so every candidate's request is
    trimmed by the route's own factory to `window` tokens."""
    import core.database as database
    import routes.chat_routes as chat_routes
    import src.foreground_model_routing as foreground_model_routing
    import src.llm_core as llm_core
    from src.request_models import ChatRequest
    from test_foreground_model_routing import _NonStreamChatHandler, _RouteRequest, _no_post_response

    fact = {"id": entry["id"], "text": entry["text"]}
    memory = _attach_memory_facts(
        own_context_message("saved memory: pinned context", f"- {entry['text']}"), [fact])
    turn = [{"role": "system", "content": "You are helpful."}, memory,
            {"role": "user", "content": "x" * 6000}]
    context = SimpleNamespace(
        user="alice", messages=list(turn), route_messages=list(turn), context_length=window,
        used_memories=[{**fact, "type": "pinned"}], uprefs={},
        preset=SimpleNamespace(temperature=0.2, max_tokens=128, character_name=None))
    session = SimpleNamespace(endpoint_url="https://selected.example/v1", model="selected-model",
                              headers={}, history=[], add_message=lambda m: None)
    sent = []

    async def fake_build_context(*args, **kwargs):
        return context

    async def fake_compact(session, url, model, messages, headers=None, **kwargs):
        return list(messages), window, False

    async def fake_call(url, model, messages, **kwargs):
        sent.append(messages)
        return "OK."

    monkeypatch.setattr(foreground_model_routing, "_load_policy_preferences", lambda owner=None: {
        "foreground_fallback_enabled": True,
        "foreground_model_fallbacks": [{"endpoint_id": "backup", "model": "backup-model"}]})
    monkeypatch.setattr(foreground_model_routing, "resolve_fallback_entries",
                        lambda *a, **k: [("https://backup.example/v1", "backup-model", {})])
    monkeypatch.setattr(llm_core, "llm_call_async", fake_call)
    monkeypatch.setattr(chat_routes, "maybe_compact", fake_compact)
    monkeypatch.setattr(chat_routes, "_verify_session_owner", lambda *a, **k: None)
    monkeypatch.setattr(chat_routes, "effective_user", lambda request: "alice")
    monkeypatch.setattr(chat_routes, "_clear_orphaned_session_endpoint", lambda *a, **k: False)
    monkeypatch.setattr(chat_routes, "_recover_empty_session_model", lambda *a, **k: False)
    monkeypatch.setattr(chat_routes, "_require_usable_model", lambda *a, **k: None)
    monkeypatch.setattr(chat_routes, "_enforce_chat_privileges", lambda *a, **k: None)
    monkeypatch.setattr(chat_routes, "build_chat_context", fake_build_context)
    monkeypatch.setattr(chat_routes, "clean_thinking_for_save", lambda reply, md: (reply, md))
    monkeypatch.setattr(chat_routes, "run_post_response_tasks", _no_post_response)
    monkeypatch.setattr(database, "update_session_last_accessed", lambda session_id: None)
    router = chat_routes.setup_chat_routes(
        SimpleNamespace(get_session=lambda sid: session, save_sessions=lambda: None),
        _NonStreamChatHandler(), processor, SimpleNamespace(), SimpleNamespace(), SimpleNamespace())
    endpoint = next(r.endpoint for r in router.routes if r.path == "/api/chat")
    asyncio.run(endpoint(_RouteRequest("chat"), ChatRequest(message="hello", session="session-1")))
    [request] = sent
    return MEMORY in "\n".join(str(m.get("content")) for m in request)


@pytest.mark.parametrize(("window", "carried"), [(1500, False), (128_000, True)])
def test_a_chat_turn_counts_only_what_the_answering_request_carried(monkeypatch, tmp_path, window, carried):
    manager, entry = _store(tmp_path)
    processor = ChatProcessor(memory_manager=manager, personal_docs_manager=_Docs())
    assert _nonstream_chat(monkeypatch, processor, entry, window) is carried, \
        "premise: the candidate's trim left the memory out only on the small window"
    assert _stored_uses(manager, entry) == (1 if carried else 0)


# ── the preface counts nothing; the turn's settled list is counted once ─────

def test_building_the_preface_counts_nothing_and_the_settled_list_is_counted_once(tmp_path):
    manager, entry = _store(tmp_path)
    manager_rows = manager.load()
    pinned = [{**manager_rows[0], "pinned": True}]
    manager.load = lambda owner=None: pinned   # the pinned engine picks it as core
    processor = ChatProcessor(memory_manager=manager, personal_docs_manager=_Docs())
    processor.build_context_preface(message="what is the code word", session=SimpleNamespace(),
                                    use_rag=False, use_memory=True)
    used = processor._last_used_memories
    assert [m["id"] for m in used] == [entry["id"]], "premise: the preface carries it"
    assert _stored_uses(MemoryManager(str(tmp_path)), entry) == 0
    processor.count_memory_uses(used + used)
    assert _stored_uses(MemoryManager(str(tmp_path)), entry) == 1
    processor.count_memory_uses([])
    assert _stored_uses(MemoryManager(str(tmp_path)), entry) == 1
