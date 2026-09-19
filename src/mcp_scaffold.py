# SPDX-License-Identifier: AGPL-3.0-or-later
"""`P8-47` — make somebody a working MCP server, on the data volume.

**Why this module exists rather than a template in `mcp_servers/`.** The source
tree is baked into the image and nothing bind-mounts it (`Dockerfile`, and
`docker-compose.yml:7` mounts `${APP_DATA_DIR:-./data}:/app/data` and nothing
else). A file written next to `mcp_servers/memory_server.py` therefore lives
until the next `docker compose pull` and then is not there any more, while the
row in `mcp_servers` that points at it survives — the database is on the volume.
So a generated server is written under `DATA_DIR`, and it cannot be a built-in:
`src/builtin_mcp.py:_BUILTIN_SERVERS` is a fixed map of app-root-relative script
paths, connected at startup, and adding to it means editing the image.

**Which makes the registration an absolute path, which the assistant may not
do, on purpose.** A generated Python server is `<interpreter> <abs path>`, and
`_validate_mcp_command` (`src/agent_tools/admin_tools.py`) refuses both halves
of that on the `manage_mcp` agent path: an interpreter is in
`_MCP_DENIED_COMMANDS`, and a command with a `/` in it is refused outright. That
is the fix for a reported RCE (issue #438) — prompt-injected text reaching a
subprocess spawn — it is `FORBIDDEN.md` Part 2, and **nothing here weakens it**.
This module does not register anything at all. It writes the files, proves they
work by starting them, and hands back the exact fields for the admin route
(`POST /api/mcp/servers`, `require_admin`), which is the trusted door and always
was. `refusal_on_the_agent_path()` asks that same validator for the sentence it
would print, so the explanation cannot drift from the rule (`Law 13`).

**What "working" means here, and how it is checked.** `verify_server` starts the
generated file through `McpManager.connect_server` — the same method the app
uses, and the same one `pantheon-mcp tools` uses — completes the MCP handshake,
lists the tools and disconnects. A scaffold that only writes a file cannot tell
you whether the file runs.

Public surface:

    scaffold_root()                 where generated servers live
    create_server(name, tools=…)    write one; refuses to overwrite
    verify_server(name)             start it, list its tools, stop it  (async)
    registration_for(name)          the admin route's fields, exactly
    refusal_on_the_agent_path(reg)  why the assistant cannot register it
    list_servers()                  what has been generated here
    main(argv)                      the CLI behind `scripts/pantheon-mcp-new`
"""

from __future__ import annotations

import json
import keyword
import os
import re
import sys
from typing import Any, Dict, List, Optional, Sequence

__all__ = [
    "ScaffoldError",
    "scaffold_root",
    "normalise_server_name",
    "normalise_tool_name",
    "server_dir",
    "list_servers",
    "create_server",
    "registration_for",
    "refusal_on_the_agent_path",
    "verify_server",
    "main",
]


class ScaffoldError(ValueError):
    """A refusal a person is meant to read. Carries no traceback worth showing."""


# The directory, under DATA_DIR, that generated servers live in. `DATA_DIR` is
# the volume; see the module docstring for why this is not `mcp_servers/`.
SCAFFOLD_SUBDIR = "mcp_servers"

SERVER_FILENAME = "server.py"
README_FILENAME = "README.md"

# A generated directory name is also part of an absolute path that an admin
# later registers as a command argument, so it is constrained rather than
# escaped: lowercase, digits and single dashes, first character alphanumeric.
_NAME_RE = re.compile(r"^[a-z0-9][a-z0-9-]{0,39}$")

# A tool name becomes a Python function name in the generated file AND the tail
# of `mcp__{server_id}__{tool_name}`, whose sole parse in this repo is one
# `split("__", 2)` (`P8-44`). A tool called `a__b` would route a call to the
# wrong server, so a double underscore is refused here even though MCP itself
# allows it. `FORBIDDEN.md` Part 1 pins that name shape.
_TOOL_RE = re.compile(r"^[a-z][a-z0-9_]{0,47}$")

# Names the generated module already binds. A tool called `call_tool` would
# shadow the dispatcher decorated three lines below it, and the server would
# answer every call with the last definition to win.
_RESERVED_TOOL_NAMES = frozenset({
    "asyncio", "json", "main", "server", "stdio_server", "list_tools",
    "call_tool", "Server", "Tool", "TextContent", "TOOLS", "HANDLERS",
    "SERVER_NAME", "SERVER_DESCRIPTION",
})

