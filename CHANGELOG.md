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
`{"version": "…"}`, `GET /api/ready` carries the same string, and the
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

- **`.xls`, `.ods`, `.pptx` and `.epub` are read on a default install,** and an attached `.zip`
  lists what is in it and reads its small text files (`B1178`, `B1289`, `B1291`).
- **Diagnostics → Evals and → Sign-ins and access:** an operator runs an eval suite from a recent
  run, and reads who signed in, from the page (`B490`, `B684`).
- **Settings → System → How long records are kept,** and the skill importer's GitHub token in
  MCP & Integrations (`B1539`, `B927`).
- **The image editor hands an edit back to the message** (`B1293`), and the composer estimates
  what a text file will cost before it is sent (`B761`).

- **Each Tools entry can be switched off for everyone** — Assistant, Calendar, Compare, Email,
  Notes, Tasks, Theme and Workbench, in Settings → Agent Tools — beside the per-person switch:
  the door hides, the routes refuse everyone, the agent's tools go, and background work holds
  with a sentence; nothing is deleted (`B1488`).
- **`auth_events_retention_days`** keeps the sign-in audit trail on its own clock; unset follows
  `events_retention_days`, 0 keeps it forever (`B685`).

- **Ctrl+K finds a chat by its name,** not only by a word in its messages (`B1249`).
- **The mail unread count shows on the sidebar with the mail window closed** (`B812`).

- **A person keeps their own keyboard shortcuts;** an admin's are everyone's default (`B1196`).
- **A plain API token can be minted** from Settings › Integrations (`B1193`).
- **A build says which commit it is:** `GET /api/version` carries `commit` (`B453`).

- ***Print as PDF* prints the document as text** a reader can select and search, through the
  same page *Export HTML* builds, instead of a picture of it — 35 KB where a long document was
  1.5 MB (`B1333`).
- **A waiting document tidy survives a restart** — plans are kept in the database (`B1018`).

- **A reply that failed before a word is kept,** and a reload draws it as the model's bubble
  with one sentence and *Retry* (`B1200`).
- **The Brain shows how you write** — each line editable, and *Forget how I write* — and says
  when a memory is about to fade (`B820`, `B821`); a provider import says what it read (`B822`).
- **The Skills preview says why each of your skills is not in the block,** and the Add form
  takes *Use only when these are unavailable* (`B586`).

- **A signed-in person can fork a shipped skill, and their copy replaces it for them alone.**
  Everyone else on the install keeps the shipped one; deleting the copy brings it back (`B1421`).
- **A task a workflow step runs waits for your yes on the workflow's card** instead of being
  denied on the spot — one card, one answer, and the action runs once (`B1173`).
- **An event or webhook task retries with its payload** when it fails and has retries left; the
  card says how many (`B805`).
- **A deferred task says why and until when** on its card (`B675`).
- **The chat says when an MCP server is not answering** and that its tools are not in this chat
  (`B1326`).
- **The skill editor lints as you type,** before the save (`B613`).

- **An admin can switch each Tools entry off for one person** — Assistant, Calendar, Compare,
  Email, Notes, Tasks, Theme and Workbench join Brain, Deep Research, Gallery and the Library
  in Settings → Users. Off hides the entry, its routes refuse that person in the same sentence
  the door says, its tools leave the agent, and its work that runs without the window — their
  scheduled tasks and workflows, the Assistant's check-ins, the inbox check, mail scheduled to
  send, their email actions, note reminders — is held with a sentence saying why. Nothing is
  deleted; turning it back on is all it takes (`B1191`, `D-2026-10-26-01` §5).
- **A lost admin password has a way back.** Stop Pantheon, run
  `python scripts/reset_password.py <name>` where its data lives (in Docker,
  `docker compose run --rm pantheon …`), start it again: the password is set, that person is
  signed out everywhere, and no other account changes. `--disable-2fa` is there for a lost
  authenticator (`B1272`).
- **`scripts/claim_ownerless.py` gives one account everything an install without sign-in
  made** — its tasks, notes, calendars, allow-rules, workflows, folders, drafts and the rest,
  its vault and git settings where the account has none of its own, its skills, preferences
  and projects folder — and prints how to copy its workstation home. `--dry-run` says what
  would move (`B1270`).
