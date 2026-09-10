# SPDX-License-Identifier: AGPL-3.0-or-later
"""Config/integration admin agent tools (TOOL_HANDLERS).

Moved verbatim from tool_implementations.py as part of the tool-registry
migration (#3629, the `admin_tools.py` bullet): manage_endpoints / manage_mcp /
manage_webhooks / manage_tokens / manage_settings, plus manage_mcp's
command-allowlist guard. Each impl keeps its `do_*(content, owner)` shape;
ADMIN_TOOL_HANDLERS wraps them into registry `execute(content, ctx)` adapters
via one factory.
"""
import json
import os
import re
import logging
from typing import Optional, Dict

from src.tool_capabilities import TrustRung

from src.tool_utils import get_mcp_manager, _parse_tool_args
from src.tool_security import BUILTIN_EMAIL_TOOLS

logger = logging.getLogger(__name__)


async def do_manage_endpoints(content: str, owner: Optional[str] = None) -> Dict:
    """Manage model endpoints: list, add, delete, enable, disable."""
    from core.database import SessionLocal, ModelEndpoint
    try:
        args = _parse_tool_args(content)
    except ValueError:
        return {"error": "Invalid JSON arguments", "exit_code": 1}

    action = args.get("action", "list")
    db = SessionLocal()
    try:
        if action == "list":
            eps = db.query(ModelEndpoint).all()
            items = [{"id": e.id, "name": e.name, "base_url": e.base_url,
                       "is_enabled": e.is_enabled} for e in eps]
            return {"response": f"{len(items)} endpoints", "endpoints": items, "exit_code": 0}

        elif action == "add":
            import uuid as _uuid
            name = args.get("name", "")
            base_url = args.get("base_url", "")
            api_key = args.get("api_key", "")
            if not base_url:
                return {"error": "base_url is required", "exit_code": 1}
            eid = str(_uuid.uuid4())[:8]
            from datetime import datetime
            ep = ModelEndpoint(id=eid, name=name or base_url, base_url=base_url,
                               api_key=api_key, is_enabled=True,
                               created_at=datetime.utcnow(), updated_at=datetime.utcnow())
            db.add(ep)
            db.commit()
            return {"response": f"Added endpoint '{name or base_url}' (id: {eid})", "exit_code": 0}

        elif action == "delete":
            eid = args.get("endpoint_id", "")
            ep = db.query(ModelEndpoint).filter(ModelEndpoint.id == eid).first()
            if not ep:
                return {"error": f"Endpoint {eid} not found", "exit_code": 1}
            name = ep.name
            db.delete(ep)
            db.commit()
            return {"response": f"Deleted endpoint '{name}'", "exit_code": 0}

        elif action in ("enable", "disable"):
            eid = args.get("endpoint_id", "")
            ep = db.query(ModelEndpoint).filter(ModelEndpoint.id == eid).first()
            if not ep:
                return {"error": f"Endpoint {eid} not found", "exit_code": 1}
            ep.is_enabled = (action == "enable")
            db.commit()
            return {"response": f"Endpoint '{ep.name}' {action}d", "exit_code": 0}

        else:
            return {"error": f"Unknown action: {action}", "exit_code": 1}
    except Exception as e:
        logger.error(f"manage_endpoints error: {e}")
        return {"error": str(e), "exit_code": 1}
    finally:
        db.close()


# ---------------------------------------------------------------------------
# MCP server management tool
# ---------------------------------------------------------------------------

# Parallel to routes/cookbook_helpers._validate_serve_cmd but deliberately the
# opposite policy: that gate guards an admin-only serve command and allows
# interpreters (python3/etc) because model-serving needs them, whereas this is
# the model/prompt-injection-reachable manage_mcp path, so interpreters and
# runners are denied here.
#
# Commands that can execute arbitrary code regardless of their arguments. These
# are NEVER accepted on the manage_mcp agent path, even if an operator lists one
# in PANTHEON_MCP_ALLOWED_COMMANDS -- a stdio server that genuinely needs an
# interpreter or package runner must be registered via the trusted admin route.
_MCP_DENIED_COMMANDS = frozenset({
    "sh", "bash", "zsh", "fish", "dash", "ksh", "csh", "tcsh", "ash", "busybox",
    "cmd", "command.com", "powershell", "pwsh",
    "python", "pypy", "node", "nodejs", "deno", "bun", "ruby", "jruby",
    "perl", "raku", "php", "lua", "luajit", "tclsh", "wish", "expect", "rscript",
    "groovy", "scala", "elixir", "erl", "iex", "java", "javac", "jshell", "jbang",
    "kotlin", "kotlinc", "dotnet", "mono", "swift", "osascript", "tsx", "ts-node",
    "npx", "bunx", "uvx", "pipx", "npm", "pnpm", "yarn", "pip", "uv",
    "gem", "cargo", "go", "bundle", "poetry", "conda", "mamba", "brew",
    "apt", "apt-get", "yum", "dnf", "pacman", "apk",
    "env", "xargs", "nohup", "setsid", "nice", "ionice", "time", "timeout",
    "watch", "stdbuf", "unbuffer", "script", "ssh", "scp", "sshpass", "sudo",
    "doas", "su", "make", "cmake", "docker", "podman", "kubectl", "find",
    "awk", "gawk", "sed", "vi", "vim", "nvim", "emacs", "ed", "tee", "eval",
})

