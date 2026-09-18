# SPDX-License-Identifier: AGPL-3.0-or-later
"""Backend-reported generation/prefill speed metrics.

llama.cpp emits a `timings` block alongside `usage` on the final stream chunk
with the TRUE decode speed (predicted_per_second) and prompt speed
(prompt_per_second). These are pure-phase numbers; the old per-message t/s was
output_tokens / wall-clock, which includes prefill + tool + network time and so
reads low (and sags as the prompt grows).

These tests lock in two things:
  1. stream_llm passes the llama.cpp `timings` through on the usage event as
     gen_tps / prefill_tps (captured-stream fixture), and omits them when the
     backend doesn't report timings (e.g. cloud APIs).
  2. _compute_final_metrics prefers the backend gen speed over wall-clock when
     present, tags tps_source accordingly, and surfaces prefill_tps.
"""
import json
import asyncio

import pytest

from src import llm_core
from src.agent_loop import _compute_final_metrics


# --- captured-stream harness (mirrors test_llm_core_streaming.py) -----------

class _FakeResp:
    def __init__(self, lines):
        self._lines = lines
        self.status_code = 200

    async def aiter_lines(self):
        for ln in self._lines:
            yield ln

    async def aread(self):
        return b""


class _FakeStreamCtx:
    def __init__(self, lines):
        self._lines = lines

    async def __aenter__(self):
        return _FakeResp(self._lines)

    async def __aexit__(self, *a):
        return False


class _FakeClient:
    def __init__(self, lines):
        self._lines = lines

    def stream(self, method, url, **kw):
        return _FakeStreamCtx(self._lines)


def _usage_event(monkeypatch, lines):
    """Drive stream_llm against canned SSE lines; return the usage event data."""
    monkeypatch.setattr(llm_core, "_get_http_client", lambda: _FakeClient(lines))
    monkeypatch.setattr(llm_core, "_is_host_dead", lambda u: False)
    monkeypatch.setattr(llm_core, "note_model_activity", lambda *a, **k: None)
    monkeypatch.setattr(llm_core, "_clear_host_dead", lambda *a, **k: None)

    async def run():
        usage = None
        async for chunk in llm_core.stream_llm(
            "http://127.0.0.1:8081/v1/chat/completions",
            "qwen-local",
            [{"role": "user", "content": "hi"}],
        ):
            for ln in chunk.split("\n"):
                ln = ln.strip()
                if ln.startswith("data: ") and ln[6:] != "[DONE]":
                    try:
                        ev = json.loads(ln[6:])
                    except ValueError:
                        continue
                    if ev.get("type") == "usage":
                        usage = ev["data"]
        return usage

    return asyncio.run(run())


def _stream_events(monkeypatch, lines):
    """Drive stream_llm and return all JSON data events."""
    monkeypatch.setattr(llm_core, "_get_http_client", lambda: _FakeClient(lines))
    monkeypatch.setattr(llm_core, "_is_host_dead", lambda u: False)
    monkeypatch.setattr(llm_core, "note_model_activity", lambda *a, **k: None)
    monkeypatch.setattr(llm_core, "_clear_host_dead", lambda *a, **k: None)

    async def run():
        events = []
        async for chunk in llm_core.stream_llm(
            "http://127.0.0.1:8081/v1/chat/completions",
            "openrouter/auto",
            [{"role": "user", "content": "hi"}],
        ):
            for ln in chunk.split("\n"):
                ln = ln.strip()
                if ln.startswith("data: ") and ln[6:] != "[DONE]":
                    try:
                        events.append(json.loads(ln[6:]))
                    except ValueError:
                        pass
        return events

    return asyncio.run(run())