- **A task drafted from a sentence offers a workflow when the work is several steps** — the
  Workbench's *Or describe it*, with the same words already in it (`B1210`).
- **The ship line is a CI gate.** `check-ship-line.py --check` fails when an open row its
  triage calls a candidate is in neither list of `SHIP-LINE.md` § 7 (`B451`).

- **Each person can declare their own networks, and an admin sees them all.** With *Each person
  may declare their own networks* on (Settings → Networks, off by default), Settings → My
  networks lets a person name the networks their agents work in — their lab, their NAS, a client's
  VPN — with a trust each, and link a login from their own vault to one: the agent is told to sign
  in with it there, by name, and never sees it. A person's networks direct their own runs only.
  The admin's list shows every person's networks, and of a linked login only that one is linked —
  never which, nor anything in it (`B1475`, `D-2026-10-25-04` §5).
- **A task can be held to its networks.** *Networks* in the task form: its runs are refused every
  address outside the networks picked, with *internet* for everything no network claims (`B1475`).
- **The workstation's backend switch switches** (opt-in). Add `docker/workstation-both.yml` to run
  the VM host beside the container; Settings → Workstation → *Backend* chooses which one the agents
  use, and *Automatic* picks the VM where the host has KVM. With `docker/host-docker.yml` too, the
  choice starts that backend and stops the other, and the panel lists the workstation's containers
  with Start, Stop, Restart and Logs — only the workstation's own, only those acts (`B1478`).
- **A VM has its person's projects folder.** On the VM backend each person's machine is given
  their folder of `data/projects` — that folder, never the others — so what an agent builds there
  is in Pantheon (`B1427`).
- **Python code blocks run for everyone.** *Run* on a Python block sent it to the server's shell,
  which only an admin may use, so for everyone else it did nothing useful. A person without the
  shell now runs it in their own browser (Pyodide, shipped with Pantheon) — in a sandboxed frame
  that cannot read their cookies, storage or this app, on its own thread, so a block that never
  ends is stopped after ten seconds without freezing the page. An admin's blocks still run on the
  server (`B1474`, `D-2026-10-25-04`).
- **The agent can launch a model by name.** `serve_model` with just a model uses a saved preset
  for it on that host, or plans a first command for the right engine from the model's metadata,
  and diagnoses it like any launch (`B1476`). *Stop* on a model server that ignores the signal now
  force-kills it, and says so — and one that survives even that keeps its card (`B1477`).
- **Doors for things that were built and unreachable** (`B1453`, `B1469`): *Uploaded files* in
  Settings → System (how many, how much, and *Remove expired uploads* — nothing ever removed
  them), the RAG index's own count under its panel, a *not spam* override on the AI's spam pill in
  Email, and *From a file…* in Skills to import the file a skill's *Download* gives.
- **An agent says when your model is short of what it needs** (`B1448`): a mark on its card, the
  reason on its page and a line in its run, when the model has a smaller context window than the
  agent declared or calls tools only in the fenced form it cannot rely on. It warns; it never stops
  a run.
- **The phone gets every control that decides a turn.** On a phone the Agent/Chat toggle was
  dropped below a 340 px chat bar and nothing took its place — a 360×800 phone makes that bar
  exactly 340 px — so there was no way to reach Agent or Chat mode at all, and no menu, palette
  or slash command named it either. A chip in the composer now says which mode you are in and
  opens one sheet holding Mode, Approval, Model, Context, Plan, Web, Shell and Persona, each
  showing its current value, each a thumb-sized row. Escape, a tap outside and the phone's Back
  button all close it. `/toggle mode [agent|chat]` is the same control, typed.

### Changed — read this before upgrading

- **Muted text is darker on light palettes and lighter on dark ones,** so it clears 4.5:1 on all of
  them; links, model names in a chat, and the danger colour were moved for the same reason
  (`B1486`, `B391`, `B395`, `B1084`, `B393`). Sidebar labels are 11px (`B784`).
