# SPDX-License-Identifier: AGPL-3.0-or-later
"""Server-side tool safety policy."""

from __future__ import annotations

import logging
from typing import Optional, Set

logger = logging.getLogger(__name__)


# Every tool exposed by the built-in email MCP server
# (mcp_servers/email_server.py). Single source of truth: the fence tags
# (TOOL_TAGS), bare-name dispatch (tool_execution), native-call mapping
# (tool_schemas), and the non-admin blocklist below all derive from this set,
# so a tool added to the email server can't become reachable under its bare
# name without also being blocked for non-admins.
BUILTIN_EMAIL_TOOLS = frozenset({
    "list_email_accounts",
    "list_emails",
    "read_email",
    "search_emails",
    "scan_email_unsubscribes",
    "unsubscribe_email",
    "send_email",
    "reply_to_email",
    "draft_email",
    "draft_email_reply",
    "ai_draft_email_reply",
    "archive_email",
    "delete_email",
    "mark_email_read",
    "bulk_email",
    "download_attachment",
})


# Tools regular/public users must not execute directly. These either expose
# server/runtime access, sensitive user data, external messaging, persistent
# state changes, or generic loopback/integration surfaces. All email tools are
# included (SECURITY.md: email/MCP capabilities are privileged admin
# functionality).
#
# ── `P2-25`: the list stays, and now it says why ────────────────────────────
#
# The row was retitled from *"Prune…"* to *"Document… prune nothing"* because
# an agent that stopped at the title would have pruned, and the safe prune
# count is **zero**. `NON_ADMIN_BLOCKED_REASONS` below carries one sentence per
# name saying **what the tool reaches**, not that it is dangerous — the reader
# who wants to re-litigate an entry needs the reach, because that is the thing
# they have to argue is harmless.
#
# **Why a prune cannot be validated by trying it.** Eleven of these names are
# ALSO in `tool_execution._ADMIN_ONLY_TOOLS`, which is checked **first** and
# refuses with a different sentence. Remove one of those eleven from this set
# and a manual test still shows a refusal — from the other gate — so the change
# looks harmless and is not: what actually moved is what the model is
# *advertised*, because `blocked_tools_for_owner` (this module) and the prompt
# and schema filters read THIS set and not that one. `B533` put both gates and
# their order into `THREAT_MODEL.md` for exactly this reason. The pairing is
# asserted in `tests/test_the_blocklist_says_why.py`, so a prune of either is
# visibly a change to a pair.
#
# `adopt_served_model` is the counter-example that makes the point concrete: it
# is the one model tool this set blocks alone, so pruning it is the one prune in
# that family that really does open something.
#
# The register and the set are held equal by a test rather than by care. The set
# below is untouched (`Law 1`) and remains the gate; the register is documentation
# with a completeness check, and `blocked_tool_reason()` puts it in front of the
# person who hit the wall instead of in a comment only maintainers read
# (`Law 15`).
NON_ADMIN_BLOCKED_TOOLS = BUILTIN_EMAIL_TOOLS | {
    "bash",
    "host_shell",  # `P17-11`: runs on the operator's own machine
    "python",
    "manage_bg_jobs",
    "read_file",
    "write_file",
    "edit_file",
    "apply_patch",
    "grep",
    "glob",
    "ls",
    "get_workspace",
    "search_chats",
    "manage_memory",
    "manage_skills",
    "manage_tasks",
    "manage_endpoints",
    "manage_mcp",
    "manage_webhooks",
    "manage_tokens",
    "manage_documents",
    "manage_settings",
    "api_call",
    "app_api",
    "resolve_contact",
    "manage_contact",
    "manage_calendar",
    "vault_search",
    "vault_get",
    "vault_unlock",
    "download_model",
    "serve_model",
    "serve_preset",
    "stop_served_model",
    "cancel_download",
    "adopt_served_model",
}


# One sentence per blocked name: **what it reaches**, in the words someone
# arguing for a prune would have to answer. Grouped the way the set is grouped.
#
# Held equal to `NON_ADMIN_BLOCKED_TOOLS` by
# `tests/test_the_blocklist_says_why.py` — a name added to the set without a
# reason is a red test, not a silent gap.
_EMAIL_TOOL_REASON = (
    "reads or sends the operator's real mail through their configured accounts; "
    "SECURITY.md names email a privileged admin capability"
)

