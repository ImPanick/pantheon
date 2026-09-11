# SPDX-License-Identifier: AGPL-3.0-or-later
"""What this agent will answer for. Set on the host; Pantheon cannot change it.

`P17-02`. The row says *"operator-set and not agent-writable, because a gate the
gated party can widen is not a gate"* — and **Pantheon is the gated party.** So
the list does not live in Pantheon's settings, where a compromised Pantheon could
edit it and where `manage_settings` is one prompt injection away from trying. It
lives here, as arguments to the process the operator started, on the machine they
started it on. A Pantheon that has been talked into anything at all still cannot
widen this, because the widening move does not exist on this side of the wire.

**Empty refuses everything, and that is the shipped state.** Not "allow all until
configured" — the whole argument of `P17-02` is that *"enumerate 10.0.0.0/8"* is
refused **because 10.x was never named**, rather than because a model declined,
which is not a security control. An allowlist that starts open has no such
answer to give.

**TWO LAYERS, DIFFERENT OWNERS, AND THIS IS NOT A DUPLICATE OF `src/networks.py`.**
`Law 14` deserves the argument rather than a claim:

  * `src/networks.py` **directs**. It is Pantheon's own scoping — a run told to
    work on the lab is offered the lab's endpoints and refused the others. It
    answers *"which of my networks is this run about?"*, it is set by the
    operator in Pantheon, and its failures are mistakes: an agent tidying the lab
    and wandering onto the printer VLAN.
  * This **bounds**. It answers *"what may this process be asked about at all?"*,
    it is set outside Pantheon, and its failure mode is not a mistake — it is a
    Pantheon that has been told to do something by a web page.

One can be narrowed by the thing it governs; the other cannot. That is what makes
them two things rather than one thing written twice. The vocabulary is
deliberately shared — cidrs and hosts, exactly as `Network` splits them — so a
reader moving between the two files is not learning a second dialect.

**Names are not resolved here**, for the reason `src/networks.py` gives in its
own comment: resolving would make membership depend on DNS answered by whichever
network we happen to be on, which is the ambiguity the allowlist exists to
remove. An IP literal is matched against the CIDRs; a name matches only by exact
listing.
"""
from __future__ import annotations

import ipaddress
import os
from typing import Iterable, List, Optional, Sequence, Tuple

ENV_CIDRS = "PANTHEON_NETAGENT_ALLOW"
ENV_HOSTS = "PANTHEON_NETAGENT_ALLOW_HOSTS"


def _split(raw: str) -> List[str]:
    return [part for part in str(raw or "").replace(",", " ").split() if part]


class Allowlist:
    """The addresses and names this agent will answer questions about."""

    __slots__ = ("cidrs", "hosts", "rejected")

    def __init__(self, cidrs: Sequence[str] = (), hosts: Sequence[str] = ()) -> None:
        self.cidrs: List[ipaddress._BaseNetwork] = []
        self.rejected: List[str] = []
        for raw in cidrs:
            text = str(raw).strip()
            if not text:
                continue
            try:
                self.cidrs.append(ipaddress.ip_network(text, strict=False))
            except ValueError:
                # Recorded, not dropped. A typo in a security boundary that
                # silently narrows it is the kindest possible failure and still
                # the wrong one: the operator believes they named a network and
                # nothing tells them otherwise. `serve()` prints these.
                self.rejected.append(text)
        self.hosts = [str(h).strip().lower() for h in hosts if str(h).strip()]

    @classmethod
    def from_env_and_args(cls, cidrs: Optional[Iterable[str]] = None,
                          hosts: Optional[Iterable[str]] = None) -> "Allowlist":
        """Command line first, environment second, nothing third."""
        given_cidrs = list(cidrs or []) or _split(os.environ.get(ENV_CIDRS, ""))
        given_hosts = list(hosts or []) or _split(os.environ.get(ENV_HOSTS, ""))
        return cls(given_cidrs, given_hosts)

    def is_empty(self) -> bool:
        return not self.cidrs and not self.hosts

    def allows(self, target: str) -> bool:
        """May this agent be asked about `target`?

        Empty list, no. Unparseable target, no. A name not listed exactly, no —
        *"I could not classify it"* is never a reason to permit reach, which is
        the same rule `networks.host_allowed` states one layer over.
        """
        target = str(target or "").strip().lower().strip("[]")
        if not target:
            return False
        # There is deliberately no `if self.is_empty(): return False` here, and
        # its absence is the safe direction rather than an oversight. An empty
        # list already refuses by construction: `target in []` is False and
        # `any(... for cidr in [])` is False, so the function fails closed with
        # no help. Mutation testing showed the guard could not change an answer,
        # and a branch that cannot change an answer is deleted rather than tested
        # around — the same call as `P13-14`'s cutoff and `P13-15`'s dead
        # `sessions <= 1`. Keeping it would also suggest the empty case needs
        # special handling, which is an invitation to "fix" it the other way.
        # `is_empty()` is still live: `refusal()` uses it to say something more
        # useful than "not in the list" when there is no list.
        if target in self.hosts:
            return True
        try:
            ip = ipaddress.ip_address(target.split("%")[0])
        except ValueError:
            return False
        return any(ip in cidr for cidr in self.cidrs)

    def refusal(self, target: str) -> str:
        """Why, in a sentence that tells the operator what to do about it."""
        if self.is_empty():
            return (f"{target!r} is refused: this agent has no allowlist, so it "
                    f"answers for nothing. Start it with --allow <cidr>.")
        return (f"{target!r} is refused: it is not in this agent's allowlist "
                f"({self.describe()}). The list is set where the agent was "
                f"started and cannot be changed from Pantheon.")

    def describe(self) -> str:
        parts = [str(c) for c in self.cidrs] + list(self.hosts)
        return ", ".join(parts) if parts else "empty"

    def as_dict(self) -> dict:
        return {"cidrs": [str(c) for c in self.cidrs], "hosts": list(self.hosts),
                "rejected": list(self.rejected)}
