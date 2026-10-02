# SPDX-License-Identifier: AGPL-3.0-or-later
"""`P22-11` / `P22-17` — a step that parks says so, in the node vocabulary
(`src/builtin_actions.py`: `NODE_STATUS_WAITING`, `TaskWaiting`).

`SLICE-CD-DESIGN` § 1.4: a run that reaches a Wait or a step that needs a yes
parks as `waiting`, and the coroutine exits. `TaskWaiting` is the signal, a
`BaseException` beside `TaskNoop` and `TaskDeferred` for their reason: an
`except Exception` fallback (`_execute_llm_task`'s) must not swallow it and
turn a parked step into a failed one. `NodeResult` reads it both ways, as it
reads the other two (`Law 14`: the fifth word is added where the four are).
"""

import pytest

from src import builtin_actions as ba


def test_waiting_is_the_fifth_node_status_and_a_result_can_carry_it():
    assert ba.NODE_STATUS_WAITING == "waiting"
    assert ba.NODE_STATUSES == ("success", "error", "skipped", "deferred", "waiting")
    res = ba.NodeResult(ba.NODE_STATUS_WAITING, payload="Waiting until 08:00")
    assert (res.status, res.text, res.ok, res.failed) == ("waiting", "Waiting until 08:00",
                                                          False, False)
    assert ba.coerce_node_result(("Waiting for your yes", "waiting")).status == "waiting"


def test_an_except_exception_fallback_cannot_swallow_a_parked_step():
    def executor():
        try:
            raise ba.TaskWaiting("Waiting for your yes on “Send reply”", kind="approval",
                                 approval_id="ap-1", session_id="s-1", card={"tool": "send_reply"})
        except Exception:  # noqa: BLE001 - the fallback this guards against
            return "the step failed"

    with pytest.raises(ba.TaskWaiting) as err:
        executor()
    signal = err.value
    assert (signal.summary, signal.kind) == ("Waiting for your yes on “Send reply”", "approval")
    assert signal.details == {"approval_id": "ap-1", "session_id": "s-1",
                              "card": {"tool": "send_reply"}}


def test_the_signal_and_the_status_read_each_other():
    res = ba.NodeResult.from_signal(ba.TaskWaiting("Waiting until 08:00", kind="time"))
    assert (res.status, res.text) == ("waiting", "Waiting until 08:00")
    back = res.as_signal()
    assert isinstance(back, ba.TaskWaiting) and back.summary == "Waiting until 08:00"
    assert isinstance(ba.NodeResult(ba.NODE_STATUS_WAITING).as_signal(), ba.TaskWaiting)
    # The other two signals still read as before.
    assert ba.NodeResult.from_signal(ba.TaskNoop("nothing")).status == "skipped"
    assert ba.NodeResult.from_signal(ba.TaskDeferred("later", 60)).status == "deferred"


def test_a_wait_is_for_a_time_a_yes_or_an_idle_pantheon_and_nothing_else():
    assert ba.WAIT_KINDS == ("time", "approval", "idle")
    for kind in (*ba.WAIT_KINDS, None):
        assert ba.TaskWaiting("x", kind=kind).kind == kind
    with pytest.raises(ValueError):
        ba.TaskWaiting("x", kind="forever")