- **Every outbound HTTP call the server makes from module level goes through the path that reads
  `NO_PROXY` ranges** — model discovery, the OAuth flows, image downloads (`B1022`); a held search
  says when it comes back (`B492`).
- **A fork is named `Fork: <name>`** and drawn with one mark (`B1530`); `RESEARCH_LLM_ENDPOINT`,
  which nothing read, is no longer passed to the app (`H21`).

- **A document records where it came from** — written here, imported, or derived — and only
  a document written here is given to the agent as the person's own words (`B1325`); documents
  older than the column are treated as untrusted.
- **`pantheon-ui.service` waits for `/api/ready`** before `systemctl start` returns (`B444`).
- **`src/config.py`'s second settings system is gone** (`B550`).

- **The assistant asks before it switches on or redirects its own settings** — image generation,
  the teacher, speech, model downloads, metrics, wider search or LAN reach, a higher remote-image
  mode, a new address for any destination, or a tool an admin switched off — every time, at every
  trust rung (`B897`, `B912`, `D-2026-10-25-01`).
- **One handler compacts a chat:** `POST /api/session/{id}/compact` leaves a visible *Chat
  compacted* marker in order and answers a chat too short to compact with a 400 and a sentence
  (`B1529`).
- **The search providers are paced** like every other outbound call, a 429 counts once, and an
  empty fallback chain sends nothing to DuckDuckGo (`B1533`, `B1538`).

- **A message you just sent can be deleted before a reload:** the chat stream announces the sent
  message's row id in a new `user_message_saved` event (`B1507`).
- **`GET /api/search?chats=1`** returns `{chats, results}`; without the flag the answer is the
  plain list as before (`B1249`).

- **`GET /api/ready` answers without a sign-in,** with only `{"ready": bool}` and 200 or 503 to a
  caller with no session; the compose healthchecks ask it instead of `/api/health` (`B441`).
- **An auth-exempt path is exempt only for the methods it names:** `POST /api/auth/settings` and
  `POST /api/auth/features` answer 401 without a session (`B542`).
- **An unanswered approval is denied when its deadline passes,** by a sweep every five seconds,
  not when someone next touches the store (`B560`).
- **The chat's `document_editor` switch is gone;** asking for it says where the switch is
  (`B898`). A role can set the agent's input-token budget (`B751`).

- **The Library refuses a file it cannot read** — a binary the browser has no type for is checked
  by the server first and refused with its reason, where it used to import as a page of
  replacement characters (`B401`).
- **A workflow's start waits for Save with its steps** instead of saving the moment the form
  closes (`B1209`).

- **A task's type is one of three.** `POST`/`PUT /api/tasks` and `manage_tasks` refuse a
  `task_type` other than `llm`, `research` or `action`, with a sentence; a workflow is made in the
  Workbench. A row already stored with another word can still be saved while it keeps it (`B1076`).
- **A refusal about a missing or someone else's chat says *That chat no longer exists.*** at
  every route, where four spellings of *Session not found* were (`B1216`).
- ***Test this step* waits for a slow model** up to the workflow's own time limit (else five
  minutes) instead of the 45-second request ceiling, and stops when the page stops waiting
  (`B1496`).
- **A one-off task with retries retries** before it ends (`B1492`), and **a webhook task's
  pending retry survives a restart** (`B1494`).

- **The built-in *Chat Sessions Tidy* task is now *Chats Tidy*.** An existing install's row shows
  the new name at once and is renamed on the next start; both names stay hidden from the
  sidebar (`B1215`).