MAX_TOOLS = 12
MAX_DESCRIPTION_CHARS = 500

# The one tool a scaffold with no `--tool` gets. It is deliberately trivial and
# deliberately real: it answers, so the person sees the whole chain work before
# they have written anything, and it is the shape they edit.
DEFAULT_TOOL_NAME = "echo"


# ---------------------------------------------------------------------------
# Paths
# ---------------------------------------------------------------------------

def scaffold_root(data_dir: Optional[str] = None) -> str:
    """Absolute path of the directory generated servers are written into.

    `data_dir` exists for tests and for an operator with more than one volume;
    it is not read from the environment, because `PANTHEON_DATA_DIR` is already
    the one place that decision is made (`src/constants.py:33`).
    """
    if data_dir is None:
        from src.constants import DATA_DIR
        data_dir = DATA_DIR
    return os.path.abspath(os.path.join(data_dir, SCAFFOLD_SUBDIR))


def normalise_server_name(raw: Any) -> str:
    """The directory name for `raw`, or raise.

    Runs the same `slugify` the skill store uses on a skill's directory name
    (`Law 14`), then holds it to `_NAME_RE`. `slugify` maps every non-`[a-z0-9]`
    run to `-`, so `../../etc` arrives as `etc` before the regex sees it;
    `server_dir` still realpath-contains the result, because a name check and a
    containment check protect against different mistakes.
    """
    from services.memory.skill_format import slugify

    text = str(raw or "").strip()
    if not text:
        raise ScaffoldError(
            "give the server a name — `pantheon-mcp-new weather`. It becomes the "
            "folder it lives in and the name you will see in Settings."
        )
    slug = slugify(text, fallback="")[:40].strip("-")
    if not _NAME_RE.match(slug):
        raise ScaffoldError(
            f"{text!r} does not work as a server name. Use lowercase letters, "
            "digits and dashes, up to 40 characters — `weather`, `home-assistant`, "
            "`jira2`."
        )
    return slug


def normalise_tool_name(raw: Any) -> str:
    """The function name for a tool, or raise."""
    name = str(raw or "").strip()
    if not name:
        raise ScaffoldError("a tool needs a name — `--tool get_forecast`.")
    if not _TOOL_RE.match(name):
        raise ScaffoldError(
            f"{name!r} does not work as a tool name. Use a lowercase word, "
            "digits and single underscores, starting with a letter — "
            "`get_forecast`, `send_alert`, `search2`."
        )
    if "__" in name:
        raise ScaffoldError(
            f"{name!r} has two underscores in a row. Pantheon addresses an MCP "
            "tool as mcp__<server>__<tool> and splits on that, so a tool with "
            "`__` inside it would be read as belonging to another server."
        )
    if keyword.iskeyword(name) or name in _RESERVED_TOOL_NAMES:
        raise ScaffoldError(
            f"{name!r} is already used by the generated file itself (or is a "
            "Python keyword), so the tool would overwrite the wiring. Pick "
            "another word."
        )
    return name


def server_dir(name: str, *, data_dir: Optional[str] = None) -> str:
    """Absolute path of one generated server's directory.

    The realpath of the result must sit inside the realpath of the root. This
    is belt to `_NAME_RE`'s braces and catches the case the regex cannot see: a
    symlink planted in the scaffold root pointing somewhere else.
    """
    root = scaffold_root(data_dir)
    slug = normalise_server_name(name)
    path = os.path.join(root, slug)
    real_root = os.path.realpath(root)
    real_path = os.path.realpath(path)
    if real_path != real_root and not real_path.startswith(real_root + os.sep):
        raise ScaffoldError(
            f"{slug!r} resolves outside {root} and will not be written."
        )
    return path


