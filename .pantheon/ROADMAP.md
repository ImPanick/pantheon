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
| P0 | Fork identity & licence | 30 | 16 | 0 | **14** |
| P1 | Token layer — the free wins | 14 | 14 | 0 | 0 |
| P2 | Un-nerf | 26 | 15 | 1 | **10** |
| P3 | Mechanical hygiene | 19 | 19 | 0 | 0 |
| P4 | The wire — the real glass box | 28 | 28 | 0 | 0 |
| P5 | Trace & composer restyle | 16 | 16 | 0 | 0 |
| P6 | Queue & Plan | 18 | 18 | 0 | 0 |
| P7 | Trust ladder & control plane | 11 | 11 | 0 | 0 |
| P8 | The Workshop | 48 | 48 | 0 | 0 |
| P9 | Feature surfaces | 18 | 18 | 0 | 0 |
| P10 | Accessibility & release | 12 | 12 | 0 | 0 |
| P11 | Identity & access | 13 | 13 | 0 | 0 |
| P12 | Limits & the control plane | 10 | 10 | 0 | 0 |
| P13 | The Brain | 12 | 12 | 0 | 0 |
| P14 | Measurement | 7 | 7 | 0 | 0 |
| **Total** | | **288** | **257** | **1** | **30** | | **287** | **256** | **1** | **30** | | **266** | **235** | **1** | **30** | | **253** | **222** | **1** | **30** | | **250** | **219** | **1** | **30** | | **231** | **200** | **1** | **30** | | **231** | **211** | **0** | **20** | | **229** | **208** | **1** | **20** | | **228** | **211** | **1** | **16** |

**Nothing is waiting on a decision.** All eighteen are answered and recorded in `DECISIONS.md`
D-2026-08-26-06, and each task line carries its own call. `P2-13` is the only blocked row in the
programme, on four test assertions.

**Run `P2` to finish it** — every remaining task now has a settled answer on its line, and the
work-list was verified against the source before any of it. Then `P1`, because everything visual
depends on the token layer and `P1-01` is finally specified correctly.

**`P1` is the next phase to run** — everything visual depends on the token layer, and `P1-01` is
now specified correctly (per theme, never `:root`).

**Then the licence gaps** — they are the gate on going public (`DECISIONS.md`
D-2026-08-26-02), and `P0-17` is the only one that is a genuine legal obligation rather
than tidying: the AGPL §13 source link, which does not exist anywhere in the UI today.
After that, `P0-19 … P0-26` — seven vendored libraries ship with no licence text, one
bundle's banner points at a file that is not in the repo, and the twenty KaTeX font faces
are credited as MIT when they are OFL with Reserved Font Names.

`P0-13` (the mark) also blocks the flip: the wordmark and screenshot in `docs/` are still
upstream's artwork under Pantheon's filenames.

`P2` has no dependencies at all and runs in parallel with any of it.

---

## Progress

*The one progress area. Newest first. One entry per completed section — two lines, a
commit range, and nothing else. The detail lives in the commit messages, which is what
they are for.*

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

**Deployment reality: one self-created admin account, one Docker install, a home LAN,
no other users, no downstream consumers, and the data is explicitly disposable.** The
entire "breaking change" analysis collapses — there is nobody to break and nothing to
preserve. **No migration shims. No compatibility layer. No data migration.** Rename,
purge, re-index, log back in. The only manual step is one line in your `.env`.

`scripts/pantheon-init.sh` does the mechanical sweep. Review its diff before committing.

- [x] **P0-01** Create `.pantheon/` with `AGENTS.md`, `ROADMAP.md`, `FORBIDDEN.md`, `DEFERRED.md`, `handoff/`. Seed one empty handoff file per area. — **done:** the directory exists; the sixteen empty handoff files were deleted in favour of § Progress.
- [x] **P0-01b** Run `scripts/pantheon-init.sh --dry-run`, read the diff, then run it for real. It does P0-02, P0-03, P0-04, P0-06, P0-07, P0-08, P0-10 and P0-11 as one reviewable sweep, with the attribution files excluded. Everything after it is by hand. — **done:** swept, 373 files, 2,615 in / 2,615 out, 37 path renames.
- [x] **P0-02** Rename cosmetic surfaces: page titles, wordmark text in `index.html` + `login.html`, 111 UI strings across `static/js/`, tray menu in `launcher.py`, `setup.py` banner. `Verify:` grep for case-insensitive `odysseus` in `static/` returns only attribution strings. — **done:** verified — `git grep -icI odysseus -- static/` returns one hit, the protected provenance link in `cookbook.js`.
- [x] **P0-03** Rename env prefix `ODYSSEUS_*` → `PANTHEON_*` (99 distinct names, 560 refs). Update `.env.example`, `docker-compose*.yml`, `Dockerfile`, `docs/`, **and your live `.env` on the host** — that one file is the entire migration. No shim. `Verify:` app boots with only `PANTHEON_*` set. — **done:** code and live `.env`; only `PANTHEON_ADMIN_USER`/`PASSWORD` existed on the host, and both are read solely at first-boot admin creation.
- [x] **P0-04** Rename browser storage keys (113 distinct, 206 refs in `static/`). Costs you one theme re-pick and a layout reset. `CI:` none. — **done:** verified — no `ody-`/`ody.` keys remain in `static/`.
- [ ] **P0-05** **Corrected — there is nothing to drop.** The previous entry claimed the volume still held `odysseus_*` collections. Queried the live instance: one tenant, one database, and only two collections exist — `pantheon_rag_fastembed` (0 docs) and `pantheon_memories_fastembed` (**8 docs**). The app created them under the new names on first boot and memory is already writing to them. No orphans anywhere, so nothing was stranded and nothing needs migrating. What is left is smaller: **RAG is empty and `pantheon_tool_index` does not exist yet** — add the directories back through the RAG UI, and the tool index builds itself on first tool search. `Verify:` RAG search returns results after re-adding a directory; `GET :8100/api/v2/tenants/default_tenant/databases/default_database/collections` lists a tool index. *(Caught by Law 9 — the entry described what I assumed, not what was there.)*
- [x] **P0-06** Rename session cookie `odysseus_session` → `pantheon_session`. You log in again once. — **done:** swept.
- [x] **P0-07** Rename outbound HTTP headers (`X-Odysseus-Origin/Kind/Ref/Event/Signature/Owner`) and the four User-Agent strings. No downstream consumers exist yet — do it now, before any do. — **done:** swept.
- [x] **P0-08** Rename Docker compose service, container user (`ODY_USER`), and the SearXNG settings sentinel `odysseus-local-searxng-json-2026-05-30`. `Verify:` a clean `docker compose up` produces a working SearXNG. — **done:** swept; a clean rebuild produced a healthy SearXNG.
- [ ] **P0-09** Rename data dir default (`~/.odysseus/data`), systemd unit + installer, PyInstaller spec, macOS `CFBundleIdentifier`, PWA manifest name, service-worker cache name. **Docker mounts `./data` explicitly, so the default path change does not move your live data** — verify that before restarting.
- [x] **P0-10** Rename the 19 `scripts/odysseus-*` CLI scripts (`git mv`). If you have a crontab or systemd timer pointing at any of them, update it — otherwise nothing references them. — **done:** all 19 `git mv`-d.
- [x] **P0-11** Rename Swift package + two executables, the two integration plugin ids (`integrations/{claude,codex}/skills/odysseus/`), `_EMAIL_MCP_OWNER_ARG`, and the 3 custom DOM events. `Depends:` P0-02. — **done:** swept.
- [x] **P0-12** **The sweep rewrote two badges to dead targets — they need removing, not renaming.** `README.md:17` now points at `repology.org/project/pantheon-ai`, which does not exist; `README.md:71-75` now points the star-history chart at `ImPanick/pantheon`, which is private and will 404 for every reader. Delete both blocks. The rest of this task is done: the 47 `odysseus-dev` references, `package.json`, `.github/` templates and `cookbook.js:3177` were handled by the sweep, and the three links to specific upstream issues and discussions were deliberately preserved. `Verify:` no README image URL 404s. — **done:** both dead badges removed in the README rewrite; the sweep had already handled the 47 `odysseus-dev` references, `package.json`, `.github/` and `cookbook.js:3177`.
- [ ] **P0-13** Design the Pantheon mark — **and take a real screenshot with it.** Every README worth copying opens with one; ours would have to be `docs/pantheon-browser.jpg`, which is upstream's shot of the old UI under a renamed file, so shipping it would misrepresent the product. The README currently has none for that reason. **Do not reuse the red sailing boat, the wordmark, or the per-route favicon shapes** — the licence grants them but they are upstream's identity. Replace `static/icon.ico`, the favicon registry, the inline boat SVG (5 copies), and the programmatic tray drawing. **Keep the ASCII wave loader** — it's a loader, not a logo. — **DECIDED — its own session: three or four directions, pick one, then favicon, tray icon and the five inline SVG copies follow** (D-2026-08-26-06).
- [x] **P0-14** **§5(a) + §5(b) notices.** Add to `README.md` and a new `NOTICE`: a prominent statement that this is a modified version of Odysseus, **with a date**, and that it is released under the AGPL. Neither exists today. — **done:** `NOTICE` carries the §5(a) modification notice with the fork commit and date; the README carries the same statement in its status block.
- [x] **P0-15** **§4 copyright line.** There is **no project copyright notice anywhere in the repo today**. Add Pantheon's and preserve any upstream one that can be established. — **done:** `NOTICE` line 2 — `Copyright (c) 2026 Panick`. There was no upstream copyright line in the repo to preserve.
- [ ] **P0-16** **Apache-2.0 §4(b) change notices** on the research-derived files (`services/research/`, `src/research_handler.py`, `routes/research/`, `services/search/`) — "You changed the files". Absent today.
- [ ] **P0-17** **§13 Source link.** Single footer button in the UI. `href` → the public repo. `title="Built on Odysseus — click to see where Pantheon originated from!"`. Must be present on the logged-in shell and the login page. This is the one licence obligation that is genuinely required and genuinely missing. `Depends:` P0-12.
- [ ] **P0-18** Decide `AGPL-3.0-only` vs `AGPL-3.0-or-later` and state it in `LICENSE`, `README`, and SPDX headers. Today the qualifier lives in exactly one README line with zero SPDX headers. — **DECIDED — `AGPL-3.0-or-later`, matching upstream, with real SPDX headers** (D-2026-08-26-06).