- **A slash command's skill is sent beside your message, not as it.** `POST
  /api/skills/{name}/invoke` returns `request`, `message` and `skill` instead of one string with
  the whole SKILL.md inside it; the skill travels as a `skill` field on the chat form and reaches
  the model framed and escaped like a matched skill. A client that sent `/invoke`'s old string
  as the message should send the person's words and the name (`B1374`).
- **A due task is no longer pushed back fifteen minutes while someone uses Pantheon;** it queues,
  waits for idle without holding a model slot, and its row says so (`B1094`).
- **A skill you write in the form is a draft until you publish it,** and now says so — the toast
  has a Publish button (`B581`). The nightly audit drafts a skill only when it is the same skill
  saved twice, and names the copy it kept (`B790`).

- **A webhook an admin sets up may point at the LAN.** n8n, Home Assistant, a tailnet or an
  IPv6 ULA address are accepted from Settings, and the save is logged; loopback, link-local and
  cloud metadata stay refused, and delivery stays pinned to the address that was checked. A
  webhook the agent adds keeps the public-only rule — which now also refuses CGNAT, a tailnet's
  range, that it had let through (`B692`).
- **Kimi Code is sent Pantheon's own name.** Pantheon re-sent a refused request under five
  other products' names until one got through; it sends `Pantheon/<version>` once now, as to
  every endpoint, and if Kimi Code refuses it the chat says so and names the Moonshot API as
  the way to use Kimi models (`P15-07`).
- **An unreadable account store refuses privilege-gated routes** with a 503 that says why,
  where it used to grant them; an admin's routes and sign-in stay reachable (`B531`).
- **`cute` and `retrowave` read at 4.5:1.** `cute`'s pink text is darker (`#c9366b`) and
  `retrowave`'s surfaces a shade darker (`#141423`, `#111a31`) (`B390`).
- **The Gallery stays open to a person without *Image generation*;** that switch takes the AI
  image tools only (`B1195`).

- **`sudo` in the workstation is by backend unless an admin chose.** An install that never set it
  had root on in the shared container, where it reads every person's work. Unset, it is now on in a
  person's own VM and **off in the container**; an admin who wants it on there turns it on, and
  the panel says that root then reads everyone's files (`B1428`, `D-2026-10-25-04` §4). The
  backend setting is *Automatic* unless set — the container wherever no VM host is configured, so
  nothing changes for an install with one backend.
- **A network scope holds the agent, not Pantheon's own calls.** Inside a run scoped to some
  networks, the agent's page fetches, integrations and reach checks are refused every address
  outside them, as before; Pantheon's own calls for the run — its model, its workstation — are
  refused only an address in *another* declared network. Until now nothing opened a scope, and the
  first task given one would have been refused its own model (`B1475`).
- **An agent can read your LAN by URL — if you may use the workstation.** `web_fetch` refused every
  private address in `v0.2.0`. It now reaches LAN and tailnet addresses (a router page, a NAS's
  API) for the agent of a person allowed the workstation, while *Agents may reach the local
  network* (Settings → Workstation) is on, which it is by default (`D-2026-10-25-02`, `B1459`).
  Loopback, link-local and cloud metadata stay refused for everyone; the image proxy, search
  results and every other fetch Pantheon makes never reach the LAN; a network you declare
  `untrusted` is never connected to. Switch it off and everything is as in `v0.2.0`.
- **The agent's `network` tool lists and checks one host — it does not scan.** `list` names this
  machine's interfaces and your declared networks; `reach` opens one connection to one host and
  port and says connected, refused or no answer (`D-2026-10-25-03`). Network trust is two levels,
  `trusted` and `untrusted`; a saved `limited` reads as `trusted` (what it always did) and writing
  it through the API is refused.
- **The admin's Default is everyone's default.** Settings → *Default chat model* is the model a
  person gets until they pick their own — in the composer and for every background model alike.
  The *Share defaults with users* switch is gone; a model a person's privileges exclude is not
  offered to them as a default (`B1479`, `D-2026-10-25-04`).