# Argv flags that make even an allowlisted binary execute inline code. Matched
# by prefix so glued forms (-cimport os, --eval=...) are caught, not just the
# exact-token form.
_MCP_CODE_EXEC_SHORT_FLAGS = ("-c", "-e", "-m")
_MCP_CODE_EXEC_LONG_FLAGS = ("--eval", "--exec", "--print", "--module", "--command", "--require")

_MCP_URL_SCHEMES = ("http://", "https://", "ftp://", "ftps://", "file://", "data:", "jar:", "blob:")

# Shell metacharacters refused in command/args. Args are passed as an argv list
# (no shell), but refusing these keeps the surface narrow and obvious.
_MCP_SHELL_METACHARS = set(";|&$`><\n\r")

# Env vars that let a child process load attacker-supplied code before main().
_MCP_DANGEROUS_ENV = frozenset({
    "LD_PRELOAD", "LD_LIBRARY_PATH", "LD_AUDIT", "DYLD_INSERT_LIBRARIES",
    "DYLD_LIBRARY_PATH", "DYLD_FRAMEWORK_PATH", "PYTHONPATH", "PYTHONSTARTUP",
    "PYTHONHOME", "PYTHONEXECUTABLE", "NODE_OPTIONS", "NODE_PATH", "BASH_ENV",
    "ENV", "SHELLOPTS", "PERL5LIB", "PERL5OPT", "RUBYOPT", "RUBYLIB", "GEM_PATH",
    "R_PROFILE", "R_HOME", "PATH", "IFS", "PROMPT_COMMAND",
})


def _mcp_allowed_commands() -> set:
    """Operator-configured allowlist of safe MCP launcher basenames for the agent
    path. Empty by default; set PANTHEON_MCP_ALLOWED_COMMANDS (comma-separated)
    to opt specific trusted binaries in. Denied commands are rejected even if
    listed here."""
    raw = os.environ.get("PANTHEON_MCP_ALLOWED_COMMANDS", "")
    return {c.strip().lower() for c in raw.split(",") if c.strip()}


def _validate_mcp_command(command, args, env) -> Optional[str]:
    """Validate a model-supplied stdio MCP registration. Returns an error string
    if it must be rejected, else None.

    Closes the RCE where manage_mcp 'add' passed prompt-injection-controlled
    command/args/env straight to a subprocess spawn (issue #438): a payload
    smuggled into a skill description, memory entry, fetched page, or email body
    could register a stdio server running arbitrary code as the app UID.
    """
    if not isinstance(command, str) or not command.strip():
        return "command must be a non-empty string"
    command = command.strip()
    if "/" in command or "\\" in command:
        return "command must be a bare executable name, not a path"
    if any(ch in _MCP_SHELL_METACHARS for ch in command):
        return "command contains shell metacharacters"
    base = command.lower()
    if base.endswith(".exe") or base.endswith(".cmd") or base.endswith(".bat"):
        base = base.rsplit(".", 1)[0]
    # Canonicalize a trailing version suffix so versioned aliases collapse to the
    # family name (python3.11 -> python, node18 -> node, pip3 -> pip); both the
    # raw basename and the canonical form are denied, so an operator cannot
    # accidentally allowlist a runtime alias back into the path.
    canon = re.sub(r"[-_.]?\d+(?:\.\d+)*$", "", base)
    if base in _MCP_DENIED_COMMANDS or canon in _MCP_DENIED_COMMANDS:
        return (
            f"command '{command}' is not allowed on the agent MCP path: "
            "interpreters, runtimes, package runners, and shells can execute "
            "arbitrary code. Register such a server via the admin route instead."
        )
    if base not in _mcp_allowed_commands():
        return (
            f"command '{command}' is not in the MCP allowlist. Add it to "
            "PANTHEON_MCP_ALLOWED_COMMANDS if you trust it, or register the "
            "server via the admin route."
        )

    if args is not None:
        if isinstance(args, str):
            try:
                args = json.loads(args)
            except Exception:
                return "args must be a JSON list"
        if not isinstance(args, list):
            return "args must be a list"
        for a in args:
            if not isinstance(a, str):
                return "args must all be strings"
            s = a.strip()
            low = s.lower()
            if any(s == f or s.startswith(f) for f in _MCP_CODE_EXEC_SHORT_FLAGS):
                return f"arg '{a}' is a code-execution flag and is not allowed"
            if any(low == f or low.startswith(f + "=") for f in _MCP_CODE_EXEC_LONG_FLAGS):
                return f"arg '{a}' is a code-execution flag and is not allowed"
            if any(low.startswith(u) for u in _MCP_URL_SCHEMES):
                return f"arg '{a}' is a remote URL and is not allowed"
            if any(ch in _MCP_SHELL_METACHARS for ch in a):
                return f"arg '{a}' contains shell metacharacters"

    if env:
        if isinstance(env, str):
            try:
                env = json.loads(env)
            except Exception:
                return "env must be a JSON object"
        if not isinstance(env, dict):
            return "env must be an object"
        for k in env:
            if str(k).strip().upper() in _MCP_DANGEROUS_ENV:
                return f"env var '{k}' can inject code into the child process and is not allowed"

    return None


