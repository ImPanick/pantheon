# SPDX-License-Identifier: AGPL-3.0-or-later
"""P6-18 — the transport: ``POST /api/chat/steer/{session_id}``.

The inbox (`src/agent_loop.py`) and the composer control
(`static/js/chatStream.js`) were already tested on their own; nothing could
test the join between them until this route existed. So these drive the route
over real HTTP and read the result off the two things it actually touches —
the inbox in `agent_loop` and the verdict on the wire — rather than off the
route's source.

Four properties are load-bearing and each has a test that fails loudly if it
ever stops holding:

  * **A steer is only accepted by a run that will actually read it.** Only
    `stream_agent_loop` drains the inbox; a plain-chat, image-generation or
    research stream is registered in `agent_runs` exactly like an agent run
    but never calls `consume_steers_for_round`. Accepting a steer for one of
    those told the user it would land at the next step and then let
    `clear_steers` drop it, while the client — reading the 200 — had already
    emptied the composer. The gate is `is_steerable`, never `is_active`.
  * **The ownership check runs before anything else.** A steer aimed at a
    stranger's live run must not reach the inbox, and the capability probe —
    which reports whether this build has the route — must not become a cheaper
    way to ask about a session than the steer itself.
  * **A refusal is never 404, 405 or 501.** `chatStream.js` reads exactly those
    three as "this build has no steer transport", hides the control and stops
    asking for the page's remaining life, so borrowing one for "no run in
    flight" would retire a working feature on the first mistimed keystroke.
    The ownership refusal is bound by the same rule and answers 403; these
    tests originally expected the 404 `_verify_session_owner` raises, which
    meant a steer aimed at a session another tab had just deleted retired the
    control in this one and reported it as "not available on this server".
  * **The limits stay in one place.** `STEER_MAX_PENDING` / `STEER_MAX_CHARS`
    are the inbox's; the route forwards the inbox's verdict including its
    ``limit``, so a second set cannot drift away from the first.

Auth is real: a shim sets ``request.state.current_user`` the way the auth
middleware does, and `_verify_session_owner` then runs unmodified against a
real (in-memory) sessions table. Nothing about the ownership decision is
stubbed, because that decision is what most of this file is about.
"""

from contextlib import ExitStack, contextmanager
from pathlib import Path
from types import SimpleNamespace

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

from core.database import Base, Session as DbSession
from routes import chat_routes, session_routes
from src import agent_runs
from src.agent_loop import (
    STEER_MAX_CHARS,
    STEER_MAX_PENDING,
    clear_steers,
    consume_steers_for_round,
    pending_steers,
)

ROOT = Path(__file__).resolve().parents[1]

ALICE_SID = "sess-alice"
BOB_SID = "sess-bob"

# The three statuses `chatStream.js` treats as "no transport on this build".
RETIRING_STATUSES = {404, 405, 501}


@contextmanager
def _run_in_flight(session_id: str, *, steerable: bool = True):
    """Register a running detached run for ``session_id``.

    `agent_runs.start()` wants a live event loop and a real stream generator,
    neither of which a request-scoped test has; the registry entry it would
    create is the whole of what the route reads, so it is written directly.

    ``steerable`` is the flag `chat_stream` passes to `agent_runs.start()`:
    True for the agent branch, False for every other stream a session can be
    running. `test_start_records_what_the_stream_can_do` drives the real
    `start()` so this shortcut cannot drift from what it stores.
    """
    run = agent_runs._Run()
    run.steerable = steerable
    agent_runs._RUNS[session_id] = run
    try:
        yield
    finally:
        agent_runs._RUNS.pop(session_id, None)


@contextmanager
def _chat_mode_run_in_flight(session_id: str):
    """A run in flight that will never read the inbox.

    What `chat_stream` registers for `mode: 'chat'` (and for an image-
    generation session, and for research): detached and live, so `is_active`
    is True, but heading for `stream_llm_with_fallback` rather than
    `stream_agent_loop`.
    """
    with _run_in_flight(session_id, steerable=False):
        yield


