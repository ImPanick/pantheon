"""Named network segments, and a scope the agent cannot reason its way out of.

`P16-16`. The owner's north star includes automating things on *"my network
(even my parallel networks etc)"*, and that is not what the product does. Today
`model_discovery._get_hosts()` returns one flat list — loopback,
`host.docker.internal`, whatever `LLM_HOSTS` says, and every Tailscale peer —
assembled from wherever the container happens to sit. There is no notion of
*which* network a host belongs to, so there is nothing to scope.

Several segments at once is not a bigger scan. A VLAN for printers, a lab
subnet behind a jump host, a second tailnet, the production network: those have
different reachability, different credentials and **different trust**, and
flattening them into one pool means an agent asked to tidy the lab can reach
production. The fix is that a host belongs to a named thing, and a run can be
told which names it may use.

`Law 16` IS NOT IN TENSION WITH THIS. The law is about defaults, not capability:
a network the operator *named* is a network they linked. Nothing is declared out
of the box, and with nothing declared this module changes no behaviour at all —
`network_for()` returns None, no scope is active, and every existing call path
runs exactly as it did.

WHAT THIS ENFORCES, AND WHAT IT HONESTLY DOES NOT.

It is a boundary on every connection **Pantheon itself opens on the agent's
behalf**: model endpoint selection, discovery, URL fetches, integrations. Inside
a scope, a host outside it is refused before a socket is opened.

It is **not** an OS-level control. A shell tool running `curl 10.9.9.9` reaches
that address regardless, because the process has a route to it — stopping that
needs a network namespace or a firewall rule, not a Python function. Saying so
here rather than implying otherwise is the point: a boundary described as
tighter than it is, is worse than one described accurately, because people plan
around the description. `P16-20` is filed for the OS-level half.
"""
import contextlib
import contextvars
import ipaddress
import json
import logging
from typing import Any, Dict, Iterable, List, Optional, Sequence, Set

logger = logging.getLogger(__name__)

# Trust levels, ordered. The names are the operator's vocabulary, not ours --
# they describe what a person is willing to let an agent do there.
TRUST_LEVELS = ("untrusted", "limited", "trusted")
DEFAULT_TRUST = "limited"

# The active scope: which declared networks this run may reach. None means "no
# scope in force", which is the shipped state and today's behaviour.
_scope: "contextvars.ContextVar[Optional[frozenset]]" = contextvars.ContextVar(
    "pantheon_network_scope", default=None)


class NetworkScopeViolation(Exception):
    """Raised when something inside a scope reaches for a host outside it.

    An exception, not a False return. A caller that forgets to check a boolean
    gets the reach it should not have had; a caller that forgets to catch this
    gets a loud failure in a test.
    """


class Network:
    """One named segment: what is in it, how far it is trusted."""

    __slots__ = ("name", "hosts", "cidrs", "trust", "enabled", "notes")

    def __init__(self, name: str, hosts: Sequence[str] = (),
                 cidrs: Sequence[str] = (), trust: str = DEFAULT_TRUST,
                 enabled: bool = True, notes: str = "") -> None:
        self.name = str(name).strip()
        self.hosts = [str(h).strip().lower() for h in hosts if str(h).strip()]
        self.cidrs = []
        for raw in cidrs:
            try:
                self.cidrs.append(ipaddress.ip_network(str(raw).strip(), strict=False))
            except ValueError:
                logger.warning("network %r: ignoring unparseable CIDR %r", name, raw)
        self.trust = trust if trust in TRUST_LEVELS else DEFAULT_TRUST
        self.enabled = bool(enabled)
        self.notes = str(notes or "")

    def contains(self, host: str) -> bool:
        host = (host or "").strip().lower().strip("[]")
        if not host:
            return False
        if host in self.hosts:
            return True
        try:
            ip = ipaddress.ip_address(host)
        except ValueError:
            # A name that is not an IP matches only by exact listing. Resolving
            # it here would make membership depend on DNS answered by whichever
            # network we happen to be on -- which is the ambiguity this module
            # exists to remove.
            return False
        return any(ip in cidr for cidr in self.cidrs)

    def as_dict(self) -> Dict[str, Any]:
        return {"name": self.name, "hosts": list(self.hosts),
                "cidrs": [str(c) for c in self.cidrs], "trust": self.trust,
                "enabled": self.enabled, "notes": self.notes}


