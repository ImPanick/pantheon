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
from src.tool_security import (
    BUILTIN_EMAIL_TOOLS,
    is_delegated_credential_blocked_tool,
)
from src.ui_switches import switch_request
from src.run_limits import cap_label, configured_cap, describe_cap, owner_set_cap_raise


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
    # `P20-04`. Driving a desktop is running code and reaching the network,
    # whatever the click is on: a terminal is one click away on it, so typing
    # into the screen is typing into a shell, and its browser reaches the
    # internet and — on the owner's *full* network answer (`D-2026-09-30-03`) —
    # the LAN. So a click carries what `bash` and `web_fetch` carry, and the
    # approval card says both. It is **not** `DESTRUCTIVE` like `host_shell`:
    # that one is the operator's own machine; this one is a separate box that
    # holds no Pantheon secret and has *Reset to clean*. Its results are
    # `EXTERNAL_UNTRUSTED` because a screen shows whatever a web page or a file
    # put on it, so a screenshot arms the post-external gate like any fetched
    # page — which `FORBIDDEN.md` Part 2 says never lifts, and means a click
    # after reading a stranger's page asks first. Looking without touching is
    # narrowed below (`_OBSERVE_ONLY_ACTIONS`).
    {"computer"},
    ToolEffect.EXECUTE_CODE,
    ToolEffect.NETWORK_EGRESS,
    result_integrity=ResultIntegrity.EXTERNAL_UNTRUSTED,
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


# ── The assistant may take its own reach away, never give itself more (P7-02) ─
#
# `ui_control` moves the chat's own switches — the shell, web search, Deep
# Research, the RAG knowledge base, the document editor, Nobody mode, Agent mode
# — and the browser applies whatever comes back without asking anyone
# (`static/js/chatStream.js`, `handleUIControl`). Registered as a UI side effect
# and nothing more, it went through this gate the way a theme change does:
# unasked in every clean run at the default rung, and unasked in a tainted run
# too once the person had pressed "allow for this task" for something else. So
# the assistant could switch the shell back on after being told it was off —
# on its own reading of a request, or on a page's say-so once any blanket yes
# was in hand — and the next message the person sent carried `allow_bash=true`
# without them touching anything.
#
# **The rule is one-directional on purpose.** Switching something *off* — or
# Nobody mode *on*, or back to Chat — only narrows what the assistant can do and
# stays exactly as unasked as it was: an assistant that can stand itself down is
# one a person can ask to. Switching something *on* widens it, and that asks
# every time: at every rung, tainted or clean, and under no blanket approval.
# "Allow for this task" and "allow for this chat session" answer the
# untrusted-content gate; neither is a person choosing to hand the assistant a
# tool. The sealed exact grant still authorises the one action it was minted
# for, through `PendingToolApproval` unchanged (`Law 14`).
#
# Everything else `ui_control` does — panels, themes, a model switch, an email
# draft — does not move the assistant's own reach and is untouched.


@dataclass(frozen=True)
class SelfEscalation:
    """One request that would widen what the assistant may do: a `ui_control`
    switch turned on (`P7-02`), or a loop cap the owner typed raised
    (`P7-12`)."""

    # The switch after aliasing: a toggle name, or `agent` for `set_mode agent`;
    # for a loop cap, the setting's key.
    switch: str
    # What the card says the assistant wants to do, in the words on the switch.
    words: str
    # What switching it hands over, as `ToolEffect`s, so the card ranks and
    # phrases it through `describe_effects` like every other action (`P7-06`) —
    # not a second vocabulary for "this one is serious".
    grants: frozenset[ToolEffect]
    # Why only a person can say yes — the card's second sentence begins with
    # this. `P7-12` gives a raised limit its own words, because a step limit is
    # not "access"; `P7-02`'s sentence is the default and is unchanged.
    only_you: str = "Only you can give it more access"


def _effects_of(*tool_names: str) -> frozenset[ToolEffect]:
    """The registered effects of the tools a switch hands over. Derived, so a
    tool reclassified above reclassifies every switch that governs it."""
    return frozenset().union(*(TOOL_CAPABILITIES[name].effects for name in tool_names))


