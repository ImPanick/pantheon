# SPDX-License-Identifier: AGPL-3.0-or-later
"""Deterministic capability metadata for agent tools.

Model output requests an action; it never supplies the authority for that
action.  This module classifies the effects of each built-in tool and applies
run-local integrity gates before dispatch.
"""

from __future__ import annotations

import json
import uuid
from dataclasses import dataclass, field
from enum import Enum
from types import MappingProxyType
from typing import Any, Iterable, Mapping

from src.tool_approval_scopes import CHAT_SESSION_APPROVAL_CONTEXT_MARKER
from src.tool_security import BUILTIN_EMAIL_TOOLS, is_public_blocked_tool


class ToolEffect(str, Enum):
    READ_PUBLIC = "read_public"
    READ_WORKSPACE = "read_workspace"
    READ_PRIVATE = "read_private"
    WRITE_WORKSPACE = "write_workspace"
    WRITE_PRIVATE = "write_private"
    EXECUTE_CODE = "execute_code"
    BROKERED_NETWORK_READ = "brokered_network_read"
    NETWORK_EGRESS = "network_egress"
    EXTERNAL_SIDE_EFFECT = "external_side_effect"
    UI_SIDE_EFFECT = "ui_side_effect"
    ADMIN_CHANGE = "admin_change"
    DESTRUCTIVE = "destructive"
    USER_INTERACTION = "user_interaction"


class ResultIntegrity(str, Enum):
    SYSTEM = "system"
    WORKSPACE_UNTRUSTED = "workspace_untrusted"
    EXTERNAL_UNTRUSTED = "external_untrusted"


@dataclass(frozen=True)
class ToolCapabilities:
    effects: frozenset[ToolEffect]
    result_integrity: ResultIntegrity = ResultIntegrity.SYSTEM
    known: bool = True


def _capabilities(
    *effects: ToolEffect,
    result_integrity: ResultIntegrity = ResultIntegrity.SYSTEM,
) -> ToolCapabilities:
    return ToolCapabilities(frozenset(effects), result_integrity)


_REGISTRY: dict[str, ToolCapabilities] = {}


def _register(
    names: Iterable[str],
    *effects: ToolEffect,
    result_integrity: ResultIntegrity = ResultIntegrity.SYSTEM,
) -> None:
    capabilities = _capabilities(*effects, result_integrity=result_integrity)
    for name in names:
        if name in _REGISTRY:
            raise RuntimeError(f"Duplicate tool capability classification: {name}")
        _REGISTRY[name] = capabilities


_register(
    {"ask_user", "update_plan"},
    ToolEffect.USER_INTERACTION,
)
_register(
    {
        "list_cached_models",
        "list_cookbook_servers",
        "list_downloads",
        "list_models",
        "list_serve_presets",
        "list_served_models",
    },
    ToolEffect.READ_PRIVATE,
    # These readers return provider-controlled model identifiers or durable
    # user/admin-authored Forge and process state.  Local brokering does not
    # make the returned text server-authored.
    result_integrity=ResultIntegrity.EXTERNAL_UNTRUSTED,
)
_register(
    {"search_hf_models"},
    ToolEffect.BROKERED_NETWORK_READ,
    result_integrity=ResultIntegrity.EXTERNAL_UNTRUSTED,
)
_register(
    {"get_workspace", "glob", "grep", "ls", "read_file"},
    ToolEffect.READ_WORKSPACE,
    result_integrity=ResultIntegrity.WORKSPACE_UNTRUSTED,
)
_register(
    {"web_search"},
    ToolEffect.BROKERED_NETWORK_READ,
    result_integrity=ResultIntegrity.EXTERNAL_UNTRUSTED,
)
_register(
    {"web_fetch"},
    ToolEffect.BROKERED_NETWORK_READ,
    ToolEffect.NETWORK_EGRESS,
    result_integrity=ResultIntegrity.EXTERNAL_UNTRUSTED,
)
_register(
    {
        "list_email_accounts",
        "list_emails",
        "read_email",
        "resolve_contact",
        "scan_email_unsubscribes",
        "search_chats",
        "search_emails",
        "list_sessions",
        "tail_serve_output",
        "vault_get",
        "vault_search",
    },
    ToolEffect.READ_PRIVATE,
    result_integrity=ResultIntegrity.EXTERNAL_UNTRUSTED,
)
_register(
    # `B66`. Both halves are real: `add_directory` indexes files off disk, and
    # `search` hands their contents back to the next model round, so results are
    # workspace-untrusted for the same reason `read_file`'s are.
    {"manage_rag"},
    ToolEffect.READ_WORKSPACE,
    ToolEffect.WRITE_PRIVATE,
    result_integrity=ResultIntegrity.WORKSPACE_UNTRUSTED,
)
_register(
    # `P17-11`. Deliberately a heavier classification than `bash`, which carries
    # `EXECUTE_CODE` alone: that one runs inside a container whose worst case is
    # a rebuild, and this one runs on the machine. `DESTRUCTIVE` is what makes
    # the approval card say so, and the card is the last thing a person reads
    # before a command leaves for their own computer.
    {"host_shell"},
    ToolEffect.EXECUTE_CODE,
    ToolEffect.DESTRUCTIVE,
    result_integrity=ResultIntegrity.WORKSPACE_UNTRUSTED,
)
_register(
    {"bash", "manage_bg_jobs", "python"},
    ToolEffect.EXECUTE_CODE,
    result_integrity=ResultIntegrity.WORKSPACE_UNTRUSTED,
)
_register(
    {"apply_patch", "edit_file", "write_file"},
    ToolEffect.WRITE_WORKSPACE,
    # Successful writes include unified diffs that can echo arbitrary existing
    # workspace content back into the next model round.
    result_integrity=ResultIntegrity.WORKSPACE_UNTRUSTED,
)
_register(
    {
        "create_document",
        "manage_calendar",
        "manage_contact",
        "manage_documents",
        "manage_memory",
        "manage_notes",
        "manage_research",
        "manage_session",
        "manage_skills",
        "manage_tasks",
        "suggest_document",
        "todowrite",
    },
    ToolEffect.WRITE_PRIVATE,
)
_register(
    {
        "ai_draft_email_reply",
        "create_session",
        "draft_email",
        "draft_email_reply",
    },
    ToolEffect.WRITE_PRIVATE,
    # These tools resolve user-configured endpoints/accounts or read stored
    # email content before returning model-visible status text.
    result_integrity=ResultIntegrity.EXTERNAL_UNTRUSTED,
)
_register(
    {"edit_document", "update_document"},
    ToolEffect.WRITE_PRIVATE,
    # These tools can echo stored document content that was not present in
    # their arguments.  edit_document returns the complete edited document;
    # update_document also preserves stored email headers/thread history.
    result_integrity=ResultIntegrity.EXTERNAL_UNTRUSTED,
)
_register(
    {"pipeline"},
    ToolEffect.NETWORK_EGRESS,
    result_integrity=ResultIntegrity.EXTERNAL_UNTRUSTED,
)
_register(
    {"send_to_session"},
    ToolEffect.NETWORK_EGRESS,
    ToolEffect.WRITE_PRIVATE,
    result_integrity=ResultIntegrity.EXTERNAL_UNTRUSTED,
)
_register(
    {"chat_with_model", "ask_teacher"},
    ToolEffect.NETWORK_EGRESS,
    result_integrity=ResultIntegrity.EXTERNAL_UNTRUSTED,
)
_register(
    {"download_attachment"},
    ToolEffect.READ_PRIVATE,
    ToolEffect.WRITE_WORKSPACE,
    result_integrity=ResultIntegrity.EXTERNAL_UNTRUSTED,
)
_register(
    {"edit_image", "generate_image", "trigger_research"},
    ToolEffect.NETWORK_EGRESS,
    ToolEffect.WRITE_PRIVATE,
    result_integrity=ResultIntegrity.EXTERNAL_UNTRUSTED,
)
_register(
    {
        "archive_email",
        "bulk_email",
        "mark_email_read",
        "reply_to_email",
        "send_email",
        "unsubscribe_email",
    },
    ToolEffect.EXTERNAL_SIDE_EFFECT,
    # Email action results can include stored headers/account labels or remote
    # SMTP/IMAP responses, even when the action itself succeeded.
    result_integrity=ResultIntegrity.EXTERNAL_UNTRUSTED,
)
_register(
    {"delete_email"},
    ToolEffect.EXTERNAL_SIDE_EFFECT,
    ToolEffect.DESTRUCTIVE,
    result_integrity=ResultIntegrity.EXTERNAL_UNTRUSTED,
)
_register(
    {"ui_control"},
    ToolEffect.UI_SIDE_EFFECT,
    # Model switches and custom-theme validation read mutable user settings.
    result_integrity=ResultIntegrity.EXTERNAL_UNTRUSTED,
)
_register(
    {
        "adopt_served_model",
        "cancel_download",
        "download_model",
        "serve_model",
        "serve_preset",
        "stop_served_model",
        "vault_unlock",
    },
    ToolEffect.ADMIN_CHANGE,
    # Forge/process operations can return stored presets, provider data,
    # remote shell output, and command errors.
    result_integrity=ResultIntegrity.EXTERNAL_UNTRUSTED,
)
_register(
    {
        "api_call",
        "app_api",
        "manage_endpoints",
        "manage_mcp",
        "manage_settings",
        "manage_tokens",
        "manage_webhooks",
    },
    ToolEffect.ADMIN_CHANGE,
    # api_call/app_api return remote or stored application data, and the
    # admin managers can echo user-controlled configuration.  Conservatively
    # retain the action effect while treating every successful result as data.
    result_integrity=ResultIntegrity.EXTERNAL_UNTRUSTED,
)


