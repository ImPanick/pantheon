# SPDX-License-Identifier: AGPL-3.0-or-later
"""`B1069` — a turn approved part-way resumes with everything it had gathered.

Measured before the fix, with the README showcase's scripted model recording
every request it was sent through the real app: the filing chat's request before
its card carried `[system, user, assistant(tool_calls), tool]` — the document
list, every id in it — and the request after *Allow for this task* carried
`[system, user, assistant("Allow this task to continue?"), user(the approved
call's result)]`. The continuation was rebuilt from saved history, which keeps a
turn's words and not its tool traffic, so the model was asked again without
anything the turn had learned before the card.

Now the card keeps the paused turn server-side (`agent_loop.PausedTurn`, held on
the pending approval outside its seal) and the continuation asks with it: every
message the turn added, as it was sent before the card, then the paused round
with the approved result answering the model's own call id. The saved reply that
stood in for the turn is taken out of the request.

`Law 20`: nothing above the model's socket is faked. `capture.Server` boots this
checkout's `app.py` on a throwaway data directory; the person signs in, the
documents are made through the API, and every turn goes through `/api/chat_stream`
— the card's answer included, which is the approval route — into the real agent
loop, which runs every tool for real. The model is the showcase's scripted
stand-in (`demo_model.DemoModel`) playing this file's script and keeping every
request it is sent, which is the instrument that measured the row.

The two halves of `FORBIDDEN.md` Part 2 the resume touches are checked where
they show: a turn the gate armed is still armed after it (a strict rung asks
again, and the card names the result that armed it — a name only the restored
transcript carries), and a card minted in a clean run is still answerable (the
transcript does not arm the gate against its own approval).

The round-1 fallback half of the fix, and the steer it also reaches, are driven
in-process through the real route and loop with `B935`'s `wire` in
`test_a_fallback_resumes_with_the_turn.py`.
"""
from __future__ import annotations

import json
import secrets
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
SHOWCASE = ROOT / "scripts" / "showcase"
sys.path.insert(0, str(SHOWCASE))

import demo_model  # noqa: E402
import seed  # noqa: E402
from src.prompt_security import GUARD_CLOSE, GUARD_OPEN  # noqa: E402

STAND_IN = "Allow this task to continue?"
PLAN = {"plan": "- [ ] list what is scheduled\n- [ ] list the folders"}
TASKS_LIST = {"action": "list"}
DOCS_LIST = {"action": "list", "unfiled": True}
FOLDERS = {"action": "list_folders"}
NOTE = {"action": "create", "title": "Prep for Wednesday",
        "content": "Bring the launch checklist."}


def _calls(*pairs):
    return [{"call": name, "args": args} for name, args in pairs]


# One turn per conversation; each says what it calls, in order. The card lands
# where the gate puts it, and the test says where that is. Each request names
# what it is about: a turn the agent reads as small talk is answered on a short
# path with no tools at all (`_direct_low_signal`).
SCRIPT = [
    {   # The row's `Verify:` — a card on the turn's third call.
        "key": "third", "title": "third",
        "turns": [{"user": "Check my scheduled tasks, then list my document folders.",
                   "steps": [{"call": "update_plan", "args": PLAN},
                             {"call": "manage_tasks", "args": TASKS_LIST},
                             {"call": "manage_documents", "args": FOLDERS},
                             {"say": "Nothing is scheduled and there are nine folders."}]}],
    },
    {   # Two calls in one message; the card stops the second.
        "key": "batch", "title": "batch",
        "turns": [{"user": "List my loose documents and the folders in one go.",
                   "steps": [{"calls": _calls(("manage_documents", DOCS_LIST),
                                              ("manage_documents", FOLDERS))},
                             {"say": "Five loose documents and nine folders."}]}],
    },
    {   # A model sent no tools writes its calls as fenced blocks; its results come
        # back wrapped as untrusted data in a user message.
        "key": "fenced", "title": "fenced", "fenced": True,
        "turns": [{"user": "List my loose documents, then the document folders.",
                   "steps": [{"call": "manage_documents", "args": DOCS_LIST},
                             {"call": "manage_documents", "args": FOLDERS},
                             {"say": "Five loose documents and nine folders."}]}],
    },
    {   # On a strict rung: armed by the task list, stopped twice.
        "key": "strict", "title": "strict",
        "turns": [{"user": "Check my scheduled tasks, my document folders and my loose documents.",
                   "steps": [{"call": "manage_tasks", "args": TASKS_LIST},
                             {"call": "manage_documents", "args": FOLDERS},
                             {"call": "manage_documents", "args": DOCS_LIST},
                             {"say": "Nothing scheduled, nine folders, five loose documents."}]}],
    },
    {   # On a strict rung, in a clean run: the card is for a write nothing armed.
        "key": "clean", "title": "clean",
        "turns": [{"user": "Plan it, then add a note to my notes for Wednesday.",
                   "steps": [{"call": "update_plan", "args": PLAN},
                             {"call": "manage_notes", "args": NOTE},
                             {"say": "The note is there."}]}],
    },
]
WORDS = {conv["key"]: conv["turns"][0]["user"] for conv in SCRIPT}