NON_ADMIN_BLOCKED_REASONS: dict = {
    # ── Server and runtime access ──
    "bash": "runs arbitrary commands as the app user on the host",
    "host_shell": "runs commands on the operator's own machine (`P17-11`)",
    "python": "executes arbitrary Python in the app process's environment",
    "manage_bg_jobs": "lists and kills the shell processes `bash` started",

    # ── The filesystem family. All eight, including the read-only ones: a
    # non-admin who cannot run the shell must not be able to map the host
    # either, which is the same sentence `routes/workspace_routes.py` gives
    # for `GET /api/workspace/browse`.
    "read_file": "reads any file the app user can read, inside the workspace",
    "write_file": "creates or overwrites files on the host filesystem",
    "edit_file": "rewrites existing files on the host filesystem",
    "apply_patch": "applies multi-file diffs to the host filesystem",
    "grep": "searches file CONTENTS across the workspace",
    "glob": "enumerates paths across the workspace",
    "ls": "enumerates directory contents on the host",
    "get_workspace": (
        "discloses the absolute host path of the workspace — the same "
        "disclosure `require_admin` refuses on `GET /api/workspace/browse`"
    ),

    # ── Other people's data ──
    "search_chats": (
        "searches stored chat transcripts. Owner-scoped, but the filter is "
        "`owner = X OR owner IS NULL` and a null owner means legacy/shared "
        "(`core/database.py`), so this reads the pre-auth and shared "
        "transcripts of an instance that predates its users"
    ),
    "resolve_contact": (
        "**the trap on this list.** It takes an `owner` argument and never "
        "reads it: it searches the server-wide CardDAV address book and the "
        "operator's sent mail. It looks owner-scoped and is not"
    ),
    "manage_contact": "writes to the server-wide CardDAV address book",
    "manage_calendar": "writes to the operator's calendar",
    "vault_search": "searches the credential vault's entry names",
    "vault_get": "returns a stored secret's value",
    "vault_unlock": "unlocks the credential vault for the process",

    # ── Persistent state and configuration ──
    "manage_memory": "writes the long-term memory every later turn is fed",
    "manage_skills": "writes skill files that are injected into later prompts",
    "manage_tasks": "creates and runs scheduled work under the operator's identity",
    "manage_documents": "creates, edits and deletes stored documents",
    "manage_settings": "writes instance settings, including every limit in `P12`",
    "manage_endpoints": "adds inference endpoints the whole instance then uses",
    "manage_mcp": (
        "registers MCP servers, whose command/arg/env validation is the RCE "
        "control in `FORBIDDEN.md` Part 2"
    ),
    "manage_webhooks": "registers outbound webhook destinations",
    "manage_tokens": "mints API tokens, which are long-lived credentials",

    # ── Generic reach: one tool that can become any of the above ──
    "api_call": "makes arbitrary outbound HTTP requests from the server",
    "app_api": (
        "calls this app's own HTTP API in-process. It carries its own "
        "blocklist (`src/tools/system.py`) because it can otherwise reach "
        "every route the agent is not meant to reach"
    ),

    # ── Model serving: each of these starts or rewires a host process ──
    "download_model": "fetches model weights to the host disk",
    "serve_model": "spawns an inference server process on the host",
    "serve_preset": "spawns an inference server process from a stored preset",
    "stop_served_model": "kills a running inference server process",
    "cancel_download": "aborts another caller's in-flight download",
    "adopt_served_model": (
        "registers an already-running server in `cookbook_state.json` AND adds "
        "it as a chat endpoint. **The one model tool this set blocks alone** — "
        "`_ADMIN_ONLY_TOOLS` does not name it, so unlike its five siblings a "
        "prune here really does open something"
    ),
}

# The sixteen email tools share one reason, and they derive from
# `BUILTIN_EMAIL_TOOLS` rather than being retyped: a tool added to the email
# server is blocked automatically today, and it must acquire a reason
# automatically too, or the register becomes the place the next name goes
# missing.
NON_ADMIN_BLOCKED_REASONS.update(
    {name: _EMAIL_TOOL_REASON for name in sorted(BUILTIN_EMAIL_TOOLS)}
)

#: Why the `mcp__` namespace is refused wholesale. This rule lives in
#: `is_public_blocked_tool` and NOT in the set, so `blocked_tools_for_owner`
#: does not carry it — the advertisement path compensates out of band by
#: dropping the MCP manager entirely (`agent_loop`). Two enforcement paths,
#: different rules; any refactor touches both.
MCP_NAMESPACE_BLOCK_REASON = (
    "every `mcp__*` tool comes from a server the operator configured, so its "
    "reach is whatever they connected — unknowable from the name, and refused "
    "for non-admins as a namespace rather than one entry at a time"
)


