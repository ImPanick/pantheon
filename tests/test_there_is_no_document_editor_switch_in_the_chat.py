# SPDX-License-Identifier: AGPL-3.0-or-later
"""`B898` — `ui_control toggle document_editor` reported success and did nothing.

The executor accepted it (`src/ui_switches.TOGGLES`), the tool schema and the
system prompt advertised it, and the model was told *"Toggle 'document_editor'
set to on"* — but the browser has no Document Editor switch to move:
`TOGGLE_CHECKBOX_IDS` in `static/js/chatStream.js` has no entry for it, and
nothing reads it from storage. The Document Editor is a server feature flag an
admin sets for everyone (`H05`), not a per-browser toggle. `Law 13`.

The row offered two fixes and the right one is the second: stop accepting and
advertising it, and refuse with a sentence saying where the real switch is.
Driven through the real executor, the real gate and the real browser module
(`Law 20`).
"""
from __future__ import annotations

import asyncio
import json
import shutil
import subprocess
from pathlib import Path

import pytest

import src.agent_tools  # noqa: F401
from src.ai_interaction import do_ui_control
from src.tool_capabilities import ToolRunSecurityContext, self_escalation_for

ROOT = Path(__file__).resolve().parent.parent


@pytest.mark.parametrize("content", [
    "toggle document_editor off", "toggle document_editor on",
    "toggle documents off", "toggle docs on", "TOGGLE Doc off",
])
def test_the_toggle_is_refused_with_a_sentence_saying_where_the_switch_is(content):
    """The row's `Verify:` — refused with a sentence saying there is no such switch."""
    result = asyncio.run(do_ui_control(content))
    assert "ui_event" not in result, result
    assert result["error"].startswith("There is no Document Editor switch in the chat."), result
    assert "Settings → Agent Tools → Switched on for everyone" in result["error"]


def test_the_gate_reads_it_as_moving_nothing():
    """Not a widening to ask about: it moves nothing, the gate's own reading."""
    assert self_escalation_for("ui_control", "toggle document_editor on") is None
    assert ToolRunSecurityContext().decision_for(
        "ui_control", "toggle document_editor on").allowed is True


def test_nothing_offers_the_model_a_switch_the_chat_does_not_have():
    """Every toggle the executor accepts or lists is one the browser moves."""
    from src.tool_schemas import FUNCTION_TOOL_SCHEMAS
    from src.ui_switches import TOGGLES

    listed = asyncio.run(do_ui_control("get_toggles"))["results"]
    assert "document_editor" not in listed
    assert "document_editor" not in TOGGLES
    ui = next(s for s in FUNCTION_TOOL_SCHEMAS if s["function"]["name"] == "ui_control")
    name_help = ui["function"]["parameters"]["properties"]["name"]["description"]
    toggle_help = name_help.split("For toggle:", 1)[1].split(".", 1)[0]
    assert "document_editor" not in toggle_help


@pytest.mark.skipif(not shutil.which("node"), reason="node binary not on PATH")
def test_every_accepted_toggle_has_a_control_in_the_chat():
    """The other direction, asked of the browser module itself: each switch the
    executor accepts is one `chatStream.js` knows how to move."""
    from src.ui_switches import TOGGLES

    source = (ROOT / "static" / "js" / "chatStream.js").read_text(encoding="utf-8")
    block = source.split("export const TOGGLE_CHECKBOX_IDS = Object.freeze(", 1)[1]
    block = block.split(");", 1)[0]
    keys = subprocess.run(
        ["node", "-e", f"process.stdout.write(JSON.stringify(Object.keys({block})))"],
        capture_output=True, text=True, check=True).stdout
    assert set(TOGGLES) <= set(json.loads(keys)), (sorted(TOGGLES), keys)