### P0 · Credits — the licence gaps you inherit
*Do not publish before these close.*

- [ ] **P0-19** Rewrite `ACKNOWLEDGMENTS.md` as Pantheon's credits file. **Lead with Odysseus.** Preserve every credited party. Update paths that moved.
- [ ] **P0-20** Add missing licence bodies to `licenses/`: highlight.js (BSD-3), SheetJS/xlsx (Apache-2.0 — check upstream for a `NOTICE`), docx (MIT), mammoth.js (BSD-2), jsPDF (MIT), html2canvas (MIT), node-qrcode (MIT). MIT and both BSDs require the notice to travel with redistributed copies.
- [ ] **P0-21** Fetch the missing `html2pdf.bundle.min.js.LICENSE.txt` — the bundle's own banner references a file that is not in the repo.
- [ ] **P0-22** Add OFL text for Fira Code and Inter, and list the **20 KaTeX font faces** — all carry Reserved Font Names and are currently credited as MIT-only. Do not subset any font, or OFL §3 bites.
- [ ] **P0-23** **Resolve `static/fonts/custom/GohuFont.ttf`.** The shipped file is 1,468 bytes / 3 glyphs, metadata reads `Untitled1 / Copyright (c) 2025, Unknown`. It is not GohuFont. Replace with the real WTFPL font + licence, or remove it and drop the credits row. — **DECIDED — delete the file and its credits row** (D-2026-08-26-06).
- [ ] **P0-24** Add undisclosed deps to credits: `nh3`, `python-dateutil`, `httpcore`, `httpx2`, `python-magic`, Real-ESRGAN wheels, the two MLX Swift packages. Update `duckduckgo-search` → `ddgs`.
- [ ] **P0-25** Correct the PyMuPDF scope statement — it is documented as form-filling only; it also backs the PDF viewer's page render and the annotation-fill endpoint (three route handlers). Fix the stale docstring at `routes/email_helpers.py:1453` that credits it for text extraction it does not perform.
- [ ] **P0-26** Reconcile the credits file's "the core ships fully permissive (MIT-compatible)" framing against the AGPL `LICENSE`, or state which is authoritative for Pantheon.
- [x] **P0-27** README statement of intent: *"Pantheon is free software under the AGPL. I don't sell it, and I'd rather you didn't."* **Social, not legal — do not add a non-commercial clause.** AGPL §10 prohibits further restrictions and §7 lets any recipient strip one. — **done:** in the README licence section, phrased as intent and explicitly not as a clause.
- [ ] **P0-28** **The root `ROADMAP.md` is upstream's, and the sweep put Pantheon's name on it.** It now opens *"Pantheon is on a voyage, but not home yet... (I don't know what I'm doing, help)"* — upstream's words, upstream's self-deprecation, attributed to this project. It also collides with the real tracker at `.pantheon/ROADMAP.md`, which the README links as "Tracker". Replace it with a short pointer to `.pantheon/ROADMAP.md`, or delete it. `Verify:` a reader following either link lands somewhere that is true. — **DECIDED — delete it; point everything at `.pantheon/ROADMAP.md`** (D-2026-08-26-06).
- [ ] **P0-29** **Rename Cookbook → Forge** (`DECISIONS.md` D-2026-08-26-05). It reads as a recipe box; it is a model-serving control plane — remote host registry with SSH keys, GPU detection and hardware fit, weight downloads from HuggingFace and Ollama, vLLM / llama.cpp / Ollama launches held open in tmux, process kill, and task-status polling. 17 routes. **Surface: 3,533 occurrences across 172 files and 43 paths — larger than the Odysseus→Pantheon sweep was** (2,929). Use the same tool: `scripts/pantheon-init.sh` is proven and parameterises cleanly. Decide the name first (`DECISIONS.md`, pending) and whether *recipe* survives — 242 occurrences, and a vLLM recipe genuinely is a parameterised launch config, so it may earn its keep even if Cookbook does not. `Verify:` no user-visible string says Cookbook; `rail-*`, `tool-*-btn` and modal ids move together with their CSS.