@pytest.fixture(scope="module")
def pantheon(tmp_path_factory):
    import capture

    work = tmp_path_factory.mktemp("b1069")
    data = work / "data"
    data.mkdir()
    server = capture.Server(sys.executable, data, capture._free_port(),
                            extra_env={"PANTHEON_DISABLE_MCP": "1"})
    try:
        server.start(timeout=150)
    except RuntimeError as e:
        server.stop()
        pytest.fail(f"{e}\n{server.log_path.read_text(encoding='utf-8', errors='replace')[-3000:]}")
    try:
        yield server
    finally:
        server.stop()


@pytest.fixture(scope="module")
def world(pantheon):
    """A signed-in person with the showcase's documents, and the scripted model
    on two endpoints: one that is sent tools and one that is not."""
    import httpx

    client = httpx.Client(base_url=pantheon.base, timeout=180)
    seed.setup_admin(client, secrets.token_urlsafe(18))
    seed.seed_documents(client)
    log: list = []
    with demo_model.DemoModel(log=log, conversations=SCRIPT) as native, \
            demo_model.DemoModel(log=log, conversations=SCRIPT) as plain:
        endpoints = {"native": seed.register_demo_model(client, native.base_url)["endpoint_id"]}
        out = seed._ok(client.post("/api/model-endpoints", data={
            "name": "Demo model (no tools)", "base_url": plain.base_url,
            "supports_tools": "false", "require_models": "true"}), "plain endpoint")
        endpoints["plain"] = out["id"]
        yield client, endpoints, log
    client.close()


@pytest.fixture
def rung(world):
    client, _, _ = world

    def set_rung(value):
        seed._ok(client.post("/api/auth/settings", json={"trust_rung": value}), "trust rung")

    yield set_rung
    set_rung("gate_on_untrusted")


def _turn(world, key, endpoint="native"):
    """The person's turn, each card answered *Allow for this task*. Returns the
    cards, in order, and for each card the first request the model was sent
    after it was answered, and the request in which the model asked for the
    call the card stopped."""
    client, endpoints, log = world
    sess = seed._ok(client.post("/api/session", data={"endpoint_id": endpoints[endpoint],
                                                      "model": seed.DEMO_MODEL_ID}), "chat")
    form = {"message": WORDS[key], "session": sess.get("session_id") or sess.get("id"),
            "mode": "agent", "plan_mode": "false", "selected_model": seed.DEMO_MODEL_ID,
            "selected_endpoint_id": endpoints[endpoint], "allow_bash": "false",
            "allow_web_search": "false"}
    cards, asked, after = [], [], []
    for _ in range(4):
        start = len(log)
        resp = client.post("/api/chat_stream", data=form)
        assert resp.status_code == 200, resp.text[:400]
        events = list(seed._sse_events(resp.text))
        sent = [e for e in log[start:] if e["stream"] and e["conv"] == key]
        if cards:
            after.append(sent[0]["messages"])
        assert not [e for e in events if e.get("type") == "error"], events
        new = [e["data"] for e in events if e.get("type") == "ask_user"
               and (e.get("data") or {}).get("kind") == "tool_approval"]
        if not new:
            return {"cards": cards, "after": after, "asked": asked, "events": events}
        cards.append(new[-1])
        asked.append(sent[-1]["messages"])
        form = {**form, "message": "", "tool_approval_id": new[-1]["approval_id"],
                "tool_approval_decision": "approve_task"}
    raise AssertionError(f"{key}: more cards than the script has calls")