def list_servers(*, data_dir: Optional[str] = None) -> List[Dict[str, Any]]:
    """Every generated server on this volume: name, path, whether it still has
    a `server.py`, and when it was last edited."""
    root = scaffold_root(data_dir)
    out: List[Dict[str, Any]] = []
    try:
        entries = sorted(os.listdir(root))
    except FileNotFoundError:
        # Nothing has been generated on this install yet. That is the ordinary
        # first state, not a failure, and an empty list says it.
        return out
    for entry in entries:
        path = os.path.join(root, entry)
        if not os.path.isdir(path):
            continue
        source = os.path.join(path, SERVER_FILENAME)
        record: Dict[str, Any] = {
            "name": entry,
            "directory": path,
            "has_server_py": os.path.isfile(source),
        }
        try:
            record["modified"] = round(os.path.getmtime(source), 3)
        except OSError:
            # Only reachable when `server.py` is missing or unreadable, which
            # `has_server_py` already reports. No second way of saying it.
            record["modified"] = None
        out.append(record)
    return out


# ---------------------------------------------------------------------------
# Rendering
# ---------------------------------------------------------------------------

def _py_literal(text: Any) -> str:
    """A Python string literal for arbitrary text.

    `json.dumps` is the generator rather than `repr` because its output is a
    double-quoted literal with every control character, backslash and quote
    escaped and no raw newline possible, and Python reads `\\uXXXX` the same way
    JSON writes it. So nothing a person types into `--description` can close the
    literal, open a comment, or add a statement to the generated file. Pinned by
    `tests/test_a_generated_mcp_server_runs.py::test_hostile_text_*`.
    """
    return json.dumps(str(text if text is not None else ""), ensure_ascii=True)


_TOOL_BLOCK = '''    Tool(
        name={name},
        description={description},
        inputSchema={{
            "type": "object",
            "properties": {{
                "text": {{
                    "type": "string",
                    "description": {arg_description},
                }},
            }},
            "required": ["text"],
        }},
    ),
'''

_HANDLER_BLOCK = '''
async def {fn}(arguments: dict) -> str:
    """{fn} — replace the body. Whatever you return becomes the tool's answer."""
    text = arguments.get("text", "")

    # ---- your code goes here -------------------------------------------
    answer = "{fn} has not been written yet. It was called with text=" + repr(text)
    # --------------------------------------------------------------------

    return answer

'''


def render_server_py(name: str, tools: Sequence[str], description: str = "") -> str:
    """The generated `server.py`, as text."""
    tool_entries = "".join(
        _TOOL_BLOCK.format(
            name=_py_literal(tool),
            description=_py_literal(
                f"TODO: say what {tool} does, in the words someone would use when "
                f"they want it. The assistant reads this to decide whether to call it."
            ),
            arg_description=_py_literal(
                f"TODO: what {tool} needs. Rename it, add more, delete this one."
            ),
        )
        for tool in tools
    )
    handlers = "".join(_HANDLER_BLOCK.format(fn=tool) for tool in tools)
    handler_map = "".join(f'    {_py_literal(t)}: {t},\n' for t in tools)

    return f'''#!/usr/bin/env python3
"""An MCP server, made by `pantheon-mcp-new`.

Two things to know before you edit it.

1. It talks over stdin/stdout. **Never `print()` in here** — that is the wire.
   Write to `sys.stderr` if you want to see something while it runs.
2. It is yours. Nothing regenerates or overwrites this file.

Run `pantheon-mcp-new {name} --check` after an edit: it starts this file the
same way Pantheon does and tells you whether it still works.
"""

from __future__ import annotations

import asyncio
import json

from mcp.server import Server
from mcp.server.stdio import stdio_server
from mcp.types import TextContent, Tool

SERVER_NAME = {_py_literal(name)}
SERVER_DESCRIPTION = {_py_literal(description)}


# ===========================================================================
# 1. WHAT THIS SERVER OFFERS
#    One entry per tool. `name` is what the assistant types; `description` is
#    how it decides to. `inputSchema` is what the tool takes.
# ===========================================================================
TOOLS = [
{tool_entries}]


# ===========================================================================
# 2. WHAT THEY DO
#    One function per tool, named after it. Return a string, or anything
#    JSON-serialisable.
# ===========================================================================
{handlers}
HANDLERS = {{
{handler_map}}}


# ===========================================================================
# 3. THE WIRING. You should not need to change anything below this line.
# ===========================================================================
server = Server(SERVER_NAME)


@server.list_tools()
async def list_tools() -> list[Tool]:
    return TOOLS


@server.call_tool()
async def call_tool(name: str, arguments: dict) -> list[TextContent]:
    handler = HANDLERS.get(name)
    if handler is None:
        return [TextContent(type="text", text="Unknown tool: " + str(name))]
    try:
        result = await handler(arguments or {{}})
    except Exception as exc:  # a tool that raises must answer, not kill the server
        result = "{{}} failed: {{}}: {{}}".format(name, type(exc).__name__, exc)
    if not isinstance(result, str):
        result = json.dumps(result, default=str, ensure_ascii=False)
    return [TextContent(type="text", text=result)]


async def main() -> None:
    async with stdio_server() as (read_stream, write_stream):
        await server.run(
            read_stream, write_stream, server.create_initialization_options()
        )


if __name__ == "__main__":
    asyncio.run(main())
'''


