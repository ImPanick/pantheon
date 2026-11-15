# SPDX-License-Identifier: AGPL-3.0-or-later
"""`B2128`: what the model is sent of a tool's work, round after round.

The owner, 2026-11-15: *"per-round trimming is also critical as well, we can
take a users dense input - and trim what the model wouldn't need to do the
same job at the same quality"*. Measured on `fix/agent-lean-turn` before this:
a shell's colour codes and progress lines reached the model as sent; a tool's
structured payload went as `indent=2` JSON; and once a long turn's own results
outgrew the budget, the agent's instructions were cut to 2,000 characters
before any earlier result of the turn gave way.
"""
from __future__ import annotations

import importlib.util
import json
import pathlib

from src.context_compactor import (
    PROMPT_CUT_NOTICE, TURN_RESULTS_LEFT_OUT_WORDS, trim_for_context, trim_left_out,
)
from src.model_context import estimate_tokens
from src.result_shaping import compact_json, shape_terminal_output
from src.tool_execution import format_tool_result

_spec = importlib.util.spec_from_file_location(
    "_long_chat", pathlib.Path(__file__).with_name(
        "test_a_long_chat_keeps_its_instructions_and_its_prefix.py"))
_long = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(_long)


def test_terminal_noise_is_not_sent():
    raw = ("\x1b[32mok\x1b[0m build\n"
           "progress 10%\rprogress 50%\rprogress 100%\n"
           + "warning: same thing\n" * 40 + "done\r\n")
    shaped = shape_terminal_output(raw)
    assert "\x1b" not in shaped
    assert "ok build" in shaped and "progress 100%" in shaped and "progress 10%" not in shaped
    assert shaped.count("warning: same thing") == 1 and "39 more times" in shaped
    assert shaped.endswith("done\r\n"), "a CRLF line ending is a file's, not a progress bar"
    assert len(shaped) < len(raw) / 4


def test_a_few_repeats_and_short_base64_are_kept():
    raw = "a\na\na\nb\n" + "QUJD" * 100
    assert shape_terminal_output(raw) == raw


def test_long_base64_is_named_not_sent():
    blob = "QUJD" * 2000
    shaped = shape_terminal_output("image: " + blob + "\nend")
    assert blob not in shaped and "8,000 characters" in shaped and shaped.endswith("end")


def test_the_structured_payload_goes_compact():
    result = {"response": "3 events", "events": [{"title": f"e{i}", "when": "today"} for i in range(30)]}
    text = format_tool_result("calendar", result)
    assert '"events":[{"title":"e0","when":"today"}' in text
    assert json.loads(compact_json(result["events"])) == result["events"]


def test_a_file_read_is_sent_exactly():
    content = "line one   \n\n\n\nkeep\x1b[0m   this\n" * 3
    text = format_tool_result("read", {"content": content, "size": len(content)})
    assert content in text


def test_a_long_turn_keeps_its_instructions_while_its_earlier_results_give_way():
    hold: dict = {}
    firsts, moves = [], 0
    for n in range(1, 16):
        msgs = [_long.PROMPT] + _long._history() + _long._round(n)
        sent = trim_for_context(msgs, _long.BUDGET, hold=hold)
        assert sent[0]["content"] == _long.PROMPT["content"], f"instructions cut in round {n}"
        assert PROMPT_CUT_NOTICE not in sent[0]["content"]
        assert estimate_tokens(sent) <= _long.BUDGET
        newest = msgs[-1]["content"]
        assert any(m.get("content") == newest for m in sent), "the newest result was left out"
        if n >= 10:
            assert TURN_RESULTS_LEFT_OUT_WORDS in trim_left_out(msgs, sent)
        firsts.append(sent[1]["content"])
        if len(firsts) > 1 and firsts[-1] != firsts[-2]:
            moves += 1
    assert moves <= 5, f"the beginning moved {moves} times in 15 rounds"
