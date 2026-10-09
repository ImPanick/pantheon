# The ship line — a proposal

> **This is a proposal, not a decision.** Nothing in the tracker has been
> re-categorised, no row has been re-ticked, and no gate has been changed.
> `.pantheon/ship-line.py` is deliberately not named `check-*.py`, so
> `release-gate.py` does not run it and a red answer here blocks nobody.
> Adopting it is one rename; § *Adopting this* says what that costs.
>
> Filed 2026-09-17 under `B451`. The owner's question is the whole reason it
> exists: *"the tracked items keeps growing and our progress isnt really making
> a dent."*

---

## 1. The measurement

Every number below comes from `.pantheon/ship-line.py --trend`, which reads the
`**N tracked, M done.**` headline off each `§ Progress` entry. That headline is
the status table's `Total` row restated, and `check-tracker.py` validates the
newest one against the table — so this is the tracker's own arithmetic, not a
second count of it (`Law 14`).

`§ Progress` carries 110 headlines. Ten of them moved the totals; the rest are
turns inside a wave that restated the line unchanged. Those ten, oldest first:

| tracked | done | open | done % | Δ tracked | Δ done | Δ open |
|---|---|---|---|---|---|---|
| 382 | 190 | 192 | 49.7 % | | | |
| 481 | 268 | 213 | 55.7 % | +99 | +78 | +21 |
| 491 | 276 | 215 | 56.2 % | +10 | +8 | +2 |
| 507 | 285 | 222 | 56.2 % | +16 | +9 | +7 |
| 508 | 286 | 222 | 56.3 % | +1 | +1 | 0 |
| 522 | 306 | 216 | 58.6 % | +14 | +20 | −6 |
| 537 | 326 | 211 | 60.7 % | +15 | +20 | −5 |
| 550 | 337 | 213 | 61.3 % | +13 | +11 | +2 |
| 588 | 363 | 225 | 61.7 % | +38 | +26 | +12 |
| 619 | 390 | 229 | 63.0 % | +31 | +27 | +4 |

Over those nine intervals: **237 rows filed, 200 closed, 37 net new open.** That
is 26.3 filed and 22.2 closed per interval, a **file-to-close ratio of 1.185**.

**Both of the two things a reader notices are true and neither is a mistake.**
Done went 49.7 % → 63.0 %. Open went 192 → 229. The percentage converges because
closure outruns filing *as a share of the total*; the open count diverges because
it does not outrun filing *in absolute terms*. The open count falls only when the
ratio drops below 1.000, and it has been above 1.000 in six of the nine intervals.

**Do not read the ratio as a forecast.** It is not going to drop below 1.000 by
working harder. A codebase of this size always has more to find, the sweeps that
find it are the thing that made the last four waves good, and each one files more
than it closes by construction — the last wave closed 27 rows and filed 29 by its
own count. An open count that only falls when we stop looking is not a target;
it is a thermometer that goes up when the patient gets better.

**What is actually wrong is not the count. It is that the tracker has one mark
for *not done* and no mark for *not a gate*.** Every defect a sweep finds is
filed as a row, every row reads as blocking, and so the answer to *are we nearly
there* is always "234 things away", whatever those 234 are. The rest of this
document proposes the missing distinction.

### Re-measured 2026-10-01 — the ratio crossed 1.000

The paragraphs above are the 2026-09-17 measurement and they stay as written.
Re-run on the tree that carries `P20`, `P21` and wave five, `§ Progress` holds
130 headlines and the ten distinct ones run 886 → 1009 tracked, 606 → 734 done:
**123 filed, 128 closed over nine intervals — a file-to-close ratio of 0.961**,
so **the open count is falling**: 280 → 275, with the last two waves at −13 and
−15. Done went 68.4 % → 72.7 %.

The sentence above that says the ratio *"is not going to drop below 1.000 by
working harder"* was a forecast, and this is the measurement that answers it.
It did not drop because the sweeps stopped — `B955`–`B1033` were filed inside the
same window — but because the last two waves closed 28 and 32 rows while filing
15 and 17. It is a thermometer, as the paragraph says, and it reads lower today.
`tests/test_ship_line.py` reads the direction stated on the line below and fails
when the tracker disagrees with it, so the next reversal rewrites this line
rather than carrying it (`B44`).

**Direction as of 2026-10-01: the open count is falling.**

Re-measured the same day, after `P22` was filed and its first wave landed: the
ten distinct headlines now run 893 → 1059 tracked, 613 → 750 done — **140 filed,
112 closed, 1.250**, open 281 → 309. Twenty-five of those rows are one phase
filed in one entry (`P22 · The Workbench`), and wave A's merged-tree check filed
eight more from driving it. The thermometer moved because the owner asked for a
room that did not exist, not because closing slowed.

**Direction as of 2026-10-01, after `P22` was filed: the open count is rising.**

Re-measured 2026-10-03, after waves F and G and `g-sec`: the ten distinct headlines read 147 filed, 152 closed —
**a ratio of 0.967**, open 299 → 294. The Workbench phase closed its twenty-five rows and the ship line's blocking set
closed with it; the sweeps kept filing, and closing outran them.

**Direction as of 2026-10-03: the open count is falling.**

Re-measured 2026-10-07, after `P23`'s eight lanes merged: the ten distinct headlines read 149 filed, 104 closed —
**a ratio of 1.433**, open 312 → 357. The last three waves filed sixty-three rows and closed none: `P23`'s nine, the
two `main` brought, fifty the lanes filed from what they found while building, and two the tracker pass filed
(`B1235`, `B1236`). `P23`'s own rows tick only after the merged-tree drive, so this reading is taken before the
phase's closing, not after it. **Done went 71.6 % → 71.3 %** — the first window this document has measured in which
the percentage fell; `tests/test_ship_line.py` holds that it rises, unconditionally, and is red on this tree for that
reason alone (`B1235`). None of the fifty-two is a gate; the two closest, `B1229` and `B1231`, are in § 7 with what
would make each one.

**Direction as of 2026-10-07: the open count is rising.**

Re-measured at `P23`'s close the same day: 159 filed, 110 closed — **a ratio of 1.445**, open 310 → 359, done
72.2 % → 71.8 %. The closing wave ticked twenty-seven rows — `P23`'s nine, `P0-29`, `B480`, four of its own filings
(`B1229`, `B1231`, `B1234`, `B1236`) and the twelve defects its acceptance found and its second round fixed — and
filed seventeen, so the open count still rose by two, and *done %* is still below the window's first wave
(`B1235` stays open). None of the seventeen is a gate: `B1259` and `B1264` are in § 7 with what would make each one.

**Direction as of 2026-10-07, at `P23`'s close: the open count is rising.**

Re-measured 2026-10-08, after `D-2026-10-07-02`'s lanes and the owner's two reports: 188 filed, 127 closed —
**a ratio of 1.480**, open 312 → 373, done 72.1 % → 71.4 %. The wave closed fifteen rows — eleven of the thirty-one it
filed, plus `B1181` (withdrawn by the ruling), `B1194`, `B1254` and `B1259` — and filed twenty that stay open, two of
them the owner's. None is a gate; `B1296` is the closest, and § 7 says what would make it one.

**Direction as of 2026-10-08: the open count is rising.**