def render_readme(
    name: str,
    tools: Sequence[str],
    description: str,
    registration: Dict[str, Any],
    refusal: str,
) -> str:
    """The `README.md` written beside the server — the same words the CLI
    prints, kept where the person will be when they come back to it."""
    args_json = json.dumps(registration["args"])
    tool_lines = "\n".join(f"- `{t}`" for t in tools)
    return f"""# {name}

An MCP server. {description or "No description was given when it was made."}

Pantheon did not register it — registering a server means running a program, so
that is an administrator's decision and it is made in one of the two places
below. Nothing has been started for you.

## What you got

- `{SERVER_FILENAME}` — the server. Edit it. Nothing regenerates it.
- This file.

Tools it offers right now:

{tool_lines}

Each one answers with a placeholder that repeats its argument back, so you can
see the whole chain work before you write anything. Section 2 of
`{SERVER_FILENAME}` is where the real code goes.

## Register it — in the browser

**Settings → Integrations → + → MCP Tool Server.** You need to be an
administrator.

| Field | What to put in it |
|---|---|
| Name | `{registration['name']}` |
| Transport | `{registration['transport']}` |
| Command | `{registration['command']}` |
| Arguments | `{registration['args'][0]}` (one box) |
| Environment | leave empty |

The form shows you the command line it will run before you save it. It should
read exactly `{registration['command']} {registration['args'][0]}`.

## Register it — on the shell

    pantheon-mcp add --name {registration['name']} --transport stdio \\
        --command {registration['command']} \\
        --args '{args_json}'

That writes the row directly and does not tell the running app about it —
reconnect it in Settings, or restart Pantheon, before the tools appear.

## Why the assistant cannot do this for you

Ask it and it will refuse, with this:

> {refusal}

That refusal is deliberate and is not a bug to work around. Text the assistant
reads — a web page, an email, a skill somebody shared — can reach `manage_mcp`,
and a registration is a program to run, so the agent's own path allows neither
an interpreter nor a command containing a path. Registering is an
administrator's action and lives behind an administrator's door.

## Things that bite

- **Never `print()` in `{SERVER_FILENAME}`.** stdout is the protocol. Use
  `sys.stderr`.
- **Check your work with `pantheon-mcp-new {name} --check`.** It starts the
  file exactly as Pantheon does and tells you what broke.
- **After you edit it, reconnect the server** (Settings → Integrations, or
  `POST /api/mcp/servers/{{id}}/reconnect`). A running server is a running
  process; it does not re-read the file.
- **If your tool needs an environment variable** — an API key, a proxy setting
  — put it in the Environment box when you register. A server registered with
  *no* environment variables at all starts with a minimal environment, so
  `PYTHONPATH`, `NODE_PATH` and proxy variables are not inherited from
  Pantheon.
- **This folder is on the data volume**, so it survives an image update. A file
  you put next to Pantheon's own `mcp_servers/` would not.
"""


# ---------------------------------------------------------------------------
# Creating
# ---------------------------------------------------------------------------

