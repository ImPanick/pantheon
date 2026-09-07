# Pantheon — Working Agreement

Read this before touching anything. It is short on purpose.

Pantheon is a fork of **Odysseus** (`pewdiepie-archdaemon/odysseus`, AGPL-3.0).
The whole programme is **elevation, not rewrite**. The engines already work. What was
missing was the surface, the lighting, and the room you stand in to build things.

**`ROADMAP.md` is the only tracker.** One task list, one progress area. There are no
per-area handoff files — there were sixteen, all empty, and they are gone.

---

## The Laws

Three about the work. Twelve about drift and discipline. All of them came from something that actually
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

Drift is not one failure. It is the twelve below, and they compound: a wrong number becomes a
wrong plan becomes a wrong implementation, and by then nobody remembers which step was the lie.

### Law 4 — The roadmap is updated every turn. No exceptions.
**Every single turn.** Not at the end of a phase, not when it feels significant, not when
there is something impressive to report. If a turn produced nothing, the roadmap says so.
A tracker updated *sometimes* is worse than no tracker, because people trust it.

This is the one law with no judgement call in it. Ticked a task, corrected a premise,
found a bug, changed your mind, got blocked, did nothing — it goes in. Then run
`python3 .pantheon/check-tracker.py`.

### Law 5 — A number without a stated scope is not a number.
`--accent` is referenced **813** times, or **968**, or **1,325**, depending entirely on
whether you counted `var(--accent…)` in `style.css`, every appearance of the token in
that file, or every appearance across CSS, JS and HTML. All three are true. Only one
answers the question being asked.

Write the scope into the claim: *"813 `var(--accent…)` sites in `static/style.css`, 205
of them bare."* Never *"813 references."*

*Those three figures were 799 / 950 / 1,014 until 2026-08-28. `static/style.css` grew by 342
lines that day and every one of them moved. The law's own example is the best demonstration of
the law: **measure it when you cite it.***

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


### Law 13 — Nothing ships half-wired.
A backend with no caller, an element id with no markup, a flag with no consumer, a module
loaded on every boot that returns early on a missing element — **that is not "built", it is
drift**, and calling it velocity is how it accumulates. If you cannot finish the wiring in the
same change, the task is not done: it stays open with a note saying what is missing, and the
unwired half does not merge.

`python3 .pantheon/check-wiring.py` counts it. The number is **124** unresolved element-id
targets — measured as: static-string lookups across `static/js/**` and `static/*.js` excluding
`static/lib/**`, minus ids present in any tracked HTML, minus ids the JS itself creates at
runtime. **It may go down. It may not go up.**

*It said 78 until 2026-08-27, which was the count before wiring run 01 cleared them — the law
against carrying numbers, carrying a number. Then it said 2, and then 9, and neither number was
the truth: the checker saw only literal `getElementById`, and this codebase reaches for elements
through a one-line helper — `ui.el`, `admin.el`, `settings/dom.byId`, all three of them
`return document.getElementById(id)` — at 925 call sites against ~1,100 direct ones. **Nearly
half the wiring in the product was outside the measurement**, and `VERIFY-2026-08-27.md` said
so at the time ("2 ✔ literal-`getElementById`; 125 helper-aware") without the checker ever being
changed. `H07` closed it, and the number went 9 → 124 in one commit without a line of product
code changing. A ratchet nobody widens is a ratchet measuring a smaller and smaller thing; when
the count jumps because the scan improved, say that in the same breath as the new number,
because the alternative is a future reader concluding the product got worse.*

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
A feature nobody can work has not shipped. The owner abandoned a competitor's memory graph for
exactly this reason, and it was better than anything here.

The test: **can someone who has never seen this surface tell, from the surface alone, what it
is for and what to do next?** If the answer needs a paragraph of explanation, the surface is
the thing to fix.

> **Incident.** A competitor's memory-graph feature — genuinely more advanced than anything
> here — was abandoned by an interested beta user who wanted it to work, because there were no
> tutorials and the curve was too steep for the time available. The capability was real. The
> adoption was zero. That is the whole lesson.

### Law 16 — Self-hosted by default. Nothing leaves the machine until someone links it.

The owner's words, 2026-08-31:

> *"we drop external dependence. i dont want things that'll may route to external services
> unless the user (or sysadmin) explicitly links it. the intent is fully self hosted everything,
> with options to add cloud providers via api in which case the cloud provider being API linked
> will have everything the users subscription allows."*

**Amended by the owner the same day, and the amendment is the sharp edge of the law:**

> *"telemetry is fine, but 'phone home' to an external destination is not allowed. if the user
> wants to establish their own telemetry endpoint, they can bypass this law and do so… like
> Prometheus or Grafana etc.. maybe even enrolling other services to connect like OpenSEO, or
> other CRM products"*

**So the rule is about the destination, not the activity.** Measuring is not the sin. Sending
what you measured somewhere the user did not choose is. Rewrite any question of the form *"is X
allowed?"* as ***"who owns the address at the other end?"*** — if the answer is the user or their
sysadmin, it is allowed and always was; if the answer is us, or a vendor, or anyone the user did
not name, it is forbidden however anonymous, aggregated or well-meant it is.

