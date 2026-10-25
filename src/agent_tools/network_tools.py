# SPDX-License-Identifier: AGPL-3.0-or-later
"""`network` — what network the workstation is on, and whether it can reach a
host. `P16-20`, trimmed by `D-2026-10-25-03`.

The owner (2026-10-25): *"literally just a 'what's around me' thing"* — the
agent should be able to answer connectivity questions about the person's own
networks, and nothing more. Two actions:

  * **list** — this machine's interfaces (name, address, the CIDR each is on)
    and the networks the person has declared (`src/networks.py`), with each
    one's trust. What the model reads to know which subnets exist.
  * **reach** — can the workstation connect to one host on one port?
    Connected, refused, or no answer, and whether the route went through the
    gateway — the question a person asks when two segments can't talk.

There is no range action and no port list: one connection per call. A person
who wants more has a shell.

**Where the line is.** The check runs in the person's own workstation
(`workstation/netcheck.py`), inside its network mode — so *internet only* or
*none* refuses a LAN target at the kernel, as it does the browser. On top of
that, Pantheon decides *here*, before the call: a run bound to one declared
network is refused the others, and a network the person marked **untrusted** is
listed but never connected to (its ranges go to the daemon as `deny`, checked
after the name resolves there). The tool is offered only where the person has a
workstation and an admin left LAN reach on (`agent_lan_reach`).
"""

from __future__ import annotations

import json
import re
from typing import Any, Dict, List, Optional, Tuple

TOOL_NAME = "network"
ACTIONS = ("list", "reach")


def lan_reach_on() -> bool:
    """`agent_lan_reach` (default on): whether this install lets the agent reach
    the LAN at all — this tool and the LAN half of `web_fetch`. An admin turns
    it off for a shared box that should stay on the public internet."""
    try:
        from src.settings import get_setting
        from src.env_flags import tool_arg_truthy
        return tool_arg_truthy(get_setting("agent_lan_reach", True), default=True)
    except Exception:
        return True


# The line form: "host port", "host:port", or "[v6]:port".
_BRACKETED = re.compile(r"^\[([^\]]+)\](?::|\s+)(\d{1,5})$")
_NAME_PORT = re.compile(r"^([^\s:\[\]]+)(?::|\s+)(\d{1,5})$")
_V6_SPACE_PORT = re.compile(r"^([0-9A-Fa-f:]+)\s+(\d{1,5})$")


def _split_host_port(text: str) -> Tuple[str, Optional[int]]:
    text = text.strip()
    for rx in (_BRACKETED, _NAME_PORT, _V6_SPACE_PORT):
        m = rx.match(text)
        if m:
            return m.group(1), int(m.group(2))
    return text.strip("[]"), None


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
                return {}, ('`network` arguments are a JSON object, such as '
                            '{"action": "reach", "host": "192.168.1.10", "port": 443}.')
        else:
            parts = text.split(None, 1)
            raw = {"action": parts[0]}
            if len(parts) > 1:
                host, port = _split_host_port(parts[1])
                raw["host"] = host
                if port is not None:
                    raw["port"] = port
    if not isinstance(raw, dict):
        return {}, "`network` arguments are a JSON object."
    action = str(raw.get("action") or "list").strip().lower()
    if action not in ACTIONS:
        return {}, f"“{raw.get('action')}” is not a `network` action. It is one of {', '.join(ACTIONS)}."
    out: Dict[str, Any] = {"action": action}
    if action == "reach":
        host = str(raw.get("host") or raw.get("target") or "").strip()
        if not host:
            return {}, '`reach` needs “host”: one address or name, like "192.168.1.10".'
        if "/" in host:
            return {}, "`reach` checks one host, not a range."
        port = raw.get("port")
        if isinstance(port, str) and port.strip().isdigit():
            port = int(port.strip())
        if isinstance(port, bool) or not isinstance(port, int) or not 1 <= port <= 65535:
            return {}, "`reach` needs “port”: one port number, like 443."
        out["host"] = host
        out["port"] = port
        if raw.get("timeout_ms") is not None:
            out["timeout_ms"] = raw["timeout_ms"]
    return out, None


def describe(args: Dict[str, Any]) -> str:
    if args.get("action") == "reach":
        return f"reach {args.get('host')}:{args.get('port')}"
    return "list the networks"


def command_line(content: Any) -> str:
    args, problem = parse_args(content)
    return str(content or "").strip()[:200] if problem else describe(args)


# ── scope and trust, decided here before the daemon is asked ──────────────────

