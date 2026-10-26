# SPDX-License-Identifier: AGPL-3.0-or-later
"""What a `manage_settings` call asks of the settings, read once. `B897`, `B912`.

Two readers, one parser — `src/ui_switches.py`'s shape for `manage_settings`.
`src/agent_tools/admin_tools.do_manage_settings` carries a call out, and the
approval gate (`src/tool_capabilities.self_escalation_for`) has to know *before*
it runs whether it would hand the assistant more reach than the person left it
with: a capability switched on, a destination moved, a tool an admin switched
off switched back on. If the gate resolved "image gen" or "shell" one way and
the executor another, every alias only one of them knew would be a spelling
that switched something on without asking. So the friendly names — the key
aliases and the tool-toggle aliases, which were locals inside
`do_manage_settings` — live here, and both read the call through
`settings_call`.

A leaf on purpose, like `src/ui_switches.py` and `src/run_limits.py`: the gate
imports it, so it carries the standard library plus two leaves at import time
and asks the settings store only inside a call.
"""
from __future__ import annotations

from types import MappingProxyType
from typing import Any, Mapping, NamedTuple

from src.env_flags import tool_arg_truthy
from src.run_limits import LOOP_CAP_ALIASES
from src.tool_security import BUILTIN_EMAIL_TOOLS

# Friendly names → real keys, so natural phrasing resolves. Moved here verbatim
# from `do_manage_settings` (`B897`).
SETTING_ALIASES: Mapping[str, str] = MappingProxyType({
    "voice": "tts_voice", "tts voice": "tts_voice", "tts": "tts_enabled",
    "text to speech": "tts_enabled", "tts provider": "tts_provider",
    "speech speed": "tts_speed", "voice speed": "tts_speed",
    "stt": "stt_enabled", "speech to text": "stt_enabled", "transcription": "stt_enabled",
    "search engine": "search_provider", "search provider": "search_provider",
    "search results": "search_result_count", "result count": "search_result_count",
    "default model": "default_model", "chat model": "default_model",
    "default endpoint": "default_endpoint_id",
    "task model": "task_model", "background model": "task_model",
    "teacher model": "teacher_model", "teacher": "teacher_enabled",
    "utility model": "utility_model", "research model": "research_model",
    "research max tokens": "research_max_tokens",
    "vision model": "vision_model", "vision": "vision_enabled",
    "image model": "image_model", "image quality": "image_quality",
    "image gen": "image_gen_enabled", "image generation": "image_gen_enabled",
    "reminder channel": "reminder_channel", "reminders": "reminder_channel",
    "ntfy topic": "reminder_ntfy_topic",
    "webhook integration": "reminder_webhook_integration_id",
    "webhook template": "reminder_webhook_payload_template",
    "webhook payload": "reminder_webhook_payload_template",
    # `P7-12`: the loop caps' friendly names live in `src/run_limits.py`,
    # where the approval gate reads a call through the same table.
    **LOOP_CAP_ALIASES,
    "agent timeout": "agent_stream_timeout_seconds",
    "stream timeout": "agent_stream_timeout_seconds",
    "token budget": "agent_input_token_budget", "input budget": "agent_input_token_budget",
    "hard max": "agent_input_token_hard_max",
    "token budget cap": "agent_input_token_hard_max",
    "input budget cap": "agent_input_token_hard_max",
})

_DOCUMENT_TOOLS = ("create_document", "edit_document", "update_document", "suggest_document")

# `disable_tool` / `enable_tool`'s friendly names → the names in
# `disabled_tools`. Moved here verbatim from `do_manage_settings` (`B912`).
TOOL_TOGGLE_ALIASES: Mapping[str, tuple[str, ...]] = MappingProxyType({
    "shell": ("bash", "host_shell", "shell_with_login"),  # `P17-11`, `P27-07`
    "host": ("host_shell",),
    # `P20-04`. The workstation's screen, mouse and keyboard; the bare name
    # `computer` needs no alias.
    "desktop": ("computer",),
    "computer_use": ("computer",),
    # `P25-03`: the bare name `git` needs no alias.
    "version_control": ("git",),
    # `P25-05`. Not "browser": that word already means the built-in
    # Playwright server below.
    "agent_browser": ("agent_browser",),
    "workstation_browser": ("agent_browser",),
    # `P16-20`. What network the workstation is on, and reach checks.
    "network": ("network",),
    "connectivity": ("network",),
    "terminal": ("bash",),
    "search": ("web_search", "web_fetch"),
    "web": ("web_search", "web_fetch"),
    "browser": ("builtin_browser",),
    "documents": _DOCUMENT_TOOLS,
    "doc": _DOCUMENT_TOOLS,
    "memory": ("manage_memory",),
    "rag": ("manage_rag",),  # `B66`
    "skills": ("manage_skills",),
    "images": ("generate_image",),
    "image": ("generate_image",),
    "tasks": ("manage_tasks",),
    "notes": ("manage_notes",),
    "calendar": ("manage_calendar",),
    # The full built-in email tool set, in BOTH spellings: the qualified
    # mcp__email__* names drive MCP schema hiding, the bare names drive
    # function-schema hiding, and the runtime gate accepts either — deriving
    # from BUILTIN_EMAIL_TOOLS keeps the toggle covering every tool the email
    # server exposes instead of a hand-picked subset.
    "email": tuple(sorted(BUILTIN_EMAIL_TOOLS))
             + tuple(f"mcp__email__{t}" for t in sorted(BUILTIN_EMAIL_TOOLS)),
    # research is a per-request flag, not a tool (closest analog)
    "research": ("web_search", "web_fetch"),
})