---

# P1 · Token layer — the free wins
*Area: `tokens` · Depends: P0-01 · Blocks: P5, P8*

More visible change than any redesign step, and zero markup touched.

- [ ] **P1-01** **Define `--accent` PER THEME, not in `:root`. Defining it in `:root` breaks all 16 themes.** Measured: of the 799 `var(--accent…)` sites in `style.css`, **508 are `var(--accent, var(--red))`** and resolve today to the theme's own `red`, which `applyTheme()` sets at `static/js/theme.js:263`. A `:root` definition wins over that fallback, so all 508 would flip to one global colour and every theme would lose its identity in a single commit. **The themes are protected — see `DECISIONS.md` D-2026-08-26-03.**
  **Do instead:** one line in `applyTheme()` beside `s.setProperty('--red', colors.red)` — `s.setProperty('--accent', colors.accent || colors.red)`. The 508 fallback sites then resolve to exactly what they resolve to now (zero visual change), the bare sites resolve for the first time (pure gain), each theme keeps its own accent, and the 8 custom-theme slots get it free because they run through the same function. Add an optional `accent:` key to `THEMES` for any theme that should differ from its `red`. `CI:` none. `Verify:` cycle all 16 themes and diff screenshots — only the previously-unstyled elements change. Then: rail hover backgrounds appear; both resize handles become visible; the session rename input gets a border; the scroll-to-bottom button gets its colour.
- [ ] **P1-02** Define `--accent-primary` (121 uses, never defined) — or replace those uses with `--accent`.
- [ ] **P1-03** **Define `--fg-muted`** (93 bare uses, zero definitions). Every one of those elements was authored as secondary text and renders at full strength. `Depends:` P1-01.
- [ ] **P1-04** **Delete `#sidebar-backdrop { display:none !important }`** at top-level nesting depth 0 — it beats the media-query rule everywhere. Thirteen call sites across four modules already toggle the element. `Verify:` mobile drawer dims the page and tap-to-close works.
- [ ] **P1-05** **Fix `#rail-settings`** — it unhides the sidebar and scrolls to the bottom instead of opening Settings. The guided tour uses it as its opener, polls 25 times, and gives up with an error. `Verify:` the tour completes.
- [ ] **P1-06** Add 4–6 semantic status tokens (`--ok --warn --danger --info` + optional `--think`) derived from the five theme tokens. Absorbs **420 of 517 unthemed colour occurrences across 68 distinct hex values** — 21 reds meaning danger, 22 blues meaning info.
- [ ] **P1-07** Separate the ~120 Dracula/One-Dark syntax-palette occurrences into their own token set. They are code-block theming that was never wired to the theme system — not app status colours.
- [ ] **P1-08** **Computed `--on-accent`.** `.send-btn` hardcodes `color:#fff`; white-on-accent fails 4.5:1 on **all 16 themes**, and the accent itself fails on 7 of 16. One token fixes all sixteen.
- [ ] **P1-09** Add a contrast guard inside `generateHarmonyColors()` and `applyColors()` (~15 lines) so every future custom theme clears the floor too. `Depends:` P1-08. **`CI:`** any new theme token must extend `ADV_KEYS` **and** `computeAdvancedDefaults()` in lockstep or all 16 themes break.
- [ ] **P1-10** **Normalise z-index to 7 named tiers.** 261 declarations, 63 distinct values, range −1 to 1,000,000. Use the order-preserving remap: strictly increasing in the same sorted order ⇒ no element can change stacking. `Verify:` the remap list is strictly increasing; nothing moves visually.
- [ ] **P1-11** Fix the toast occlusion the tiering surfaces — toasts sit at 9999, below every image-editor popover at 10001–10006. Deliberate second pass, needs visual review. `Depends:` P1-10.
- [ ] **P1-12** **One global `prefers-reduced-motion` guard.** 18 narrow opt-outs against 148 keyframes and 7 unguarded canvas animators — the background effects run continuously with nothing.
- [ ] **P1-13** Elevation tokens: 4 theme-aware shadows replacing 274 declarations / 198 unique values. 110 hardcode `rgba(0,0,0,α)` — on the four light themes those read as grey smudges. The good theme-aware form already exists and is used 6 times.
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
- [ ] **P2-10** **The fake concurrency limit.** "max concurrent uploads: 3" is enforced as "≤3 uploads in the last ten seconds" and fires on a normal multi-file drag. Drop it; the 60/min rate limit already exists. `CI:` the test sets it locally, so the default is not pinned. — ****DECIDED — AMENDED. Do NOT delete.** The "one operator cannot DoS themselves" reasoning does not survive `P11`. Becomes an admin control, default off — `P12-06`** (D-2026-08-26-06).
- [x] **P2-11** Raise `MAX_FILES` (10 → 25) **and** add a server-side `len(files)` cap, which does not exist. **`CI:` a test regex-parses this literal** and asserts `upload_rate_limit >= MAX_FILES`. — **done:** `MAX_FILES_PER_REQUEST = 25` at `src/upload_handler.py:227`, enforced pre-loop at `routes/upload_routes.py:274`; partial-write hazard fixed.
- [ ] **P2-12** **Stop hiding small email attachments.** The signature heuristic also returns true for *any* image under 30 KB — a real screenshot is silently invisible **and** excluded from the ZIP. Keep the filename patterns, drop the size clause. — **DECIDED — drop the size clause in **both** files, pin `_has_visible_attachments` to the old predicate, keep the two filename patterns. Write the first test** (D-2026-08-26-06).
- [~] **P2-13** **BLOCKED — correctly, on something the spec never named.** Premise verified true: both clamps exist at `src/llm_core.py:1071` and `src/agent_loop.py:2212`, and the Anthropic cloud clamp at `:1572` is untouched. But **four assertions in two unowned test files pin the cap** — `tests/test_llm_core_temperature_reasoning.py:104` and `tests/test_pr6020_rebase_regressions.py:182/:201/:216`. The two qwen tests exist to prove a mixed fallback chain leaks temperature in neither direction, and that property must survive any rewrite. **Also needs a decision:** `_apply_local_generation_stability` receives only a payload dict and cannot tell *the user asked for 0.9* from *0.9 is a default*, so a faithful "default, not cap" needs an explicitness signal threaded from the builder. The agent refused to ship a hidden env escape hatch with no UI — right call. **DECIDED — thread an `explicit_params` set from the payload builder; the clamp becomes a setdefault for everything else. Keep the Anthropic ceiling** (D-2026-08-26-06).
- [ ] **P2-14** Loosen the guide-only trigger: seven regexes fire on any mention of the phrasing and then strip every tool **and all MCP** for the turn. Require whole-message match, or an explicit toggle. — **DECIDED — anchor patterns 1–6 to whole-message match; convert pattern 7 into a confirmation mode that arms the approval gate rather than stripping tools** (D-2026-08-26-06).
- [x] **P2-15** Fix the self-contradicting bash prompt — one line forbids heredocs, seven lines later another instructs the model to use one. Prompt-only; enforces nothing. — **done:** heredoc instruction removed at `src/agent_loop.py:574` — 10 ban sites, 0 instruction sites.
- [x] **P2-16** Fix the grammar bug producing `Your account is not allowed to can use research.` — **done:** `privilege_denied_message` at `src/auth_helpers.py:127`; the fail-open `privs.get(key, True)` deliberately untouched.
- [x] **P2-17** Cap the backup import — `await request.json()` with no size limit on an admin route. — **done:** 413 cap at `routes/backup_routes.py:134`, **after** `require_admin` at `:131`; env var wired into all three compose files and `.env.example`.
- [ ] **P2-18** Fix the feature-flag story: `deep_research` defaults off, the frontend hides four buttons, and **no server route checks it**. Either enforce server-side or delete the three flags with zero consumers. Flip `deep_research` on. — **DECIDED — fix the precedence bug generally, delete the three consumerless flags, flip `deep_research` on. **No server-side enforcement** — the endpoint is auth-exempt and was never a boundary** (D-2026-08-26-06).

