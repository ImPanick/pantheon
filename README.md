<h1 align="center">Pantheon</h1>

<p align="center">
  A self-hosted AI workspace — chat, agents, research, documents, email, notes,
  calendar and local model workflows, on hardware you own.
</p>

<p align="center">
  <a href="#quick-start">Quick start</a> ·
  <a href="#we-saw-odysseus-and-fell-in-love">The story</a> ·
  <a href="#what-were-switching-back-on">What we're switching on</a> ·
  <a href=".pantheon/ROADMAP.md">The tracker</a>
</p>

---

## We saw Odysseus, and fell in love

[Odysseus](https://github.com/pewdiepie-archdaemon/odysseus) is a genuinely ambitious piece of
software. A self-hosted AI workspace with a real agent loop, real tool execution, a
hardware-aware model server, deep research, a document editor, IMAP mail, CalDAV calendar, MCP
support, sixteen themes — and animated backgrounds that change with the theme you pick, which is
the kind of detail people only add when they care.

Two thousand commits. It runs. We used it for real work — then tried to change something
small, and ended up reading all **41,401 lines** of one stylesheet in a sitting.

---

## What we found

`--accent` — the colour behind every highlight, hover state and drag handle — is referenced
**799 times and defined nowhere.** Roughly three hundred carefully written style rules resolve
to nothing. Not broken, not erroring. Somebody designed all of that and never got to switch it
on.

That turned out to be the pattern:

- **A webhooks admin panel** with a complete backend and no interface at all. Two of its
  functions crash on the missing element inside a silent `try`, which is exactly why nobody
  noticed.
- **A built-in skills editor,** fully implemented, behind one line reading `showBuiltin = false`.
- **An image upscaler** with a working backend and a local Real-ESRGAN model, and no button
  anywhere that calls it.
- **Plan mode** — a complete lifecycle — whose docked window has never existed, while three
  prompt strings tell the model that it does.
- And the one that stings: files the system doesn't recognise as text reach the model as the
  literal string `[Attached document file]`. **Zero bytes of your file.** Silently, for `.go`,
  `.tsx`, `.yaml`, `.rs`, `.sql` and seven more.

This isn't incompetence. It's the fingerprint of a project moving fast — someone builds the
difficult half, ships it, and the last ten percent never happens. **The expensive work is
already paid for. It just isn't connected.**

So we forked it. Not to replace Odysseus, and not because it's bad. Because it's good, and it
deserves to be finished.

---

## What we're switching back on

We wrote a script that counts buttons with no element behind them. It found **78**, across seven
subsystems, and every one is a feature someone built and never plugged in:

| | What was sitting there unreachable |
|---|---|
| **Documents** | bulk archive, clone, delete and export; the import button; the PDF AI-fill action |
| **Image editor** | the upscaler, edge feathering, the resize and edge menus, background removal |
| **Model server** | the Ollama library browser, HuggingFace refresh, engine rebuild, hardware rescan |
| **Skills** | the entire skill-creation form |
| **Knowledge** | RAG document upload — the endpoint works and has always worked |
| **Email** | folder switching, attachment view, load-more |

Each gets classified first: a stale reference to a renamed element is fixed, dead code is
deleted, a real feature gets its markup *and* its wiring. The count only goes down, and CI
enforces that.

---

## How we work

**Add, never subtract.** Every feature survives — this is an elevation, not a rewrite. Beyond
that, fifteen written rules, each one from something that actually went wrong while we worked:

> **Nothing ships half-wired.** A backend with no caller and a button with no handler are the
> same disease. A script counts them, CI enforces the number, and it only goes down.

> **If it needs a tutorial, it isn't finished.** We watched someone with beta access to a far
> more advanced version of a feature we're planning give up on it, because the learning curve
> was too steep and nobody had written the docs. The capability was real. The adoption was zero.

Every finding is checked by a second agent whose only job is proving the first one wrong. In
the first audit round **the sceptics won twelve out of twelve** — including against our own
headline task. That's why the numbers here are worth reading.

---

## Where we actually are

**288 tracked tasks. 30 finished.** That's the tracker, and it doesn't round up. Twenty were
setup and the rename. **Ten are real fixes, already running:**

- Uploaded files reach the model as **content** instead of a banner.
- The upload blocklist is gone — the one blocking executables while leaving `.svg`, the actual
  attack vector, wide open.
- A real files-per-upload limit, which never existed server-side.
- Uploads get a sandbox policy, placed where it can actually reach the browser — which it turns
  out no route in this app could do.
- Four blocks of dead config and a validator nothing called, removed.
- A prompt that forbade a shell technique on one line and instructed the model to use it seven
  lines later.
- *"Your account is not allowed to can use research."* Yes, that was real.

Full suite: **5,742 passing, zero regressions.**

---

## Where it's going

**A glass box.** The backend streams ~50 kinds of event about what your agent is doing and
discards 30+ before you see them. A failed turn currently looks identical to a successful one.

**A workshop.** Build a skill from nothing, wire automations on a canvas, create an MCP server
end to end — with the model helping throughout.

**Memory that lasts.** Not a graph of glowing dots; we tried that one and nobody uses it.
Knowledge about *your projects* that survives every restart, grows more confident as things
confirm it, and flags its own contradictions.

**A harness you can hand to other people.** SSO against your own identity provider, real roles
instead of one admin bit checked in eighty-four places, and limits set per team without editing
compose and rebuilding.

**Receipts.** Every run records its model, settings, tools, skills and retrievals — re-runnable,
comparable, portable.

Fifteen phases, every task written down: [`.pantheon/ROADMAP.md`](.pantheon/ROADMAP.md).

---

## What works today

Everything Odysseus does, because Pantheon inherits all of it — agents with tools, MCP, shell,
skills and memory; a model server with hardware-aware serving, local or over SSH; deep research;
blind model comparison; a document editor with AI edits; IMAP/SMTP email with triage; notes,
tasks and CalDAV calendar; a gallery and image editor; sixteen themes, web search, presets and
2FA.

Plus what the fork adds: guardrail caps lifted for self-hosted inference while cloud APIs keep
theirs, an agent scratchpad, and endpoint probe auth.

---

## Quick start

```bash
git clone https://github.com/ImPanick/pantheon.git
cd pantheon
cp .env.example .env
docker compose up -d --build
```

Open `http://localhost:7000` once the containers are healthy. Your first admin password is in
`docker compose logs pantheon`.

Native installs, GPU notes, Windows and macOS, HTTPS and configuration: the
[setup guide](docs/setup.md). `main` is the only branch here; upstream's `dev` is on the
`upstream` remote.

---

## Security

Keep auth on, keep private data out of Git, and don't expose raw model or service ports to the
internet.

- `AUTH_ENABLED=true` on anything reachable over a network.
- `LOCALHOST_BYPASS=false` outside local development.

We remove a lot of restrictions here, so it's worth naming the ones we don't. About thirty
controls are on a **never-lift list**: authentication, CSRF posture, the approval store's seal,
path-traversal and SSRF guards, command-injection guards, secrets redaction, and the extension
allowlist on uploaded fonts — the one place an uploaded file really is served back. **What we
remove is the theatre standing in front of those.**

Details: [setup guide](docs/setup.md#security-notes).

---

## Contributing

Most useful right now: fresh-install testing, provider setup bugs, and picking up a task from
[`.pantheon/ROADMAP.md`](.pantheon/ROADMAP.md). Read
[`.pantheon/AGENTS.md`](.pantheon/AGENTS.md) first — it's short. See also
[CONTRIBUTING.md](CONTRIBUTING.md).

Here for Odysseus itself? Contribute
[upstream](https://github.com/pewdiepie-archdaemon/odysseus). That project is alive; this one is
downstream of it.

---

## Licence

**AGPL-3.0-or-later** — see [LICENSE](LICENSE).

Pantheon is free software and I don't sell it. I'd rather you didn't either, though the AGPL
doesn't let me require that and I won't pretend otherwise. Use it inside your company if it's
useful — that's what it's for.

Credits and third-party licences: [`CREDITS.md`](CREDITS.md), [`ACKNOWLEDGMENTS.md`](ACKNOWLEDGMENTS.md),
[`NOTICE`](NOTICE).

Pantheon is a **modified version of Odysseus**, forked from commit `b4d1293` on **24 August
2026** and released under the same licence. Not affiliated with or endorsed by the Odysseus
project — please don't send them our bugs.

**Built on [Odysseus](https://github.com/pewdiepie-archdaemon/odysseus).** It got the hard parts
right first.