def blocked_tool_reason(tool_name) -> str:
    """Why this tool is refused to a non-admin, in one sentence.

    The register above, resolved for the spellings policy actually sees:
    a bare name, an `mcp__email__*` alias of a built-in email tool, or anything
    else under the `mcp__` prefix. Returns `""` for a name this policy does not
    block, so a caller can tell *"no reason recorded"* from *"not blocked"*
    (`Law 10`).
    """
    if not isinstance(tool_name, str) or not tool_name:
        return ""
    reason = NON_ADMIN_BLOCKED_REASONS.get(tool_name)
    if reason:
        return reason
    if tool_name.startswith("mcp__email__"):
        bare = tool_name[len("mcp__email__"):]
        if bare in BUILTIN_EMAIL_TOOLS:
            return _EMAIL_TOOL_REASON
    if tool_name.startswith("mcp__"):
        return MCP_NAMESPACE_BLOCK_REASON
    return ""


# Plan mode: the agent may investigate but must not mutate anything. Only these
# read-only/inspection tools stay enabled; everything else (writes, sends,
# manage_*, model serving, MCP, etc.) is blocked. Allowlist rather than blocklist
# so any newly added tool defaults to BLOCKED in plan mode — fail safe.
#
# bash/python are deliberately NOT here: the shell can mutate (write files, hit
# the network) and can't be constrained to read-only at the tool layer, so plan
# mode blocks it outright rather than relying on a prompt to keep it well-behaved.
# Code/file discovery is covered by the dedicated read-only tools below
# (read_file, grep, glob, ls) instead of freestyle shell.
PLAN_MODE_READONLY_TOOLS = {
    "read_file",
    "grep",
    "glob",
    "ls",
    "get_workspace",
    "web_search",
    "web_fetch",
    "search_chats",
    "list_models",
    "list_sessions",
    # Read-only email tools. list_email_accounts must be here because the
    # bare/qualified alias gate in execute_tool_block works both ways: it has
    # a native function schema, so plan mode's schema-derived bare denylist
    # contains it — and without this allowlist entry that bare entry would
    # also block the qualified mcp__email__list_email_accounts call that the
    # MCP read-only filter deliberately allows.
    "list_email_accounts",
    "list_emails",
    "read_email",
    # Explicitly read-only rather than allowed-by-omission: this PR makes
    # every BUILTIN_EMAIL_TOOLS name fence-taggable, so each one must be
    # classified — see the plan-mode partition test in
    # tests/test_email_registry_sync.py.
    "search_emails",
    "scan_email_unsubscribes",
    "list_served_models",
    "list_downloads",
    "list_cached_models",
    "search_hf_models",
    "list_serve_presets",
    "list_cookbook_servers",
    "resolve_contact",
    "chat_with_model",
    "ask_teacher",
    # A planning mode that cannot ask what you meant is planning blind (P6-14).
    # `ask_user` mutates nothing — it pauses and waits for a person — so it
    # belongs here on the same grounds as every other read-only entry.
    "ask_user",
}


# The agent's tool gate is a DENYLIST: execute_tool_block blocks any tool whose
# name is in `disabled_tools`. Plan mode's policy is the opposite — an allowlist
# (PLAN_MODE_READONLY_TOOLS). To apply an allowlist through a denylist, plan mode
# returns the inverse: every known tool name minus the allowlist.
#
# Known tool names come from FUNCTION_TOOL_SCHEMAS, but that source is imperfect:
# some tools are only XML-invocable (e.g. manage_notes, generate_image) and never
# appear there, and the import can fail outright. Either gap would drop a mutating
# tool from the subtraction and silently leave it enabled. This set is the static
# backstop for both: union it in so known mutators are always subtracted, and so a
# failed import still blocks them (fail closed, never open). Only mutators belong
# here — read-only tools are covered by the allowlist. Keep in sync when adding
# new mutating tools.
_PLAN_MODE_KNOWN_MUTATORS = {
    "write_file", "edit_file", "apply_patch", "todowrite",
    "create_document", "edit_document", "update_document",
    "suggest_document", "manage_documents", "create_session", "manage_session",
    "send_to_session", "pipeline", "manage_memory", "manage_skills",
    "manage_tasks", "manage_notes", "manage_endpoints", "manage_mcp",
    "manage_webhooks", "manage_tokens", "manage_settings", "manage_contact",
    "manage_calendar", "api_call", "app_api", "ui_control",
    "send_email", "reply_to_email", "bulk_email", "delete_email",
    "archive_email", "mark_email_read", "unsubscribe_email",
    # The draft tools create documents and download_attachment writes to
    # disk — mutating. They have no native schemas (yet), so without these
    # static entries plan-mode safety for their bare fence tags would depend
    # entirely on the MCP read-only inventory being present and current.
    "draft_email", "draft_email_reply", "ai_draft_email_reply",
    "download_attachment",
    "download_model", "serve_model",
    "stop_served_model", "cancel_download", "adopt_served_model", "serve_preset",
    "generate_image", "edit_image", "trigger_research", "manage_research",
    # Shell is never read-only-safe; block it explicitly so it stays out of plan
    # mode even if the schema list fails to load.
    "bash", "python",
    # Controls shell processes (kill); plan mode can't run bash anyway.
    "manage_bg_jobs",
}


