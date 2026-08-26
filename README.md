<h1 align="center">Pantheon</h1>

<p align="center">
  A self-hosted AI workspace — chat, agents, research, documents, email, notes,
  calendar and local model workflows, on hardware you own.
</p>

<p align="center">
  <a href="#quick-start">Quick start</a> ·
  <a href="#where-this-came-from">Where this came from</a> ·
  <a href="#why-the-fork-exists">Why the fork exists</a> ·
  <a href="#what-pantheon-is-building">What it's building</a> ·
  <a href=".pantheon/ROADMAP.md">Tracker</a>
</p>

---

> **Status: early, and honest about it.** Pantheon is a fork of
> [Odysseus](https://github.com/pewdiepie-archdaemon/odysseus) taken at `b4d1293` on
> 2026-08-24. Everything Odysseus does, Pantheon does — the fork inherits a working
> product. What is new so far is the audit, the plan, and the rename. **10 of 222
> planned tasks are complete**, and all 10 are the rename. The live tracker is
> [`.pantheon/ROADMAP.md`](.pantheon/ROADMAP.md); it does not round up.
>
> Every finding on this page is cited to a file and a line, and every one of them was
> checked against the source by an adversarial pass whose job was to prove it wrong.
> Several did not survive. Those are not on this page.

---

## Where this came from

**Pantheon exists because Odysseus is good.**

[Odysseus](https://github.com/pewdiepie-archdaemon/odysseus) is a genuinely ambitious
piece of software — a self-hosted AI workspace with a real agent loop, real tool
execution, a hardware-aware model cookbook, deep research, a document editor, IMAP mail,
CalDAV calendar, MCP support and sixteen themes. It is roughly 2,000 commits of work and
it runs. Forking it was not a judgement that it was bad. It was a judgement that its
engines were *further along than its surface*, and that the gap was worth closing.

None of the following is a criticism of the people who built it. Ambitious software
accumulates exactly this kind of debt — the audit below is the sort of thing you only
find when someone reads all 41,401 lines of one stylesheet.

Odysseus is AGPL-3.0-or-later, and so is Pantheon. Upstream stays wired in as a remote,
and fixes get cherry-picked back down. Credit is in
[`CREDITS.md`](CREDITS.md), the modification notice is in [`NOTICE`](NOTICE), and the
divergence is logged in [`CHANGELOG.md`](CHANGELOG.md).

---

## Why the fork exists

Six audit passes, one adversarial, then a thirteen-agent scout pass over the source. Here
is what came back. Every item is a real finding with a real citation.

### Things that were built and never wired up

The most striking category. Real, finished backends with no way to reach them.

- **The webhooks admin panel has a complete backend and no UI whatsoever.** Two of its
  functions throw on `null.innerHTML` inside a silent `try` — which is precisely why
  nobody noticed.
- **The built-in skills editor exists behind `showBuiltin = false`.** Its card builder and
  all three admin endpoints are fully implemented, including a per-tool
  instruction-block override editor.
- **The gallery upscaler has a backend and a local Real-ESRGAN integration, and zero
  controls.** So do the harmonize, style and import panels beside it.
- **Plan mode is a complete lifecycle whose docked plan window has never existed** —
  while three separate prompt strings tell the model that it does.
- **The RAG upload module expects three elements that were never added to the page.**
- Admin markup is missing for MCP, feature toggles, API tokens and RAG. All four
  backends are there. And it is not only markup: five entries are omitted from
  `admin.js`'s `inits` and `refreshAll`, so adding the HTML alone yields a panel that
  renders empty and never fetches.

### A design system that was never turned on

- **`--accent` is referenced 799 times in `static/style.css` and defined nowhere in the
  application's CSS.** 205 of those references carry no fallback value. `--fg-muted` is
  referenced 101 times, 93 of them bare. **That is 298 authored declarations resolving to
  nothing and silently dropping.** The only `--accent` definitions in the repository sit
  in `src/visual_report.py`, which generates standalone report documents — a different
  stylesheet entirely.
- `static/style.css` is **41,401 lines** with **963 property re-declarations across 405
  selectors**.
- Both resize handles are invisible and mouse-only, because their entire visual
  treatment routes through that undefined accent token.

### A glass box you cannot see into

- The backend streams roughly **50 distinct event types**. More than **30 computed
  fields are sent over the wire and thrown away by the renderer.**
- **A failed turn renders identically to a successful one.** The failure reason is on
  the wire. Nothing reads it.
- Six copies of the agent-thread template have drifted three different ways.

### Restrictions that restricted the wrong things

- `.js` uploads were blocked by MIME sniffing — while **`.svg`, the one genuine stored-XSS
  vector in the set, was never blocked at all.**
- Files that fail the text-file check do not lose a code fence. They return a literal
  `[Attached document file]` banner and **zero bytes reach the model** — `.go`, `.tsx`,
  `.jsx`, `.yaml`, `.rs`, `.sql`, `.rb`, `.php`, `.xml`, `.bash`.
- "Maximum 3 concurrent uploads" is implemented as "at most 3 uploads in the last ten
  seconds", and fires on an ordinary multi-file drag.
- A grammar bug ships the sentence *"Your account is not allowed to can use research."*
- The bash tool prompt forbids heredocs on one line and instructs the model to use one
  seven lines later.

### Sharp edges

- **No route in this application can set a CSP header.** The security middleware runs
  after the route and overwrites it. One route ships a `Content-Security-Policy` that is
  dead at the wire — and two tests pin it in place by calling the endpoint without the
  middleware.
- **MCP has no update endpoint.** Editing a server means delete-and-recreate, which mints
  a new id, which orphans every `mcp__<id>__<tool>` reference pointing at it. There is
  also no call timeout, and env vars are stored unencrypted.
- A chat queue exists with a live session-leak bug: it carries no session id, so it fires
  into whichever chat happens to be open.

---

## What Pantheon is building

Eleven phases, 222 tracked tasks, one tracker. The governing rule is **add, never
subtract** — this is an elevation of Odysseus, not a rewrite of it. The wheel is already
invented here; the work is making it round.

| | Phase | What it does |
|---|---|---|
| **P0** | Fork identity & licence | The rename, and closing the licence gaps inherited from upstream — the AGPL §13 source link, seven vendored libraries shipping with no licence text, fonts credited under the wrong licence |
| **P1** | The token layer | Define `--accent` and `--fg-muted`. One declaration repaints 799 reference sites at once — the 205 bare ones start resolving at all, and the 594 with fallbacks stop silently falling back |
| **P2** | Un-nerf | Delete the restrictions that were never protecting anything, widen the ones that were too narrow, and leave the ~30 controls that are genuinely load-bearing exactly where they are |
| **P3** | Mechanical hygiene | 963 duplicate declarations, 405 selectors |
| **P4** | The wire | Render what the backend already sends. A failed turn should look like a failed turn |
| **P5** | Trace & composer | The surfaces you look at most |
| **P6** | Queue & Plan | Fix the session leak; build the plan window the prompts already promise |
| **P7** | Trust ladder | Approval effects ranked, tripped effects named, the taint trail made visible |
| **P8** | The Workshop | The largest addition: a Skill Crafter, an n8n-style Automations canvas, and an MCP Creator — all three with the model assisting end to end |
| **P9** | Feature surfaces | Re-attach everything that was built and never wired |
| **P10** | Accessibility & release | Contrast across all sixteen themes, keyboard reachability, reduced motion, then ship |

Each phase is scouted before it is implemented: agents verify every task's premise
against the source and correct the plan where it is wrong. The first scout pass, over P2,
overturned its own scouts on **twelve of twelve** contested findings and proved the
headline task wrong in three separate ways. The corrected result is in
[`.pantheon/P2-CORRECTED.md`](.pantheon/P2-CORRECTED.md).

---

## What actually works today

Everything Odysseus does, because Pantheon inherits it:

- **Chat + agents** — local and API models, tools, MCP, files, shell, skills, memory
- **Cookbook** — hardware-aware model recommendations, downloads and serving
- **Deep research** — multi-step web research with source reading and report generation
- **Compare** — blind side-by-side model testing and synthesis
- **Documents** — a writing-first editor with AI edits, suggestions, Markdown, HTML, CSV
- **Email** — IMAP/SMTP with triage, tags, summaries, reminders and reply drafts
- **Notes, tasks + calendar** — reminders, todos, scheduled agent tasks, CalDAV sync
- **Extras** — gallery and image editor, sixteen themes, uploads, web search, presets,
  sessions, 2FA

Plus what the fork has added so far: guardrail caps lifted for self-hosted inference
while cloud APIs keep theirs, an agent RAG scratchpad, and endpoint probe auth.

---

## Quick start

```bash
git clone https://github.com/ImPanick/pantheon.git
cd pantheon
cp .env.example .env
docker compose up -d --build
```

Open `http://localhost:7000` once the containers are healthy. The first admin password is
printed in `docker compose logs pantheon`.

Native installs, GPU notes, Windows and macOS instructions, HTTPS and configuration are
in the [setup guide](docs/setup.md).

`main` is the only branch. Upstream's `dev` is available through the `upstream` remote.

---

## Security

Pantheon is a self-hosted workspace with powerful local tools. Keep auth on, keep private
data out of Git, and do not expose raw model or service ports publicly.

- Keep `AUTH_ENABLED=true` for any network-accessible deployment.
- Keep `LOCALHOST_BYPASS=false` outside local development.

P2 removes restrictions, and it is worth being precise about which ones. Roughly thirty
controls are on a never-lift list in [`.pantheon/FORBIDDEN.md`](.pantheon/FORBIDDEN.md) —
authentication, CSRF posture, the approval store's seal and single-use consumption, path
traversal guards, SSRF guards, command-injection guards, secrets redaction, and the
extension allowlist on uploaded fonts, which is the one place an uploaded file really is
served from a static mount. Those do not move. What P2 removes is the theatre that was
standing in front of them.

Deployment details are in the [setup guide](docs/setup.md#security-notes).

---

## Contributing

Early, and moving fast. The most useful contributions right now are fresh-install testing,
provider setup bugs, and picking up a task from
[`.pantheon/ROADMAP.md`](.pantheon/ROADMAP.md) — read
[`.pantheon/AGENTS.md`](.pantheon/AGENTS.md) first, it is the working agreement and it is
short. See also [CONTRIBUTING.md](CONTRIBUTING.md).

If you are here for Odysseus itself, contribute
[upstream](https://github.com/pewdiepie-archdaemon/odysseus) — that project is alive and
this one is downstream of it.

---

## Licence

**AGPL-3.0-or-later** — see [LICENSE](LICENSE).

Pantheon is free software and I do not sell it. I would rather you did not either, though
the AGPL does not let me require that, and I am not going to pretend otherwise: §10
prohibits adding further restrictions and §7 lets any recipient strip one. Use it
internally at your company if it is useful. That is what it is for.

Credit and third-party licences are in [`CREDITS.md`](CREDITS.md) and
[`ACKNOWLEDGMENTS.md`](ACKNOWLEDGMENTS.md). The modification notice required by §5(a) is
in [`NOTICE`](NOTICE).

**Built on [Odysseus](https://github.com/pewdiepie-archdaemon/odysseus).** It got the hard
parts right first.
