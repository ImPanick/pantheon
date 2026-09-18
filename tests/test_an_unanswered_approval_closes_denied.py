# SPDX-License-Identifier: AGPL-3.0-or-later
"""`P12-10` — a prompt nobody answered closes as denied, and the clock is a setting.

**What happened before this row, measured rather than assumed**, because the
row asserted a behaviour nobody had written down:

  * **Nothing blocks.** `src/agent_loop.py` creates the pending approval,
    emits the card, and the run *returns* with `exit_code: None` and
    `"Waiting for an exact user approval."`. There is no caller sitting on a
    future. So "does the caller block, get a default, get an error, or
    silently proceed" has a fourth answer the row did not list: **the caller
    has already gone**, and what is left is a record in memory and a card in a
    transcript.
  * **The record is dropped lazily.** `_purge_expired_locked` runs only from
    `create`, `consume`, `peek` and `retire_for_session`. There is no sweeper
    and no timer, so in a process where nobody touches the store again the
    lapsed approval sits in the dict past its deadline indefinitely.
  * **One events row said `expired`, and nothing else happened.** No decision
    was recorded, the persisted card kept no `resolved` key, and an explicit
    `deny` recorded nothing at all — `_record_approval` had exactly two call
    sites, `claimed` and `expired`.
  * **The person found out by clicking.** `routes/chat_routes.py` calls
    `peek` first, which purges, so a lapsed card answers 409 *"This tool
    approval is invalid, expired, or belongs to another thread."*

So expiry counted and denial did not exist. This file holds the row's three
claims: expiry produces a **recorded denial**, the denial reaches the
transcript that asked, and the timeout is an **operator setting** that cannot
be typed into an off switch.
"""

import json
import time
from types import SimpleNamespace

import pytest

import src.limit_policy as lp
import src.settings as settings
import src.tool_approvals as ta
from src.tool_approvals import ToolApprovalStore
from src.tool_capabilities import capabilities_for_action


@pytest.fixture(autouse=True)
def _clean(monkeypatch):
    ta.clear_approval_expiry_listeners()
    lp.clear_role_limit_provider()
    yield
    ta.clear_approval_expiry_listeners()
    lp.clear_role_limit_provider()


@pytest.fixture
def stored(tmp_path, monkeypatch):
    path = tmp_path / "settings.json"
    path.write_text("{}", encoding="utf-8")
    monkeypatch.setattr(settings, "SETTINGS_FILE", str(path))

    def write(**values):
        path.write_text(json.dumps(values), encoding="utf-8")
        monkeypatch.setattr(settings, "_settings_cache", None)

    write()
    return write


@pytest.fixture
def recorded(monkeypatch):
    """Every `record_event` the store makes, without touching the database."""
    rows: list[dict] = []

    def fake(kind, **kw):
        rows.append({"kind": kind, **kw})
        return True

    import src.events as events
    monkeypatch.setattr(events, "record_event", fake)
    return rows


def _pending(store, *, owner="alice", session="s-1"):
    return store.create(
        owner=owner, session_id=session, origin_run_id="run-1",
        tool_name="bash", content="rm -rf /tmp/scratch", workspace=None,
        external_untrusted_context_seen=False,
        capabilities=capabilities_for_action("bash", "rm -rf /tmp/scratch"),
    )


# ── expiry is a denial, not a disappearance ──────────────────────────────────


def test_a_lapsed_approval_is_recorded_as_denied(recorded):
    store = ToolApprovalStore(ttl_seconds=1)
    _pending(store)
    time.sleep(1.05)
    store.peek("anything")          # any store call is what notices the lapse

    approvals = [r for r in recorded if r["kind"] == "approval"]
    assert [r["outcome"] for r in approvals] == [ta.APPROVAL_DENIED_TIMEOUT]
    assert ta.APPROVAL_DENIED_TIMEOUT.startswith("denied")
    assert approvals[0]["name"] == "bash"
    assert approvals[0]["owner"] == "alice"


def test_an_answered_approval_is_not_swept_into_a_denial(recorded):
    store = ToolApprovalStore(ttl_seconds=600)
    pending = _pending(store)
    assert store.consume(pending.approval_id, decision="approve",
                         owner="alice", session_id="s-1") is not None
    outcomes = [r["outcome"] for r in recorded if r["kind"] == "approval"]
    assert ta.APPROVAL_DENIED_TIMEOUT not in outcomes


def test_an_explicit_deny_is_recorded_too(recorded):
    """The scheduled-task path in `src/task_scheduler.py` auto-denies a card no
    interactive surface can answer, and that denial was invisible: `consume`
    recorded nothing for `deny` and reported it through the out-parameter as
    `bad_decision`, the value reserved for a decision the card never offered."""
    store = ToolApprovalStore(ttl_seconds=600)
    pending = _pending(store)
    outcome: dict = {}
    assert store.consume(pending.approval_id, decision="deny", owner="alice",
                         session_id="s-1", outcome=outcome) is None
    assert outcome["reason"] == ta.APPROVAL_DENIED
    approvals = [r for r in recorded if r["kind"] == "approval"]
    assert [r["outcome"] for r in approvals] == [ta.APPROVAL_DENIED]