async def do_manage_mcp(content: str, owner: Optional[str] = None) -> Dict:
    """Manage MCP servers: list, add, delete, enable, disable, reconnect."""
    try:
        args = _parse_tool_args(content)
    except ValueError:
        return {"error": "Invalid JSON arguments", "exit_code": 1}

    action = args.get("action", "list")

    if action == "list":
        mcp = get_mcp_manager()
        if not mcp:
            return {"response": "No MCP manager available", "servers": [], "exit_code": 0}
        from core.database import SessionLocal, McpServer
        db = SessionLocal()
        try:
            servers = db.query(McpServer).all()
            items = []
            for s in servers:
                st = mcp.get_server_status(s.id)
                status = st.get("status", "disconnected")
                tool_count = st.get("tool_count", 0)
                items.append({"id": s.id, "name": s.name, "transport": s.transport,
                              "is_enabled": s.is_enabled, "status": status,
                              "tool_count": tool_count})
            return {"response": f"{len(items)} MCP servers", "servers": items, "exit_code": 0}
        finally:
            db.close()

    elif action == "add":
        from core.database import SessionLocal, McpServer
        import uuid as _uuid
        from datetime import datetime
        name = args.get("name", "")
        command = args.get("command", "")
        cmd_args = args.get("args", [])
        env = args.get("env", {})
        if not name or not command:
            return {"error": "name and command are required", "exit_code": 1}
        # Validate BEFORE any DB write or spawn: a rejected registration must
        # leave no enabled row (which would otherwise auto-reconnect on restart)
        # and must not attempt a connection.
        _mcp_err = _validate_mcp_command(command, cmd_args, env)
        if _mcp_err:
            return {"error": f"manage_mcp: refused unsafe server registration: {_mcp_err}", "exit_code": 1}
        sid = str(_uuid.uuid4())[:8]
        db = SessionLocal()
        try:
            srv = McpServer(id=sid, name=name, transport="stdio", command=command,
                            args=json.dumps(cmd_args) if isinstance(cmd_args, list) else cmd_args,
                            env=json.dumps(env) if isinstance(env, dict) else env,
                            is_enabled=True, created_at=datetime.utcnow(), updated_at=datetime.utcnow())
            db.add(srv)
            db.commit()
        finally:
            db.close()
        # Try to connect
        mcp = get_mcp_manager()
        tool_count = 0
        if mcp:
            try:
                await mcp.connect_server(
                    sid, name, "stdio", command=command,
                    args=cmd_args if isinstance(cmd_args, list) else json.loads(cmd_args),
                    env=env if isinstance(env, dict) else json.loads(env),
                )
                st = mcp.get_server_status(sid)
                tool_count = st.get("tool_count", 0)
            except Exception as e:
                logger.warning(f"MCP connect failed for {name}: {e}")
        return {"response": f"Added MCP server '{name}' ({tool_count} tools)", "exit_code": 0}

    elif action == "delete":
        sid = args.get("server_id", "")
        from core.database import SessionLocal, McpServer
        db = SessionLocal()
        try:
            srv = db.query(McpServer).filter(McpServer.id == sid).first()
            if not srv:
                return {"error": f"Server {sid} not found", "exit_code": 1}
            name = srv.name
            mcp = get_mcp_manager()
            if mcp:
                try:
                    await mcp.disconnect_server(sid)
                except Exception:
                    pass
            db.delete(srv)
            db.commit()
            return {"response": f"Deleted MCP server '{name}'", "exit_code": 0}
        finally:
            db.close()

    elif action == "reconnect":
        sid = args.get("server_id", "")
        mcp = get_mcp_manager()
        if not mcp:
            return {"error": "MCP manager not available", "exit_code": 1}
        try:
            await mcp.disconnect_server(sid)
            from core.database import SessionLocal, McpServer
            db2 = SessionLocal()
            try:
                srv = db2.query(McpServer).filter(McpServer.id == sid).first()
                if srv:
                    _args = json.loads(srv.args) if srv.args else []
                    _env = json.loads(srv.env) if srv.env else {}
                    await mcp.connect_server(
                        server_id=sid,
                        name=srv.name,
                        transport=srv.transport,
                        command=srv.command,
                        args=_args,
                        env=_env,
                        url=srv.url,
                    )
                    st = mcp.get_server_status(sid)
                    return {"response": f"Reconnected '{srv.name}' ({st.get('tool_count', 0)} tools)", "exit_code": 0}
                return {"error": f"Server {sid} not found", "exit_code": 1}
            finally:
                db2.close()
        except Exception as e:
            return {"error": str(e), "exit_code": 1}

    elif action in ("enable", "disable"):
        sid = args.get("server_id", "")
        from core.database import SessionLocal, McpServer
        db = SessionLocal()
        try:
            srv = db.query(McpServer).filter(McpServer.id == sid).first()
            if not srv:
                return {"error": f"Server {sid} not found", "exit_code": 1}
            srv.is_enabled = (action == "enable")
            db.commit()
            return {"response": f"MCP server '{srv.name}' {action}d", "exit_code": 0}
        finally:
            db.close()

    elif action == "list_tools":
        mcp = get_mcp_manager()
        if not mcp:
            return {"response": "No MCP manager", "tools": [], "exit_code": 0}
        tools = mcp.get_all_tools()
        items = [{"name": t["name"], "server": t["server_name"],
                  "description": t.get("description", "")[:100]} for t in tools]
        return {"response": f"{len(items)} MCP tools available", "tools": items, "exit_code": 0}

    else:
        return {"error": f"Unknown action: {action}", "exit_code": 1}


