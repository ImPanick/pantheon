# SPDX-License-Identifier: AGPL-3.0-or-later
"""Apollo's orb (phase 6), the server half: `ui_control show <place>` becomes
the `orb_show` event the browser follows (`src/apollo/orb.py`).

It names places, never CSS the model can't know; it reads and changes nothing
on the server; a line range is put the right way round and capped; and the
structured call (`action: show`) reads the same as the typed one in both
places that turn a call into a command. Apollo is told it has the orb.
"""
from __future__ import annotations

import asyncio

import pytest

from src.apollo import orb
from src.apollo.frame import character
from src.ai_interaction import do_ui_control


def _show(text):
    return asyncio.run(do_ui_control(text))


def test_a_place_becomes_an_orb_show_event():
    assert _show("show needs_you") == {
        "ui_event": "orb_show", "place": "needs_you",
        "results": "Pointing at Needs you. If that place isn't on their screen, nothing moves."}
    r = _show("show task 3f2a-91 Waiting on your answer")
    assert (r["place"], r["target"], r["label"]) == ("task", "3f2a-91", "Waiting on your answer")


@pytest.mark.parametrize("text,lines,target", [
    ("show code lines=12-18", [12, 18], None),
    ("show code 2 18-12", [12, 18], 2),
    ("show code 12 - 18", [12, 18], None),
    ("show code 1 lines=7", [7, 7], 1),
    ("show view editor lines=1-9000", [1, orb.MAX_LINES], None),
])
def test_line_ranges_are_read_the_right_way_round_and_capped(text, lines, target):
    r = _show(text)
    assert r["lines"] == lines
    if target is not None:
        assert r["target"] == target
    assert "label" not in r


def test_aliases_and_words_after_the_range_are_its_label():
    r = _show("show composer")
    assert r["place"] == "chat_input"
    r = _show("show code lines=3-4 this line drops the error")
    assert (r["lines"], r["label"]) == ([3, 4], "this line drops the error")
    assert r["results"].endswith("lines 3 to 4. If that place isn't on their screen, nothing moves.")


@pytest.mark.parametrize("text", ["show", "show elsewhere", "show task", "show view", "show task ../etc/passwd",
                                  "show task <script>"])
def test_what_it_cant_follow_is_refused_in_words(text):
    r = _show(text)
    assert set(r) == {"error"} and r["error"]


def test_a_label_is_kept_to_a_line():
    r = _show("show pane " + "word " * 80)
    assert len(r["label"]) == orb.MAX_LABEL


def test_the_structured_call_reads_as_the_typed_one():
    args = {"action": "show", "name": "code", "value": "2", "lines": "12 - 18", "label": "  look   here "}
    assert orb.show_content(args) == "show code 2 lines=12-18 look here"
    assert _show(orb.show_content(args))["lines"] == [12, 18]
    assert orb.show_content({"action": "show", "name": "home"}) == "show home"


def test_both_converters_send_show_to_the_orb():
    from src import tool_parsing, tool_schemas
    src_p = open(tool_parsing.__file__, encoding="utf-8").read()
    src_s = open(tool_schemas.__file__, encoding="utf-8").read()
    for text in (src_p, src_s):
        assert 'elif action == "show":' in text and "show_content(args)" in text
    ui = next(f["function"] for f in tool_schemas.FUNCTION_TOOL_SCHEMAS if f["function"]["name"] == "ui_control")
    assert "show" in ui["parameters"]["properties"]["action"]["enum"]
    assert {"lines", "label"} <= set(ui["parameters"]["properties"])


def test_apollo_is_told_it_has_the_orb():
    text = character("sam")
    assert "orb" in text and "ui_control" in text and "action show" in text


def test_pointing_wakes_the_ui_tools():
    from src.agent_loop import _classify_agent_request
    q = "point at the line that breaks"
    assert "ui" in _classify_agent_request([{"role": "user", "content": q}], q)["domains"]