- **Nineteen API routes nothing called are gone** (`B1453`, `B1454`, `B1263`): `POST
  /api/compare/start` and `/{id}/vote`, the notes `pin`/`archive`/`items/{i}/toggle` POSTs (use
  `PUT /api/notes/{id}`), `GET /api/gallery/tags` and `/stats`, `POST /api/gallery/dedupe-tags` and
  `/clear-user-tags`, `POST /api/session/openai`, `POST /api/session/{sid}/delete`, `DELETE
  /api/sessions/all` (Settings → Danger Zone → *Delete all chats* is the one way, and now removes
  the chats' images too), `POST /api/sessions/save`, `GET /api/conversations/topics`, `POST
  /api/cookbook/packages/install`, `GET /api/email/contacts`, `POST
  /api/email/attachment-path/{uid}/{index}`, and `GET /api/cookbook/vllm-recipe` and
  `/vllm-recipe-manifest`. A script that called one of them gets a 404 now.
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

- **The one focus ring shows on every palette** — 92 outline suppressions that could hide it are
  gone (`B662`); Settings, the model picker and the workflow view fit a phone (`B1255`, `B1347`,
  `B1222`); the developer sandboxes hold still under Reduce Motion (`B663`).
- **A running SD WebUI Forge is reported as itself,** not as A1111 (`B471`); the document index no
  longer lists its own state files (`B1547`); an `.ods` repeated cell fills every column it covers
  (`B1549`).

- **Windows minimised to the dock come back after a reload** (`B1185`), every tour passes a step
  with nothing on screen (`B1537`), a page asks each boot read once (`B1228`), and a
  switched-off tool's page stops polling its routes (`B1542`).
- **The chat searches a document index that came up after start** (`B1532`); DuckDuckGo's library
  path is paced (`B1541`); a silent refused send in the workstation is counted and said
  (`B1021`); a compare vote names a winner it compared (`B642`).

- **A truncated plan update is sent back** instead of erasing approved steps (`B1415`); a
  read-only MCP tool is not held like a destructive one (`B1329`); a model nobody ruled out gets
  a tool's picture, and a refusal of it falls back to words (`B1281`); an event that lands
  mid-run runs after it (`B1512`).
- **The approval card speaks plainly** (`B1202`), a widening card offers no rule it cannot keep
  (`B900`), the OCR editor and a dimmed opener follow the Escape stack and the keyboard
  (`B1531`, `B1221`), and the sidebar's Email title is a button (`B1213`).

- **Every mail path gives up on a silent server in seconds** — the routes' sender joins the agent's
  tools (`B1526`); an email task no longer rewrites `settings.json` to pass itself flags
  (`B801`); a reminder Odysseus queued is still a reminder (`B1161`).
- ***Delete all unsorted* deletes all of them,** not the hundred the sidebar holds (`B1225`); a
  compacted chat's summary reloads first (`B1506`); the palette names Settings groups as the
  Settings window does (`B1206`).
- **The RAG chip says when no index answered** (`B1287`); the search cache is swept after a
  restart (`B1336`); a page that fails once is asked once more (`B1337`); the Forge's local
  Ollama probe goes direct, not through a proxy (`B1262`); a failed GGUF scan says its sentence
  (`B1261`).

- **The kept offline page runs its JavaScript** — cached modules were missed on `Vary: Origin`
  (`B1508`).
- **A demoted admin takes the role they are given** (`B680`); a privilege map is the caller's
  own copy (`B1522`); a guest's page asks for nothing only an admin may have (`B1192`).
- **The agent's mail tools give up on a silent server in seconds** and read an 8-bit subject
  (`B1230`, `B1232`); `resolve_contact` reads its person's mail history (`B1182`); deleting an
  MCP server says which switched-off tools went with it (`B864`); a step limit of 0 is one step,
  not fifty (`B1030`).

- **A Word export of a document with a control character opens in Word** (`B422`); a new mail's AI
  button says *Draft* (`B1212`); a text document stays text (`B1233`); the Library counts the
  folder it is in (`B1219`) and leaves Deep Research's tab when Deep Research is switched off
  (`B1275`); a reloaded research card says why it stopped (`B1188`).
- **An event fired from the mail server reaches its task with its payload** (`B1075`); a
  hand-off between steps says what it was in words (`B1096`); each task form's labels name its
  own fields when two are open (`B1041`); *Test this step* offers only what the step can be
  handed (`B1082`).

- **A task you made is never called built-in,** offered *Revert to default*, or converted into a
  housekeeping action because of its name (`B1493`, `B1495`); a crew-linked task reads on its
  crew member's clock (`B1040`); a two-step workflow's run reads *2 steps* (`B1081`).
- **A stopped reply shows what was saved** (`B1205`), a reloaded message can be deleted
  (`B1331`), a compacted chat's first page is full (`B1332`), a lapsed approval says *Ask again*
  (`B561`), a refused send is not drawn as the model's reply (`B1268`), a failed teacher is saved
  once and both runs' tokens are counted (`B1031`, `B1032`), and the assistant switching a chat's
  mode no longer becomes your default (`B701`).
- **A slash skill follows the tool switches** (`B1499`), a skill needing a tool nobody has says so
  when saved (`B1490`), and a note or reminder turn no longer carries fifteen management tools
  (`B1489`).

- **A run continued after an approval counts its steps on from the card** instead of starting at
  1 again, and a reload draws the approved call before the rest (`B1199`); a replayed stream
  draws an approved call once (`B1257`).
- **A non-admin is told why a tool is held,** and a model that calls a tool that does not exist
  is told so instead of the turn ending empty (`B1382`, `B1383`). The model is told its step
  budget on a run's last two steps (`B1344`).
- **A task's run no longer wakes the task that ran it** (`B1077`); a *Notification* result is
  also saved to its chat, as the picker said (`B1078`); a Run task step's target says why it
  stopped (`B1079`); a step test the page said had timed out is stopped and leaves no chat
  behind (`B1093`); a scheduled research run's chat is registered (`B1171`); a person's own
  task with a housekeeping action is kept as they made it (`B1063`); a scheduled run's tools no
  longer depend on the embedding index (`B1372`); a run's step log says when it was cut
  (`B612`).
- **A skill needing a switched-off tool is out of the Skills preview as it is out of the
  prompt** (`B580`), the preview says which kind of turn it shows (`B1376`), a blank rewrite
  leaves a skill as it was (`B791`), an audit that stopped for a yes says to press Test
  (`B886`), a SKILL.md inside a skill's folder is one of its files (`B591`), and a broad word is
  counted once (`B595`).
- ***every file*** **is not a schedule** (`B502`, `B503`), a question naming a skill gets the skill
  tool (`B1373`), and an English word such as *eventually* no longer opens the MCP tool array
  (`B1388`).
- **A new person's Assistant opens again,** and the Settings panels from Services to System are
  back in their column — both broken in commits that had not been pushed (`B1501`).

- **A failed call to your own workstation or model server is not held for five seconds** before
  the next one; the hold is for third-party services, and the workstation's own host names are
  paced as local now (`B1226`).
- **Every database made since `B1480` logged a skipped signature migration on start** — it still
  selected the retired `svg` column; and a notes migration re-added a retired column (`B1487`).
- **The vendored skill library stays out of what the model is shown by rule,** not by its
  confidence happening to sit under the floor; it is still found by a search and opened by
  name (`B869`).

- **Saving the install's networks keeps their notes.** The Networks panel dropped each network's
  `notes` on every save; both network lists now draw from one editor that keeps them (`B1475`).
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
- **Settings that were saved and then ignored now take effect.** Settings → Reminders → *Send from*
  was dropped on save, so every reminder went from the default account (`B1461`); a nightly skill
  audit set to 00:00 ran at 02:00, and a new hour waited a whole extra night (`B1462`); and the
  Agents panel says when the background-model slots, not its own number, are the real limit on
  scheduled runs (`B1464`). Sorting calendar events reads your saved memories again — it read a
  table nothing has written since memories moved to their own store (`B1463`). Opening Notes
  clears the fired-reminder dot, and a deleted chat's running cost is forgotten with it (`B1468`).
  A Docker install now reads `PANTHEON_SOURCE_URL`, `PANTHEON_OTLP_ENDPOINT` and
  `SEARXNG_GENERAL_ENGINES` from `.env`, as the setup guide always said it did (`B1471`).
- **Cancelling a Copilot or ChatGPT sign-in cancels it.** Settings has a *Cancel* beside the code,
  and a sign-in you cancel, or one that runs out, is dropped on the server rather than left until
  it expires (`B1482`). An urgent-email alert no longer keeps the email's subject, sender and the
  model's reason — only that it was alerted about (`B1480`). Upgrading a very old database no longer
  drops scheduled-task columns while relaxing three of them (`B1481`).

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
