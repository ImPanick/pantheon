# SPDX-License-Identifier: AGPL-3.0-or-later
"""Per-turn tool policy composition for agent execution."""

from __future__ import annotations

import logging
import re
from dataclasses import dataclass, field
from types import MappingProxyType
from typing import Iterable, Mapping, Optional, Set, Tuple

_logger = logging.getLogger(__name__)


GUIDE_ONLY_DIRECTIVE = (
    "## GUIDE-ONLY MODE - TOOL POLICY\n"
    "The latest user turn explicitly forbids tool use. Do not call tools, do not "
    "run shell commands, and do not inspect local files or the environment. "
    "Respond in normal text by guiding the user or asking them to paste the "
    "output they will produce locally."
)

# `P2-14`. What the model is told when the turn asked to be consulted. It is
# not a disarm: the tools are there, the gate in front of them is armed, and
# saying so is what stops the model treating the run as guide-only on its own
# initiative.
CONFIRM_TOOLS_DIRECTIVE = (
    "## CONFIRM-BEFORE-TOOLS - TOOL POLICY\n"
    "The latest user turn asked to be consulted before you use tools. Tools "
    "remain available. Every tool call in this run raises an approval card the "
    "user must click before the action runs, so say what you intend to do and "
    "why before calling it, and prefer one clearly-explained call to several "
    "exploratory ones."
)

WEB_TOOL_NAMES = frozenset({"web_search", "web_fetch"})


def tool_toggle_enabled(value: object) -> bool:
    """Return true only for explicit true-like tool toggle values.

    flag-spelling: `B97` holds this one. It is an HTTP request field, so the
    shared rule at that boundary is `env_flags.request_flag` — but this toggle
    *grants tools*, and widening it would turn `allow_web_search=1` from denied
    into granted for any caller already sending it. The same hold, for the same
    reason, as `allow_bash` in `routes/chat_routes.py`: honouring an intent and
    loosening a gate are not the same act, and our own composer sends the
    literal `'true'`/`'false'` so nothing the product itself does is affected
    either way. Named here rather than left as an unexplained `== "true"` —
    `B97` found this and `routes/model_routes._truthy` as two private
    half-helpers of one boundary, neither reachable from the other's callers.
    """

    return str(value).lower() == "true"


def tool_toggle_explicitly_denied(value: object) -> bool:
    """Return true when a caller explicitly supplied a non-true toggle value."""

    return value is not None and not tool_toggle_enabled(value)


def is_web_search_explicitly_denied(allow_web_search: object) -> bool:
    """Whether the web-search agent toggle was explicitly set to false."""

    return tool_toggle_explicitly_denied(allow_web_search)


def web_search_enabled_for_turn(allow_web_search: object, use_web: object = None) -> bool:
    """Return true only when this request explicitly enables web search.

    Agent mode sends ``allow_web_search``; chat-mode pre-search sends
    ``use_web``. If both are present, an explicit ``allow_web_search=false``
    wins so a stale or conflicting intent path cannot re-enable web tools.
    """

    if is_web_search_explicitly_denied(allow_web_search):
        return False
    return tool_toggle_enabled(allow_web_search) or tool_toggle_enabled(use_web)


_COMMON_TOOL_NAMES = {
    "api_call",
    "app_api",
    "archive_email",
    "ask_teacher",
    "ask_user",
    "bash",
    "bulk_email",
    "builtin_browser",
    "cancel_download",
    "chat_with_model",
    "create_document",
    "create_session",
    "delete_email",
    "download_model",
    "edit_document",
    "edit_file",
    "edit_image",
    "generate_image",
    "glob",
    "grep",
    "list_cached_models",
    "list_cookbook_servers",
    "list_downloads",
    "list_emails",
    "list_models",
    "list_serve_presets",
    "list_served_models",
    "list_sessions",
    "ls",
    "manage_calendar",
    "manage_contact",
    "manage_documents",
    "manage_endpoints",
    "manage_mcp",
    "manage_memory",
    "manage_notes",
    "manage_research",
    "manage_session",
    "manage_settings",
    "manage_skills",
    "manage_tasks",
    "manage_tokens",
    "manage_webhooks",
    "mark_email_read",
    "pipeline",
    "python",
    "read_email",
    "read_file",
    "reply_to_email",
    "resolve_contact",
    "search_chats",
    "search_hf_models",
    "send_email",
    "send_to_session",
    "serve_model",
    "serve_preset",
    "stop_served_model",
    "suggest_document",
    "trigger_research",
    "ui_control",
    "update_document",
    "update_plan",
    "vault_get",
    "vault_search",
    "vault_unlock",
    "web_fetch",
    "web_search",
    "write_file",
}


