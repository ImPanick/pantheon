# Screenshots and animations

Every picture in this folder is made by one command, from this checkout, against a
fictional world — nothing here was taken by hand, so nothing here goes stale on purpose:

```bash
python3 scripts/showcase/capture.py --workstation
```

Run it before a release. It takes about six minutes and needs Python with
[Playwright](https://playwright.dev/python/) (`pip install playwright` then
`playwright install chromium`), Pillow and httpx, `ffmpeg` on the `PATH`, and Docker for
`--workstation`. If the interpreter you run it with does not have Pantheon's own
requirements, pass the one that does: `--server-python .venv/bin/python`.

| Option | |
|---|---|
| `--workstation` | also start a `pantheon-workstation` container and photograph the agent's desktop. Without it the two workstation pictures are left as they are. |
| `--only chat,workbench` | just those scenes; `--list` prints them all |
| `--no-gifs` | screenshots only |
| `--force` | rewrite every file, even one that did not visibly change |
| `--keep-data` | keep the throwaway data directory to look around in |

## What it does

1. Starts `app.py` on a throwaway data directory and a free loopback port, with
   authentication on. It inherits nothing that points at real data: the database is
   the throwaway one, and every address, key and token `.env.example` names is blank —
   so neither your shell nor your `.env` can put the demo into your real install, or
   your real models into a picture.
2. Seeds a fictional world **through the API** — documents in nested folders, a chain
   of automations with a failure branch and a dry run, a workflow (two steps, one start),
   skills with an imported package and a group, notes, a week of calendar, memories. The
   skill package is the one exception: importing fetches from GitHub, so the importer's
   own `install_package` is handed the package instead, before the server starts.
3. Plays the chats on a **scripted stand-in model** (`scripts/showcase/demo_model.py`,
   shown as `scripted-demo`): its words are written down, and Pantheon runs every tool
   call for real against the demo data — the approval cards are real, and so are the
   folders the agent files into and the event it books.
4. Drives Chromium through each scene, in the `dark` and `light` palettes at 1440×900
   and three at phone width, and records the GIFs. Chromium is given a proxy address
   that answers nothing, with loopback the only exception, and any page request to
   another host fails the run.
5. Writes PNGs reduced to 256 colours where that is visually lossless (each is kept
   lossless otherwise) and two-pass palette GIFs at 900 px and 12 fps, then stops
   everything it started.

**Churn.** A picture whose pixels moved by less than 0.4% — a clock, "5m ago" — is left
as committed, and so is a GIF with as many frames that opens and closes on the same
picture, so a release-day run changes only what really changed. The live agent turn
waits on the product, so `agent.gif` is rewritten every run. The budgets (400 KB a PNG,
3 MB a GIF, 15 MB in all) are in `scripts/showcase/media.py`, and
`tests/test_the_showcase_pipeline.py` holds the README to them.

## What each file shows

Each screenshot exists as `-dark.png` and `-light.png`; the README shows whichever
matches the reader's GitHub theme.

| File | Shows |
|---|---|
| `workstation-*` | the agent's Ubuntu desktop docked beside its chat: it wrote a page, ran a command and opened it in Firefox |
| `chat-*` | an agent turn — each tool call, the approval card it raised, the answer |
| `workbench-*` | the Workbench canvas after *Show me what this would do* on a chain with a failure branch, the shelf of workflows beside it |
| `tasks-*` | the Tasks window |
| `documents-*` | the Library's documents, in folders |
| `skills-*` | the Skills window: the person's own, an imported package, a group |
| `settings-*` | Settings → Workstation |
| `palette-*` | the command palette (Ctrl+K) |
| `themes-*` | the sixteen palettes |
| `brain-*` | the Brain's memories |
| `phone-chat`, `phone-documents`, `phone-tasks` | the same at 390×844 |
| `agent.gif` | a turn live: thinking, the approval card, the tool calls, the answer |
| `workflow.gif` | wiring *if it fails* by dragging, then a dry run of the chain |
| `filing.gif` | dragging documents into folders |
| `palette.gif` | Ctrl+K: what *work* finds, then *skills* and Enter |
| `themes.gif` | switching palettes |

Every name, file and figure in the pictures is invented; the e-mail addresses are at
`example.com`.
