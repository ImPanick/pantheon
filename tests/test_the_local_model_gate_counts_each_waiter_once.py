# SPDX-License-Identifier: AGPL-3.0-or-later
"""`B2024`. The local model gate took a waiting request off its count twice.

Every model call to a local endpoint passes one gate
(`src.llm_core._local_model_slot`): one call at a time, and a person's call
("foreground") before background work. A foreground call adds itself to
`_LOCAL_MODEL_WAITING_FOREGROUND` while it waits for the lock, and a
background call (a builtin action, a scheduled summary) does not join the
queue while that count is above zero. The count went down when a call got
the lock and again when it left, so each call that ended took one more off
than it had put on. With one call running and two waiting (Deep Research's
three extractions at once, two chats at once) the count read 0 while a
request still waited. When nothing else was holding background work back
(`has_foreground_activity()` false: no chat stream, agent run or busy page,
or `BACKGROUND_TASK_FOREGROUND_GATE=false`), a background call joined the
queue then, and a person's request made after it waited for the whole of
the background call's answer.

Now a call comes off the count once: when it gets the lock or, if it is
cancelled or fails before that, when it leaves. The single lock and the
three gate globals keep their names, which other tests patch.

Upstream Odysseus made the same one-line fix in 218d7624; its case is reused
here for Pantheon's single counter. Its per-endpoint locks are not taken.

Driven: the real gate, with only the endpoint check and the switch stubbed.
"""
from __future__ import annotations

import asyncio

import pytest

from src import llm_core as core

URL = "http://127.0.0.1:8080/v1/chat/completions"
# Long enough for a loaded machine; nothing here waits for it when it passes.
WAIT = 5.0


def _count() -> int:
    return core._LOCAL_MODEL_WAITING_FOREGROUND


class _Calls:
    """Model calls through the gate. Each one, once inside, stays until it is
    let go; `order` is the order in which they got the model."""

    def __init__(self) -> None:
        # Names of the calls that have taken their place at the gate (below).
        self.placed: list[str] = []
        self.order: list[str] = []
        self.inside: dict[str, asyncio.Event] = {}
        self.leave: dict[str, asyncio.Event] = {}
        self.tasks: dict[str, asyncio.Task] = {}

    async def start(self, name: str, workload: str = "foreground") -> asyncio.Task:
        """Start a call and return once it has taken its place: a foreground
        call is counted and queued on the lock (or inside, if it was free),
        a background call has read the count once."""
        self.inside[name] = asyncio.Event()
        self.leave[name] = asyncio.Event()

        async def call():
            async with core._local_model_slot(URL, name, workload):
                self.order.append(name)
                self.inside[name].set()
                await self.leave[name].wait()

        self.tasks[name] = asyncio.create_task(call(), name=name)
        await _until(lambda: name in self.placed)
        return self.tasks[name]

    async def let_go(self, name: str, *, then: str | None = None) -> None:
        """Let `name` leave; with `then`, wait until that call is inside."""
        self.leave[name].set()
        if then:
            await asyncio.wait_for(self.inside[then].wait(), WAIT)
        else:
            await asyncio.wait_for(self.tasks[name], WAIT)


async def _until(condition, timeout: float = WAIT) -> None:
    # The gate asks whether the endpoint is local on a worker thread before
    # it counts (`B1588`), so a call takes its place a few turns later.
    async def _poll():
        while not condition():
            await asyncio.sleep(0)
    await asyncio.wait_for(_poll(), timeout)


@pytest.fixture
async def calls(monkeypatch):
    """A fresh gate, switched on, for an endpoint that counts as local."""
    monkeypatch.setattr(core, "_LOCAL_MODEL_LOCK", asyncio.Lock())
    monkeypatch.setattr(core, "_LOCAL_MODEL_CURRENT", {})
    monkeypatch.setattr(core, "_LOCAL_MODEL_WAITING_FOREGROUND", 0)
    monkeypatch.setattr(core, "_local_model_gate_enabled", lambda: True)
    monkeypatch.setattr(core, "is_local_endpoint", lambda url: True)
    c = _Calls()
    real = core._gate_workload

    # `_gate_workload` is the first thing a call does after the endpoint
    # check, and nothing from there to the call's first wait gives the loop
    # away, so a call that has been through it has taken its place.
    def placed(workload):
        c.placed.append(asyncio.current_task().get_name())
        return real(workload)

    monkeypatch.setattr(core, "_gate_workload", placed)
    yield c
    left = [t for t in c.tasks.values() if not t.done()]
    for task in left:
        task.cancel()
    await asyncio.gather(*left, return_exceptions=True)


async def test_a_waiting_request_is_still_counted_when_the_call_ahead_of_it_ends(calls):
    """Upstream's case: the holder leaves, and the request it handed the lock
    to has not run yet. It is still waiting, so it is still counted."""
    async with core._local_model_slot(URL, "holder"):
        await calls.start("waiter")
        assert _count() == 1
    assert _count() == 1, "the holder took the waiting request off the count as it left"
    await asyncio.wait_for(calls.inside["waiter"].wait(), WAIT)
    assert _count() == 0
    await calls.let_go("waiter")
    assert _count() == 0


async def test_with_two_requests_waiting_the_second_is_counted_while_the_first_runs(calls):
    await calls.start("holder")
    await calls.start("first")
    await calls.start("second")
    assert _count() == 2

    await calls.let_go("holder", then="first")
    assert _count() == 1, "the second request still waits, and the count read 0"

    await calls.let_go("first", then="second")
    assert _count() == 0
    await calls.let_go("second")
    assert _count() == 0
    assert calls.order == ["holder", "first", "second"]


async def test_a_request_cancelled_while_it_waits_takes_itself_off_the_count(calls):
    """The other half of the rule: a call that never got the lock comes off
    the count when it leaves, so a cancelled one leaves no count behind."""
    await calls.start("holder")
    waiter = await calls.start("waiter")
    assert _count() == 1

    waiter.cancel()
    with pytest.raises(asyncio.CancelledError):
        await waiter
    assert _count() == 0

    await calls.let_go("holder")
    await calls.start("next")
    await asyncio.wait_for(calls.inside["next"].wait(), WAIT)
    assert _count() == 0
    await calls.let_go("next")
    assert calls.order == ["holder", "next"]


async def test_a_background_call_waits_for_a_person_who_asked_after_it(calls, monkeypatch):
    """What a person notices. While one request runs and another waits, a
    background call arrives, and then the person asks again. The person's
    request gets the model first; the background call goes last."""
    # Nothing else holds the background call back: only the count can.
    monkeypatch.setenv("BACKGROUND_TASK_FOREGROUND_GATE", "false")

    await calls.start("holder")
    await calls.start("first")
    await calls.start("second")
    await calls.let_go("holder", then="first")

    await calls.start("summary", workload="background")
    await calls.start("person")

    for name in ("first", "second", "person", "summary"):
        calls.leave[name].set()
    await asyncio.wait_for(asyncio.gather(*calls.tasks.values()), WAIT)
    assert calls.order == ["holder", "first", "second", "person", "summary"], (
        "the background call went ahead of a request a person made after it")
    assert _count() == 0