# Each switch, the words for moving it the widening way, and what that hands
# over. A switch that governs registered tools grants *their* effects; the two
# that govern no tool say what they do instead of borrowing one.
_REACH_SWITCHES: Mapping[str, tuple[str, frozenset[ToolEffect]]] = MappingProxyType({
    # `allow_bash` is the container shell and the host shell together (`P17-11`,
    # `routes/chat_routes.py`), so the host shell's `destructive` comes with it.
    "bash": ("turn on Shell access", _effects_of("bash", "host_shell")),
    # `src/tool_policy.WEB_TOOL_NAMES`.
    "web": ("turn on Web search", _effects_of("web_search", "web_fetch")),
    # The next message runs a Deep Research job, which is `trigger_research`.
    "research": ("turn on Deep Research", _effects_of("trigger_research")),
    # Retrieval is not a tool (`src/tool_security._FEATURE_NOTES["rag"]`): the
    # person's indexed documents are put into the prompt.
    "rag": ("turn on the RAG knowledge base", frozenset({ToolEffect.READ_PRIVATE})),
    "document_editor": (
        "turn on the Document Editor",
        _effects_of("create_document", "edit_document", "update_document", "suggest_document"),
    ),
    # *Off* is the widening direction here: the chat is saved again and memory
    # is read and written again — `routes/chat_routes.py` withholds the memory
    # and history tools while Nobody mode is on.
    "incognito": (
        "turn off Nobody mode",
        frozenset({ToolEffect.READ_PRIVATE, ToolEffect.WRITE_PRIVATE}),
    ),
    # Agent mode is the tool loop itself, so it hands over what the tools do.
    "agent": ("switch to Agent mode", _effects_of(*KNOWN_CAPABILITY_TOOLS)),
})

# The one toggle whose *on* narrows: Nobody mode takes memory and history away.
_TOGGLES_THAT_NARROW_WHEN_ON = frozenset({"incognito"})


def self_escalation_for(tool_name: Any, content: Any) -> SelfEscalation | None:
    """`P7-02`. Would this action widen the assistant's own reach? `None` if not.

    The command is read by `src/ui_switches.switch_request`, which is the
    executor's own reading of it — so an alias, a capital letter, a tab or a
    trailing word means exactly here what it means when the command runs, and
    there is no spelling that one of them understands and the other does not.

    A toggle this table has not heard of fails *high*: its "on" is treated as a
    widening with every effect an unknown tool is assumed to have, the rule this
    module already applies to unknown tools. A new switch should be added to
    `_REACH_SWITCHES` with its own words — the test for that is what stops this
    fallback being the one a person ever reads.

    `P7-12`: and `manage_settings` raising a loop cap the owner typed
    (`_loop_cap_escalation`).
    """
    if tool_name == "manage_settings":
        return _loop_cap_escalation(content)
    if tool_name != "ui_control":
        return None
    request = switch_request(content)
    if not request:
        return None
    event = request.get("ui_event")
    if event == "toggle":
        switch = str(request.get("toggle_name") or "")
        state = bool(request.get("state"))
        widens = (not state) if switch in _TOGGLES_THAT_NARROW_WHEN_ON else state
    elif event == "set_mode":
        switch = str(request.get("mode") or "")
        widens = switch == "agent"
    else:
        # An error dict: the executor refuses the command, so it moves nothing.
        return None
    if not widens:
        return None
    words, grants = _REACH_SWITCHES.get(
        switch,
        (f"turn on {switch}", _UNKNOWN_CAPABILITIES.effects),
    )
    return SelfEscalation(switch=switch, words=words, grants=grants)


def _loop_cap_escalation(content: Any) -> SelfEscalation | None:
    """`P7-12`. A `manage_settings` call that raises a loop cap the owner typed.

    `D-2026-09-08-04`: the agent may set its own loop caps — *"a number the
    owner typed is not raised by the agent without saying so"* — and
    `D-2026-09-10-02` generalises it: *"the agent may move within the ceiling but
    never raise it."* So a raise of a pinned cap (`setting_is_explicit`, the pin
    `H08`'s lift honours) is the assistant widening its own reach, and it goes
    through the one mechanism for that (`Law 14`): asked every time, at every
    rung, under any blanket yes. A raise of a cap nobody typed is not asked
    about — that is the full automation the decision is for — and is held to
    the run by `manage_settings` itself.

    Read through `src/run_limits.loop_cap_request`, the executor's own reading
    of the call. Grants `admin_change`, which `manage_settings` already has, so
    the sealed effects of the card are exactly those of the action and an
    approval matches whatever the pin says by then.
    """
    try:
        request = owner_set_cap_raise(content)
    except Exception:
        return None
    if request is None:
        return None
    what = cap_label(request.key)
    words = (f"raise the {what} you set, {describe_cap(request.key, configured_cap(request.key))}, "
             f"to {describe_cap(request.key, request.requested)} for this run")
    return SelfEscalation(
        switch=request.key,
        words=words,
        grants=frozenset({ToolEffect.ADMIN_CHANGE}),
        only_you="Only you can raise a limit you set",
    )