### Re-surface what was built and never wired
- [ ] **P2-19** **Webhooks admin panel** — backend complete, **no UI whatsoever**. Add `adm-whList` / `adm-whAddBtn` markup. Add the null guards at the two functions that currently throw on `null.innerHTML` inside a silent `try` — which is why nobody noticed.
- [ ] **P2-20** MCP admin panel markup (`adm-mcp*`) — this also makes the OAuth-file registration path reachable for the first time. Feature toggles (`adm-featureToggles`), API tokens (`adm-tokenList`), RAG (`adm-rag*`). All four backends exist. — **DECIDED — build only RAG and feature toggles; skip MCP and tokens, which already have live UIs in settings (`Law 14`). Wire both into `inits` and `refreshAll`** (D-2026-08-26-06).
- [ ] **P2-21** Built-in skills editor: flip `showBuiltin = false` → `true`. `_buildBuiltinCards()` and its three admin endpoints are fully implemented, including a per-tool instruction-block override editor. — **DECIDED — gate the two GETs, write the list loader, then flip the flag. **Amended from optional to required** by `P11-10`** (D-2026-08-26-06).
- [ ] **P2-22** Re-attach the gallery upscaler controls (`ge-upscale-*`). Backend + local Real-ESRGAN both implemented, zero UI. — **DECIDED — target `/api/image/upscale-local` (local Real-ESRGAN). A backend selector waits for a real GPU host** (D-2026-08-26-06).
- [ ] **P2-23** Give RAG upload a UI — the module expects three elements that do not exist. The endpoint works and has **no extension restriction at all**. — **DECIDED — resurface the **user-facing** `rag.js` module, not the admin one. Three ids plus wiring, on a module already called every boot** (D-2026-08-26-06).
- [ ] **P2-24** Add a custom-font upload route. **Keep the extension allowlist here** — these files land under the static mount and are served with no forced disposition. This is the exception that proves the rule.
- [ ] **P2-25** Prune `NON_ADMIN_BLOCKED_TOOLS` of owner-scoped read-only tools. **Must stay:** shell, python, all filesystem tools, vault, settings, tokens, endpoints, MCP, webhooks, api_call, app_api, and the `mcp__*` prefix rule. **`CI:` two tests cover this partition.** — **DECIDED — prune nothing. Confirmed** (D-2026-08-26-06).
- [ ] **P2-26** Trim the "use the nicer tool" half of the app-API blocklist. **Must stay:** the cookbook install/rebuild/kill entries and every prefix rule. — **DECIDED — prune nothing. Correct the must-stay documentation and close it. Gets **stronger** under `P11`, not weaker** (D-2026-08-26-06).

---

# P3 · Mechanical hygiene
*Area: `css-hygiene` · Depends: P1 · Blocks: P5*

Provably safe, and each one removes a trap the restyle would otherwise fall into.

- [ ] **P3-01** **Resolve `#message` declared 4×.** The composer never renders at its authored 14px — a later `!important` forces 13px, and a third rule forces 16px on touch. One of the conflicting blocks sits under a class that does not exist. **Do this before any composer work.** *(Note: `max-height` is fine — 200px wins on specificity; only the font-size conflict is real.)*
- [ ] **P3-02** Resolve `.attach-strip` declared 3× with conflicting margin and padding.
- [ ] **P3-03** Delete the 510 confidently-dead rule blocks (**2,590 lines, 6.3%**). Verified 0/55 false positives on two random samples. **Do not touch the 349 UNCERTAIN blocks** — they are dynamically constructed.
- [ ] **P3-04** Delete duplicate `@font-face` (the whole Fira Code set is declared twice) and the 3 exact-duplicate `@keyframes`.
- [ ] **P3-05** **Fix the 2 conflicting `@keyframes` redefinitions** — `research-pulse` and `fadeIn`. These are live bugs: the later definition silently wins for every consumer, including code written against the earlier one.
- [ ] **P3-06** Collapse the 9 clone-body animations (nine names for one 360° rotation) into one.
- [ ] **P3-07** **Canonicalise breakpoints to three.** 13 distinct widths today. One 560-line block switches to mobile at 700px while 3,066 lines switch at 768px — **between those widths the UI is in a mixed state**, and there is a 20px dead zone (701–719) where an unpaired min/max leaves neither rule applying.
- [ ] **P3-08** Add paired-rule comments so a desktop rule points at its mobile override — the roadmap's own "CSS did not move" item.
- [ ] **P3-09** Delete `:root.light` (21 lines + 3 other sites) — unreachable by construction, since light themes push values through the five tokens and never add a class. **Recover the well-tuned light syntax palette inside it first.** `Verify:` the four light themes stop rendering dark native dropdowns.
- [ ] **P3-10** Delete the 3 dead modules: the RAG module (its three DOM targets exist nowhere, and two app-level call sites invoke a function it does not export), the calendar reminder poller (complete, zero callers, browser-notification path inert), and the tour autoplay module (its entire body is a "Disabled for v1 stability" comment, and it still imports a 6,500-line module for a side effect that never runs). **Two are still precached by the service worker** — update `sw.js`. `Depends:` P2-23 must land first if you want RAG's UI, else delete.
- [ ] **P3-11** Fix the duplicate module specifier — `chatRenderer.js` is imported under 3 distinct specifiers, so a 3,126-line module is parsed three times per page load. A config module's header documents the symptom and works around it; the root cause was never fixed. One-line change per import.
- [ ] **P3-12** Delete the 6 verified-dead elements and handlers: two elements killed by CSS with zero JS references, four ids appearing once in markup and nowhere in script, a handler wired to a nonexistent element, and section drag-reorder (queries a `draggable` attribute nothing ever adds).

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
  instead of surfacing an error." This codebase already has the same disease documented — the
  webhook admin functions that throw on `null.innerHTML` inside a silent `try` are the reason
  nobody noticed the panel was missing for years. `Verify:` no bare `except: pass` around a
  user-visible operation.
- [ ] **P3-18** **Stacking order: menus above modals.** They shipped dropdowns and context menus
  rendering *behind* open dialogs. Pantheon has a window system, a tile manager, modal chrome
  and popovers. `Verify:` every popover opened from inside a modal is visible.