# A real llama.cpp final chunk carries `usage` (delta empty / choices []) with a
# sibling `timings` block. The decode speed here (78.91) is far above the
# wall-clock figure the old code would have shown.
_LLAMACPP_TIMINGS_STREAM = [
    'data: ' + json.dumps({"choices": [{"index": 0, "delta": {"content": "Hi there"}}]}),
    'data: ' + json.dumps({
        "choices": [],
        "object": "chat.completion.chunk",
        "usage": {"prompt_tokens": 15, "completion_tokens": 42},
        # `P4-14`. The `prompt_ms` / `predicted_ms` halves were added to this
        # fixture on 2026-09-18. A real llama.cpp `timings` block has carried
        # all eight keys (`*_ms`, `*_n`, `*_per_token_ms`, `*_per_second`) for
        # as long as the block has existed; this fixture carried only the two
        # per-second rates, which is exactly the subset the passthrough kept —
        # so the fixture could not have caught the drop.
        "timings": {
            "prompt_n": 15, "prompt_ms": 29.28, "prompt_per_second": 512.34,
            "predicted_n": 42, "predicted_ms": 532.25, "predicted_per_second": 78.91,
        },
    }),
    "data: [DONE]",
]


def test_stream_llm_passes_through_llamacpp_timings(monkeypatch):
    usage = _usage_event(monkeypatch, _LLAMACPP_TIMINGS_STREAM)
    assert usage is not None, "no usage event was emitted"
    assert usage["input_tokens"] == 15
    assert usage["output_tokens"] == 42
    # The timings block is surfaced as gen_tps / prefill_tps (rounded to 2dp).
    assert usage["gen_tps"] == 78.91
    assert usage["prefill_tps"] == 512.34


def test_stream_llm_omits_tps_when_backend_has_no_timings(monkeypatch):
    # A backend (e.g. a cloud API) that reports usage but no `timings` block must
    # not invent gen_tps/prefill_tps — the caller then falls back to wall-clock.
    no_timings = [
        'data: ' + json.dumps({"choices": [{"index": 0, "delta": {"content": "Hi"}}]}),
        'data: ' + json.dumps({
            "choices": [],
            "usage": {"prompt_tokens": 8, "completion_tokens": 5},
        }),
        "data: [DONE]",
    ]
    usage = _usage_event(monkeypatch, no_timings)
    assert usage is not None
    assert "gen_tps" not in usage
    assert "prefill_tps" not in usage


def test_stream_llm_surfaces_provider_resolved_model(monkeypatch):
    events = _stream_events(monkeypatch, [
        'data: ' + json.dumps({
            "model": "meta-llama/llama-3.3-70b-instruct:free",
            "choices": [{"index": 0, "delta": {"content": "Hi"}}],
        }),
        'data: ' + json.dumps({
            "model": "meta-llama/llama-3.3-70b-instruct:free",
            "choices": [],
            "usage": {"prompt_tokens": 8, "completion_tokens": 5},
        }),
        "data: [DONE]",
    ])

    actual = [e for e in events if e.get("type") == "model_actual"]
    assert actual == [{
        "type": "model_actual",
        "requested_model": "openrouter/auto",
        "model": "meta-llama/llama-3.3-70b-instruct:free",
    }]
    usage = [e["data"] for e in events if e.get("type") == "usage"][0]
    assert usage["requested_model"] == "openrouter/auto"
    assert usage["model"] == "meta-llama/llama-3.3-70b-instruct:free"


# --- _compute_final_metrics preference logic --------------------------------

def _metrics(**overrides):
    kwargs = dict(
        messages=[{"role": "user", "content": "hi"}],
        full_response="hello world",
        total_duration=10.0,           # wall-clock: 42/10 = 4.2 t/s (reads low)
        time_to_first_token=0.5,
        context_length=4096,
        real_input_tokens=15,
        real_output_tokens=42,
        has_real_usage=True,
        tool_events=[],
        round_texts=[],
        model="qwen-local",
    )
    kwargs.update(overrides)
    return _compute_final_metrics(**kwargs)


def test_metrics_prefer_backend_gen_tps_over_wallclock():
    m = _metrics(backend_gen_tps=78.91, backend_prefill_tps=512.34)
    # Uses the backend's true decode speed, NOT 42/10 = 4.2.
    assert m["tokens_per_second"] == 78.91
    assert m["tps_source"] == "backend"
    assert m["prefill_tps"] == 512.34