That reframing is what makes the law buildable rather than merely restrictive. Pantheon **should**
be able to emit metrics — to *your* Prometheus, *your* Grafana, *your* OTLP collector — and to
enrol whatever else you connect it to. That is a capability this product is missing, not a
temptation it is resisting.

**The test, and it is a hard one:** install Pantheon on a machine with no credentials configured,
open it, and use it. **Nothing should reach the public internet.** Not a package registry, not a
model catalogue, not a font, not an emoji, not a search engine, not a version check, and not a
metrics push. If a fresh install talks to anyone, that is a defect with a row.

Four clauses, and the second is the one that gets misread:

1. **Default local.** Every endpoint default points at loopback, the LAN, or nothing. A default
   that points at somebody's cloud is a bug however convenient it is.
2. **This is a rule about defaults, not a cap on capability.** Once a person or sysadmin links a
   provider, that provider gets **everything their subscription allows** — full context, full
   model list, full rate. Do not nerf a configured provider in the name of this law; that is a
   different mistake and `P2` exists because this product has made it before.
3. **Deliberate beats silent.** An outbound call a person asked for is fine. The failure is the
   call nobody chose — a convenience default, a `@latest` lookup, a "free, no API key required
   so it is safe to ship on" fallback.
4. **Telemetry is allowed; phoning home is not.** Collect whatever is useful, store it locally by
   default, and export it **only** to an address the user configured. A Prometheus scrape
   endpoint, an OTLP exporter pointed at their collector, a webhook into their CRM — all fine,
   all `Law 16`-compliant, because in every case the user owns the far end. What is never
   permitted, at any sample rate, in any aggregation, is a build that reports to us. **There is
   no opt-out ceremony that makes vendor telemetry acceptable here** — not opt-in, not a consent
   dialog, not "anonymous". The address is the whole test.

> **Incident.** `npx -y @playwright/mcp@latest` ran about three seconds after **every** boot —
> installing from the npm registry on first start and re-checking the dist-tag on every one
> after. A fresh install reached the public internet before the user had clicked anything. Its
> opt-out existed and was inverted, and the comment above it explained the choice plainly, so
> nobody had hidden it. It had simply never been asked the question this law asks.
>
> Alongside it: `search_fallback_chain` shipped as `["duckduckgo"]`, justified in a comment as
> *"free, no API key required, so safe to ship on by default for every user."* On a native
> install SearXNG never starts, so the primary always failed and **every search a user typed
> went to DuckDuckGo** — scraped, under a spoofed desktop user-agent.

**What this law does not say.** It does not say remove capability. `videodb`, `x-api` and the
other vendor-specific skills in the bundled library stay; they do nothing until a person opens
them and supplies their own key. Deleting a capability and defaulting it off are different acts,
and this law asks for the second.

**Nor does it say "no observability".** Reading clause 4 as *do not measure anything* would be
the opposite of what it says, and would leave operators flying blind on their own hardware —
which is `Law 15` failing in a different costume. `P14` owns the measurement; `P16-12` owns the
export. The whole design constraint is one line: **the destination is configured by the person
running it, and there is no default.**

### Law 17 — Ask who the adversary is. If nobody named one, you are building the wrong thing.

Before hardening anything, answer one question out loud: **who is the adversary, and did anyone
ask for one?**

Where the answer is *"nobody — this is a mistake we are preventing"*, build the thing that
prevents mistakes and **stop there**. Where there genuinely is an adversary — someone who may log
in, a hostile document, a tool acting on an approval it never got — build the control and do not
weaken it.

The tell is a rule that starts reasonable and generalises past its purpose. It always sounds like
rigour, and it always costs the same three things: platform-specific plumbing that breaks working
installs, a guarantee nobody asked for, and time not spent on the product.

**Pantheon is an orchestration harness on machines the owner owns.** Traffic between them is
normal. That is a statement about *reach between the operator's own boxes*, and it is never a
statement about the auth boundary — `FORBIDDEN.md` Part 2 and `D-2026-09-01-01` stand, because
those have a real adversary.

> **Incident, twice, three days apart.** `Law 16` was nearly read as *no external capability*
> rather than *no external default* — which would have banned the operator's own Grafana and left
> people blind on their own hardware. The owner corrected it: *"telemetry is fine, but 'phone
> home' to an external destination is not allowed."*
>
> Then `P16-16` shipped network scoping written up as a security boundary, and I filed `P16-20`
> beside it to close the remaining hole with a network namespace or nftables rules. The owner
> corrected that too: *"internal comms, LAN to LAN etc is totally fine. we arent building fort
> knox. just an orchestration harness etc.."* The scoping is for **directing** the agent — it
> stops a model list mixing the lab GPU with the production one, and it does that completely.
> Containing a hostile run is a different problem, and on a machine already executing shell there
> is no adversary left to contain. `P16-20` is deferred (`D-2026-09-01-03`).
>
> Both times the engineering was sound and the *premise* was not. That is the failure this law
> catches, and it is not caught by testing harder.

---


### Law 18 — a mutation run that can be killed must restore itself, or it is a commit you did not make.

