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

---

## D-06 · Training and fine-tuning — not scope creep, if it stays adapters

**The ask.** Pantheon already serves models. Could it also train them — so that alongside
self-adapting skills, RAG, and LLM-assisted MCP and automation building, the models themselves
refine over time?

**The honest answer: this fits, and it fits better than most things that get called scope
creep — but only under one constraint, and the constraint is the whole decision.**

### Why it genuinely fits

The hard infrastructure is **already built, for serving**. A training run needs exactly what
the Forge already has: a remote host registry with SSH, GPU detection and hardware fit, a
long-running job lifecycle held open in tmux, a zombie-revival probe that checks whether a
session is still alive before declaring a job dead, weight download and cache management, and a
file-durable background job store with PID liveness that survives a server restart. Roughly
70% of a training station is the serving station.

And Pantheon has the thing nobody else building this has: **the data**. Chat transcripts,
approved tool traces, the RAG corpus, skill invocations that worked and ones that did not. The
scarce input for a useful fine-tune is a good dataset, and this platform is already sitting on
one.

### The constraint: adapters, never full fine-tuning

Everything else in Pantheon's adaptation story — skills, RAG, MCP servers, automations — shares
one property: **it is reversible and inspectable.** You can read a skill. You can delete it and
be exactly where you were. You can see which documents a retrieval pulled.

A fine-tune is neither. You cannot read a weight delta, and you cannot un-bake it. Worse, a bad
fine-tune **does not error** — it just gets quietly, subtly worse at things you were not
testing. For a harness whose entire pitch is being a glass box, that is the most dangerous
possible failure mode, because it looks like nothing.

**LoRA and QLoRA adapters restore the property.** An adapter is a separate file of tens to
hundreds of megabytes, it attaches and detaches at serve time, vLLM and llama.cpp both load
them as a first-class feature, and turning one off puts you exactly back where you started.
That is the same contract as a skill. Full fine-tuning breaks it and should never ship here.

### The second constraint: an eval gate is mandatory

Training without evaluation is a random walk that feels like progress. A held-out set and a
before/after comparison, with the adapter **not promoted unless it wins**, is not a nice-to-have
— it is the difference between a feature and a way to quietly degrade your own platform.

This is also why `D-05` telemetry comes first. You cannot gate on a measurement you do not take.

### What it would actually be

1. **Dataset curation from what already exists** — transcripts, approved tool traces, RAG
   corpus. Explicit opt-in per source, with a review step. This is the largest piece of work
   and the real differentiator; the training run is the easy part.
2. **LoRA / QLoRA runs on the Forge's existing remote-host machinery.** No new subsystem for
   hosts, SSH, GPU detection or job lifecycle.
3. **Adapter registry** — versioned, with the dataset and hyperparameters that produced each
   one recorded beside it. An adapter whose provenance is unknown is not promotable.
4. **Eval harness and the promotion gate.**
5. **Serve with the adapter attached** — vLLM `--enable-lora`, llama.cpp adapter loading.

### Where this is scope creep, stated plainly

- **"Train models"** is scope creep. Full fine-tuning, base-model pretraining, anything that
  produces a weight file you cannot detach.
- **Training without the eval gate** is worse than scope creep; it is a liability.
- **Building it before `P11`/`P12`** is scope creep of a different kind: a training run is the
  single most expensive thing a user could trigger, and shipping that capability before
  per-role quotas exist means one person can consume a GPU server indefinitely with no control
  available to the operator.

**Revisit when** the Forge rename has landed and settled, `P11` and `P12` are in place so a
training job can be quota'd and permissioned, `D-05` telemetry exists so eval has somewhere to
report, and there is a real GPU host to run on. In that order. None of those is a stalling
tactic — each one is a thing that must exist for the feature to be safe rather than impressive.

