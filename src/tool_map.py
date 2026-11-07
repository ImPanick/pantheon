# SPDX-License-Identifier: AGPL-3.0-or-later
"""The tool map: every tool in a few words, and when to reach for it.

The owner, 2026-11-07, after a Gemma 4 12B run that spent three `find_tools`
calls guessing at words ("Virtual Machine", "remote desktop") and then tried
`ui_control open_panel workstation`: *"distinguish in the tool search an
extremely short description of everything... along with where to use said
skills/tools"*.

Two readers, one table:

* the partial-turn notice lists the tools a turn did **not** load, by area, in
  two to five words each (`index_text`), so a small model knows the name
  before it searches — about 400 tokens for the whole suite, and the same
  bytes on every turn of a conversation, so a local server's cached prefix
  holds;
* `find_tools` answers each match with its line here (`brief`) and searches
  these words and `ALSO_KNOWN_AS` besides the register's long descriptions.

Kept tiny on purpose: the earlier slimming took the owner's first message from
~50k tokens of tool input to under 7k for a whole session (2026-11-07), and
this must not undo it. A tool missing here still works; it is listed under
"Other" by name alone.
"""

from __future__ import annotations

from typing import Dict, Iterable, List, Tuple

#: (area, {tool: "what · when"}). Order is the order the notice prints.
AREAS: Tuple[Tuple[str, Dict[str, str]], ...] = (
    # A hint of "" prints the bare name: the name already says it.
    ("Workstation = the Ubuntu desktop/VM", {
        "computer": "see the screen, click, type · any app or site on the workstation desktop",
        "agent_browser": "watchable web browser · open, read and click web pages",
        "network": "is a host reachable from the workstation",
    }),
    ("Files and code", {
        "read_file": "", "write_file": "", "edit_file": "", "apply_patch": "multi-file edit",
        "ls": "", "glob": "find files by name", "grep": "search inside files",
        "bash": "shell", "python": "", "git": "", "host_shell": "command on the host",
        "shell_with_login": "command with a vault login", "get_workspace": "project folder",
        "todowrite": "", "manage_bg_jobs": "",
    }),
    ("Web", {
        "web_search": "", "web_fetch": "read one URL",
        "trigger_research": "deep-research report", "manage_research": "",
    }),
    ("Email", {
        "list_emails": "inbox", "read_email": "", "search_emails": "",
        "draft_email": "unsent", "draft_email_reply": "unsent", "ai_draft_email_reply": "",
        "send_email": "", "reply_to_email": "sends now", "archive_email": "",
        "delete_email": "", "mark_email_read": "", "bulk_email": "", "download_attachment": "",
        "list_email_accounts": "", "scan_email_unsubscribes": "", "unsubscribe_email": "",
    }),
    ("Planner and people", {
        # `B1876`: the room is called Automations and its page the Workbench.
        "manage_calendar": "", "manage_tasks": "scheduled jobs, automations and workflows",
        "manage_notes": "notes, todos, reminders", "manage_contact": "address book",
        "resolve_contact": "a person's email address", "ledger_table": "money",
    }),
    ("Documents and images", {
        "create_document": "editor", "edit_document": "", "update_document": "rewrite",
        "suggest_document": "", "manage_documents": "", "generate_image": "", "edit_image": "",
    }),
    ("Memory, skills and chats", {
        "manage_memory": "facts about the person", "use_skill": "open a how-to",
        "manage_skills": "", "search_chats": "", "read_chat": "", "list_sessions": "chats",
        "manage_session": "rename/archive chats", "create_session": "new chat",
        "send_to_session": "", "manage_rag": "knowledge base",
    }),
    ("Models (Forge)", {
        "list_models": "", "chat_with_model": "ask another model", "ask_teacher": "",
        "pipeline": "chain models", "search_hf_models": "", "download_model": "",
        "list_downloads": "", "cancel_download": "", "list_cached_models": "",
        "serve_model": "", "serve_preset": "", "list_serve_presets": "",
        "list_served_models": "", "stop_served_model": "",
        "tail_serve_output": "why a server failed", "adopt_served_model": "",
        "list_cookbook_servers": "GPU hosts",
    }),
    ("Pantheon itself", {
        "ui_control": "switches, panels: documents/email/notes/settings, theme",
        "manage_settings": "", "app_api": "any other app action", "manage_endpoints": "",
        "manage_mcp": "", "manage_webhooks": "", "manage_tokens": "",
        "api_call": "Home Assistant and other services",
    }),
    ("Vault", {
        "vault_search": "saved logins", "vault_get": "", "vault_unlock": "",
        "connections": "logins this agent may use",
    }),
)

#: Words people use for a tool that its own description does not say.
ALSO_KNOWN_AS: Dict[str, str] = {
    "computer": "vm virtual machine remote desktop workstation ubuntu linux screen mouse "
                "keyboard gui firefox click screenshot phone android",
    "agent_browser": "browser website page url navigate firefox chrome",
    "ui_control": "panel open show toggle switch theme",
    "manage_calendar": "schedule meeting appointment event",
    "manage_notes": "todo reminder checklist",
    "manage_tasks": "automate workbench cron recurring",
    "web_search": "google lookup internet",
}

_BRIEF: Dict[str, str] = {name: hint for _area, tools in AREAS for name, hint in tools.items()}


def brief(name: str) -> str:
    """The tool's line, or `""` when the map has none."""
    return _BRIEF.get(str(name or ""), "")


def search_words(name: str) -> str:
    """What `find_tools` matches besides the register's description."""
    return f"{brief(name)} {ALSO_KNOWN_AS.get(name, '')}".strip()


def _short(hint: str) -> str:
    """The notice's form: the part before the `·`."""
    return hint.split(" · ")[0].strip()


def index_lines(names: Iterable[str]) -> List[str]:
    """One line per area for `names`, in the map's order; MCP tools by server."""
    names = {str(n) for n in (names or ()) if n}
    lines: List[str] = []
    for area, tools in AREAS:
        here = [f"{n} ({_short(h)})" if h else n for n, h in tools.items() if n in names]
        if here:
            lines.append(f"- {area}: " + ", ".join(here))
    mapped = set(_BRIEF)
    mcp = 0
    other: List[str] = []
    for n in sorted(names - mapped):
        if n == "find_tools":
            continue
        if n.startswith("mcp__"):
            mcp += 1      # a server id says nothing; the search reads their words
        else:
            other.append(n)
    if mcp:
        lines.append(f"- Connected MCP servers: {mcp} more tool{'s' if mcp != 1 else ''} — find_tools "
                     "{\"query\": \"<the job>\"} searches them")
    if other:
        lines.append("- Other: " + ", ".join(other))
    return lines


def index_text(names: Iterable[str]) -> str:
    """The notice's index block, or `""` when nothing is left out."""
    lines = index_lines(names)
    if not lines:
        return ""
    return "Not loaded yet:\n" + "\n".join(lines)