Re-measured 2026-10-09, after the owner ran the pushed `v0.2.0` and reported two things: 206 filed, 133 closed —
**a ratio of 1.549**, open 314 → 387, done 72.5 % → 71.3 %. Seven lanes answered the two reports; the wave closed
twenty-six rows and filed fourteen that stay open, two of them the owner's. None is a gate. The one row that touches
a `FORBIDDEN.md` Part 2 control is `B1308`, and § 7 says what it narrowed, what it did not, and what the residual is.

**Direction as of 2026-10-09: the open count is rising.**

Re-measured 2026-10-09, after the owner ruled on the day's two open questions and reported a third thing: 188 filed,
112 closed — **a ratio of 1.679**, open 316 → 392, done 73.0 % → 71.1 %. Three lanes built `D-2026-10-09-01`; the
wave closed five rows — the three the last wave left open (`B1324`, `B1327` and `B1328`, two of them the owner's own
questions), plus `B1338` and `B1339`, closed as they were filed — and filed eight that stay open, **four of them the
owner's**. None is a gate. **This is the first wave to amend a `FORBIDDEN.md` Part 2 control rather than narrow
what it reads**, and § 7 says under `B1338`
what the amendment gives up, what it keeps, and what the residual is. The gate itself has not lifted, and
`untrusted_context_message` and `_escape_guard_markers` are byte-identical across the wave (checked, not asserted:
`a5ee5f8..8586638`).

**Direction as of 2026-10-09, after the ruling: the open count is rising.**

### A second number, which is the one that moves

Of the last 40 `B` rows filed — `B360` through `B455`, four waves of sweeps plus
today's — **four are gates** under the line proposed below: `B370`, `B400`,
`B411` and `B452`. Ten per cent. The other 90 % is real work that a stranger can
use the software without. That is the convergence argument, and it is the only
one available: not that we will stop finding things, but that almost nothing we
find is a gate. The figure is recomputed by `ship-line.py` rather than carried
forward, which is the failure `B44` is named after.

---

## 2. What "blocking" means here

A row **blocks** if it stops this repository being made public and used by a
stranger. Four tests, and a row needs one:

1. **A security control that does not hold.** Not a control that could be
   stronger — one that is measurably not doing the job it is named for.
2. **A licence obligation unmet.** AGPL-3.0 or an inbound licence, where the
   obligation attaches at publication or at network offer.
3. **A documented claim that is false.** A published file says something about
   this software that is not true. `LEDGER.md`'s own preamble states the standard
   this test enforces: *"One figure that does not survive being checked is not
   one bad row — it is the row a sceptic quotes."*
4. **A defect a first-time user hits in the first ten minutes.** A reachable
   surface, an ordinary action, a silently wrong result.

**And a row does not block** merely because it is a `Law 13` consolidation, a
checker with a hole that is written down, a currency bump with no reachable
advisory, an unbuilt feature, or a row whose own body says it is not urgent.
Those stay tracked. They stop being a gate.

**The line is *public*, not *finished*.** There is a second line — *a second
person can use this box* — and four `P11` rows sit on it rather than on this
one. Conflating them is how a fifteen-row list becomes a forty-row list. Those
rows are marked `second-line` in the register.

---

## 3. The blocking set — twenty-two rows, all met

Fifteen of 234 open rows when this was written; **seven have since been met and three
have been added, and the met ones are marked `landed` in the register rather than deleted,
because a line that quietly loses its met gates cannot be audited.** `P0-17` and `P6-08` closed
on 2026-09-18; `P11-01` and `P11-02d` closed the same day, which is the fail-open privilege
default and the six unreconciled route files — both of them gates this document named and both
of them now measurements rather than unknowns.
**Two were added on 2026-09-18, and adding them is the point of keeping the line honest.** The
`P11-02d` reconciliation that met one gate is what found them: `B540`, where any signed-in
account can clear the instance-wide TTS cache while the same act on uploads is `require_admin`,
and `B541`, where four `/api/hwfit/*` routes will SSH to a host the caller names — for any
signed-in account, when the identical question behind `GET /api/cookbook/gpus` is admin-only.
A line that only ever shrinks is a line that has stopped being measured. The third addition,
`B533`, was adjudicated and **fixed in the same hour** — the threat model named one of two tool
gates and said admins always get full access, which stopped being true the moment `P11-01`
denied undeclared keys to everybody. Four lines to correct is not a gate; it is registered
`landed` so the adjudication is on the record.
**`P2-21` was met on 2026-09-18** and it is the first of these that was met in the order its own
row demanded: the list loader first, then the two open `GET`s gated, then the flag flipped. A gate
over an empty section reads as done and is not, which is why the row refused to be closed by the
gate alone — and closing it closed `P11-10` with it, the same hole named twice from two phases.
**`P10-11` was met on 2026-09-18, the hour the owner said the repository was going public**, and
it is the one row here whose cost is irreversible: a pushed secret cannot be recalled. All three
checks are clean, with the secret sweep widened from the checkout to all 186 commits, because a
public repository exposes every one of them. The checklist's own grep turned out to match the word
`task-` and is fixed (`B770`) — the check a fork owner runs once, under time pressure, before
doing something they cannot undo, returned a hundred false lines.
**`B896` was added on 2026-09-27**, by the agent working `P7-02`: the assistant's own `app_api` bridge
was the owner on `POST /api/import`, a door the blocklists did not name. **It was met the same day**:
the bridge lost the owner's whole trust surface, audited route by route on its row.
**None stands (2026-10-02).** Eleven stood that morning — three security (`B370`, `B540`,
`B541`), three a false documented claim (`B71`, `B411`, `B452`), two a licence obligation
(`P0-16`, `B349`), one an action rather than a commit (`B357`), one a defect a first-time user
hits (`B400`) and one the release artefact (`P10-12`) — and wave F met all eleven; each is
`landed` in the register with one line saying how. **Two more were added and met at the same
merge**, adjudicated blocking on the day they were filed: `B1144`, two Apache-2.0 §4(b) notices
saying Pantheon redistributes *unmodified* files it had changed (licence), and `B1147`, the
published `LEDGER.md` stating three numbers its own claims contradicted (claim). So the set is
twenty-one rows, all met, and `ship-line.py` lists no open blocking row. That is a statement
about the adjudicated set: 267 open rows are *clear by rule, not read*, the weakest
classification in this document, and the line stays measured — `--check` names a new row the
rule reads a signal in the day it is filed. *(The sentence that stood here until 2026-10-02 said
"Four are security … two are an action rather than a commit", which summed to thirteen against
eleven; the register then had three security rows and one pre-flip row standing. `f-sec` found
it.)*
**One stands again (2026-10-03): `B1179`**, filed and adjudicated blocking at wave G's merge.
Closing `B1175` — on the agent's loopback `require_admin` now asks whether the person the request
names is an admin — measured the door that change does not reach: Forge's read tools call the
loopback naming nobody, so `require_admin` answers them as Pantheon itself, and a non-admin's
assistant reads `GET /api/cookbook/state` (200) where the person gets 403. It is `B540`'s and
`B541`'s class — a signed-in non-admin reaching what is the operator's — through the assistant,
so it is on this line for the reason they were. `B1175` itself is registered `tracked`: it was one
gate deep (the dispatcher refused `app_api` to a non-admin) and was closed the day it was filed.
**It was met the same day (`g-sec`):** the dispatcher binds the person a tool call acts for and `_internal_headers`
names them whenever its caller names nobody, so every tool loopback is asked what its person's own request is asked;
the shell's own admin gate asks the same of a named person; and measured on the real app, bob's assistant is refused
each Forge read where bob is, and starts no `ssh` to a host it names.
So the set is twenty-two rows, all met, and 245 open rows are *clear by rule,
not read*. One line of reasoning each below; the row carries the measurement.

