# SPDX-License-Identifier: AGPL-3.0-or-later
"""`B741`: the direct (low-signal, single-call) path keeps the speed the
backend measured.

It read `model`, `input_tokens` and `output_tokens` off the usage event and
stepped over `gen_tps` and `prefill_tps`, so its usage bucket carried no speed
— which, under the absence contract, reads as *the backend did not report
one*. On a local llama.cpp that is false. The agent path read all six timing
keys, so the two branches disagreed about what a usage event contains.

`Verify:` a one-shot local turn reports the same measured decode speed an
agent turn on the same model does. Both halves drive the real
`stream_agent_loop`; the agent half reuses `test_chat_metrics._agent_metrics`,
the file that owns per-round speed, rather than building a second harness.
"""

import asyncio
import json

import pytest

import src.agent_loop as agent_loop
from tests.test_chat_metrics import _agent_metrics

USAGE = {
    "model": "small-local-model",
    "input_tokens": 200,
    "output_tokens": 20,
    "gen_tps": 78.91,
    "prefill_tps": 512.34,
    "prefill_ms": 29.28,
    "decode_ms": 532.25,
    "prefill_tokens": 15,
    "decode_tokens": 42,
}


def _direct_metrics(monkeypatch, usage, *, terminal_error=False):
    """Drive the direct low-signal branch of the real loop and return the
    envelope it ends on (`metrics`, or `agent_terminal` on a provider error)."""
    monkeypatch.setattr(agent_loop, "get_setting", lambda key, default=None: default)
    monkeypatch.setattr(agent_loop, "get_mcp_manager", lambda: None)
    monkeypatch.setattr(agent_loop, "estimate_tokens", lambda *args, **kwargs: 10)
    monkeypatch.setattr(
        agent_loop,
        "_classify_agent_request",
        lambda messages, latest, approved_plan=None: {
            "low_signal": True,
            "continuation": False,
            "domains": [],
            "retrieval_query": latest,
        },
    )
    monkeypatch.setattr(agent_loop, "_is_casual_low_signal", lambda latest: True)

    async def fake_stream(candidates, messages, **kwargs):
        yield f'data: {json.dumps({"type": "usage", "data": usage})}\n\n'
        yield 'data: {"delta": "hey there"}\n\n'
        if terminal_error:
            yield 'event: error\ndata: {"status": 503, "error": "gone"}\n\n'
        else:
            yield "data: [DONE]\n\n"

    monkeypatch.setattr(agent_loop, "stream_llm_with_fallback", fake_stream)

    async def _drain():
        return [
            chunk
            async for chunk in agent_loop.stream_agent_loop(
                "http://local.test/v1",
                "small-local-model",
                [{"role": "user", "content": "hello"}],
                relevant_tools=set(),
                _is_teacher_run=True,
            )
        ]

    chunks = asyncio.run(_drain())
    event_type = "agent_terminal" if terminal_error else "metrics"
    data = json.loads(
        next(chunk for chunk in chunks if f'"type": "{event_type}"' in chunk)[6:]
    )["data"]
    if not terminal_error:
        assert data.get("direct_low_signal") is True, "the direct branch did not run"
    return data


def test_a_one_shot_reply_reports_the_speed_an_agent_turn_does(monkeypatch):
    direct = _direct_metrics(monkeypatch, USAGE)
    agent = _agent_metrics(monkeypatch, [USAGE], rounds=2)

    assert direct["tokens_per_second"] == agent["tokens_per_second"] == 78.91
    assert direct["tps_source"] == agent["tps_source"] == "backend"
    for key in ("prefill_tps", "prefill_ms", "decode_ms", "prefill_tokens", "decode_tokens"):
        assert direct[key] == agent[key], key

    (direct_bucket,) = direct["usage_buckets"]
    agent_bucket = agent["usage_buckets"][-1]
    for key in ("gen_tps", "prefill_tps", "prefill_ms", "decode_ms"):
        assert direct_bucket[key] == agent_bucket[key], key


def test_a_one_shot_reply_whose_backend_said_nothing_claims_no_speed(monkeypatch):
    direct = _direct_metrics(
        monkeypatch, {"model": "cloud-model", "input_tokens": 5, "output_tokens": 3}
    )
    (bucket,) = direct["usage_buckets"]
    for key in ("gen_tps", "prefill_tps", "prefill_ms", "decode_ms"):
        assert key not in bucket, f"{key} invented for a call nothing measured"
    for key in ("prefill_tps", "prefill_ms", "decode_ms", "prefill_tokens", "decode_tokens"):
        assert key not in direct, key
    assert direct["tps_source"] == "computed"


def test_a_one_shot_reply_cut_off_keeps_the_speed_in_its_partial_record(monkeypatch):
    terminal = _direct_metrics(monkeypatch, USAGE, terminal_error=True)
    (bucket,) = terminal["usage_buckets"]
    assert bucket["gen_tps"] == pytest.approx(78.91)
    assert bucket["prefill_tps"] == pytest.approx(512.34)
