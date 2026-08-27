# Pantheon — Working Agreement

Read this before touching anything. It is short on purpose.

Pantheon is a fork of **Odysseus** (`pewdiepie-archdaemon/odysseus`, AGPL-3.0).
The whole programme is **elevation, not rewrite**. The engines already work. What was
missing was the surface, the lighting, and the room you stand in to build things.

**`ROADMAP.md` is the only tracker.** One task list, one progress area. There are no
per-area handoff files — there were sixteen, all empty, and they are gone.

---

## The Laws

Three about the work. Ten about drift and discipline. All of them came from something that actually
went wrong — every anti-drift law below cites the incident that produced it, because a
law with no scar behind it gets ignored.

### Law 1 — Add. Never subtract.
If a feature exists, it survives. If you think something should go, propose it on the
task line — you do not delete it. The only exceptions are items explicitly marked
`DELETE` in the roadmap, each proven dead by audit.

### Law 2 — Names in `FORBIDDEN.md` do not move.
Class names, data attributes, storage keys, env vars and wire values listed there are
load-bearing. Renaming one silently breaks the accessibility shim, a CI test, or a
user's stored preferences. Style freely; rename nothing on that list.

### Law 3 — Verify against the code, not against the plan.
The roadmap was written from six audit passes and still contained wrong numbers when an
adversarial pass checked it. A scout pass on P2 then found the archetype task wrong in
three ways, and the hostile reviewers overturned the scouts on **twelve of twelve**
contested calls. **Assume the line you are reading is wrong until the source agrees.**
If it does not, correct the task line in `ROADMAP.md` and stop.

---

## The anti-drift laws

Drift is not one failure. It is eight, and they compound: a wrong number becomes a wrong
plan becomes a wrong implementation, and by then nobody remembers which step was the lie.

### Law 4 — The roadmap is updated every turn. No exceptions.
**Every single turn.** Not at the end of a phase, not when it feels significant, not when
there is something impressive to report. If a turn produced nothing, the roadmap says so.
A tracker updated *sometimes* is worse than no tracker, because people trust it.

This is the one law with no judgement call in it. Ticked a task, corrected a premise,
found a bug, changed your mind, got blocked, did nothing — it goes in. Then run
`python3 .pantheon/check-tracker.py`.

### Law 5 — A number without a stated scope is not a number.
`--accent` is referenced **799** times, or **950**, or **1,014**, depending entirely on
whether you counted `var(--accent…)` in `style.css`, every appearance of the token in
that file, or every appearance across CSS, JS and HTML. All three are true. Only one
answers the question being asked.

Write the scope into the claim: *"799 `var(--accent…)` sites in `static/style.css`, 205
of them bare."* Never *"799 references."*

> **Incident.** The programme's own README first said `--fg-muted` was referenced 93
> times. It is referenced 101 times, 93 of them without a fallback. Both numbers were
> real measurements of different things, and the sentence was still wrong.

### Law 6 — Count it, do not carry it.
Never copy a number out of a document into another document. Re-measure it. Numbers
propagate faster than corrections do, and a figure that has been quoted three times looks
authoritative regardless of whether it was ever right.

> **Incident.** A tally of `45 / 51 / 15 / 52 = 163` had been incremented by hand each
> pass instead of counted from its own rows. Recounting gave `29 / 20 / 18 / 41 = 108`.
> Thirteen other figures in the same document were wrong the same way.

### Law 7 — One source of truth per fact. Duplicates go stale, never both.
If two files state the same thing, one of them is already wrong or shortly will be. Delete
the copy and link to the original.

> **Incident.** `FRONTIER-NOTES.md` and `DEFERRED.md` both described the container and VM
> stations. `DEFERRED.md` was updated; `FRONTIER-NOTES.md` was not, and still called the
> project Odysseus weeks after the rename. It was deleted, not reconciled.

