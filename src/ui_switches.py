# SPDX-License-Identifier: AGPL-3.0-or-later
"""The chat's own switches, as the model names them in a `ui_control` call.

`P7-02`. Two readers, one parser. `src/ai_interaction.do_ui_control` carries out
`toggle <name> <on|off>` and `set_mode <agent|chat>`, and the approval gate in
`src/tool_capabilities.py` has to know, *before* either runs, whether the call
would give the assistant more reach than the person left it with. If the gate
read the command one way and the executor another, every difference between the
two readings would be a spelling the model could use to switch a tool on without
asking — an alias the gate did not know, a capital letter it did not fold, a tab
where it expected a space.

So the reading lives here, once, and `switch_request` returns **the very dict
`do_ui_control` hands back** for those two commands — the executor returns it and
the gate inspects it. There is no second interpretation to drift (`Law 7`).

A leaf on purpose: `src/tool_capabilities.py` imports this, and that module must
stay light enough for everything on the dispatch path to import. Standard
library plus `src.env_flags`, which is itself standard library only.
"""
from __future__ import annotations

from types import MappingProxyType
from typing import Any, Mapping

from src.env_flags import tool_arg_truthy

# Moved here verbatim from `do_ui_control`, where it was a local dict. Friendly
# names people and models use for the switches — "shell", "search".
TOGGLE_ALIASES: Mapping[str, str] = MappingProxyType({
    "shell": "bash",
    "terminal": "bash",
    "search": "web",
    "websearch": "web",
    "web_search": "web",
    "deepresearch": "research",
    "deep_research": "research",
    "documents": "document_editor",
    "doc": "document_editor",
    "docs": "document_editor",
    "private": "incognito",
})

# The switches `toggle` accepts, after aliasing. Order is irrelevant; the error
# message sorts them.
TOGGLES = frozenset({"web", "bash", "rag", "research", "incognito", "document_editor"})

MODES = ("agent", "chat")

# The two commands that move a switch. Every other `ui_control` action — panels,
# themes, a model switch, an email draft — is read by `do_ui_control` itself.
SWITCH_ACTIONS = frozenset({"toggle", "set_mode"})


def command_parts(content: Any) -> list[str]:
    """`do_ui_control`'s tokenisation of a command: the first line, split in three.

    `str.split(None, 2)` splits on any run of whitespace, so a tab, a double
    space or a non-breaking space all separate words here exactly as they do in
    the executor — because this is the executor's reading.
    """
    lines = str(content).strip().split("\n")
    return lines[0].strip().split(None, 2)


def switch_request(content: Any) -> dict | None:
    """What `do_ui_control` answers for a `toggle` or `set_mode` command.

    `None` for anything else, including content that is not a string at all —
    the executor only ever receives a string, so nothing else can move a switch.
    An error dict is returned exactly as the executor returns it; the gate reads
    it as "this moves nothing", which is what it is.
    """
    if not isinstance(content, str):
        return None
    parts = command_parts(content)
    if not parts:
        return None
    action = parts[0].lower()

    if action == "toggle":
        if len(parts) < 3:
            return {"error": "toggle needs: toggle <name> <on|off>"}
        toggle_name = parts[1].lower()
        # `B97`. One of three vocabularies this file and `builtin_actions`
        # used for "what did the model mean by yes"; the shared rule is the
        # union of all three, so no spelling any of them took is lost.
        state = tool_arg_truthy(parts[2])
        toggle_name = TOGGLE_ALIASES.get(toggle_name, toggle_name)
        if toggle_name not in TOGGLES:
            return {"error": f"Unknown toggle '{toggle_name}'. Valid: {', '.join(sorted(TOGGLES))}"}
        return {
            "ui_event": "toggle",
            "toggle_name": toggle_name,
            "state": state,
            "results": f"Toggle '{toggle_name}' set to {'on' if state else 'off'}",
        }

    if action == "set_mode":
        if len(parts) < 2:
            return {"error": "set_mode needs: set_mode <agent|chat>"}
        mode = parts[1].lower()
        if mode not in MODES:
            return {"error": f"Invalid mode '{mode}'. Use: agent, chat"}
        return {
            "ui_event": "set_mode",
            "mode": mode,
            "results": f"Mode changed to '{mode}'",
        }

    return None