TOOL_CAPABILITIES: Mapping[str, ToolCapabilities] = MappingProxyType(dict(_REGISTRY))
KNOWN_CAPABILITY_TOOLS = frozenset(TOOL_CAPABILITIES)

_UNKNOWN_CAPABILITIES = _capabilities(
    ToolEffect.READ_PRIVATE,
    ToolEffect.WRITE_WORKSPACE,
    ToolEffect.WRITE_PRIVATE,
    ToolEffect.EXECUTE_CODE,
    ToolEffect.NETWORK_EGRESS,
    ToolEffect.EXTERNAL_SIDE_EFFECT,
    ToolEffect.ADMIN_CHANGE,
    ToolEffect.DESTRUCTIVE,
    result_integrity=ResultIntegrity.EXTERNAL_UNTRUSTED,
)
_UNKNOWN_CAPABILITIES = ToolCapabilities(
    _UNKNOWN_CAPABILITIES.effects,
    _UNKNOWN_CAPABILITIES.result_integrity,
    known=False,
)
_BROWSER_MCP_READ_CAPABILITIES = _capabilities(
    ToolEffect.BROKERED_NETWORK_READ,
    result_integrity=ResultIntegrity.EXTERNAL_UNTRUSTED,
)
_BROWSER_MCP_READ_TOOLS = frozenset(
    {
        "mcp__builtin_browser__browser_console_messages",
        "mcp__builtin_browser__browser_network_requests",
        "mcp__builtin_browser__browser_snapshot",
        "mcp__builtin_browser__browser_take_screenshot",
    }
)


def capabilities_for_tool(tool_name: Any) -> ToolCapabilities:
    """Return deterministic capabilities; malformed and unknown tools fail high."""
    if not isinstance(tool_name, str) or not tool_name:
        return _UNKNOWN_CAPABILITIES
    capabilities = TOOL_CAPABILITIES.get(tool_name)
    if capabilities is not None:
        return capabilities
    if tool_name.startswith("mcp__email__"):
        bare_name = tool_name[len("mcp__email__"):]
        capabilities = TOOL_CAPABILITIES.get(bare_name)
        if bare_name in BUILTIN_EMAIL_TOOLS and capabilities is not None:
            return capabilities
    if tool_name in _BROWSER_MCP_READ_TOOLS:
        return _BROWSER_MCP_READ_CAPABILITIES
    return _UNKNOWN_CAPABILITIES


_PRIVATE_ACTION_READS: Mapping[str, frozenset[str]] = MappingProxyType(
    {
        "manage_calendar": frozenset({"list_calendars", "list_events"}),
        "manage_contact": frozenset({"list"}),
        "manage_documents": frozenset({"list", "read", "view", "open", "get"}),
        "manage_memory": frozenset({"list", "search"}),
        "manage_notes": frozenset({"list", "search", "find", "view"}),
        "manage_research": frozenset({"list", "read", "open", "view", "get"}),
        "manage_session": frozenset({"list", "switch", "open", "select", "view"}),
        "manage_skills": frozenset({"list", "index", "view", "view_ref", "search",
                                    "lint", "versions", "export"}),
        "manage_tasks": frozenset({"list"}),
    }
)

_PRIVATE_ACTION_WRITES: Mapping[str, frozenset[str]] = MappingProxyType(
    {
        "manage_calendar": frozenset(
            {"create_event", "update_event", "delete_event"}
        ),
        "manage_contact": frozenset({"add", "update", "edit", "delete"}),
        "manage_documents": frozenset({"delete", "tidy"}),
        "manage_memory": frozenset({"add", "edit", "delete"}),
        "manage_notes": frozenset({"add", "update", "delete", "toggle_item"}),
        "manage_research": frozenset({"delete"}),
        "manage_session": frozenset(
            {
                "rename",
                "archive",
                "unarchive",
                "delete",
                "important",
                "unimportant",
                "truncate",
                "fork",
            }
        ),
        "manage_skills": frozenset({"add", "edit", "patch", "publish", "delete", "restore"}),
        "manage_tasks": frozenset({"create", "edit", "delete", "pause", "resume", "run"}),
    }
)

