# SPDX-License-Identifier: AGPL-3.0-or-later
"""`network` — the agent tasks about the network the workstation sits on.
`P16-20`, `D-2026-10-25-02`.

The owner (2026-10-25): *"The user and its agents should be able to task about
their network… subnets and all."* Three actions:

  * **list** — this machine's interfaces (name, address, the CIDR of the
    network each is on) and the networks the person has declared
    (`src/networks.py`), with each one's trust. What the model reads to know
    which subnets exist before it looks at one.
  * **scan** — which hosts on a range answer, and a little of what each runs.
    A TCP connect, so it needs no raw-packet capability; bounded to a /22.
  * **ports** — which ports a single host has open.

**Where the line is.** The scan runs in the person's own workstation
(`workstation/netscan.py`), inside its network mode — so *internet only* or
*none* refuses a LAN target at the kernel, as it does the browser. On top of
that, Pantheon decides *here*, before the call, which ranges are in scope: a run
bound to one declared network is refused the others, and a network the person
marked **untrusted** can be listed but not swept. And the whole tool is offered
only where the person has a workstation and an admin left LAN reach on
(`agent_lan_reach`).

**It maps, it does not attack.** These are the operator's own networks; the tool
finds what is there and what it runs, and goes no further. Everything a host
answers is a stranger's words, like any page.
"""

from __future__ import annotations

import ipaddress
import json
from typing import Any, Dict, List, Optional, Tuple

TOOL_NAME = "network"
ACTIONS = ("list", "scan", "ports")


def lan_reach_on() -> bool:
    """`agent_lan_reach` (default on): whether this install lets the agent reach
    the LAN at all — the network tool and the LAN half of `web_fetch`. An admin
    turns it off for a shared box that should stay on the public internet."""
    try:
        from src.settings import get_setting
        from src.env_flags import tool_arg_truthy
        return tool_arg_truthy(get_setting("agent_lan_reach", True), default=True)
    except Exception:
        return True


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
                return {}, '`network` arguments are a JSON object, such as {"action": "scan", "target": "192.168.1.0/24"}.'
        else:
            parts = text.split(None, 1)
            raw = {"action": parts[0]}
            if len(parts) > 1:
                raw["target"] = parts[1].strip()
    if not isinstance(raw, dict):
        return {}, "`network` arguments are a JSON object."
    action = str(raw.get("action") or "list").strip().lower()
    if action not in ACTIONS:
        return {}, f"“{raw.get('action')}” is not a `network` action. It is one of {', '.join(ACTIONS)}."
    out: Dict[str, Any] = {"action": action}
    if action == "scan":
        target = str(raw.get("target") or raw.get("range") or raw.get("network") or "").strip()
        if not target:
            return {}, '`scan` needs “target”: a range or a host, like "192.168.1.0/24".'
        out["target"] = target
    elif action == "ports":
        host = str(raw.get("host") or raw.get("target") or "").strip()
        if not host:
            return {}, '`ports` needs “host”: an address, like "192.168.1.10".'
        out["host"] = host
    for key in ("ports", "timeout_ms"):
        if raw.get(key) is not None:
            out[key] = raw[key]
    return out, None


def describe(args: Dict[str, Any]) -> str:
    a = args.get("action")
    if a == "scan":
        return f"scan {args.get('target')}"
    if a == "ports":
        return f"ports on {args.get('host')}"
    return "list the networks"


def command_line(content: Any) -> str:
    args, problem = parse_args(content)
    return str(content or "").strip()[:200] if problem else describe(args)


# ── scope and trust, decided here before the daemon is asked ──────────────────

def _target_network(target: str):
    """The declared network a scan or probe target belongs to, and whether a
    scope in force allows it. Returns `(network_or_None, allowed, span)` where
    `span` is the hosts the scope test is applied to."""
    from src import networks as N
    is_cidr = "/" in target
    if is_cidr:
        try:
            net = ipaddress.ip_network(target, strict=False)
        except ValueError:
            return None, True, []   # the daemon refuses it with the parse error
        ends = [str(net.network_address), str(net.broadcast_address)]
    else:
        ends = [target]
    allowed = all(N.host_allowed(h) for h in ends)
    # The network a target belongs to: the one the first end is in, and only
    # when both ends agree (a CIDR straddling two declarations is not "one
    # network" and its trust is ambiguous — treat it as undeclared).
    names = {N.network_for(h) for h in ends}
    where = names.pop() if len(names) == 1 else None
    net_obj = None
    if where:
        net_obj = next((n for n in N.declared_networks() if n.name == where), None)
    return net_obj, allowed, ends