# ── `P2-14`: the trigger, narrowed, and the seventh pattern re-homed ────────
#
# Seven unanchored `.search`es over the whole user message disarmed the agent
# on any *mention* of the phrasing. Re-measured 2026-09-19 by executing the
# detector: all three of `P2-CORRECTED`'s reproductions still fired, and a hit
# still strips **82** tools (`known_tool_names()`, executed in-tree — the same
# number the roadmap re-measured on 2026-08-27) plus MCP, tool preprocessing
# and background extraction.
#
# What actually distinguishes a request from a mention is not the words, it is
# **whose words they are and where in the sentence they sit**. So three rules,
# each closing one reproduced failure and nothing wider:
#
#   1. **Quoted spans are removed before matching.** Reported speech is not an
#      instruction — `Quote: "do not use any tools" — what does that mean?`
#      asked a question and lost every tool.
#   2. **The two mode names need an activation frame**, or they must open the
#      clause. `I love guide-only mode discussions` names the mode and asks for
#      nothing.
#   3. **The two "not allowed" patterns need a second-person present-tense
#      subject**, or they must open the clause. `Why am I not allowed to use
#      tools here?` is a question *about* the policy, and answering it by
#      enforcing the policy is the single worst case on the row. `you were not
#      allowed` is reported speech and is out for the same reason as rule 1.
#
# **Matched per clause, not per message.** `D-2026-08-26-06` says *"anchor
# patterns 1–6 to whole-message match"*; whole-*message* would refuse
# `Guide-only mode for this one — just tell me what to type`, which is the most
# natural way anybody asks for it, and `Law 1` keeps the feature working.
# Clause scope is what the anchors need to be worth anything, and it is what
# lets `GUIDE-ONLY MODE. DO NOT USE TOOLS.` still hit both patterns. Whitespace
# is normalised **before** splitting, so a newline-separated list stays one
# clause — `You are not allowed to:\n- use tools` is a single directive.
_QUOTED_SPAN = re.compile(
    "\"[^\"]*\"|'[^']*'|“[^”]*”|‘[^’]*’|`[^`]*`"
)
_CLAUSE_SPLIT = re.compile(r"[.!?;]+")

#: An imperative lead-in that turns a mode's NAME into a request for it.
_ACTIVATION = (
    r"(?:^|\b(?:use|using|switch to|switching to|enable|enabling|turn on|"
    r"activate|start|stay in|staying in|go|put us in|we(?:'re| are) in|in)\s+)"
)
#: A second-person present-tense subject, or the start of the clause. Past
#: tense is deliberately absent: *"you were not allowed"* is a report.
_ADDRESSED = r"(?:^|\byou(?:'re| are)\s+)"

_GUIDE_ONLY_PATTERNS: Tuple[Tuple[re.Pattern[str], str], ...] = tuple(
    (re.compile(pattern, re.IGNORECASE), reason)
    for pattern, reason in (
        (_ACTIVATION + r"guide[-\s]?only mode\b", "guide-only mode requested"),
        (_ACTIVATION + r"no[-\s]?tools? mode\b", "no-tools mode requested"),
        (r"\bdo not use (?:any )?tools?\b", "user forbade tool use"),
        (r"\bdon'?t use (?:any )?tools?\b", "user forbade tool use"),
        (_ADDRESSED + r"not allowed to use (?:any )?tools?\b", "user forbade tool use"),
        (_ADDRESSED + r"not allowed to:?.{0,120}\buse (?:any )?tools?\b",
         "user forbade tool use"),
    )
)

