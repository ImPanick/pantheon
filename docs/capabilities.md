# What Pantheon can do

A reference for operators and evaluators: every major capability, how it's controlled, and who
controls it. It's written from the code on `dev`. The [README](../README.md) is the tour,
[features](features.md) is the short list with what the fork added, and the
[deployment guide](deployment.md) is how to run it.

> **Pantheon will stay free and open source, forever.** It doesn't matter if you're one person
> running inference on a single GPU or a multi-billion-dollar firm. If it's useful, use it. That's
> why I created it. *Panick*

---

## The idea

Most agent tools stop where the API stops. Pantheon gives the agent the same things a person uses
when there's no API: a Linux desktop, a browser, a shell and a real Android phone, each one
isolated per person, each one watchable live and taken back with a click. Around that is
everything an agent needs to do real work on someone's behalf: memory, skills, tools, automations,
approvals and a workspace to put results in. It runs on hardware you own, against whichever models
you choose.

---

## Models

**Any model, no vendor lock-in.** Pantheon is model-agnostic by design. Nothing in the agent loop,
the tools or computer use is written for one provider.

- **Local:** any OpenAI-compatible server (LM Studio, Ollama, vLLM, llama.cpp). Context windows are
  read from LM Studio and Ollama rather than guessed.
- **Hosted:** the frontier providers by API key, with OpenAI's pro, deep-research and codex models
  routed to the Responses API they need. Or sign in with a ChatGPT or GitHub Copilot subscription
  instead of a key.
- **Serving them yourself (the Forge):** run a model on the Pantheon host or on a remote machine
  over SSH, with hardware-aware recommendations for what fits and downloads handled for you.
- **Several at once:** `LLM_HOSTS` lists more than one model host, and Pantheon finds the servers
  on each. Built-in tasks pick a sensible
  model by default and each person can override it.
- **Made for local models:** a local model gets a small core tool set under a token budget, the
  same set every turn so the server's prompt cache holds, plus `find_tools` to reach the rest.
  Tool calls in Qwen3-Coder's format and eight other families are parsed rather than dropped.
  Long chats are compacted to about a tenth of the window: a dense summary plus the newest
  messages word for word.
- **Reasoning effort** from Low to Max per chat, and `ultrathink` for one turn at Max.
- **When a model is stuck** it can ask a stronger one, and keep the answer as a skill.

Embeddings for memory and document search run on a local model baked into the image, so they need
no service and no network. `EMBEDDING_URL` points them at your own embedding server instead.

---

## How you work with it

Each chat has a mode, and a few switches on top.

| | What it does |
|---|---|
| **Agent** | The model plans and acts with tools: shell, files, browser, desktop, phone, MCP servers, documents, mail. Every step is shown, and the ones that need a yes ask first. |
| **Chat** | Conversation without the tool loop. |
| **Research** | Deep research: it searches, reads the sources and writes a cited report. |
| **Plan mode** | Asks what you have in mind before it drafts a plan, then works the plan. |
| **Nobody mode** | Incognito. Nothing from the chat is kept: no transcript, memories, documents, notes, tasks, gallery images, speech cache or log lines. The agent can't reach your memory or past chats while it's on. |
| **Computer Use mode** | Accepted once, behind a warning. Steps inside your own workstation run without a card each time; a command that deletes or overwrites still asks. |
| **Approval: Manual or Auto** | Per chat, never inherited, never install-wide. Auto skips the asking and records that it did. Only accounts an admin allows may turn it on, and the agent can never turn it on for itself. |

**The personal assistant** is a standing agent of your own with a pinned chat and three daily
check-ins (morning, midday, evening). Its name, personality, model, tools, time zone and each
check-in's time and prompt are yours to set.

**The message box:** `@` summons an agent, `/` runs a skill or command, <kbd>Ctrl</kbd>+<kbd>K</kbd>
opens the command palette over windows, settings, commands and chats. The model can react to your
message with an emoji, and hears yours on its next turn.

**Approvals on your lock screen.** When the agent needs a yes, the request reaches your phone or
desktop as a Web Push notification, even with Pantheon closed (`ntfy` is in the stack for this).

---

## Agents

- **The Agents hall:** over 250 agents in departments and teams, each one a runbook with its own
  schedule, tools and evaluation cases that run through the real harness. Model-capability checks
  say whether the model you've picked can actually do what an agent needs.
- **Summon or hire:** `@` an agent into a chat, or hire one to run on its own schedule.
- **Teams:** agents grouped to work a job together.
- **The roster is growing,** and the agents already there keep getting sharper.

---

## Tools and MCP

- **Built-in tools:** shell, filesystem, coding and code navigation, git, web fetch and search,
  the browser, the desktop and phone (`computer`), documents, sessions, background jobs, model
  calls, network checks and admin tools. Each tool has a registered effect (read, write, reach
  outside), and that effect decides whether it asks first.
