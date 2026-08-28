# Pantheon — Master Tracker

> Fork of **Odysseus** (`pewdiepie-archdaemon/odysseus`, AGPL-3.0-or-later).
> Elevation, not rewrite. Read `AGENTS.md` before starting anything.

> ## ⬛ LAW 4 — this file is updated **every single turn**. No exceptions.
>
> Not at the end of a phase. Not when there is something impressive to report. Every
> turn. Ticked a task, corrected a premise, found a bug, got blocked, did nothing — it
> goes in, and then `python3 .pantheon/check-tracker.py` runs. A tracker updated
> *sometimes* is worse than no tracker, because people trust it.
>
> The other eleven laws are in `AGENTS.md`. Eight of them are anti-drift laws, and each
> one cites the incident that produced it.

**This file is the only place work is tracked.** One list, one progress area. There are
no per-area handoff files — there were sixteen, all empty, and they are gone. An agent
that finishes a phase writes one entry in **§ Progress**, below. Nothing else.

The other files in `.pantheon/` are *reference*, never tracking:

| File | What it is |
|---|---|
| `AGENTS.md` | working agreement — read first |
| `FORBIDDEN.md` | names that cannot move; controls that never lift |
| `DECISIONS.md` | settled calls, with what each one costs |
| `P2-CORRECTED.md` | the scouted P2 detail — supersedes P2's task text below |
| `DEFERRED.md` | decided, not scheduled — and why |
| `ORCHESTRATION.md` | how agents are batched and run |
| `check-tracker.py` | recounts the ticks and fails if the status table has drifted |
| `check-wiring.py` | counts element lookups that resolve to nothing. Law 13's enforcement |
| `design/pantheon-v10.html` | the mockup. Reference, not source. |

---

## Status

| Mark | Meaning |
|---|---|
| `[ ]` | **ready** — premise holds, nothing blocks it, pick it up |
| `[~]` | **blocked** — the reason is on the line; unblock before starting |
| `[·]` | **claimed** — an agent is on it; the id is on the line |
| `[x]` | **done** — traced in § Progress |

Dependencies are ordering, not blocking. A task marked ready with `Depends:` is ready as
soon as its dependency lands.

| Phase | Area | Tasks | Ready | Blocked | Done |
|---|---|---|---|---|---|
| Setup | Fork, rename, rebuild | 6 | 0 | 0 | **6** |
| P0 | Fork identity & licence | 30 | 16 | **1** | **13** |
| P1 | Token layer — the free wins | 14 | 12 | **1** | **1** |
| P2 | Un-nerf | 26 | 12 | **1** | **13** |
| P3 | Mechanical hygiene | 19 | 14 | **3** | **2** |
| P4 | The wire — the real glass box | 28 | 28 | 0 | 0 |
| P5 | Trace & composer restyle | 16 | 16 | 0 | 0 |
| P6 | Queue & Plan | 18 | 5 | 0 | **13** |
| P7 | Trust ladder & control plane | 11 | 9 | **1** | **1** |
| P8 | The Workshop | 48 | 44 | **3** | **1** |
| P9 | Feature surfaces | 18 | 17 | 0 | **1** |
| P10 | Accessibility & release | 12 | 12 | 0 | 0 |
| P11 | Identity & access | 13 | 12 | **1** | 0 |
| P12 | Limits & the control plane | 11 | 11 | 0 | 0 |
| P13 | The Brain | 12 | 11 | 0 | **1** |
| P14 | Measurement | 7 | 7 | 0 | 0 |
| **Total** | | **295** | **221** | **11** | **63** | | **295** | **222** | **11** | **62** | | **294** | **221** | **11** | **62** | | **291** | **218** | **11** | **62** | | **291** | **221** | **11** | **59** | | **291** | **231** | **11** | **49** | | **288** | **239** | **11** | **38** | | **288** | **253** | **1** | **34** | | **288** | **255** | **1** | **32** | | **288** | **257** | **1** | **30** | | **287** | **256** | **1** | **30** | | **266** | **235** | **1** | **30** | | **253** | **222** | **1** | **30** | | **250** | **219** | **1** | **30** | | **231** | **200** | **1** | **30** | | **231** | **211** | **0** | **20** | | **229** | **208** | **1** | **20** | | **228** | **211** | **1** | **16** |

**Nothing is waiting on a decision** except one, and it is first: `P0-19` has to settle which of
`CREDITS.md` and `ACKNOWLEDGMENTS.md` is the credits file. All eighteen ledger calls are answered
in `DECISIONS.md` D-2026-08-26-06 and each task line carries its own.

**Every open row was re-read against the source on 2026-08-27.** 121 rows are verified accurate
and safe to pick up as written; the rest carry a correction on the line. Anything marked `[~]`
names its blocker. Nothing below is a guess.

### The P0 licence block is closed except for two named points

Ten of its rows landed on 2026-08-27 — see § Progress. What is left of it:

- **`P0-08`** — the `ODY_` prefix rename is done and proven byte-exactly reversible. It needs one
  real `docker compose up` to satisfy its own `Verify:` line, on a machine with Docker.
- **`P0-16`** — eight files carry an Apache-2.0 §4(b) notice. `services/search/` is deliberately
  unstamped and **that decision needs a human**: it is in the derived-path list because upstream
  Odysseus attributed it there, and overriding the copyright holder's own attribution is not an
  agent's call to finalise, even with the evidence pointing that way.
- **`P0-17`** — the §13 source link, which cannot be written until the repo is public.
- **`P0-13`** — blocked on a design decision. It gates the public flip alongside `P0-17`.
- **`P0-21b`, `P0-31`** — new, from the run: twelve bundled packages with no notice anywhere, and
  49 unaudited `ody-` storage-key hits.

### `P6` is 13 of 18. Finish it with the three reuse rows

**`P6-04`, `P6-06` and `P6-07` are what is left of the phase, and all three say the same thing:
reuse the thing that already exists.** The queue panel clones the research job engine (382
self-contained lines, ~16 research-specific references across 7 endpoints — budget a
generalisation pass, not a find-and-replace). The sequential/parallel picker is already built in
that same research panel. And the Tasks activity view already renders every status with shared
elapsed timers, a force button and a stop button, so pointing it at queue items beats building a
second queue UI.

They were held until now for a reason: **reuse is only judgeable once the surface it plugs into
is real**, and as of wave 2 it is. `P6-18` (steer mid-response, not only queue) is the one
genuinely new feature left in the phase and depends on `P6-01`, which landed in wave 1.

`P6-11` also stays open on `effect`. **`P7-06` owns putting the `ToolEffect` taxonomy on the SSE
wire** — it already needs the data to rank approval prompts, and it is one field on two emits.
Landing it closes `P6-11`.

**Still out of scope on its own:** `P0-29`. The Cookbook → Forge sweep is 3,529 occurrences
across 171 files and 43 paths — the largest blast radius in the programme, coupled to
`_ROUTE_FAVICON_SHAPES` **and to the `ody-` residue `P0-31` now tracks**. Its own session, as
D-2026-08-26-06 already says.

**Second choice, if the licence work is someone else's:** `P6` — queue and plan mode. 13 of 18
rows verified accurate, contained to `chat.js`, `app.js` and two scheduler files, no cross-phase
gate, and `P6-01/02/03` is one coherent user-facing bug cluster: queued messages fire into the
wrong chat, vanish on reload, and silently swallow a send with attachments.

**Do not start with:** `P1` — `P1-01` is three files plus a `CACHE_NAME` bump, not one module, and
`P1-06` is blocked on a measurement that does not exist. `P4` — `P4-01`'s six-template unification
gates eight rows behind it. `P3-03` — its classifier was never committed. `P11`–`P14` — `P14-01` unblocks five rows, and its write
location was wrong until it was corrected on the row itself; the row is right now.

---

## Progress

*The one progress area. Newest first. One entry per completed section — two lines, a
commit range, and nothing else. The detail lives in the commit messages, which is what
they are for.*

### Vision alignment — the corrections landed on the rows and never got carried up
**Five read-only auditors and a reconciler, against twelve vision points quoted from the owner
verbatim rather than paraphrased.** The verdict is worth stating plainly: this programme is
substantially aligned. `V1` (elevation, not rewrite), `V4` (training parked), `V5` (no
marketplace), `V6` (permanence, not a picture) and `V12` (AGPL, the non-commercial line as a
wish) are honoured well and in the owner's own terms, and `V7` and `V8` are enforced row by row
rather than merely cited.

**What had not happened was the second sweep.** A correction would land on the task row and never
be carried up into the preamble, the header, the decision file or the README above it — so five
vision points were contradicted by a document sitting *upstream* of the row that got them right.
The P0 preamble still stated the pre-correction deployment assumption fourteen lines below a
paragraph superseding it. `P0-29` said the Forge name was "pending" on a row whose own title
carries the decision id. `P11-02b` said 84 `require_admin` sites where its own phase preamble had
retired that number twice, thirty lines above.

**The worst finding was not a vision drift at all. It was the thing that would have caught them.**
`P3-13` — *"wire `check-wiring.py` into CI"* — was ticked done, and `git grep check-wiring`
outside `.pantheon/` returned two hits, neither of them a workflow. Three documents advertised a
gate that did not exist. The law against shipping half-wired features was itself half-wired.
**It runs now**, as the `wiring-ratchet` job, which made all three claims true rather than
requiring three documents be edited down to match a gap.

**The correction with the most at stake was `P3-10`.** It scheduled `tourAutoplay.js` for
deletion as a dead module. It is 133 lines of working code, imported from `index.html`, mapping
seven modals to per-feature walkthroughs — **the product's entire first-run onboarding.** `Law 15`
exists in this project because its owner stopped using a competitor's *more advanced* version of
what we are building, for one reason: *"There's no tutorials and the learning curve is too
steep."* Deleting the only tutorial we have would have been that mistake, made deliberately, by
the project that wrote the law. Split: `calendar/reminders.js` goes, and `P3-10b` turns the tours
back on.

**Two corrections the owner gave had never become decisions at all.** Identity and the RBAC
clean-up — thirteen `P11` rows resting on one subordinate clause inside an entry titled *"what
that voids"*, with `rbac` and `keycloak` both returning zero hits in the decision file. And the
Brain losing its graph, one of the five corrections this tracker itself names, with `Brain`,
`graph` and `confetti` all returning zero. Both are now written down. `D-2026-08-26-07` and
`D-2026-08-26-08`.

**`Law 15` was stated and then never applied.** Cited zero times across 101 open `P0`–`P6` rows;
87 of them carry no `Verify:` line at all; the 48-row Workshop phase — the three steepest surfaces
in the product — had a one-line preamble and no legibility gate, while its own second row already
diagnosed a live `Law 15` failure. Gates added to `P4`, `P5`, `P6`, `P8`, `P9` and `P13`, and
Laws 13–15 moved into the anti-drift section they belong to: they had been filed below *"When to
stop and ask"*, which is exactly why the header's count of thirteen omitted those three.

**And `Law 6` caught us again, in the sentence that ruled it out.** `P1-01` said *"521, not 508 —
`style.css` has one commit in this repo, so the old figure was wrong when written, not stale."*
The file has three commits. Our own P6 wave 2 added 342 lines to it the next day, and the count
is now **535**. The claim that a number could not go stale went stale in twenty-four hours.

Nineteen numbers refreshed with their scopes, twenty-one document contradictions closed, one
finding rejected — see below.

### One audit finding rejected, and the brief was mine
The `V2` brief said the project must not frame models as *"deities, oracles, minds, or anything
with a claim about what they ARE"*, and an auditor correctly applied it to **The Brain**, the name
of an entire phase. That extension was wrong, and it was wrong because I wrote it. The owner
rejected **Olympus** specifically — *"posturing the LLM's as 'Gods' in residence"* — and then, in
a later message, introduced "The Brain" himself while asking about a competitor's. He named it
after the decision, knowing it. The auditor flagged it as a question rather than a defect and
said the owner should decide, which was the right call. The name stays; the over-broad brief is
recorded here so nobody re-derives the objection from it.

### P6 wave 2 — the plan window exists, and four prompt strings stopped lying
**Three rows done, one honestly left open.** `static/js/planWindow.js` renders the approved
checklist docked beside the chat, updates when `plan_update` arrives, and survives a reload.
`src/agent_loop.py:759`, `:3402-3403`, `src/tool_index.py:109` and `src/tool_schemas.py:545`
have all been telling the model *"the user's docked plan window updates live"* since before this
fork existed. **That sentence is now true**, verified by driving the live module against the real
SSE ordering rather than by reading the code.

`P6-11` stays open on one point: `effect`, one of its five named per-step fields, is the 13-value
`ToolEffect` taxonomy and it is **not on the SSE wire** — neither `tool_start` nor `tool_output`
carries it. Four of five ship; the row is not finished, so it is not ticked.

**Refutation found two `breaks-users` defects, and the first is the kind that only turns up when
someone drives the code.**

- **The window was corrupted by the tool it was built for.** `update_plan` is what the model is
  *ordered* to call after every step — and it arrives wrapped in the same `tool_start` /
  `tool_output` pair as real work. So each step's real bound tool was overwritten with
  "update_plan", its result deleted, the raw plan JSON rendered as the target chip, and a phantom
  result planted on the step that had not started yet. The window would have destroyed its own
  contents on the mainline path, every step, from the first run.
- **Approving one plan approved every later plan on that browser.** A new plan reset neither the
  approval nor the per-step history, which it inherited by ordinal — so a brand-new checklist
  read "Executing" and bound the next unrelated tool call straight to its step 1.

`P6-17` came with five more, including **a second live door onto the same defect** — compare mode
builds the identical card and `todowrite` is not stripped from it, so the agent's task list still
surfaced there as raw JSON. That is the third time this programme has found a fix that was right
and reached only one of two paths (`P6-01`, `P6-10`, now this). Also fixed: N repeated calls
stacked N always-visible contradictory lists; a *successful* cleared list fell back to raw JSON;
and the dashed in-progress box never drew, having lost a specificity contest to
`li.task-item .task-check`.

**The cross-batch finding neither refuter could see.** Both batches render the same row
component, and they disagreed on its accessibility contract: the todo card gave each box
`role="img"` and a label, while the plan window — this wave's headline feature — set
`aria-hidden` on every one. A completed step was **silent to a screen reader**, its only "done"
signal a fill and a strikethrough. Each refuter reviewed its own half and the halves had drifted
apart inside a single run. The plan window now adopts the better contract.

**The sixteen themes are intact**, checked five ways: zero `--accent` definitions in `:root`
anywhere, no runtime `setProperty('--accent')`, every added token pre-existing, and zero
hardcoded hex added. One real find in passing — `.plan-step-ok` and `.plan-step-bad` both
resolved to `--red`, so success and failure chips were **the same colour in all sixteen themes**
until `P1-01` lands. Now `--green`, which is a real `:root` token.

**Suite: 5,785 passing, 19 failing, all 19 pre-existing.** The integrator caught that the
baseline had quietly become 22, and the three extra were mine: wave 1's `crew_member_id` tests
passed alone and failed in the suite, because they resolved `SessionLocal` at import time while
the executor resolves it at call time — so any earlier test rebinding it broke them. Made
hermetic against their own database, the way the rest of the suite does it.

### P6 wave 1 — the queue bug cluster closed, and two fixes that needed a second pass
**Ten rows done.** A queued message no longer fires into whichever chat happens to be open, the
queue survives a reload, queueing with an attachment works instead of swallowing the send, and
ten clicks on "solve with an agent" no longer start ten unbounded agent loops. Plan mode can ask
a clarifying question, its verifier judges against the approved checklist instead of the literal
string *"Execute the approved plan."*, and `crew_member_id` reaches the executor.

**Refutation caught two things that would have shipped as green ticks, and both are the same
shape: the fix was right and incomplete.**

- **`P6-01` still leaked on a second path.** The auto-drain was genuinely fixed; the
  click-to-promote path was not. It guarded at *click* time, then handed the item to a poller
  retrying every 220ms with no check — so switching chats during the abort round trip still
  posted one session's text into another. Guarded at *send* time instead, and a mismatched item
  goes **back into the queue** rather than being dropped. Verified with the refuter's own attack
  script: never fires into B, kept and addressed to A, still sends on returning to A.
- **`P6-10` shipped half-wired.** The tool schema advertised `crew_member_id` while the executor
  had never heard of it, so the model would accept the argument, report the task assigned, and
  the value would vanish — the model confidently telling someone their task runs as Research Bot
  when it does not. Now resolved through an owner-scoped lookup, with six tests pinning the
  round trip, the cross-owner refusal, and schema-versus-executor agreement.

**Four premises were wrong, including one this tracker itself wrote.** The run brief warned the
integrator about a `P6-15` seam at `chat.js:961`; there was no seam — `chat.js` has posted
`approved_plan` since before this phase and that line is the trigger, not the payload. `P6-14`'s
mechanism was wrong (the tool was stripped from the prompt, not rejected by the gate — plan mode
was mute, not lying). `P6-08`'s quoted comment was wrong twice over. And an implementer proposed
a wording correction to `P6-03` that refutation showed was itself false; it was not applied.

**Two comments were asserting things the tree contradicted, and both are corrected in place.**
`P6-16`'s exemption was justified with "every mutating tool is denied anyway" — but plan mode is
an *allowlist* with 25 read-only tools enabled and a directive ordering their use, so the nudge
was harmful rather than harmless. And `core/database.py`'s new status block said `error` was the
only status counting against a task's error rate while `static/js/tasks.js` text-scanned run
output for the word "error" and filed aborted runs under Errors — fixed, with the one remaining
violation named in the block and filed as `B07`.

`AGENTS.md`'s Law 13 still said the wiring count was **78**. It has been **2** since the wiring
run — the law against carrying numbers, carrying a number. Both refuters found it independently,
which is how you know it was misleading rather than merely stale.

**Suite: 5,779 passing, 19 failing, all 19 pre-existing and verified unchanged.** One of my own
edits broke three tests on the way — adding the concurrency env var to `docker-compose.yml` alone
tripped `test_gpu_compose_standalone.py`, which pins the standalone GPU files as base-plus-overlay.
That is the suite doing its job, and it is why the setting now lands in all four places it has to
exist rather than the one that was obvious.

### P0 licence run — ten rows closed, and the notices now travel
**Eleven agents: five implementers on disjoint files, five refuters told to break the work, one
integrator that re-ran every check itself.** `P0-14`, `P0-19`, `P0-20`, `P0-21`, `P0-22`,
`P0-23`, `P0-24`, `P0-25`, `P0-26` and `P0-28` are done; `P0-08` and `P0-16` are open on one
named point each. Eighteen licence bodies now sit in `licenses/`, every one fetched from
upstream at the version actually vendored and byte-compared by at least two agents
independently. `ACKNOWLEDGMENTS.md` merged into `CREDITS.md` losslessly and is gone
(`D-2026-08-27-01`).

**Refutation earned its place, and the pattern is worth naming: the implementers' *code* held
and their *claims* did not.** Twelve findings, none trivial. Three were legal:

- **The notices did not travel.** `Pantheon.spec` and `build-windows-portable.ps1` listed their
  payload by hand and shipped no licence file at all; `.dockerignore`'s blanket `*.md` excluded
  `CREDITS.md` — the file `NOTICE` names as this distribution's third-party notice — from the
  image. Adding bodies to `licenses/` had satisfied MIT/BSD/OFL for the git repo and for none of
  the three things people actually download. Pre-existing; now `P0-30`, fixed.
- **Six AGPL files were stamped `# Licence: licenses/DeepResearch-Apache-2.0.txt`** — the only
  per-file licence declarations in the whole Python tree, reading as a claim those files are
  Apache-2.0. Reworded.
- **"Modified for Pantheon" was false on seven of eight stamped files.** Measured against the
  fork point, only `routes/research/research_routes.py` differs. §4(b) still applies, but the
  party who changed them is Odysseus, and the notices now say so.

Two more were the run tripping over itself, which is what concurrent file ownership costs:
`CREDITS.md` described five licence files as missing that another agent added five minutes
later, and the `ACKNOWLEDGMENTS.md` deletion left a 404 in a README section nobody owned.

**`P0-25`'s correction was itself an undercount** — the sentence written to fix "form-filling
only" claimed to have resolved *every* call site and had walked two files. Ten handlers reach
PyMuPDF, and the two missing were `/api/chat` and `/api/chat_stream`.

**`P0-28` was replaced rather than deleted.** `.github/ISSUE_TEMPLATE/feature_request.yml:11`
linked the root `ROADMAP.md` by absolute URL — invisible to any README-scoped sweep — so a bare
delete would have 404'd it. The path now holds a pointer, which the task line always allowed and
which loses nothing that git history does not keep.

**Suite: 5,780 passing, 19 failing, all 19 pre-existing at `ec1c7c0` and unchanged by this run**
(verified by stashing). Two went green: a `P0-04` residue where the fixture proving the storage
rename still seeded `ody-prefetch-settings`, and a security line the README rewrite had reworded
out from under the test that pins it verbatim — `AUTH_ENABLED=true`, restored.

### Roadmap verification — every open task re-read against the source
**Eight agents, 282 rows, zero source files changed.** Five tasks were finished and untracked
(`P0-09`, `P2-22`, `P2-23`, `P8-01`, `P9-15b`), **two ticks did not hold** (`P0-08` — `ODY_USER`
never renamed; `P0-14` — the second upstream identity never named), **28 rows had a false premise**,
and **40 figures were wrong**, including a `508` copied into three documents that is really `521`
and a function called `applyTheme()` that does not exist. Full report in
`.pantheon/VERIFY-2026-08-27.md`; every correction is on its own task line.

The pass paid for itself twice over. `P3-10` would have deleted the RAG module four days after
`P2-23` brought it to life. `P3-03` would have deleted the exact CSS `P2-20` needs. `P3-17`'s
acceptance test **passed on an unfixed tree**, and so did `P1-05`'s. Nine rows were smaller than
written and three were larger — `P5-13`'s icon variance is two and a half times what the line
claimed. Eleven rows are now marked blocked with the blocker named, because a row that cannot
start is worth knowing about before an agent claims it, not after.

**What the checker cannot see.** `check-tracker.py` recounts marks against the table and passes
whatever the source says — it never opens a source file, so it was green throughout while five
finished tasks sat unticked and two false ticks sat green. That is `Law 8`'s blind spot, named
here so the next person does not mistake a green checker for a true tracker. `check-wiring.py`
has its own: it scans neither `static/app.js` nor `static/sw.js` and sees only literal
`getElementById`, so `admin.js`'s 39 dead `el('adm-*')` lookups have never been counted. Both
are written up on `P3-15`.

### Wiring run 01 — 78 unreachable features resolved, 2 left
**340 insertions, 1,524 deletions.** Mostly deletions, as predicted: `models.js` shed 565 lines
whose entry point exists in neither this tree nor upstream, a document overflow menu whose
initialiser had one reference in the whole tree — its own definition — and an Ollama browser with
two independent first-party removal notes. What got wired instead were features whose absence was
a live bug: archived documents could be archived but never retrieved, the RAG upload module that
`AGENTS.md` quotes as Law 13's own incident, and a skill-creation form whose absence meant every
hand-made skill shipped with `description == name`. Three renames fixed real defects, including
`submit`, which left the send button stuck in streaming state after tab recovery.