def test_metrics_fall_back_to_wallclock_without_backend_timings():
    m = _metrics(backend_gen_tps=0, backend_prefill_tps=0)
    # 42 output tokens / 10s wall-clock.
    assert m["tokens_per_second"] == 4.2
    assert m["tps_source"] == "computed"
    assert "prefill_tps" not in m


# ── `P4-14` — prefill and decode, separated and measured ────────────────────
#
# Re-measured 2026-09-18 against the source, and the row's premise is half
# landed already: `gen_tps`, `prefill_tps` and the `tps_source` enum exist and
# the two tests above pin them. What is *not* measured is the part the row's
# own word is about.
#
# llama.cpp's `timings` block reports eight figures. Only the two *derived*
# per-second rates were passed through, and the durations and token counts
# they were derived from were dropped on the floor — so the product kept the quotient and threw away
# the measurement. Nothing downstream could separate prefill from decode *in
# time*, check a reported rate against anything, or tell a 40ms prefill from a
# 4s one on the same 78 t/s decode.
#
# `response_time` and `time_to_first_token` are wall clocks and stay wall
# clocks — no backend reports a TTFT — so the honest split is: the durations
# are present exactly when a backend measured them, and absent otherwise.
# Absence means "not reported", the same contract `P4-22` set for the prompt
# cache, and for the same reason: a `prefill_ms: 0` on a cloud API would read
# as an instantaneous prefill rather than as a backend that does not say.

def test_stream_llm_passes_through_the_measured_prefill_and_decode_figures(monkeypatch):
    usage = _usage_event(monkeypatch, _LLAMACPP_TIMINGS_STREAM)
    assert usage is not None
    assert usage["prefill_ms"] == 29.28
    assert usage["decode_ms"] == 532.25
    assert usage["prefill_tokens"] == 15
    assert usage["decode_tokens"] == 42


def test_the_passed_through_durations_are_the_ones_the_rates_came_from(monkeypatch):
    """The point of carrying the durations: the rate becomes checkable.

    A quotient nobody can divide back out is a claim, not a measurement. These
    four figures are one measurement reported two ways by the backend, so they
    have to agree here or the passthrough picked the wrong keys.
    """
    usage = _usage_event(monkeypatch, _LLAMACPP_TIMINGS_STREAM)
    assert usage["decode_tokens"] / (usage["decode_ms"] / 1000) == pytest.approx(
        usage["gen_tps"], rel=0.01
    )
    assert usage["prefill_tokens"] / (usage["prefill_ms"] / 1000) == pytest.approx(
        usage["prefill_tps"], rel=0.01
    )


def test_stream_llm_omits_the_durations_when_the_backend_reports_none(monkeypatch):
    no_timings = [
        'data: ' + json.dumps({"choices": [{"index": 0, "delta": {"content": "Hi"}}]}),
        'data: ' + json.dumps({
            "choices": [],
            "usage": {"prompt_tokens": 8, "completion_tokens": 5},
        }),
        "data: [DONE]",
    ]
    usage = _usage_event(monkeypatch, no_timings)
    assert usage is not None
    for key in ("prefill_ms", "decode_ms", "prefill_tokens", "decode_tokens"):
        assert key not in usage, f"{key} invented on a backend that reported nothing"


def test_a_partial_timings_block_carries_only_what_it_measured(monkeypatch):
    # vLLM and a few llama.cpp builds report the prompt half and not the
    # predicted half. Half a measurement is still a measurement; inventing the
    # other half from wall-clock would be the defect this row exists for.
    partial = [
        'data: ' + json.dumps({"choices": [{"index": 0, "delta": {"content": "Hi"}}]}),
        'data: ' + json.dumps({
            "choices": [],
            "usage": {"prompt_tokens": 15, "completion_tokens": 42},
            "timings": {"prompt_n": 15, "prompt_ms": 29.28},
        }),
        "data: [DONE]",
    ]
    usage = _usage_event(monkeypatch, partial)
    assert usage["prefill_ms"] == 29.28
    assert usage["prefill_tokens"] == 15
    assert "decode_ms" not in usage
    assert "decode_tokens" not in usage


