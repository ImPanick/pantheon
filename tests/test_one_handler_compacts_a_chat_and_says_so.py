# SPDX-License-Identifier: AGPL-3.0-or-later
"""`B1529` — one handler answers `POST /api/session/{id}/compact`, and it leaves a marker.

Walking the real app's route table, the path had two handlers — the only
duplicate (method, path) in it — and `routes.session_routes.compact_session`,
included before `history_routes`, was the one that ran: it stored a `system`
summary and nothing else, so a compacted chat's earlier messages vanished with
no line saying why, and `B1214`'s *Chat compacted* marker and `B1506`'s order
lived in the shadowed handler. Now `history_routes` holds the one handler, with
the adaptive tail and the readable refusal the other had, and the response
fields `slashCommands.js` prints (`summarized`, `kept`).

Booted out of process and driven as a signed-in person
(`tests/helpers/gated_app.py`): the route table, a twelve-message chat
compacted through the real app, the history the browser then draws, the
context the model is then sent, and a chat too short to compact.
"""
import pytest

from tests.helpers.gated_app import gated_app_probe

_PROBE = r'''
from collections import Counter

import src.agent_runs as agent_runs
import src.endpoint_resolver as endpoint_resolver
import src.llm_core as llm_core
from core.models import ChatMessage

def walk(routes, prefix=""):
    """Every endpoint route, with its full path. This FastAPI keeps an included
    router nested (`_IncludedRouter`: its routes hang off `original_router`,
    its prefix off `include_context` — `check-unreachable.py` measured a flat
    walk of `app.routes` reaching a fraction of them), so the walk recurses
    and carries each include's prefix down."""
    for route in routes:
        included = getattr(route, "original_router", None)
        if included is not None:
            context = getattr(route, "include_context", None)
            yield from walk(included.routes, prefix + (getattr(context, "prefix", "") or ""))
        elif getattr(route, "endpoint", None) is not None:
            yield route, prefix + (getattr(route, "path", "") or "")


seen = Counter()
handlers = []
endpoints = list(walk(app_module.app.routes))
for route, path in endpoints:
    for method in sorted(getattr(route, "methods", None) or ()):
        seen[(method, path)] += 1
    if path == "/api/session/{session_id}/compact":
        handlers.append(f"{route.endpoint.__module__}.{route.endpoint.__qualname__}")
RESULT["routes"] = len(endpoints)
RESULT["duplicates"] = sorted(f"{m} {p}" for (m, p), n in seen.items() if n > 1)
RESULT["compact_handlers"] = handlers


async def summarise(*_a, **_k):
    return "They planned the launch week."

llm_core.llm_call_async = summarise
endpoint_resolver.resolve_endpoint = lambda kind, owner=None: ("http://model.test/v1", "m", {})
agent_runs.is_active = lambda sid: False

manager = app_module.session_manager
manager.create_session("c1", "Launch week", "http://model.test/v1", "m", owner=ADMIN)
for i in range(12):
    manager.add_message("c1", ChatMessage("user" if i % 2 == 0 else "assistant", f"line {i}"))
manager.create_session("c2", "Short", "http://model.test/v1", "m", owner=ADMIN)
for i in range(3):
    manager.add_message("c2", ChatMessage("user" if i % 2 == 0 else "assistant", f"short {i}"))

me = client(ADMIN)
answer = me.post("/api/session/c1/compact")
RESULT["status"] = answer.status_code
RESULT["answer"] = answer.json()
RESULT["drawn"] = [e["content"] for e in me.get("/api/history/c1").json()["history"]]
RESULT["context"] = [(m["role"], m["content"][:60])
                     for m in manager.get_session("c1").get_context_messages()]
short = me.post("/api/session/c2/compact")
RESULT["short"] = [short.status_code, short.json().get("detail")]
'''


@pytest.fixture(scope="module")
def probe(tmp_path_factory):
    return gated_app_probe(tmp_path_factory.mktemp("b1529"), _PROBE)


def test_one_handler_per_method_and_path(probe):
    assert probe["duplicates"] == []
    assert probe["routes"] > 400, "the walk did not reach the included routers"
    assert probe["compact_handlers"] == [
        "routes.history.history_routes.setup_history_routes.<locals>.compact_session"]


def test_compacting_through_the_real_app_leaves_a_visible_marker_in_order(probe):
    assert probe["status"] == 200
    # Twelve messages: the adaptive tail keeps four, at least, and up to eight.
    assert (probe["answer"]["ok"], probe["answer"]["summarized"], probe["answer"]["kept"]) == (
        True, 8, 4)
    assert probe["drawn"] == ["**Chat compacted** — 8 messages summarized, 4 kept.",
                              "line 8", "line 9", "line 10", "line 11"]


def test_the_model_reads_the_summary_first(probe):
    first, *rest = probe["context"]
    assert first[0] == "system"
    assert first[1].startswith("[Conversation summary — 8 earlier messages were compacted]")
    assert [content for _role, content in rest] == [
        "**Chat compacted** — 8 messages summarized, 4 kept.",
        "line 8", "line 9", "line 10", "line 11"]


def test_a_chat_too_short_to_compact_is_refused_in_words(probe):
    """The shadowed handler answered 200 *Not enough messages* here, which
    the composer read as success and toasted *Context compacted*."""
    assert probe["short"] == [400, "Not enough messages to compact yet — a chat needs six."]
