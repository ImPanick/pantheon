# SPDX-License-Identifier: AGPL-3.0-or-later
"""`B1383`: a call naming a tool nothing registers is refused, and said.

`function_call_to_tool_block` refuses the name — the control that must never
stand down, and every case here asserts it held: the name never reaches the
dispatcher. What the person read was *"The model returned an empty response.
Please try again or switch to a different model."* The model had not returned
an empty response; it had asked for a tool that does not exist, and the only
record of that was a log line (`-> FAILED to convert native call`).

Now the refusal is a `tool_blocked` row naming the tool (live and persisted),
and the model is handed the round back with the fact, capped, so a turn ends
on an answer or on a sentence about what happened — never on "empty".

Driven through the real `stream_agent_loop` with a scripted model; the
probe-world case is
`tests/test_every_tool_in_the_suite_is_reachable_and_callable.py::
test_a_call_to_a_name_nobody_registered_is_not_routed`.
"""
import asyncio
import json

import src.agent_loop as agent_loop

BOGUS = "definitely_not_a_pantheon_tool"


def _call(name, args=None):
    return {"name": name, "arguments": json.dumps(args or {})}


def _drive(monkeypatch, script, *, max_rounds=5):
    """`script` is one entry per round: a list of native calls, or a string
    of prose. Returns (events, dispatched, requests)."""
    dispatched, requests = [], []
    rounds = iter(script)
    monkeypatch.setattr(agent_loop, "get_setting", lambda key, default=None: default)
    monkeypatch.setattr(agent_loop, "get_mcp_manager", lambda: None)
    monkeypatch.setattr(agent_loop, "estimate_tokens", lambda *args, **kwargs: 10)
    monkeypatch.setattr(agent_loop, "blocked_tools_for_owner", lambda owner: set())
    monkeypatch.setattr(
        agent_loop, "_agent_route_tool_mode", lambda *args, **kwargs: (True, False, False)
    )

    async def fake_stream(candidates, messages, **kwargs):
        requests.append([dict(m) for m in messages])
        step = next(rounds, "All done.")
        if isinstance(step, list):
            yield f'data: {json.dumps({"type": "tool_calls", "calls": step})}\n\n'
        else:
            yield "data: " + json.dumps({"delta": step}) + "\n\n"
        yield "data: [DONE]\n\n"

    async def fake_execute(block, *args, **kwargs):
        dispatched.append(block.tool_type)
        return block.tool_type, {"output": "ok", "exit_code": 0}

    monkeypatch.setattr(agent_loop, "stream_llm_with_fallback", fake_stream)
    monkeypatch.setattr(agent_loop, "execute_tool_block", fake_execute)

    async def _drain():
        return [
            chunk
            async for chunk in agent_loop.stream_agent_loop(
                "http://local.test/v1",
                "small-local-model",
                [{"role": "user", "content": "check the weather in the shell"}],
                max_rounds=max_rounds,
                relevant_tools={"bash", "ask_user", "update_plan"},
                owner="local",
                _is_teacher_run=True,
            )
        ]

    events = []
    for chunk in asyncio.run(_drain()):
        if chunk.startswith("data: {"):
            try:
                events.append(json.loads(chunk[6:]))
            except json.JSONDecodeError:
                pass
    assert BOGUS not in dispatched, "an unknown name was dispatched: the control stood down"
    return events, dispatched, requests


def _reply(events):
    return "".join(e.get("delta", "") for e in events if "delta" in e and not e.get("thinking"))


def _metrics(events):
    return next(e["data"] for e in events if e.get("type") == "metrics")


def test_the_refusal_names_the_tool_and_the_model_gets_the_round_back(monkeypatch):
    events, _dispatched, requests = _drive(monkeypatch, [[_call(BOGUS)], "Done."])

    held = [e for e in events if e.get("type") == "tool_blocked"]
    assert [e["tool"] for e in held] == [BOGUS]
    assert held[0]["policy"] == "unknown_tool"
    assert f"'{BOGUS}'" in held[0]["reason"] and "nothing ran" in held[0]["reason"]

    reply = _reply(events)
    assert "empty response" not in reply
    assert reply.strip().endswith("Done.")

    # The model was told, in the request that followed.
    assert len(requests) == 2
    told = "\n".join(str(m.get("content") or "") for m in requests[1])
    assert f"`{BOGUS}`" in told and "no tool by that name exists" in told

    # And the record a reload draws from carries the same row.
    persisted = [e for e in _metrics(events).get("tool_events", []) if e.get("tool") == BOGUS]
    assert persisted and persisted[0]["blocked"] is True
    assert persisted[0]["policy"] == "unknown_tool"


def test_a_model_that_keeps_inventing_names_ends_on_what_happened(monkeypatch):
    events, _dispatched, requests = _drive(
        monkeypatch, [[_call(BOGUS)]] * 6, max_rounds=6)
    # One first try and `_MAX_UNKNOWN_TOOL_NUDGES` hand-backs, then it ends.
    assert len(requests) == 1 + agent_loop._MAX_UNKNOWN_TOOL_NUDGES
    reply = _reply(events)
    assert "empty response" not in reply
    assert "switch to a different model" not in reply
    assert "does not exist" in reply and f"'{BOGUS}'" in reply


def test_a_real_call_beside_an_unknown_one_still_runs_and_the_model_is_told(monkeypatch):
    events, dispatched, requests = _drive(
        monkeypatch,
        [[_call("bash", {"command": "echo hi"}), _call(BOGUS)], "Done."],
    )
    assert dispatched == ["bash"]
    assert [e["tool"] for e in events if e.get("type") == "tool_blocked"] == [BOGUS]
    told = "\n".join(str(m.get("content") or "") for m in requests[1])
    assert f"`{BOGUS}`" in told


def test_a_call_that_names_a_real_tool_badly_is_not_called_unknown(monkeypatch):
    """`bash` with no command fails conversion for its arguments, not its
    name: it is not "a tool that does not exist" and gets no such row."""
    events, _dispatched, _requests = _drive(monkeypatch, [[_call("bash", {})], "Done."])
    assert not [e for e in events if e.get("policy") == "unknown_tool"]
