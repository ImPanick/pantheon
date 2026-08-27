<h1 align="center">Pantheon</h1>

<p align="center">
  A self-hosted AI workspace — chat, agents, research, documents, email, notes,
  calendar and local model workflows, on hardware you own.
</p>

<p align="center">
  <a href="#quick-start">Quick start</a> ·
  <a href="#we-saw-odysseus-and-fell-in-love">The story</a> ·
  <a href="#what-well-have-when-were-done">Where it's going</a> ·
  <a href=".pantheon/ROADMAP.md">The tracker</a>
</p>

---

## We saw Odysseus, and fell in love

[Odysseus](https://github.com/pewdiepie-archdaemon/odysseus) is a genuinely ambitious piece of
software. A self-hosted AI workspace with a real agent loop, real tool execution, a
hardware-aware model server, deep research, a document editor, IMAP mail, CalDAV calendar, MCP
support, sixteen themes — and animated backgrounds that change depending on which theme you
pick, which is the kind of detail people only add when they care.

Two thousand commits. It runs. We installed it and used it for real work.

Then we started reading it.

Not looking for problems — trying to change something small. And the small thing led to a
bigger thing, and eventually to reading all **41,401 lines** of one stylesheet in a single
sitting. What we found there changed what this project is.

---

## What we found

`--accent` — the colour that draws the highlights, the hover states, the active tabs, the
handles you drag — is referenced **799 times**, and defined nowhere. Around three hundred
carefully written style rules were quietly resolving to nothing at all. Not broken. Not
throwing errors. Just… not applied. Somebody designed all of that and never got to switch it on.

That turned out to be the pattern.

**A webhooks admin panel with a complete, working backend and no interface whatsoever.** Two of
its functions crash on a missing element inside a silent `try`, which is precisely why nobody
ever noticed it wasn't there.

**A built-in skills editor, fully implemented**, sitting behind a single line that reads
`const showBuiltin = false;`.

**An image upscaler** with a working backend and a local Real-ESRGAN model behind it, and no
button anywhere that calls it.

**Plan mode** — a complete lifecycle, properly built — whose docked plan window has never
existed, while three separate prompt strings cheerfully tell the model that it does.

And the one that stings: files you upload that the system doesn't recognise as text don't lose
their syntax highlighting. They arrive at the model as the literal string
`[Attached document file]`. **Zero bytes of your actual file.** Silently, for `.go`, `.tsx`,
`.yaml`, `.rs`, `.sql`, and seven more.

None of this is incompetence. It's the fingerprint of a project moving fast — someone builds
the difficult half, ships it, and the last ten percent never happens. The expensive work is
*already paid for*. It just isn't connected.

So we forked it. Not to replace Odysseus, and not because it's bad. Because it's good, and it
deserves to be finished.

---

## How we're doing it

**One rule above all the others: add, never subtract.** Every feature survives. Nothing gets
deleted because it's inconvenient. This is an elevation, not a rewrite — the wheel is already
invented here, and we're making it rounder.

Beyond that, we wrote down fifteen rules, and every one of them came from something that
actually went wrong while we worked. A few worth sharing, because they're the reason to trust
anything else on this page:

> **Nothing ships half-wired.** A backend with no caller and a button with no handler are the
> same disease. There's a script that counts them, it runs in CI, and the number is allowed to
> go down and never up.

> **A number without a stated scope is not a number.** Is `--accent` used 799 times, or 950, or
> 1,014? All three are true — they're counting different things. Only one answers the question.

> **If it needs a tutorial, it isn't finished.** We watched someone with beta access to a far
> more advanced version of a feature we're planning give up on it, because nobody had written
> the docs and the learning curve was too steep. The capability was real. The adoption was zero.

Every finding on this page was checked by a second agent whose only job was to prove the first
one wrong. In the first audit round, **the sceptics won twelve out of twelve** — including
proving that our own headline task was wrong in three separate ways. That's why we do it that
way, and it's why the numbers here are worth reading.

---

## Where we actually are

**288 tracked tasks. 30 finished.** That's not modesty, it's the tracker, and it doesn't round
up.

Twenty of those were setup and the rename. **Ten are real fixes**, already running:

- Files you upload now reach the model as **content**, not as a banner.
- The upload type blocklist is gone — the one that blocked executables while leaving `.svg`,
  the actual attack vector, wide open.
- A real limit on files-per-upload, which somehow never existed on the server side.
- Uploads get a proper sandbox policy — placed where it can actually reach the browser, which
  it turns out no route in this application can do.
- Four blocks of dead configuration and a validator nothing ever called, removed.
- A prompt that forbade a shell technique on one line and instructed the model to use it seven
  lines later.
- *"Your account is not allowed to can use research."* Fixed, and yes, that was real.

Full test suite: **5,742 passing, zero regressions.**

---

## What we'll have when we're done

**A glass box.** The backend already streams around fifty kinds of event about what your agent
is doing, and throws more than thirty of them away before you see any of it. Today a failed
turn looks exactly like a successful one. It shouldn't.

**A workshop.** Build a skill from nothing, wire automations together on a canvas, and create an
MCP server end to end — with the model helping at every step. The biggest single addition, and
the reason this is a fork rather than a patch.

**A memory that lasts.** Not a pretty graph of glowing dots — we tried the one that exists and
it's beautiful and nobody uses it. Something plainer and far more useful: knowledge about
*your projects* that survives every session, model swap and restart, that gets more confident as
things confirm it, that tells you when two things it learned contradict each other, and that you
can read, search and correct like a document instead of navigating like a star map.

**A harness you can hand to other people.** Single sign-on against whatever identity provider
you already run. Real roles instead of one admin bit checked in eighty-four places. Limits an
operator can actually set, per team, without editing a compose file and rebuilding.

**And an honest one.** Every run leaves a receipt — the model, the settings, the tools it had,
the skills it used, what it retrieved. Re-runnable, comparable, and portable enough to hand to
someone else when something goes strange.

The full plan is in [`.pantheon/ROADMAP.md`](.pantheon/ROADMAP.md) — fifteen phases, every task
written down, every finished one traceable to the commit that did it.

---

## What works today

Everything Odysseus does, because Pantheon inherits all of it:

**Chat and agents** with local or API models, tools, MCP, files, shell, skills and memory ·
**a model server** with hardware-aware recommendations, downloads and serving, local or over SSH ·
**deep research** across multiple steps with real source reading ·
**blind model comparison** ·
**a writing-first document editor** with AI edits and suggestions ·
**IMAP/SMTP email** with triage, summaries and reply drafts ·
**notes, tasks and a CalDAV calendar** ·
plus a gallery and image editor, sixteen themes, web search, presets, sessions and 2FA.

And what the fork has added so far: guardrail caps lifted for self-hosted inference while cloud
APIs keep theirs, an agent scratchpad, and endpoint probe auth.

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

Native installs, GPU notes, Windows and macOS, HTTPS and configuration all live in the
[setup guide](docs/setup.md). `main` is the only branch here; upstream's `dev` is available
through the `upstream` remote.

---

## Security

This is a self-hosted workspace with powerful local tools. Keep auth on, keep private data out
of Git, and don't expose raw model or service ports to the internet.

- Keep `AUTH_ENABLED=true` on anything reachable over a network.
- Keep `LOCALHOST_BYPASS=false` outside local development.

We remove a lot of restrictions in this fork, so it's worth being precise about which ones. About
thirty controls are on a **never-lift list** — authentication, CSRF posture, the approval store's
seal and single-use consumption, path traversal and SSRF guards, command-injection guards,
secrets redaction, and the extension allowlist on uploaded fonts, which is the one place an
uploaded file really does get served back. Those don't move. What we remove is the theatre
standing in front of them.

Deployment details: [setup guide](docs/setup.md#security-notes).

---

## Contributing

Early days, moving fast. The most useful things right now are fresh-install testing, provider
setup bugs, and picking up a task from [`.pantheon/ROADMAP.md`](.pantheon/ROADMAP.md) — read
[`.pantheon/AGENTS.md`](.pantheon/AGENTS.md) first, it's the working agreement and it's short.
See also [CONTRIBUTING.md](CONTRIBUTING.md).

If you're here for Odysseus itself, contribute
[upstream](https://github.com/pewdiepie-archdaemon/odysseus). That project is alive, and this one
is downstream of it.

---

## Licence

**AGPL-3.0-or-later** — see [LICENSE](LICENSE).

Pantheon is free software and I don't sell it. I'd rather you didn't either, though the AGPL
doesn't let me require that and I'm not going to pretend otherwise. Use it inside your company
if it's useful to you. That's what it's for.

Credits and third-party licences are in [`CREDITS.md`](CREDITS.md) and
[`ACKNOWLEDGMENTS.md`](ACKNOWLEDGMENTS.md). The modification notice the licence requires is in
[`NOTICE`](NOTICE).

Pantheon is a **modified version of Odysseus**, forked from commit `b4d1293` on **24 August
2026** and released under the same licence. It isn't affiliated with or endorsed by the Odysseus
project — please don't send them our bugs.

**Built on [Odysseus](https://github.com/pewdiepie-archdaemon/odysseus).** It got the hard parts
right first, and we wouldn't be here without it.