_ACTION_DESTRUCTIVE: Mapping[str, frozenset[str]] = MappingProxyType(
    {
        "manage_calendar": frozenset({"delete_event"}),
        "manage_contact": frozenset({"delete"}),
        "manage_documents": frozenset({"delete", "tidy"}),
        "manage_endpoints": frozenset({"delete"}),
        "manage_bg_jobs": frozenset({"kill", "stop", "cancel", "terminate"}),
        # `bulk_email` is the one non-`manage_*` multiplexer in this table, and
        # it earns its place: `delete_email` is registered DESTRUCTIVE at the
        # tool level for removing *one* message, while `bulk_email` removes
        # many — with `permanent: true` it sets `\Deleted` and bypasses Trash
        # entirely (`mcp_servers/email_server.py`). Without this line the card
        # for emptying a mailbox ranked *below* the card for deleting a single
        # message, which is the exact inversion P7-06 exists to prevent.
        "bulk_email": frozenset({"delete", "junk"}),
        "manage_memory": frozenset({"delete"}),
        "manage_mcp": frozenset({"delete"}),
        "manage_notes": frozenset({"delete"}),
        "manage_research": frozenset({"delete"}),
        "manage_session": frozenset({"delete", "truncate"}),
        "manage_settings": frozenset({"delete", "reset"}),
        "manage_skills": frozenset({"delete"}),
        "manage_tasks": frozenset({"delete"}),
        "manage_tokens": frozenset({"delete"}),
        "manage_webhooks": frozenset({"delete"}),
    }
)

_ACTION_DEFAULTS: Mapping[str, str] = MappingProxyType(
    {
        "manage_calendar": "list_events",
        "manage_documents": "list",
        "manage_research": "list",
        "manage_tasks": "list",
    }
)

_ACTION_ALIASES: Mapping[str, Mapping[str, str]] = MappingProxyType(
    {
        "manage_calendar": MappingProxyType(
            {
                "create": "create_event",
                "update": "update_event",
                "delete": "delete_event",
                "list": "list_events",
            }
        ),
        "manage_notes": MappingProxyType(
            {
                "create": "add",
                "new": "add",
                "save": "add",
                "remind": "add",
                "reminder": "add",
                "remove": "delete",
                "remove_item": "toggle_item",
            }
        ),
    }
)

class _ActionArgumentTooDeep(Exception):
    """`B17`. A tool argument nested past `_MAX_ACTION_JSON_DEPTH`.

    Internal to this module: every raise is caught by
    `capabilities_for_action`, which answers `_UNKNOWN_CAPABILITIES`.
    """


_LINE_ACTION_TOOLS = frozenset({"manage_memory", "manage_session"})

# `B17`. A nesting depth beyond which we refuse to parse rather than ask CPython
# to. `json.loads` recurses per level and raises `RecursionError`, which is a
# `RuntimeError` and therefore named by neither `TypeError` nor `ValueError` —
# so a deeply nested argument escaped this function, escaped six unguarded call
# sites, and was caught only by `src/agent_runs.py`'s outer handler, which ends
# the run. The user gets a generic `Agent run failed before completion.` and —
# worse — `save_assistant_response` is INSIDE the `async for` body in
# `routes/chat_routes.py`, so the turn's partial reply is discarded.
#
# The threshold is not a Pantheon constant. Measured, the first failing nesting
# depth is `sys.getrecursionlimit() - frames_at_call - 4`, so the row's "1,984
# characters" is exactly `2 x (1000 - 4 - 4)` at the stock limit from a bare
# call, and it moves with the ambient stack. A property of the interpreter is
# not something to leave load-bearing.
#
# 64 is three orders of magnitude above any real tool argument, and the bound is
# on DEPTH, not length: a large-but-flat argument is legitimate and keeps
# working (`Law 1`). It is checked before parsing, so nothing recurses.
_MAX_ACTION_JSON_DEPTH = 64


def _json_depth_exceeds(raw: str, limit: int) -> bool:
    """Single pass, string-literal and escape aware. No recursion, by design —
    a recursive depth check would be the same defect in a new function."""
    depth = 0
    in_string = False
    escaped = False
    for ch in raw:
        if in_string:
            if escaped:
                escaped = False
            elif ch == "\\":
                escaped = True
            elif ch == '"':
                in_string = False
            continue
        if ch == '"':
            in_string = True
        elif ch in "[{":
            depth += 1
            if depth > limit:
                return True
        elif ch in "]}":
            depth -= 1
    return False


def _action_from_content(tool_name: str, content: Any) -> str | None:
    """Extract the action discriminator using the same accepted input shapes."""
    if isinstance(content, Mapping):
        payload: Any = dict(content)
    elif isinstance(content, str):
        raw = content.strip()
        if tool_name in _LINE_ACTION_TOOLS and raw and not raw.startswith("{"):
            return raw.splitlines()[0].strip().replace("-", "_").casefold() or None
        if _json_depth_exceeds(raw, _MAX_ACTION_JSON_DEPTH):
            # `B17`. Not `None` — that falls through to the tool's base
            # capabilities, which is the silent degradation the row warns
            # about. Raising here lets `capabilities_for_action` answer with
            # `_UNKNOWN_CAPABILITIES`, so the approval card says
            # "unknown/high-impact" out loud instead of guessing low.
            raise _ActionArgumentTooDeep(tool_name)
        try:
            payload = json.loads(raw) if raw else {}
        except (TypeError, ValueError, RecursionError):
            # `RecursionError` is belt-and-braces: the depth bound above should
            # make it unreachable, and a parse path that recurses some other way
            # must not be able to end a run.
            return None
    else:
        payload = {}

    if not isinstance(payload, dict):
        return None
    if (
        len(payload) == 1
        and isinstance(payload.get("body"), dict)
        and "action" in payload["body"]
    ):
        payload = payload["body"]

    action = payload.get("action")
    if (
        not action
        and tool_name == "manage_calendar"
        and isinstance(payload.get("events"), list)
    ):
        action = "create_event"
    if not action and tool_name == "manage_tasks" and any(
        payload.get(key) is not None
        for key in ("task", "description", "schedule", "time", "day_of_week")
    ):
        action = "create"
    if not isinstance(action, str) or not action.strip():
        action = _ACTION_DEFAULTS.get(tool_name)
    if not action:
        return None
    normalized = action.strip().replace("-", "_").casefold()
    return _ACTION_ALIASES.get(tool_name, {}).get(normalized, normalized)