@pytest.fixture
def client(monkeypatch):
    """The chat router on a real app, with real auth and real owner lookup."""
    engine = create_engine(
        "sqlite://",
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
    )
    Base.metadata.create_all(engine, tables=[DbSession.__table__])
    db_factory = sessionmaker(bind=engine, autocommit=False, autoflush=False)

    db = db_factory()
    try:
        for session_id, owner in ((ALICE_SID, "alice"), (BOB_SID, "bob")):
            db.add(
                DbSession(
                    id=session_id,
                    name=f"{owner}'s chat",
                    endpoint_url="http://model.test/v1",
                    model="test-model",
                    owner=owner,
                )
            )
        db.commit()
    finally:
        db.close()

    # Auth on, so an unauthenticated caller is refused rather than waved
    # through as single-user mode.
    monkeypatch.setenv("AUTH_ENABLED", "true")
    monkeypatch.setattr(session_routes, "SessionLocal", db_factory)

    signed_in = {"user": "alice"}
    app = FastAPI()

    @app.middleware("http")
    async def _authenticate(request, call_next):
        request.state.current_user = signed_in["user"]
        return await call_next(request)

    app.include_router(
        chat_routes.setup_chat_routes(
            SimpleNamespace(),  # session_manager
            SimpleNamespace(),  # chat_handler
            SimpleNamespace(),  # chat_processor
            SimpleNamespace(),  # memory_manager
            SimpleNamespace(),  # research_handler
            SimpleNamespace(),  # upload_handler
        )
    )

    test_client = TestClient(app)
    test_client.signed_in = signed_in
    try:
        yield test_client
    finally:
        clear_steers(ALICE_SID)
        clear_steers(BOB_SID)
        engine.dispose()


def _steer(client, session_id, payload):
    return client.post(f"/api/chat/steer/{session_id}", json=payload)


# ── the capability probe ────────────────────────────────────────────────────


def test_the_probe_answers_with_no_run_in_flight_and_queues_nothing(client):
    response = _steer(client, ALICE_SID, {"probe": True})

    assert response.status_code not in RETIRING_STATUSES
    assert response.json()["supported"] is True
    assert pending_steers(ALICE_SID) == [], "a probe is a question, not a steer"


def test_the_probe_answers_during_a_run_and_still_queues_nothing(client):
    with _run_in_flight(ALICE_SID):
        response = _steer(client, ALICE_SID, {"probe": True})

    assert response.status_code not in RETIRING_STATUSES
    # This used to also expect ``"active": True``. Nothing ever read that field
    # — `probeSteerSupport` branches on `res.status` alone — so pinning it here
    # gave a payload with no consumer the appearance of a contract.
    assert response.json() == {"supported": True}
    assert pending_steers(ALICE_SID) == []


@pytest.mark.parametrize("probe_value", ["false", "no", "true", 1, 0, [], {}])
def test_only_a_real_boolean_is_a_probe(client, probe_value):
    """``body.get("probe")`` was truthiness, which split the wire types the
    wrong way: ``"no"`` probed and ``0`` steered. A flag is a bool or it is
    not a flag, and anything else falls through to the steer path — where a
    body with no ``text`` is refused as empty rather than answered as a probe.
    """
    with _run_in_flight(ALICE_SID):
        response = _steer(client, ALICE_SID, {"probe": probe_value})

    assert "supported" not in response.json()
    assert response.json()["reason"] == "empty"
    assert pending_steers(ALICE_SID) == []


# ── the accepted path ───────────────────────────────────────────────────────


def test_a_steer_during_a_live_run_reaches_the_inbox(client):
    with _run_in_flight(ALICE_SID):
        response = _steer(client, ALICE_SID, {"text": "use the staging db"})

        assert response.status_code == 200
        assert response.json() == {
            "accepted": True,
            "pending": 1,
            "applies_at": "next_round",
        }
        assert pending_steers(ALICE_SID) == ["use the staging db"]