_PRIVATE_ACTION_READS: Mapping[str, frozenset[str]] = MappingProxyType(
    {
        "manage_calendar": frozenset({"list_calendars", "list_events"}),
        "manage_contact": frozenset({"list"}),
        "manage_documents": frozenset({"list", "read", "view", "open", "get",
                                       "list_folders"}),
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
        # `P21-02`. Filing is a write to the person's own library; `remove_folder`
        # can delete what is in the folder, so it, and the two actions that can
        # carry it (`reorganise`, `apply_plan`), are destructive below as well.
        "manage_documents": frozenset({"delete", "tidy", "create_folder",
                                       "rename_folder", "move_folder", "move",
                                       "remove_folder", "reorganise", "apply_plan"}),
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
        "manage_documents": frozenset({"delete", "tidy", "remove_folder",
                                       "reorganise", "apply_plan"}),
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
        # `P21-02`. The spelling models reach for first; `document_tools.
        # _folder_action` maps it the same way so the classified action runs.
        "manage_documents": MappingProxyType({"reorganize": "reorganise"}),
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


# `P20-04`. Actions of a multiplexed tool that look and change nothing. A
# screenshot, or a wait before the next one, reads the person's own workstation
# screen: `read_workspace`, the effect `read_file` carries, which no rung's gate
# set blocks — so watching the screen never asks, and every click still does
# after untrusted content (the tool's own classification above). The result
# stays `EXTERNAL_UNTRUSTED`: what the screen shows is still a stranger's page.
_OBSERVE_ONLY_ACTIONS: Mapping[str, frozenset[str]] = MappingProxyType({
    "computer": frozenset({"screenshot", "wait"}),
})
_OBSERVE_ONLY_CAPABILITIES = _capabilities(
    ToolEffect.READ_WORKSPACE,
    result_integrity=ResultIntegrity.EXTERNAL_UNTRUSTED,
)


def capabilities_for_action(tool_name: Any, content: Any) -> ToolCapabilities:
    """Classify a sealed multiplexed action; ambiguous actions fail high."""
    base = capabilities_for_tool(tool_name)
    if not isinstance(tool_name, str):
        return base

    # `P7-02`. A switch the assistant would turn on for itself carries what the
    # switch hands over, so the card ranks it by that and not as a theme change:
    # registered as `ui_side_effect` alone, "turn on Shell access" drew the
    # lowest band on the card, below the `bash` command it exists to enable —
    # the inversion `P7-06` was written to end. The seal follows, because
    # `ExactToolApproval.claim` re-derives the effects from this function.
    escalation = self_escalation_for(tool_name, content)
    if escalation is not None:
        return ToolCapabilities(
            frozenset(base.effects | escalation.grants),
            base.result_integrity,
            known=base.known,
        )

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
    if action in _OBSERVE_ONLY_ACTIONS.get(tool_name, ()):
        return _OBSERVE_ONLY_CAPABILITIES
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

# `B967`. Where the action runs, when it is not this machine.
#
# Every phrase above is about the box Pantheon runs on, and that is what they
# meant until `P20-03`: with the workstation on, `bash`, `python` and the file
# tools run in the person's workstation, so a `bash` card read "Runs code on
# this machine" beside a *workstation* label saying the opposite, and a
# `read_file` there read "Reads workspace files" about a home this machine
# never sees. `computer` (`P20-04`) only ever acts on the workstation.
#
# Only the words change. The effect itself — `execute_code` is `execute_code`
# wherever it runs — and its rank are the same, so the gate decides exactly what
# it decided before, and the approval seal, which binds effect *values*, does
# not include where (`PendingToolApproval.runs_in`).
#
# `RUNS_IN_WORKSTATION` is the value `ran_in` already carries on a workstation
# result (`src/agent_tools/workstation_tools.py`), so the card's label and the
# effect phrase say one place in one word. Effects with no entry here keep their
# phrase: "Sends data out to the internet" is as true from the workstation.
RUNS_IN_WORKSTATION = "workstation"
_WHERE_EFFECT_PHRASE: Mapping[str, Mapping[ToolEffect, str]] = MappingProxyType({
    RUNS_IN_WORKSTATION: MappingProxyType({
        ToolEffect.EXECUTE_CODE: "Runs code in your workstation",
        # One phrase for the file tools and the computer's screenshot, which is
        # narrowed to `read_workspace` (`P20-04`): both read from there.
        ToolEffect.READ_WORKSPACE: "Reads from your workstation",
        ToolEffect.WRITE_WORKSPACE: "Writes files in your workstation",
    }),
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


def describe_effects(capabilities: Any, *, runs_in: Any = None) -> dict:
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

    `runs_in` (`B967`): where the action runs when it is not this machine —
    `RUNS_IN_WORKSTATION`, or nothing. It changes words only; the values, the
    rank and the band are the same either way, and anything else is ignored.
    """
    effects = getattr(capabilities, "effects", None)
    if effects is None and isinstance(capabilities, (list, tuple, set, frozenset)):
        effects = capabilities
    if not effects:
        return {}
    ranked = sorted(effects, key=lambda e: (-effect_severity(e), str(getattr(e, "value", e))))
    values = [e.value if isinstance(e, ToolEffect) else str(e) for e in ranked]
    where = _WHERE_EFFECT_PHRASE.get(runs_in, {}) if isinstance(runs_in, str) else {}

    def _phrase(effect: Any) -> str:
        """The words, or the identifier when there are none.

        A raw string reaching here still gets its phrase if it names a member of
        the enum — the approval record stores values, not members, and it would
        otherwise show identifiers to the one person being asked to consent.
        """
        try:
            member = ToolEffect(effect)
            return where.get(member) or _EFFECT_PHRASE[member]
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
# CORRECTED 2026-09-27 (`P7-13`). This said *"Ordered strictest first. Only the
# order is meaningful."* Nothing read the order, and nothing could: which rung
# is stricter was written nowhere, and `D-2026-09-08-05` records that it could
# not be read from outside. `TRUST_LADDER` below is where the order now lives,
# derived from what each rung asks about; the declaration order here is kept
# (`Law 1`) and means nothing.
class TrustRung(str, Enum):
    ASK_EVERY_TIME = "ask_every_time"
    ALLOW_LISTED = "allow_listed"
    GATE_ON_UNTRUSTED = "gate_on_untrusted"


DEFAULT_TRUST_RUNG = TrustRung.GATE_ON_UNTRUSTED


# ── The ladder, defined by what each rung stops and asks about (P7-13) ───────
#
# `D-2026-09-08-05`: *"we make our own trust rungs. Because the current
# posturing of failure detection etc is incorrectly done."* The row asked
# whether an order exists among the three inherited rungs, because two callers
# talk as if one does — a role profile *"may only raise strictness"*, and a turn
# that says "ask me before using tools" is raised to the strictest rung — while
# nothing said what "stricter" meant. The owner's test for an order is the
# only one that can be checked: **a rung is a set of conditions under which the
# assistant stops and asks the person, and rung N's set is a strict superset of
# rung N−1's.** Two rungs that fail it are two switches wearing one field.
#
# So each rung is written down here as its set of `StopCondition`s, and
# `decision_for` asks *that set* rather than the rung's name — the ladder is the
# behaviour, not a description of it beside the behaviour (`Law 7`, `Law 13`).
# The inherited names keep working and keep their meaning (`Law 1`); each is one
# rung of this ladder.
#
# **Measured before it was written, and the premise had moved since the
# decision.** On 2026-09-08 the three were not ordered in behaviour; `P7-03`'s
# fix — a blanket yes no longer outranks a rung that asks — and `P7-04`'s — a
# standing rule does not survive untrusted content — are what made them nest.
# The sets below are exactly what `decision_for` did before this block existed,
# which a test proves by driving the gate through every case and asking which
# condition it was in when it asked. What was missing was never the order; it
# was any one place that said it, so every caller that needed it assumed it.
#
# A condition is a *situation*, and the five partition every consequential
# action — a registered effect the relevant gate set blocks, or an unrecognised
# tool — by who could be steering it and what the person has already said:
class StopCondition(str, Enum):
    # The assistant would give itself more reach than the person left it, or
    # raise a limit the person set (`P7-02`, `P7-12`: `self_escalation_for`).
    MORE_REACH = "more_reach"
    # Untrusted content has entered the run — a fetched page, an email, a file
    # someone else wrote — and nothing the person said covers the action.
    AFTER_UNTRUSTED = "after_untrusted"
    # Nothing untrusted has entered, and no standing allow rule covers it.
    IN_A_CLEAN_CHAT = "in_a_clean_chat"
    # Untrusted content has entered, after the person pressed "allow for this
    # task" or "for this chat" on an earlier card: a yes given for one action,
    # not for whatever a stranger's text asks for next.
    AFTER_UNTRUSTED_DESPITE_A_YES = "after_untrusted_despite_a_yes"
    # Nothing untrusted has entered, and a standing allow rule (`P7-04`) covers
    # it — the one condition that separates "ask every time" from "allow-listed".
    DESPITE_A_STANDING_RULE = "despite_a_standing_rule"


# What each condition means to a person, in the words `manage_settings` uses to
# say which way a move of the rung went. Each completes both "Pantheon now also
# stops and asks ..." and "Pantheon no longer stops and asks ...".
STOP_CONDITION_WORDS: Mapping[StopCondition, str] = MappingProxyType({
    StopCondition.MORE_REACH:
        "before it gives itself more reach, or a higher limit than you set",
    StopCondition.AFTER_UNTRUSTED:
        "before anything consequential once something from outside the chat "
        "(a web page, an email, a file it fetched) has come in",
    StopCondition.IN_A_CLEAN_CHAT:
        "before anything that changes or sends something in a clean chat",
    StopCondition.AFTER_UNTRUSTED_DESPITE_A_YES:
        "after something from outside has come in, when you had already "
        "allowed the task or the whole chat",
    StopCondition.DESPITE_A_STANDING_RULE:
        "before an action you saved an allow rule for",
})

# The conditions no rung may drop. Below them there is nothing to call a gate:
# a rung without `AFTER_UNTRUSTED` would lift the post-external gate
# `FORBIDDEN.md` Part 2 says never lifts, and one without `MORE_REACH` would let
# the assistant hand itself what the person withheld (`P7-02`).
FLOOR_STOP_CONDITIONS = frozenset({StopCondition.MORE_REACH, StopCondition.AFTER_UNTRUSTED})

# Least asking first. Each rung is the one before it plus what it adds.
TRUST_LADDER: tuple[tuple[TrustRung, frozenset[StopCondition]], ...] = (
    (TrustRung.GATE_ON_UNTRUSTED, FLOOR_STOP_CONDITIONS),
    (TrustRung.ALLOW_LISTED, FLOOR_STOP_CONDITIONS | {
        StopCondition.AFTER_UNTRUSTED_DESPITE_A_YES,
        StopCondition.IN_A_CLEAN_CHAT,
    }),
    (TrustRung.ASK_EVERY_TIME, FLOOR_STOP_CONDITIONS | {
        StopCondition.AFTER_UNTRUSTED_DESPITE_A_YES,
        StopCondition.IN_A_CLEAN_CHAT,
        StopCondition.DESPITE_A_STANDING_RULE,
    }),
)


def validate_trust_ladder(ladder) -> None:
    """Raise `ValueError` unless `ladder` is one: every rung exactly once, the
    floor in all of them, and each a strict superset of the one below.

    Run on `TRUST_LADDER` at import, so a ladder that is not one cannot ship —
    the failure `D-2026-09-08-05` diagnosed is "an order everybody assumed and
    nobody checked", and a check that runs only in a test is a check someone
    can skip.
    """
    rungs = [rung for rung, _ in ladder]
    if sorted(r.value for r in rungs) != sorted(r.value for r in TrustRung):
        raise ValueError(f"the ladder must name every rung exactly once: {rungs}")
    below = None
    for rung, conditions in ladder:
        if not FLOOR_STOP_CONDITIONS <= conditions:
            raise ValueError(f"{rung.value} drops a floor condition")
        if below is not None and not conditions > below:
            raise ValueError(
                f"{rung.value} is not a strict superset of the rung below it, "
                "so the two cannot be ordered: they are two switches, not two rungs"
            )
        below = conditions


validate_trust_ladder(TRUST_LADDER)

_STOP_CONDITIONS: Mapping[TrustRung, frozenset[StopCondition]] = MappingProxyType(dict(TRUST_LADDER))
_RUNG_RANK: Mapping[TrustRung, int] = MappingProxyType(
    {rung: rank for rank, (rung, _) in enumerate(TRUST_LADDER)}
)


def stop_conditions(rung: Any) -> frozenset[StopCondition]:
    """When a run on `rung` stops and asks. An unreadable rung is the default,
    by `coerce_trust_rung`'s rule."""
    return _STOP_CONDITIONS[coerce_trust_rung(rung)]


def rung_rank(rung: Any) -> int:
    """`0` for the rung that asks least; one more for each rung above it."""
    return _RUNG_RANK[coerce_trust_rung(rung)]


def is_stricter(rung: Any, than: Any) -> bool:
    """Whether `rung` asks in every situation `than` asks in, and more. The
    owner's definition, applied to the sets rather than to a rank."""
    return stop_conditions(rung) > stop_conditions(than)


def stricter_of(*rungs: Any) -> TrustRung:
    """The rung that asks most of `rungs` — how a rule that *"may only raise
    strictness"* combines a floor with what it was given."""
    if not rungs:
        return DEFAULT_TRUST_RUNG
    return max((coerce_trust_rung(r) for r in rungs), key=lambda r: _RUNG_RANK[r])


def strictest_rung() -> TrustRung:
    return TRUST_LADDER[-1][0]


# The three answers to "which way did the rung move" (`Law 10`: an enum, not a
# boolean — "not stricter" is two different things).
RUNG_STRICTER = "stricter"
RUNG_LOOSER = "looser"
RUNG_UNCHANGED = "unchanged"


def rung_direction(before: Any, after: Any) -> str:
    """Which way moving from `before` to `after` goes on the ladder."""
    if is_stricter(after, before):
        return RUNG_STRICTER
    if is_stricter(before, after):
        return RUNG_LOOSER
    return RUNG_UNCHANGED


def rung_move_sentence(before: Any, after: Any) -> str:
    """What moving the rung from `before` to `after` changes, in words.

    `P7-13`'s chat-side reader. `manage_settings set trust_rung` used to answer
    *"Set trust_rung = allow_listed."* and nothing else, so neither the person
    reading the tool card nor the model could tell a tightening from a
    loosening — the question `B42` got wrong in both directions. The answer is
    read off the ladder: the conditions the move adds or drops, in
    `STOP_CONDITION_WORDS`, in the order the enum lists them.
    """
    before_rung, after_rung = coerce_trust_rung(before), coerce_trust_rung(after)
    direction = rung_direction(before_rung, after_rung)
    if direction == RUNG_UNCHANGED:
        return f"It was already {after_rung.value}."
    gained = stop_conditions(after_rung) - stop_conditions(before_rung)
    lost = stop_conditions(before_rung) - stop_conditions(after_rung)
    changed = [STOP_CONDITION_WORDS[c] for c in StopCondition if c in (gained | lost)]
    if direction == RUNG_STRICTER:
        return (f"That is stricter than {before_rung.value}: Pantheon now also stops "
                f"and asks {'; '.join(changed)}.")
    return (f"That is looser than {before_rung.value}: Pantheon no longer stops "
            f"and asks {'; '.join(changed)}.")


def rung_consults_allow_rules(rung: Any) -> bool:
    """Whether a standing allow rule can answer for this rung: it asks in a
    clean chat, and not despite a rule. `src/agent_loop.py` builds the rule
    lookup only when this is true, since no other rung would read it."""
    asks = stop_conditions(rung)
    return (
        StopCondition.IN_A_CLEAN_CHAT in asks
        and StopCondition.DESPITE_A_STANDING_RULE not in asks
    )


# The rungs that ask in a clean session — derived from the ladder now, and kept
# under its old name because tests and readers use it (`Law 1`).
# `GATE_ON_UNTRUSTED` is the current behaviour and stays exactly as it was: an
# untainted run is never gated.
_RUNGS_THAT_ASK_UNTAINTED = frozenset(
    rung for rung, conditions in TRUST_LADDER
    if StopCondition.IN_A_CLEAN_CHAT in conditions
)


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
            or StopCondition.IN_A_CLEAN_CHAT in stop_conditions(self.rung)
        )

    def asks_for(self, tool_name: Any, content: Any = None) -> bool:
        """Whether this run's gate stops and asks before *this* action.

        `P7-02`. `gate_is_armed` answers for the whole run and keeps meaning
        exactly that. A self-escalation asks in every run, armed or not — so its
        approval has to be replayable into a run whose gate is otherwise quiet,
        or the card it mints is one nobody can answer: `P7-03`'s incident a
        second time, at the same line of `src/tool_execution.py`.
        """
        return self.gate_is_armed or self_escalation_for(tool_name, content) is not None

    def decision_for(self, tool_name: Any, content: Any = None) -> ToolGateDecision:
        # `P7-13`. Every question below is asked of this set — the rung's stop
        # conditions from `TRUST_LADDER` — and never of the rung's name, so the
        # ladder that says which rung is stricter is the gate that enforces it.
        asks = stop_conditions(self.rung)
        # B70. Checked before the bypasses below, because neither may lift it,
        # and kept independent of `external_untrusted_context_seen` so it holds
        # on a run where that gate never arms and raises no prompt to bypass.
        # `B995`: the non-admin policy plus what only a token is refused, the
        # same set `delegated_credential_blocked_tools()` withholds up front.
        if self.delegated_credential and is_delegated_credential_blocked_tool(tool_name):
            return ToolGateDecision(
                False,
                (
                    f"Tool '{tool_name}' is not available to API-token callers. "
                    "It requires an interactive session."
                ),
                classification=TOOL_CLASSIFICATION_UNAVAILABLE,
            )
        # `P7-02`. Before the bypass and before the untainted exit, because
        # both exist to let the assistant *act* without asking, and neither is
        # a person choosing to give it more to act with. Below B70, whose
        # refusal no approval lifts — this one an approval does, once.
        escalation = self_escalation_for(tool_name, content)
        if escalation is not None and StopCondition.MORE_REACH in asks:
            return self._self_escalation_decision(escalation)
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
        #
        # `P7-13`: "a rung that asks" is the one whose set holds
        # `AFTER_UNTRUSTED_DESPITE_A_YES` — the condition this line exists for.
        if (
            self.approval_gate_bypassed
            and StopCondition.AFTER_UNTRUSTED_DESPITE_A_YES not in asks
        ):
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
        asks_untainted = StopCondition.IN_A_CLEAN_CHAT in asks
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
        # be the control lying about its own name. `P7-13`: that is the rung
        # without `DESPITE_A_STANDING_RULE` among those that ask at all in a
        # clean chat — the default never reaches this line untainted.
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
            StopCondition.DESPITE_A_STANDING_RULE not in asks
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

    def _self_escalation_decision(self, escalation: SelfEscalation) -> ToolGateDecision:
        """`P7-02`. The refusal, in the words on the switch.

        The sentence reaches the card through the same door every refusal does
        — `decision.reason` becomes the payload's `description`, which
        `static/js/chatRenderer.js` draws under the question (`P4-04`) — and the
        grant rides beside it as `tripped_effects`, ranked by `describe_effects`.

        It says "every time" and "even after you have allowed other actions"
        because the card's own buttons say "allow for this task" and "allow for
        this chat session", and a person who pressed one of those earlier is
        owed the reason they are being asked again.

        Taint is named when it is true and never when it is not: the card's
        `gate.tainted` sits beside this sentence, and a sentence blaming
        untrusted content over `tainted: false` is two statements contradicting
        each other on one surface (`Law 10`, `P4-04`).
        """
        why = (
            "External untrusted context has already influenced this run. "
            if self.external_untrusted_context_seen
            else ""
        )
        # `P7-07`'s meaning of "tripped": the part of the grant the gate treats
        # as consequential, not every effect it includes — "Asks you a question"
        # is part of Agent mode and is not why anybody is being asked.
        tripped = (escalation.grants & POST_EXTERNAL_BLOCKED_EFFECTS) or escalation.grants
        return ToolGateDecision(
            False,
            (
                f"{why}The assistant wants to {escalation.words}. "
                f"{escalation.only_you}, so it asks every time — even after you "
                "have allowed other actions."
            ),
            tripped_effects=tuple(describe_effects(tripped).get("effects", ())),
            classification=TOOL_CLASSIFICATION_RECOGNISED,
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
