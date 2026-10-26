# SPDX-License-Identifier: AGPL-3.0-or-later
"""Per-turn tool policy composition for agent execution."""

from __future__ import annotations

import logging
import re
from dataclasses import dataclass, field
from types import MappingProxyType
from typing import Dict, Iterable, Mapping, Optional, Set, Tuple

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


#: `B1382`. The two sentences a policy gives when it knows nothing more
#: specific than *withheld*: a name the route's denylist named, and a name
#: nothing named at all. A refusal that has the register's reason for the name
#: (a privilege, `tool_security.non_admin_refusal`) answers ahead of these, and
#: behind every sentence that says something of its own (a step's own list, a
#: guide-only turn).
DISABLED_FOR_REQUEST = "Tool is disabled for this request."
DISABLED_FOR_TURN = "Tool use is disabled for this turn."
GENERIC_REFUSALS = frozenset({DISABLED_FOR_REQUEST, DISABLED_FOR_TURN})


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
    #: `P22-16`. The ONLY tools this turn may use — a workflow's AI step, whose
    #: author picked them from a list. `None` is every existing caller: no
    #: allowlist, the denylists above decide. A set — even an empty one — is a
    #: closed list: `blocks` refuses every name outside it, known or not, so a
    #: tool added to Pantheon tomorrow is outside it too. `stream_agent_loop`
    #: advertises only what is inside it, after retrieval and every widening.
    allowed_tools: Optional[frozenset] = None
    #: `P24-05`. Whose list `allowed_tools` is, in the words its refusal uses:
    #: a workflow step's (the default, every existing caller) or an agent's.
    allowed_owner: str = "this step's"
    #: `P24-07`. A hired agent's effects table: actions with one of these
    #: effects ask before they run (`ask_effects`) or are refused in a sentence
    #: no approval lifts (`never_effects`). Empty for every other turn, which
    #: is every existing caller. Read by `ToolRunSecurityContext.decision_for`,
    #: ahead of the trust ladder and of a chat's Auto, because the hire is the
    #: person's standing answer about this agent and a chat setting is not.
    ask_effects: frozenset = frozenset()
    never_effects: frozenset = frozenset()
    #: `D-2026-10-24-01`. True when a hired agent's whole kit has no way to
    #: carry data out of the install (`src.agents.runtime.SEALING_EFFECTS`):
    #: then reading more of the person's own data after outside content does
    #: not ask. False for every other turn, which is every existing caller.
    sealed: bool = False
    #: `D-2026-10-24-02`. True when a hired agent's whole kit cannot read any
    #: of the person's private data (`src.agents.runtime.PRIVATE_READ_EFFECTS`):
    #: then searching and fetching public pages after outside content does not
    #: ask. False for every other turn.
    blind: bool = False
    #: `P27-09`. The agent this turn is — a summoned or hired one's id — so a
    #: vault login granted to some agents only is offered to those. `None` is
    #: the plain chat, which every existing caller is.
    agent_id: Optional[str] = None

    def __post_init__(self) -> None:
        # A list or set handed in becomes a frozenset of names, so the policy a
        # turn starts with is the policy it ends with.
        if self.allowed_tools is not None:
            object.__setattr__(self, "allowed_tools", frozenset(
                str(name) for name in self.allowed_tools if isinstance(name, str) and name))

    def all_disabled_names(self) -> Set[str]:
        return set(self.disabled_tools) | set(self.hidden_tools)

    def outside_allowed(self, tool_name: Optional[str]) -> bool:
        """Whether an allowlist is set and this name is not on it.

        Asked of every policy-equivalent spelling at once
        (`tool_security.email_tool_policy_names`): an author who picked
        `list_emails` picked `mcp__email__list_emails` too, and the dispatcher
        asks `blocks` of both spellings — one of them being outside the list
        must not refuse a call the other is on it for. A name that is not a
        string is outside any list."""
        if self.allowed_tools is None:
            return False
        if not isinstance(tool_name, str) or not tool_name:
            return True
        from src.tool_security import email_tool_policy_names
        return email_tool_policy_names(tool_name).isdisjoint(self.allowed_tools)

    def blocks(self, tool_name: Optional[str]) -> bool:
        if not tool_name:
            return False
        return (self.block_all_tool_calls or tool_name in self.disabled_tools
                or tool_name in self.hidden_tools or self.outside_allowed(tool_name))

    def reason_for(self, tool_name: Optional[str]) -> str:
        if tool_name and self.outside_allowed(tool_name):
            return f"“{tool_name}” is not one of {self.allowed_owner} tools."
        if tool_name and tool_name in self.reasons:
            return self.reasons[tool_name]
        if self.block_all_tool_calls and self.mode == "guide_only":
            return "Tool use is disabled for this guide-only turn."
        return DISABLED_FOR_TURN

    def refusal_for(self, names, *, called: Optional[str] = None) -> Optional[str]:
        """`B1101`. The sentence a refused call is answered with, asked of
        every policy-equivalent spelling (`email_tool_policy_names`): the
        spelling the model called first, then the others in a fixed order —
        so the loop's refusal and the dispatcher's backstop name the same
        spelling and say the same sentence. `None` when nothing blocks.

        Before it the dispatcher answered every `blocks` refusal with "…is
        forbade by the active guide-only policy" — for a step's allowlist and
        an ordinary turn's denylist alike — while the loop said this policy's
        own reason."""
        spelled = [str(n) for n in (names or ()) if n]
        order = ([called] if called in spelled else []) + sorted(n for n in spelled if n != called)
        for name in order:
            if self.blocks(name):
                return self.reason_for(name)
        return None

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


