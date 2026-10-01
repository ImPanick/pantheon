# SPDX-License-Identifier: AGPL-3.0-or-later
"""The network agent: the process that actually has the LAN.

`P17-01`, from `D-2026-09-10-01`. Measured from inside the running container on
the owner's own machine, 2026-09-11: `1.1.1.1:53` **reachable**, `192.168.1.1:80`
**TimeoutError**. The agent had more reach to the public internet than to the
network it lives on.

**That measurement no longer holds there (`B975`).** Measured 2026-10-01 on the
owner's Docker Desktop 29.7.2 for Windows, from a container on the default bridge
and on a compose network: `192.168.1.1:80` and `:443` and the host's
`192.168.1.71:445` all **open**. How much LAN a container reaches is Docker's
answer and it changed under us, so nothing here may rest on the container being
unable to reach the LAN. What this package is for does not: a bridged
container's neighbour table is the bridge's and its addresses are the bridge's,
so the network *as the host sees it* — the devices it has talked to, the
segments it sits on, what answers there — lives in a small process on the host,
and Pantheon holds a *credential* for it rather than the capability itself.

THREE RULES THIS PACKAGE KEEPS.

**1. It imports nothing from the app.** Not `src`, not `core`, not `routes`.
It runs on the operator's host, outside Docker, and a host is not a place to
install SQLAlchemy and a vector store so a laptop can list its own ARP table.
Standard library only — a test asserts it.

**2. It is small enough to read in one sitting.** That is the security model,
not a style preference: this process has the LAN, and a thing with the LAN that
nobody has read is worse than no thing at all.

**3. It is not `companion/`.** `Law 14`, and the difference is direction.
`companion/` is **inbound** — a phone pairing *to* Pantheon, authenticating
itself to us. This is **outbound** — Pantheon authenticating *itself* to the
agent. Different direction, different process, not a duplicate. The token
machinery is the same shape pointed the other way, and reusing the shape rather
than the module is what keeps rule 1.
"""