def capabilities_for_action(tool_name: Any, content: Any) -> ToolCapabilities:
    """Classify a sealed multiplexed action; ambiguous actions fail high."""
    base = capabilities_for_tool(tool_name)
    if not isinstance(tool_name, str):
        return base

    # Every table below is keyed on the bare tool name, but the model can call an
    # email tool under its MCP alias — `capabilities_for_tool` already strips
    # that prefix and these lookups did not, so an aliased call silently missed
    # its own action table and resolved one rung too low.
    if (
        tool_name.startswith("mcp__email__")
        and tool_name[len("mcp__email__"):] in BUILTIN_EMAIL_TOOLS
    ):
        tool_name = tool_name[len("mcp__email__"):]

    try:
        action = _action_from_content(tool_name, content)
    except _ActionArgumentTooDeep:
        # `B17`. The argument is unclassifiable, so say so rather than guess.
        # `_UNKNOWN_CAPABILITIES` carries `known=False`, which `decision_for`
        # already renders as "because it can cause unknown/high-impact" and
        # `describe_effects` already bands as serious — so the approval card is
        # truthful by construction and no second vocabulary is invented
        # (`Law 14`).
        return _UNKNOWN_CAPABILITIES
    destructive = action in _ACTION_DESTRUCTIVE.get(tool_name, ())
    if tool_name not in _PRIVATE_ACTION_READS:
        if not destructive:
            return base
        return ToolCapabilities(
            frozenset(set(base.effects) | {ToolEffect.DESTRUCTIVE}),
            base.result_integrity,
            known=base.known,
        )
    if action in _PRIVATE_ACTION_READS[tool_name]:
        return _capabilities(
            ToolEffect.READ_PRIVATE,
            result_integrity=ResultIntegrity.EXTERNAL_UNTRUSTED,
        )
    if action in _PRIVATE_ACTION_WRITES[tool_name]:
        effects = set(base.effects)
        if destructive:
            effects.add(ToolEffect.DESTRUCTIVE)
        return ToolCapabilities(
            frozenset(effects),
            ResultIntegrity.EXTERNAL_UNTRUSTED,
            known=base.known,
        )

    return _capabilities(
        ToolEffect.READ_PRIVATE,
        ToolEffect.WRITE_PRIVATE,
        result_integrity=ResultIntegrity.EXTERNAL_UNTRUSTED,
    )


# ── One severity ordering, and one set of words for it (P7-06) ──────────────
#
# The 13-value taxonomy above says *what* a tool does. It does not say which of
# two effects a person should worry about more, and until this block existed the
# answer lived nowhere — so an approval card printed `Effects: destructive` and
# `Effects: ui_side_effect` in the same grey text at the same size, and the plan
# window had no way to render its fifth per-step field at all.
#
# The ordering is a judgement and it is written down once, here, beside the
# taxonomy it ranks. It is deliberately NOT duplicated in JavaScript: the wire
# carries the resolved rank and the resolved words, so a value added to the enum
# cannot render as a blank in one surface and a raw identifier in another.
#
# Read the numbers as ranks, not scores. Only their order is meaningful, and the
# gaps are there so a value can be inserted later without renumbering.
_EFFECT_SEVERITY: Mapping[ToolEffect, int] = MappingProxyType({
    ToolEffect.UI_SIDE_EFFECT: 10,
    ToolEffect.USER_INTERACTION: 20,
    ToolEffect.READ_PUBLIC: 30,
    ToolEffect.READ_WORKSPACE: 40,
    ToolEffect.BROKERED_NETWORK_READ: 50,
    ToolEffect.WRITE_WORKSPACE: 60,
    ToolEffect.READ_PRIVATE: 70,
    ToolEffect.EXECUTE_CODE: 80,
    ToolEffect.NETWORK_EGRESS: 90,
    ToolEffect.WRITE_PRIVATE: 100,
    ToolEffect.EXTERNAL_SIDE_EFFECT: 110,
    ToolEffect.ADMIN_CHANGE: 120,
    ToolEffect.DESTRUCTIVE: 130,
})

# `Law 15`: the person approving this has not read the enum. The phrase says what
# happens to *them*, not what the tool is classified as. Short enough to sit on a
# plan-window step row without wrapping.
_EFFECT_PHRASE: Mapping[ToolEffect, str] = MappingProxyType({
    ToolEffect.UI_SIDE_EFFECT: "Changes what is on screen",
    ToolEffect.USER_INTERACTION: "Asks you a question",
    ToolEffect.READ_PUBLIC: "Reads public information",
    ToolEffect.READ_WORKSPACE: "Reads workspace files",
    ToolEffect.BROKERED_NETWORK_READ: "Fetches a page through the app",
    ToolEffect.WRITE_WORKSPACE: "Writes workspace files",
    ToolEffect.READ_PRIVATE: "Reads your private data",
    ToolEffect.EXECUTE_CODE: "Runs code on this machine",
    ToolEffect.NETWORK_EGRESS: "Sends data out to the internet",
    ToolEffect.WRITE_PRIVATE: "Changes your private data",
    ToolEffect.EXTERNAL_SIDE_EFFECT: "Changes something outside this app",
    ToolEffect.ADMIN_CHANGE: "Changes settings for everyone",
    ToolEffect.DESTRUCTIVE: "Can permanently delete or overwrite",
})

# Three bands, because a card can afford three visual treatments and not
# thirteen. The thresholds are the rank of the lowest member of each band, so
# adding an effect between two existing ones lands in the right band without
# anyone editing this.
EFFECT_BAND_ROUTINE = "routine"      # reads, and drawing on the screen
EFFECT_BAND_NOTABLE = "notable"      # writes, code, and anything leaving the box
EFFECT_BAND_SERIOUS = "serious"      # other people's state, and deletion


def effect_severity(effect: Any) -> int:
    """Rank one effect. An unrecognised value sorts *highest*, not lowest.

    Failing high is the same rule the rest of this module uses for unknown
    tools: a value nobody has classified is treated as the most consequential
    thing it could be, so a new enum member cannot quietly render as harmless
    on a surface that has not been updated.
    """
    try:
        return _EFFECT_SEVERITY[ToolEffect(effect)]
    except (KeyError, ValueError):
        return 999


def effect_band(severity: int) -> str:
    """Map a rank onto the three bands a surface can actually draw."""
    if severity >= _EFFECT_SEVERITY[ToolEffect.EXTERNAL_SIDE_EFFECT]:
        return EFFECT_BAND_SERIOUS
    if severity >= _EFFECT_SEVERITY[ToolEffect.WRITE_WORKSPACE]:
        return EFFECT_BAND_NOTABLE
    return EFFECT_BAND_ROUTINE