def resolve_setting_key(raw: Any) -> str:
    """`do_manage_settings`' reading of a key: a real key, an alias, or the
    text as written (which the executor then refuses as unknown)."""
    text = raw if isinstance(raw, str) else ("" if raw is None else str(raw))
    lowered = text.strip().lower()
    try:
        from src.settings import DEFAULT_SETTINGS
        if lowered in DEFAULT_SETTINGS:
            return lowered
    except Exception:
        pass
    return SETTING_ALIASES.get(lowered, text.strip())


def tool_toggle_targets(name: Any) -> tuple[str, ...]:
    """The `disabled_tools` names `disable_tool`/`enable_tool` move for `name`."""
    tool_name = str(name or "").strip().lower()
    return TOOL_TOGGLE_ALIASES.get(tool_name, (tool_name,)) if tool_name else ()


def coerce_setting_value(value: Any, default: Any) -> Any:
    """The value `set` stores, given the key's shipped default. Raises
    `ValueError`/`TypeError` for a number that is not one, as it always did."""
    if isinstance(default, bool):
        # `B97`. This was one of three vocabularies the tree used for "what
        # did the model mean by yes", and the widest — it is the one
        # `tool_arg_truthy`'s ON set was mostly derived from. The model writes
        # this value, so `"enabled"` has to be a yes here even though an
        # operator typing it into `.env` is told it is not a spelling we take.
        return tool_arg_truthy(value)
    if isinstance(default, int):
        return int(value)
    return value


class SettingsCall(NamedTuple):
    """One `manage_settings` call that would write something.

    `action` is `set`, `reset` (which `delete` also means) or `enable_tool`.
    For the first two, `key` is the resolved key and `value` what the executor
    would store: `set`'s value through `coerce_setting_value`, or the shipped
    default for a reset. For `enable_tool`, `tool` is the name as written and
    `targets` the names it takes out of `disabled_tools`."""

    action: str
    key: str = ""
    value: Any = None
    tool: str = ""
    targets: tuple[str, ...] = ()


def settings_call(content: Any) -> SettingsCall | None:
    """What this call would write, read the way `do_manage_settings` reads it,
    or `None` for a call that writes nothing (`get`, `list`, `list_tools`,
    `disable_tool` — which only narrows — or anything the executor refuses
    before it writes: bad JSON, an unknown key, a value that will not coerce).

    The executor's other refusals (secrets, `B42`'s keys, structured settings,
    enums, the loop caps' own path) are the gate's to weigh, because they
    depend on the key and the gate asks only about the keys it lists."""
    try:
        from src.tool_utils import _parse_tool_args
        args = _parse_tool_args(content)
    except Exception:
        return None
    if not isinstance(args, dict):
        return None
    action = args.get("action", "list")
    if action == "enable_tool":
        tool = str(args.get("tool") or args.get("name") or "").strip().lower()
        targets = tool_toggle_targets(tool)
        return SettingsCall("enable_tool", tool=tool, targets=targets) if targets else None
    if action not in ("set", "reset", "delete"):
        return None
    try:
        from src.settings import DEFAULT_SETTINGS, RETIRED_SETTING_KEYS
    except Exception:
        return None
    raw_key = args.get("key", "")
    if not raw_key and action == "set":
        return None
    key = resolve_setting_key(raw_key)
    if key not in DEFAULT_SETTINGS or key in RETIRED_SETTING_KEYS:
        return None
    if action == "set":
        try:
            value = coerce_setting_value(args.get("value"), DEFAULT_SETTINGS[key])
        except Exception:
            # `int(Infinity)` raises `OverflowError`: the executor refuses the
            # call, so it writes nothing.
            return None
        return SettingsCall("set", key=key, value=value)
    return SettingsCall("reset", key=key, value=DEFAULT_SETTINGS[key])


__all__ = [
    "SETTING_ALIASES", "SettingsCall", "TOOL_TOGGLE_ALIASES", "coerce_setting_value",
    "resolve_setting_key", "settings_call", "tool_toggle_targets",
]