# ── Feature flags, made real (`H05`) ────────────────────────────────────────
#
# `DEFAULT_FEATURES` has eight switches. Before this, **seven of them did
# nothing**: `load_features()` had three callers and all three were read-write
# plumbing, so no server-side code branched on any flag. Enforcement was
# entirely client-side — `static/app.js` hid four elements — which meant an
# admin who turned off Deep Research got a success response, the toggle stayed
# off, and the feature was still there. **And the agent could call the tool
# regardless**, which is the half that matters: a flag the model does not honour
# is not a control, it is a label.
#
# THIS IS A DENYLIST CONTRIBUTOR, NOT A SECOND GATE.
#
# `execute_tool_block` already blocks anything in `disabled_tools`, and
# `plan_mode_disabled_tools()` above is the precedent for computing that set
# from a policy rather than storing it. A second enforcement path would be a
# second thing that can disagree with the first (`Law 14`), so this returns
# names into the same set and inherits its tests, its cache key and its
# fail-closed behaviour.
#
# `sensitive_filter` is deliberately absent from this map and that is not an
# oversight. It is a DISPLAY filter — it redacts what is shown, it does not
# remove a capability — so there is no tool whose absence would implement it.
# Mapping it to something would be inventing a meaning the switch never had.
_FEATURE_TOOLS: dict = {
    "web_search": {"web_search"},
    "web_fetch": {"web_fetch"},
    "deep_research": {"trigger_research", "manage_research"},
    "memory": {"manage_memory"},
    "document_editor": {
        "create_document", "edit_document", "update_document",
        "suggest_document", "manage_documents",
    },
    "rag": {"manage_rag"},  # see _FEATURE_NOTES
    "gallery": {"generate_image", "edit_image"},
}

# Why a flag maps to nothing, written down rather than left as an empty set for
# the next reader to guess at.
_FEATURE_NOTES = {
    "rag": (
        "Retrieval proper is not a tool the model calls — it is context "
        "assembled before the turn, and turning that off is a check at the "
        "retrieval site, not a name in a denylist. That half is still honoured "
        "there and in the routes. `B66` added the half that does belong here: "
        "`manage_rag` IS a tool the model calls, and it writes to and searches "
        "the same store, so a switch that stops retrieval and leaves the agent "
        "free to write to and read the index was never the whole switch."
    ),
    "sensitive_filter": (
        "A display filter, not a capability. It redacts what is shown and "
        "removes nothing the agent can do."
    ),
}


def feature_disabled_tools(features: Optional[dict] = None) -> Set[str]:
    """Tool names to add to the denylist because their feature is switched off.

    Reads `load_features()` when not given a mapping. Fails **open** on a read
    error and closed on nothing: a features file that will not parse must not
    silently disable half the product, and `load_features` already falls back to
    the defaults on every error it can see.
    """
    if features is None:
        try:
            from src.settings import load_features
            features = load_features()
        except Exception as exc:
            logger.warning("Unable to read feature flags for tool gating: %s", exc)
            return set()
    if not isinstance(features, dict):
        return set()
    blocked: Set[str] = set()
    for flag, names in _FEATURE_TOOLS.items():
        if flag in features and not features.get(flag):
            blocked |= set(names)
    return blocked