The two survivors are checker artifacts. `adv-` is a truncation of `getElementById('adv-' + key)`;
`cmp-history-0` **is** built, as `'cmp-history-' + i`, and the regex banks the prefix. Reaching
zero means editing the checker, so 2 is the floor.

### README rewritten dry, with badges and a nav row
The AI-essay rhythm was the real problem rather than the length — "this isn't X, it's Y"
reframes, punchy two-word closers, a rhetorical turn ending nearly every section. Rewritten
against `we-promise/sure` and `apexcharts` as reference: badge row, nav links, quick start first,
bullets over prose, origin told as plain fact. 1,269 words, and a regex scan for the reframe
pattern comes back clean. `P0-13` grew the screenshot requirement.

### README trimmed, and the unwired inventory made public
Prose cut to 1,411 words. Gained a section the old one was missing entirely — the 78 unreachable
features by subsystem, which is the most interesting thing about this fork and was buried in a
tracker nobody outside would read. All three nav anchors verified against real headings, and both
licence obligations re-checked after the trim.

### README rewritten for people
Same facts, told as a story rather than an audit: saw Odysseus, fell in love, read all 41,401
lines of the stylesheet, decided to finish it. The forensics moved out of the prose and the
numbers stayed — 288 tracked, 30 done, and it still says so. `P0-14`'s §5(a) statement and
`P0-27`'s statement of intent were both re-verified present afterwards, because a rewrite that
quietly drops a licence obligation un-ticks a task nobody would notice.

### Wiring run 01 in flight — all 78 under classification
Every unresolved lookup inventoried and batched by owning file: documents 19, gallery editor 17,
Forge 12, skills+RAG 8, email+gallery 8, shell singletons 14. Six agents classifying each id as
rename victim, dead code, or missing markup — with the rule that a deletion needs evidence the
code is unreachable and a build needs evidence no working UI already does it (`Law 1`, `Law 14`).
No agent may edit `index.html`; markup is emitted as fragment specs and applied serially by one
agent afterwards, so the one shared file cannot collide.

### All eighteen decisions answered; the Brain loses its graph
`DECISIONS.md` D-2026-08-26-06 settles every open call and each task line now carries its own.
Five shifted under the scaling track — `P2-10` most of all, which flips from *delete the
concurrency guard* to *make it an admin control*, because "one operator cannot denial-of-service
themselves" stops being true the moment there is a second account. And `P13` loses the
force-directed graph entirely: permanence is the feature, a picture of it is not, and the
constellation was the exact part of a competitor's version that made it go unused. Edges stay as
data — an edge that only exists to be drawn is not worth storing.

### Two more laws, and a competitor's scar tissue turned into tasks
`Law 14` — extend the primary scaffolding, never build a second one — applied to this roadmap
first: receipts went into `P4` because `P4` already exists to render what the wire discards, and
the context budget into `P12`. `Law 15` — if it needs a tutorial, it is not finished — came from
a beta user abandoning a more advanced version of `P13` because the curve was too steep, and is
now `P13-00`, the acceptance criterion for that whole phase. Training parked (`D-06`), a
marketplace closed for good (`D-07`), `D-05` promoted to `P14 · Measurement` because four things
now block on it. Four hardening tasks mined from PandaOS's public changelog — the sharpest being
a silent decrypt failure followed by a destructive save that permanently lost user API keys.

### Law 13 written, the drift measured, the Brain scoped
The complaint was right and now it has a number: **78 `getElementById` targets resolve to
nothing**, across 16 prefixes and seven subsystems — the P2 audit found a handful of them by
hand. `check-wiring.py` counts it, Law 13 forbids adding to it, and `P3-13`/`P3-14` put a
ceiling on it that may fall and may never rise. `P13 · The Brain` scoped from the source:
memories have no confidence and no edges, but the skill extractor already scores 0..1 with a
0.6 floor, and `/timeline`, `/audit` and `/import` all exist — edges are the only genuinely
new thing.

### Forge named, RBAC scoped, training filed
`Cookbook` → **`Forge`** (`DECISIONS.md` D-2026-08-26-05); Olympus was rejected on positioning,
not aesthetics. RBAC grew four tasks after reading `core/auth.py`, which corrected two things
this tracker had wrong: the privileges **are** declared and **already carry quota primitives**
(`max_messages_per_day`, `allowed_models`), so P12 extends that dict rather than building a
parallel system; and authorization is one bit applied 84 times — `require_admin` 84 sites
against `require_privilege` 17. Training filed as `D-06`: fits, but adapters only.

### Scaling track opened — P11, P12, and the Cookbook rename
The deployment assumption changed from one admin on a LAN to real infrastructure. Two phases
added: identity and access (10 tasks — OIDC/SSO against a BYO provider, roles, and closing the
privilege fail-open at `auth_helpers.py:172`), and limits and the control plane (8 — every limit
is a process-wide env constant today, none per-role, none adjustable without a restart). Five
earlier decisions had "a second user account" as their voiding condition; `DECISIONS.md`
D-2026-08-26-04 records which move and which do not. Cookbook filed for rename as `P0-29` —
3,533 occurrences, larger than the Odysseus sweep was.

### Decision ledger — 18 open calls collected, awaiting answers
Everything blocked on a product call rather than a code question, gathered into one sheet with
measured findings, options and a recommendation each: nine finish P2, two re-land what run 01
pulled back, five gate the public flip, two are UI couplings. Nothing implemented pending answers.
→ https://claude.ai/code/artifact/021da439-f620-4d16-948d-36e30c314f53

### P2 run 01 — 10 implemented, 1 reverted, 1 blocked
Upload blocklist deleted, upload CSP sandboxed in the middleware, four dead config blocks and a
dead validator removed, `_is_text_file` widened 10 → 28, email decode fallback, a real `MAX_FILES`
cap, the heredoc contradiction, the grammar bug, and a 413 on the admin import. Suite: 5,742 pass
against 5,731 at baseline, same 44 pre-existing failures, zero regressions. Four bugs filed.
Rebuilt and live — app serving, `PANTHEON_BACKUP_IMPORT_MAX_BYTES` confirmed inside the
container. `1f5ec17 … 67decb5`

### R-06 closed + first implementation run launched
Pantheon's real tree is now in the cloud container at `/work/pantheon`, staged from cybertooth
as a 15 MB archive, checksum-verified, and baselined under git at `f4364bf` — 1,516 files,
confirmed identical to the fork on the accent counts (799 / 205 / 101). Agents edit the fork
itself now instead of reading upstream; `/work/base` stays as the b4d1293 reference. Seven
P2 file-ownership batches running, each with a refuter. `62bf5d2 … HEAD`

### Theme protection — P1-01 corrected before it shipped
The themes and their 7 canvas background animators are protected (`DECISIONS.md`
D-2026-08-26-03). Auditing that found P1-01 would have collapsed all 16 themes to one
accent colour; rewritten to set `--accent` per theme instead. `3bd293d … HEAD`

### Datastore audit — no change made, two decisions recorded
Measured the ChromaDB coupling (130 call sites, 2,110 LOC, 24 tests) and decided against a
swap: `DEFERRED.md` D-04. Filed D-05 — telemetry is the real TimescaleDB case — and B01,
the unpinned datastore image. Nothing in the source changed.

### Tracker consolidation + README — implemented
Sixteen empty handoff files and a stale duplicate note deleted; one tracker, one progress
area, and a `check-tracker.py` that fails on table drift. Twelve laws in `AGENTS.md`, eight
of them anti-drift, each citing its incident. README rewritten around the audit. `930bfb9 … HEAD`

### Setup · R-01 … R-06 — implemented
Repo created private at `ImPanick/pantheon`, upstream kept as a remote, full 2,077-commit
history. Rename swept, stack rebuilt, app serving as Pantheon. `ac65b63 … 930bfb9`

---

## Where things run

Three machines, and the tools do not reach the same one. This bit the first plan.

| Where | Reached by | Has | Lacks |
|---|---|---|---|
| Cloud build container | `Bash` | git, docker, network, `/work/base` | the fork's credentials |
| Cowork device VM | `device_bash` | the repo mounted r/w, git, python, node | network, docker, gh, **cannot delete files** |
| cybertooth (Windows) | `Windows-MCP` → Git Bash | **git, gh (auth), docker, network** | — |

**Edit files with `device_bash`. Do everything git, gh or docker through `Windows-MCP`.**
`device_bash` cannot unlink, so `sed -i`, `git commit` and `git gc` all fail there.

The fork is private, so agents cannot clone it. They read `/work/base` — upstream at
exactly `b4d1293`, the fork point — and hand back patches that cybertooth applies.

**Verifying a sync: compare `git rev-parse HEAD^{tree}` on both machines.** Two commits
with different messages, authors or timestamps still produce the same tree hash if the
files match, which makes it the right check for "did everything arrive". A checksum on
the tarball proves the transfer; the tree hash proves the *result*.

*Confirmed useful on 2026-08-27.* It disagreed after a sync that had in fact worked:
1,532 files, **zero differing blobs**, and 1,484 files whose only difference was the
executable bit — the container mirror had been seeded from a tarball that set `+x` on
everything, so its index recorded `100755` where cybertooth has `100644`. Nothing wrong
was ever pushed, because cybertooth is the push source. `core.fileMode false` is now set
in the container so the seed cannot reintroduce it. **Do not skip this check because it
disagreed once for a boring reason** — the same disagreement with a differing *blob* is
the one that matters, and you cannot tell them apart without looking.

### Two upstream identities — settle before P0-14
Cloned from **`pewdiepie-archdaemon/odysseus`**; the code and docs referenced
**`odysseus-dev/odysseus`** (47 occurrences across 16 files). The sweep rewrote the second
to `ImPanick` and left the first alone. `NOTICE` and `CREDITS.md` name only the first.
Confirm which is canonical before the attribution files are final.

---

## How an agent picks up work

Read `AGENTS.md` first — it is the working agreement and it is short. This section is the
mechanical part.

**Task line format.** Every task is one line, parseable:

```
- [ ] **Px-yy** <what to do>. `Depends:` Px-aa. `CI:` <test that pins this>. `Verify:` <how you know it worked>.
```

`Depends:` is ordering. `CI:` names a test that asserts on this code — often on its
*source text* rather than its behaviour, so read the test before refactoring. `Verify:` is
the acceptance check, and it is the definition of done.

Ids in examples are always `Px-yy`, never a real one, so that counting the list never
picks up an illustration. `python3 .pantheon/check-tracker.py` recounts every tick,
checks each task sits under its own phase header, and fails if the status table has
drifted. Run it after any batch of ticks — a table that disagrees with the list sends
agents to redo finished work.

**Before starting a task**

1. Re-read the task against the source. If the premise is false, **stop and correct the
   line** — do not implement a task whose premise does not hold. This is `AGENTS.md`
   rule 3, and the P2 scout pass found it false often enough to matter.
2. Check `FORBIDDEN.md` Part 1 (names that cannot move) and Part 2 (controls that never
   lift). Check `DECISIONS.md` for a settled call on this task.
3. Claim it by flipping `[ ]` → `[·]` with your agent id. Release it if you stop.

**While working**

- Add, never subtract. If something has to go, say why on the task line.
- `static/` has **no bind mount**. A restart serves the old files —
  `docker compose up -d --build`, and bump the service-worker `CACHE_NAME`.
- Inline scripts need the CSP nonce. Add zero external requests.
- **No route in this app can set a CSP header** — the security middleware overwrites it.
  If a task tells you to set one at a handler, it is wrong.

**Definition of done**

A task is done when all four hold:

- [ ] the `Verify:` check passes
- [ ] `pytest -q` is green, or the failures are pre-existing and named
- [ ] `py_compile` across `app.py routes/ src/`, `node --check` on every touched module
- [ ] the tick is flipped to `[x]` with a one-clause trace on the line

**When a whole phase is done**

Write **one** entry in § Progress. Two lines and a commit range. Not a report — the
commit messages carry the detail, which is what they are for. Then set the phase's row in
the status table.

**Where things go**

| What | Where |
|---|---|
| A finished phase | one § Progress entry |
| A bug you found in passing | § Bugs, at the bottom |
| A premise that turned out false | corrected on the task line itself |
| A judgement call someone might re-litigate | `DECISIONS.md` |
| Anything else | the commit message |

---

Phases are ordered by dependency, not importance. **P0 → P1 → P3 are strictly
sequential.** P2 is independent and can run in parallel with anything from the start.
P4 gates P5. P8 depends only on P1.

**P11 and P12 are the scaling track** and depend on nothing in P0–P10. They exist because the
deployment assumption changed: this was planned for one admin on a home LAN, and it is now
being planned to survive real infrastructure with real users. Several settled decisions named
"a second user account" as their voiding condition — those conditions are now foreseeable
rather than hypothetical, and `P11-09` is where that debt comes due.

---

# P0 · Fork identity & licence
*Area: `identity`, `release` · Blocks: everything*

The rename is ~2,900 occurrences across 371 files, of which ~150 identifiers are
load-bearing.

**Deployment reality, corrected 2026-08-28.** This phase was written for one self-created
admin account on a home LAN with disposable data, and that is still where it runs today — so
everything already swept under that assumption stays swept. But the assumption itself was
superseded: the owner asked to plan around someone scaling into real infrastructure, and
`P11`/`P12` exist because of it. **Every rename still open — `P0-29`, `P0-31` — decides per key
whether a read-old-write-new path is needed, and records that decision on its own row.**
`P0-31`'s `Verify:` line already accepts "a migration path reading the old key"; this paragraph
used to forbid one.

**Nothing is purged.** `P0-05` below measured the live instance: two collections, both already
under the new names, and `pantheon_memories_fastembed` holds real memories. Re-index what is
genuinely empty and log back in. The only manual step is one line in your `.env`.

`scripts/pantheon-init.sh` does the mechanical sweep. Review its diff before committing.

- [x] **P0-01** Create `.pantheon/` with `AGENTS.md`, `ROADMAP.md`, `FORBIDDEN.md`, `DEFERRED.md`, `handoff/`. Seed one empty handoff file per area. — **done:** the directory exists; the sixteen empty handoff files were deleted in favour of § Progress.
- [x] **P0-01b** Run `scripts/pantheon-init.sh --dry-run`, read the diff, then run it for real. It does P0-02, P0-03, P0-04, P0-06, P0-07, P0-08, P0-10 and P0-11 as one reviewable sweep, with the attribution files excluded. Everything after it is by hand. — **done:** swept, 373 files, 2,615 in / 2,615 out, 37 path renames.
- [x] **P0-02** Rename cosmetic surfaces: page titles, wordmark text in `index.html` + `login.html`, 111 UI strings across `static/js/`, tray menu in `launcher.py`, `setup.py` banner. `Verify:` grep for case-insensitive `odysseus` in `static/` returns only attribution strings. — **done:** verified — `git grep -icI odysseus -- static/` returns one hit, the protected provenance link in `cookbook.js`.
- [x] **P0-03** Rename env prefix `ODYSSEUS_*` → `PANTHEON_*` (**103 distinct names, 574 refs** — re-measured 2026-08-27 post-sweep, scope: `PANTHEON_*` in tracked files excluding `.pantheon/`; the pre-sweep estimate of 99 / 560 undercounted). Update `.env.example`, `docker-compose*.yml`, `Dockerfile`, `docs/`, **and your live `.env` on the host** — that one file is the entire migration. No shim. `Verify:` app boots with only `PANTHEON_*` set. — **done:** code and live `.env`; only `PANTHEON_ADMIN_USER`/`PASSWORD` existed on the host, and both are read solely at first-boot admin creation.
- [x] **P0-04** Rename browser storage keys (113 distinct, 206 refs in `static/`). Costs you one theme re-pick and a layout reset. `CI:` none. — **done:** verified — no `ody-`/`ody.` keys remain in `static/`.
- [ ] **P0-05** **Corrected — there is nothing to drop.** The previous entry claimed the volume still held `odysseus_*` collections. Queried the live instance: one tenant, one database, and only two collections exist — `pantheon_rag_fastembed` (0 docs) and `pantheon_memories_fastembed` (**8 docs**). The app created them under the new names on first boot and memory is already writing to them. No orphans anywhere, so nothing was stranded and nothing needs migrating. What is left is smaller: **RAG is empty and `pantheon_tool_index` does not exist yet** — add the directories back through the RAG UI, and the tool index builds itself on first tool search. `Verify:` RAG search returns results after re-adding a directory; `GET :8100/api/v2/tenants/default_tenant/databases/default_database/collections` lists a tool index. *(Caught by Law 9 — the entry described what I assumed, not what was there.)* **Verification note 2026-08-27:** the code half is confirmed; **the two live-instance claims are not.** ChromaDB at `localhost:8100` is unreachable from the build container, and this row's own `Verify:` needs that endpoint — so "RAG is empty" and "`pantheon_tool_index` does not exist yet" are **carried, not measured** (`Law 6`). Whoever picks this up runs the collections query on the box that can see it, first.
- [x] **P0-06** Rename session cookie `odysseus_session` → `pantheon_session`. You log in again once. — **done:** swept.
- [x] **P0-07** Rename outbound HTTP headers (`X-Odysseus-Origin/Kind/Ref/Event/Signature/Owner`) and the four User-Agent strings. No downstream consumers exist yet — do it now, before any do. — **done:** swept.
- [ ] **P0-08** Rename Docker compose service, container user (`ODY_USER`), and the SearXNG settings sentinel `odysseus-local-searxng-json-2026-05-30`. `Verify:` a clean `docker compose up` produces a working SearXNG. — **UNTICKED (verified 2026-08-27):** the compose service and the sentinel were swept, but **`ODY_USER` itself never was** — only its *value* changed. It is still `ODY_USER` at `docker/entrypoint.sh:29,30,45,141,146`, where `:30` now reads the giveaway `[ -z "$ODY_USER" ] && ODY_USER=pantheon`, plus two assertions at `tests/test_docker_devops_hardening.py:100-101`. **The sweep only ever matched `odysseus`/`Odysseus`/`ODYSSEUS`; the abbreviated `ODY_`/`_ody_` prefix was never in scope.** Same class, same cause, and none of it is renamed: `_ody_qwen_temperature_cap` (`src/agent_loop.py:2212` + 3 call sites), `_ODY_VENV_FOR_LIBS` / `_ody_nvlib` / `_ODY_LLAMA_SHIM_EOF` (`routes/cookbook_routes.py:138-141,2251`), and the three `ody_*_finetune_*` wire keys at `src/agent_loop.py:4346-4348`. `ody_` appears in 71 lines of `src/agent_loop.py` alone and in ten other `src/` files. **Scope this as its own prefix sweep** — the wire keys are protocol surface and changing them is not cosmetic.
  **The rename landed on 2026-08-27 and this row stays open only on its `Verify:` line.** Seven files, 29 identifiers, proven **byte-exactly reversible**: a reverse map applied to every touched file reproduces `git show ec1c7c0:<path>` exactly, which closes losslessness, behaviour-neutrality and collision-safety in one measurement. `ODY_USER` → `PANTHEON_USER` across `docker/entrypoint.sh` and both pinning assertions in `tests/test_docker_devops_hardening.py`. **The three `ody_*_finetune_*` wire keys at `src/agent_loop.py:4346-4348` were traced end to end and deliberately left alone** — they cross a protocol boundary, and renaming a live wire key to tidy a prefix is the damage these laws exist to prevent. **Do not tick until someone runs one real `docker compose up`.** Note before you do: `docker-compose.yml:113` only regenerates SearXNG settings when the file is empty or holds the `pantheon-local-` sentinel, so a volume still carrying the pre-rename `odysseus-` sentinel is treated as user-customised and never refreshed. "Clean" in that `Verify:` line is load-bearing.
- [x] **P0-09** Rename data dir default (`~/.odysseus/data`), systemd unit + installer, PyInstaller spec, macOS `CFBundleIdentifier`, PWA manifest name, service-worker cache name. **Docker mounts `./data` explicitly, so the default path change does not move your live data** — verify that before restarting. — **done:** all six landed in the rename sweep and nobody ticked the line. `src/runtime_paths.py:29` `~/.pantheon/data`, `pantheon-ui.service`, `Pantheon.spec`, `build-macos-app.sh:56` `com.pantheon.launcher`, `static/manifest.json:2-3`, `static/sw.js:10`. `.odysseus` now occurs nowhere outside `.pantheon/`. (verified 2026-08-27)
- [x] **P0-10** Rename the **20** `scripts/odysseus-*` CLI scripts (`git mv`). If you have a crontab or systemd timer pointing at any of them, update it — otherwise nothing references them. — **done:** all of them `git mv`-d. *(Count corrected 2026-08-27: **20**, not 19 — scope: `pantheon-*` in `scripts/` minus the init and repo-setup scripts. The work was complete; only the number was wrong.)*
- [x] **P0-11** Rename Swift package + two executables, the two integration plugin ids (`integrations/{claude,codex}/skills/odysseus/`), `_EMAIL_MCP_OWNER_ARG`, and the 3 custom DOM events. `Depends:` P0-02. — **done:** swept.
- [x] **P0-12** **The sweep rewrote two badges to dead targets — they need removing, not renaming.** `README.md:17` now points at `repology.org/project/pantheon-ai`, which does not exist; `README.md:71-75` now points the star-history chart at `ImPanick/pantheon`, which is private and will 404 for every reader. Delete both blocks. The rest of this task is done: the 47 `odysseus-dev` references, `package.json`, `.github/` templates and `cookbook.js:3177` were handled by the sweep, and the three links to specific upstream issues and discussions were deliberately preserved. `Verify:` no README image URL 404s. — **done:** both dead badges removed in the README rewrite; the sweep had already handled the 47 `odysseus-dev` references, `package.json`, `.github/` and `cookbook.js:3177`.
- [~] **P0-13** Design the Pantheon mark — **and take a real screenshot with it.** Every README worth copying opens with one; ours would have to be `docs/pantheon-browser.jpg`, which is upstream's shot of the old UI under a renamed file, so shipping it would misrepresent the product. The README currently has none for that reason. **Do not reuse the red sailing boat, the wordmark, or the per-route favicon shapes** — the licence grants them but they are upstream's identity. Replace `static/icon.ico`, the favicon registry, the inline boat SVG — **9 copies, not 5** (re-measured 2026-08-27: the wave path `M4 24Q10 20 16 24` across 4 files; 6 if you exclude `docs/index.html`) — and the programmatic tray drawing. **Keep the ASCII wave loader** — it's a loader, not a logo. — **DECIDED — its own session: three or four directions, pick one, then favicon, tray icon and the nine inline SVG copies follow** (D-2026-08-26-06). `Blocked:` needs a design decision no agent can make. It gates the public flip alongside the licence rows.
- [x] **P0-14** **§5(a) + §5(b) notices.** Add to `README.md` and a new `NOTICE`: a prominent statement that this is a modified version of Odysseus, **with a date**, and that it is released under the AGPL. Neither exists today. — **PARTLY DONE, UNTICKED (verified 2026-08-27):** the notice itself is right — `NOTICE` carries the §5(a) statement with the fork commit and date, and `README.md:207` repeats it in prose. **What is missing is the second upstream identity.** `odysseus-dev/odysseus` returns **zero** hits across `NOTICE`, `README.md`, `CREDITS.md` and `ACKNOWLEDGMENTS.md`; `NOTICE:23` names only `pewdiepie-archdaemon/odysseus`. D-2026-08-26-06 requires both be named, and § *Two upstream identities* below is the reason. An attribution that names one of two upstreams is the one defect in this block you cannot ship publicly. Add the second identity to `NOTICE` and to whichever credits file `P0-19` makes authoritative, then re-tick. — **done:** `NOTICE:22-44` and `CREDITS.md:37-59` now name **both** upstream identities — `pewdiepie-archdaemon/odysseus` as the clone source and `odysseus-dev/odysseus` as the identity its own code and docs referenced — with the distinction evidenced from the fork point's git remote, and `README.md` says so in one sentence under *Where this came from*. The §5(a) modification notice keeps commit `b4d1293` and date 2026-08-24 unchanged.
- [x] **P0-15** **§4 copyright line.** There is **no project copyright notice anywhere in the repo today**. Add Pantheon's and preserve any upstream one that can be established. — **done:** `NOTICE` line 2 — `Copyright (c) 2026 Panick`. There was no upstream copyright line in the repo to preserve.
- [ ] **P0-16** **Apache-2.0 §4(b) change notices** on the research-derived files (`services/research/`, `src/research_handler.py`, `routes/research/`, `services/search/`) — "You changed the files". **Notices are now on eight files** (2026-08-27) and this row stays open on one point.
  **What landed:** the six research/route modules plus `src/deep_research.py` and `src/goal_based_extractor.py`, comment-only and AST-identical to before, proven per file. Refutation caught two defects in the first attempt and both are fixed: the notice's `# Licence: licenses/DeepResearch-Apache-2.0.txt` line was **the only per-file licence declaration in the entire Python tree** and read as declaring those AGPL files Apache-2.0; and "modified for Pantheon" was false on seven of the eight — measured against the fork point, **only `routes/research/research_routes.py` differs**. The notices now name Odysseus as the party that changed them and state the file's own licence as AGPL-3.0-or-later.
  **Why it is still open:** `services/search/` is in the derived-path list because that is **upstream Odysseus's own attribution** — the copyright holder's words, carried forward. It is deliberately unstamped: nine files, 2,222 lines, zero matches for `Tongyi`/`DeepResearch`/`IterResearch`/`Alibaba`, and every one byte-identical to the fork point. Stamping "you changed this" on a file nobody changed is a false statement in the other direction. **That reasoning is recorded in `CREDITS.md` and needs a human ruling before this ticks** — overriding the upstream copyright holder's own attribution is not an agent's call to finalise.
