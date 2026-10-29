# SPDX-License-Identifier: AGPL-3.0-or-later
"""Deterministic capability metadata for agent tools.

Model output requests an action; it never supplies the authority for that
action.  This module classifies the effects of each built-in tool and applies
run-local integrity gates before dispatch.
"""

from __future__ import annotations

import functools
import json
import logging
import uuid
from dataclasses import dataclass, field
from enum import Enum
from types import MappingProxyType
from typing import Any, Iterable, Mapping

from src.tool_approval_scopes import CHAT_SESSION_APPROVAL_CONTEXT_MARKER
from src.tool_security import (
    BUILTIN_EMAIL_TOOLS,
    delegated_credential_refusal,
    is_delegated_credential_blocked_tool,
)
from src.ui_switches import switch_request
from src.settings_requests import settings_call
from src.run_limits import (
    cap_label,
    configured_cap,
    describe_cap,
    loop_cap_request,
    owner_set_cap_raise,
)

logger = logging.getLogger(__name__)


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
        # `B1621`. One of the person's own chats, read through: their words
        # and the assistant's, which may quote a page or a mail, so data.
        "read_chat",
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
    # `P27-09`. The logins an agent may use, by name (reading the person's own
    # vault's labels), and whether one's address answers (reaching it).
    {"connections"},
    ToolEffect.READ_PRIVATE,
    ToolEffect.NETWORK_EGRESS,
    result_integrity=ResultIntegrity.EXTERNAL_UNTRUSTED,
)
_register(
    # `P27-07`. A shell command, with the person's own credentials in it:
    # running code, and whatever it reaches it reaches signed in as them —
    # outward, under their name, as a push is.
    {"shell_with_login"},
    ToolEffect.EXECUTE_CODE,
    ToolEffect.NETWORK_EGRESS,
    ToolEffect.EXTERNAL_SIDE_EFFECT,
    result_integrity=ResultIntegrity.EXTERNAL_UNTRUSTED,
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
    # `P16-20`. What network the workstation sits on: the tool as a whole
    # carries reading (its `list`) and reaching the network (a `reach`), each
    # call classified by its action below (`_ACTION_CAPABILITIES`).
    {"network"},
    ToolEffect.READ_WORKSPACE,
    ToolEffect.NETWORK_EGRESS,
    result_integrity=ResultIntegrity.EXTERNAL_UNTRUSTED,
)
_register(
    # `P25-05`. The agent browser: everything any of its actions can do (what an
    # agent's effects table lists), each call classified by its action below.
    {"agent_browser"},
    ToolEffect.READ_PUBLIC,
    ToolEffect.NETWORK_EGRESS,
    ToolEffect.EXTERNAL_SIDE_EFFECT,
    result_integrity=ResultIntegrity.EXTERNAL_UNTRUSTED,
)
_register(
    # `P25-03`. The person's own git. The tool as a whole carries every effect
    # one of its actions has — what an agent's effects table lists for it
    # (`src/agents/hires.manifest_effects`) — and each call is classified by
    # its action (`_ACTION_CAPABILITIES` below), so a status never asks and a
    # push is what it is: something sent out under the person's name.
    {"git"},
    ToolEffect.READ_WORKSPACE,
    ToolEffect.WRITE_WORKSPACE,
    ToolEffect.NETWORK_EGRESS,
    ToolEffect.EXTERNAL_SIDE_EFFECT,
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
    if tool_name.startswith("mcp__") and _mcp_declared_read_only(tool_name):
        return _BROWSER_MCP_READ_CAPABILITIES
    return _UNKNOWN_CAPABILITIES


def _mcp_declared_read_only(tool_name: str) -> bool:
    """`B1329`. An MCP tool its server (or the operator's override) declares
    read-only is classified as the built-in browser's read tools are:
    `brokered_network_read`, which no rung blocks, with its result
    `external_untrusted`.

    Every MCP tool used to be `known=False`, so once a run was tainted a pure
    lookup was refused with *"can cause unknown/high-impact"* exactly as a
    destructive one was. **The adversary (`Law 17`) is the server itself** —
    the thing the gate exists to hold — and `readOnlyHint` is its claim. So the
    claim may only soften: it can turn "unknown, refuse" into "a read, run",
    for this call, and nothing more. It never adds an effect, never makes the
    output trusted (the result still arms the gate, so the next effectful call
    asks — the hint is about the call, never about what comes back), and it
    lifts no other control: plan mode, the disabled list, a step's allowlist
    and `NON_ADMIN_BLOCKED_TOOLS` are all asked before this and unchanged.
    Without a hint — or with `destructiveHint` beside it, or the operator's
    override saying otherwise — the tool stays unknown. A manager that cannot
    be asked answers *not declared*: fails high.
    """
    try:
        from src.tool_utils import get_mcp_manager
        manager = get_mcp_manager()
        if manager is None:
            return False
        return bool(manager.declared_read_only(tool_name))
    except Exception:
        logger.debug("MCP read-only declaration unreadable for %r; unknown", tool_name,
                     exc_info=True)
        return False


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
    # `B898`: no `document_editor` — the chat has no such switch, and
    # `ui_switches` refuses it with a sentence saying where the real one is.
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
    (`_loop_cap_escalation`). `B897`/`B912`: and `manage_settings` switching a
    capability on, moving a destination, or turning back on a tool that is
    switched off in Settings (`_settings_escalation`).
    """
    if tool_name == "manage_settings":
        return _loop_cap_escalation(content) or _settings_escalation(content)
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


# ── `manage_settings` and the assistant's own reach (`B897`, `B912`) ────────
#
# `D-2026-10-25-01`, the owner answering `B700`: *"self switch is good with user
# consent"* — the assistant may propose giving itself more reach, and each such
# switch stops and asks; the yes is for that one switch. `P7-02` built that for
# `ui_control`'s chat switches. `manage_settings` writes the server's settings,
# and through it the same widening went through unasked: measured against a
# scratch data dir at the default rung in a clean run, `image_gen_enabled`,
# `teacher_enabled`, `teacher_tier2_enabled` and `stt_enabled` went `False →
# True`, `allow_model_download` and `metrics_enabled` `None → 'true'`,
# `remote_images` `'ask' → 'allow'`, four destinations took an address nobody
# configured, and `enable_tool shell` took `bash`/`host_shell` out of the
# `disabled_tools` an admin wrote (`B912`).
#
# **The adversary (`Law 17`)** is the one `B42` names: a page, a document or a
# mail the assistant was asked to read, whose instruction arrives as the same
# tool call the person's would — and, in a clean chat, the model acting alone on
# its own reading of a request. Neither is a person choosing to hand the
# assistant more. So these ask every time, through `P7-02`'s one mechanism
# (`Law 14`): at every rung, tainted or clean, and under any blanket yes. They
# are not refused (that is `B42`'s list, for gates whose purpose is "a human
# must confirm"): the person keeps the ability to ask for them from chat.
#
# One-directional, as `P7-02` is: switching a capability off, clearing a
# destination and `disable_tool` only narrow, and stay unasked. A destination
# is the address *is* the switch (`Law 16`: "the destination is configured by
# the person running it"), so any new non-empty address asks.
#
# Each entry: (words for the card, what it hands over). The words take the new
# address for a destination. `D-2026-10-25-01` records why these keys and not
# `forge_model_hubs` (`src/settings.py` says why the agent may set that one).
_SETTING_SWITCHES: Mapping[str, tuple[str, frozenset[ToolEffect]]] = MappingProxyType({
    "image_gen_enabled": ("turn on image generation", _effects_of("generate_image")),
    # `src/teacher_escalation.py`: a failed turn goes to another model, and
    # what it writes back is saved as a skill.
    "teacher_enabled": (
        "turn on the teacher model, which is sent a failed turn and saves a skill",
        frozenset({ToolEffect.NETWORK_EGRESS, ToolEffect.WRITE_PRIVATE}),
    ),
    "teacher_tier2_enabled": (
        "turn on the teacher model's self-check, which sends turns to it to grade",
        frozenset({ToolEffect.NETWORK_EGRESS, ToolEffect.WRITE_PRIVATE}),
    ),
    "stt_enabled": ("turn on speech to text", frozenset({ToolEffect.READ_PRIVATE})),
    "allow_model_download": (
        "let Pantheon download models from the internet",
        frozenset({ToolEffect.NETWORK_EGRESS}),
    ),
    "metrics_enabled": (
        "serve this instance's readings at /metrics to anything that asks",
        frozenset({ToolEffect.READ_PRIVATE}),
    ),
    # `P16-10`: the retry that drops the pinned engines hands the query to
    # SearXNG's defaults.
    "searxng_widen_engines": (
        "let a failed search retry on SearXNG's default engines",
        frozenset({ToolEffect.NETWORK_EGRESS}),
    ),
    "agent_lan_reach": (
        "let its web tools reach your local network",
        frozenset({ToolEffect.NETWORK_EGRESS}),
    ),
    # Its three modes are an order, `block` < `ask` < `proxy`
    # (`routes/image_proxy_routes.py`); a move up the order is the widening.
    "remote_images": (
        "fetch remote images in content you did not write",
        frozenset({ToolEffect.NETWORK_EGRESS}),
    ),
})

_SETTING_DESTINATIONS: Mapping[str, str] = MappingProxyType({
    "otlp_endpoint": "push this instance's metrics to",
    "search_url": "send every web search to the search server at",
    "search_provider": "send every web search to",
    "research_search_provider": "send Deep Research's searches to",
    "reminder_email_to": "email your reminders to",
    "reminder_ntfy_topic": "post your reminders to the ntfy topic",
    "netagent_url": "send network-agent commands, and its token, to",
    "issue_tracker_url": "point the diagnostic bundle's report link at",
    "source_url": "point the source-code link at",
})

_DESTINATION_GRANTS = frozenset({ToolEffect.NETWORK_EGRESS, ToolEffect.EXTERNAL_SIDE_EFFECT})

# `routes/image_proxy_routes.VALID_MODES`, in the order of what each lets out;
# a value outside it is read as `ask` there, and refused by `manage_settings`.
_REMOTE_IMAGE_ORDER = MappingProxyType({"block": 0, "ask": 1, "proxy": 2})


def _stored_settings() -> dict | None:
    try:
        from src.settings import load_settings
        stored = load_settings()
    except Exception:
        return None
    return stored if isinstance(stored, dict) else None


def _switch_is_on(key: str, settings: dict) -> bool:
    """A switch's effective state, read the way its readers read it: the three
    tri-state flags through `env_backed_flag` (stored → environment →
    default), the rest as the bool they are stored as."""
    try:
        from src.settings import ENV_BACKED_FLAGS, env_backed_flag
        if key in ENV_BACKED_FLAGS:
            env_name, default = ENV_BACKED_FLAGS[key]
            return bool(env_backed_flag(settings, key, env_name, default))
    except Exception:
        return False
    return bool(settings.get(key))


def _remote_image_rank(value: Any) -> int | None:
    return _REMOTE_IMAGE_ORDER.get(str(value if value is not None else "").strip().lower())


def _settings_escalation(content: Any) -> SelfEscalation | None:
    """`B897`/`B912`. A `manage_settings` call that widens the assistant's own
    reach: a capability switched on, a destination moved to a new address, or
    `enable_tool` for a tool in `disabled_tools`. `None` for anything else.

    Read through `src/settings_requests.settings_call`, the executor's own
    reading of the call. Compared with what is stored, so a call that moves
    nothing asks nothing; a store that cannot be read fails *high* (every one
    of these is then treated as a widening). The grants depend on the call
    alone, never on the store, so the effects an approval seals are the ones it
    is claimed against.
    """
    call = settings_call(content)
    if call is None:
        return None
    stored = _stored_settings()
    if call.action == "enable_tool":
        if stored is None:
            freed = list(call.targets)
        else:
            disabled = stored.get("disabled_tools")
            disabled = disabled if isinstance(disabled, list) else []
            freed = [t for t in call.targets if t in disabled]
        if not freed:
            return None
        grants = frozenset({ToolEffect.ADMIN_CHANGE}).union(
            *(capabilities_for_tool(name).effects for name in call.targets))
        return SelfEscalation(
            switch=f"enable_tool:{call.tool}",
            words=(f"turn {call.tool} back on ({', '.join(freed)}), which is switched "
                   "off for it in Settings"),
            grants=grants,
        )
    key = call.key
    before = stored if stored is not None else {}
    after = dict(before)
    after[key] = call.value
    if key in _SETTING_SWITCHES:
        words, grants = _SETTING_SWITCHES[key]
        if key == "remote_images":
            new_rank = _remote_image_rank(call.value)
            old_rank = _remote_image_rank(before.get(key))
            if new_rank is None:
                return None  # refused by the executor: moves nothing
            widens = stored is None or new_rank > (old_rank if old_rank is not None else 1)
            if call.value is not None and str(call.value).strip().lower() == "ask":
                words = "show remote images in content you did not write on a click"
        else:
            widens = _switch_is_on(key, after) and (stored is None or not _switch_is_on(key, before))
        if not widens:
            return None
        return SelfEscalation(
            switch=key, words=words,
            grants=frozenset(grants | {ToolEffect.ADMIN_CHANGE}),
        )
    if key in _SETTING_DESTINATIONS:
        new = str(call.value if call.value is not None else "").strip()
        old = str(before.get(key) if before.get(key) is not None else "").strip()
        if not new or (stored is not None and new == old):
            return None
        shown = new if len(new) <= 120 else new[:117] + "…"
        return SelfEscalation(
            switch=key,
            words=f"{_SETTING_DESTINATIONS[key]} “{shown}”",
            grants=frozenset(_DESTINATION_GRANTS | {ToolEffect.ADMIN_CHANGE}),
            only_you="Only you can choose where Pantheon sends things",
        )
    return None


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
        "manage_tasks": frozenset({"create", "edit", "delete", "pause", "resume", "run", "draft_workflow"}),
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
        # `P25-03`. The spellings `git` accepts; `git_tools` reads them from
        # here (`Law 7`), so the action classified is the action run.
        # `P25-05`. `agent_browser`'s spellings, read by the tool from here.
        "agent_browser": MappingProxyType({"navigate": "open", "goto": "open", "visit": "open",
                                           "get_text": "read", "snapshot": "read", "fill": "type",
                                           "key": "press", "new_tab": "tab_new",
                                           "switch_tab": "tab_switch", "close_tab": "tab_close",
                                           "refresh": "reload", "go_back": "back"}),
        "git": MappingProxyType({"st": "status", "show": "diff", "history": "log",
                                 "checkout": "branch", "switch": "branch", "ci": "commit",
                                 "fetch": "pull", "publish": "push"}),
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


# `P16-20`: `network` too, so a bare `network reach 10.0.0.5 443` resolves its
# action for the gate the same as the JSON form does.
_LINE_ACTION_TOOLS = frozenset({"manage_memory", "manage_session", "network"})

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


# `P25-03`. A multiplexed tool whose actions differ in kind, not only in
# whether they look: each action's own effects. An action the table does not
# name keeps the tool's whole registration (fail high). Results that only
# show the repository are `WORKSPACE_UNTRUSTED` — its files are whoever wrote
# them — and what a pull or clone brings from a host is `EXTERNAL_UNTRUSTED`.
_LOOK = _capabilities(ToolEffect.READ_PUBLIC, result_integrity=ResultIntegrity.EXTERNAL_UNTRUSTED)
_REACH = _capabilities(ToolEffect.NETWORK_EGRESS, result_integrity=ResultIntegrity.EXTERNAL_UNTRUSTED)
_SEND = _capabilities(ToolEffect.NETWORK_EGRESS, ToolEffect.EXTERNAL_SIDE_EFFECT,
                      result_integrity=ResultIntegrity.EXTERNAL_UNTRUSTED)
_ACTION_CAPABILITIES: Mapping[str, Mapping[str, ToolCapabilities]] = MappingProxyType({
    # `P25-05`. Looking at what is open never asks; going somewhere reaches the
    # web; a click, typing and a key press can send a form, a message or an
    # order, so they are what a push is — outward, under the person's name.
    "agent_browser": MappingProxyType({
        "read": _LOOK, "screenshot": _LOOK, "tabs": _LOOK, "tab_switch": _LOOK,
        "tab_close": _LOOK, "scroll": _LOOK,
        "open": _REACH, "back": _REACH, "forward": _REACH, "reload": _REACH, "tab_new": _REACH,
        "click": _SEND, "type": _SEND, "press": _SEND,
        # `P27-06`. Signing in sends the person's own credentials to a
        # service: outward, under their name, whatever the page.
        "login": _SEND,
        # `P26-03`. Reading the person's notes and closing one touch only the
        # notes, which are the person's words to the agent — looking.
        "notes": _LOOK, "note_done": _LOOK,
        # `P25-11`. Reading how the open page is made — looking.
        "inspect": _LOOK,
    }),
    # `P27-09`. Listing reads the person's own vault's names; a test reaches
    # the address — a status line back from a stranger's server.
    "connections": MappingProxyType({
        "list": _capabilities(ToolEffect.READ_PRIVATE),
        "test": _REACH,
    }),
    # `P16-20`. Listing reads this machine's own interfaces and the person's
    # declared networks — local, looking. A `reach` opens a connection to a
    # host the model names — the same shape as a fetch.
    "network": MappingProxyType({
        "list": _capabilities(ToolEffect.READ_WORKSPACE),
        "reach": _REACH,
    }),
    "git": MappingProxyType({
        "status": _capabilities(ToolEffect.READ_WORKSPACE,
                                result_integrity=ResultIntegrity.WORKSPACE_UNTRUSTED),
        "diff": _capabilities(ToolEffect.READ_WORKSPACE,
                              result_integrity=ResultIntegrity.WORKSPACE_UNTRUSTED),
        "log": _capabilities(ToolEffect.READ_WORKSPACE,
                             result_integrity=ResultIntegrity.WORKSPACE_UNTRUSTED),
        "branch": _capabilities(ToolEffect.WRITE_WORKSPACE,
                                result_integrity=ResultIntegrity.WORKSPACE_UNTRUSTED),
        "commit": _capabilities(ToolEffect.WRITE_WORKSPACE,
                                result_integrity=ResultIntegrity.WORKSPACE_UNTRUSTED),
        "pull": _capabilities(ToolEffect.NETWORK_EGRESS, ToolEffect.WRITE_WORKSPACE,
                              result_integrity=ResultIntegrity.EXTERNAL_UNTRUSTED),
        "clone": _capabilities(ToolEffect.NETWORK_EGRESS, ToolEffect.WRITE_WORKSPACE,
                               result_integrity=ResultIntegrity.EXTERNAL_UNTRUSTED),
        "push": _capabilities(ToolEffect.NETWORK_EGRESS, ToolEffect.EXTERNAL_SIDE_EFFECT,
                              result_integrity=ResultIntegrity.EXTERNAL_UNTRUSTED),
    }),
})


# ── `B930` · a step-limit reply is Pantheon's own words ─────────────────────
#
# `manage_settings` is registered `EXTERNAL_UNTRUSTED` above because the admin
# managers echo configuration back: a `get` or a `list` returns stored values
# that a person, an import or an earlier call may have written, and the model
# then reads them as text. `P7-12`'s loop-cap replies were classified the same
# way, and they are not that. Measured (`P7-12`, re-measured by `w5-local`):
# after *"Raised this run's step limit to 60 steps…"* in a clean run at the
# default rung, the next `bash ls` was refused with *"External untrusted context
# has already influenced this run"*, the trail naming `manage_settings` — a
# false sentence on the card (`Law 10`), and an agent that gave itself more
# steps was then stopped at every consequential one, the opposite of the
# automation `D-2026-09-08-04` asked for.
#
# The owner's call (`D-2026-10-01-04`): **trust only step-limit replies.** A
# `manage_settings` call that `run_limits.loop_cap_request` recognises — the
# executor's own reading of the call (`_parse_tool_args`, the same key aliases,
# `int()` on the value), so the gate and the tool cannot disagree about which
# call this is — has a `SYSTEM` result. Nothing else moves: the effects are the
# action's as before (so the card, the approval seal's effects and every rung
# decide exactly what they decided), the gate itself is untouched (`FORBIDDEN.md`
# Part 2), and a run already tainted stays tainted — `SYSTEM` only declines to
# arm the gate, and nothing disarms it.
#
# **Why that reply cannot carry outside content.** Every exit
# `do_manage_settings` (`src/agent_tools/admin_tools.py`) has for such a call:
#
#   * a raise (`_loop_cap_raise`) — `RaiseOutcome.words`: fixed sentences
#     around `cap_label` (one of two fixed names) and `describe_cap` (an
#     integer, formatted), plus `run_limit` — `key` one of `LOOP_CAP_KEYS`,
#     `outcome` one of four constants, `limit` an integer or `None`, `saved`
#     False;
#   * a lowering, saved — *"Set {key} = {value}."* and `B931`'s clamp sentence:
#     `key` is the resolved key (one of the two, never the alias the model
#     wrote) and `value` has been through `int()` and `clamp_int_setting`;
#   * a reset or delete, saved — *"Reset {key} to default ({default})."*, a
#     shipped integer;
#   * an exception — `str(e)` from Pantheon's own settings store (an OS error
#     about its own file, or `P3-16`'s refusal to replace an unreadable one).
#     `int()` cannot be what raises: `loop_cap_request` already parsed the same
#     value, and a value it cannot parse is not recognised.
#
# None of them reads back a stored string, a file, a page, a mailbox or a
# person's text. What is *not* recognised keeps `EXTERNAL_UNTRUSTED`: `get`,
# `list`, every other key, a loop-cap `set` whose value `int()` refuses (its
# error repeats the value), and any MCP tool merely named `manage_settings`
# (`mcp__…`, which never reaches this executor).
#
# Decided from the call, never from the result: a tool cannot mark its own
# output trusted (the shape `B930` ruled out), and `loop_cap_request` reads only
# the call and the shipped defaults, never the stored settings — so the answer,
# which the approval seal binds (`ExactToolApproval`), is the same when a card
# is minted and when it is claimed. Anything that goes wrong reading the call is
# "not recognised", the classification it had before.
def _replies_in_numbers(tool_name: str, content: Any) -> bool:
    """`B930`. Whether this call's reply is built by Pantheon from integers."""
    if tool_name != "manage_settings":
        return False
    try:
        return loop_cap_request(content) is not None
    except Exception:
        return False


def call_reaches(tool_name: Any) -> tuple[frozenset[ToolEffect], ...]:
    """`B1629` / `B1632`. Each set of effects one call of this tool can be
    classified with by `capabilities_for_action`, distinct, the registration
    first: an action a table names, a look, a read or a write of the person's
    own data, a deletion (`_ACTION_DESTRUCTIVE`), and a command that deletes
    or cannot be read (`B1622`) or reaches the network (`B1652`) — for
    `shell_with_login`, registered `network_egress` already, those are the
    same set, and for `host_shell`, registered `destructive` already, a
    command that reaches the network is the one more (`B1655`) — and a
    `write_file` over a file that was there before the run (`B1660`), and an
    `apply_patch` that deletes a file (`B1668`). Read in one
    place so the three questions below cannot disagree about what a call of
    the tool can be (`Law 7`).

    Two classifications are not listed, and neither is something a hire's
    table decides: a switch that widens the assistant's own reach is asked at
    every rung, whatever else says yes (`self_escalation_for`, `P7-02`), and
    an argument too deep to read is classified unknown, which a hire asks
    about and a sealed run never lifts (`B17`). A tool that is not known is
    its registration alone — already every effect (fail high).
    """
    base = capabilities_for_tool(tool_name)
    if not base.known or not isinstance(tool_name, str):
        return (base.effects,)
    bare = tool_name
    if tool_name.startswith("mcp__email__") and tool_name[len("mcp__email__"):] in BUILTIN_EMAIL_TOOLS:
        bare = tool_name[len("mcp__email__"):]
    reaches = [base.effects]
    if tool_name in _COMMAND_TOOLS:
        # `B1622`, `B1652`: a command that deletes, one that reaches the
        # network, and one that does both or cannot be read.
        reaches.append(base.effects | {ToolEffect.DESTRUCTIVE})
        reaches.append(base.effects | {ToolEffect.NETWORK_EGRESS})
        reaches.append(base.effects | {ToolEffect.DESTRUCTIVE, ToolEffect.NETWORK_EGRESS})
    if tool_name in _WRITE_TOOLS or tool_name in _PATCH_TOOLS:
        # `B1660`: a write over a file that was there before the run began;
        # `B1668`, a patch that deletes a file.
        reaches.append(base.effects | {ToolEffect.DESTRUCTIVE})
    if bare in _ACTION_CAPABILITIES:
        reaches += [c.effects for c in _ACTION_CAPABILITIES[bare].values()]
    if bare in _OBSERVE_ONLY_ACTIONS:
        reaches.append(_OBSERVE_ONLY_CAPABILITIES.effects)
    if bare in _ACTION_DESTRUCTIVE:
        reaches.append(base.effects | {ToolEffect.DESTRUCTIVE})
    if _PRIVATE_ACTION_READS.get(bare):
        reaches.append(frozenset({ToolEffect.READ_PRIVATE}))
        # An action neither of its tables names: `capabilities_for_action`'s
        # last line, a read and a write of the person's own data.
        reaches.append(frozenset({ToolEffect.READ_PRIVATE, ToolEffect.WRITE_PRIVATE}))
    return tuple(dict.fromkeys(reaches))


def least_reach(tool_name: Any) -> frozenset[ToolEffect]:
    """`B1619`. The effects **every** call of this tool carries, whatever its
    action or command — the tool's registration for a tool that does one
    thing, and what all its actions share for one that does several.

    A hire's `never` used to drop a tool from the run's kit when its widest
    reach held the effect, so `write_private: never` on Memory Auditor took
    `manage_memory` away whole and its reads went with its writes. A tool is
    dropped now only when this set holds a `never` — when no call of it could
    run — and every other call is answered by the gate one call at a time
    (`ToolRunSecurityContext._hire_decision_for`, which classifies the call by
    `capabilities_for_action`). An action a table does not name keeps the
    tool's whole registration there, so it is refused, never let through.
    """
    return frozenset.intersection(*call_reaches(tool_name))


def widest_reach(tool_name: Any) -> frozenset[ToolEffect]:
    """`B1629`. The effects **some** call of this tool can carry — what an
    agent's effects table must decide (`hires.manifest_effects`). The
    registration alone left out what only some calls carry: `destructive`
    from a shell's `rm` (`B1622`) or a `manage_*` delete, and `read_private`
    from a `manage_*` list, so a hire of Restore Drill, whose one command
    ends `rm -rf "$t"`, had no `destructive` row and no cautious default."""
    return frozenset().union(*call_reaches(tool_name))


def reach_left(tool_name: Any, never: Iterable[Any]) -> frozenset[ToolEffect]:
    """`B1632`. The effects the calls of this tool a hire's `never` leaves
    can carry: a call carrying any `never` is refused before anything else
    is asked (`_hire_decision_for`), so what it could have done is no part of
    what the run can do. With no `never`, `widest_reach`."""
    refused = {getattr(e, "value", e) for e in never or ()}
    left = [r for r in call_reaches(tool_name) if not ({e.value for e in r} & refused)]
    return frozenset().union(*left)


# ── `B1622` · a shell's deletion is a deletion ──────────────────────────────
#
# `bash` is registered `execute_code` and nothing else, and no table looked
# inside the command, so `_is_destructive_call('bash', 'rm -rf x')` was False:
# a hire's `destructive: ask`/`never` on a shell (Disk Janitor, File Converter,
# Photo Organiser…) did nothing, and Auto's one exception (`B1341`) let a shell
# `rm -rf` through. A command tool's call now carries `destructive` when
# `src/shell_reading.py` reads a deletion or an overwrite in it — or cannot
# read it, so a command whose effect is hidden is never called safe. That
# module names the adversary and where it stops; this only ever *adds* the
# effect, so every gate asks more for it and never less. The tool-level
# registration is untouched: a card for `ls` says what it said.
#
# `B1655`. `host_shell` too: registered `destructive` already, its command was
# never read for its reach, so a host `curl https://…` carried no
# `network_egress` and a hire's `never` for it did nothing. Its host runs it
# under `/bin/sh -c` (or `cmd.exe /c` on Windows, whose `powershell -Command …`
# this reader calls unreadable, so it is never called local). A background
# job is not a fifth: `manage_bg_jobs` starts nothing — its actions are
# `list`, `output` and `kill` — and a job is started by a `bash` call whose
# first line is `#!bg`, read here as every `bash` call is.
_COMMAND_TOOLS = frozenset({"bash", "shell_with_login", "python", "host_shell"})


def _command_text(tool_name: str, content: Any) -> str | None:
    """The command or code a call runs, read as its executor reads it."""
    if tool_name == "shell_with_login":
        from src.agent_tools.login_shell_tools import parse_args
        args, problem = parse_args(content)
        # A call the tool refuses runs nothing.
        return None if problem else str(args.get("command") or "")
    if tool_name == "host_shell":
        from src.agent_tools.host_tools import command_of
        return command_of(content)
    if isinstance(content, Mapping):
        content = content.get("command") or content.get("cmd") or content.get("code") or ""
    return content if isinstance(content, str) else None


@functools.lru_cache(maxsize=512)
def _command_reading(tool_name: str, text: str) -> tuple:
    """`(why it destroys, why it reaches the network, what it writes over)`,
    from one reading — the third (`B1669`) is the reading's `writes` and
    `chdir` findings, which only the run can answer (`src/run_files.py`)."""
    from src.shell_reading import python_findings, read_shell, readings, writes_of
    findings = python_findings(text) if tool_name == "python" else read_shell(text)
    return (*readings(findings), writes_of(findings))


def _command_readings(tool_name: Any, content: Any) -> tuple[str | None, str | None]:
    if tool_name not in _COMMAND_TOOLS:
        return None, None
    text = _command_text(tool_name, content)
    if not text or not text.strip():
        return None, None
    return _command_reading(tool_name, text)[:2]


def command_writes(tool_name: Any, content: Any) -> tuple:
    """`B1669`. What this command call writes over and where it moves, as the
    reader names them (`shell_reading.writes_of`), or `()`."""
    if tool_name not in _COMMAND_TOOLS:
        return ()
    text = _command_text(tool_name, content)
    if not text or not text.strip():
        return ()
    return _command_reading(tool_name, text)[2]


def command_destroys(tool_name: Any, content: Any) -> str | None:
    """`B1622`. Why this command call carries `destructive` — what it deletes,
    or why it cannot be read — or `None`. `None` for every other tool, and for
    a call with no command (the tool-level question)."""
    return _command_readings(tool_name, content)[0]


def command_reaches(tool_name: Any, content: Any) -> str | None:
    """`B1652`. Why this command call carries `network_egress` — what in it
    reaches another machine, or why it cannot be read — or `None`, as
    `command_destroys` answers for `destructive`."""
    return _command_readings(tool_name, content)[1]


# ── `B1669` · a shell writing over a file that was there ────────────────────
#
# `bash 'echo x > notes.md'` was `execute_code` alone while `write_file
# notes.md` over the same file carried `destructive` (`B1660`): under the
# owner's principle (`D-2026-10-29-02` §1), replacing a file that was there
# before the run is destructive whatever tool does it. The reader names what a
# command writes over (`command_writes`), and the run decides whether it was
# there (`src/run_files.command_replaces`, which says where it looks and where
# it stops). `host_shell` is registered `destructive` already and runs on
# another machine, so it is not looked at.
_REPLACE_READ_TOOLS = frozenset({"bash", "python", "shell_with_login"})


def command_replaces(tool_name: Any, content: Any, files: Any = None) -> str | None:
    """`B1669`. Why this command call carries `destructive` for a file it
    writes over — the file, or why it cannot be known whether it was there —
    or `None`. `files` is the run's record (`src/run_files.RunFiles`)."""
    if tool_name not in _REPLACE_READ_TOOLS:
        return None
    writes = command_writes(tool_name, content)
    if not writes:
        return None
    from src.run_files import command_replaces as replaces_in_run
    return replaces_in_run(tool_name, writes, content, files)


# ── `B1660` · writing over a file that was there is an overwrite ────────────
#
# A `write_file` whose path held a file before the run began carries
# `destructive` as well as `write_workspace` (`D-2026-10-29-02` §1), as a shell
# `mv` over a file does (`B1622`) — so a hire's `destructive: ask`/`never` and
# Auto's one exception cover it. A file the same run made is a plain write.
# Whether the path was there is a fact about the run as well as the call, so
# the run's record (`src/run_files.RunFiles`, on `ToolRunSecurityContext.files`)
# is handed in; `src/run_files.py` says what it knows, where it stops and why.
# Like `B1622`, this only ever adds the effect, and the registration is
# untouched: a card for a new file says what it said.
_WRITE_TOOLS = frozenset({"write_file"})


def write_replaces(tool_name: Any, content: Any, files: Any = None) -> str | None:
    """`B1660`. Why this `write_file` call carries `destructive` — the file it
    replaces, or why that cannot be known — or `None`. `None` for every other
    tool."""
    if tool_name not in _WRITE_TOOLS:
        return None
    from src.run_files import replaces
    return replaces(content, files)


# ── `B1668` · a patch's deletion is a deletion ──────────────────────────────
#
# `apply_patch` is registered `write_workspace`, so a patch whose `*** Delete
# File: notes.md` removes the file (`filesystem_tools._run_patch`,
# `files.remove`) carried no `destructive`: a hire's `destructive:
# ask`/`never` and Auto's one exception (`B1341`) never covered it. Now a patch
# that deletes a file carries `destructive` — outright, as a shell's `rm` does
# (`B1622`), whether or not the run made the file: deleting is not writing
# over, and `D-2026-10-29-02` §1's "the run's own draft" is about rewriting
# one. The patch is read as the tool reads it (`_patch_text`,
# `_parse_agent_patch`); one the tool refuses deletes nothing. Its other
# operations stay what they were: `*** Add File:` is refused when the path is
# there, a move is refused, and `*** Update File:` edits as `edit_file` does.
_PATCH_TOOLS = frozenset({"apply_patch"})


def patch_deletes(tool_name: Any, content: Any) -> str | None:
    """`B1668`. Why this `apply_patch` call carries `destructive` — the files
    its patch deletes — or `None`. `None` for every other tool."""
    if tool_name not in _PATCH_TOOLS:
        return None
    if isinstance(content, Mapping):
        content = json.dumps(dict(content))
    if not isinstance(content, str):
        return None
    from src.agent_tools.filesystem_tools import _parse_agent_patch, _patch_text
    try:
        operations = _parse_agent_patch(_patch_text(content))
    except (ValueError, TypeError):
        return None                 # the tool refuses it, and deletes nothing
    gone = [op["path"] for op in operations if op.get("kind") == "delete"]
    return f"apply_patch deletes {', '.join(dict.fromkeys(gone))}" if gone else None


# ── `B1670` · one set of words for what a call destroys ─────────────────────
#
# A hire's card said what in the call was destructive — *(rm deletes files)*,
# *(write_file replaces notes.md, which was there before this run began)* —
# and the card the ladder makes (a chat that has read outside data, in Auto or
# not, or a rung that asks) said only *It has read outside data this turn, so
# this needs a yes from you*: the person was asked to approve a deletion
# without being told it was one (`Law 15`). Both now take their words from
# here, so the two cards cannot word one call two ways (`Law 7`).

def call_destroys(tool_name: Any, content: Any, files: Any = None) -> str | None:
    """Why this call carries `destructive` beyond its tool's registration, in
    the words every card uses: a command's deletion, or that it cannot be read
    (`B1622`); a file a command writes over — a `>`, or a program told to
    write over its output (`B1669`, `B1680`); a `write_file` over a file that
    was there, not an append (`B1660`, `B1672`); a patch's deletion (`B1668`).
    `None` when nothing in the call adds it."""
    return (command_destroys(tool_name, content) or command_replaces(tool_name, content, files)
            or write_replaces(tool_name, content, files) or patch_deletes(tool_name, content))


def call_reasons(tool_name: Any, content: Any, effects: Iterable[Any], files: Any = None) -> str:
    """`B1670`. What in this call carries each of `effects`, as the words a
    card adds after its sentence — `" (rm deletes files)"` — or `""` when
    nothing in the call is what carries them (the tool's registration is).
    `destructive` (`call_destroys`) and `network_egress` (`B1652`,
    `command_reaches`) are the two a call's arguments add."""
    named = {getattr(e, "value", e) for e in effects or ()}
    said = []
    if ToolEffect.DESTRUCTIVE.value in named:
        said.append(call_destroys(tool_name, content, files))
    if ToolEffect.NETWORK_EGRESS.value in named:
        said.append(command_reaches(tool_name, content))
    said = [w for w in said if w]
    return f" ({'; '.join(dict.fromkeys(said))})" if said else ""


def _is_destructive_call(tool_name: Any, content: Any, files: Any = None) -> bool:
    """Does this exact call carry `DESTRUCTIVE`, arguments included?

    `B1341` / `D-2026-10-17-01`. One statement of Auto's single exception, so
    the gate does not re-derive it (`Law 7`). It asks
    `capabilities_for_action` rather than the tool-level registration, because
    `_ACTION_DESTRUCTIVE` makes destructiveness a property of the action for
    nine multiplexed tools — `manage_memory action=delete` is destructive and
    `action=add` is not, and a tool-level check would miss every one of them —
    and `B1622` makes it a property of the command for a shell: `bash rm -rf`
    is destructive and `bash ls` is not — and `B1660` of the path and the run
    for a `write_file` (`files`, the run's record).

    Fails **closed** on an unreadable call: a call whose classification cannot
    be resolved is treated as destructive, so Auto asks. That is the safe
    direction for a one-line exception whose whole purpose is that the person
    sees an irreversible step before it happens.
    """
    try:
        return ToolEffect.DESTRUCTIVE in capabilities_for_action(
            tool_name, content, files=files).effects
    except Exception:  # noqa: BLE001
        logger.debug(
            "destructive check unreadable for %r; asking rather than auto-approving",
            tool_name, exc_info=True,
        )
        return True


def capabilities_for_action(tool_name: Any, content: Any, *, files: Any = None) -> ToolCapabilities:
    """Classify a sealed multiplexed action; ambiguous actions fail high.

    `files` (`B1660`) is the run's record of the files it made
    (`src/run_files.RunFiles`): whether a `write_file` replaces a file that
    was there before the run began — and `B1669`, whether a command's `>`,
    `tee` or `cp` does, and where its shell starts. Every surface that classifies one call of
    a run — the gate, the card, its seal, the step's effect keys — hands in the
    same record, so they cannot disagree; without one, nothing is known to be
    the run's own."""
    base = capabilities_for_tool(tool_name)
    if not isinstance(tool_name, str):
        return base
    if _replies_in_numbers(tool_name, content):
        base = ToolCapabilities(base.effects, ResultIntegrity.SYSTEM, known=base.known)

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

    # `B1622`. A shell's or Python's call: destructive when its command says
    # so, or cannot be read; `B1652`, reaching the network the same way —
    # `B1655`, a host command's too; otherwise exactly the tool's registration.
    if tool_name in _COMMAND_TOOLS:
        destroys, reaches = _command_readings(tool_name, content)
        if destroys is None:
            # `B1669`: or when it writes over a file that was there before the
            # run began — or whether one was cannot be known.
            destroys = command_replaces(tool_name, content, files)
        added = ({ToolEffect.DESTRUCTIVE} if destroys is not None else set()) | (
            {ToolEffect.NETWORK_EGRESS} if reaches is not None else set())
        if not added:
            return base
        return ToolCapabilities(
            frozenset(base.effects | added),
            base.result_integrity,
            known=base.known,
        )

    # `B1660`. A write over a file that was there before the run began;
    # `B1668`, a patch that deletes a file.
    if tool_name in _WRITE_TOOLS or tool_name in _PATCH_TOOLS:
        if (write_replaces(tool_name, content, files) or patch_deletes(tool_name, content)) is None:
            return base
        return ToolCapabilities(
            frozenset(base.effects | {ToolEffect.DESTRUCTIVE}),
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
    if tool_name in _ACTION_CAPABILITIES:
        return _ACTION_CAPABILITIES[tool_name].get(action, base)
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
# because `.pantheon/design/pantheon-v10.html`'s `#rungs` draws five rungs and only
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
# whether an order exists among the three inherited rungs, because callers
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


#: `D-2026-10-24-01`. In a sealed hire's run after outside content, an action
#: whose every effect is one of these runs without the floor's question.
SEALED_LIFTED_EFFECTS = frozenset({"read_workspace", "read_private", "write_workspace", "write_private"})
#: ...unless the tool writes what a later run will trust. These keep the floor.
LAUNDERING_TOOLS = frozenset({"manage_memory", "manage_skills", "manage_tasks"})
#: `D-2026-10-24-02`. In a blind hire's run after outside content, an action
#: whose every effect is one of these — reading the public web — runs.
BLIND_LIFTED_EFFECTS = frozenset({"read_public", "brokered_network_read", "network_egress"})


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
    # `D-2026-10-09-01` §2. True on an `allowed=True` decision that a stop
    # condition would otherwise have refused, in a chat set to **Auto**. It is
    # how the run records that it ran without asking: `src/agent_loop.py` puts
    # it on the `tool_start` frame and on the persisted `tool_event`, beside
    # the six effect keys, so a live card and a reloaded one both say so.
    #
    # An enum would be wrong here: this is not "which mode is the chat in", it
    # is "did this action skip a card it was owed". A step Auto never touched
    # — an untainted run at the default rung — carries False, which is the
    # truth about that step (`Law 10`).
    #
    # `tripped_effects` is populated on these decisions too, so the record
    # names what the person was not asked about rather than only that they
    # were not asked. `reason` is NOT: it is the refusal sentence and every
    # reader of it is behind `if not decision.allowed`.
    auto_approved: bool = False
    # `D-2026-10-29-01` §1 (`B1605`). True on an `allowed=True` decision that
    # the post-external gate would otherwise have refused, in a hired agent's
    # run whose own effects table sets every effect of the action to *allow*
    # (`ToolRunSecurityContext._allowed_hire_decision_for`). Recorded exactly
    # as `auto_approved` is — on the `tool_start`, the `tool_output`, the
    # persisted `tool_event` and, for a hire, the run's step log — and only on
    # the steps it changed, so a run says which steps ran without a person
    # seeing them after outside content came in. `tripped_effects` rides on it
    # as on Auto's, naming what nobody was asked about.
    hire_approved: bool = False


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
    # `D-2026-10-09-01` §2. This chat is set to **Auto**: a stop condition does
    # not raise a card, the step runs, and the decision says it ran under Auto.
    # Resolved once per run by the caller, from the chat's own row
    # (`src/approval_mode.mode_for`) — this module reads no setting and no
    # database, exactly as it reads no rung setting (`resolve_trust_rung` is
    # the caller's).
    #
    # It is one flag and not a rung, because it is not a rung: the ladder is a
    # nest of stop-condition sets and `validate_trust_ladder` enforces that
    # every rung holds `FLOOR_STOP_CONDITIONS`. A fourth rung that dropped
    # `AFTER_UNTRUSTED` would make the ladder not a ladder and would lift the
    # floor for every chat at once. Auto sits beside the ladder, per chat, and
    # the ladder is unchanged — which is also what makes "turn Auto off and the
    # chat is exactly as it was" true by construction.
    auto_approved: bool = False
    # `P24-07`. A hired agent's effects table, from its run's `ToolPolicy`:
    # an action carrying one of `hire_never_effects` is refused and no
    # approval lifts it; one carrying `hire_ask_effects` asks. Both empty for
    # every run that is not an agent's, which is every existing caller.
    hire_ask_effects: frozenset = frozenset()
    hire_never_effects: frozenset = frozenset()
    # `D-2026-10-24-01`. A hired agent whose whole kit cannot carry data out
    # of the install. Read by `_sealed_hire_decision_for`; False for every run
    # that is not such an agent's, which is every existing caller.
    hire_sealed: bool = False
    # `D-2026-10-24-02`. A hired agent whose whole kit cannot read the
    # person's private data. False for every other run.
    hire_blind: bool = False
    # `D-2026-10-29-01` §1 (`B1605`). The effects a hired agent's table sets
    # to *allow* — the third side of `hire_ask_effects` / `hire_never_effects`,
    # read only by `_allowed_hire_decision_for` — and whether the lift that
    # reads them is on for this run: True only for a hired agent's run whose
    # person holds `can_auto_approve`, resolved once per run by the caller
    # (`src.approval_mode.hire_lift_for`), as `auto_approved` is. This module
    # reads no privilege. Both empty/False for every run that is not such a
    # hire's — every chat, every task, every summoned agent — so the gate
    # answers those exactly as before.
    hire_allow_effects: frozenset = frozenset()
    hire_allow_after_outside: bool = False
    # `P27-08`. `(tool_name, content) -> sentence | None`, supplied by the
    # caller (`src/vault.asks_before`, bound to the run's owner and chat): a
    # vault login this call signs in with is set to ask — each time, or once
    # per chat. A callable for the reason `allow_rule_lookup` is one: this
    # module reads no database. `None` for every caller that does not wire it.
    vault_use_lookup: Any = None
    # `B1660`. The run's record of the files it made (`src/run_files.RunFiles`),
    # the same object each of its tool calls notes into: a `write_file` over a
    # file that was there before the run began is `destructive`, and one over a
    # file this run made is not. `None` for every caller that does not wire it
    # — nothing is then known to be the run's own (the cautious reading).
    files: Any = None

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
        if self.gate_is_armed or self_escalation_for(tool_name, content) is not None:
            return True
        # `P27-08`. A login set to ask asks in a clean run too, so its card
        # has to be answerable there (`B1431`'s reason, for a login).
        if self._vault_use_decision_for(tool_name, content) is not None:
            return True
        # `B1431` (`P24-08`). A hired agent's `ask` effect asks in a clean run
        # too, so its card has to be answerable there: asked of the run alone,
        # approving it answered "requires an armed run security context" and
        # the action never ran — `P7-03`'s incident a third time. A `never` is
        # not a question, and no card lifts it.
        hired = self._hire_decision_for(tool_name, content)
        return hired is not None and hired.classification != TOOL_CLASSIFICATION_UNAVAILABLE

    def decision_for(self, tool_name: Any, content: Any = None) -> ToolGateDecision:
        """Whether this action runs, or waits for the person.

        `D-2026-10-09-01` §2 wraps the ladder rather than entering it: B70's
        refusal is asked first and is never lifted, then the ladder answers
        exactly as it always has, and only then does a chat in **Auto** turn a
        refusal into a run. Three properties follow from that order and each
        one is a case in
        `tests/test_a_chat_decides_whether_it_asks.py`:

          * a tool a bearer token may not call is still refused in Auto, with
            the same sentence and `not_available` (`FORBIDDEN.md` Part 2);
          * what Auto allows is exactly what Manual would have refused, so
            turning it off restores the chat byte-for-byte;
          * the effects the gate tripped on travel on the allowed decision, so
            the run can record what the person was not asked about.
        """
        if self.delegated_credential and is_delegated_credential_blocked_tool(tool_name):
            # B70. First, because no approval lifts it and Auto is not an
            # approval. `src/approval_mode.mode_for` already answers MANUAL for
            # a delegated run, so this is the second of two independent
            # controls rather than the only one.
            return ToolGateDecision(
                False,
                # `B1382`: one copy of the sentence, shared with the loop.
                delegated_credential_refusal(tool_name),
                classification=TOOL_CLASSIFICATION_UNAVAILABLE,
            )
        vault = self._vault_use_decision_for(tool_name, content)
        if vault is not None:
            # `P27-08`. Before a hire's table and before Auto: how a login may
            # be used is the person's standing answer about that login, and
            # Auto is not that answer. An approved action never reaches here —
            # the exact grant is claimed by the dispatcher instead of asking.
            return vault
        hired = self._hire_decision_for(tool_name, content)
        if hired is None:
            hired = self._sealed_hire_decision_for(tool_name, content)
        if hired is None:
            # `D-2026-10-29-01` §1. After the table's `ask` and `never` (asked
            # just above, so neither is lifted) and after the sealed and blind
            # lifts (a step they run is not this amendment's to record).
            hired = self._allowed_hire_decision_for(tool_name, content)
        if hired is not None:
            # `P24-07`. Before the ladder and before Auto: what a hire says
            # about an effect is the person's standing answer about this agent.
            # An approved action never reaches here — an exact grant is claimed
            # by the dispatcher instead of asking (`tool_execution`).
            return hired
        decision = self._ladder_decision_for(tool_name, content)
        if decision.allowed or not self.auto_approved:
            return decision

        # `B1341` / `D-2026-10-17-01`: **Auto has exactly one exception, and it
        # is `DESTRUCTIVE`.**
        #
        # This block used to carry the opposite note — *"There is no exception
        # list here on purpose — a destructive effect runs too. If one should
        # not, that is a row for the owner, not a quiet `if`"* — and
        # `D-2026-10-09-01` §2 shipped Auto that way deliberately, on the
        # argument that a mode which keeps some asks is a mode nobody can
        # describe in one sentence. The owner has now ruled the other way,
        # because there **is** a one-sentence description: *Auto runs
        # everything without asking, except what cannot be undone.*
        #
        # What decides it is the asymmetry rather than a general preference for
        # caution. The exception costs one extra card on a rare action; its
        # absence costs an unrecoverable loss when an injected instruction
        # lands in a chat that was set to Auto weeks ago and forgotten.
        # `DESTRUCTIVE` is the only class whose blast radius is not bounded by
        # the action's own arguments and whose result cannot be undone from
        # inside Pantheon.
        #
        # Asked of `capabilities_for_action`, not of `decision.tripped_effects`
        # (`Law 7`). The tripped list is built differently on each refusal path,
        # and destructiveness is frequently a property of the **arguments**
        # rather than the tool: `_ACTION_DESTRUCTIVE` is why
        # `manage_memory action=delete` and `bulk_email action=delete` are
        # destructive while the same tools' other actions are not. A check
        # against the string list would have auto-approved exactly those.
        #
        # This is still not a second rung and moves no control: it narrows one
        # opt-out, in the direction of asking more rather than less, and a chat
        # that is not set to Auto is unaffected in either direction.
        if _is_destructive_call(tool_name, content, self.files):
            logger.info(
                "[approval] %s is destructive; asking even though this chat is "
                "set to Auto (B1341)", tool_name,
            )
            return decision
        #
        # Nothing about the refusal is discarded except the refusal: the
        # effects that tripped and how well the tool is understood ride along
        # so the record names them, and `reason` is dropped because it is the
        # refusal sentence and the step is not being refused.
        logger.info(
            "[approval] auto-approved %s in a chat set to Auto (would have asked: %s)",
            tool_name, decision.reason,
        )
        return ToolGateDecision(
            True,
            None,
            tripped_effects=decision.tripped_effects,
            classification=decision.classification,
            auto_approved=True,
        )

    def _vault_use_decision_for(self, tool_name: Any, content: Any = None):
        """`P27-08`. A card for a vault login set to ask, or `None`."""
        if self.vault_use_lookup is None or tool_name not in ("agent_browser", "shell_with_login"):
            return None
        try:
            sentence = self.vault_use_lookup(tool_name, content)
        except Exception:  # noqa: BLE001 — a lookup that fails asks; it never lets a login through unasked
            sentence = "The vault could not say how this login may be used, so this asks."
        if not sentence:
            return None
        capabilities = capabilities_for_action(tool_name, content, files=self.files)
        return ToolGateDecision(
            False,
            f"{sentence} '{tool_name}' waits for your yes.",
            tripped_effects=tuple(describe_effects(capabilities.effects).get("effects", ())),
            classification=TOOL_CLASSIFICATION_RECOGNISED,
        )

    def _sealed_hire_decision_for(self, tool_name: Any, content: Any = None):
        """`D-2026-10-24-01` — the owner's amendment to the post-external gate,
        for one kind of run only.

        A hired agent runs with a fixed kit, set before the run starts. When
        nothing in that kit can carry data out of the install — no network,
        no fetch or search, no sending, no shell, no settings
        (`src.agents.runtime.SEALING_EFFECTS`) — reading more of the person's
        own data after outside content arrived has nowhere to leak to, so it
        does not ask. Writes the hire's table allows run too, except the
        three that a *later* run would trust (`LAUNDERING_TOOLS`: memory,
        skills, scheduled tasks), which keep the floor — the laundering path
        `D-2026-10-09-01` gated at the write (their reads are lifted like any
        other). Everything not covered here goes
        to the ladder exactly as before; with `hire_sealed` False (every run
        that is not such an agent's) this answers `None`."""
        if not ((self.hire_sealed or self.hire_blind) and self.external_untrusted_context_seen):
            return None
        if self.hire_blind:
            # `D-2026-10-24-02`, the mirror: nothing private in the run to
            # leak, so reading more of the public web does not ask. Writes,
            # sending and everything else go to the ladder as before.
            caps = capabilities_for_action(tool_name, content, files=self.files)
            effs = {effect.value for effect in caps.effects}
            if caps.known and effs and effs <= BLIND_LIFTED_EFFECTS:
                return ToolGateDecision(True, None)
        if not self.hire_sealed:
            return None
        bare = tool_name[len("mcp__email__"):] if isinstance(tool_name, str) and tool_name.startswith(
            "mcp__email__") else tool_name
        capabilities = capabilities_for_action(tool_name, content, files=self.files)
        effects = {effect.value for effect in capabilities.effects}
        if not capabilities.known or not effects or not effects <= SEALED_LIFTED_EFFECTS:
            return None
        if bare in LAUNDERING_TOOLS and effects - {"read_workspace", "read_private"}:
            return None
        return ToolGateDecision(True, None)

    def _allowed_hire_decision_for(self, tool_name: Any, content: Any = None):
        """`D-2026-10-29-01` §1 (`B1605`) — the third amendment of the
        post-external gate, for one kind of run only.

        A hired agent whose kit both reads the person's data and reaches
        outside stopped at almost every step after its first outside read —
        Newsletter Writer six times in one case — so a scheduled one could not
        finish unattended. The owner's ruling: *hire approval covers it*. In a
        hired agent's run, after outside content, an action **every** effect of
        which the hire's own table sets to *allow* is answered as it would be
        had nothing come in. What is lifted is whether a person is asked, never
        what is validated — the rung, the tool policy, ownership and every
        validator still answer as before.

        **The adversary (`Law 17`)** is the one the gate exists for: the author
        of a page, a mail or a tool result the agent reads, writing text that
        steers it. With this lift that author can steer the agent's next steps
        *within what the hire allows* — read more of the person's data, write
        it, send it, if the person set those to allow — and nobody sees the
        step first. That cost was put to the owner and accepted
        (`D-2026-10-29-01`); it is why each such step is recorded
        (`hire_approved`), why the hire form says it before the hire, and why
        three things the hire's table does not decide keep the gate:

          * **a self-escalation asks every time** (`D-2026-10-25-01`,
            `StopCondition.MORE_REACH`) — more reach is the person's to give,
            not an effect a hire can pre-approve;
          * **a write to memory, skills or scheduled tasks** after outside
            content keeps the gate (`LAUNDERING_TOOLS`, as for a sealed kit,
            `D-2026-10-24-01`) — the injected text would outlive the run and
            reach every later chat; their reads are lifted like any other;
          * **only a hire whose person holds `can_auto_approve`** — the people
            Auto is held to (`hire_allow_after_outside`, resolved by the
            caller); anyone else's hire behaves exactly as before.

        And `ask` still asks, `never` is still refused: `_hire_decision_for`
        answers before this and its answer is final. An unrecognised action is
        never lifted (its effects are a guess). "As it would be had nothing
        come in" is asked of the ladder itself (`_ladder_decision_for` with
        `tainted=False`), so a stricter rung that asks in a clean chat still
        asks here — the lift can never make a rung ask *less* after outside
        content than before it, the inversion `P7-03`'s refutation found.
        `None` means "not this amendment's": the ladder answers as before."""
        if not (self.hire_allow_after_outside and self.external_untrusted_context_seen):
            return None
        if self_escalation_for(tool_name, content) is not None:
            return None
        capabilities = capabilities_for_action(tool_name, content, files=self.files)
        effects = {effect.value for effect in capabilities.effects}
        if not capabilities.known or not effects or not effects <= set(self.hire_allow_effects):
            return None
        bare = tool_name[len("mcp__email__"):] if isinstance(tool_name, str) and tool_name.startswith(
            "mcp__email__") else tool_name
        if bare in LAUNDERING_TOOLS and effects - {"read_workspace", "read_private"}:
            return None
        gated = self._ladder_decision_for(tool_name, content)
        if gated.allowed:
            return None   # the ladder runs it anyway: nothing was lifted, nothing to record
        if not self._ladder_decision_for(tool_name, content, tainted=False).allowed:
            return None   # the rung asks for it in a clean run too: that question stands
        logger.info(
            "[approval] %s ran unasked after outside content: the hire allows %s "
            "(D-2026-10-29-01)", tool_name, ", ".join(sorted(effects)),
        )
        return ToolGateDecision(
            True,
            None,
            tripped_effects=gated.tripped_effects,
            classification=gated.classification,
            hire_approved=True,
        )

    def _hire_decision_for(self, tool_name: Any, content: Any = None):
        """`P24-07`. A hired agent's effects table, or `None` when it has
        nothing to say about this action (which is every non-agent run)."""
        if not (self.hire_ask_effects or self.hire_never_effects):
            return None
        capabilities = capabilities_for_action(tool_name, content, files=self.files)
        effects = {effect.value for effect in capabilities.effects}
        never = effects & set(self.hire_never_effects)
        # `B1622`. A command's deletion is named, so the person reads what in
        # it is destructive rather than only that something is; `B1652`, and
        # what in it reaches the network; `B1660`, and the file a write
        # replaces — in the words the ladder's card uses too (`B1670`).
        def because(named):
            return call_reasons(tool_name, content, named, self.files)
        if never:
            return ToolGateDecision(
                False,
                (f"This agent's hire never allows {', '.join(sorted(never))}, so "
                 f"'{tool_name}' was not run{because(never)}. "
                 f"Change the hire's effects in Agents to allow it."),
                tripped_effects=tuple(describe_effects(
                    frozenset(e for e in capabilities.effects if e.value in never)).get("effects", ())),
                classification=TOOL_CLASSIFICATION_UNAVAILABLE,
            )
        ask = effects & set(self.hire_ask_effects)
        if ask or not capabilities.known:
            tripped = frozenset(e for e in capabilities.effects if e.value in ask)
            return ToolGateDecision(
                False,
                (f"This agent's hire asks before {', '.join(sorted(ask)) or 'an action it cannot classify'}: "
                 f"'{tool_name}' waits for your yes{because(ask)}."),
                tripped_effects=tuple(describe_effects(tripped).get("effects", ())),
                classification=(TOOL_CLASSIFICATION_RECOGNISED if capabilities.known
                                else TOOL_CLASSIFICATION_UNRECOGNISED),
            )
        return None

    def _ladder_decision_for(self, tool_name: Any, content: Any = None, *,
                             tainted: bool | None = None) -> ToolGateDecision:
        """The trust ladder's own answer — `P7-02`, `P7-03`, `P7-04`, `P7-13`.

        Split out of `decision_for` by `D-2026-10-09-01` §2 and otherwise
        unchanged, so "what does Manual approve do" has one answer and Auto is
        visibly a wrapper around it rather than a second gate (`Law 7`).

        `tainted` is whether outside content has come in, and defaults to the
        run's own answer. `D-2026-10-29-01` asks it once with `False` — what
        this rung answers the same action in a clean run — so a hire's lift is
        the ladder's own clean answer, not a second copy of it.
        """
        if tainted is None:
            tainted = self.external_untrusted_context_seen
        # `P7-13`. Every question below is asked of this set — the rung's stop
        # conditions from `TRUST_LADDER` — and never of the rung's name, so the
        # ladder that says which rung is stricter is the gate that enforces it.
        asks = stop_conditions(self.rung)
        # `P7-02`. Before the bypass and before the untainted exit, because
        # both exist to let the assistant *act* without asking, and neither is
        # a person choosing to give it more to act with. Below B70, whose
        # refusal no approval lifts — this one an approval does, once. (B70 is
        # asked by `decision_for` before it calls this, so "below" still holds:
        # `D-2026-10-09-01` §2 only moved the line it is written on.)
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
        if not tainted and not asks_untainted:
            return ToolGateDecision(True)

        capabilities = capabilities_for_action(tool_name, content, files=self.files)
        # `B19`. Tainted runs keep the full set, byte for byte. Only the
        # untainted strict rungs narrow, and only by `read_private`.
        gate_effects = (
            POST_EXTERNAL_BLOCKED_EFFECTS
            if tainted
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
            and not tainted
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
        if tainted:
            why = "External untrusted context has already influenced this run. "
        else:
            # The rung asked for this, and the sentence has to say so — the old
            # one blamed untrusted context, which on this path has not happened.
            why = "This conversation is set to confirm every effectful action. "
        # `B1670`. And what in the call carries what tripped it — *(rm deletes
        # files)* — in the words a hire's card uses, so the card made in a
        # chat that has read outside data, Auto's among them, says what the
        # person is approving (`tool_approvals.card_words` keeps it).
        named = call_reasons(tool_name, content, blocked_effects, self.files) if capabilities.known else ""
        return ToolGateDecision(
            False,
            (
                f"{why}"
                f"Tool '{tool_name}' requires a separate user-authorized action "
                f"because it can cause {effects}{named}."
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


def authored_call_context(call: Any, *, rung: Any, run_id: str,
                          allow_rule_lookup: Any = None) -> ToolRunSecurityContext:
    """`P22-17` (`D-2026-10-01-05` §4). ONE deterministic workflow step's call,
    whose tool and every `never` slot the author fixed at save and whose
    `value` slots `workflow_slots.render_call` filled at run — proven by the
    type: anything that is not a `RenderedCall` raises `TypeError`. No model
    chose this action, so the taint the gate exists for (untrusted text
    choosing a privileged action) is absent by construction.

    **The adversary (`Law 17`):** whoever writes an inbound mail or webhook
    body — and, through a model's output, whoever steered it. Their bytes may
    reach `value` slots, as JSON values `render_call` placed; they never choose
    the tool, the destination, a recipient, a URL, a host or a command, which
    the author typed and the document rule refuses a reference in.

    Starts untainted, with NO standing approval (`approval_gate_bypassed`
    False, whatever any other step was allowed) and no allow rules unless the
    rung consults them, at the owner's rung (`apply_role_floor(
    resolve_trust_rung(), owner)`, the caller's — this module reads no
    setting). Nothing in `decision_for`, `POST_EXTERNAL_BLOCKED_EFFECTS` or
    `observe_tool_result` changes (`FORBIDDEN.md` Part 2): at the default rung
    an untainted context is allowed; at a stricter one the person asked to be
    asked, and the step parks on a card. A step's RESULT stays untrusted — a
    Prompt step that reads it is wrapped and gated exactly as today.
    """
    from src.workflow_slots import RenderedCall

    if not isinstance(call, RenderedCall):
        raise TypeError(
            "authored_call_context takes a workflow_slots.RenderedCall — a call "
            "the author fixed and render_call filled — and nothing else")
    run_rung = coerce_trust_rung(rung)
    return ToolRunSecurityContext(
        external_untrusted_context_seen=False,
        approval_gate_bypassed=False,
        delegated_credential=False,
        rung=run_rung,
        run_id=str(run_id),
        allow_rule_lookup=(allow_rule_lookup if rung_consults_allow_rules(run_rung)
                           else None),
    )


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