def selectable_tool_names() -> Set[str]:
    """The names a turn may **offer** — `known_tool_names()`' routable half.

    `B1354` (agent:`fx11-reach`). `known_tool_names()` below says what it is
    for in its own first line: *"prompt hiding and denylisting"*. A denylist
    register has to be **generous** — a name it misses is a name a guide-only
    turn fails to hide, and its own comment says enforcement does not depend on
    the list being complete. An **offer** register has to be **exact** — a name
    it over-counts is a name the model is shown and can never call. The two
    requirements point in opposite directions, so one answer cannot serve both
    (`Law 10`), and `src/agent_loop.plan_turn_tool_suite` was asking the
    generous one for the exact question: its candidate line read
    `(set(known_tool_names()) | mcp_names) - disabled`.

    Measured on `747cda6` by driving the real loop and spying on
    `_assemble_prompt`: an admin's ordinary turn handed the prompt builder
    **84** names, the request's array carried **73**, the prompt named **79**,
    and **4** were in neither channel — `builtin_browser`, `vault_get`,
    `vault_search`, `vault_unlock`. A call for any of the four, in all five
    reply shapes a local server emits, dispatched **nothing**: the native shape
    logged `Unknown function call` and the person read *"The model returned an
    empty response. Please try again or switch to a different model."*, and the
    other four streamed the model's raw tool syntax into the chat.

    Why those four and no others: `builtin_browser` is a **server id**
    (`FORBIDDEN.md` Part 1 lists it under *built-in MCP server ids*), earning
    its place in the denylist register because it is the word the browser
    toggle accepts (`admin_tools._ALIASES["browser"]`) and the intent marker
    `_expand_browser_mcp_tools` turns into that server's real qualified tool
    names — neither of which is an offer. The three `vault_*` names are a real
    admin capability whose surface is Settings: `require_admin` on every
    `/api/vault/*` route, and `src/tool_index.py`'s index pruner names them
    *"removed tools like the old vault_* set"* while `BUILTIN_TOOL_DESCRIPTIONS`
    has no entry for any of them, so retrieval was never meant to reach them.
    `Law 1`: nothing about them is removed — the dispatch arms, the
    `NON_ADMIN_BLOCKED_TOOLS` gate and its sentences, `tool_capabilities`'
    effects and `agent_stops._CREDENTIAL_TOOLS` are all exactly where they
    were, and a workflow step or an approved card still runs them. What is
    withdrawn is the **offer** of a name the model cannot call.

    Derived, never a list: `src.tool_schemas.dispatch_name_for` is the
    product's own answer to *"will anything route a call for this name"*, so a
    tool added tomorrow with no schema and no fence tag falls out of here with
    nobody editing a file. Fails **open** the way its neighbour does — an
    import that cannot be made answers the generous set, because offering too
    much is the behaviour before this row and offering nothing would take every
    tool away (`P3-17`).
    """

    names = known_tool_names()
    try:
        from src.tool_schemas import dispatch_name_for
    except Exception as exc:
        # The same `tool_schemas`/`agent_tools` cycle `known_tool_names()`
        # documents below. Said out loud, not swallowed.
        _logger.debug("selectable_tool_names: dispatch rule unavailable (%s)", exc)
        return names
    return {name for name in names if dispatch_name_for(name) is not None}


