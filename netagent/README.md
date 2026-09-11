<!-- SPDX-License-Identifier: AGPL-3.0-or-later -->
# The network agent

Pantheon runs in a container and cannot reach your LAN. **That is deliberate.**
The alternative is handing LAN reach to a 2.9 GB container that runs
agent-authored code, which would put your network inside its blast radius by
construction.

So the capability lives here instead: a small read-only process you run on the
machine that has the network, and Pantheon holds a *credential* for it rather
than the reach itself.

## What it is

Three modules, standard library only. No dependencies, nothing to install, and
nothing from the Pantheon application is imported — a test enforces both. It is
meant to be read in one sitting; that is the security model, not a style
preference.

| Route | Answers |
|---|---|
| `GET /health` | that it is running, and that it is this agent |
| `GET /whoami` | the hostname, and every address this host answers on, classified |
| `GET /networks` | the private `/24`s it sits on, ready to paste into Settings → Networks |
| `GET /neighbours` | the ARP/neighbour table — devices this machine has actually talked to |
| `GET /reach?target=…` | whether something is there, and which ports answered |
| `GET /dns?target=…` | reverse lookup of an address, forward lookup of an allowed name |

`/neighbours` is **not a scan.** It reads the machine's own cache — devices it
has exchanged traffic with recently. Nothing is probed and no packet is sent, so
a quiet device will not appear. That is deliberate: turning "look at my network"
into a sweep is how a convenience becomes something your IDS reports. Its rows
are filtered to the allowlist, and the answer says how many were withheld, so a
short list reads as a narrow allowlist rather than an empty network.

`/dns` is gated like `/reach` and for a reason worth stating: a **forward** lookup
is an outbound channel. Resolving `<secret>.attacker.example.com` puts the secret
in somebody's DNS logs without a single packet reaching the "target". So a forward
lookup works only for a name you listed with `--allow-host`; reverse lookups of
allowed addresses are unaffected and are the common case.

Every route needs the token. `POST` returns **405** — changing firewall rules,
router settings or DHCP is a different risk class from reading them, and bundling
it in would mean the thing that describes your network can also break it
(`P17-05`).

## The allowlist

**This is the boundary, and it is set here rather than in Pantheon.** `P17-02`:
a gate the gated party can widen is not a gate, and Pantheon is the gated party.
A Pantheon that has been talked into anything at all — by a web page, by a
document, by anything it was asked to read — still cannot widen this, because
the widening move does not exist on its side of the wire.

```
python -m netagent.server --allow 192.168.1.0/24
```

Repeatable. `--allow-host nas.local` names a single host. Also read from
`PANTHEON_NETAGENT_ALLOW` and `PANTHEON_NETAGENT_ALLOW_HOSTS`; the command line
wins.

**With nothing allowed the agent refuses every target.** Not "allow all until
configured" — the point is that `10.0.0.0/8` is refused *because it was never
named*, and a list that starts open has no such answer to give. `/whoami` and
`/networks` still work, because they describe this machine rather than reach
anything; run them first to see what you have, then allow what you meant.

Names are never resolved to decide membership. `--allow 127.0.0.0/8` does **not**
allow `localhost`, deliberately: resolving would make the boundary depend on DNS
answered by whichever network you happen to be on, which is the ambiguity an
allowlist exists to remove. List the name if you want the name.

An unparseable CIDR is **reported**, not silently dropped — a typo in a security
boundary that quietly narrows it is the kindest possible failure and still the
wrong one.

## Running it

```
python -m netagent.server --allow 192.168.1.0/24
```

On first run it mints a token and prints it **once**:

```
====================================================================
  A token was minted for this agent. Paste it into Pantheon:

      pan_…

  Settings -> Networks -> Agent. It is not recoverable from
  ~/.pantheon-netagent/token.json, which holds only its hash.
====================================================================
```

Paste it into **Settings → Networks → Network agent**, along with the address.
Press *Check connection*.

### The bind address

It listens on `127.0.0.1:7010` by default. **Nothing listens beyond this machine
unless you say so** — that is `Law 16`, and it means the safe value is the one
that ships.

If Pantheon runs in Docker on this same machine, the container reaches the host
through `host.docker.internal`, which does **not** arrive on loopback. Bind to
the address the container can see and set the address in Pantheon to match:

```
python -m netagent.server --bind 0.0.0.0 --port 7010
```

…and in Pantheon: `http://host.docker.internal:7010`.

Binding to `0.0.0.0` puts the agent on your LAN. It is authenticated, read-only
and refuses an unknown token — but it is a listener, and you should know you
opened it. If your firewall can scope the port to the Docker bridge only, do
that.

### Keeping it running

Deliberately **not** a service installer. A background service is the kind of
change that is easy to install and hard to remember you installed, and this
process has the LAN. Start with a terminal you can see. When you want it to
survive a logout, use your platform's own scheduler, where it shows up in a list
you already know how to read:

**Windows** — Task Scheduler, *Create Task*:
- *Triggers*: At log on
- *Actions*: Start a program — `pythonw.exe`, arguments
  `-m netagent.server --bind 0.0.0.0 --allow 192.168.1.0/24`
- *Start in*: your Pantheon checkout

**macOS / Linux** — a user-level `launchd` job or `systemd --user` unit in the
usual place. Nothing here needs root, and if something tells you it does, that is
worth stopping to read.

## Environment

| Variable | Default | Meaning |
|---|---|---|
| `PANTHEON_NETAGENT_BIND` | `127.0.0.1` | address to listen on |
| `PANTHEON_NETAGENT_PORT` | `7010` | port |
| `PANTHEON_NETAGENT_STATE` | `~/.pantheon-netagent` | where the token hash is kept |
| `PANTHEON_NETAGENT_ALLOW` | *(empty — refuses everything)* | networks it may be asked about |
| `PANTHEON_NETAGENT_ALLOW_HOSTS` | *(empty)* | single names it may be asked about |

## If the token is lost

Delete `token.json` in the state directory and restart. A new one is minted and
printed. The old one stops working immediately, which is the point of storing
only a hash: the file is not the credential, so losing the file is a
re-pairing rather than a leak.