- [ ] **P3-19** **Graph and canvas surfaces need a no-acceleration fallback.** Their Brain graph
  crashed outright on machines with hardware acceleration disabled. `P13-07` is a graph.
  `Depends:` P13-07.

### Drift control — Law 13's enforcement
- [ ] **P3-13** **Wire `check-wiring.py` into CI at `--max 78`.** It counts `getElementById`
  targets that resolve to nothing: 78 today, across 16 prefixes and seven subsystems. The
  ceiling may fall and may never rise. Every built-and-never-wired finding in the P2 audit
  would have shown up here years ago if anything had been counting. `Verify:` a PR that adds
  an unresolved lookup fails.
- [ ] **P3-14** **Clear the 78.** Not one task — each id is either wired to markup, or deleted
  along with the handler that looks for it. Grouped by owner: `ge-*` 17 (gallery editor,
  overlaps `P2-22`), `doc-*` 11, `cookbook-*` 9 (becomes `forge-*` under `P0-29`),
  `doclib-*` 6, `new-skill-*` 5, `email-*` 4, `gallery-*` 3, `hwfit-*` 3, `rag-*` 2
  (`P2-23`), `tool-*` 2, plus 13 singletons. Lower the ceiling after each batch.
- [ ] **P3-15** **Extend the check to the other half of the disease** — routes with no caller,
  settings keys with no reader, feature flags with no consumer. `P2-18` found three flags with
  zero consumers by hand; a script finds the next three for free.

---

# P4 · The wire — the real glass box
*Area: `wire`, `trace` · Depends: P1 · Blocks: P5*

The backend emits ~50 distinct SSE event types through a single `if/else if` chain;
anything without a branch is silently discarded. **Thirty-plus fields are computed,
serialised, sent to the browser and never read.** None of this needs backend work.

### Prerequisite — do this first
- [ ] **P4-01** **Unify the six drifted agent-thread templates into one builder.** They exist across the live path, history replay and compare mode, and **zero pairs are byte-identical**. They diverged three ways: compare mode hardcodes the fallback icon so it can never show the search glyph; one copy omits the diff block; the labels differ. **This is not a mechanical extract — you must decide which behaviour is correct and record the decision in your handoff note.** Every other P4/P5 trace task depends on this.
- [ ] **P4-02** Fix the key-name mismatch: the shell tool sends elapsed time under one name and the frontend reads another, so the displayed timer is a client-side guess rather than server truth. One rename. `Depends:` P4-01.
- [ ] **P4-03** Delete the dead handler for a skill-saved event the server never emits.

### Free — already on the wire, zero backend work
- [ ] **P4-04** **The approval card's own reason.** The server sends a written explanation naming the exact effects that tripped the gate; the renderer never reads the field. *(Style-only — see `DEFERRED.md` for the markup constraint.)*
- [ ] **P4-05** **The full fallback chain** — every model candidate tried with its HTTP status. Render `gpt-4o ✗502 → claude ✗429 → llama ✓` instead of a six-second "retrying" toast.
- [ ] **P4-06** **`failed` and `failure{status,message}` on terminal metrics.** **A failed turn currently renders identically to a successful one.** This is a correctness bug, not polish. Highest priority in P4.
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
- [ ] **P4-24** **Background sessions get none of this.** When a stream is resumed after navigating away, a second and much poorer dispatch chain collapses every tool, research and source payload to a single "this was rich" boolean. A background agent run is currently unobservable after the fact. `Depends:` P4-01.

### Run receipts — Law 14: this is P4's job, not a phase of its own
The wire already computes model, parameters, tools offered, skills injected and RAG hits, then
discards them. A receipt is that data kept instead of thrown away.

- [ ] **P4-25** **Capture a receipt per agent run** — model and endpoint, resolved sampling
  parameters, the tool schemas actually sent, which skills were injected and at what confidence,
  which memories and documents were retrieved, round count, token usage, and every approval
  decision with its outcome. All of it is already on the wire; none of it is kept.
- [ ] **P4-26** **Make a receipt re-runnable.** Same inputs, same configuration, new run —
  which is the only honest way to answer "did that change help". `Depends:` P4-25.
- [ ] **P4-27** **Make a receipt portable.** One file, exportable, readable by a person who was
  not there. This is what turns "it did something weird" into a bug report. `Depends:` P4-25.
- [ ] **P4-28** **Diff two receipts.** What changed between the run that worked and the one that
  did not. `Depends:` P4-26.

---

# P5 · Trace & composer restyle
*Area: `trace`, `composer` · Depends: P3, P4-01*

- [ ] **P5-01** Replace the three nested 300px scrollers with a `grid-template-rows: 0fr → 1fr` transition. Long reasoning currently clips into a 300px inner scroller inside the page scroller — the worst UX defect in the trace.
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
- [ ] **P5-12** Consolidate the six hand-styled tool chips and the two bare-icon toggles into **one chip component**. Cleanest large win in the composer, and it makes the strip themeable for the first time.
- [ ] **P5-13** Icon normalisation — three sizes and one stroke token replacing 8 sizes and 9 stroke widths across 1,182 inline SVGs. A stroke-2 glyph from a 24 viewBox at 11px has an effective stroke under one pixel. **Attributes only; no SVG markup is rewritten.**
- [ ] **P5-14** Type scale — collapse 27 ad-hoc steps onto a ramp drawn from the existing values, with **11px as the floor rather than the median** (827 of 1,222 sizes are 10–12px; 118 are ≤9px).
- [ ] **P5-15** **Populate `#pinned-tools-bar`** — an empty div appearing once in the whole codebase with zero CSS and zero JS. Unclaimed composer real estate, no layout risk.
- [ ] **P5-16** Make the send button's five states legible without changing the machine. **Eight modules mutate it**; any composer rework must reproduce `newchat · mic · send · streaming(processing/receiving/queue) · recording` exactly. Note Enter-on-empty opens a new chat, and the mic state appears from a silent server capability check.

---

# P6 · Queue & Plan
*Area: `queue`, `plan` · Depends: P4-01*

- [ ] **P6-18** **Steer mid-response, not only queue.** The queue holds the *next* message;
  steering redirects the one in flight. Two different verbs, and only one exists. Prior art has
  both on one key pair — Enter queues, Cmd/Ctrl+Enter steers — which is the right shape because
  it is the same intent at two urgencies. `Depends:` P6-01.