def known_tool_names() -> Set[str]:
    """Best-effort set of native tool names for prompt hiding and denylisting.

    **Not the set a turn may offer** — that is `selectable_tool_names()` above,
    and the difference is why this one stays exactly as generous as it is
    (`Law 1`): a name here is a name a guide-only turn can hide and a denylist
    can name, whether or not any channel carries a call for it.
    """

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


# ── `B1351` (fx11-cap). One answer to "what can this turn call?" ──────────
#
# `stream_agent_loop` built a plain `set` named `disabled_tools` and then wrote
# to it from **ten** places — `ToolPolicy.all_disabled_names()`,
# `blocked_tools_for_owner(owner)`, `delegated_credential_blocked_tools()`,
# `feature_disabled_tools()`, the workstation gate, `plan_mode_disabled_tools()`,
# the open email draft, plan mode's MCP block queue, a workflow step's own list
# (twice) and a `pantheon-qwen3` clamp — and read it in **thirteen**, each of
# which wrote the predicate out again. Measured on `747cda6`, driving the real
# loop with `relevant_tools={"ask_user","update_plan"}` and real accounts from
# `tests/helpers/signed_in.people`:
#
#     privilege                 cap   what else was true
#     anonymous                  53   `manage_memory` capped; it is in
#                                     `tool_index.ALWAYS_AVAILABLE`, which four
#                                     selection sites pin unconditionally
#     registered non-admin       53   identical
#     admin                       2   `computer`, `generate_image`
#     delegated credential       54   + `manage_documents` (`B995`)
#     plan mode (admin)          56
#     guide-only (admin)         85
#
# Three things that set could not say, and each of them was a defect:
#
#   1. **Only one of the thirteen readers honoured `email_tool_policy_names`.**
#      The dispatcher asked every policy-equivalent spelling; the prompt and the
#      schema filter asked the literal name — which is why the open-email-draft
#      writer has to spell `list_emails` and `mcp__email__list_emails` by hand.
#   2. **Nothing recorded WHY a name was withheld**, so a later clamp could lift
#      a privilege cap. `_pan_notes_finetune_mode`'s
#      `difference_update({manage_notes, manage_calendar, manage_tasks})` did
#      exactly that: on a `pantheon-qwen3` notes turn a non-admin's cap went
#      from 52 names to **50**, and `manage_calendar` and `manage_tasks` were
#      named in the prompt and sent as schemas to an anonymous visitor. The
#      dispatcher's own gate (`is_public_blocked_tool`, the second of `B533`'s
#      two) still refused every call — so what shipped was two tools offered and
#      then refused, which is what *"intermittent"* looks like from outside.
#   3. **A name could be in `relevant_tools` and in the cap at once** and
#      nothing noticed, because the subtraction happened later inside
#      `_assemble_prompt`. `B1366` had to add a helper for two gates that were
#      reading the overlap.
#
# So: the set is still a `set` — every `in`, `-`, `.update()` and
# `.difference_update()` in the loop keeps working byte for byte — and it now
# carries the predicate and the reasons. `lift()` is the `Law 1` guarantee
# expressed as a property of the type rather than as a thing thirteen call
# sites have to remember: **a privilege, a policy, a switched-off feature, a
# workstation an admin turned off, the route's own set and a step's own list
# cannot be lifted by a later clamp.**
#
# `B1399`. That sentence named **five** reasons while `LIFTABLE_REASONS` below
# made **seven** unliftable, and the two it did not name were
# `WITHHELD_BY_CALLER` and `WITHHELD_BY_WORKSTATION`. The gap was not
# cosmetic — `src/agent_loop.py` tags the route's whole `disabled_tools` kwarg
# `because=WITHHELD_BY_CALLER`, so the `pantheon-qwen3` notes clamp can lift
# **nothing the route passed in**, which is every name PR `#6020` wrote it to
# lift, and that clamp became dead code with no commit deciding it.
#
# Widening the liftable set was tried first and measurement refused it:
# `caller` was one bucket for two different facts. It held a neutral starting
# set *and* every deliberate route restriction — incognito's `manage_memory`,
# `search_chats` and `manage_skills`, the email reader's `send_email` and
# `create_document`, and chat-mode compare's `manage_tasks`, which is one of
# the exact three names both `lift()` call sites pass. Making the bucket
# liftable in that state would have let the notes clamp re-enable
# `manage_tasks` in a mode whose own comment reads *"disable ALL agent tools"*.
#
# **Fixed 2026-10-17 by attribution at the route** (`D-2026-10-17-02` §2), not
# by a wider liftable set. `routes/chat_routes.py` composes its denylist through
# `RouteWithholds` below, which **requires a reason for every name** — so the
# deliberate sets carry `policy`, `privilege`, `feature` or `plan_mode` and
# only the genuinely neutral remainder is `caller`. `caller` is liftable now
# and `#6020`'s `pantheon-qwen3` notes clamp works again.
#
# **The risk this moves to is exhaustiveness, and it is the whole risk**: a
# deliberate set the route forgets to attribute becomes liftable, which is a
# privacy control defeated by an omission. That is why `RouteWithholds` has no
# default reason — the parameter is positional and required — and why
# `tests/test_a_route_says_why_it_withheld.py` asserts the route composes its
# denylist through nothing else, derived from the source, so a sixth
# restriction added later fails rather than leaking.

