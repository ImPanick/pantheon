# Everything in Pantheon

The README covers the headline features. This is the full list, and what the fork added over [Odysseus](https://github.com/pewdiepie-archdaemon/odysseus).

## Agents and models
- Local or API models: OpenAI-compatible servers (LM Studio, Ollama, vLLM, llama.cpp) and the frontier
  providers, with OpenAI's pro, deep-research and codex models routed to the Responses API they need
- Model serving on this machine or a remote host over SSH, with hardware-aware recommendations and
  downloads
- Tool execution, MCP servers (and a builder that makes one in your workstation and tries it before an
  admin registers it), shell, filesystem, skills and memory, behind per-person approval rules
- Skills learned from finished chats, used again on their own above a confidence bar you set
  (85% by default), and written, edited or published from chat when you ask; a stuck model can ask a
  stronger one and keep the answer as a skill
- Automations from a sentence in chat: a scheduled or event-driven task, or a multi-step workflow
  drafted switched off for you to check in the Workbench, where steps are wired by dragging from a
  port; a failed step comes back with the model's explanation and a fix you can apply
- Tool approvals on your lock screen, by Web Push, with Pantheon closed
- Models by API key, or by signing in with a ChatGPT or GitHub Copilot subscription
- Plan mode that asks what you have in mind before it drafts; reasoning effort from Low to Max, and
  `ultrathink` for one turn at Max
- Chat compaction that brings a long conversation to about a tenth of the window from a dense summary
  plus the newest messages word for word
- Emoji reactions both ways — the model can react to your message, and hears yours on its next turn
- A vault of your own for keys and logins the agent may use, within the rules you set (a git host's
  token signs in `git` and `gh` in the agent's shell)

## Computer use
- The workstation: desktop, live stream with take-over, a saved starting point and Reset, per-person
  homes and projects folders, sudo by default, networks declared per person
- The agent's own live Firefox on a separate screen, with its own tabs and address bar
- Screen grounding with numbered marks; *Computer Use* mode, accepted once behind a warning, so steps
  inside your own workstation run without a card — a command that deletes or overwrites still asks
- Devices: Android phones, foldables and tablets on Google's emulator, or a mobile view without hardware acceleration

## Workspace
- Deep research with source reading and reports; Compare for blind side-by-side model tests
- Documents: a writing-first editor with AI edits and suggestions, Markdown, HTML and CSV, nested
  folders, PDF and Word export
- Email over IMAP/SMTP with triage, tags, summaries, reminders and reply drafts; a workflow can start
  when mail arrives
- Notes, tasks and a calendar with CalDAV sync; gallery and image editor
- The cockpit: one window with a tuckable workspace column (Document, Workstation, Browser) in four
  layouts, twenty palettes in one material, a command palette, and the same app at phone width

## Voice
- Voice chat like a call, dictation that says *Listening . . .* and *Transcribing . . .*, and a
  per-person *Conversation* switch that reads every reply aloud — Kokoro, Chatterbox or Piper, Whisper
  for speech-to-text, all on your own hardware

## Running it
- One `docker compose up`; sign-in always on, accounts with display names, 2FA, and an
  admin switch for open sign-up
- Nothing phones home: the workstation's Firefox is locked down by policy, and the screenshot pipeline
  itself fails if a page tries to reach another host

## What the fork added

Pantheon forked [Odysseus](https://github.com/pewdiepie-archdaemon/odysseus) — the fork began on 24 August 2026 — and has
been built on every day since. Everything below arrived after the fork; each has its row in
[`.pantheon/ROADMAP.md`](../.pantheon/ROADMAP.md), where how it was verified is written down.

| | Added since the fork |
|---|---|
| **Interface** | The cockpit: a new shell with a docked workspace column, one material in twenty palettes, the composer deck, `/` and `@` pickers, a next step waiting for <kbd>Tab</kbd> |
| **Computer use** | The workstation (container or KVM VM), KasmVNC live desktop with take-over, the agent's own live browser, four OS images, screen grounding, Computer Use mode, saved starting points |
| **Devices** | Android phones, foldables and tablets the agent drives, installed on demand |
| **Agents** | The Agents hall — 259 agents, 18 teams, evaluation cases through the real harness, model-capability checks |
| **Automations** | The Workbench: canvas, branches, If/Switch, dry runs, *Describe it*, versions you can undo, workflows as files you can hand someone without their keys |
| **Voice** | Voice chat, local speech-to-text, Kokoro/Chatterbox/Piper replies, the Conversation switch |
| **Local models** | The slim tool set and `find_tools`, nine more tool-call formats read, reasoning effort, context windows read from LM Studio and Ollama, compaction that works on a slow model |
| **Memory** | The Brain rebuilt around a local embedding model that needs no service and ships in the image |
| **Trust** | Mailbox and service sign-in reduced to one record type, an agent that reaches its host only behind a denylist it cannot edit, every outbound call paced, a checker in CI for each way a fact here has been caught rotting |

The numbers behind each — and the command that reproduces them — are in the [proof ledger](../LEDGER.md).