# ---------------------------------------------------------------------------
# Webhook management tool
# ---------------------------------------------------------------------------

async def do_manage_webhooks(content: str, owner: Optional[str] = None) -> Dict:
    """Manage webhooks: list, add, delete, enable, disable, test."""
    from core.database import SessionLocal
    try:
        args = _parse_tool_args(content)
    except ValueError:
        return {"error": "Invalid JSON arguments", "exit_code": 1}

    action = args.get("action", "list")
    db = SessionLocal()
    try:
        from core.database import Webhook
        if action == "list":
            hooks = db.query(Webhook).all()
            items = [{"id": h.id, "name": h.name, "url": h.url,
                       "events": h.events, "is_active": h.is_active} for h in hooks]
            return {"response": f"{len(items)} webhooks", "webhooks": items, "exit_code": 0}

        elif action == "add":
            import uuid as _uuid
            from datetime import datetime
            from src.webhook_manager import validate_events, validate_webhook_url
            name = args.get("name", "")
            url = args.get("url", "")
            events = args.get("events", "chat.completed")
            if not url:
                return {"error": "url is required", "exit_code": 1}
            try:
                url = validate_webhook_url(url)
                events = validate_events(events)
            except ValueError as e:
                return {"error": str(e), "exit_code": 1}
            wid = str(_uuid.uuid4())[:8]
            hook = Webhook(id=wid, name=name or url, url=url,
                           events=events, is_active=True,
                           created_at=datetime.utcnow(), updated_at=datetime.utcnow())
            db.add(hook)
            db.commit()
            return {"response": f"Added webhook '{name or url}'", "exit_code": 0}

        elif action == "delete":
            wid = args.get("webhook_id", "")
            hook = db.query(Webhook).filter(Webhook.id == wid).first()
            if not hook:
                return {"error": f"Webhook {wid} not found", "exit_code": 1}
            name = hook.name
            db.delete(hook)
            db.commit()
            return {"response": f"Deleted webhook '{name}'", "exit_code": 0}

        elif action in ("enable", "disable"):
            wid = args.get("webhook_id", "")
            hook = db.query(Webhook).filter(Webhook.id == wid).first()
            if not hook:
                return {"error": f"Webhook {wid} not found", "exit_code": 1}
            hook.is_active = (action == "enable")
            db.commit()
            return {"response": f"Webhook '{hook.name}' {action}d", "exit_code": 0}

        else:
            return {"error": f"Unknown action: {action}", "exit_code": 1}
    except Exception as e:
        logger.error(f"manage_webhooks error: {e}")
        return {"error": str(e), "exit_code": 1}
    finally:
        db.close()


# ---------------------------------------------------------------------------
# API token management tool
# ---------------------------------------------------------------------------

async def do_manage_tokens(content: str, owner: Optional[str] = None) -> Dict:
    """Manage API tokens: list, create, delete."""
    from core.database import SessionLocal, ApiToken
    try:
        args = _parse_tool_args(content)
    except ValueError:
        return {"error": "Invalid JSON arguments", "exit_code": 1}

    action = args.get("action", "list")
    db = SessionLocal()
    try:
        if action == "list":
            tokens = db.query(ApiToken).all()
            items = [{"id": t.id, "name": t.name, "token_prefix": t.token_prefix + "...",
                       "is_active": t.is_active} for t in tokens]
            return {"response": f"{len(items)} API tokens", "tokens": items, "exit_code": 0}

        elif action == "create":
            import uuid as _uuid, bcrypt
            from datetime import datetime
            from core.api_tokens import (
                TOKEN_PREFIX_LEN, invalidate_token_cache, mint_raw_token,
            )
            name = args.get("name", "API Token")
            # B43. A token with no owner is not a weak token, it is a dead one:
            # `_refresh_token_cache` in app.py resolves every row's owner against
            # the auth store and skips the ones it cannot place, logging a
            # warning on every rebuild. Handing the caller a credential that is
            # guaranteed to 401 is worse than saying no.
            if not owner:
                return {
                    "error": "Cannot create an API token without an owner — "
                             "the auth middleware ignores ownerless tokens, so "
                             "the token would never authenticate.",
                    "exit_code": 1,
                }
            # `mint_raw_token()` and not a bare `token_urlsafe`: the middleware
            # only looks at Authorization headers whose credential carries a
            # known prefix, so a token minted without one could not authenticate
            # even with an owner. This path shipped without the prefix.
            raw_token = mint_raw_token()
            token_hash = bcrypt.hashpw(raw_token.encode(), bcrypt.gensalt()).decode()
            tid = str(_uuid.uuid4())[:8]
            # `chat` explicitly rather than by column default. It is the same
            # scope this path already produced — `ApiToken.scopes` defaults to
            # "chat" on insert — and writing it down is what makes it a decision
            # instead of an accident. Anything broader is the admin UI's job:
            # it has the scope allowlist and the profiles, and a tool the model
            # drives should not be the place that widens a credential.
            t = ApiToken(id=tid, owner=owner, name=name, token_hash=token_hash,
                         token_prefix=raw_token[:TOKEN_PREFIX_LEN], scopes="chat",
                         is_active=True,
                         created_at=datetime.utcnow(), updated_at=datetime.utcnow())
            db.add(t)
            db.commit()
            # Bearer auth serves from an in-memory map that only rebuilds when
            # flagged dirty. Without this the new token does not work until
            # some unrelated token operation or a restart clears the cache.
            invalidate_token_cache()
            return {"response": f"Created token '{name}' for {owner} (scope: chat)",
                    "token": raw_token, "owner": owner, "scopes": ["chat"],
                    "exit_code": 0}

        elif action == "delete":
            from core.api_tokens import invalidate_token_cache
            tid = args.get("token_id", "")
            t = db.query(ApiToken).filter(ApiToken.id == tid).first()
            if not t:
                return {"error": f"Token {tid} not found", "exit_code": 1}
            name = t.name
            db.delete(t)
            db.commit()
            # The row is gone and the cached copy is not. This is the half of
            # B43 that matters: without it a revoked token kept authenticating
            # until the next restart, because nothing else in this tool ever
            # touched the dirty flag.
            invalidate_token_cache()
            return {"response": f"Deleted token '{name}'", "exit_code": 0}

        else:
            return {"error": f"Unknown action: {action}", "exit_code": 1}
    except Exception as e:
        logger.error(f"manage_tokens error: {e}")
        return {"error": str(e), "exit_code": 1}
    finally:
        db.close()