def _refusal(host: str) -> Optional[str]:
    """A sentence when this run may not connect to `host`, or None."""
    from src import networks as N
    if not N.host_allowed(host):
        scope = N.current_scope()
        name = N.network_for(host)
        where = f"network “{name}”" if name else "no network you have declared"
        return (f"{host} is in {where}, and this run may only reach {sorted(scope or [])}. "
                "Ask the person to widen the run's networks.")
    return N.untrusted_refusal(host)


def interfaces_text(answer: Dict[str, Any]) -> str:
    from src import networks as N
    lines: List[str] = []
    ifs = answer.get("interfaces") or []
    if ifs:
        lines.append("This machine's network interfaces:")
        for i in ifs:
            for a in i.get("addresses") or []:
                state = "" if i.get("up") else " (down)"
                lines.append(f"- {i['name']}{state}: {a['ip']}  on {a['cidr']}")
    elif not answer.get("ip_available", True):
        lines.append("This machine has no `ip` command, so its interfaces can't be listed.")
    else:
        lines.append("No network interfaces with an address (other than loopback).")
    nets = N.declared_networks(include_disabled=True)
    if nets:
        lines.append("")
        lines.append("Networks the person has declared:")
        for n in nets:
            cidrs = ", ".join(str(c) for c in n.cidrs) or "no range"
            hosts = f"; hosts: {', '.join(n.hosts)}" if n.hosts else ""
            off = "" if n.enabled else " (disabled)"
            lines.append(f"- “{n.name}” [{n.trust}]{off}: {cidrs}{hosts}")
        lines.append("Check whether a host answers with network reach {host} {port}. An "
                     "untrusted network is listed only.")
    else:
        lines.append("")
        lines.append("No networks are declared. The person declares networks (with their "
                     "trust) in Settings → Networks.")
    scope = N.current_scope()
    if scope is not None:
        lines.append(f"This run is scoped to: {', '.join(sorted(scope)) or '(none)'}.")
    return "\n".join(lines)


def reach_text(answer: Dict[str, Any]) -> str:
    host = answer.get("host")
    addr = answer.get("address")
    port = answer.get("port")
    shown = f"{host}:{port}" + (f" ({addr})" if addr and addr != host else "")
    result = answer.get("result")
    if result == "connected":
        line = f"{shown} — connected in {answer.get('took_ms')} ms. Something is listening there."
    elif result == "refused":
        line = (f"{shown} — refused. The host answered, but nothing is listening on that port, "
                "or a firewall rejected the connection.")
    else:
        line = (f"{shown} — no answer within {answer.get('timeout_ms')} ms. The host may be down, "
                "a firewall may be dropping the traffic, or this workstation's network mode may "
                "not reach it.")
    if answer.get("via_gateway") is True:
        hint = (" If it should be reachable, a rule there is the first place to look."
                if result != "connected" else "")
        line += ("\nThis address isn't on one of the workstation's own subnets, so the connection "
                 "went through your gateway/firewall." + hint)
    return line


async def run_network(content: Any, *, owner: Optional[str]) -> Dict[str, Any]:
    from src.workstation_access import ensure_ready
    from src.workstation_client import WorkstationError

    args, problem = parse_args(content)
    if problem:
        return {"error": problem, "exit_code": 1}
    action = args["action"]
    if not lan_reach_on():
        return {"error": "Reaching the local network is turned off on this install. An admin turns it "
                         "on in Settings (LAN reach).", "exit_code": 1}
    if action == "reach":
        refusal = _refusal(args["host"])
        if refusal:
            return {"error": refusal, "exit_code": 1}
    try:
        ready = await ensure_ready(owner)
    except WorkstationError as e:
        return e.as_result()
    if action == "list":
        daemon_action, fields = "interfaces", {}
    else:
        from src import networks as N
        daemon_action = "reach"
        fields = {k: v for k, v in args.items() if k in ("host", "port", "timeout_ms")}
        deny = N.untrusted_ranges()
        if deny:
            fields["deny"] = deny
    try:
        answer = await ready.client.network(ready.account, daemon_action, **fields) or {}
    except WorkstationError as e:
        return e.as_result()
    if action == "reach":
        return {"output": reach_text(answer), "exit_code": 0, "ran_in": "workstation"}
    return {"output": interfaces_text(answer), "exit_code": 0, "ran_in": "workstation"}


class NetworkTool:
    """The registry's handler; the dispatcher calls `run_network` with the
    turn's owner."""

    async def execute(self, content: str, ctx: Optional[dict] = None) -> Dict[str, Any]:
        return await run_network(content, owner=(ctx or {}).get("owner"))