# **The seventh pattern is not a disarm and never was one.** *"Ask me before
# using tools"* is a request for **confirmation**, and the response was a fully
# disarmed agent — the sharpest case on the row. It now raises the run's trust
# rung to `ask_every_time`, which is the confirmation mechanism this product
# already has (`P7-03`'s ladder): every action mints an approval card the person
# clicks. `Law 14` — the gate exists, so the request routes into it rather than
# into a second idea of what "ask me" means.
_CONFIRM_TOOLS_PATTERNS: Tuple[Tuple[re.Pattern[str], str], ...] = tuple(
    (re.compile(pattern, re.IGNORECASE), reason)
    for pattern, reason in (
        (r"\bask (?:me )?(?:for confirmation |first )?before (?:using|running|calling) tools?\b",
         "user requested confirmation before tools"),
        (r"\bcheck with me before (?:using|running|calling) tools?\b",
         "user requested confirmation before tools"),
    )
)


def _directive_clauses(message: object) -> list:
    """The clauses of a user turn, with reported speech removed.

    Whitespace is normalised first so a newline-separated list stays one
    clause; quoted spans are dropped because a quotation is somebody else's
    instruction; and the result is split on sentence punctuation so an anchor
    means *"opens this clause"* rather than *"opens the whole message"*.
    """
    if not isinstance(message, str) or not message.strip():
        return []
    text = re.sub(r"\s+", " ", message.strip())
    text = _QUOTED_SPAN.sub(" ", text)
    return [clause.strip() for clause in _CLAUSE_SPLIT.split(text) if clause.strip()]


@dataclass(frozen=True)
class ToolPolicy:
    """Effective tool behavior for one agent turn."""

    disabled_tools: frozenset[str] = frozenset()
    hidden_tools: frozenset[str] = frozenset()
    reasons: Mapping[str, str] = field(default_factory=dict)
    mode: str = "normal"
    block_all_tool_calls: bool = False
    disable_mcp: bool = False
    #: `P2-14`. The turn asked to be consulted, not to be disarmed. Read by
    #: `stream_agent_loop`, which raises the run's trust rung to
    #: `ask_every_time` — it only ever makes the run stricter, never looser.
    require_tool_confirmation: bool = False

    def all_disabled_names(self) -> Set[str]:
        return set(self.disabled_tools) | set(self.hidden_tools)

    def blocks(self, tool_name: Optional[str]) -> bool:
        if not tool_name:
            return False
        return self.block_all_tool_calls or tool_name in self.disabled_tools or tool_name in self.hidden_tools

    def reason_for(self, tool_name: Optional[str]) -> str:
        if tool_name and tool_name in self.reasons:
            return self.reasons[tool_name]
        if self.block_all_tool_calls and self.mode == "guide_only":
            return "Tool use is disabled for this guide-only turn."
        return "Tool use is disabled for this turn."

    def confirms(self) -> bool:
        """Whether this turn asks for an approval card on every action."""
        return bool(self.require_tool_confirmation)


def _first_match(clauses, patterns) -> Optional[str]:
    for clause in clauses:
        for pattern, reason in patterns:
            if pattern.search(clause):
                return reason
    return None


def detect_guide_only_turn(message: object) -> Optional[str]:
    """Return a reason when the latest user turn strongly requests no tools.

    Six patterns now, not seven: the confirmation request moved to
    `detect_tool_confirmation_turn`, because asking to be asked is not asking
    to be refused (`P2-14`).
    """

    return _first_match(_directive_clauses(message), _GUIDE_ONLY_PATTERNS)


def detect_tool_confirmation_turn(message: object) -> Optional[str]:
    """Return a reason when the turn asks to be consulted before tool use.

    A disarm and a confirmation are different requests and this is the one the
    product already had a mechanism for. A turn that asks for BOTH is a disarm:
    `build_effective_tool_policy` checks the stronger reading first.
    """

    return _first_match(_directive_clauses(message), _CONFIRM_TOOLS_PATTERNS)