def test_a_decision_the_card_never_offered_is_still_not_a_denial(recorded):
    store = ToolApprovalStore(ttl_seconds=600)
    pending = _pending(store)
    outcome: dict = {}
    store.consume(pending.approval_id, decision="perhaps", owner="alice",
                  session_id="s-1", outcome=outcome)
    assert outcome["reason"] == "bad_decision"


# ── the denial reaches whatever asked ────────────────────────────────────────


def test_the_lapse_is_announced_to_listeners_with_the_record(recorded):
    seen: list = []
    ta.register_approval_expiry_listener(seen.append)
    store = ToolApprovalStore(ttl_seconds=1)
    pending = _pending(store)
    time.sleep(1.05)
    store.peek("anything")

    assert [p.approval_id for p in seen] == [pending.approval_id]
    assert seen[0].session_id == "s-1"
    assert seen[0].owner == "alice"


def test_a_listener_is_told_once_and_not_on_every_later_call(recorded):
    seen: list = []
    ta.register_approval_expiry_listener(seen.append)
    store = ToolApprovalStore(ttl_seconds=1)
    _pending(store)
    time.sleep(1.05)
    store.peek("a")
    store.peek("b")
    assert len(seen) == 1


def test_a_listener_that_throws_does_not_break_the_store(recorded):
    def boom(pending):
        raise RuntimeError("no session manager")

    ta.register_approval_expiry_listener(boom)
    store = ToolApprovalStore(ttl_seconds=1)
    _pending(store)
    time.sleep(1.05)
    assert store.peek("anything") is None          # did not raise
    # and a later approval still works
    assert _pending(store) is not None


def test_the_listener_is_notified_outside_the_store_lock(recorded):
    """A listener writes to the database. Holding the store's lock across that
    would serialise every approval in the process behind a disk write, and a
    listener that reached back into the store would deadlock outright."""
    depth: list = []

    def reentrant(pending):
        depth.append(store.peek("anything"))       # would deadlock under the lock

    ta.register_approval_expiry_listener(reentrant)
    store = ToolApprovalStore(ttl_seconds=1)
    _pending(store)
    time.sleep(1.05)
    store.peek("anything")
    assert depth == [None]


def test_the_chat_surface_marks_the_lapsed_card_denied_in_its_transcript(monkeypatch):
    """`Law 20` — the real function, against the transcript shape it reads.

    The card the run left behind lives in `metadata.tool_events[].ask_user`.
    Until this row nothing ever wrote `resolved` on it for a lapse, so a
    reloaded chat rebuilt the card as live (`chatRenderer.renderAskUserCard`
    returns `null` only when `resolved` is set) and its buttons answered 409.
    """
    from routes import chat_routes

    ask_user = {"kind": "tool_approval", "approval_id": "a-1", "session_id": "s-1"}
    metadata = {"_db_id": "m-1", "tool_events": [{"ask_user": ask_user}]}
    sess = SimpleNamespace(id="s-1", history=[SimpleNamespace(metadata=metadata)])
    db_message = SimpleNamespace(meta_data=None)

    class Column:
        def __eq__(self, value):
            return value

    class FakeDBMessage:
        id = Column()
        session_id = Column()

    class FakeQuery:
        def filter(self, *conditions):
            return self

        def first(self):
            return db_message

    class FakeDB:
        def query(self, model):
            return FakeQuery()

        def commit(self):
            pass

        def rollback(self):  # pragma: no cover
            pass

        def close(self):
            pass

    monkeypatch.setattr(chat_routes, "DBChatMessage", FakeDBMessage)
    monkeypatch.setattr(chat_routes, "SessionLocal", FakeDB)
    monkeypatch.setattr(
        chat_routes, "get_session_manager_instance",
        lambda: SimpleNamespace(sessions={"s-1": sess}),
    )

    pending = SimpleNamespace(approval_id="a-1", session_id="s-1", owner="alice")
    assert chat_routes.deny_expired_tool_approval(pending) is True
    assert ask_user["resolved"] == "deny"
    assert json.loads(db_message.meta_data)["tool_events"][0]["ask_user"]["resolved"] == "deny"


def test_the_chat_surface_survives_having_no_session_manager(monkeypatch):
    from routes import chat_routes
    monkeypatch.setattr(chat_routes, "get_session_manager_instance", lambda: None)
    pending = SimpleNamespace(approval_id="a-1", session_id="s-1", owner="alice")
    assert chat_routes.deny_expired_tool_approval(pending) is False


