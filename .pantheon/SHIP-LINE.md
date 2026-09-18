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

## 3. The blocking set — fifteen rows, of which two are now met

Fifteen of 234 open rows when this was written; **`P0-17` and `P6-08` closed on
2026-09-18 and are marked `landed` in the register rather than deleted, because a line that
quietly loses its met gates cannot be audited.** Thirteen stand. One line of reasoning each;
the row carries the
measurement. Four are security, four are a false documented claim, three are a
licence obligation, two are an action rather than a commit, one is a defect a
first-time user hits, and one is the release artefact.

### Security — the control does not hold (4)

- **`B370`** — `/static/wave-variants.html` and `/static/whirlpool-variants.html`
  answer **200 to a client with no cookie** under `AUTH_ENABLED=true`, while `/`,
  `/docs` and `/backgrounds` all `302 → /login`. The exposure is small and the row
  says so; what is not acceptable at publication is an auth boundary with a hole
  and no written exemption beside `AUTH_EXEMPT_PREFIXES`. Either half of its
  `Verify:` closes this.
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
- **`B349`** — the fork date is `2026-08-24` in `NOTICE` (*"Date of fork"*),
  `CREDITS.md`, `CHANGELOG.md` and `README.md`, and `2026-08-20` in
  `.pantheon/ledger/claims.py` — which renders into the published `LEDGER.md`
  header. Two attribution surfaces, one event, two dates. The row's later note
  makes the resolution likely (they are two different facts) and that is exactly
  why it is cheap and why it needs the owner.

### A documented claim is false (3)

- **`B71`** — `docs/pantheon-wordmark.png`, `docs/pantheon.jpg` and
  `docs/pantheon-browser.jpg` are upstream's artwork under this fork's filenames,
  and `build-macos-app.sh:31-37` ships `docs/pantheon.jpg` **as the macOS app
  icon**. A published repository whose desktop icon is a picture of the other
  product is a false claim in the loudest available place.
- **`B411`** — four claims in the generated, published `LEDGER.md` state a number
  their own `repro` command does not print: `tracker` 370 vs 376, `spdx` 1,541 vs
  1,653, `credits` 13 vs 43, and `fan-out`'s 40. The ledger's own preamble sets
  the standard they fail.
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
  this worktree does not own.

### A first-time user hits it (1)

- **`B400`** — a `.docx` imported from the Documents panel's own menu item is
  stored as its zip bytes, while the same file dropped on the library gives
  markdown. Three clicks apart, no error, no refusal. **This is the softest call
  in the set** — the alternative reading is that it is a `Law 13` third-copy row
  like `B401`, which is registered as tracked. It is here because `.docx` is the
  single most likely file a stranger opens this product with, and because the
  failure is silent.

### Must happen before the flip, and is not a commit (2)

- **`P10-11`** — run the `SECURITY.md` fork checklist: `git status --short`, the
  ignore check, the secret grep. A secret pushed to a public repository is not
  recoverable by deleting it.
- **`B357`** — five links in four files send vulnerability reporters to
  `…/security/advisories/new`, which 404s unless **Private vulnerability
  reporting** is switched on. The row could not verify it and says so. It is a
  repository setting, and `docs/security-ci.md` already lists it under
  *"One-time settings to turn on"*.

### The release artefact (1)

- **`P10-12`** — release notes leading with the Odysseus credit and enumerating
  the breaking renames. **The version half of this landed today** (`B450`):
  `CHANGELOG.md` has a `0.1.0` section, the tree carries one version string that
  is Pantheon's, and § *Versions* says how the three agree. What is left is the
  rename enumeration and the credit paragraph. It is in the set because a
  stranger's first question about a public repository is *which version is this*,
  and until today the answer was another project's number.

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
| `P0-16` | blocking | licence | Apache-2.0 §4(b): the `services/search/` point needs the copyright holder's call, before publication |
| `P0-17` | landed | licence | AGPL §13 source link — attaches at network offer; built and dark |
| `B349` | blocking | licence | `NOTICE` and the published `LEDGER.md` give two dates for one fork |
| `B370` | blocking | security | two `/static` pages answer 200 with no cookie; no exemption written down |
| `P11-01` | blocking | security | `privs.get(key, True)` fails open and non-admin accounts are reachable today |
| `P2-21` | blocking | security | two `builtin` GETs make no auth call beside a `require_admin` PUT and DELETE |
| `P11-02d` | blocking | security | six route files whose gating is unreconciled — an unknown on an auth surface |
| `B71` | blocking | claim | upstream's artwork under this fork's filenames, and it is the macOS app icon |
| `B411` | blocking | claim | four numbers in the published ledger do not print from their own repro |
| `P6-08` | landed | claim | `.env.example` and three compose files document an env override that is dead code |
| `B400` | blocking | first-ten | a `.docx` imported from the Documents panel is stored as zip bytes, silently |
| `P10-11` | blocking | pre-flip | the secret grep has not been run and a pushed secret is unrecoverable |
| `B357` | blocking | pre-flip | five links route reporters to an advisory form nobody has confirmed is on |
| `P10-12` | blocking | artefact | release notes; the version half landed under `B450`, the renames have not |
| `B492` | tracked | second-line | every throttled host but the mailbox is admin-only; an operator surface, not a stranger's first ten minutes |
| `B505` | tracked | coverage | the tool eval is not in CI — a gap in enforcement, not a defect a user meets |
| `P0-13` | tracked | identity | a missing mark is not a gate — shipping upstream's is, and that is `B71` |
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
| `B452` | blocking | claim | `SECURITY.md` says the sha is the only version identifier; two existed |
| `B451` | tracked | owner | this proposal; the line is the owner's to draw and they have not |
| `B453` | tracked | build-ref | *which commit* needs a build stamp, and that needs files this row cannot touch |
| `B454` | tracked | registry | the image tag moves backwards; probably academic and nobody has looked |
| `B455` | tracked | tracker | twelve open rows are not available work; the remedy is the ruling `B451` awaits |

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
  else, and the public flip is gated on the fifteen rows above. `1.0.0` is the
  first release that is public, tagged and supported, and this is not that.
- **A tag per released version**, and `CHANGELOG.md` heads each section with the
  same string. Tag, heading and `APP_VERSION` agree or the tests fail. `0.1.0` is
  not tagged in this tree: a release tag points at the commit that is released,
  and this is a worktree tip awaiting a merge, so the tag is cut on the merge.
- **Two things it does not answer, both filed rather than half-done.** `B453` —
  the version says which release line, not which commit, and everyone on `main`
  sits between tags; stamping a build ref needs the `Dockerfile` and the
  workflows. `B454` — the published image tag would move 1.0.3 → 0.1.0, which is
  backwards, and nobody has looked at whether any image exists.
