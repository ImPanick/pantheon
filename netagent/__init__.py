# SPDX-License-Identifier: AGPL-3.0-or-later
"""The network agent: the process that actually has the LAN.

`P17-01`, from `D-2026-09-10-01`. Measured from inside the running container on
the owner's own machine: `1.1.1.1:53` **reachable**, `192.168.1.1:80`
**TimeoutError**. The agent had more reach to the public internet than to the
network it lives on.

**The container staying unable to reach the LAN is a feature, not a
consolation.** The alternative is handing LAN reach to a 2.9GB container that
runs agent-authored code, which would put the owner's network inside its blast
radius by construction. So the capability lives in a small process on the host
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