### Security — the control does not hold (5)

- **`B370`** — `/static/wave-variants.html` and `/static/whirlpool-variants.html`
  answer **200 to a client with no cookie** under `AUTH_ENABLED=true`, while `/`,
  `/docs` and `/backgrounds` all `302 → /login`. The exposure is small and the row
  says so; what is not acceptable at publication is an auth boundary with a hole
  and no written exemption beside `AUTH_EXEMPT_PREFIXES`. Either half of its
  `Verify:` closes this. **Met 2026-10-02** — three pages, measured; each has a route
  behind a session, the exemption is written beside the prefix, and `check-auth-map`
  rule F fails a page under `static/` with no route. `B540` and `B541`, added above,
  were met the same day (`require_admin`; rule E holds every route to a caller-named
  host to it).
- **`P11-01`** — `src/auth_helpers.py:216` reads `privs.get(key, True)`: a
  privilege absent from a user's record is **granted**. Non-admin accounts are
  reachable today — `routes/auth_routes.py:319` (`admin_create_user`) and `:155`
  (`/signup`, behind `signup_enabled`) — so this is live, not latent. The row
  calls itself "the cheapest security fix in the tracker" and it is a one-line
  guard.
- **`P2-21`** — `GET /api/skills/builtin` and `GET /api/skills/builtin/{name}`
  (`routes/skills_routes.py:1256`, `:1292`) make no auth call, while the `PUT` and
  `DELETE` beside them call `require_admin`. Any logged-in non-admin reads all 60
  tool instruction blocks. **Only the gating half of this row blocks**; the flag
  flip and the list loader do not. `P11-10` closes with it.
- **`P11-02d`** — six route files whose gating nobody has reconciled. **This is
  the one row in the set that is an unknown rather than a known failure**, and it
  is here on that basis: an auth surface nobody has mapped is a bet, the row is
  bounded (six files and a table), and the deliverable is a reconciliation rather
  than a change.
- **`B1179`** — added 2026-10-03, **met 2026-10-03**. `require_admin` on `GET /api/cookbook/state`
  refuses bob, a signed-in non-admin, in person (403) and lets his assistant's
  `list_serve_presets` read it (200), because Forge's read tools loop back with no
  person named (`_internal_headers()` at sixteen sites in `src/tools/cookbook.py`).
  Read in the source, not driven: `tail_serve_output` and `list_cached_models` reach
  SSH to a host the caller names the same way — `B541`'s class. Met by the first: every
  tool loopback names its person (`g-sec`); measured, not read — `tail_serve_output` and
  `list_cached_models` did reach SSH to a named host on `3e4888b`, and do not now.

### Licence — the obligation is unmet (3)

- **`P0-17`** — the AGPL §13 source link. The row's own words: *"the one licence
  obligation that is genuinely required and genuinely missing."* Built and left
  dark against a repository URL that ships empty (`D-2026-09-08-06`); the
  obligation attaches the moment a modified version is offered over a network.
- **`P0-16`** — the Apache-2.0 §4(b) change notices. Eight files carry one;
  `services/search/` is deliberately unstamped because stamping *"you changed
  this"* on nine byte-identical files would be false in the other direction. The
  row is right that overriding the upstream copyright holder's own attribution
  **needs a human**, and the moment to have that ruling is before publication.
  **Met 2026-10-02** on the owner's ruling (`D-2026-10-02-03` §3): credit only, no
  notice, on the reason that still holds — the nine files contain nothing of Tongyi's.
- **`B349`** — the fork date is `2026-08-24` in `NOTICE` (*"Date of fork"*),
  `CREDITS.md`, `CHANGELOG.md` and `README.md`, and `2026-08-20` in
  `.pantheon/ledger/claims.py` — which renders into the published `LEDGER.md`
  header. Two attribution surfaces, one event, two dates. The row's later note
  makes the resolution likely (they are two different facts) and that is exactly
  why it is cheap and why it needs the owner.
  **Narrowed 2026-09-19 (`B860`).** One of the two dates is no longer a reading
  taken elsewhere. `b4d1293` was unreachable in the container this project is
  developed in — a clone that begins at a snapshot import — and CI checks out
  with `fetch-depth: 0`, so the first completed run reached it:
  `b4d12932a953b3cdfc745b3525c7ecd5dffd8b3c`, authored `2026-08-20T05:06:22-06:00`
  and committed `2026-08-20T13:06:22+02:00`, subject matching `FORK_POINT_SUBJECT`
  to the character. **`2026-08-20` is confirmed.** What is still the owner's is
  the §5(a) wording — *cloned* versus *forked* on `NOTICE`, `CREDITS.md` and
  `CHANGELOG.md`, and whether the commit date belongs on that surface at all.
  Cheaper than it was: a wording decision, not a choice between two numbers.
  **Met 2026-10-02**: *forked*, with both events labelled on every surface — the fork
  point committed 2026-08-20, the fork begun 2026-08-24 (UTC) — and `check-ledger.py`
  holds `NOTICE` to both.

### A documented claim is false (3)

- **`B71`** — `docs/pantheon-wordmark.png`, `docs/pantheon.jpg` and
  `docs/pantheon-browser.jpg` are upstream's artwork under this fork's filenames,
  and `build-macos-app.sh:31-37` ships `docs/pantheon.jpg` **as the macOS app
  icon**. A published repository whose desktop icon is a picture of the other
  product is a false claim in the loudest available place. **Met 2026-10-02** with
  `P0-13`: the two pictures are deleted, the macOS build copies Pantheon's own icon,
  and `check-fork-names.py` now looks at pixels as well as names.
- **`B411`** — four claims in the generated, published `LEDGER.md` state a number
  their own `repro` command does not print: `tracker` 370 vs 376, `spdx` 1,541 vs
  1,653, `credits` 13 vs 43, and `fan-out`'s 40. The ledger's own preamble sets
  the standard they fail. **Met 2026-10-02**: `check-ledger.py` prints no NOTEs.
- **`P6-08`** — `.env.example:335-338` documents `PANTHEON_TASK_CONCURRENCY_CAP`
  as *"this env var overrides the built-in default"*, and all three compose files
  pass it through. The row proves the env leg is **unreachable code on every
  install from first boot**. The file a stranger configures the app from
  documents a knob that does nothing.
- **`B452`** — `SECURITY.md:57` tells a self-hoster the git sha is *"the only
  version identifier this project has"*. It was not when it was written — two
  version strings existed — and `B450` has now given the project a version line,
  so it is false in a second way. **It is here for the same reason `P6-08` and
  `B411` are**: a published document stating something untrue about this
  software, in the file a security reporter reads first. One sentence, in a file
  this worktree does not own. **Met 2026-10-02**: `SECURITY.md` prints what
  `GET /api/version` returns — a test calls the route — and says no release is tagged.

### A first-time user hits it (1)