### Law 8 — Derived state is checked by a script, never by eye.
Any summary computed from detail — a status table, a total, a count of open items — gets
a checker that recomputes it and fails on mismatch. `check-tracker.py` is that for the
status table. Run it after any batch of ticks.

> **Incident.** The status table claimed eight P0 tasks were done while every P0 task line
> still read `- [ ]`. An agent reading the table would have skipped work; an agent reading
> the lines would have redone it.

### Law 9 — Done means verified, not written.
A task is done when its `Verify:` line passes, not when the edit lands. "The code was
changed" and "the thing works" are different claims, and the gap between them is where
the worst drift lives — because it looks finished.

> **Incident.** The rename sweep renamed six ChromaDB collections in code and looked
> complete. The volume still held the old collections, so memory, RAG and the tool index
> silently returned nothing. Nothing errored. It is `P0-05`, and it shipped looking done.

### Law 10 — A tool's output must be unambiguous to whatever consumes it.
Excludes must match the stated intent. Field names must have one reading. A boolean whose
polarity can be understood two ways **will** be understood both ways, and the automation
downstream of it will silently do the wrong thing while every individual step looks correct.

Prefer an enum to a boolean for any verdict. `verdict: upheld | refuted | inconclusive` cannot
be misread; `stands: true/false` can.

> **Incident (excludes).** The rename sweep's own header said it excluded attribution files. It
> did not exclude `CHANGELOG.md`, so it would have rewritten *"forked from Odysseus"* into
> *"forked from Pantheon"*, and it did not exclude itself, so a second run would have rewritten
> its own search string.

> **Incident (polarity).** A reviewer schema defined `stands: false` as *"the change is wrong"*.
> Every reviewer read it as *"my challenge did not stand"* and returned `false` on findings they
> had just confirmed as sound — with `severity: none` beside it. The agent consuming the field
> then skipped the **eight best-validated** fragments in the run and applied the ones with real
> defects. Eight of the ten remaining ids traced to that one word. Nothing wrong shipped, but
> only because a later agent noticed the contradiction between the two fields.
A script that says what it protects and then does not protect it is worse than one that
makes no claim, because the claim is what people review instead of the behaviour.

> **Incident.** The rename sweep's own header said it excluded attribution files. It did
> not exclude `CHANGELOG.md`, so it would have rewritten *"forked from Odysseus"* into
> *"forked from Pantheon"*. It also did not exclude itself, so a second run would have
> rewritten its own search string and self-destructed.

### Law 11 — Edit one copy. Sync deliberately, never incidentally.
When the same file exists in two places, decide which is authoritative before you touch
either, and propagate in one explicit step. Never assume an edit landed on both.

> **Incident.** `ROADMAP.md` existed in the build package and in the repo. Two consecutive
> edits went to different copies. The second silently reverted part of the first.

### Law 12 — Adversarial review is the default, not the escalation.
An agent that checks its own work confirms it. Findings get a reviewer whose job is to
**refute** them, defaulting to refuted when uncertain. This is not paranoia; it is the
measured hit rate.

> **Incident.** Six scouts read the source and produced findings. Six reviewers tried to
> break them. The reviewers won **twelve of twelve** contested calls — including proving
> that the phase's headline task was wrong in three separate ways.

---

## Before you start a task

```
□ Read the task's full entry in ROADMAP.md — including `Depends`, `CI` and `Verify`
□ Check DECISIONS.md — the call may already be settled, with reasons
□ Check FORBIDDEN.md Part 1 (names) and Part 2 (controls that never lift)
□ Confirm the task's premise is true in the current source        ← rule 3
□ If `CI` is set, read the named test BEFORE editing — several assert on source
  text rather than behaviour, so a clean refactor can still fail them
□ Claim it: flip `- [ ]` to `- [·]` and put your agent id on the line
```

## Before you tick a task