def test_an_accepted_steer_is_delivered_as_a_user_turn_at_the_next_round(client):
    """The round trip the inbox tests could not reach: HTTP in, user turn out."""
    with _run_in_flight(ALICE_SID):
        assert _steer(client, ALICE_SID, {"text": "switch to the other file"}).status_code == 200

    messages = [{"role": "user", "content": "original request"}]
    applied = consume_steers_for_round(ALICE_SID, messages)

    assert applied == ["switch to the other file"]
    assert messages[-1]["role"] == "user"
    assert "switch to the other file" in messages[-1]["content"]
    assert pending_steers(ALICE_SID) == [], "consumed once, not re-applied every round"


# ── refusals ────────────────────────────────────────────────────────────────


def test_a_steer_with_no_run_in_flight_is_refused_and_queues_nothing(client):
    response = _steer(client, ALICE_SID, {"text": "too late"})

    # ``pending`` rides on this refusal like it rides on every `submit_steer`
    # verdict; it was the one refusal without it, and a client that has to
    # special-case a missing field is a client that will forget to.
    assert response.json() == {
        "accepted": False,
        "reason": "no_active_run",
        "pending": 0,
    }
    assert response.status_code not in RETIRING_STATUSES
    assert pending_steers(ALICE_SID) == []


def test_the_no_active_run_refusal_reports_the_backlog_it_found(client):
    """``pending`` is a real count, not a zero constant: a steer accepted while
    the agent ran and still waiting when the run ends is reported back."""
    with _run_in_flight(ALICE_SID):
        assert _steer(client, ALICE_SID, {"text": "first"}).status_code == 200

    late = _steer(client, ALICE_SID, {"text": "second, too late"})

    assert late.json() == {
        "accepted": False,
        "reason": "no_active_run",
        "pending": 1,
    }
    assert pending_steers(ALICE_SID) == ["first"], "the refused steer is not queued"


# ── the run has to be one that can read the inbox ───────────────────────────


def test_a_steer_during_a_chat_mode_run_is_refused_and_queues_nothing(client):
    """The `breaks-users` defect this gate exists for.

    `chat.js` sends ``mode: 'chat'`` whenever the agent toggle is off and
    raises the busy flag on every send, so the steer bar is drawn and
    Cmd/Ctrl+Enter is live for a plain chat turn. `chat_stream` detaches that
    stream through `agent_runs` exactly like an agent run, so `is_active` says
    yes — but it is heading for `stream_llm_with_fallback`, and
    `consume_steers_for_round` is only ever called from `stream_agent_loop`.

    Accepting here returned 200, which makes `submitSteer` clear the composer
    and toast "lands at the next step"; the words then sat in the inbox until
    the next run's `clear_steers` dropped them. Refusing returns them to the
    user: `chatStream.js` maps `no_active_run` onto `chat.js`'s queue and the
    text is still there.
    """
    with _chat_mode_run_in_flight(ALICE_SID):
        response = _steer(client, ALICE_SID, {"text": "actually use postgres"})

        assert response.status_code == chat_routes._STEER_REFUSAL_STATUS["no_active_run"]
        assert response.json()["reason"] == "no_active_run"
        assert response.status_code not in RETIRING_STATUSES
        assert pending_steers(ALICE_SID) == [], (
            "a stream that never drains the inbox must not be given anything to drain"
        )


def test_a_run_that_can_read_the_inbox_still_accepts(client):
    """The other half of the pair above: the gate narrowed, it did not close."""
    with _run_in_flight(ALICE_SID, steerable=True):
        assert _steer(client, ALICE_SID, {"text": "use the staging db"}).status_code == 200
        assert pending_steers(ALICE_SID) == ["use the staging db"]


