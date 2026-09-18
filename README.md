<h1 align="center">Pantheon</h1>

<p align="center">
  <strong>A self-hosted AI workspace.</strong><br>
  Chat, agents, research, documents, email, notes, calendar and local model serving —
  on hardware you own.
</p>

<p align="center">
  <img src="https://img.shields.io/badge/licence-AGPL--3.0--or--later-blue" alt="AGPL-3.0-or-later">
  <img src="https://img.shields.io/badge/status-early-orange" alt="Early">
  <img src="https://img.shields.io/badge/tests-9%2C580%20passing-brightgreen" alt="9,580 tests passing">
  <img src="https://img.shields.io/badge/docker-compose-2496ED?logo=docker&logoColor=white" alt="Docker Compose">
  <img src="https://img.shields.io/badge/python-FastAPI-009688?logo=fastapi&logoColor=white" alt="FastAPI">
  <img src="https://img.shields.io/badge/forked%20from-Odysseus-6E5494?logo=github&logoColor=white" alt="Forked from Odysseus">
</p>

<p align="center">
  <a href="https://github.com/ImPanick/pantheon/actions/workflows/ci.yml?query=branch%3Amain"><img src="https://github.com/ImPanick/pantheon/actions/workflows/ci.yml/badge.svg?branch=main" alt="CI"></a>
  <a href="https://github.com/ImPanick/pantheon/actions/workflows/secret-scan.yml?query=branch%3Amain"><img src="https://github.com/ImPanick/pantheon/actions/workflows/secret-scan.yml/badge.svg?branch=main" alt="Secret scan"></a>
  <a href="https://github.com/ImPanick/pantheon/actions/workflows/workflow-security.yml?query=branch%3Amain"><img src="https://github.com/ImPanick/pantheon/actions/workflows/workflow-security.yml/badge.svg?branch=main" alt="Workflow security"></a>
  <a href="https://github.com/ImPanick/pantheon/actions/workflows/dependency-review.yml?query=branch%3Amain"><img src="https://github.com/ImPanick/pantheon/actions/workflows/dependency-review.yml/badge.svg?branch=main" alt="Dependency review"></a>
  <a href="https://github.com/ImPanick/pantheon/actions/workflows/container-scan.yml?query=branch%3Amain"><img src="https://github.com/ImPanick/pantheon/actions/workflows/container-scan.yml/badge.svg?branch=main" alt="Container scan"></a>
</p>

<p align="center">
  <sub>
    Live status of the five merge-blocking pipelines on <code>main</code>. These are the real thing —
    click one and you get the run. <strong>A badge that says nothing is not a badge that says yes:</strong>
    while this repository is private the images render blank or broken to anyone not signed in with
    access, and a workflow that has never run reads <em>no status</em> rather than failing. What the
    badges can and cannot tell you, in each state, is written down in
    <a href="docs/security-ci.md#how-to-tell-whether-ci-is-actually-passing">the security CI guide</a>.
  </sub>
</p>

<p align="center">
  <a href="#quick-start">Quick start</a> ·
  <a href="#whats-inside">What's inside</a> ·
  <a href="#where-this-came-from">Where this came from</a> ·
  <a href="LEDGER.md"><strong>Proof ledger</strong></a> ·
  <a href="#switching-it-back-on">What we're fixing</a> ·
  <a href=".pantheon/ROADMAP.md">Roadmap</a> ·
  <a href="docs/setup.md">Setup guide</a>
</p>

---

## Quick start

You need Docker with the Compose v2 plugin (`docker compose`, not `docker-compose`) and
nothing else. Everything the app serves is in the image.

```bash
git clone https://github.com/ImPanick/pantheon.git
cd pantheon
cp .env.example .env
docker compose up -d --build
```

Open `http://localhost:7000` once the containers are healthy. The app binds to `127.0.0.1`
unless you set `APP_BIND`, and the port is `APP_PORT`. Your first admin password is generated
on first boot and printed in `docker compose logs pantheon` as `Temporary password:` — set
`PANTHEON_ADMIN_PASSWORD` in `.env` beforehand to choose your own.

`.env.example` is the whole configuration surface, commented; copying it unedited is a working
default.

Native installs, GPU setup, Windows and macOS, HTTPS and configuration are in the
[setup guide](docs/setup.md). `main` is the only branch here; upstream's `dev` is available on
the `upstream` remote.

---

## What's inside

- **Agents** — local or API models, tool execution, MCP servers, shell, filesystem, skills, memory
- **Model serving** — hardware-aware recommendations, downloads, and vLLM / llama.cpp / Ollama
  serving on this machine or a remote host over SSH