#: Why a name is withheld from a turn. An enum rather than a flag (`Law 10`):
#: "it is withheld" and "it is withheld because this person may not use it" are
#: different facts and only the second one is unliftable.
WITHHELD_BY_CALLER = "caller"
WITHHELD_BY_POLICY = "tool_policy"
WITHHELD_BY_PRIVILEGE = "privilege"
WITHHELD_BY_FEATURE = "feature"
WITHHELD_BY_WORKSTATION = "workstation"
WITHHELD_BY_PLAN_MODE = "plan_mode"
WITHHELD_BY_STEP_TOOLS = "step_tools"
WITHHELD_BY_TURN = "turn"
#: A name added through the plain `set` API with no reason given. Liftable,
#: because every `.update()` that predates this type behaved that way and
#: `Law 1` says a working path survives.
WITHHELD_UNATTRIBUTED = "unattributed"

WITHHELD_REASONS = frozenset({
    WITHHELD_BY_CALLER, WITHHELD_BY_POLICY, WITHHELD_BY_PRIVILEGE,
    WITHHELD_BY_FEATURE, WITHHELD_BY_WORKSTATION, WITHHELD_BY_PLAN_MODE,
    WITHHELD_BY_STEP_TOOLS, WITHHELD_BY_TURN, WITHHELD_UNATTRIBUTED,
})

