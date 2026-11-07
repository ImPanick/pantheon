# SPDX-License-Identifier: AGPL-3.0-or-later
"""`B1758` · a small local model finds its tools, and a desktop run stays light.

The owner, 2026-11-07, with a Gemma 4 12B (LM Studio) chat and its server log:
three `find_tools` calls guessed at words ("Virtual Machine", "remote
desktop") and each answered "Not available on this turn: computer"; the model
then tried `ui_control open_panel workstation`, which is not a panel. His ask:
*"distinguish in the tool search an extremely short description of
everything... along with where to use said skills/tools"*. And, when the run
finally worked: *"it was insanely slow"*.
"""

import asyncio

import pytest

from src import screen_marks
from src.tool_map import AREAS, brief, index_text
from src.tool_policy import (WITHHELD_BY_POLICY, WITHHELD_BY_PRIVILEGE,
                             TurnToolAccess, selectable_tool_names)
from src.tools.system import find_tool_matches


# ── the map ──────────────────────────────────────────────────────────────────

def test_every_tool_a_turn_can_offer_is_on_the_map():
    mapped = {n for _area, tools in AREAS for n in tools}
    left = set(selectable_tool_names()) - mapped - {"find_tools", "ask_user", "update_plan"}
    assert not left, f"add these to src/tool_map.py: {sorted(left)}"


def test_the_whole_index_stays_tiny():
    # The owner's baseline (2026-11-07): a whole session under 7k tokens of
    # tool input. The index of the whole suite is under ~650 tokens.
    text = index_text(selectable_tool_names())
    assert len(text) < 2600, len(text)


def test_the_index_names_the_workstation_desktop_in_the_person_s_words():
    text = index_text({"computer", "agent_browser"})
    line = next(l for l in text.splitlines() if "computer" in l)
    assert "desktop" in line.lower() and "vm" in line.lower()


def test_ui_control_says_which_panels_it_has():
    assert "panels" in brief("ui_control")


def test_mcp_tools_are_counted_not_listed_by_server_id():
    text = index_text({"mcp__47a5fba5__search", "mcp__47a5fba5__get"})
    assert "47a5fba5" not in text and "2 more tools" in text


def test_the_index_is_the_same_bytes_for_the_same_set():
    names = {"computer", "manage_calendar", "git"}
    assert index_text(names) == index_text(set(reversed(sorted(names))))


# ── the search ───────────────────────────────────────────────────────────────

@pytest.mark.parametrize("query", [
    "Virtual Machine Remote Desktop Workstation Workspace",
    "remote desktop vm virtual machine explorer",
    "remote desktop vm workstation ubuntu",
])
def test_the_owner_s_three_searches_find_the_desktop_first(query):
    assert find_tool_matches(query, mcp_tools={})[0]["name"] == "computer"


def test_a_match_answers_with_what_and_when():
    row = find_tool_matches("", ["computer"], mcp_tools={})[0]
    assert " · " in row["description"]


# ── why a tool is not loaded ─────────────────────────────────────────────────

def test_a_tool_the_shell_switch_took_says_so():
    from src.agent_loop import _find_tools_refusal
    access = TurnToolAccess({"computer"}, because=WITHHELD_BY_POLICY)
    said = _find_tools_refusal("computer", access)
    assert "Shell" in said and "turn" in said


def test_a_privilege_cap_says_an_admin_can_change_it():
    from src.agent_loop import _find_tools_refusal
    access = TurnToolAccess({"computer"}, because=WITHHELD_BY_PRIVILEGE)
    assert "admin" in _find_tools_refusal("computer", access)


def test_the_notice_names_what_this_chat_switched_off():
    from src.agent_loop import _switched_off_here
    access = TurnToolAccess({"computer", "bash"}, because=WITHHELD_BY_POLICY)
    line = _switched_off_here(access)
    assert "computer" in line and "Shell" in line
    assert _switched_off_here(TurnToolAccess()) == ""


# ── a desktop run re-reads only the newest screen's marks ────────────────────

def _result(n):
    return (f"Did: click mark {n}. The screen is attached.\n"
            + screen_marks.listing([{"n": 1, "role": "button", "name": f"Go {n}",
                                     "box": [0, 0, 10, 10]}]))


def test_older_mark_lists_are_cut_and_the_newest_kept():
    messages = [{"role": "tool", "content": _result(1)},
                {"role": "assistant", "content": "next"},
                {"role": "user", "content": [{"type": "text", "text": _result(2)}]}]
    assert screen_marks.shed_superseded_marks(messages) == 1
    assert "Go 1" not in messages[0]["content"]
    assert "newer screenshot" in messages[0]["content"]
    assert "Go 2" in messages[2]["content"][0]["text"]
    assert screen_marks.shed_superseded_marks(messages) == 0


# ── a model the server cannot load is skipped for a while ────────────────────

def test_a_model_the_server_could_not_load_is_skipped(monkeypatch):
    from src import llm_core
    monkeypatch.setattr(llm_core, "_unloadable", {})
    url, model = "http://127.0.0.1:1234/v1/chat/completions", "qwen/qwen3.8-27b"
    llm_core._note_unloadable(url, model, 400, '{"error": "Failed to load model \\"x\\"."}')
    assert llm_core._unloadable_reason(url, model)
    assert llm_core._unloadable_reason(url, "google/gemma-4-12b-qat") is None
    llm_core._note_unloadable(url, "other", 500, "CUDA error")
    assert llm_core._unloadable_reason(url, "other") is None


# ── each round's words start a new paragraph ─────────────────────────────────

def test_a_second_round_s_words_are_not_glued_to_the_first(tmp_path):
    from tests.helpers import tool_suite_probe as probe

    async def run():
        async with probe.probe_world(str(tmp_path), mcp_states=("absent",)) as world:
            cell = probe.Cell(embeddings="down", mcp="absent", window="large", mode="agent")
            # The first round promises an action and makes no call, so the loop
            # nudges and asks again: two rounds of text in one reply.
            return await probe.drive_turn(
                world, cell, "Is the server up?",
                script=["I will check the logs now.", "Understood. It is up."],
                dispatch="real")

    record = asyncio.run(run())
    text = "".join(str(ev.get("delta") or "") for ev in record.events
                   if ev.get("delta") and not ev.get("thinking"))
    assert "now.Understood" not in text
    assert "now.\n\nUnderstood" in text
