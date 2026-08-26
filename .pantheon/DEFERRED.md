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

---

## D-04 · The vector store — keep ChromaDB for now

**The question.** Should Pantheon swap ChromaDB while the platform is already open?

**Decided: no, not now.** Not because Chroma is the best choice — because the swap that
would be worth doing is bigger than the one being proposed, and none of it is on the path
to anything a user sees.

**Measured coupling.** `chroma_client.py` is a 72-line singleton and looks trivially
swappable. It is not the coupling. The real surface is **130 direct collection-API call
sites across 2,110 lines** in six modules, with **24 tests** referencing Chroma, the
embedding lanes or the collections built on them:

    src/embedding_lanes.py      39 call sites   ← the deepest coupling
    src/rag_vector.py           37
    services/memory/…           27
    src/memory_vector.py        23
    src/service_health.py       16
    src/tool_index.py           15

`embedding_lanes.py` is the hard part: per-embedding-model collections with dimension
tracking and HNSW config. It does not map onto one table.

**What makes a swap actually pay.** Today there are two datastores — SQLite through
SQLAlchemy for six models, and ChromaDB as a separate HTTP service. Two failure modes, a
network hop per vector query, no transaction spanning them, and a startup probe in
`chroma_client.py` that exists purely because an unreachable Chroma used to hang boot for
30–60 seconds.

Swapping Chroma → pgvector while keeping SQLite pays the whole migration cost and buys
almost nothing. **The move that pays is Postgres replacing BOTH at once** — one datastore,
one backup, one connection, and a memory row and its vector written in a single
transaction. If this is ever done, that is the shape.

**Not TimescaleDB, for this.** TimescaleDB is Postgres plus hypertables, compression and
continuous aggregates — it is a time-series extension and it does not do vector search.
The vector extension is **pgvector**, optionally with Timescale's own **pgvectorscale**
(StreamingDiskANN plus statistical binary quantisation) layered on for scale. They ship
from the same company, which is where the association comes from. See D-05: TimescaleDB
has a real place here, just not under the vectors.

**Two things checked that turned out not to be blockers.**

- The one `$contains` reference in `rag_vector.py:563` is in a **comment explaining why
  they do not use it**. There is no `where_document` hybrid-search dependency to port.
- Upstream has migrated this layer before — `scripts/migrate_faiss_to_chroma.py` exists.
  The path is known.

**Revisit when any of these is true.**

- Chroma actually becomes a bottleneck. It is not one at single-user, home-LAN scale.
- The relational store moves to Postgres for its own reasons — then the vectors follow
  for free and D-04 collapses into that work.
- A memory-vs-vector divergence bug is observed in the wild. That is the consistency
  argument becoming concrete rather than theoretical.
- D-05 lands. If Postgres arrives for telemetry, the marginal cost of moving vectors onto
  it drops sharply.

**Do not** start this before P1. Everything visible depends on the token layer, and a
datastore migration delivers zero visible improvement while consuming the attention that
would have gone to 799 reference sites that currently resolve to nothing.

---

## D-05 · Telemetry — the real case for TimescaleDB

**The gap.** `core/database.py:219-221` stores `message_count`, `total_input_tokens` and
`total_output_tokens` as **running totals on a session row**. The time dimension is
discarded at write time. The app therefore cannot answer *what did I spend on Tuesday*,
*which model is getting more expensive*, *how long do agent rounds take now versus last
month*, or *did that prompt change help*. Not because the query is hard — because the
events were never recorded.

**Why this matters more than it looks.** Pantheon is intended as a harness and
orchestration layer for a GPU server. A harness that cannot report on itself is a harness
you have to babysit. Token cost per model, round latency, tool failure rate, queue depth,
GPU utilisation during a serve — these are the numbers that make an orchestrator
trustworthy, and every one of them is a timestamped measurement.

**This is what TimescaleDB is for.** Hypertables, native compression on old partitions,
and continuous aggregates that keep a rolling daily rollup current without a cron job.
A telemetry table is append-only, high-cardinality on time, and queried almost exclusively
by range — the exact shape it was built for.

**Why it is an addition, not a replacement.** It touches nothing that exists. No
migration, no coupling to unpick, no risk to the six models or the six collections. It is
a new table and a write call in `llm_core.py` where the usage delta is already parsed and
then folded into a running total.

**Sequencing.** Cheapest useful version first: record the events. One append-only table,
written where the totals are already computed. Dashboards, rollups and the Timescale
extension itself only earn their place once there is data worth compressing.

**Revisit when** the GPU-harness use case becomes real, or the first time a question about
usage over time cannot be answered.
