# Orchestration — how the phases actually get built

Short answer to "can each phase be an agent with sub-agents and its own adversarial
reviewer": **yes, and it's the right shape.** But three things have to be true first,
and two of them aren't yet.

---

## The blocker nobody mentioned

**The repo is on cybertooth. The agents run in a cloud container. They are not the
same machine.**

Right now every file operation would have to go through the desktop bridge — which is
exactly what just dropped. That makes the bridge a single point of failure for a
250-agent build, and it makes every edit a round-trip over a link that has already
proven flaky.

**Fix: `R-06`.** Once the repo is pushed to GitHub, clone it into the build container.
From then on:

```
agents → cloud clone → push branch → you pull on cybertooth → rebuild → look at it
```

The desktop stops being on the critical path. It becomes the place you *verify*, not the
place work happens. This is the single most important setup step and it costs one clone.

---

## Why one agent per task is the wrong granularity

221 tasks × (implementer + reviewer) = 442 agents. Under the lifetime cap, but wrong for
a different reason: **agents editing the same file in parallel collide.**

Twelve P1 tasks all edit `style.css`. Six P5 tasks all edit the composer. Running those
concurrently produces conflicts, not throughput.

**Batch by file ownership, not by task count.** One agent owns a file or a coherent
subsystem for the duration of a phase and executes every task that touches it.

---

## The shape

Per phase:

```
  ┌─ scout ─────────── reads the source, confirms each task's premise is still true
  │                    (AGENTS.md rule 3), returns a corrected work-list
  │
  ├─ implement ─────── N agents, batched by file ownership, running in parallel
  │    │               each writes its own handoff note
  │    └─ verify ───── one adversarial reviewer per implementer, prompted to REFUTE:
  │                    "find where this is wrong, incomplete, or broke something"
  │
  └─ integrate ─────── one agent: runs the full test suite, reconciles the handoff
                       notes, ticks the roadmap, reports what's still open
```

The scout matters more than it looks. This roadmap was built from six audit passes and
**still had wrong numbers when an adversarial pass checked it** — a tally that didn't
match its own rows, thirteen wrong figures, two fabricated claims. Assume more remain.
An agent that implements a task with a false premise produces confident garbage.

The adversarial reviewer is not a second opinion, it's a hostile one. Prompt it to break
the change, not to bless it. Default its verdict to "refuted" when uncertain.

---

## Realistic agent counts

| Phase | Batches | Agents (scout + impl + verify + integrate) |
|---|---|---|
| P0 | 4 | ~10 |
| P1 | 3 | ~8 |
| P2 | 6 | ~14 |
| P3 | 3 | ~8 |
| P4 | 6 | ~14 |
| P5 | 5 | ~12 |
| P6 | 4 | ~10 |
| P7 | 3 | ~8 |
| P8 | 9 | ~20 |
| P9 | 5 | ~12 |
| P10 | 3 | ~8 |
| | | **~124 total** |

Comfortably inside the 1000 lifetime cap. Concurrency is capped around 16 at a time, so
a phase's implement stage runs in one or two waves.

**Run one phase per turn.** Read the integrate report, decide, then launch the next. Do
not chain phases inside a single workflow — the dependencies are real and you want a
human decision at each boundary.

---

## Where parallelism is genuinely unsafe

**P0** — the rename sweep is one `sed` across 371 files. Do not parallelise it. One agent,
one pass, one diff to review.

**P1-01** — defining `--accent` repaints **799 sites at once**. Its own step, app open,
eyes on it. Not batched with anything.

**P4-01** — unifying the six drifted agent-thread templates requires *deciding* which
behaviour is correct. That's a judgement call with a written rationale, not a parallel
task. Everything else in P4 waits on it.

**Anything touching `style.css`** — 41,401 lines, 963 property re-declarations across 405
selectors. Two agents editing it concurrently will conflict. Serialise or use worktree
isolation.

Worktree isolation (`isolation: 'worktree'`) gives each agent its own checkout and is the
answer when parallel mutation is unavoidable — but merging them back is manual, so use it
only where the throughput is worth the merge.

---

## Non-negotiables for every spawned agent

Put these in every prompt. Not a reference to a file — the actual text.

1. **`FORBIDDEN.md` Part 1** — the names that cannot move.
2. **`FORBIDDEN.md` Part 2** — the security controls that never lift. An agent asked to
   "remove restrictions" will happily remove the email inline-image content-type check,
   which is the one thing standing between a crafted email and a same-origin HTML page.
3. **AGENTS.md rule 3** — verify the premise against the source. Stop if it's false.
4. **Write the handoff note before finishing.** An agent that finishes without one has
   not finished.
5. **The static-asset facts** — no bind mount, bump the cache-buster, nonce inline
   scripts, add zero external requests.

---

## What I'd run first

`P2` — un-nerf. It has **no dependencies at all**, six clean file-ownership batches, and
it's the phase where you feel the difference immediately. `P2-01` alone means your `.js`
uploads start working.

Then `P1`, because everything visual depends on the token layer.

`P0` sits ahead of both on paper, but the rename is a script you run and read — it
doesn't need a workflow.