Twice in one session a `timeout`-killed mutation script left a checker mutated in the working tree: `check-outbound.py`'s `clientish` guard, and `check-jitter.py`'s computed-sleep guard. Both times the next full suite failed in a way that looked exactly like a real regression — `check-jitter` reporting two recurring jobs on a boundary that had been fine an hour earlier — and both times the diagnosis cost more than the mutation was worth.

A `finally:` block does not run when the process is killed. So a mutation harness registers its restore with `atexit` **and** handles `SIGTERM`/`SIGINT`, and prints `git diff --stat` when it finishes so a leftover is visible in the same output that reported the results. `/tmp/mutlib.py` is that harness.

The general form: **any tool that edits the tree to ask a question must be able to answer it while dying.** The measurement is not worth a silent change to the thing being measured.

### Law 19 — a suite run is evidence about the tree it started with, and nothing else.

The suite takes seven minutes. Editing during those seven minutes is the obvious way to use them, and it silently invalidates the run.

`H02`'s verification came back with two failures that were not in the baseline, both in `test_task_session_folder.py`, both asserting on `inspect.getsource(TaskScheduler._execute_llm_task)`. The tests were fine and the code was fine. `getsource` finds a function by the `co_firstlineno` recorded when the module was **imported**, then reads the file from **disk** — and `src/task_scheduler.py` had grown twelve lines in between, for unrelated work. It returned a different function's body. Re-running the file alone: three passed.

**Eight test files in this repo, at eleven call sites, read their own source this way.** A `git checkout` mid-run does it too, and so does a `sed -i` that only adds a comment. Nothing warns; the failure arrives dressed as a regression in whatever the offset happens to land on, which is the most expensive possible disguise.

**The author broke this law within the hour of writing it**, editing `admin_tools.py` a minute into a run because the change was small and obviously safe. It was small; "obviously safe" is not a property anyone can establish about a suite they have not read. The run was killed and restarted, which cost seven minutes and nothing else — the alternative is a green result about a tree that no longer exists, and that is what the previous paragraph cost. Assume you will want to do this. The answer is still no.

So: **start the suite, then keep your hands off the tree until it finishes.** Read, plan, measure something in a scratch copy, write the roadmap entry — all fine. If an edit cannot wait, the run is spent: make the edit and start a new one. A diff against the baseline is only worth running if the tree did not move, and "it was only a comment" is exactly the change that makes `getsource` lie.
### Law 20 — a test that greps a file is testing the file, not the code.

Three times in one session, and each looked like a different mistake until they were put side by side:

  * `H02` asserted a stale sentence was **gone**. The corrected comment *quotes* it, because a reader needs to see what the file used to claim in order to understand why the door was missing. Green expectation, red test, nothing wrong with the code.
  * `H10` asserted `"innerHTML" not in panel`. The only occurrence was the comment explaining why the panel does not use `innerHTML`.
  * `B41` asserted `'"memories": relevant' in ROUTES`. It was there — **in a different function**, two handlers below the one being edited, where the accompanying variable was not in scope. The test was green while `POST /api/memory/search` raised a `NameError` on every call.

One cause: **a source file is code and prose about code interleaved, and a substring search can tell you neither which of the two it found nor what scope it landed in.** The third is the dangerous one, because grep will happily confirm that the right line exists somewhere in the wrong place.

So, in order of preference:

1. **Call the thing.** `B41`'s replacement builds the router and invokes the handler; a mutation emptying the original key survives the grep and dies here.
2. **Resolve the scope first, then assert inside it.** `ast.get_source_segment` for a Python function, a delimited split for a JS block. `check-outbound.py` already does this per function and it is why its `_POLICED_HOSTS` rule is trustworthy.
3. **Assert the shape, not the word.** `\.innerHTML\b` is a property access; `innerHTML` is a word that appears in English sentences about property accesses.

A file-wide substring is acceptable for one thing only: proving a string is *absent from the whole file* when its presence anywhere would be wrong. Everything else needs a scope.

## Before you start a task

```
□ Read the task's full entry in ROADMAP.md — including `Depends`, `CI` and `Verify`
□ Check DECISIONS.md — the call may already be settled, with reasons
□ Check DEFERRED.md — it may already be parked, or closed outright
□ Check FORBIDDEN.md Part 1 (names) and Part 2 (controls that never lift)
□ Confirm the task's premise is true in the current source        ← Law 3
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

1. **The source.** Beats everything. See Law 3.
2. **`P2-CORRECTED.md`** for anything in P2 — it was verified against the source by
   thirteen agents and it supersedes P2's task text.
3. **`DECISIONS.md`** for a settled call, and what accepting it cost.
4. **`DEFERRED.md`** for whether the thing is parked or closed. A task line asking for work
   that `D-06` parked or `D-07` closed is a task line nobody swept, and it outranks the row.
5. **The roadmap task line.**
6. **The mockup** (`design/pantheon-v10.html`) — what it should look like when done. It
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
- You are about to remove a security control. Read `FORBIDDEN.md` **Part 2** first;
  if it is on that list, the answer is no.
- Two tasks conflict and the roadmap does not say which wins.