- **`B400`** — a `.docx` imported from the Documents panel's own menu item is
  stored as its zip bytes, while the same file dropped on the library gives
  markdown. Three clicks apart, no error, no refusal. **This is the softest call
  in the set** — the alternative reading is that it is a `Law 13` third-copy row
  like `B401`, which is registered as tracked. It is here because `.docx` is the
  single most likely file a stranger opens this product with, and because the
  failure is silent.
  **Landed 2026-10-02.** Worse than registered: the menu item opened no file picker at all
  while the Documents panel showed anything but an email — a hidden Send button's 0×0 rect "contained"
  every `element.click()`, so the click was cancelled and the page said *"To and body are required"*
  (the Library's Import and the composer's Attach files failed the same way with the panel open). Behind
  the picker, a `.docx` was stored as its zip bytes. It now imports through the Library's own per-file
  function, so a `.docx`, `.pdf` or `.xlsx` opens readable and named as the file was, and what it cannot
  read is said in words.

### Had to happen before the flip, and was not a commit (2) — both met

- **`P10-11`** — run the `SECURITY.md` fork checklist: `git status --short`, the
  ignore check, the secret grep. A secret pushed to a public repository is not
  recoverable by deleting it.
- **`B357`** — five links in four files send vulnerability reporters to
  `…/security/advisories/new`, which 404s unless **Private vulnerability
  reporting** is switched on. The row could not verify it and says so. It is a
  repository setting, and `docs/security-ci.md` already lists it under
  *"One-time settings to turn on"*. **Met 2026-10-02**: read from the owner's
  machine, `{"enabled": true}`; every fallback stays.

### The release artefact (1) — met

- **`P10-12`** — release notes leading with the Odysseus credit and enumerating
  the breaking renames. **The version half of this landed today** (`B450`):
  `CHANGELOG.md` has a `0.1.0` section, the tree carries one version string that
  is Pantheon's, and § *Versions* says how the three agree. What is left is the
  rename enumeration and the credit paragraph. It is in the set because a
  stranger's first question about a public repository is *which version is this*,
  and until today the answer was another project's number. **Met 2026-10-02**:
  `docs/release-notes/0.2.0.md` leads with the Odysseus credit, measured, and
  enumerates every rename an Odysseus install has to follow — derived from the lists
  that own the names and checked against `b4d1293` by
  `tests/test_the_release_notes_name_every_rename.py`. Written as `0.1.0.md`; the owner
  called the release `0.2.0` (`D-2026-10-02-04` §1).

---

## 4. What happens to the other 219

**They stay tracked, in the same file, with the same marks, and they stop being
a gate.** Nothing is deleted, nothing is deferred, no row moves, and `Law 4`
still puts every one of them in the tracker every turn. The only thing that
changes is the sentence a reader can now form: *fifteen rows stand between this
repository and being published; 219 are the work that continues afterwards.*