def _after_words(messages, key):
    """The messages the turn added: everything after the person's words."""
    at = max(i for i, m in enumerate(messages)
             if m.get("role") == "user" and WORDS[key] in demo_model._text(m.get("content")))
    return messages[at + 1:]


def _called(message):
    return [(c["function"]["name"], json.loads(c["function"]["arguments"]))
            for c in message.get("tool_calls") or []]


def _stand_ins(messages):
    return [m for m in messages if m.get("role") == "assistant"
            and STAND_IN in demo_model._text(m.get("content"))]


# ── the row ─────────────────────────────────────────────────────────────────

def test_a_card_on_the_third_call_resumes_with_the_first_two_results(world):
    """The row's `Verify:`. The request after the card is the request before it —
    message for message, the first two calls and their results — and then the
    third call, answered by the approved result under the model's own call id."""
    turn = _turn(world, "third")
    assert [c["action"]["tool"] for c in turn["cards"]] == ["manage_documents"]
    before = _after_words(turn["asked"][0], "third")
    resumed = _after_words(turn["after"][0], "third")
    assert [_called(m) for m in before if m["role"] == "assistant"] == [
        [("update_plan", PLAN)], [("manage_tasks", TASKS_LIST)]]
    assert resumed[:len(before)] == before
    third, result = resumed[len(before):len(before) + 2]
    assert _called(third) == [("manage_documents", FOLDERS)]
    assert result["role"] == "tool" and result["tool_call_id"] == third["tool_calls"][0]["id"]
    assert "folder(s)" in result["content"]
    assert len(resumed) == len(before) + 2
    assert not _stand_ins(turn["after"][0])


def test_a_card_on_the_second_call_of_a_message_keeps_the_first_result(world):
    """A card stopping a round part-way: the model's message with both calls, the
    first call's result, and the approved second — the row's loss on a turn's
    first round, which "an approval on the first call loses nothing" missed."""
    turn = _turn(world, "batch")
    resumed = _after_words(turn["after"][0], "batch")
    assert [m["role"] for m in resumed] == ["assistant", "tool", "tool"]
    assert _called(resumed[0]) == [("manage_documents", DOCS_LIST), ("manage_documents", FOLDERS)]
    ids = [c["id"] for c in resumed[0]["tool_calls"]]
    assert [m["tool_call_id"] for m in resumed[1:]] == ids
    assert "Found 5 document(s)" in resumed[1]["content"]
    assert "folder(s)" in resumed[2]["content"]
    assert not _stand_ins(turn["after"][0])


def test_a_model_sent_no_tools_resumes_with_its_results_still_wrapped(world):
    """The fenced path: each result came back to the model as untrusted data in a
    user message, behind the guard. The resumed request carries them again —
    the first exactly as it was sent, guard and all — and the approved one wrapped
    the same way."""
    turn = _turn(world, "fenced", endpoint="plain")
    before = _after_words(turn["asked"][0], "fenced")
    resumed = _after_words(turn["after"][0], "fenced")
    assert resumed[:len(before)] == before
    wrapped = [m for m in resumed if m["role"] == "user"]
    assert len(wrapped) == 2
    for message, says in zip(wrapped, ("Found 5 document(s)", "folder(s)")):
        text = demo_model._text(message["content"])
        assert GUARD_OPEN in text and GUARD_CLOSE in text
        assert text.index(GUARD_OPEN) < text.index(says) < text.index(GUARD_CLOSE)
    assert '"list_folders"' in demo_model._text(
        [m for m in resumed if m["role"] == "assistant"][-1]["content"])
    assert not _stand_ins(turn["after"][0])


