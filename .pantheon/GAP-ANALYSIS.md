# Capability gaps, measured — 2026-09-13

`P17-06` asked for a gap analysis *"derived from what the agent is actually
asked to do rather than from imagination"*. `P17-07` built the instrumentation.
`P17-08` said the analysis could not be written from this tree — **0 sessions,
0 chat messages, 1 `events` row** — and that the corpus existed on one running
deployment and nowhere else.

This is that run. It was produced by
[`.pantheon/gap-analysis.py`](gap-analysis.py) against a snapshot of the
owner's deployment, and **the script is the artifact**: a page of figures from
a database nobody else can open is exactly the *trust us* this fork's ledger
refuses. Run it against your own and you get your own answer.

```
python3 .pantheon/gap-analysis.py /path/to/snapshot-of-app.db
```

Take the snapshot with `sqlite3.Connection.backup()` from a `mode=ro` source.
The script will not open a database read-write, and prints no message content —
every figure in it is a count or a name.

## The corpus

| | |
|---|---|
| sessions | 14 (12 with messages) |
| user messages | 48 |
| assistant messages | 50 |
| events | 168 |
| runs | 40 |
| window | 2026-09-10 05:53 – 2026-09-11 05:01 |

**A corpus this size is a signal and not a conclusion**, and every number below
is a count from these rows. Nothing is extrapolated. What it is good for is
finding *shapes* — and it found three, two of which are defects in the
instrumentation rather than in the tools.

## 1. There are two tool channels and the receipt records one

**`create_document` was called 19 times. In 17 of them it was not in its own
run's recorded offer.** Every other called tool matched its run's offer exactly;
the single exception is one `bash` call in the one run that recorded no config
at all.

A tool the model has no schema for should be impossible to call. These arrived
through the **fenced tool channel** — the agent writes a ```` ```create_document ````
block and it executes — which is described in prose inside the system prompt and
leaves no offer fingerprint anywhere.

That reframes everything else in this report. *Offered and never picked* is a
statement about the schema channel only, and **the most-used tool on this
deployment is not in it.** A tool reachable the other way is neither offered nor
missing: it sits in neither column, and a gap analysis that only reads
`run_config` will never see it. Filed as `P17-12`.

**Fixed 2026-09-13**, the same day. `run_config` now records `fenced` beside
`tools`, and the script checks calls against both channels. **The numbers above
are from before that landed** and are kept as they were measured — a corrected
figure and a recorded one are different things, and this file is the record.
The next run against a deployment on this code will have a *called without
being offered* column that is empty for the right reason; if it is not, what is
in it is a genuine third channel and worth reading.

## 2. Failures record that they happened, never why

**Seven of eight failed tool calls have an empty `detail`.** The eighth says
`{"policy": "p"}`. One of three `capability_gap` events recorded `{}` — the
event fired and named nothing, so it says a gap happened and not which one.

The most striking number in the report is unusable because of this:

| tool | offered | called | failed |
|---|---|---|---|
| `web_fetch` | 37 | 3 | **3** |

A 100% failure rate on the tool the selector reaches for most often, and the
rows cannot say whether it was a blocked host, a timeout, a parse failure or a
dead URL. Those are four different fixes. Filed as `P17-13`.

## 3. The selector's top pick is the least-used tool

Tool selection is active: a run is offered a **median of 11** tools out of 81,
with a range of 0–40. So the offer column is not *what exists*, it is *what the
selector chose* — which makes it a measurement of the selector.

| tool | offered (of 39 runs) | called |
|---|---|---|
| `ask_user` | 39 | 1 |
| `web_search` | 37 | **0** |
| `web_fetch` | 37 | 3 (all failed) |
| `update_plan` | 30 | 5 |
| `manage_memory` | 22 | **0** |
| `manage_bg_jobs` | 22 | 1 |
| `ask_teacher` | 20 | **0** |
| `pipeline` | 20 | **0** |
| `manage_tasks` | 17 | **0** |
| `create_document` | 1 | **19** |

69 of 81 tools were offered and never picked. Unnecessary, undiscoverable or
badly described are three different problems that look identical from outside,
and this column cannot tell them apart — it can only say which tools to ask the
question about. Filed as `P17-14`.

Two entries are worth reading against other rows rather than on their own.
`manage_memory` is offered 22 times and never called, and it is already `B67`'s
subject — a tool dispatched natively while its MCP server runs as a shadow.
`ask_teacher` is offered 20 times and never called, and `P17-07` found that the
teacher path returns at its first gate unless two settings are on, both of which
default off.

## What this data cannot see

**A tool the agent was never offered leaves no row anywhere.** Nothing here is
evidence about capabilities that do not exist — only about the ones that do.
That half needs a different method, and saying so is the difference between a
limitation and a silent one.

And one correction, recorded because the first account of it was published in a
commit message before it was checked: chasing finding 1, the cause was first
written down as a latch in `_capture_run_config` that lets a tools-less capture
suppress a later one carrying the list. That bug is real and readable in the
source — three call sites, one latch, and only `stream_llm` passes `tools` — but
**it is not what happened here**: 39 of 40 runs recorded a tool list. It is
fixed anyway, as a latent bug found while chasing something else, and the claim
that the data proved it has been withdrawn from the places it reached.