def _raw_networks() -> List[Dict[str, Any]]:
    try:
        from src.settings import get_setting
        value = get_setting("networks", [])
    except Exception:
        return []
    if isinstance(value, str):
        try:
            value = json.loads(value)
        except Exception:
            logger.warning("networks setting is not valid JSON; ignoring")
            return []
    return value if isinstance(value, list) else []


def declared_networks(*, include_disabled: bool = False) -> List[Network]:
    """Every network the operator has named. Empty out of the box."""
    out = []
    for raw in _raw_networks():
        if not isinstance(raw, dict) or not str(raw.get("name") or "").strip():
            continue
        net = Network(
            name=raw.get("name"),
            hosts=raw.get("hosts") or [],
            cidrs=raw.get("cidrs") or [],
            trust=raw.get("trust") or DEFAULT_TRUST,
            enabled=raw.get("enabled", True),
            notes=raw.get("notes") or "",
        )
        if net.enabled or include_disabled:
            out.append(net)
    return out


def network_for(host: str) -> Optional[str]:
    """Which declared network a host belongs to, or None.

    First match wins, and declaration order is therefore meaningful: a narrow
    segment listed before a broad one keeps its own name. That is stated rather
    than sorted for the operator, because "most specific wins" quietly reorders
    what someone wrote and the surprise lands later.
    """
    for net in declared_networks():
        if net.contains(host):
            return net.name
    return None


def trust_for(host: str) -> Optional[str]:
    for net in declared_networks():
        if net.contains(host):
            return net.trust
    return None


def current_scope() -> Optional[Set[str]]:
    scope = _scope.get()
    return set(scope) if scope is not None else None


@contextlib.contextmanager
def scoped_to(names: Optional[Iterable[str]]):
    """Restrict this run to the named networks. `None` lifts the restriction.

    A ContextVar, so it follows an async task and concurrent runs cannot read
    each other's scope. Restoring the previous value on exit rather than
    clearing it means nesting narrows and never widens -- a scope that could be
    widened from inside is not a scope.
    """
    if names is None:
        token = _scope.set(None)
    else:
        requested = frozenset(str(n).strip() for n in names if str(n).strip())
        existing = _scope.get()
        token = _scope.set(requested if existing is None else (requested & existing))
    try:
        yield current_scope()
    finally:
        _scope.reset(token)


def host_allowed(host: str) -> bool:
    """May this run reach `host`?

    With no scope in force -- the shipped state -- everything is allowed and
    this module is invisible. Inside a scope the rule is deliberately strict:
    a host that belongs to no declared network is **refused**, not waved
    through. "I could not classify it" is not a reason to permit reach; the
    operator who named two segments and asked for one of them did not mean
    "and also anything I forgot to describe".
    """
    scope = _scope.get()
    if scope is None:
        return True
    name = network_for(host)
    return name is not None and name in scope


def require_host(host: str, *, what: str = "connection") -> None:
    """Refuse an out-of-scope host, loudly and with the reason."""
    if host_allowed(host):
        return
    scope = current_scope()
    name = network_for(host)
    where = f"network {name!r}" if name else "no declared network"
    raise NetworkScopeViolation(
        f"{what} to {host!r} refused: it is in {where}, and this run is scoped "
        f"to {sorted(scope or [])}."
    )


def hosts_in_scope() -> Optional[List[str]]:
    """Every explicitly listed host of the in-scope networks, or None.

    Used by discovery to scan the right segments. CIDRs are deliberately not
    expanded: a /16 is 65,536 addresses, and turning a declaration into a sweep
    is how a "scan my networks" feature becomes a port scanner someone's IDS
    reports. CIDRs classify; listed hosts are scanned.
    """
    scope = _scope.get()
    nets = declared_networks()
    if scope is not None:
        nets = [n for n in nets if n.name in scope]
    elif not nets:
        return None
    out: List[str] = []
    for net in nets:
        for host in net.hosts:
            if host not in out:
                out.append(host)
    return out


def summary() -> Dict[str, Any]:
    """What is declared and what is in force. For diagnostics and the UI."""
    nets = declared_networks(include_disabled=True)
    return {
        "networks": [n.as_dict() for n in nets],
        "declared": len(nets),
        "enabled": sum(1 for n in nets if n.enabled),
        "scope": sorted(current_scope() or []) if current_scope() is not None else None,
    }