def describe_effects(capabilities: Any) -> dict:
    """Resolve a capability set into what a surface needs to draw it.

    Returns the raw values *and* the presentation, because the two surfaces that
    consume this want different halves: the approval card shows every phrase, the
    plan window has room for one. Both need the same answer to "which one of
    these matters most", and this is the only place that answer is computed.

        {"effects": ["destructive", "read_private"],   # ranked, most severe first
         "effect": "destructive",                       # the dominant one
         "effect_label": "Can permanently delete or overwrite",
         "effect_labels": ["Can permanently delete or overwrite", "Reads your private data"],
         "effect_severity": 130,
         "effect_band": "serious"}

    An empty or unrecognisable capability set returns an empty dict rather than a
    dict of empty strings, so a caller can spread it into an event and the key is
    simply absent — a surface that reads `effect` gets `undefined`, which it
    already handles, instead of a falsy string it has to special-case.

    Takes either a `ToolCapabilities` or a bare iterable of effect values,
    because `PendingToolApproval` keeps its effects as a tuple of strings for
    digest stability and would otherwise need a second resolver of its own.
    """
    effects = getattr(capabilities, "effects", None)
    if effects is None and isinstance(capabilities, (list, tuple, set, frozenset)):
        effects = capabilities
    if not effects:
        return {}
    ranked = sorted(effects, key=lambda e: (-effect_severity(e), str(getattr(e, "value", e))))
    values = [e.value if isinstance(e, ToolEffect) else str(e) for e in ranked]

    def _phrase(effect: Any) -> str:
        """The words, or the identifier when there are none.

        A raw string reaching here still gets its phrase if it names a member of
        the enum — the approval record stores values, not members, and it would
        otherwise show identifiers to the one person being asked to consent.
        """
        try:
            return _EFFECT_PHRASE[ToolEffect(effect)]
        except (KeyError, ValueError):
            return str(getattr(effect, "value", effect))

    labels = [_phrase(e) for e in ranked]
    top = effect_severity(ranked[0])
    return {
        "effects": values,
        "effect": values[0],
        "effect_label": labels[0],
        "effect_labels": labels,
        "effect_severity": top,
        "effect_band": effect_band(top),
    }


def tool_result_is_successful(result: Any) -> bool:
    """Return whether a result actually introduced successful tool output."""
    return bool(
        isinstance(result, dict)
        and not result.get("blocked")
        and not result.get("approval_required")
        and not result.get("error")
        and result.get("exit_code") in (None, 0)
        and result.get("success") is not False
    )


def tool_result_should_arm_gate(
    tool_name: Any,
    result: Any,
    content: Any = None,
) -> bool:
    """Return whether a result introduced non-system content to the model.

    A blocked/approval placeholder and a genuinely content-free failure do not
    change authority. Once a non-system tool returns text or structured data
    that will be folded into model context, however, failure status cannot make
    that payload trusted: MCP ``isError`` text, provider exception messages,
    and HTTP error bodies are all attacker-controlled input surfaces.
    """
    if not isinstance(result, dict):
        return False
    if result.get("blocked") or result.get("approval_required"):
        return False
    # A producer that knows a particular response body came from a remote or
    # stored source overrides a coarse static SYSTEM default.
    if result.get("untrusted_content") is True:
        return True
    capabilities = capabilities_for_action(tool_name, content)
    if capabilities.result_integrity is ResultIntegrity.SYSTEM:
        return False
    if tool_result_is_successful(result):
        return True
    # ``format_tool_result`` serializes every additional structured field, so
    # a fixed allowlist here would inevitably miss model-visible payloads such
    # as ``details``, ``events``, or provider-specific response keys. Exclude
    # only status/policy controls that carry no producer content; any other
    # non-empty field crosses the same integrity boundary even on failure.
    non_content_keys = frozenset(
        {
            "approval_required",
            "blocked",
            "exit_code",
            "policy",
            "success",
            "untrusted_content",
        }
    )
    return any(
        key not in non_content_keys and value not in (None, "", [], {}, ())
        for key, value in result.items()
    )


POST_EXTERNAL_BLOCKED_EFFECTS = frozenset(
    {
        ToolEffect.READ_PRIVATE,
        ToolEffect.WRITE_WORKSPACE,
        ToolEffect.WRITE_PRIVATE,
        ToolEffect.EXECUTE_CODE,
        ToolEffect.NETWORK_EGRESS,
        ToolEffect.EXTERNAL_SIDE_EFFECT,
        ToolEffect.UI_SIDE_EFFECT,
        ToolEffect.ADMIN_CHANGE,
        ToolEffect.DESTRUCTIVE,
    }
)

# `B19`. What the strict rungs ask about **before** a run is tainted.
#
# `ask_every_time` and `allow_listed` reused `POST_EXTERNAL_BLOCKED_EFFECTS`,
# which is the set for *after* untrusted content has entered the run. The two
# questions are different: post-external asks "could this act on something the
# model was told by a stranger", and an untainted strict rung asks "is this
# about to change or send something". Reading the user's own notes is neither.
#
# Measured on the tree that had the defect: 74 of 83 registry tools were gated
# on a clean run, **17 of them solely by `read_private`** — plus 30 multiplexed
# read actions across `manage_calendar`, `manage_contact`, `manage_documents`,
# `manage_memory`, `manage_notes`, `manage_research`, `manage_session`,
# `manage_skills` and `manage_tasks`. So the strictest rungs asked permission
# for the agent to read back a note it had written itself, which is how a
# security control gets switched off.
#
# **Derived, not retyped** (`Law 13`): a second eight-item literal is the
# defect class, and the two would drift the first time an effect is added.
#
# This does not relax `POST_EXTERNAL_BLOCKED_EFFECTS`, which `FORBIDDEN.md`
# Part 2 forbids relaxing. The moment a run is tainted the full set applies
# again — and it always taints promptly, because every private-read tool and
# every private-read action carries `result_integrity=EXTERNAL_UNTRUSTED` and
# arms the gate on success, with **zero exceptions** (verified by enumerating
# the registry). So the first private read in a clean run stops asking; the
# read→exfiltrate path stays exactly as closed as it was.
RUNG_BLOCKED_EFFECTS = POST_EXTERNAL_BLOCKED_EFFECTS - frozenset({ToolEffect.READ_PRIVATE})


