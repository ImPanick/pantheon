# SPDX-License-Identifier: AGPL-3.0-or-later
"""`connections` — what this agent may sign in to, and whether it answers.
`P27-09`.

The owner (2026-10-24): *"Connections hub for the Agents to use."* The hub
is the Workbench's MCP & Integrations room (`P27-01`); this is the agent's
side of it. Two actions:

  * **list** — the logins in the person's vault this agent may use (a login
    granted to some agents only is invisible to the rest, as it is to
    `agent_browser login` and `shell_with_login`), with their addresses, how
    each asks, and whether it is an account made for the agent; and the git
    hosts the person keeps a token for. Names and addresses only — never a
    user name's password, a token, or a one-time-code secret.
  * **test** — whether a login's address answers, from where the person's
    shell runs (their workstation; on this machine only for a person `bash`
    is not blocked for, because a request from Pantheon's own process to an
    address a model names is a request the server makes). An HTTP status, or
    the sentence that it did not answer.

The tools take a connection by its name (`agent_browser login {item}`,
`shell_with_login {logins}`), so the model never handles an address and a
secret together.
"""

from __future__ import annotations

import json
import shlex
from typing import Any, Dict, Optional, Tuple

TOOL_NAME = "connections"
ACTIONS = ("list", "test")
TEST_TIMEOUT_S = 12.0
USE_WORDS = {"ask": "asks the person each time", "chat": "asks once per chat",
             "allowed": "may be used without asking"}


def parse_args(content: Any) -> Tuple[Dict[str, Any], Optional[str]]:
    if isinstance(content, dict):
        raw: Any = dict(content)
    else:
        text = str(content or "").strip()
        if not text:
            return {"action": "list"}, None
        if text.startswith("{"):
            try:
                raw = json.loads(text)
            except ValueError:
                return {}, '`connections` arguments are a JSON object, such as {"action": "list"}.'
        else:
            parts = text.split(None, 1)
            raw = {"action": parts[0], "name": parts[1] if len(parts) > 1 else ""}
    if not isinstance(raw, dict):
        return {}, "`connections` arguments are a JSON object."
    action = str(raw.get("action") or "list").strip().lower()
    if action not in ACTIONS:
        return {}, f"“{raw.get('action')}” is not a `connections` action. It is list or test."
    out = {"action": action}
    if action == "test":
        name = str(raw.get("name") or raw.get("item") or "").strip()
        if not name:
            return {}, "`test` needs “name”: a login from `connections list`."
        out["name"] = name
    return out, None


def describe(args: Dict[str, Any]) -> str:
    return f"test {args['name']}" if args.get("action") == "test" else "list"


def command_line(content: Any) -> str:
    args, problem = parse_args(content)
    return str(content or "").strip()[:200] if problem else describe(args)


def listing_text(items, hosts, agent: Optional[str]) -> str:
    who = f"the agent {agent}" if agent else "this chat"
    lines = []
    if items:
        lines.append(f"Logins {who} may sign in with (by name — you never see the values):")
        for it in items:
            facts = [USE_WORDS.get(it.get("use"), USE_WORDS["ask"])]
            if it.get("agent_account"):
                facts.append("an account made for the agent")
            if it.get("has_totp"):
                facts.append("one-time codes")
            where = ", ".join(it.get("addresses") or []) or "no address"
            lines.append(f"- “{it['label']}” ({it.get('kind') or 'login'}) — {where} — {'; '.join(facts)}")
        lines.append("Use: agent_browser login {item}, or shell_with_login {logins, command} with $LOGIN_… "
                     "variables. connections test {name} checks its address answers.")
    else:
        lines.append(f"No logins in the vault for {who}. The person adds them in Settings → Vault, "
                     "and can grant one to some agents only.")
    if hosts:
        lines.append("")
        lines.append("Git hosts with a token (the git tool uses it for pushes and pulls): "
                     + ", ".join(f"{h['host']} as {h['username']}" for h in hosts))
    return "\n".join(lines)


async def run_connections(content: Any, *, owner: Optional[str], agent_id: Optional[str] = None,
                          station_workspace: Optional[str] = None) -> Dict[str, Any]:
    from core.database import SessionLocal
    from src import git_accounts as G
    from src import vault as V

    args, problem = parse_args(content)
    if problem:
        return {"error": problem, "exit_code": 1}
    db = SessionLocal()
    try:
        if args["action"] == "list":
            listing = V.listing(db, owner)
            mine = {r.id: r for r in V._rows(db, V.account(owner))}
            items = [it for it in listing["items"] if it["id"] in mine and V.may_use(mine[it["id"]], agent_id)]
            text = listing_text(items, G.hosts(db, owner), agent_id)
            if listing.get("locked"):
                text += "\n(The vault is locked: signing in will be refused until the person unlocks it.)"
            return {"output": text, "exit_code": 0}
        row = V._find(db, V.account(owner), args["name"])
        if row is None or not V.may_use(row, agent_id):
            names = V.labels(db, owner, agent_id)
            have = ("You may use: " + ", ".join(f"“{n}”" for n in names[:30]) + ".") if names else \
                "There are no logins for you to use."
            return {"error": f"There is no login “{args['name'][:80]}” for you. {have}", "exit_code": 1}
        addresses = json.loads(row.addresses or "[]")
        label = row.label
    finally:
        db.close()
    if not addresses:
        return {"error": f"“{label}” has no address to test.", "exit_code": 1}
    return await _test(owner, label, addresses[0], station_workspace)


async def _test(owner: Optional[str], label: str, url: str, station_workspace: Optional[str]) -> Dict[str, Any]:
    from src.agent_tools.git_tools import _Place, _where
    place = _Place(owner, station_workspace)
    refused = await place.open()
    if refused is not None:
        return refused
    if not place.in_workstation:
        from src.tool_security import blocked_tools_for_owner
        if "bash" in blocked_tools_for_owner(owner):
            return {"error": "Testing an address runs from your workstation, and this account has none "
                             "turned on. Ask an admin for one.", "exit_code": 1}
    command = ("curl -sS -o /dev/null -k --max-time 8 -w '%{http_code} %{time_total}' "
               + shlex.quote(url))
    r = await place.run(command, place.base(), {}, TEST_TIMEOUT_S)
    out = (r.get("stdout") or "").strip()
    if r.get("exit_code") == 0 and out and out.split()[0].isdigit() and out.split()[0] != "000":
        code, took = (out.split() + ["?"])[:2]
        return {"output": f"“{label}” at {url} answered HTTP {code} in {took} s.", "exit_code": 0,
                **_where(place)}
    why = (r.get("stderr") or "").strip().splitlines()[-1:] or ["no answer"]
    return {"output": f"“{label}” at {url} did not answer: {why[0][:200]}", "exit_code": 1,
            "error": f"{url} did not answer.", **_where(place)}


class ConnectionsTool:
    """The registry's handler; the dispatcher calls `run_connections` by name
    with the turn's owner, agent and workspace."""

    async def execute(self, content: str, ctx: Optional[dict] = None) -> Dict[str, Any]:
        # `B1449`: the workspace too, when the caller has one — without it a
        # `test` through this path probed from Pantheon's machine instead of
        # the person's workstation, unlike the by-name dispatch.
        c = ctx or {}
        return await run_connections(content, owner=c.get("owner"), agent_id=c.get("agent_id"),
                                     station_workspace=c.get("station_workspace"))