@pytest.mark.parametrize(
    "chat_mode, is_image_session, do_research, expected",
    [
        ("agent", False, False, True),     # the only branch that drains the inbox
        ("chat", False, False, False),     # stream_llm_with_fallback
        ("agent", True, False, False),     # image generation returns before the branch
        ("chat", True, False, False),
        ("agent", False, True, False),     # research returns from its own block
        ("chat", False, True, False),
        ("research", False, True, False),
        ("", False, False, True),          # anything not 'chat' takes the else branch
    ],
)
def test_the_steerable_predicate_matches_the_branch_that_drains_the_inbox(
    chat_mode, is_image_session, do_research, expected
):
    """`_stream_is_steerable` is the whole of what `chat_stream` passes to
    `agent_runs.start()`, so its table is the definition of which streams can
    be steered. It mirrors `stream_with_save`'s three-way choice; if a fourth
    destination is ever added, this table is where the omission shows up.
    """
    assert chat_routes._stream_is_steerable(
        chat_mode=chat_mode,
        is_image_session=is_image_session,
        do_research=do_research,
    ) is expected


@pytest.mark.asyncio
async def test_start_records_what_the_stream_can_do():
    """`agent_runs.start()` must actually carry the flag to the registry, and
    default to refusing. A caller that forgets loses steering; the opposite
    default would silently re-open the accept-and-drop path."""
    session_id = "sess-steerable-start"
    agent_runs._RUNS.pop(session_id, None)

    async def _one_event():
        yield "data: [DONE]\n\n"

    try:
        run = agent_runs.start(session_id, _one_event())
        assert agent_runs.is_active(session_id) is True
        assert agent_runs.is_steerable(session_id) is False, "the default is 'cannot'"
        await run.task

        run = agent_runs.start(session_id, _one_event(), steerable=True)
        assert agent_runs.is_steerable(session_id) is True
        await run.task
        # A finished agent run is live for nothing and steerable for nothing.
        assert agent_runs.is_active(session_id) is False
        assert agent_runs.is_steerable(session_id) is False
    finally:
        agent_runs._RUNS.pop(session_id, None)


# ── refusals the inbox itself issues ────────────────────────────────────────


@pytest.mark.parametrize("text", ["", "   ", "\n\t "])
def test_an_empty_steer_is_refused_as_empty(client, text):
    with _run_in_flight(ALICE_SID):
        response = _steer(client, ALICE_SID, {"text": text})

    assert response.json()["reason"] == "empty"
    assert pending_steers(ALICE_SID) == []


def test_a_missing_text_field_is_refused_as_empty(client):
    with _run_in_flight(ALICE_SID):
        response = _steer(client, ALICE_SID, {})

    assert response.json()["reason"] == "empty"
    assert pending_steers(ALICE_SID) == []


def test_a_non_string_text_never_reaches_the_model_as_its_repr(client):
    with _run_in_flight(ALICE_SID):
        response = _steer(client, ALICE_SID, {"text": {"nested": "object"}})

    assert response.json()["reason"] == "empty"
    assert pending_steers(ALICE_SID) == []


def test_an_over_long_steer_is_refused_with_the_inboxs_own_limit(client):
    with _run_in_flight(ALICE_SID):
        response = _steer(client, ALICE_SID, {"text": "x" * (STEER_MAX_CHARS + 1)})

    body = response.json()
    assert body["reason"] == "too_long"
    assert body["limit"] == STEER_MAX_CHARS, "the route must not invent a second cap"
    assert pending_steers(ALICE_SID) == []


def test_the_backlog_cap_is_the_inboxs_and_the_route_adds_no_second_one(client):
    with _run_in_flight(ALICE_SID):
        for index in range(STEER_MAX_PENDING):
            assert _steer(client, ALICE_SID, {"text": f"steer {index}"}).status_code == 200
        response = _steer(client, ALICE_SID, {"text": "one too many"})

    body = response.json()
    assert body["reason"] == "too_many"
    assert body["limit"] == STEER_MAX_PENDING
    assert len(pending_steers(ALICE_SID)) == STEER_MAX_PENDING