- [ ] **P0-17** **§13 Source link.** Single footer button in the UI. `href` → the public repo. `title="Built on Odysseus — click to see where Pantheon originated from!"`. Must be present on the logged-in shell and the login page. This is the one licence obligation that is genuinely required and genuinely missing. `Depends:` P0-12.
- [ ] **P0-18** Decide `AGPL-3.0-only` vs `AGPL-3.0-or-later` and state it in `LICENSE`, `README`, and SPDX headers. Today the qualifier lives in exactly one README line with zero SPDX headers. — **DECIDED — `AGPL-3.0-or-later`, matching upstream, with real SPDX headers** (D-2026-08-26-06).

### P0 · Credits — the licence gaps you inherit
*Do not publish before these close.*

- [x] **P0-19** **Decide which file is the credits file, then rewrite it.** *(2026-08-27 — this is the decision that gates the whole licence block.)* `CREDITS.md` and `ACKNOWLEDGMENTS.md` both exist and **disagree about which is authoritative**, and `NOTICE:41-42` points at the wrong one. One call unblocks `P0-20`, `P0-24`, `P0-25` and `P0-26`, and `P0-14` cannot be re-ticked until it lands, because the second upstream identity has to go somewhere authoritative. **Do this first in the P0 run.** Then: rewrite it as Pantheon's credits file, **lead with Odysseus**, preserve every credited party, update paths that moved, and make `NOTICE` point at the surviving file. — **done:** `ACKNOWLEDGMENTS.md` merged into `CREDITS.md` losslessly and deleted (D-2026-08-27-01): `CREDITS.md` 105 → 483 lines, every credited party carried across and checked individually, all relative links and in-page anchors resolving, `NOTICE` keeping the pointer it already had. Four merge consequences fixed in the same pass — the 404 the deletion left at `README.md:212`, a dangling `ACKNOWLEDGMENTS.md` pointer in `requirements-optional.txt`, and two paragraphs describing licence files as missing that a concurrent agent had added five minutes earlier.
- [x] **P0-20** Add missing licence bodies to `licenses/`: highlight.js (BSD-3), SheetJS/xlsx (Apache-2.0 — check upstream for a `NOTICE`), docx (MIT), mammoth.js (BSD-2), jsPDF (MIT), html2canvas (MIT), node-qrcode (MIT). MIT and both BSDs require the notice to travel with redistributed copies. — **done:** seven licence bodies added to `licenses/`, **each fetched from upstream at the version actually vendored here** and byte-compared by two independent agents: highlight.js 11.9.0 (BSD-3), SheetJS 0.20.3 (Apache-2.0 — confirmed to ship no `NOTICE`, so §4(d) has nothing to carry), docx 8.5.0 (MIT), mammoth.js 1.8.0 (BSD-2), jsPDF 2.3.1 (MIT), html2canvas 1.0.0 (MIT), node-qrcode (MIT). Real copyright holders present in all seven.
- [x] **P0-21** Fetch the missing `html2pdf.bundle.min.js.LICENSE.txt` — the bundle's own banner references a file that is not in the repo. — **done:** `licenses/html2pdf.bundle.min.js.LICENSE.txt` is the genuine upstream artefact — fetched from html2pdf.js 0.10.2 and `cmp`-verified at 143,251 bytes, not reconstructed. **The banner no longer points at a file that is missing.** What the sidecar does *not* cover became `P0-21b`.
- [x] **P0-22** Add OFL text for Fira Code and Inter, and list the **20 KaTeX font faces** — all carry Reserved Font Names and are currently credited as MIT-only. Do not subset any font, or OFL §3 bites. — **done:** OFL text added for Fira Code and Inter, both byte-identical to upstream (`tonsky/FiraCode@6.2`, `rsms/inter@v4.1`); all 20 KaTeX faces listed in `licenses/KaTeX-fonts-OFL.txt` with the Reserved Font Name blocks read out of the shipped `.woff2` metadata, replacing an MIT-only credit that was wrong. **No font was subsetted, renamed or regenerated** — OFL §3 and the RFN clause both bite there. A false provenance line in that file (it quoted FiraCode's hash for OpenDyslexic's) was caught by refutation and corrected before commit.
- [x] **P0-23** **Resolve `static/fonts/custom/GohuFont.ttf`.** The shipped file is 1,468 bytes / 3 glyphs, metadata reads `Untitled1 / Copyright (c) 2025, Unknown`. It is not GohuFont. Replace with the real WTFPL font + licence, or remove it and drop the credits row. — **DECIDED — delete the file and its credits row** (D-2026-08-26-06). — **done:** `static/fonts/custom/GohuFont.ttf` deleted **and its credits row with it**, as D-2026-08-26-06 required. Verified before deleting rather than taken on trust: 1,468 bytes, 13 sfnt tables, 3 glyphs, `name` table reading `Untitled1` / `Copyright (c) 2025, Unknown` / `FontForge 2.0`. It was the one affirmatively false statement in this repo's attribution. A short note in `CREDITS.md` records what was removed and why, so the deletion is on the record rather than silent (`Law 1`).
- [x] **P0-24** Add undisclosed deps to credits: `nh3`, `python-dateutil`, `httpcore`, `httpx2`, `python-magic`, Real-ESRGAN wheels, the two MLX Swift packages. Update `duckduckgo-search` → `ddgs`. — **done:** `nh3`, `python-dateutil`, `httpcore`, `httpx2`, `python-magic`, the three Real-ESRGAN wheels and the two MLX Swift packages credited with licences fetched from PyPI and upstream, none invented; `duckduckgo-search` → `ddgs`. `httpx2` was checked rather than assumed and **is real** — 2.12.0, BSD-3-Clause, declared at `requirements.txt:53`.
- [x] **P0-25** Correct the PyMuPDF scope statement — it is documented as form-filling only; it also backs the PDF viewer's page render and the annotation-fill endpoint (three route handlers). Fix the stale docstring at `routes/email_helpers.py:1453` that credits it for text extraction it does not perform. — **done:** `routes/email_helpers.py:1453` no longer credits PyMuPDF for text extraction it does not perform, and the credits file carries a real scope table in place of "form-filling only". **Ten route handlers reach PyMuPDF, not eight** — the correction was itself an undercount, and the two it missed are `/api/chat` and `/api/chat_stream`, which reach it indirectly through `build_user_content` → `src/document_processor.py:504`. The busiest endpoints in the app were absent from a scope statement claiming to cover every call site.
- [x] **P0-26** Reconcile the credits file's "the core ships fully permissive (MIT-compatible)" framing against the AGPL `LICENSE`, or state which is authoritative for Pantheon. — **done:** `CREDITS.md` states plainly that **Pantheon as a whole is AGPL-3.0-or-later**, with the permissive licences scoped to the individual vendored components; the inherited "fully permissive / MIT-compatible core" headline is gone and no non-commercial language was added (AGPL §10, D-2026-08-26-06). The same framing survived in three more files and was corrected there too — `requirements-optional.txt:33` and `:41`, which ship inside the Docker image, and `src/pdf_forms.py:13`.
- [x] **P0-27** README statement of intent: *"Pantheon is free software under the AGPL. I don't sell it, and I'd rather you didn't."* **Social, not legal — do not add a non-commercial clause.** AGPL §10 prohibits further restrictions and §7 lets any recipient strip one. — **done:** in the README licence section, phrased as intent and explicitly not as a clause.
- [x] **P0-28** **The root `ROADMAP.md` is upstream's, and the sweep put Pantheon's name on it.** It now opens *"Pantheon is on a voyage, but not home yet... (I don't know what I'm doing, help)"* — upstream's words, upstream's self-deprecation, attributed to this project. It also collides with the real tracker at `.pantheon/ROADMAP.md` — **but only by filename** (**Premise corrected 2026-08-27.**): all three README references already point at `.pantheon/ROADMAP.md`, so no reader is currently sent to the wrong file. That lowers the urgency and leaves the actual problem, which is upstream's self-deprecation flying Pantheon's name. Replace it with a short pointer to `.pantheon/ROADMAP.md`, or delete it. `Verify:` a reader following either link lands somewhere that is true. — **DECIDED — delete it; point everything at `.pantheon/ROADMAP.md`** (D-2026-08-26-06). — **done:** **replaced, not deleted** — the task line offered both and the pointer is strictly better. The root `ROADMAP.md` is now four lines sending readers to `.pantheon/ROADMAP.md`, plus a short note saying what used to be there and where Odysseus's real roadmap lives. Keeping the path alive matters: `.github/ISSUE_TEMPLATE/feature_request.yml:11` linked it by **absolute URL**, which no README-scoped sweep can see, and a bare delete would have 404'd it. That reference now points at the real tracker. Upstream's self-deprecation no longer flies Pantheon's name.
- [ ] **P0-21b** **Twelve bundled packages have no licence notice anywhere in this repository.** `html2pdf.bundle.min.js` bundles fifteen top-level packages; its sidecar `LICENSE.txt` carries a copyright notice for **three** of them — `es6-promise`, `html2canvas`, `jspdf` — plus html2pdf.js itself. Measured 2026-08-27 across all comment-block forms (955 blocks, 23 copyright-bearing), which is why an earlier `/*!`-only count said five. The twelve: `@babel/runtime-corejs3`, `canvg`, `core-js`, `core-js-pure`, `dompurify`, `fflate`, `performance-now`, `raf`, `regenerator-runtime`, `rgbcolor`, `stackblur-canvas`, `svg-pathdata`. **`dompurify` is not just a missing file** — DOMPurify 2.3.0 is dual-licensed Apache-2.0 **or** MPL-2.0, so someone has to choose and record the choice. `Verify:` every package the bundle ships has a notice in `licenses/`, and the count is re-derived rather than carried.
- [x] **P0-30** **The notices did not travel.** Adding licence bodies to `licenses/` satisfies MIT/BSD/OFL for the git repository and for nothing else, and all three of those licences require the notice to accompany **redistributed copies**. Found 2026-08-27: `Pantheon.spec:8` and `build-windows-portable.ps1` both listed their payload by hand and shipped no licence file at all, so the desktop builds redistributed a dozen libraries with their attribution stripped; and `.dockerignore`'s blanket `*.md` excluded **`CREDITS.md`** — the exact file `NOTICE` designates as this distribution's third-party notice — from the image. — **done:** `licenses/`, `LICENSE`, `NOTICE` and `CREDITS.md` added to the PyInstaller spec and the Windows `--add-data` list with a comment saying why, and negated in `.dockerignore`. **This was pre-existing, not caused by the licence run — the run is just what made it visible.** `Verify:` build each of the three artefacts and confirm `licenses/` is inside it.
- [ ] **P0-31** **`ody-` browser storage keys survive in the test fixtures that prove the rename worked.** `P0-04` renamed 113 storage keys in `static/` and its trace reads "verified — no `ody-`/`ody.` KEYS remain in static/", which is true and was not the whole question. `git grep -nIP '(?<![A-Za-z0-9])(?i:ody)[-.]'` returns **50 lines across 12 files**, 24 of them under `static/`. One was a genuinely red test — `tests/test_app_config_shared_fetch_js.py` seeded `ody-prefetch-settings` while `static/js/appConfig.js:31` reads `pan-prefetch-settings`, so the fixture that exists to prove the rename was pinning the old name and failing. Fixed 2026-08-27; the other 49 lines are unaudited. `Verify:` every remaining hit is either deliberate (a migration path reading the old key) or renamed, and each one is named.
- [ ] **P0-29** **Rename Cookbook → Forge** (`DECISIONS.md` D-2026-08-26-05). It reads as a recipe box; it is a model-serving control plane — remote host registry with SSH keys, GPU detection and hardware fit, weight downloads from HuggingFace and Ollama, vLLM / llama.cpp / Ollama launches held open in tmux, process kill, and task-status polling. 17 routes. **Surface: 3,529 occurrences across 171 files and 43 paths — larger than the Odysseus→Pantheon sweep was** (2,929). *(Re-measured 2026-08-27; scope: case-insensitive `cookbook` in tracked files, excluding `.pantheon/`. The old 3,533 / 172 counted this tracker's own text.)* Use the same tool: `scripts/pantheon-init.sh` is proven and parameterises cleanly. **The name is settled: `Forge`** (D-2026-08-26-05), and the reason is positional rather than aesthetic — Olympus was rejected because it would have cast the models as gods in residence, and AI is under enough of that already. Forge names what the *operator* does. *(This clause read "Decide the name first (`DECISIONS.md`, pending)" until 2026-08-28, on a row whose own title already carries the decision id.)* The one open sub-question is whether *recipe* survives — 242 occurrences, and a vLLM recipe genuinely is a parameterised launch config, so it may earn its keep even if Cookbook does not. `Verify:` no user-visible string says Cookbook; `rail-*`, `tool-*-btn` and modal ids move together with their CSS.

---

# P1 · Token layer — the free wins
*Area: `tokens` · Depends: P0-01 · Blocks: P5, P8*

More visible change than any redesign step, and zero markup touched.

- [ ] **P1-01** **Define `--accent` PER THEME, not in `:root`. Defining it in `:root` breaks all 16 themes.** Measured **2026-08-28**: of the **813** `var(--accent…)` sites in `style.css`, **535 are `var(--accent, var(--red))`** and resolve today to the theme's own `red`, which `applyColors()` sets at `static/js/theme.js:263`. A `:root` definition wins over that fallback, so all 521 would flip to one global colour and every theme would lose its identity in a single commit. **The themes are protected — see `DECISIONS.md` D-2026-08-26-03.**
  **Do instead:** `s.setProperty('--accent', colors.accent || colors.red)` beside the existing `s.setProperty('--red', colors.red)`, guarded the same way. The 535 fallback sites then resolve to exactly what they resolve to now (zero visual change), the bare sites resolve for the first time (pure gain), each theme keeps its own accent, and the 8 custom-theme slots get it free — `generateHarmonyColors()` at `theme.js:220` returns no `accent` key, so `colors.accent || colors.red` falls through to red exactly as intended. Add an optional `accent:` key to `THEMES` for any theme that should differ from its `red`.
  **Three corrections, verified 2026-08-27, and all three change the work.** **(1) The count moves — re-derive it before you start.** It was 508 in three documents, then 521 when four independent methods agreed on 2026-08-27, and it is **535** today. `static/style.css` has **three** commits, not the one the previous version of this sentence claimed: `078e0b4` added 342 lines to it on 2026-08-28, some of them new fallback sites. *The sentence that ruled out staleness went stale in a day, which is the most honest argument for `Law 6` this programme has produced.* **(2) There is no `applyTheme()`.** The function is `applyColors()` at `theme.js:257`; the only `applyTheme` in the tree is a dead call at `slashCommands.js:876` behind an `||` the module can never satisfy. An implementer searching for the named function finds nothing. **(3) One line is not enough — `--red` is set at three sites.** `theme.js:263` (the module), `index.html:29` (the first-paint inline script) and `login.html:54` (the login page's own script, which never runs `applyColors` — its comment at `:605-607` says so). Adding the line only in `applyColors()` leaves a flash on every cold load, where the 205 bare sites resolve to nothing until the module boots, and leaves the **login page permanently without `--accent`** — it carries a `var(--accent` site of its own and `index.html` carries 14. **Mirror the line into all three, and bump `CACHE_NAME` in `sw.js`** or returning users keep the old first-paint script.
  `CI:` none. `Verify:` cycle all 16 themes and diff screenshots — only the previously-unstyled elements change. Then: rail hover backgrounds appear; both resize handles become visible; the scroll-to-bottom button gets its colour; and the session rename input gets a border — that last one is **not** in the bare-site list, because that rule (at `style.css:7020` as of 2026-08-28; it was `:6775` before the file grew) is `var(--accent, var(--accent-primary))` with *both* undefined, so the whole `border` shorthand is invalid at computed-value time and falls back to `border-style: none`. Same fix, different failure mode.
- [ ] **P1-02** Define `--accent-primary` (121 uses, never defined) — or replace those uses with `--accent`. **Premise corrected 2026-08-27: this is token hygiene, not a bug hunt.** The line reads as 121 broken uses. It is not — **120 of the 121 already resolve correctly through their fallbacks**, 116 of them to the theme's `--red`. **Exactly one site is genuinely dead** — the session rename input, `style.css:7020` as of 2026-08-28 — — and that is the same pixel `P1-01` already fixes, so as written these two rows overlap on their only real defect. *(Line numbers in this row and `P1-01` move whenever `style.css` grows — re-derive rather than trusting them.)* Do `P1-01` first, then this becomes what it should always have been: an undefined token used 121 times, worth resolving so the next reader is not misled, with no visual change expected and none acceptable.
- [ ] **P1-03** **Define `--fg-muted`** (93 bare uses, zero definitions). Every one of those elements was authored as secondary text and renders at full strength. `Depends:` P1-01.
- [ ] **P1-04** **Delete `#sidebar-backdrop { display:none !important }`** at top-level nesting depth 0 — it beats the media-query rule everywhere. Thirteen call sites across four modules already toggle the element. `Verify:` mobile drawer dims the page and tap-to-close works.
- [ ] **P1-05** **Fix `#rail-settings`** — it unhides the sidebar and scrolls to the bottom instead of opening Settings. **Premise corrected 2026-08-27.** The rail gear is genuinely broken and stays open, but **the guided tour is not its victim.** The tour opens Settings through `#user-bar-settings` (`slashCommands.js:3337`), which works; the `#rail-settings` branch is reached only when that element is absent, and `ui_visibility.js:32` guarantees it never is. That branch is unreachable dead code. **The old `Verify:` passed on an unfixed tree** — a rewritten one is the only reason this row is still worth opening. `Verify:` click the rail gear on a cold load with the sidebar hidden; the Settings panel opens and the sidebar does not scroll.
- [~] **P1-06** Add semantic status tokens derived from the five theme tokens. — **BLOCKED on its own premise (2026-08-27).** Two problems, both fatal as written. **(1) The numbers do not exist.** 517 / 68 / 420 carried no scope and reproduce under none tried (`Law 5`); the nearest defensible measurement is **346 occurrences across 75 distinct non-grey hex values in `static/style.css` outside `:root`**. Nobody can size this row until its scope is written down. **(2) It would fork a third colour vocabulary.** `--warn` already exists at `style.css:30`, and the codebase already carries two semantic colour scaffoldings. Adding `--ok --warn --danger --info` beside them is precisely `Law 14`. **Unblock by:** stating the scope, then extending whichever of the two existing vocabularies is the better host — not by adding a third. `P1-07`'s 135 loose hexes outside `:root` fold in here.
- [x] **P1-07** Separate the Dracula/One-Dark syntax-palette occurrences into their own token set. — **SUPERSEDED (verified 2026-08-27) — the separation already exists.** Ten `--hl-*` tokens are declared and used 97 times, and they are recomputed per theme at `theme.js:270-281` and `index.html:45-56`. The palette was never unwired; the audit read the loose hexes and inferred a missing system. Re-measured with scope: 150 occurrences of the 27 One-Dark ∪ Dracula values in `static/style.css`, **135 of them outside `:root`** — and roughly half are duplicates of `--red`/`--green`, which makes them ordinary hardcoded colours. **Folded into `P1-06`**, which is the row that owns loose hexes. Nothing here is a separate task.
- [ ] **P1-08** **Computed `--on-accent`.** `.send-btn` hardcodes `color:#fff`; white-on-accent fails 4.5:1 on **15 of 16 themes**, and the accent itself fails on **8 of 16**. *(Re-measured 2026-08-27 — WCAG 2.x relative luminance per theme against the resolved send-button background and the theme background. One theme passes, which is worth knowing: it is the proof the token can be right rather than merely uniform.)* One token fixes all sixteen.
- [ ] **P1-09** Add a contrast guard inside `generateHarmonyColors()` and `applyColors()` (~15 lines) so every future custom theme clears the floor too. `Depends:` P1-08. **`CI:`** any new theme token must extend `ADV_KEYS` **and** `computeAdvancedDefaults()` in lockstep or all 16 themes break.
- [ ] **P1-10** **Normalise z-index to 7 named tiers.** **259 declarations, 64 distinct values** (re-measured 2026-08-27, scope: `static/style.css` only — 63 numeric plus one `var()`), range −1 to 1,000,000. Use the order-preserving remap: strictly increasing in the same sorted order ⇒ no element can change stacking. `Verify:` the remap list is strictly increasing; nothing moves visually.
- [ ] **P1-11** Fix the toast occlusion the tiering surfaces — toasts sit at 9999, below every image-editor popover at 10001–10006. Deliberate second pass, needs visual review. `Depends:` P1-10.
- [ ] **P1-12** **One global `prefers-reduced-motion` guard.** 18 narrow opt-outs against **160 keyframes** and 7 unguarded canvas animators — the background effects run continuously with nothing. **The 160 is the load-bearing correction** (re-measured 2026-08-27): 148 live in CSS, and **12 are injected into `document.head` at runtime by `slashCommands.js`**. A CSS-only guard cannot reach those twelve, so a guard written against the old 148 would pass its own review and still animate. Guard the injection site too.
- [ ] **P1-13** Elevation tokens: 4 theme-aware shadows replacing **288 declarations / 209 unique values** (re-measured 2026-08-28) (re-measured 2026-08-27, scope: `static/style.css`, comments stripped). **144** hardcode `rgba(0,0,0,α)` — re-counted 2026-08-28 across the whole file — on the four light themes those read as grey smudges. **156 of the 287 are already token-aware**, which the old figures hid: slightly over half the file is done, and the row is smaller than 287 makes it sound. The good theme-aware form already exists and is used 6 times.
- [ ] **P1-14** Name the signature curve. `cubic-bezier(0.34, 1.56, 0.64, 1)` is used 34 times and has never had a token.

---

# P2 · Un-nerf
*Area: `unnerf` · Depends: nothing · Runs in parallel from day one*

> ### ⚠ Scouted. Read `P2-CORRECTED.md` first — the task text below is superseded.
>
> Six scouts and six adversarial reviewers checked all 26 premises against the source.
> The reviewers overturned the scouts on **twelve of twelve** contested calls. What the
> pass changed:
>
> - **26 findings, not 29.** The count below was unsupported.
> - **P2-01 is blocked on a decision, not ready.** libmagic does *not* refuse every `.js`
>   — plain `function`/`console.log` files sniff as `text/plain` and upload fine today;
>   only IIFE, UMD, `"use strict"`, shebang and React-import shapes trip it. And deleting
>   the function also deletes the only block on `.exe .dll .bat .cmd .vbs .ps1`.
> - **P2-02 as written is a no-op.** A route cannot set a CSP in this app — the security
>   middleware overwrites it. The route it "mirrors" is already dead at the wire.
> - **P2-06 is bigger than stated.** Files that fail the check do not lose a code fence;
>   they return a literal `[Attached document file]` banner and **zero bytes reach the
>   model** — `.go .bash .tsx .jsx .php .yaml .rs .sql .rb .xml`.
> - **P2-19 and half of P2-20 are missing *wiring*, not missing markup.** Five entries are
>   omitted from `admin.js`'s `inits` and `refreshAll`. Adding HTML alone yields a panel
>   that renders empty and never fetches.
> - **P2-25's safe prune count is zero**, and a second admin gate the roadmap never named
>   (`_ADMIN_TOOLS`, checked *before* the blocklist) means a wrong prune can pass a manual
>   test and still be wrong.
> - **P2-13 and P2-09 need the fork head.** Both sit in the guardrail-caps commit's
>   subject area; editing them against upstream would redo or silently revert it.
>
> Eighteen cross-cutting surprises are listed there too. Several apply outside P2.

Read `FORBIDDEN.md` § Never Lift before starting — ~30 controls on the other side of the
line stay exactly where they are, and `P2-CORRECTED.md` § A names the five tasks that will
cross one if implemented carelessly.

### The archetype
- [x] **P2-01** **Delete the upload type check whole** — **decided, see `DECISIONS.md` — **done:** blocklist and call site deleted whole per D-2026-08-26-01; rationale comment at `src/upload_handler.py:1246`.
  D-2026-08-26-01: delete the function entirely, both blocklists.** Read that entry for the
  two things this genuinely costs before you write the diff. Original text follows; two of
  its claims are wrong, see `P2-CORRECTED.md` § C. — `is_safe_file_type()` and its call site. The blocked-MIME set contains `application/javascript`, so libmagic refuses every real `.js` file; `.js` isn't even in the extension list. **Nothing on the server executes an upload**, and every download carries `Content-Disposition: attachment` + `nosniff` ×2 + CSP. `.svg` — the actual stored-XSS vector — was never blocked. `CI:` none; no test references either constant. `Verify:` **not** `chat.js` — that always worked. `mimetypes.guess_type('f.js')` is `text/javascript`, which was never in the blocked MIME set, and `.js` was never in the extension list. The real delta is the extension half: `installer.exe` guesses to `application/x-msdos-program` (never MIME-blocked) but *was* extension-blocked, so it 400'd and now saves.
- [x] **P2-02** **That one line is a no-op and this task is not optional.** No route in this app can set a CSP — the middleware runs after the handler and starlette's `MutableHeaders.__setitem__` replaces rather than appends. The branch lives in `core/middleware.py`. The emoji route it was to mirror ships the same dead header. `Depends:` P2-01. — **done:** sandbox CSP branch at `core/middleware.py:138`, with `default-src 'none'`; the three pre-existing branches byte-identical.
- [x] **P2-03** **Delete four dead config blocks** (two allowlists, two blocklists) with zero readers. One blocks `.py`, `.sh` and `.js` — a live landmine if anyone wires it up. — **done:** four zero-reader blocks deleted, `src/config.py:34` and `:103`; the module-scope `validate_config()` side effect verified intact.
- [x] **P2-04** Delete the dead chat-upload validator that advertises a policy with no route callers. — **done:** `validate_file_upload` deleted, `src/chat_helpers.py:226`; live-path cap coverage retained in the test.

### Widen
- [ ] **P2-05** Memory import allowlist → add `.yaml .yml .ts .tsx .jsx .sh .xml .sql .rs .go .java .c .cpp .rb .php .docx` — **not** `.scss .toml .ini .vue .svelte`: none of those is in `is_document_file`'s `document_extensions`, so adding them here is unreachable code, or replace with a size+decodability check. Content is decoded to text and fed to an LLM; nothing is served back. Update the frontend `accept` to match. — **DECIDED — drop the allowlist entirely; decode and reject only what fails. Keep the PDF extractor and `.json` fast path as branches. Size and rate become the real control, per-role under `P12-01`/`P12-05`** (D-2026-08-26-06).
- [x] **P2-06** `_is_text_file` → add `.ts .tsx .jsx .css .scss .yaml .yml .sh .bash .sql .toml .ini .c .cpp .h .go .rs .rb .php .java .xml .vue .svelte` — matching the fence-language set already in the same file. — **done:** `_is_text_file` 10 → 28 suffixes at `src/document_processor.py:45`; 11 extensions verified to flip from banner to content.
- [x] **P2-07** Email attachment-as-doc → add a text fallback for any decodable attachment instead of `Unsupported attachment type`. The editor renders every language already. — **done:** **backend only** — decode fallback at `routes/email_routes.py:3728`. Unreachable from the UI until `emailLibrary.js:6807` moves, see B02.
- [ ] **P2-08** Raise `MAX_INLINE_ATTACHMENT_CHARS` (24,000 shared across **all** attachments in a turn — with 10 files that is 2.4 K each). Make it per-attachment or scale it off the input token budget. — **DECIDED — scale off the context window via `budget_context_for_model(…, fallback=0)`, keep first-come-first-served, per-role ceiling under `P12-04`. Reconcile all three numbers together** (D-2026-08-26-06).
- [ ] **P2-09** **Implemented once and REVERTED — read this before re-landing.** Scaling `skill_max_injected` off the context window is right in principle and wrong as first built: the value reaches `_build_system_prompt` from `get_context_length()`, which returns `DEFAULT_CONTEXT = 128000` for any endpoint whose window cannot be proven **and discards the `known` flag**. `compute_skill_injection_limit(3, 128000, explicit=False)` is **12**. A local llama.cpp box holding 8K would have been injected 12 skill blocks of user-editable untrusted content instead of 3 — the exact failure `src/model_context.py:313-315` warns about. A user who deliberately typed `3` into the `max="12"` input at `index.html:495` would also have got 12. **Re-land:** call `budget_context_for_model(url, model, fallback=0)` at `agent_loop.py:4342` — returns 0 for an unproven window, shares the existing cache, adds no probe, restores the flat 3. **Decide first:** `0` is already the documented off switch, so *auto* needs its own sentinel or an explicit UI affordance. The pure functions written for it were correct in isolation and are worth keeping for the re-land. **DECIDED — a checkbox, "scale to the model's context window", disabling the number field when ticked; the number becomes the ceiling** (D-2026-08-26-06).

### Fix
- [x] **P2-10** **The fake concurrency limit.** — **SUPERSEDED (verified 2026-08-27) — the work is `P12-06`.** D-2026-08-26-06 reversed this row's body: it does **not** get deleted, because "one operator cannot DoS themselves" stops being true under `P11`. Leaving a line whose title and first sentence say *drop it* while a clause at the end says *do not* is a `Law 10` hazard — an agent that stops reading at the instruction deletes a control the roadmap decided to keep. The false-positive on multi-file drag was fixed independently (`upload_routes.py:285-291`, #1346); the constant and the ten-second window are open at `P12-06`.
- [x] **P2-11** Raise `MAX_FILES` (10 → 25) **and** add a server-side `len(files)` cap, which does not exist. **`CI:` a test regex-parses this literal** and asserts `upload_rate_limit >= MAX_FILES`. — **done:** `MAX_FILES_PER_REQUEST = 25` at `src/upload_handler.py:227`, enforced pre-loop at `routes/upload_routes.py:274`; partial-write hazard fixed.
- [ ] **P2-12** **Stop hiding small email attachments.** The signature heuristic also returns true for *any* image under 30 KB — a real screenshot is silently invisible **and** excluded from the ZIP. Keep the filename patterns, drop the size clause. — **DECIDED — drop the size clause in **both** files, pin `_has_visible_attachments` to the old predicate, keep the two filename patterns. Write the first test** (D-2026-08-26-06).
- [~] **P2-13** **BLOCKED — correctly, on something the spec never named.** Premise verified true: both clamps exist at `src/llm_core.py:1071` and `src/agent_loop.py:2212`, and the Anthropic cloud clamp at `:1572` is untouched. But **four assertions in two unowned test files pin the cap** — `tests/test_llm_core_temperature_reasoning.py:104` and `tests/test_pr6020_rebase_regressions.py:182/:201/:216`. The two qwen tests exist to prove a mixed fallback chain leaks temperature in neither direction, and that property must survive any rewrite. **Also needs a decision:** `_apply_local_generation_stability` receives only a payload dict and cannot tell *the user asked for 0.9* from *0.9 is a default*, so a faithful "default, not cap" needs an explicitness signal threaded from the builder. The agent refused to ship a hidden env escape hatch with no UI — right call. **DECIDED — thread an `explicit_params` set from the payload builder; the clamp becomes a setdefault for everything else. Keep the Anthropic ceiling** (D-2026-08-26-06).
- [ ] **P2-14** Loosen the guide-only trigger: seven regexes fire on any mention of the phrasing and then strip **all 82 tools** — re-measured 2026-08-27 by executing `known_tool_names()` in-tree, not 81 — **and all MCP** for the turn. Require whole-message match, or an explicit toggle. — **DECIDED — anchor patterns 1–6 to whole-message match; convert pattern 7 into a confirmation mode that arms the approval gate rather than stripping tools** (D-2026-08-26-06).
- [x] **P2-15** Fix the self-contradicting bash prompt — one line forbids heredocs, seven lines later another instructs the model to use one. Prompt-only; enforces nothing. — **done:** heredoc instruction removed at `src/agent_loop.py:574` — 10 ban sites, 0 instruction sites.
- [x] **P2-16** Fix the grammar bug producing `Your account is not allowed to can use research.` — **done:** `privilege_denied_message` at `src/auth_helpers.py:127`; the fail-open `privs.get(key, True)` deliberately untouched.
- [x] **P2-17** Cap the backup import — `await request.json()` with no size limit on an admin route. — **done:** 413 cap at `routes/backup_routes.py:134`, **after** `require_admin` at `:131`; env var wired into all three compose files and `.env.example`.
- [ ] **P2-18** Fix the feature-flag story: `deep_research` defaults off, the frontend hides four buttons, and **no server route checks it**. Either enforce server-side or delete the three flags with zero consumers. Flip `deep_research` on. — **DECIDED — fix the precedence bug generally, delete the three consumerless flags, flip `deep_research` on. **No server-side enforcement** — the endpoint is auth-exempt and was never a boundary** (D-2026-08-26-06).

### Re-surface what was built and never wired
- [ ] **P2-19** **Webhooks admin panel** — backend complete, **no UI whatsoever**. Add `adm-whList` / `adm-whAddBtn` markup. **Premise corrected 2026-08-27.** The two functions do not throw, because **neither is ever called** — `initWebhookForm` (`admin.js:2735`) is absent from the `inits` array at `:3152-3156`, and `loadWebhooks` (`:2684`) is absent from `refreshAll` at `:3164-3171`, and `initWebhookForm` has no `try` at all. The silent-`try` story was wrong, and it mattered: null guards alone would have shipped a panel that still never renders. **The fix is markup *plus* registration in `inits` and `refreshAll`**, the same pairing `P2-20` needs. `Verify:` the panel renders on a cold load of the admin page, not merely on a hand-called init.
- [ ] **P2-20** MCP admin panel markup (`adm-mcp*`) — this also makes the OAuth-file registration path reachable for the first time. Feature toggles (`adm-featureToggles`), API tokens (`adm-tokenList`), RAG (`adm-rag*`). All four backends exist. — **DECIDED — build only RAG and feature toggles; skip MCP and tokens, which already have live UIs in settings (`Law 14`). Wire both into `inits` and `refreshAll`** (D-2026-08-26-06).
- [ ] **P2-21** Built-in skills editor: flip `showBuiltin = false` → `true`. `_buildBuiltinCards()` and its admin endpoints are fully implemented, including a per-tool instruction-block override editor. **There are four endpoints, not three, and only two are gated** (`skills_routes.py:1250/1287/1311/1337` — both GETs are open, re-measured 2026-08-27). That is the whole reason `P11-10` amended this row from optional to required. — **DECIDED — gate the two GETs, write the list loader, then flip the flag. **Amended from optional to required** by `P11-10`** (D-2026-08-26-06).
- [x] **P2-22** Re-attach the gallery upscaler controls (`ge-upscale-*`). Backend + local Real-ESRGAN both implemented, zero UI. — **DECIDED — target `/api/image/upscale-local` (local Real-ESRGAN). A backend selector waits for a real GPU host** (D-2026-08-26-06). — **done:** completed by wiring run 01 — `ge-upscale-section` built in `static/js/editor/build/controls.js`, toolbar entry present, and `ai-tools-misc.js` targets `upscale-local` per D-2026-08-26-06.
- [x] **P2-23** Give RAG upload a UI — the module expects three elements that do not exist. The endpoint works and has **no extension restriction at all**. — **DECIDED — resurface the **user-facing** `rag.js` module, not the admin one. Three ids plus wiring, on a module already called every boot** (D-2026-08-26-06). — **done:** completed by wiring run 01 — `rag-upload-zone`, `rag-file-input` and `docs-view` all present in `static/index.html`, on the user-facing `rag.js` module as decided.
- [ ] **P2-24** Add a custom-font upload route. **Keep the extension allowlist here** — these files land under the static mount and are served with no forced disposition — the one place in this app where an uploaded file is served back to a browser, which is why the allowlist stays here and nowhere else.
- [ ] **P2-25** **Document `NON_ADMIN_BLOCKED_TOOLS` — prune nothing.** *(Retitled 2026-08-27: the old title read "Prune…" while its own decision clause said not to. An agent that stopped at the title would have pruned — `Law 10`.)* The decision is settled: **nothing comes out of this list.** The remaining work is documentation — say beside each entry why it is blocked, so the next reader does not re-litigate it. **Must stay:** shell, python, all filesystem tools, vault, settings, tokens, endpoints, MCP, webhooks, api_call, app_api, and the `mcp__*` prefix rule. **`resolve_contact` is the trap** — it reads owner-scoped and harmless and is the entry most likely to be pruned by someone acting on the old title. **`CI:` two tests cover this partition.** (D-2026-08-26-06)
- [ ] **P2-26** **Document the app-API blocklist — trim nothing.** *(Retitled 2026-08-27, same reason as `P2-25`.)* The decision is settled and this list gets **stronger** under `P11`, not weaker. **Must stay:** the cookbook install/rebuild/kill entries, every prefix rule, and — **missing from the old must-stay list** — `POST /api/cookbook/state` and `DELETE /api/cookbook/state`. Those two are data-destruction guards that **no test pins**, which makes them the pair most likely to be trimmed by accident and the least likely to be caught. Write the reason beside every entry and close the row. (D-2026-08-26-06)

---

# P3 · Mechanical hygiene
*Area: `css-hygiene` · Depends: P1 · Blocks: P5*

Provably safe, and each one removes a trap the restyle would otherwise fall into.

- [ ] **P3-01** **Resolve `#message` declared 4×.** The composer never renders at its authored 14px — a later `!important` forces 13px, and a third rule forces 16px on touch. One of the conflicting blocks sits under a class that does not exist. **Do this before any composer work.** *(Note: `max-height` is fine — 200px wins on specificity; only the font-size conflict is real.)*
- [ ] **P3-02** Resolve `.attach-strip` declared 3× with conflicting margin and padding.
- [~] **P3-03** Delete the confidently-dead CSS rule blocks. — **BLOCKED (2026-08-27), for two independent reasons, either one sufficient.** **(1) The measurement does not exist.** 510 / 2,590 / 349 came from a classifier that **is not in this repo**, so nobody can reproduce or re-check them — and they are stale besides: the wiring run deleted 1,524 lines of JS *after* they were taken, which moves every one of those numbers. The arithmetic checks out (2,590 / 41,401 = 6.26%) and that is all that can be said for them. **(2) `P2-20` must land first.** 16 `admin-rag-*` rules in `static/style.css` (`.admin-rag-upload-zone` at `:15733-15747` and others) are dead **only because `P2-20`'s markup is missing** — a sweep run today deletes exactly the CSS `P2-20` needs. **This already happened in reverse and proves the risk:** `.rag-upload-zone` (`style.css:2392/:2402`) was an orphan until `P2-23` landed its markup, and is live again now. **Unblock by:** landing `P2-20`, then rebuilding the classifier with the `check-wiring` scope lesson applied — it must resolve helper lookups, not just `getElementById`. Verified 0/55 false positives on two random samples, which is the one part of the old row still worth keeping.
- [ ] **P3-04** Delete duplicate `@font-face` (the whole Fira Code set is declared twice) and the exact-duplicate `@keyframes` — **3 names but 4 duplicate blocks**, because `spin` has two extras rather than one (re-measured 2026-08-27). Deleting three blocks leaves one behind.
- [ ] **P3-05** **Fix the 2 conflicting `@keyframes` redefinitions** — `research-pulse` and `fadeIn`. These are live bugs: the later definition silently wins for every consumer, including code written against the earlier one.
- [ ] **P3-06** Collapse the clone-body animations into one — **9 definitions under 7 distinct names** (re-measured 2026-08-27; two names are themselves declared twice), every one of them the body `to { transform: rotate(360deg) }`.
- [ ] **P3-07** **Canonicalise breakpoints to three.** 13 distinct widths today. One **559**-line block switches to mobile at 700px while **2,965** lines switch at 768px (re-measured 2026-08-27, scope: 85 `max-width:768px` blocks, span-summed) — **between those widths the UI is in a mixed state**, and there is a 20px dead zone (701–719) where an unpaired min/max leaves neither rule applying.
- [~] **P3-08** Add paired-rule comments so a desktop rule points at its mobile override. — **BLOCKED (2026-08-27):** the row cites *"the roadmap's own 'CSS did not move' item"* and **there is no such item** — the citation is self-referential with no antecedent, so there is no way to know which pairs are meant or when this is finished (`Law 9`). It also **must follow `P3-07`**: canonicalising 13 breakpoints down to three rewrites the pairings, and doing this first means writing 85 comments twice. **Unblock by:** landing `P3-07`, then defining what a "pair" is in one sentence.
- [ ] **P3-09** Delete `:root.light` (21 lines + 3 other sites) — unreachable by construction, since light themes push values through the five tokens and never add a class. **Recover the well-tuned light syntax palette inside it first.** `Verify:` the four light themes stop rendering dark native dropdowns.
- [ ] **P3-10** Delete the **2** dead modules. **Premise corrected 2026-08-27.** **The RAG module is live and must not be deleted** — `P2-23` landed its three DOM targets at `static/index.html:485-487`, so the bail-out at `rag.js:143` no longer fires. Deleting it now would remove a feature that started working four days ago; this is exactly the row that would have caused it. **Corrected again 2026-08-28, and the row is now one module, not two.** What is actually dead: **`calendar/reminders.js`** (114 lines, zero importers). That one goes — update `sw.js` and bump `CACHE_NAME` in the same commit.

  **`tourAutoplay.js` is not dead and must not be deleted. It is the product's entire first-run walkthrough system**, and deleting it is the single most vision-contradicting act available in this tracker. Read: 133 lines of working code, imported at `static/index.html:2642`, mapping seven modals to per-feature tours — `doclib-modal`→`tour-library`, `cookbook-modal`→`tour-cookbook`, `research-overlay`→`tour-research`, `compare-model-overlay`→`tour-compare`, `theme-modal`→`tour-theme`, `settings-modal`→`tour-settings`, `gallery-modal`→`tour-gallery` — one-shot per modal, mobile excluded because tours position halos by rect math. Only `init()` is stubbed, with the comment "Disabled for v1 stability". **`Law 15` exists in this project because its owner stopped using a competitor's *more advanced* version of what we are building, for exactly one reason: *"There's no tutorials and the learning curve is too steep."*** Deleting the only onboarding we have would be that mistake, made deliberately, by the project that wrote the law. Re-filed as `P3-10b`.
- [ ] **P3-10b** **Re-enable the first-run tours — `Law 15`'s first concrete row.** `static/js/tourAutoplay.js` is complete and switched off: `init()` is stubbed with "Disabled for v1 stability", and nobody recorded which instability. Find out whether it still reproduces (the seven target modals have all changed since), then turn it back on behind a setting a person can find. `Depends:` nothing. `CI:` none. `Verify:` a browser with cleared storage opens the Forge modal for the first time and gets its walkthrough; opening it again does not; and the setting that turns tours off is discoverable without reading the source. **This row is the answer to the question the owner asked of a competitor and we have not yet asked of ourselves.**
- [ ] **P3-11** Fix the duplicate module specifier — `chatRenderer.js` is imported under 3 distinct specifiers, so a 3,126-line module is parsed three times per page load. A config module's header documents the symptom and works around it; the root cause was never fixed. One-line change per import.
- [ ] **P3-12** Delete the verified-dead elements and handlers. **Re-measured 2026-08-27 and the orphan-id count is not four — it is 26.** Scope: 476 ids in `static/index.html`; 31 are never read by JS; 26 of those 31 are absent from CSS too. Only the drag-reorder item was verifiable as written (it queries a `draggable` attribute nothing ever adds). **The other two items — "two elements killed by CSS" and "a handler wired to a nonexistent element" — are not itemised anywhere**, so under `Law 9` this row cannot be honestly ticked until someone names them. Itemise the 26, then delete under `Law 1`.

---

### Hardening — failure modes another product shipped, that this one can still ship
Mined from a competitor's public changelog. Their private repo hit these; ours has the same
shapes. Each is an audit, not a guess.

- [ ] **P3-16** **Audit every read-then-write path for the destructive-save pattern.** PandaOS
  permanently lost user API keys when a locked keychain caused a **silent decrypt failure
  followed by a destructive save** — the read returned empty, the empty overwrote the good data.
  Pantheon stores MCP env vars unencrypted, has an admin backup import, and writes `auth.json`,
  settings and skill files in place. `Verify:` no writer persists a value derived from a read
  that failed; a failed read aborts the write.
- [ ] **P3-17** **Fail loudly.** They fixed "several paths where the app could quit silently
  instead of surfacing an error." **Premise corrected 2026-08-27.** **Both halves of this row were wrong.** The
  webhook example is refuted — see `P2-19`; those functions are never called and one has no
  `try` at all. And the `Verify:` line **passes today on an unfixed tree**: there are **zero**
  bare `except:` statements in non-test Python. A row whose acceptance test already passes is a
  row that gets ticked without a fix. The real target is `except Exception: pass` — **199 pairs**
  in non-test Python (re-measured 2026-08-27). `Verify:` every one of the 199 either logs, or
  surfaces to the user, or carries a comment saying why swallowing is correct there.
- [ ] **P3-18** **Stacking order: menus above modals.** They shipped dropdowns and context menus
  rendering *behind* open dialogs. Pantheon has a window system, a tile manager, modal chrome
  and popovers. `Verify:` every popover opened from inside a modal is visible.
- [~] **P3-19** **Graph and canvas surfaces need a no-acceleration fallback.** Their Brain graph
  crashed outright on machines with hardware acceleration disabled. `P13-07` is a graph.
  **`Blocked:` `P13-07` is unstarted — the artefact to be made resilient does not exist yet**
  (2026-08-27). Nothing here is verifiable until it does. *(The canvas half is not idle work:
  the 7 unguarded canvas animators in `P1-12` are already in the tree today.)*

### Drift control — Law 13's enforcement
- [x] **P3-13** **Wire `check-wiring.py` into CI at `--max 78`.** It counts `getElementById` — **done:** the ratchet runs in CI as the `wiring-ratchet` job in `.github/workflows/ci.yml`, at `--max 2`. **Wired 2026-08-28, after an alignment audit found this row ticked on a gate that did not exist** — `git grep check-wiring` outside `.pantheon/` returned two hits, neither of them a workflow, while three documents advertised it. The law against shipping half-wired features was itself half-wired, which is the one defect that lets every other one through. `--max 2` is the floor rather than a target — both remaining entries are artifacts of the checker's own regex against dynamic lookups, and its docstring already concedes that class is invisible.
  targets that resolve to nothing: 78 today, across 16 prefixes and seven subsystems. The
  ceiling may fall and may never rise. Every built-and-never-wired finding in the P2 audit
  would have shown up here years ago if anything had been counting. `Verify:` a PR that adds
  an unresolved lookup fails.
- [x] **P3-14** **Clear the 78.** Not one task — each id is either wired to markup, or deleted — **done:** **78 → 2.** 340 insertions against **1,524 deletions** — overwhelmingly dead code removed, not markup added. Full report in `runs/wiring-run-01.md`.
  along with the handler that looks for it. Grouped by owner: `ge-*` 17 (gallery editor,
  overlaps `P2-22`), `doc-*` 11, `cookbook-*` 9 (becomes `forge-*` under `P0-29`),
  `doclib-*` 6, `new-skill-*` 5, `email-*` 4, `gallery-*` 3, `hwfit-*` 3, `rag-*` 2
  (`P2-23`), `tool-*` 2, plus 13 singletons. Lower the ceiling after each batch.
- [ ] **P3-15** **Extend the check to the other half of the disease** — routes with no caller,
  settings keys with no reader, feature flags with no consumer. `P2-18` found three flags with
  zero consumers by hand; a script finds the next three for free.

**`check-wiring.py` has two blind spots, and they are worth fixing before extending it**
*(measured 2026-08-27)*. It scans `tracked("static/js")` only, so **`static/app.js` and
`static/sw.js` are never scanned at all**; adding them to the identical algorithm takes
UNRESOLVED from **2 to 6** — `notes-fullscreen-toggle` (`app.js:1175`), `mode-toggle`
(`:1336`), `overflow-research-btn` (`:1357`), `message-input` (`:3840`). And it matches only
literal `getElementById(...)`, so every `el('…')` helper lookup is invisible: **`static/js/
admin.js` makes zero literal calls and 75 `el('adm-*')` ones, 39 of which resolve to nothing.**
Extending the checker's own resolution rule to `el()`/`_el()` across the same tree gives
**1,351 lookups and 125 unresolved** (`settings.js` 51, `admin.js` 45, `app.js` 27). Treat 125
as the size of the blind spot, **not** as 125 confirmed defects — only 3 were individually
adjudicated, and the `--max 2` ceiling is honest for what the checker currently measures.
`P3-13`'s ceiling should fall to cover `app.js` and `sw.js` first; the helper-aware rule is a
bigger change and belongs here, with `P3-14` re-run against it.

---

# P4 · The wire — the real glass box
*Area: `wire`, `trace` · Depends: P1 · Blocks: P5*

**`Law 15` applies to every row in this phase.** It draws surface a person has to operate, and the law exists because the owner stopped using a competitor's *more advanced* version of this product for one reason: *"There's no tutorials and the learning curve is too steep for the little amount of time I have."* A row here is not done because the feature works — it is done when someone who has not read this tracker can find it, tell what state it is in, and use it without being told how. Put that in the row's `Verify:` line, in those terms.

The backend emits **39** distinct SSE event types through a single `if/else if` chain;
anything without a branch is silently discarded. **Thirty-plus fields are computed,
serialised, sent to the browser and never read.** None of this needs backend work.
*(39 re-measured 2026-08-27, scope stated: the `type` key of every dict serialised into a
`data:` frame on `/api/chat`. The old "~50" was a tilde doing load-bearing work — `Law 5`.)*

### Prerequisite — do this first
- [ ] **P4-01** **Unify the six drifted agent-thread templates into one builder.** They exist across the live path, history replay and compare mode, and **zero pairs are byte-identical**. They diverged three ways: compare mode hardcodes the fallback icon so it can never show the search glyph; one copy omits the diff block; the labels differ. **This is not a mechanical extract — you must decide which behaviour is correct and record the decision in your handoff note.** Every other P4/P5 trace task depends on this.
- [ ] **P4-02** Fix the key-name mismatch: the shell tool sends elapsed time under one name and the frontend reads another, so the displayed timer is a client-side guess rather than server truth. One rename. `Depends:` P4-01.
- [ ] **P4-03** Delete the dead handler for a skill-saved event the server never emits.

### Free — already on the wire, zero backend work
- [ ] **P4-04** **The approval card's own reason.** The server sends a written explanation naming the exact effects that tripped the gate; the renderer never reads the field. *(Style-only — see `DEFERRED.md` for the markup constraint.)*
- [ ] **P4-05** **The full fallback chain** — every model candidate tried with its HTTP status. Render `gpt-4o ✗502 → claude ✗429 → llama ✓` instead of a six-second "retrying" toast.
- [ ] **P4-06** **`failed` and `failure{status,message}` on terminal metrics.** **Premise corrected 2026-08-27.** Not *identically* — the reply text does carry `[Agent stopped: …]`, so a reader is not left with nothing. What renders identically is **the metrics footer and the stats popup**, which report a failed turn with the same shape and styling as a successful one. Still a correctness bug and still the highest priority in `P4`; the scope is narrower than the line claimed and an implementer diffing whole messages will not find it.
- [ ] **P4-07** Per-round token buckets — round, model, endpoint, input/output tokens, cost-tracked flag. Currently summed into one cost number and discarded.
- [ ] **P4-08** Live prep breakdown — request setup, tool selection, prompt build, context trim, each timed. Replaces a static spinner label.
- [ ] **P4-09** `full_command` on every tool start — expand-to-full-arguments on the running card. The truncated version is what you see now. `Depends:` P4-01.
- [ ] **P4-10** Loop-breaker detail and the unkept-promise phrase — `"Stopped: called bash with identical arguments 15 times"` instead of a generic message.
- [ ] **P4-11** Round numbers on every step and tool event. `Depends:` P4-01.
- [ ] **P4-12** `approved: true` badge on tool events — the action you personally authorised is currently indistinguishable from a routine call. `Depends:` P4-01.
- [ ] **P4-13** Trim and compaction figures — tokens before/after, messages before/after.
- [ ] **P4-14** Real decode speed, prefill speed, time-to-first-token, context tokens — separating prefill from decode and measured from computed.
- [ ] **P4-15** `tmux_session` on long shell runs → an "attach to this session" affordance.

### Cheap — one emit line or one field
- [ ] **P4-16** **Which skills were injected** — name, source, teacher model. Up to twelve enter a request and **nothing says which**. The loop knows all of it and emits none. Highest-value gap in P4; mirrors how memories already work.
- [ ] **P4-17** The verifier's findings — a second model checks the work and its issue list is injected into the prompt, never shown.
- [ ] **P4-18** Auto-escalation and its hidden tool blocklist — "Promoted to Agent (shell and file tools withheld)". Currently silent in both directions. The flag is computed and never sent.
- [ ] **P4-19** **stderr, separated.** The model sees stdout and stderr labelled separately; the user only sees stderr when stdout is empty. Add a separate pane and the actual numeric exit code.
- [ ] **P4-20** Policy-blocked calls emit **no tool card at all** — the call vanishes and the thread's state pointer goes stale, so an approval card appears with no visible cause. Add a distinct "blocked by policy" node. `Depends:` P4-01.
- [ ] **P4-21** Approval expiry — a ten-minute TTL that is computed and never sent. Today the card silently stops working.
- [ ] **P4-22** Prompt-cache read/write tokens — extracted from the provider, written to a log line, dropped. **Cache hit ratio is the single biggest lever on real cost.**
- [ ] **P4-23** Live tool-budget and round meter — a progress bar instead of a surprise stop at the limit. The agent already streams step events.
- [ ] **P4-24** **Background sessions get none of this.** When a stream is resumed after navigating away, a second and much poorer dispatch chain collapses every tool, research and source payload to a single "this was rich" boolean. **Premise corrected 2026-08-27.** **"Unobservable after the fact" is wrong** — the session reloads and replays from persisted `tool_events`, so the history is there once the stream ends. What is actually lost is the **live** view *during* the resumed stream: for the length of that stream you watch a rich run through a one-bit window. Narrower, still real, and the fix is the same dispatch chain. `Depends:` P4-01.

### Run receipts — Law 14: this is P4's job, not a phase of its own
The wire already computes model, parameters, tools offered, skills injected and RAG hits, then
discards them. A receipt is that data kept instead of thrown away.

- [ ] **P4-25** **Capture a receipt per agent run** — model and endpoint, resolved sampling
  parameters, the tool schemas actually sent, which skills were injected and at what confidence,
  which memories and documents were retrieved, round count, token usage, and every approval
  decision with its outcome. **Premise corrected 2026-08-27.** **"All on the wire, none kept" is wrong in both
  directions.** Five of the eight items already persist (`routes/chat_helpers.py:1044-1070`), so a
  fresh receipt table would duplicate them — `Law 14`. Three are neither on the wire nor kept,
  and those are the actual work: **extend what persists, do not start a second store.**
- [ ] **P4-26** **Make a receipt re-runnable.** Same inputs, same configuration, new run —
  which is the only honest way to answer "did that change help". `Depends:` P4-25.
- [ ] **P4-27** **Make a receipt portable.** One file, exportable, readable by a person who was
  not there. This is what turns "it did something weird" into a bug report. `Depends:` P4-25.
- [ ] **P4-28** **Diff two receipts.** What changed between the run that worked and the one that
  did not. `Depends:` P4-26.

---

# P5 · Trace & composer restyle
*Area: `trace`, `composer` · Depends: P3, P4-01*

**`Law 15` applies to every row in this phase.** It draws surface a person has to operate, and the law exists because the owner stopped using a competitor's *more advanced* version of this product for one reason: *"There's no tutorials and the learning curve is too steep for the little amount of time I have."* A row here is not done because the feature works — it is done when someone who has not read this tracker can find it, tell what state it is in, and use it without being told how. Put that in the row's `Verify:` line, in those terms.

- [ ] **P5-01** Replace the **two** nested 300px scrollers with a `grid-template-rows: 0fr → 1fr` transition. *(Re-measured 2026-08-27 — scope: CSS rules pairing `max-height:300px` with `overflow-y:auto` in trace markup. An implementer hunting a third will not find it.)* Long reasoning currently clips into a 300px inner scroller inside the page scroller — the worst UX defect in the trace.
- [ ] **P5-02** Give tool nodes the same open/close transition as reasoning. They hard show/hide today while a sibling inches away animates.
- [ ] **P5-03** **Stop cards renaming themselves on completion.** A node reading *Running* becomes *bash*; *Searching* becomes *web_search*. 21 tools affected, and history replay shows raw ids for all of them. Compare mode already does it right — proof it is a bug. `Depends:` P4-01.
- [ ] **P5-04** Per-tool icons — the map has **one entry** against 21 labels; everything else falls back to a triangle. Inline monochrome SVG. `Depends:` P4-01.
- [ ] **P5-05** One disclosure idiom. Two compete today: left-▶-rotate for generic details, right-▼-flip for reasoning, sources and tool output. Pick the right-side chevron and retire the global left marker.
- [ ] **P5-06** **Code block headers.** `data-lang` is already on every `<code>` and never displayed; `langIcons.js` already has the icons and is imported by two document modules and never by chat. Both halves exist and have never been connected. Moving copy/edit/run into the header also solves buttons-covering-text.
- [ ] **P5-07** Make the executed command copyable — `.agent-thread-cmd` has no highlight, no copy, no expansion, and it is the most copy-worthy string in the UI. `Depends:` P4-09.
- [ ] **P5-08** Expand-all, tool-argument pretty-printing, and copy-on-tool-output. `createCollapsible()` is the ready-made primitive — written, inheriting the delegated toggle and hash persistence, reachable from nothing.
- [ ] **P5-09** Injection disclosure as a collapsible peer of `.sources-section`, reusing that idiom verbatim so it inherits styling and behaviour. `Depends:` P4-16.
- [ ] **P5-10** Restore prose heading hierarchy. `h1`–`h6` map to keyword/function/string/builtin/variable/number — a five-heading answer renders as five hues across a 20% size range. **Keep the syntax hue on h1 and h2 only**; that pairing is the tell, the rest is noise.
- [ ] **P5-11** Fix the section-header inversion — headers are 10px/400 over 13px rows. Both sizes already exist; this is a swap.
- [ ] **P5-12** Consolidate the **seven** hand-styled tool chips and the two bare-icon toggles into **one chip component**. *(Re-measured 2026-08-27, scope: `input-icon-btn tool-indicator` in `static/index.html`.)* Cleanest large win in the composer, and it makes the strip themeable for the first time.
- [ ] **P5-13** Icon normalisation — three sizes and one stroke token replacing **20 sizes and 14 stroke widths across 1,193 inline SVGs**. *(Re-measured 2026-08-27, scope: `static/*.html` + `static/js/**` + `static/app.js`, excluding `static/lib`. The old 8 and 9 were `index.html` alone — the row is two and a half times the variance it advertised.)* A stroke-2 glyph from a 24 viewBox at 11px has an effective stroke under one pixel. **Attributes only; no SVG markup is rewritten.**
- [ ] **P5-14** Type scale — collapse 27 ad-hoc steps onto a ramp drawn from the existing values, with **11px as the floor rather than the median** (**829** of 1,222 sizes are 10–12px; 118 are ≤9px — re-measured 2026-08-27, scope: `font-size:<N>px` declarations in `static/style.css`; the 27 steps confirmed).
- [ ] **P5-15** **Populate `#pinned-tools-bar`** — an empty div appearing once in the whole codebase with zero CSS and zero JS. Unclaimed composer real estate, no layout risk.
- [ ] **P5-16** Make the send button's five states legible without changing the machine. **Eight modules mutate it**; any composer rework must reproduce `newchat · mic · send · streaming(processing/receiving/queue) · recording` exactly. Note Enter-on-empty opens a new chat, and the mic state appears from a silent server capability check.

---

# P6 · Queue & Plan
*Area: `queue`, `plan` · Depends: P4-01*

**`Law 15` applies to every row in this phase.** It draws surface a person has to operate, and the law exists because the owner stopped using a competitor's *more advanced* version of this product for one reason: *"There's no tutorials and the learning curve is too steep for the little amount of time I have."* A row here is not done because the feature works — it is done when someone who has not read this tracker can find it, tell what state it is in, and use it without being told how. Put that in the row's `Verify:` line, in those terms.

- [ ] **P6-18** **Steer mid-response, not only queue.** The queue holds the *next* message;
  steering redirects the one in flight. Two different verbs, and only one exists. Prior art has
  both on one key pair — Enter queues, Cmd/Ctrl+Enter steers — which is the right shape because
  it is the same intent at two urgencies. `Depends:` P6-01.
- [x] **P6-01** **Session-bind the queue — live bug.** Queue items carry no session id. Switching chats wipes the message list, destroying every queued bubble's element while the array keeps the items; when the old stream ends the prompt **fires into whichever chat is now open**, invisibly. Add the field, filter the drain on it, re-render bubbles on session switch. — **done:** queue items carry `sessionId`, set at queue time; the drain filters on it and bubbles re-render on session switch. **The fix needed a second pass:** refutation proved the click-to-promote path still leaked — `_promoteQueuedRequest` guarded at click time and then handed the item to a poller that retried every 220ms with no check, so switching chats during the abort round trip still posted one session's text into another. Guarded at *send* time instead (`chat.js` `trySend` plus a backstop in `_setComposerAndSend`), and a mismatched item is **put back in the queue** rather than dropped — it is still the user's message. Verified with the refuter's own attack: fires into B never, kept and addressed to A, and still sends correctly on returning to A.
- [x] **P6-02** Persist the queue. `_queuedAgentRequests` is a bare module array — a reload loses it silently. — **done:** queue persisted through the app's existing `Storage` helper — no second store (`Law 14`). Restored items never auto-replay: they re-arm only on their own session's next ended stream, expire at 24h, and cap at 20 rows, so a reload cannot resurrect a stale prompt.
- [x] **P6-03** Allow queueing with attachments — currently refused with an error that swallows the send. — **done:** attachments are uploaded at queue time and re-carried through the slot resend/regenerate already uses, so a queued send goes down exactly one attachment path. A failed upload returns the text **and** the files to the composer instead of eating them. *(The implementer proposed a wording correction to this line; refutation showed the line was already accurate and the correction was not applied — the tracker says "swallows the send" in all four places and nothing claimed the message disappears.)*
- [ ] **P6-04** Build the queue panel: drag-reorder, edit in place, per-item mode/model/trust rung, start-now force bypass, pause, remove. **Clone the research job engine** (382 self-contained lines) rather than writing a new one — but **not "only two lines are research-specific"**. Re-measured 2026-08-27: **roughly 16 research-specific references across 7 endpoints** (scope: case-insensitive `research` in `research/jobs.js`). Still worth cloning; budget a generalisation pass rather than a find-and-replace.
- [x] **P6-05** Adopt the shipped status vocabulary: `queued → running → success | error | skipped | aborted`. `skipped` and `aborted` are load-bearing — `aborted` keeps infrastructure events out of error-rate stats. **The gap is a documentation gap, and it is the reason this row exists** (2026-08-27): `db.py:818`'s comment documents **3** statuses while `task_scheduler.py` actually writes **6**. Three real states are undocumented, so anything reading the comment instead of the code mis-handles them. — **done:** the six-value `TaskRun.status` vocabulary is documented at `core/database.py:810+` — what each means, which writer sets it, and why folding `aborted` into `error` corrupts error-rate statistics. **Refutation caught the block asserting something the tree contradicted**, so the audit came with it: `static/js/tasks.js` `_entryStatus` text-scanned run output for `/error|failed|exception|traceback/` and filed an `aborted` run under Errors whenever its partial output mentioned one — fixed to prefer the row's own status, matching its correct sibling in the same file. One violation stays open and is named in the block: the scheduler writes `error` on an admin-privilege refusal where the task never ran, which is `skipped` by these definitions. Changing a persisted status value earns its own row.
- [ ] **P6-06** Sequential-vs-parallel picker. **Already built** in the research panel — reuse it. Parallel must allocate a session per item: one agent run per session is enforced.
- [ ] **P6-07** Point the existing Tasks activity view at queue items rather than building a second queue UI. It already renders every status with shared elapsed timers, a force button and a stop button.
- [x] **P6-08** Make `_concurrency_cap` actually configurable — it sits next to `Semaphore(1)` and is documented as "a hard guarantee, not configurable". — **done:** `_concurrency_cap` resolves through instance setting → env → built-in default, clamped to [1,16], re-read on settings change without a restart. **Registered in all four places it has to exist** — `DEFAULT_SETTINGS`, `.env.example`, and *all three* compose files: adding it only to `docker-compose.yml` broke `test_gpu_compose_standalone.py`, which pins the standalone GPU files as base-plus-overlay, and the suite caught it. The comment claiming the cap upheld "exactly one task at a time" was wrong twice over and is corrected in place: two paths already bypassed the semaphore, and `run_task_now(force=True)` neither checks nor adds `_executing`, so a forced trigger can overlap a task with itself. That is what `force` means; it is now written down.
- [x] **P6-09** Rewrite the todo "solve with an agent" button to enqueue instead of firing an unbounded raw stream. **Click ten todos and ten agent loops run at once**, with no progress and no cancel. — **done:** both todo agent-solve entry points enqueue through a bounded one-at-a-time queue with visible position, live status and a real server-side stop. Baseline reproduced before the fix: ten clicks, **ten concurrent streams**, no progress and no cancel.
- [x] **P6-10** Expose `crew_member_id` in the task create/update schemas and the `manage_tasks` tool. It is read-only today and honoured by the executor — **this one field closes the roadmap's "todos assignable to an agent from the UI" item at the API layer.** — **done:** `crew_member_id` exposed in the task create/update schemas and in `manage_tasks`. **It shipped half-wired and refutation caught it:** the tool schema advertised the field while `src/tools/system.py` had never heard of it, so the model would accept the argument, report the task assigned, and the value would be discarded — the model confidently telling a user their task runs as Research Bot when it does not. Now resolved through an owner-scoped lookup mirroring the route layer's, because the executor runs the task with that crew member's persona, model, endpoint and tool allowlist. `tests/test_manage_tasks_crew_member.py` (6 tests) pins the round trip, the cross-owner refusal, and the schema-versus-executor agreement.
- [ ] **P6-11** **Build the docked plan window.** Three prompt strings tell the model it exists and a code comment claims it renders. **Nothing has ever rendered it** — mid-execution `update_plan` writes to browser storage with zero visible effect, and the prompt is telling the model something false about its own interface. Structured steps with per-step status, bound tool, effect, elapsed and result.
  **The window is built and live — four of the five per-step fields ship — but `effect` does
  not, so this row stays open** (`AGENTS.md`: a partly done task stays open with a note saying
  what is left). `static/js/planWindow.js` renders the approved checklist docked, updates on
  `plan_update`, and survives a reload; **the four prompt strings that have been promising this
  window are now true.** What is left: `effect` is the 13-value `ToolEffect` taxonomy at
  `src/tool_capabilities.py:21-34`, and it is **not on the SSE wire** — neither `tool_start`
  (`src/agent_loop.py:5830`) nor `tool_output` (`:6056`) carries it. Resolved effect strings *do*
  already reach the frontend on the approval `action` payload (`chatRenderer.js:2594`), so the
  field exists; it just does not travel on the tool events. **`P7-06` owns emitting it** — it already needs the taxonomy to rank approval prompts, and
  saying so on that row is what this handoff was missing.
  **Two `breaks-users` defects were found by refutation and are fixed:** `update_plan` — the tool
  this window exists to listen to, and the one the model is *ordered* to call after every step —
  arrived wrapped in the same `tool_start`/`tool_output` pair as real work and overwrote each
  step's bound tool, deleted its result, rendered the raw plan JSON as the target chip and put a
  phantom result on the step that had not started; and approving one plan approved every later
  plan on that browser, because a new plan reset neither the approval nor the per-step history it
  inherited by ordinal. Both closed and verified by driving the live module against the real SSE
  ordering.
- [x] **P6-12** Give plan mode a real entry control. The toggle button resolves to nothing — the element does not exist; entry is Tab-in-composer or a mobile swipe, and the status pill can only turn it **off**. Its CSS is written and dead. **Do not use the three-up mode toggle** — it belongs to the model-serving panel. — **done:** plan mode has a labelled **Plan** button in the composer toolbar (`static/index.html:1209`) that toggles **both** directions, folding into the overflow menu on narrow widths. It is not the three-up mode toggle, which belongs to the model-serving panel. The `.plan-mode-btn` CSS that had been dead since it was written is now live — and its `.active` rule needed a `var(--red)` fallback, because bare `var(--accent)` is undefined until `P1-01` runs and the whole declaration was invalid, leaving on and off visually identical. A 2px vertical offset inherited from the dead rule was removed once the element was real enough to see it.
- [x] **P6-13** Add a step model with ids. A plan is an opaque markdown string everywhere — storage, form field, prompt, tool argument — and progress is computed by counting ticked boxes in that string. `Depends:` P6-11. — **done:** steps carry stable ids derived from the markdown — FNV-1a of the normalised step text plus an occurrence ordinal — so status, bound tool, elapsed and result attach to something that survives every `update_plan`. **`src/tool_schemas.py` was deliberately not touched:** its schema tells the model to send the complete checklist every time, and quietly teaching it a different wire format would have made the prompt lie a second time. Ticking a box does not change a step's text, so the id holds.
- [x] **P6-14** **Let planning mode ask a question.** The clarifying-question tool is absent from the read-only allowlist, so the gate blocks it. A planning mode that cannot ask what you meant is planning blind. — **done:** `ask_user` added to `PLAN_MODE_READONLY_TOOLS` (24 → 25), and `PLAN_MODE_DIRECTIVE` now tells the model the tool is there and to prefer asking over guessing — refutation caught that half missing, and an allowlist entry the prompt never mentions is a tool the model does not know it has. *(Premise mechanism corrected: the gate did not reject the call. `_assemble_prompt` computes `included = tool_names - disabled`, so the tool was stripped from the prompt entirely — plan mode was mute, not half-wired-and-lying.)*
- [x] **P6-15** **Pass the plan to the verifier.** It judges against the last user message, which during plan execution is literally the string *"Execute the approved plan"* — naming no deliverables. **The verifier is blind for the entire run.** One line. — **done:** the verifier now judges plan-execution turns against the approved checklist instead of the bare trigger string. *(The roadmap's claimed cross-batch seam did not exist: `chat.js` has posted `approved_plan` since before this phase, and `chat.js:961` is the trigger, not the payload. `P6-15` was self-contained in `src/agent_loop.py` after all.)*
- [x] **P6-16** Guard the narrating-without-acting supervisor against plan mode, where narrating **is** the job. One line. — **done:** the narrating-without-acting supervisor is exempt in plan mode, where describing un-taken actions is the job. **The code was right and the reasoning under it was false** — it justified the exemption with "every mutating tool is denied anyway", but plan mode is an *allowlist* with 25 read-only tools enabled and a directive that orders their use, so the nudge was not harmless-because-blocked, it was harmful because it pushed the model from planning into acting on tools that work. Corrected in place, because anyone re-deriving the decision from that sentence would have reached the wrong answer.
- [x] **P6-17** Render the agent's own todo list. A structured todo tool exists, persists to disk, is instructed for multi-step work, and **has no renderer** — it surfaces only as raw tool output text. — **done:** `todowrite` renders as a real checklist card instead of a raw JSON blob, on the live path, the reload path **and compare mode** — that third one was a second live door onto the same defect, found by refutation, the same shape as `P6-01` in wave 1. Four more defects came out of that review and are fixed: N repeated calls no longer stack N always-visible contradictory lists (superseded cards keep their header and lose their rows — `Law 1`, nothing deleted); a cleared list (`{"todos": []}`, a *successful* call) no longer falls back to raw JSON; the dashed in-progress box now actually draws, having lost a specificity contest to `li.task-item .task-check`; and an uppercase `[X]` marker is accepted rather than guarded against by a branch the regex made unreachable.

---

# P7 · Trust ladder & control plane
*Area: `trust` · Depends: P4*

The approval store is better than anything that would replace it. Do not rebuild it.

- [ ] **P7-01** **Stop the mode toggle lying.** A keyword regex of **58 alternations** — including *change, update, review, test, run, build, source, system, device, app* — silently promotes Chat to Agent, and **33 lines later** a single line **overwrites the user's own shell toggle to true**. *(Re-parsed 2026-08-27 from the alternation group at `chat.js:1884`.)* The backend escalates again on tool intent, search and web intent, computes an escalation flag, and never sends it. `Depends:` P4-18.
- [ ] **P7-02** Stop the model raising its own trust level — it can currently flip the mode toggle through a UI-control event with no confirmation.
- [ ] **P7-03** Add rung **"ask every time"**. Does not exist: the gate is conditional on untrusted content having entered, so a clean session never prompts. Change the gate condition from *taint seen* to *taint seen **or** the current rung requires confirmation*. **Reuse `PendingToolApproval` unchanged.**
- [ ] **P7-04** Add rung **"allow-listed"** — a rule store mapping tool + argument pattern to auto-allow, consulted before the blocked-effect check. Does not exist.
- [x] **P7-05** Record the correction in the UI: **Auto-Pilot is already the default** for every untainted conversation. — **SUPERSEDED (verified 2026-08-27) — not independently actionable.** There is no ladder UI to record it in; this is an acceptance criterion, not a task, and left on its own it is a row nobody can ever honestly tick. **Re-filed as acceptance criteria on `P7-03` and `P7-04`**, citing `design/pantheon-v10.html:1721-1727`: whatever those two build must show Auto-Pilot as the existing default with the ladder added below it, never above.
- [ ] **P7-06** Rank prompts by effect. A destructive action and a UI side effect produce an identical card. The 13-value taxonomy (`ToolEffect`, `src/tool_capabilities.py`) is written and used to rank nothing. **This row owns putting `effect` on the SSE wire, and that ownership is stated here because it was previously stated nowhere** — `tool_start` and `tool_output` carry no `effect` key, and two independent auditors reading the same handoff assigned the job to two different phases. It is one field on two emits. **Landing it unblocks `P6-11`**, whose plan window is built and open on exactly this: four of its five per-step fields ship and `effect` is the fifth.
- [ ] **P7-07** Send only the effects that actually **tripped** the gate, not all of them — and surface the unrecognised-tool case, which is the riskiest and currently invisible.
- [ ] **P7-08** **Surface the taint trail.** The security context builds a complete list of which tools introduced untrusted content into a run, and it is read **nowhere** — server or client. Built in memory and thrown away.
- [ ] **P7-09** Grant inspector — once a session-wide grant is given, nothing lists it and nothing revokes it.
- [ ] **P7-10** Surface run limits at the moment of decision. "How far can it run unattended" sits in a settings tab, invisible when you choose. `Depends:` P4-23.
- [~] **P7-11** Real file export — Markdown, JSON, HTML download. **Premise corrected 2026-08-27.** **The export already exists.** `GET /api/session/{sid}/export` serves md, txt, json and html as attachments (`session_routes.py:804`) — it is simply unreachable except by typing `/export`, so the work is a UI entry point, not a backend. The PDF observation stands. **The approval-trail half is blocked and cannot be built:** approvals are held in memory with a 600-second TTL and are never persisted, so there is no trail to export. `Blocked:` persist the approval trail first — file that under `P4-25`, which is already the row that owns extending what persists.

---

# P8 · The Workshop
*Area: `skills`, `automations`, `mcp` · Depends: P1*

Three authoring surfaces over three engines that already run.

**This is the largest phase in the programme — 48 rows — and it builds the three steepest
surfaces in the product.** It is therefore the phase where `Law 15` bites hardest, and until
2026-08-28 it had no gate at all. `P8-02` already diagnoses a live `Law 15` failure *inside* the
phase: four skill fields the API supports, reachable only by someone who already knows the
SKILL.md frontmatter format. That is the pattern to avoid, found in the phase's own second row.

**`Law 15` applies to every row in this phase.** It draws surface a person has to operate, and the law exists because the owner stopped using a competitor's *more advanced* version of this product for one reason: *"There's no tutorials and the learning curve is too steep for the little amount of time I have."* A row here is not done because the feature works — it is done when someone who has not read this tracker can find it, tell what state it is in, and use it without being told how. Put that in the row's `Verify:` line, in those terms.


### Skill Crafter
- [x] **P8-01** **Add the five phantom inputs** — `#new-skill-name`, `-description`, `-when`, `-procedure`, `-category`. The handler already reads them, they are in the clear-on-success list, and one has an Enter binding. **Zero JavaScript change.** — **done:** wiring run 01. All five are at `static/index.html:389/393/397/401/405`, read at `skills.js:1935-1944` and cleared at `:1970-1972`. Zero JavaScript changed, as predicted. Unblocks `P9-06`. (verified 2026-08-27)
- [ ] **P8-00** **Legibility is this phase's acceptance criterion, and it is checkable.** Not a
  build row — a gate on the other 47. The Workshop is where a person authors a skill, wires an
  automation and creates an MCP server, and it is the part of the product most likely to be
  abandoned for the reason the owner abandoned a competitor's. **Every `P8` row carries a
  `Verify:` line naming what a first-time user can do unaided.** `Verify:` for this row — someone
  who has never opened the Workshop creates one working skill, end to end, without reading the
  source, the tracker, or a tutorial that does not exist yet. If they cannot, the phase is not
  finished however many rows are ticked.
- [ ] **P8-02** Add pitfalls, verification, platforms and required-toolsets inputs. **Premise corrected 2026-08-27.** All four are supported by the API and **all four are reachable** — through the raw SKILL.md card editor at `skills.js:1034`, where you hand-write the frontmatter. So this is not a `Law 13` wiring gap; it is a **`Law 15` failure**: the capability exists and only someone who already knows the file format can use it. That changes the deliverable. Do not build a second write path — add the four fields to the form that already posts to the same API, so the raw editor stays the power-user route rather than the only route.
- [ ] **P8-03** Relabel "draft". A draft is excluded from the catalogue the model browses and **still keyword-injected** when it matches — "uncatalogued", not "inactive".
- [ ] **P8-04** Fix the confidence-slider trap: maximum position stores **zero**, labelled "All", which disables the gate entirely. Dragging right is "let everything in", not "only perfect skills".
- [ ] **P8-05** Surface the hidden coupling: turning auto-approve off sets the injection floor to 2.0, silently making injection published-only.
- [ ] **P8-06** **Prompt preview** — call `GET /api/skills/index`, which exists to answer exactly this and **no frontend file has ever called**. Extract the injection renderer into a shared function so the preview is the truth, not a re-implementation.
- [ ] **P8-07** Show what the preview reveals: **verification and body text are never injected.** They surface only through an on-demand view action.
- [ ] **P8-08** Wire the test's `task` field — the endpoint has accepted a user task all along and the UI has never sent one. One textarea.
- [~] **P8-09** **Before/after behaviour diff.** The runner is parameterised on arbitrary markdown *and* an arbitrary task and never reads from disk — call it twice with old and new against the same task. — **BLOCKED (2026-08-27), and this one bites on the first run.** `_run_skill_test_once` **destructively denies a pending approval when it hits a gate**, so calling it twice — which is the entire idea — burns two approvals and the second half of the diff runs against a state the first half changed. `Depends:` P8-08, **`Blocked:` P8-10** — the runner needs to be non-destructive before a before/after diff means anything.
- [ ] **P8-10** **Versioning.** Every write overwrites in place and the audit rewrites destructively with no copy kept; the version field is decorative and never bumped. A skill is a *directory* — a `versions/` sibling costs one line in the writer, and the rewrite path still holds the old markdown in a local when it writes the new one.
- [ ] **P8-11** Rollback from a version. `Depends:` P8-10.
- [ ] **P8-12** Pre-save lint — the necessity and retrieval-precision judges are pure functions of `(skill, siblings)`, already run nightly, callable with no refactor.
- [ ] **P8-13** "Improve this draft" — the existing rewrite prompt with a synthetic verdict, a trick the audit itself already uses to force a metadata-only fix.
- [ ] **P8-14** "Draft from my last session" — retarget the teacher's skill-from-trace prompt, which already emits the full modern schema, from a failure trace to a user description.
- [ ] **P8-15** Surface duplicate overlap at authoring time. Similarity is already computed client-side for a badge and server-side at audit — neither runs when you type. Note hand-written skills post a source value that **exempts them from creation-time dedup**.
- [ ] **P8-16** Single-skill export — `read_skill_md` plus a directory walk, ~20 lines. Unlocks share, backup and rollback-by-hand.
- [ ] **P8-17** Fix the extractor's output schema — it still writes the old shape and never populates pitfalls, verification, category or when-to-use. Everything it makes is structurally impoverished relative to what the schema supports.
- [ ] **P8-18** Say that injecting a skill raises the security posture — skills arrive as untrusted context, which arms the approval gate. Correct behaviour, completely invisible, and the reason a skill test can pause mid-run.
- [ ] **P8-19** Add an mtime-keyed cache to the skills manager before any live-preview UI. Every read is an `os.walk` parsing every file, on every request that injects skills. `Depends:` P8-06.
- [ ] **P8-20** *(Stretch)* Vector-index skills. Retrieval is Jaccard overlap against the last user message only — no embeddings, no conversation context. **Memories are already vector-indexed; skills are not.** Same template, unapplied.
- [ ] **P8-21** *(Stretch)* Budget the index. It costs ~15 tokens per published skill on **every single request** and participates in no budget. Also: the usage counter records *retrievals*, not successes, so "most-used" measures keyword luck.

### Automations
- [ ] **P8-22** Node palette endpoint — merge the three `/meta/*` routes, move the client-side category/icon taxonomy server-side, emit param schemas and a `model_backed` flag (currently maintained twice: once to gate the semaphore, once to draw a badge). **A defect this row inherits and nobody had recorded** (found 2026-08-27, AST-verified): `BUILTIN_ACTIONS` holds **18** entries and `BUILTIN_ACTION_INFO` holds **16**, so `run_local` and `cookbook_serve` exist and are **never offered by `/meta/actions`**. Two working actions are invisible to the palette. Reconcile the pair in the same commit — that is the merge's whole point (`Law 7`).
- [ ] **P8-23** **Give triggers payloads.** The event bus takes a name and an owner — a "document created" trigger cannot say *which* document. The webhook route has **no request parameter**: body, query and headers are read by nobody. It is a doorbell. **Highest-leverage change in Automations; everything downstream depends on it.** Do not change the webhook URL shape — it is CI-pinned.
- [ ] **P8-24** Widen the node output contract from `(text, success)` to `(payload, status)` with a back-compat adapter for the 18 existing actions. The no-op and defer-with-backoff signals already encode skip and retry — generalise them.
- [~] **P8-25** **Write `TaskRun.steps`** — declared, never written. A run records one result string for the whole task. Filling it upgrades the shipped activity view instantly with no new UI. — **BLOCKED (2026-08-27): "migrated" is false.** There is **no `ALTER TABLE task_runs ADD COLUMN steps` anywhere in the tree**, so the column exists in the model and not in any database that was created before it. Writing to it raises `OperationalError` on every upgraded install — a fresh dev box would pass and every real deployment would break. **Unblock by:** writing the migration first. It also blocks `P8-34`.
- [ ] **P8-26** Add the graph document. One nullable successor today; the cycle check doubles as a **silent depth cap of ten**. Project the existing successor as a single edge on read.
- [ ] **P8-27** Run-scoped execution identity — the current one is keyed by task, so a task cannot be in flight twice. Required before fan-out. `Depends:` P8-26.
- [ ] **P8-28** Branch node — the only conditional in the engine is `status == "success"`. `Depends:` P8-26.
- [ ] **P8-29** Data mapping between nodes. `Depends:` P8-23, P8-24.
- [ ] **P8-30** Collapse the parallel event catalogues into one registry, and **add `document_updated`** — it is fired in production and appears in no catalogue, so nothing can trigger on it. **Re-measured 2026-08-27: not three catalogues but two enumerated ones plus five hardcoded strings** (`task_routes.py:1035-1043`, `tool_schemas.py:583`, `task_scheduler.py:241-251`). The five loose strings are the ones a merge of "three catalogues" would miss entirely.
- [ ] **P8-31** Default a user-built automation's event count to 1. The UI defaults to 5; anyone arriving from a workflow tool expects every event.
- [ ] **P8-32** Per-task timezone, retries, and a per-task timeout — none exist. Timezone today comes only via a crew member.
- [ ] **P8-33** A dry run that is actually dry. "Run now" is a real run with real side effects — no mocking, no pinned input, no per-node execution.
- [ ] **P8-34** The canvas, last, against a stable API. **Ship a Mermaid rendering of a workflow first** — it is already vendored and wired, works today, and needs no graph library. `Depends:` P8-22, P8-25, P8-26.

### MCP Creator
- [ ] **P8-35** **An update endpoint — the structural blocker.** The only mutation is an enable/disable toggle; editing a command means delete-and-recreate, which mints a new id and **orphans every stored `mcp__<id>__<tool>` reference**, including the server's own disabled-tool list and any scheduled task pointing at one. Iterate-and-refine is impossible until this exists.
- [ ] **P8-36** Test-call endpoint — no route invokes a tool; the manager's call method is public with a normalised envelope. ~15 lines behind an admin check.
- [ ] **P8-37** **Add a timeout to the MCP call path — there is none.** A hung tool hangs the agent turn indefinitely. Do this in the same change as P8-36.
- [ ] **P8-38** Keep the handshake. The initialize result is discarded at exactly three connect sites; it carries server name and version, protocol version, advertised capabilities and the server's own instructions, and **nothing in the app records any of it.** One line each.
- [ ] **P8-39** **Encrypt server env vars.** Every other secret in the schema is encrypted at rest; this one is plain text, and it is where the tokens live. The CLI already redacts on read behind a reveal flag. Storage migration only — no wire or JSON shape changes. **Do this before a Creator multiplies the rows holding them.**
- [ ] **P8-40** Capture `annotations` on the HTTP transport — stdio and SSE both do, HTTP does not, so a remote server gets no plan-mode read-only credit however it advertises itself.
- [ ] **P8-41** Fix the **two** stale comments claiming MCP is dropped in plan mode *(re-counted 2026-08-27 by multiline grep across `src/`, `routes/`, `core/`, `services/`, `static/` and `docs/`)*. It is not — read-only tools are kept via annotations with a fail-closed verb heuristic.
- [ ] **P8-42** Fix the empty-env trap: an empty env dict yields `None`, so the SDK substitutes a minimal environment. **Premise corrected 2026-08-27.** **`PATH` and `HOME` are not the casualties** — both are in `DEFAULT_INHERITED_ENV_VARS` and survive. What vanishes is `PYTHONPATH`, `NODE_PATH`, the npm cache location and every proxy variable, and **only when the env dict is empty**. That is a narrower trap and a much harder one to diagnose: a server that resolves its interpreter fine and then cannot find its own packages, or cannot reach the network from behind a corporate proxy. `Verify:` a generated server with an empty env dict inherits the parent's `PYTHONPATH` and proxy settings.
- [ ] **P8-43** Let `builtin_browser` auto-reconnect — the reconnect helper hard-returns false for anything outside a four-entry map, despite the browser server counting as built-in. A crashed Playwright server stays dead until a manual reconnect.
- [ ] **P8-44** Server-id validation. One `split("__", 2)` is the sole parse of the namespaced name; **an id containing `__` routes the call to the wrong server.** Unreachable today because ids are uuid4-derived — the moment a Creator lets people name servers, this field holds the invariant.
- [~] **P8-45** Surface the **15**-entry preset catalogue (14 with setup walkthroughs) currently sitting in **420** lines of unreachable code. Its two entry points look up DOM ids no template has ever rendered. *(Re-measured 2026-08-27 by balanced-bracket parse: 15 top-level objects at `admin.js:1793-1859`. A naive `{ name:` regex returns 23 — that is exactly how the wrong figure was produced, and it is worth recording because the same regex habit produced several others in this pass.)* `Depends:` P2-20. **`Blocked:` `Law 14` — `settings.js:5000` already ships a working MCP form.** Decide whether these presets feed *that* form before building a second surface for them.
- [ ] **P8-46** Replace the single-line JSON inputs — a parse failure is caught and **silently discarded**, posting empty args and env, after which the server fails to connect for a reason nothing explains.
- [ ] **P8-47** Scaffold generator, writing to the **data volume** — the source tree is baked into the image with no bind mount, so generated servers cannot be built-ins and must register as ordinary rows with an absolute path. **That path is denied on the agent's registration path by design.** Author here; register through the admin route. **Do not weaken the command validation** — it closes a reported RCE and is pinned by 10 tests.
- [ ] **P8-48** Tool schema editor + `readOnlyHint` / `destructiveHint` annotation UI. The schema is already carried end-to-end and nothing edits it; `manage_mcp list_tools` drops it entirely, so the LLM cannot see a tool's parameters through its own tool.

---

# P9 · Feature surfaces
*Area: `surfaces` · Depends: P5*

**`Law 15` applies to every row in this phase.** It draws surface a person has to operate, and the law exists because the owner stopped using a competitor's *more advanced* version of this product for one reason: *"There's no tutorials and the learning curve is too steep for the little amount of time I have."* A row here is not done because the feature works — it is done when someone who has not read this tracker can find it, tell what state it is in, and use it without being told how. Put that in the row's `Verify:` line, in those terms.

### Theme expansion — additive, no dependency on anything
- [ ] **P9-15** **New themes.** The system takes them cleanly: five colours plus an optional
  `advanced` block, one entry in `THEMES`, one line in `THEME_DEFAULT_PATTERN`. Nothing else
  changes. `Depends:` P1-01, so a new theme can ship its own `accent` from day one.
- [ ] **P9-16** **ASCII-art backgrounds as a ninth pattern class.** Subtle, per-theme, behind
  everything — `terminal` wants something very different from `ume`. Slots into the existing
  machinery: one entry in `_BG_CLASSES`, one in `_CANVAS_PATTERNS`, one init function beside the
  seven that already exist, and `--bg-effect-color/intensity/size` come free. It can be a canvas
  animator like the other seven, or CSS-only like `dots` if the art is static. **Read
  `FORBIDDEN.md` § The theme system first** — this extends that machinery, it does not replace it.
  `Depends:` nothing. `Verify:` selecting a theme with an ASCII pattern renders it behind the app
  at the configured intensity, and `prefers-reduced-motion` stops any animation without hiding
  the art.

- [ ] **P9-01** **Command palette**, framed as extending the existing search rather than a parallel component. Every data source is already a registry: slash commands, settings panels with keywords, the modal auto-wire map, the route table. **`#search-overlay`, `#search-input` and `#search-results` must stay in the DOM** — five call sites including the rail button and `/find`.
- [ ] **P9-02** Render the settings nav from its own registry. Two sources of truth for one information architecture; the registry was built for this and is consumed only by search. **Keep the class name and data attribute identical** — four modules query them. There is also a `getSettingsRegistryIssues()` self-check that diffs registry against DOM — run it while you work.
- [ ] **P9-03** Unify the library. Chats, Documents, Research and Archive are already tabs of one modal; make it *the* library with Gallery and Email as facets, and settle the three names for one thing (`rail-archive` labelled "Library", `rail-documents` labelled "Docs", modal id `doclib`).
- [ ] **P9-04** Consolidate email settings. **Premise corrected 2026-08-27.** **The consolidation already landed** at `static/index.html:2100-2124`, so this is no longer the highest-priority IA fix — or an IA fix at all. What remains is a **deletion**: two dead forms, `eaf-*` and `set-email-*`. Under `Law 1` a deletion is marked, reviewed and justified before it runs, so treat this as a delete row and not a build row. **Keep compose-in-document-editor** — it is why AI drafting works.
- [ ] **P9-05** Full views for Calendar and Compare. **Premise corrected 2026-08-27.** **Both views already exist.** The month grid and the N-way comparison are built; what is missing is the full-view presentation, not the feature. And the Compare half of this row **contradicts its own protected constraint**: Compare deliberately shows and hides the original container's children rather than replacing markup (`compare/index.js:328-336`) precisely so the input-bar and mode-toggle listeners survive — putting it inside a ~780px draggable box is the rework that constraint forbids. **Rewrite this as Calendar-only, or state how Compare gets a full view without replacing the container.** As written it asks for the one thing `FORBIDDEN.md` protects.
- [ ] **P9-06** Promote Skills out of the Brain modal — different object, different lifecycle (draft → audit → publish). `Depends:` P8-01.
- [x] **P9-15b** **Freeform answers on the ask-user card.** When the model offers choices, a
  person should be able to type something that is not on the list. `.ask-user-card` is in
  `FORBIDDEN.md` Part 1 — extend it, do not rebuild it. — **done:** `chatRenderer.js:2516-2546`
  adds the `.ask-user-other` input, its send button and an Enter binding, appended at `:2546` on
  non-approval cards only; CSS at `style.css:40940-40957`. Live on all three render paths. The
  card was extended in place, never rebuilt. Withheld from `tool_approval` deliberately — a
  freeform box on an approval card is a different and worse control. (verified 2026-08-27)
- [ ] **P9-15c** **Hybrid chat search — keyword and meaning in one box.** **Premise corrected 2026-08-27.** **This is
  backwards, and the correction makes the row bigger, not smaller.** The *keyword* half is what
  ships: FTS5 plus `LIKE` at `session_search.py:300`. The *vector* half does not exist — there
  are three Chroma collections and **not one of them indexes chat messages**. So "find the
  message where I pasted that error" already works, and the semantic query is the missing one.
  Scope accordingly: a chat-message embedding lane, an indexing hook on write, **and a backfill
  over existing sessions.** That is a `P13`-sized piece of work sitting on a `P9` line — decide
  whether it moves before anyone starts.
- [ ] **P9-07** **Empty states.** **Premise corrected 2026-08-27.** **"Not one exists anywhere" is wrong by about fifty-four.** There are ~54 empty-state sites across 20 class names, a shared helper at `ui.js:833`, and `calendar.js:827-855` is a complete, well-built example worth copying. The cookbook clause is false too — `cookbookRunning.js:2411` already renders real output and a diagnosis, not "crashed". **This is a consistency task, not a greenfield one:** pick the `ui.js:833` helper as the one shape, then bring the 20 class names onto it. `Law 14` — do not author a twenty-first.
- [ ] **P9-08** Honest error messages, same lane. `Depends:` P9-07.
- [ ] **P9-09** Provenance on everything the model produced. **Premise corrected 2026-08-27.** **Four of the six already have it** — memories (`memory.js:776`), skills (`skills.js:208`), generated images (`gallery.js:1286/1481`) and research reports (`research/panel.js:897`). Only **tidy results and calendar parses** lack it, and "the formatter already exists" is false: the four that work each format their own. So the row is two additions plus a genuine `Law 14` opportunity — **extract one formatter from the four existing ones first**, then use it for the two that are missing. Doing the two additions without that leaves six implementations of the same idea.
- [ ] **P9-10** Preview before destructive AI operations. **Chat tidy deletes sessions *and* re-folders them with no preview at all**; memory tidy has an animation, not a reviewable diff. Calendar has a real undo stack and is the only surface that does — proof it is solvable here.
- [ ] **P9-11** Make background work visible with its window closed — skills audit, research jobs, cookbook downloads, memory tidy and email sync all report into windows the user has closed. **Extend the minimized-dock chips**, which already carry per-window status; email writes an unread label onto its own.
- [ ] **P9-12** Fix "non-passing" in the skills bulk delete — it currently catches **never-audited** skills, so a brand-new hand-written skill counts as failing. Add an undo path. `Depends:` P8-10.
- [ ] **P9-13** Surface the theme zone highlighter — hovering a colour picker outlines the element it controls on the live page behind the modal. **The best explainability feature in the app**, with no label, legend or hint that it exists. The map is keyed by picker id, so extending it is a data edit.
- [ ] **P9-14** Bulk-operation reporting. **Premise corrected 2026-08-27.** **Both halves are wrong.** The selection
  count *is* rendered, in four live bulk bars. And three document operations plus one gallery
  operation already report done and failed counts. The one-row-at-a-time loop the audit found
  is at `sessions.js:3283-3312`, inside `#library-modal` — **a surface that is unreachable**, so
  fixing it changes nothing a user can see. **Delete-or-justify row:** either delete the dead
  library-modal loop under `Law 1`, or name a bulk surface that genuinely lacks reporting. Do
  not implement it as written.

---

# P10 · Accessibility & release
*Area: `a11y`, `release` · Depends: P1, P5*

The accessibility pass is the upstream roadmap's own item, unclaimed, and historically
the only lane through which the theme file gets touched.

- [ ] **P10-01** One focus ring through `:focus-visible`. **97 `outline:none` suppressions — plus 2 `outline:0`, so 99 in total** (re-measured 2026-08-27; the 97 confirmed exactly, and the two stragglers are the ones a find-and-replace on `outline:none` leaves behind) — against 35 `:focus-visible` rules and six competing ring styles. The a11y shim's own header notes the ring already exists and never fired because rows were never focusable. Most suppressions can then be deleted.
- [ ] **P10-02** Author sidebar rows as real buttons. **Keep `.list-item`** — the a11y shim and the drag-sort module both query it, and rows *contain* nested buttons, which is exactly why the shim declines `role="button"` on them. **Change the tag, not the class.**
- [ ] **P10-03** Make the resize handles visible and keyboard-reachable. **Premise corrected 2026-08-27.** **There are three, not two** — and `#settings-sidebar-resize-handle` is **already done**. That makes it the template: copy its treatment onto the other two rather than inventing one. They are mouse-only and invisible because their entire treatment routes through the accent token. `Depends:` P1-01.
- [ ] **P10-04** Contrast audit across all 16 themes with the guard from P1-09 enforcing it. `Depends:` P1-09.
- [ ] **P10-05** Verify the reduced-motion guard covers all **160** keyframes and the 7 canvas animators — **including the 12 that `slashCommands.js` injects into `document.head` at runtime**, which a CSS-only audit will not see. `Depends:` P1-12.
- [ ] **P10-06** Keyboard navigation pass over the rail, the sidebar, the composer, the window system and the Workshop.
- [ ] **P10-07** Give the loader a stage line so boot is not silent, move it off `innerHTML`-per-frame, and add a reduced-motion guard. **Keep the wave.**
- [ ] **P10-08** Zoom compensation for modals. **Premise corrected 2026-08-27.** **This is backwards.** The generic rule at `style.css:181` already covers every `.modal-content`, so a new modal is compensated by default and needs no line of its own. The five per-modal `ui-scale-125` rules are **exceptions to that rule**, not the pattern to follow. Rewritten deliverable: find out why each of the five needs an override, fold back the ones that do not, and document the remainder. As written this row taught every future contributor the wrong habit.
- [ ] **P10-09** Rebuild, redeploy, bump the cache-buster, verify in-container imports. **`static/` has no bind mount.**
- [ ] **P10-10** Full regression: `pytest -q`, `py_compile` across app/routes/src, `node --check` across every touched module, and a manual pass over every surface in the mockup.
- [ ] **P10-11** Run the `SECURITY.md` fork checklist before the first public push — `git status --short`, the ignore check, and the secret grep.
- [ ] **P10-12** Write the release notes. Lead with the Odysseus credit. Enumerate the breaking renames: env vars, storage keys, vector collections, cookie, CLI scripts, systemd unit, bundle id.

---

# P11 · Identity & access
*Area: `identity` · Depends: nothing · Blocks: P12's per-role limits*

**Why this is a phase and not a task.** Identity is one JSON file: bcrypt hashes and pyotp
secrets in `auth.json`, a single `is_admin` boolean, and a privilege dict. No roles, no
groups, no external identity.

Two things the first pass of this section got wrong, corrected by reading `core/auth.py`:

1. **The privileges are declared, not grep-discovered.** `DEFAULT_PRIVILEGES` at
   `core/auth.py:24` is a real registry. Better still, **it already holds quota primitives** —
   `max_messages_per_day` (int), `allowed_models` (list), `allowed_models_restricted`, and a
   `block_all_models` sentinel that exists because an empty allowlist was ambiguous. Seven
   `can_*` booleans, four non-boolean policy values. **This is already a control plane; it is
   just under-populated.** `P12` should extend this dict rather than build a parallel system,
   and a role is then a named overlay on it.
2. **Authorization is effectively one bit, applied 103 times.** Re-measured 2026-08-27 with
   the scope stated: non-test `.py`, excluding the definition and its imports. `require_admin`
   has **103** call sites against `require_privilege`'s **16**. Ownership scoping is healthier
   — `owner_filter` at **32** sites — so the data model already understands "whose row is
   this". What it does not understand is "what may this kind of person do". *(The old 84 / 17 /
   58 carried no scope and reproduces under none of six tried — `Law 5`. The ratio, which is
   the whole point of the paragraph, turned out worse rather than better.)*

The live defect: unknown privilege keys **fail open** — `privs.get(key, True)` at
`src/auth_helpers.py:172` — with the comment "the UI gates display-side", and `P2-18` proved
that UI gate does not work. A typo in a privilege key currently grants access.

None of this is wrong for one admin on a LAN. All of it is wrong the moment a second person
has an account.

- [ ] **P11-01** **Close the fail-open default.** Known keys default to denied; genuinely
  unknown keys stay permissive so a new key does not lock everyone out mid-deploy. **Premise corrected 2026-08-27.**
  **The registry already exists** — `DEFAULT_PRIVILEGES` in `core/auth.py:24-38` is it, with
  **11 keys** (AST-verified: 9 boolean, 1 integer, 1 list; the earlier 9 was a grep of the
  booleans only), and `set_privileges` already filters against it. So this is not a new
  registry: it is **a one-line guard at `src/auth_helpers.py:172`**, changing `privs.get(key,
  True)` to default known keys closed while leaving genuinely unknown ones open. That moves it
  from a design task to the cheapest security fix in the tracker. `Verify:` a typo'd key denies
  rather than grants, and adding a brand-new key to `DEFAULT_PRIVILEGES` does not lock out
  existing users mid-deploy.
- [ ] **P11-02** **Roles as named overlays on `DEFAULT_PRIVILEGES`.** Not a new system — the
  dict already carries booleans, an integer quota and a model allowlist. A role is a named set
  of overrides; a user gets a role and optional per-user overrides on top. Resolution order:
  built-in default → role → user. Keep `is_admin` as the superuser role rather than replacing
  it, because 103 call sites depend on it and rewriting them all at once is how this goes wrong.
- [ ] **P11-02b** **Audit every `require_admin` site against the role model.** **103** of them
  — scope: 83 direct `require_admin(` calls plus 20 `Depends(require_admin)`, non-test `.py`,
  excluding the definition and its imports. *(The line said 84 until 2026-08-28, which this
  phase's own preamble had already retired twice, thirty lines above. A map 19 gates short would
  have survived the entire refactor.)* Each is
  each is currently a binary answer to a question that should have three or four. Produce the
  mapping before changing any of them: which are genuinely superuser-only, which are
  "operator", which are "power user", which were `require_admin` because nothing finer existed.
- [ ] **P11-02c** **Resolve the `_ADMIN_TOOLS` name collision before touching either.**
  `src/tool_execution.py:322` defines an 11-name set that **blocks** non-admins, checked
  *before* the public blocklist and with a different error string. `src/agent_loop.py:2842`
  defines a different 15-name set with the **inverted** meaning — a force-include for prompts
  and schemas. Same name, opposite semantics, one grep away from a serious mistake during an
  RBAC refactor. Rename one.
- [ ] **P11-02d** **Audit the fifteen route files that make no auth call of their own.**
  `assistant` 6, `auth` 29, `chat` 8, `cleanup` 2, `compare` 5, `editor_draft` 5, `emoji` 1,
  `font` 1, `hwfit` 4, `prefs` 3, `search` 4, `signature` 3, `stt` 2, `tts` 3, `workspace` 2.
  Several are covered by `AuthMiddleware` and some are deliberately exempt — **this is a
  reconciliation task, not a list of holes.** The deliverable is a table: route, what actually
  gates it, and whether that is intended. Nothing here should be changed before that exists.
  **Premise corrected 2026-08-27.** **Two fixes.** First, the premise: **nine of the fifteen do make an auth call of
  their own** — `get_current_user` or `owner_filter` — and `chat_routes.py:338/367` performs a
  real admin check via `owner_is_admin_or_single_user`. Six files are the actual unknowns.
  Second, four lines of `P11-02`'s role paragraph had been **mis-merged onto the end of this
  row** and are now removed; they said nine privileges where there are eleven, and they made
  this reconciliation row read like a build row. `Law 7` — one source of truth per fact, and
  `P11-02` is the one for roles.
- [ ] **P11-03** **OIDC Authorization Code + PKCE against a discovery document.** BYO
  provider — Keycloak, Zitadel, Authentik, Authelia, or a hosted IdP. Discovery URL, client id,
  client secret, scopes. No provider-specific code.
- [ ] **P11-04** **Claim → role mapping.** Configurable: which claim carries groups, and which
  group maps to which Pantheon role. This is the piece that makes SSO useful rather than just
  a different login button.
- [ ] **P11-05** **Keep local auth alongside, not instead.** BYO means both — an OIDC outage
  must not lock the operator out of their own box. Local admin stays as a break-glass path.
- [ ] **P11-06** **JIT provisioning on first SSO login**, with a default role. SCIM is a
  later question and probably never for self-hosted.
- [ ] **P11-07** **Sessions that survive more than one process.** They are file-backed today
  (`Loaded N session(s) from disk`), which is fine for one container and wrong behind a load
  balancer. Decide before, not after, someone runs two replicas.
- [ ] **P11-08** **An auth audit log** — logins, role changes, privilege grants, failures.
  Feeds `D-05`'s telemetry table rather than inventing a second store.
- [ ] **P11-11** **Where an operator actually does any of this.** `P11-03` names four values
  someone must supply — discovery URL, client id, client secret, scopes — and gives them no
  home. `P11-04` calls the claim map "configurable" without saying where. `P11-02` never says
  how a role is created or assigned. **Left as-is, the whole phase lands as roles hand-edited
  in `auth.json` and a client secret pasted into a compose file** — which is `Law 13`'s unwired
  feature and `Law 15`'s steep curve at once, in the phase whose entire purpose is that a second
  person can use this. **Extend the admin panel that already ships** (`static/js/admin.js`, its
  `refreshAll` list, and `#adm-userList` in `static/index.html`) — a live per-user privilege
  editor is already there, which makes this `Law 14` rather than new construction. `Depends:`
  P11-02, P11-03. `Verify:` an admin creates a role, assigns it to a second user, and connects a
  self-hosted Keycloak realm — without editing `auth.json` and without restarting the server.
- [~] **P11-09** **Re-arm what single-user mode let us delete.** `DECISIONS.md`
  D-2026-08-26-01 deleted the upload type blocklist and named "a second user account" as the
  condition that voids it. This phase *is* that condition. Restore the check — with `.svg` in
  it this time — gated on multi-user being enabled, not unconditionally. **`Blocked:`
  (2026-08-27) two things, both real.** `tests/test_upload_multifile.py:297` and `:310`
  **actively pin the deletion**, so restoring the check turns the suite red on arrival — those
  assertions have to be rewritten in the same commit, deliberately, not discovered. And **there
  is no multi-user flag to gate on yet**; it arrives with `P11-02`'s roles. Restoring the check
  ungated would re-impose on a single-user LAN box exactly the restriction D-2026-08-26-01
  removed.
- [ ] **P11-10** **Admin-gate the built-in capability reads** if `P2-21` has not already. Any
  logged-in non-admin can currently read all 60 tool instruction blocks (AST-verified
  2026-08-27 — `TOOL_SECTIONS`, exactly 60). **`Blocked:` `P2-21`'s missing list loader.**
  `builtinSkills` is never assigned from any fetch, so flipping the flag today ships an empty
  section — a gate over nothing, which reads as done and is not.

---

# P12 · Limits & the control plane
*Area: `control-plane` · Depends: P11-02 for per-role, `D-05` for anything adaptive*

**The gap.** Every limit in Pantheon is a process-wide constant read from an environment
variable at import: eleven `PANTHEON_*_MAX_BYTES` caps, one 49-line `RateLimiter`, and a
handful of literals like the 24,000-character attachment budget. Nothing is per-user, nothing
is per-role, and nothing can be changed without a restart. An operator who wants to give one
team bigger uploads has no move except editing compose and rebuilding.

**The principle: a limit is policy, not a constant.** Settings already has the right shape —
a file-backed dict with `get_setting` / `set_setting` and a `DEFAULT_SETTINGS` merge — so this
is mostly moving values into a system that exists, then layering roles on top.

- [ ] **P12-01** **Move the ten byte caps into settings** *(re-measured 2026-08-27 — distinct
  `PANTHEON_*BYTES` env names in non-test Python: 7 in `upload_limits.py`, 1 backup, 1 TTS, 1
  lazy. Eleven was one too many, and knowing which ten they are is the row's actual first
  step)*, with the environment variable as
  an *override* rather than the only source. Order: role profile → instance setting → env →
  built-in default.
- [ ] **P12-02** **Limit profiles attached to roles.** Upload size, files per request, request
  rate, context budget, concurrent agent runs, model-serve permission.
- [ ] **P12-03** **Runtime-adjustable without a restart.** **8 of the 10 caps** are read at
  import today (re-measured 2026-08-27) — so this is a real refactor, not a settings row. The
  other two already re-read per call and are the pattern to copy rather than files to change:
  `get_chat_upload_max_bytes` re-reads on every call, and the TTS cap is read at instance init.
- [ ] **P12-04** **Context and attachment budgets become policy.** This is where `P2-08` and
  `P2-09` land properly. **Premise corrected 2026-08-27.** **There are more budgets than the line admits** — five
  live in `document_processor.py` alone, including a `.log`-only 10,000 branch nobody has
  mentioned, and **seven** across the codebase: the shared 24,000-char budget, the PDF's 15,000,
  the per-file 30,000, the `.log` 10,000, and the skill-injection count. All of them become a
  single coherent budget with a per-role ceiling — the ceiling is what stops a proven-window
  scale-up from handing someone twelve untrusted skill blocks. **`services/context_budget.py`
  already implements the shape this wants.** Extend it; do not author an eighth (`Law 14`).
- [ ] **P12-05** **Per-user and per-role rate limiting.** The current limiter is per-IP, which
  behind any reverse proxy is one bucket for everyone.
- [ ] **P12-05b** **The throttle *values* are still literals, and `P12-05` does not change
  that.** It changes the key the limiter buckets on. Measured 2026-08-28: `routes/auth_routes.py`
  builds three `RateLimiter`s with hardcoded `15/60`, `3/300` and `3/300`; `src/upload_handler.py`
  sets `self.upload_rate_limit = 60`, **shadowing the default of 5 declared in `src/config.py`** —
  reconcile those two before making either settable. None of the four is among `P12-01`'s ten byte
  caps, so after `P12-01`, `P12-03` and `P12-05` all land, **an operator still cannot change a
  throttle without a rebuild** — which is the thing the owner asked for by name: *"adding admin
  controls, such as throttling and such."* Also decide where the counters live:
  `src/rate_limiter.py` is 49 lines and in-memory, so per-user limits behind two replicas are two
  buckets. `Depends:` P12-01. `Verify:` an admin changes a login-attempt limit and the next
  attempt honours it, with no restart.
- [ ] **P12-06** **Reinstate upload concurrency as an admin control, not a constant.**
  `P2-10`'s recommendation to delete it assumed one user on a LAN. Under real infrastructure
  it becomes a per-role setting with the default off. **Premise corrected 2026-08-27.** **The false-positive is
  already fixed** — `upload_routes.py:285-291` (#1346) no longer fires on a normal multi-file
  drag, so the urgency is gone and the deletion argument with it. Two real defects remain and
  they are what this row now owns: **`3` is a hardcoded constant**, and **"concurrent" is
  implemented as a ten-second window**, which is a rate limit wearing the wrong name. Make the
  number a per-role setting and either make it mean concurrency or rename it.
- [ ] **P12-07** **An admin surface for all of it** — one panel, not eleven env vars in a
  compose file. Depends on `P2-20` landing the admin markup pattern first.
- [ ] **P12-09** **Make the context budget visible while you work, not in a settings tab.**
  What is consuming the window right now — system prompt, skills, retrieved memory, attachments,
  history — as a live breakdown at the composer. Nobody self-hosted does this well, and it turns
  every abstract limit in this phase into something a person can see themselves hitting.
  `Depends:` P12-04.
- [ ] **P12-10** **Auto-deny pending approvals on timeout rather than leaving them open.**
  The approval store already has a TTL; expiry and denial are not the same event. A prompt left
  hanging while nobody is at the keyboard should close as *denied*, and the timeout should be an
  operator setting. Prior art: PandaOS shipped exactly this after the same problem.
- [ ] **P12-08** **Show operators what is actually being consumed** before asking them to set
  a number. Blocked on `D-05` — you cannot tune a limit you cannot measure, and today token
  usage is stored as a running total with the time dimension discarded at write.

---

# P13 · The Brain
*Area: `brain` · Depends: nothing · Independent of everything else*

> ### The graph visual is cut. Decided 2026-08-26.
> **What matters is permanence, not a picture of it.** Long-term knowledge of projects that
> survives sessions, gets better rather than noisier, and can be trusted — that is the whole
> feature. The force-directed constellation is the part of a competitor's version that looked
> impressive and was the reason it went unused (`Law 15`).
>
> **Edges survive; the drawing does not.** A `supersedes` edge makes retrieval correct whether
> or not anyone ever looks at it, and a recorded `contradicts` is worth having even if it is
> only ever read by a query. Keep the data model. Drop the canvas, the node layout, the
> starburst and the confetti.
>
> The Brain surface becomes something a person can **read and search** — filter, sort, inspect,
> correct — not something they navigate by dragging.

**`Law 15` is this phase's acceptance criterion, and it is why the graph was cut.** The owner
stopped using a competitor's more advanced version of exactly this feature for one reason:
*"There's no tutorials and the learning curve is too steep for the little amount of time I
have."* Every row here is measured against a person who has never seen the page: can they find
what the agent remembers about a project, and correct something that is wrong, without being
taught how? `P13-07` and `P13-08` carry that as a `Verify:` line. *(Filed as row `P13-00` until
2026-08-28, which was the shape `P7-05` had already been superseded for — an acceptance
criterion filed as a task is one nobody can tick.)*

**What is actually there today.** *(Corrected 2026-08-27 — this paragraph named the wrong
store, and every task under it inherited the error.)* The **live store is `data/memory.json`**
(read at `src/memory.py:136`, atomically rewritten at `:275-278`). There is also a `memories` SQL table — `id, text, category, source,
owner, session_id, timestamp` behind a vector index — but it has **two non-test readers** and is
not where memory actually lives. **No confidence, no edges, no provenance beyond a one-word
`source`.** The correction is load-bearing and it makes the phase *smaller*: adding confidence
is **a JSON key and a default, not a schema migration**, and anyone who starts by writing an
`ALTER TABLE` is editing a store nothing reads. Four of the pieces this needs already exist and are
proven, which is why this is a smaller phase than it looks:

- **Confidence is already implemented — on the wrong half.** `services/memory/skill_extractor.py`
  scores every extracted skill 0..1 and drops anything under a `MIN_CONFIDENCE = 0.6` floor.
  The pattern works. Memories never got it.
- **`GET /memory/timeline`** already returns memories chronologically with their source
  session. That is half of "observable growth" already shipped.
- **`POST /memory/audit`** already runs an LLM dedup-and-consolidate pass and reports before
  and after counts. That is the consolidation step, unwired to any notion of confidence.
- **`POST /memory/import`** exists but takes a file upload and returns suggestions. Provider
  import is a new source feeding an existing pipe, not a new pipe.

**What genuinely does not exist: edges.** Re-measured 2026-08-27: `link|related|edge|graph`
across `services/memory/*.py` returns **6 raw hits and 0 relevant** — the earlier "one grep hit"
was itself a false positive. The finding is unchanged and stronger. That is the phase.

**Evidence from a shipped implementation.** A beta screenshot of PandaOS's *PandAtlas* — the
closest thing to this that exists — with what it teaches:

- **616 entries, 614 connections.** That is **≈1.0 edges per node**, and the render shows why:
  one enormous hub with a starburst of spokes, and a periphery of dots connected to almost
  nothing. A graph at that ratio is a star with confetti, not a network. **The lesson is that
  edges are not free** — they have to be *earned* by a real relation, or the visual promises a
  structure the data does not have. `P13-02`'s typed edges exist partly to make that failure
  impossible: an edge you cannot name is an edge you should not draw.
- **A node reading `CONFIDENCE 66%` and `1 mentions`.** Confidence there is the extractor's own
  self-report, not corroboration. Two-thirds certainty from a single unconfirmed mention is a
  number that *looks* like evidence. `P13-01` should separate **how sure the extractor was**
  from **how much has confirmed it since** — they are different columns and only the second
  should move on its own.
- **Their "Avoid" list contains raw venting, promoted to a rule at 95%.** Verbatim entries like
  *"not a single person I have had look at it knows what the fuck is going on"* are sitting in a
  behavioural policy list at high confidence.
  **This is the single strongest argument for `P13-05`'s explicit commitment gate** — extraction
  should propose; only promotion should bind.
- **"Last analyzed 5m ago · Covering last 3 months."** It is a batch job over a window, not a
  live index. That is a reasonable choice and worth copying — but it should say so in those
  words, because a stale graph presented as current is a lie of omission.

- [ ] **P13-00b** **Project-scoped permanence is the point of this phase.** Memory today is
  owner-scoped and session-linked; there is no notion of a *project* that outlives either. Long
  term knowledge — this stack, these conventions, this decision and why — should attach to the
  thing it is about and survive every session boundary, model swap and restart. `Verify:` start
  a new session months later, ask about a project, and the answer carries what was learned
  before without being re-explained.
- [ ] **P13-01** **Confidence on memories.** Lift the skill extractor's 0..1 score and floor
  onto memory extraction. Same shape, same tuning surface, one fewer concept to learn.
- [ ] **P13-02** **Typed edges between memories** — as data, not as a picture. `supersedes`,
  `contradicts`, `derived_from`, `co_occurs`. Each one changes what retrieval returns: a
  superseded memory stops surfacing, a contradiction surfaces *both* sides with the conflict
  named. **An edge that only exists to be drawn is not worth storing.** That is the test.
  *(Re-measured 2026-08-27: `link|related|edge|graph` across `services/memory/*.py` returns 6
  raw hits and **0 relevant** — the earlier "one grep hit" was itself a false positive. The
  finding is unchanged and stronger: there is nothing here to extend, so this row is a genuine
  build. It writes to the `data/memory.json` store — see the corrected preamble — and it
  depends on `P13-03` landing provenance first.)*
- [ ] **P13-03** **Provenance.** Which session, which message, which tool produced this — and
  what has confirmed or contradicted it since. `session_id` exists; the rest does not.
  **Premise corrected 2026-08-27.** **Do this one first.** It carries the store correction above — provenance fields
  go on the `data/memory.json` record (`src/memory.py:136` / `:275-278`), not on the SQL table — and
  `P13-01`, `P13-02`, `P13-05` and `P13-09` all write to whatever store this row establishes.
  Landing any of them before this one points four tasks at the wrong half of the system.
- [ ] **P13-04** **Decay and archive.** **Premise corrected 2026-08-27.** **Reinforcement already ships** —
  `memory.py:297-315` strengthens on retrieval, `chat_processor.py:352` calls it, and the "Most
  used" sort is that signal surfacing in the UI. Building it again is a second counter that
  disagrees with the first (`Law 14`). **What is open is the other direction:** a memory never
  retrieved fades toward archive rather than deletion. Nothing is ever silently dropped.
- [ ] **P13-05** **Commitment as an explicit act.** Suggestions today are accepted or not. Add
  a real promotion step with a quality gate, so "committed to memory" means something and can
  be audited afterwards.
- [ ] **P13-06** **Provider import** — ChatGPT, Claude, Gemini conversation exports. Every
  imported memory carries its origin and enters at a lower confidence than something learned
  first-hand, because it was.
- [x] **P13-00** **Legibility is the acceptance criterion for this entire phase — `Law 15`.** — **SUPERSEDED 2026-08-28 — moved into the phase preamble, where a criterion belongs.** This is the row shape `P7-05` was already superseded for: an acceptance criterion filed as a task, which nobody can honestly tick and which therefore sits open forever while the phase it governs ships around it. The statement is now in the `P13` preamble and hangs as a `Verify:` clause on `P13-07` and `P13-08`, naming a cold reader. Same words, somewhere they bite.
  The competitor's version of this feature is more advanced than anything planned here, and an
  interested beta user who *wanted it to work* abandoned it because there were no tutorials and
  the curve was too steep. The capability was real; the adoption was zero. Nothing in `P13`
  ships until someone who has never seen the surface can tell what it is for and what to do
  next, from the surface alone. **If it needs a tutorial, it is not finished.**
- [ ] **P13-07** **The Brain page — readable, not navigable-by-dragging.** `Verify:` someone who
  has never opened this page finds what the agent remembers about one project, and corrects a
  wrong memory, without being told how and without reading the source (`Law 15`). A dedicated surface,
  **not on the main path and not on open**, reached from a small card via *Explore more*. Lists
  and filters: by project, confidence, category, age, session, and edge type. Open a memory, see
  what it supersedes and what contradicts it, correct it, retire it. Search that finds a thing
  in one query rather than a thing you spot in a cloud. State plainly how fresh the analysis is.
  **No canvas. No force layout.** (`P3-19` is therefore moot unless another surface needs it.)
- [ ] **P13-08** **Observable skill growth, as a list with dates.** `Verify:` a cold reader can
  say which skills got better this week, and why, from the page alone (`Law 15`). Skills already carry
  confidence and `/memory/timeline` already exists; extend it so a person can see a capability
  form, strengthen, get used, or fall away — in a table they can read, sort and act on. The
  value is knowing *what the system learned this week and whether it was right*, which is a
  reading task, not a viewing one.
- [ ] **P13-09** **Wire `audit` to confidence.** The consolidation pass exists and is blind —
  it should raise confidence where sources agree and record a contradiction edge where they
  do not, rather than picking a winner quietly.
- [ ] **P13-10** **A retrieval trace.** When memory changes an answer, say which memories and
  at what confidence. **Premise corrected 2026-08-27.** **"Computed and thrown away" is wrong — this is wired end to
  end.** `chat_processor.py:311/330/347` → `routes/chat_helpers.py:1068` → `chat_routes.py:1622` →
  `chat.js:3417` → `chatRenderer.js:1847`, which renders a `.memory-used-pill` and a detail
  panel. Which memories were used is already visible. **The only missing field is confidence**,
  which `P13-01` introduces — so this collapses to a one-field extension of that row and is not
  independently actionable. `Depends:` P13-01, and it is not worth starting without it.

---

# P14 · Measurement
*Area: `measurement` · Depends: nothing · Blocks: P12-08, and everything adaptive*

**Promoted out of `DEFERRED.md` D-05, because too much now depends on it.** `P12` cannot ask an
operator to set a limit it cannot show them consuming. `D-06` cannot gate a training run on an
evaluation nobody records. And the platform cannot answer the most basic question anyone asks
of a harness — *did that change help?* — because the events were never written down.

`core/database.py:219-221` stores `message_count` and token totals as **running counters on a
session row**. The time dimension is discarded at write. Not because the query is hard; because
nothing ever recorded the event.

- [ ] **P14-01** **One append-only events table.** Timestamp, session, owner, model, endpoint,
  tokens in and out, duration, outcome. Everything else in this phase reads from it.
  **Premise corrected 2026-08-27.** **The stated write location was wrong, and wrong in an expensive direction.**
  `llm_core.py` writes no total at all — the totals accumulate in `accumulate_token_usage` at **`routes/chat_helpers.py:828-844`** —
  path-qualified deliberately, because `src/chat_helpers.py` also exists —
  which has four callers. That is a **17-line insertion point instead of a 3,731-line file** to
  read first. This row unblocks `P14-02`, `P14-03`, `P14-05`, `P12-08` and half of `P14-04`, so
  the wrong address here was costing five downstream rows.
- [ ] **P14-02** **Instrument the rest of the loop** — round latency, tool call and failure
  counts, queue depth, approval outcomes, retrieval hit rates. Same table.
- [ ] **P14-03** **An eval harness.** Save a set of cases, run them against a configuration,
  get a number. Nothing in this codebase does that today: every prompt change, model swap, skill edit and
  retrieval tweak in this codebase is currently evaluated by vibes.
- [ ] **P14-04** **Wire eval to receipts.** A saved case is a receipt (`P4-27`); a run is a
  re-run (`P4-26`); a result is a diff (`P4-28`). Law 14 — no second scaffolding.
- [ ] **P14-05** **Usage over time, per model and per owner.** The question that started this
  phase. Cheap once `P14-01` exists.
- [ ] **P14-06** **Decide the store.** SQLite is fine until it is not. `DEFERRED.md` D-05 makes
  the case for TimescaleDB — hypertables, native compression, continuous aggregates — and it
  only earns its place once there is data worth compressing. Do not start here.
- [ ] **P14-07** **Pace and bound every indexing job.** Not measurement, but it belongs to the
  same discipline: background work that nobody watches. PandaOS shipped an out-of-memory crash
  that closed the app with no warning while building a search index, then fixed it with a
  single lazy bounded index and paced background work. Pantheon indexes ChromaDB, the tool
  index and RAG on the same machine a person is using.

---

# Deferred

- **D-01 · The approval card's new markup.** Effect chips, fingerprint badge, expiry countdown, taint trail. Two CI tests assert literal source strings from that file and the upstream cluster around it is the hottest code in the project — 15 commits in 4 weeks, a revert inside the most recent PR. **Style through existing selectors only; add no markup.** Revisit when the upstream commits stop landing daily. *(P4-04 and P7-06/07/08 are the style-only subset and can proceed.)*
- **D-02 · Container station.** Full entry in `DEFERRED.md`. The strongest framing is as the sandbox the threat model says does not exist, not as a deploy feature. ~70% of the machinery is in Cookbook.
- **D-07 · No marketplace.** Closed, not deferred. MCP already is one, and a store would be a
  second way to install a capability with the moderation and supply-chain burden of a platform
  and none of the network. Full entry in `DEFERRED.md`.
- **D-06 · Training and fine-tuning — PARKED, skip for now.** Not scheduled, not counted,
  nothing blocks on it. The analysis is kept because its constraints are the reason it would
  ever be safe. Fits the platform — ~70% of a training station is the
  serving station the Forge already is, and Pantheon is sitting on the scarce input, which is
  the dataset. **Constrained to LoRA/QLoRA adapters, never full fine-tuning**, because every
  other adaptation path here is reversible and inspectable and a baked weight is neither. An
  eval gate is mandatory, not optional. Blocked behind the Forge rename, `P11`, `P12` and
  `D-05` — a training run is the most expensive thing a user can trigger, and it should not
  ship before quotas exist. Full entry in `DEFERRED.md`.
- **D-04 · The vector store.** Keep ChromaDB for now. The coupling is 130 call sites over
  2,110 lines, not the 72-line client that makes it look easy, and the swap that would
  actually pay is Postgres replacing SQLite **and** Chroma at once — not Chroma alone.
  Full entry in `DEFERRED.md`. `Depends:` do not start before P1.
- **D-05 · Telemetry.** The app stores token totals as running counters and throws the
  time dimension away at write time, so it cannot report on its own usage over time. One
  append-only table where the totals are already computed. This is the real case for
  TimescaleDB — an addition, touching nothing that exists. Full entry in `DEFERRED.md`.
- **D-03 · VM station.** Held. If the need proves real, wire to Proxmox or libvirt through an MCP server rather than building a hypervisor. `Depends:` P8 complete.

---

# Bugs found during implementation

*Agents append here. Format: `- [ ] **Bxx** … — found during Px-yy — agent:`id``*

- [ ] **B02** **P2-07's decode fallback cannot be reached from the UI.** `static/js/emailLibrary.js:6807` gates the "Open in document editor" button on `_OPENABLE_RE = /\.(pdf|docx|txt|md|markdown|eml)$/i` — the six pre-existing suffixes. No `.log`, `.csv`, `.json`, `.yaml` or extensionless attachment can reach the new branch. Suggested fix: drop the extension gate entirely and let the backend sniff be the single decision point. `Verify:` a `.log` attachment opens in the editor. **DECIDED — drop the extension gate entirely; the backend sniff is the single decision point** (D-2026-08-26-06). — found during P2 run 01
- [ ] **B03** **P2-11's rejected files vanish silently.** Partial-failure batches now return 200 with `files` + `rejected`, where they previously returned a failure status. `static/js/fileHandler.js:325` clears `pendingFiles` on any 2xx, so the rejected subset disappears from the composer with no message. One toast reading `rejected` closes it. `Verify:` drop 30 files, see a message naming the 5 that did not upload. **DECIDED — one toast naming what was rejected and why** (D-2026-08-26-06). — found during P2 run 01
- [ ] **B04** **The two new controls have no test coverage.** The P2-17 413 cap, its boundary, and its ordering behind `require_admin` have zero tests; `attachment_as_doc` has zero and always did. Both implementing agents owned no test files. Promote the two scratch harnesses into `tests/`. — found during P2 run 01
- [ ] **B05** **An unenforced cross-file invariant.** `src/upload_handler.py`'s `document_extensions` must stay a subset of `src/document_processor.py`'s `_is_text_file`, or an upload is accepted and then silently discarded at ingest. The invariant is now in a docstring; nothing checks it. A three-line test would. — found during P2 run 01
- [ ] **B06** **The verifier goes blind again after the first round of a long plan run.** `static/js/chat.js` blanks `_pendingApprovedPlan` immediately after appending it to the first request, so `P6-15`'s fix — judging the run against the approved checklist — only covers round one. Every continuation turn falls back to the bare trigger string. Either keep the plan for the life of the execution or re-send it per round. `Verify:` a plan run that takes four rounds has the checklist in the verifier's instruction on all four. — found during P6-15 — agent:`impl:agent-loop`
- [ ] **B07** **The scheduler files an admin-privilege refusal as `error`.** `src/task_scheduler.py` sets `status = "error"` where the task never ran and is then paused. By the vocabulary documented at `core/database.py:810+` that is `skipped` — "deliberately did not run", not a failure — so every privilege refusal currently counts against the task's error rate. Changing a persisted status value is why this is its own row rather than part of `P6-05`: decide whether old rows are migrated or left. `Verify:` a task whose owner lacks the privilege records `skipped` and does not appear under Errors. — found during P6-05 — agent:`integrator`
- [ ] **B08** **A stale `agent_status: running` outlives the run that set it.** `static/js/notes.js` reads `agentLive || item.agent_status`, so a `running` value persisted before a reload — or written when the tab closed mid-run, which is exactly the `P6-09` scenario — survives with no live job behind it. The tooltip then says "open the menu to stop it" while `_agentSolveState` is live-only, so no Stop entry renders. Related: `grep is-agent-running|is-agent-queued static/style.css` returns **0** — the class the button's visibility depends on has no rule, so it stays at `opacity:0`. `Verify:` reload with a stale `running` todo; either it offers a working stop or it stops claiming to. — found during P6-09 — agent:`refute:queue`
- [ ] **B09** **`static/js/chat.js` is loaded under two different cache-buster strings.** `static/index.html:250` preloads it as `?v=20260815toolapproval4` while `static/index.html:2620` and `static/app.js:13` request `?v=20260819approvalcontrol1`. The modulepreload therefore warms a URL the page never asks for — the preload is wasted and the module is fetched twice on a cold load. Pre-existing, not this run's. `Verify:` one string, three sites. — found during P6 wave 1 — agent:`integrator`
- [ ] **B10** **`node --check` is a no-op for `static/app.js`, and `AGENTS.md` names it as a gate.** `static/js/package.json` is `{"type": "module"}`, so every module under `static/js/` parses as ESM and the check works. `static/app.js` sits outside that directory with no marker, so Node parses it as CommonJS, the ESM syntax error is swallowed by module detection, and it exits **0 on a file with a deliberate syntax error** — measured by appending `const broken = ;` to a copy. `static/sw.js` is fine (plain script). So the pre-tick checklist silently verifies nothing for the one top-level module in the tree. Fix: add a marker, move the file, or say so on the line. `Verify:` a syntax error in `static/app.js` fails the gate. — found during P6 wave 2 — agent:`integrator`
- [ ] **B11** **The plan window and the todo card render visually identical rows that mean different things.** Sharing the row system was right (`Law 14`) and the CSS is genuinely joined by selector, not copied. But an approved plan and the agent's private scratch list can now be on screen at once looking the same, and they are not the same kind of thing — one is a commitment the user approved, the other is the model's working memory. They need a tell. `Law 15`: a person should not have to work out which is which. `Verify:` both on screen at once, and a stranger can say which is the approved plan. — found during P6 wave 2 — agent:`integrator`
- [ ] **B12** **Four smaller duplications survive between the plan window and the todo card.** The row system is shared, the chrome is not: `.plan-window-head` / `.todo-card-head` (2 of 6 declarations shared), the `"N of M done"` string built two ways (`planWindow.js:392`, `chatRenderer.js:1377`), the step chip built as DOM in one and as a string in the other, and the play triangle `points="7 4 20 12 7 20 7 4"` hand-written twice (`chat.js:978`, `planWindow.js:412`). None is a bug today; all four are the shape that becomes one, the way the accessibility contract already did — the two row builders disagreed on it until this run and each batch's refuter only saw its own half. `Verify:` one implementation each. — found during P6 wave 2 — agent:`integrator`
- [ ] **B01** **The datastore image is unpinned.** `chromadb/chroma:latest` in all three
  compose files, and `binwiederhier/ntfy` with no tag at all in the same three. A
  breaking Chroma release lands on the next `--build` and the collections stop loading —
  silently, since nothing validates the schema on connect. `searxng` is pinned to
  `2026.5.31-7159b8aed`, so the convention already exists in the file; these two just
  missed it. Six one-line changes. `Verify:` `grep -c ':latest\|ntfy$' docker-compose*.yml`
  returns 0. — found during the datastore audit

---

**Provenance.** Every task traces to a row in the Elevation Ledger. Six audit passes,
one adversarial. Two claims were caught wrong and corrected; assume more remain and
verify against the source before implementing. See `AGENTS.md` rule 3.