```
□ The task's own `Verify:` line passes
□ `python -m pytest -q` passes, or every failure is pre-existing and named
□ `python -m py_compile app.py routes/*.py src/*.py` passes
□ `node --check static/js/<each file you touched>.js` passes
□ You ran the app and looked at it (any visual change)
□ The cache-buster is bumped if you touched a static asset
□ ROADMAP.md is updated and `python3 .pantheon/check-tracker.py` passes   ← Law 4
```

Tick by changing `- [·]` to `- [x]` in `ROADMAP.md` and adding a one-clause trace to the
task line. Never tick a task you did not finish — a partly done task stays open with a
note saying what is left.

---

## Where things get written

One tracker, one progress area. Nothing else.

| What you have | Where it goes |
|---|---|
| A finished **phase** | **one** entry in `ROADMAP.md` § Progress — two lines and a commit range |
| A finished **task** | the tick and a one-clause trace on its own line |
| A premise that was wrong | corrected on the task line itself, in place |
| A bug you found but did not fix | § Bugs at the bottom of `ROADMAP.md`, as a new `Bxx` |
| A judgement call someone might re-litigate | `DECISIONS.md` — with what it costs, not just what it permits |
| Everything else | the commit message |

**The commit message is the report.** § Progress is a two-line trace that a section
landed, not a summary of how. Write the detail where `git log` will keep it.

A phase entry looks like this and no longer:

```markdown
### P2 · Un-nerf — implemented
Upload type check deleted, four dead config blocks removed, admin panels rewired,
blocklists trimmed. `a1c6f2c … 9e40b17`
```

---

## Ground truth, in order

**A contradiction between two programme documents is a bug. Resolve it; do not rank it.**
The list below breaks ties for a question nobody has answered yet. It is not a licence to
implement from a document you can see is contradicted by another one. If two files disagree,
stop, work out which is newer and better evidenced, fix the loser **in place** so the next
agent never meets the same fork in the road, and say in your report that you did.

> **Incident.** `P2-CORRECTED.md` § D said P2-09 and P2-13 could not be verified without the
> fork head. The roadmap task lines said the fork-head check was done and cited the diff. Both
> were in the repo; nothing said which won. Seven agents each silently assumed P2-CORRECTED
> superseded, and the integrator had to surface the contradiction as an open question after the
> work was already done.

1. **The source.** Beats everything. See rule 3.
2. **`P2-CORRECTED.md`** for anything in P2 — it was verified against the source by
   thirteen agents and it supersedes P2's task text.
3. **`DECISIONS.md`** for a settled call, and what accepting it cost.
4. **The roadmap task line.**
5. **The mockup** (`design/pantheon-v10.html`) — what it should look like when done. It
   is a mockup: it fakes its data and does not reproduce every state. Where it disagrees
   with the source, the source wins and you file the discrepancy.

---

## Operational facts that bite

- **`static/` has no bind mount.** Every CSS or JS change needs
  `docker compose up -d --build`. A restart serves the old files.
- **Bump the cache-buster** on any changed static asset, or browsers keep the old one.
  The service worker has its own: `CACHE_NAME` in `static/sw.js`.
- **The approval-path modules share one version string** and must be bumped together,
  or a browser pairs new code with a cached interceptor and the approval click lands
  on the wrong branch. The list is in `FORBIDDEN.md`.
- **No route in this app can set a CSP header.** `SecurityHeadersMiddleware` runs after
  the route and overwrites it — starlette replaces duplicate headers rather than
  appending. A task that tells you to set one at a handler is wrong; the branch goes in
  the middleware.
- **`python-magic` is Docker-only.** It is in the `Dockerfile` but in neither
  `requirements.txt` nor `requirements-optional.txt`, so on a pip or venv install the
  content sniffer is `None` and `mimetypes` decides. Reason about uploads from
  `mimetypes` unless you are reasoning about the image specifically.
- **CI skips the entire pytest job for docs-only PRs** (`.github/workflows/ci.yml`). A
  documentation change that claims to have re-validated something ran zero tests.
- **No build step, no bundler, no framework.** ES modules load directly.
- **Nonce every inline script.** The CSP requires it.
- **Add zero external requests.** Self-host anything new.

---

## Where things run

Three machines, and the tools do not reach the same one.

- Edit files with **`device_bash`** — but it cannot unlink, so `sed -i`, `git commit`
  and `git gc` all fail there.
- Do everything git, gh or docker through **`Windows-MCP`** on cybertooth.
- Read the source at **`/work/base`** in the cloud container — upstream at exactly
  `b4d1293`, the fork point. The fork itself is private, so you cannot clone it; hand
  back patches.

Full table in `ROADMAP.md` § Where things run.

---

## When to stop and ask

- A task's premise is false in the source.
- A change would touch something in `FORBIDDEN.md`.
- A change would touch the approval card's markup (see `DEFERRED.md`).
- You are about to remove a security control. Read `FORBIDDEN.md` § Never Lift first;
  if it is on that list, the answer is no.
- Two tasks conflict and the roadmap does not say which wins.


### Law 13 — Nothing ships half-wired.
A backend with no caller, an element id with no markup, a flag with no consumer, a module
loaded on every boot that returns early on a missing element — **that is not "built", it is
drift**, and calling it velocity is how it accumulates. If you cannot finish the wiring in the
same change, the task is not done: it stays open with a note saying what is missing, and the
unwired half does not merge.

`python3 .pantheon/check-wiring.py` counts it. The number is **2** unresolved
`getElementById` targets — measured as: static-string lookups across `static/js/**` excluding
`static/lib/**`, minus ids present in any tracked HTML, minus ids the JS itself creates at
runtime. **It may go down. It may not go up.**

*It said 78 until 2026-08-27, which was the count before wiring run 01 cleared them — the law
against carrying numbers, carrying a number. Both remaining entries are checker artifacts, not
drift, and the CI ceiling is `--max 2`. The checker has two known blind spots, written up on
`P3-15`: it scans neither `static/app.js` nor `static/sw.js`, and it sees only literal
`getElementById`, so helper lookups like `el('adm-*')` are invisible to it.*

> **Incident.** An audit of one phase found a complete webhooks backend with no UI at all, a
> skills editor behind a flag whose list was never fetched, a Real-ESRGAN upscaler with no
> button, a RAG module called on every single startup that bails on a missing element, and
> plan mode whose docked window three prompt strings promise and nobody ever drew. None of it
> was broken. All of it passed CI. Nothing measured whether it was reachable.

### Law 14 — Extend the primary scaffolding. Never build a second one.
Before adding anything, ask: **does this create a second way to do something that already
works?** If it does, the answer is to extend the first one. A second implementation is not
redundancy, it is a fork in the maintenance path where one side goes stale and nobody notices
which.

This applies to plans as much as to code. A new capability that fits an existing phase belongs
in that phase, not in a phase of its own — receipts belong in `P4` because `P4` already exists
to render what the backend computes and discards; a visible context budget belongs in `P12`
because `P12` already exists to make limits legible and adjustable. Inventing `P14 · Receipts`
would be the same mistake in a different medium.

> **Incident.** This codebase carries **two** dead RAG interfaces, an admin MCP form duplicating
> a working one in settings, two files named `ROADMAP.md` saying different things, and two
> `_ADMIN_TOOLS` constants with **opposite** meanings. Not one of those was a bad idea. Each was
> a second way to do something that already had a first way.

### Law 15 — If it needs a tutorial, it is not finished.
Power that cannot be operated is worth less than a modest thing that can. A feature whose
learning curve requires documentation nobody wrote has not shipped — it has been *placed*.

The test: **can someone who has never seen this surface tell, from the surface alone, what it
is for and what to do next?** If the answer needs a paragraph of explanation, the surface is
the thing to fix.

> **Incident.** A competitor's memory-graph feature — genuinely more advanced than anything
> here — was abandoned by an interested beta user who wanted it to work, because there were no
> tutorials and the curve was too steep for the time available. The capability was real. The
> adoption was zero. That is the whole lesson.