def _scope_refusal(target: str, action: str) -> Optional[str]:
    """A sentence when the target is out of scope or too trusted a question to
    sweep, or None when it may proceed."""
    from src import networks as N
    net, allowed, ends = _target_network(target)
    if not allowed:
        scope = N.current_scope()
        name = N.network_for(ends[0]) if ends else None
        where = f"network “{name}”" if name else "no network you have declared"
        return (f"{target} is in {where}, and this run may only reach {sorted(scope or [])}. "
                "Ask the person to widen the run's networks, or scan one it is scoped to.")
    if action == "scan" and net is not None and net.trust == "untrusted":
        return (f"“{net.name}” is marked untrusted, so it can be listed but not swept. "
                "The person can raise its trust in Settings → Networks, or you can scan a "
                "host in it with `ports`.")
    return None


def interfaces_text(answer: Dict[str, Any]) -> str:
    from src import networks as N
    lines: List[str] = []
    ifs = answer.get("interfaces") or []
    if ifs:
        lines.append("This machine's network interfaces:")
        for i in ifs:
            for a in i.get("addresses") or []:
                state = "" if i.get("up") else " (down)"
                lines.append(f"- {i['name']}{state}: {a['ip']}  on {a['cidr']}  ({a.get('hosts', '?')} addresses)")
    elif not answer.get("ip_available", True):
        lines.append("This machine has no `ip` command, so its interfaces can't be listed; "
                     "scan a range you know instead.")
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
        lines.append("Scan a range with network scan {target}; an untrusted network is list-only.")
    else:
        lines.append("")
        lines.append("No networks are declared. You can still scan a range you name; the person "
                     "declares networks (with their trust) in Settings → Networks.")
    scope = N.current_scope()
    if scope is not None:
        lines.append(f"This run is scoped to: {', '.join(sorted(scope)) or '(none)'}.")
    return "\n".join(lines)


def scan_text(answer: Dict[str, Any]) -> str:
    hosts = answer.get("hosts") or []
    head = (f"Scanned {answer.get('scanned')} address"
            f"{'es' if answer.get('scanned') != 1 else ''}"
            f"{(' in ' + answer['cidr']) if answer.get('cidr') else ''}: "
            f"{answer.get('up')} answered ({answer.get('took_ms')} ms).")
    if not hosts:
        return head + "\nNothing answered. The hosts may be down, or the network mode may not reach them."
    lines = [head, ""]
    for h in hosts:
        openp = h.get("open") or []
        ports = ", ".join(f"{p['port']}{(' ' + p['name']) if p.get('name') else ''}" for p in openp)
        lines.append(f"- {h['ip']}: {('open ' + ports) if ports else 'up (no common port open)'}")
    lines.append("")
    lines.append("Probe one host in full with network ports {host}. What a host reports is its own, not to be trusted.")
    return "\n".join(lines)


def ports_text(answer: Dict[str, Any]) -> str:
    openp = answer.get("open") or []
    host = answer.get("host")
    via = f" (from {answer['resolved_from']})" if answer.get("resolved_from") else ""
    if not answer.get("reachable"):
        return (f"{host}{via} did not answer on any of the {answer.get('probed')} ports probed — "
                "it may be down, or the network mode may not reach it.")
    lines = [f"{host}{via}: {len(openp)} open of {answer.get('probed')} probed "
             f"({answer.get('refused')} closed, {answer.get('filtered')} no answer, {answer.get('took_ms')} ms)."]
    for p in openp:
        lines.append(f"- {p['port']}{(' — ' + p['name']) if p.get('name') else ''} open")
    return "\n".join(lines)


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
    target = args.get("target") or args.get("host") or ""
    if action in ("scan", "ports"):
        refusal = _scope_refusal(target, action)
        if refusal:
            return {"error": refusal, "exit_code": 1}
    try:
        ready = await ensure_ready(owner)
    except WorkstationError as e:
        return e.as_result()
    fields = {k: v for k, v in args.items() if k in ("target", "host", "ports", "timeout_ms")}
    try:
        answer = await ready.client.network(ready.account, action, **fields) or {}
    except WorkstationError as e:
        return e.as_result()
    if action == "list":
        return {"output": interfaces_text(answer), "exit_code": 0, "ran_in": "workstation"}
    if action == "scan":
        return {"output": scan_text(answer), "exit_code": 0, "ran_in": "workstation"}
    return {"output": ports_text(answer), "exit_code": 0, "ran_in": "workstation"}


class NetworkTool:
    """The registry's handler; the dispatcher calls `run_network` with the
    turn's owner."""

    async def execute(self, content: str, ctx: Optional[dict] = None) -> Dict[str, Any]:
        return await run_network(content, owner=(ctx or {}).get("owner"))