@pytest.mark.parametrize(
    "live, payload, expected_reason",
    [
        (False, {"text": "too late"}, "no_active_run"),
        (True, {"text": ""}, "empty"),
        (True, {"text": "x" * (STEER_MAX_CHARS + 1)}, "too_long"),
    ],
)
def test_a_refusal_never_answers_as_a_missing_route(client, live, payload, expected_reason):
    """404/405/501 would hide the control permanently — see the module docstring."""
    with ExitStack() as stack:
        if live:
            stack.enter_context(_run_in_flight(ALICE_SID))
        response = _steer(client, ALICE_SID, payload)

    assert response.status_code not in RETIRING_STATUSES, (
        f"a {expected_reason!r} refusal must still look like a working route"
    )
    assert response.json()["reason"] == expected_reason


# ── ownership ───────────────────────────────────────────────────────────────


def test_another_owners_live_run_cannot_be_steered(client):
    with _run_in_flight(BOB_SID):
        response = _steer(client, BOB_SID, {"text": "rm -rf the wrong repo"})

        assert response.status_code == 403
        assert pending_steers(BOB_SID) == [], "a stranger's words never reach bob's run"

        # The same request from bob is accepted, so the refusal above is
        # ownership and not a broken fixture.
        client.signed_in["user"] = "bob"
        assert _steer(client, BOB_SID, {"text": "mine to steer"}).status_code == 200
        assert pending_steers(BOB_SID) == ["mine to steer"]


@pytest.mark.parametrize(
    "payload", [{"text": "rm -rf the wrong repo"}, {"probe": True}], ids=["steer", "probe"]
)
def test_the_ownership_refusal_does_not_look_like_a_missing_route(client, payload):
    """This test previously asserted 404 for both — the status the owner check
    raises — which was the bug: `submitSteer` reads 404 as "this build has no
    steer route", removes the bar, sets `_steerSupported = false` and reports
    "Steering is not available on this server". Tab A steering a long agent run
    on a session tab B had just deleted therefore retired a working control for
    the rest of tab A's page load, on a false statement. A legacy `owner IS
    NULL` row reached the same 404 by the same path.
    """
    with _run_in_flight(BOB_SID):
        response = _steer(client, BOB_SID, payload)

    assert response.status_code == 403
    assert response.status_code not in RETIRING_STATUSES
    assert pending_steers(BOB_SID) == []


@pytest.mark.parametrize(
    "payload", [{"text": "whose session is this"}, {"probe": True}], ids=["steer", "probe"]
)
def test_the_ownership_refusal_cannot_tell_a_strangers_session_from_one_that_never_existed(
    client, payload
):
    """Ownership is checked before the body is read, so both the steer and the
    probe inherit one refusal that conflates "not yours" with "no such thing".

    Re-stamping 404 as 403 must not have split the two apart. Both go through
    the same `except HTTPException` on the same call with the same arguments,
    which is what keeps them identical in status, body and headers — and in
    the work done, so the timings the refuter measured as indistinguishable
    stay that way. Nothing here is asserted about elapsed time: a wall-clock
    bound in CI is a flaky test, and the property that matters is that there
    is only one code path.
    """
    with _run_in_flight(BOB_SID):
        stranger = _steer(client, BOB_SID, payload)
    imaginary = _steer(client, "sess-does-not-exist", payload)

    assert stranger.status_code == imaginary.status_code == 403
    # Compared against the owner check's own wording, so a route that simply
    # is not mounted (FastAPI's bare "Not Found") cannot pass this by accident.
    assert stranger.json() == {"detail": f"Session {BOB_SID} not found"}
    assert imaginary.json() == {"detail": "Session sess-does-not-exist not found"}
    assert (
        {k.lower() for k in stranger.headers} == {k.lower() for k in imaginary.headers}
    ), "a header present on only one answer is an existence oracle"
    assert pending_steers(BOB_SID) == []


