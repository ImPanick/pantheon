# SPDX-License-Identifier: AGPL-3.0-or-later
"""`B1961`. A compaction slower than the request ceiling was answered as a
failure, and then rewrote the chat anyway.

*Compact* (`POST /api/session/{id}/compact`) asks a model for the summary with
the time `B1731` gives a local reasoning model: up to 180 s, of the utility
model and then of the chat's own. `app.py`'s 45 s request ceiling did not
leave that route alone, so a slow summary was answered *"Request exceeded 45s
timeout"* while the compaction ran on behind the answer (`B1093`: the ceiling
cancels the wait, not the work) and replaced the chat when it finished. A turn
the person sent meanwhile was in neither the summary nor the kept messages,
and went with the rows the rewrite deleted.

Now the route is exempt from the ceiling, matched on the route path as
`B1958` matches every exemption, because it is bounded already: two summary
calls with their own timeouts, then Pantheon condenses the chat itself. And a
turn stored while the summary is written is kept, after the kept messages.

Driven: the real app out of process with its ceiling at one second, against
a stand-in LM Studio three times slower than that, and a turn sent through
the real route while the summary is being written.

Reported upstream in Odysseus PR #6806, which also adds a summary timeout of
its own; `B1731`'s stays.
"""
from __future__ import annotations

import pytest

from tests.helpers.gated_app import gated_app_probe
from tests.test_compact_cuts_the_chat_to_a_tenth import _LMStudio, lmstudio  # noqa: F401

LATE = "LATE TURN: and who brings the catering?"

_PROBE = r'''
import threading, time
import src.agent_runs as agent_runs
import src.endpoint_resolver as endpoint_resolver
import src.context_compactor as cc
from core.models import ChatMessage

app_module.REQUEST_HARD_TIMEOUT = 1.0          # the ceiling, at one second
cc.SUMMARY_TIMEOUT_LOCAL = 10                  # the summary's own time, over it
agent_runs.is_active = lambda sid: False
endpoint_resolver.resolve_endpoint = lambda kind, owner=None: (None, None, {})

manager = app_module.session_manager
manager.create_session("c1", "Launch week", URL, "openai/gpt-oss-20b", owner=ADMIN)
for i in range(7):
    manager.add_message("c1", ChatMessage("user" if i % 2 == 0 else "assistant",
                                          f"message {i}: " + "the launch week plan for hall B " * 18))

writing = threading.Event()
summarize = cc.summarize_for_compaction

async def summarize_and_say_so(*args, **kwargs):
    writing.set()
    return await summarize(*args, **kwargs)

cc.summarize_for_compaction = summarize_and_say_so

def the_person_writes_on():
    writing.wait(30)
    time.sleep(0.3)
    sent = client(ADMIN).post("/api/session/c1/inject_messages",
                              json={"messages": [{"role": "user", "content": LATE}]})
    RESULT["late_sent"] = sent.status_code

turn = threading.Thread(target=the_person_writes_on)
turn.start()
started = time.monotonic()
answer = client(ADMIN).post("/api/session/c1/compact?mode=chat")
RESULT["seconds"] = round(time.monotonic() - started, 2)
turn.join(30)
RESULT["status"] = answer.status_code
RESULT["answer"] = answer.json()
RESULT["history"] = [m.content for m in manager.get_session("c1").history]
RESULT["drawn"] = [e["content"] for e in client(ADMIN).get("/api/history/c1").json()["history"]]
RESULT["exempt"] = {path: app_module._exempt_from_request_ceiling(path) for path in EXEMPT}
'''

#: The compaction route leaves the ceiling; its neighbours keep it.
EXEMPT = {"/api/session/c1/compact": True, "/api/session/c1/compact/": True,
          "/api/session/c1/context": False, "/api/session/c1": False,
          "/api/session/c1/compact/more": False, "/api/sessions/c1/compact": False}


@pytest.fixture(scope="module")
def compacted(tmp_path_factory, lmstudio):  # noqa: F811
    _LMStudio.slow, _LMStudio.posts = 3.0, []
    body = f"URL = {lmstudio!r}\nLATE = {LATE!r}\nEXEMPT = {sorted(EXEMPT)!r}\n" + _PROBE
    return gated_app_probe(tmp_path_factory.mktemp("b1961"), body)


def test_a_compaction_slower_than_the_ceiling_is_answered(compacted):
    assert compacted["status"] == 200, compacted["answer"]
    assert compacted["answer"]["summarized_by"] == "openai/gpt-oss-20b"
    assert compacted["seconds"] >= 3            # the model's time, not the ceiling's


def test_a_turn_sent_while_the_summary_is_written_is_kept(compacted):
    assert compacted["late_sent"] == 200
    assert compacted["history"][-1] == LATE
    assert compacted["drawn"][-1] == LATE       # stored, not only in memory


def test_only_the_compaction_route_leaves_the_ceiling(compacted):
    assert compacted["exempt"] == EXEMPT