def test_the_card_keeps_the_turn_to_itself(world):
    """The browser's copy of a card is what it always was: the paused turn is
    the server's, never part of the payload."""
    turn = _turn(world, "batch")
    card = turn["cards"][0]
    assert "continuation_turn" not in json.dumps(card)
    assert "Found 5 document(s)" not in json.dumps(card)


# ── the gate stands where it stood (`FORBIDDEN.md` Part 2) ──────────────────

def test_an_armed_turn_is_still_armed_and_says_by_what(world, rung):
    """`allow_listed` asks again after untrusted content despite a yes. The task
    list armed this turn before the first card; after it, the next private read
    is stopped again, and that card names the task list — a result only the
    restored transcript holds. Twice stopped, the last request carries all three
    results in order and neither stand-in."""
    rung("allow_listed")
    turn = _turn(world, "strict")
    first, second = turn["cards"]
    assert first["gate"]["tainted"] and second["gate"]["tainted"]
    assert second["action"]["content"] == json.dumps(DOCS_LIST)
    assert {"kind": "context", "source": "tool result: manage_tasks"} in second["gate"]["taint_trail"]
    last = _after_words(turn["after"][-1], "strict")
    assert [_called(m) for m in last if m["role"] == "assistant"] == [
        [("manage_tasks", TASKS_LIST)], [("manage_documents", FOLDERS)],
        [("manage_documents", DOCS_LIST)]]
    assert [m["role"] for m in last] == ["assistant", "tool"] * 3
    assert "Found 5 document(s)" in last[-1]["content"]
    assert not _stand_ins(turn["after"][-1])


def test_a_clean_turn_stays_clean_and_its_approval_still_runs(world, rung):
    """A strict rung stops a write in a run nothing armed. The transcript put
    back (a plan update, a trusted result) does not arm the gate, so the approval
    sealed clean is still good in the resumed run and the note is written."""
    client, _, _ = world
    rung("allow_listed")
    turn = _turn(world, "clean")
    assert [c["gate"]["tainted"] for c in turn["cards"]] == [False]
    ran = [e for e in turn["events"] if e.get("type") == "tool_output" and e.get("approved")]
    assert [e["tool"] for e in ran] == ["manage_notes"]
    notes = client.get("/api/notes").json()
    titles = {n["title"] for n in (notes.get("notes") if isinstance(notes, dict) else notes)}
    assert NOTE["title"] in titles
    resumed = _after_words(turn["after"][0], "clean")
    assert [_called(m) for m in resumed if m["role"] == "assistant"] == [
        [("update_plan", PLAN)], [("manage_notes", NOTE)]]


def test_a_card_that_kept_no_turn_leaves_its_reply_in_the_history():
    """Only a run that put a turn back replaced a stand-in. A card that kept no
    turn (the teacher's) left its saved reply in the history as an ordinary
    message, and a card minted later in the run that resumed it does not take
    that reply out; one that kept a turn passes on what it replaced."""
    from types import SimpleNamespace

    import src.agent_loop as agent_loop

    def minted_after(pending):
        return agent_loop._paused_turn(
            [], round_response="", round_reasoning="", used_native=True, calls=[],
            tool_results=[], tool_result_texts=[], tool_result_records=[], round_num=1,
            resumed_from=SimpleNamespace(pending=pending))

    kept = agent_loop.PausedTurn(messages=(), paused_round={}, replaces=("first",))
    assert minted_after(SimpleNamespace(approval_id="teacher", continuation_turn=None)).replaces == ()
    assert minted_after(SimpleNamespace(approval_id="second", continuation_turn=kept)).replaces == (
        "first", "second")