# ── The trust ladder (P7-03, P7-04) ─────────────────────────────────────────
#
# How often the approval gate asks. One value, resolved once per run, and it is
# the *only* thing on this ladder the gate implements — which is worth stating,
# because `.pantheon/design/pantheon-v10.html:1721` draws five rungs and only
# three of them are gate settings.
#
#   rung 0 "plan only"          — NOT here. Plan mode is a tool allowlist plus a
#                                 directive (`PLAN_MODE_READONLY_TOOLS`), a mode
#                                 you enter, not a gate condition. Putting it in
#                                 this enum would claim a control this code does
#                                 not have.
#   rung 4 "auto-pilot"         — NOT here, and the design says so itself: *"auto-
#                                 pilot isn't a new top rung. It's already the
#                                 default."* `P7-05` re-filed that correction onto
#                                 these two rows. Adding it would be a second name
#                                 for `GATE_ON_UNTRUSTED` in a clean session.
#
# Ordered strictest first. Only the order is meaningful.
class TrustRung(str, Enum):
    ASK_EVERY_TIME = "ask_every_time"
    ALLOW_LISTED = "allow_listed"
    GATE_ON_UNTRUSTED = "gate_on_untrusted"


DEFAULT_TRUST_RUNG = TrustRung.GATE_ON_UNTRUSTED

# The two rungs that ask in a clean session. `GATE_ON_UNTRUSTED` is the current
# behaviour and stays exactly as it was: an untainted run is never gated.
_RUNGS_THAT_ASK_UNTAINTED = frozenset({
    TrustRung.ASK_EVERY_TIME,
    TrustRung.ALLOW_LISTED,
})


def coerce_trust_rung(value: Any) -> TrustRung:
    """Resolve a stored or supplied rung, failing *safe* rather than open.

    An unreadable value returns the default rather than the strictest rung. That
    is the opposite of `effect_severity`'s fail-high rule and the difference is
    deliberate: an unknown *effect* is a thing we might be under-warning about,
    while an unknown *rung* is a corrupt setting, and answering it by silently
    switching a working install to confirm-everything would read as the product
    breaking. The default is what the install had before this ladder existed.
    """
    if isinstance(value, TrustRung):
        return value
    try:
        return TrustRung(str(value).strip().casefold())
    except (ValueError, AttributeError):
        return DEFAULT_TRUST_RUNG


# `P7-07`. How well this action is understood, as an enum and not a boolean.
# `Law 10`: `known: true/false` on a card reads as "is this allowed" as easily
# as "did we recognise the tool", and the consumer of a misread verdict here is
# the sentence a person approves on.
#
#   recognised     the tool is in the capability registry and the effects below
#                  are what it actually does.
#   unrecognised   no registry entry. The effects below are the worst case this
#                  module assumes, not a measurement — and this is the case the
#                  row calls the risky one, because it was previously rendered
#                  identically to a classified tool.
#   not_available  refused by policy rather than by effect; no approval lifts it
#                  (`B70`, delegated credentials). There is nothing to rank.
TOOL_CLASSIFICATION_RECOGNISED = "recognised"
TOOL_CLASSIFICATION_UNRECOGNISED = "unrecognised"
TOOL_CLASSIFICATION_UNAVAILABLE = "not_available"


@dataclass(frozen=True)
class ToolGateDecision:
    allowed: bool
    reason: str | None = None
    # `P7-07`. The effects that actually intersected the gate's blocked set —
    # not every effect the tool has. `manage_rag` is `read_workspace` +
    # `write_private`; only the second one stops it, and a card listing both
    # makes the person read two phrases to find the one that mattered.
    #
    # **Measured before it was written, and it is a smaller defect than it
    # sounds**: of the 83 registry tools, 74 are refusable in a tainted run and
    # exactly 2 ever over-listed (`manage_rag`, `web_fetch`); every multiplexed
    # action over-listed 0, because the action tables already answer narrow. The
    # half of this row that is universal is `classification` below.
    #
    # Severity-ranked by `describe_effects`, most severe first, so a surface
    # never re-derives an ordering that lives in this module (`P7-06`).
    tripped_effects: tuple[str, ...] = ()
    classification: str = TOOL_CLASSIFICATION_RECOGNISED


_EXTERNAL_MESSAGE_SOURCES = frozenset(
    {
        "injected research context",
        "prefetched search context",
        "research context",
        "web search results",
        "youtube transcript",
    }
)
_EXTERNAL_MESSAGE_SOURCE_PREFIXES = ("web page:",)


# `P7-08`. What a taint-trail entry says about itself. Three kinds, because the
# three answer different questions for the person reading the card, and one
# undifferentiated list of strings would answer none of them:
#
#   tool      a tool this run called returned content the model then saw.
#   context   labelled external text was already in the prompt — a prefetched
#             search, a fetched page, a research injection. No tool call of this
#             run is responsible for it.
#   carried   the run began tainted: an approval sealed in a tainted run, or a
#             card retired by an ordinary turn. The originating tool is not
#             recoverable here, and saying "carried" is more honest than
#             attributing it to whichever tool happens to be running now.
TAINT_KIND_TOOL = "tool"
TAINT_KIND_CONTEXT = "context"
TAINT_KIND_CARRIED = "carried"

# Used whenever taint is asserted with no nameable origin. It exists so a trail
# is never *empty* while the gate is telling the person untrusted content
# influenced the run — two statements that contradict each other on one card is
# exactly the ambiguity `Law 10` is about.
CARRIED_TAINT_SOURCE = "untrusted content from earlier in this run"


def external_untrusted_context_sources(messages: Iterable[dict]) -> list[str]:
    """Name every labelled external context already present in a run.

    `P7-08`. The predicate below used to be the whole of this: it answered
    *whether* untrusted text was in the prompt and threw away *which*, so a run
    tainted by a prefetched web page and a run tainted by a research injection
    produced the same card and the same silence. The names are recovered here,
    in prompt order, de-duplicated, and the predicate is derived from this so
    the two can never disagree about what counts (`Law 7`).

    A message's own `source` label is preferred because it is what the wrapper
    already wrote for a person to read — `"web page: https://example.com"`
    rather than `"external"`. Where there is no label, the fallback names the
    reason the message qualified instead of inventing a source.
    """
    sources: list[str] = []

    def _note(label: Any) -> None:
        text = str(label or "").strip()
        if text and text not in sources:
            sources.append(text)

    for message in messages or ():
        if not isinstance(message, dict):
            continue
        metadata = message.get("metadata")
        if not isinstance(metadata, dict) or metadata.get("trusted") is not False:
            continue
        raw_source = metadata.get("source")
        label = raw_source if isinstance(raw_source, str) else ""
        gate_marker = metadata.get("tool_gate_untrusted")
        if gate_marker is True:
            _note(label or "untrusted context in the prompt")
            continue
        if gate_marker is False:
            # Explicit current-format opt-outs are authoritative.  The source
            # label heuristics below exist only for older saved wrappers that
            # predate the marker.
            continue
        if metadata.get("provenance_origin") == "external":
            _note(label or "external content in the prompt")
            continue
        if not isinstance(raw_source, str):
            continue
        normalized_source = raw_source.strip().casefold()
        if normalized_source in _EXTERNAL_MESSAGE_SOURCES:
            _note(raw_source)
            continue
        if normalized_source.startswith(_EXTERNAL_MESSAGE_SOURCE_PREFIXES):
            _note(raw_source)
    return sources