# ---------------------------------------------------------------------------
# Settings/preferences management tool
# ---------------------------------------------------------------------------

async def do_manage_settings(content: str, owner: Optional[str] = None) -> Dict:
    """Manage user settings and preferences."""
    try:
        args = _parse_tool_args(content)
    except ValueError:
        return {"error": "Invalid JSON arguments", "exit_code": 1}

    action = args.get("action", "list")

    from core.database import SessionLocal
    db = SessionLocal()
    try:
        # set/get/list/delete operate on the REAL app settings (the same store
        # the Settings panel writes), so changing a model / voice / search
        # engine / reminder channel from chat actually takes effect.
        from src.settings import (
            DEFAULT_SETTINGS,
            RETIRED_SETTING_KEYS,
            load_settings,
            save_settings,
        )

        # Secrets/credentials the agent must NOT write: kept read-only (masked)
        # so API keys never flow through chat. User sets these in the panel.
        _SECRET_KEYS = {
            "brave_api_key", "google_pse_key", "google_pse_cx",
            "tavily_api_key", "serper_api_key", "app_public_url",
        }
        # `B42`. Settings that exist to keep a human in the loop, which the
        # agent may READ and may not WRITE.
        #
        # Measured before it was written: `manage_settings set
        # agent_email_confirm false` moved the stored value from True to False,
        # and `set trust_rung allow_listed` moved the confirmation ladder from
        # `gate_on_untrusted`. Both succeeded. The agent could take off the gate
        # that requires a person to approve an email before it sends, and lower
        # the ladder that decides when it has to ask at all.
        #
        # That is reachable by prompt injection, because the tool call is the
        # same whether the instruction came from the operator or from a web page
        # the agent was asked to read. **A gate whose purpose is "a human must
        # confirm" cannot be removable through the channel the gate exists to
        # distrust** — not even at what looks like the operator's own request,
        # because looking like it is precisely what an injection does. Settings
        # is where a request provably came from the person, and `H18` is the
        # commit that gives all three of these a control there.
        #
        # `agent_loop.py` already argues this for role profiles: a profile "may
        # only raise strictness — a profile that lowers the rung hands a user a
        # way to switch their own confirmation gate off." The same sentence
        # applies with more force to the agent itself.
        #
        # Deliberately NOT here: `agent_max_rounds` and `agent_max_tool_calls`.
        # They are runaway and cost caps with no approval semantics, "give
        # yourself more steps" is a real thing to ask for, and a restriction
        # that has to be argued each time is one nobody keeps. Filed as `P7-12`.
        _SELF_RESTRAINT_KEYS = {
            "agent_email_confirm",
            # Added by `H16`, which declared it — and declaring a key hands it
            # to the agent as well as to the person, because `DEFAULT_SETTINGS`
            # is the allowlist for both. A checker that the checked party can
            # switch off is not a check.
            "agent_verifier_subagent",
        }
        #
        # `trust_rung` is NOT here, and the first version of this set had it.
        # Removing it is a correction, not a softening.
        #
        # The claim was "the agent lowered the confirmation ladder from
        # `gate_on_untrusted` to `allow_listed`". The measurement was right and
        # the word "lowered" was not: `allow_listed` is one of
        # `_RUNGS_THAT_ASK_UNTAINTED`, so it asks in clean runs that
        # `gate_on_untrusted` lets through. It may well be the *stricter* of
        # the two.
        #
        # And the rungs are not a ladder that can be read from outside.
        # `decision_for` carries the reproduction: on `ask_every_time`,
        # approving one harmless command in a clean run used to spend a bypass
        # that a later hostile page then rode — so "the two stricter rungs were
        # strictly less protected than the one they sit below." That is fixed,
        # and the lesson is that no total order exists to check a write against.
        #
        # There is also a reasoned test in the other direction:
        # `test_the_chat_tool_still_sets_a_rung_it_does_implement` sets
        # `ask_every_time` from chat, and `P7-03`'s framing is "a person being
        # able to set it". Asking for more confirmation in the same breath as
        # the work is a real thing to want.
        #
        # So: shipping a refusal here would have been a security change resting
        # on an ordering the codebase says does not hold. Filed as `P7-13`.

        # One sentence per key, because they are not the same kind of thing and
        # a refusal that describes the wrong one reads as a canned excuse.
        _SELF_RESTRAINT_WHY = {
            "agent_email_confirm":
                "decides whether a person has to approve an email before I send it",
            "agent_verifier_subagent":
                "is the check on whether I actually did what I said I did",
        }

        def _is_self_restraint(k):
            return k in _SELF_RESTRAINT_KEYS

        def _self_restraint_why(k):
            return _SELF_RESTRAINT_WHY.get(k, "is a limit a person set on what I can do")

        def _is_secret(k):
            # `token` must be a suffix, not a substring: otherwise the int
            # setting `agent_input_token_budget` (which even has a "token budget"
            # alias to set it from chat) is wrongly classified as a credential.
            return (
                k in _SECRET_KEYS
                or k.endswith("token")
                or any(t in k for t in ("api_key", "_key", "secret", "password"))
            )

        # Friendly aliases → real keys, so natural phrasing resolves.
        _ALIASES_SET = {
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
            "webhook template": "reminder_webhook_payload_template", "webhook payload": "reminder_webhook_payload_template",
            "agent tool calls": "agent_max_tool_calls", "max tool calls": "agent_max_tool_calls",
            "agent timeout": "agent_stream_timeout_seconds", "stream timeout": "agent_stream_timeout_seconds",
            "token budget": "agent_input_token_budget", "input budget": "agent_input_token_budget",
            "hard max": "agent_input_token_hard_max",
            "token budget cap": "agent_input_token_hard_max",
            "input budget cap": "agent_input_token_hard_max",
        }
        def _resolve(k):
            k2 = (k or "").strip().lower()
            if k2 in DEFAULT_SETTINGS:
                return k2
            return _ALIASES_SET.get(k2, (k or "").strip())

        def _is_managed_key(key):
            return key in DEFAULT_SETTINGS and key not in RETIRED_SETTING_KEYS

        _ENUMS = {
            "image_quality": ["low", "medium", "high"],
            "reminder_channel": ["browser", "email", "ntfy", "webhook"],
            # The trust rung is the one entry here with a security consequence.
            # `coerce_trust_rung` falls back to the *default* rather than the
            # strictest rung, so without this line "set trust_rung to ask every
            # time" answered *"Set trust_rung = ask every time."* and left the
            # install on the default — the user told to their face that the
            # protection they asked for is on, when it is not.
            "trust_rung": [rung.value for rung in TrustRung],
        }
        def _coerce(value, default):
            if isinstance(default, bool):
                return value if isinstance(value, bool) else str(value).strip().lower() in ("true", "on", "yes", "1", "enable", "enabled")
            if isinstance(default, int):
                return int(value)
            return value

        def _model_slug(value: str) -> str:
            import re as _re
            return _re.sub(r"[^a-z0-9]+", "", (value or "").lower())

        def _endpoint_model_from_cache(model_query: str):
            """Resolve friendly model text to an enabled endpoint + real model id.

            The Settings UI stores both `<prefix>_endpoint_id` and
            `<prefix>_model`; writing only the model leaves the runtime on the
            old endpoint. Prefer cached model lists so this stays fast/offline.
            """
            import json as _json
            import re as _re
            from core.database import ModelEndpoint

            wanted = (model_query or "").strip()
            wanted_slug = _model_slug(wanted)
            wanted_tokens = [_model_slug(t) for t in _re.findall(r"[A-Za-z0-9]+", wanted)]
            wanted_tokens = [t for t in wanted_tokens if t]
            if not wanted_slug:
                return None
            best = None
            for ep in db.query(ModelEndpoint).filter(ModelEndpoint.is_enabled == True).all():
                raw_models = []
                try:
                    raw_models = _json.loads(ep.cached_models or "[]") or []
                except Exception:
                    raw_models = []
                # If cache is empty, still allow matching against endpoint name
                # for callers using model@endpoint elsewhere later.
                for mid in raw_models:
                    mid = str(mid)
                    mid_slug = _model_slug(mid)
                    if not mid_slug:
                        continue
                    exact = mid.lower() == wanted.lower()
                    compact_match = wanted_slug in mid_slug or mid_slug in wanted_slug
                    token_match = bool(wanted_tokens) and all(tok in mid_slug for tok in wanted_tokens)
                    if exact or compact_match or token_match:
                        score = 3 if exact else (2 if compact_match else 1)
                        if not best or score > best[0]:
                            best = (score, ep.id, mid)
            if best:
                return {"endpoint_id": best[1], "model": best[2]}
            return None

        def _mask(k, v):
            return "••••• (set in panel)" if _is_secret(k) and v else v

        if action == "list":
            s = load_settings()
            shown = {
                k: _mask(k, v)
                for k, v in s.items()
                if _is_managed_key(k) and not isinstance(v, dict)
            }
            return {"response": f"{len(shown)} settings (use get/set with a key)", "settings": shown, "exit_code": 0}

        elif action == "get":
            key = _resolve(args.get("key", ""))
            if not key:
                return {"error": "key is required", "exit_code": 1}
            if not _is_managed_key(key):
                return {"error": f"Unknown setting '{args.get('key')}'. Use action='list' to see them.", "exit_code": 1}
            val = load_settings().get(key, DEFAULT_SETTINGS.get(key))
            return {"response": f"{key} = {_mask(key, val)}", "value": _mask(key, val), "exit_code": 0}

        elif action == "set":
            raw = args.get("key", "")
            value = args.get("value")
            if not raw:
                return {"error": "key is required", "exit_code": 1}
            key = _resolve(raw)
            if not _is_managed_key(key):
                return {"error": f"Unknown setting '{raw}'. Use action='list' to see available settings.", "exit_code": 1}
            if _is_secret(key):
                return {"response": f"'{key}' is a credential/secret. For security I can't set it from chat. Open Settings and set it there.", "exit_code": 0}
            if _is_self_restraint(key):
                # Names the setting and says where to change it: a refusal that
                # does not say where to go is a refusal the person works around.
                return {"response": f"'{key}' {_self_restraint_why(key)}, so I can't change it "
                                    f"from chat — including if you ask me to, because a message "
                                    f"asking for that looks the same whether it came from you or "
                                    f"from something I was reading. Open Settings and change it "
                                    f"there.", "exit_code": 0}
            # Structured settings (dicts/lists like keybinds or vision fallbacks)
            # have no safe scalar coercion; _coerce would pass a bare string
            # straight through and clobber the structure. Refuse them here; they
            # are edited in Settings.
            #
            # `B68`. This used to end "(You can reset it to default here.)" on
            # the reasoning that reset restores the default structure and is
            # therefore safe. That holds for exactly one of the nine structured
            # settings. Eight ship **empty**, so for those the offer was an offer
            # to delete the operator's configuration — and a refusal that
            # advertises a worse door than the one it closed is not a refusal.
            if isinstance(DEFAULT_SETTINGS[key], (dict, list)):
                restorable = bool(DEFAULT_SETTINGS[key])
                tail = (" (You can reset it to default here.)" if restorable
                        else " It ships empty, so there is nothing to reset it to.")
                return {"response": f"'{key}' is a structured setting. Edit it in Settings, not from chat.{tail}", "exit_code": 0}
            try:
                value = _coerce(value, DEFAULT_SETTINGS[key])
            except (ValueError, TypeError):
                return {"error": f"'{value}' isn't a valid value for {key} (expected {type(DEFAULT_SETTINGS[key]).__name__}).", "exit_code": 1}
            if key in _ENUMS and str(value).lower() not in _ENUMS[key]:
                return {"error": f"{key} must be one of: {', '.join(_ENUMS[key])}.", "exit_code": 1}
            s = load_settings()
            s[key] = value
            if key in {"default_model", "research_model", "utility_model", "task_model", "vision_model", "image_model"}:
                resolved = _endpoint_model_from_cache(str(value))
                if resolved:
                    prefix = key[:-6]
                    s[f"{prefix}_endpoint_id"] = resolved["endpoint_id"]
                    s[key] = resolved["model"]
                    value = resolved["model"]
            save_settings(s)
            if key.endswith("_model") and s.get(f"{key[:-6]}_endpoint_id"):
                return {"response": f"Set {key} = {value} (endpoint {s.get(f'{key[:-6]}_endpoint_id')}).", "exit_code": 0}
            return {"response": f"Set {key} = {value}.", "exit_code": 0}

        elif action == "delete" or action == "reset":
            key = _resolve(args.get("key", ""))
            if not _is_managed_key(key):
                return {"error": f"Unknown setting '{args.get('key')}'.", "exit_code": 1}
            if _is_secret(key):
                return {"response": f"'{key}' is a credential. Reset it in the panel.", "exit_code": 0}
            if _is_self_restraint(key):
                # `reset` writes `DEFAULT_SETTINGS[key]`, which for
                # `agent_email_confirm` is True and for `trust_rung` is the
                # default rung — so resetting is usually *safe*. It is refused
                # anyway: "the agent may only move this in the safe direction"
                # is a rule that inverts the day someone changes a default, and
                # a control the agent cannot touch is easier to reason about
                # than one it can touch carefully.
                return {"response": f"'{key}' {_self_restraint_why(key)}. Reset it in Settings.",
                        "exit_code": 0}
            # `B68`. The `set` branch above refuses every structured setting and
            # says "(You can reset it to default here.)" on the reasoning, in its
            # own comment, that "reset/delete still restore the default
            # structure, which is safe". That is true of exactly one of the nine
            # structured settings. The other eight — `networks`,
            # `search_fallback_chain`, `tool_path_extra_roots`, `eval_suites`,
            # the two OTLP maps and the two model-fallback lists — **ship
            # empty**, and for those "restore the default" is not restoring
            # anything. It is deleting what the operator wrote, in one call, in
            # response to a sentence in a chat.
            #
            # Not a security hole and the row says so: `networks` fails *closed*
            # — a run scoped to a name that no longer exists refuses every host,
            # including the operator's own. So this is durability, not
            # escalation, and writing down the right reason matters because the
            # wrong one is how the protection gets removed later.
            #
            # Computed from `DEFAULT_SETTINGS`, not listed, so a ninth empty
            # structured setting is covered the day it is added (`Law 13`).
            default = DEFAULT_SETTINGS[key]
            if isinstance(default, (dict, list)) and not default:
                return {
                    "response": (
                        f"'{key}' is a structured setting that ships empty, so there "
                        f"is no default to restore — resetting it would just delete "
                        f"what is configured. Edit it in Settings."
                    ),
                    "exit_code": 0,
                }
            s = load_settings()
            s[key] = DEFAULT_SETTINGS[key]
            save_settings(s)
            return {"response": f"Reset {key} to default ({DEFAULT_SETTINGS[key]}).", "exit_code": 0}

        elif action in ("disable_tool", "enable_tool", "list_tools"):
            # Tool-toggle actions. These edit settings.json:disabled_tools
            # (the global list read on every chat request) rather than
            # prefs.json. Friendly aliases accepted: "shell" -> "bash",
            # "search" -> "web_search", "browser" -> "builtin_browser",
            # "documents" -> the document tool set, "memory" ->
            # manage_memory, etc.
            from src.settings import get_setting, save_settings, load_settings
            _ALIASES = {
                "shell": ["bash"],
                "terminal": ["bash"],
                "search": ["web_search", "web_fetch"],
                "web": ["web_search", "web_fetch"],
                "browser": ["builtin_browser"],
                "documents": ["create_document", "edit_document", "update_document", "suggest_document"],
                "doc": ["create_document", "edit_document", "update_document", "suggest_document"],
                "memory": ["manage_memory"],
                "rag": ["manage_rag"],  # `B66`
                "skills": ["manage_skills"],
                "images": ["generate_image"],
                "image": ["generate_image"],
                "tasks": ["manage_tasks"],
                "notes": ["manage_notes"],
                "calendar": ["manage_calendar"],
                # The full built-in email tool set, in BOTH spellings: the
                # qualified mcp__email__* names drive MCP schema hiding, the
                # bare names drive function-schema hiding, and the runtime
                # gate accepts either — deriving from BUILTIN_EMAIL_TOOLS
                # keeps the toggle covering every tool the email server
                # exposes instead of a hand-picked subset.
                "email": sorted(BUILTIN_EMAIL_TOOLS)
                         + [f"mcp__email__{t}" for t in sorted(BUILTIN_EMAIL_TOOLS)],
                "research": ["web_search", "web_fetch"],  # research is a per-request flag, not a tool (closest analog)
            }

            if action == "list_tools":
                current = get_setting("disabled_tools", []) or []
                return {
                    "response": (
                        f"Currently disabled: {', '.join(current) if current else '(none)'}.\n"
                        "Common toggles: shell (bash), search (web_search), browser, documents, "
                        "memory, skills, images, tasks, notes, calendar, email."
                    ),
                    "disabled": list(current),
                    "exit_code": 0,
                }

            tool_name = (args.get("tool") or args.get("name") or "").strip().lower()
            if not tool_name:
                return {"error": "tool name required (e.g. 'shell', 'search', 'bash')", "exit_code": 1}
            targets = _ALIASES.get(tool_name, [tool_name])

            settings = load_settings()
            current = list(settings.get("disabled_tools") or [])
            before = set(current)
            if action == "disable_tool":
                for t in targets:
                    if t not in current:
                        current.append(t)
            else:  # enable_tool
                current = [t for t in current if t not in targets]
            after = set(current)
            settings["disabled_tools"] = current
            save_settings(settings)

            verb = "Disabled" if action == "disable_tool" else "Enabled"
            changed = sorted(after.symmetric_difference(before))
            return {
                "response": (
                    f"{verb} {tool_name} ({', '.join(targets)}). "
                    f"Now disabled: {', '.join(current) if current else '(none)'}."
                ),
                "changed": changed,
                "disabled": list(current),
                "exit_code": 0,
            }

        else:
            return {"error": f"Unknown action: {action}", "exit_code": 1}
    except Exception as e:
        logger.error(f"manage_settings error: {e}")
        return {"error": str(e), "exit_code": 1}
    finally:
        db.close()


# ---------------------------------------------------------------------------
# API call tool
# ---------------------------------------------------------------------------



# ── registry adapters ────────────────────────────────────────────────────────
def _owner_adapter(fn):
    """Wrap a do_*(content, owner) impl as a registry execute(content, ctx)."""
    async def _execute(content: str, ctx: dict) -> dict:
        return await fn(content, ctx.get("owner"))
    return _execute


ADMIN_TOOL_HANDLERS = {
    "manage_endpoints": _owner_adapter(do_manage_endpoints),
    "manage_mcp": _owner_adapter(do_manage_mcp),
    "manage_webhooks": _owner_adapter(do_manage_webhooks),
    "manage_tokens": _owner_adapter(do_manage_tokens),
    "manage_settings": _owner_adapter(do_manage_settings),
}