#: The reasons a later clamp may lift. Everything outside this set is a
#: privilege decision (`blocked_tools_for_owner`, `B70`'s token cap), a policy
#: the route composed, a capability an admin switched off (`H05`), a
#: workstation an admin turned off, plan mode or a workflow step's own list
#: (`P22-16`) — and `FORBIDDEN.md` Part 2 holds three of those six.
#:
#: `WITHHELD_BY_CALLER` joined this set on 2026-10-17 (`B1399`,
#: `D-2026-10-17-02` §2) and the order of the two changes is the whole of the
#: safety argument: it is liftable **because** the route now attributes its
#: deliberate sets to `policy`, `privilege`, `feature` and `plan_mode` through
#: `RouteWithholds`, so what remains in `caller` is a neutral starting set and
#: nothing else. Lifting it before that attribution existed was tried, broke
#: `test_the_caller_s_own_set_is_recorded_as_the_caller_s`, and that test was
#: right. Do not widen this set without the matching attribution; the two are
#: one change.
LIFTABLE_REASONS = frozenset({
    WITHHELD_BY_TURN, WITHHELD_UNATTRIBUTED, WITHHELD_BY_CALLER,
})


class TurnToolAccess(set):
    """The names this turn withholds, and the one predicate that reads them.

    A `set`, so it is a drop-in for the `disabled_tools` every caller of
    `stream_agent_loop` already passes and for the ~40 plain set operations
    inside it. What it adds:

    * :meth:`blocks` / :meth:`allows` / :meth:`allowed_among` — **one**
      predicate, asked of every policy-equivalent spelling
      (`tool_security.email_tool_policy_names`), so the prompt, the schema
      list and the dispatcher cannot answer differently for one name;
    * :meth:`withhold` with a ``because``, and :meth:`reasons_for`;
    * :meth:`lift`, which removes a name only when every reason it is withheld
      for is liftable — so a per-turn clamp cannot widen a privilege cap.

    ``discard``, ``remove``, ``difference_update`` and ``-=`` route through
    :meth:`lift`, so a call site that predates this type gets the guarantee
    without being rewritten.
    """

    def __init__(self, names=(), *, because=WITHHELD_UNATTRIBUTED):
        super().__init__()
        self._why: dict = {}
        self.withhold(names, because=because)

    # ── the predicate, in one place ────────────────────────────────────────
    @staticmethod
    def _spellings(tool_name):
        """Every policy-equivalent spelling of a name, the dispatcher's rule.

        Imported at call time: `src.tool_security` imports nothing from here,
        but this module is reached from `src.agent_loop`, which both import.
        """
        try:
            from src.tool_security import email_tool_policy_names
            return email_tool_policy_names(tool_name)
        except Exception as exc:                                  # pragma: no cover
            # `P3-17`, and it fails **closed on nothing**: the literal name is
            # still asked, which is what every reader but the dispatcher did
            # before this existed.
            _logger.debug("TurnToolAccess: alias lookup unavailable (%s)", exc)
            return frozenset((tool_name,))

    def blocks(self, tool_name) -> bool:
        """Whether this turn withholds ``tool_name`` under any of its spellings."""
        if not tool_name:
            return False
        return not self._spellings(tool_name).isdisjoint(self)

    def allows(self, tool_name) -> bool:
        return not self.blocks(tool_name)

    def allowed_among(self, names) -> set:
        """The subset of ``names`` this turn can call — the answer to the
        question every reader was asking with its own subtraction."""
        return {n for n in (names or ()) if self.allows(n)}

    def reasons_for(self, tool_name) -> frozenset:
        """Why ``tool_name`` is withheld, over every spelling. Empty when it is
        not withheld at all."""
        out: set = set()
        for spelling in self._spellings(tool_name):
            out |= self._why.get(spelling, set())
        return frozenset(out)

    def privilege_refusal(self, tool_name, *, delegated_credential=False) -> Optional[str]:
        """The sentence for a call this turn withholds **by privilege**, or
        ``None`` when privilege is not one of the reasons.

        `B1382`. `blocked_tools_for_owner` writes a non-admin's names into this
        cap before any call is made, so the loop's own `tool_blocked` arm
        answers first — and it answered *"disabled by the current request
        policy"*, never reaching the dispatcher's `P2-25` sentence, which says
        what the tool reaches and who may run it. The reason is recorded here
        (`WITHHELD_BY_PRIVILEGE`), so the sentence is chosen from it rather
        than guessed from the owner again. A bearer-token run's cap is a
        privilege too (`B70`), and it gets the token's own sentence. Nothing is
        lifted or changed about what is blocked; this only reads.
        """
        if WITHHELD_BY_PRIVILEGE not in self.reasons_for(tool_name):
            return None
        from src.tool_security import delegated_credential_refusal, non_admin_refusal
        if delegated_credential:
            return delegated_credential_refusal(tool_name)
        return non_admin_refusal(tool_name)


    # ── the writers ───────────────────────────────────────────────────────
    def withhold(self, names, *, because=WITHHELD_UNATTRIBUTED) -> set:
        """Withhold ``names`` for ``because``. Returns the names newly added."""
        if because not in WITHHELD_REASONS:
            raise ValueError(f"unknown withholding reason: {because!r}")
        added = set()
        for name in (names or ()):
            if not isinstance(name, str) or not name:
                continue
            if name not in self:
                added.add(name)
            super().add(name)
            self._why.setdefault(name, set()).add(because)
        return added

    def lift(self, names, *, because=WITHHELD_BY_TURN) -> set:
        """Stop withholding ``names``, but **only** the ones whose every reason
        is liftable. Returns what was actually lifted; what was refused is
        logged with the reason, because a clamp that silently did nothing is
        how the opposite defect would arrive.

        ``because`` is who is asking, and it is recorded in the log line. It
        does not widen the rule: a privilege entry is unliftable whoever asks.
        """
        lifted, refused = set(), {}
        for name in (names or ()):
            if name not in self:
                continue
            why = self._why.get(name, {WITHHELD_UNATTRIBUTED})
            if why - LIFTABLE_REASONS:
                refused[name] = sorted(why - LIFTABLE_REASONS)
                continue
            super().discard(name)
            self._why.pop(name, None)
            lifted.add(name)
        if refused:
            _logger.info(
                "[tool-access] %s may not lift %s", because,
                ", ".join(f"{n} ({'+'.join(r)})" for n, r in sorted(refused.items())),
            )
        return lifted

    # ── the plain `set` API, so nothing in the loop has to change ─────────
    def add(self, name) -> None:
        self.withhold((name,))

    def update(self, *others) -> None:
        for other in others:
            self.withhold(other)

    def discard(self, name) -> None:
        self.lift((name,), because="discard")

    def remove(self, name) -> None:
        if name not in self:
            raise KeyError(name)
        self.lift((name,), because="remove")

    def difference_update(self, *others) -> None:
        for other in others:
            self.lift(other, because="difference_update")

    def clear(self) -> None:
        self.lift(set(self), because="clear")

    def __ior__(self, other):
        self.withhold(other)
        return self

    def __isub__(self, other):
        self.lift(other, because="-=")
        return self

    def copy(self) -> "TurnToolAccess":
        twin = TurnToolAccess()
        for name, why in self._why.items():
            for because in why:
                twin.withhold((name,), because=because)
        return twin