- **Deep research** — multi-step web research with source reading and report generation
- **Compare** — blind side-by-side model testing
- **Documents** — writing-first editor with AI edits, suggestions, Markdown, HTML, CSV
- **Email** — IMAP/SMTP with triage, tags, summaries, reminders and reply drafts
- **Notes, tasks, calendar** — reminders, todos, scheduled agent tasks, CalDAV sync
- **Extras** — gallery and image editor, sixteen themes and eight background patterns
  (seven of them animated) chosen independently of each other, web search,
  presets, sessions, 2FA

**What this fork has added, and what proves it, is in the [proof ledger](LEDGER.md)** — 26 claims,
each with where its number came from and a command you can run to check it. The short version:
the Brain rebuilt around a local embedding model that needs no service, an agent that can reach
the host it runs on behind a denylist it cannot edit, a checker in CI for each way a fact in this
project has been caught rotting, every outbound call paced, mailbox and service sign-in reduced to
one record type, and full AGPL attribution for code that shipped without it. The checker count is
a ledger claim rather than a sentence here, because it is read out of `.github/workflows/ci.yml`
and a number typed twice is a number that will disagree with itself.

---

## Where this came from

Pantheon is a fork of [Odysseus](https://github.com/pewdiepie-archdaemon/odysseus), a self-hosted
AI workspace with about two thousand commits behind it. We installed it, used it for real work,
and liked it.

Odysseus goes by two names. We cloned `pewdiepie-archdaemon/odysseus`; its own code and docs point
at `odysseus-dev/odysseus`. Both are the same upstream project and we credit both — see
[`NOTICE`](NOTICE).

Then we tried to change something small and ended up reading all 42,739 lines of the stylesheet.

`--accent` — the colour behind every highlight, hover state and drag handle — was referenced 813
times and defined nowhere. 206 style rules resolved to nothing. Nothing errored; the rules simply
never applied. It is defined now, and deliberately **not** in `:root`: a `:root` definition would
retire the `var(--accent, var(--red))` fallback the rest of the stylesheet leans on and hand all
sixteen themes the same accent. Each theme carries its own instead (`P1-01`).

Most of what we found after that was finished work that had never been connected:

- A **webhooks admin panel** with a complete backend and no interface. Two of its functions crash
  on the missing element inside a silent `try`, so nothing ever reported it.
- A **built-in skills editor**, fully implemented, behind one line reading `showBuiltin = false`.
- An **image upscaler** with a working backend and a local Real-ESRGAN model, and no button that
  calls it.
- **Plan mode** — a complete lifecycle — whose docked window has never existed, while three
  prompt strings tell the model that it does.
- Files the system doesn't recognise as text reach the model as the literal string
  `[Attached document file]` — no content at all — for `.go`, `.tsx`, `.yaml`, `.rs`, `.sql` and
  seven more.

The backends exist, the endpoints respond and the styling is written. Someone built the hard
part and moved on before the last step, which is a normal thing to happen to a project moving
quickly. We forked it to finish that last step.

---

## Switching it back on

We wrote a script that counts element lookups with nothing behind them. It found **78**, across
six subsystems, which is the point of writing the script rather than writing the list. What
follows is that original finding, kept because it is the honest picture of what a fork inherits.

**Run it today and it says 120.** That is not 42 regressions — it is the same script looking at
more than it used to. It has been widened three times since the 78 was taken, each time because
it turned out to be measuring less than it claimed: it read `static/js/` and never `static/app.js`,
the largest module in the product; it counted a lookup *described in a comment* as a lookup; and
it scored a lookup that indexes a map with a variable as clean, which on 2026-08-30 hid a live
defect where the agent reported opening a panel that had no button behind it. Closing that last
one moved the count from 9 to 124 with no product code changing. **So 78 and 120 are two
different measurements and the difference between them means nothing.** The ratchet is what
means something: `check-wiring.py` runs in CI at a ceiling that may come down and may not go up,
so a *new* unreachable id shows up the day it is written.

**Nor are the 120 all defects.** Classified by how each id is reached rather than by name, at
least 87 of the 124 measured at triage are guarded by construction — code that knows the markup
may be absent and returns early. That is a feature removed cleanly with its wiring left behind
on purpose, costing one null check. The triage is `P3-20`, and its finding was that driving the
number down is the wrong goal: it would mean deleting guarded code that costs nothing, which
this fork's first law forbids.

And a script that counts one shape of unreachability says nothing about the others: routes with
no caller, settings nothing reads, features whose only door is an undocumented keystroke. Those
are `check-unreachable.py` (`P3-15`) and the `H` rows.

| Area | Built, but unreachable |
|---|---|
| **Documents** | bulk archive, clone, delete, export; import; PDF AI-fill |
| **Image editor** | upscaler, edge feathering, resize and edge menus, background removal |
| **Model serving** | Ollama library browser, HuggingFace refresh, engine rebuild, hardware rescan |
| **Skills** | the skill-creation form |
| **Knowledge** | RAG document upload — the endpoint works and always has |
| **Email** | folder switching, attachment view, load-more |

Two of those six are wired: the image upscaler (`P2-22`) and RAG document upload (`P2-23`). The
rest are open rows in the tracker's `P2` section, which is where their current status lives.
Each is classified before anything changes — a stale reference to a renamed element gets fixed,
a real feature gets its markup and its event wiring, and code is deleted only when an audit has
proved it dead.

---

## Status

**668 tracked tasks, 422 done.** The tracker is [`.pantheon/ROADMAP.md`](.pantheon/ROADMAP.md) and
it is the only place work is tracked — one list, one progress area, validated by a script that
recounts every phase row against its own ticks. It exists because the summary line was once wrong
by nineteen and carried forward unread from entry to entry, because each author copied the line
above.

**Read that number with the trend beside it, because one line of it is misleading on its own.**
Over the last ten waves, *done* went **49.7% → 63.0%** and *open* went **192 → 229**: 237 rows
filed against 200 closed, a file-to-close ratio of **1.185**. Both movements are real and neither
is a counting error — the fraction converges because closure outruns filing as a share of the
total, and the open count grows because it does not outrun filing in absolute terms. **The open
count falls only when we stop looking**, since most of those 237 rows are defects found by sweeps
over code that was already here, not new work invented. What makes that survivable rather than
hopeless is a different number: of the last 40 backlog rows filed, **four** would block making
this repository public. The series, the classification and what counts as blocking are in
[`.pantheon/SHIP-LINE.md`](.pantheon/SHIP-LINE.md), and every figure in it is recomputed by
`.pantheon/ship-line.py --trend` rather than copied from the line above.

Test suite: **9,580 passing**, nothing red. The fourteen standing failures this fork
inherited and carried were cleared on 2026-09-12 — eight were a container missing dependencies
the project already declares, three were stale test stubs hiding behind broad `except` blocks,
and three were rules pinned to upstream's shape rather than this fork's.

Measured against the fork point `b4d1293`: **156 commits, 1,964 files changed, 175,966
insertions — 537 files added, 1,387 modified and 5 removed.** That last number is this fork's
first law as a measurement: *an elevation, not a rewrite — we add, never subtract.* All five
deletions are named and argued in the [ledger](LEDGER.md); the fifth was found by a failing
test nobody had looked at, and turned out to be upstream's logo wearing our filename.

## What's next

- **The wire** — the backend emits 39 distinct kinds of event per agent turn through one
  `if`/`else if` chain, and anything without a branch is dropped before it reaches the screen.
  Most of that phase has landed; the conspicuous gap left is that the metrics footer and the
  stats popup report a failed turn with the same shape and styling as a successful one.
- **The Workshop** — build a skill from scratch, wire automations on a canvas, create an MCP
  server end to end, with the model assisting throughout.
- **Persistent memory** — project knowledge that survives restarts, gains confidence as sources
  agree, and records contradictions instead of silently resolving them.
- **Identity and limits** — SSO against your own provider, roles rather than a single admin
  flag, and per-team quotas set without editing compose files.
- **Run receipts** — model, settings, tools, skills and retrievals recorded per run;
  re-runnable and comparable.
- **More themes** — new palettes, and subtle ASCII-art backgrounds as a ninth pattern, picked
  the same way the seven animated ones already are: independently of the palette.

Twenty phases, every task written down: [`.pantheon/ROADMAP.md`](.pantheon/ROADMAP.md).

---

## How we work

**Add, never subtract.** Features survive. This is an elevation of Odysseus rather than a
rewrite.

Twenty laws are written down in [`.pantheon/AGENTS.md`](.pantheon/AGENTS.md), each one added
after something went wrong, and nine of them cite the incident that produced them. Two examples:

> **Nothing ships half-wired.** A backend with no caller and a button with no handler get treated
> the same way. A script counts them and CI enforces the number.

> **If it needs a tutorial, it isn't finished.** A beta user with access to a more advanced
> version of a feature we're planning stopped using it because the learning curve was too steep
> and there were no docs.

Findings get checked by a second agent tasked with disproving them. In the first audit round the
reviewers overturned **twelve of twelve** contested findings, including on the phase's headline
task.

---

## On AI in this project

Large language models help build this. They orchestrate CI/CD, organise the DevOps work, and
write some of the code. It is stated here rather than left to be inferred, because a self-hosted
AI workspace should be plain about its own provenance.

**An engineer is in the loop at every stage of the development lifecycle.** The decisions are
made by a person, and the work is theirs to accept.

The rest of this repository is the argument for taking that seriously. Every change is a tracked
row with a `Verify:` line, and a row cannot be ticked on a claim nobody checked. Twenty-three
checkers run in CI, each one added after a specific defect got through — not designed in advance.
A test earns its place by failing on the tree as it stood *before* the fix, and mutation testing
is what proves it would. [`.pantheon/ROADMAP.md`](.pantheon/ROADMAP.md) records the mistakes with
the same detail as the fixes, including a number of occasions where a claim made *in this
repository* turned out to be false and had to be corrected in public.

**Some bugs will still get through.** They get sought out and squashed. If you find one, open an
issue — that is the fastest way to put it in front of someone.

---

## Security

- Keep `AUTH_ENABLED=true` for any network-accessible deployment.
- Keep `LOCALHOST_BYPASS=false` outside local development.
- Don't expose raw model or service ports publicly.

If you are upgrading rather than installing, read
[Changed — read this before upgrading](CHANGELOG.md#changed--read-this-before-upgrading)
first. `AUTH_ENABLED=0`, `=no` and `=off` used to leave authentication **on**; they turn it off
now, which is what an operator who typed them meant and is not what their instance has been
doing.

This fork removes restrictions, so it's worth naming the ones it doesn't. About thirty controls
are on a never-lift list: authentication, CSRF posture, the approval store's seal, path-traversal
and SSRF guards, command-injection guards, secrets redaction, and the extension allowlist on
uploaded fonts, which is the one place an uploaded file is served back.

**Dependencies.** `.github/dependabot.yml` opens grouped weekly pull requests for the Python and
npm packages, the Docker base image, and the pinned versions of the GitHub Actions themselves. On
every pull request, dependency review blocks a change that pulls in a package with a known
advisory; `pip-audit` reports advisories in what is already installed and deliberately does not
block, because it flags things no particular pull request introduced. Front-end libraries are
vendored rather than fetched at runtime, and `.pantheon/check-licences.py` treats that inventory
as an allowlist — a file under `static/lib/`, `static/fonts/`, `static/icons/` or `library/` that
is not listed in [`CREDITS.md`](CREDITS.md) fails the build, so adding one means having read its
licence. What each check does, whether it can block a merge, and where its findings land is in
the [security CI guide](docs/security-ci.md).

Deployment details: [setup guide](docs/setup.md#security-notes).

---

## Contributing

Useful right now: fresh-install testing, provider setup bugs, and tasks from
[`.pantheon/ROADMAP.md`](.pantheon/ROADMAP.md). Read
[`.pantheon/AGENTS.md`](.pantheon/AGENTS.md) first — it's short. See
[CONTRIBUTING.md](CONTRIBUTING.md) for conventions.

For Odysseus itself, contribute
[upstream](https://github.com/pewdiepie-archdaemon/odysseus). That project is active and this one
is downstream of it.

---

## Licence

**AGPL-3.0-or-later** — see [LICENSE](LICENSE).

Every file of program text in this repository carries
`SPDX-License-Identifier: AGPL-3.0-or-later`, so a single file in a search result or a diff
says what it is under without anyone having to find this page. `LICENSE` is the AGPL text
verbatim and stays that way — the document's own terms forbid changing it — so the *or-later*
qualifier is stated here, in [`NOTICE`](NOTICE), and in those headers. Vendored third-party
files keep their own licences and are deliberately not stamped;
[`CREDITS.md`](CREDITS.md) lists every one.

Pantheon is free software and isn't sold. We'd rather nobody else sold it either, though the
AGPL doesn't allow that restriction and we won't pretend otherwise. Use it internally at your
company if it's useful.

Pantheon is a modified version of Odysseus, forked from commit `b4d1293` on 24 August 2026 and
released under the same licence. It is not affiliated with or endorsed by the Odysseus project,
so please don't send them issues from here.

Credits and third-party licences: [`CREDITS.md`](CREDITS.md), [`NOTICE`](NOTICE).
