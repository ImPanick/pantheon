# Frontier Elevation — Parked Ideas

Not in the ledger. Not scoped. Not decided. Notes only.

---

## Container Station

**The idea:** deploy and manage Docker containers from inside Odysseus.

**Why it's stronger than it first sounds.** The obvious pitch is "deploy things from the UI."
The better pitch is that it closes the biggest hole in the product's own threat model.

`THREAT_MODEL.md` — Known Gap 1, verbatim:

> No shell/filesystem sandbox. The agent `bash` and `read_file`/`write_file` tools run as the
> app process user with **no network egress filtering or filesystem confinement**. A successful
> prompt-injection reaching a shell-enabled admin session can make outbound requests to internal
> services. See #1058 for the sandbox proposal.

So the sandbox is already an acknowledged gap with an open proposal against it. A container
station is that sandbox — the deploy capability is the side effect, not the point.

Second reason it matters: the app container already has the **host Docker socket mounted** for
Cookbook. Anything running inside reaches the host daemon. A container station that owns and
mediates that access is strictly better than the current situation, where it's ambient.

**What already exists that it would extend — Cookbook has ~70% of the hard parts:**

- remote host registry with SSH
- tmux session lifecycle (launch detached, survive disconnect, reattach)
- a per-host mutex so two jobs never fight over the same machine
- GPU detection and hardware-fit calculation
- zombie revival — probes `tmux has-session` and flips a task back to running if it finds one alive
- a background job store with PID liveness that survives a server restart
- server-side reconciliation merging known jobs back into client state

A container station is Cookbook's sibling, not a new subsystem.

**Open questions if it's ever picked up:**

- Does the agent get a *persistent* sandbox container or a fresh one per run? Per-run is safer,
  slower, and loses state between rounds.
- Egress policy — the whole point is filtering, so what's the default? Deny-all with an allowlist
  is the only version that closes the gap.
- Does the agent get to *create* containers, or only *run inside* one someone else defined?
  Creating means image pulls, which means network, which means the thing you were confining.
- Where does the Docker socket live once this exists? Mediated through the station, or still
  ambient for Cookbook? Two paths to the daemon is worse than one.

---

## VM Station

**The idea:** run full virtual machines inside Odysseus.

**Current read: hold.** Not because it's bad — because value-per-complexity is much worse than
containers and it overlaps them for most of what an agent actually needs a machine for.

**What you'd be signing up to own:**

- disk image management (tens of GB each) and snapshot lifecycle
- virtual networking
- a browser console — VNC or SPICE, streamed and input-mapped
- GPU passthrough if any of it is to be useful for model work
- **nested virtualisation.** On cybertooth, Docker already runs inside WSL2. VMs there means
  VMs inside a VM — a real performance and reliability tax before shipping anything.

**Where it genuinely wins over containers:** a full desktop OS. Windows-specific testing. GUI
automation against a real environment. Kernel-level work. These are real, and they're a
different product from what Odysseus is.

**The middle path, if the need turns out to be real:** don't build a hypervisor. Wire to one
that already runs — Proxmox and libvirt both have clean APIs. And the right way to reach an
external hypervisor from Odysseus is **an MCP server**.

Which closes the loop: MCP Creator is how the VM station gets added without building one.

---

## Ordering, if both ever happen

1. Container station, framed as the sandbox — it has a threat-model justification, an open
   upstream proposal, and 70% of its machinery already written in Cookbook.
2. MCP Creator ships (it's in the ledger as Section G).
3. VM control arrives as an MCP server against Proxmox or libvirt — no new subsystem.