def test_an_unauthenticated_caller_is_refused(client):
    client.signed_in["user"] = None
    with _run_in_flight(ALICE_SID):
        response = _steer(client, ALICE_SID, {"text": "who are you"})

    assert response.status_code == 401
    assert pending_steers(ALICE_SID) == []


# ── malformed transport ─────────────────────────────────────────────────────


@pytest.mark.parametrize("raw", [b"not json at all", b"[1, 2, 3]", b""])
def test_a_body_that_is_not_a_json_object_is_rejected(client, raw):
    with _run_in_flight(ALICE_SID):
        response = client.post(
            f"/api/chat/steer/{ALICE_SID}",
            content=raw,
            headers={"Content-Type": "application/json"},
        )

    assert response.status_code == 400
    assert pending_steers(ALICE_SID) == []


# ── the confirmation's return leg ───────────────────────────────────────────


def test_chat_js_routes_the_steer_confirmation_to_its_only_consumer():
    """The steer round trip is two legs: this route in, `steer_applied` out.

    `chatStream.js` exports `handleSteerApplied` and `src/agent_loop.py` emits
    the event, but for a while nothing joined them — `chat.js` routed
    `ui_control` and nothing else — so `_steerConfirmSeen` was never set and
    the module's own "your steer missed the run" warning could not fire. That
    is the `Law 13` half-wire this pins.

    Asserted against the source rather than by driving it: `chat.js` imports
    twenty-odd browser-coupled modules, so the node sandbox that exercises
    `chatStream.js` in `tests/test_chat_steer_js.py` cannot reach it. This is
    the same source-structure check `test_ask_user_persistence.py` uses for the
    `ask_user` branch of the same dispatch chain.
    """
    chat_js = (ROOT / "static" / "js" / "chat.js").read_text(encoding="utf-8")
    chat_stream_js = (ROOT / "static" / "js" / "chatStream.js").read_text(encoding="utf-8")

    # The whole event, not `json.data`: `stream_agent_loop` puts `round`,
    # `count` and `steers` at the top level of the SSE payload, and
    # `handleSteerApplied` reads `data.round` off what it is handed.
    assert "chatStream.handleSteerApplied(json)" in chat_js
    assert "export function handleSteerApplied" in chat_stream_js
    assert "handleSteerApplied," in chat_stream_js, "reachable on the default export"

    # Inside the dispatch chain, not merely somewhere in the file.
    ui_control = chat_js.index("json.type === 'ui_control'")
    steer_applied = chat_js.index("json.type === 'steer_applied'")
    ask_user = chat_js.index("json.type === 'ask_user'")
    assert ui_control < steer_applied < ask_user


def test_chat_js_routes_the_steerability_verdict_to_its_only_consumer():
    """`B14`'s outbound leg, wired the same way and pinned the same way.

    What the event says is tested by driving both ends —
    `tests/test_stream_announces_its_steerability.py` reads the payload off the
    real route, and `tests/test_chat_steer_js.py` drives `handleStreamSteerable`
    with it. Only the join is left, and the join lives in a dispatch chain the
    node sandbox cannot reach for the reason given above: `chat.js` imports
    twenty-odd browser-coupled modules. So this checks the same three things the
    test above checks, and nothing about behaviour.
    """
    chat_js = (ROOT / "static" / "js" / "chat.js").read_text(encoding="utf-8")
    chat_stream_js = (ROOT / "static" / "js" / "chatStream.js").read_text(encoding="utf-8")

    # The whole event: `steerable` is at the top level, like `round` is.
    assert "chatStream.handleStreamSteerable(json)" in chat_js
    assert "export function handleStreamSteerable" in chat_stream_js
    assert "handleStreamSteerable," in chat_stream_js, "reachable on the default export"

    ui_control = chat_js.index("json.type === 'ui_control'")
    steerable = chat_js.index("json.type === 'stream_steerable'")
    ask_user = chat_js.index("json.type === 'ask_user'")
    assert ui_control < steerable < ask_user