def create_server(
    name: str,
    *,
    tools: Optional[Sequence[str]] = None,
    description: str = "",
    data_dir: Optional[str] = None,
    python: Optional[str] = None,
) -> Dict[str, Any]:
    """Write a new server. Returns what was written and how to register it.

    Refuses if the directory already exists, and there is no `--force`: the
    only thing an overwrite could do here is destroy code somebody wrote.
    """
    slug = normalise_server_name(name)
    wanted = list(tools) if tools else [DEFAULT_TOOL_NAME]
    if len(wanted) > MAX_TOOLS:
        raise ScaffoldError(
            f"{len(wanted)} tools is more than this makes in one go (max "
            f"{MAX_TOOLS}). Generate the first few and add the rest by hand — "
            "section 1 and section 2 of the file are the two places."
        )
    seen: List[str] = []
    for raw in wanted:
        tool = normalise_tool_name(raw)
        if tool in seen:
            raise ScaffoldError(f"you asked for a tool called {tool!r} twice.")
        seen.append(tool)

    text = str(description or "").strip()
    if len(text) > MAX_DESCRIPTION_CHARS:
        raise ScaffoldError(
            f"the description is {len(text)} characters; keep it under "
            f"{MAX_DESCRIPTION_CHARS}. It is a sentence, not the manual — the "
            "manual is the README next to the server."
        )

    target = server_dir(slug, data_dir=data_dir)
    if os.path.exists(target):
        raise ScaffoldError(
            f"{slug!r} already exists at {target}. Nothing was changed — this "
            "never overwrites a server, because the only thing that could "
            "destroy is code you wrote. Pick another name, or delete that "
            "folder yourself if you meant to start over."
        )

    os.makedirs(target, exist_ok=False)
    source_path = os.path.join(target, SERVER_FILENAME)
    with open(source_path, "w", encoding="utf-8") as handle:
        handle.write(render_server_py(slug, seen, text))
    os.chmod(source_path, 0o700)

    registration = registration_for(slug, data_dir=data_dir, python=python)
    refusal = refusal_on_the_agent_path(registration)
    readme_path = os.path.join(target, README_FILENAME)
    with open(readme_path, "w", encoding="utf-8") as handle:
        handle.write(render_readme(slug, seen, text, registration, refusal))

    return {
        "name": slug,
        "directory": target,
        "description": text,
        "tools": seen,
        "files": {
            SERVER_FILENAME: os.path.getsize(source_path),
            README_FILENAME: os.path.getsize(readme_path),
        },
        "register": registration,
        "the_assistant_cannot_do_this_for_you": refusal,
    }


def registration_for(
    name: str,
    *,
    data_dir: Optional[str] = None,
    python: Optional[str] = None,
) -> Dict[str, Any]:
    """Exactly what `POST /api/mcp/servers` wants, for this generated server.

    `command` is the interpreter running Pantheon (`sys.executable`), because
    that is the one certain to have the `mcp` package the generated file
    imports. `scripts/pantheon` execs subcommands under the project venv, so a
    CLI run picks up the app's interpreter rather than whatever `python3` is on
    PATH. `python=` overrides it when the two really do differ.
    """
    slug = normalise_server_name(name)
    target = server_dir(slug, data_dir=data_dir)
    interpreter = str(python or sys.executable or "python3")
    return {
        "where": "Settings → Integrations → + → MCP Tool Server (administrators only)",
        "route": "POST /api/mcp/servers",
        "name": slug,
        "transport": "stdio",
        "command": interpreter,
        "args": [os.path.join(target, SERVER_FILENAME)],
        "env": {},
    }


def refusal_on_the_agent_path(registration: Dict[str, Any]) -> str:
    """The sentence `manage_mcp` would answer with, asked of `manage_mcp` itself.

    Not a copy of the rule. `_validate_mcp_command` is the rule (`Law 13`), so
    if the allowlist moves, or an operator opts an interpreter in through
    `PANTHEON_MCP_ALLOWED_COMMANDS`, this text moves with it — including to
    "nothing: the agent path would accept this", which is the honest answer and
    the one a stale hand-written sentence could never give.
    """
    try:
        from src.agent_tools.admin_tools import _validate_mcp_command
    except Exception:  # pragma: no cover - only if the tool registry is absent
        # Import failure here is a broken install, not a scaffold problem. Say
        # the rule's shape rather than inventing its wording.
        return (
            "The assistant's own manage_mcp tool refuses to register a server "
            "whose command is an interpreter or contains a path. Use the admin "
            "route above."
        )
    error = _validate_mcp_command(
        registration.get("command"),
        registration.get("args") or [],
        registration.get("env") or {},
    )
    if not error:
        return (
            "Nothing — on this install manage_mcp would accept this "
            "registration. It is still an administrator's decision, so the "
            "admin route above is the one to use."
        )
    return f"manage_mcp: refused unsafe server registration: {error}"


# ---------------------------------------------------------------------------
# Proving it works
# ---------------------------------------------------------------------------

