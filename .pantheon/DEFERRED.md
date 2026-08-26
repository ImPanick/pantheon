# DEFERRED — decided, not scheduled

Three items are deliberately out of the roadmap's critical path. Each has a reason and a
condition for revisiting. None is "we forgot".

---

## D-01 · The approval card's new markup

**What's deferred:** effect chips, the fingerprint badge, the expiry countdown, and the
taint trail — everything in the elevated approval card that needs markup that doesn't
exist yet.

**Why.** Two CI tests assert **literal source strings** from that renderer, including
exact class assignments and the event-dispatch line. And the code around it is the
hottest in the upstream project: fifteen commits in four weeks, twelve of them on a
single day, a revert inside the most recent pull request, and the current HEAD sitting
in that cluster. There is also a cache-buster contract requiring a version string to be
bumped across six modules in lockstep — get it wrong and a browser pairs new code with a
cached interceptor, so the approval click lands on the New-chat branch.

**What can proceed now.** The style-only subset, through selectors that already exist:

- **P4-04** — render the server's own written reason. It is on the wire and the renderer
  never reads the field. Pure data, no new markup.
- **P7-06 / P7-07 / P7-08** — effect ranking, tripped-effect identification, and the
  taint trail can all be *computed and sent* now; only their presentation waits.

**Revisit when.** The upstream commits in that cluster stop landing daily. Check the log
before starting; if the last three weeks are quiet, it's safe.

**Do not.** Weaken or route around the approval store's seal, TTL, single-use
consumption, or owner binding to make presentation easier. Dismissing a card retires it
but preserves the taint — that is deliberate, and it is what stops the card being used to
launder an action.

---

## D-02 · Container station

**What it is.** Deploying and managing containers from inside Pantheon.

**Why it's parked, not dropped.** It's a good idea framed badly. The obvious pitch is
"deploy things from the UI". The better one is that it closes the largest acknowledged
hole in the product's own threat model, which states plainly that the agent's shell and
filesystem tools run as the app user with **no egress filtering and no filesystem
confinement**, and points at an open sandbox proposal. A container station *is* that
sandbox; deployment is the side effect.

Second reason it matters: the app container already has the **host Docker socket
mounted** for Cookbook. Anything inside reaches the host daemon. A station that owns and
mediates that access is strictly better than the current ambient arrangement.

**What already exists.** Cookbook has roughly 70% of the hard parts — a remote host
registry with SSH, tmux session lifecycle, a per-host mutex, GPU detection and
hardware-fit, and a zombie-revival probe that checks whether a tmux session is still
alive before declaring a job dead. Plus a file-durable background job store with PID
liveness that survives a server restart. This is Cookbook's sibling, not a new subsystem.

**Open questions to settle first.**

- Persistent sandbox container per session, or fresh per run? Per-run is safer, slower,
  and loses state between rounds.
- Egress default. The whole point is filtering, so deny-all with an allowlist is the only
  version that actually closes the gap.
- Does the agent get to *create* containers, or only *run inside* one someone defined?
  Creating means image pulls, which means network, which is the thing you were confining.
- Where does the Docker socket live afterwards — mediated through the station, or still
  ambient for Cookbook? Two paths to the daemon is worse than one.

**Revisit when.** P8 is complete and there's appetite for a security-shaped project
rather than a feature-shaped one.

---

## D-03 · VM station

**What it is.** Running full virtual machines inside Pantheon.

**Why it's held.** Value-per-complexity is much worse than containers, and it overlaps
them for most of what an agent needs a machine for. You'd own disk image management (tens
of GB each), snapshot lifecycle, virtual networking, a browser console over VNC or SPICE,
and GPU passthrough if any of it is to be useful for model work — plus **nested
virtualisation**, because on a Windows host Docker already runs inside WSL2. That's a
real performance and reliability tax before anything ships.

**Where it genuinely wins.** A full desktop OS. Windows-specific testing. GUI automation
against a real environment. Kernel work. These are real needs — they're just a different
product from what Pantheon is.

**The path if the need proves real.** Don't build a hypervisor. Wire to one that already
runs — Proxmox and libvirt both have clean APIs — and reach it **through an MCP server**.

Which closes the loop: **P8's MCP Creator is how the VM station gets added without
building one.**

**Revisit when.** Someone has a concrete task that a container demonstrably cannot do.