- **MCP servers:** connect any MCP server, local or remote, including OAuth-protected ones. Built-in
  servers ship for image generation, RAG over your documents and email; a Playwright browser server
  is available and starts only when used, so a fresh install reaches nothing on its own. MCP tools
  stay on hand in Agent mode.
- **MCP servers it writes for itself:** name the tools you want and Pantheon scaffolds an MCP server
  in your workstation, starts it, completes the handshake and lists its tools to prove it works. An
  admin then registers it from a list. The agent can't register a server by itself, on purpose:
  text the agent reads must never become a program it runs.
- **The vault:** keys and logins of your own that the agent may use, inside the rules you set. A
  git host's token signs in `git` and `gh` in the agent's shell.
- **Parallel networks:** declare network segments and scope a run to one.

---

## Skills

- **Learned from your chats.** After a chat that took real work, the agent writes down how it got
  there as a skill. Skills it's at least 85% sure of come back on their own next time they fit; you
  set that bar or approve each one yourself (Brain → Skills).
- **Written on request.** Ask in chat and it writes, edits and publishes a skill on the spot.
- **Imported.** Packages from skills.sh or GitHub arrive as packages, with their sections intact.
- **Groups** switch a set of skills on or off together.

---

## The Brain

What Pantheon learns about you as you use it: preferences, projects, people and facts. Every
memory shows where it came from and how often it's been used, and you can read, edit or delete all
of it. Retrieval runs on local embeddings; on the retrieval test set it puts the right memory first
far more often than the keyword search it replaced (figures, and how to score it on your own data,
in the [README](../README.md#a-memory-that-actually-recalls) and the [proof ledger](../LEDGER.md)).

---

## Automations

- **From a sentence.** "Every morning at 7:30, summarize my unread mail" becomes a scheduled task.
  "When this finishes, do that and then this" becomes a drafted workflow.
- **The Workbench:** a canvas where steps are wired by dragging from a step's port, on success or
  on failure. If and Switch without code. Steps can be HTTP calls, MCP tools, skills, model calls
  or code run in your workstation. Versions you can undo, and workflows saved as files you can hand
  to someone else without your keys.
- **Safe by default:** a drafted workflow arrives switched off with every step flagged for you to
  check, a dry run plans the chain without running anything, and a failed step comes back with the
  model's explanation and a fix you can apply.
- **Triggers:** schedules with time zones, retries and time limits; mail arriving; webhooks.
- **Concurrency:** `PANTHEON_TASK_CONCURRENCY_CAP` sets how many scheduled tasks may hold the model
  at once (1 to 16). One task never runs twice concurrently.

---

## Computer use: the workstation

Each person gets a Linux desktop of their own for the agent to work in, kept between chats.

- **What's in it:** XFCE, a shell, Python, files, Firefox (locked down by policy), sudo by default,
  and a projects folder shared with Pantheon. Streamed live over KasmVNC: watch the agent, take
  over, hand it back, or reset to a starting point you saved.
- **Distros:** Ubuntu 24.04 by default, and Debian 13, Fedora 45 or Rocky Linux 9 where the operator
  has enabled them. Each person picks their own.
- **Backends:**

  | Backend | What it is | When |
  |---|---|---|
  | `vm` | A QEMU/KVM virtual machine per person, or a shared one, in the `workstation-vm` service | Hosts with KVM. The default under `auto`. |
  | `container` | One container, a Unix account and desktop per person | Hosts without KVM |
  | `remote` | A workstation daemon on another machine, reached over pinned TLS | Desktops on a separate box or hypervisor VM |
  | `auto` | The VM where Docker can use KVM, else the container | Default |

- **Own machine or shared machine:** on the `vm` backend an admin decides, per person, whether
  someone gets a VM of their own or an account on one machine several people share. A default
  covers new accounts and each person can be named on their own, so power users get a dedicated
  machine and everyone else shares one. On the shared machine sudo is always off, other people's
  processes are hidden, and only Unix permissions keep homes and projects folders apart. Moving
  someone powers off the machine they leave and keeps its disk for when they come back.
- **Resources:** an admin sets the memory per machine and the pool of processors; each person on a
  machine of their own picks their processor count within that pool. Idle machines power off and
  give their memory back.
- **Network:** an admin chooses full access, internet only, or none, enforced from outside the
  desktop where its root user can't change it. Agents may read LAN or tailnet addresses by URL
  (never loopback or cloud metadata) unless an admin turns that off.
- **The agent's own browser:** a separate live Firefox with its own tabs and address bar, used
  whenever the workstation can't answer yet.
- **Screen grounding:** every screenshot the agent sees has a numbered box on each control, read
  from the accessibility tree, the page's own elements or the image itself. It clicks by number
  instead of guessing pixels. `scripts/grounding_eval.py` measures the difference on your model.
- **Any model that can see can drive it:** vision plus tool calling plus reasoning is enough.
  From testing, use something larger than 12B parameters; smaller models tend to avoid the
  computer-use tool and fall back to shell commands and web fetches.

---

## Computer use: the phone

A real Android phone per person, not a desktop browser at phone width.

- **Google's Android Emulator, Android 15 (API 35),** accelerated by the host's hypervisor: KVM on
  Linux, WHPX on Windows, Hypervisor.Framework on macOS. Nineteen device profiles: phones,
  foldables and tablets from Pixel, Galaxy, Razr, OnePlus and Nothing.
- **Shared with the agent:** live beside the chat. Click to tap, drag to swipe, right click for
  Back; take it over and hand it back. The agent uses the same `computer` tool as on the desktop,
  plus side keys, rotate, fold and unfold, and open a URL, with numbered marks from Android's own
  UI tree.
- **Files both ways:** a USB-style shared folder links your projects folder to
  `Download/PantheonUSB` on the phone.
- **Isolated per person:** own SDK home, ADB keys, console token and emulator. Secure ADB is
  checked at boot, scrcpy-server must match a pinned SHA-256, and a phone host on another machine
  needs TLS with a pinned certificate.
- **Where it runs:** `android-vm`, a Compose service of its own beside the desktops, one Android VM
  per person; on a Mac, a native host worker beside Docker. See [phones](deployment.md#phones).

---

## The rest of the workspace

- **Documents:** a writing-first editor with AI edits and suggestions; Markdown, HTML and CSV;
  nested folders; PDF and Word export.
- **Mail:** IMAP/SMTP with triage, tags, summaries, reminders and reply drafts; Google and Microsoft
  sign-in. Mail the agent writes is held until you say so.
- **Notes, tasks and a calendar** with CalDAV sync; contacts.
- **Research and Compare:** deep research with source reading, and blind side-by-side model tests.
- **Images:** generation, editing and upscaling, and a gallery.
- **Voice:** talk to it like a call and cut it off mid-sentence. Whisper listens; Kokoro, Piper or
  Chatterbox (on an NVIDIA GPU) speak. All on your hardware.
- **The cockpit:** one window with a tuckable workspace column (document, workstation, browser) in
  four layouts, twenty palettes, light and dark, and the whole app at phone width.

---

## Accounts, isolation and administration

- **Always a sign-in.** Accounts with display names and two-factor authentication. Open sign-up is
  an admin switch, off on a new install.
- **Per-account privileges** an admin sets: agent, assistant, shell, browser, workstation,
  workbench, research, compare, documents, mail (and private mail), notes, tasks, calendar, image
  generation, memory management, Auto approval and operating the instance. An admin can also limit
  which models each person may use.
- **People are separate.** Each person has their own desktop VM or account, home, projects folder,
  phone, memories, skills, chats and vault. Each person always gets their own phone and their own
  desktop session; when an admin puts several people on the shared desktop machine, each is a
  separate Unix account there with sudo off.
- **Nothing phones home.** Outbound calls are paced and listed, a fresh install reaches no external
  service on its own, and the workstation's screenshot pipeline fails if a page tries to reach
  another host.
- **Admin tools:** backups and restore (`scripts/pantheon-backup`), a diagnostic bundle, admin wipe,
  instance-wide settings.

---

## Integrating with it

- **API tokens** with scoped profiles: `chat`, `metrics` (`metrics:read`), and narrow read/write
  profiles for to-dos, documents and email drafts.
- **Webhooks** in and out, and workflows triggered by them.
- **CLI:** `scripts/pantheon <name>` dispatches to `pantheon-mail`, `pantheon-tasks`,
  `pantheon-docs`, `pantheon-memory`, `pantheon-skills`, `pantheon-mcp`, `pantheon-deploy`,
  `pantheon-backup` and more, the way `git` finds `git-foo`.
- **Observability:** Prometheus at `/metrics`, OTLP push with `PANTHEON_OTLP_ENDPOINT`, and
  `/api/ready` for health.

---

## On the roadmap

Infrastructure work that's designed or under way, so you can plan around it:

| Item | Status |
|---|---|
| `android-vm`: phones as their own Compose service, one Android VM per person beside the desktops, with its own admin pool | Shipped |
| An iOS VM family, as a third sibling service | Planned, nothing built |
| Own desktop VM or an account on a shared one, chosen per person by an admin | Shipped |
| A pool of several workstation hosts that desktops are spread across | Planned, nothing built |
| Direct hypervisor backend: each person's desktop and phone created as sibling VMs on Proxmox, vSphere or KubeVirt | Planned, nothing built |
| A Docker Swarm stack file | Planned |
| A Helm chart for Kubernetes and k3s, with the KVM options in [the deployment guide](deployment.md#kubernetes-and-k3s) | Planned |

Everything else that's open, with how each item will be verified, is in
[`.pantheon/ROADMAP.md`](../.pantheon/ROADMAP.md).

---

## Licence

[AGPL-3.0-or-later](../LICENSE), the same licence as [Odysseus](https://github.com/pewdiepie-archdaemon/odysseus),
which Pantheon was forked from and has been built on since. Free to use at any scale. If you change
it and let other people use it over a network, offer them your source; the
[deployment guide](deployment.md#the-licence-in-a-deployment) says how in three lines.