def plan_mode_disabled_tools() -> Set[str]:
    """Tool names to add to the denylist in plan mode.

    Plan mode allows only PLAN_MODE_READONLY_TOOLS. The gate is a denylist, so
    return the inverse: every known tool name minus the allowlist. Known names
    come from the function-tool schemas, backstopped by _PLAN_MODE_KNOWN_MUTATORS
    (see above) so XML-only tools and a failed schema import can't leave a mutator
    enabled. MCP tools are handled separately — the loop drops the MCP manager
    entirely in plan mode."""
    try:
        # agent_tools / tool_parsing / tool_schemas form a mutually-circular
        # cluster that only resolves cleanly when entered via agent_tools.
        # Import it first so the lazy schema import works even from a cold
        # import (e.g. tests) — not just after the app has wired everything up.
        import src.agent_tools  # noqa: F401
        from src.tool_schemas import FUNCTION_TOOL_SCHEMAS

        all_names = {
            (t.get("function") or {}).get("name")
            for t in FUNCTION_TOOL_SCHEMAS
        }
        all_names.discard(None)
    except Exception as exc:
        logger.warning("Unable to load tool schemas for plan-mode gating: %s", exc)
        all_names = set()
    # Subtract the allowlist from all known tool names (schema-derived plus the
    # static mutator backstop). Fail closed: if the schema import failed above,
    # the backstop alone still blocks known mutators.
    return (all_names | _PLAN_MODE_KNOWN_MUTATORS) - PLAN_MODE_READONLY_TOOLS


def email_tool_policy_names(tool_name: str) -> frozenset:
    """All policy-equivalent spellings of a tool name.

    A bare built-in email tool name and its MCP-qualified mcp__email__<name>
    form dispatch to the same email server tool, but policy sources spell
    them either way — plan mode and the MCP settings toggle write qualified
    names into denylists, chat-level toggles write bare ones. Every gate must
    match against the full alias set, or a call in one spelling slips past a
    denylist entry written in the other. Non-email names alias only to
    themselves.
    """
    if not isinstance(tool_name, str):
        return frozenset((tool_name,))
    if tool_name in BUILTIN_EMAIL_TOOLS:
        return frozenset((tool_name, f"mcp__email__{tool_name}"))
    if tool_name.startswith("mcp__email__"):
        bare = tool_name[len("mcp__email__"):]
        if bare in BUILTIN_EMAIL_TOOLS:
            return frozenset((tool_name, bare))
    return frozenset((tool_name,))


def is_public_blocked_tool(tool_name: Optional[str]) -> bool:
    """Return True when a non-admin/public user must not execute this tool.

    This is a security gate, so it fails CLOSED: a malformed non-string tool
    name can't be matched against the blocklist or the ``mcp__`` namespace, so
    it is treated as blocked rather than silently allowed through. ``None`` /
    empty string means there is no tool to gate.
    """
    if tool_name is None or tool_name == "":
        return False
    if not isinstance(tool_name, str):
        return True
    return tool_name in NON_ADMIN_BLOCKED_TOOLS or tool_name.startswith("mcp__")


def owner_is_admin_or_single_user(owner: Optional[str]) -> bool:
    """Return True for admins, or in intentional single-user mode.

    Single-user mode means the operator explicitly disabled auth
    (``AUTH_ENABLED=false``) — the local/self-host default where the owner has
    full access to their own box.

    The pre-setup window (auth ENABLED but no admin created yet) is treated as
    NON-admin: returning True there would hand server-execution tools
    (``bash``/``python``) to any caller before setup completes. The auth
    middleware already 401s ``/api/`` requests pre-setup, so this is
    defense-in-depth for callers that bypass it (e.g. trusted loopback).
    """
    try:
        from src.auth_helpers import _auth_disabled

        if _auth_disabled():
            return True

        from core.auth import AuthManager

        auth = AuthManager()
        if not auth.is_configured:
            return False
        return bool(owner and auth.is_admin(owner))
    except Exception as exc:
        logger.warning("Unable to evaluate owner admin status: %s", exc)
        return False


def blocked_tools_for_owner(owner: Optional[str]) -> Set[str]:
    """Tools to hide/disable for this owner under public-user policy."""
    if owner_is_admin_or_single_user(owner):
        return set()
    return set(NON_ADMIN_BLOCKED_TOOLS)


def delegated_credential_blocked_tools() -> Set[str]:
    """Tools an agent run driven by a bearer API token must not reach.

    `B70`. **Deliberately not owner-dependent.** `blocked_tools_for_owner` asks
    whether the OWNER is an admin, and for a token that question is always
    answered yes — minting is an admin-only action, so the empty set comes back
    for every token in existence. A token is a long-lived credential the owner
    hands to a third party, so it is capped at the non-admin policy no matter
    who minted it.
    """
    return set(NON_ADMIN_BLOCKED_TOOLS)