- [ ] **P6-01** **Session-bind the queue — live bug.** Queue items carry no session id. Switching chats wipes the message list, destroying every queued bubble's element while the array keeps the items; when the old stream ends the prompt **fires into whichever chat is now open**, invisibly. Add the field, filter the drain on it, re-render bubbles on session switch.
- [ ] **P6-02** Persist the queue. `_queuedAgentRequests` is a bare module array — a reload loses it silently.
- [ ] **P6-03** Allow queueing with attachments — currently refused with an error that swallows the send.
- [ ] **P6-04** Build the queue panel: drag-reorder, edit in place, per-item mode/model/trust rung, start-now force bypass, pause, remove. **Clone the research job engine** (382 self-contained lines) rather than writing a new one — only two lines are research-specific.
- [ ] **P6-05** Adopt the shipped status vocabulary: `queued → running → success | error | skipped | aborted`. `skipped` and `aborted` are load-bearing — `aborted` keeps infrastructure events out of error-rate stats.
- [ ] **P6-06** Sequential-vs-parallel picker. **Already built** in the research panel — reuse it. Parallel must allocate a session per item: one agent run per session is enforced.
- [ ] **P6-07** Point the existing Tasks activity view at queue items rather than building a second queue UI. It already renders every status with shared elapsed timers, a force button and a stop button.
- [ ] **P6-08** Make `_concurrency_cap` actually configurable — it sits next to `Semaphore(1)` and is documented as "a hard guarantee, not configurable".
- [ ] **P6-09** Rewrite the todo "solve with an agent" button to enqueue instead of firing an unbounded raw stream. **Click ten todos and ten agent loops run at once**, with no progress and no cancel.
- [ ] **P6-10** Expose `crew_member_id` in the task create/update schemas and the `manage_tasks` tool. It is read-only today and honoured by the executor — **this one field closes the roadmap's "todos assignable to an agent from the UI" item at the API layer.**
- [ ] **P6-11** **Build the docked plan window.** Three prompt strings tell the model it exists and a code comment claims it renders. **Nothing has ever rendered it** — mid-execution `update_plan` writes to browser storage with zero visible effect, and the prompt is telling the model something false about its own interface. Structured steps with per-step status, bound tool, effect, elapsed and result.
- [ ] **P6-12** Give plan mode a real entry control. The toggle button resolves to nothing — the element does not exist; entry is Tab-in-composer or a mobile swipe, and the status pill can only turn it **off**. Its CSS is written and dead. **Do not use the three-up mode toggle** — it belongs to the model-serving panel.
- [ ] **P6-13** Add a step model with ids. A plan is an opaque markdown string everywhere — storage, form field, prompt, tool argument — and progress is computed by counting ticked boxes in that string. `Depends:` P6-11.
- [ ] **P6-14** **Let planning mode ask a question.** The clarifying-question tool is absent from the read-only allowlist, so the gate blocks it. A planning mode that cannot ask what you meant is planning blind.
- [ ] **P6-15** **Pass the plan to the verifier.** It judges against the last user message, which during plan execution is literally the string *"Execute the approved plan"* — naming no deliverables. **The verifier is blind for the entire run.** One line.
- [ ] **P6-16** Guard the narrating-without-acting supervisor against plan mode, where narrating **is** the job. One line.
- [ ] **P6-17** Render the agent's own todo list. A structured todo tool exists, persists to disk, is instructed for multi-step work, and **has no renderer** — it surfaces only as raw tool output text.

---

# P7 · Trust ladder & control plane
*Area: `trust` · Depends: P4*

The approval store is better than anything that would replace it. Do not rebuild it.

- [ ] **P7-01** **Stop the mode toggle lying.** A 60-word keyword regex — including *change, update, review, test, run, build, source, system, device, app* — silently promotes Chat to Agent, and 35 lines later a single line **overwrites the user's own shell toggle to true**. The backend escalates again on tool intent, search and web intent, computes an escalation flag, and never sends it. `Depends:` P4-18.
- [ ] **P7-02** Stop the model raising its own trust level — it can currently flip the mode toggle through a UI-control event with no confirmation.
- [ ] **P7-03** Add rung **"ask every time"**. Does not exist: the gate is conditional on untrusted content having entered, so a clean session never prompts. Change the gate condition from *taint seen* to *taint seen **or** the current rung requires confirmation*. **Reuse `PendingToolApproval` unchanged.**
- [ ] **P7-04** Add rung **"allow-listed"** — a rule store mapping tool + argument pattern to auto-allow, consulted before the blocked-effect check. Does not exist.
- [ ] **P7-05** Record the correction in the UI: **Auto-Pilot is already the default** for every untainted conversation. The ladder is added *below* current behaviour, not above it.
- [ ] **P7-06** Rank prompts by effect. A destructive action and a UI side effect produce an identical card. The 13-value taxonomy is written and used to rank nothing.
- [ ] **P7-07** Send only the effects that actually **tripped** the gate, not all of them — and surface the unrecognised-tool case, which is the riskiest and currently invisible.
- [ ] **P7-08** **Surface the taint trail.** The security context builds a complete list of which tools introduced untrusted content into a run, and it is read **nowhere** — server or client. Built in memory and thrown away.
- [ ] **P7-09** Grant inspector — once a session-wide grant is given, nothing lists it and nothing revokes it.
- [ ] **P7-10** Surface run limits at the moment of decision. "How far can it run unattended" sits in a settings tab, invisible when you choose. `Depends:` P4-23.
- [ ] **P7-11** Real file export — Markdown, JSON, HTML download. PDF is `window.print()`, which cannot run headless or be scheduled. Nothing exports the approval trail at all.

---

# P8 · The Workshop
*Area: `skills`, `automations`, `mcp` · Depends: P1*

Three authoring surfaces over three engines that already run.