def test_building_the_chat_routes_registers_the_denial_listener():
    """`Law 13` — the half that would otherwise not be wired, driven not grepped.

    A listener nothing registers is a backend with no caller. `setup_chat_routes`
    is the one place that runs once at boot and owns
    `_mark_tool_approval_resolved`, so the router is actually built here and the
    store is asked who is listening.
    """
    from routes import chat_routes

    assert chat_routes.deny_expired_tool_approval not in ta.approval_expiry_listeners()
    chat_routes.setup_chat_routes(*[SimpleNamespace() for _ in range(6)])
    assert chat_routes.deny_expired_tool_approval in ta.approval_expiry_listeners()


def test_building_the_chat_routes_twice_registers_one_listener():
    """The suite builds this router several times. A denial written twice is a
    transcript written twice."""
    from routes import chat_routes

    chat_routes.setup_chat_routes(*[SimpleNamespace() for _ in range(6)])
    chat_routes.setup_chat_routes(*[SimpleNamespace() for _ in range(6)])
    listeners = ta.approval_expiry_listeners()
    assert listeners.count(chat_routes.deny_expired_tool_approval) == 1


def test_registering_the_same_listener_twice_only_calls_it_once(recorded):
    seen: list = []
    ta.register_approval_expiry_listener(seen.append)
    ta.register_approval_expiry_listener(seen.append)
    store = ToolApprovalStore(ttl_seconds=1)
    _pending(store)
    time.sleep(1.05)
    store.peek("anything")
    assert len(seen) == 1


# ── the timeout is an operator setting ───────────────────────────────────────


def test_the_default_timeout_is_unchanged(stored, recorded):
    store = ToolApprovalStore()
    pending = _pending(store)
    assert pending.public_payload()["ttl_seconds"] == ta.DEFAULT_APPROVAL_TTL_SECONDS
    assert ta.DEFAULT_APPROVAL_TTL_SECONDS == 600


def test_an_operator_setting_changes_the_timeout(stored, recorded):
    stored(approval_timeout_seconds=120)
    store = ToolApprovalStore()
    assert _pending(store).public_payload()["ttl_seconds"] == 120


def test_the_timeout_changes_without_a_restart(stored, recorded):
    """The store is built once, at import, and lives for the process. The value
    is resolved per card, so a settings change reaches the next card."""
    store = ToolApprovalStore()
    assert _pending(store).public_payload()["ttl_seconds"] == 600
    stored(approval_timeout_seconds=90)
    assert _pending(store, session="s-2").public_payload()["ttl_seconds"] == 90


def test_zero_does_not_mean_no_timeout(stored, recorded):
    """`FORBIDDEN.md` Part 2 keeps the approval store's TTL. A setting that can
    be typed to `0` is that control with an off switch, so it is clamped to a
    floor and the floor is named."""
    stored(approval_timeout_seconds=0)
    store = ToolApprovalStore()
    assert _pending(store).public_payload()["ttl_seconds"] == ta.MIN_APPROVAL_TTL_SECONDS
    assert ta.MIN_APPROVAL_TTL_SECONDS >= 1


def test_an_absurd_timeout_is_capped(stored, recorded):
    stored(approval_timeout_seconds=10_000_000)
    store = ToolApprovalStore()
    assert _pending(store).public_payload()["ttl_seconds"] == ta.MAX_APPROVAL_TTL_SECONDS


def test_an_explicit_constructor_ttl_still_pins_it(stored, recorded):
    """Four test files and the skill tester build stores with a fixed TTL. An
    explicit number is a caller saying *this one*, and the setting does not
    override it."""
    stored(approval_timeout_seconds=90)
    store = ToolApprovalStore(ttl_seconds=30)
    assert _pending(store).public_payload()["ttl_seconds"] == 30


def test_the_refusal_to_move_the_deadline_names_it_and_says_where_to_go():
    """`B42`'s trade: the refusal has to point somewhere or it is worked around.

    The stored-value half — that the agent's write does not land — is driven in
    `tests/test_agent_cannot_loosen_its_own_gates.py`, which owns that
    measurement for every key in the set and now owns this one too.
    """
    import asyncio
    import json as _json
    from src.agent_tools.admin_tools import do_manage_settings

    result = asyncio.run(do_manage_settings(_json.dumps({
        "action": "set", "key": "approval_timeout_seconds", "value": 86_400,
    })))
    response = str(result.get("response", ""))
    assert "approval_timeout_seconds" in response
    assert "Settings" in response
    assert "including if you ask me to" in response


def test_the_timeout_key_is_declared_so_the_settings_route_accepts_it():
    from src.settings import DEFAULT_SETTINGS
    assert DEFAULT_SETTINGS["approval_timeout_seconds"] == 600