async def verify_server(
    name: str,
    *,
    data_dir: Optional[str] = None,
    python: Optional[str] = None,
    timeout: float = 30.0,
) -> Dict[str, Any]:
    """Start the generated server, complete the MCP handshake, list its tools,
    stop it. Returns `{started, tools, error}` and never raises for a server
    that simply does not work — that is the answer, not an exception.

    This goes through `McpManager.connect_server`, which is what the app calls
    and what `pantheon-mcp tools` calls (`Law 14`). A second launcher written
    here would be a second opinion about whether a server runs.
    """
    import asyncio

    slug = normalise_server_name(name)
    target = server_dir(slug, data_dir=data_dir)
    source = os.path.join(target, SERVER_FILENAME)
    if not os.path.isfile(source):
        return {
            "started": False,
            "tools": [],
            "error": f"there is no {SERVER_FILENAME} at {target}.",
        }

    from src.mcp_manager import McpManager

    registration = registration_for(slug, data_dir=data_dir, python=python)
    manager = McpManager()
    probe_id = f"scaffold-{slug}"
    try:
        # `asyncio.timeout`, not `asyncio.wait_for`. `wait_for` wraps the
        # coroutine in a Task, so `connect_server`'s AsyncExitStack is entered
        # in that task and closed here in ours — anyio then refuses the exit
        # with "Attempted to exit cancel scope in a different task than it was
        # entered in", and every run of this ended with that line above an
        # otherwise successful result. Measured 2026-09-19.
        async with asyncio.timeout(timeout):
            started = await manager.connect_server(
                server_id=probe_id,
                name=slug,
                transport="stdio",
                command=registration["command"],
                args=registration["args"],
                env=registration["env"],
            )
    except asyncio.TimeoutError:
        return {
            "started": False,
            "tools": [],
            "error": (
                f"it did not answer within {timeout:g}s. An MCP server that "
                "writes to stdout — a print(), a banner, a progress bar — "
                "corrupts the protocol and hangs exactly like this."
            ),
        }
    try:
        if not started:
            status = manager.get_server_status(probe_id)
            reason = status.get("error") or status.get("status") or "it did not start."
            # The SDK forwards the child's stderr to this process's stderr, so
            # a traceback from the server has already been printed by the time
            # we get here — and "Connection closed" on its own reads like a
            # network fault rather than the SyntaxError three lines above it.
            return {
                "started": False,
                "tools": [],
                "error": (
                    f"{reason} — anything the server printed while failing went "
                    "to this process's standard error, above this."
                ),
            }
        tools = sorted(
            tool["name"] for tool in manager.get_all_tools()
            if tool.get("server_id") == probe_id
        )
        return {"started": True, "tools": tools, "error": None}
    finally:
        try:
            await manager.disconnect_server(probe_id)
        except Exception:
            # The probe process is being torn down either way; a failure to
            # close it cleanly must not turn a working server into a failed
            # check. The subprocess dies with this one.
            pass


# ---------------------------------------------------------------------------
# The door
# ---------------------------------------------------------------------------

def _next_steps(record: Dict[str, Any], self_test: Optional[Dict[str, Any]]) -> List[str]:
    reg = record["register"]
    source = os.path.join(record["directory"], SERVER_FILENAME)
    if self_test and not self_test.get("started") and self_test.get("ran", True):
        # A server that does not start is the only thing worth saying. Telling
        # somebody to register it, or where to write their tool, on top of a
        # failure is three instructions when one is true.
        return [
            "It did not start, so do not register it yet: "
            + str(self_test.get("error")),
            f"Fix {source}, then run `pantheon-mcp-new {record['name']} --check` again.",
        ]
    steps: List[str] = []
    if self_test and not self_test.get("ran", True):
        steps.append(
            "It was not started, so nothing here has been proved. Run "
            f"`pantheon-mcp-new {record['name']} --check` to start it."
        )
    else:
        steps.append(
            f"Register it: {reg['where']} — Command `{reg['command']}`, "
            f"Arguments `{reg['args'][0]}`, Environment empty."
        )
    steps.append(
        f"Then open {source} and write your tool. Section 2 is the only part "
        "you need."
    )
    steps.append(
        f"After every edit: `pantheon-mcp-new {record['name']} --check`, then "
        "reconnect the server in Settings so the running app picks it up."
    )
    return steps