Three of the 219 cannot be closed on their own terms and inflate the count for
no work: `B16` (folded into `B15`), `P13-10` (collapsed into `P13-01`, "not
independently actionable") and `B392` (*"Unused. Reserved and not used."*). Nine
more are `[~]` blocked, several on conditions that do not exist yet — `P11-09`
waits on a second user account and the install has zero accounts. That is twelve
open rows which are not available work, and no reader of "234 open" can tell.
`B455` is the row for it.

**What this proposal deliberately does not do**: re-mark those rows, split the
tracker, or add a third file. `Law 14` — the tracker is the list, and a second
list of the same rows is the defect this repository has fixed three times
already (`B44`, `B79`, `B241`).

---

## 5. Where the analysis disagrees with the tracker

Three places. Each is a judgement and each can be overruled in one line.

- **`P0-13` is not a gate, and the tracker's preamble says it is.** That preamble
  reads *"`P0-13` is blocked on a design decision. It gates the public flip
  alongside `P0-17`."* Under the four tests it does not: a project with no logo
  of its own is not publishing a false claim, breaking a licence or failing a
  user. **Shipping upstream's identity as ours is the gate, and that is `B71`,**
  which is in the set. Drawing it this way also unblocks the sequence — `B71` can
  be closed by removal, which needs no design decision, while `P0-13` needs one.
- **`B421` reads like a shipped CRITICAL advisory and is not.** Its first line
  offers jsPDF 4.2.1 *"against 4.0.0's nine including one CRITICAL"*, and the tree
  does ship jsPDF 4.0.0 inside `html2pdf.bundle.min.js`. `B336` closed on option
  (a) having measured **all twenty-seven advisories as unreachable**, written each
  one down per advisory id against the API `static/js/document.js` does not call,
  and wired `check-vendored-versions.py` rule 6 to fail the gate if the bundle's
  inner versions ever move. That is the brief's *"checker with a known narrow hole
  that is written down"*, exactly. Tracked, not blocking.
- **`P15-07` meets none of the four tests and probably should not ship
  unresolved.** It re-sends a refused request under five other vendors' client
  names, narrowly — kimi.com `/coding` only, an endpoint the operator pays for —
  and it is `[~]` blocked on an owner ruling that is a genuine trade. It is not a
  failed control, not a licence obligation, not a false claim in a document, and
  not a first-ten-minutes defect. **If the owner wants it gated, the line needs a
  fifth test** — something like *"behaviour a public repository would be read by
  its intent"* — rather than one of these four stretched to fit. Stretching a
  test is how a fifteen-row list becomes a forty-row list again.

Two further close calls, both tracked: **`P8-39`** (MCP server env vars are plain
text while every other secret in the schema is encrypted — no document claims
otherwise, and the data directory is already the operator's own) and **`B373`**
(the Cookbook's runtime `pip install realesrgan` is unpinned and unseen by CI —
behind an explicit user action, and `Law 16` is satisfied because a user asked
for it).

---

## 6. The mechanism — how a row gets classified when it is filed

Every hand-maintained list in this repository has rotted. The status table drifted
by nineteen and nothing read it (`B44`); the backlog sat outside the table its own
heading claimed to cover (`B79`); a `§ Progress` entry claimed rows it left
unticked for two days (`B241`). Each was fixed the same way: a script recounts and
fails on drift. This is that, for the ship line.

**`.pantheon/ship-line.py --check` fails when:**

1. an id in the register below is not a row in the tracker;
2. a row named `blocking` is no longer open — it has been closed and the count in
   this document is stale;
3. **an open row the rule calls a candidate appears in neither list.** That row is
   *unclassified*, by name, and somebody has to say which it is.

**The rule is triage, not a verdict.** `triage()` reads a row's whole body —
including the indented corrections, which is where `B421` stops being a CRITICAL
advisory — for the signals a gate leaves: an auth boundary, a licence section
number, a claim named false, a silent wrong result, a shipped advisory. It is
recall-oriented on purpose. A false positive costs one reading; a false negative
ships a gate as a nice-to-have. Measured on today's tracker its 53 signals call
**43 of 234 open rows candidates** and catch **14 of the 15** in the blocking
set; the one it misses is `P10-12`, an absence of an artefact, which no prose
signal can find and which is registered by hand.

**It has already earned its place.** Five rows were filed while this document was
being written (`B450`–`B455`). `--check` named two of them unclassified — `B451`
and `B452` — and `B452` turned out to be a gate: `SECURITY.md` tells a
self-hoster the git sha is *"the only version identifier this project has"*,
which was false when it was written and is more false now. Nobody would have gone
looking.

**So a row filed tomorrow is classified the day it is filed, by the agent filing
it, or `--check` names it.** That is the whole mechanism. It does not depend on
anyone remembering, and it does not require re-reading 234 rows ever again.

### Adopting this

One rename:

    git mv .pantheon/ship-line.py .pantheon/check-ship-line.py

`release-gate.py` globs `.pantheon/check-*.py` and runs anything CI does not, so
the gate picks it up with no other change. A line in `.github/workflows/ci.yml`
puts it in CI, and `release-gate.py` reads its checker list out of that file, so
the two stay in step by construction. Until the owner rules, it stays unrenamed.

---

## 7. The register

`verdict` is `blocking` or `tracked`. `class` says why. Both columns are read by
`ship-line.py`; the reason column is for people.

Rows not listed here were read in digest and are **not blocking by rule** — the
rule found none of its signals in them. That is a classification and it is the
weakest one in this document: it means nobody adjudicated them individually.
`--check` upgrades any of them the moment a later edit puts a signal in the body.

| row | verdict | class | why |
|---|---|---|---|
| `P0-16` | landed | licence | ruled 2026-10-02 (`D-2026-10-02-03`): credit only, no notice; `CREDITS.md` records it, and that the nine files are no longer byte-identical |
| `P0-17` | landed | licence | AGPL §13 source link — attaches at network offer; built dark 2026-09-18, and since 2026-10-02 it offers this repository by default (`D-2026-10-02-04` §2, `B1165`) |
| `B349` | landed | licence | the fork point (committed 2026-08-20) and the fork's start (2026-08-24 UTC) are labelled on every surface; `check-ledger.py` holds `NOTICE` to both |
| `B370` | landed | security | three `/static` pages answered 200 with no cookie; met 2026-10-02 — every page under the mount has a route and the sandboxes need a session, the exemption is written beside `AUTH_EXEMPT_PREFIXES`, and `check-auth-map` rule F fails a page without a route |
| `P11-01` | landed | security | `privs.get(key, True)` fails open and non-admin accounts are reachable today |
| `P2-21` | landed | security | two `builtin` GETs make no auth call beside a `require_admin` PUT and DELETE |
| `B540` | landed | security | any signed-in account cleared the instance-wide TTS cache; met 2026-10-02 — `require_admin`, the height of the upload cleanup, with a no-login install unchanged |
| `B541` | landed | security | four `/api/hwfit/*` routes opened SSH to a host any signed-in account named; met 2026-10-02 — the router is `require_admin`, and `check-auth-map` rule E holds every route to a caller-named host to it |
| `B542` | tracked | security | two admin writes are middleware-exempt on path alone; their in-handler `is_admin` still stands |
| `B543` | tracked | claim | the admin gate is written four times; a consistency defect on a surface no stranger reaches first |
| `B530` | tracked | second-line | the resolution rule longhand at eight sites; fail-open only once roles exist, and roles do not |
| `B531` | tracked | decision | a corrupt privilege store grants; the fix is a lockout on a one-operator box and needs a ruling |
| `B532` | tracked | second-line | a derivation `P11-02` will have to change; nothing resolves differently today |
| `B533` | landed | claim | the threat model named one of two tool gates; corrected at the merge that found it |
| `B571` | tracked | tooling | a conflicted index triples every checker's count; a runner's index is never conflicted |
| `P8-12` | tracked | second-line | an authoring aid in the Workshop; the rule flagged it on the word *supply*, which is about a skill's fields |
| `P13-01` | tracked | second-line | a confidence number on memories; the rule flagged it on *first ten minutes* and it is not one of them |
| `B623` | tracked | claim | `CREDITS.md` is correct today and nothing holds it so; a missing guard, not a false statement |
| `B680` | tracked | second-line | shadows a role that cannot be created yet; no role ships defined and no panel assigns one |
| `B681` | tracked | second-line | `B543`'s class on a new surface, behind `require_admin`, reachable by an operator not a stranger |
| `B683` | tracked | second-line | the `operator` tier has no privilege key yet; a scope statement about roles, not a defect in the tree |
| `B692` | tracked | decision | a `FORBIDDEN.md` Part 2 validator refuses the LAN `Law 17` allows; the owner rules, an agent does not |
| `B702` | tracked | second-line | a revoke lands next turn and the panel now says so; timing copy, not a control that lies |
| `B722` | tracked | security | measured and closed the day it was filed, so it never had to be adjudicated as a gate |
| `B723` | tracked | security | the `Law 16` gate had two doors; fixed in the same hour, so it was never on the line |
| `B731` | tracked | second-line | an authoring aid's threshold disagreeing with the server's; nobody's first ten minutes |
| `B741` | tracked | claim | one of two paths drops two usage fields; what it shows is true, what it omits is the gap |
| `B742` | tracked | claim | a subtraction standing where a measurement should be — and `P4-14` just made it checkable |
| `B790` | tracked | decision | a nightly job silently unpublishes a skill on a 0/24-precision signal; changing what it destroys is the owner's call |
| `B864` | tracked | security | `disabled_tools` survives its own row and not the row's deletion — and `P8-35`, landing in the same commit, removed the only reason anyone had to delete it |
| `B892` | tracked | first-ten | a context bar larger than the fact it states — the sentence that was FALSE on it was `B893`, and that is fixed |
| `B896` | landed | security | the agent's `app_api` bridge is the owner on `POST /api/import` — it turned a `B42` self-restraint key off and a disabled feature on, in its own name |
| `B907` | tracked | claim | a wait message that says the model is "pre-filling context" is a guess, and it never fires anyway — nothing false reaches a screen today |
| `B912` | tracked | security | `manage_settings enable_tool` re-enables an admin-disabled tool unasked in a clean run; a tainted run's gate already stops it, and which switches may move is the owner's call with `B897` |
| `B921` | tracked | claim | an agent turn's own compaction is announced with no figures and not saved — a notice that says less than happened, not one that says something false |
| `B930` | tracked | claim | the untrusted-content card names Pantheon's own two-integer run-limit reply as outside content — it over-asks, which is safe; the sentence is what is false |
| `B937` | tracked | security | a font uploaded by mistake has no remove button and needs a server-side delete — nothing is exposed; the upload itself is admin-only, magic-checked and served nosniff |
| `P20-05` | tracked | security | the live view is a window onto a workstation display; it shipped behind the same privilege and account derivation the tools use, refuses another person's display (65 route cases), and the token never reaches the browser |
| `B966` | tracked | security | `can_use_bash` granted a non-admin nothing and failed closed throughout; closed by the owner's call (`D-2026-10-01-01`) — Settings → Users no longer offers it to a non-admin, and the composer's Shell switch follows where the person's shell runs |
| `B975` | tracked | claim | documents still say a container cannot reach the LAN; measured 2026-10-01 it can on the owner's Docker Desktop — the controls do not rest on that sentence (the SSRF validators guard content-supplied URLs regardless, and `P20-06`'s gate enforces the workstation's mode), so it is words to correct, not a hole |
| `B976` | tracked | security | `ping` does not start in the workstation because `P20-06` drops `CAP_NET_RAW` on purpose — a usability cost of a control that holds, fails closed, and has a one-line fix an agent can run with sudo |
| `B981` | tracked | claim | on the VM backend the sudo sentence over-warns: each person has their own machine there, so it says homes are readable when they are not — safe in direction, false in words |
| `P8-48` | tracked | security | the read-only verdict shipped and is read by the panel and the plan-mode gate alike; the schema editor did not, on a recommendation the owner has to rule on |
| `P11-02d` | landed | security | six route files whose gating is unreconciled — an unknown on an auth surface |
| `B71` | landed | claim | upstream's artwork under this fork's filenames, and the macOS app icon; met 2026-10-02 — Pantheon's own mark wherever upstream's shipped, and `check-fork-names.py` fails on upstream's images by hash, by look-alike and by the boat's path data |
| `B411` | landed | claim | `check-ledger.py` prints no NOTEs: two claims state their checker's rule, `credits` the checker's count, `fan-out` prints its 40 |
| `P6-08` | landed | claim | `.env.example` and three compose files document an env override that is dead code |
| `B400` | landed | first-ten | *Import from device* opened no file picker while the panel showed a non-email document, and behind it stored a `.docx` as zip bytes; it now imports through the Library's own per-file function |
| `P10-11` | landed | pre-flip | the secret grep has not been run and a pushed secret is unrecoverable |
| `B357` | landed | pre-flip | `{"enabled": true}` read 2026-10-02 from the owner's machine; every fallback kept |
| `P10-12` | landed | artefact | release notes at `docs/release-notes/0.2.0.md` (written as `0.1.0.md`, renamed with the version, `D-2026-10-02-04` §1) — the Odysseus credit first, every rename derived from its owning list and checked against the fork point; met 2026-10-02 |
| `B492` | tracked | second-line | every throttled host but the mailbox is admin-only; an operator surface, not a stranger's first ten minutes |
| `B505` | tracked | coverage | the tool eval is not in CI — a gap in enforcement, not a defect a user meets |
| `P0-13` | tracked | identity | a missing mark is not a gate — shipping upstream's is, and that is `B71`; done with it 2026-10-02 |
| `B437` | tracked | fail-open | a workflow that reports and always exits 0 — written down, and it cannot run at all until Actions does |
| `B441` | tracked | claim | `/api/ready` answers 401 against its own docstring; the reader is an orchestrator, not a stranger in the first ten minutes |
| `P2-05` | tracked | decision | decided; content is decoded to text for a model and never served back |
| `P2-12` | tracked | defect | real, and it needs the email surface — not a first-ten-minutes path |
| `P8-00` | tracked | quality-bar | an acceptance criterion for a phase, not a defect in the tree |
| `P8-25` | tracked | blocked | nothing writes the column today, so nothing breaks today |
| `P8-39` | tracked | hardening | no document claims these are encrypted; the data dir is the operator's |
| `P8-45` | tracked | tidy | unreachable presets behind a `Law 14` decision that has not been made |
| `P8-46` | tracked | defect | needs the MCP surface; a stranger reaches it after the first ten minutes |
| `P8-47` | tracked | constraint | names a control to preserve, not one that fails |
| `P9-07` | tracked | tidy | consistency across 20 empty-state class names |
| `P9-09` | tracked | tidy | two additions plus a `Law 14` extraction |
| `P11-02` | tracked | second-line | gates a second user, not a public repository |
| `P11-02b` | tracked | second-line | the 103-gate mapping; same line as `P11-02` |
| `P11-08` | tracked | second-line | an auth audit log is for multi-user operation |
| `P11-09` | tracked | blocked | correctly blocked — the install has zero accounts |
| `P11-10` | tracked | rides-on | closes with `P2-21`; it is the same gate named twice |
| `P11-11` | tracked | second-line | where an operator configures roles that do not exist yet |
| `P13-19` | tracked | feature | register-not-mood; a Brain design row |
| `P16-20` | tracked | deferred | the owner ruled it out of scope (`D-2026-09-01-03`) |
| `H21` | tracked | internal | dead-code deletion with two corrections already on it |
| `B15` | tracked | themes | palette contrast, owner-gated, and no shipped document claims WCAG AA |
| `B16` | tracked | folded | folded into `B15`; cannot be worked alone |
| `B280` | tracked | written-down | the residual `B201` could not reach, measured and recorded |
| `B324` | tracked | written-down | direct pins exist; the row says an honest lock cannot be generated here |
| `B373` | tracked | written-down | unpinned, but behind an explicit user action and `Law 16` is satisfied |
| `B401` | tracked | defect | the tail after `B233`; not a file a stranger opens first |
| `B421` | tracked | written-down | `B336` measured all 27 advisories unreachable and machine-checks the bundle |
| `B424` | tracked | future-cost | the cost of a bump not taken, not something shipped |
| `B425` | tracked | future-cost | currency across a documented breaking change; zero advisories either side |
| `P15-07` | tracked | owner | meets none of the four tests — see § 5; registered so it is on the record |
| `B452` | landed | claim | `SECURITY.md` names what `GET /api/version` returns and that no release is tagged |
| `B451` | tracked | owner | this proposal; the line is the owner's to draw and they have not |
| `B453` | tracked | build-ref | *which commit* needs a build stamp, and that needs files this row cannot touch |
| `B454` | tracked | registry | the image tag moves backwards; probably academic and nobody has looked |
| `B455` | tracked | tracker | twelve open rows are not available work; the remedy is the ruling `B451` awaits |
| `B1020` | tracked | test-order | a suite-order leak into four test cases; the model allow-list holds in a fresh process and in the product |
| `B1021` | tracked | defect | the refusal holds — the datagram is not sent; only the sentence explaining it is missing for one silent tool |
| `B1038` | tracked | defect | the engine refuses and pauses the admin-only task, so nothing runs; the tool misreports a refusal as success |
| `B1070` | tracked | defect | a loading state drawn as an empty one for seconds; the memories arrive and nothing is lost |
| `P22-08` | tracked | feature | the rule flagged it on *plain text*, which is the sample a person types to test a step, not a secret at rest; a feature row held open on `B1080` |
| `B1144` | landed | licence | two Apache-2.0 §4(b) notices said Pantheon redistributes unmodified files it had changed; adjudicated blocking and met at the merge that found it (2026-10-02) — each notice names what Pantheon changed |
| `B1147` | landed | claim | the published `LEDGER.md` stated 8,819 tests, 15 checkers and seven upstream commits against its own claims; adjudicated blocking and met at the merge (2026-10-02) — read from the claims |
| `B1145` | tracked | claim | two documents said private reporting was "not enabled yet"; both kept a correct fallback; corrected 2026-10-02 |
| `B1146` | tracked | decision | eight places said the repository is private; one was the §13 link's premise, answered by `D-2026-10-02-04` §2; corrected 2026-10-02 |
| `B1148` | tracked | claim | README trend figures and checker count were copies; held to `ship-line.py` and `ci.yml` by `check-ledger.py` since 2026-10-02 |
| `B1143` | tracked | claim | `P11-AUTH-MAP.md` § C argues from two tier counts that have drifted; a design note's arithmetic, while § A's checked summary is right and every gate is mapped |
| `B1157` | tracked | first-ten | an imported PDF's page view needs PyMuPDF on a default install; the text is stored and the view says in words what it needs, so it is not silent |
| `B1166` | tracked | identity | the tour's last line uses upstream's voyage motif; copy in the product, not a claim about the software |
| `B1168` | tracked | defect | at phone width the §13 tag sits on the composer's corner; nothing interactive is under it (measured) and the offer itself is right |
| `B1175` | tracked | security | a non-admin's loopback passed `require_admin`; one gate deep — the dispatcher refused `app_api` to a non-admin, so no person's assistant reached it — and closed the day it was filed (2026-10-03): the gate asks about the person named |
| `B1179` | landed | security | Forge's read tools looped back naming nobody, so a non-admin's assistant read the admin's Forge state the person is refused and ran `ssh` to a host it named; met 2026-10-03 — the dispatcher binds the person a tool call acts for and every tool loopback names them, the shell's own gate asks about a named person, and the read tools say a refusal |
| `B1181` | tracked | defect | fails closed: on a no-login install the shell's own gate refused everyone; **withdrawn 2026-10-07** by `D-2026-10-07-02` §2 — there is always a sign-in, so the configuration is gone, and the Forge's shell answers its admin, her loopback and the lifecycle loop on every install (fx4-auth) |
| `P23-03` | tracked | doors | one table for what each tool's switches hide; the server's own refusals (`require_feature`, the privileges) are the controls and stand as they were — the row is the doors agreeing with them, and the rule flagged it on the table's privilege column |
| `P23-06` | tracked | display | display and motion; the rule flagged it on *dead end* — two phone dead ends found by driving and fixed in the same row |
| `B1191` | tracked | decision | a switch for everyone and per person on the tools that have only *Show in this browser*; the switches that exist hold, and what "off" means for work that runs without its window is the owner's call |
| `B1195` | tracked | decision | the person's Gallery switch hides the window while the routes that list a person's own gallery do not ask for `can_generate_images`; making or editing an image does (`require_privilege`), so the capability the switch names holds — whether it should also hide a person's own pictures is the owner's call |
| `B1198` | tracked | tidy | two buttons on a user row that belong behind ⋯; the rule flagged it on *Privileges*, the name of the button beside them |
| `B1207` | tracked | owner | the §13 link's tooltip and accessible name say different things; the link and what it offers are right (`P0-17`, `B1165`), and the tooltip is the owner's own words |
| `B1229` | tracked | decision | opening the Forge refreshed the model catalog from huggingface.co — and ollama.com — with nothing switched on; **closed 2026-10-07** on the owner's ruling (`D-2026-10-07-01` §2): one admin switch, off by default, asked at every request, so the 0.2.0 notes' *nothing reaches the public internet* holds — a serve of a model not on disk fetched nothing either once `B1259` closed (2026-10-08) |
| `B1231` | tracked | owner | SQLite's write-ahead log by default, on a share that may not hold it; **closed 2026-10-07** (fx3-forge): forced on Linux, the database is put back on the rollback journal at start and keeps working — the owner's Windows install is still the one place to see it for real, and safe either way |
| `B1259` | tracked | decision | a *serve* of a model not on disk let the engine fetch it with the Forge's switch off; **closed 2026-10-08** on the owner's ruling (`D-2026-10-07-02` §1): with the switch off a fetch-by-design command is refused and every other serve runs offline, stopping on a repo that is not on disk (fx4-models) |
| `B1264` | tracked | claim | `SECURITY.md` says no release is tagged — true on this tree, false on the commit `v0.2.0` goes on; `B452`'s class, so the release commit carries the change, and `tests/test_security_documents_are_true.py` goes red the day the tag exists if it does not; a gate the moment the tag is pushed without it |
| `B1270` | tracked | decision | an upgraded no-sign-in install's owner-less tasks, notes, calendar rows and allow-rules reach no one after `claim_ownerless.py` — nothing is exposed (it fails closed) and nothing is deleted; widening the script or offering the rows to the first admin is the owner's call; the rule read *privilege* in a function's name |
| `B1271` | tracked | security | branches only an anonymous `require_user` reached are unreachable from a request since `D-2026-10-07-02` §2; `require_privilege`'s pass-through needs an app assembled with no auth manager, which the real app never is — dead code to remove or comment, not a door |
| `B1273` | tracked | defect | a documents poller asks for a Tidy plan with documents switched off and is refused 403, swallowed; the rule read *is false* in the row's code expression `toolShown('library') is false` |
| `B1296` | tracked | claim | `v0.2.0` is tagged on `bbd66a3` while `[0.2.0]` and its notes describe work merged after it; true once the tag is re-cut on the released commit, a claim gate if `v0.2.0` is published on `bbd66a3` with these notes — the integrator's to settle before the tag is pushed |
| `B1308` | tracked | security | registering any MCP server armed the post-external approval gate for every turn, so the first MCP call of every turn waited for a click; **closed 2026-10-09** by narrowing what counts as *post-external* — the gate's own mechanism and `untrusted_context_message` are byte-identical (`FORBIDDEN.md` Part 2 untouched) and a tool **manifest** no longer arms it, while everything that genuinely came from outside still does, asserted as ten parametrised sources each of which still refuses `bash`, with the adversary named (`Law 17`): the first **result** from a hostile MCP server arms the run and `bash`, `write_file`, `send_email` and `manage_settings` are all refused. Read against the four tests and not a gate: the control holds in the direction it exists for, the narrowing is measured and asserted both ways, guard-marker escaping got wider rather than narrower, and the server prose that no longer arms on its own reaches the prompt only because an admin registered that server (`require_admin` on `/api/mcp/servers`). The residual, written down rather than argued away: a hostile tool **description** no longer arms the gate by itself — it sits inside guard markers in a block that says to read a description as a description, and the server's first output arms the run |
| `B1324` | tracked | decision | the person's own saved memory arms that gate, so every agent run with one pinned memory asks before a privileged effect and the card calls it external context; over-arming, so it fails closed, and the owner's call — a memory can be laundered in by an agent calling `manage_memory add`, which is itself a gated write, which is why `B1300` held the behaviour byte-for-byte rather than changing it while rewording a header ; **closed 2026-10-09** on the owner's ruling (`D-2026-10-09-01` §1): a person's own saved material is not content that arrived from outside, so `own_context_message` writes `tool_gate_untrusted: False` while keeping `trusted: False` and every boundary — the strip, the context budget's accounting and the merge refusal are unchanged, and `untrusted_context_message` and `_escape_guard_markers` are byte-identical across the wave. The laundering path the row named is answered where it happens rather than argued away: `manage_memory add` and `manage_skills add` are privileged effects, so the gate asks at the **write**, in the run that read the page, while the taint is still attributable. Asserted both ways over 51 cases — five own-store sources that must not arm, nine outside sources that still must, and a hostile MCP result, a hostile page on a run that also has memory and skills, and a hostile skill write all still held. The residual: integration prompt text still arms, filed as `B1340` |
| `B1328` | tracked | decision | an installed skill arms that gate for the same reason the MCP manifest did; the same over-arming shape as `B1324` and the same fail-closed direction, and harder than the manifest was, because skill text is editable through `manage_skills`, which an agent can call — so it wants one answer together with memory and integration prompt text rather than a second one ; **closed 2026-10-09** with `B1324`, by one decision for both stores exactly as the row asked (`D-2026-10-09-01` §1). Both the matched-skills block and the Level-0 skill index move to `own_context_message`, so a published skill no longer arms the gate from the first token of every turn while still reaching the model inside the same delimiters, in the same `user` role, with `trusted: False`. Two surfaces deliberately keep the armed untrusted envelope, with the reason at each call site: the skill **tester** and a workflow's skill step, where the skill is the thing being run rather than the person's background material (`P8-18`) |
| `B1338` | tracked | security | **the first amendment to a `FORBIDDEN.md` Part 2 control** (`D-2026-10-09-01` §2, built and closed 2026-10-09), and the case this register exists for: a stranger relying on this repository should be able to read what Auto costs before anyone turns it on. **What it gives up, written down rather than argued away:** inside a chat a person has set to **Auto**, a privileged effect that follows outside content runs without a person seeing it first — and with **no exception list**, so a `DESTRUCTIVE` effect (`manage_memory delete_all`, a bulk session delete, `delete_file`, `admin_wipe`) runs under it too, and so does `MORE_REACH`, the self-escalation door that asks in every run. For a reversible effect *"without seeing it first"* still means *"seeing it after"* — every auto-approved step is recorded on the `tool_start` frame, the `tool_output` frame and the persisted `tool_event`, absent rather than `False` on a step Auto never touched — and for mass deletion it does not. **What it keeps:** the mode is one chat's (`sessions.approval_mode`, NULL on a chat nobody set), the install default is the **constant** `manual` and deliberately not a setting, it is never inherited by a new chat and never install-wide, it needs the new `can_auto_approve` privilege (off for non-admins, granted in Settings → Users) **and** a caller `request_is_a_person` accepts — so a bearer token (`B70`) and the agent's own loopback are both refused, an admin's agent included — the privilege is re-asked every run so a revoke lands on the next turn, and the chat says so on the composer chip and in the header, drawn from one state. **What it does not touch:** this amends **one row of Part 2's twenty-five**, and the other twenty-four are unchanged — measured across `a5ee5f8..8586638`, where the only changed lines naming one of them are comments. The approval store's seal, TTL, single-use consumption and owner binding, the MCP command/arg/env validation, the SSRF validators and pinned-IP transports, `OutboundHostLimiter`, `require_admin` and the `app_api` blocklist are untouched, and so are `POST_EXTERNAL_BLOCKED_EFFECTS`, `RUNG_BLOCKED_EFFECTS`, `TRUST_LADDER`, `FLOOR_STOP_CONDITIONS` and `validate_trust_ladder`. Auto is one flag beside the ladder and **not a fourth rung**, because a rung that dropped `AFTER_UNTRUSTED` would lift the floor for every chat at once and would fail `validate_trust_ladder` at import. Read against the four tests: the control holds unchanged for everyone who has not opted out, the opt-out is a person's own deliberate per-chat act behind a privilege an admin grants, the cost is stated where the person makes it and again in `CHANGELOG.md` under *Changed — read this before upgrading*, and 59 cases plus 14 of 14 mutations hold all of it — so `tracked`, not blocking. **The residual, not argued away:** no install can forbid Auto to its own admins (`B1342`), and whether any effect should still stop under Auto is the owner's open call (`B1341`) |
| `B1340` | tracked | security | integration prompt text still arms the post-external gate, so an install with one enabled integration still has the constant verdict `B1324` was filed for; over-arming, so it fails closed, and left as it was deliberately — `D-2026-10-09-01` §1 enumerates three stores (memory, notes, installed skills) and widening a security control's relaxation past what the owner wrote is not a lane's call. The same question `B1324` and `B1328` were, for the fourth store, and the arming table already asserts today's answer in both directions |
| `B1341` | tracked | decision | whether any effect should still stop in a chat set to Auto — filed rather than decided quietly, which is what the brief for `B1338` required. Auto ships as ruled, with no exception list and a case that drives every stop condition at every rung, so a quiet `if` cannot be added without reddening it; the argument for an exception is `DESTRUCTIVE`, the one class whose result a person cannot undo from inside Pantheon and whose blast radius is not bounded by the action's own arguments, and the argument against is the ruling's own, that a mode which keeps some asks is a mode nobody can describe in one sentence. Not a gate: Auto is off until a person turns it on, per chat, and `B1338` states the cost where they do |
| `B1342` | tracked | security | an admin cannot be forbidden Auto in their own install, because `core/auth.ADMIN_PRIVILEGES` flips every boolean in `DEFAULT_PRIVILEGES` to True, so an admin holds `can_auto_approve` by construction and nothing an admin can set takes it away from themselves. `can_auto_approve` is the one control over who may turn Auto on, and clearing it for every account does forbid Auto install-wide for every non-admin; what is uncovered is an install that wants the gate un-switchable even for admins — a shared or compliance install, or one where Auto should need a second person. The same shape as `can_use_workstation`, and the fix if wanted is a **floor rather than a default**, which is the one shape that cannot be read as an install-wide *enable* and so does not reopen what the ruling closed |

---

## 8. Versions

The ship line needs something to ship, and until 2026-09-17 this repository had
no answer to *which version is deployed*: no tag, no release, and
`APP_VERSION = "1.0.3"` — **Odysseus's** number, last moved by an upstream
maintainer in `3f2ad23` (*"align dev version with 1.0.3"*, cherry-picked from
upstream `e71f8ce`). Two different programs reported the same version.

**And it was worse than that, which `Law 14` is the reason we know.** Looking for
an existing version before writing one found **two**, disagreeing:
`scripts/_lib/cli.py:82` carries `VERSION = "0.1.0"` and twenty
`scripts/pantheon-*` executables print it for `--version`, so on one install
`pantheon-memory --version` said `0.1.0` — this project's own line — while
`GET /api/version` said `1.0.3`. The one nobody had noticed was the right one.

`B450` settles it. The scheme in full is in `CHANGELOG.md` § *Versions*; what
matters here:

- **The app was aligned to the CLI's number, not to a number somebody picked.**
  `src/constants.py:APP_VERSION` is `0.1.0`, which `/api/version`,
  `/api/readiness`, `pantheon_build_info`, the diagnostic bundle, OTLP
  `service.version` and `docker-publish.yml`'s image tag all read.
  `tests/test_one_version_string.py` pins the two declarations to each other and
  fails on a third; `pyproject.toml` carries a comment saying why it is not one.
- **`0.x` is a claim, not modesty.** `SECURITY.md` supports `main` and nothing
  else, and the rows in § 3 are what stood between this public repository and a
  stranger relying on it *(until 2026-10-02 this said "the public flip is gated on
  the fifteen rows above"; the repository is public, `D-2026-10-02-03`)*. `1.0.0` is
  the first release that is public, tagged and supported, and this is not that.
- **A tag per released version**, and `CHANGELOG.md` heads each section with the
  same string. Tag, heading and `APP_VERSION` agree or the tests fail. **`0.1.0`
  was never tagged** — this said, on 2026-09-17, that the tag would be cut on the
  merge, and it was not — so the release that carries `P20`–`P22` is **`0.2.0`**
  (`D-2026-10-02-04` §1), and its tag `v0.2.0` is cut on the owner's word, `D-2026-10-07-01` §1. Each version's
  release notes are `docs/release-notes/x.y.z.md` (`P10-12`).
- **Two things it does not answer, both filed rather than half-done.** `B453` —
  the version says which release line, not which commit, and everyone on `main`
  sits between tags; stamping a build ref needs the `Dockerfile` and the
  workflows. `B454` — the published image tag would move 1.0.3 → 0.1.0, which is
  backwards, and nobody has looked at whether any image exists.
