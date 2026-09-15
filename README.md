<h1 align="center">Pantheon</h1>

<p align="center">
  <strong>A self-hosted AI workspace.</strong><br>
  Chat, agents, research, documents, email, notes, calendar and local model serving —
  on hardware you own.
</p>

<p align="center">
  <img src="https://img.shields.io/badge/licence-AGPL--3.0--or--later-blue" alt="AGPL-3.0-or-later">
  <img src="https://img.shields.io/badge/status-early-orange" alt="Early">
  <img src="https://img.shields.io/badge/tests-9%2C416%20passing-brightgreen" alt="9,416 tests passing">
  <img src="https://img.shields.io/badge/docker-compose-2496ED?logo=docker&logoColor=white" alt="Docker Compose">
  <img src="https://img.shields.io/badge/python-FastAPI-009688?logo=fastapi&logoColor=white" alt="FastAPI">
  <img src="https://img.shields.io/badge/forked%20from-Odysseus-6E5494?logo=github&logoColor=white" alt="Forked from Odysseus">
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

```bash
git clone https://github.com/ImPanick/pantheon.git
cd pantheon
cp .env.example .env
docker compose up -d --build
```

Open `http://localhost:7000` once the containers are healthy. Your first admin password is
printed in `docker compose logs pantheon`.

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
the host it runs on behind a denylist it cannot edit, eighteen checkers in CI that upstream does
not have, every outbound call paced, mailbox and service sign-in reduced to one record type, and
full AGPL attribution for code that shipped without it.

---

## Where this came from

Pantheon is a fork of [Odysseus](https://github.com/pewdiepie-archdaemon/odysseus), a self-hosted
AI workspace with about two thousand commits behind it. We installed it, used it for real work,
and liked it.

Odysseus goes by two names. We cloned `pewdiepie-archdaemon/odysseus`; its own code and docs point
at `odysseus-dev/odysseus`. Both are the same upstream project and we credit both — see
[`NOTICE`](NOTICE).

Then we tried to change something small and ended up reading all 42,739 lines of the stylesheet.

`--accent` — the colour behind every highlight, hover state and drag handle — is referenced 813
times and defined nowhere. 206 style rules resolve to nothing. Nothing errors; the rules simply
never apply.

Most of what we found after that is finished work that never got connected:

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
six subsystems — and **that number is now 2**, which is the point of writing the script rather
than the list. What follows is the original finding, kept because it is the honest picture of
what a fork inherits; the notes say where each one now stands.

Two cautions the table cannot carry. The count only measures lookups whose argument is a
*string literal* — a lookup that indexes a map with a variable scores as clean, and on
2026-08-30 exactly that hid a live defect where the agent reported opening a panel that had no
button behind it. And a script that counts one shape of unreachability says nothing about the
others: routes with no caller, settings nothing reads, features whose only door is an
undocumented keystroke. Those are `P3-15` and the `H` rows.

| Area | Built, but unreachable |
|---|---|
| **Documents** | bulk archive, clone, delete, export; import; PDF AI-fill |
| **Image editor** | upscaler, edge feathering, resize and edge menus, background removal |
| **Model serving** | Ollama library browser, HuggingFace refresh, engine rebuild, hardware rescan |
| **Skills** | the skill-creation form |
| **Knowledge** | RAG document upload — the endpoint works and always has |
| **Email** | folder switching, attachment view, load-more |

Each is classified before anything changes: a stale reference to a renamed element gets fixed,
dead code gets deleted, a real feature gets its markup and its event wiring. `check-wiring.py`
runs in CI and the count only goes down.

---

## Status

**491 tracked tasks, 276 done.** The tracker is [`.pantheon/ROADMAP.md`](.pantheon/ROADMAP.md) and
it is the only place work is tracked — one list, one progress area, validated by a script that
recounts every phase row against its own ticks. It exists because the summary line was once wrong
by nineteen and carried forward unread from entry to entry, because each author copied the line
above.

Test suite: **9,416 passing**, nothing red. The fourteen standing failures this fork
inherited and carried were cleared on 2026-09-12 — eight were a container missing dependencies
the project already declares, three were stale test stubs hiding behind broad `except` blocks,
and three were rules pinned to upstream's shape rather than this fork's.

Measured against the fork point `b4d1293` (2026-08-20): **156 commits, 1,964 files changed,
175,966 insertions — 537 files added, 1,387 modified and 4 removed.** That last number is this
fork's first law as a measurement: *an elevation, not a rewrite — we add, never subtract.* All
four deletions are named and argued in the [ledger](LEDGER.md).

## What's next

- **The wire** — the backend streams 39 kinds of event per agent turn and discards
  more than thirty before display. A failed turn currently renders the same as a successful one.
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

Fifteen phases, every task written down: [`.pantheon/ROADMAP.md`](.pantheon/ROADMAP.md).

---

## How we work

**Add, never subtract.** Features survive. This is an elevation of Odysseus rather than a
rewrite.

Fifteen rules are written down in [`.pantheon/AGENTS.md`](.pantheon/AGENTS.md), each one added
after something went wrong. Two examples:

> **Nothing ships half-wired.** A backend with no caller and a button with no handler get treated
> the same way. A script counts them and CI enforces the number.

> **If it needs a tutorial, it isn't finished.** A beta user with access to a more advanced
> version of a feature we're planning stopped using it because the learning curve was too steep
> and there were no docs.

Findings get checked by a second agent tasked with disproving them. In the first audit round the
reviewers overturned **twelve of twelve** contested findings, including on the phase's headline
task.

---

## Security

- Keep `AUTH_ENABLED=true` for any network-accessible deployment.
- Keep `LOCALHOST_BYPASS=false` outside local development.
- Don't expose raw model or service ports publicly.

This fork removes restrictions, so it's worth naming the ones it doesn't. About thirty controls
are on a never-lift list: authentication, CSRF posture, the approval store's seal, path-traversal
and SSRF guards, command-injection guards, secrets redaction, and the extension allowlist on
uploaded fonts, which is the one place an uploaded file is served back.

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