def test_metrics_separate_prefill_from_decode_when_a_backend_measured_them():
    m = _metrics(
        backend_gen_tps=78.91,
        backend_prefill_tps=512.34,
        backend_prefill_ms=29.28,
        backend_decode_ms=532.25,
        backend_prefill_tokens=15,
        backend_decode_tokens=42,
    )
    assert m["prefill_ms"] == 29.28
    assert m["decode_ms"] == 532.25
    assert m["prefill_tokens"] == 15
    assert m["decode_tokens"] == 42
    # The wall clocks stay wall clocks and keep saying so. `response_time` is
    # the whole turn including tools; the two above are the model's own phases.
    assert m["response_time"] == 10.0
    assert m["tps_source"] == "backend"


def test_metrics_omit_the_phase_durations_when_nothing_measured_them():
    m = _metrics(backend_gen_tps=0, backend_prefill_tps=0)
    for key in ("prefill_ms", "decode_ms", "prefill_tokens", "decode_tokens"):
        assert key not in m, f"{key} present with no backend measurement behind it"
    assert m["tps_source"] == "computed"


# ── `P4-07` — the speeds belong to a round, like the tokens already do ───────
#
# Premise re-measured 2026-09-18 and the row's list is already on the wire:
# `_usage_bucket` (`src/agent_loop.py`) has carried round, model, endpoint id
# and label, input/output tokens and the `endpoint_cost_tracked` flag since
# before this wave, they ride the metrics envelope as `usage_buckets`, and the
# envelope is what `add_assistant_message` copies into the stored metadata. The
# half of the row that is still true is its last clause — the only consumer is
# `_metricsBillableCost` (`static/js/chatRenderer.js`), which sums them into one
# cost number and shows none of the attribution.
#
# What was genuinely missing is the speed. `backend_gen_tps` is a single
# variable overwritten by every round, so a five-round agent turn reported the
# *fifth* round's decode speed as the turn's — and the other four were measured
# by the backend, streamed, and dropped. Round 1 against a 40k-token prompt and
# round 5 against a 200-token continuation are not the same measurement, and
# the bucket is where the per-round half of every other figure already lives.

def _agent_metrics(monkeypatch, round_payloads, *, rounds=3):
    """Drive the real `stream_agent_loop` and return its metrics envelope.

    Deliberately the same shape as
    `test_foreground_model_routing.test_agent_metrics_attribute_usage_to_each_answering_route`,
    which is the file that owns per-round attribution: one usage event per
    round, a tool call to force a second round, and the metrics event read off
    the end. Nothing here builds a second dispatcher.
    """
    import src.agent_loop as agent_loop

    calls = 0
    monkeypatch.setattr(agent_loop, "get_setting", lambda key, default=None: default)
    monkeypatch.setattr(agent_loop, "get_mcp_manager", lambda: None)
    monkeypatch.setattr(agent_loop, "estimate_tokens", lambda *args, **kwargs: 10)
    monkeypatch.setattr(
        agent_loop, "_agent_route_tool_mode", lambda *args, **kwargs: (True, False, False)
    )

    async def fake_stream(candidates, messages, **kwargs):
        nonlocal calls
        payload = round_payloads[min(calls, len(round_payloads) - 1)]
        calls += 1
        yield f'data: {json.dumps({"type": "usage", "data": payload})}\n\n'
        if calls < len(round_payloads):
            tool_call = {"name": "bash", "arguments": json.dumps({"command": "printf one"})}
            yield f'data: {json.dumps({"type": "tool_calls", "calls": [tool_call]})}\n\n'
        else:
            yield 'data: {"delta": "done"}\n\n'
        yield "data: [DONE]\n\n"

    async def fake_execute(block, *args, **kwargs):
        return "bash", {"output": "ok", "exit_code": 0}

    monkeypatch.setattr(agent_loop, "stream_llm_with_fallback", fake_stream)
    monkeypatch.setattr(agent_loop, "execute_tool_block", fake_execute)

    async def _drain():
        return [
            chunk
            async for chunk in agent_loop.stream_agent_loop(
                "http://local.test/v1",
                "small-local-model",
                [{"role": "user", "content": "do the thing"}],
                max_rounds=rounds,
                relevant_tools={"bash"},
                _is_teacher_run=True,
            )
        ]

    chunks = asyncio.run(_drain())
    return json.loads(
        next(chunk for chunk in chunks if '"type": "metrics"' in chunk)[6:]
    )["data"]


