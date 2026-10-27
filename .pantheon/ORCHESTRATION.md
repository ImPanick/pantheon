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

### A route and its caller land in one merge (`B596`)

`check-unreachable.py` holds a ceiling on routes no frontend code calls, and it sits at
zero headroom on purpose — a ratchet with slack is where the next unwired route hides. Its
second effect is the one to plan around: **a branch that adds a route without the code that
calls it fails the gate on its own**, however soon the caller is coming. That shaped `P8`
(`P8-11`, `P8-12` and `P8-16` were built on `manage_skills` actions rather than new routes)
and `P12-09`, whose endpoint waited a commit for its composer (`B752`).

So, when a wave is cut:

1. **Split work by vertical slice, not by layer.** A route and its `fetch` belong to the
   same agent and the same branch. A wave that gives the backend to one agent and the page to
   another has built the failure in.
2. **If a pair must be split, it merges as a pair.** Both branches name the other in their
   report; the integrator merges both before running the gate, and neither lands alone.
   A branch whose other half is not ready does not carry the route — it waits with its
   caller.
3. **Never buy the slot.** Raising the ceiling, or putting a browser-called route in
   `ALLOWED`, makes the ratchet fit an unwired half. `ALLOWED` is for callers that are not
   the browser, each with its reason.
4. **The ceiling only comes down.** Wiring or retiring a route is the only way a slot is
   bought back, and the change that does it lowers the number in `ci.yml` in the same commit.

The checker's failure message points here, so the rule is met where it bites.

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
5. **The static-asset facts** — no bind mount, never move a `?v=` on one site (an edit
   needs no bump to reach a browser; `AGENTS.md` § Operational facts, `B780`), nonce
   inline scripts, add zero external requests.
6. **No `git stash` in a worktree.** Every worktree of one repository shares one
   `refs/stash` stack, so a `pop` in one takes whatever another pushed last. Measured
   2026-10-26: two agents stashing in the same minute each popped the other's work —
   three `src/` files for nineteen checker files — and only the patches they had saved
   by hand put it back. Set work aside with `git diff > file` and `git apply`, or a
   commit on your own branch.

---

## What I'd run first

`P2` — un-nerf. It has **no dependencies at all**, six clean file-ownership batches, and
it's the phase where you feel the difference immediately. `P2-01` alone means your `.js`
uploads start working.

Then `P1`, because everything visual depends on the token layer.

`P0` sits ahead of both on paper, but the rename is a script you run and read — it
doesn't need a workflow.