def turn_tool_access(disabled_tools, *, because=WITHHELD_UNATTRIBUTED) -> TurnToolAccess:
    """This turn's access, from whatever the caller handed in.

    The object itself when it is already one — so no reason is lost and a
    reader cannot accidentally make a privilege entry liftable — and a new one
    around a plain set or `None` otherwise. Every reader in `src/agent_loop.py`
    goes through this, which is what makes the predicate single (`Law 7`) while
    the dozens of existing callers that pass a plain set keep working.
    """
    if isinstance(disabled_tools, TurnToolAccess):
        return disabled_tools
    return TurnToolAccess(disabled_tools or (), because=because)


class RouteWithholds:
    """A route's denylist under composition, with a reason on every name.

    `B1399` / `D-2026-10-17-02` §2. `routes/chat_routes.py` composed its
    denylist as a plain `set` across sixteen `update()` calls and three
    `difference_update()` calls, and `stream_agent_loop` then tagged the whole
    result `WITHHELD_BY_CALLER` — one bucket holding a neutral starting set
    *and* every deliberate privacy restriction. That is why `caller` could not
    be liftable, and why `#6020`'s notes clamp had become dead code.

    **Why a type and not a convention.** The attribution has to be exhaustive
    or it is worse than nothing: a deliberate set that is forgotten becomes
    liftable, which is a privacy control defeated by an omission. So:

    * ``because`` is **positional and required** — there is no reason to
      forget, because there is no default to fall through to;
    * composition churn goes through :meth:`allow`, so the route can still add
      the web tools and take them back out (it does, three times) without the
      add needing to be liftable;
    * :meth:`finish` is the only way out, and it is what attributes the names
      the **policy layer** added on top — `build_effective_tool_policy` can
      disable every tool in the product on a guide-only turn, and those are the
      policy's, not the caller's.

    Everything the route does not attribute at all ends up `caller`, which is
    liftable — so this type's correctness is exactly the claim that a name
    reaching `caller` is a name nobody decided anything about.
    """

    __slots__ = ("_why",)

    def __init__(self):
        self._why: Dict[str, Set[str]] = {}

    # ── the writers ───────────────────────────────────────────────────────
    def deny(self, names, because) -> "RouteWithholds":
        """Withhold ``names`` for ``because``. Chainable, so a site is one line."""
        if because not in WITHHELD_REASONS:
            raise ValueError(f"unknown withholding reason: {because!r}")
        if isinstance(names, str):
            names = (names,)
        for name in (names or ()):
            if isinstance(name, str) and name:
                self._why.setdefault(name, set()).add(because)
        return self

    def allow(self, names) -> "RouteWithholds":
        """Take ``names`` back off the list, whatever they were denied for.

        This is composition, not a clamp: the route denies the web tools and
        then allows them again on the branch where the chat's own setting
        enabled them. `TurnToolAccess.lift` deliberately refuses an unliftable
        reason; that rule is about a **later** clamp reaching a decision that is
        already made, and nothing here is later than anything else.
        """
        if isinstance(names, str):
            names = (names,)
        for name in (names or ()):
            self._why.pop(name, None)
        return self

    # ── the readers ───────────────────────────────────────────────────────
    def names(self) -> Set[str]:
        """The denylist as a plain set, for the policy layer to compose with."""
        return set(self._why)

    def reasons_for(self, name) -> frozenset:
        return frozenset(self._why.get(name, ()))

    def finish(self, all_disabled) -> "TurnToolAccess":
        """The turn's `TurnToolAccess`, attributed.

        ``all_disabled`` is what the policy layer answered — normally
        ``build_effective_tool_policy(...).all_disabled_names()``. A name this
        route denied keeps its reasons; a name only the policy layer added is
        `policy`, because that is literally what added it; a name in neither is
        not withheld at all.
        """
        access = TurnToolAccess()
        for name in sorted({str(n) for n in (all_disabled or ()) if n}):
            why = self._why.get(name)
            if why:
                for because in sorted(why):
                    access.withhold((name,), because=because)
            else:
                access.withhold((name,), because=WITHHELD_BY_POLICY)
        return access


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
    reasons = {tool: DISABLED_FOR_REQUEST for tool in disabled}

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