def test_every_round_keeps_the_speed_the_backend_measured_for_it(monkeypatch):
    metrics = _agent_metrics(monkeypatch, [
        {"input_tokens": 40000, "output_tokens": 30,
         "gen_tps": 12.5, "prefill_tps": 480.0,
         "prefill_ms": 83333.33, "decode_ms": 2400.0,
         "prefill_tokens": 40000, "decode_tokens": 30},
        {"input_tokens": 200, "output_tokens": 10,
         "gen_tps": 91.2, "prefill_tps": 990.0,
         "prefill_ms": 202.02, "decode_ms": 109.65,
         "prefill_tokens": 200, "decode_tokens": 10},
    ])

    buckets = metrics["usage_buckets"]
    assert [b["round"] for b in buckets] == [1, 2]
    assert [b["gen_tps"] for b in buckets] == [12.5, 91.2]
    assert [b["prefill_tps"] for b in buckets] == [480.0, 990.0]
    assert [b["prefill_ms"] for b in buckets] == [83333.33, 202.02]
    assert [b["decode_ms"] for b in buckets] == [2400.0, 109.65]
    # The turn-level figure is still the last round's, which is what the footer
    # has always shown. It is now the summary of a record that survives rather
    # than the only survivor.
    assert metrics["tokens_per_second"] == 91.2
    assert metrics["tps_source"] == "backend"


def test_a_round_the_backend_said_nothing_about_claims_no_speed(monkeypatch):
    """Absent before a measurement and absent again after one.

    The second half is the one worth the third round: the accumulators are
    per-round and reset with the rest of the round state, so a measured round
    followed by a silent one must not leave the silent round wearing its
    predecessor's number. That is the failure mode `backend_gen_tps` has at the
    turn level by design, and the reason this row exists.
    """
    metrics = _agent_metrics(monkeypatch, [
        {"input_tokens": 100, "output_tokens": 10},
        {"input_tokens": 200, "output_tokens": 20,
         "gen_tps": 78.91, "decode_ms": 253.45, "decode_tokens": 20},
        {"input_tokens": 300, "output_tokens": 30},
    ])

    first, second, third = metrics["usage_buckets"]
    for key in ("gen_tps", "prefill_tps", "prefill_ms", "decode_ms"):
        assert key not in first, f"{key} invented for a round nothing measured"
        assert key not in third, f"{key} carried over from the round before it"
    assert second["gen_tps"] == 78.91
    assert second["decode_ms"] == 253.45
    assert "prefill_ms" not in second


def test_the_turn_metrics_carry_the_phase_figures_the_last_round_measured(monkeypatch):
    metrics = _agent_metrics(monkeypatch, [
        {"input_tokens": 200, "output_tokens": 20,
         "gen_tps": 78.91, "prefill_tps": 512.34,
         "prefill_ms": 29.28, "decode_ms": 532.25,
         "prefill_tokens": 15, "decode_tokens": 42},
    ])

    assert metrics["prefill_ms"] == 29.28
    assert metrics["decode_ms"] == 532.25
    assert metrics["prefill_tokens"] == 15
    assert metrics["decode_tokens"] == 42