### Skill Crafter
- [ ] **P8-01** **Add the five phantom inputs** — `#new-skill-name`, `-description`, `-when`, `-procedure`, `-category`. The handler already reads them, they are in the clear-on-success list, and one has an Enter binding. **Zero JavaScript change.** Do this first; it is the cheapest win in the whole roadmap.
- [ ] **P8-02** Add pitfalls, verification, platforms and required-toolsets inputs. All four are supported by the API and reachable from nowhere — **half the structure of every hand-written skill is currently unusable.**
- [ ] **P8-03** Relabel "draft". A draft is excluded from the catalogue the model browses and **still keyword-injected** when it matches — "uncatalogued", not "inactive".
- [ ] **P8-04** Fix the confidence-slider trap: maximum position stores **zero**, labelled "All", which disables the gate entirely. Dragging right is "let everything in", not "only perfect skills".
- [ ] **P8-05** Surface the hidden coupling: turning auto-approve off sets the injection floor to 2.0, silently making injection published-only.
- [ ] **P8-06** **Prompt preview** — call `GET /api/skills/index`, which exists to answer exactly this and **no frontend file has ever called**. Extract the injection renderer into a shared function so the preview is the truth, not a re-implementation.
- [ ] **P8-07** Show what the preview reveals: **verification and body text are never injected.** They surface only through an on-demand view action.
- [ ] **P8-08** Wire the test's `task` field — the endpoint has accepted a user task all along and the UI has never sent one. One textarea.
- [ ] **P8-09** **Before/after behaviour diff.** The runner is parameterised on arbitrary markdown *and* an arbitrary task and never reads from disk — call it twice with old and new against the same task. `Depends:` P8-08, P8-10.
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
- [ ] **P8-22** Node palette endpoint — merge the three `/meta/*` routes, move the client-side category/icon taxonomy server-side, emit param schemas and a `model_backed` flag (currently maintained twice: once to gate the semaphore, once to draw a badge).
- [ ] **P8-23** **Give triggers payloads.** The event bus takes a name and an owner — a "document created" trigger cannot say *which* document. The webhook route has **no request parameter**: body, query and headers are read by nobody. It is a doorbell. **Highest-leverage change in Automations; everything downstream depends on it.** Do not change the webhook URL shape — it is CI-pinned.
- [ ] **P8-24** Widen the node output contract from `(text, success)` to `(payload, status)` with a back-compat adapter for the 18 existing actions. The no-op and defer-with-backoff signals already encode skip and retry — generalise them.
- [ ] **P8-25** **Write `TaskRun.steps`** — declared, migrated, never written. A run records one result string for the whole task. Filling it upgrades the shipped activity view instantly with no new UI.
- [ ] **P8-26** Add the graph document. One nullable successor today; the cycle check doubles as a **silent depth cap of ten**. Project the existing successor as a single edge on read.
- [ ] **P8-27** Run-scoped execution identity — the current one is keyed by task, so a task cannot be in flight twice. Required before fan-out. `Depends:` P8-26.
- [ ] **P8-28** Branch node — the only conditional in the engine is `status == "success"`. `Depends:` P8-26.
- [ ] **P8-29** Data mapping between nodes. `Depends:` P8-23, P8-24.
- [ ] **P8-30** Collapse the three parallel event catalogues into one registry, and **add `document_updated`** — it is fired in production and appears in neither catalogue, so nothing can trigger on it.
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
- [ ] **P8-41** Fix three stale comments claiming MCP is dropped in plan mode. It is not — read-only tools are kept via annotations with a fail-closed verb heuristic.
- [ ] **P8-42** Fix the empty-env trap: an empty env dict yields `None`, so the SDK substitutes a minimal environment instead of inheriting the parent's. A generated server relying on inherited `PATH`/`HOME` starts on a fresh install and fails on a bare one.
- [ ] **P8-43** Let `builtin_browser` auto-reconnect — the reconnect helper hard-returns false for anything outside a four-entry map, despite the browser server counting as built-in. A crashed Playwright server stays dead until a manual reconnect.
- [ ] **P8-44** Server-id validation. One `split("__", 2)` is the sole parse of the namespaced name; **an id containing `__` routes the call to the wrong server.** Unreachable today because ids are uuid4-derived — the moment a Creator lets people name servers, this field holds the invariant.
- [ ] **P8-45** Surface the 23-entry preset catalogue (14 with setup walkthroughs) currently sitting in ~400 lines of unreachable code. Its two entry points look up DOM ids no template has ever rendered. `Depends:` P2-20.
- [ ] **P8-46** Replace the single-line JSON inputs — a parse failure is caught and **silently discarded**, posting empty args and env, after which the server fails to connect for a reason nothing explains.
- [ ] **P8-47** Scaffold generator, writing to the **data volume** — the source tree is baked into the image with no bind mount, so generated servers cannot be built-ins and must register as ordinary rows with an absolute path. **That path is denied on the agent's registration path by design.** Author here; register through the admin route. **Do not weaken the command validation** — it closes a reported RCE and is pinned by 10 tests.
- [ ] **P8-48** Tool schema editor + `readOnlyHint` / `destructiveHint` annotation UI. The schema is already carried end-to-end and nothing edits it; `manage_mcp list_tools` drops it entirely, so the LLM cannot see a tool's parameters through its own tool.

---

# P9 · Feature surfaces
*Area: `surfaces` · Depends: P5*

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
- [ ] **P9-04** Consolidate email settings — they live in three places. Highest-priority IA fix. **Keep compose-in-document-editor** (it is why AI drafting works); present it as a composer.
- [ ] **P9-05** Full views for Calendar and Compare — a month grid and an N-way comparison inside ~780px draggable boxes. **Compare deliberately shows/hides the original container's children rather than replacing markup**, so listeners on the input bar and mode toggle survive; any rework must honour that.
- [ ] **P9-06** Promote Skills out of the Brain modal — different object, different lifecycle (draft → audit → publish). `Depends:` P8-01.
- [ ] **P9-15b** **Freeform answers on the ask-user card.** When the model offers choices, a
  person should be able to type something that is not on the list. `.ask-user-card` is in
  `FORBIDDEN.md` Part 1 — extend it, do not rebuild it.
- [ ] **P9-15c** **Hybrid chat search — keyword and meaning in one box.** The vector half exists;
  exact-match does not, and "find the message where I pasted that error" is a keyword query.
- [ ] **P9-07** **Empty states.** A named roadmap item, and **not one empty state exists anywhere.** Include the cookbook's, which should show the actual command and output instead of "crashed".
- [ ] **P9-08** Honest error messages, same lane. `Depends:` P9-07.
- [ ] **P9-09** Provenance on everything the model produced — memories, skills, tidy results, research reports, calendar parses, generated images. Chat bubbles show it; nothing else does. The formatter already exists.
- [ ] **P9-10** Preview before destructive AI operations. **Chat tidy deletes sessions *and* re-folders them with no preview at all**; memory tidy has an animation, not a reviewable diff. Calendar has a real undo stack and is the only surface that does — proof it is solvable here.
- [ ] **P9-11** Make background work visible with its window closed — skills audit, research jobs, cookbook downloads, memory tidy and email sync all report into windows the user has closed. **Extend the minimized-dock chips**, which already carry per-window status; email writes an unread label onto its own.
- [ ] **P9-12** Fix "non-passing" in the skills bulk delete — it currently catches **never-audited** skills, so a brand-new hand-written skill counts as failing. Add an undo path. `Depends:` P8-10.
- [ ] **P9-13** Surface the theme zone highlighter — hovering a colour picker outlines the element it controls on the live page behind the modal. **The best explainability feature in the app**, with no label, legend or hint that it exists. The map is keyed by picker id, so extending it is a data edit.
- [ ] **P9-14** Add the selection count to the bulk bar — it is computed and never rendered — and stop looping bulk archive/delete one row at a time with no progress and no partial-failure reporting.

---

# P10 · Accessibility & release
*Area: `a11y`, `release` · Depends: P1, P5*

The accessibility pass is the upstream roadmap's own item, unclaimed, and historically
the only lane through which the theme file gets touched.

- [ ] **P10-01** One focus ring through `:focus-visible`. **97 `outline:none` suppressions** against 35 `:focus-visible` rules and six competing ring styles. The a11y shim's own header notes the ring already exists and never fired because rows were never focusable. Most suppressions can then be deleted.
- [ ] **P10-02** Author sidebar rows as real buttons. **Keep `.list-item`** — the a11y shim and the drag-sort module both query it, and rows *contain* nested buttons, which is exactly why the shim declines `role="button"` on them. **Change the tag, not the class.**
- [ ] **P10-03** Make both resize handles visible and keyboard-reachable. They are mouse-only and invisible because their entire treatment routes through the accent token. `Depends:` P1-01.
- [ ] **P10-04** Contrast audit across all 16 themes with the guard from P1-09 enforcing it. `Depends:` P1-09.
- [ ] **P10-05** Verify the reduced-motion guard covers all 148 keyframes and the 7 canvas animators. `Depends:` P1-12.
- [ ] **P10-06** Keyboard navigation pass over the rail, the sidebar, the composer, the window system and the Workshop.
- [ ] **P10-07** Give the loader a stage line so boot is not silent, move it off `innerHTML`-per-frame, and add a reduced-motion guard. **Keep the wave.**
- [ ] **P10-08** Any new modal needs its own `ui-scale-125` height compensation — otherwise zoom pushes the draggable header and close button off-screen, and you cannot reach the control to turn the size back down.
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
2. **Authorization is effectively one bit, applied 84 times.** `require_admin` has **84** call
   sites against `require_privilege`'s **17**. Ownership scoping is healthier — `owner_filter`
   at 58 sites — so the data model already understands "whose row is this". What it does not
   understand is "what may this kind of person do".