def _build_parser():
    import argparse

    parser = argparse.ArgumentParser(
        prog="pantheon-mcp-new",
        description=(
            "Make a working MCP server and tell you how to register it. An MCP "
            "server is a small program that gives the assistant new tools. This "
            "writes one onto the data volume, starts it to prove it runs, and "
            "prints the three fields you paste into Settings."
        ),
        epilog=(
            "examples:\n"
            "  pantheon-mcp-new weather\n"
            "  pantheon-mcp-new weather --tool get_forecast --tool get_current\n"
            "  pantheon-mcp-new weather --check      # start it again after an edit\n"
            "  pantheon-mcp-new --list               # what is on this volume\n"
        ),
        formatter_class=argparse.RawDescriptionHelpFormatter,
    )
    parser.add_argument(
        "name", nargs="?",
        help="what to call it: lowercase letters, digits and dashes (`weather`)",
    )
    parser.add_argument(
        "--tool", action="append", dest="tools", metavar="NAME",
        help="a tool it should offer; repeat for more (default: one called "
             f"`{DEFAULT_TOOL_NAME}` you can rename)",
    )
    parser.add_argument(
        "--description", default="",
        help="one sentence about what the server is for",
    )
    parser.add_argument(
        "--python", default=None, metavar="PATH",
        help="the interpreter to register it under (default: the one running this)",
    )
    parser.add_argument(
        "--check", action="store_true",
        help="do not create anything — start the server of this name that is "
             "already there, and say whether it works",
    )
    parser.add_argument(
        "--no-self-test", action="store_true",
        help="write the files without starting them (faster; proves less)",
    )
    parser.add_argument(
        "--list", action="store_true", dest="list_all",
        help="list the generated servers on this volume",
    )
    parser.add_argument(
        "--data-dir", default=None,
        help="write under a different data directory (default: Pantheon's)",
    )
    parser.add_argument("--pretty", action="store_true", help="pretty-print JSON")
    return parser


def _print(payload: Dict[str, Any], pretty: bool) -> None:
    json.dump(
        payload, sys.stdout,
        indent=2 if (pretty or sys.stdout.isatty()) else None,
        default=str, ensure_ascii=False,
    )
    sys.stdout.write("\n")


def main(argv: Optional[Sequence[str]] = None) -> int:
    """`scripts/pantheon-mcp-new`'s whole body. Returns an exit code."""
    import asyncio

    parser = _build_parser()
    args = parser.parse_args(list(argv) if argv is not None else None)

    try:
        if args.list_all:
            servers = list_servers(data_dir=args.data_dir)
            _print({
                "root": scaffold_root(args.data_dir),
                "servers": servers,
                "count": len(servers),
                "note": (
                    "These are generated server directories on the data volume. "
                    "Whether one is registered with Pantheon is a different "
                    "question — `pantheon-mcp list` answers that."
                ),
            }, args.pretty)
            return 0

        if not args.name:
            parser.print_help()
            return 2

        if args.check:
            record = {
                "name": normalise_server_name(args.name),
                "directory": server_dir(args.name, data_dir=args.data_dir),
                "register": registration_for(
                    args.name, data_dir=args.data_dir, python=args.python
                ),
            }
            result = asyncio.run(verify_server(
                args.name, data_dir=args.data_dir, python=args.python
            ))
            record["self_test"] = result
            record["the_assistant_cannot_do_this_for_you"] = \
                refusal_on_the_agent_path(record["register"])
            record["next"] = _next_steps(record, result)
            _print(record, args.pretty)
            return 0 if result.get("started") else 1

        record = create_server(
            args.name,
            tools=args.tools,
            description=args.description,
            data_dir=args.data_dir,
            python=args.python,
        )
        if args.no_self_test:
            result = {"ran": False, "started": None, "tools": [], "error": None}
        else:
            result = asyncio.run(verify_server(
                args.name, data_dir=args.data_dir, python=args.python
            ))
            result["ran"] = True
        record["self_test"] = result
        record["next"] = _next_steps(record, result)
        _print(record, args.pretty)
        return 0 if result.get("started") in (True, None) else 1
    except ScaffoldError as refusal:
        sys.stderr.write(f"error: {refusal}\n")
        return 1


if __name__ == "__main__":
    sys.exit(main())
