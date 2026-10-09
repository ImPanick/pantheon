# Changelog

All notable changes to Pantheon. Modifications relative to upstream Odysseus are
listed under **Diverged from Odysseus**, which satisfies AGPL-3.0 §5(a).

**Upgrading an existing instance?** Read
[Changed — read this before upgrading](#changed--read-this-before-upgrading) first. It is
the only section that can change what your host does without you editing anything. In
`[Unreleased]` the entry to read is **a chat can be set to Auto** — a new privilege and a
per-chat setting that decide whether the agent asks before a privileged effect. In
`0.2.0` it is **there is always a sign-in** — an install that
ran without one asks for one now. (In `0.1.0`, three switches — `AUTH_ENABLED`,
`PANTHEON_SINGLE_USER` and the `use_rag` field on `POST /api/chat_stream` — stopped ignoring
values meaning *no*; the first two are now ignored altogether.)

**Coming from Odysseus?** The [0.2.0 release notes](docs/release-notes/0.2.0.md)
name every rename you have to follow — each environment variable, command, path,
service, stored value, header and browser key, derived from the fork point and
checked by a test — and the upgrade steps in order.

---

## Versions

**Which version am I running?** Ask the instance: `GET /api/version` returns
`{"version": "…"}`, `GET /api/readiness` carries the same string, and the
Prometheus surface exposes it as `pantheon_build_info{version="…"}`. All three
read one constant, `APP_VERSION` in `src/constants.py`, and nothing else in this
tree declares a version — `tests/test_one_version_string.py` fails if a second
one appears (`Law 14`).

**Until 2026-09-17 that answer was wrong rather than missing.** `APP_VERSION`
read `1.0.3`, which is *Odysseus's* version: set by an upstream maintainer in
`3f2ad23` ("chore(release): align dev version with 1.0.3", cherry-picked from
upstream `e71f8ce`), carried across the fork, and never changed. Two different
programs reported the same number. `B450` corrected it, and this section is the
scheme that stops it drifting again.

**The scheme.**

- **`MAJOR.MINOR.PATCH`, and the line starts at `0.1.0`.** `0.x` is a statement
  about support, not modesty: [`SECURITY.md`](SECURITY.md) supports `main` and
  nothing else, and the rows that still stand between this tree and a stranger
  using it are listed in [`.pantheon/SHIP-LINE.md`](.pantheon/SHIP-LINE.md).
  *(Until 2026-10-02 this sentence said the repository was not public yet. It
  is public, and stays so — `D-2026-10-02-03`.)*
  **`1.0.0` is the first release that is public, tagged and supported.** Until
  then, an operator-visible break bumps the **minor** and gets a *Changed — read
  this before upgrading* block; everything else bumps the **patch**.
- **Three things carry the version and they are equal or the build is wrong**:
  the `APP_VERSION` constant, the `## [x.y.z] — date` heading below, and the
  annotated git tag `vx.y.z`. `tests/test_version_and_changelog_agree.py` pins
  the first two to each other; the tag is checked by the person cutting it,
  against the same string.
- **Each version has release notes**, `docs/release-notes/x.y.z.md`, listed
  under [Release notes](#release-notes) below — the account a person reads
  before upgrading. Their rename tables are checked against the lists that own
  each name (`tests/test_the_release_notes_name_every_rename.py`). Until
  `vx.y.z` is tagged the notes follow the tree; once it is, they are a record,
  like the heading.
- **`## [Unreleased]` is where work lands between releases.** Cutting a release
  renames that heading to `## [x.y.z] — YYYY-MM-DD`, opens a fresh empty
  `[Unreleased]` above it, and moves `APP_VERSION` to match. Nothing is edited
  under a heading that already carries a date — a released section is a record of
  what was claimed at the time, and quietly correcting one is the kind of
  dishonesty `B44` is about.
- **To see what changed between two versions**, read every `## [x.y.z]` section
  between them, newest first. Each carries the same four sub-headings in the same
  order — *Diverged from Odysseus*, *Added*, *Changed — read this before
  upgrading*, *Fixed* — so the block that can alter what your host does without
  you editing anything is always in the same place.

**Cutting a release** (the tag is the one step no test can do for you):

    # on the commit being released, with APP_VERSION and the heading already equal
    git tag -a v0.2.0 -m "Pantheon 0.2.0"
    git push origin v0.2.0

**`0.1.0` was never tagged.** This section said, on 2026-09-17, that its tag would
be cut on the merge; it was not, and `P20`–`P22` landed under its heading's date.
So the release that carries them is `0.2.0` (`D-2026-10-02-04` §1), and `[0.1.0]`
stays below as the record of the day the version line was set. **`0.2.0` is cut
on the owner's word**, `D-2026-10-07-01` §1 (*"Version up. Merge and close."*):
the annotated tag `v0.2.0` goes on the commit that is released — the owner's act,
and the one step above that no test can do.

---

## Release notes

One file per version, for the person deciding whether to upgrade.

- **[0.2.0](docs/release-notes/0.2.0.md)** — the first release (`P10-12`). It
  leads with the Odysseus credit, then names every rename an Odysseus install
  has to follow, what each phase since the fork added, the gates still open, and
  the upgrade steps. Written as `0.1.0.md` on 2026-10-02 and renamed when the
  owner called this release `0.2.0` (`D-2026-10-02-04` §1). `0.1.0` has no notes
  of its own: it was the version line `B450` set, and never tagged.

---

## [Unreleased]

The first fixes from `v0.2.0` in use: the owner ran the release on their own install and reported
two things on 2026-10-09, then ruled on the two questions those fixes raised and reported a third
thing (`D-2026-10-09-01`). All of it is here, and these entries move under a version heading when
the next one is cut.

### Added

- **The phone gets every control that decides a turn.** On a phone the Agent/Chat toggle was
  dropped below a 340 px chat bar and nothing took its place — a 360×800 phone makes that bar
  exactly 340 px — so there was no way to reach Agent or Chat mode at all, and no menu, palette
  or slash command named it either. A chip in the composer now says which mode you are in and
  opens one sheet holding Mode, Approval, Model, Context, Plan, Web, Shell and Persona, each
  showing its current value, each a thumb-sized row. Escape, a tap outside and the phone's Back
  button all close it. `/toggle mode [agent|chat]` is the same control, typed.

### Changed — read this before upgrading

- **A chat can be set to Auto, and then it does not ask.** Every chat has an approval mode:
  *Manual approve*, which is what chats do today and what every chat still starts at, or *Auto*,
  where the agent runs a step that would have raised an approval card. **Read what Auto gives up
  before you grant it.** That card exists because a web page, a fetched document, an email or a
  tool's output can carry an instruction, so in a chat set to Auto a privileged effect that
  follows outside content runs without a person seeing it first — with **no exception list**,
  including effects that delete. It is set **per chat**: never a default, never install-wide,
  never inherited, and a new chat is always *Manual approve*. Turning it on needs the **new
  `can_auto_approve` privilege**, which is **off** for every account except admins (grant it in
  Settings → Users) — so **no existing account gains anything on upgrade** — and it is refused to
  a bearer token and to the agent's own loopback, so a chat cannot put itself into Auto. While
  Auto is on the chat says so, in the composer and in the header, and every step it ran without
  asking is recorded on the run and in the stored event. **What Auto does not change:** nothing is
  validated less. The approval store's seal, expiry and single use, the checks on what an MCP
  server may be told to run, the outbound address and host limits and the admin-only routes all
  behave exactly as before. Auto changes whether you are asked, and nothing else.
- **Your own saved material no longer puts a run into *external untrusted context*.** One pinned
  memory, one note or one installed skill used to arm the approval gate from the first token of
  every agent turn, so the turn's first privileged effect waited for a click and the card
  described your own note as content that came from outside — on any install that uses memory,
  that verdict was always on, and a verdict that is always on says nothing. It no longer arms.
  Everything that genuinely arrived from outside still does, and the write that could launder a
  hostile page into your memory or your skills — `manage_memory add`, `manage_skills add` — is
  itself a gated effect, asked in the run that read the page, while it can still be traced to it.
  **If you were relying on that**: a chat left on *Manual approve*, which is the default, still
  asks before every privileged effect that follows anything from outside; what is gone is the
  arming that a non-empty memory store did on its own.

### Fixed

- **The model can tell where your message begins.** Everything Pantheon adds to a turn — the
  delivery register, the date and time — had to be a `user` message, and nothing marked it, so it
  was glued to your words. A model sent that spent 92 seconds deciding which part of its prompt was
  the question, called the turn a *"prompt injection"* test and answered the wrong thing. What the
  application adds now says so, and your own saved memory no longer arrives under the warning
  written for hostile web pages.
- **Tools and MCP servers reach the model.** A model whose *name* Pantheon did not recognise was
  sent no tools at all; every MCP tool was dropped from the request whenever the embedding backend
  was down; one MCP tool with a schema a strict local server cannot read refused the whole request,
  taking the others with it; the prompt named eleven tools the request withheld; two of the five
  tool-call shapes a local server writes were dropped; and a registered server that is not running
  is now named to the model with its own error instead of being silently absent.
- **The first tool call of a turn no longer waits for a click.** Registering any MCP server put the
  run into *"external untrusted context has already influenced this run"* before you had asked
  anything, because the list of what your install can call was wrapped as if it had been fetched
  from outside. A tool list is not a web page. Everything that genuinely comes from outside — a
  tool's output, a web result, a fetched page, mail, a document, a skill — still holds the next
  privileged effect, and a hostile MCP result still refuses `bash`.
- **A web search searches what you asked.** The query was broken into capitalised words and OR-ed
  back together, so *"Old School RuneScape Fractured Archive raid details"* matched pages holding
  only the word *Old* — the owner's search returned a film, IMDb, a dictionary and a clothing shop.
  The query goes out as written, the block says which provider answered and what was sent, and a
  search whose results do not match says so instead of letting the model answer from memory.
- **Export writes the whole chat.** Every item in the chat's Export menu read the page on screen,
  so an export held the top of the chat and stopped. The menu asks the server, which has had the
  whole thing all along, and the Markdown it writes carries each turn's reasoning. A document's
  *Export as PDF* failed silently on one of this page's own colours and works now.
- **One typed message is one message.** A resend trimmed the chat by counting the bubbles on
  screen, so on a chat longer than one page the message was stored twice and sent to the model
  twice — which is what the owner's own exported chat shows.
- **The agent does the work instead of asking whether to.** Measured over five multi-step tasks
  against the same model: **none finished**, and four ended by asking whether to take a step they
  had already been told to take. **Four of five finish now**, and none ends on a question the
  agent asked. A turn that offers to do something and then stops gets one push to do it, and a
  first action that is a question with nothing yet looked at buys one round of looking. `ask_user`
  still raises its card once anything has been run, asked twice, or asked on a turn with no other
  tool, and plan mode may still end on a question.

---

## [0.2.0] — 2026-10-02

**The first release.** `0.1.0` below set the version line on 2026-09-17 and was
never tagged; the workstation (`P20`), documents in folders (`P21`), the
Workbench (`P22`) and the audits' fixes (`P23`) landed after it, so this is the
next minor (`D-2026-10-02-04` §1). Dated the day `APP_VERSION` moved to `0.2.0`;
the tag `v0.2.0` is cut on the owner's word, `D-2026-10-07-01` §1, on the commit
that is released. **The account to read is the
[release notes](docs/release-notes/0.2.0.md)** — the Odysseus credit, every rename,
each phase, the gates still open and the upgrade steps, checked against the tree
by `tests/test_the_release_notes_name_every_rename.py`. This section lists what an
operator should know at a glance.

### Diverged from Odysseus

#### Renamed
- Every rename an Odysseus install has to follow — environment variables,
  commands, paths, services and volumes, stored values, headers, user agents and
  browser keys — is in the release notes' *Breaking renames*, each derived from
  the list that owns the name and checked against the fork point `b4d1293`.
- **The names a person reads** (`P23-05`, `P0-29`): *Brain* (not Memory), *chat*
  (not session or conversation), *MCP & Integrations* and *Forge* (not Cookbook)
  on every label. Routes, stored keys, ids and classes keep their names
  (`D-2026-09-18-04`), so there is nothing here to follow.

#### Added
- **The AGPL-3.0 §13 source offer, on by default** (`P0-17`, `D-2026-10-02-04`
  §2). Every page the app serves, the login page included, carries a *Source*
  link to `https://github.com/ImPanick/pantheon`. `PANTHEON_SOURCE_URL` (or the
  `source_url` setting) points it somewhere else.
- **Pantheon's own mark** (`P0-13`, `B71`) — the favicon, the PWA and Windows
  icons, the tray, the macOS app icon and the login and welcome screens no longer
  carry upstream's boat. Sources and usage: `docs/brand/`.
- **The workstation** (`P20`), **documents in folders** (`P21`) and **the
  Workbench** (`P22`) — see the release notes, *What is new, phase by phase*.
- **"When mail arrives" runs with nobody looking at the inbox** (`B1137`): a
  background check every `email_inbox_check_minutes` (default 5; 0 turns it off).
- **One back stack and one table for the Tools** (`P23-01`, `P23-03`): Back,
  Escape and `←` close the same thing, every window has a URL and a reload
  reopens it; a tool switched off — for everyone, one person or one browser — is
  off at every door. The rest of `P23` is in the release notes, *What is new*.
- **Settings → Forge** (`B1229`): the *Hugging Face and Ollama* switch, and a
  door to where each setting for serving a model already lives.
- **The attachment tray is a hand of cards** (`B1292`): small cards fanned at the
  composer's edge, each with a menu (Preview, Crop, Save to Gallery, Remove), in
  place of a full-width band that took its height from the chat.

#### Changed — read this before upgrading
- **There is always a sign-in** (`D-2026-10-07-02` §2 — the owner: *"there is always
  authentication. What's toggleable is registration. We keep it this way."*).
  - **An install that ran without a sign-in now asks for one.** `AUTH_ENABLED=false`
    (or `0`/`no`/`off`), `LOCALHOST_BYPASS=true` and `PANTHEON_SINGLE_USER` no longer
    let anything in unsigned; each is ignored and named once in the log at start —
    remove it from `.env`. The app comes up behind its sign-in page rather than
    refusing to start.
  - **The first run asks for the admin account** — on the sign-in page when no account
    exists, in the terminal on a native install (`setup.py`). A Docker container's
    first boot made `admin` and printed a temporary password to the container log
    (unless `PANTHEON_ADMIN_PASSWORD` named one); sign in with that. Lost it, and
    `admin` is the only account? Set `PANTHEON_ADMIN_PASSWORD`, move `data/auth.json`
    aside and restart.
  - **Registration is off by default.** Whether people may make their own accounts is
    one switch, Settings → Users → *People can sign themselves up*; off, the sign-in
    page offers no sign-up and `POST /api/auth/signup` says so. An admin adds people
    under *Add User* either way.
  - **What the no-sign-in install made has no owner**, and a signed-in person is not
    shown owner-less chats. Give them to the admin once, after the first sign-in:
    `python scripts/claim_ownerless.py <admin>` (Docker: `docker compose exec pantheon
    python scripts/claim_ownerless.py admin`) — chats, documents, gallery images,
    comparisons, memories and skills. It does not reach scheduled tasks: an owner-less
    task that runs a shell, SSH or a serve is refused until an admin makes it again.
- **If you run a modified copy of Pantheon for other people, point the source
  link at your own source.** An unmodified install now offers this repository's;
  a modified one owes its users *its* source (AGPL-3.0 §13). Set
  `PANTHEON_SOURCE_URL` in `.env`, or the `source_url` setting — `docs/setup.md`
  says how.
- **Three routes that any signed-in account could use are now admin-only**:
  `POST /api/tts/clear-cache` (`B540`) and the four `/api/hwfit/*` probes
  (`B541`). On a single-user install nothing changes — the first account is the
  admin. The three developer sandbox pages under `/static/` need a session and
  live at `/sandbox/<name>` (`B370`).
- **The Forge no longer reaches Hugging Face or Ollama until an admin switches
  them on** — *Hugging Face and Ollama* in Settings → Forge (`B1229`). Opening
  the Forge used to refresh its catalog from huggingface.co and fetch
  ollama.com's library by itself. An install that did that before starts off
  too: the catalog it already fetched is still listed, and a model download
  says where the switch is instead of reaching out.
- **SQLite keeps a write-ahead log by default** (`P23-07`): `app.db-wal` and
  `app.db-shm` sit beside `app.db` while Pantheon runs, and `pantheon-backup`
  copies the database through SQLite's own backup rather than the files. A write
  that meets a held lock is answered `503` with a sentence in under a second.
- **The service worker controls the app at `/`** (`P23-07`), not only
  `/static/`: an offline reload draws the app. A browser holding the old
  registration drops it by itself.
- **The sidebar lists your own chats**, a page at a time with *Show older chats*
  (`P23-07`) — it listed the newest hundred of everyone's.
- **SQLite's write-ahead log falls back where it cannot work** (`B1231`). On a
  data directory that cannot hold one — `./data` bind-mounted from the host by
  Docker Desktop on Windows or macOS can be one — Pantheon puts the database
  back on the rollback journal at start, keeps running, and says so once in the
  log. `PANTHEON_SQLITE_JOURNAL_MODE=delete` in `.env` skips the check.
- **A model is offered only while an endpoint lists it** (`D-2026-10-07-02` §1,
  `B1259`). Names come from a server's own model list or a provider's own list
  call on a key that answered — no built-in list stands in. **What you may
  notice after upgrading:** an Anthropic endpoint added without a key (or with
  one Anthropic refuses) offers nothing until a key answers — it listed ten
  built-in `claude-*` names; an endpoint that stops answering shows one line
  with *Retry* instead of its old names; a saved default, or a task's or
  workflow step's model, that its endpoint no longer lists is not used — the
  model menu says so, and the run records why it did not run; a task with no
  model takes Settings → Agent Tools → *Model for scheduled tasks* (else Utility,
  else the default chat model) — it took the model of its owner's newest chat;
  and a run whose configured model is not listed says which and why. A send
  refused for want of a model keeps its message: *Pick a model* opens the
  menu, and the message goes once one is picked. A pinned model name the
  endpoint does not list stays in Added Models, marked *not listed*, and is
  offered when it is. `POST /api/v1/chat` with an `api_key` and
  `POST /api/session/openai` now need a `model`.
- **With *Hugging Face and Ollama* off, serving a model does not fetch it**
  (`B1259`): `llama-server -hf …`, `ollama pull` and `ollama run` are refused
  with the switch's sentence, and every other serve runs with
  `HF_HUB_OFFLINE=1` and stops, saying so, on a repo id that is not in that
  machine's Hugging Face cache.

#### Fixed
- *Import from device* in the Documents panel opens a file picker again, and a
  `.docx`, `.xlsx` or `.pdf` picked there opens readable, the same as through the
  Library (`B400`).
- One mail fires `email_received` once, however it is listed (`B1139`); a
  workflow run the foreground pauses reads *waiting*, never *aborted* first
  (`B1138`); an Integration added through a step's door is offered on that step
  at once (`B1136`).
- **The chat tells the truth** (`P23-04`): Escape stops the reply on the server
  too, a denied tool call is drawn denied after a reload as well, and one agent
  turn reads as one reply (`B1247`).
- **The Library and Mail** (`P23-08`): Reply, Compose and Create leave no empty
  chat or *Untitled* behind; the scheduled Tidy never proposes an unsent draft; a
  failed send names the server it could not reach.
- **Every attachment reaches the model, or says why not** (`B1278`–`B1280`,
  `B1284`–`B1286`): a picture in a new chat's first message reaches the model
  (it was dropped); a recording goes as its transcript when the server has
  speech-to-text; an email or a document open beside the chat reaches a
  Chat-mode turn; a Library document dropped on the chat is attached; a file the
  model was not given whole is said under its card.
- **A hidden Library keeps the archive** (`B1194`, `D-2026-10-07-02` §3): with
  documents switched off, archived chats keep their door, Chats → *manage*, and
  a Library reached anyway says where they are.

---

## [0.1.0] — 2026-09-17

**The first version of Pantheon that is Pantheon's.** Everything below was
already in the tree; what `0.1.0` adds is a number that belongs to this project
and a heading a later release can be read against. Nothing here is a behaviour
change made on 2026-09-17 except the version string itself — the *Changed — read
this before upgrading* block below is the accumulated set since the fork, and an
operator upgrading from a commit rather than from a tag should read all of it.

### Diverged from Odysseus

Forked from `pewdiepie-archdaemon/odysseus` @ `b4d1293` (branch `dev`), which was
committed upstream on 2026-08-20; the fork began on 2026-08-24 (UTC), with this
repository's first commit of its own, `a4c44567`.

#### Before the fork was named — local customisation (branch `custom`)

The five changes below were made on one machine, under the working name *Cybertooth*,
before this became a named fork. They are what the fork was started to keep. The detail
as it was written at the time — with every stale path and variable name corrected and
dated rather than rewritten — is in [`CYBERTOOTH_CHANGES.md`](CYBERTOOTH_CHANGES.md).

- Guardrail caps are lifted when inference runs on local, self-hosted
  infrastructure, and kept when the active model is a cloud provider. Gated on a
  per-request context variable set from the active endpoint, with env overrides.
- The degenerate-stream phrase-loop guard is env-gated and defaults off. It was
  firing on legitimate structured output — repeated bar-chart rows normalise to
  the same phrase and trip their own guard.
- Output truncation, web-fetch caps, filesystem read caps and agent round limits
  are lifted under local inference.
- The RAG MCP server gained `add_text` and `search` actions; it was previously
  write-crippled to directory registration only.
- Agent prompts gained explicit working-memory guidance so the model uses the
  RAG, memory and notes systems that already existed.
- Model-probe requests now carry the endpoint's auth token.

#### Renamed
- Project renamed to Pantheon. Env prefix, storage keys, vector collections,
  session cookie, outbound headers, CLI scripts, service names and identifiers
  all follow. See `.pantheon/ROADMAP.md` P0.

#### Added
- `.pantheon/` — the Frontier Elevation programme: roadmap, working agreement,
  do-not-touch list, deferred decisions, and per-area handoff notes.
- `B95`. The three settings that could previously only be changed by
  hand-writing `data/settings.json` — `allow_model_download` (the `Law 16` gate
  on fetching a model from HuggingFace), `searxng_widen_engines` and
  `metrics_enabled` — now have controls in **Settings → System**. Each is
  three-state: *yes*, *no*, or *use the environment variable or the default*,
  and the panel says which of those three layers is answering on this host.

<!-- `B25` / `D-2026-09-08-06`. A line here once read "Source link in the UI
     footer, per AGPL-3.0 §13." It never shipped. A changelog is what a
     stranger reads to audit AGPL conformance, so a false compliance claim is
     worse while this repo is private, not better — nobody can check it. The
     link is `P0-17`; it is built and left dark against a repository URL that
     ships empty, and it goes back in this file when it renders. -->

#### Changed — read this before upgrading

`B96`. **Two environment switches meant the opposite of what an operator typed,
and both are corrected. If you set either to a disabling value, this upgrade
changes what your host does.**

- **`AUTH_ENABLED`** — until now, only the literal `false` disabled
  authentication. `AUTH_ENABLED=0`, `=no` and `=off` left authentication
  **enabled**, with nothing logged and nothing in `.env.example` saying so. All
  four spellings disable it now. **If you are running with `AUTH_ENABLED=0`
  believing auth is off, it has been on, and after this upgrade it will be off —
  your instance will answer without a login.** Set `AUTH_ENABLED=true`, or unset
  it, to keep authentication. The value is also logged as a warning at the first
  check, naming the change.
- **`PANTHEON_SINGLE_USER`** — until now, only the literal `0` turned
  single-user mode off, and *it did not work either*: the value was computed at
  import into a module constant nothing read (`B150`). Unauthenticated calendar
  requests were written under `PANTHEON_FALLBACK_OWNER` regardless of what this
  was set to. It is consulted now, and `0`, `false`, `no` and `off` all turn it
  off, which makes an unauthenticated calendar request a `401` instead of a
  write under the fallback owner. **If you set this to any of those values and
  rely on the fallback owner, unset it.**

Both are the direction an operator reading `.env.example` already expected, and
neither is a sweep: the other seven switches `B91` held stay held, because
widening them would loosen a control rather than honour an intent.

`B152`. **`use_rag=0` meant *yes*, on the chat API. If you send `use_rag` with a
value meaning no, this upgrade changes what you get back.**

- **`use_rag`**, the form field on `POST /api/chat_stream`, is the one field in
  this API that defaults **on**, and until now only the literal `false` turned
  retrieval off. `use_rag=0`, `use_rag=no` and `use_rag=off` all turned
  retrieval **on** — a caller asked for retrieval to be skipped and got it
  anyway, with nothing logged and nothing in the API saying so. All four
  spellings turn it off now, which is the same eight-word vocabulary
  `compare_mode`, `incognito`, `plan_mode` and `no_memory` on the same request
  already read.
- **The default has not changed and is not going to.** Omitting `use_rag`, or
  sending it blank, or sending a word nobody recognises, still means *yes*:
  a default answers when the field did not say, and it was never a licence to
  overrule a caller who did say. That distinction is the whole change.
- **Pantheon's own web UI is unaffected.** It sends the literal `'false'` and
  nothing else, so this can only reach a hand-written API client. The first
  affected call logs a warning naming the value.

#### Fixed
_(populated as P1 onward lands; `B24`, `P1-12` and `P1-14` are in and
belong here the next time this section is written out.)_

---

## Upstream

For changes prior to the fork, see the Odysseus repository.
