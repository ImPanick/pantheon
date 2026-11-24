# SPDX-License-Identifier: AGPL-3.0-or-later
"""The names a host goes by when it is this machine, a local server, or a
place no fetch may go — one module, with each meaning named.

`B2177`. About a dozen modules spelled their own set of these: `{"localhost",
"127.0.0.1", "::1"}`, the same with `"0.0.0.0"`, with `"::"`, with
`"host.docker.internal"`, two different sets in `routes/model_routes.py` alone,
and five different lists of the names an outbound fetch refuses. Several of the
differences are real — a set that *allows* (a local model server is billed
nothing, the LM Studio probe goes only to a local host, the limiter does not
pace the operator's own services) must not grow, and a set that *refuses* (an
SSRF guard, the eval world's loopback wall) must not shrink — so this is not
one set. It is the few sets there are, each named for what it means, and every
call site reads the one it meant (`D-2026-11-24-02`). Where two sites asked the
same question with different members, the allowing set kept its members and
the refusing sets took their union. `tests/test_one_list_of_local_names.py`
pins every call site's answers.

No DNS here: every check is on the name or literal as typed.
"""

from __future__ import annotations

# ── this machine, as a client types it ─────────────────────────────────────

#: Loopback, the three ways it is typed.
LOOPBACK_NAMES = frozenset({"localhost", "127.0.0.1", "::1"})
#: The any-address a server binds; typed as a client's target it reaches this
#: machine.
ANY_ADDRESS_NAMES = frozenset({"0.0.0.0", "::"})
#: The name Docker gives the host from inside a container.
DOCKER_HOST_NAMES = frozenset({"host.docker.internal"})

#: Every name that reaches this machine: loopback or the any-address. The
#: model routes' loopback rewrite for a server inside Docker reads this, and the
#: eval world's loopback wall refuses it.
THIS_MACHINE_NAMES = LOOPBACK_NAMES | ANY_ADDRESS_NAMES

#: A model server on this machine, as the endpoint classifiers have always
#: known it: loopback and `0.0.0.0`, not `::`. Allowing (a local endpoint is
#: billed nothing and probed for reachability), so it keeps its members: adding
#: `::` would widen it, and that is a ruling, not a refactor.
LOCAL_SERVER_NAMES = LOOPBACK_NAMES | frozenset({"0.0.0.0"})
#: The same, plus the Docker host: what `model_context.is_local_endpoint`, the
#: endpoint resolver and the LM Studio probe call a local endpoint by name.
LOCAL_ENDPOINT_NAMES = LOCAL_SERVER_NAMES | DOCKER_HOST_NAMES


def names_this_machine(host: str | None) -> bool:
    return (host or "").strip("[]").lower() in THIS_MACHINE_NAMES


# ── names no outbound fetch reaches ─────────────────────────────────────────

#: Names that are this machine without a lookup. `.localhost` is reserved for
#: loopback too (RFC 6761), see `is_loopback_alias`.
LOOPBACK_ALIASES = frozenset({"localhost", "localhost.", "ip6-localhost", "ip6-loopback"})
#: Cloud metadata services, by name.
METADATA_NAMES = frozenset({"metadata", "metadata.google.internal"})
#: Refused by name before any lookup by every SSRF guard: the union of the five
#: lists the guards carried, so none of them refuses less than it did.
NEVER_FETCHED_NAMES = LOOPBACK_ALIASES | METADATA_NAMES


def is_loopback_alias(host: str | None) -> bool:
    name = (host or "").strip().lower()
    return name in LOOPBACK_ALIASES or name.endswith(".localhost")


def is_never_fetched_name(host: str | None) -> bool:
    """Refused by name, whatever the LAN setting: this machine and the cloud
    metadata names."""
    name = (host or "").strip().lower()
    return name in NEVER_FETCHED_NAMES or name.endswith(".localhost")


# ── names an operator owns (not an SSRF question) ──────────────────────────

#: The outbound limiter's: services an operator runs, paced as local
#: (`src/rate_limiter.host_is_local`). Allowing (no politeness delay), so it
#: does not take the vault's wider suffixes.
OPERATOR_SERVICE_NAMES = frozenset({
    "localhost", "host.docker.internal", "gateway.docker.internal",
    # compose service names — inside the network Pantheon ships with
    "pantheon", "searxng", "chromadb", "chroma", "ntfy", "ollama",
    # `B1226`: and the workstation's, which were paced as a stranger's.
    "workstation", "workstation-net", "workstation-vm",
})
OPERATOR_SERVICE_SUFFIXES = (".local", ".lan", ".internal", ".localdomain", ".home.arpa")

#: The vault's: a bare name only a local network knows is opened over http,
#: everything else over https (`browserWindow.addressOf`'s rule). Wider than the
#: limiter's (`.home`, `.test`) because it decides a default scheme, not whether
#: a third party is spared a pause.
PLAIN_HTTP_SUFFIXES = (".lan", ".local", ".home", ".internal", ".localdomain", ".home.arpa", ".test")