The live defect: unknown privilege keys **fail open** — `privs.get(key, True)` at
`src/auth_helpers.py:172` — with the comment "the UI gates display-side", and `P2-18` proved
that UI gate does not work. A typo in a privilege key currently grants access.

None of this is wrong for one admin on a LAN. All of it is wrong the moment a second person
has an account.

- [ ] **P11-01** **Close the fail-open default.** Known keys default to denied; genuinely
  unknown keys stay permissive so a new key does not lock everyone out mid-deploy. Requires a
  registry of known privilege keys, which does not exist — there are 9, discovered by grep.
  `Verify:` a typo'd key denies rather than grants.
- [ ] **P11-02** **Roles as named overlays on `DEFAULT_PRIVILEGES`.** Not a new system — the
  dict already carries booleans, an integer quota and a model allowlist. A role is a named set
  of overrides; a user gets a role and optional per-user overrides on top. Resolution order:
  built-in default → role → user. Keep `is_admin` as the superuser role rather than replacing
  it, because 84 call sites depend on it and rewriting them all at once is how this goes wrong.
- [ ] **P11-02b** **Audit every `require_admin` site against the role model.** 84 of them, and
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
  every privilege wholesale (`ADMIN_PRIVILEGES`), and non-admin means nine independent
  booleans set per user. A role is the missing middle: a named bundle of privileges plus limit
  profile. Keep `is_admin` as the superuser role rather than replacing it.
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
- [ ] **P11-09** **Re-arm what single-user mode let us delete.** `DECISIONS.md`
  D-2026-08-26-01 deleted the upload type blocklist and named "a second user account" as the
  condition that voids it. This phase *is* that condition. Restore the check — with `.svg` in
  it this time — gated on multi-user being enabled, not unconditionally.
- [ ] **P11-10** **Admin-gate the built-in capability reads** if `P2-21` has not already. Any
  logged-in non-admin can currently read all 60 tool instruction blocks.

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

- [ ] **P12-01** **Move the eleven byte caps into settings**, with the environment variable as
  an *override* rather than the only source. Order: role profile → instance setting → env →
  built-in default.
- [ ] **P12-02** **Limit profiles attached to roles.** Upload size, files per request, request
  rate, context budget, concurrent agent runs, model-serve permission.
- [ ] **P12-03** **Runtime-adjustable without a restart.** The caps are read at import today,
  so this is a real refactor, not a settings row.
- [ ] **P12-04** **Context and attachment budgets become policy.** This is where `P2-08` and
  `P2-09` land properly: the shared 24,000-char budget, the PDF's 15,000, the per-file 30,000,
  and skill-injection count all become a single coherent budget with a per-role ceiling — and
  the ceiling is what stops a proven-window scale-up from handing someone twelve untrusted
  skill blocks.
- [ ] **P12-05** **Per-user and per-role rate limiting.** The current limiter is per-IP, which
  behind any reverse proxy is one bucket for everyone.
- [ ] **P12-06** **Reinstate upload concurrency as an admin control, not a constant.**
  `P2-10`'s recommendation to delete it assumed one user on a LAN. Under real infrastructure
  it becomes a per-role setting with the default off.
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

**What is actually there today.** `memories` is a flat table — `id, text, category, source,
owner, session_id, timestamp` — behind a vector index. **No confidence, no edges, no
provenance beyond a one-word `source`.** Four of the pieces this needs already exist and are
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

**What genuinely does not exist: edges.** One grep hit for link/related/edge/graph across the
whole memory subsystem. That is the phase.

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
  behavioural policy list at high confidence. A bad afternoon became a durable instruction.
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
- [ ] **P13-03** **Provenance.** Which session, which message, which tool produced this — and
  what has confirmed or contradicted it since. `session_id` exists; the rest does not.
- [ ] **P13-04** **Reinforcement and decay.** A memory retrieved and acted on gets stronger; one
  never retrieved fades toward archive rather than deletion. Nothing is ever silently dropped.
- [ ] **P13-05** **Commitment as an explicit act.** Suggestions today are accepted or not. Add
  a real promotion step with a quality gate, so "committed to memory" means something and can
  be audited afterwards.
- [ ] **P13-06** **Provider import** — ChatGPT, Claude, Gemini conversation exports. Every
  imported memory carries its origin and enters at a lower confidence than something learned
  first-hand, because it was.
- [ ] **P13-00** **Legibility is the acceptance criterion for this entire phase — `Law 15`.**
  The competitor's version of this feature is more advanced than anything planned here, and an
  interested beta user who *wanted it to work* abandoned it because there were no tutorials and
  the curve was too steep. The capability was real; the adoption was zero. Nothing in `P13`
  ships until someone who has never seen the surface can tell what it is for and what to do
  next, from the surface alone. **If it needs a tutorial, it is not finished.**
- [ ] **P13-07** **The Brain page — readable, not navigable-by-dragging.** A dedicated surface,
  **not on the main path and not on open**, reached from a small card via *Explore more*. Lists
  and filters: by project, confidence, category, age, session, and edge type. Open a memory, see
  what it supersedes and what contradicts it, correct it, retire it. Search that finds a thing
  in one query rather than a thing you spot in a cloud. State plainly how fresh the analysis is.
  **No canvas. No force layout.** (`P3-19` is therefore moot unless another surface needs it.)
- [ ] **P13-08** **Observable skill growth, as a list with dates.** Skills already carry
  confidence and `/memory/timeline` already exists; extend it so a person can see a capability
  form, strengthen, get used, or fall away — in a table they can read, sort and act on. The
  value is knowing *what the system learned this week and whether it was right*, which is a
  reading task, not a viewing one.
- [ ] **P13-09** **Wire `audit` to confidence.** The consolidation pass exists and is blind —
  it should raise confidence where sources agree and record a contradiction edge where they
  do not, rather than picking a winner quietly.
- [ ] **P13-10** **A retrieval trace.** When memory changes an answer, say which memories and
  at what confidence. Same principle as `P4` — the data is computed and thrown away.

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

- [ ] **P14-01** **One append-only events table.** Written where the totals are already
  computed in `llm_core.py`. Timestamp, session, owner, model, endpoint, tokens in and out,
  duration, outcome. Everything else in this phase reads from it.
- [ ] **P14-02** **Instrument the rest of the loop** — round latency, tool call and failure
  counts, queue depth, approval outcomes, retrieval hit rates. Same table.
- [ ] **P14-03** **An eval harness.** Save a set of cases, run them against a configuration,
  get a number. This is the missing organ: every prompt change, model swap, skill edit and
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