def messages_contain_external_untrusted_context(messages: Iterable[dict]) -> bool:
    """Detect explicitly labelled external context already present in a run."""
    return bool(external_untrusted_context_sources(messages))


@dataclass
class ToolRunSecurityContext:
    """Server-owned integrity state for one agent run."""

    external_untrusted_context_seen: bool = False
    external_sources: list[str] = field(default_factory=list)
    # `P7-08`. The ordered record of what armed this run's gate — the same
    # events `external_sources` records, plus the two kinds it cannot express:
    # prompt-borne context, which is not a tool, and taint carried in at run
    # start, which has no name left. Entries are `{"kind": ..., "source": ...}`.
    #
    # `external_sources` is NOT derived from this and is not removed: it is the
    # existing tool-name list and it keeps meaning exactly what it meant
    # (`Law 1`). Both are written by `_note_taint` and by nothing else, so the
    # two views cannot drift apart at a call site.
    taint_trail: list[dict] = field(default_factory=list)
    run_id: str = field(default_factory=lambda: uuid.uuid4().hex)
    # Task-scope approval sets this for the resumed in-memory run. Chat-scope
    # approval is projected from the server-owned session history marker below.
    # The bypass affects only this automatic gate; current tool policy, ownership,
    # workspace confinement, and execution/sandbox restrictions still apply.
    approval_gate_bypassed: bool = False
    # P7-03. How often this run asks. Resolved once, at run start, from the
    # owner's setting — never re-read mid-run, because a rung that changed under
    # a run would make two actions in the same turn answerable to two policies.
    rung: TrustRung = DEFAULT_TRUST_RUNG
    # P7-04. `(tool_name, content) -> bool`, supplied by the caller. A callable
    # rather than a store because this module classifies tools and must not grow
    # a database import to do it; the rule store lives in `src/tool_allow_rules.py`
    # and `src/agent_loop.py` wires the two together. `None` means no rules, which
    # is what every existing caller gets without changing a line.
    allow_rule_lookup: Any = None
    # B70. Driven by a bearer API token rather than a person at a browser.
    # Privileged tools are refused outright and no approval can lift it.
    delegated_credential: bool = False

    def __post_init__(self) -> None:
        """`P7-08`. A run that starts tainted still has to be able to say so.

        `src/agent_loop.py` builds this with `external_untrusted_context_seen`
        already true when the route carried taint forward — a card retired by an
        ordinary turn, or an approval sealed in a tainted run. No tool of *this*
        run did that and no prompt message names it, so the trail records the
        one true thing: it arrived before this run started.
        """
        if self.external_untrusted_context_seen and not self.taint_trail:
            self._note_taint(CARRIED_TAINT_SOURCE, TAINT_KIND_CARRIED)

    def _note_taint(self, source: Any, kind: str) -> None:
        """Record one thing that armed the gate. The only writer of both views.

        De-duplicated on `(kind, source)` so a page fetched four times is one
        line on the card rather than four, and appended in the order it
        happened, because "what tainted this run first" is the question a person
        reading a trail is actually asking.
        """
        text = str(source or "").strip()
        if not text:
            return
        if any(
            entry.get("kind") == kind and entry.get("source") == text
            for entry in self.taint_trail
        ):
            return
        self.taint_trail.append({"kind": kind, "source": text})
        if kind == TAINT_KIND_TOOL and text not in self.external_sources:
            self.external_sources.append(text)

    def observe_messages(self, messages: Iterable[dict]) -> None:
        """Apply server-owned chat scope and promote untrusted prompt context."""
        message_list = list(messages or ())
        if self.delegated_credential:
            # B70. A delegated run has no human to grant chat-session scope, so
            # a grant sitting in this chat's history — left there legitimately
            # by the owner's own browser — must not be picked up by a token
            # driving the same chat. The untrusted-context promotion below
            # still runs, because that is about the content and not the caller.
            self.approval_gate_bypassed = False
            self.observe_prompt_context(message_list)
            return
        if any(
            isinstance(message, dict)
            and isinstance(message.get("metadata"), dict)
            and message["metadata"].get(
                CHAT_SESSION_APPROVAL_CONTEXT_MARKER
            ) is True
            for message in message_list
        ):
            self.approval_gate_bypassed = True
        self.observe_prompt_context(message_list)

    def observe_prompt_context(self, messages: list) -> None:
        """`P7-08`. Arm on labelled prompt context, and name what armed it.

        Public because `src/agent_loop.py` needs it at construction time. It
        used to fold this question into the constructor's boolean, which armed
        the gate correctly and lost every name — so a run tainted entirely by a
        fetched page in the prompt reported `carried`, the entry that exists for
        taint with nothing left to attribute it to.
        """
        for source in external_untrusted_context_sources(messages):
            self.external_untrusted_context_seen = True
            self._note_taint(source, TAINT_KIND_CONTEXT)

    @property
    def gate_is_armed(self) -> bool:
        """Whether this run's gate can refuse anything at all.

        Two things arm it now, and the second is why this property exists.
        Before `P7-03` "armed" and "untrusted content has arrived" were the same
        sentence, so callers outside this module wrote the second and meant the
        first. `src/tool_execution.py` did exactly that, and the day a rung
        started minting approval cards in a clean run, approving one returned
        *"Exact-action approval requires an armed run security context"* and the
        action never ran — the ladder built a card nobody could answer.

        The bypass is deliberately not consulted: a bypassed gate refuses
        nothing, but an approval replayed into one is still an approval being
        replayed into a run that asked for it.
        """
        return bool(
            self.external_untrusted_context_seen
            or self.rung in _RUNGS_THAT_ASK_UNTAINTED
        )

    def decision_for(self, tool_name: Any, content: Any = None) -> ToolGateDecision:
        # B70. Checked before the bypasses below, because neither may lift it,
        # and kept independent of `external_untrusted_context_seen` so it holds
        # on a run where that gate never arms and raises no prompt to bypass.
        if self.delegated_credential and is_public_blocked_tool(tool_name):
            return ToolGateDecision(
                False,
                (
                    f"Tool '{tool_name}' is not available to API-token callers. "
                    "It requires an interactive session."
                ),
                classification=TOOL_CLASSIFICATION_UNAVAILABLE,
            )
        # The bypass does not outrank a rung that asks. **Refutation proved the
        # ladder inverted without this line**, and the reproduction is worth
        # keeping: on `ask_every_time`, approving one harmless `bash` in a clean
        # run set `allow_remaining_actions`, and a later round then fetched a
        # hostile page and ran an exfiltration command with no prompt — an
        # action the *default* rung stops and asks about. The two "stricter"
        # rungs were strictly less protected than the one they sit below.
        #
        # It happened because before `P7-03` a card could only exist once taint
        # had armed the gate, so a bypass was always granted under the same
        # threat model it then relaxed. A rung mints cards in clean runs, and a
        # yes given when nothing was wrong must not spend itself after something
        # is. `src/tool_execution.py` already refuses that across the *approval*
        # door; this is the same rule on the *bypass* door.
        #
        # The approved action itself still runs: it is authorised by the sealed
        # exact grant, which is bound to that owner, session, tool and content —
        # not by this blanket flag.
        if self.approval_gate_bypassed and self.rung not in _RUNGS_THAT_ASK_UNTAINTED:
            return ToolGateDecision(True)

        # The untainted early exit is preserved exactly for the default rung,
        # and behaviour preservation is the whole of the reason: every verdict
        # and every sentence the default rung produces is the one it produced
        # before this ladder existed.
        #
        # CORRECTED 2026-08-29. This used to claim a second reason, and the
        # claim was false. It said `capabilities_for_action` parses model output
        # and can raise on a pathological payload, that *"today a clean chat
        # never reaches it"*, and that the early exit therefore kept that
        # failure mode out of untainted runs. Instrumented, a clean chat at the
        # default rung reaches `capabilities_for_action` four times for one
        # fenced tool block: once from `_effect_fields` in `src/agent_loop.py`,
        # and three more from `tool_result_should_arm_gate`, which every result
        # passes through — twice via `observe_tool_result` (the dispatcher and
        # the loop each call it) and once more when the result is folded into
        # the message history. Skipping one caller in four protects nothing.
        #
        # It is not even the caller that would matter. `_effect_fields` catches
        # and logs; this method and `tool_result_should_arm_gate` do not, and
        # nothing between here and the SSE stream does either. A payload that
        # made `json.loads` raise something other than `TypeError`/`ValueError`
        # — a deeply nested one raises `RecursionError`, which the `except` in
        # `_action_from_content` did not name — ended the run at whichever of
        # those two was reached first, at every rung. **Fixed in `B17`**:
        # `_action_from_content` bounds nesting depth before parsing and
        # `capabilities_for_action` answers `_UNKNOWN_CAPABILITIES`, so a
        # pathological argument is refused with a truthful card instead of
        # ending the turn and discarding its reply.
        asks_untainted = self.rung in _RUNGS_THAT_ASK_UNTAINTED
        if not self.external_untrusted_context_seen and not asks_untainted:
            return ToolGateDecision(True)

        capabilities = capabilities_for_action(tool_name, content)
        # `B19`. Tainted runs keep the full set, byte for byte. Only the
        # untainted strict rungs narrow, and only by `read_private`.
        gate_effects = (
            POST_EXTERNAL_BLOCKED_EFFECTS
            if self.external_untrusted_context_seen
            else RUNG_BLOCKED_EFFECTS
        )
        blocked_effects = capabilities.effects & gate_effects
        if capabilities.known and not blocked_effects:
            return ToolGateDecision(True)

        # P7-04 says "consulted before the blocked-effect check", and it is
        # consulted before the *refusal*, which is the same thing behaviourally
        # and safer literally: an action with no blocked effect is already
        # allowed above, so the only actions a rule can reach are the ones that
        # would otherwise be refused — and a rule can never make an action fail
        # classification and be allowed anyway.
        #
        # Only at `ALLOW_LISTED`. `ASK_EVERY_TIME` honouring a saved rule would
        # be the control lying about its own name.
        #
        # And **never once untrusted content has entered**. Refutation found the
        # rung asking *less* than the default without this: a standing "anything
        # starting with git" rule let `git push --force origin main` run without
        # a prompt in a run that had already pulled in a web page — which the
        # default rung stops. A rule is a standing yes to a routine action, and
        # the moment the run is carrying someone else's text it is not routine
        # any more. The ladder's own copy promises the strict rungs "only ever
        # make Pantheon ask more often"; this is what makes that true.
        if (
            self.rung is TrustRung.ALLOW_LISTED
            and not self.external_untrusted_context_seen
            and self._allow_rule_matches(tool_name, content)
        ):
            return ToolGateDecision(True)

        effects = ", ".join(sorted(effect.value for effect in blocked_effects))
        if not capabilities.known:
            effects = "unknown/high-impact"
        # `P7-07`. The effects that tripped, ranked by the one ordering this
        # module owns (`P7-06`), carried on the decision so the card can name
        # them instead of listing everything the tool can do. For an
        # unrecognised tool these are the assumed worst case, which is why the
        # classification travels beside them and not as a phrase inside the
        # sentence — a surface has to be able to draw that case differently,
        # and until now it could not tell the two apart at all.
        tripped = tuple(describe_effects(blocked_effects).get("effects", ()))
        classification = (
            TOOL_CLASSIFICATION_RECOGNISED
            if capabilities.known
            else TOOL_CLASSIFICATION_UNRECOGNISED
        )
        if self.external_untrusted_context_seen:
            why = "External untrusted context has already influenced this run. "
        else:
            # The rung asked for this, and the sentence has to say so — the old
            # one blamed untrusted context, which on this path has not happened.
            why = "This conversation is set to confirm every effectful action. "
        return ToolGateDecision(
            False,
            (
                f"{why}"
                f"Tool '{tool_name}' requires a separate user-authorized action "
                f"because it can cause {effects}."
            ),
            tripped_effects=tripped,
            classification=classification,
        )

    def _allow_rule_matches(self, tool_name: Any, content: Any) -> bool:
        """Ask the injected rule store, and treat any failure as "no rule".

        A rule store that errors must not become a rule store that allows. The
        lookup reaches a database on a live tool-dispatch path, so it *will*
        fail sometimes, and the safe answer to "is this allowed" when nobody
        knows is no.
        """
        lookup = self.allow_rule_lookup
        if lookup is None:
            return False
        try:
            return bool(lookup(tool_name, content))
        except Exception:
            return False

    def observe_tool_result(
        self,
        tool_name: Any,
        result: Any,
        content: Any = None,
    ) -> None:
        if not tool_result_should_arm_gate(tool_name, result, content):
            return
        self.external_untrusted_context_seen = True
        if isinstance(tool_name, str):
            self._note_taint(tool_name, TAINT_KIND_TOOL)


def blocked_tool_result(tool_name: Any, reason: str) -> tuple[str, dict]:
    return (
        f"{tool_name}: BLOCKED",
        {
            "error": reason,
            "exit_code": 1,
            "blocked": True,
            "policy": "external_untrusted_context",
        },
    )