def known_tool_names() -> Set[str]:
    """Best-effort set of native tool names for prompt hiding and denylisting."""

    names = set(_COMMON_TOOL_NAMES)
    try:
        from src.tool_schemas import FUNCTION_TOOL_SCHEMAS

        for schema in FUNCTION_TOOL_SCHEMAS:
            name = (schema.get("function") or {}).get("name") or schema.get("name")
            if name:
                names.add(name)
    except Exception as exc:
        # `P2-14`, 2026-09-19. This was a bare `except Exception: pass` while
        # the two legs below it both logged — and it is the leg that actually
        # fails. `src/tool_schemas.py` and `src/agent_tools/__init__.py` import
        # each other, so in a process that reaches THIS module before
        # `src.agent_loop`, the first call raises `ImportError` here, swallows
        # it, and answers **82** instead of **84**; `host_shell` and
        # `manage_rag` are the two it drops. Every later call in the same
        # process answers 84, because the failed import left the cycle
        # resolved. The live app imports `agent_loop` at startup and so always
        # gets 84 — but a number that silently depends on import order is
        # `Law 5` with no scope attached, and the count of what a guide-only
        # turn strips was quoted from the degraded answer. `B830`.
        #
        # Enforcement does not depend on this list being complete:
        # `block_all_tool_calls` refuses names the denylist never learned. What
        # a short list costs is *advertisement* — two tools stay visible to the
        # model on a turn that asked for none.
        _logger.debug("known_tool_names: FUNCTION_TOOL_SCHEMAS unavailable (%s)", exc)
    try:
        from src.agent_loop import TOOL_SECTIONS

        names.update(TOOL_SECTIONS.keys())
    except Exception as exc:
        # `P3-17`. Import cycles are the expected failure here — this module is
        # imported *by* agent_loop — and a partial name set is the designed
        # degraded answer, so it is not raised. It is said out loud because a
        # caller reading a short list has no other way to know it is short.
        _logger.debug("known_tool_names: TOOL_SECTIONS unavailable (%s)", exc)
    try:
        from src.tool_security import PLAN_MODE_READONLY_TOOLS, _PLAN_MODE_KNOWN_MUTATORS

        names.update(PLAN_MODE_READONLY_TOOLS)
        names.update(_PLAN_MODE_KNOWN_MUTATORS)
    except Exception as exc:
        # `P3-17`: same shape as above.
        _logger.debug("known_tool_names: plan-mode tool lists unavailable (%s)", exc)
    return names


def build_effective_tool_policy(
    *,
    disabled_tools: Optional[Iterable[str]] = None,
    last_user_message: object = "",
) -> ToolPolicy:
    """Compose the effective policy for one agent turn.

    Existing callers still provide the already-composed disabled-tool denylist.
    This function adds higher-level turn policy on top so enforcement is not
    delegated to prompt compliance.
    """

    disabled = {str(t) for t in (disabled_tools or []) if t}
    hidden: Set[str] = set()
    reasons = {tool: "Tool is disabled for this request." for tool in disabled}

    guide_reason = detect_guide_only_turn(last_user_message)
    if guide_reason:
        all_tools = known_tool_names()
        disabled.update(all_tools)
        hidden.update(all_tools)
        reasons.update({tool: f"{guide_reason}." for tool in all_tools})
        return ToolPolicy(
            disabled_tools=frozenset(disabled),
            hidden_tools=frozenset(hidden),
            reasons=MappingProxyType(dict(reasons)),
            mode="guide_only",
            block_all_tool_calls=True,
            disable_mcp=True,
        )

    # `P2-14`. Checked after the disarm, so a turn that says both gets the
    # stronger reading. Nothing is added to the denylist and MCP is not
    # dropped: the request was to be asked, and the answer is the approval
    # ladder this product already has, not an agent with no hands.
    confirm_reason = detect_tool_confirmation_turn(last_user_message)
    if confirm_reason:
        return ToolPolicy(
            disabled_tools=frozenset(disabled),
            hidden_tools=frozenset(hidden),
            reasons=MappingProxyType(dict(reasons)),
            mode="confirm_tools",
            require_tool_confirmation=True,
        )

    return ToolPolicy(
        disabled_tools=frozenset(disabled),
        hidden_tools=frozenset(hidden),
        reasons=MappingProxyType(dict(reasons)),
    )
