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
> The other nineteen laws are in `AGENTS.md`. Nine of them are anti-drift laws, and each
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
| `check-licences.py` | compares every shipped third-party file against `CREDITS.md`. An allowlist |
| `check-destinations.py` | no address ships pre-filled. Law 16 clause 4's enforcement |
| `check-jitter.py` | no recurring job fires on an exact boundary. P15-10's enforcement |
| `check-outbound.py` | every call that leaves the process is paced, or it is named. P15-06's enforcement |
| `check-unreachable.py` | routes with no caller. P3-15's automation of the discovery audit |
| `check-fork-names.py` | the fork's old short name, in code, with every survivor named. P0-31's enforcement |
| `check-spdx.py` | every file of program text declares its licence, and no vendored file declares ours. P0-18's enforcement |
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

**A row that opens `FOLDED INTO` or says *this is a pointer, not a row* keeps its mark but
cannot be picked up alone** — its work lives on the row it names, and doing it separately
produces the duplicate the fold exists to prevent. It stays visible so nobody rediscovers it
from scratch. Introduced 2026-08-31; the folds are listed in § *What this run leaves behind*.

| Phase | Area | Tasks | Ready | Blocked | Done |
|---|---|---|---|---|---|
| Setup | Fork, rename, rebuild | 6 | 0 | 0 | **6** |
| P0 | Fork identity & licence | 33 | 5 | **1** | **27** |
| P1 | Token layer — the free wins | 15 | 7 | 0 | **8** |
| P2 | Un-nerf | 26 | 12 | 0 | **14** |
| P3 | Mechanical hygiene | 24 | 12 | **2** | **10** |
| P4 | The wire — the real glass box | 28 | 24 | 0 | **4** |
| P5 | Trace & composer restyle | 17 | 17 | 0 | 0 |
| P6 | Queue & Plan | 18 | 1 | 0 | **17** |
| P7 | Trust ladder & control plane | 14 | 9 | **1** | **4** |
| P8 | The Workshop | 49 | 45 | **3** | **1** |
| P9 | Feature surfaces | 18 | 16 | 0 | **2** |
| P10 | Accessibility & release | 12 | 12 | 0 | 0 |
| P11 | Identity & access | 14 | 13 | **1** | 0 |
| P12 | Limits & the control plane | 11 | 11 | 0 | 0 |
| P13 | The Brain | 14 | 13 | 0 | **1** |
| P14 | Measurement | 8 | 3 | 0 | **5** |
| P15 | Outbound politeness | 12 | 2 | **1** | **9** |
| P16 | Self-hosted by default | 20 | 1 | 0 | **19** |
| **Total** | | **339** | **203** | **9** | **127** |

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
- **`P0-18`, `P0-21b` and `P0-31` closed 2026-09-07.** The API token prefix migrated (with the
  agent's tmux session name); the whole tree declares `AGPL-3.0-or-later` per file; and every
  package inside a shipped bundle has a notice — thirteen of them added, and the derivation that
  proved it found two more bugs (`B45`, `B46`). `check-fork-names.py`, `check-spdx.py` and
  `check-licences.py`'s new rule 7 fail CI on any regression.

### Next: `P3-12` (itemise the 26 orphan ids), then `P3-09`. `P3-01`, `P3-02`, `P3-04`, `P3-05`, `P3-06` and `P3-07` are done. `P3-01`, `P3-02`, `P3-04`, `P3-05` and `P3-06` are done. **`P1-08` needs the owner** — it changes what all sixteen protected themes look like. `P1-12` and `P1-14` are done; `P1-12` left `P1-15` behind. **The `P0` licence block is finished except for six rows that cannot be closed from here** — `P0-05` needs the live ChromaDB, `P0-08` needs Docker, `P0-16` and `P0-17` need the owner, `P0-13` is blocked on a design decision, and `P0-29` is its own session. `P0-18`, `P0-21b` and `P0-31` closed 2026-09-07; standing suite failures **19 → 14**. `P3-21`, `P7-12`, `P7-13`, `P13-11` and `P15-07` wait on the owner

**`P16-05` is the last zero-configuration leak**, and the only one that is not a one-liner: the
embedding model is pulled from HuggingFace on the *first chat message*, because
`build_embedding_lanes` builds the fastembed lane unconditionally and `fastembed` is a hard
requirement. Either the model ships in the image or the lane becomes conditional on an explicit
download permission.

**`P16-08` is the biggest remaining `Law 16` gap and it is not a one-liner.** `img-src` still
allows any `https:` host, so an `![](…)` in model output, a RAG document or an **email** makes the
viewer's browser beacon a third party — content the user did not author, fetched from a host they
did not choose. Tightening the header alone breaks every legitimate remote image, so it needs the
same-origin proxy pattern `routes/emoji_routes.py` already demonstrates (fetch, validate, cache,
serve) with the SSRF guards in `src/outbound_fetch.py`. Build the proxy, then tighten the header
in the same change; doing the header first is a regression wearing a fix's clothes.

**`P16-14` is about *other people's* issues**, not ours: open source means strangers file bugs,
and a diagnostic bundle is what makes those reports usable rather than *"it broke"*.

**`P16-16` is new and is a capability gap, not a defect** — the north star includes *"even my
parallel networks"*, and the product reaches one network's worth of hosts, implicitly, from
wherever the container sits.

**`P16-12` is the one that turns the law into a feature**, and it is now the most valuable row in
the phase: operators on their own hardware currently have no way to see what Pantheon is doing,
and clause 4 explicitly permits fixing that. Build it with `P16-13`'s guard in place, not after.

**`P16-11` is the row that stops all of this recurring.** Everything in `P16` was found by reading.
A CI job with no route to the internet, asserting the app boots and answers one message, would
find the next one — and would have found all of these.

**2026-08-31 — a live ban reordered the queue.** The owner was soft-banned by GitHub by his own
product while this session was running. `P15` exists because of it, and four of its rows are
closed; what is left of it comes before the `H` rows, because a feature nobody can reach costs
less than one that gets the user locked out of a service they depend on.

**`P15-07` needs a human, not an agent.** `llm_core` rotates its `User-Agent` through six
different vendors' clients until a 403 stops coming back. That is block evasion by construction
and it is the one thing most likely to convert a soft ban into a permanent one. Removing it may
break a provider someone relies on, so it is a decision, not a task — but it cannot stay
undocumented, and now it is not.

**`P15-09` landed 2026-09-05** — cooldowns and the escalation ladder now survive a restart, stored
as wall-clock deadlines because the in-memory value is a monotonic reading and monotonic's origin
resets at boot. `P15-10` is the last cheap one in this phase.

**`P15-10` landed 2026-09-05 and `P15-06` on 2026-09-06**, each with a checker behind it —
`check-jitter.py` found twelve sites the hand audit had missed and `check-outbound.py` found four
unpaced calls to hosts that have already throttled this product. What is left in `P15` is `P15-07`
(waiting on the owner) and `P15-11`. The `H` rows outrank both.

**Then `H01`, unchanged and still the biggest data-loss row** — the invisible email backlog.
Its gating question was answered on 2026-08-31: the default arrived at the fork baseline, so the
backlog is as old as the install, and the drafts UI comes before the default flip.

### Then: `H05`, then `P3-15`. The `H` rows outrank the remaining phases

**The discovery audit changed what the top of the queue is.** 21 rows of working code with no
door, and three of them are live harm rather than absent polish:

**`H01` landed 2026-09-07** — the approval panel exists, it opens itself, and the three places
that claimed it existed are now telling the truth. What is left of it is the default flip, which
was always second: the drainer had to come first or flipping it would strand the backlog.
**The question that gated this row is answered (2026-08-31): it is a year, not a week.** The
default arrived at the fork baseline `fff72ec` and is in upstream too, so the backlog is as old as
the install and is not bounded by the fork date. **That settles the order: the UI first, not the
default flip.** Flipping the default stops new drafts accumulating and strands every one already
staged, invisible, in `scheduled_emails`. Build the pending-drafts card, drain the backlog, then
decide the default.

**`H05` landed 2026-09-07** — the flags are enforced in the agent's denylist, on four routers and
at the retrieval site, and the admin's decision now outranks the user's Appearance preferences
instead of being undone by them one line later.

**`H14`, `H15`, `H17` landed 2026-09-07.** They were one-liners with real payoff — a tooltip that names the gesture it
actually needs, settings search that indexes the controls rather than only the panels, and the
idempotent open-signup route that already exists and nothing calls.

**Then `P3-15`**, which is now specified rather than sketched: the audit's method is on the row,
and a correct script rediscovers all 21 `H` rows from a clean checkout. Fix `check-wiring.py`'s
two newly-found blind spots first — string-literal-only matching, and not stripping comments.

**`P1` continues at 6 of 14 when the `H` rows are drained, and it has one more ready row than it
did.** `P1-06` **is unblocked** — `B22` supplied the scope it was missing, and the two are now one
job: move the semantic tokens into `theme.js`'s per-theme block and give the four light palettes
their own values. `P1-10` (z-index, 259 declarations, 64 values, order-preserving remap) is still
the largest unblocked row; `P1-08` waits on `B15`, which `B16` now folds into. Re-derive every
count first — every number in that phase has moved at least once and `P1-01`'s moved four times.

**What this run leaves behind.** The 21 `H` rows, four of them now corrected rather than as
written — **read `H21`'s warning before acting on it; two of its items delete live code.** The
newly-freed rows: `P1-06` (with `B22`), `P2-13`, `P3-19`, `P7-11a`. **`P6-08` is open again** and
`H06` is the row that fixes it. New this run: `B25` (the changelog claims the AGPL §13 link
shipped; it did not) and `B26` (the sidebar anti-flash guard, renamed on one side only). From
earlier runs: `B21`'s `src/` half, `B23`, `B17`, `B18`, `B19`, `B20` (corrected — `H06` is the
defect, this is the second-order hazard), `P5-17`, `B13`, `B14`, `B15` (now carrying `B16`),
`B06`, `B10`.

**Rows that can no longer be picked up alone**, because their work lives on another row and doing
them separately produces a duplicate: `P13-10` → `P13-01`, `P12-08` → `P14-05`, `H16(b)` →
`P2-21`, `H20(b)` → `P7-11a`, `H05`'s flag inventory → `P2-18`, `B16` → `B15`, `B22` → `P1-06`.
Each says so on its own line.

**Still out of scope on its own:** `P0-29`. The Cookbook → Forge sweep is 3,529 occurrences
across 171 files and 43 paths — the largest blast radius in the programme, coupled to
`_ROUTE_FAVICON_SHAPES` **and to the `ody-` residue `P0-31` now tracks**. Its own session, as
D-2026-08-26-06 already says.

**Second choice, if the licence work is someone else's:** `P6` — queue and plan mode. 13 of 18
rows verified accurate, contained to `chat.js`, `app.js` and two scheduler files, no cross-phase
gate, and `P6-01/02/03` is one coherent user-facing bug cluster: queued messages fire into the
wrong chat, vanish on reload, and silently swallow a send with attachments.

**Do not start with:** `P1` — `P1-01` is three files plus a `CACHE_NAME` bump, not one module.
*(`P1-06` was named here as blocked on a measurement that does not exist; the measurement is
`B22` and it exists now, so that half of this warning is withdrawn.)* `P4` — `P4-01`'s six-template unification
gates eight rows behind it. `P3-03` — its classifier was never committed. `P11`–`P14` — `P14-01` unblocks five rows, and its write
location was wrong until it was corrected on the row itself; the row is right now.

---

## Progress

*The one progress area. Newest first. One entry per completed section — two lines, a
commit range, and nothing else. The detail lives in the commit messages, which is what
they are for.*

> **The `N tracked, M done` on each entry is the status table's `Total` row, and until
> 2026-09-07 nothing checked it.** It read `135 done` against a table saying `116` — the
> one line in this file whose whole job is to summarise the rest, wrong by nineteen and
> carried forward unread from entry to entry, because each author copied the line above.
> `check-tracker.py` now validates the newest entry against the table and fails on drift.
> Entries below the `P0-31` one keep the figure they were written with: a record of what
> was claimed at the time is worth more than a quietly corrected one (`B44`).

### P3-07 — one number decides what "mobile" means, and eight places disagreed
`e355dcf..HEAD`. **339 tracked, 127 done. 7 new tests, 0 regressions.**
The row was about a stylesheet and the stylesheet was the smaller half. **`B50`**:
`sidebar-layout.js` disagrees with itself — seven tests say 768, including the one that shows
the mobile backdrop, and three said 700, including click-outside-to-close. Between 700 and 767
the sidebar was an overlay with a backdrop inviting the click that dismisses it, and the
handler returned early. Four more 700s in the image editor's `right-panel.js` are why moving
only the CSS would have been a half-fix: the panel would have laid out as a sheet no gesture
could dismiss. **Two of the row's claims are corrected**: the "20px dead zone" does not exist
(that `min-width` pairs with a base rule, and a test says so), and "canonicalise to three" was
not the work — the other ten widths reflow components, not the shell. 13 widths → 12, and one
answer to where mobile ends.

### P3-01, P3-02 — two elements whose applied style nobody wrote
`18a9e64..HEAD`. **339 tracked, 126 done. 18 new tests, 0 regressions.**
The composer has never rendered as authored: a bare `#message` block pins four `!important`
declarations over `.chat-input-bar textarea#message`'s 14px / 1.5 — **and it belongs to a
section in which every other selector is dead**, an older composer layout kept in the file with
one id selector in it that still reaches something. Scoped, not deleted. **What the 13px cost
was invisible until it was measured**: `#message-ghost` is drawn over the textarea and authors
14px / 1.5 to match it, so the inline autocomplete ghost drifted further right with every
character. A test pins the two layers together now. `.attach-strip` was three blocks at equal
specificity, each replacing part of the last; collapsed at the values the cascade already
produced, with every declaration's origin recorded.

**One trap, from writing the comment**: a `*` `/` inside a CSS comment ends it, so quoting the
section name *with its delimiters* turned half the note into a selector — the test's own parser
caught it on the first run. Same shape as `check-wiring.py`'s comment-stripper incident.

### P3-04, P3-05, P3-06 — one name, one animation, and two that meant something else
`b388f6b..HEAD`. **339 tracked, 124 done. 8 new tests, 0 regressions.**
`@keyframes` are global and the last definition of a name wins for every consumer, silently.
`style.css` shipped 149 blocks under 143 names. **`research-pulse` was the live one**: a button
whose own comment says "glow" asks for a background pulse three lines above it and gets an
opacity-and-scale throb from 6,800 lines below. Renamed, both kept. Seven names for one 360°
rotation collapsed to `spin` — and the sweep had to leave the stylesheet, because `settings.js`
writes one of them into an inline style, and needed word boundaries, because `admin-spin` is a
prefix of the live class `admin-spinner`. **The check written for the cluster found a third
defect on its first run** (`B49`): a spinner naming keyframes that do not exist, inherited at
the fork baseline, that has never spun. `B48` is the tracker's own: two rows shared one id and
nothing checked. 149 → 139 blocks, 139 names, none defined twice.

### P1-14 — one name for the curve that decides how everything feels
`a505720..HEAD`. **339 tracked, 121 done. 5 new tests, 0 regressions.**
`cubic-bezier(0.34, 1.56, 0.64, 1)` on 34 transitions and animations, never named, so the one
decision that most defines the product's feel could only be changed by find-and-replace.
`--ease-signature` now, in `:root`. **Three near-misses stay literal on purpose** — same shape,
gentler overshoot, and nobody knows whether that is taste or drift; a test pins their counts so
a later sweep has to be a decision.

### P1-12 — the guard the row asked for, minus the reason it gave
`657e14f..HEAD`. **339 tracked, 120 done. 13 new tests, 0 regressions.**
The row said a CSS-only guard could not reach the keyframes `slashCommands.js` injects at
runtime. It can — `!important` beats a normal declaration whatever stylesheet it came from —
and that claim is withdrawn on the row. **The trap it did not name is the one that matters**:
21 `!important` motion declarations already live in `style.css`, and between two `!important`
author declarations specificity decides before order, so a `*` guard loses to all of them
while reading as correct. `:is(#\9#\9#\9, *)` fixes that and a test recomputes the ceiling
rather than pinning the spelling. `0.01ms` rather than `none`, because this product cleans up
in `animationend` handlers. The seven canvas animators — the half CSS genuinely cannot reach —
stop, the theme class stays, and the panel says why. `P1-15` files the 52 smooth-scroll sites
the CSS guard cannot override. **`B47` is what the four-line import broke on the way**: the JS
sandboxes hand-write a stub per import, so the stub list is a second copy of the import list —
54 theme assertions, one node path in a temp directory, and nothing saying why. The copier
reads the imports now.

### P0-21b — the row asked for twelve notices and the derivation found two more bugs
`7bcd753..HEAD`. **338 tracked, 119 done. 51 new tests, 0 regressions.**
Thirteen licence texts added and every one fetched at a version, not typed. The list came out
of the shipped bytes — webpack left 1,736 module paths in the blob — so `check-licences.py`
rule 7 recomputes it in CI instead of trusting a comment. Two bugs fell out. **`B45`**: the
vendored `html2pdf` bundle is not upstream's, by exactly one string in jsPDF's language table,
inherited at the fork baseline and recorded nowhere. **`B46`**: rule 7's first draft read a
hardcoded list of bundles, a mutation that emptied the list survived, and rewriting it to
derive the list from the tree immediately found that `mermaid.min.js` is a bundle too — three
Microsoft `vscode-*` packages with no notice anywhere. DOMPurify's dual offer is settled as
Apache-2.0 (`D-2026-09-07-01`), with Cure53's file shipped verbatim, both texts in it.

### P0-18 — 1,463 files that say what they are, and one that must not
`c44941f..HEAD`. **338 tracked, 118 done. 17 new tests, 0 regressions.**
`AGPL-3.0` and `AGPL-3.0-or-later` are different licences to anyone combining this with
something else, and which one Pantheon is under was stated **once**, in a README badge —
not in `NOTICE`, not in `package.json`, not on the container image, and in none of the
files. Now in all of them, as the identifier alone: `SPDX-FileCopyrightText: 2026 Panick`
on a file nobody here wrote would be the `GohuFont.ttf` mistake again (`P0-23`), and
`NOTICE` is already the authority on copyright. **`LICENSE` is deliberately not touched** —
its own second paragraph says changing it is not allowed, so the row's "state it in
`LICENSE`" is refused and the refusal is on the row. `.pantheon/check-spdx.py` enforces both
directions; the second — *no vendored file carries our identifier* — is the one `P0-16`
already got wrong once, pointed the other way.

### P0-31 closes — five red tests were the row, and one green one was worse
`29accaf..HEAD`. **338 tracked, 117 done. 7 new tests, 5 pre-existing failures fixed.**
The standing failure count goes **19 → 14**, and it was never flake: four fixtures asserted
`ody-math-pending` at a `pan-math-pending` module and one watched the wrong `localStorage`
bucket, since `P0-04`'s sweep. A sixth file was green and wrong — it retyped the constants it
spliced real functions out of, so it tested a key the product does not use. All read the
module now. **A kind the row never listed:** the agent's persistent shell was
`ody-agent-<session>`, and that name is how a *running* tmux session is found, so a rename
abandons a live shell and leaks the process — mint `pan-agent-`, adopt `ody-agent-`.
`.pantheon/check-fork-names.py` turns the row's `Verify:` into CI: comments and docstrings
excluded so history survives, 23 deliberate hits named with reasons, stale excuses fail too.

### P0-31 (part) — `pan_`, and every `ody_` token still works
`022ec9b..29accaf`. **338 tracked, 116 done. 10 new tests, 0 regressions.**
The fork's old name was on the one string this product asks you to paste into another
machine. `B43` had already put the prefix behind one constant, so the code half was two
values: mint `pan_`, honour both. **The second value is the row.** A rename revokes every
token issued before today — a phone that cannot be re-paired without holding it, a scrape
config that starts 401ing at 3am — and does it silently, on upgrade. Five shipped examples
that printed `ody_…` to a first-time user updated with it. `P0-31` stays open: the fixture
residue is next, and **five of the nineteen standing suite failures turn out to be exactly
that** — `test_markdown_lazy_lib_loading_js` pinning `ody-math-pending` against a
`pan-math-pending` module, and `test_pr6020_browser_review_regressions` keying a stub
`localStorage` on `ody-session-cost-runs`.

### B43 — a token the tool could mint but the door would not open, and one it could not shut
`79d18ef..022ec9b`. **338 tracked, 116 done. 16 new tests, 0 regressions.**
Counting `P0-31`'s mint sites found a third one the row never named, and it was broken three
ways: no prefix, no owner, no cache invalidation. The first two fail closed. The third fails
open — `manage_tokens delete` said *"Deleted token"* and the token went on authenticating out
of the middleware's in-memory map until the next restart, because a tool running in the model
loop has no `Request` to reach `app.state.invalidate_token_cache` through. `core/api_tokens.py`
is the shared thing the four sites now have: the minted prefix, the separately-named accepted
prefixes, and a process-level invalidator registry. That also makes `P0-31`'s rename a
two-value change instead of a four-file one.

### B26 — the guard that ran before first paint, and matched nothing
`e17dd93..79d18ef`. **338 tracked, 116 done. 5 new tests, 0 regressions.**
Sixteen CSS selectors read three `html.ody-…` classes that `P0-04`'s rename had already
turned into `pan-…` on the writing side, so the pre-paint sidebar guard had been dead
since the sweep — a visible flash on every cold load for anyone whose sidebar is off or
mini. `B26` said ten selectors in `static/style.css`; there are six more in
`static/index.html`'s inline `<style>`, in the same file the row cites for the writers.
`tests/test_root_class_wiring.py` is the guard, and it joins the two sides in both
directions. **`:root.light` is the finding it turned up and did not fix**: seven rules,
no writer, and none at the fork point either — pre-existing upstream, so it is named in
the test's allowlist with the reason rather than deleted (`Law 1`).

### P3-20 — the 124 is not a backlog, and the row that said so was mine
`48825ac..HEAD`. **338 tracked, 135 done. No code change.**

The ids were classified by how each is reached rather than by prefix. **At least 87 of 124 are guarded
by construction** — JS that knows the markup may be absent and returns early. That is a feature removed
cleanly, not drift. About ten more are dead `||` fallbacks that harm nothing, eleven sit in the two
genuinely uncalled functions, and the residue is small.

The classifier ran four times and the number fell every time — 38 → 20 → 16 — because each pass found
another guard spelling it had missed. Spot-checking the last sixteen found more false positives:
`notes-panel` is a modal-registry key, not an element id at all.

So the row's `Verify` was wrong, and I wrote it. Bringing the ceiling down means deleting guarded code
that costs nothing. **The value is the ratchet, not the number**: it cannot grow, so a new id with no
markup surfaces on the day it is written — which is how `H02`'s rail button and `H07`'s dead CardDAV
block would have been caught the first time.

### H18 — the last of the settings the model could change and you could not
`dfd152a..HEAD`. **338 tracked, 135 done. Suite 7,314 → 7,333 passing.**

Eight controls, and two deliberate exceptions. The interesting one is the token budget:
`agent_input_token_budget: 6000` is a **sentinel** meaning "scale to the model's window", not a cap of
6000 — so a plain number box would let someone type 6000 meaning a cap and silently get auto. It is a
mode picker, 0 is reachable as the documented "no trimming" value, and typing 6000 as a fixed budget is
refused with the setting's own advice. A test pins the sentinel against `context_budget.DEFAULT_BUDGET`,
because the two live in different files with nothing joining them.

`search_safesearch` had seventeen lines of documentation that reached nobody, including the two
exceptions nobody could have guessed — Tavily has no such knob, and a custom backend keeps its own
behaviour. Those are the sentences the panel now says out loud.

`teacher_tier2_enabled` deliberately keeps none: its card is hidden by a decision written in
`index.html`, and adding a switch for one field of a parked feature would re-open that decision
sideways. **This closes the last open `H` row** apart from `H21`, which is verified and parked under
`Law 1`.

### H19, H20 — four copies of one map, three of another, and a find bar with no door
`d02a645..HEAD`. **338 tracked, 134 done. Suite 7,294 → 7,314 passing.**

`/shortcuts` printed seven shortcuts against a runtime twenty-one, **invented two actions bound to
nothing anywhere**, omitted fourteen real ones, and gave the wrong combo for `toggle_sidebar` — which
the Shortcuts panel also got wrong, from its own second copy of the same table. One registry now,
exported from the module that runs and imported by the other two, with `/shortcuts` generated from it
and unbound actions skipped rather than printed with a blank key.

`H20` needed that first: Find is in the registry, the panel and `/shortcuts` both name it, and the
document header has a button beside Undo. The editor reads the keybind rather than hardcoding Ctrl+F,
because an entry the editor ignored would be worse than no entry — the panel would offer to change a key
and nothing would change. The global dispatcher still does not bind it; Ctrl+F outside a document is the
browser's.

`H19`'s other half landed in the same change. `hidden: true` filters from **both** `/help` and the
autocomplete, so the three diagnostics had no door; they are un-hidden into a `Diagnostics` category,
and `/sh` is safe to surface because its route is admin-gated server-side — hiding it was obscurity.

And `/toggle rag` exists. The row calls it a handler with no registry entry; it is also a handler that
could not have worked, because the `toggleMap` it reads had no `rag` key. **There were four copies of
that map** — one complete, three missing entries — which is the same disease as the keybind table, in
the same file, found while fixing it.

Fourth Law 20 trap this session, and the first one caught by my own test before it shipped rather than
after: two assertions matched a word that the comment recording the defect necessarily contains.

### B42 — the agent could take off its own gates
`0ea6486..HEAD`. **337 tracked, 132 done. Suite 7,280 → 7,294 passing.**

`H18` reads `agent_email_confirm` as a setting with no control. It is that, and it is also one the
**agent** could set: measured on the stored value, `manage_settings set agent_email_confirm false` moved
it True → False. The agent could remove the gate requiring a person to approve an email before it sends
— through a tool call indistinguishable from the operator's own request, which is exactly what an
injected instruction produces.

`_SELF_RESTRAINT_KEYS`, the same shape as the `_SECRET_KEYS` set already beside it. The refusal names
the setting, says where to change it, and says it survives being asked politely. `reset` is refused too,
even though it writes the safe default today, because "only in the safe direction" inverts the day
someone changes a default.

**`trust_rung` was in the first version and is not in the shipped one.** The write took effect, but
`allow_listed` asks in clean runs the default lets through, the rungs have no total order — the file
itself records an incident where the "stricter" rungs were less protected — and a deliberate test sets
the strictest rung from chat because a person asking for more confirmation is a real request. Six suite
failures caught it. One gate the agent could take off, not two. `P7-13`.

The trade only works because the person gains the control, so `agent_email_confirm` gets a switch in
Settings → Email that says in the panel that the agent cannot turn it off. `P7-12` is the loop caps,
deliberately left writable and left to the owner.

### H04, H16 — the manager gets pixels, and four keys get past the allowlist
`901ac61..HEAD`. **336 tracked, 132 done. Suite 7,244 → 7,280 passing.** `check-unreachable` 96 → 91.

`H04`: a finished, admin-gated embedding-model manager with no markup at all. Settings → Embeddings now,
leading with what is in use rather than with a list — because `fastembed` and `chromadb` are both
optional, a clean install has neither, and then memory and document search fall back to the keyword
scorer `B40` found ranking by "contains two consecutive capitalised words". A missing optional dependency
is a state with an explanation and an install line, not an error. Where a route refuses — deleting the
model in use, an endpoint URL that breaks a rule — its own words are shown rather than flattened.

`H16`: `DEFAULT_SETTINGS` is an allowlist, not a list of defaults. The settings route iterates it, so
four keys read by live code and absent from it were dropped from every save in silence. Declared with
the exact fallbacks their readers already used, clamped where they feed a loop, and given switches.
`tool_path_extra_roots` deliberately gets none — the row's own second option, and a test now fails if a
control appears without someone arguing for it first.

Two defect-pinning tests turned round rather than deleted, `H04`'s and `H10`'s. A ratchet that has run
out of real orphans to point at is exactly when its own fixture tests matter most.

### H12 — the vote history stops living in one browser
`0efc4d0..HEAD`. **336 tracked, 130 done. Suite 7,222 → 7,244 passing.**

The Scoreboard read browser storage while `POST /api/compare/record` wrote a server row nothing ever
read back, and `GET /api/compare/history` and `DELETE /api/compare/{id}` had no caller at all. Two
copies, drifting in both directions, and nothing saying which one you were looking at: clear your site
data and the visible history vanished while the server kept every vote; vote from a second browser and
the Scoreboard disagreed with itself.

The join is `server_id` — an id the record endpoint has always returned and the browser has always
thrown away. Costs and mode now travel with the vote, because they are what the Scoreboard needs and
the browser was their only holder. Clear History clears both. Every vote already in the table survives
the change, including the genuinely different blob shape the full comparison flow writes into the same
column — which is `P13-12`.

The Scoreboard now says whether it is showing the synced history or this browser's copy. That is the
row's real lesson: the numbers were never wrong, there were two of them, and a silent fallback would
have been the same defect with better plumbing.

### H13, Law 20 — the album verb, and the third grep that lied
`bbc41ec..HEAD`. **335 tracked, 129 done. Suite 7,211 → 7,222 passing.** `check-unreachable` 100 → 98.

The gallery could move images into albums since before the fork and never offered it. The row's own
correction was the useful part: the handle is the image bulk bar, whose `_selectedIds()` already returns
exactly the array the endpoint wants, so *Album…* is one more entry in a list. The picker is a second
page of the same dropdown rather than a second dropdown, remove is offered only inside an album, and
album names are the first user-supplied text this menu has ever rendered — so `textContent`.

`Law 20` is the session's third self-inflicted lesson, and the one that cost the most: `H02` asserted a
sentence was gone and the corrected comment quotes it; `H10` asserted `innerHTML` was absent and the
comment saying not to use it contains the word; `B41` asserted a line existed and it did — in a
different function, where the variable beside it was out of scope. A source file is code and prose about
code interleaved, and grep can tell you neither which it found nor what scope it landed in.

### H11 — you can now ask why a memory would fire, before sending the message
`b24f645..HEAD`. **335 tracked, 128 done. Suite 7,187 → 7,211 passing.**

The Brain's search box gets a second mode. *Contains* is the substring filter it has always been;
**Would fire** runs the real retriever and reports what it would return and why. `POST /api/memory/debug`
was live and callerless, and could only ever answer the *which* — the score and the boost were computed
and dropped on the scorer's last line. `explain_relevant_memories` keeps them; `get_relevant_memories`
is now a wrapper over it with its contract for five callers unchanged.

The reason that matters most is the one saying a memory was admitted at 0.9 **without being scored** —
invisible from the ranking, and exactly the behaviour that was hiding `B40`. Writing truthful reasons is
what found it.

The `timeline` and `by-session` routes are still unwired, and that is stated in the row rather than
papered over: neither is the `Verify`, and bolting them into this modal to close a row would be the
second scaffolding `Law 14` exists to prevent.

### B40 — the Brain ranked memories by "contains two consecutive capitalised words"
`96651e4..HEAD`. **335 tracked, 127 done. Suite 7,173 → 7,187 passing.**

Found while building `H11`, the row about showing a person *why* a memory fired — which is exactly the
view that makes this impossible to miss. `identity_words` contains `"i"`, and the check was a substring
test, so "what **i**s the weather" was an identity question and **ten of ten ordinary queries classified
as identity**. Every memory containing two consecutive capitalised words — *Bridge Street*, *Docker
Compose* — was then admitted at 0.9 ahead of anything scored on similarity, and identity memories were
excluded from scoring entirely otherwise, so `Afrog Labs` could not retrieve *"Joseph Jeffrey works at
Afrog Labs"*.

Reproduced with nine memories: *"what is the build timeout"* did not retrieve the memory containing the
answer at `top_k=5` or `top_k=8`. It now leads. And this is not a fallback nobody hits — ChromaDB is an
optional dependency, so on a clean install this scorer is the only memory retrieval there is.

The deliberate half is untouched: identity memories still bypass similarity for genuine identity
queries, exactly as the original comment asks. `P13-11` is the two judgements this did not make.

### H10 — session cleanup had a dry run and no door
`fbb7092..HEAD`. **334 tracked, 127 done. Suite 7,162 → 7,173 passing.**

`GET /api/cleanup/preview` and `POST /api/cleanup` have been live and owner-scoped with no caller in
`static/` at all. The preview is the reason this belongs above the Danger Zone rather than in it: it
names what it would archive, what it would delete, and what it is sparing **with the reason**. All three
groups render; Run stays hidden until a preview finds something; the confirm is `danger` only when a
deletion will actually happen. The row's "under-10-message" was wrong — the constant is 20 — and the
panel's prose is now asserted against the constants so it cannot drift.

Two things recorded rather than fixed: a flat `app.routes` walk claims these routes are unmounted (they
are not — this FastAPI wraps included routers, the same false alarm that shaped `check-unreachable.py`),
and `initRag`/`initWebhookForm` are ~250 lines of `admin.js` that were dropped from the init list rather
than deleted. The second is worked triage for `P3-20`, and it means `H16`'s "webhooks UI is absent" is
really "webhooks UI is unmounted".

### B39 — Ollama was the only route where the prompt and the transport disagreed
`16a0351..HEAD`. **334 tracked, 126 done. Suite 7,148 → 7,162 passing.**

Filed as needing the owner, then measured, and the measurement made it a bug rather than a decision.
On a default Ollama endpoint no schemas are sent, the fenced parser is the only live channel, and the
compact prompt told the model not to use it — every tool unreachable, in silence. The apparent trade
(prompt size on the machines with least room) turned out not to exist: llama.cpp with a `gpt-oss` model
is also `is_api_model=False` and already gets the full fenced prompt. Ollama was the anomaly.
Measured across seven route shapes before and after: `compact=is_api` changes the two Ollama rows and
nothing else. `P3-22` is what is still missing — no way for an admin to declare `supports_tools`.

### H08, H09 — two prompts and a cap that told the model something untrue
`fae4a12..HEAD`. **333 tracked, 126 done. Suite 7,033 → 7,148 passing.** One suite run verified both
rows, so they are one commit: a tree that was never tested alone should not be a commit on its own.

`H08`: local inference lifted the agent's round limit to 100,000 and the stream timeout to 24 hours,
which is right on your own GPU — but it did not tell a shipped default from a number a person entered.
`agent_max_rounds` is validated to 1..200 by the admin endpoint and re-clamped in `chat_routes` with a
comment about defending against hand-edits, and then replaced. `setting_is_explicit` again, third
caller. The off-switch, which appeared nowhere outside the module that read it, is now in `.env.example`.

`H09`: `generate_image` and `manage_research` are the only members of `TOOL_SECTIONS` with no
`FUNCTION_TOOL_SCHEMAS` entry, so no schema was sent and the fenced fallback was shut — both channels
closed, both names offered, to a model the same prompt tells to say what is missing instead of
pretending. Fixed as the guard the row asked for rather than as two names.

Two things came out of it that belong to the owner. `B39`: on a **default** Ollama endpoint no schemas
are sent at all and the compact prompt still goes out, so the model is told to use native calls it does
not have and not to write the fenced syntax that is the only channel being parsed. `P3-21`: the same
lift flattens every preset's `max_tokens` to 1,000,000, which makes the preset picker cosmetic on local.

`B38` is mine. Extracting `_resolve_local_lifts` left a `NameError` in the hot loop that 20 tests, 16
mutations and eight checkers were all green for — the test covering the call site matched source text,
and the text was correct while the name was not in scope. 96 full-suite failures found it.
`test_agent_loop_names_resolve.py` resolves every free name in every top-level function of
`agent_loop.py`, and found a second thing on its first run: a lambda parameter its own walker missed.

### H06, H07 — a fallback written as a default argument fires on absence, not on blank
`60e1387..HEAD`. **332 tracked, 124 done. Suite 6,991 → 7,033 passing.**

`PANTHEON_TASK_CONCURRENCY_CAP` had never worked on any install: the resolver asked "did the operator
set this?" with `get_setting(KEY, None)`, and `load_settings` merges the defaults on every read, so
the env leg beneath it was unreachable code from first boot. CardDAV asked the same question with
`settings.get(k, os.environ.get(K, ""))`, and Remove writes three empty strings. Neither existing
helper could fix it — `is_setting_overridden` is blind after a save, `budget_is_explicit` is blind
before one — so `setting_is_explicit` is both, and `env_backed` is the string form. Ten more latent
instances in the mail config are fixed before they fire.

None of it was caught because `check-wiring.py` read only literal `getElementById` and this codebase
reaches for elements through a helper at 925 call sites. Blind spot 4 closed: `--max 9` → `--max 124`
with no product code changing. The backlog is `P3-20`. `Law 19` is the cost of learning that a suite
run is evidence about the tree it started with.

### H02 — 475 lines of assistant behind two doors that did not open
`2d378d8..60e1387`. **Suite 6,975 → 6,991 passing.**

`openAssistantChat()` had zero callers repo-wide, and the gear that reached the settings modal was
built by a poll gated on `sessionModule.getActiveSession()` — a method that occurs exactly once in
this repository, at that call site. So the poll's only effect was 120 wasted ticks per page load.
A rail button now calls the chat, and the gear rides a new `pantheon:session-changed` event instead
of a timer. The comment claiming the views had moved into `tasks.js` is corrected, not deleted:
that sentence is why nobody looked.

### H03 — four advertised actions, four URLs that did not exist
`bc2571c..HEAD`. **Suite 6,975 → 6,991 passing.**

`edit_image` offered upscale, rembg, inpaint and harmonize, and posted all four to
`/api/gallery/{action}` — none of which is a route. Every call 405'd and the model was told
"upscale failed", with no hint the URL was wrong. All the capabilities were real under other names,
with three different body shapes; `inpaint` needs a mask a tool call cannot draw and is no longer
advertised.

### H14, H15, H17 — three sentences the product was telling that were not true
`e0e69a3..HEAD`. **Suite 6,962 → 6,975 passing.**

A tooltip naming a gesture that does not open the SIGKILL panel; a Settings search that indexed 13
panel labels and none of the 96 controls, leaving the app's only privacy control unfindable by any
word in its own label; an admin switch wired to the endpoint whose own docstring calls it unsafe,
and a webhook secret you could copy but not rotate.

### P3-15 — the audit, as a script, and the fix that ate half a file
`30bbff6..HEAD`. **Suite 6,939 → 6,962 passing.**

`.pantheon/check-unreachable.py` rediscovers `H04` and `H10` from a clean checkout with no hints,
which is the row's `Verify` line. Getting there needed the walk to follow `original_router` — the
naive recursion reports 23 of 443 routes while looking correct — and needed `check-wiring`'s three
blind spots closed first, one of whose fixes silently deleted 55% of `gallery.js` before the test
that measures output length caught it.

### H05 — seven switches that did nothing, and the one line that undid the eighth
`ffb88f2..HEAD`. **Suite 6,913 → 6,939 passing.**

A feature is three things — a tool the agent can call, a route that answers, and a button — and the
flags governed only the button. They do all three now. The client-side half did not work either:
the fetch hid nine elements and `applyUIVis` showed seven of them again in the same callback, both
halves deliberate, which made it a question of precedence rather than ordering.

### H01 — the screen the agent had been promising for a year
`044b233..HEAD`. **Suite 6,868 → 6,913 passing.**

Three places said an approval surface existed — a route comment, a docstring, and the model's own
tool description, which told users their mail was waiting for them there. None of them was true.
Building it found the defect the card would have inherited: the endpoint returned the message
without its recipients, so the first thing anyone approved would have been a blind copy they could
not see.

### P15-06 — the operator's own machines are not a destination
`682ace6..HEAD`. **Suite 6,829 → 6,868 passing.**

The precondition turned out to be the interesting part: routing the local-first services through the
limiter is a performance regression until loopback, private space and the tailnet are paced at zero,
and `.pantheon/check-outbound.py` then found four unpaced calls to hosts that already throttle us —
including the DuckDuckGo fallback, where a 429 was being recorded and never honoured.

### P15-10 — the fix was easy; the checker was the row
`994afd7..HEAD`. **Suite 6,807 → 6,829 passing.**

Every recurring job is spread now, but the finding that mattered is that the row's own hand audit
undercounted by more than half: `.pantheon/check-jitter.py` found twelve more sites, two of them
real, and then caught five stale entries in its own author's allowlist on the first run.

### P15-09 — the clock you persist is not the clock you read it back with
`f093f26..HEAD`. **Suite 6,782 → 6,807 passing, the same 19 failing.**

Cooldowns survive a restart, which required storing a wall-clock deadline rather than the monotonic
reading held in memory — the naive version works on a box that only restarted the app and fails on
the one that rebooted, which is the only case the row is about.

### P16-19 — the push half, and every bug in it is silent
`d94d257..HEAD`. **Suite 6,711 → 6,782 passing, the same 19 failing.**

One address that ships empty and is enforced empty, one set of collectors feeding two wire formats,
and a JSON encoder written by hand because every mistake it can make — a uint64 as a number, a `NaN`
token, a `200` that delivered nothing — is accepted locally and lost at the collector.

### P4-27 — the interesting bug was over-redaction
`cdbda76..HEAD`. **Suite 6,704 → 6,711 passing, the same 19 failing.**

A receipt you can hand to someone, built by extending `P16-14`'s bundle rather than growing a second
exporter — "make something a person can hand over, with nothing of theirs in it" already had an
owner.

**The bug worth reading was over-redaction.** A `run_id` is 32 hex characters, exactly the shape the
opaque-string rule catches, so the first version redacted the one field that lets two people point
at the same run — a document whose subject was `<redacted>`. Redaction is field-by-field now with an
identifier exemption: redacting a serialised blob cannot tell an endpoint's hostname from a run's
identity and treats both the same.

**A mutation survived and was worth more than the ones that didn't.** My credential test asserted on
an endpoint label — which `events._safe_label` already sanitises at write — so it passed with this
module's redaction removed entirely. It proved the earlier layer, not this one. It asserts on a
skill name now: operator free text that nothing else touches.

**`B34`, closed at the right level.** `mark_turn_start()` is idempotent within a turn, which is
correct in production and a trap under pytest where everything shares one context. A helper that
seeded a run left the ContextVar set, and another module's test went red *only when the two happened
to sort in that order*. Fixed in `conftest.py` with an autouse reset — fixing the one offending
helper would have left the trap armed for whoever writes the next one.

### P4-28 and P14-04 — the classification is the product
`4b97fd5..HEAD`. **Suite 6,681 → 6,704 passing, the same 19 failing.**

Two receipts differ in dozens of ways that mean nothing. A diff that lists them all is one nobody
reads twice — worse than no diff, because it was paid for. So every difference is **chosen** (the
operator asked), **inflicted** (the world moved), **outcome** (what the run produced), or **noise**.

`P4-26`'s `deliberate` field is what lets chosen and inflicted be told apart rather than guessed
from the shape of the change — the return on having recorded it two rows ago. And the tool hash from
`P4-25` earns its keep here: a schema that changed under an unchanged name is invisible without one.

**The headline leads with the unasked-for changes**, and that ordering is the argument — putting
outcome first buries the cause under its own consequences.

`P14-04` then had almost nothing left to do, which was the point of the sequencing. A failing eval
case now carries the diff's headline and the inflicted differences: *"case 3 failed"* sends someone
to read a transcript, *"case 3 failed, and the tool schema changed"* is the answer. Failures only —
diffing passes doubles the cost of a green suite to produce something nobody opens.

**A gap found while building it:** `P4-26` recorded `replay` rows carrying the link back to the
original run, and `receipt()` dropped them on the way out. Stored, and unreadable through the only
API that reads receipts.

### P14-03 — the thing that replaces the vibes
`7994d28..HEAD`. **Suite 6,660 → 6,681 passing, the same 19 failing.**

A suite is a list of `run_id`s and what the operator expects; running one is `replay()` in a loop.
No case store, no runner, no second copy of the configuration — `P4-25` and `P4-26` had already
built all three.

**Assertions are deterministic and the operator writes them.** Not a judge model: a harness whose
first answer to "did that change help" is itself non-deterministic has replaced vibes with dearer
vibes. `P14-08` is filed for when a judge earns its place, with the questions to settle first —
whose model, at what temperature, paid for by whom.

**The decision that matters: a case that could not be reproduced is neither a pass nor a fail.** It
is skipped and counted separately. Folding it into *failed* makes a broken environment look like a
regression; folding it into *passed* is worse, because it is quiet. A suite where nothing ran
refuses to print a rate at all.

**Checks are an allowlist**, so a typo refuses the suite before a model call rather than silently
never running — a suite passing for the wrong reason is the one failure mode of an eval harness that
costs anything, because nobody investigates a pass.

One mutation survived and found a decorative defence: `score_case` ended `else error is None`, which
reads like it handles the errored case and is unreachable whenever there is one.

### P4-26 — a re-run is what proves the receipt was enough
`7f10ad8..HEAD`. **Suite 6,638 → 6,660 passing, the same 19 failing.**

`rerun_plan()` reads a receipt and says what it would take; `replay()` runs it as a new run that
links back. GET is free so the claim can be checked before a model call is spent on it.

**A receipt is not enough on its own, and that is by design.** `P4-25` keeps message content out —
which is what makes one portable — so a replay joins the receipt's configuration to the session's
inputs, and **a receipt exported to somebody else cannot be re-run by them.** Stated in the drift
line rather than discovered later by someone running a shorter conversation.

**Drift is the product.** "Same configuration" is a claim; a model can be gone, a skill edited, a
confidence moved. Substituting silently would make every answer this row exists to give a lie, so
the plan reports what it cannot reproduce and the replay records it — letting `P4-28` tell a
difference that was *chosen* from one that was *inflicted*.

**A replay never touches the session.** It is a diagnostic; appending its output would change the
thing being measured and put a machine-generated turn in front of the person next time they
scrolled up.

**Correction first (`B33`):** `P4-25` recorded a config for streamed turns only — `/api/chat` never
streams, so half the chat surface had `config: null`, and my test grepped the file for the call,
which one entry point satisfies. One helper, all three entry points, before the cache check. Fixing
it then reproduced `B32` in a new file, which this time raised loudly because the guard moved inside
the helper. The scope test is parameterised over every capturing module now — *a test written to the
shape of one bug catches one bug.*

`P14-03` is unblocked: a case is a receipt, a run is a re-run, and the harness is now scoring
replays rather than building a store.

### P4-25 — the three things that explain why two runs differ
`ac53d94..HEAD`. **Suite 6,617 → 6,638 passing, the same 19 failing.**

Re-measured before building, as the row's own corrected premise demands. It said five of eight items
persist; after `P14-01` and `P14-02`, **seven** do — the loop instrumentation picked up approvals and
tool outcomes on its way past. The remainder is exactly three, and they are the three that explain
why two runs of the same thing come out different: **resolved sampling parameters, the tool schemas
actually sent, and which skills were injected at what confidence.**

**No third store.** `events` gains a `run_id`, one `run_config` row per turn holds the three, and a
receipt is a range scan over rows that were already being written.

**Tool schemas are name + hash, not the schemas.** The point is to make a *change* visible; full
schemas are kilobytes each and dozens per turn, and `P4-28`'s diff reads a changed hash exactly as
well as a changed blob. Order-independent, because a shuffled tool list is not a different
configuration and a diff that claims otherwise gets ignored.

**No message content reaches a receipt** — which is the whole of what makes `P4-27` possible. Sampling
is an allowlist, because the payload it filters contains the prompt.

**`B32`, caught before it shipped:** the skills capture referenced a name that isn't in scope there,
and the `except Exception` that keeps a receipt from breaking a reply would have swallowed the
`NameError` forever — recording nothing, silently. The guard that makes instrumentation safe is the
same guard that makes broken instrumentation invisible. There is an AST test resolving every name at
that call site now.

**And `P14-03` is blocked, checked rather than assumed.** `P14-04` says a saved case *is* a receipt
and a run *is* a re-run. Building a case store now would be the second scaffolding that row exists to
prevent. `P4-26` is the real prerequisite.

### P14-05 — what did last Tuesday cost
`3fed404..HEAD`. **Suite 6,598 → 6,617 passing, the same 19 failing.**

The question that started `P14`. The session row always knew a conversation's total; it threw the
timestamp away. `usage_over_time()` returns daily buckets by model and by owner, and a collapsed
panel in Settings draws them.

**Quiet days are filled in**, and that is the property worth naming: a series that omits a day with
no traffic draws a straight line from Monday to Wednesday, and a gap that reads as continuity is the
one way a usage chart actively misleads.

**Only `llm_round` rows are counted** — `P14-02` put tool calls and retrievals in the same table, and
a usage number that silently includes them reconciles with nothing. Models are ordered by cost, not
name. Unattributed rounds are labelled rather than dropped.

**No charting library.** One series of daily totals, inline SVG, DOM calls — vendoring a dependency
to draw rectangles is a dependency for what the browser already does. The bars carry an accessible
name with the numbers in it.

**And the fold with `P12-08` is undone, on evidence.** That row needs the operator's limit *field* to
sit next to, and `P12-07` — the admin surface that would hold it — is not built. The fold assumed
both halves would land together; only one could, and a folded row cannot be half-ticked. `P12-08` is
open again with the dataset already built for it.

`B31`: a test of mine sliced "everything between two functions I know about" and blamed the
self-check panel for code that landed in the gap — failing on a *comment* that said "never
innerHTML". Brace-matched and comment-stripped now, and still red when the real violation returns.

### P16-16 — two segments, and a run that cannot cross between them
`1d43204..HEAD`. **Suite 6,574 → 6,598 passing, the same 19 failing.**

Discovery returned one flat list of hosts with no notion of which network anything was on, so there
was nothing to scope. `src/networks.py` gives segments names, hosts, CIDRs and trust, and binds a
run to a set of them.

**Ships declaring nothing, and nothing declared changes nothing.** `Law 16` is about defaults, not
capability — a network the operator *named* is one they linked.

**Enforced at three independent layers**, because a caller that skips one should still be caught:
the URL gate, the pinned fetch path, and both limiter `acquire` paths. **Refused before DNS** —
rejecting after a lookup has told the other network's resolver we asked is a boundary that leaks the
question it exists to prevent.

**A host in no declared network is refused too.** "I could not classify it" is not a reason to
permit reach.

**CIDRs classify; listed hosts are scanned.** A `/16` is 65,536 addresses, and expanding a
declaration into a sweep is how "discover my networks" becomes a port scan someone's IDS reports.

**And what it does not do is written down rather than implied.** It is not an OS-level control: a
shell tool running `curl` reaches whatever the process has a route to. That needs a network
namespace, not a Python function — filed as `P16-20`, with a test that fails if the disclosure is
ever removed. A boundary described as tighter than it is, is worse than one described accurately,
because people plan around the description.

### P16-12 — a scrape has no destination
`e94a42c..HEAD`. **Suite 6,549 → 6,569 passing, the same 19 failing.**

`GET /metrics`, off by default. Point Prometheus at it and Grafana shows throughput, token cost,
turn latency, tool failures, retrieval misses, unanswered approvals, self-check state, outbound
cooldowns and queue depth.

**`Law 16` clause 4 is satisfied by the shape of a pull, not by a promise.** There is no collector
address in the module and no place for one; a test walks the AST and fails on an outbound import or
a `://` literal.

**No `prometheus_client`.** The exposition format is a name, labels and a number — taking a hard
dependency to do string formatting, here, would be the wrong trade.

**Everything is a gauge, and that is the decision worth reading.** A counter must be monotonic, and
retention pruning makes a `_total` from the events table decline *gradually* as rows age out —
neither a reset nor a real rate, and `rate()` over it is wrong in a way nobody notices. The windowed
numbers say their window in the name.

**Auth reuses the API-token system** rather than building a second one: a read-only `metrics:read`
scope, which Prometheus sends natively. Disabled returns 404, not 403 — off should look like never
built.

**And a defect caught before it ran anywhere (`B30`).** The scrape called `run_self_checks()`
every time, and one of those checks asks the embedding server over HTTP whether it is alive. At a
15-second interval that is 240 requests an hour to the operator's own machine — the exact thing this
module refuses liveness probing to avoid, one layer down where its own test could not see it. Cached
for 60 seconds now, with the age exposed so nobody reads a cached number as live, and a test that
stubs `socket` and fails any collector that reaches the network.

Three mutations survived, and two were the same trap in a new place: **the module's own docstring
being read as code.** It explains at length why `requests`, `service_health` and `prometheus_client`
are absent, so a substring search found those words in the prose — and then the same thing hid a
**deleted scope gate**, because the handler's docstring names `metrics:read`. Both parse the AST
now. The third found the `# TYPE` de-duplication guard to be dead code; it is kept and tested
directly, because declaring a metric inside its own loop is the natural mistake and a duplicate
`# TYPE` is a parse error in strict scrapers.

The push half — OTLP to an operator's collector — is `P16-19`, filed rather than folded in.

### P14-02 — the rest of the loop, and a metric that would have lied
`52d5b11..HEAD`. **Suite 6,530 → 6,549 passing, the same 19 failing.**

Latency, tool calls, retrieval and approvals all land in the same table `P14-01` opened. `events`
gains a `name` column through a real migration — `create_all` creates missing tables and never
alters one, and this table shipped a commit ago.

**The metric that would have lied.** Counting only tool *exceptions* would have reported a 0%
failure rate, because almost every tool in this codebase reports errors by returning
`{"error": ...}`. A reassuring number is worse than no number. `ok`, `error` and `exception` are
three outcomes.

**Retrieval keeps `unavailable` and `empty` apart.** Nothing came back because the store is down,
and nothing came back because nothing matched, look identical to a user and are different bugs.

**Latency is honest about what it measures** — the whole turn, tool calls and retries included, not
time in the model — and a missing measurement is `NULL`, never `0`. Zero would sit in a dashboard
looking like the best turn ever recorded.

**Queue depth is not here, and the row's framing is corrected rather than quietly satisfied.** It is
a gauge, not an event; writing it into an append-only log would be sampling something you can just
ask for. It belongs in `P16-12`'s scrape endpoint.

**And two bugs in `P14-01`, found by reviewing it a day later.** Pruning never ran on a freshly
booted machine — `_last_prune = 0.0` against `time.monotonic()`, which counts from boot (`B28`).
And `usage_summary` pulled every event in the window into Python to add integers, on a table
designed to accumulate (`B29`). Both fixed, both with tests that catch the original.

### P14-01 — the time dimension, written down
`797b832..HEAD`. **Suite 6,512 → 6,530 passing, the same 19 failing.**

`Session` carried `message_count` and token totals as **running counters on a row**. So Pantheon
knew what a conversation had cost in total and could never say what it cost on Tuesday, whether one
model was cheaper than another, or whether a change helped. The query was never the hard part. The
event was not recorded.

`Event` now is: ts, kind, session, owner, model, endpoint, tokens, duration, outcome, detail.
Written from `accumulate_token_usage` — the one place four call paths already converge, which is
what the 2026-08-27 premise correction bought — and **before its early return**, because
`if not (in_t or out_t): return` is precisely what discards failed rounds.

**Its own database session, swallowing everything.** Measuring is worth nothing if the measured
thing stops working, and the counters worked before any of this existed.

**Shape, never content** (`D-2026-09-01-02`). No prompts, no responses, no thinking — which is what
makes `session_id` a plain column rather than a cascading foreign key. Deleting a session removes
the conversation; keeping its rows leaks nothing the deletion was for, and *"what did last month
cost"* survives tidying up. Retention ships finite at 90 days.

`duration_ms` is present and NULL. Round latency is not available at this insertion point; that is
`P14-02`, and the column ships now so that row needs no migration.

**Two survived mutations, both the same shape as always.** The zero-token test called the recorder
directly, so moving the write below the early return passed cleanly — the placement *is* the
behaviour. And nothing caught the terminal paths dropping `outcome="error"`, which files every
failure as a success in the one column that makes failure countable.

**And a bug the suite found that isolation never would: 18 tests passed alone, 10 failed together.**
The suite runs on `sqlite:///:memory:`, where every new connection is a *new empty database* — they
had been leaning on one pooled connection surviving the run. Each test builds its own file-backed
database now, which also stops them writing to and pruning the developer's real one.

### P16-10 — self-hosted search, and the sentence no setting can make true
`8cf6c6e..HEAD`. **Suite 6,505 → 6,512 passing, the same 19 failing.**

When a pinned SearXNG search returned nothing, the third retry dropped the `engines` parameter — and
`use_default_settings: true` handed the query to Google, DuckDuckGo, Brave and Startpage. The exact
engines an operator excluded *by pinning*. Silently, logged at INFO as a detail.

**The gate:** behind `searxng_widen_engines`, shipping off, registered in all five places. Not
removed — the same shape as `P16-01`'s inverted opt-out. The refusal names the engines tried, what
widening would reach, and the setting to flip.

**The documentation, because the gate cannot make the honest sentence true.** SearXNG has **no index
of its own**. Self-hosting it means the *aggregator* runs on your hardware, never that the searching
does — queries reach other people's engines by definition, and no setting changes that. `docs/setup.md`
now says so, along with the fact that the shipped pin `bing,mojeek,presearch` was chosen because the
usual defaults are CAPTCHA-blocked on a fresh instance, not because those three are more private.

Restricting engines in SearXNG's own config is the stronger guarantee and is documented as the
by-hand change. It is not shipped: the news category pins no engines, so a `keep_only` list tuned
for general search silently breaks news, and a default that breaks a working feature is worse than
the one it replaces.

**And a dependency nobody had checked.** `P16-12` says its source is `P14-01`'s events table.
`P14-01` is not done and that table does not exist — 30 tables in `core/database.py`, none of them
this one, and token totals are accumulated in memory and never persisted per request. Round latency
and token usage have nothing to read. The row stays **open behind `P14-01`** rather than being
half-ticked; what could ship today is a scrape endpoint over the self-checks, limiter and liveness
data that already exist and already have no reader, and that is a different row.

### P16-13 — the guard, armed before there is a hole
`055d2a8..HEAD`. **Suite 6,493 → 6,505 passing, the same 19 failing.**

`P16-12` will create the first legitimate place in this codebase for an outbound metrics URL, and
therefore the first place a well-meant default could land. `.pantheon/check-destinations.py` exists
so the answer is already no, and it is in CI beside the other ratchets.

**Allowlist over shape, not a denylist of vendor names.** Any absolute URL that ships as a default —
`DEFAULT_SETTINGS` at any nesting depth, `.env.example`, compose environment defaults — must be
local, an obvious placeholder, or listed with a written reason. `ALLOWED` ships empty. Every
telemetry vendor was new once, and the one that matters is the one nobody has heard of yet; the
known-host list survives as a cheap second layer with its weakness written into the file.

Baseline measured before ratcheting: **zero** absolute URLs in `DEFAULT_SETTINGS`, and all 32
elsewhere are loopback, RFC1918, tailnet, `host.docker.internal`, a compose service name, or
`your-domain.com`. `not ip.is_global`, not `is_private` — a tailnet is `100.64.0.0/10`, and that
mistake has already been made here once.

**Half the tests assert it does not fire.** A guard that cries wolf is a guard people learn to route
around, and `.env.example` legitimately links to Google's OAuth docs and quotes a Gmail scope
spelled as a URL. Both fired on the first version.

One mutation survived, and it was worth more than the four that did not. I had added a
`COMPOSE_DEFAULT` regex to close the `${VAR:-…}` hole; putting the hole back broke nothing, because
`classify()` only ever receives an extracted URL and the URL pattern excludes braces — the hole was
never open. The regex changed no result and is gone. What actually makes compose scannable is one
`lstrip("- ")`, and the test says so now instead of claiming credit for the regex.

### P16-14 — the bug report you can read before you send it
`573c00d..HEAD`. **Suite 6,466 → 6,493 passing, the same 19 failing.**

People do not report bugs because they do not know what to include and they are afraid of leaking
their own data. In this product the second fear is **correct**: a trace here carries the username
in every file path, the LAN in every endpoint, and often a slice of the message that failed.

So Pantheon writes the report, redacts it, and hands it back as **editable text on the person's own
screen**. Nothing transmits. There is no collector and no place in the endpoint for one; the
"open issue tracker" control is an `<a>` they click, carrying no report.

**Settings are allowlisted, and the measurement is the argument.** Filtering names on
`key|token|secret` across this tree's 71 settings flags three that are not secret and would miss a
credential named `openrouter_thing`. So ~20 feature flags show values; everything else reports only
its shape. A test plants a secret under an innocuous name and asserts it never appears.

**Half the tests assert what survives.** A bundle redacted into mush is not safe, it is useless —
and it fails while still looking like a bug report. Model names, short SHAs, timings, file and line
and the exception message all come through; `127.0.0.1` is exempt, because almost every report about
a local model server names it. Two of the eight mutations are *over*-redaction.

`issue_tracker_url` ships empty. A company running this as their own private stack points it at
their queue, and an empty default is also what keeps the env layer alive.

Also fixed, one commit after it shipped: `fetch-pyodide.py` wrote its own manifest through
`write_text`, which translates newlines per platform — so Linux and Windows produced files 16 bytes
apart. It passed because `.gitattributes` normalises text in the index. Git was covering for the
script, on the one file whose whole job is recording exact bytes (`B27`).

### P16-07 — the last CDN load, and the tightening that needed an addition
`7cb337b..HEAD`. **Suite 6,451 → 6,466 passing, the same 19 failing.**

Pyodide loaded from jsDelivr the moment someone ran a Python block, and **the feature did not
work anyway** — the CSP that let `pyodide.js` through blocked the `.wasm` fetch it makes next. A
request that left the machine and bought nothing.

**13.8 MB vendored: the runtime and the Python standard library, no packages.** `codeRunner.js`
never called `loadPackage`, so nothing else was ever being fetched. `indexURL` mattered as much as
`script.src` — Pyodide resolves the wasm, the stdlib zip and the lock file against it, so
repointing only the script tag would leave three of five files remote while a grep for `jsdelivr`
came back clean.

**Dropping the CDN required adding `'wasm-unsafe-eval'`.** No page with a `script-src` can compile
WebAssembly without it. Removing the host and stopping there would have moved the failure instead
of fixing it: no request leaves, and Python still does not run. `'unsafe-eval'` would also have
worked, and is far wider; there is a test that rejects it.

`cdn.jsdelivr.net` was in `script-src`, `style-src` **and** `font-src`. All three are gone. **The
policy now names no external host at all.**

**One artifact, verified before it is opened.** `scripts/fetch-pyodide.py` takes the npm registry
tarball, checks it against the registry's own `dist.integrity` *before* `tarfile.open` — verifying
after extraction verifies nothing — then checks every extracted file against a pinned hash, and
only then writes. All five were separately confirmed byte-identical to what jsDelivr serves.

The licence checker built one commit earlier refused this commit until Pyodide's MPL-2.0 paperwork
was in it. That is the whole reason it exists.

### P16-18 — the emoji stays; the paperwork was the thing that was wrong
`4f973fa..HEAD`. **Suite 6,441 → 6,451 passing, the same 19 failing.**

The instruction was *"make sure licenses are aligned, we can still use that emoji thing it could
add good personality to the platform"* — so this is an attribution audit, and OpenMoji is not going
anywhere. It found two more gaps and one false statement.

**Two vendor marks, unattributed since the fork baseline.** `static/icons/ollama-mark{,-crop}.png`
and `static/icons/sglang-{mark,logo}.png` are other projects' brand marks, labelling backends in
the Cookbook. A permissive software licence covers a project's **code, not its trademarks**, so
nothing in `licenses/` was ever going to cover them — which is precisely why an audit that looks
for `LICENSE` files walks past a logo. They have a section now: nominative use, no affiliation
claimed, and removable on request.

**`CREDITS.md`'s own summary had gone false.** *"The one copyleft dependency is optional"* named
PyMuPDF while CC BY-SA 4.0 artwork shipped by default two sections below it. A summary gets read
*instead of* the detail, which makes it the one place an omission does damage. It now names both,
and states the aggregation argument nobody had written down: the emoji are a data file the program
reads — §5's aggregate — so CC BY-SA does not reach Pantheon's code and the AGPL does not reach the
artwork. A fork that redraws the glyphs owes share-alike on the glyphs alone.

**The real finding is that none of this was ever checked.** Three gaps, all of them visible to
anyone who compared the tree against `CREDITS.md`, none of them found for months, because nobody
did. `.pantheon/check-licences.py` is that comparison and its inventory is an **allowlist** — an
unlisted file under `static/lib/`, `static/fonts/`, `static/icons/` or `library/` fails the build.
Adding a vendored asset now means writing its licence line, which means having read it. Six rules,
one per way this has actually rotted; in CI beside `check-wiring` and `check-specifiers`.

It caught two of my own mistakes on the way in: an assertion on the string `"Ollama"` that was
already satisfied by a *different* list — one that says outright those projects are not distributed
here — and a broken `licenses/` link inside a sentence explaining that the file does not exist.

### P16-06 — vendoring the emoji found a licence nobody had met
`4b29678..HEAD`. **Suite 6,427 → 6,439 passing, the same 19 failing.**

The emoji route fetched from the OpenMoji CDN on first use. Same-origin from the browser's side —
that part was designed carefully — but the **server** reached a third party on roughly the first
assistant reply, because models emit emoji constantly.

**Vendored as one 5 MB JSON, not 4,147 files.** The same bytes cost 18 MB on disk as separate
files; a single blob is kinder to git and to the filesystem. Each entry holds only the inner
markup, because every glyph in this set repeats the same six stroke attributes — hoisted onto one
wrapping `<g>` at serve time, which is most of the 7.6 MB → 5.0 MB saving. It loads lazily, so an
install that never renders an emoji never pays the memory.

**And OpenMoji is CC BY-SA 4.0, credited nowhere.** Not in `CREDITS.md`, not in `NOTICE`, not in
`licenses/`. The product had been serving its artwork since before the fork. Attribution is
required whether the bytes are proxied or bundled — vendoring only made the omission easy to see.
Given how carefully `P0` handled the AGPL and MIT obligations, **this one being absent is the
finding**, not a footnote to the egress fix. Share-alike also reaches what we did to it: stripping
the wrappers is an adaptation, so the vendored file is CC BY-SA 4.0 too, and the manifest says so.

**Two existing tests pinned the disk cache the CDN fetch filled**, so they went red. Rewritten
rather than deleted: the source changed, the property did not — an SVG leaving that route carries
every header that keeps it inert, and unsafe content blanks. The second is now checked on the
*trusted* path too, because a guard that only runs where you expect trouble is one you have
already argued yourself out of. Two more cases came free while I was in there: an unknown
codepoint, and a traversal-shaped code that must never reach the library at all.

**And one of my own tests passed alone and failed in the sweep** — `get_event_loop()` reaching for
a loop another test had already closed. `asyncio.run`. That is the same test-order pollution this
project has paid for before, and it is why the full suite runs before every ship rather than the
file I just touched.

**Three mutations survived first time and all three were my tests.** The CDN check required
`httpx` and a call on the *same line*, so a two-line reintroduction walked through. The sanitiser
test called `_is_safe_svg` directly rather than checking the **handler** uses it — so a handler
that ignored the result passed. And the attribution check matched the substring `OpenMoji`, which
`OpenMojiX` also contains. The first of those also exposed real dead code: the `httpx` import and
the CDN constant were still sitting in the module.

### P16-08 — the proxy was not the fix
`b233bd0..HEAD`. **Suite 6,412 → 6,427 passing, the same 19 failing.**

`img-src` allowed any `https:` host, so an `![](…)` in model output, a RAG document or an
**email** made the reader's browser fetch from a host nobody chose — announcing their IP, their
user-agent and the moment they opened it. That is what a tracking pixel is, and mail is full of
them.

**The obvious fix is a same-origin proxy, and it is only half.** Routing the fetch through the
server protects the browser and dedupes the request — but it still leaves the machine, for content
nobody chose. Under `Law 16` that is the same defect one hop further away. So **the default is
`ask`**: a remote image renders as a control naming its host, and nothing leaves until someone
clicks. `proxy` and `block` are the other two answers.

`/api/img` is deliberately suspicious of what it gets back: session required, SSRF-guarded and
DNS-pinned through `outbound_fetch`, paced by the `P15` limiter, size-capped, `image/*` only,
**`image/svg+xml` refused** — SVG executes, and this path serves bytes a stranger chose to a
logged-in origin — and cached on disk by URL hash.

**Both CSP blocks were tightened, not one.** The app's and the report pages'. There is a test that
counts them, because tightening one and missing the other leaves the hole open and looks fixed.

**`P1-01`'s counting tests went red, correctly.** The placeholder's focus ring is one more
`var(--accent, var(--red))`, so 553 became 554 and the resolved total 562 became 563. Those tests
exist to catch exactly this and their failure message says what to do: *"move this number and say
which site in the commit — do not widen the assertion."* Moved, in all five places that quote it,
and the site is named. That is a counting guard earning its keep on the first unrelated change to
touch the stylesheet since it was written.

**And one mutation found a real gap in my tests.** They asserted the placeholder was *present* and
never that the raw URL was *absent* — so a renderer emitting **both** a plain `<img src=rawUrl>`
and the button passed clean. The CSP would have caught it in a browser, which is exactly the
second layer that hides a first-layer regression. The test now counts how many times the
un-proxied URL can reach an `src`: once, on the same-origin path.

### P16-17 and P16-09 — the report nobody read, and the button that ran a stranger's code
`81200ee..HEAD`. **Suite 6,406 → 6,412 passing, the same 19 failing.**

**`P16-17`** — `/api/diagnostics/services` probes five subsystems, is admin-gated and safe to
poll, and had **no frontend caller at all**. It now renders in the panel `P16-15` built, *after*
the state checks. That order is the argument: something can be perfectly reachable and still
quietly broken, and the reverse is obvious the moment you try to use it. Only non-`ok` services
show — a wall of green teaches people to stop reading. The liveness fetch is wrapped so a failing
probe cannot blank the state checks beside it.

**`P16-09`** — the *remove background* button ran `trust_remote_code=True`, which downloads Python
from a model repository and **executes it**, in the app process, with the app's permissions, on an
ordinary user click, with nothing on screen saying so. Removed under `Law 1`. Nothing opt-in was
lost — the path only ran when rembg was absent, and the error already said how to install it; it
now also says why Pantheon stopped short rather than fetching.

**And my own row was wrong about the scope.** It said *"the one place in the tree"*.
`scripts/diffusion_server.py` passes `trust_remote_code=True` **five more times**, and is
deliberately left alone: an operator who starts a diffusion server has chosen to load models, most
diffusion pipelines require remote code, and loading models is that script's whole purpose. It is
not the app's, and the app is where a user clicks buttons. The distinction is now written where
the deleted code was, and a test fails if it stops being written down — an unexplained exclusion
is how a scoped hole becomes an open one.

### P16-15 — liveness said green for a year
`770f825..HEAD`. **Suite 6,392 → 6,406 passing, the same 19 failing.**

`service_health.py` already answered *can I reach X*. That is liveness, and it is not the
question that matters. **When a year of agent-written email sat staged and invisible, the mail
server was reachable the entire time.** Nothing was down; something had stopped *finishing*, and
no surface counted it. So `src/self_checks.py` asks the other question — *is something
accumulating, or has something quietly stopped* — and puts the answer in front of a person.

Four checks, all local and cheap: staged agent mail with the age of the oldest (`H01`), hosts the
outbound limiter is holding off, embedding lanes unavailable so memory and knowledge search
silently return nothing, and background follow-ups that have given up. **Three of the four give a
reader to something that had none** — `P15-11`'s `snapshot()`, `P15-12`'s per-account mail
backoff, `P16-05`'s degraded lanes. Pointed at this container it immediately reported a real
`stuck`: no embedding lane.

**Two rules the panel enforces on itself.** Every check that can report `stuck` must carry an
`action`, with a test that fails if one cannot — a dot that goes red and offers nothing costs
attention and returns none. And `unknown` never rolls up as `ok`, because *the check could not
run* and *nothing is wrong* are different answers.

It renders **above** the log console, deliberately: the lesson of `H01` is that nobody reads a log
to find a problem they do not know they have. Built with DOM calls rather than `innerHTML` —
this is the one surface whose whole job is reporting trouble, which makes it the likeliest to be
handed a hostile string from a mail subject or a host name.

**Three mutations survived first time and all three were my tests, not the code.** A rollup test
with a single check never exercised the ordering, so ranking `unknown` below `ok` went unnoticed.
A caller test counted `loadSelfChecks()` including its own definition, so it passed with every
call site deleted. And an admin-gate test read a fixed 1,200-character window that reached into
the next route's `require_admin`.

**And building it found another one:** `/api/diagnostics/services` — the liveness report itself —
has no frontend caller at all. Same family as the `H` rows, in the diagnostics surface, which is a
particularly poor place for it. Filed as `P16-17`; the panel just built is its obvious host.

### P16-11 — stop reading, make the machine try
`f65b5cb..HEAD`. **Suite 6,382 → 6,392 passing, the same 19 failing.** `P16` now has a tripwire.

Every finding in this phase was found by a person reading code. That works once and does not
hold: the next convenience default will look as reasonable as `npx -y @playwright/mcp@latest`
did, and its comment will explain the choice just as plainly. So the guard is a **runnable test**
rather than a CI-only job — it fails on a developer's machine, before the push — wired into CI as
`law16-egress` beside the wiring ratchet.

**It sits at `socket.connect` and `getaddrinfo`, not at `httpx`.** Guarding the HTTP library
would have missed `urllib`; guarding both would have missed `subprocess` → `npx`, and the npm
fetch was the worst offender of the lot. Everything reaches a socket eventually.

**The classifier is `not ip.is_global`, and the first version was wrong in the dangerous
direction.** It enumerated loopback, private and link-local — which calls **Tailscale egress**,
because tailnet addresses live in `100.64.0.0/10`, RFC 6598 shared space, where `is_private` is
False. A guard that fires on the product reaching a model server over Tailscale is a guard that
gets switched off. My own test for "not so strict it bans the LAN" caught it.

**And the mutation run found the guard is two independent layers.** Blunt DNS and connect catches
it; blunt connect and DNS catches it; only blunting both goes red. Correct — and it meant the
combined test could prove neither half alive. Each is now exercised on a path the other cannot
reach: a raw `sock.connect` to a literal IP for one, a bare `getaddrinfo` for the other. That
first attempt failed, usefully: `create_connection` calls `getaddrinfo` **even for a literal IP**,
so the DNS guard fired first and the connect guard was never reached.

**The telemetry question closed the same day** (`D-2026-09-01-01`). The owner will be the product's
heaviest user, so he is the sensor — and a better one than a crash-rate curve, because he sees
the bug *and* knows what he was doing when it happened, which is the half telemetry never
captures. That re-ranks the phase: `P16-15` (local self-checks) is now its highest-value row,
because if the maintainer is the instrument, the instrument needs a dial.

### P16-05 — the fallback that always ran
`2dc908a..HEAD`. **Suite 6,374 → 6,382 passing, the same 19 failing.** The last
zero-configuration leak is closed.

`build_embedding_lanes` returns lanes in preference order — a local HTTP embedding server, then
fastembed. `embeddings.py` calls fastembed the *"zero config fallback"*. It was built
**unconditionally**: the `try` around it was never conditional on the primary succeeding. And
`FastEmbedClient.__init__` fetches ~90 MB of ONNX from HuggingFace when the model is absent,
with `fastembed` a hard requirement so the path is never skipped. **A fresh install downloaded a
model from a third party on its first chat message — with a local embedding server running and
answering.** A fallback that always runs is not a fallback.

Three cases now, and only the third reaches the network: cached → use it, free; a working local
lane → do not fetch a second one nobody asked for; nothing else *and* permission → fetch, because
the alternative is silently having no embeddings at all.

**The cache probe deliberately looks for the `.onnx` on disk rather than asking fastembed**,
because fastembed's way of answering *is it there* is to fetch it. That regression would still
return the right answer, which is what makes it invisible — so there is a tripwire test that
constructs a fake `TextEmbedding` and fails if the probe ever touches it.

**I put the gate in the wrong place first, and the suite said so — 14 red.** Those tests stub the
client builder to exercise lane mechanics, so gating the *assembler* refused lanes in tests that
were never going to download anything. The gate belongs at the one function that reaches the
network, not where the lane list is assembled. My own tests moved with it: they now stub
`FastEmbedClient` — the thing that downloads — rather than the function containing the gate,
which had been testing nothing.

**Two rows came out of the telemetry conversation rather than the code.** The owner's real
problem is *"having people report bugs is not very easy to get to happen"*, and the usual answer —
open a pipe — treats the symptom. `P16-14`: people do not report bugs because they do not know
what to include and fear leaking data, and **in this product that fear is correct** — a stack
trace here carries usernames, LAN topology and often the message that caused it. A diagnostic
bundle they can read in full before it goes anywhere removes both obstacles, needs no collector,
and creates no data-controller obligation. `P16-15`: aggregate signal exists to reveal *silent*
failure, and `H01` is the proof it can be got locally — every agent-composed email since install,
staged and invisible for a year, would have been caught in a week by a local check that counted
the queue and put the number in front of the user.

### Law 16, amended — the address is the test, not the activity
Same day, and it turned a restriction into a specification. `3166798..HEAD`. **Suite 6,371 →
6,375 passing, the same 19 failing.**

The owner, hours after `Law 16` landed:

> *"telemetry is fine, but 'phone home' to an external destination is not allowed. if the user
> wants to establish their own telemetry endpoint, they can bypass this law and do so… like
> Prometheus or Grafana etc.. maybe even enrolling other services to connect like OpenSEO, or
> other CRM products"*

**Every question of the form *is X allowed?* is now rewritten as *who owns the address at the
other end?*** If it is the user or their sysadmin, it was always allowed. If it is us, or a
vendor, or anyone they did not name, it is forbidden however anonymous or aggregated.

**This matters because the obvious misreading is wrong in both directions.** *"No telemetry, we
are privacy-first"* is what an agent reaches for, and it would ban the operator's own Grafana —
which the owner explicitly wants — while leaving someone running Pantheon on their own hardware
with no way to see what it is doing, which is `Law 15` failing in a different costume. The same
misreading would *wave through* "anonymous aggregated usage stats" to a vendor, because that
phrasing avoids the word. The address test gets both right and needs no judgement call.

**It also converts the law from a thing to obey into a thing to build.** `P16-12` is now filed:
Pantheon has **no telemetry export at all**, which is compliant by accident rather than by
design. A Prometheus scrape endpoint and an OTLP exporter, with `P14-01`'s local events table as
the source and **no default destination** — because an empty destination here is not a disabled
feature, it is the only correct shipped state.

**`P16-13` arms the guard before the hole exists.** `P16-12` will create the first legitimate
place in this codebase for an outbound metrics URL, and therefore the first place a well-meant
default could land. The test is already red for a compiled-in Sentry DSN, a PostHog beacon in the
frontend, or any telemetry setting that ships pre-filled — checked across 24 collector hosts, in
Python and in JS. Five mutations, all caught.

**The cost is written down rather than glossed** (`D-2026-08-31-01`): nobody upstream will ever
know how Pantheon is used. No crash-rate signal, no adoption data, no way to learn a feature is
broken for everyone except by being told. Paid on purpose — the one thing someone running this
on their own machine is buying is that it does not report on them.

### Law 16, and 286 skills that need no network
`417c91c..HEAD`. **Suite 6,349 → 6,381 passing, the same 19 failing.** New phase `P16`, four rows
closed on the day it opened.

**The owner set a standing constraint:** fully self-hosted by default, nothing routes anywhere
until a person or sysadmin links it — and a linked provider then gets *everything their
subscription allows*. That second clause matters as much as the first: this is a rule about
defaults, not a cap on capability, and nerfing a configured provider in its name is the mistake
`P2` exists to undo. It is `Law 16` now, with the owner's words on it.

**The audit says the product was already most of the way there** — no telemetry of any kind, every
model, embedding and search endpoint defaulting to loopback, `.env.example` two active lines and
both localhost, fonts and libraries vendored, invasive scheduled tasks shipping paused. What was
left were convenience defaults, and the sharpest one is worth naming: **`npx -y
@playwright/mcp@latest` ran about three seconds after every boot**, installing from the npm
registry on first start and re-checking the dist-tag on every one after. A fresh install with no
account and no key reached the public internet before anyone had clicked anything. Its opt-out
existed and was **inverted** — and the comment above it explained the choice plainly, so nobody
had hidden it. It had simply never been asked this question. Alongside it, `search_fallback_chain`
shipped as `["duckduckgo"]` on the reasoning that it is free and keyless, which meant that on a
native install — where SearXNG never starts — **every search a user typed left the machine**.

**And the product now ships 286 skills.** ECC (MIT) vendored under `library/ecc/`, pinned to
`2.2.0` @ `005eff4`. The reason it fits in an afternoon is that nothing needed converting: ECC
writes `name:`/`description:` frontmatter in `SKILL.md`, which is exactly what
`skill_format.py` already reads. All 286 parse with the reader that was already there.

**Three design calls worth the record.** It loads as a **read-only layer beneath** `data/skills/`
rather than seeding copies into it — `data/` is disposable here, and seeding would make every
update a three-way merge against files the user may have edited, where a shadowing layer has no
merge at all. It is kept **off every write path**, because `_iter_skill_files` has three callers
and one of them *rewrites* every file it is handed; folding the library in would have rewritten
286 vendored files in place on the next owner backfill, visible only as a dirty tree. And
**SKILL.md text only** — no upstream scripts or assets, because a product built to depend on
nothing external should not ship code it has not read to run on someone's machine.

**Updatable, not auto-updating.** `scripts/update-skill-library.py` fetches through the `P15`
limiter, **refuses to apply if any incoming skill fails to parse with this product's own reader**,
and regenerates the manifest with per-file checksums so the diff is reviewable. An auto-updating
bundle is an external dependency wearing a different hat, and it turns *review the diff* into
*hope upstream is fine*.

### P15-07 — I overstated my own row, and the scope changes the decision
Pacing landed; the policy question is now correctly framed and belongs to the owner.

`P15-07` read: *"rotates its User-Agent through six vendors' clients to defeat a 403 — block
evasion by construction."* Every word of that is true and it **omitted the scope**, which is the
same failure I spent the previous run correcting in the `H` rows. `_is_kimi_code_url` gates the
whole path to **kimi.com with `/coding` in the path** — a subscription endpoint the operator pays
for. It never touches another provider. Moonshot serves that endpoint only to clients naming
themselves as one of a whitelist of coding agents; Pantheon is a coding agent not on the list. And
the first accepted name is cached per base URL, so the rotation runs once per endpoint, not once
per request.

**The half that needed no decision is done.** The retries went out back to back with no delay —
six rapid re-sends at a host that has just refused you is the shape that escalates, whatever one
concludes about the names. They are paced through the limiter now, and the facts above sit in a
comment over the list so the decision is made on them rather than on my summary of them.

**Marked `[~]`, blocked on the owner.** Not on an agent. Removing the list breaks Kimi Code
subscription support for whoever is using it, so it is a trade, not a cleanup.

### P15-12 — the mailbox that must not be retried was the only one always retried
`38931c6..HEAD`. **Suite 6,339 → 6,349 passing, the same 19 failing.**

`/unread-state` is index-first *specifically* so polling does not hit the provider — its own
docstring says so, and says the fallback happens once. The guard was `if indexed_total:`, and
**the account most likely to have an empty index is the one whose IMAP is failing**, because a
failing account never indexes. So the single mailbox that must not be hammered was the only one
that always was: a live login attempt every 60 seconds, in every open tab, indefinitely.
Repeated failing logins are what providers lock accounts for.

**I wrote the wrong fix first, and it would have shipped.** Wrapping the call in `try/except`
and backing off in the handler is the obvious move — and `_list_emails_sync` **catches every
exception** and reports failure as an `error` key on an otherwise-empty result. AST-verified:
two broad handlers, both returning, neither re-raising. So the handler never runs and the
backoff engages never. It compiles, it reads correctly, and it does nothing.

**That swallowing is also why nobody noticed the hammering.** From the poll's side, a mailbox
that has been refusing logins for a week is indistinguishable from one with no unread mail.
`P3-17` is the row that owns 250 of these; this is the first one that cost something.

**New primitive: `penalise()` / `succeeded()`** — escalating cooldowns for protocols with no
429. IMAP, SMTP, CalDAV: *stop* arrives as a socket error or an auth rejection, so the protocols
without a status code are exactly the ones where blind retrying costs the user most. Keyed by
account rather than host, deliberately — one stale password must not silence the other mailboxes.

**Two mutations survived, and both were my tests.** One asserted `second > first`, which the 20%
jitter satisfies about half the time with escalation deleted entirely — flaky *and* vacuous. The
other checked only that an unrelated account stayed clear, which passes trivially when the
penalty is written to the wrong key and *nothing* is blocked, including the failing account.

### P15-05 — 260 requests from one button, and the error handler made it worse
`d2eb00a..HEAD`. **Suite 6,330 → 6,339 passing, the same 19 failing.**

The hardware-fit catalogue refresh walked 13 collection sources × 20 pages at
huggingface.co — **sequential, no delay, no token** — while two other call sites in this same
product send a Bearer token to that exact host. Now: a **shared** 40-request budget across the
whole refresh (per-source caps alone do not help — thirteen sources each stopping politely at
their own limit still add up to a burst), the token that was two imports away, and a five-minute
floor under `force=True`, which previously walked straight past the 24-hour TTL from a UI button.

**The error handler was the real find.** `except Exception: continue` meant a 429 on the first
source was swallowed and answered by trying the other twelve — so being told to stop bought the
host twelve more bursts. That is the same shape as the search chain in `P15-04`, in a module
nobody connected to it.

**And one mutation survived, usefully.** Deleting the rate-limit `break` changed nothing, because
the limiter's own cooldown already blocks the second source. Two independent protections, which
is correct — but it meant the test could not see the loop it claimed to test. There is now a
second test with a deaf limiter stubbed in, so each half is proved alone.

### P15 — the product had no brakes on anything it called
Four rows closed the day the phase was opened. `ba8f561..HEAD`. **Suite 6,287 → 6,330
passing, the same 19 failing and all 19 pre-existing.**

**This came from the owner getting soft-banned by GitHub**, mid-session, for pasting a link
into his own product's skill importer. The importer walked a repository tree unauthenticated,
at wire speed, opening a fresh TLS connection per file, identifying itself as `python-httpx`.
That is not a feature with a bug in it — that is the exact request shape abuse detection is
built to catch, and it caught it.

**Two audits found the same thing everywhere, and both facts are one-liners.** *Nothing in
this codebase read `Retry-After`* — not one call site out of 50 modules that make outbound
requests. And *nothing had jitter*, so every install fires at the same instant on the same
boundary. `src/rate_limiter.py` did exist, and is **inbound**: it protects Pantheon from its
callers. Nothing protected the user from the services Pantheon calls for them.

**The fix is one shared limiter keyed by destination host, not by feature** — because two
features each staying under a limit will jointly exceed it, and the importer and the
cookbook's GitHub calls could already collide. Its shape is lifted from `routes/device_flow.py`,
which turned out to be the only correct outbound throttle in the tree: a `next_poll_at` per key
and a `slow_down()` that obeys the server's own pacing signal. Re-keying that from poll session
to host was the smallest change that made it apply to everything.

**Hearing "stop" correctly is the part that matters, and it has three forms.** A `429` is the
easy one. **GitHub's primary rate limit is a `403`**, carrying `X-RateLimit-Reset` rather than
`Retry-After` — a client reading only `Retry-After` learns nothing from the response that
matters most. And `X-RateLimit-Remaining: 0` on an otherwise successful response is the only
signal that lets you stop *before* being told to. A plain `403` is not a rate limit and must
not silence a host for an hour; there is a test for that too, because getting it wrong turns
one private repository into a twenty-minute outage.

**The importer's cap was counting the wrong thing.** `MAX_FILES = 64` counts files *kept*. A
directory costs a request whether or not it yields a file, so a tree of empty or binary-only
folders cost an unbounded number of `api.github.com` calls while the counter never moved — and
unauthenticated GitHub allows sixty requests an hour, total. There is now a budget on requests.
There is also a token setting, which is the difference between a couple of imports an hour and
five thousand; and the 403 message now names the wait instead of saying *"try again in a bit"*,
which is the sentence that makes a person click again and deepen the ban.

**Three hammers stopped.** Search retried a rate-limited provider **immediately, with no
sleep**, then walked down the chain doing the same to the next — turning one provider's limit
into load on all of them. `llm_core` retried a 429 on a flat 0.5 seconds, three times, without
reading the header that said when. And `bg_monitor` retried a failed follow-up **every five
seconds, forever** — 720 attempts an hour, each allowed twelve model rounds, each round able to
call `web_search`, entirely unattended.

**Two of my own tests were wrong and the mutation run is what said so.** The jitter test
measured wall-clock time around `acquire`, and scheduler noise alone made the gaps differ — it
passed with jitter switched off entirely; it now reads the *planned* gap and has a control that
proves it can tell the two cases apart. The escalation test called `reset()` in its own setup,
which cleared the counter the assertion was checking, so it passed with the clearing logic
deleted. Both were caught by mutating the thing they claimed to test, which is the only way
either would ever have been caught.

**And one production bug came out of writing them:** `Retry-After: 0` is a legal answer meaning
*go ahead now*, and `parse_retry_after(...) or parse_reset_header(...)` reads `0.0` as absent —
so the clearest instruction a server can give was being converted into the sixty-second penalty
reserved for servers that said nothing at all. It was in three files. The `or` looked right in
all three.

### The reconciliation — the checker was green over six wrong rows
Five read-only agents across all 335 rows; two bumps, four unblocks, one tick withdrawn, nine
dedupes, six premises corrected, two new bugs. `505cd6d..HEAD`. **Suite unchanged — no product
code was touched. Tracker green for the first time on every row.**

**The tracker's own checker had a hole, and it was shaped exactly like the thing it was meant to
catch.** `ROW`'s Blocked group was a bare `(\d+)` while the Done group accepted `**bold**`. The
table bolds a count worth the eye — so **every row with a blocked task failed to match and was
silently skipped**. Seven of fifteen phases: P0, P1, P2, P3, P7, P8, P11 — *exactly* the seven
containing all eleven blocked rows. **Six of the seven were wrong.** P0's table said 16 ready /
13 done where the ticks said 8 / 24. The checker had reported `tracker OK` over that for days,
and three of the five agents found it independently. Fixed with one character class, plus the
rule that mattered more: **a line that names a phase and will not parse is now reported, never
skipped.** The Total row got the same treatment — nothing had ever checked that it added up, and
it had quietly accumulated **27 appended copies of itself** on one line.

**Then the test found a third one in the same file.** `tests/test_check_tracker_guard.py` bends
the tracker in each way it has actually drifted and asserts the checker notices — and one bend
came back green: a task filed under the wrong phase (the `P3-16`/`P5-16` collision, which has
happened here) was *printed* as a `FAIL` line and then exited **0**, so CI passed over it.
Reporting a fault you do not fail on is the same silence as not looking. All three defects are
one habit, which is why the fix is a test and not three patches: **the checker now has ten
mutations it must fail, and the proof lives in the suite instead of in a transcript.**

**`P6-08`'s tick is withdrawn — it was ticked on code as written, not as executed.** The trace
claimed the cap *"resolves through instance setting → env → built-in default … without a
restart."* Both load-bearing clauses are false. The env leg is unreachable at import on a fresh
install (`get_setting` merges `DEFAULT_SETTINGS` on every read, so `get_setting(k, None)` cannot
return `None` — `H06` holds the proof), and `_refresh_concurrency_cap` has exactly one caller,
inside start-up, so nothing re-reads it. The registration and the clamp were real and stand.
`B20`, which described this as dying on the first settings save, is corrected: it dies earlier
and the fix it implies would not have worked.

**Two rows were already done before anyone opened them.** `P2-26` asked for documentation that
exists and **predates the fork** — the blocklist tuples verified byte-identical to baseline
`b4d1293`. `P9-04` had been reduced to a deletion, and the deletion was never valid: `eaf-*` is
the **live** email-account form (provider picker, IMAP/SMTP auto-fill, OAuth), and `set-email-*`
is live too. Both read as dead because the consolidation *moved* them. Under `Law 1` a deletion
is justified before it runs, and that is what caught it.

**Four rows were blocked on nothing.** `P3-19` and `P2-13` had each discharged their own blocker
in their own text and never flipped the mark. `P1-06` was blocked for want of a scope that `B22`
had since supplied. `P7-11` was one `[~]` over two halves — the export UI, ready; the approval
trail, unbuildable because approvals are in-memory with a 600-second TTL — now split so the ready
half can be picked up. **`P11-09` stays blocked and is the one that was right to be.**

**Four `H` rows were wrong, and one was dangerous.** `H21` proposed deleting a 282-line span
containing `_checkPeekCleanup`, which has a live caller **outside** it, and a class-name sweep
that is `P3-03`'s exact blocker — `P3-03` is blocked *because* that sweep deletes the CSS `P2-20`
needs. Struck. `H12` claimed you can never see your compare results; a Scoreboard exists and is
reachable — the real defect is narrower and better: the server record is **write-only** and the
visible history is per-browser, so the two copies drift and neither is authoritative. `H13` cited
the album Set instead of the image Set, which makes the row *cheaper* — `_selectedIds()` already
produces the array the endpoint wants and already drives a live bulk bar. `H11` overstated twice.

**Two new bugs, both found by checking a claim rather than reading code.** `CHANGELOG.md:37`
tells the public the AGPL §13 source link shipped; `P0-17` is open and calls it *"the one licence
obligation that is genuinely required and genuinely missing"* (`B25`). And the sidebar anti-flash
guard was renamed on one side only — the pre-paint script sets `pan-sidebar-*`, the stylesheet
still selects `html.ody-sidebar-*`, so the guard does nothing and every cold load flashes on
exactly the two layouts it was written to protect (`B26`).

**`H01`'s open question is answered: it is a year, not a week.** `agent_email_confirm: True`
arrived at the fork baseline and is in upstream too, so the invisible email backlog is as old as
the install — and the drafts already staged need a way out, not just a switch that stops making
more.

**What this run is really about.** A tracker that reports green while six of its rows are wrong is
worse than no tracker, because it is trusted. Every number I would have written this run would
have gone unvalidated into a table nobody could check. Three agents finding the same regex hole
independently is the part worth keeping: the defect was not hidden, it was *unlooked-at*, and the
thing that finds those is a second reader with no stake in the first one being right.

### The discovery audit — 21 features that exist and cannot be reached
Four read-only audits, five fixes, 21 new `H` rows. `65054fa..HEAD`. **Suite 6,301 collected,
6,277 passing, the same 19 failing and all 19 pre-existing.**

**This run came from one sentence.** The owner, about his own product: *"there's a lot of hidden
things that are in this platform that we can't fully discover yet."* Four agents swept the
backend, the frontend, the configuration surface, and every place the product *claims* a
capability. **Two of them independently found the same two defects**, which is the strongest
evidence in the set.

**The territory was bigger than any document said.** 500 routes, not the 301 in `routes/*.py` —
**173 live in subdirectories** a naive scan omits, and three of the best findings are in that
half. 168 JS modules, not 145. 128 environment variables read, 54 declared.

**Ranked by harm, the product lying to the model comes first**, because the model repeats it to a
person as fact. Three of those:

- **`ui_control open_panel skills` and `open_panel settings` returned "Opening skills panel" and
  did nothing.** The two element ids they clicked **exist nowhere in the repository** — the only
  occurrence of either string was that line. And the system prompt steers *towards* it: *"'open
  skills' … means OPEN THE PANEL — call `ui_control`, NOT a manage/list tool"*, so the one
  phrasing a person would use was routed off a working tool onto a silent no-op. **Fixed.**
- **`tail_serve_output` was advertised on four surfaces and callable from none.** In the native
  schema, in the system prompt, in the RAG tool index, in the cookbook toolset group — and absent
  from `TOOL_TAGS`, which gates *both* call channels. `do_serve_model` **orders** the model to
  call it after every serve: *"Do not tell the user to check logs; you have the log tool."* So at
  the exact moment a model server crashes, the agent reached for the traceback and the call was
  dropped. **Fixed — one string, and the comment eight lines above it already described this
  failure for the rest of the family.**
- **`edit_image` advertises four actions and all four POST to routes that do not exist.** Filed as
  `H03` rather than fixed: all four capabilities are real under other names, but the bodies
  differ enough that a path map would be wrong.

**Then losing their data.** `agent_email_confirm` defaults on, so agent-composed mail is staged
into `scheduled_emails` with a `send_at` the poller never reaches. Three routes exist to approve
it. **`grep` for them across 183 frontend files returns nothing.** The model is instructed to tell
the user their mail awaits approval *in the chat UI*; there is no approval surface in existence.

**Then hiding capability the owner already paid for.** A 475-line Personal Assistant with daily
check-ins whose only entry point is gated on a function that occurs **once in the repository, at
that call site**. A complete embedding-model manager: seven admin routes, zero pixels. Session
cleanup *with a dry run*. Three memory views including "why did it remember that". A blind-vote
history you can never read. An add-to-album endpoint that takes exactly the array the gallery's
existing multi-select already produces.

**And two places where a control lies.** Seven of eight feature flags do nothing, and four are
un-hidden one line after being hidden — measured by replaying the real sequence: 9 of 9 hidden,
then 7 of 9 shown again. `PANTHEON_TASK_CONCURRENCY_CAP` has **never worked on any install**, not
"after the first admin save" as `B20` says — `get_setting` merges defaults on every read, so the
env layer is unreachable code, and the helper written to solve exactly this has zero callers.

**Two lessons about our own instruments.** `check-wiring.py` matches only lookups whose argument
is a *string literal*, so the id map that produced the headline defect scored clean — Law 13's
enforcement has a structural blind spot, not a one-off. And it does not strip comments: writing
the correction note with the call spelled out made it count my own comment as an unresolved
lookup. Both are now on `P3-15`, whose specification is no longer "a script finds the next three
for free" but "a correct script rediscovers all 21".

**Also corrected: three documents told contributors to target a `dev` branch that does not
exist** — at clone, at contribute, and at harden-CI, the three places a newcomer meets the
project. `README.md` said the opposite and was right. And the README's own badge said 5,742 tests
while its body said 6,277, on one page.

### `P1` wave 2 — four rows, and the feature the owner loves was quietly broken
`P1-02`, `P1-03`, `P1-04`, `P1-05`, plus `B24`. `a67000b..HEAD`. **296 tracked, 77 done. Suite
6,199 → 6,277, the same 19 failing and all 19 pre-existing.**

**The find of the run did not come from a row.** The owner sent a real exported theme mid-run
with a note: *"the theme creator that's built into the platform… is genuinely awesome, and we
should ensure it stays functional. It is also the location where you enable the glass panels
too."* Checking it against the code took ten minutes and found that **a theme stores seven
options and the exporter wrote four**. `frosted` was one of the three missing — so turning the
glass on, exporting, and importing on another machine silently gave you a theme with the glass
off, and a tuned background pattern came back at its defaults. The importer had the identical
gap. **Nothing failed loudly**: the file imported cleanly and simply produced a different theme,
which is exactly why it had survived every previous pass over that module. Four lists now carry
all seven and a test holds them equal, **using the owner's own export as its fixture**. The
editor is named in `FORBIDDEN.md` Part 1 with his words attached.

**`P1-03` was the row whose value was the work.** Its counts were right — 93 bare uses, zero
declarations — but "renders at full strength" undersold it: **nine of the 93 rendered nothing.**
`.ge-adj-hist-handle` is a triangle drawn entirely from borders and painted none; every
image-editor history dot but the current one was invisible; and three tab strips hovered
`--fg-muted → var(--fg)`, so on `retrowave` and `terminal` — where those two are the same hex —
inactive, hovered and active tabs were one colour.

**And the obvious value would have reintroduced `P1-01`'s defect one layer down.** Every point on
the `--fg`→`--bg` segment passes within 22.0 sRGB units of `forest`'s accent *at every ratio*,
and the sheet paints "inactive" muted against "active" accent at **33 opposition pairs** — so the
natural choice collapses all 33 on `forest`, and on `gpt` too. That is `P1-01`'s third class
relocated from the fallbacks into the value. Pivoting through `--color-muted` moves the closest
approach to 45.6 and the collapsing pairs to zero.

**`P1-02` ended in deletion, and the arithmetic is why.** Three of its four keys have **zero
readers in the entire tree**; the fourth resolves to the theme's red at 124 of 130 sites. Wiring
it would have *defined* the token on every load and retired the fallback at all 131 — six of them
changing colour on all sixteen themes. That is the flattening `D-2026-08-26-03` protects against,
spelled with a different token name, and `P1-01` refused exactly this for `--accent` eight days
earlier.

**`P1-04` is the row where "delete" was the wrong verb.** The backdrop's every style lives inside
a `max-width:768px` query, so deleting the top-level `display:none !important` leaves a bare
`<div>` — and `body { display: flex }`, so a zero-width flex child. Scoped to `min-width: 769px`
instead. Why it existed at all: it sits directly below a blanket rule written for **dead markup**
and arrived in the same commit — a live element caught by someone else's cleanup.

**`P1-05` closed a control that was fighting itself.** The rail gear unhid the sidebar and
scrolled it, and `syncRailSide()` sets the icon rail to `display:none` when the sidebar is open —
so it hid the very rail containing the gear just clicked. `sidebar-layout.js` had *already*
excluded that button from its scroll-to-section handler; the `app.js` handler was doing precisely
what its sibling deliberately excluded it from.

**One of my own edits called a function that does not exist.** `applyFrosted`, where the real name
is `applyFrostedGlass`. `node --check` passed it — it parses, and does not resolve names. Caught
by looking, then pinned by a test that checks every function the importer calls is one the module
defines. It is the same `Law 13` shape this programme keeps finding in other people's work, and it
took about ninety seconds to introduce.

### `P1-01` — the row whose numbers were the work, and the badge that would have turned red
`P1-01` (define `--accent` per theme). `7f28702..HEAD`. **296 tracked, 73 done. Suite 6,156 →
6,199, the same 19 failing and all 19 pre-existing.**

**The count moved a fourth time, exactly as the row warned it would.** 508 → 521 → 535 → **816
sites at implementation, 553 of them `var(--accent, var(--red))`**. `static/style.css` is 42,739
lines now. Both figures are re-derived by a test in both directions, so a stale comment fails
rather than drifts — which is the only durable answer to a number three documents have already
carried wrongly.

**But the counts were not the finding. The row's model of the population was wrong.** It described
two classes: fallback sites that do not move, and bare sites that gain colour. There are three.
562 resolve to the theme's red and do not move; 204 paint for the first time; and **63 carry a
hand-picked fallback that is not red, so defining the token changes their colour.** No version of
`P1-01`, `DECISIONS.md` or `FORBIDDEN.md` had named that third class, and the row's `Verify:` line
— *"only the previously-unstyled elements change"* — would have failed on the tree it produced.

**Twelve of the 63 were never accent sites.** A green *verified* badge, two link blues, a
supervisor amber and a green completion dot had all reached for `var(--accent, <the real colour>)`
because `--accent` did not exist and the fallback was the actual intent. Left alone,
**`.skill-verified` would have rendered in the same hue as `.skill-needsmark`** on all sixteen
themes — a verified badge in the failure colour — and `.note-checkbox-edit:hover` would have
matched the *delete* control beside it at identical geometry and identical tint. They now name the
semantic token they meant, all four of which already existed, because adding a third colour
vocabulary is precisely what `P1-06` is blocked for.

**The classification criterion is the part worth reusing.** Not *"red is wrong here"*, which is a
taste argument and theme-relative anyway — `--red` is the palette's brand accent and `terminal`
sets it to green. The test was: **after the change, does this element become indistinguishable
from a sibling that means the opposite?** That is checkable, theme-independent, and it is what
separated the twelve from the fifty that stay accent-coloured.

**Two dead sites, not one.** `P1-02` says exactly one `--accent-primary` use is genuinely dead and
that `P1-01` fixes it. The session rename input is fixed as predicted. The second — *"+ New
Folder"* at `sessions.js:426` — had **no fallback at all**, so it resolved to `inherit` and the
action row rendered identically to the plain folder rows above it. `P1-01` could not reach it:
there is no `--accent` in that chain to define. Fixed in passing.

**And `P1-02`'s real content turned out not to be hygiene.** `create_theme` accepts
`accentPrimary` and `index.html`'s first-paint script writes it, but `ADV_KEYS` omits it — so
`applyColors()` never updates or clears it, and a theme made through the assistant sets
`--accent-primary` once and it sticks, stale, through every later theme switch. `style.css`'s own
header claimed theme.js set it. Both corrected; the row now says what it is for.

### The trust ladder — and the run where refutation found the control inverted
`P7-03` (rung "ask every time") and `P7-04` (rung "allow-listed"), discharging `P7-05`'s
superseded acceptance criterion. `3b5cf9c..HEAD`. **296 tracked, 72 done. Suite 5,962 → 6,156,
the same 19 failing and all 19 pre-existing.**

**Three implementers, two refuters, both `broken: true`, and the headline finding is the reason
this programme refutes everything.** The ladder *inverted*. `approval_gate_bypassed` short-circuits
the gate before the rung is consulted, and both approval buttons set `allow_remaining_actions` — so
on `ask_every_time`, approving one harmless `bash` in a clean run disarmed the gate, and a later
round fetched a hostile page and ran an exfiltration command **with no prompt at all**, an action
the *default* rung stops and asks about. The two "stricter" rungs were strictly less protected than
the one they sit below, and the ladder's own copy promised the opposite in the same commit. A
second refuter found the same shape in the allow-list: a standing *"anything starting with git"*
rule let `git push --force origin main` run unprompted in a run that had already pulled in a web
page. Both are one line each, and neither was pinned by any test — which is how they survived
three implementers who all reported their work green.

**The reason both happened is the same and worth keeping.** Before this row a card could only exist
once untrusted content had armed the gate, so every grant was given under the same threat model it
then relaxed. A rung mints cards in *clean* runs, and **a yes given when nothing was wrong must not
spend itself after something is.** `src/tool_execution.py` already enforced that across the
approval door; nothing enforced it across the bypass door, or across a saved rule.

**The row also could not be answered end to end when it first landed, and the batch said so instead
of ticking.** `execute_tool_block` refused every approval replay unless *both* the run and the
sealed pending carried taint — because "taint seen" had been standing in for "the gate asked". A
rung refusal mints a card with taint false, so approving it answered *"Exact-action approval
requires an armed run security context"* and the tool never ran: the ladder could ask a question
nobody could answer. It shipped as `xfail(strict=True)` naming the file and the fix rather than as
a green tick, which is the behaviour the laws are for.

**Two more `breaks-users` findings, both a control reporting success and doing nothing.** In
no-login mode the route filed rules under the reserved local owner while the run carried
`owner=None`, so every rule was written, listed, toasted as *saved*, and never read. And switching
*onto* the allow-listed rung never drew the "always allow" chooser until a page reload — the one
thing the rung promises, unreachable by the route a first-time user takes.

**The largest gap was not code.** A rule could be created and then neither seen nor revoked from
any screen: the widest grant, *"anything bash does"*, one click away with no undo. `core/database.py`
had already written *"this is the table where that omission is expensive"*, and the store's
five-second TTL was defended on the grounds that *"revoke means revoked before the user has
finished reading the confirmation"* — with nothing in the product able to revoke. There is a list
under the ladder now, and its failure path says the unwelcome half out loud.

**On mutation testing.** Between them the two waves ran 58 mutation/test pairs and found eight
properties the code got right that no test pinned — including the second half of the replay guard,
whose deletion passed the entire suite, and the revoke route's authentication gate. Two mutants
survived a batch's *own* first sweep and exposed real gaps in tests written minutes earlier. And
one finding came out of it that belongs to nobody here: a 1,984-character nested tool argument
kills a run at every rung, because `json.loads` is wrapped in `except (TypeError, ValueError)` and
`RecursionError` is neither. That is `B17`, pre-existing, and the model writes that content.

### P6 closes at 18 of 18 — the steer route, and the taxonomy that ranked nothing
`P6-18` (steer mid-response), `P7-06` (rank prompts by effect) and `P6-11` (the plan window's
fifth field, closed by `P7-06`). `22c8628..HEAD`. **296 tracked, 70 done. Suite 5,835 → 5,962,
the same 19 failing and all 19 pre-existing.**

**Two rows, three implementers, three refuters, and all three refuters returned `broken: true`.**
Both headline findings were the same shape: a thing that *looked* landed, passed its tests, and was
wrong in the one case that mattered most.

**`P6-18`'s gate asked the wrong question, and it deleted user text on the default mode.**
`agent_runs.is_active()` answers "a run is registered", not "a run that can read the steer inbox is
in flight" — and `agent_runs.start()` is called for every non-compare stream while only one of
*four* exits reaches `stream_agent_loop`. So on a plain chat turn the route accepted the steer, the
client cleared the composer and said *"lands at the next step"*, and the words went into an inbox
nothing would ever read. Reproduced end to end, server and client. Fixed with `is_steerable()` —
liveness stays in `agent_runs` (`Law 14`), it is just now the right predicate — plus a fourth
non-steerable exit the refutation itself had missed. Three more closed with it, including a
`Law 13` half-wire that had been sitting in plain sight: `steer_applied` was emitted by the
backend, exported by the frontend, documented in both, and **routed nowhere**, so the module's own
"your steer missed the run" warning could never fire.

**`P7-06`'s ranking lied about the worst action in the product.** `bulk_email` — the tool whose
purpose is deleting *many* messages, and which with `permanent: true` bypasses Trash entirely —
ranked **below** `delete_email` for a single message. The card for emptying a mailbox read milder
than the card for deleting one email, which is the exact inversion the row exists to prevent. The
general defect underneath it was worse: the action tables are keyed on bare tool names while the
model can call an email tool under its MCP alias, so *every* aliased call was missing its own
action table and resolving one rung low.

**The second finding made the design smaller, and is the one worth remembering.** Three files
asserted that the sealed approval payload "cannot carry more — the seal is a control that never
lifts", so the presentation was threaded beside it, event by event, consumer by consumer. The
premise was false: the digest seals a server-side dict, while `public_payload()` is a derived view
never read back as authority — proven by mutating it and watching the digest hold. Refutation had
already found **three** surfaces shipping the card unranked because of the threading. Moving the
resolution *inside* the shared payload deleted two copies, fixed all three surfaces at once, and
turned five pending consumer edits into none. **A false constraint had produced real duplication,
and the duplication was already drifting.**

**`Law 15`, from the refuter, unedited: *"the honest answer is yes — from the sentence, not from
the design."*** The wording carries the card; the visual system was one pixel of font-size, two
pixels of rule width and one mark shape — and on six of sixteen themes it was actively harmful,
with the `serious` lead measured at **2.11:1 on `paper`** while the harmless line beside it sat at
11.05:1. The lead is no longer recoloured. After: no theme has the serious lead more than 10%
below the routine line, where 14 of 16 did before.

**On refutation itself.** Twenty-eight mutation/test pairs were run against the new tests; two
mutants survived the first pass and exposed real gaps in tests written by the same agent that
wrote them. Six mutations had survived all sixteen original surface tests, including one that
inverted the module's stated fail-high rule for unknown effects. `tests/test_tool_capabilities_effects.py`
exists because of that mutation and nothing else.

### P6 reuse wave — three rows, and the systemic defect they uncovered
`P6-04` (queue panel), `P6-06` (sequential-vs-parallel picker), `P6-07` (point the Tasks activity
view at queue items) and `P3-11` (one specifier per module). `01e8807..HEAD`.

**The integrator's verdict on the three reuse rows was "tick nothing" — all three failed their own
`Verify:` line — and it was right.** What it found underneath them was not three defects but one:
`P6-07`'s registry did not work, and the reason was that `chat.js` registered through
`import('./tasks.js')` while `app.js` imports `'./js/tasks.js?v=…'`. **ES module identity is keyed on
the resolved URL including the query string**, and there is no import map in this tree, so those are
two modules with two copies of their state — and nothing fails loudly when it happens. A registry
written through one specifier is simply empty when read through the other.

**Eleven modules were forked that way.** `chatRenderer.js` under three URLs, `modalManager.js` under
two, `settings.js`, `tasks.js`, `gallery.js`, `memory.js`, `models.js`, `slashCommands.js`,
`compare/index.js` and both research modules. Two features were dead because of it: `P6-07`'s
registry, and `chatStream.js`'s `research_started` fast-path adopt, which called `adoptSession` on an
instance whose `_jobs` array was always empty — so every agent-started research job waited for the
slow poll instead. **Eight `sw.js` precache entries had never matched a request URL**, because the
fetch handler uses `cache.match(e.request)` with no `ignoreSearch`. And the fork *silently defeated a
control `FORBIDDEN.md` says never lifts*: "the approval cache-buster string must be bumped across all
six approval-path modules together" was structurally impossible to obey while four importers held no
buster at all. Nobody lifted that control. It was voided by an unrelated convenience, four modules
away, and the document went on describing a guarantee the tree could not provide.

`P3-11` had been sitting in the tracker the whole time, scoped as *"one module, one line per import,
a performance row."* It was eleven modules, 42 rewrites across 27 files, and not a performance row.
**`check-specifiers.py` now runs in CI at `--max 0`**, beside the wiring ratchet the alignment pass
wired up — the second entry in a section that exists because `Law 13` needs a machine, not a habit.

**On reuse, the three rows landed differently and the tracker says so.** `P6-07` is the unambiguous
win: 19 hunks in `tasks.js`, exactly one of them new. `P6-04` genuinely reuses the app's `Storage`
helper and the activity view's row CSS rather than building a second store or a second row system.
`P6-06` is a **clone**, not a share, and the row states that plainly — the honest answer was that
sharing it as written would ship *"Opens N new chats"* to a panel that opens no chats, which is a
worse `Law 15` outcome than the duplication. Parameterising it is `P5-17`, filed with the three
differences named.

**Nine defects were found by refutation and fixed before any of these were ticked**, four of them
`breaks-users`: a *Send now* button that was a guaranteed no-op, a per-item mode that flipped the
composer permanently and survived a reload, a model restore that fired before the send it was
restoring, and parallel mode 403ing for every signed-in non-admin. Three more were caught reviewing
my own work in this run — an editor that lost your typing on any re-render, a popover leaking two
document listeners per toggle, and uploading rows inflating the count behind the Send button.

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

**Use a patch, not a bundle.** The two mirrors carry the same trees under *different commit
SHAs* — the container was seeded from a tarball, so its history is its own. A `git bundle` is
addressed by SHA and will not apply on cybertooth for that reason; `git format-patch
<base>..HEAD --stdout` is addressed by content and does. The 2026-08-29 sync ran:
`SendUserFile` → `device_commit_files` into `.pantheon-transfer/` → `md5sum` on both sides →
`git apply --check` → `git am --keep-non-patch --committer-date-is-author-date` →
`git commit --amend --author='ImPanick <…>'` (the container's git identity is not the repo's,
and `--reset-author` and `--author` cannot be passed together) → delete `.pantheon-transfer/` →
`git push`. Three checks, in order: the md5 matches, `git apply --check` is clean, and the tree
hashes agree afterwards.

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
- [x] **P0-18** Decide `AGPL-3.0-only` vs `AGPL-3.0-or-later` and state it in `LICENSE`, `README`, and SPDX headers. Today the qualifier lives in exactly one README line with zero SPDX headers. — **DECIDED — `AGPL-3.0-or-later`, matching upstream, with real SPDX headers** (D-2026-08-26-06). — **done 2026-09-07, with one part of the row refused and the refusal is the interesting half.** **1,463 files** of program text now carry `SPDX-License-Identifier: AGPL-3.0-or-later` — every tracked `.py .js .mjs .ts .css .html .sh .zsh .ps1 .swift` outside the vendored roots `check-licences.py` already owns. **The identifier only, with no `SPDX-FileCopyrightText` line**, and that is deliberate: most of this tree is upstream's code that Pantheon modified, `P0-15` established there was no upstream copyright notice to preserve, and `Copyright 2026 Panick` on a file nobody here wrote is the same class of statement as the font that claimed to be GohuFont (`P0-23`). The licence identifier is true of every file; `NOTICE` stays the authority on copyright. **`LICENSE` is deliberately NOT changed.** The row asked for the qualifier there, and the AGPL's own second paragraph says copying it verbatim is permitted and changing it is not — so a project header prepended to it modifies a document nobody here may modify. It goes in `NOTICE` (which already carried the *"or (at your option) any later version"* sentence and now carries the identifier beside it), the README, `package.json` + its lockfile root, and an `org.opencontainers.image.licenses` label on the Docker image, **which declared no licence at all** — the same failure class as `P0-30`, where the desktop builds shipped a dozen libraries with their attribution stripped. `org.opencontainers.image.source` is deliberately absent until `P0-17`: a source label has to point at a repository a reader can open. Enforced by `.pantheon/check-spdx.py` (with `--fix`), whose **second rule is the one that matters** — no vendored file may carry *our* identifier, because `P0-16`'s first attempt already went wrong in that direction once, pointed the other way. 17 tests, 8 mutations, all caught.

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
- [x] **P0-21b** **Twelve bundled packages have no licence notice anywhere in this repository.** `html2pdf.bundle.min.js` bundles fifteen top-level packages; its sidecar `LICENSE.txt` carries a copyright notice for **three** of them — `es6-promise`, `html2canvas`, `jspdf` — plus html2pdf.js itself. Measured 2026-08-27 across all comment-block forms (955 blocks, 23 copyright-bearing), which is why an earlier `/*!`-only count said five. The twelve: `@babel/runtime-corejs3`, `canvg`, `core-js`, `core-js-pure`, `dompurify`, `fflate`, `performance-now`, `raf`, `regenerator-runtime`, `rgbcolor`, `stackblur-canvas`, `svg-pathdata`. **`dompurify` is not just a missing file** — DOMPurify 2.3.0 is dual-licensed Apache-2.0 **or** MPL-2.0, so someone has to choose and record the choice. `Verify:` every package the bundle ships has a notice in `licenses/`, and the count is re-derived rather than carried. — **done 2026-09-07, and the re-derivation was the whole row.** The list is not carried and not grepped: webpack left **1,736 `node_modules/<package>/` paths in the shipped blob**, so the fifteen come out of the bytes on disk, offline, and recompute if the file is ever replaced. That confirmed the row's twelve exactly. **Thirteen texts added**, not twelve: `es6-promise` was one of the three the sidecar happened to cover, and leaving it to depend on a minifier having kept a comment was the wrong shape when the other fourteen have a file. **Versions:** the bundle states six of them in banners it kept (`dompurify 2.3.0`, `html2canvas 1.0.0`, `jspdf 2.3.1`, `es6-promise 4.2.8`, `core-js 3.16.0`, `core-js-pure 3.15.2`) and none for the other nine, so rather than guess, each of those nine had its `LICENSE` fetched at **two versions spanning the plausible range and compared byte for byte** — all nine identical, so the version is not load-bearing for the notice. Pairs: `@babel/runtime-corejs3` 7.14.8/7.24.0, `canvg` 3.0.7/3.0.10, `fflate` 0.4.8/0.7.4, `regenerator-runtime` 0.13.9/0.14.1, `svg-pathdata` 5.0.5/6.0.3, `es6-promise` 4.2.5/4.2.8; single-version-in-years for `performance-now` 2.1.0, `raf` 3.4.1, `rgbcolor` 1.0.1, `stackblur-canvas` 2.5.0. **DOMPurify is `Apache-2.0`** (`D-2026-09-07-01`): MPL-2.0 §3.2 would oblige us to make DOMPurify's own Source Code Form available to everyone who receives a 906 KB minified blob — a real, ongoing obligation for a dependency of a dependency of the PDF button — while Apache-2.0 asks for attribution and adds a patent grant. Cure53's `LICENSE` ships **verbatim with both texts**, because a trimmed copy misrepresents what was offered. **`check-licences.py` gained rule 7**, and then gained a second version of it: the first read a hardcoded `BUNDLES` tuple, and **a mutation that emptied the tuple survived** — the rule could be switched off with every check still green. It now derives which files are bundles from the tree (three or more distinct packages in a vendored script), which is what found `B46`. Two new bugs fell out of this row: `B45` and `B46`. **And a third correction, from a test that already existed.** Rule 7's anti-vacuity guard was written as *"and there must be at least one bundle — two of them are"*, which is a claim about **this** tree inside a checker that `tests/test_licence_alignment.py` also runs against a stripped fixture repo where every `.min.js` is an empty stand-in. It failed there, correctly, on the first full suite. The guard moved to where the claim is true — `tests/test_bundled_package_notices.py`, against the real tree — and the fixture gained two rule-7 mutations of its own, because with every bundle stubbed to zero bytes that file could not otherwise tell whether rule 7 existed. **A checker's assertions must hold on every tree it is pointed at, not only ours.** One surviving mutation is recorded and rejected: renaming a credits row's *link text* (`[canvg]` → `[cnvg]`) leaves the row's URL, its licence link and the file all correct and findable, so it is a typo rather than an attribution defect, and tightening the test to catch it would break the rows whose display name legitimately differs from the package name (`jsPDF`/`jspdf`, `DOMPurify`/`dompurify`, and the one row naming three packages).
- [x] **P0-30** **The notices did not travel.** Adding licence bodies to `licenses/` satisfies MIT/BSD/OFL for the git repository and for nothing else, and all three of those licences require the notice to accompany **redistributed copies**. Found 2026-08-27: `Pantheon.spec:8` and `build-windows-portable.ps1` both listed their payload by hand and shipped no licence file at all, so the desktop builds redistributed a dozen libraries with their attribution stripped; and `.dockerignore`'s blanket `*.md` excluded **`CREDITS.md`** — the exact file `NOTICE` designates as this distribution's third-party notice — from the image. — **done:** `licenses/`, `LICENSE`, `NOTICE` and `CREDITS.md` added to the PyInstaller spec and the Windows `--add-data` list with a comment saying why, and negated in `.dockerignore`. **This was pre-existing, not caused by the licence run — the run is just what made it visible.** `Verify:` build each of the three artefacts and confirm `licenses/` is inside it.
- [x] **P0-31** **`ody-` browser storage keys survive in the test fixtures that prove the rename worked.** `P0-04` renamed 113 storage keys in `static/` and its trace reads "verified — no `ody-`/`ody.` KEYS remain in static/", which is true and was not the whole question. `git grep -nIP '(?<![A-Za-z0-9])(?i:ody)[-.]'` returns **50 lines across 12 files**, 24 of them under `static/`. One was a genuinely red test — `tests/test_app_config_shared_fetch_js.py` seeded `ody-prefetch-settings` while `static/js/appConfig.js:31` reads `pan-prefetch-settings`, so the fixture that exists to prove the rename was pinning the old name and failing. Fixed 2026-08-27; the other 49 lines are unaudited. **And the regex on this row cannot see the biggest one (found 2026-08-31).** `(?<![A-Za-z0-9])(?i:ody)[-.]` matches `ody-` and `ody.` only — **not `ody_`** — and **every API token this product mints still begins with `ody_`**: `routes/api_token_routes.py:130` and `companion/pairing.py:191` both build `"ody_" + secrets.token_urlsafe(32)`, and `app.py:419` documents the format in a comment. That is the fork's old name on the credential a user pastes into another machine, and the row scoped to find it looked past it three times. **Treat the prefix as a migration, not a rename:** tokens already issued must keep working, so accept both prefixes on read and mint only the new one — a bare rename invalidates every paired companion and every stored token at once. `Verify:` every remaining hit of `(?i)ody[-._]` is either deliberate (a migration path reading the old name) or renamed, and each one is named — with the separator class widened to include `_`, or this row cannot see its own subject.
  **Re-derived 2026-09-07 with the widened class.** `git grep -nIP '(?<![A-Za-z0-9])(?i:ody)[-._]'` returns **106 lines across 28 files**, of which 16 are this tracker's own prose. The residue sorts into five kinds, and only two of them are work:
  1. **The token prefix** — and **there were three mint sites, not two**. `routes/api_token_routes.py` and `companion/pairing.py` both minted `"ody_" + secrets.token_urlsafe(32)`; the third, `src/agent_tools/admin_tools.py`, minted **no prefix at all** and every token it produced was inert. That is `B43`, fixed 2026-09-07, and the fix is what makes this row's migration cheap: `core/api_tokens.py` now owns `TOKEN_PREFIX` (what is minted) and `ACCEPTED_TOKEN_PREFIXES` (what is honoured) as two separate names, `app.py` reads the accept side through `bearer_credential()`, and a test asserts no other module spells the literal. **So the code half is a two-value change**: `TOKEN_PREFIX = "pan_"`, `ACCEPTED_TOKEN_PREFIXES = ("pan_", "ody_")`. **Landed 2026-09-07**: `TOKEN_PREFIX = "pan_"`, `ACCEPTED_TOKEN_PREFIXES = ("pan_", "ody_")`, and the five prose sites that quoted the old shape to a first-time user — `src/auth_helpers.py`, `companion/routes.py`, `.env.example`, `docs/setup.md` and both integration READMEs — updated with it. `tests/test_token_prefix_migration.py` holds the promise: 10 tests, 7 mutations, all caught, including *"a rename instead of a migration"*.
  2. **The dead stylesheet selectors** — `B26`, **done 2026-09-07**, and sixteen selectors rather than the ten that row counted.
  3. `@keyframes ody-pulse` / `ody-breathe` (`static/style.css:7196,7200,7213,7222`) — defined and consumed in one file, live, misnamed. Cosmetic.
  4. `data-ody-attach-kind` (`static/js/document.js`, 4 lines) and the `__ODY_OR__` regex sentinel (`static/js/cookbookServe.js:367,369`) — internal, self-consistent, invisible to users. Cosmetic.
  5. **Test fixtures pinning the token prefix** — 48 lines across 8 files, and they are not residue to sweep: they are the fixtures that will have to assert *both* prefixes once the migration lands. Do them with the migration, not before it.
  **Done 2026-09-07, and the last two kinds were the ones that cost something.** Item (5) was
  understated: **five of the nineteen standing suite failures were this row** — four in
  `test_markdown_lazy_lib_loading_js.py`, which asserted `ody-math-pending` against a module that
  has said `pan-math-pending` since the sweep, and one in `test_pr6020_browser_review_regressions.py`,
  whose stub `localStorage` watched `ody-session-cost-runs` while the real ledger wrote
  `pan-session-cost-runs`. They had been red for a fortnight and read as flake. A sixth file,
  `test_agent_round_model_provenance_ui.py`, was **green and wrong**: it splices real functions out
  of `chatRenderer.js` and retyped the constants they close over, so it proved the logic worked
  against a key the product does not use. All three now read the constant out of the module.
  **And a sixth kind the row never listed:** `src/agent_tools/subprocess_tools.py` named the agent's
  persistent shell `ody-agent-<session>`, and that name is how a *running* tmux session is found —
  a bare rename abandons a live shell mid-use and leaves the process running until the machine
  restarts. Same treatment as the token prefix: mint `pan-agent-`, adopt a live `ody-agent-` one.
  The cosmetics went too (`@keyframes ody-pulse`/`ody-breathe`, `data-ody-attach-kind`, the
  `__ODY_OR__` regex sentinel, `ody.example` in a webhook fixture).
  **`Verify:` is now a checker rather than a claim.** `.pantheon/check-fork-names.py` reads
  `git ls-files`, skips vendored and tracker paths, strips comments — Python through `ast`, so a
  docstring explaining the old name survives (`Law 1`) — and fails on any hit not in a named
  `ALLOWED` map. It also fails on a *stale* entry, so an excuse outlives its subject by one commit
  at most. **23 deliberate hits across 7 files, each with a reason**; the 10 remaining raw hits are
  comments and docstrings recording what happened. In CI beside the other eight.
- [ ] **P0-29** **Rename Cookbook → Forge** (`DECISIONS.md` D-2026-08-26-05). It reads as a recipe box; it is a model-serving control plane — remote host registry with SSH keys, GPU detection and hardware fit, weight downloads from HuggingFace and Ollama, vLLM / llama.cpp / Ollama launches held open in tmux, process kill, and task-status polling. 17 routes. **Surface: 3,529 occurrences across 171 files and 43 paths — larger than the Odysseus→Pantheon sweep was** (2,929). *(Re-measured 2026-08-27; scope: case-insensitive `cookbook` in tracked files, excluding `.pantheon/`. The old 3,533 / 172 counted this tracker's own text.)* Use the same tool: `scripts/pantheon-init.sh` is proven and parameterises cleanly. **The name is settled: `Forge`** (D-2026-08-26-05), and the reason is positional rather than aesthetic — Olympus was rejected because it would have cast the models as gods in residence, and AI is under enough of that already. Forge names what the *operator* does. *(This clause read "Decide the name first (`DECISIONS.md`, pending)" until 2026-08-28, on a row whose own title already carries the decision id.)* The one open sub-question is whether *recipe* survives — 242 occurrences, and a vLLM recipe genuinely is a parameterised launch config, so it may earn its keep even if Cookbook does not. `Verify:` no user-visible string says Cookbook; `rail-*`, `tool-*-btn` and modal ids move together with their CSS.

---

# P1 · Token layer — the free wins
*Area: `tokens` · Depends: P0-01 · Blocks: P5, P8*

More visible change than any redesign step, and zero markup touched.

- [x] **P1-01** **Define `--accent` PER THEME, not in `:root`. Defining it in `:root` breaks all 16 themes.** Measured **2026-08-28**: of the **813** `var(--accent…)` sites in `style.css`, **535 are `var(--accent, var(--red))`** and resolve today to the theme's own `red`, which `applyColors()` sets at `static/js/theme.js:263`. A `:root` definition wins over that fallback, so all 521 would flip to one global colour and every theme would lose its identity in a single commit. **The themes are protected — see `DECISIONS.md` D-2026-08-26-03.**
  **Do instead:** `s.setProperty('--accent', colors.accent || colors.red)` beside the existing `s.setProperty('--red', colors.red)`, guarded the same way. The 535 fallback sites then resolve to exactly what they resolve to now (zero visual change), the bare sites resolve for the first time (pure gain), each theme keeps its own accent, and the 8 custom-theme slots get it free — `generateHarmonyColors()` at `theme.js:220` returns no `accent` key, so `colors.accent || colors.red` falls through to red exactly as intended. Add an optional `accent:` key to `THEMES` for any theme that should differ from its `red`.
  **Three corrections, verified 2026-08-27, and all three change the work.** **(1) The count moves — re-derive it before you start.** It was 508 in three documents, then 521 when four independent methods agreed on 2026-08-27, and it is **535** today. `static/style.css` has **three** commits, not the one the previous version of this sentence claimed: `078e0b4` added 342 lines to it on 2026-08-28, some of them new fallback sites. *The sentence that ruled out staleness went stale in a day, which is the most honest argument for `Law 6` this programme has produced.* **(2) There is no `applyTheme()`.** The function is `applyColors()` at `theme.js:257`; the only `applyTheme` in the tree is a dead call at `slashCommands.js:876` behind an `||` the module can never satisfy. An implementer searching for the named function finds nothing. **(3) One line is not enough — `--red` is set at three sites.** `theme.js:263` (the module), `index.html:29` (the first-paint inline script) and `login.html:54` (the login page's own script, which never runs `applyColors` — its comment at `:605-607` says so). Adding the line only in `applyColors()` leaves a flash on every cold load, where the 205 bare sites resolve to nothing until the module boots, and leaves the **login page permanently without `--accent`** — it carries a `var(--accent` site of its own and `index.html` carries 14. **Mirror the line into all three, and bump `CACHE_NAME` in `sw.js`** or returning users keep the old first-paint script.
  — **done at all three sites**, `colors.accent || colors.red` beside `colors.red`, guarded the same way, and **`--accent` is declared nowhere in `style.css`** — a test fails if a `:root` declaration ever appears. Every theme's accent is its own red today, so no theme lost its identity; a theme that should differ gets an `accent:` key.
  **The count moved a fourth time, and the row said it would.** 508 → 521 → 535 → **816 sites at implementation, 553 of them `var(--accent, var(--red))`**. `static/style.css` is 42,739 lines now. Both figures are re-derived by a test, in both directions, so a stale comment fails rather than drifts.
  **The row's two-class model was wrong, and the third class is the work.** 562 sites resolve to the theme's red and **do not move**; **204 paint for the first time** — the row's whole point; and **63 carry a hand-picked fallback that is not red, so defining the token changes their colour.** No version of this row, `DECISIONS.md` or `FORBIDDEN.md` had named that third class.
  **Twelve of the 63 were never accent sites.** A green *verified* badge, two link blues, a supervisor amber and a green completion dot had reached for `var(--accent, <the real colour>)` because `--accent` did not exist and the fallback was the actual intent. Left alone, **`.skill-verified` would have rendered in the same hue as `.skill-needsmark`** on all sixteen themes, and `.note-checkbox-edit:hover` would have matched the delete control beside it at identical geometry. They now name the semantic token they meant — `--color-success`, `--color-warning`, `--color-accent`, `--green` — all four pre-existing, because adding a third colour vocabulary is what `P1-06` is blocked for. The author's literal is kept as each one's fallback: it is the record of intent, and the diff then shows exactly one thing moving.
  *(The remaining fifty stay accent-coloured. They are hover borders, focus rings, selection highlights and drag ghosts — which is what `var(--accent, …)` asks for.)*
  `CI:` none. `Verify:` **rewritten, because the old line would have passed on a tree with the verified badge rendering as an error.** Cycle all 16 themes and diff screenshots: the 204 previously-unstyled elements gain the accent, the 50 reclassified ones change to it, the 12 semantic ones do **not**, and nothing else moves. Then: rail hover backgrounds appear; both resize handles become visible; the scroll-to-bottom button gets its colour; and the session rename input gets a border — that last one is **not** in the bare-site list, because that rule (at `style.css:7020` as of 2026-08-28; it was `:6775` before the file grew) is `var(--accent, var(--accent-primary))` with *both* undefined, so the whole `border` shorthand is invalid at computed-value time and falls back to `border-style: none`. Same fix, different failure mode.
- [x] **P1-02** Define `--accent-primary` (121 uses, never defined) — or replace those uses with `--accent`. **Premise corrected 2026-08-27: this is token hygiene, not a bug hunt.** The line reads as 121 broken uses. It is not — **120 of the 121 already resolve correctly through their fallbacks**, 116 of them to the theme's `--red`. **Exactly one site is genuinely dead** — the session rename input, `style.css:7020` as of 2026-08-28 — — and that is the same pixel `P1-01` already fixes, so as written these two rows overlap on their only real defect. *(Line numbers in this row and `P1-01` move whenever `style.css` grows — re-derive rather than trusting them.)* Do `P1-01` first, then this becomes what it should always have been: an undefined token used 121 times, worth resolving so the next reader is not misled, with no visual change expected and none acceptable. **Re-measured 2026-08-30 with `P1-01` landed, and all three of this row's claims are wrong.** **(1) 132 uses, not 121** — 121 in `style.css` plus **11 in JavaScript**, which no previous measurement scoped for. **(2) Two dead sites, not one.** The session rename input is fixed by `P1-01` as predicted. The second is `static/js/sessions.js:426`, where *"+ New Folder"* set `color: var(--accent-primary)` with **no fallback at all** — so it resolved to `inherit` and the action row rendered identically to the plain folder rows above it. `P1-01` could not reach it: there is no `--accent` in that chain to define. **Fixed in passing 2026-08-30**, because a one-line live defect found while measuring a row is not worth carrying to the next session. **(3) The real content is not hygiene — the token is half-wired.** `create_theme` accepts `accentPrimary` (`src/ai_interaction.py`, `src/tool_schemas.py`) and `index.html`'s first-paint `advMap` writes it, but **`ADV_KEYS` contains no `accentPrimary`**, so `applyColors()` never updates or clears it. A theme made through the assistant sets `--accent-primary` once at first paint and it **sticks, stale, through every later theme switch**. `style.css`'s own header claimed both it and `--accent-error` were *"set by theme.js"*; neither is, and that line is corrected in place. So the residue is: wire `accentPrimary` into `ADV_KEYS` **and** `computeAdvancedDefaults()` in lockstep and into both mirrors, or delete it from `create_theme` and `advMap` — plus an optional sweep of the 130 resolving `var(--accent-primary, …)` uses onto `--accent`, which is the no-visual-change half this row was written as. — **done: deleted, not wired, and the same decision for all four.** `--accent-primary`, `--accent-error`, `--section-accent` and `--toggle-bg` are gone from `index.html`'s `advMap`. **Three of the four have zero readers in the entire `static/` tree** — there was nothing to wire them to. The fourth is a synonym for `--accent`: **124 of its 130 fallback-bearing uses resolve to the theme's red**, which is what `--accent` resolves to on all sixteen palettes and all eight harmony slots. **And wiring it would have moved pixels on all sixteen themes.** `applyColors()` writes every `ADV_KEYS` entry unconditionally, so adding `accentPrimary` would have *defined* `--accent-primary` on every load and retired the fallback at all 131 sites — 124 unchanged, **six changed**. That is the flattening `D-2026-08-26-03` protects the themes from, spelled with a different token name, and `P1-01` refused exactly this for `--accent` eight days earlier. *(Measured again at implementation: **131** uses, not the 132 recorded yesterday — the `sessions.js` fix that row describes is what moved it, so the number was right when written and stale by the time it was read. That is the fourth time an accent count has done this.)* **`ADV_KEYS` gained `hamburgerColor`** in the same pass, which was the missing-key half of the same disease: `style.css` reads `var(--hamburger-color, var(--fg))` and a custom colour flashed `--fg` on every load.
- [x] **P1-03** **Define `--fg-muted`** (93 bare uses, zero definitions). Every one of those elements was authored as secondary text and renders at full strength. `Depends:` P1-01. — **done, and the row's numbers were exactly right** — 101 uses, **93 bare**, 8 with a fallback, **0 declarations**, plus 13 more in JavaScript. **But "renders at full strength" undersells it: nine of the 93 rendered *nothing*.** The bare uses split 87 `color:` / 4 `border-color:` / 2 `background:` — a dropped `color` still inherits, but `.ge-adj-hist-handle` is a triangle drawn *entirely from borders* and painted nothing at all, and every image-editor history dot but the current one was invisible. Three tab strips (`.cookbook-tab`, `.lib-tab`, `.admin-tab`) hovered `--fg-muted → var(--fg)`, so base and hover resolved to the same colour and **on `retrowave` and `terminal`, where `--fg` and `--red` are the same hex, inactive, hovered and active tabs were one colour.** **Class three was empty, and that was verified rather than assumed** — every one of the 101 sites was checked against every rule setting the same property on a sibling selector, resolved on all sixteen palettes. The one candidate ran *backwards*: the stalled-download pill spells `#888`, and on `gpt` — whose red is `#949494` — that grey sat 20.8 units from the accent its running sibling paints, so stalled and running were already the same pill there. The fallback was hiding a collision, not protecting one. **The value is `color-mix(in srgb, var(--fg) 45%, var(--color-muted))`, and the reasoning is the row's real content.** Both obvious choices are wrong and measurably so: every point on the `--fg`→`--bg` segment passes within **22.0 sRGB units of `forest`'s accent** at *every* ratio, and the sheet paints "inactive" in `--fg-muted` against "active" in `--accent` at **33 opposition pairs** — so the natural value collapses all 33 on `forest`, and on `gpt` too. That is `P1-01`'s third class relocated from the fallbacks into the *value*. Pivoting through `--color-muted` moves the closest accent approach to 45.6 and the collapsing pairs to zero. Fourteen of sixteen palettes clear 4.5:1; `cute` and `retrowave` are the `B15` ceiling — their own `--fg` measures 3.44 and 4.15 against their own `--panel` — and on `cute` the muted token now **out-contrasts the palette's own body text**. `Verify:` the three tab strips show which tab is active on all sixteen themes, and the image-editor history handles are visible.
- [x] **P1-04** **Delete `#sidebar-backdrop { display:none !important }`** at top-level nesting depth 0 — it beats the media-query rule everywhere. Thirteen call sites across four modules already toggle the element. `Verify:` mobile drawer dims the page and tap-to-close works. — **done, and "delete" would have been wrong.** Confirmed by brace-depth walk: the element's every style lives inside `@media (max-width:768px)`, so with the top-level rule simply deleted it becomes a bare `<div>` — and `body { display: flex }`, so a zero-width flex child rather than nothing. The rule is **scoped** instead, to `@media (min-width: 769px)`, the sheet's own house complement with 13 existing uses. Desktop resolves identically to before; at 375/640/768 the backdrop now dims and takes the tap that closes the drawer. **Why it existed:** it sits immediately below `#mobile-backdrop, #mobile-menu-btn { display:none !important; }` and arrived in the same commit — **a live element caught by a blanket rule written for dead markup.** Those two are genuinely dead (zero JavaScript references; `#mobile-menu-btn` is a second `☰` beside the live one), so they stay hidden, and a test now asserts both that they stay hidden and that no script references them — if the markup ever goes live, the test says to revisit.
- [x] **P1-05** **Fix `#rail-settings`** — it unhides the sidebar and scrolls to the bottom instead of opening Settings. **Premise corrected 2026-08-27.** The rail gear is genuinely broken and stays open, but **the guided tour is not its victim.** The tour opens Settings through `#user-bar-settings` (`slashCommands.js:3337`), which works; the `#rail-settings` branch is reached only when that element is absent, and `ui_visibility.js:32` guarantees it never is. That branch is unreachable dead code. **The old `Verify:` passed on an unfixed tree** — a rewritten one is the only reason this row is still worth opening. `Verify:` click the rail gear on a cold load with the sidebar hidden; the Settings panel opens and the sidebar does not scroll. — **done:** the handler is now one line, `settingsModule.open()` — the same opener `#user-bar-settings`, `/settings`, the model picker, the email library, the calendar and admin all use, rather than a second way into one panel. **Not** routed through `#user-bar-settings.click()`, which would make a sidebar element load-bearing for the rail and would break when *Customize UI* hides that button — a case `ui_visibility.js`'s guarantee does not cover, because it guarantees the node exists, not that it is displayed. **The unhide and the scroll are both gone, and the old pairing was self-defeating:** `#settings-modal` is a body-level full-viewport overlay, so there was no sidebar location to scroll to — and `syncRailSide()` sets the icon rail to `display:none` when the sidebar is open, so the old handler hid the very rail containing the gear the user had just clicked. `sidebar-layout.js:241` had *already* excluded `#rail-settings` from its scroll-to-section handler; the `app.js` handler was doing exactly what its sibling deliberately excluded it from. The `"Scroll to bottom where settings typically are"` comment is kept verbatim as a correction note — the guess was tried, and the next reader should know.
- [ ] **P1-06** Add semantic status tokens derived from the five theme tokens. — **BLOCKED on its own premise (2026-08-27).** Two problems, both fatal as written. **(1) The numbers do not exist.** 517 / 68 / 420 carried no scope and reproduce under none tried (`Law 5`); the nearest defensible measurement is **346 occurrences across 75 distinct non-grey hex values in `static/style.css` outside `:root`**. Nobody can size this row until its scope is written down. **(2) It would fork a third colour vocabulary.** `--warn` already exists at `style.css:30`, and the codebase already carries two semantic colour scaffoldings. Adding `--ok --warn --danger --info` beside them is precisely `Law 14`. **Unblock by:** stating the scope, then extending whichever of the two existing vocabularies is the better host — not by adding a third. `P1-07`'s 135 loose hexes outside `:root` fold in here. — **Unblocked 2026-08-31: `B22` is the scope this row was blocked for.** It names the exact set (`--green`, `--warn` and the seven `--color-*` tokens, static `:root` literals in `static/style.css`), the exact population (the twelve sites `P1-01` moved, joining **100+** that already had the shortfall), and a measured failure (`--green` on `paper` at **1.37:1**) — which is what *(1)* asked for. It settles *(2)* by elimination rather than by choice: the host is the `--color-*` vocabulary that already exists, made theme-scoped instead of `:root`-static. Nothing new is added, so `Law 14` is satisfied by construction. **The work is now stateable: move the semantic tokens into `theme.js`'s per-theme block beside `--red` and `--accent`, and give the four light palettes their own values.** `B22` is this row's measurement half and closes with it — do not work them separately.
- [x] **P1-07** Separate the Dracula/One-Dark syntax-palette occurrences into their own token set. — **SUPERSEDED (verified 2026-08-27) — the separation already exists.** Ten `--hl-*` tokens are declared and used 97 times, and they are recomputed per theme at `theme.js:270-281` and `index.html:45-56`. The palette was never unwired; the audit read the loose hexes and inferred a missing system. Re-measured with scope: 150 occurrences of the 27 One-Dark ∪ Dracula values in `static/style.css`, **135 of them outside `:root`** — and roughly half are duplicates of `--red`/`--green`, which makes them ordinary hardcoded colours. **Folded into `P1-06`**, which is the row that owns loose hexes. Nothing here is a separate task.
- [ ] **P1-08** **Computed `--on-accent`.** `.send-btn` hardcodes `color:#fff`; white-on-accent fails 4.5:1 on **15 of 16 themes**, and the accent itself fails on **8 of 16**. *(Re-measured 2026-08-27 — WCAG 2.x relative luminance per theme against the resolved send-button background and the theme background. One theme passes, which is worth knowing: it is the proof the token can be right rather than merely uniform.)* One token fixes all sixteen. **Re-measured 2026-08-30, now that `--accent` resolves and the blast radius is knowable.** **187 declarations set `color:` to the undiluted accent**, and seven palettes miss 4.5:1 against `--panel`: `paper` **2.24**, `cute` 2.56, `light` 3.03, `claude` 3.26, `lavender` 3.63, `organs` 3.72, `retrowave` 4.15. `paper` and `cute` miss even the 3:1 large-text floor. **And the larger half this row already half-named: 33 rules paint text directly on an undiluted accent background, 19 of them with a hard-coded `#fff`.** At least 14 of the 33 fall under 4.5:1 on *every* theme; on `light`, `paper`, `retrowave`, `lavender`, `claude` and `cute`, all 33 do. **Two of the sixteen cannot be fixed by this row at all** — `cute` and `retrowave` put their own `--fg` under 4.5:1 against their own `--panel` (3.44 and 4.15), so no colour reaches the floor there; that is `B15`. A test pins the failing *set* and the 187 *population*, so a dimmed red, a new palette, or a new full-strength accent `color:` fails rather than drifts.
- [ ] **P1-09** Add a contrast guard inside `generateHarmonyColors()` and `applyColors()` (~15 lines) so every future custom theme clears the floor too. `Depends:` P1-08. **`CI:`** any new theme token must extend `ADV_KEYS` **and** `computeAdvancedDefaults()` in lockstep or all 16 themes break.
- [ ] **P1-10** **Normalise z-index to 7 named tiers.** **259 declarations, 64 distinct values** (re-measured 2026-08-27, scope: `static/style.css` only — 63 numeric plus one `var()`), range −1 to 1,000,000. Use the order-preserving remap: strictly increasing in the same sorted order ⇒ no element can change stacking. `Verify:` the remap list is strictly increasing; nothing moves visually.
- [ ] **P1-11** Fix the toast occlusion the tiering surfaces — toasts sit at 9999, below every image-editor popover at 10001–10006. Deliberate second pass, needs visual review. `Depends:` P1-10.
- [x] **P1-12** **One global `prefers-reduced-motion` guard.** 18 narrow opt-outs against **160 keyframes** and 7 unguarded canvas animators — the background effects run continuously with nothing. **The 160 is the load-bearing correction** (re-measured 2026-08-27): 148 live in CSS, and **12 are injected into `document.head` at runtime by `slashCommands.js`**. A CSS-only guard cannot reach those twelve, so a guard written against the old 148 would pass its own review and still animate. Guard the injection site too. — **done 2026-09-07, and the row's central claim is withdrawn.** **A CSS-only guard *does* reach the injected keyframes.** An `!important` author declaration beats a normal one whatever stylesheet it came from, so `animation-duration: … !important` overrides the shorthand in a `<style>` element written into `document.head` at runtime exactly as it overrides one in this file. No injection-site guard is needed and none was written. **The real trap was one the row did not name**, and it is why the obvious guard fails silently: **21 `!important` declarations of `animation`/`transition` already exist in `style.css` across 34 selectors** — the most specific `#email-lib-modal.email-lib-fullscreen .modal-content` at (1,2,0) — and between two `!important` author declarations, **specificity decides before order does**. `* { animation-duration: 0.01ms !important }` loses to every one of them while reading as correct. The guard is `:is(#\9#\9#\9, *)`: `:is()` takes its most specific argument's weight, `#\9` is an id nothing can have, `*` is what matches. **And it must not say `animation: none`** — modules across this product clean up in `animationend`/`transitionend` handlers (`compare/panes.js` clears an inline animation there; `app.js` restarts the welcome animation by toggling it), so `none` means the event never fires and the "safer" spelling is the one that leaves state stuck. `0.01ms` is invisible and still fires. **Counts re-derived:** 149 keyframes in `style.css` (not 148), 5 *distinct* injected ones (not 12 — `slashCommands.js` carries the same three-keyframe `egg-styles` string **ten times verbatim**, guarded by an id check so only the first ever applies), 20 pre-existing narrow blocks (not 18), all kept (`Law 1` — several substitute a static appearance rather than freezing a moving one). **The JS half is the part CSS genuinely cannot reach**: `static/js/motion.js` owns the query, `theme.js` no longer starts any of the seven canvas animators under reduced motion — the theme class still applies, so colours and styling are untouched — and the Appearance panel says so, because a slider that vanishes with no explanation reads as a bug. `P1-15` is what this row leaves behind — and `B47`, which it broke on the way: a four-line import took 54 theme assertions down because the JS sandboxes keep a hand-written stub per import, and the stub list is a second copy of the import list.
- [ ] **P1-15** **Smooth scrolling ignores `prefers-reduced-motion`, in 52 places.** `P1-12`'s CSS guard sets `scroll-behavior: auto !important`, and that is not enough: `scrollIntoView({behavior: 'smooth'})` and `scrollTo({behavior: 'smooth'})` name the behaviour in the call and override the stylesheet, by design. **52 sites** (measured 2026-09-07, scope: `behavior: 'smooth'` and `scroll-behavior: smooth` in `static/`), the heaviest being `slashCommands.js` (12), `document.js` (8) and `emailLibrary.js` (7). The fix already exists and is one import: `scrollBehavior()` in `static/js/motion.js` returns `'auto'` or `'smooth'`. **This is filed rather than swept because it is 52 edits across 17 files for one line of value each**, and a sweep that size belongs in its own change where the diff can be read. One more thing rides with it: `compare/vote.js:279` is the only `element.animate()` call in the product — the Web Animations API is invisible to both the CSS guard and `scroll-behavior`, and it needs the same helper. `Verify:` no `behavior: 'smooth'` literal remains outside `motion.js`; `element.animate` asks first. `Depends:` P1-12 (done).

- [ ] **P1-13** Elevation tokens: 4 theme-aware shadows replacing **288 declarations / 209 unique values** (re-measured 2026-08-28) (re-measured 2026-08-27, scope: `static/style.css`, comments stripped). **144** hardcode `rgba(0,0,0,α)` — re-counted 2026-08-28 across the whole file — on the four light themes those read as grey smudges. **156 of the 287 are already token-aware**, which the old figures hid: slightly over half the file is done, and the row is smaller than 287 makes it sound. The good theme-aware form already exists and is used 6 times.
- [x] **P1-14** Name the signature curve. `cubic-bezier(0.34, 1.56, 0.64, 1)` is used 34 times and has never had a token. — **done 2026-09-07.** `--ease-signature` in `:root`, 34 sites converted, count confirmed at 34 exactly. **Twenty distinct `cubic-bezier()` values live in `style.css`** and only this one is named: the rest are situational and stay literal until someone has a reason. **Three are near-misses on the signature and are deliberately not swept in** — `0.34, 1.2, 0.64, 1` (×2), `0.34, 1.32, 0.55, 1` and `0.34, 1, 0.64, 1` are the same shape with a gentler overshoot, which is either a considered choice or drift, and folding them in would answer that question by accident (`Law 1`). A test pins their counts, so a later sweep has to be a decision rather than a cleanup. `:root` is the right home and the `P1-01` prohibition does not carry: that one existed because 554 sites shipped a `var(--red)` fallback a `:root` rule would have flipped, and no site carries a fallback for an easing curve. 5 tests, 4 mutations, all caught.

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
- [ ] **P2-13** **Was blocked — correctly, on something the spec never named.** Premise verified true: both clamps exist at `src/llm_core.py:1071` and `src/agent_loop.py:2212`, and the Anthropic cloud clamp at `:1572` is untouched. But **four assertions in two unowned test files pin the cap** — `tests/test_llm_core_temperature_reasoning.py:104` and `tests/test_pr6020_rebase_regressions.py:182/:201/:216`. The two qwen tests exist to prove a mixed fallback chain leaks temperature in neither direction, and that property must survive any rewrite. **Also needs a decision:** `_apply_local_generation_stability` receives only a payload dict and cannot tell *the user asked for 0.9* from *0.9 is a default*, so a faithful "default, not cap" needs an explicitness signal threaded from the builder. The agent refused to ship a hidden env escape hatch with no UI — right call. **DECIDED — thread an `explicit_params` set from the payload builder; the clamp becomes a setdefault for everything else. Keep the Anthropic ceiling** (D-2026-08-26-06). — **Unblocked 2026-08-31.** The row states its blocker as *"also needs a decision"* and then records that decision two sentences later. `D-2026-08-26-06` supplies the explicitness signal the agent correctly refused to fake with a hidden env var. The four pinning assertions are **scope, not a blocker**: they are named, they are in two files, and the row already says they must be rewritten in the same commit rather than discovered. The mark was never flipped after the decision landed.
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
- [x] **P2-26** **Document the app-API blocklist — trim nothing.** *(Retitled 2026-08-27, same reason as `P2-25`.)* The decision is settled and this list gets **stronger** under `P11`, not weaker. **Must stay:** the cookbook install/rebuild/kill entries, every prefix rule, and — **missing from the old must-stay list** — `POST /api/cookbook/state` and `DELETE /api/cookbook/state`. Those two are data-destruction guards that **no test pins**, which makes them the pair most likely to be trimmed by accident and the least likely to be caught. Write the reason beside every entry and close the row. (D-2026-08-26-06) — **done 2026-08-31 by inspection; no code written, because the reasons were already there and they predate the fork.** `_APP_API_BLOCKLIST_PREFIXES` and `_APP_API_BLOCKLIST_METHOD_PATH` (`src/tools/system.py:582-631`) carry a comment on every entry or on the group above it — including the incident that produced the pair this row called out: *"Saw the agent wipe cookbook_state.json (presets + tasks) by POSTing {"tasks": []} to /api/cookbook/state, which overwrote the whole file."* Both `POST` and `DELETE /api/cookbook/state` are present and both annotated. Verified **byte-identical to `/work/base` at `b4d1293`** — 2,375 characters across the two tuples, no drift either way. The row was written from the assumption the list was undocumented; it was documented upstream and the fork has not touched it. **What this row was actually protecting survives elsewhere:** no test pins those two entries, so its real value was the warning that they are the pair most likely to be trimmed by accident. That warning is now in `FORBIDDEN.md` Part 1, where a row marked done cannot quietly stop protecting it.

---

# P3 · Mechanical hygiene
*Area: `css-hygiene` · Depends: P1 · Blocks: P5*

Provably safe, and each one removes a trap the restyle would otherwise fall into.

- [x] **P3-01** **Resolve `#message` declared 4×.** The composer never renders at its authored 14px — a later `!important` forces 13px, and a third rule forces 16px on touch. One of the conflicting blocks sits under a class that does not exist. **Do this before any composer work.** *(Note: `max-height` is fine — 200px wins on specificity; only the font-size conflict is real.)* — **done 2026-09-08, and the row understated it in a way worth reading.** The bare `#message` block does not merely force 13px: it carries **four** `!important` declarations — `font-size`, `line-height`, `overflow-y`, `font-family` — over `.chat-input-bar textarea#message`'s authored 14px / 1.5. **And it is not a competing opinion about the composer.** It sits in the *Unified chat input area* section, and **every other selector in that section is dead**: `.chat-input-area`, `.chat-input-form`, `.chat-controls-row/-left/-right`, `.control-group`, `.control-label`, `.preset-buttons-row`, `.toggle-switch`, `.toggle-slider`, `.action-button` and `#stop-icon` — eleven classes and one id, none of them in any markup or script. An older composer layout, kept in the file, with **one** selector in it that still reaches something because an id is an id wherever it is written. So the row's *"one of the conflicting blocks sits under a class that does not exist"* is right and small: the whole block is under classes that do not exist. Scoped to `.chat-input-form #message` rather than deleted (`Law 1`) — intact, exactly reversible, and matching only the layout it describes. **What the 13px was costing, which nobody had written down:** `#message-ghost` (`.ghost-text-overlay`) is absolutely positioned over the textarea and renders the inline autocomplete suggestion in transparent text so the glyphs line up with what you type. It authors `font-size: 14px; line-height: 1.5` — the composer's *authored* values. Two layers drawn on top of each other were a point apart in size and a tenth apart in leading, so the ghost drifted further right with every character. That is the proof 14px was intended rather than a guess, and a test now pins the two together. The 16px coarse-pointer override is untouched and still wins on touch. 18 tests, 6 mutations, all caught.
- [x] **P3-02** Resolve `.attach-strip` declared 3× with conflicting margin and padding. — **done 2026-09-08.** Three blocks at identical specificity, **two of them three lines apart** and the third 5,200 lines below, so each replaced part of the one before and the rule that applied was written by none of them: `margin` from the second, `min-height` from the second, `padding` and the centring from the third, and the first's `margin: 0 0 8px` / `min-height: 0` never applying to anything at all. Collapsed into one block **at exactly the values the cascade already resolved to** — nothing changes visually — with each declaration's origin recorded beside it. The duplicate `:empty { display: none }` went with it.
- [~] **P3-03** Delete the confidently-dead CSS rule blocks. — **BLOCKED (2026-08-27), for two independent reasons, either one sufficient.** **(1) The measurement does not exist.** 510 / 2,590 / 349 came from a classifier that **is not in this repo**, so nobody can reproduce or re-check them — and they are stale besides: the wiring run deleted 1,524 lines of JS *after* they were taken, which moves every one of those numbers. The arithmetic checks out (2,590 / 41,401 = 6.26%) and that is all that can be said for them. **(2) `P2-20` must land first.** 16 `admin-rag-*` rules in `static/style.css` (`.admin-rag-upload-zone` at `:15733-15747` and others) are dead **only because `P2-20`'s markup is missing** — a sweep run today deletes exactly the CSS `P2-20` needs. **This already happened in reverse and proves the risk:** `.rag-upload-zone` (`style.css:2392/:2402`) was an orphan until `P2-23` landed its markup, and is live again now. **Unblock by:** landing `P2-20`, then rebuilding the classifier with the `check-wiring` scope lesson applied — it must resolve helper lookups, not just `getElementById`. Verified 0/55 false positives on two random samples, which is the one part of the old row still worth keeping.
- [x] **P3-04** Delete duplicate `@font-face` (the whole Fira Code set is declared twice) and the exact-duplicate `@keyframes` — **3 names but 4 duplicate blocks**, because `spin` has two extras rather than one (re-measured 2026-08-27). Deleting three blocks leaves one behind. — **done 2026-09-08, and every number on this row reproduced exactly.** 5 `@keyframes` names were declared more than once and 3 of those were byte-identical (`spin` ×3, `loading-bounce` ×2, `pulse` ×2) = **4 redundant blocks**, as written. `@font-face`: 8 blocks, 5 distinct — the three Fira Code weights each twice. All 7 removed; identical bodies, so nothing changed. 149 → 145 keyframe blocks.
- [x] **P3-05** **Fix the 2 conflicting `@keyframes` redefinitions** — `research-pulse` and `fadeIn`. These are live bugs: the later definition silently wins for every consumer, including code written against the earlier one. — **done 2026-09-08, and only one of the two was costing anything — which is worth knowing before the next such row.** **`research-pulse` was the live one.** `#research-toggle-btn.research-running` asks for it three lines above a definition that pulses the *background*, and gets a definition 6,800 lines below that pulses *opacity and scale*. The comment above the rule says "Research button glow"; the button throbs in size instead and its background never moves. The other consumer, `.session-star.processing`, is a 10px dot with no background — the scale version is what suits it and what it has always had. So: the background version becomes `research-glow` and the button points at it; the dot keeps `research-pulse`. **`fadeIn` was a trap rather than a defect.** Its only consumer sits beside the definition that wins, so nothing looks wrong; the earlier plain-opacity block in the compare-pane section has simply never applied to anything. Renamed to `compare-fade-in` rather than deleted (`Law 1`) — a plain fade is a reasonable thing for that section to want, and the hazard was that a rule added near it would silently get the 10px slide. **A third defect fell out**, found by the check written for this cluster on its first run: `B49`.
- [x] **P3-06** Collapse the clone-body animations into one — **9 definitions under 7 distinct names** (re-measured 2026-08-27; two names are themselves declared twice), every one of them the body `to { transform: rotate(360deg) }`. — **done 2026-09-08. 9 definitions and 7 names both confirmed; the parenthetical is off by one** — it is *one* name declared three times (`spin`), not two declared twice. Collapsed to `spin`: `admin-spin`, `email-spin`, `email-inline-image-spin`, `ge-canvas-spin`, `model-picker-refresh-spin` and `whirlpool-spin` deleted and their six use sites repointed. **The sweep had to leave the stylesheet to finish**: `static/js/settings.js:4948` writes `animation:whirlpool-spin` into an inline style, so a CSS-only rename would have left one spinner still. **And word boundaries were load-bearing** — `admin-spin` is a prefix of the live class `admin-spinner`, and `email-spin` of `email-spinner`; a naive replace would have renamed two classes to `spinner`. A test asserts both classes survive. 145 → 139 blocks, 139 names, no name defined twice.
- [x] **P3-07** **Canonicalise breakpoints to three.** 13 distinct widths today. One **559**-line block switches to mobile at 700px while **2,965** lines switch at 768px (re-measured 2026-08-27, scope: 85 `max-width:768px` blocks, span-summed) — **between those widths the UI is in a mixed state**, and there is a 20px dead zone (701–719) where an unpaired min/max leaves neither rule applying. — **done 2026-09-08, with two of the row's three claims corrected and the third larger than written.** **The 700-vs-768 mixed state is real and was not only CSS.** The 558-line block (row says 559) is 72 selectors, every one of them the image editor. Moving it to 768 alone would have been a half-fix: `static/js/editor/build/right-panel.js` carries **four** more 700s that arm the editor's swipe-to-dismiss and re-parent its controls panel, so at 701–768 the stylesheet would have laid the panel out as a sheet no gesture could dismiss. **And the worst of it was not the editor at all.** `static/js/sidebar-layout.js` disagrees *with itself*: seven tests in that file say 768 — including the one that shows the mobile backdrop — and three said 700, among them click-outside-to-close. **Between 700 and 767 the sidebar was an overlay with a backdrop inviting the click that dismisses it, and the handler for that click returned early.** `calendar.js` had one more, under a comment defining desktop. That is `B50`; eight JS sites moved to 768. **The "20px dead zone (701–719)" is withdrawn.** The `min-width: 720px` block holds one declaration — `.ge-shortcuts-grid { repeat(4, 1fr) }` — and is paired not with a `max-width` but with an unconditional base rule two lines above it that sets two columns. Below 720 the base applies, at and above it the override does; no width is uncovered. A test asserts that pairing so the claim cannot come back. **And "canonicalise to three" is not what was worth doing.** 13 widths → 12, not 3. The remaining ten (420, 460, 480, 520, 540, 600, 640, 720, 820, 821) reflow individual components inside modals and panels rather than switching the shell; forcing them onto a three-value grid would change when those components reflow, to buy consistency in a number nobody reads. The disagreement about **where mobile ends** was the harm, and there is now one answer to it — enforced across the stylesheet, the pre-paint script and every script, with component widths named rather than lumped in. 7 tests, 7 mutations, all caught.
- [~] **P3-08** Add paired-rule comments so a desktop rule points at its mobile override. — **BLOCKED (2026-08-27):** the row cites *"the roadmap's own 'CSS did not move' item"* and **there is no such item** — the citation is self-referential with no antecedent, so there is no way to know which pairs are meant or when this is finished (`Law 9`). It also **must follow `P3-07`**: canonicalising 13 breakpoints down to three rewrites the pairings, and doing this first means writing 85 comments twice. **Unblock by:** landing `P3-07`, then defining what a "pair" is in one sentence.
- [ ] **P3-09** **Land the `color-scheme` fix first, then delete `:root.light`** (21 lines + 3 other sites) — unreachable by construction, since light themes push values through the five tokens and never add a class. **Recover the well-tuned light syntax palette inside it first.** `Verify:` the four light themes stop rendering dark native dropdowns.
- [ ] **P3-10** Delete the **2** dead modules. **Premise corrected 2026-08-27.** **The RAG module is live and must not be deleted** — `P2-23` landed its three DOM targets at `static/index.html:485-487`, so the bail-out at `rag.js:143` no longer fires. Deleting it now would remove a feature that started working four days ago; this is exactly the row that would have caused it. **Corrected again 2026-08-28, and the row is now one module, not two.** What is actually dead: **`calendar/reminders.js`** (114 lines, zero importers). That one goes — update `sw.js` and bump `CACHE_NAME` in the same commit.

  **`tourAutoplay.js` is not dead and must not be deleted. It is the product's entire first-run walkthrough system**, and deleting it is the single most vision-contradicting act available in this tracker. Read: 133 lines of working code, imported at `static/index.html:2642`, mapping seven modals to per-feature tours — `doclib-modal`→`tour-library`, `cookbook-modal`→`tour-cookbook`, `research-overlay`→`tour-research`, `compare-model-overlay`→`tour-compare`, `theme-modal`→`tour-theme`, `settings-modal`→`tour-settings`, `gallery-modal`→`tour-gallery` — one-shot per modal, mobile excluded because tours position halos by rect math. Only `init()` is stubbed, with the comment "Disabled for v1 stability". **`Law 15` exists in this project because its owner stopped using a competitor's *more advanced* version of what we are building, for exactly one reason: *"There's no tutorials and the learning curve is too steep."*** Deleting the only onboarding we have would be that mistake, made deliberately, by the project that wrote the law. Re-filed as `P3-10b`.
- [ ] **P3-10b** **Re-enable the first-run tours — `Law 15`'s first concrete row.** `static/js/tourAutoplay.js` is complete and switched off: `init()` is stubbed with "Disabled for v1 stability", and nobody recorded which instability. Find out whether it still reproduces (the seven target modals have all changed since), then turn it back on behind a setting a person can find. `Depends:` nothing. `CI:` none. `Verify:` a browser with cleared storage opens the Forge modal for the first time and gets its walkthrough; opening it again does not; and the setting that turns tours off is discoverable without reading the source. **This row is the answer to the question the owner asked of a competitor and we have not yet asked of ourselves.**
- [x] **P3-11** Fix the duplicate module specifier — `chatRenderer.js` is imported under 3 distinct specifiers, so a 3,126-line module is parsed three times per page load. A config module's header documents the symptom and works around it; the root cause was never fixed. One-line change per import. — **done, and it was eleven modules rather than one.** `.pantheon/check-specifiers.py` counts modules imported under more than one URL; against the pre-fix tree it read `modules 166 · specifiers 178 · FORKED 11`, and it now reads `modules 167 · specifiers 167 · FORKED 0`. **42 specifier rewrites across 27 files**, plus **eight** `sw.js` precache entries that had never matched a request URL — the fetch handler uses `cache.match(e.request)` with no `ignoreSearch`, so a precached `/static/js/tasks.js` is simply not the response to a request for `/static/js/tasks.js?v=…`. `--max 0` is now a CI job (`wiring-ratchet` → `check-specifiers`), so the fork cannot come back.
  **This was not a performance row. Two features were dead and nobody had noticed.** ES module identity is keyed on the resolved URL *including the query string*, and there is no import map in this tree, so `./tasks.js` and `./js/tasks.js?v=…` are two modules with two copies of their state — and nothing fails loudly when it happens: a registry written through one specifier is simply empty when read through the other. `P6-07`'s queue registry was written into a `tasks.js` instance the sidebar never reads. `chatStream.js:553` called `adoptSession` on a second instance of `research/jobs.js` whose `_jobs` array was always empty, so the `research_started` fast-path adopt did nothing and every agent-started research job waited for the slow poll instead. **And the fork silently defeated a control `FORBIDDEN.md` says never lifts** (line 38): *"the approval cache-buster string must be bumped across all six approval-path modules together."* It was structurally impossible to obey — `sessions.js` held `chatRenderer.js?v=20260815toolapproval4` while four other importers held `?v=20260819approvalcontrol1` and four more imported it bare, with no buster at all. *(`appConfig.js`'s header, which documented the symptom and worked around it, is corrected in place rather than deleted — `Law 1`. The shared config cache is still worth having; it is now worth having for one reason instead of two.)* `Verify:` `python3 .pantheon/check-specifiers.py --max 0` exits 0, and its report lists every module exactly once — nine `chatRenderer.js` importers on one specifier where there were three.
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
  row that gets ticked without a fix. The real target is `except Exception: pass` — and **the count was wrong and carried no scope,
  which is the `Law 5` failure this row itself was written to punish.** Re-measured 2026-08-31 by AST
  (an `ExceptHandler` whose body is exactly one `Pass`), excluding tests, with the scope stated:
  **250** across `src/`, `routes/`, `services/` and `app.py` (278 files); **314** once `mcp_servers/`,
  `companion/`, `core/` and `integrations/` are included (299 files). Not 199 under either reading.
  **Bare `except:` is 0 in both scopes**, which does confirm the row's other half. Grep cannot measure
  this — `grep -A1` miscounts multi-line handlers in both directions — so the acceptance test has to
  parse. `Verify:` a script that AST-counts silent handlers over a named scope reports 0, or every
  remaining one logs, surfaces to the user, or carries a comment saying why swallowing is correct there.
- [ ] **P3-18** **Stacking order: menus above modals.** They shipped dropdowns and context menus
  rendering *behind* open dialogs. Pantheon has a window system, a tile manager, modal chrome
  and popovers. `Verify:` every popover opened from inside a modal is visible.
- [ ] **P3-19** **Graph and canvas surfaces need a no-acceleration fallback.** Their Brain graph
  crashed outright on machines with hardware acceleration disabled. `P13-07` is a graph.
  **Restated 2026-08-28: the graph half of this row is moot.** `D-2026-08-26-08` cut the canvas,
  the force layout and the constellation — `P13-07` builds a page you read, not one you drag, so
  there is no graph to make resilient and there never will be. **What survives is the canvas
  half, and it is real today:** the 7 unguarded canvas animators named in `P1-12` ship in the
  product now, and a machine with hardware acceleration disabled is the case that broke a
  competitor outright. Rewrite as: the seven background animators degrade to a static background
  rather than failing, and `Verify:` the app renders correctly with acceleration off. *(The canvas half is not idle work:
  the 7 unguarded canvas animators in `P1-12` are already in the tree today.)* **Unblocked 2026-08-31 — the mark was stale, not the row.** The 2026-08-28 restatement above *is* the discharge: the blocker was that the graph half had no defensible target, `D-2026-08-26-08` removed the graph, and the restatement rewrote the row around the seven canvas animators that ship today. Nothing was outstanding after that paragraph was written; only the `[~]` was never flipped.

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
- [x] **P3-15** **Extend the check to the other half of the disease** — routes with no caller,
  settings keys with no reader, feature flags with no consumer. `P2-18` found three flags with
  zero consumers by hand; a script finds the next three for free.
  **The audit that this script would have automated ran by hand on 2026-08-30 and produced the
  21 `H` rows.** Its findings are the specification: build the script against them, and a
  correct script rediscovers all 21. What it established that changes the row:
  **(1) The route count is 500, not 301.** `routes/*.py` top-level is 304; **173 more live in
  `routes/<subdir>/*.py`** plus 5 in `companion/`. Three of the audit's best findings are in the
  half a naive scan omits. Get the list by walking `app.routes` — this FastAPI keeps included
  routers nested, so a flat walk returns 69 and recursion returns 505.
  **(2) Path matching needs three passes.** Literal search alone is useless against
  `` `${API_BASE}/api/a/${id}/b` ``. What worked: normalise both sides to segment patterns; then
  a head-plus-tail-on-one-line probe; then a per-file base-variable resolver, which was the only
  thing that caught three false positives in `assistant.js`. Two independent methods agreed on 90
  routes and disagreed on 8 — the stricter was right all 8 times.
  **(3) `check-wiring.py` has two more blind spots than the two already recorded.** It matches
  only a lookup whose argument is a **string literal**, so an id map indexed by a variable scores
  clean — and on 2026-08-30 exactly that hid the highest-harm defect in the audit, where the agent
  reported opening a panel that had no button behind it. And it **does not strip comments**, so
  writing that sentence with the call spelled out made it count the comment as a fourth unresolved
  lookup. Fix both before extending it.
  **(4) 84 environment variables are read by app code and absent from `.env.example`**, including
  the switch that silently uncaps every local agent run (`H08`). 128 read / 54 declared / 55
  forwarded by compose / 33 in `docs/setup.md`.
  `Verify:` the script finds `H01`, `H04` and `H10` from a clean checkout with no hints.
  — **done 2026-09-07, and it does.** `.pantheon/check-unreachable.py` finds `H04` (`/api/embeddings/models`, `/api/embeddings/endpoint` — the model manager with zero pixels) and `H10` (`/api/cleanup` and its `preview` dry run) from a clean checkout with no hints. `H01` was the third and is fixed, so its *shape* is asserted against a fixture instead — otherwise the checker would only be proven on defects that happen to remain. **443 routes reached, and the row's warning about the walk was the load-bearing sentence.** The first implementation recursed into `route.app` and `route.router`, both of which are `None` on this FastAPI's `_IncludedRouter` — so it recursed, found nothing, and reported **23 routes** while looking entirely correct. The content hangs off `original_router`. **Path matching is pattern-to-pattern**, both sides normalised so every parameter, template hole and variable becomes `*`: `/api/gallery/{image_id}/rename` and `` `${API_BASE}/api/gallery/${id}/rename` `` share no useful substring and are the same route. The head-plus-tail probe the hand audit needed as its second pass is there as every prefix of the pattern. **It reports, it does not accuse** — an API token, a CLI, a webhook sender or the agent's own `app_api` may be the caller — so it is an inventory with a ceiling (`--max-routes 91` — 104 before `H10`, `H11`, `H12`, `H13` and `H04` wired thirteen of them; the ratchet comes down with every fix, because a ceiling left where a fix left it is slack nobody voted for) in the shape `check-wiring` and `check-outbound` already use, and every `ALLOWED` prefix names who calls it. A test fails on an entry without a real reason.
  **The three `check-wiring` blind spots the row required closing first are closed, and one of the fixes was itself the defect this project keeps finding.** The obvious comment stripper — `re.sub(r"/\*.*?\*/", "", src, flags=re.S)` — took `static/js/gallery.js` from **144,034 characters to 64,919**, because a `/*` inside a string opened a comment that ran thousands of lines. Every `id="..."` in the span went with it and the checker reported **153 unresolved ids that are created three lines from where they are looked up**. It is a character scanner now, string- and regex-literal aware, and the test asserts the output length is unchanged. The **variable-indexed collection** blind spot — the shape that hid the audit's highest-harm finding, an agent reporting it had opened a panel with no button behind it — needed two corrections of its own: the first rule ("this file has a computed lookup, so every literal collection in it counts") took UNRESOLVED from 2 to **511**, sweeping up model catalogues and icon names; requiring the collection to be named *at* the lookup brought it to 153, binding iteration to the **loop variable** killed `args: ['-y', 'caldav-mcp']` from an MCP preset table, and requiring kebab shape killed menu labels like `Calendar` and `Done`. **`static/app.js` and `static/sw.js` were never scanned at all** and now are. **UNRESOLVED moves 2 → 9, and nothing regressed** — the checker can see further. The seven new ones are `notes-fullscreen-toggle` and `mode-toggle` (predicted by name in this row's own notes), `notes-panel`, `message-input`, `overflow-research-btn`, `rail-agents` and `tool-agents-btn`; the last two sit behind a `.filter(Boolean)` that has been tolerating their absence. Each is an `H`-class finding and none is fixed here — discovering them was the row. 23 tests, 15 mutations, all caught. *(Two survived and were the same trap as the last five rows: `test_static_app_js_is_actually_scanned` called `tracked()` and checked the file was in the list, which stayed true when `main()` was changed to ignore it. Both assert through the real run now, on ids only that code path can produce.)* **(4) is not done**: the 84 environment variables read by app code and absent from `.env.example` are a separate scan against a separate source of truth, and folding them into a route checker would be one script doing two jobs. Filed as `P3-23`.

- [ ] **P3-22** **`supports_tools` decides whether an endpoint gets tools at all, and there is no way to set it.** `ModelEndpoint.supports_tools` is `nullable, default=None`; `POST /api/models/endpoints` accepts it as a form field (`"true"`/`"false"`/`""`); and **nothing in `static/` sends it** — the only writers are `cookbookRunning.js` (when a vLLM command contains `--enable-auto-tool-choice`) and the Copilot importer. So an admin who knows their runtime supports native tool calling has no way to say so, and `_agent_route_tool_mode` falls back to a model-name allowlist (`qwen3`, `llama-3.1`, …) that an Ollama or llama.cpp URL short-circuits before it is consulted. `B39` made the failure mode honest — a route with no native tools now gets the fenced prompt and works — but *correct by fallback* is not the same as *configurable*, and the fallback misjudges any runtime whose model names are not on the list. **A tri-state control, not a checkbox:** `None` means "work it out", and collapsing that to false on save would silently downgrade every endpoint anyone edits. `Verify:` an admin can tell Pantheon their endpoint speaks native tools, and see what it currently believes. — found while fixing `B39` — agent:`H09`

- [ ] **P3-21** **On local inference every preset's `max_tokens` is the same number, so a preset's token budget means nothing.** Each shipped preset picks one deliberately — Code Analyze 8000, Reason 6000, Brainstorm 4096 — and the local-inference lift raises all of them to 1,000,000 (`src/agent_loop.py`, `_resolve_local_lifts`). `H08` fixed the settings-backed caps beside it, where the operator's number was overwritten and nobody would defend that; **this one is a genuine product question and is not being answered unilaterally.** The case for lifting: on your own GPU tokens are free, and a preset truncated mid-answer is worse than a long one. The case against: 4096 on Brainstorm is not a cost control, it is *the preset* — short, punchy ideas — and flattening it makes the picker cosmetic on the default deployment. There is no third position where both hold. A middle path exists: treat the preset value as a floor and lift only presets that never set one, which today is none of them. `Verify:` the owner has picked, and the reason is in `DECISIONS.md`. — found while fixing `H08` — **needs the owner** — agent:`H08`

- [ ] **P3-20** **124 element ids the JavaScript looks for and no markup provides — the backlog `check-wiring.py` could not see until `H07`.** The checker matched literal `getElementById` only, and this product reaches for elements through a one-line helper at **925 call sites against ~1,100 direct ones**; scanning both took lookups 600 → 1,395 and UNRESOLVED 9 → 124 **without a line of product code changing**. `VERIFY-2026-08-27.md` measured 125 the same way a week earlier and the checker was never updated, so this is a known number finally wired to a ratchet. Biggest groups: `adm-*` 39, `set-*` 35, `intg-*` 13, `caldav-*` 6. **They are not all defects and must not be cleared as a batch.** Three kinds are mixed together: (a) legacy fallbacks in an `||` chain that can never resolve — `el('adm-epLocalMsg') || el('adm-epApiMsg') || el('adm-epMsg')`, `getElementById('message') || getElementById('message-input')` — harmless, and each one is a sentence about a rename nobody finished; (b) whole dead blocks, like the five `set-carddav-*` ids `H07` found, where a feature was replaced and its predecessor's wiring stayed; (c) genuine missing markup of the `H02` kind, where the handler is right and the button was never drawn. **A worked example of (b), found during `H10` and recorded so the triage does not start from zero:** `initRag` and `initWebhookForm` are both defined in `admin.js`, together about 250 lines, both reference `adm-rag*` / `adm-wh*` ids with no markup anywhere, and **both were dropped from `initAll`'s `inits` list rather than deleted** — so they would throw on their first `addEventListener` if anything called them, and nothing does. That accounts for a chunk of the `adm-*` 39 in one stroke and explains the shape: someone hit the error and removed the call. Note `H16` describes the webhooks UI as absent; it is not absent, it is unmounted, which is a different and much smaller fix. `Verify:` each id is triaged into one of those three and the ceiling comes down; a batch delete would take the third kind with it. `CI:` `check-wiring.py --max 124` — **it may go down, it may not go up.** — found while fixing `H07` — agent:`H07` — **⚠ TRIAGED 2026-09-07, and the row's own `Verify` is wrong. Corrected by the agent that filed it.** The 124 were classified by **how each id is reached**, not by prefix, and the answer is not a backlog: **at least 87 of 124 are guarded by construction** — JS that knows the markup may be absent and returns early, `if (!cmdEl) return;  // MCP form not present in this build`. That is not drift. It is a feature removed cleanly, with its wiring left behind on purpose, costing one null check on init. The rest: ~10 are dead `||` fallbacks that can never resolve and harm nothing (`el('adm-epLocalMsg') || el('adm-epApiMsg') || el('adm-epMsg')`), ~11 sit in the two genuinely uncalled functions (`initRag`, `initWebhookForm`), and the residue is small. **The classifier was run four times and the number fell every time** — 38 → 20 → 16 unguarded — because each pass found another guard spelling it had missed (`?.`, `if (el(...))`, assign-then-test, a batch of consts followed by a batch of `if` blocks). Spot-checking the last sixteen found more false positives still: `notes-panel` is a **modal-registry key, not an element id**, and `model-sort-dropdown` is guarded by a two-name condition. **So the honest count of genuinely unguarded lookups is small and I did not pin it**, because every attempt to narrow it moved it down. `adm-ragDirList` is one real example — `dirList.innerHTML = ...` with no check — and it lives in the same dead RAG panel as `initRag`. **What this means for the row: "the ceiling comes down" is the wrong goal.** Bringing it down means deleting guarded code that costs nothing, which `Law 1` forbids and which buys nothing. **The value is the ratchet, not the number** — it cannot grow, so a NEW id with no markup shows up immediately, which is exactly how `H02`'s rail button and `H07`'s `set-carddav-*` would have been caught on the day they were written. `Verify:` **rewritten** — the ceiling stays where it is and CI keeps it there; what should come down is the count of *unguarded* lookups, and the two uncalled functions belong to whoever owns the RAG and webhook panels. — triaged agent:`P3-20`

- [ ] **P3-23** **84 environment variables are read by app code and absent from `.env.example`.** Measured by the discovery audit on 2026-08-30: **128 read / 54 declared / 55 forwarded by compose / 33 in `docs/setup.md`** — four sources of truth and no two agree. Among the undeclared is the switch that silently uncaps every local agent run (`H08`), which is the argument for the row: an operator cannot turn off a behaviour they cannot discover, and `.env.example` is where they look. Split out of `P3-15` on 2026-09-07 rather than folded into `check-unreachable.py`: the route scan compares a mounted app against frontend strings, this compares `os.getenv` call sites against a declared list, and one script doing both would have two ceilings and one name. `Verify:` a script names every variable read and undeclared, and CI holds the count. Same shape as `check-outbound.py` — the number may fall and never rise. — filed during `P3-15` — agent: `opus-5` *(Renumbered from `P3-17` to `P3-23` on 2026-09-08: it was filed one day earlier under an id `P3-17` already held by the *Fail loudly* row above, and nothing checked. `B48`.)*

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
- [ ] **P4-03** **Audit, then delete or wire — the skill-saved handler.** The frontend listens for an event the server never emits. `Law 1`'s only exception is a deletion *proven dead by audit*, and this row had none: no file:line, no scope, no `Verify:`. Establish first whether the *handler* is dead or the *emit* is missing — a save that never notifies the UI is a `Law 13` gap, not dead code, and deleting the listener would close it the wrong way. Decide on the row and record which it was.

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

- [x] **P4-25** **Capture a receipt per agent run** — model and endpoint, resolved sampling
  parameters, the tool schemas actually sent, which skills were injected and at what confidence,
  which memories and documents were retrieved, round count, token usage, and every approval
  decision with its outcome. **Premise corrected 2026-08-27.** **"All on the wire, none kept" is wrong in both
  directions.** Five of the eight items already persist (`routes/chat_helpers.py:1044-1070`), so a
  fresh receipt table would duplicate them — `Law 14`. Three are neither on the wire nor kept,
  and those are the actual work: **extend what persists, do not start a second store.**
  — **done 2026-09-02, and the premise was re-measured before building.** The 2026-08-27 correction said five of the eight items persist; measured again after `P14-01`/`P14-02`, **seven do** — the loop instrumentation added approvals and tool outcomes on its way past. The remainder is exactly three, and they are the three that explain why two runs of *the same thing* differ: **resolved sampling parameters, the tool schemas actually sent, and which skills were injected at what confidence.** **No third store** (`Law 14`): `events` gains a `run_id` column and one `run_config` row per turn holds those three; everything else was already being written. **A receipt is a range scan on `run_id`** — which is why it is a column and not a key inside `detail`, since JSON extraction in SQLite is neither indexable nor pleasant. **Tool schemas are stored as name + a 16-char hash, not in full.** The point of recording them is to make a *change* visible; full schemas are kilobytes each and dozens per turn, and `P4-28`'s diff reads a changed hash exactly as well as a changed blob. Fingerprints are order-independent, because a tool list that arrives shuffled is not a different configuration and a diff that says so will be ignored. **Sampling is an allowlist**, same reason as `P16-14`'s settings — a denylist keeps whatever it did not think of, and the payload it is filtering contains the prompt. **No message content reaches a receipt**, which is what makes `P4-27` possible at all: one you cannot hand to someone is not portable. Captured where the values are **resolved** — inside `_stream_llm`, after defaults are merged and caps applied, and after the skill threshold is applied — because a receipt built from what the caller intended records the wrong thing on every path that adjusts either, and several do. Once per turn via a `ContextVar`, not a module global: a global would let the first turn of a busy minute suppress everyone else's. Served at `/api/diagnostics/receipt/{run_id}`. 21 tests, 7 mutations. **A bug caught during the build and worth naming (`B32`):** the skills capture passed `session_id`, which `_build_system_prompt` does not take — and the `except Exception` around it would have swallowed the `NameError` forever. **Guarded code that never runs and never says so is worse than code that fails.** There is now an AST test that resolves every name at that call site against the enclosing function's parameters.
- [x] **P4-26** **Make a receipt re-runnable.** Same inputs, same configuration, new run —
  which is the only honest way to answer "did that change help". `Depends:` P4-25.
  — **done 2026-09-02.** `src/replay.py`: `rerun_plan()` reads a receipt and reports what it would take, `replay()` executes it as a **new run** that links back, and `GET/POST /api/diagnostics/rerun/{run_id}` expose both — GET is free and read-only so the claim can be checked before a model call is spent on it. **The part that is not obvious: a receipt is not enough on its own.** `P4-25` keeps message content out, which is exactly what makes one portable (`P4-27`) — so a replay joins the receipt's *configuration* to the session's *inputs*, and **a receipt exported to somebody else cannot be re-run by them.** That is the correct trade and it is now stated rather than discovered: `rerun_plan` says so in the drift line instead of quietly running a shorter conversation. **Drift is the product, not an error.** *Same configuration* is a claim; between two runs a model can be gone, a skill edited, a confidence moved. Substituting silently would make every answer this row exists to give a lie, so the plan returns what it can reproduce **alongside a list of what it cannot**, and the replay records that list — letting `P4-28` tell a difference that was *chosen* from one that was *inflicted*. A model override is recorded as `deliberate` for the same reason. Skill drift is reported but does **not** disqualify a replay: re-running today's skills against yesterday's configuration is often exactly the comparison someone wants, and refusing it would make the honest answer unavailable. **Inputs are the messages from before the run started** — everything after is what the run *produced*, and replaying with it in the prompt is not a replay, it is a different conversation that happens to contain the answer. Ordered by `(timestamp, id)`, because two messages in the same second are otherwise ordered arbitrarily and a reversed user/assistant pair replays nothing. **A replay never touches the session:** it is a diagnostic, and appending its output would change the thing being measured and put a machine-generated turn in front of the person next time they scrolled up. It also resets the run ContextVars before starting — `mark_turn_start` only acts on an unset var, so without that a replay called inside a request would write its rows onto the caller's receipt. 17 tests, 6 mutations.
- [x] **P4-27** **Make a receipt portable.** One file, exportable, readable by a person who was
  not there. This is what turns "it did something weird" into a bug report. `Depends:` P4-25.
  — **done 2026-09-05, by extending `P16-14` rather than building a second exporter** (`Law 14`): *make something a person can hand over, with nothing of theirs in it* already had an owner. `build_bundle(run_id=…)` attaches the receipt, the same renderer prints it, and `/api/diagnostics/receipt/{run_id}/export` returns markdown — the destination is an issue and the reader is a human. The section carries the model, the endpoint, the sampling, the tools it was offered, the skills it was following, the round and token totals, and which tools failed. **A receipt already excludes message content by construction (`P4-25`)**, which is most of what makes it handable, and the export says so on its face. **The interesting bug was over-redaction, not a leak.** A `run_id` is 32 hex characters — exactly the shape the opaque-string rule exists to catch — so the first version redacted the one field that lets two people point at the same run, producing a document whose subject was `<redacted>`. Redaction is field-by-field now with an identifier exemption, because redacting a serialised blob cannot tell an endpoint's hostname from a run's identity and treats both the same. 7 tests, 4 mutations. *(One survived and was worth it: my credential test asserted on an **endpoint label**, which `events._safe_label` already sanitises at write — so it passed with this module's redaction removed entirely. It proved the earlier layer, not this one. It asserts on a skill name now, which is operator free text nothing else touches.)* **And a test-suite trap closed at the right level (`B34`).**
- [x] **P4-28** **Diff two receipts.** What changed between the run that worked and the one that — **done 2026-09-05.** `src/receipt_diff.py`, served at `/api/diagnostics/diff/{before}/{after}`. **The classification is the product, not the completeness.** Two receipts differ in dozens of ways that mean nothing, and a diff that lists them all is one nobody reads twice — which is worse than no diff, because it was paid for. So every difference is **chosen** (the operator asked; a replay's model override is the experiment, not a finding), **inflicted** (the world moved — a skill edited, a tool's schema changed, an endpoint renamed; almost always the actual answer), **outcome** (what the run produced — never presented as a cause), or **noise** (timestamps, token wobble under 25%; counted, not printed). `P4-26`'s `deliberate` field is what lets *chosen* and *inflicted* be told apart rather than guessed from the shape of the change — which is the return on having recorded it. **The headline leads with the unasked-for changes**, and that ordering is the argument: putting outcome first buries the cause under its own consequences. **The tool hash earns its keep here** — a schema that changed under an unchanged name is invisible without it. A receipt with no `config` (one from before `P4-25`) still diffs what it has, because refusing would make the oldest runs — the ones most worth comparing against — undiffable. 19 tests, 8 mutations. **A gap found while building it:** `P4-26` recorded `replay` events carrying the link back to the original run, and `receipt()` dropped them on the way out — stored, and unreadable through the only API that reads receipts. Fixed, with a test.
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
- [ ] **P5-15** **Populate `#pinned-tools-bar`** — **`Depends:` P5-12, and this is a `Law 14` dependency rather than an ordering one.** `P5-12` consolidates seven hand-styled tool chips into one component; this row adds a second tool strip a few pixels above them. Build it out of `P5-12`'s chip or the composer ends up with two chip vocabularies stacked on top of each other. — an empty div appearing once in the whole codebase with zero CSS and zero JS. Unclaimed composer real estate, no layout risk.
- [ ] **P5-16** Make the send button's five states legible without changing the machine. **Eight modules mutate it**; any composer rework must reproduce `newchat · mic · send · streaming(processing/receiving/queue) · recording` exactly. Note Enter-on-empty opens a new chat, and the mic state appears from a silent server capability check.
- [ ] **P5-17** **One run-mode picker, not two.** `P6-06` shipped the queue's sequential-vs-parallel popover as a *clone* of the research panel's, and said so rather than pretending otherwise. The two are byte-identical in positioning, classes (`.research-run-mode-popover` / `.research-run-mode-row` / `.rrm-title`), glyphs and dismissal; they differ in exactly three things — the popover id, the two subtitles, and what the rows call. **Sharing it naively is worse than the duplication**, which is why `P6-06` did not: the queue's copy says *"Opens N new chats, one per message"*, and shipping that string to the research panel — which opens no chats — is a `Law 15` regression. Parameterise it instead: id, per-row title and subtitle, and the two callbacks. `queuePanel.js` `promptRunMode` is already three-quarters of the way there — it takes handlers rather than calling `jobs.startAllQueued()` directly. Move it somewhere both can import and delete `research/panel.js` `_promptParallelOrSequential`. **Fix the shared defect once while you are there:** both copies leak their two capture-phase document listeners on the toggle-shut path (patched in place 2026-08-29, in both files — one implementation means one patch next time). `Depends:` nothing. `Verify:` the `.research-run-mode-popover` markup is built in exactly one module, and the research panel's popover still says "Parallel" / "Sequential" with no chat-opening subtitle.

---

# P6 · Queue & Plan
*Area: `queue`, `plan` · Depends: P4-01*

**`Law 15` applies to every row in this phase.** It draws surface a person has to operate, and the law exists because the owner stopped using a competitor's *more advanced* version of this product for one reason: *"There's no tutorials and the learning curve is too steep for the little amount of time I have."* A row here is not done because the feature works — it is done when someone who has not read this tracker can find it, tell what state it is in, and use it without being told how. Put that in the row's `Verify:` line, in those terms.

- [x] **P6-18** **Steer mid-response, not only queue.** The queue holds the *next* message;
  steering redirects the one in flight. Two different verbs, and only one exists. Prior art has
  both on one key pair — Enter queues, Cmd/Ctrl+Enter steers — which is the right shape because
  it is the same intent at two urgencies. `Depends:` P6-01, which landed.
  **Two of three parts landed 2026-08-29 and the row stays open on the third.** The backend
  accepts a steer at a round boundary — `src/agent_loop.py` carries the inbox, and the round
  boundary is the honest granularity, so the UI says *"applies at the next step"* rather than
  implying instant redirection. The composer control and its key binding are in
  `static/js/chatStream.js`, visible rather than keyboard-only (`Law 15`). **What is missing is
  the transport:** no route accepts the steer, so nothing reaches the inbox. Add it beside
  `chat_stop` and `inject_context` in `routes/chat_routes.py` — `agent_runs` and
  `_verify_session_owner` are already imported there, so it needs no new ones. *(The row said
  "50 tests cover the inbox"; refutation counted **36** — 21 in `test_agent_loop_steer.py`, 15 in
  `test_chat_steer_js.py`. Corrected rather than quietly dropped, because a number nobody can
  reproduce is how a row stops being checkable.)*
  — **done:** `POST /api/chat/steer/{session_id}` lands the third part.
  `_verify_session_owner` is the **first statement**, before the body is even read, so the probe
  cannot become an existence oracle — a stranger's live session and a session that never existed
  return the same status, the same body and the same headers, measured indistinguishable over 400
  warmed samples each. 44 tests, every one killed by at least one of ten deliberate mutations.
  **Refutation found the gate asking the wrong question, and it was a `breaks-users` defect on the
  *default* mode.** `agent_runs.is_active()` answers "a run is registered", not "a run that can
  read this inbox is in flight" — and `agent_runs.start()` is called for every non-compare stream,
  while only one of four exits reaches `stream_agent_loop`. So on a plain chat turn the steer was
  accepted, the client cleared the composer and said *"lands at the next step"*, and the words went
  into an inbox nothing would ever read: **silently deleted user text, on every attempt, in the
  mode most people are in.** Fixed with `agent_runs.is_steerable()` — liveness stays in
  `agent_runs` (`Law 14`), it is just now the right predicate — and a fourth non-steerable exit
  (research) that the refutation itself had missed is refused too.
  **Three more, all closed:** a steer that hit the ownership 404 made the client conclude the
  *build* had no steer route and retire the control for the page load while saying so out loud —
  the refusal is now **403**, which the client does not read as a missing route, with the
  indistinguishability property preserved and tested; nothing dispatched `steer_applied`, so the
  module's own "your steer missed the run" warning could never fire (`Law 13` — the event was
  emitted, exported, documented, and routed nowhere); and the bar was drawn for plain chat turns,
  offering a control that could only ever decline. It now asks the composer's own mode getter and
  stays away — **not offering a control is better than offering one that always says no**
  (`Law 15`), and the refusal sentence stopped saying *"The agent already finished"* for a turn
  that had not finished.
  `Verify:` send an agent message, type a correction, press Cmd/Ctrl+Enter — the bar says it
  lands at the next step and it does; do the same in chat mode and no bar is offered at all.
- [x] **P6-01** **Session-bind the queue — live bug.** Queue items carry no session id. Switching chats wipes the message list, destroying every queued bubble's element while the array keeps the items; when the old stream ends the prompt **fires into whichever chat is now open**, invisibly. Add the field, filter the drain on it, re-render bubbles on session switch. — **done:** queue items carry `sessionId`, set at queue time; the drain filters on it and bubbles re-render on session switch. **The fix needed a second pass:** refutation proved the click-to-promote path still leaked — `_promoteQueuedRequest` guarded at click time and then handed the item to a poller that retried every 220ms with no check, so switching chats during the abort round trip still posted one session's text into another. Guarded at *send* time instead (`chat.js` `trySend` plus a backstop in `_setComposerAndSend`), and a mismatched item is **put back in the queue** rather than dropped — it is still the user's message. Verified with the refuter's own attack: fires into B never, kept and addressed to A, and still sends correctly on returning to A.
- [x] **P6-02** Persist the queue. `_queuedAgentRequests` is a bare module array — a reload loses it silently. — **done:** queue persisted through the app's existing `Storage` helper — no second store (`Law 14`). Restored items never auto-replay: they re-arm only on their own session's next ended stream, expire at 24h, and cap at 20 rows, so a reload cannot resurrect a stale prompt.
- [x] **P6-03** Allow queueing with attachments — currently refused with an error that swallows the send. — **done:** attachments are uploaded at queue time and re-carried through the slot resend/regenerate already uses, so a queued send goes down exactly one attachment path. A failed upload returns the text **and** the files to the composer instead of eating them. *(The implementer proposed a wording correction to this line; refutation showed the line was already accurate and the correction was not applied — the tracker says "swallows the send" in all four places and nothing claimed the message disappears.)*
- [x] **P6-04** Build the queue panel: drag-reorder, edit in place, per-item mode and model, start-now force bypass, pause, remove. **The per-item *trust rung* is deliberately not in this list** (removed 2026-08-28): it would make this row the first trust-ladder UI in the product, built inside the queue panel, selecting from a ladder `P7-05` records as not existing. Add it to the queue once `P7-03`/`P7-04` have built the ladder — one control, not two vocabularies. **Clone the research job engine** (382 self-contained lines) rather than writing a new one — but **not "only two lines are research-specific"**. Re-measured 2026-08-27: **roughly 16 research-specific references across 7 endpoints** (scope: case-insensitive `research` in `research/jobs.js`). Still worth cloning; budget a generalisation pass rather than a find-and-replace. — **done:** the docked queue panel: drag-reorder, edit in place, per-item mode and model, force, pause, remove — `static/js/queuePanel.js` as a **view**, with `chat.js` keeping the one queue and the one persistence hook, so no second store. `Verify:` queue a message while a reply streams and the panel appears above the composer saying what will happen and when, unprompted. **Four defects found by refutation and fixed before the tick:** the panel's primary *Send now* button was a guaranteed no-op — items can only be queued while a reply streams, and the drain it called returns immediately in exactly that state, so it now stops the reply first the way promoting a single row already did; per-item **mode** was applied and never restored, and `setMode` persists, so one queued agent-mode item permanently flipped the composer and survived a reload; the model restore probe treated *a stream is live* as *my send is done*, so on the promote path it put the route back before the queued send went out; and neither mode nor model was in the persisted row, so a restored item sent under whatever the composer happened to be. Also: rows no longer claim a chat is *gone* from a payload documented to omit archived and Incognito sessions, and the panel's state line survives on phones — it was `display:none` under 768px, deleting the sentence that says *"Paused — nothing sends until you press Resume"* on the form factor with the least room for guessing.
- [x] **P6-05** Adopt the shipped status vocabulary: `queued → running → success | error | skipped | aborted`. `skipped` and `aborted` are load-bearing — `aborted` keeps infrastructure events out of error-rate stats. **The gap is a documentation gap, and it is the reason this row exists** (2026-08-27): `db.py:818`'s comment documents **3** statuses while `task_scheduler.py` actually writes **6**. Three real states are undocumented, so anything reading the comment instead of the code mis-handles them. — **done:** the six-value `TaskRun.status` vocabulary is documented at `core/database.py:810+` — what each means, which writer sets it, and why folding `aborted` into `error` corrupts error-rate statistics. **Refutation caught the block asserting something the tree contradicted**, so the audit came with it: `static/js/tasks.js` `_entryStatus` text-scanned run output for `/error|failed|exception|traceback/` and filed an `aborted` run under Errors whenever its partial output mentioned one — fixed to prefer the row's own status, matching its correct sibling in the same file. One violation stays open and is named in the block: the scheduler writes `error` on an admin-privilege refusal where the task never ran, which is `skipped` by these definitions. Changing a persisted status value earns its own row.
- [x] **P6-06** Sequential-vs-parallel picker. **Already built** in the research panel — reuse it. Parallel must allocate a session per item: one agent run per session is enforced. — **done:** sequential-vs-parallel picker on the queue, with parallel allocating a session per item because one agent run per session is enforced. Copy names the consequence rather than the mechanism — *"One after another / Here in this chat"* versus *"All at once / One new chat each"*. **Parallel 403'd for every signed-in non-admin** until refutation caught it: the session-create guard passes when `endpoint_id` is set *or* when no raw `endpoint_url` is sent, and this sent the URL unconditionally while sending the id only for per-item models — so the common case hit neither exit. **On reuse, the honest answer: this is a clone of the research panel's control, not a shared one.** Positioning and the dismiss handlers are byte-identical; the two subtitles and the popover id are chat-specific. Sharing it as the row imagined would ship *"Opens N new chats"* to a panel that opens no chats, which is a worse `Law 15` outcome than the duplication. Parameterising it is `P5-17`.
- [x] **P6-07** Point the existing Tasks activity view at queue items rather than building a second queue UI. It already renders every status with shared elapsed timers, a force button and a stop button. — **done:** queue items render in the **existing** Tasks activity view — same rows, same status dots, same elapsed timers, same force and stop buttons. `git diff` on `tasks.js` is 19 hunks of which exactly one is new; every other edit is inside a function that already existed, and task rows are unchanged. This is the run's one unambiguous reuse win. **It did not work when first written, for a reason worth the row:** `chat.js` registered through `import('./tasks.js')` while `app.js` imports `'./js/tasks.js?v=…'` — two URLs, and ES module identity is keyed on the resolved URL, so the registry was written into an instance the sidebar never reads. Fixed by `P3-11`, which unified all eleven forked modules and put a checker in CI.
- [ ] **P6-08** Make `_concurrency_cap` actually configurable — it sits next to `Semaphore(1)` and is documented as "a hard guarantee, not configurable". — **~~done~~ — TICK WITHDRAWN 2026-08-31. The claim was tested and is false in both of its load-bearing clauses.** It read: *"resolves through instance setting → env → built-in default, clamped to [1,16], re-read on settings change without a restart."* **(a) The env leg is unreachable code, on every install, from first boot.** `resolve_task_concurrency_cap` (`src/task_scheduler.py:98`) reads the instance layer as `get_setting(KEY, None)`, and `get_setting` merges `DEFAULT_SETTINGS` on every read — so it cannot return `None`, returns the shipped `1`, and `:119` never executes. Proved with no settings file at all. `H06` holds the proof and is the row that owns the fix. **(b) "without a restart" is not wired.** `_refresh_concurrency_cap` (`:459`) has exactly **one** caller — `:566`, inside start-up. Nothing re-reads it when settings change, so the value a running scheduler uses is the one it booted with. **What was actually done stands and is not withdrawn:** the key is registered in all four places (`DEFAULT_SETTINGS`, `.env.example`, all three compose files), and the wrong comment about "exactly one task at a time" is corrected in place. The clamp and the registration are real; the resolution and the refresh are not. **Re-do:** make the env layer reachable (`is_setting_overridden` at `src/settings.py:279` was written for exactly this and has zero production callers — see `H06`), and give `_refresh_concurrency_cap` a caller on the settings-change path. *(How this got ticked: the trace described the code as written rather than as executed, and every sentence in it was individually checkable except the two that mattered. The three-clause `Verify:` line this row never had is why.)* — original trace follows: **Registered in all four places it has to exist** — `DEFAULT_SETTINGS`, `.env.example`, and *all three* compose files: adding it only to `docker-compose.yml` broke `test_gpu_compose_standalone.py`, which pins the standalone GPU files as base-plus-overlay, and the suite caught it. The comment claiming the cap upheld "exactly one task at a time" was wrong twice over and is corrected in place: two paths already bypassed the semaphore, and `run_task_now(force=True)` neither checks nor adds `_executing`, so a forced trigger can overlap a task with itself. That is what `force` means; it is now written down.
- [x] **P6-09** Rewrite the todo "solve with an agent" button to enqueue instead of firing an unbounded raw stream. **Click ten todos and ten agent loops run at once**, with no progress and no cancel. — **done:** both todo agent-solve entry points enqueue through a bounded one-at-a-time queue with visible position, live status and a real server-side stop. Baseline reproduced before the fix: ten clicks, **ten concurrent streams**, no progress and no cancel.
- [x] **P6-10** Expose `crew_member_id` in the task create/update schemas and the `manage_tasks` tool. It is read-only today and honoured by the executor — **this one field closes the roadmap's "todos assignable to an agent from the UI" item at the API layer.** — **done:** `crew_member_id` exposed in the task create/update schemas and in `manage_tasks`. **It shipped half-wired and refutation caught it:** the tool schema advertised the field while `src/tools/system.py` had never heard of it, so the model would accept the argument, report the task assigned, and the value would be discarded — the model confidently telling a user their task runs as Research Bot when it does not. Now resolved through an owner-scoped lookup mirroring the route layer's, because the executor runs the task with that crew member's persona, model, endpoint and tool allowlist. `tests/test_manage_tasks_crew_member.py` (6 tests) pins the round trip, the cross-owner refusal, and the schema-versus-executor agreement.
- [x] **P6-11** **Build the docked plan window.** Three prompt strings tell the model it exists and a code comment claims it renders. **Nothing has ever rendered it** — mid-execution `update_plan` writes to browser storage with zero visible effect, and the prompt is telling the model something false about its own interface. Structured steps with per-step status, bound tool, effect, elapsed and result.
  **Closed 2026-08-29 by `P7-06`, which put the fifth field on the wire.** All five per-step
  fields now ship: status, bound tool, `effect`, elapsed and result. The step row leads with one
  plain-language phrase — *"Can permanently delete or overwrite"*, not `destructive` — because the
  ranking and the wording live in `src/tool_capabilities.py` and the window renders what it is
  told rather than deciding for itself; a value added to the taxonomy cannot render one way here
  and another way on the approval card. **Refutation found a real misattribution and it is fixed:**
  an approval gate and a policy block both emit `tool_output` with no `tool_start` before it, so a
  refused tool's output landed on a step a *different* tool had claimed — reproduced overwriting a
  step that had just written `/etc/hosts` with *"Reads your private data"* in the routine band, the
  red rule and the triangle both gone. A differing tool name is now treated as a hand-over, which
  replaces the record rather than editing it.
  **The history below is kept because it is the record of what was wrong** (`AGENTS.md`: a partly
  done task stays open with a note saying what is left — this one was, for two waves): `static/js/planWindow.js` renders the approved checklist docked, updates on
  `plan_update`, and survives a reload; **the four prompt strings that have been promising this
  window are now true.** What is left: `effect` is the 13-value `ToolEffect` taxonomy at
  `src/tool_capabilities.py:21-34`, and it is **not on the SSE wire** — neither `tool_start`
  carries it. **Re-measured 2026-08-29: four emit sites, not two.** `tool_start` is emitted at
  `src/agent_loop.py:4694` (the post-approval replay) and `:5990` (the main path); `tool_output` at
  `:4801` and `:6216`. Resolved effect strings *do* already reach the frontend on the approval
  `action` payload (`chatRenderer.js:2637`, `aq.action.effects`), so the field exists; it just does
  not travel on the tool events. **`P7-06` owns emitting it** — it already needs the taxonomy to rank approval prompts, and
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
- [x] **P7-03** Add rung **"ask every time"**. Does not exist: the gate is conditional on untrusted content having entered, so a clean session never prompts. Change the gate condition from *taint seen* to *taint seen **or** the current rung requires confirmation*. **Reuse `PendingToolApproval` unchanged.** — **done, and both premises held exactly** — `decision_for`'s second line was `if not self.external_untrusted_context_seen: return ToolGateDecision(True)`. `TrustRung` lives in `src/tool_capabilities.py` beside the gate it controls, `trust_rung` is a `DEFAULT_SETTINGS` key defaulting to today's behaviour, and `PendingToolApproval` is untouched. **The untainted early exit is preserved for the default rung**, so an existing install's clean session is byte-for-byte what it was — pinned by a sweep of 21,360 cases (every known tool × 20 hostile contents × taint × bypass × three lookup shapes) against an oracle transcribed from the previous commit: **0 diverged**, verdict *and* reason string.
  **Two of the design's five rungs are deliberately not in the enum, and saying why is half the row.** *"Plan only"* is a mode you enter (`PLAN_MODE_READONLY_TOOLS` plus a directive), not a gate condition — putting it in an enum `decision_for` switches on would claim a control this code does not have. *"Auto-pilot"* is what `gate_on_untrusted` feels like in a clean chat, and `design/pantheon-v10.html:1727` says so itself: *"auto-pilot isn't a new top rung. It's already the default."* That is `P7-05`'s superseded correction, discharged here rather than re-derived.
  **The row could not be answered end to end when it first landed, and the batch that found it said so instead of ticking.** `execute_tool_block` refused every approval replay unless *both* the resumed run and the sealed pending carried `external_untrusted_context_seen` — because until this row an untainted run could never mint a card, so "taint seen" was standing in for "the gate asked". A rung refusal mints one with taint `False`, so approving it answered *"Exact-action approval requires an armed run security context"* and the tool never ran. The guard now asks `gate_is_armed`, which lives beside the gate, and separately keeps the older protection: an approval granted before taint arrived cannot be spent after it. That second half **had no test at all** — deleting it passed the entire suite — and now does.
  **Refutation found the ladder inverted, and that is the finding of the run.** `approval_gate_bypassed` short-circuits before the rung, and both allow buttons set `allow_remaining_actions`. So on `ask_every_time`, approving one harmless `bash` in a clean run disarmed the gate — and a later round then fetched a hostile page and ran an exfiltration command **with no prompt, an action the default rung stops and asks about.** The two "stricter" rungs were strictly *less* protected than the one they sit below, and the ladder's own copy promised the opposite. One line: a bypass no longer outranks a rung that asks. The sealed exact grant still authorises its own action, so the rung stays usable.
  **And a typo bought less protection than the operator asked for.** `coerce_trust_rung` fails to the default rather than the strictest rung — deliberate, and argued in its docstring — but nothing validated the write, so `ask_every_tim`, `Ask every time` and `ask-every-time` all stored fine, answered `200`, echoed the typo back into the settings panel, and left the install on the default. Through chat it was worse: `manage_settings` replied *"Set trust_rung = ask every time."* Both doors now reject an unknown rung at the door.
  `Verify:` set the rung to *Ask every time*, send a message in a clean chat that writes a file, and it stops and asks; approve it and it runs; the same chat still asks about the next one.
- [x] **P7-04** Add rung **"allow-listed"** — a rule store mapping tool + argument pattern to auto-allow, consulted before the blocked-effect check. Does not exist. — **done:** `ToolAllowRule` (owner **not null** and indexed, unlike every other owner column in that file, because a rule with no owner is a rule that matches for everyone), `src/tool_allow_rules.py`, and owner-scoped `GET`/`POST`/`DELETE /api/tool-allow-rules`. **No regular expressions, and that is a decision rather than an omission**: a regex in a security allow-list is two problems — users cannot write them correctly, and a catastrophic-backtracking pattern is a denial of service on a live tool-dispatch path. Three explicit kinds instead (`any` / `exact` / `prefix`), normalised with `strip()` and nothing else, because matching *less* is the safe failure direction for a control that only ever grants. A person picks a scope on the approval card; nobody authors a pattern.
  **Consulted before the *refusal*, not literally before the blocked-effect check**, which is the same behaviour and safer literally: an action with no blocked effect is already allowed above, so the only actions a rule can reach are ones that would otherwise be refused — and a rule can never make an action fail classification and be allowed anyway.
  **Refutation found the rung asking *less* than the default, in the case the default exists for.** A standing *"anything starting with git"* rule let `git push --force origin main` run with no prompt in a run that had already pulled in a web page — which `gate_on_untrusted` stops. A rule is a standing yes to a *routine* action, and a run carrying someone else's text is not routine; the consult now requires an untainted run. No test pinned it in either direction, which is why it survived to refutation.
  **Two more `breaks-users` findings, both about a control that reported success and did nothing.** In no-login mode the route filed rules under the reserved local owner while the run carried `owner=None`, so every rule was written, listed, toasted as *saved* — and never once read; the run now resolves its owner through the same `effective_storage_owner` the route uses. And switching *onto* the rung never drew the "always allow" chooser until a page reload, so the one thing the rung promises was unreachable by the route a first-time user takes.
  **The largest gap was not code.** A rule could be created and then neither seen nor revoked from any screen — the widest grant, *"anything bash does"*, one click away with no undo. The refuter called it the worst thing in the change and was right; `core/database.py`'s own comment said *"this is the table where that omission is expensive"* and the store's five-second snapshot TTL was defended on the grounds that *"revoke means revoked before the user has finished reading the confirmation"* — with no revoke to be prompt about. There is a list under the ladder now, each row with a Revoke button, the failure path saying the unwelcome half out loud: *"That could not be taken back, so Pantheon can still do it without asking."*
  **`P7-05`'s acceptance criterion is met and visible:** the default leads the ladder, badged *"What you have now"*, and the two additions sit below it. **The copy was also lying and is fixed** — it promised confirmation before *"saves a file, runs code, sends anything or deletes anything"* while the rung gates 72 of 81 tools including pure reads of your mail, calendar, notes and memory. It now says so, and a test binds the sentence to `POST_EXTERNAL_BLOCKED_EFFECTS` in both directions so it cannot drift again. `B19` carries the argument that the effect set itself is wrong for a clean run.
  `Verify:` on *Allow-listed*, approve one action with "anything beginning with…", watch the next matching action run unprompted, then revoke it from Settings and watch it ask again.
- [x] **P7-05** Record the correction in the UI: **Auto-Pilot is already the default** for every untainted conversation. — **SUPERSEDED (verified 2026-08-27) — not independently actionable.** There is no ladder UI to record it in; this is an acceptance criterion, not a task, and left on its own it is a row nobody can ever honestly tick. **Re-filed as acceptance criteria on `P7-03` and `P7-04`**, citing `design/pantheon-v10.html:1721-1727`: whatever those two build must show Auto-Pilot as the existing default with the ladder added below it, never above.
- [x] **P7-06** Rank prompts by effect. A destructive action and a UI side effect produce an identical card. The 13-value taxonomy (`ToolEffect`, `src/tool_capabilities.py`) is written and used to rank nothing. **This row owns putting `effect` on the SSE wire, and that ownership is stated here because it was previously stated nowhere** — `tool_start` and `tool_output` carry no `effect` key, and two independent auditors reading the same handoff assigned the job to two different phases. It is one field per emit — and **re-measured 2026-08-29 it is four emit sites, not two**: `tool_start` at `src/agent_loop.py:4694` (the post-approval replay) and `:5990` (the main path), `tool_output` at `:4801` and `:6216`. **Miss the approval pair and you ship the bug this row exists to fix** — the prompts that asked for consent would be the ones carrying no consequence. The frontend already renders a resolved effect list from the approval `action` payload (`chatRenderer.js:2637`, `aq.action.effects`), so there is a rendering shape to match rather than invent. **Landing it unblocks `P6-11`**, whose plan window is built and open on exactly this: four of its five per-step fields ship and `effect` is the fifth. — **done:** the 13-value taxonomy now ranks something. `src/tool_capabilities.py` gained one severity ordering and one set of plain-language phrases — *"Can permanently delete or overwrite"*, not `destructive` — plus three bands, and `describe_effects()` resolves a capability set into what a surface needs to draw it. **It is written down once and only in Python**; no JavaScript copy of the ordering or the wording exists, and two tests enforce that, because a second home for an ordering drifts the first time the enum grows and then the same action reads as harmless on one surface and severe on the other. Unknown values fail *high*: an effect nobody has classified ranks above `destructive` rather than below `ui_side_effect`, which is the same rule the module already used for unknown tools. `P6-11` closes with it, and `chatRenderer.js` stopped printing `Effects: destructive, external_side_effect` as a run of grey text identical to `Effects: ui_side_effect`.
  **Refutation found the ranking lying, and that was the whole row.** `bulk_email` — the one tool whose purpose is deleting *many* messages, and which with `permanent: true` sets `\Deleted` and bypasses Trash entirely — ranked **below** `delete_email` for a single message, because it was never in `_ACTION_DESTRUCTIVE`. The card for emptying a mailbox read milder than the card for deleting one email, which is precisely the inversion this row exists to prevent. Fixed, along with the general defect underneath it: the action tables are keyed on bare tool names while the model can call an email tool under its MCP alias, so **every** aliased call was missing its own action table and resolving one rung low.
  **The second finding rewrote the design and made it smaller.** Three files asserted that the sealed approval payload "cannot carry more — the seal is a control that never lifts", so the presentation was threaded beside it, event by event, consumer by consumer. That premise was false: `_canonical_digest` seals `_binding_payload`, a server-side dict, while `public_payload()` is a derived view never read back as authority — proven by mutating it and watching the digest and `matches()` hold. Refutation had already found **three** surfaces shipping this card unranked because of the threading — the compare pane, the background monitor and the teacher escalation. The resolution now lives inside `public_payload()` itself, so **all five producers get it from one place**, the two threaded copies were deleted, and the false sentence is corrected in place in all three files rather than removed.
  **`Law 15` verdict, from the refuter, unedited:** *"the honest answer is yes — from the sentence, not from the design."* The wording carries it; the visual system was one pixel of font-size, two pixels of rule width and one mark shape. It was also **actively harmful on six of sixteen themes** — the `serious` lead was recoloured to the accent over a tinted panel and measured **2.11:1 on `paper`** while the harmless line beside it sat at 11.05:1, and on `terminal` and `retrowave` `--fg` and `--red` are the same hex so the colour channel was worth exactly nothing. The lead is no longer recoloured; the accent moved to the rule and the mark, which survive greyscale. **After: no theme has the serious lead more than 10% below the routine line, and none is under the large-text floor — before, 14 of 16 were.** The band ladder is now four graded channels (size, weight, rule width, mark shape and fill), none of them a hue, all pinned by value tests rather than property-name tests.
  `Verify:` a destructive approval and a `ui_control` approval on screen together, and someone who has never read this tracker can say which one deletes things — in greyscale, and on a phone.
- [ ] **P7-07** Send only the effects that actually **tripped** the gate, not all of them — and surface the unrecognised-tool case, which is the riskiest and currently invisible.
- [ ] **P7-08** **Surface the taint trail.** The security context builds a complete list of which tools introduced untrusted content into a run, and it is read **nowhere** — server or client. Built in memory and thrown away.
- [ ] **P7-09** Grant inspector — once a session-wide grant is given, nothing lists it and nothing revokes it.
- [ ] **P7-10** Surface run limits at the moment of decision. "How far can it run unattended" sits in a settings tab, invisible when you choose. `Depends:` P4-23.
- [ ] **P7-11a** **Real file export — the UI entry point.** *(Split from `P7-11` on 2026-08-31: one half was ready and the other could not be built, and a single `[~]` was hiding the ready half.)* **The export already exists.** `GET /api/session/{sid}/export` serves md, txt, json and html as attachments (`session_routes.py:804`) — it is simply unreachable except by typing `/export`, so the work is a UI entry point, not a backend. The PDF observation stands. **`H20`'s second half is the same defect one level down** and closes here: `/chats export` accepts `json`, `txt`, `html` and a `> filename.ext` redirect while its help text advertises only *"Download as markdown"*, so three of four formats are invisible even to someone who found the command. Fix the usage string in the same change as the button. `Verify:` a person exports a chat in each of the four formats without typing a slash command, and the command's own help names all four.
- [~] **P7-11b** **Export the approval trail.** *(Split from `P7-11` on 2026-08-31.)* **Cannot be built and is not close.** Approvals are held in memory with a 600-second TTL and are never persisted, so there is no trail to export — the export is not missing, the data is. `Blocked:` persist the approval trail first, under `P4-25`, which already owns extending what persists. Do not start this row by inventing a second store; that is `Law 14` and `P4-25` is the host.
- [ ] **P7-13** **Is there a direction `trust_rung` should not move from chat, and can it be named?** `B42` refused the write, six suite failures reversed it, and the reversal is the finding. The rungs have **no total order**: `ASK_EVERY_TIME` and `ALLOW_LISTED` both ask in an untainted run and the default `GATE_ON_UNTRUSTED` does not, so `gate_on_untrusted → allow_listed` is plausibly a *tightening*; and `decision_for` documents an incident where *"the two 'stricter' rungs were strictly less protected than the one they sit below"*, which is fixed but is the reason no ladder can be assumed. Meanwhile `agent_loop.py` says a role profile *"may only raise strictness"*, which presumes an order that is not written down anywhere. **So the question is not whether to restrict the write — it is whether the ordering the codebase keeps referring to actually exists**, and if it does, to define it once where both the profile rule and any chat-side rule can read it. Until then `trust_rung` stays writable from chat, which is also what `P7-03` intended. `Verify:` either a named, tested ordering both callers use, or a decision in `DECISIONS.md` that there is none. — found while correcting `B42` — **needs the owner** — agent:`H18`

- [ ] **P7-12** **Should the agent be able to raise its own loop caps?** `B42` made `agent_email_confirm`, `trust_rung` and `agent_verifier_subagent` read-only to `manage_settings`, and deliberately left `agent_max_rounds` and `agent_max_tool_calls` writable. The case for leaving them: they are runaway and cost caps with no approval semantics, *"give yourself more steps for this"* is a real and reasonable request, and a restriction that has to be argued every time is one nobody keeps. The case against: they are still constraints a person set on the agent, an injected instruction can raise them, and `H08` has just made `agent_max_rounds` **mean something** on local inference where it previously did not — an agent that raises its own cap to 200 and then runs 200 rounds is a real cost on someone's electricity bill. A middle exists: allow raising within the validated range but refuse when the value is already explicit (`setting_is_explicit` — a person who typed a number meant it), which is the same distinction `H06` and `H08` are built on. `Verify:` the owner has picked, and the reason is in `DECISIONS.md`. — found while fixing `B42` — **needs the owner** — agent:`H18`


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
  finished however many rows are ticked. **This row supersedes every per-row restatement of the same requirement (2026-08-31).** Where a `P8` row says its capability *exists but only an expert can reach it*, that is this gate speaking and not a separate finding — `P8-02` is the worked example: four inputs the API supports, all four reachable, but only by hand-writing frontmatter in the raw SKILL.md editor. Read those rows as instances. **The corollary is the part that binds:** a `P8` row may not be ticked on the existence of a capability, only on a person reaching it unaided.
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
- [x] **P9-04** Consolidate email settings. **Premise corrected 2026-08-27.** **The consolidation already landed** at `static/index.html:2100-2124`, so this is no longer the highest-priority IA fix — or an IA fix at all. What remains is a **deletion**: two dead forms, `eaf-*` and `set-email-*`. Under `Law 1` a deletion is marked, reviewed and justified before it runs, so treat this as a delete row and not a build row. **Keep compose-in-document-editor** — it is why AI drafting works. — **done 2026-08-31, and the half that remained was never valid.** The consolidation landed, as the row already says. The deletion it was reduced to would have removed **two live forms**. `eaf-*` is the email-account add/edit form, rendered by `static/js/settings.js:2786-2793` — provider picker, IMAP/SMTP host/port auto-fill, OAuth section, From and Display Name — so deleting it removes the only way to configure a mailbox. `set-email-*` is live too: `static/index.html:1845-1849` is the writing-style extractor and Save, `:2213-2229` the three cross-links into Email Settings, Integrations and Tasks. Both read as dead because the consolidation **moved** them, not because nothing calls them — which is the failure mode `Law 1` exists to catch, and it caught it. **There is nothing to delete. That is the finding, and the row closes on it.**
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
  removed. **Re-checked 2026-08-31: the block stands, and correctly.** `data/auth.json` does not exist and the install has zero accounts, so the second-user condition `D-2026-08-26-01` named as the thing that voids the deletion has still not arrived. Both blockers are intact. This is the one `[~]` in the audit that was right to be there.
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
  scale-up from handing someone twelve untrusted skill blocks. **`src/context_budget.py`
  already implements the shape this wants.** Extend it; do not author an eighth (`Law 14`). *(Path corrected 2026-08-31: the row said `services/context_budget.py`, which does not exist — `services/` has no such file. The module is `src/context_budget.py`. An agent following the row as written would have found nothing there and authored the eighth budget, which is the exact outcome the sentence exists to prevent.)* Its `budget_is_explicit` is also the working version of the pattern `H06` needs — same idea, used, and correct.
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
  **Unfolded from `P14-05` on 2026-09-01, and the reason is worth keeping:** the dataset half is now **built** — `usage_over_time()` and the Settings panel show the last 30 days per model and per owner. What is missing is not data, it is the *place*: this row puts the number next to the field where an operator types a limit, and `P12-07` (the admin surface for the limits) does not exist. The 2026-08-31 fold bet that both halves would land in one build; only one could, and a folded row cannot be half-ticked. `Verify:` unchanged — an operator sets a limit while looking at the last 30 days of the thing they are limiting. **Blocked on `P12-07`**, not on measurement.
  a number. **Same build as `P14-05`, which hosts it (2026-08-31).** *"Usage over time, per model and per owner"* and *"show operators what is being consumed"* are one dataset and one view, asked for from two phases — `P14` because it is measurement, `P12` because a limit you cannot measure cannot be set. Build it once, in `P14`. **This row is `P12`'s consumer of it:** the number goes next to the field where the operator types the limit. The obstacle is shared and belongs on the host row: token usage is stored as a running total with the time dimension discarded at write, so there is nothing to plot until that changes (`D-05`). *(The `[ ]` mark with "Blocked on" in the prose was a disagreement between mark and text; the fold settles it — the blocker is `P14-05`'s, and this row simply waits on its host.)*

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
  onto memory extraction. Same shape, same tuning surface, one fewer concept to learn. **`P13-10` folds in here (2026-08-31):** the retrieval trace is already wired end to end and already renders, so the *only* thing it still needs is the confidence number this row introduces. Surface it on the existing `.memory-used-pill` in the same change — the field and its one consumer, together, or the number ships with nowhere to be read.
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
  independently actionable. `Depends:` P13-01 — **and as of 2026-08-31 this is a pointer, not a row.** The work is one field on `P13-01` and one pill on the renderer that already exists; both are written into that row. Nothing here can be picked up alone, and picking it up alone produces a second confidence concept, which is `Law 14`.

- [ ] **P13-12** **`Comparison.blind_mapping` is three different things depending on who wrote the row.** Declared as *"JSON: `{"left": "a"/"b", "right": ...}`"* and used that way by the full comparison flow; repurposed by `POST /api/compare/record` to hold `{"models": [...]}` because `model_a`/`model_b` cannot hold three; and extended by `H12` to carry `costs` and `mode` as well, because those are what the Scoreboard needs and there was nowhere else to put them without a migration. `_history_row` therefore has to guess which shape it is holding, and it does — a `{"left": ...}` blob correctly falls through to `model_a`/`model_b` — but that guess is load-bearing for a table that is now the source of truth for someone's vote history. **Two unused columns sit beside it**: `metrics_a` and `metrics_b` are declared, never written and never read by anything in the tree. So the fix is not more space, it is honest space: either name what the vote path stores (`vote_meta`, nullable, one migration alongside the `supports_tools` pattern already in `core/database.py`) or use the metrics columns for what their name says. `Verify:` one column, one meaning, and `_history_row` stops guessing. — found while fixing `H12` — agent:`H12`

- [ ] **P13-11** **Two retrieval-quality judgements `B40` deliberately did not make.** Both are now reachable for the first time — before `B40` the classifier said *identity* to everything, so neither could be observed. **(a) `_is_identity_memory` is far broader than its name.** Any two consecutive capitalised words qualify, so *"the office is at 12 Bridge Street"* and *"deploys with Docker Compose on Sunday"* are identity memories, and on an identity query they are admitted at 0.9 ahead of a memory that actually answers. Narrowing it — a capitalised pair adjacent to a first-person marker, say — changes what the agent recalls in every conversation, which is a product judgement and not a bug fix. **(b) group order puts identity above preference**, and `"i"` is an identity word, so *"do I prefer dark mode"* is an identity query and the preference boost still does not fire for the first-person phrasing people actually use. Identity-first is the stated intent and defensible — a question about who someone is should beat one that merely mentions a phone number — but nobody has weighed it against first-person preference questions, because until `B40` no query reached the second group at all. **And the third thing neither of those covers:** the whole scorer is Jaccard overlap plus four hand-written keyword lists, and it is the ONLY retrieval on an install without ChromaDB, which is an optional dependency. Whether that is acceptable, or whether the vector store should be required for the Brain to be worth calling one, is the largest question here. `Verify:` the owner has picked, and the reasons are in `DECISIONS.md`. — found while fixing `B40` — **needs the owner** — agent:`H11`

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

- [x] **P14-01** **One append-only events table.** Timestamp, session, owner, model, endpoint,
  tokens in and out, duration, outcome. Everything else in this phase reads from it.
  **Premise corrected 2026-08-27.** **The stated write location was wrong, and wrong in an expensive direction.**
  `llm_core.py` writes no total at all — the totals accumulate in `accumulate_token_usage` at **`routes/chat_helpers.py:828-844`** —
  path-qualified deliberately, because `src/chat_helpers.py` also exists —
  which has four callers. That is a **17-line insertion point instead of a 3,731-line file** to
  read first. This row unblocks `P14-02`, `P14-03`, `P14-05`, `P12-08` and half of `P14-04`, so
  the wrong address here was costing five downstream rows.
  — **done 2026-09-01. The corrected address was right and the insertion was 5 lines.** `core/database.py` gains `Event`: ts, kind, session, owner, model, endpoint, tokens in and out, duration, outcome, detail, with three indexes. `src/events.py` writes and prunes it; `GET /api/diagnostics/usage` reads it. **Written from `accumulate_token_usage`, and *before* its early return** — that `if not (in_t or out_t): return` is exactly what discards failed rounds, and *how often does this endpoint fail* is the question the running counters can never answer. **Its own DB session, and it swallows everything:** measuring is worth nothing if the measured thing stops working, and sharing the counters' session would let a failed commit here roll back an update that worked fine before any of this existed. **`session_id` is deliberately not a cascading FK** (`D-2026-09-01-02`) — that would delete the cost of a conversation along with the conversation, and what is stored is *shape, never content*: no prompts, no responses, no thinking, so keeping rows past a session deletion leaks nothing the deletion was for. **Retention ships finite at 90 days**, `0` = keep everything; an append-only table with no ceiling is a defect on someone's home server. **The endpoint LABEL is stored, never the URL** — those carry credentials in userinfo and query, and a caller that hands one over by mistake gets it redacted rather than stored. `duration_ms` is present and **NULL**: round latency is not available here and threading it is `P14-02`; the column ships now so that row needs no migration. **`events_retention_days` is settings-only** and the absence of an env var is the decision — I registered `PANTHEON_EVENTS_RETENTION_DAYS` in the env and all three compose files, then removed it, because `get_setting` merges `DEFAULT_SETTINGS` on every read and a fallback beneath a **truthy** default can never run. That is `H06`/`B20` for the fourth time and `P16-05` from the other side. 18 tests, 7 mutations. *(Two survived. The zero-token test called `record_llm_round` **directly**, so moving the write below the early return passed cleanly — the placement IS the behaviour and now has its own test through the caller. And nothing caught the two terminal paths dropping `outcome="error"`, which would silently file every failure as a success.)* **A separate bug, found by the suite and worth naming: all 18 tests passed alone and 10 failed together.** The suite runs on `sqlite:///:memory:`, where each new connection is a **new empty database** — they had been leaning on one pooled connection surviving. They now build a private file-backed DB per test, which also stops them writing to and *pruning* the developer's real database.
- [x] **P14-02** **Instrument the rest of the loop** — round latency, tool call and failure
  counts, queue depth, approval outcomes, retrieval hit rates. Same table.
  — **done 2026-09-01, four of the five instrumented — and the fifth was the wrong shape.** `events` gains a `name` column (the tool that ran, the store that was searched, the capability that was approved) via a real migration: `create_all` builds missing *tables* and never alters one, and `events` shipped a commit earlier, so an install on that build has the table without the column and would fail every insert. **Round latency** — a `ContextVar` clock started at both `/api/chat` and `/api/chat_stream`, read at `accumulate_token_usage`. It measures the **turn**, tool calls and retries included, and the code says so: calling that *round latency* without qualification is the quietly-wrong metric that outlives its author. A missing measurement is `NULL`, never `0` — zero would sit in a dashboard looking like the best turn ever recorded. **Tool call and failure counts** — one event at `execute_tool_block`'s single choke point, and **a tool that fails by *returning* counts as a failure**. Almost every tool here reports errors in its result dict rather than raising, so counting exceptions alone would report a 0% failure rate: a metric worse than none, because it is reassuring. `error`, `exception` and `ok` are three outcomes, not two. **Retrieval hit rates** — `memory` and `rag`, recording asked-vs-returned, and **`unavailable` is not `empty`**: nothing came back because the store is down, and nothing came back because nothing matched, look identical to a user and are different bugs; merging them is the flattering choice. **Approval outcomes** — `claimed` at the claim, `expired` at the purge. Expiry is the one worth counting: a ladder that asks often and is answered rarely is a ladder people have learned to ignore. **Queue depth is deliberately not here, and the row's framing is corrected rather than quietly satisfied:** it is a *gauge* — a point-in-time reading — and writing it into an append-only log would be sampling something you can simply ask for at scrape time. It belongs in `P16-12`'s endpoint, and is filed there. Every insertion point is guarded and last: instrumentation never changes whether a tool succeeded, never delays its result, and never fails a chat. 16 tests, 7 mutations. *(One survived, the same shape as ever: the latency tests called `mark_turn_start` directly, so deleting the call from `chat_stream` passed all of them. Both handlers are asserted now — an unmeasured one shows up as a dashboard where half the turns have no latency at all.)*
- [x] **P14-03** **An eval harness.** Save a set of cases, run them against a configuration,
  get a number. Nothing in this codebase does that today: every prompt change, model swap, skill edit and
  retrieval tweak in this codebase is currently evaluated by vibes.
  **Unblocked 2026-09-02 — `P4-26` shipped.** A saved case is a receipt (`P4-25`, done) and a run is a re-run (`P4-26`, done), so the harness is now *scoring a set of replays* rather than a new store. `Verify:` a saved set of cases runs against a configuration and produces a number, and `P14-04` wires it to `P4-28`'s diff. Order was `P4-25` → `P4-26` → here, and each one made the next smaller.
  — **done 2026-09-05, and it is small because the two rows in front of it did the work.** `src/evals.py` is a suite of `run_id`s plus what the operator expects, and running one is `replay()` in a loop — **no case store, no execution engine, no second copy of the configuration** (`Law 14`). Suites live in the `eval_suites` setting, following `networks`; `P14-06` is the row that decides a real store when one outgrows that, which is a call to make on evidence rather than pre-empt. **Assertions are deterministic and the operator writes them** — `contains`, `not_contains`, `regex`, `max_tool_failures`, `no_error`. Not a judge model: that is a real technique and a bigger decision (whose model, at what temperature, paid for by whom), and a harness whose *first* answer to *did that change help* is itself non-deterministic has replaced vibes with dearer vibes. Filed as `P14-08`. **The decision that matters is that a case which could not be reproduced is neither a pass nor a fail.** It is `skipped`, counted separately, and it drags nothing into the rate: folding unrunnable cases into *failed* makes a broken environment look like a regression and sends someone hunting a bug that is not there, and folding them into *passed* is worse because it is quiet. `P4-26`'s drift reporting is what makes that knowable at all, and a suite that skipped half its cases says so in the headline instead of in a field nobody reads. A suite where **nothing** ran refuses to print a rate — one computed over zero executed cases reads like evidence and is not. **Checks are an allowlist**, so a typo is a loud refusal before any model call rather than an assertion that silently never runs: a suite passing for the wrong reason is the single failure mode of an eval harness that costs anything, because nobody investigates a pass. Tool failures are read from the **replay's own** receipt, not the original's. 21 tests, 7 mutations. *(One survived and found a decorative defence: `score_case` ended `else error is None`, which looks like it handles the errored case and is unreachable whenever there IS an error — a `no_error` check is always added first. Mutating it to `else True` changed nothing. Simplified, and the test now pins the mechanism rather than the outcome.)*
- [ ] **P14-08** **Model-graded scoring for `P14-03`, if it earns its place.** The harness scores deterministically — `contains`, `regex`, tool failures — because the first answer to *did that change help* must not itself be non-deterministic. Some questions genuinely need a judge (*is this summary better*), and that is what this row is for. **Decide before building:** which model judges, at what temperature, and who pays for it — a judge that is a cloud API by default would be `Law 16` clause 4 arriving through a side door, and one that is the same local model being tested grades its own homework. `Verify:` a graded suite reports the judge's model and settings beside the score, and a run with no judge configured is refused rather than silently scored some other way.
- [x] **P14-04** **Wire eval to receipts.** A saved case is a receipt (`P4-27`); a run is a — **done 2026-09-05, and there was almost nothing left to do, which was the point.** `P14-03` already made a case a receipt and a run a re-run; the remaining wire was *a result is a diff*. A **failing** case now carries `why` — `P4-28`'s headline — and `changed`, the inflicted differences only. *"Case 3 failed"* sends someone to read a transcript; *"case 3 failed, and the tool schema changed"* is the answer. **Failures only:** diffing passes would double the cost of a green suite to produce something nobody opens. **Inflicted only:** `P4-28` already ranks chosen and outcome below, and re-deciding that here would bury the cause under its consequences. Guarded — the score is the deliverable and the explanation is a bonus, and a bonus must never cost the deliverable. 4 tests, 4 mutations.
  re-run (`P4-26`); a result is a diff (`P4-28`). Law 14 — no second scaffolding.
- [x] **P14-05** **Usage over time, per model and per owner.** The question that started this
  phase. Cheap once `P14-01` exists. **`P12-08` is the same build and folds in here (2026-08-31)** — it asks for this dataset so an operator can see consumption before setting a limit, which is one more consumer of this view, not a second view. Two things follow: the time dimension has to survive the write (today usage is a running total and the timestamp is discarded — `D-05`), and the result needs a reading beside `P12`'s limit fields as well as its own page. `Verify:` an operator sets a limit while looking at the last 30 days of the thing they are limiting.
  — **done 2026-09-01 for its own scope, and the 2026-08-31 fold with `P12-08` is undone — see below.** `usage_over_time()` returns daily buckets split by model and by owner, aggregated in SQL (`B29`'s lesson, one row per model per day rather than one object per event), served alongside the summary from `/api/diagnostics/usage` so one request draws the chart. A collapsed panel under Settings → System renders it, **querying only when it is opened** — nobody changing a theme should pay for a scan of the events table. **Quiet days are filled in, and that is the property that matters:** a series which simply omits a day with no traffic draws a straight line from Monday to Wednesday, and a gap that reads as continuity is the one way a usage chart actively misleads rather than merely disappoints. **Models are ordered by what they cost**, because a table sorted by name makes the operator hunt for the expensive one. **Only `llm_round` rows are counted** — `P14-02` put tool calls, retrievals and approvals in the same table, and a usage number that silently includes them reconciles with nothing. Rounds with no owner are labelled `(unattributed)` rather than dropped: they predate multi-user and dropping them makes the totals disagree with the summary. **Buckets are UTC days**, because `Event.ts` is naive UTC and inventing a local timezone here would put the boundary somewhere no other timestamp in the product agrees with; the panel says so under the axis. **No charting library** — one series of daily totals, drawn as inline SVG with DOM calls, because vendoring a dependency to draw rectangles is a dependency for something the browser already does. The bars carry an accessible name with the numbers in it. 19 tests, 6 mutations. **The fold with `P12-08` is undone**, on evidence: that row needs the operator's limit *field* to sit beside, and `P12-07` — the admin surface that would hold it — is not built. Folding assumed both would land together and only one could. `P12-08` is open again, waiting on `P12-07`, with this view already built for it to read.
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

# P15 · Outbound politeness — not getting the user banned
*Area: `outbound` · Depends: nothing · Independent of everything else*

**Why this phase exists.** On 2026-08-31 the owner pasted a GitHub link into the skills
importer and **GitHub soft-banned his IP.** The audit that followed found the cause was not
one careless feature. It was two absences, everywhere:

> **Nothing in this codebase read `Retry-After`.** Not one call site, in 50 modules that
> make outbound requests. Servers send that header to tell you exactly how to stay welcome,
> and we ignored every one of them.
>
> **Nothing had jitter.** Every recurring job fires on an exact wall-clock boundary, so
> every Pantheon install in the world hits a given provider on the same second.

`src/rate_limiter.py` existed and is **inbound** — it protects Pantheon from its callers,
keyed by client IP, with one consumer (`routes/auth_routes.py`). Nothing protected the user
from the services Pantheon calls on their behalf. `P12` owns inbound limits; this phase owns
outbound, and the two must not be confused again.

**The rule for this phase:** a limit is a conversation. The server tells you when to come
back, and the only way to *stay* banned is to keep asking while it is telling you.

- [x] **P15-01** **A shared outbound limiter, keyed by destination host.** Not per feature — two features each staying under a limit will jointly blow through it, and the importer and the cookbook's GitHub calls could already collide. — **done:** `OutboundHostLimiter` in `src/rate_limiter.py`, beside the inbound one so there is one vocabulary and not two. Per-host minimum interval, concurrency cap, jitter, and a cooldown fed by the server's own signal. Sync (`acquire`) and async (`acquire_async`) entry points over one state, because the importer is synchronous and search and `llm_core` are not. Shape borrowed deliberately from `routes/device_flow.py`, which was **the only correct outbound throttle in the tree** — its `next_poll_at`/`slow_down` pair, re-keyed from poll session to host. 25 tests; 12 mutations, all caught.
- [x] **P15-02** **Read the server's instructions — all three forms.** — **done:** `parse_retry_after` handles the delta-seconds **and** the HTTP-date form (reading only `int(value)` is the obvious implementation and silently drops every date-form response, which is the half carrying the long waits); `parse_reset_header` handles `X-RateLimit-Reset`, which is what **GitHub sends instead of `Retry-After`** on a primary rate limit. Three things count as *stop*: a `429`; a `403` whose body names a rate or abuse limit — **GitHub's primary rate limit is a 403, not a 429** — and `X-RateLimit-Remaining: 0` on an otherwise fine response, which is the one signal that lets us stop *before* being told to. A plain `403` is **not** a rate limit and must not silence a host; there is a test.
- [x] **P15-03** **Fix the import that caused this.** — **done:** every request in `services/memory/skill_importer.py` now passes through one chokepoint (`_get_checked`) that paces, authenticates, identifies itself, and feeds the response back. Five defects closed: **(a)** no pacing — GitHub asks for serial requests a second apart, and gets them; **(b)** `MAX_FILES = 64` capped *files kept*, not requests made, so a tree of empty or binary-only folders cost **unbounded** `api.github.com` calls while the counter never moved — a per-import request budget now caps the real number (40 unauthenticated, 200 with a token); **(c)** no `User-Agent`, so every request went out as `python-httpx`, a bot signature GitHub scores against you before reading the path; **(d)** no token — unauthenticated GitHub is **60 requests an hour**, with one it is 5,000, and `github_token` is now a setting registered in all five places (`DEFAULT_SETTINGS`, `.env.example`, three compose files); **(e)** the 403 was detected only to print *"try again in a bit"*, which is what makes a person click again and deepen the ban — it now names the wait and says Pantheon has stopped calling, which is what lets the limit expire.
- [x] **P15-04** **Stop the hammer-on-429 sites.** — **done:** three. `services/search/core.py` retried a rate-limited provider **immediately, with no sleep**, then moved down the chain and did the same to the next one — one provider's limit became load on all of them; a `RateLimitError` is now terminal for that provider and is recorded against its host so every other feature sees it. `src/llm_core.py` retried a 429 on a flat 0.5s three times and never read the header; it now honours `Retry-After`/`X-RateLimit-Reset`, sits through a short wait, and surfaces a long one so the caller can fall back rather than queue behind it. `src/bg_monitor.py` retried a failed follow-up **every 5 seconds forever** — 720 attempts an hour, each up to 12 model rounds, each round able to call `web_search`, unattended — now 30s doubling to 30 minutes with jitter, and it gives up after 12.
- [x] **P15-05** **`services/hwfit/hf_discovery.py` fires up to 260 unauthenticated requests from one click.** 13 collection sources × 20 pages, sequential, zero delay, no token — while `routes/cookbook_routes.py:3876` and `src/tools/cookbook.py:484` *do* send an `Authorization: Bearer` to the same host. The 24h TTL is real protection but `force=True` bypasses it and is reachable from the UI (`routes/hwfit_routes.py:210`, `refresh_catalog=1`). `Verify:` the refresh button cannot exceed the host's budget, and it uses the token the rest of the product already has. — **done 2026-08-31.** Four changes, and the third was the one worth finding. **(a)** A **shared** request budget across the whole refresh — 40, against a worst case of 260. Capping pages per source is not enough on its own: thirteen sources each politely stopping at their own limit still add up to a burst, so the budget is one cell threaded through every source. **(b)** The token this product already has. `load_stored_hf_token` was two imports away, and two other call sites already send it to this exact host. **(c)** **The `except Exception: continue` was an amplifier.** A 429 on the first source was swallowed and answered by trying the other twelve — so being told to stop bought the host twelve more bursts. A rate limit now ends the refresh. **(d)** `force=True` skips the 24-hour staleness check, which is what it is for; it no longer skips a five-minute floor, which is a different question — *is this stale* versus *have we just done this*. 9 tests, 7 mutations, all caught. *(One survived at first and was informative: deleting the rate-limit `break` changed nothing, because the limiter's own cooldown already blocks the second source. Two independent protections, which is right — so there is now a test with a deaf limiter stubbed in, isolating the loop itself.)*
- [x] **P15-06** **Route the remaining outbound clients through the limiter.** The audit inventoried **50 modules** making outbound calls. `P15-03`/`P15-04` cover the ones that caused harm; these are the rest, in risk order: `src/embeddings.py` (⌈N/8⌉ sequential POSTs with no pacing, **and a fan-out amplifier** — a failing batch of 8 is retried as 8 single-item requests, 9 where there was 1); `src/deep_research.py` (up to 25 queries per run launched in one unbounded `asyncio.gather`, each walking the whole provider chain — its page fetches *are* capped at 3, so the pattern is already there to copy); the four unauthenticated third-party endpoints in `routes/cookbook_routes.py`; `src/webhook_manager.py` (one task per matching webhook, no per-host cap); `src/caldav_sync.py`. `Verify:` a call that leaves the process without passing the limiter is the exception and is named. — **done 2026-09-06. The row's `Verify:` is a checker, and one thing had to be true before any of the routing was safe.** **First, the precondition: the operator's own machines are not a destination to be polite to.** `D-2026-09-01-03` in code — `LOCAL_POLICY` paces loopback, private space, tailnet (`100.64.0.0/10`, which `is_private` reports as False — the third time that has come up), `.lan`/`.local` names and the compose service names at **zero**. Without it, routing the local-first services through the limiter is a performance regression: a 5,000-chunk RAG index is 625 embedding batches, and at the default 0.25s floor that is over two and a half minutes of pure sleeping against a server on the same box. The first person to profile it would have ripped the limiter back out, correctly. **What is dropped is the pre-emptive politeness, not the response handling** — a local server that answers 429 is a real signal and the cooldown applies exactly as it would to anyone else. An explicit policy still wins, because an operator who wrote one down meant it. **`src/paced_http.py` makes the polite version shorter than the impolite one.** The reason pacing was the exception across fifty modules was never carelessness: the ritual is three statements and the third — hand the response back so a 429 becomes a cooldown — is the one that gets dropped, silently, because dropping it costs nothing until a provider starts refusing and nobody is listening. It is one call now. It also reads the response body **only** on a 403 or 429, because GitHub's primary rate limit is a 403 whose body is the only place that says so, and materialising every response body to find that would be a real cost for a rare signal. **The five named modules.** `src/embeddings.py`: every request paced, and **the fan-out amplifier bounded** — a 400 means one item is too long, and splitting the batch to find it turned ONE request into NINE with no depth limit, so a batch whose items were all too long produced the maximum fan-out every time, during a RAG index, when thousands of batches are in flight. It was the one place in the product that could manufacture a burst out of a steady workload. A batch splits into singles once; a single that still fails is trimmed. `src/deep_research.py`: the searches were an unbounded `gather` over up to 25 queries each walking the whole provider chain, while the extractions **ten lines below** had a semaphore all along. `routes/cookbook_routes.py`: five endpoints against `huggingface.co`, `ollama.com`, `api.github.com` and `raw.githubusercontent.com` — four of the five hosts in the policy table. `src/webhook_manager.py`: one task per matching webhook with no per-host cap, paced in `_deliver` rather than in `_send_request`, which is the seam tests replace to avoid real sockets. `src/caldav_sync.py`: the fan-out is **inside the `caldav` library** — one PROPFIND, one REPORT per calendar, one PUT per event — so the gate is wrapped around the library's own session, on the instance rather than the class, because patching `requests.Session.request` globally would pace every unrelated caller in the process. **`.pantheon/check-outbound.py` is the `Verify` line.** Two rules. A **budget** that can go down and never up (`--max 117`, the shape `check-wiring` and `check-specifiers` already use) — a hard zero today would be a lie, because most of what remains is the agent's own tools calling Pantheon's HTTP API on loopback, where pacing is free but converting a hundred call sites in one commit is how you ship a regression nobody can bisect. And a rule with **no budget at all**: an unpaced call in a function that names a host carrying an explicit `HostPolicy` fails outright, because those policies exist only because those hosts have already throttled this product. It found four such calls beyond the row's list — two HuggingFace collection walks in `services/hwfit/image_models.py` (a `urlopen` per slug, in a loop), the HF model-info lookup in `src/tools/cookbook.py`, and **the DuckDuckGo HTML fallback**, which is the keyless path every install shares and where `services/search/core.py` was already *recording* a 429 that nothing honoured. All four fixed. 39 tests, 23 mutations, all caught. *(Four survived first and every one was a range or presence assertion satisfied by the degenerate case: nothing checked that the embedding response was OBSERVED rather than merely paced; the search-fan-out test read the word `Semaphore` in the source and checked a constructor clamp, both of which stay true when the semaphore is built with 9999, so it measures peak concurrency now; the body-read test used an exploding property, which `_observe`'s own `except Exception` swallowed; and the transport-failure test asserted the host merely appeared in the snapshot, which `acquire` alone makes true.)* **And it found `B36`** — the limiter's docstring has always claimed a 200 ends a cooldown, which the code has never done and should not. **One existing test needed pointing at the new seam, and the reason is worth recording:** `test_service_ddg_html_fallback_sends_safesearch` stubbed `providers.httpx.get`, which after this row is a function nothing calls — so it would have gone on passing against a transport it was no longer exercising. A stub that survives the code moving out from under it is not a passing test, it is a test that stopped running.
- [~] **P15-07** **`src/llm_core.py` re-sends a refused request under five other vendors' client names.** `KIMI_CODE_USER_AGENTS` re-fires the same request as `claude-code`, `KimiCLI`, `Kilo-Code`, `Roo-Code` and `Cursor` in turn until a 403 stops coming back. **Scope corrected 2026-08-31 — my own row overstated this by omitting it, which is the same failure I spent yesterday correcting in the `H` rows.** It is not a general-purpose block-evasion path: `_is_kimi_code_url` gates it to **kimi.com with `/coding` in the path only**, a subscription endpoint the operator has paid for, and it never touches another provider. Moonshot serves that endpoint only to clients naming themselves as one of a whitelist of coding agents; Pantheon is a coding agent that is not on the list, so it tries the names that are. The first accepted name is cached per base URL, so the rotation runs once per endpoint, not once per request. **The pacing half needed no decision and is done:** the retries went out back to back with no delay, and six rapid retries at a host that has just refused you is the shape that escalates whatever one concludes about the names. They now go through the outbound limiter. **`Blocked:` the remaining question is the owner's and only the owner's** — is naming ourselves after other vendors' products acceptable on an endpoint we pay for? Removing the list breaks Kimi Code subscription support for anyone using it, so this is a trade, not a cleanup. Three answers are viable: keep it as documented; reduce to a single honest `Pantheon/1.0` and accept that the endpoint may refuse us; or drop Kimi Code support. The comment block above the list now carries these facts so the decision is made on them.
- [ ] **P15-08** **A schedulable task accepts `* * * * *` with no floor.** `routes/task/task_routes.py:500-503` validates cron *syntax* only, and the UI is a free-text field. A user can set a minute-by-minute task that hits IMAP, a search provider and a model API. Failure does not back off either — `next_run` advances to the next slot, so a task failing against a rate-limiting provider retries at full cadence forever. Related precedent on the same line: `check_email_urgency` shipped at `*/15 * * * *` and was **walked back** to hourly with a migration (`src/task_scheduler.py:2539-2548`) — this exact failure class has already bitten this product once. `Verify:` a minimum interval, enforced server-side with a reason the user can read, and a failing task slows down.
- [x] **P15-09** **The limiter forgets everything on restart.** Cooldowns, escalation counts and `bg_monitor`'s per-job backoff are all in memory. Restart Pantheon while GitHub has you in a 40-minute penalty and it will start asking again immediately — and a crash-loop plus a rate limit is exactly the pair that turns a soft ban into a hard one. The state is small and boring: host, blocked-until, consecutive failures. `Verify:` a cooldown survives a restart. — **done 2026-09-05, and the whole row is the clock domain.** The state is as small and boring as the row says — key, wall-clock deadline, consecutive failures, the provider's own message — in `data/outbound_state.json`, written atomically. **`blocked_until` is a `time.monotonic()` reading, and persisting it is meaningless across processes**: monotonic's origin is arbitrary and per-boot, so a stored value compared against a fresh origin answers a different question. The failure is worse than wrong, it is *selectively* wrong — restart without a reboot and monotonic has kept counting, so the naive version appears to work perfectly; restart after a **reboot**, which is what a crash-loop and a power cut produce and the only case this row is about, and the answer is unrelated to reality. It passes on the developer's box and fails on the machine that rebooted. So the file stores a wall-clock deadline and converts on both sides, and **the tests move the monotonic origin as well as the process** — a test that merely builds a second limiter would pass against the defect. **The escalation ladder is restored too**, which is half the value: a crash-loop that resets `consecutive_429` re-earns the ban from the base cooldown every time, which recovers more slowly than never escalating at all. **A success clears the file**, or a penalty the provider has already forgiven comes back at the next restart — the same defect pointing the other way. **Loading is lazy and unconditional**, not a startup call someone has to remember: a load forgotten in one entry point produces a cooldown that silently does not apply, which is exactly what this row exists to fix. **There is deliberately no write debounce** — a penalty set and then a `kill -9` inside the debounce window is a penalty that never reached disk, and a crash is the common way this process ends when it is being rate limited. It needs none: the projection is written only when it *changes*, and the steady state on a healthy install is an empty projection that is never rewritten. **A restored deadline is capped at 24h** — not policy about how long a host may block us, a bound on what a corrupt file or a moved system clock can do. **Pacing and the per-process counters are not persisted**: pacing is re-earned in one request, and the counters feed `pantheon_outbound_*`, where carrying them across a restart would make a gauge that says *this process* quietly mean something else. A corrupt file starts clean rather than raising, and an unwritable data directory degrades to in-memory-only — refusing to pace because a file will not open would turn a disk problem into a rate-limit ban. 25 tests, 18 mutations, all caught. *(One of the eighteen survived first: `reset()`'s `_loaded = True`. Its own write normally leaves an empty file, so a reload restores nothing and the flag changes no outcome — it is load-bearing only when the write FAILS, where without it the next read would silently undo the operator's clear. Kept and tested on that case, as `P16-12` kept its `# TYPE` guard.)* **It also found `B35`**: this module has never defined a `logger`, and two of the three new call sites sit inside `except` blocks where the `NameError` would have escaped while already handling a failure. Documented in `docs/setup.md`; `data/` is already tarred whole by `scripts/pantheon-backup`, so the file needs no backup change. **One more thing the suite taught, and it is the right behaviour rather than a test accommodation:** the first version wrote the file unconditionally, so a fresh install gained a permanent `outbound_state.json` saying *nothing is blocked* — the default state, recorded as an artefact. It is not written at all when the projection is empty and no file exists, and it is still written when one does, because that stale file is the case the write is for. Thirteen suite failures found it: the test fixture put the file in each test's `tmp_path`, and every test that globs or indexes its own working directory saw it.
- [x] **P15-10** **Give jitter to every recurring job.** Confirmed absent everywhere: `grep -rnE "jitter|random\.uniform|random\.randint" src/ routes/ services/ app.py` found nothing but a comment. The seeded email tasks all use minute `0`; the nightly skill audit runs at exactly 02:00 local; the 60s unread poll fires on the tab's own boundary. Individually harmless, collectively a thundering herd against whatever provider they share. `P15-04` added jitter to `bg_monitor` as the worked example. `Verify:` no recurring job fires on an exact boundary. — **done 2026-09-05, and the row's hand audit undercounted by more than half.** `src/jitter.py` is the one place that decides when a recurring job fires; every site routes through it, including `P16-19`'s push loop, which had grown its own copy an hour earlier (`Law 14`). **The interesting part is not the arithmetic, it is that this had to become a checker.** The row's own grep found nothing but a comment — not one recurring job in the product had jitter — and that state arrived through nobody deciding anything: an exact sixty seconds is simply what you write. Fixing the call sites and stopping there guarantees the next loop somebody adds is bare again, and the defect is invisible from inside a single install because **the herd is across installs**: every Pantheon hits the top of the hour together, so a shared provider sees a spike per hour rather than a rate, and a provider *outage* fails everyone at once and brings everyone back at the same synchronised moment. So `.pantheon/check-jitter.py` ships with it, in CI. **It found twelve sites the hand audit missed, and two were real** — `routes/email_pollers.py`'s scheduled-email poller, a thirty-second fixed tick reaching a mail provider, and `upload_routes.periodic_rate_limit_cleanup`. The other ten are request-scoped pumps (a tmux output generator, an SSE progress emitter, a per-run foreground watchdog) which look identical from the AST and are nothing like a recurring job — they start when a person does something and poll a local process, so the start time is already random. They are named in the allowlist with the reason rather than excluded by a cleverer rule, so a new one has to be added deliberately. **The seeded email tasks are jittered at DISPATCH, not in the shipped cron expressions**: the reconciliation in `ensure_defaults` compares against the shipped string, so a randomised default would be rewritten on every start — and dispatch covers user-created tasks too, with no migration of a schedule somebody may have edited. The hold is **scaled to the task's own period** (5%, capped at 45s) because the herd is hourly-and-slower while a `* * * * *` task held for half a minute would start skipping periods once its runtime is added. It is deliberately **not** in `_execute_task`, which is also the manual *Run now* path, where a person is watching. **What is deliberately not jittered is the list worth reading**: the scheduler's own tick (it wakes near the next due boundary on purpose — a fix for `* * * * *` tasks firing a minute late, and jittering the dispatcher would put that back), a manual run, and `llm_core`'s flat 0.5s connect/read-timeout retries. Its geometric 429 backoff **is** jittered, because a provider rate-limiting everyone at once is the synchronising event itself. **The browser poll needed a different shape:** `setInterval` fires on a fixed grid, so jittering the first delay shifts the grid once and then keeps every tick exactly sixty seconds apart forever — it is a self-rescheduling `setTimeout` now, and the drift is the point. 22 tests, 14 mutations, all caught. *(Three survived first, all the same vacuity: a range assertion is satisfied by the degenerate value at either end — `0 <= v <= FALLBACK` passes when every `v` is `0`, and `3600 <= s <= 3600+N` passes when every `s` is exactly `3600`, which IS the defect. A `_varies` helper pairs every range assertion with a distinctness one. The fourth was a wiring gap: every test exercised `dispatch_hold` directly, so replacing the call in `_check_due_tasks` with a bare `_execute_task` changed nothing any of them could see.)* **And the checker caught its own author on its first run:** the orphan rule — an `ALLOWED` entry matching nothing — fired on five entries written from *reading* the code rather than from running the check, every one covering a sleep whose argument is computed and which this checker never flags.
- [ ] **P15-11** **Show the user what is throttled.** `OutboundHostLimiter.snapshot()` already returns per-host cooldown, consecutive-429 count, requests made and seconds waited — it exists and has no reader. When a host has us in cooldown the person should be able to see it and see when it lifts, rather than watching a feature quietly fail. This is `Law 15`: the product knows something the person needs and does not say it. `Verify:` a throttled host is visible somewhere a person will look, with the time it clears.
- [x] **P15-12** **The unread-email poll falls through to IMAP whenever the index is empty.** `routes/email_routes.py:2452` is index-first *"so periodic UI polling does not trigger Gmail SEARCH/LIST round-trips"* — but the guard is `if indexed_total:`, so a new account, or one whose IMAP is **failing** and therefore never indexes, drops to a live `_list_emails_sync` on every 60s tick, per open tab, forever. Repeated failing IMAP logins are exactly what providers throttle and lock. There is **no failure counter, cooldown or auto-disable for a broken email account anywhere in the tree**. `Verify:` a failing account backs off and says so, instead of retrying every minute in every tab. — **done 2026-08-31, and the row understated it by one level.** The gate is now a per-account cooldown (`imap-unread:<account>`) checked *before* the live call, escalating 120s → 1 hour with jitter and clearing on the first success; two mailboxes at one provider fail independently, because one stale password must not silence the others. **The part the row did not know:** `_list_emails_sync` **catches every exception** and reports failure as an `error` key on an otherwise-empty result (AST-verified: two broad handlers, both returning, neither re-raising). So the obvious fix — wrap the call in `try/except` and back off in the handler — compiles, reads correctly, ships, and backs off **never**. I wrote that version first. The swallowing is also *why* nobody noticed the hammering: from the poll's side, a mailbox that has been refusing logins for a week is indistinguishable from one with no unread mail. The response now carries `sync.source: "unavailable"` with `retry_in`, so `P15-11` has something true to show. **New primitive:** `OutboundHostLimiter.penalise()` / `.succeeded()` — escalating cooldowns for protocols with no 429 (IMAP, SMTP, CalDAV), where *stop* arrives as a socket error and blind retrying costs the user the most. 10 tests, 7 mutations. *(Two survived first time and both were my tests: one asserted `second > first`, which the 20% jitter satisfies half the time with escalation deleted; the other checked only that the unrelated account was clear, which passes trivially when the penalty is written to the wrong key and nothing is blocked at all.)*

---

# P16 · Self-hosted by default — Law 16
*Area: `egress` · Depends: nothing · Independent of everything else*

**The directive, in the owner's words (2026-08-31):**

> *"we drop external dependence. i dont want things that'll may route to external services
> unless the user (or sysadmin) explicitly links it. the intent is fully self hosted everything,
> with options to add cloud providers via api in which case the cloud provider being API linked
> will have everything the users subscription allows."*

**The acceptance test for the whole phase:** install Pantheon with no credentials, open it, use
it — and nothing reaches the public internet. `P15` is about being *polite* to services we call;
this phase is about not calling them at all until someone asks.

**Read clause 2 of `Law 16` before starting any row here.** This is a rule about defaults, not a
cap on capability. A provider the user has linked gets everything their subscription allows.
Nerfing a configured provider in the name of this phase is the mistake `P2` exists to undo.

**The audit found the product much closer to this than not** — no telemetry of any kind, every
model/embedding/search endpoint defaulting to loopback, `.env.example` two active lines and both
localhost, fonts and libraries all vendored, invasive scheduled tasks shipping paused. The gaps
below are convenience defaults, and most are a line each.

- [x] **P16-01** **`npx -y @playwright/mcp@latest` ran ~3 seconds after every boot.** A fresh install with no account, no key and no user action reached `registry.npmjs.org` — installing on first start and re-checking the `@latest` dist-tag on every one after. The opt-out existed and was **inverted**: `PANTHEON_BROWSER_MCP_REQUIRE_CACHE` defaulted to off, and the comment above it explained the choice plainly, so nobody had hidden it — it had simply never been asked this question. — **done:** default flipped to on. The capability is unchanged: browser automation starts the moment the package is on disk. What is gone is Pantheon going to get it uninvited. The test that pinned the old default is rewritten to pin the new one, with the reason on it.
- [x] **P16-02** **`search_fallback_chain` shipped as `["duckduckgo"]`.** Justified in a comment as *"free, no API key required, so safe to ship on by default for every user"* — both true, and neither is the question. On a native install SearXNG never starts, so the primary provider **always** failed and every search a user typed went to DuckDuckGo, scraped from an HTML endpoint under a spoofed desktop user-agent, which is also how an IP gets blocked. — **done:** defaults to `[]`. Adding a fallback is one line in Settings and it is the user's line to add.
- [x] **P16-03** **Ship a skill library that needs no network.** — **done:** 286 skills vendored from ECC (MIT) under `library/ecc/`, pinned to upstream `2.2.0` @ `005eff4`. They needed no conversion — ECC's `name:`/`description:` frontmatter is exactly what `skill_format.py` already reads, and all 286 parse. Loaded as a **read-only layer beneath** `data/skills/`, so a `data/` wipe does not cost the library and a user skill of the same name shadows it. **SKILL.md text only** — no upstream scripts, assets or docs, because a product built to depend on nothing external should not ship code it has not read to execute on the user's machine. Attribution in `CREDITS.md` and `licenses/ECC-MIT.txt`. 11 tests, 7 mutations.
- [x] **P16-04** **Make the library updatable without making it auto-updating.** — **done:** `scripts/update-skill-library.py --check|--apply`. Fetches through the `P15` limiter, **refuses to apply if any incoming skill fails to parse with this product's own reader** (a skill Pantheon cannot read is a regression, not an update), and regenerates `MANIFEST.json` with the new commit and per-file checksums so the diff is reviewable. An auto-updating bundle is an external dependency wearing a different hat, and a supply-chain hole besides.
- [x] **P16-05** **The embedding model is downloaded from HuggingFace on the first chat message.** `build_embedding_lanes` (`src/embedding_lanes.py:266-270`) builds the fastembed lane **unconditionally** — the `try` is not conditional on the HTTP lane succeeding — and `FastEmbedClient.__init__` fetches `all-MiniLM-L6-v2` (~90 MB). `fastembed` is a hard requirement, so it is never skipped, and `memory` and `rag` both default on, so the first message triggers it. The HTTP lane's own default is already correct (`http://localhost:11434/v1/embeddings`). **This is the last zero-configuration leak and the only one that is not a one-liner.** `Verify:` a fresh install answers its first message with no outbound request; either the model ships in the image or the lane is conditional on an explicit download permission. — **done 2026-09-01.** `_build_fastembed_client` now **refuses** rather than downloading when the model is absent and nobody permitted a fetch; cached costs no network so it is always allowed. **The gate's placement is load-bearing and cost a red suite to learn.** I first put it in `build_embedding_lanes`, which turned **14 existing tests red** — they stub `_build_fastembed_client` to check dimension separation, legacy backfill and dual-write, and none of them downloads anything, because a stub does not download. Gating the assembler refused lanes in tests that were never going to fetch. Moved to the one function that actually reaches the network, the rule binds exactly where the cost is and a caller holding a real client is unaffected. `allow_model_download` ships `False`, registered in all five places (`DEFAULT_SETTINGS`, `.env.example`, three compose files). With no lane, memory and RAG degrade to unavailable — `memory_vector` and `rag_vector` already handled zero lanes — and the log says which of the two fixes to apply. **The cache probe looks for the `.onnx` on disk rather than asking fastembed**, because fastembed's way of answering *is it there* is to fetch it; there is a tripwire test that fails if that ever regresses, since the wrong implementation still returns the right answer. *(The env fallback here is reachable precisely because the default is falsy — `H06` found the identical shape dead where the default is `1`. The distinction is truthiness, not the pattern.)* 8 tests, 7 mutations, all caught.
- [x] **P16-06** **Emoji SVGs are proxied from jsDelivr on the first emoji in any message.** `routes/emoji_routes.py:28,97` ← `static/js/markdown.js:515`. The design is deliberately same-origin and sanitised and disk-cached — the client never touches the CDN — but the *server* does, and the codepoint sequence is a weak side-channel about message content. Models emit emoji constantly, so this fires on roughly the first reply. The OpenMoji black set is ~4 MB. `Verify:` vendor it into `static/` beside the fonts and KaTeX, and delete the fetch. — **done 2026-09-01, and it turned up a licence obligation that was never met.** **The egress:** vendored as **one 5 MB JSON, not 4,147 files** — the same bytes cost 18 MB on disk as individual files, and a single blob is kinder to git and the filesystem. Each entry holds only the inner markup; the six stroke attributes every glyph in this set repeats are hoisted onto one wrapping `<g>` at serve time, which is most of the 7.6 MB → 5.0 MB saving. Loads lazily, so an install that never renders an emoji never pays the memory. The `httpx` import and the CDN constant are gone with the fetch — **a test that only looked for both on one line let a two-line reintroduction through**, so it now checks for the client, the CDN host and three call idioms separately. **The licence:** OpenMoji is **CC BY-SA 4.0** and appeared **nowhere** in `CREDITS.md`, `NOTICE` or `licenses/`. The product had been serving its artwork through `/api/emoji/` since before the fork. Attribution is required whether the bytes are proxied or bundled — vendoring only made the omission easier to see. Now credited in both the table and the prose, with the full licence text, and the manifest discloses that the attribute-stripping is itself an adaptation and therefore CC BY-SA 4.0 too. *(Given how carefully `P0` handled the AGPL and MIT obligations, this one being absent is the finding, not a footnote.)* 12 tests, 5 mutations. *(Three survived first time, all my tests: the CDN check required `httpx` and a call on the same line; the sanitiser test called `_is_safe_svg` directly rather than checking the **handler** uses it, so ignoring its result passed; and the attribution check matched the substring `OpenMoji`, which `OpenMojiX` also contains.)*
- [x] **P16-07** **Pyodide is loaded from jsDelivr when a user runs a Python block**, and it half-works. `static/js/codeRunner.js:156` pulls `pyodide.js` from the CDN — while the CSP's `connect-src 'self'` (`core/middleware.py:200`) blocks the `.wasm` fetch that follows. So the request leaks and the feature likely fails anyway. `Verify:` vendor Pyodide into `static/lib/`, then tighten `script-src` to `'self'` — which removes the last external allowance in the CSP. — **done 2026-09-01. The last CDN load in the tree is gone, and the CSP now names no external host at all.** 13.8 MB vendored to `static/lib/pyodide/`: runtime plus the Python standard library, **no packages**. `full/` is ~250 wheels and hundreds of MB, and `codeRunner.js` never calls `loadPackage` — `import numpy` raised `ModuleNotFoundError` against the CDN too — so vendoring narrows nothing; it makes what already happened happen locally. **`indexURL` mattered as much as `script.src`:** Pyodide resolves the wasm, the stdlib zip and the lock file against it, so repointing only the script tag leaves three of five files remote while every grep for `jsdelivr` in the obvious place comes back clean. There is a test for exactly that mutation. **The CSP change is a tightening that required an addition.** `https://cdn.jsdelivr.net` came out of `script-src`, `style-src` **and** `font-src` — all three, it was in all three — and `'wasm-unsafe-eval'` went in, because a page with any `script-src` cannot compile WebAssembly without it. **Dropping the host without adding that would have moved the failure rather than fixed it**: no request leaves, and Python still does not run, which is precisely the state this row was filed to end. `'unsafe-eval'` would also work and is far wider; a test rejects it. **Supply chain:** `scripts/fetch-pyodide.py` downloads **one** artifact — the npm registry tarball — checks it against the registry's published `dist.integrity` **before** `tarfile.open` (verifying after extraction verifies nothing; extraction is the part that parses hostile bytes), then checks each extracted file against a hash pinned in the script, and only then writes. Every file was independently confirmed byte-identical to what jsDelivr serves at `v0.27.5/full/` — two origins, one set of hashes. `--check` re-verifies on disk and runs in the suite, because a vendored binary nobody re-hashes is a binary nobody would notice changing. `*.wasm` and `*.zip` are marked `binary` in `.gitattributes` rather than left to `text=auto`'s content heuristic: this repository has already shipped a CRLF corruption bug from a Windows checkout (#150, #77), and a mangled 10 MB wasm fails at instantiate with nothing useful on screen. **MPL-2.0 paperwork paid in the same commit**, as `P16-18` required a commit earlier — and the checker `P16-18` built refused the commit until it was. 15 tests, 8 mutations. **Vendoring makes paperwork due in the same commit** (`P16-18`): Pyodide is **MPL-2.0**, and MPL §3.2 attaches on *distribution* — pointing a browser at jsDelivr distributes nothing, shipping the bytes does. Licence text, an `INVENTORY` entry in `check-licences.py` and a row in the vendored-libraries table, or CI fails.
- [x] **P16-08** **Rendered markdown loads images from any https host.** `img-src 'self' data: blob: https:` (`core/middleware.py:198`) means an `![](…)` in model output, a RAG document or an **email** causes the viewer's browser to beacon a third party. Content the user did not author, fetched by their browser, from a host they did not choose. `Verify:` `img-src 'self' data: blob:`, with remote images proxied same-origin (the emoji route is the pattern) or behind click-to-load. — **done 2026-09-01, and the proxy alone would not have been the fix.** Routing the fetch through the server protects the reader's browser and dedupes the request, but it still leaves the machine for content nobody chose — under `Law 16` that is the same defect one hop further away. **So the default is `ask`:** a remote image renders as a control naming its host until someone clicks. `remote_images` takes `ask` (default), `proxy` (fetch server-side automatically; the browser still never talks to the third party) or `block`. `/api/img` is deliberately boring and suspicious of what it gets back: session required, SSRF-guarded and DNS-pinned through `outbound_fetch`, paced by the `P15` limiter, size-capped, `image/*` only, **`image/svg+xml` refused** because SVG executes and this path serves bytes a stranger chose to a logged-in origin, and cached on disk by URL hash. **Both CSP blocks were tightened, not one** — the app's and the report pages' — and there is a test that counts them, because missing one leaves the hole open. 15 tests, 9 mutations. *(One survived and found a real gap: my tests asserted the placeholder was **present**, never that the raw URL was **absent**, so a renderer emitting both a plain `<img src=rawUrl>` and the button passed. The CSP would have caught it in a browser — which is exactly the second layer that hides a first-layer regression.)*
- [x] **P16-09** **`trust_remote_code=True` on a HuggingFace download.** `routes/gallery/gallery_routes.py:2022` runs `transformers.pipeline("briaai/RMBG-1.4", trust_remote_code=True)` as the rembg fallback — downloading **and executing** arbitrary remote code. Gated behind a user action, so not a `Law 16` default violation, but it is the one place in the tree that executes code fetched at runtime from a third party. `Verify:` pinned revision with `trust_remote_code=False`, or the path is removed. — **done 2026-09-01: removed, under `Law 1`.** `trust_remote_code=True` downloads Python from a model repository and **executes it**, in the app process, with the app's permissions — triggered by an ordinary user clicking *remove background*, with nothing on screen saying that is what happens. That is not a fallback; it is a different product. Nothing opt-in was lost: the path only ran when rembg was absent, and the error already said how to install it — it now also says why Pantheon stopped short rather than fetching. **My own row was wrong about the scope and is corrected:** it said *"the one place in the tree"*. `scripts/diffusion_server.py` passes `trust_remote_code=True` **five more times**, and is deliberately left alone — an operator who starts a diffusion server has chosen to load models, most diffusion pipelines require remote code, and loading models is that script's entire purpose. It is not the app's, and the app is where a user clicks buttons. `tests/test_no_remote_code_execution.py` now fails on any **uncommented** `trust_remote_code` outside that script, across seven app roots, and on the exclusion losing its written reason. 4 tests, 4 mutations.
- [x] **P16-10** **Self-hosted SearXNG still fans out to commercial engines.** `use_default_settings: true` (`config/searxng/settings.yml:1`) and the last-ditch retry at `services/search/providers.py:222-229` **strips the `engines` parameter entirely**, re-enabling SearXNG's Google/DDG/Brave defaults. Inherent to metasearch and not a defect on its own — but "self-hosted search" that silently queries Google on retry is not what the phrase promises. `Verify:` the engine list is explicit and the retry cannot widen it, or the behaviour is documented where a person choosing SearXNG will read it. — **done 2026-09-01, both halves, because only one of them can be true.** **The gate:** the engine-stripping retry is now behind `searxng_widen_engines`, shipping **off**, registered in all five places. Dropping `engines` was never "retrying harder" — it handed the query to whatever `use_default_settings: true` enables, which is SearXNG's full default set, which is the engines the operator excluded *by pinning in the first place*. On the third attempt, silently, logged at INFO as a detail. Default-off rather than removed, the same shape as `P16-01` and `P16-02`; the refusal log names the engines that were tried, what widening would reach, and the setting to change. **The documentation, because the gate cannot make the honest sentence true:** `docs/setup.md` gains *What self-hosted search does and does not mean* — SearXNG has **no index of its own**, so self-hosting it means the *aggregator* runs on your hardware, never that the searching does. What you get is real (no account, no profile, no history held by a company, and your browser never talks to those engines); what you do not get is queries that stay on your network, and there is no setting that changes that. It also says plainly that the shipped pin `bing,mojeek,presearch` was chosen because the usual defaults are CAPTCHA-blocked on a fresh instance, **not** because those three are more private. **What I did not do, and why:** restricting the engine set at the source with `use_default_settings: {engines: {keep_only: […]}}` is the stronger guarantee, and it is documented as the by-hand change. Pantheon does not ship it because the **news** category pins no engines, so a `keep_only` list tuned for general search silently breaks news queries — a default that breaks a working feature is worse than the one it replaces. 7 tests, 5 mutations. *(Two survived, both mine, both the same shape: the refusal-log test anchored first on the function definition — reading its docstring — and then on a window wide enough to swallow the **opt-in** branch, whose log also says `searxng_widen_engines`. It passed while the refusal said nothing at all. It now reads the `else` branch alone.)*
- [x] **P16-12** **Give operators the telemetry the law now explicitly allows — to their address, never ours.** `Law 16` clause 4 and `D-2026-08-31-01`: measuring is not the sin, sending it somewhere the user did not choose is. Today there is **no telemetry export at all**, which is compliant by accident rather than by design and leaves someone running this on their own hardware with no way to see what it is doing — `Law 15` in a different costume. Build the two shapes that cover the field: a **Prometheus scrape endpoint** (pull, so nothing leaves unless something asks) and an **OTLP exporter** with a user-supplied collector URL (push, to their box). `P14-01`'s events table is the source; it is local and always was. **The shipped destination is empty, and empty is the only correct default** — a default endpoint here is the whole defect whatever its value. `Verify:` an operator points Grafana at Pantheon and sees round latency, tool failures and token usage, having configured exactly one address. — **Premise corrected 2026-09-01, and it is a dependency nobody had checked.** This row says *"`P14-01`'s events table is the source; it is local and always was"*. **`P14-01` is not done and that table does not exist.** `core/database.py` has 30 tables and none of them is an events table; token totals accumulate in `accumulate_token_usage` (`routes/chat_helpers.py:828-844`) and are never persisted per-request. So the two metrics in this row's `Verify` that need per-request records — **round latency** and **token usage** — have no source to read, and building them under this row would be building `P14-01` badly, under the wrong number, where nobody would look for it. **What could ship today** is a Prometheus scrape endpoint over the sources that already exist and already have no reader: `run_self_checks()` (`P16-15`), `outbound.snapshot()` (`P15-11`), `collect_service_health()` (`P16-17`), `task_runs`, and DB stats. That is genuinely the *silent-failure* signal `P16-15` argued for, and it is a different row. **This one stays open behind `P14-01`** rather than being half-ticked. `P16-13`'s guard is armed either way, which was the point of arming it first. **Unblocked 2026-09-01** — `P14-01` built the table and `P14-02` filled it with turn latency, tool failures and retrieval outcomes, which is the three things this row's `Verify` names. **It also inherits queue depth from `P14-02`:** that is a *gauge*, a point-in-time reading, and writing it into an append-only event log would be sampling something a scrape can simply ask for. It is read here, at scrape time, not stored. **One further note for whoever builds it: an all-time Prometheus counter would be dishonest on this data.** `events_retention_days` prunes at 90 days, so a `_total` counter sourced from the table declines gradually as old rows leave — which Prometheus reads as neither a reset nor a real rate. Expose windowed gauges, named for their window, or a process-lifetime counter that genuinely is monotonic. Not both wearing the same name. — **done 2026-09-01, the pull half, and the row's `Verify` describes exactly that:** an operator points Grafana at Pantheon having configured one address, and the address is Pantheon's. `GET /metrics`, off by default, in all five places. **A scrape has no destination**, which is `Law 16` clause 4 satisfied by shape rather than by promise — there is no collector URL in the module and an AST-level test fails if an import or a `://` literal ever appears. **No `prometheus_client` dependency.** The exposition format is a name, labels and a number; taking a hard dependency to do string formatting, in a product whose stated direction is *drop external dependence*, is the wrong trade. **The decision worth reading is that everything is a `gauge`.** A Prometheus counter must be monotonic, and `events_retention_days` prunes at 90 days — so a `_total` from that table declines **gradually** as rows age out, which Prometheus reads as neither a reset nor a real rate, and `rate()` over it is wrong in a way nobody notices on a dashboard. The windowed numbers carry their window in the name (`_1h`) instead. **Queue depth is read here, at scrape time**, as `P14-02` said it should be — `agent_mail` is `H01` as a number in front of someone. **Liveness is deliberately absent:** `collect_service_health` makes real calls to every configured provider, and at a 15-second scrape that is thousands of outbound requests an hour — `P15` undone by the telemetry meant to watch it. **Auth reuses the existing API-token system** rather than building a second one (`Law 14`): a new read-only `metrics:read` scope, which Prometheus sends natively via `authorization: credentials:`, plus an admin session so a person can just open the URL. Disabled returns **404, not 403** — off should look like never built. A failing collector costs its own metrics and is itself reported; a scrape that 500s because one subsystem is unwell goes blind exactly when it is needed. Documented in `docs/setup.md` with a copy-pasteable `scrape_config`. 20 tests, 7 mutations. *(Three survived. Two were the **docstring read as code** trap — the module explains at length why `requests`, `service_health` and `prometheus_client` are absent, and a substring search found those words in the prose; the same trap then hid a deleted **scope gate**, because the handler's docstring names `metrics:read`. Both parse the AST now, with the docstring dropped. The third found the `# TYPE` de-duplication guard to be dead — no collector declares inside a loop today, so removing it changed nothing — and it is kept, tested directly on the unit, because declaring beside each value is the natural mistake and a duplicate `# TYPE` is a parse error in strict scrapers.)* **The push half — an OTLP exporter to an operator-supplied collector — is filed as `P16-19`**, not folded in here: it is a different shape with a background loop and a real destination, and this row's `Verify` is met by the pull.
- [x] **P16-13** **A guard that no default destination can ever appear.** `P16-12` creates the first legitimate place in the codebase for an outbound metrics URL, and therefore the first place a well-meant default could land — a "public demo collector", a "community stats" endpoint, an SDK whose constructor has a hosted URL baked in. The rule is absolute and has no opt-in ceremony that satisfies it (`D-2026-08-31-01`). `Verify:` a test asserts every telemetry destination setting ships empty, and CI fails on any hardcoded collector or analytics host anywhere in the tree — the check runs whether or not `P16-12` has landed, so it is armed before the hole exists rather than after. — **done 2026-09-01, before `P16-12` exists.** `.pantheon/check-destinations.py`, in CI beside the other ratchets. **The primary rule is an allowlist over shape, not a denylist of vendor names:** any absolute URL shipping as a default — in `DEFAULT_SETTINGS` at any nesting depth, `.env.example`, or a `docker-compose*.yml` environment default — must point somewhere local, be an obvious placeholder, or be listed with a written reason. **`ALLOWED` ships empty and the emptiness is the point.** A denylist is a guess about tomorrow's vendor names, and the vendor that matters is the one nobody has heard of yet; the known-collector host list is kept as a cheap second layer with its weakness stated in the file. Also enforced: any destination-shaped key (`*_url`, `*_endpoint`, `*_host`, `*_collector`, `*_target`, …) must ship falsy — broader than the five magic words the pytest guard used, which would not have caught `metrics_push_url`. **Baseline measured before ratcheting:** zero absolute URLs in `DEFAULT_SETTINGS`, and all 32 shipped URLs elsewhere are loopback, RFC1918, tailnet, `host.docker.internal`, a compose service name, or a `your-domain.com` placeholder. `not ip.is_global` rather than `is_private`, because a tailnet is `100.64.0.0/10` and `is_private` says False — that mistake was already made once, in the `P16-11` egress guard. **Half the tests assert it does NOT fire**, because a guard that cries wolf is a guard people route around: `.env.example` legitimately links to Google's OAuth docs and quotes a Gmail scope spelled as a URL, and both fired on the first version. 12 tests, 5 mutations. *(One mutation survived and was worth more than the four that did not: I had added a `COMPOSE_DEFAULT` regex to 'close the `${VAR:-…}` hole', and reinstating the hole broke nothing — because `classify()` only ever sees an extracted URL and the URL pattern excludes braces, so the hole was never open. The regex changed no result and is deleted; what actually makes compose scannable is one `lstrip("- ")`, and the test now says so.)*
- [x] **P16-14** **Make reporting a bug so easy it actually happens — which is the problem, not the missing pipe.** The owner, weighing opt-in vendor telemetry: *"having people report bugs is not very easy to get to happen."* True, and the usual conclusion — open a telemetry pipe — treats the symptom. **People do not report bugs because they do not know what to include and they are afraid of leaking their data**, and in this product that fear is correct: a stack trace here carries file paths (usernames), endpoint URLs (their LAN topology), model names, and often a slice of the message that caused it. So build the thing that removes both obstacles: **a one-click diagnostic bundle the person can read in full before it goes anywhere.** Last N log lines, the failing trace, versions, feature flags, redacted config — rendered on screen, editable, then copied to clipboard or attached to a GitHub issue **from their account**. No collector to run, no standing pipe, no data-controller obligation, and `Law 16`-clean because the destination is theirs and chosen per incident. `Verify:` someone who hits a bug files a useful report in under a minute without being asked to gather anything. — **done 2026-09-01.** `src/diagnostic_bundle.py` + `GET /api/diagnostics/bundle` + a collapsed panel under Settings → System. **The endpoint builds; it does not transmit, and there is no place in it for a destination.** The report is assembled locally, redacted, rendered as markdown into an **editable** box, and copied by the person after they have read it — no collector, no standing pipe, no data-controller obligation, and the destination chosen per incident. **Settings are allowlisted, not denylisted, and the measurement is why.** Filtering keys on `key|token|secret` against this tree's 71 settings flags `agent_input_token_budget`, `keybinds` and `research_max_tokens` — none of them secret — while sailing past a credential someone names `openrouter_thing`. A denylist is a guess about tomorrow's setting names. So values appear only for ~20 feature flags on `SHOW_VALUE`; every other setting reports its *shape* (`set` / `not set` / `number` / `3 item(s)`), which is what a maintainer actually needs. There is a test that plants a secret under an innocuous name and asserts it never appears. **Redaction runs over free text, because that is where the leak lives** — home paths (the username), URLs (userinfo and query, via the existing `redact_url`), email addresses, non-loopback IPs, known credential prefixes, and opaque strings of 32+ characters. **Ordering was measured, not assumed:** with the bearer pass ahead of the URL pass, `…/embeddings?api_key=abc` became `…/embeddings<redacted>` — safe, but mangled, and the comment claiming otherwise was wrong. The username pass runs **last**, over whatever survived, so nothing earlier can reintroduce it. **Half the tests assert what SURVIVES.** A bundle redacted into mush is not safe, it is useless, and it fails while still looking like a bug report — so model names, short SHAs, timings, file/line and the exception message must come out intact, and `127.0.0.1` is exempt because almost every report about a local model server names it and redacting it buys no privacy. Two of the eight mutations are *over*-redaction. **`issue_tracker_url` ships empty**, registered in all five places: `D-2026-09-01-01` says companies will make this their own private stack and their bugs belong in their queue, and a truthy default would additionally have made the `PANTHEON_ISSUE_TRACKER_URL` fallback dead code (`H06`/`B20`, `P16-05` from the other side). When empty the client offers this project's issues page — as an `<a>` the person clicks, carrying no report. 26 tests, 8 mutations.
- [x] **P16-15** **Let the product notice its own breakage and tell the user.** The other half of the telemetry problem: aggregate signal exists to reveal *silent* failure — a feature broken for everyone that nobody mentions. There is a way to get that without a pipe, and this product has already proved the need for it. **`H01` is the worked example:** every agent-composed email since install, staged and invisible, for a year, because nothing surfaced the queue. A local self-check that counted `agent_draft` rows and put a number in front of the user would have caught it the first week. Generalise it: a **health surface** that runs local assertions — is every configured integration answering, is the queue draining, is anything staged and unreachable, did any background job give up — and shows the user, on their own screen. The user becomes the sensor, which is both the honest design and, on this evidence, the faster one. `Verify:` a deliberately broken subsystem is visible to its own operator within one session, unasked. — **done 2026-09-01.** `src/self_checks.py`, surfaced at `/api/diagnostics/self-check` and rendered **above** the log console in Settings → System, because the whole lesson of `H01` is that nobody reads a log to find a problem they do not know they have. **The distinction that makes this worth building:** `service_health.py` already answers *can I reach X* — liveness. This answers *is something accumulating, or has something quietly stopped*. When a year of agent-written mail sat staged and invisible, **the mail server was reachable the entire time**; liveness said green. Four checks, each local, cheap and safe to poll: staged agent mail with its oldest date (`H01`), hosts the outbound limiter is holding off, embedding lanes unavailable so memory and knowledge search silently return nothing, and background follow-ups that have given up. **Three of the four give a reader to something that had none** — `P15-11`'s `snapshot()`, `P15-12`'s per-account mail backoff, and `P16-05`'s degraded lanes. Run against this very container it immediately reported one real `stuck`: no embedding lane. **Every check that can report `stuck` must carry an `action`** — a dot that goes red and offers nothing costs attention and returns none — and there is a test that enforces it. `unknown` never rolls up as `ok`: *the check could not run* and *nothing is wrong* are different answers. The panel is built with DOM calls, never `innerHTML`: this is the one surface whose entire job is reporting trouble, which makes it the likeliest to be handed a hostile string from a mail subject or a host name. 14 tests, 8 mutations. *(Three survived first time and all three were my tests: a rollup test with only one check never exercised the ordering; a caller test counted `loadSelfChecks()` including its own definition, so it passed with every call site deleted; and an admin-gate test used a fixed 1,200-character window that reached into the neighbouring route's `require_admin`.)* **Noted while building it:** `/api/diagnostics/services` — the liveness report — has **no frontend caller at all**. Same family as the `H` rows, filed as `P16-17`.
- [x] **P16-17** **The liveness report has no reader.** `/api/diagnostics/services` (`routes/diagnostics_routes.py:24`) collects a consolidated degraded-state report across ChromaDB, SearXNG, email, ntfy and every provider endpoint — real probes, admin-gated, safe to poll — and **nothing in `static/` calls it**. Found while building `P16-15`, which now renders beside it. This is the same family as the `H` rows: finished work with no door, in the diagnostics surface, which is a particularly poor place for it. The panel `P16-15` added is the obvious host. `Verify:` an operator sees which of their configured services are answering, without typing a URL. — **done 2026-09-01.** Fetched alongside the self-checks and rendered in the same panel, **after** them. That order is the point: something can be perfectly reachable and still quietly broken, and the reverse is obvious the moment you try to use it. Only non-`ok` services are shown — a wall of green teaches people to stop reading. The liveness fetch is wrapped so a failing probe cannot blank the state checks beside it; they answer different questions and one must not take the other down. 16 tests.
- [ ] **P16-20** **(Deferred — `D-2026-09-01-03`.) A hard network boundary, for whoever actually wants one.** I filed this as *the OS-level half of `P16-16`*, on the assumption that a scope which a shell command can step around is incomplete. The owner corrected the premise: *"internal comms, LAN to LAN etc is totally fine. we arent building fort knox. just an orchestration harness etc.."* **`P16-16`'s scoping is for directing the agent, not defending against it** — it prevents a model list that mixes the lab GPU with the production one, a sweep that wanders into the printer VLAN, an agent that helpfully fixes the wrong box. It does that completely. Containing a *hostile* run is a different problem with a different adversary, and on a machine where something is already executing shell there is no adversary left to contain. So this stays filed for the deployment that has one — most plausibly a company running Pantheon shared — and is **not on the path to a good version of this product**. `Verify:` if it is ever built, a run scoped to one segment cannot reach another even by running `curl`, via a network namespace, per-scope nftables/pf rules, or a per-run egress proxy — chosen on the evidence of the deployment rather than assumed. **What does not defer:** the auth boundary. `FORBIDDEN.md` Part 2 and `D-2026-09-01-01` stand — *LAN-to-LAN is fine* is about traffic between machines the operator owns, never about who may log in.
- [x] **P16-19** **The push half of `P16-12`: an OTLP exporter to the operator's own collector.** `P16-12` shipped the pull, which covers Grafana and is what its `Verify` describes. Push is the case pull cannot reach: a Pantheon behind NAT, or on one of the *parallel networks* of `P16-16`, where the collector cannot scrape in. `Verify:` an operator sets one collector URL and metrics arrive there; **the shipped value is empty** and `.pantheon/check-destinations.py` fails the build if it is not. Build it with `httpx` and OTLP/HTTP+JSON rather than the OpenTelemetry SDK unless the SDK earns its weight — and route it through the `P15` limiter, because a metrics push on a timer is precisely the recurring outbound job that phase exists for. Note that the exporter is the first legitimate outbound destination in the product; `P16-13`'s guard is what keeps it the operator's and not ours. — **done 2026-09-05, and the row's `Verify` is met by construction rather than by promise.** One address, `otlp_endpoint`, shipping empty — and empty is enforced by `.pantheon/check-destinations.py`, which `P16-13` armed before this row existed precisely so the answer was already no by the time someone wrote the file. **There is no separate on/off switch, deliberately (`Law 14`):** the address is the switch, because a second control can disagree with the first and the failure that enables — enabled true, address blank, operator waiting for data — is worse than the one it prevents. **`httpx` and OTLP/HTTP+JSON, no OpenTelemetry SDK**, as the row asked: the payload is six nested keys and the SDK brings a dependency tree, its own background processor, and a constructor whose default endpoint is a real address — three things to audit in exchange for serialising a dict. **The push does not have its own collectors.** `metrics_export._Out` now keeps the values structurally alongside the text lines and `collect_metrics()` hands them over, so both transports read one set of collectors; two sets is how a dashboard starts disagreeing with itself. The metric names still say `scrape` on the push path on purpose — renaming them for the second transport would silently halve every series for an operator running both. **Paced by the `P15` limiter**, which also buys `P16-16` scoping for free: `acquire_async` calls `require_host` before it paces, so an out-of-scope collector is refused without this module knowing what a network is. Jittered, per `P15-10`. **The bugs worth knowing about are all in the JSON, and all silent.** `timeUnixNano` is a uint64 and proto3's JSON mapping renders 64-bit integers as **strings**; a nanosecond timestamp is ~1.8e18, so emitted unquoted some collectors reject the batch and others truncate it and plot the data in 1970 — and `json.dumps` is happy either way, so nothing local ever complains. Everything goes out as `asDouble` for the same reason (`asInt` is int64 and would need the same treatment; `P16-12` already decided everything is a gauge). Attributes are a **list** of key/value, samples sharing a name are **one** metric with several data points, and label values are **not** run through the Prometheus escaper — doing both would put a literal backslash-n inside a string `json.dumps` was about to escape correctly. `NaN` is the one that would take down the whole batch: `float("nan")` succeeds and `json.dumps` writes the bare token `NaN`, which is not valid JSON, so one bad sample would cost every other point in the push. **A 200 is not proof of delivery** — OTLP/HTTP answers a partly-rejected batch with `200` and a `partialSuccess` body, so the response is read rather than checked, and `pantheon_otlp_points_rejected` is on the scrape. **The exporter's own health is reported on the pull endpoint**, which is the whole point of putting it there: when the push is failing, the pushed copy of that metric is exactly the one that does not arrive. `..._last_success_age_seconds` is **absent** until a push succeeds rather than `0`, which would read as *just now* and is `B28` in a new costume. 53 tests plus 4 on the shared accumulator, 22 mutations, all caught. *(One survived first: a test that `collect_metrics()` returns a copy. `_assemble()` builds a fresh `_Out` per call, so mutating the returned list could never corrupt the next call — the test passed with the copy removed and proved nothing. The hazard is one level down, where `_Out` is now shared between two renderers, and it is tested there.)* Documented in `docs/setup.md` with the settings table and what to alert on. The one-switch call is `D-2026-09-05-01`, written down because adding an `otlp_enabled` beside the address is the obvious improvement and the next reader will want to. **One correction to an existing guard:** `test_no_telemetry_destination_ships_pre_filled` matched any key *containing* one of five topic words, so `otlp_interval_seconds` — a number of seconds — was read as an address and had to be empty; and because it matched on topic rather than shape, `grafana_target` would have sailed past, which `check-destinations.py`'s own docstring already names as that guard's weakness. It now imports the checker's `DESTINATION_KEY` rather than restating it, so the two cannot drift. **The other correction is at the settings door:** `otlp_endpoint` was accepted unvalidated, and the push loop only logs a warning — so a typo answered 200, echoed the operator's value back, and left them watching a collector that would never receive anything. That is the `trust_rung` defect exactly (`a security setting must not be quietly rejected`), and it is refused at the door now, with the interval clamped and the header map type-checked beside it.
- [x] **P16-16** **Reach across parallel networks, deliberately.** The owner's north star includes *"my network (even my parallel networks etc)"*, and that is not what the product does today: `src/model_discovery.py:207-243` scans loopback, `host.docker.internal`, the local LAN and Tailscale peers — one network's worth of hosts, implicitly, from wherever the container happens to sit. Several segments at once (VLANs, a second physical LAN, more than one tailnet, a lab subnet behind a jump host) is a different feature, not a bigger scan: it needs named networks with their own reachability, their own credentials, and their own trust level, because "the printer VLAN" and "the production subnet" should not be one undifferentiated pool the agent may roam. **`Law 16` is not in tension with this** — a network the operator named is a network they linked. `Verify:` an operator declares two segments, and the agent can be told to act on one without gaining reach into the other. — **done 2026-09-01.** `src/networks.py`: named segments with their own hosts, CIDRs and **trust level**, plus a `ContextVar` scope a run is bound to. **Ships declaring nothing, and nothing declared changes nothing** — `network_for()` returns `None`, no scope is in force, and every existing path runs exactly as before. `Law 16` is not in tension with this and the law's own words are why: it is about *defaults*, not capability, and a network the operator **named** is a network they linked. **The boundary is enforced, not advisory:** inside a scope an out-of-scope host is refused at `check_outbound_url`, `outbound_fetch._resolve_public_ips`, and both `OutboundHostLimiter.acquire` paths — three independent layers, because a caller that skips one should still be caught. **Refused before DNS**, deliberately: rejecting after a lookup has already told the other network's resolver that we asked is a boundary that leaks the question it exists to prevent. **A host in no declared network is refused too** — *I could not classify it* is not a reason to permit reach, and someone who named two segments and asked for one did not mean *and also anything I forgot to describe*. **Nesting narrows and never widens**; a scope that can be widened from inside is not a scope. **CIDRs classify, listed hosts are scanned** — a `/16` is 65,536 addresses and expanding a declaration into a sweep is how *discover my networks* becomes a port scan the operator's own IDS reports. Discovery tags every endpoint with its network, because a model list that cannot say which network a server is on is how *the lab GPU* and *the production GPU* become one dropdown. **What it honestly does not do is written into the module's own docstring and the docs:** it is not an OS-level control, a shell tool running `curl` reaches whatever the process has a route to, and stopping that needs a network namespace rather than a Python function. A boundary described as tighter than it is, is worse than one described accurately — people plan around the description. Filed as `P16-20`, and there is a test that fails if that disclosure is ever removed. 24 tests, 7 mutations.
- [x] **P16-11** **A `Law 16` regression test that runs in CI.** The defaults are pinned by `tests/test_self_hosted_defaults.py`, which is the cheap half. The expensive half is the one that would actually hold: **run the app with egress blocked and assert it boots, answers a message, and renders a reply.** Everything above was found by reading; a test that runs would find the next one. `Verify:` a CI job with no route to the internet completes a first-message round trip. — **done 2026-09-01, and built as a runnable test rather than a CI-only job** so it fails on a developer's machine too, before the push. **The guard sits at `socket.connect` and `getaddrinfo`, not at `httpx`.** Guarding the HTTP library would have missed `urllib`; guarding both would have missed `subprocess` → `npx`, and the npm fetch was the worst offender of the lot. Every one of them reaches a socket eventually. Loopback, the docker host alias, RFC1918 and link-local pass; the classifier is `not ip.is_global` rather than an enumeration of private ranges — **the first version listed loopback/private/link-local and called Tailscale egress**, because tailnet addresses live in `100.64.0.0/10`, which is RFC 6598 shared space and `is_private` is False for it. That would have made the guard fire on the product doing its actual job. Covers: the settings layer, the built-in MCP registry (where the npm fetch lived), the 286-skill bundled library, the embedding lanes, the search defaults and the limiter itself. Wired into CI as the `law16-egress` job beside `wiring-ratchet`. **10 tests. The mutation run found the guard is two independent layers** — blunt DNS and connect catches it, blunt connect and DNS catches it, only blunting both goes red — which is right, and meant the combined test could prove neither half alive. Each is now exercised on a path the other cannot reach: a raw `sock.connect` to an IP for one *(`create_connection` calls `getaddrinfo` even for a literal IP, so it could not be used)*, and a bare `getaddrinfo` for the other.
- [x] **P16-18** **Nothing ever compared the tree against `CREDITS.md`, so two attributions were missing and the summary of the rest was wrong.** `P16-06` found OpenMoji (**CC BY-SA 4.0**) credited nowhere; the owner's instruction was *"make sure licenses are aligned, we can still use that emoji thing it could add good personality to the platform"* — so the fix is paperwork, never removal. — **done 2026-09-01.** **The audit found three things and only one of them was OpenMoji.** *(1)* `static/icons/ollama-mark{,-crop}.png` and `static/icons/sglang-{mark,logo}.png` are **other projects' brand marks**, in the tree since the fork baseline (`fff72ec`), used to label backends in the Cookbook, attributed nowhere. A permissive software licence covers a project's code, not its trademarks, so nothing in `licenses/` was ever going to cover them — which is exactly why an audit that looks for `LICENSE` files walks straight past a logo. Now a section of their own, stating the use is **nominative** and that Pantheon claims no affiliation. The Ollama line under *companion services* — a list that says outright those projects are *"not distributed with this project"* — was true of Ollama's software and never of its mark; both entries now stand, cross-referenced. *(2)* **`CREDITS.md`'s own summary had gone false.** *"The one copyleft dependency is optional"* named PyMuPDF, while CC BY-SA 4.0 artwork shipped by default two sections below it. A summary is read *instead of* the detail, so that is the one place the omission does damage. Rewritten to name both, plus the aggregation argument that was never stated: the emoji are a data file the program reads, §5's aggregate, so **CC BY-SA does not reach Pantheon's code and the AGPL does not reach the artwork** — and a fork that redraws the glyphs owes share-alike on the glyphs alone. *(3)* A paragraph claimed five vendored bundles carry no licence banner; measured, it is **seven** — KaTeX and Mermaid have none either. **The systemic fix is `.pantheon/check-licences.py`, and its inventory is an allowlist**: an unlisted file under `static/lib/`, `static/fonts/`, `static/icons/` or `library/` fails the build, so adding a vendored asset means writing its licence line, which means having read it. Six rules, one per way this has actually rotted — undeclared file, missing text, unlinked text, orphan text, broken link, and **a copyleft entry absent from the scope summary**, which is the regression just fixed. In CI beside `check-wiring` and `check-specifiers`. 10 tests, 8 mutations. *(The checker's first pass on the vendor marks asserted the string `"Ollama"`, which **already appeared** in `CREDITS.md` under the not-distributed list — a green tick over an unattributed logo. The assertion is the file path now: a project name matches incidentally, a path only matches deliberately. It then caught **my own prose**, failing on a `licenses/Pyodide-MPL-2.0.txt` I had written inside a sentence explaining that the file does not exist.)*

---

# Hidden — features that exist and cannot be reached

*Found 2026-08-30 by a four-part discovery audit, run because the owner said of his own
product: **"there's a lot of hidden things that are in this platform that we can't fully
discover yet."** He was right. Four read-only agents swept the backend (500 routes — not the
301 in `routes/*.py`, which silently omits 173 in subdirectories), the frontend (168 modules),
the configuration surface (68 settings keys, 8 flags, 128 env vars) and every place the product
*claims* a capability. Two of them independently found the same two defects, which is the
strongest evidence in the set.*

*These are not bugs in a feature someone is building. They are **working code with no door** —
and the difference matters, because every one of them is already paid for. Ranked by harm:
the product lying to the model comes first, because the model repeats the lie to a person as
fact; then losing their data; then hiding capability they own.*

- [x] **H01** **The agent's email approval queue is a black hole, on by default.** `agent_email_confirm` defaults to `True` (`src/settings.py:46`), so `_send_email` does not SMTP — it stages the message into `scheduled_emails` with `status='agent_draft'` and a **far-future `send_at` the poller never reaches** (`mcp_servers/email_server.py:1393,1478`). Three endpoints exist to complete the loop: `GET /api/email/pending`, `POST /api/email/pending/{sid}/approve`, `DELETE /api/email/pending/{sid}` (`routes/email_routes.py:4471,4490,4514`). **`grep -rn "email/pending\|agent_draft" static/` returns nothing** — no path, no identifier, no comment, in 183 frontend files. Three places state the intent and all three are wrong about reality: the route comment says *"these endpoints let the chat UI surface them"*, the stash docstring says *"the chat UI can render as an approval card"*, and the model is **instructed** at `src/agent_loop.py:949` and `:962` that the tool *"stages the email for the user to approve in the chat UI."* So the model tells the user their mail awaits approval and there is no approval surface in existence. Every agent-composed email since this default landed is sitting unsent and invisible. `Verify:` a pending-drafts card in chat with Approve and Discard; and run `git log -S'"agent_email_confirm": True' src/settings.py` first, because that tells you whether the backlog is a week or a year. **The question this row told you to ask first is answered (2026-08-31): it is a year, not a week.** `git log -S'"agent_email_confirm": True' -- src/settings.py` returns exactly one commit — `fff72ec`, *baseline: cybertooth c3b2120*, which is this fork's own starting point — and `/work/base/src/settings.py:46` carries the same default. **The default arrived with the install and predates the fork entirely.** So the backlog is not something Pantheon introduced and is not bounded by the fork date: every agent-composed email since this instance was first stood up is staged, unsent and invisible, and the same is true of every Odysseus install running this default. That changes the priority and it changes the fix: the drafts already in `scheduled_emails` need a way out, not just a switch that stops making more. **One-line stopgap while the UI is built: default it to `False` so new mail actually sends — but that strands the existing backlog, so the drafts view is the real fix and the stopgap is not a substitute for it.** — found during the discovery audit — agent:`audit:backend` — **done 2026-09-07. The panel exists, and the three sentences that claimed it did are now true.** `static/js/agentDrafts.js` + a `<section>` docked above the composer, and the grep that opened this row is now inverted into a test so it can never come back clean. **It opens itself.** No tab, no menu, no badge, no setting — the failure being fixed is that mail was held where nobody looked, and a surface that has to be found is the same bug with a shorter path. Two tests pin that: one that a single draft opens the panel with nothing clicked, and one that the `start()` call in `chat.js` has no flag or condition in front of it. **A failed poll does not empty it** — hiding held mail because one request failed is the original bug in miniature. **The endpoint had a defect the card would have inherited, and it is the one worth recording.** `list_pending` returned `to_addr, subject, body` and *not* `cc` or `bcc`, although `_stash_agent_draft` has always stored both. Nothing had ever called the endpoint, so nothing had ever noticed. An approval card built on it would have shown a message without its recipients and asked somebody to press Send on a blind copy they could not see — a worse failure than the black hole it replaces. Both are returned now, both are on the card, and a `bcc` is marked. **The age is the headline, not the count.** The row's gating question was *a week or a year*, because the answer changes what the user should do; so the endpoint returns `oldest_age_seconds` (the max, not the first row) and the panel says *"the oldest since 2 years ago"* rather than *"47"*. `created_at` is naive UTC and is parsed as UTC — read as local time it reports the backlog hours off by the operator's offset, which is the one number this row exists to put in front of somebody, and `None` rather than `0` for an unreadable value because `0` reads as *just now*. **`POST /pending/discard-all` is new, and there is deliberately no approve-all.** Clicking through a year-deep backlog one item at a time is not a way out, but a button that SENDS hundreds of year-old model-composed emails to real people in one press is the auto-send hole `agent_email_confirm` exists to close, rebuilt with a dialog in front of it. Approving stays per-message because each one is a separate decision about a separate recipient. Discard is `status='cancelled'`, never a DELETE — draining a backlog should not be the destructive act — and it touches only `agent_draft` rows, so the user's own scheduled mail in the same table is untouched. **The shell is the queue panel's, class for class** (`Law 14`): one more thing docked above the composer, not a second visual language for the same idea. Only the row vocabulary is new, and nothing defines `--accent` in `:root`. No `innerHTML` anywhere — every field on these cards is model-written text derived from email that arrived from outside. 32 + 13 tests, 20 mutations, all caught. *(Two survived. One found the plural rule untested: every age case was plural, so `1 years ago` passed — the singulars are reachable at exactly the band handovers and are pinned now. The second is the `Law 15` one and it is the lesson of this whole row repeating itself: deleting `agentDrafts.start()` from `chat.js` broke nothing, because every test imported the module directly and none of them went through the app. A panel nobody starts is the same defect as three endpoints nobody called.)* Documented in `docs/setup.md`, including the sentence that matters most to an existing install: expect a backlog on first launch, nothing was sent, and nothing was lost. **The default flip is still not done and that ordering stands** — flipping it now would stop new drafts accumulating and strand every one already staged. The drainer had to come first. **The theme guards caught a real defect on the way through, and it is worth reading.** The obvious way to weight the approve button and mark a `bcc` is `color: var(--accent)`, and `test_the_population_under_the_contrast_exception_cannot_grow` refused both: 187 sites already paint text in the undiluted accent and every one fails the contrast floor on **seven of the sixteen palettes**. A `bcc` warning that is invisible on seven themes is worse than no warning, and *Approve & send* is the one label on this panel nobody can afford to misread — so the accent carries them as a border-and-background TINT and the labels stay `--fg`. That population is unchanged at 187. The spelled-fallback count moved 554 → 556 for the two `color-mix` tints, which is bookkeeping, and the test says in as many words what to do about it: *move the number and say which site in the commit — do not widen the assertion.* Both quoted mirrors in `theme.js` and `index.html` moved with it, because `test_the_counts_the_accent_comments_quote_are_still_the_counts` asserts equality rather than membership: a second mention left at the old value is exactly how a count goes half-stale and still reads as current.
- [x] **H02** **The Personal Assistant has no door at all.** 475 lines of frontend (`static/js/assistant.js`, loaded on every page at `index.html:2751`) and six live routes (`routes/assistant_routes.py` — session, settings GET/PATCH, run, run-status, timezones) behind a settings modal offering a personality picker, timezone, endpoint, model, a grouped tool allow-list and **daily scheduled check-ins**. Both entry points are dead: `openAssistantChat()` (`:23`) has **zero callers repo-wide**, and `openAssistantSettings()` (`:401`) is reached only from a gear built by a poll gated on `window.sessionModule?.getActiveSession?.()` — **`getActiveSession` occurs exactly once in the repository, at that call site**, and is not among `sessionModule`'s 22 exports. So the gear is never built and the poll spins 120 times over two minutes on every page load doing nothing. The comment at `:416` says the views *"now live as Activity / Settings tabs inside the Tasks modal (see tasks.js)"* — **`tasks.js` never imports `assistant.js`**; that migration never happened. The session is lazily created by the route only `openAssistantChat()` calls, so the assistant does not even appear in the chat list by accident. `Verify:` a person can open the assistant, configure it, and receive a daily check-in. — found during the discovery audit — agent:`audit:frontend` — **done 2026-09-07. A rail button, and the gear now gets built.** `rail-assistant` sits in the icon rail beside the other launchers, with a hover label and a `UI_VIS_MAP` entry so it behaves like everything else there — the point of this row is that the assistant is part of the product, and a launcher without a label is visibly a bolt-on. It calls `openAssistantChat()`, which had **zero callers repo-wide**. **The gear's condition was dead in both branches.** It polled `window.sessionModule?.getActiveSession?.()?.id` — a method that occurs exactly once in this repository, at that call site, and is not among `sessionModule`'s exports (the real one is `getCurrentSessionId`) — falling back to `document.body.dataset.activeSessionId`, which nothing sets. So the gear was never built and **the only observable effect of the whole mechanism was 120 wasted ticks per page load**, every load, for two minutes. **Replaced with an event, not a fixed poll**: `sessions.js` now dispatches `pantheon:session-changed` from `selectSession`, which is a small general addition other modules can use, and the assistant listens for it plus checks once at boot for a reload that lands directly on its session. That removes a recurring timer rather than adding one, which is `P15-10`'s direction. **The stale comment is corrected rather than deleted.** It said the views *"now live as Activity / Settings tabs inside the Tasks modal (see tasks.js)"* — `tasks.js` has never imported this module, and the exports it claimed were in use were used by nothing. The migration was described and never performed, and **the description is why nobody noticed**: a reader checking whether the assistant was reachable found a sentence saying it had moved, and stopped looking. The correction quotes the old claim, because a reader needs to see what the file used to say to understand why the door was missing — which made the test about the correction rather than the absence of the sentence. That is now **four false claims about reachability in one audit** (`H01`'s three and this one), which is the pattern rather than the exception. **Check-ins already ride the existing scheduler** as three `ScheduledTask` rows, so they inherit `P15-10`'s dispatch jitter and needed nothing new — the third clause of the `Verify` was only ever blocked by the settings modal being unreachable. 16 tests, 9 mutations, all caught.
- [x] **H03** **`edit_image` advertises four actions and all four POST to routes that do not exist.** `src/tool_schemas.py:1037` offers `upscale · rembg · inpaint · harmonize`; `src/tools/image.py:34` posts to `{base}/api/gallery/{action}`. **None of the four exists.** The path matches `/api/gallery/{image_id}`, which is GET/PATCH/DELETE only, so it 405s; `do_edit_image` reads `data.get("error")`, finds none, and returns the bare string `"upscale failed"` — the model gets no hint the URL was wrong. **All four capabilities are real under other names**: `/api/gallery/ai-upscale`, `/api/image/remove-bg`, `/api/image/inpaint`, `/api/image/harmonize`. **The bodies differ and that is why this is a row rather than a path map** — `ai-upscale` takes multipart with an `image` file, not a JSON `image_id`, and `inpaint` needs a mask. Ship the three that map cleanly and **remove `inpaint` from the enum** rather than leaving it advertised. The only test touching `edit_image` asserts a symbol re-export. `Verify:` each advertised action performs its edit, and nothing advertised is unreachable. — found during the discovery audit — agent:`audit:promises` — **done 2026-09-07. Three actions now reach the routes that were always there, and `inpaint` is no longer advertised.** `upscale` → `POST /api/gallery/ai-upscale` (**multipart**, an `image` file plus `scale`), `rembg` → `POST /api/image/remove-bg` and `harmonize` → `POST /api/image/harmonize` (**JSON**, base64). The row was right that this is a rewrite and not a path map: a single path table would have turned three 405s into a 405 and two 422s. All three answer `{"image": "<base64>"}` — raw bytes, not a saved gallery row — so the tool reads the source image off disk, calls the route, writes the result back into the gallery **beside its original** and returns the new id; an edit that lands in an unrelated album is an edit the person has to go and find. **`inpaint` is removed rather than left advertised**, and asking for it now says why and where the capability lives: it needs a mask marking the area to replace, and a caller holding only an `image_id` cannot draw one. An action that cannot work is worse advertised than absent — absent, the model routes around it; advertised, it burns a turn and reports a failure the user cannot act on. **A wrong URL is loud now**, which is the actual complaint in this row: the old code read `data.get("error")` off a 405 body that had none and returned the bare string `"upscale failed"`, so a routing mistake was indistinguishable from a model that could not upscale. The status and the path are in the message. **And there was a second defect in the same function**: it posted without `_internal_headers()`, so even with the right URL every call would have been refused by `require_privilege(..., "can_generate_images")` — fixing the paths alone would have moved the failure from 405 to 403 and changed nothing the model could see. **The test that matters resolves every mapped path against the REAL mounted app**, because a table of plausible-looking paths is exactly what was there before. 16 tests, 12 mutations, all caught. **`check-outbound.py` caught the rewrite adding a call**: two posts where there was one took the budget from 117 to 118, so both go through `paced_http` — loopback, paced at zero by `LOCAL_POLICY`, costing nothing and keeping the count monotonic. The budget *fell* to 116. That also moved the stub in the new tests: patching `httpx.AsyncClient` would have stubbed a client nothing constructs, which is the *"a stub that survives the code moving out from under it"* failure `P15-06` found in the DuckDuckGo test — caught here by the mutation run rather than by the suite.
- [x] **H04** **A complete embedding-model manager with zero pixels.** `routes/embedding_routes.py`, all admin-gated: the fastembed catalogue with `downloaded`/`downloading`/`active`/`recommended`/`size_gb`/`cached_size_mb` sorted active-first (`:115`), download off the event loop (`:154`), progress poll (`:190`), delete-with-refusal-to-delete-the-active-model (`:211`), and custom endpoint config (`:244/:255/:335`). `grep -rn "embeddings" static/js static/app.js static/index.html` returns two irrelevant hits. This is finished, self-consistent code — it guards double-downloads and blocks deleting the model in use — that never got its markup. `Verify:` Settings → Embeddings shows which model RAG uses and lets an admin change it. — found during the discovery audit — agent:`audit:backend` — **done 2026-09-07. Settings → Embeddings, admin-only, all seven routes wired.** The panel leads with **what is in use**, not with a catalogue, because **the state that matters most is the one where nothing is installed**: `fastembed` and `chromadb` are *both* optional dependencies and a clean checkout has neither — verified — so memory and document search fall back to keyword matching, which is exactly the fallback `B40` found ranking by *contains two consecutive capitalised words*. Reporting "fastembed is not installed" and stopping tells an operator nothing about what it costs them, so the 503 is a **state with an explanation and an install line**, not an error. **Vector storage is reported separately** — chromadb can be absent while a model is configured, and then memory search cannot use vectors whatever this page says — and it reuses the existing `/api/diagnostics/services` rather than adding a second health route (`Law 14`). **The quietest failure available here is named**: a setting pointing at a model that was never downloaded, where nothing embeds and nothing complains. **Delete is not offered for the model in use** because the route raises 400 for it and an action that always fails is not an action — and where the route *does* refuse, its own words are shown rather than flattened to "failed", which is true of the endpoint validator too: it says which rule the URL broke and that is more useful than a red box. The download poll is keyed by model name, cannot be started twice, and is cleared when the panel opens; the API key is wiped from the DOM after a save; the catalogue is rendered in the order the route sorted it, because that decision belongs there. **One trap worth recording: a new frontend file is invisible to `check-unreachable` until it is `git add`ed**, because the scan is `git ls-files` — the panel was fully wired and the inventory did not move. Ceiling 96 → 91. 21 tests, 13 mutations, all caught.
- [x] **H05** **Seven of the eight feature flags do nothing, and four are un-hidden one line after being hidden.** `load_features()` has three Python callers, all of them read-write plumbing — **no server-side code branches on any flag.** Enforcement is entirely client-side: `static/app.js:1505-1514` hides four elements (`web_search`, `deep_research`, `document_editor`, `gallery`) and `censor.js:62` reads `sensitive_filter`; **`web_fetch`, `memory` and `rag` have zero consumers** (the three `P2-18` found by hand — confirmed). **The flag inventory in this row is `P2-18`'s and closes there** (2026-08-31); what follows is new and does not appear on that row. Worse, `static/app.js:1522`, in the *same* `.then()` callback, runs `applyUIVis(loadUIVis())`, which writes `display` for all 31 selectors in `UI_VIS_MAP` — and for a user with default Appearance prefs every one resolves visible. Measured by replaying the real sequence against a DOM stub: **after feature hiding 9 of 9 hidden; after `applyUIVis`, 7 of 9 shown again.** So an admin who turns off Deep Research or Gallery gets a success response, the toggle stays off, and the feature is still there — and was never gated server-side, so the agent could call the tool regardless. `Verify:` a flag turned off is off, for the user and for the agent. — found during the discovery audit — agent:`audit:config` — **done 2026-09-07. A feature is three things, so the flag is enforced in three places.** **The agent, which is the half the row is really about.** `tool_security.feature_disabled_tools()` maps each off flag to the tool names it removes and contributes them into the SAME `disabled_tools` denylist `execute_tool_block` already blocks on — `plan_mode_disabled_tools()` was the precedent for computing that set from a policy rather than storing it, and a second enforcement path would be a second thing that can disagree with the first (`Law 14`). So it inherits that gate's tests, its prompt-cache key and its fail-closed behaviour for free. **The HTTP surface**, via `src/feature_gate.require_feature`, mounted as a ROUTER dependency on research, gallery, memory and documents — not per route, because per-route decoration is a convention and the route that forgets is indistinguishable from the state this row found. **403 and not 404**, unlike `P16-12`'s metrics endpoint: *off should look like never built* is right for an attack surface nobody asked for and wrong for a feature a person can see in the product, whose admin switched it off — 404 there is a lie they can disprove by asking a colleague. The message names who can undo it. **Both gates fail OPEN**, deliberately: a features file that will not parse must not silently take half the product away, and that failure would look identical to an admin having turned everything off on purpose. An unknown flag name is likewise ON — the question is *has somebody switched this off*, and nobody can have switched off a flag that does not exist; treating unknown as off would turn a typo in a call site into a silently dead feature, which is this row's own defect. **`rag` is honoured at the retrieval site and nowhere else**, because retrieval is not a tool the model calls — it is context assembled before the turn, so there is no name for a denylist and no router that is only retrieval. It was one of the three flags (`web_fetch`, `memory`, `rag`) with **no consumer in any layer at all**; all three have one now. **`sensitive_filter` is deliberately mapped to nothing** and the reason is written into `_FEATURE_NOTES` rather than left as an empty set for the next reader to guess at: it is a display filter that redacts what is shown and removes no capability, so there is no tool or route whose absence would implement it. **The UI bug is fixed by precedence, not by ordering.** The features fetch hid nine elements and then, in the same `.then()` callback one line later, called `applyUIVis(loadUIVis())`, which writes `display` for all 31 `UI_VIS_MAP` selectors — every one of which resolves visible on default Appearance prefs. Nine hidden, seven shown again. **Both halves were deliberate**: that `applyUIVis` call was added to fix *"deep research only shows after I toggle"*, so removing it would put that back. The ids the admin turned off are recorded now and re-hidden as `applyUIVis`'s last step, every pass — so the user's preferences are restored without overruling the admin, which is the precedence a user's *show in sidebar* toggle should never have had. 26 tests, 19 mutations, 18 caught (the nineteenth deleted a comment, which is not a behaviour change — a badly chosen mutation rather than a gap). *(One survived and it is the same trap as the last four rows: the test asserted `_reapplyFeatureHiding()` is CALLED and that the call comes after the preference pass, and gutting the function to an empty body passed both. Presence is not behaviour. It extracts the two functions from the real `static/app.js` at test time and runs the actual sequence under node now — `app.js` cannot be imported standalone, which is why it is an extraction rather than an import, and the source is read at test time so a change to it changes what runs.)*
- [x] **H06** **`PANTHEON_TASK_CONCURRENCY_CAP` has never worked, on any install, from first boot — `B20` is filed as a weaker bug than it is.** `resolve_task_concurrency_cap` (`src/task_scheduler.py:98`) reads the instance layer as `get_setting(KEY, None)`, and `get_setting` calls `load_settings()`, which **merges `DEFAULT_SETTINGS` on every read** — so it cannot return `None`, returns the shipped `1`, and the env layer at `:119` is unreachable code. Proved with no settings file at all: `get_setting(...) -> 1`, `resolve -> (1, 'instance setting')`, `env alone would give 8`. **This contradicts `B20`, `src/settings.py:47` and `src/agent_loop.py:87`, which all say the env var dies on the first admin save.** It dies at import; materialisation is real but is not the cause, and a fix aimed at materialisation will not fix it. **The fix already exists and is unwired:** `is_setting_overridden` (`src/settings.py:279`) was written for exactly this, is documented, has four tests and **zero production callers**; `context_budget.budget_is_explicit` is the same idea, used, and correct. `Verify:` the env var wins on a fresh install and after a settings save. — found during the discovery audit — agent:`audit:config` — **done 2026-09-07. Reproduced first, on an empty data directory: `get_setting(KEY, None) -> 1`, `resolve -> (1, 'instance setting')`, env set to 8 and never consulted.** The audit's diagnosis was right and its prescribed fix was not. `is_setting_overridden` answers *presence*, and presence is the wrong signal **after** a save — `POST /api/auth/settings` does `current = load_settings()` and writes the whole dict back, so one admin save materialises all ~200 defaults and every key becomes "present", including the ones nobody has looked at. `budget_is_explicit` answers *value*, and value is the wrong signal **before** one — with no file at all `get_setting` still returns the shipped default, so a caller comparing to the default cannot tell "no file" from "someone typed 1". **Each of the two existing helpers is correct and neither is sufficient**, which is why one of them had four tests and zero callers: it was written for this and would not have fixed it. `settings.setting_is_explicit` is presence **and** a non-default value, and a mutation applying the audit's own suggested fix is one of the fifteen this file's tests catch. **The cost is stated in the docstring rather than hidden**: an operator who deliberately picks the default value is indistinguishable from a materialised one and the env layer wins — the same limit `agent_input_token_budget` already documents, and it only bites when the operator set both layers, where honouring the one we know was typed on purpose is the better guess. `is_setting_overridden` and `budget_is_explicit` are untouched; this is a third function, not a rewrite of two.
- [x] **H07** **CardDAV credentials from the environment die the first time anyone touches the Contacts panel.** `routes/contacts/contacts_routes.py:50,55,56` use `settings.get(k, os.environ.get(K, ""))` — the env var is the default only while the key is *absent*. Three UI paths write those keys unconditionally including empty values, and one of them is **"Remove", which deliberately PUTs three empty strings** (`static/js/settings.js:3059,3990,3598`). After any of the three, `CARDDAV_URL/USERNAME/PASSWORD` are permanently unreachable, and none is in `.env.example`. **The same idiom is latent on ten email fields** (`routes/email_helpers.py:1104-1117`), safe today only because no writer creates those flat keys any more — one future write of `""` reproduces this across a mail configuration. The correct shape is already in the tree: `services/search/providers.py:42` does `(settings.get(k) or "").strip() or env`. `Verify:` an operator's env credential survives a settings save and a Remove. — found during the discovery audit — agent:`audit:config` — **done 2026-09-07. Same defect as `H06` wearing different clothes: a fallback written as a default argument, which fires on absence and not on blank.** `settings.env_backed` is the shared rule, taking the dict rather than reading it so the two modules that parse `settings.json` themselves use the same one. The decrypt boundary is split out and kept: a stored password is encrypted at rest and must be decrypted, an environment one is plaintext and must not be, and the original expressed that correctly as `if password and "carddav_password" in settings` — which **silently became `if "" and ...` the first time a writer stored a blank**, which is how this hid. A mutation that decrypts an env password is caught. **Two of the three writers the row names are live; the third cannot fire at all** — `set-carddav-url/user/pass/save/msg` have no markup anywhere in the product, so that loader assigns to nothing and that click handler is bound to a button that does not exist. It is commented rather than deleted, and pointed at `uf-carddav-*`, the live form; building the missing markup would be a second CardDAV form and `Law 14` exists to stop that. **Fixing this created a new way to be confusing, so that is fixed too**: blank now means unset, so pressing Remove on a host that sets `CARDDAV_URL` leaves the field populated, which is correct — a web form cannot unset a variable in the server's process environment — and reads as a broken delete without a sentence saying so. `GET /api/contacts/config` gained an additive `sources` key naming the layer that answered, and the panel renders it. **The ten latent email fields are fixed before they fire**, which needed its own test precisely because nothing else would notice. **And the reason none of this was caught: `check-wiring.py` read only literal `getElementById`, and this codebase reaches for elements through `ui.el` / `admin.el` / `settings/dom.byId` — 925 call sites against ~1,100 direct ones, so nearly half the wiring in the product was outside the measurement.** Blind spot 4 closed; the ratchet went `--max 9` → `--max 124` with no product code changing, and `VERIFY-2026-08-27.md` had recorded the true number as 125 a week earlier. The backlog it exposes is `P3-20`. 18 + 8 tests, 24 of 26 mutations caught, the two survivors behaviourally equivalent.
- [x] **H08** **On local inference — the primary deployment — `agent_max_rounds` and the stream timeout are silently discarded.** `src/agent_loop.py:5083` lifts `max_rounds` to 100,000 and `max_tokens` to 1,000,000, and `:5142` lifts the 300s stream timeout to 24 hours, whenever `runtime_limits.unlimited()` is true — which is `_LIFT_WHEN_LOCAL` (**default on**) and any localhost/LAN `/v1` endpoint. The settings API clamps `agent_max_rounds` to 1–200 and `chat_routes.py:2357` re-clamps it *with a comment about defending against hand-edits* — then the loop replaces it. The only off-switch is `PANTHEON_UNLIMITED_LOCAL=0`, which appears **nowhere** outside `src/runtime_limits.py` — not `.env.example`, not compose, not `docs/setup.md`. `unlimited()` also removes read-file truncation and four fetch caps. **Bonus defect in the same block:** the `max_tokens` lift is nested *inside* the `max_rounds` branch, so the two knobs are accidentally coupled. `Verify:` the documented cap is the cap, or the lift is documented with an off-switch a person can find. — found during the discovery audit — agent:`audit:config` — **done 2026-09-07. The lift stands; it just may not overwrite a number a person typed.** `agent_max_rounds` is offered in the settings UI, validated to 1..200 by the admin endpoint, and re-clamped in `chat_routes` *with a comment about defending against hand-edits* — and then replaced with 100,000 on the default deployment, so **all three guards were theatre** and an operator who set 5 because their machine thrashes got 100,000. `runtime_limits.lift_cap` is the rule — `pinned` is the caller's `setting_is_explicit`, which is `H06`'s function on its **third** caller — and it lives in the one module that imports nothing from the project, so `pinned` is an argument rather than a read. **The bonus defect is real and de-nesting it was forced rather than optional**: while the outer condition was always true (`chat_routes` clamps rounds to 1..200) the nesting had no observable effect, but adding the pin check would have made an explicit ROUNDS setting silently disable the TOKENS lift too. **The `max_tokens` lift is left alone and the question filed as `P3-21`** — it comes from the preset, not from settings, and flattening every preset to 1,000,000 is a product call for the owner, not a bug fix. **The off-switch is now findable**: `PANTHEON_UNLIMITED_LOCAL` and `PANTHEON_FORCE_UNLIMITED` are in `.env.example` with what they cost, and the text says a configured limit is still honoured — without that an operator reads "caps are lifted on local" and disables the whole mechanism to get a cap they could have typed. Two tests assert that documentation, because the row's `Verify` is about discoverability and code cannot provide it. **The wiring is a function (`_resolve_local_lifts`) because it had to be**: the rule and the settings read were each testable alone and both passed, while two mutations that never consulted the pin survived — the ingredient-not-the-recipe family again, caught by mutation rather than by review. 20 tests, 16 mutations, all caught. The four content-size sites `unlimited()` also governs (read truncation, four fetch caps) are untouched: nobody configured those in a UI.
- [x] **H09** **The compact prompt names two tools the model has no way to call.** `src/agent_loop.py:4588` selects the compact prompt for every API model plus native and compat Ollama. It says *"Only the tool schemas provided by the API are available for this turn… do not write tool syntax in chat"* — then lists `generate_image` and `manage_research`, the only two entries in `TOOL_SECTIONS`/`TOOL_TAGS`/`tool_index` with **no `FUNCTION_TOOL_SCHEMAS` entry**. The fenced fallback is shut for exactly these models (`skip_fenced=is_api_model and not allow_fenced_for_api`). Both channels closed, both tools named. The same prompt then tells the model *"if a needed tool is missing, say what is missing instead of pretending"* — trusting the list that is misleading it. **The better fix is the guard, not the two instances:** filter the compact list against `FUNCTION_TOOL_SCHEMAS` so this class cannot recur. `Verify:` every tool the prompt names is callable on that turn. — found during the discovery audit — agent:`audit:promises` — **done 2026-09-07. The guard, not the two instances, exactly as the row asked.** The compact branch of `_assemble_prompt` now lists a tool only if it has a `FUNCTION_TOOL_SCHEMAS` entry, so a tool added to `TOOL_SECTIONS` without a schema — which is how both current ones arrived — cannot reintroduce this. The set is **computed from the schemas rather than named**, and a mutation that hard-codes `generate_image`/`manage_research` instead of applying the rule is one of the six the tests catch. **An omission is logged at WARNING, not swallowed**: a tool vanishing quietly from a prompt is how the next one hides, and either the schema is missing or the section should not exist. **The non-compact prompt is untouched** — it documents fenced syntax and goes to routes where the fenced parser is live, so `generate_image` is genuinely reachable there and filtering it out would delete a working capability. **The row understates the problem and the larger half is filed as `B39`, which needs the owner**: on a default Ollama endpoint `is_api_model` is forced False, so no schemas are sent at all, while `compact` is True — the prompt tells the model to use native calls it has not been given and not to write the fenced syntax that is the only channel actually being parsed. Those two tools are the visible corner of every tool being unreachable. 8 tests, 6 mutations, all caught.
- [x] **H10** **Session cleanup, with a dry run, unreachable.** `GET /api/cleanup/preview` and `POST /api/cleanup` (`routes/cleanup/cleanup_routes.py:22,38`) archive sessions untouched for 7 days, delete archived/unimportant/under-10-message ones at 14, and report MB freed — and `preview` shows exactly what *would* happen first. `grep "api/cleanup" static/` returns nothing; both halves unreachable. `Verify:` "reclaim 340 MB from 82 stale chats — here is the list" before anything is touched. — found during the discovery audit — agent:`audit:backend` — **done 2026-09-07. Settings → System, above the Danger Zone.** The dry run is why this belongs in the product rather than beside the wipes: the preview returns what would be archived, what would be deleted, **and what is being spared with the reason** — *part of last 10 sessions*, *has 20+ messages*, *contains keyword: important* — and someone deciding whether to free 340 MB wants to see what survives at least as much as what goes. All three groups render, and a mutation that drops the reason is caught, because the first version of that test asserted the *service* returns one and nothing asserted the *panel shows* it. **Run stays hidden until a preview finds something**, and the confirm is `danger` only when a deletion is actually going to happen — archiving is not deletion and a dialog that shouts at both teaches people to dismiss it. **Rendered with `createElement` and `textContent`**: session names are user-supplied and a chat title is a perfectly good XSS payload (`H01`'s discipline). **Two corrections to the row.** Its "under-10-message" is wrong — `MIN_MESSAGES_TO_KEEP` is **20**, and the panel's prose is now asserted against the constants so it cannot drift. And a flat `app.routes` walk says these routes are not mounted at all; they are, and this FastAPI wrapping included routers is the same false alarm that shaped `check-unreachable.py`'s traversal — that is now a test rather than a thing to rediscover. **The panel is asserted to be in `initAll`'s list**, because `initRag` and `initWebhookForm` show exactly how a panel dies here: both are still defined in `admin.js`, both reference markup that no longer exists, and both were removed from that list rather than deleted, so ~250 lines have not run in a long time. 11 tests, 8 mutations, all caught. **And one existing test had to be turned around rather than deleted**: `test_unreachable_surface.py` asserted the checker still finds `/api/cleanup/preview` with no frontend caller, which was the point of `H10` and is now false. A test that pins a defect argues for the bug once the defect is fixed, so it asserts the opposite claim and stays as a regression guard. `check-unreachable` reports 101, down from 104.
- [x] **H11** **Three memory views, including the answer to "why did it remember that".** `GET /api/memory/timeline` (chronological, annotated with the source chat's name), `POST /api/memory/debug` (*which memories would this query trigger, and why*) and `GET /api/memory/by-session/{id}` (*what did this chat teach the assistant*) — `routes/memory/memory_routes.py:170,85,208`. **Corrected 2026-08-31 — the finding holds, the framing overstated it twice.** All three routes do have zero frontend callers (re-checked: `grep -rn` over `static/` returns 0 for each). But **(1)** *"The UI uses only add/search/{id}/pin"* undercounts the surface: `static/` also calls `api/memory/import`, `api/memory/extract` and `api/memory/audit`. And **(2)** *"the answer to 'why did it remember that'"* names the wrong question — `POST /api/memory/debug` answers *which memories would this query retrieve, and why*, which is retrieval, not provenance; and the retrieval half is **already partly visible**, per `P13-10`: the memories used in an answer render as a `.memory-used-pill` with a detail panel today. **What is genuinely unreachable is the diagnostic run against an arbitrary query** — asking *why would this fire* without having to send the message first — plus the timeline and the per-session view. That is still worth building; it is a smaller row than the headline implied. `Verify:` a person can ask why a memory would fire for a query they have not sent. — found during the discovery audit — agent:`audit:backend` — **done 2026-09-07, to the row's corrected scope rather than its headline.** The search box in the Brain has two modes now: *Contains*, the substring filter it has always been, and **Would fire**, which runs the real retriever — the one that decides what the agent sees — and reports what it would return **and why**, without having to send the message first. `POST /api/memory/debug` was live, owner-scoped and documented as *"debug which memories would be triggered"*, with no caller anywhere. **It could only ever answer the WHICH**: `get_relevant_memories` computed a score and a keyword boost and dropped both on its last line, so a person asking *why did it remember that* was handed a list and left to infer the answer. `explain_relevant_memories` keeps them; `get_relevant_memories` is now a one-line wrapper over it, so its contract for five production callers is unchanged and a test asserts the two paths agree on selection and order. **The reasons are written from what the code does**: which words were shared, which boost applied and why, whether the query appears verbatim — and, most importantly, when a memory was **admitted at 0.9 without being scored at all**, which is invisible from the ranking and is exactly the behaviour that was hiding `B40`. **The query type is reported once**, above the list, because how the retriever reads the question is the single most surprising thing a person learns here. `explanations` and `query_type` are additive keys; `memories` and `total` are untouched. **The server's order is not re-sorted locally** — the order *is* the answer, and the normal path would have re-sorted it by date and pinned-ness two lines later. A sequence guard drops stale responses, because a diagnostic that flickers back to an earlier answer is worse than one that says nothing. **Building this is what found `B40`** — writing truthful reasons meant reading what the scorer actually does, and what it actually did was rank by *contains two consecutive capitalised words*. **Not built, and said plainly rather than quietly dropped:** the `timeline` and `by-session` routes are still unwired. The row's own correction notes the timeline is close to an existing sort and that per-session belongs on a chat rather than in the Brain; both are real, neither is the `Verify`, and bolting them into this modal to close a row would be the second scaffolding `Law 14` exists to prevent. They stay in `check-unreachable`'s inventory where the next person will find them. 16 tests, 10 mutations, all caught. **`B41` is mine and came out of this row**: the anchor I edited was the *search* route's return, not the debug route's, and the debug route returns a different shape entirely (`relevant_memories`, text and category, no ids — which is why `memories` is a separate additive key rather than an edit to it). 17 tests now, and the route assertions resolve a single handler's source rather than grepping the file.
- [x] **H12** **Your voting history lives in one browser and the server's copy is write-only.** **Premise corrected 2026-08-31 — the original headline (*"can never see your results"*) is false and the row is narrower and more interesting than it was written.** A **Scoreboard exists and is reachable**: `static/js/compare/scoreboard.js` renders per-mode win/loss/tie and cost aggregates, is imported and re-exported by `compare/index.js:32,1517,1529`, and `index.js:382` records that its button was moved into the vote bar beside Tie. What is true is the half underneath. `showScoreboard` reads `Storage.getJSON(VOTES_STORAGE_KEY, [])` — **browser storage** — while `POST /api/compare/record` (`vote.js:130`, the only compare route the UI calls) writes a server record that nothing ever reads back: `GET /api/compare/history` and `DELETE /api/compare/{id}` (`routes/compare/compare_routes.py:320,346`) have no caller. So the two copies drift silently and neither is authoritative: clear your site data and the visible history is gone while the server still holds every vote; vote from a second browser and the Scoreboard disagrees with itself. `Verify:` the Scoreboard reads the server record, so the same account sees the same history from any browser — and Clear History clears both, not one. — found during the discovery audit — agent:`audit:backend` — **done 2026-09-07, to the corrected row.** The Scoreboard reads `GET /api/compare/history` now, and the local store stops being a rival record and becomes a **cache and an offline buffer**. **`server_id` is what joins them**: `POST /api/compare/record` has always returned an id and the browser has always thrown it away, which is why there was no way to tell a vote that reached the server from one that did not, and no way to delete the right row when someone cleared their history. **Two things only the browser knows now travel with the vote** — the per-model cost it computed from the token counts it saw, and the compare mode — because without them the server's copy cannot rebuild the Scoreboard and the browser's copy stays the only complete one, which is the defect. They ride in the same JSON column this endpoint **already** repurposed for `{"models": [...]}` when N>2, and it is now written **unconditionally**: the old `if len(models) > 2` meant a two-model vote read back in a different shape from a three-model one, and a mutation restoring that condition is one of the sixteen caught. **Every vote already in the table survives** — a row with no blob, a legacy models-only blob, a corrupt blob, and the genuinely different `{"left": ...}` shape the full comparison flow writes into the same column all still yield usable models; a history about to become the source of truth cannot drop the history it inherits. **Clear History clears both**, server rows first because the ids come from the loaded list, and one failed delete does not strand the rest. **And the Scoreboard says which copy it is showing** — synced, or this browser only because the server was unreachable, or synced with N votes that never got delivered. That last part is the row's real lesson: the numbers were never wrong, there were simply two of them and nothing said which you were looking at, and a silent fallback would have been the same defect with better plumbing. **The column is still called `blind_mapping` and still holds none of what its name says** — not made worse, not made better, filed as `P13-12`. 22 tests, 16 mutations, all caught. `check-unreachable` 98 → 96.
- [x] **H13** **The gallery can move images into albums and nothing offers it.** `POST /api/gallery/albums/{id}/add` and `/remove` (`routes/gallery/gallery_routes.py:2177,2195`) take a bulk `image_ids` list, ownership-scoped. `static/js/gallery.js` already creates albums, lists them, uploads *into* them and filters by them — **the only missing verb is the one a person reaches for first**. **Corrected 2026-08-31: the row cited the wrong selection state, and the right one makes this cheaper, not harder.** `_albumSelectMode` / `_albumSelected` (`:118-119`) is the **album** multi-select, and it exists to bulk-*delete albums* — its Set holds album ids, not image ids, so the endpoint could not have taken it. The handle that matters is the **image** bulk bar: `_selectMode` (`:2466`) with `_selectedIds()` (`:2471`), which already returns exactly the array of image ids `POST /api/gallery/albums/{id}/add` wants, and already drives a live action list — Favorite, Add tag…, Download, Delete (`:2632-2635`). **The work is one more entry in that array.** `grep -rni "add to album\|move to album" static/js/gallery.js` returns nothing. Same shape one level down: the toolbar offers "Clear AI tags" while `POST /api/gallery/clear-user-tags` and `/dedupe-tags` have no surface — and the first is documented in-code as *"use after a bug populated user-tags with AI-suggested values you never added"*. `GET /api/gallery/tags` and `/stats` are the tag filter and the library header, also unreachable. `Verify:` select images, add to album. — found during the discovery audit — agent:`audit:promises` — **done 2026-09-07. The row's correction was right and it made this one entry in an array, exactly as predicted.** `_selectedIds()` already returns the array `POST /api/gallery/albums/{id}/add` wants, and the bulk-actions menu already renders a list of items from a literal — so *Album…* joins Favorite, Add tag, Download and Delete. **The album picker is a second page of the same dropdown, not a second dropdown** (`Law 14`): menu entries can carry `keepOpen`, the click handler skips `close()` for those, and the action refills the same container. **Album names go through `textContent`** — user-supplied text rendered into a menu for the first time — while the icons beside them stay `innerHTML` because they are fixed SVG literals defined three lines above. **Remove is only offered inside an album**: it has no meaning in the all-photos view, the endpoint needs an album to remove *from*, and guessing one is worse than not offering the verb. It confirms and says *the photos stay in your library*, because removing from an album is not deleting; **adding does not confirm**, because it is undone by removing and a dialog on every action teaches people to dismiss dialogs. *New album…* reuses an existing name case-insensitively, matching what the drag-and-drop import path already does — two albums called "Holiday" is a worse outcome than reusing the one meant. The local `_items` copy is corrected after each call, or the grid keeps showing the photos under the old album until a reload and the move reads as a failure. **Not done, and named rather than dropped:** `clear-user-tags`, `dedupe-tags`, `tags` and `stats` are the row's second paragraph and are still unreachable — the first two are destructive library-wide maintenance that wants its own surface and its own confirms, not a fifth toolbar button beside *Clear AI tags*, and the row's `Verify` is albums. They stay in `check-unreachable`'s inventory. 11 tests, 9 mutations, all caught. **One more thing the checker taught, and the code changed rather than the checker:** the first version built both URLs as `` `.../albums/${id}/${verb}` ``, and `check-unreachable` normalises an interpolated segment to `*`, which does not match the literal `remove` in the route — so `/remove` was genuinely wired and still listed as callerless. Loosening the matcher would have let a `*` segment resolve routes nobody calls, which is the one failure an inventory must not have. Two literal URLs instead: a route this file really does call should be findable by grepping for it, which is what the checker is enforcing on everyone's behalf. Ceiling 100 → 98.
- [x] **H14** **The GPU process viewer and killer opens on right-click, and the tooltip tells you to left-click.** `_openProbePopup` (`static/js/cookbookServe.js:2845`) lists every process holding VRAM with per-PID **Kill (SIGTERM)** and **SIGKILL**. Its only call sites are `contextmenu` (`:3095`) and `dblclick` (`:3102`); plain click toggles GPU selection. The persistent tooltip at `:3000` reads **"click to view/kill"**, which is false. The only accurate hint is a 7-second toast that fires solely on a *manual* probe. For a local-model-serving product, "a zombie process is holding my VRAM" is the highest-frequency operational failure, and this is the tool that fixes it. `Verify:` the tooltip names the real gesture, and a visible affordance exists on busy GPUs. **One line for the tooltip.** — found during the discovery audit — agent:`audit:frontend` — **done 2026-09-07, and the TOOLTIP moved, not the gesture.** It now reads *"right-click or double-click to view/kill"*, naming both working gestures because right-click does not exist on a touch device. Binding the popup to the plain click instead would have been the obvious fix and the wrong one: plain click means *select this GPU*, and that popup carries per-PID **SIGTERM and SIGKILL** — putting the most destructive control in the panel one accidental click away, to save a reader four words. The comment above the handlers said "clicking" too and was wrong in the same way; a sentence beside the code is read as the code by everyone except the interpreter.
- [x] **H15** **Settings search indexes 13 panel labels and zero of the 96 controls.** `getSettingsPanelSearchText` (`static/js/settings/registry.js:162`) builds its haystack from `panel.label` plus `panel.keywords` and nothing else, and results are panels, never controls. So **31 of 32 labelled toggles in Appearance are unfindable by any word in their own label** — including *Incognito Mode*, *Deep Research*, *Shell* and *Web Search*. The sharpest case: **"Sensitive Blur"** (`static/index.html:2102`, *"blur emails, tokens, and secrets in AI output"*) is the app's **only** privacy control, is off by default, and lives under **Appearance** — there is no Privacy or Security panel among the 13. Typing *privacy*, *secret*, *redact* or *security* returns nothing. Someone about to screen-share cannot find the feature that hides their API keys. `Verify:` searching a control's own label finds it. — found during the discovery audit — agent:`audit:frontend` — **done 2026-09-07. The control text is HARVESTED from the markup, not listed.** `harvestSettingsControlText()` walks each `[data-settings-panel]` subtree for labels, headings, hints, placeholders and titles, and `searchSettingsPanels` folds that into the haystack — so *Incognito Mode*, *Deep Research*, *Shell* and *Web Search* are findable by their own labels. A hand-written keyword list for 96 controls would be a second copy of the labels that starts drifting the day somebody renames one, which is a failure this project has already spent several rows on. Harvested **lazily and re-harvested when a panel gains text**, because panel bodies are filled in on first open and an index built at startup would capture whatever existed then and silently miss the rest — a subtler version of the bug being fixed. **The sharpest case needed one more thing.** Harvesting makes *Sensitive Blur* findable by its label and by "secrets"; it cannot make it findable by **privacy**, **security** or **redact**, because none of those words is anywhere in the markup — and those are what someone about to share their screen actually types. They are panel keywords now, with the reason on the line. *(One test had to be rewritten during mutation: the "before" case used "sensitive blur", which the new keywords resolve on their own — so the harvest could have been deleted with the test still green. It uses `incognito` and `deep research`, which appear in no keyword list at all.)*
- [x] **H16** **Three shipped capabilities have no switch a person can reach.** **(a)** `agent_verifier_subagent` (`src/agent_loop.py:5797`) gates a fresh-context verifier that independently checks effectful turns before accepting "done" — the key is **not in `DEFAULT_SETTINGS`**, so the settings route skips it and `manage_settings` refuses it; the only writer is hand-editing JSON. **(b)** **FOLDED INTO `P2-21` (2026-08-31)** — same literal, same flag, same flip, and `P2-21` already carries the decision, the four endpoint line numbers, the two open GETs and `P11-10`'s amendment from optional to required. Do the work there; this paragraph stays only so the audit's inventory reads complete. The built-in tool-prompt override editor is complete — four live routes (`routes/skills_routes.py:1250-1337`) writing `builtin_tool_overrides`, substituted into the system prompt for any of **60** `TOOL_SECTIONS` entries — and switched off by a literal, `static/js/skills.js:636` `const showBuiltin = false;`, over a list nothing populates. An operator can already rewrite how the assistant is told to use any built-in tool, today, with curl. **(c)** `tool_path_extra_roots` (`src/settings.py:156`) is the switch that lets the agent's file tools reach outside `data/`; six occurrences in the whole tree, no UI, refused by `manage_settings`. Plus a nightly skill-audit loop with three undeclared knobs (`app.py:1235`). `Verify:` each has a control, or is documented as deliberately expert-only. — found during the discovery audit — agent:`audit:config` — **done 2026-09-07, `(b)` excepted — it belongs to `P2-21` and is not touched here.** **The shape underneath is worth more than the three items: `DEFAULT_SETTINGS` is an allowlist, not a list of defaults.** `POST /api/auth/settings` iterates `for key in DEFAULT_SETTINGS`, so a key absent from that dict is **silently dropped from every save** and `manage_settings` refuses it. Four keys were read by live code and absent from it — `agent_verifier_subagent` plus the three knobs of the nightly skill audit's `while True` loop — so the only writer was hand-editing `data/settings.json`, and a save through the UI dropped them **without saying so**. Each is now declared with the **exact fallback its reader already used**, so declaring them changes nothing today; a test asserts both sides still agree, because they live in different files and nothing joins them. **The two numbers feed a loop and are clamped at the door**: an hour of 25 makes `next_daily_run` wait for a time that never comes, and a batch of 0 audits nothing every night forever. The UI clamps to the same range and writes the clamped value back, so the number on screen is the number that runs, and it reads a stored `false` as a value rather than as absence — a truthiness test there would switch the audit back on every time the panel opened. **The verifier's switch explains why it is off**, because "off by default" with no reason gets flipped by whoever is feeling optimistic, and the reason is specific: a weak local model cannot judge its own work from the action snapshot and will reject turns that were fine. **`(c)` `tool_path_extra_roots` deliberately gets no control, which is the row's own second option.** It widens where `read_file`/`write_file` may reach and `_resolve_tool_path` is a `FORBIDDEN.md` Part 2 control. The sensitive-basename block holds whatever roots are listed, so a UI would not breach the boundary — but it would put *point the agent at my home directory* one click away, and that is a different thing from being able to do it deliberately in a JSON file. The reason is written where the setting is declared, and a test fails if a control ever appears without someone arguing for it first. 15 tests, 10 mutations, 9 caught and one deliberate no-op.
- [x] **H17** **Two security controls with the wrong door.** **(a)** The admin UI calls `POST /api/auth/signup-toggle` (`static/js/admin.js:340`), whose own docstring says *"DEPRECATED: this endpoint uses toggle semantics which can lead to unsafe state changes. Use PUT /open-signup instead."* The safe idempotent replacement (`routes/auth_routes.py:652`) has **no caller anywhere**, so a double-submit or two admins clicking flips open registration back **on**. **(b)** A task's webhook token is rendered in full, readonly, with a Copy button and the label "No auth needed" (`static/js/tasks.js:1489`); `POST /api/tasks/{id}/webhook-regenerate` (`routes/task/task_routes.py:1110`) rotates it and nothing calls it — **if that URL leaks there is no revocation path in the product**. One line each. `Verify:` the toggle is idempotent, and a leaked webhook token can be rotated. — found during the discovery audit — agent:`audit:backend` — **done 2026-09-07, both halves.** **(a)** The admin switch now sends `PUT /api/auth/open-signup` with the state the switch is showing. The deprecated `POST /signup-toggle` is left mounted — not calling it and removing it are different decisions, and something outside this repository may hold that URL. The toggle-semantics defect was real: two admins clicking, or one double-submit, flipped open registration back **on** while both switches read off. The switch also reverts on a refused request now, because a security control that reports a change it did not make is worse than one that fails loudly. **(b)** The task webhook URL carries its own bearer token in the path, was rendered in full with a Copy button, and `POST /api/tasks/{id}/webhook-regenerate` — which rotates it — had no caller anywhere. **A secret you can copy but cannot rotate is a secret with no lifecycle**: if that URL leaked in a screenshot, a CI log or a support ticket, there was no revocation path in the product at all. There is a **Rotate** button now, confirmed because it breaks anything already using the old URL, and a failed rotation says so explicitly — after a failure the one thing you need to know is whether the token you were trying to revoke is still live. The label *"No auth needed"* was accurate about the receiver and read as *this is not a secret*; it says *"anyone holding it can run the task — rotate if it leaks"*.
- [x] **H18** **Twelve settings the model can change and a person cannot.** Each has zero references under `static/` and is settable by `manage_settings` under its exact key: `agent_email_confirm`, `agent_input_token_budget`, `agent_input_token_hard_max`, `agent_stream_timeout_seconds`, `document_writing_style`, `research_planning_timeout_seconds`, `research_query_timeout_seconds`, `search_safesearch`, `task_concurrency_cap`, `task_endpoint_id`, `task_model`, `teacher_tier2_enabled`. **`agent_email_confirm` is the one that matters** — it is the gate in `H01`, and the model can turn it off while the person it protects has no control at all. `search_safesearch` carries 17 lines of documentation about three levels across six providers and has no UI. `Verify:` a person can reach every setting the model can. — found during the discovery audit — agent:`audit:config` — **PARTIAL 2026-09-07, and the row's own "the one that matters" turned out to matter more than it says.** `agent_email_confirm` now has a control (Settings → Email), and `B42` took it away from the agent — the row reads this as a missing control, but the agent *having* one is the larger half: it could remove the gate that exists to require a person's approval, and did so in a measurement. `agent_stream_timeout_seconds` and `task_concurrency_cap` were reached along the way by `H08` and `H06` — both now resolve correctly, though neither has a panel control. **Completed 2026-09-07: eight more controls, and two deliberate exceptions.** `document_writing_style` sits beside the email style card that says *keep this email-specific* — which is exactly why a second key exists, greetings and sign-offs being wrong in a report — and a test asserts the new box does not write the email key. `search_safesearch` gets a three-level picker, and the panel says **which providers it reaches**: the seventeen lines of documentation included two exceptions nobody could have known (Tavily has no such knob and filters at index time; a custom backend keeps its own behaviour), and those are the sentences worth surfacing. `research_planning_timeout_seconds` and `research_query_timeout_seconds` sit beside the extraction timeout with the same 15..3600 clamp. `task_endpoint_id`/`task_model` are the third endpoint+model pair in this panel and the one that had none; empty stays selectable, because empty is the shipped state. **The token budget is the interesting one.** `agent_input_token_budget: 6000` is a **sentinel** meaning *scale to the model's window*, not a cap of 6000 — so a plain number box would let someone type 6000 meaning a cap and silently get auto. It is a mode picker (*scale* / *fixed* / *send everything*), 0 is reachable as a real documented value rather than a number to guess at, and typing 6000 as a fixed budget is **refused with the setting's own advice** (use 5999). A test pins the sentinel against `context_budget.DEFAULT_BUDGET`, because the two live in different files with nothing joining them. **Two deliberately keep no control, both recorded rather than skipped:** `teacher_tier2_enabled` sits inside a card `index.html` says is *"hidden as part of the 2.0 harden-the-core pass… Re-add this card once the core experience is faster"* — a documented decision, and adding a switch for one field of a parked feature would re-open it sideways; and `agent_stream_timeout_seconds`/`task_concurrency_cap` were fixed at the **resolution** layer by `H08` and `H06` without gaining a panel. A test asserts exactly which three are left, so the arithmetic is visible rather than re-derived. 19 tests, 10 mutations, all caught.
- [x] **H19** **Three diagnostics whose only door is an unlisted slash command.** `/probe` (`routes/model_routes.py:1841`) probes individual *models* with a real completion — the admin panel shows endpoint up/down but never per-model liveness, so this is the only way to learn an endpoint is up while half its models 404. `/stats` (`routes/diagnostics_routes.py:56`) is sessions/messages/memories/documents/uploads counts. `/sh` is the only general-purpose command runner a person can reach. All three are `hidden: true`, which filters them from **both** `/help` and the autocomplete. Also here: **`/shortcuts` is a stale hardcoded duplicate** showing 7 rows against the runtime's 20 — it **invents two actions that do not exist** (`admin_panel`, `star_session`), omits 15 real ones, and prints the wrong combo for `toggle_sidebar`, which itself disagrees between `keyboard-shortcuts.js:10` (`ctrl+alt+b`) and `settings.js:1655` (`ctrl+b`). And `_cmdToggleRag` is a handler with no registry entry — `/toggle rag` does not exist. `Verify:` a diagnostics surface, and `/shortcuts` generated from the registry or deleted. — found during the discovery audit — agent:`audit:frontend` — **PARTIAL 2026-09-07: the `/shortcuts` half is done, the three hidden diagnostics are not.** **There were three copies of the keybind table and they disagreed.** `keyboard-shortcuts.js` is the one that RUNS; `settings.js` kept a second saying `toggle_sidebar: 'ctrl+b'` where the dispatcher matches `ctrl+alt+b`; and `/shortcuts` kept a third that was the worst of them — seven rows against twenty-one, **two invented actions bound to nothing anywhere** (`star_session`, `admin_panel`), fourteen real ones omitted, and the wrong combo for the one they all disagreed about. So a person could read the wrong key in two places and be told about keys that do nothing in one of them. `KEYBIND_DEFAULTS` and `KEYBIND_LABELS` are exported from the module that runs and imported by the other two — `Law 14`: not a fourth table, the first one becoming the only one. `/shortcuts` is generated, and **skips actions with an empty combo** rather than printing a shortcut with no key, which is how a help screen starts lying again. **Still open: `/probe`, `/stats` and `/sh` are `hidden: true`, which filters them from both `/help` and the autocomplete**, and `_cmdToggleRag` is still a handler with no registry entry. Those are a diagnostics surface, not a table, and the row stays open for them. **The diagnostics half landed too.** `hidden: true` filters a command from **both** `/help` and the autocomplete, so `/probe`, `/stats` and `/sh` had no door at all — and they are the three worth having: `/probe` is the only way to learn an endpoint is up while half its models 404, `/stats` is the database counts, and `/sh` is the only general-purpose command runner a person can reach. They are un-hidden into a **`Diagnostics` category**, because dropping three commands into `Utility` beside fifteen others buries them again. **`/sh` is safe to surface**: `POST /api/shell/exec` calls `_require_admin` server-side, so hiding it was obscurity rather than protection, and a non-admin who types it gets a 403 either way. `/shortcuts` is un-hidden as well now that it tells the truth. **And `/toggle rag` exists.** The row says `_cmdToggleRag` is a handler with no registry entry, which is true — but it **could not have worked if it had one**: `_quickToggle`/`_applyToggle` look the name up in a `toggleMap` that had no `rag` key, so `getElementById(undefined)` was null and the function returned without doing anything or saying so. **There were FOUR copies of that map** — one complete in `chatStream.js`, three in `slashCommands.js` missing `rag` and `incognito` — which is the same disease as the keybind table, in the same file, found while fixing it. One `TOGGLE_CHECKBOX_IDS` now, exported from the module that owns the toggles. 20 tests, 16 mutations, all caught. **And the checkers caught the wiring mistake this created**: the new import used a bare `./chatStream.js` while every other importer uses `?v=20260829trustladder1`, which loads a **second copy of the module with its own state** — for a module that owns toggle state, exactly the bug the import was meant to fix. `check-specifiers.py --max 0` failed on it before the suite ran.
- [x] **H20** **Document-editor Find is Ctrl+F only, and documented nowhere.** `_openFindBar` (`static/js/document.js:5937`) has one caller — the Ctrl+F handler at `:6033`. The bar has match counts, prev/next and highlight rectangles (`:4965`). `doc-find` appears **zero times** in `index.html`; there is no toolbar button, and it is not in the keybind registry, so neither the Shortcuts panel nor `/shortcuts` mentions it. *(The `/chats export` half of this row moved to `P7-11a` on 2026-08-31 — it is the same defect as the session export having no button, and it should be fixed in the same change rather than twice.)* `Verify:` a find button in the doc toolbar, and Find appears in the keybind registry so the Shortcuts panel and `/shortcuts` both name it. — found during the discovery audit — agent:`audit:frontend` — **done 2026-09-07.** A **Find button** in the document header, beside Undo, reaching the same `_openFindBar()` the key does — two entry points that drift are how this row happens twice. And `doc_find` is in the keybind registry, so the Shortcuts panel and `/shortcuts` both name a find bar that had no button, no registry entry and no mention anywhere. **The editor reads the registry rather than hardcoding Ctrl+F**, which matters more than it looks: a registry entry the editor ignored would be worse than no entry, because the panel would offer to change a key and nothing would change. **The global dispatcher deliberately does not bind it** — it is an explicit chain of `_matchesCombo` calls, one per action, so an entry can exist to be *named* without capturing anything, and Ctrl+F outside a document stays the browser's. `KEYBIND_LOCAL_ONLY` says that out loud rather than leaving it to be inferred from an absence. A `readOnly: true` flag on the panel category was written and then removed: the renderer implements no such flag, so it would have been a lie in the data that nothing enforced — and rebinding genuinely works now anyway.
- [ ] **H21** **Dead weight the sweep also found, for deletion rather than wiring.** **⚠ Corrected 2026-08-31 — do not run this row as it was written; two of its items delete live code.** **(i) The archive block is not all dead.** `_checkPeekCleanup` (`static/js/sessions.js:2943`) sits inside the 282-line range this row declares reachable only from `openArchive`, and it has a caller at **`:1849`, outside that range**. Deleting the block by line span breaks a live path. The two entry points really do have zero callers; the *span* is the unsafe part, and any deletion here has to be per-function, not per-region. **(ii) The class-name sweep is `P3-03`, and `P3-03` is blocked precisely so this cannot run.** *"516 of 3,313 class names appear nowhere else"* is the same measurement, and `P3-03`'s second blocker says a sweep run today *"deletes exactly the CSS `P2-20` needs"* — 16 `admin-rag-*` rules that are dead **only** because `P2-20`'s markup has not landed. That failure has already been demonstrated in reverse: `.rag-upload-zone` was an orphan until `P2-23` landed its markup and is live again now. **The class-name half of this row is struck and belongs to `P3-03`; do not act on it here.** What survives and is safe to delete on its own evidence: `GET /backgrounds` serving a file that does not exist, `RESEARCH_LLM_ENDPOINT` read by no Python, the `services/research/` dead fork, the three superseded note endpoints, the two superseded compare endpoints, and the `.search-fallback-chain` cluster. Take those; leave the rest to their owning rows. A second complete session-archive modal nothing opens — `openArchive`/`closeArchive` (`static/js/sessions.js:3553,3618`), zero callers, **14 functions and 282 lines reachable only from it**, plus 5 dead `.archive-col-*` CSS rules; the `reminders.js` disease at 2.5× the size. `GET /backgrounds` (`app.py:939`) serves `static/backgrounds.html`, **which does not exist**, unauthenticated. `RESEARCH_LLM_ENDPOINT` is in `.env.example` and forwarded by all three compose files and read by **no Python at all**. `services/research/` is a dead fork of the live handler with a different `research_max_tokens` default. Three note endpoints superseded by `PUT /api/notes/{id}`, two compare endpoints superseded by the client. A `.search-fallback-chain` CSS cluster for a feature never built. **516 of 3,313 class names appear nowhere else** (a floor, not a ceiling — the method counts a bare token match as used). `Verify:` deleted, with the count on the row. — found during the discovery audit — agent:`audit:frontend` — **⚠ THIRD CORRECTION 2026-09-07, and one more item struck. Verified, not acted on: `Law 1` says we add and never subtract, and this row has now been wrong about what is safe to delete three times.** Every surviving claim was re-measured against the tree today with `check-unreachable`'s own route walk. **Holds:** `GET /backgrounds` — no frontend caller, and `static/backgrounds.html` genuinely does not exist, so the route serves a 404 to nobody, unauthenticated. `RESEARCH_LLM_ENDPOINT` — present in `.env.example` and all three compose files, **zero Python readers**, so an operator who sets it gets nothing and is told nothing. The three note endpoints (`/pin`, `/archive`, `/items/{index}/toggle`) and the two compare endpoints (`/start`, `/{id}/vote`) — no frontend caller, though the checker reports rather than accuses and the agent's `app_api` tool is a plausible caller for the note ones. `.search-fallback-chain` — one rule in `style.css`. **STRUCK: `services/research/` is not a dead fork that can be deleted.** `tests/test_services_research_low_quality_sources.py` loads it by file path and pins a behaviour, and its docstring records that *"the services/research copy diverged and had no gate"* — someone has already **fixed** this fork rather than deleting it, and deleting the directory deletes that test's subject. That is the third item on this row that would have removed something live, after the archive span and the class-name sweep. **The pattern is the finding**: a deletion row written from a sweep goes stale the moment anyone works on what it names, and this one has been re-checked three times and been wrong three times. Anything left here should be re-measured on the day it is done, per item, never per region. **Two of the survivors are not really deletions and could be done without touching `Law 1`:** `RESEARCH_LLM_ENDPOINT` is a *false promise in documentation* — the fix is either to read it or to say it is unread — and `GET /backgrounds` returns an error today, so making it honest is a change in what it says, not in what it does. — verification agent:`H21`

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
- [ ] **B13** **One queued message, two vocabularies, both on screen at once.** The docked queue panel (`queuePanel.js` `statusLabel`) renders the shipped six-value status set as *Waiting · Sending · Sent · Failed · Skipped · Stopped*; the Tasks activity view (`static/js/tasks.js:2958`), which renders **the same row objects** from the same `getQueueActivityEntries` source, says *Queued · Running*. Open the queue panel with the sidebar Activity view showing and one message is "Waiting" in one place and "Queued" in the other. Neither word is wrong; having both is. The status *values* are already one vocabulary — this is only the labels — so the fix is to pick one wording and give it a single home, not to touch anything persisted. Prefer the panel's wording: *Waiting/Sending* describes a message, *Queued/Running* describes a job, and the composer's queue holds messages. `Verify:` one queued item, both surfaces visible, one word. — found during P6 reuse wave — agent:`integrator`
- [ ] **B14** **The steer bar is still offered on a research turn, which cannot take a steer.** `P6-18` closed the chat-mode case by asking the composer's own mode getter, but research is a *fourth* non-steerable exit (`routes/chat_routes.py` returns from inside the `effective_do_research` block before the three-way stream choice), and the client cannot see it — a research turn is `mode: 'agent'` as far as the composer is concerned. Nothing is lost: the server refuses, the words fall back to the queue, and the sentence the user reads is accurate for both causes. But a control that can only decline is still on screen, which is the `Law 15` half of the defect `P6-18` fixed everywhere else. The honest fix is a per-run signal rather than a per-build one — the capability probe fires once per page load and cannot answer a per-run question, so either the stream announces its own steerability in an early event, or the composer learns that research is in play. `Verify:` start a research turn and no steer bar appears. — found during P6-18 — agent:`impl:steer-route`
- [ ] **B15** **Two themes put every string in the app under WCAG AA against their own panel.** Measured 2026-08-29 across all sixteen palettes in `static/js/theme.js`: `cute` renders `--fg` on `--panel` at **3.44:1** and `retrowave` at **4.15:1**, against a 4.5:1 floor for body text. Every other theme clears it with room — the next lowest is `light` at 7.13. This is not about any one component; it is the palette, so it applies to every label, every menu item and every message in the product on those two themes. **Themes are protected territory and this row does not authorise a repaint** — it authorises the measurement being on the record and a decision being made: lift `--fg`, darken `--panel`, or accept the two as decorative and say so somewhere a person will find it. `Verify:` the sixteen palettes are measured in a test, and either every one clears 4.5:1 or the exceptions are named on purpose. — found during P7-06 — agent:`refute:surfaces`
- [ ] **B16** **FOLDED INTO `B15` (2026-08-31) — settle both in one decision; do not work this row alone.** Same subject, same evidence, same remedy: two palette-contrast measurements against the same sixteen themes, both landing on *lift it, or write down that it is decorative*. Splitting them invites the two halves to be settled differently on the same screen. `B15` is the host because it covers body text, which is the harder floor. **The accent-coloured rule and mark fall below the 3:1 graphic floor on three light themes.** `--red` over `--panel` measures **2.24 on `paper`**, **2.56 on `cute`** and **3.03 on `light`**; WCAG asks 3:1 of a graphic that carries meaning. `P7-06`'s band ladder does not depend on it — after that row the distinction is carried by type size, weight, rule *width* and mark shape, all of which survive greyscale, and the colour is redundant reinforcement by design. So this is not a `Law 15` failure and it is not urgent. It is a real number that should either clear the floor or be documented as decorative, and the attempt to lift it by mixing `--fg` into the accent was abandoned because it could not clear 3:1 on `cute` at any ratio without destroying the hue. `Verify:` (on `B15`) every accent-on-panel graphic that carries meaning clears 3:1, or is documented as redundant. — found during P7-06 — agent:`refute:surfaces`
- [ ] **B17** **A 1,984-character tool argument kills the whole agent run, at every rung, including the default.** `_action_from_content` (`src/tool_capabilities.py:429`) wraps `json.loads` in `except (TypeError, ValueError)`. **`RecursionError` is neither**, so a deeply nested payload — `"["*992 + "]"*992` is enough — escapes into the SSE generator and the stream dies. Reproduced at all three rungs. `_effect_fields`'s `except Exception` is *not* the escape route and catches it correctly; the run then dies at the first unguarded `capabilities_for_action` caller instead — `decision_for` on the strict rungs, `observe_tool_result` → `tool_result_should_arm_gate` on the default. **Pre-existing**: the narrow `except` is at `HEAD` before `P7-03`, so this is `P7-06`-era or older, not the ladder's. The threshold is stack-depth dependent, not a constant — 1,940 characters survived and 1,960 died in a bare harness, and behind uvicorn the ambient stack is deeper, so the real threshold is lower. The model writes this content, so a model that emits one malformed argument takes the conversation down with it. `Verify:` that payload as a tool argument produces a refused tool call, not a dead stream. — found during P7-03 — agent:`refute:gate`
- [ ] **B18** **Running `tests/test_agent_loop.py` first breaks about 51 tests in six other files.** Confirmed with every uncommitted edit reverted, so it is neither this run's nor last's: `test_external_context_tool_gate.py` (32), `test_prompt_injection_audit.py` (9), `test_tool_path_confinement.py` (3), `test_tool_output_prompt_injection.py` (3), `test_tool_approval_task_scope.py` (2), `test_tool_approvals.py` (2). The natural full-suite order happens not to trigger it, which is why CI is green and why this will surface as a mystery the first time someone runs a subset or a shard. The mechanism is the one already documented on `tests/test_trust_rung_gate.py`'s harness: files in this suite stub entries in `sys.modules`, so a later `import` can hand back a different module object than the running code closed over — and `__module__` does not help, because it is a *name*. `Verify:` `pytest tests/test_agent_loop.py tests/test_external_context_tool_gate.py` is green. — found during P7-03 — agent:`impl:gate-tests`
- [ ] **B19** **The strict rungs gate on the wrong effect set, and it is the reason people will turn them off.** `ask_every_time` and `allow_listed` both reuse `POST_EXTERNAL_BLOCKED_EFFECTS`, which contains `READ_PRIVATE` because an *already-tainted* run must not exfiltrate. A **clean** run on a strict rung is a different threat model, and reusing one frozenset for both conflates them: 72 of 81 known tools are gated, **21 of them solely by `read_private`** — `read_email`, `search_emails`, `list_sessions`, `search_chats`, `manage_calendar`, `manage_documents`, `list_models`, `vault_search` among them. The agent needs a confirmation to read back a note it wrote in an earlier chat. `P7-04` fixed the *copy* so it no longer promises four write verbs it does not honour, and bound that copy to the set with a test in both directions — so this row is the honest follow-up, not a surprise. Give the rungs their own writes/executes/sends/deletes set. **Two corrections to the evidence, both verified:** `manage_notes` and `manage_memory` also carry `write_private` and would stay gated anyway, and `read_file`/`glob`/`grep`/`ls` are already ungated — workspace reads are fine today, private ones are what hurt. `Verify:` on *Ask every time* a clean run reads its own memory without a prompt and still stops before writing a file. — found during P7-04 — agent:`impl:trust-ladder-ui`
- [ ] **B20** **`P6-08`'s env layer is unreachable — and `H06` proves it dies earlier and harder than this row says.** **Half-closed 2026-09-07: `H06` shipped, the concurrency cap now resolves correctly on a fresh install and after a save, and `settings.setting_is_explicit` is the general tool this row was missing. What is still open is the audit, not the mechanism** — every key that has both a settings layer and an env layer needs checking with that tool, and `H07` found ten more of them in `email_helpers` alone. Nothing measures it yet; a ninth checker that walks the pairs is the obvious shape, and `P3-23`'s 128-read/54-declared inventory is where the list comes from. **Corrected 2026-08-31. The mechanism named below is real but is not the cause, and a fix aimed at it will not work.** `H06` owns the defect: `resolve_task_concurrency_cap` reads the instance layer as `get_setting(KEY, None)`, `get_setting` merges `DEFAULT_SETTINGS` on every read, so the env leg is unreachable **at import, on a fresh install, with no settings file at all** — not after the first save. **Do the fix on `H06`.** What survives here, and is why the row stays open, is the *general* hazard it discovered — first-save materialisation writing every default into `data/settings.json`, so an env var that ranks below an instance setting is silently overridden for every key that has both. That is a whole-config property, it outlives the concurrency cap, and nothing checks it. **Read the original text below as the second-order problem, not the first.** ORIGINAL: `set_settings` writes back `DEFAULT_SETTINGS` merged with the saved file, so the first save materialises **every** key into `data/settings.json` — and the resolver ranks the instance setting above the env var, so `PANTHEON_TASK_CONCURRENCY_CAP` can never win again. For a concurrency cap that is a nuisance. The row exists because the same shape would be worse elsewhere: an operator's env-var hardening silently undone the first time someone opens Settings. `trust_rung` deliberately has **no** env layer for exactly this reason — that decision is recorded here so nobody adds one thinking it will hold. `Verify:` an env var that ranks above a settings key still wins after a settings save, or the layering is documented as instance-setting-only on every key that has both. — found during P7-03 — agent:`impl:rung-setting`
- [ ] **B21** **The three theme writers disagree about what a theme is.** A theme's advanced keys are mirrored in three places and the three have drifted: `ADV_KEYS` in `static/js/theme.js` has **14** entries, `login.html`'s `ADV` has **13** (missing `brandMixTo`), and `index.html`'s first-paint `advMap` has **17**. `P1-09`'s `CI:` line already warns that `ADV_KEYS` and `computeAdvancedDefaults()` must move in lockstep or all sixteen themes break — this is the same hazard one level up, across files, and nothing checks it. Four of `advMap`'s extras (`accentPrimary`, `accentError`, `sectionAccent`, `toggleBg`) are written at first paint and then never updated or cleared by `applyColors()`, which is `P1-02`'s defect generalised. **Related, and one line:** `applyColors` calls `_updateFavicon(colors.red || '#e06c75')` under a comment reading *"match theme accent color"* — true until `P1-01` made accent separately settable, so the first theme to carry an `accent:` key gets a red favicon and an accent UI. `Verify:` a test asserts the three key sets agree, and adding a key to one of them fails until it is added to all. — found during P1-01 — agent:`impl:accent-writer` **PARTLY CLOSED 2026-08-30, and it was three sets undercounted — there are six.** `index.html` also carries `id="adv-…"` inputs (14) and `data-reset-adv` buttons (14), both reached by `getElementById('adv-' + key)` from the `ADV_KEYS` loop, and `theme.js`'s `_THEME_ZONE_MAP` carried `adv-` entries for four keys with no picker row. All six front-end sets are now **14 = 14 = 14 = 14 = 14 = 14** and a test fails when any one of them moves alone. The favicon line is settled too: `_updateFavicon` follows the accent rather than the red, a no-op on all sixteen shipped themes and correct for the first one to carry an `accent:` key. **What is left is `src/`, which is a seventh and eighth set.** `src/ai_interaction.py:767` and `src/tool_schemas.py:1574` each carry a 16-key `adv_keys`, plus the JSON schema at `tool_schemas.py:495-506` — all three still accept the four keys `P1-02` retired and none knows `brandMixTo` or `hamburgerColor`. So `create_theme` accepts a **dead parameter**: stored, and written by nobody. Remove the four from both literals, the schema block and the error string at `ai_interaction.py:754`; add the two real ones to all four places. The test bounds the gap in both directions so this can be closed later without it objecting.
- [ ] **B22** **The semantic colour tokens are not theme-scoped, so they are dark-tuned everywhere.** `--green`, `--warn` and the seven `--color-*` tokens are static `:root` literals in `static/style.css`; `theme.js` sets only `--bg --fg --panel --border --red --accent`, the ten `--hl-*` and `ADV_KEYS`. So a *success* green is the same hex on `terminal` as on `paper`, and on the four light palettes it is weak — `--green` on `paper` measures **1.37:1**. This became load-bearing on 2026-08-30: `P1-01` moved twelve mislabelled accent sites onto `--color-success` / `--color-warning` / `--color-accent` / `--green`, which is right on the twelve dark themes and inherits this weakness on the four light ones. Those twelve are not the problem — they join **100+ existing sites** with the same shortfall. **Paired with `P1-06` on 2026-08-31, and this row is what unblocked it.** `P1-06` owns loose colour and was blocked for want of a scope; the numbers here *are* that scope, so the two are one job — the measurement half (this row) and the token-move half (`P1-06`). Work them together and close them together; neither is meaningful alone. `Verify:` a semantic token clears its floor on all sixteen palettes, or the exceptions are named. — found during P1-01 — agent:`impl:accent-css`
- [ ] **B23** **Two link idioms now disagree, and `P1-01` is why.** A link in rendered body text (`.task-log-row-body a`, `.doc-email-richbody a`) is `--color-accent`, because those were semantic sites reclassified away from the accent. A link inside `details` is bare `var(--accent)` and now resolves to the theme's red for the first time. Both are correct on their own row and they look different on the same screen. Neither is wrong enough to have blocked `P1-01` — but a product should not have two link colours, and the cheapest moment to settle it is before more rows lean on either. `Verify:` one link colour, named once. — found during P1-01 — agent:`impl:accent-css`
- [x] **B24** **The frosted-glass toggle did not survive an export/import round trip.** Found 2026-08-30, from the owner handing over a real exported theme mid-run with the note that the theme editor *"is genuinely awesome… it is also the location where you enable the glass panels too"*. A theme stores **seven** options — `saveCustomTheme` and `save` both persist `font`, `density`, `bgPattern`, `bgEffectColor`, `bgEffectIntensity`, `bgEffectSize` and `frosted`. **The exporter wrote four.** So turning the glass on, exporting, and importing on another machine silently gave you a theme with the glass off, and a tuned background pattern came back at its defaults. The importer had the identical gap, so even a hand-edited file could not have carried them. **Nothing failed loudly** — the file it produced imported cleanly and simply produced a different theme, which is why it survived every previous pass over this module. — **done:** all four lists carry all seven, import reads the three additions with `!== undefined` so an older export still works and a deliberate `frosted: false` is obeyed rather than ignored, and the applied state is set before `applyBgPattern` because the canvas animators read intensity and size when they start. `tests/test_theme_export_round_trip_js.py` holds the four lists equal **using the owner's own exported theme as its fixture**, so the format under test is the one the product emits. The editor is now named in `FORBIDDEN.md` Part 1 with the owner's words. *(One of my own edits called `applyFrosted`, which does not exist — the function is `applyFrostedGlass`. `node --check` passed it, because it parses and does not resolve names. A test now checks that every function the importer calls is one this module defines.)* — found during P1 wave 2 — agent:`orchestrator`
- [ ] **B25** **`CHANGELOG.md` says the AGPL §13 source link shipped. It did not.** `CHANGELOG.md:37` lists under **#### Added**: *"Source link in the UI footer, per AGPL-3.0 §13."* There is no such link — `static/index.html` contains no footer source link, no repo href, nothing. `P0-17`, the row that owns it, is still `[ ]` and describes itself as *"the one licence obligation that is genuinely required and genuinely missing."* So the tracker and the changelog disagree, and **the changelog is the one a stranger reads**. This is worse than an ordinary stale entry for two reasons: a changelog is a public statement of compliance, and the specific claim is about the licence term that compels source availability. Anyone auditing this fork's AGPL conformance would read line 37 and stop looking. `Verify:` either the link exists on the logged-in shell and the login page (which closes `P0-17`), or line 37 is removed until it does — and nothing else in that file claims a capability no code provides. — found during the tracker reconciliation — agent:`orchestrator`
- [x] **B26** **The sidebar anti-flash guard was renamed on one side only, so it does nothing.** The pre-paint inline script in `static/index.html:140` and `static/js/sidebar-layout.js:41` set `pan-sidebar-mini`, `pan-sidebar-off` and `pan-mobile-startup-sidebar-hidden` on `<html>`. `static/style.css` still selects **`html.ody-sidebar-mini`** (`:776,779`), **`html.ody-sidebar-off`** (`:780,789,5275`) and **`html.ody-mobile-startup-sidebar-hidden`** (`:5276`) — **10 occurrences across 3 class names, none of which anything sets any more.** The whole point of that inline script is to apply the collapsed state *before first paint*; with the rules orphaned, every cold load renders the full sidebar and then snaps it away — which is precisely the flash the guard was written to prevent, on the two layouts that opt out of the sidebar. This is `P0-04`'s rename finishing in the JS and stopping at the stylesheet, and it is invisible to `check-wiring.py`, which counts element lookups and not selector agreement. **Two things in `style.css` are *not* this bug and must not be swept with it:** `ody-pulse` and `ody-breathe` are `@keyframes` **defined and consumed inside the same file** (`:7082,7086,7099,7108`) — misnamed, self-consistent, live. Renaming those is `P0-31` cosmetics; renaming these three is a fix. `Verify:` a cold load in mini and in off mode paints the collapsed sidebar on the first frame, and no `html.ody-` selector remains that nothing sets. — found during the tracker reconciliation — agent:`orchestrator` — **done 2026-09-07: sixteen selectors, not ten.** The row counted `static/style.css` and stopped there; `static/index.html`'s own inline `<style>` (`:263-274`) carries six more readers of the same three classes, inside the same file whose inline *script* the row correctly identified as a writer. So the file that was cited as evidence for the writer half was also holding a third of the reader half. All sixteen renamed `ody-` → `pan-`; the diff is the three class names and nothing else, verified with `--word-diff`. **A rename was the right shape and a migration was not:** the class is recomputed from `localStorage['pantheon-sidebar-mode']` on every load and is never itself stored, so no saved value carries the old spelling. `ody-pulse` and `ody-breathe` left alone exactly as the row instructs. Guarded by `tests/test_root_class_wiring.py`, which joins the two sides in **both** directions — a root class CSS reads that nothing writes, and one code writes that no rule reads — because a one-directional check would have passed on this tree had the sweep gone the other way. Five mutations, five caught.
- [x] **B27** **`scripts/fetch-pyodide.py` wrote its own manifest with platform-dependent newlines.** `pathlib.write_text` opens in text mode, which translates every `\n` to `os.linesep` — so the same script run on Linux and on Windows produced `MANIFEST.json` files 16 bytes apart. **It passed anyway, and that is the finding:** `.gitattributes` normalises text in the index, so the two trees hashed identically and the verification I trust for every cross-machine run said everything matched. Git was covering for the script. This is the one file in the tree whose entire job is recording exact bytes. — found during `P16-07`, immediately after it shipped — **fixed:** explicit `newline="\n"`, plus a test asserting no CRLF in the file and that `write_text` is not used for it. — agent: `opus-5`
- [x] **B28** **`events` pruning never ran on a freshly booted machine.** `_last_prune` was initialised to `0.0` and compared against `time.monotonic()`, which on Linux counts from **boot** — so `now - 0.0 < 86400` was True for the first day of a host's uptime and the gate returned early every time, leaving `_last_prune` at `0.0`. A container starting on a freshly booted host would never prune, silently, and whether it pruned at all depended on how long the machine happened to have been up. — found during `P14-02`, reviewing `P14-01` — **fixed:** the sentinel is `None`, meaning *never pruned*, not *pruned at time zero*. — agent: `opus-5`
- [x] **B29** **`usage_summary` loaded every event in the window into Python to add integers.** `for e in q.all()` on a table whose entire design is *this accumulates*: 90 days of heavy use is hundreds of thousands of ORM objects instantiated to compute six numbers. — found during `P14-02`, reviewing `P14-01` — **fixed:** aggregated in SQL with `count`/`sum` and one `GROUP BY`. The test captures statements at the driver, so it cannot pass by reading the source. — agent: `opus-5`
- [x] **B30** **The scrape endpoint would have turned Prometheus into a load generator against the operator's embedding server.** `render_metrics` called `run_self_checks()` on every scrape; `embedding_availability` calls `get_embedding_client()`, which performs a **real HTTP health check**. The process latch in `embeddings.py` only suppresses that after a *failure* — on a healthy install the probe runs every call. At a 15-second scrape that is **240 requests an hour, forever, as a side effect of being monitored**: precisely the defect `P16-12` refuses liveness probing to avoid, arriving one layer down where the module's own test for it could not see it. — found during `P16-12`'s correction pass, before it had run anywhere — **fixed:** a 60-second TTL cache, `pantheon_self_check_age_seconds` so a cached reading is never mistaken for a live one, and a test that stubs `socket` and fails any collector that reaches the network. *(The first expiry test was vacuous — it asserted the cache timestamp was non-zero, which stays true forever after the first fetch, so raising the TTL to a billion seconds passed it. It counts fetches across the boundary now.)* — agent: `opus-5`
- [x] **B31** **A test sliced *everything between two functions I know about* and blamed the wrong panel.** `test_the_panel_does_not_build_markup_from_strings` (mine, from `P16-15`) took `admin.js` from `loadSelfChecks` to `loadLogs` and asserted no `innerHTML` in between. `P14-05` added a panel in that gap and the test went red for code that was not the self-checks' — and it failed on a **comment** reading *"textContent, never innerHTML"*, which is the docstring-read-as-code trap for the third time. — found during `P14-05` — **fixed:** brace-matched extraction of the one function's body, comments stripped, plus an assertion that the slice still contains code so it cannot pass by matching nothing. Verified by mutation: an `innerHTML` put back inside `loadSelfChecks` still turns it red. — agent: `opus-5`
- [x] **B32** **A `try/except` would have swallowed a `NameError` forever.** The `P4-25` skills capture in `src/agent_loop.py` passed `session_id=session_id`, and `_build_system_prompt` does not take a `session_id` — so every run would have raised `NameError`, been caught by the `except Exception: pass` that exists to keep a receipt from breaking a reply, and recorded **nothing**, silently, for as long as anyone cared to look. The guard that makes instrumentation safe is the same guard that makes broken instrumentation invisible. — found during `P4-25`, before it shipped — **fixed:** the argument is dropped (the receipt is keyed on `run_id` and the session comes from the other rows), plus an AST test that resolves every name at that call site against the enclosing function's parameters. — agent: `opus-5`
- [x] **B33** **`P4-25` recorded a config for streamed turns only — half the chat surface had `config: null`.** `record_run_config` lived in `stream_llm`; `/api/chat` reaches the model through `llm_call_async_with_route_fallback` → `llm_call_async` and never streams. **The test I wrote for it grepped `llm_core.py` for the call, which one entry point satisfies.** — found during the `P4-26` correction pass — **fixed:** one `_capture_run_config` helper called from all three entry points (`Law 14`), placed **before** the response-cache check because a turn answered from cache still had a configuration; plus an AST test that requires every model entry point to capture. **Then the fix reproduced `B32` in a new file** — the sync `llm_call` has no `session_id` either — which this time raised loudly instead of being swallowed, because the guard now lives inside the helper rather than at the call site. The scope test is parameterised over every capturing module now: *a test written to the shape of one bug catches one bug.* — agent: `opus-5`
- [x] **B34** **A test that marks a turn leaves the next module inside it.** `mark_turn_start()` is deliberately idempotent within a turn — the first call wins, so a retry does not split a receipt — which is correct in production and a trap under pytest, where everything shares one context. A `P4-27` helper that seeds a run left `_turn_started` set, and `test_duration_is_null_and_that_is_honest` went red **only when the two modules happened to sort in that order**. — found during `P4-27` — **fixed in `tests/conftest.py`** with an autouse fixture that clears the run ContextVars before and after every test. Fixing the one offending helper would have left the trap armed for the next person; this is the level that closes it. Verified by mutation — removing the fixture reproduces the cross-module failure. — agent: `opus-5`

- [x] **B35** **`src/rate_limiter.py` used `logger` without ever defining one.** Not introduced by `P15-09` in the sense that matters — the module has never had `logging` imported, and the row simply became the first code in it to log anything. It is the `B32`/`B33` family a fourth time: a name that is not in scope, in a module where a `NameError` would have surfaced in the worst possible place. Two of the three new call sites sit inside `except Exception as e:` blocks, where the `NameError` would have escaped *while already handling a failure* — so a read-only data directory, which the code deliberately degrades on, would instead have raised out of `penalise()` and taken down every outbound call in the product. The third sits inside `_ensure_loaded`'s own guard, where it would have been swallowed forever after the restore had already run, losing only the return value and the log line. — found during `P15-09`, **by reading the module rather than by a test** — fixed by adding `import logging` and a module logger. Verified by mutation: deleting the logger line fails the suite. — agent: `opus-5`

- [x] **B36** **The limiter's docstring described a control it does not have.** `OutboundHostLimiter`'s class docstring said, since the file was written: *"Call it on every response, not only the failures — **a 200 is how a host tells us the cooldown is over**."* `observe()` has never done that. A success clears `consecutive_429` — the escalation ladder — and deliberately leaves `blocked_until` alone. **The code is right and the sentence was wrong**, which is the more dangerous direction: a `blocked_until` comes from the server's OWN instruction (`Retry-After`, `X-RateLimit-Reset`) and expires on its own schedule, so a 200 arriving while we believe the host is blocked means somebody bypassed `acquire` — and letting that erase the block would let the one caller who skips the gate un-ban the host for everybody else. — found during `P15-06`, **by writing a test against the docstring and watching it fail.** That is the whole cost of a comment that misdescribes a control: it does not break anything until somebody believes it, and then it produces a confidently wrong test. Fixed by rewriting the docstring to say what the code does and why, and naming `succeeded()` as the explicit way to drop a penalty that carried no expiry. Covered by `test_a_success_resets_the_ladder_but_NOT_the_servers_deadline`. — agent: `opus-5`

- [x] **B37** **A test of mine was flaky by wall clock, and only a full sweep could show it.** `test_an_hourly_task_gets_a_useful_spread_and_a_minutely_one_gets_a_small_one` (`P15-10`) called `dispatch_hold` with no `now`, so it used the real clock — and the hold is 5% of the time until the task's NEXT run. An hourly task evaluated at `:59` has a one-minute period and a hold under three seconds, which is **correct behaviour** and fails an assertion about hourly tasks. It went red once in a full sweep that happened to finish near the top of the hour and passed alone every time it was re-run, which is precisely how a flaky test earns its place in the ignore pile — and an ignored test is worse than a missing one, because it is counted. — found during `H03`, by the sweep rather than by the row — fixed by pinning `now` to the moment a due task is actually dispatched, just after its cron boundary, which is also the only moment the assertion was ever about. Re-verified against all 14 `P15-10` mutations. — agent: `opus-5`

- [x] **B38** **A refactor of mine left a `NameError` in the hot loop, and everything I trust was green.** `H08`'s first shape put `from src.runtime_limits import lift_cap as _lift_cap` inside `stream_agent_loop`; extracting `_resolve_local_lifts` moved that import into the new helper and left the per-round timeout call — two thousand lines below — still saying `_lift_cap`. **A `NameError` on the first round of every chat.** What was green while that was true: the 20 targeted tests, 16 mutations all caught, all eight checkers, and my own test asserting the call site — because that test matches **source text**, and `pinned=_timeout_pinned` was present exactly as written while the function it was passed to did not exist. **Only the full suite saw it: 96 new failures.** Third of the `B32`/`B33` family — a name that is not in scope where it is used — and the loudest, because this one had no `except` around it to swallow the error; that was luck. Fixed by lifting `_lift_cap` to module scope, and guarded generally by `tests/test_agent_loop_names_resolve.py`, which resolves every free name in every top-level function of `agent_loop.py` against the module's globals and that function's own bindings. **Its first run found a second thing — a lambda parameter my walker did not collect — which is the argument for running a new checker over the whole module before believing any single finding.** Both forms of the incident are mutation-proven. — **done 2026-09-07**

- [x] **B39** **On a default Ollama endpoint the agent is sent no tool schemas AND told not to write tool syntax, so every tool is unreachable — not the two `H09` names, all of them.** Measured, not reasoned: `_agent_route_tool_mode('http://localhost:11434', 'qwen3:8b')` returns `is_api=False, native=True`, and `is_api=False, compat=True` for the `/v1` form. From that one value, three things follow. `_tool_schemas_for_route` returns `[]` for a non-API route (only MCP schemas, and only when the user's message happens to contain an MCP keyword), so **nothing is sent**. `compact = is_api or is_native_ollama or is_ollama_compat` is **True**, so the prompt sent is the compact one, which opens *"You are an AI assistant with native tool/function calling. Only the tool schemas provided by the API are available for this turn… do not write tool syntax or tool instructions in chat"* and then lists bare tool names **with no fenced syntax**, because only the full prompt carries that. And `skip_fenced = is_api_model and ...` is **False**, so the fenced parser is running and is the only live channel — the one the prompt forbids and never documents. **The default is what makes this bite**: `ModelEndpoint.supports_tools` is `nullable, default=None`, and the only writers are the Cookbook (when a vLLM command contains `--enable-auto-tool-choice`) and the Copilot importer — **the add-endpoint UI has no field for it**, so an admin who adds Ollama through Settings → Models gets `None`, which routes straight into `is_api_model = False`. The model-name allowlist (`qwen3`, `llama-3.1`, …) never gets a say: the Ollama URL check short-circuits above it. **No comment anywhere acknowledges this**, so it reads as an oversight rather than a trade. `Verify:` a fresh Ollama endpoint added through the UI can call a tool. — found while fixing `H09` — agent:`H09` — **done 2026-09-07. Filed as needing the owner, then measured, and the measurement made it a bug rather than a decision.** The question was whether dropping Ollama from the compact prompt trades correctness for prompt size on the machines with least room for it. It does not, because **the rest of the product already handles "no native tools" this way**: a `gpt-oss` model on llama.cpp is also `is_api_model = False`, is not Ollama, gets `compact = False`, and therefore gets the full prompt carrying the fenced syntax its parser is running. Ollama was the only family routed away from handling that already worked, so there was no trade to weigh. Measured across LM Studio (localhost and docker), vLLM local and on the LAN, llama.cpp, OpenAI and both Ollama URL forms, before and after: **`compact=is_api` changes the two Ollama rows and nothing else**, and an Ollama endpoint that declares `supports_tools=True` is `is_api` and keeps the compact prompt exactly as before. The selection is now `_compact_prompt_applies(is_api)` — a named predicate rather than an expression — **because the same flag gates the schemas** (`_tool_schemas_for_route` branches on `route_state["is_api_model"]`), and two predicates that must agree are easier to keep in step when one of them has a name. A mutation that drifts the schema gate away from the prompt gate is one of the five the tests catch. **Not fixed here:** `supports_tools` still has no field in the add-endpoint form, so the answer is unaskable even when an operator knows it — filed as `P3-22`.

- [x] **B40** **The Brain ranked memories by "contains two consecutive capitalised words", for essentially every query, on the default install.** Found while building `H11` — the row about showing a person *why* a memory fired, which is exactly the view that makes this impossible to miss. A chain of four, each measured: **(1)** `identity_words` contains `"i"`, `"am"`, `"me"`, `"my"` and the check was `word in query_lower`, a **substring** test — so "what **i**s the weather", "expla**i**n the code", "f**i**nd the invoice" and "what ti**me**" are all identity questions. **Ten of ten ordinary queries classified as identity**, which means the contact, preference and task boosts below had never run in production, on any install, ever. **(2)** a memory is an "identity memory" if it matches `\b[A-Z][a-z]+ [A-Z][a-z]+\b` — **any two consecutive capitalised words**, so *Bridge Street*, *Docker Compose* and *Hacker News* all qualify. **(3)** for an identity query every identity memory is admitted at **0.9**, ahead of anything scored on real similarity — and with (1) that was every query. **(4)** identity memories were **excluded from scoring entirely** otherwise, so a memory could not be retrieved by its own verbatim text: with *"Joseph Jeffrey works at Afrog Labs"* stored, the query `Afrog Labs` returned **nothing**, and so did *"where does Joseph Jeffrey work"*. **Reproduced end to end**: nine memories, eight of them containing two capitalised words and one reading *"the build timeout is 900 seconds"*; the query *"what is the build timeout"* returned `[0,1,2,3,4]` at `top_k=5` and `[0..7]` at `top_k=8` — **the memory containing the answer was not retrieved at either**. It now leads. **And this is not a fallback nobody hits**: `MemoryVectorStore` needs ChromaDB, which is an *optional* dependency (`pip install chromadb-client`) — verified unavailable on a clean checkout — so `_vector_available()` is False and this scorer is the only memory retrieval there is. **Fixed: word-boundary matching**, which is what "contains the keyword" was always meant to say, and **identity memories now go through normal scoring** unless the query is genuinely an identity query. **The deliberate half is untouched** — the original comment says identity memories are admitted regardless of similarity for identity queries, and they still are; what is removed is every query being one. `_is_identity_memory` and `_query_type` are lifted out and named so they can be tested and argued with. 14 tests, 7 mutations, all caught. — **done 2026-09-07** — found while building `H11` — agent:`H11`

- [x] **B41** **The same mistake as `B38`, four hours later, in a different file — and the guard written for `B38` did not catch it.** Adding `H11`'s keys to `/api/memory/debug`, the anchor I matched on was `return {"memories": relevant, "total": len(relevant), "query": query}` followed by `@router.get("/timeline")` — which is **`search_memories`**, two handlers below `debug_memory_relevance`, not the route I meant. So the explanations were added to the search route, which does not define `explained`: a `NameError` on `POST /api/memory/search`. **My tests were green** because they asserted substrings against the WHOLE FILE (`'"memories": relevant' in ROUTES`), and that string was present — in the wrong function. That is the third time this session a substring test has matched something other than what it meant (`H02`'s quoted correction, `H10`'s `innerHTML` comment, this). **And `test_agent_loop_names_resolve.py` — written for `B38`, one commit earlier, for exactly this class — was green too, twice over.** It only read `src/agent_loop.py`; and its scope walker used `ast.walk`, which descends into nested functions, so a name bound in `debug_memory_relevance` counted as bound in the enclosing `setup_memory_routes` and its **sibling** `search_memories` inherited it. A guard aimed at the file the last incident landed in, that also forgives the shape the next one takes. Fixed on all three fronts: the keys are on the right route, the route tests resolve one handler's source with `ast.get_source_segment` instead of grepping the file, and the scope guard now covers seven modules with a walker that stops at function boundaries. All three mutations — `B38` verbatim, `B41` verbatim, and one handler reaching for a sibling's local — are caught. — **done 2026-09-07**

- [x] **B42** **The agent could take off the gates that exist to constrain it.** Found while working `H18`, whose framing — *twelve settings the model can change and a person cannot* — reads it as a missing control. **The missing control is the smaller half.** Measured before anything was written, and measured by the **stored value** rather than the exit code (these refusals answer `exit_code: 0` with a message, so an exit code proves nothing — my first pass reported three gates as writable that were not): `manage_settings set agent_email_confirm false` moved the stored value **True → False**, It took effect. **The agent could remove the gate requiring a person to approve an email before it sends** — through a tool call that looks identical whether the instruction came from the operator or from a page the agent was told to read. **`trust_rung` was in the first version of this row and has been removed, and the removal is the more interesting half.** `set trust_rung allow_listed` did take effect, and calling it *lowering the ladder* was wrong: `allow_listed` is one of `_RUNGS_THAT_ASK_UNTAINTED`, so it asks in clean runs the default lets through, and may be the stricter of the two. **The rungs are not a ladder that can be read from outside** — `decision_for` carries the reproduction showing *"the two 'stricter' rungs were strictly less protected than the one they sit below"* — and `test_the_chat_tool_still_sets_a_rung_it_does_implement` sets the strictest rung from chat **on purpose**, because `P7-03`'s framing is *a person being able to set it*. Six suite failures said so. Shipping that refusal would have been a security change resting on an ordering the codebase says does not hold, which is close to the exact mistake the trust-ladder incident in that file is about. `P7-13`. `agent_loop.py` already argues exactly this for role profiles: one *"may only raise strictness — a profile that lowers the rung hands a user a way to switch their own confirmation gate off."* The same sentence applies with more force to the agent itself. **Fixed with `_SELF_RESTRAINT_KEYS`**, the same shape as the `_SECRET_KEYS` set already beside it: read allowed, write refused, at both `set` and `reset` — reset writes the shipped default and is therefore *safe today*, and is refused anyway, because "the agent may only move this in the safe direction" inverts the day someone changes a default. **The refusal names the setting, says where to change it, and says it survives being asked politely**, because a message asking for it looks the same whether it came from the operator or from the page the agent is reading. **`tool_path_extra_roots` turned out to be already blocked** by the structured-setting rule — worth stating, because my first measurement said otherwise and I nearly filed it. **`agent_verifier_subagent` is in the set because `H16` put it there**: declaring a key hands it to the agent as well as to the person, since `DEFAULT_SETTINGS` is the allowlist for both, and a checker the checked party can switch off is not a check. **The loop caps are deliberately out** — `agent_max_rounds` and `agent_max_tool_calls` have no approval semantics and "give yourself more steps" is a real request; `P7-12`. **And the trade only works because the person gains the control**: `agent_email_confirm` had zero references under `static/` and now has a switch in Settings → Email that says, in the panel, that the agent cannot turn it off. 15 tests, 9 mutations, all caught. — **done 2026-09-07** — found while working `H18` — agent:`H18`

- [x] **B43** **The agent's `manage_tokens` handed back credentials that could never authenticate, and revoked ones that went on working.** Found while scoping `P0-31`'s prefix migration, by counting mint sites: the row named two and there are three. `src/agent_tools/admin_tools.py:468` built `secrets.token_urlsafe(32)` **with no prefix**, and `app.py`'s bearer branch only ever looked at headers reading `Bearer ody_` — so the token was hashed, stored, returned to the caller and **could not be used**. Underneath that, two more, each independently fatal: the impl takes `owner` (`_owner_adapter` threads it from the tool context, and it is the only one of the five admin tools that writes a row with an owner column) and **wrote the row without it** — `_refresh_token_cache` resolves every row's owner against the auth store, skips the ones it cannot place and logs a warning on every rebuild, so an ownerless token never enters the map the middleware reads; and **neither `create` nor `delete` invalidated the token cache**. **The third is the one that matters.** The first two fail closed — a token that does not work. The third fails **open**: bearer auth serves from an in-memory prefix→tokens map that rebuilds only when something flags it dirty, routes reach that flag through `request.app.state`, and a tool running inside the model loop has no request — so `manage_tokens delete` removed the row, reported `Deleted token 'x'`, and **the deleted token kept authenticating until the next restart**. Three route call sites already had their own private copy of the invalidation helper and a fourth had none, which is also how the prefix came to disagree. **Fixed by giving the four sites one thing to share**: `core/api_tokens.py` owns `TOKEN_PREFIX`, the separate `ACCEPTED_TOKEN_PREFIXES` read side, `mint_raw_token()`, `bearer_credential()` and a process-level invalidator registry that `app.py` registers its own dirty-flag setter into — the same setter routes already reach through `app.state`, which is untouched (`Law 1`). The tool now mints with the prefix, attributes the owner, **refuses when it has no owner** rather than minting a dead credential, writes `scopes="chat"` explicitly (the same scope the column default already produced — a tool the model drives is not where a credential gets widened) and invalidates on both verbs. `bearer_credential` also matches the scheme case-insensitively per RFC 7235 §2.1, which widens what is *offered* to the bcrypt check and nothing else. 16 tests, 10 mutations, all caught. — **done 2026-09-07** — found while scoping `P0-31` — agent:`P0-31`

- [x] **B44** **The one line in the tracker whose job is to summarise the tracker was wrong, and nothing checked it.** Every `§ Progress` entry opens `**N tracked, M done.**` — the status table's `Total` row, restated. It read **`338 tracked, 135 done`** against a table saying **338 / 116**, and had done for at least five entries: each author copied the headline above and edited the part that had changed. **`check-tracker.py` validated the phase rows, the Total against the rows above it, and any table line it could not parse — and never looked at the prose sentence claiming to be the same number.** Found while writing `P0-31`'s entry, by trying to derive the figure instead of copying it, and getting three different answers depending on what was counted (150 ticked rows of 397 including `B`/`H`; 111 of 332 phase rows; 117 of 338 with `Setup` folded in). The one that matches the table is the last, because the Total row sums the `Setup` row too. **Fixed by making the checker read it**: the newest `§ Progress` headline is compared against the Total row's tracked/done and fails on drift. **Only the newest.** The entries beneath it keep the number they were written with — a record of what was claimed at the time is evidence, and silently correcting evidence is a different kind of dishonesty than leaving it wrong (`Law 1`); the drift and its size are recorded above the list instead. — **done 2026-09-07** — found while closing `P0-31` — agent:`P0-31`

- [x] **B45** **The `html2pdf` bundle we ship is not the bundle upstream published, and one string is the difference.** Found while re-deriving `P0-21b`'s package list, by checking the vendored file against npm rather than assuming: `static/lib/html2pdf.bundle.min.js` is identical to html2pdf.js 0.10.2's `dist/` copy after normalising CRLF **except** that jsPDF's language table reads `"sv-SV":"Swedish (SE)"` where upstream reads `"sv-SV":"Swedish (Sweden)"`. **Exactly one difference, and that is measured rather than said**: substituting the string back makes the two byte-identical (906,037 bytes), so nothing else moved. It arrived at the fork baseline `fff72ec`, which makes it upstream Odysseus's edit and this fork's inheritance. jsPDF is MIT and modifying it is permitted — the defect is that **nothing recorded it**, so the next person refreshing the file from npm reverts a deliberate change without knowing one existed, and provenance for a vendored file quietly becomes "close enough". `P0-16` is the same subject with the notice pointed the other way. **Not reverted** (`Law 1`): recorded in `CREDITS.md` with the exact strings and the method, and pinned by a test whose failure message says what to do rather than what went wrong. — **done 2026-09-07** — found while working `P0-21b` — agent:`P0-21b`

- [x] **B46** **`mermaid.min.js` is a bundle, nobody knew, and it ships three Microsoft packages with no notice anywhere.** `check-licences.py` had Mermaid as one MIT library with one licence text. It is a webpack bundle carrying `vscode-jsonrpc` 8.2.0, `vscode-languageserver-protocol` 3.17.5 and `vscode-languageserver-types` 3.17.5 — **90 module paths** in the shipped bytes. **Nothing found this while the list of bundles was a list.** `P0-21b`'s rule 7 originally read a hardcoded `BUNDLES = ("static/lib/html2pdf.bundle.min.js",)`, a mutation emptying that tuple survived, and rewriting the rule to *derive* which vendored files are bundles turned this up on its first run — a checker's own weakness pointing at a defect it was not looking for. **Versions are read, not inferred**: Mermaid is built with pnpm, whose store layout writes the version into the module path (`node_modules/.pnpm/vscode-jsonrpc@8.2.0/node_modules/vscode-jsonrpc/…`), and pnpm is also why the naive match first reported a package called `.pnpm`. All three ship the same Microsoft MIT text byte for byte, so one file in `licenses/` covers all three and the entry names each. — **done 2026-09-07** — found by `check-licences.py` rule 7 — agent:`P0-21b`

- [x] **B47** **Adding one import to a sandboxed module breaks every sandbox that copies it, and the error names a temp path rather than the cause.** Found by the full suite, not by review: `P1-12` added a four-line dependency-free `./motion.js` to `theme.js`, and **54 assertions across `test_advanced_key_mirrors_js.py` and `test_accent_token_js.py` went red at once** with a node module-resolution failure pointing at `/tmp/pytest-of-root/…`. Nothing about that message says "you added an import"; the frontend checkers were all green, `node --check` was green, and the change itself was correct. The cause is the sandbox pattern these tests share: `_make_sandbox` copies one real module beside a **hand-written stub per import**, so the stub list is a second copy of the import list and the two silently disagree the moment either moves — `Law 14`'s shape, in test infrastructure. **Fixed by making the copier read the imports** instead of being told them: a stub still wins where one exists (that is how these sandboxes keep `storage.js` in memory and `ui.js` silent), and any other local import is copied from `static/js/` for real, transitively, with the `?v=` query stripped. A dependency-free helper now costs nothing; a heavy new import fails loudly on its own missing globals, which is the right way round. Two guards: a stub is never overwritten by the real module, and a bare package specifier is left alone. — **done 2026-09-07** — found while working `P1-12` — agent:`P1-12`

- [x] **B48** **Two different rows shared the id `P3-17`, and the checker that exists to keep this file honest never looked.** One is the *Fail loudly* row from the competitor-scar-tissue set; the other is the 84-undeclared-environment-variables row, split out of `P3-15` on **2026-09-07** by a run that took the next number it could see, in a file whose numbers are not contiguous. Both are cited elsewhere in this tracker and one is cited in `VERIFY-2026-08-27.md`, so *"see `P3-17`"* had two answers for a day. **`check-tracker.py` validated every row's marks, the Total, the phase each row is filed under, and any table line it could not parse — and never that an id identifies one row.** It counted the right totals over the wrong rows. Fixed both ways: the newer row is renumbered `P3-23` with its two references updated (the older keeps the id, because it is the one cited in a dated verification document), and the checker now fails on any id used twice. The older row keeps `P3-17` on purpose — renumbering the one cited in a document nobody should rewrite is the wrong half to move. — **done 2026-09-08** — found while triaging `P3` — agent:`P3-04`

- [x] **B49** **A spinner that has never spun, because CSS drops an unknown animation name without a word.** `#hwfit-cache-scan.spinning svg` asks for `animation: modelPickerRefreshSpin` — camelCase, defined nowhere. The kebab-case `model-picker-refresh-spin` it was reaching for did exist. Both spellings read as the same name to a person, and an `animation` shorthand naming keyframes that do not exist is not an error: the declaration is simply dropped, so the hardware-fit cache-scan button's spinner sits still and nothing anywhere says why. Present at the fork baseline `fff72ec`, so it is inherited and has never worked in this product. **Found by the check written for `P3-04`/`P3-05`/`P3-06` on its first run** — *every animation name used resolves to a definition* — which is the same failure those three rows are about, pointed the other way: they are about a name meaning two things, this is about a name meaning nothing. Fixed to `spin`. — **done 2026-09-08** — found by `tests/test_keyframes_are_unique_and_resolved.py` — agent:`P3-04`

- [x] **B50** **Between 700 and 767 pixels the mobile sidebar could not be dismissed, and the backdrop was there asking you to try.** `static/js/sidebar-layout.js` decides "is this mobile?" ten times. **Seven of those tests say 768 and three said 700** — and the disagreement lands exactly where it hurts: `:173` adds the mobile backdrop at `< 768`, while `:383`'s click-outside-to-close handler returned early at `>= 700`. So on any viewport in that 68px band the sidebar opened as an overlay, the dimmed backdrop appeared, and clicking it did nothing. The other two 700s in the same file arm the "restore the sidebar after a tool modal closes" behaviour, which therefore also never armed there. `static/js/calendar.js:625` had a fourth, under a comment reading *"Only remember the prior state on desktop. On mobile the sidebar is an overlay that the user intentionally swipes/taps away"* — so in the band it disagreed about, closing the calendar popped back a sidebar the person had deliberately closed, which is the exact thing its own comment calls unwanted. **Found while working `P3-07`, by a test asking which scripts have their own idea of where mobile ends** — the row was about a stylesheet and the stylesheet was the smaller half. Eight JS sites moved to 768, matching the 89 `@media (max-width: 768px)` blocks, the pre-paint script, and the other 97 JavaScript tests of the same number. `static/js/editor/build/right-panel.js`'s four are in the same fix and are why `P3-07` could not be done in CSS alone. — **done 2026-09-08** — found while working `P3-07` — agent:`P3-07`
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
