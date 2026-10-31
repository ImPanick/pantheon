# `library/` — capability that ships with the product

Everything here is vendored, pinned, and works with **no network at all**. That
is the point: `Law 16` says a fresh Pantheon install reaches nothing until a
person links something, and a skill library that phones home to be useful would
be that rule broken on day one.

## `emoji/` — 4,147 glyphs

[OpenMoji](https://openmoji.org)'s black (monochrome line-art) set, **CC BY-SA
4.0**. Every emoji the product renders. Before this, they were fetched from a
CDN on first use — same-origin from the browser's side, but the *server* reached
a third party on roughly the first assistant reply, because models emit emoji
constantly.

**One 5 MB JSON, not 4,147 files.** The same bytes cost 18 MB on disk as
individual files; a single blob is kinder to git and to the filesystem. Each
entry holds only the inner markup, because every glyph in this set repeats the
same six stroke attributes — those are hoisted onto one wrapping `<g>` at serve
time, which is most of the 7.6 MB → 5.0 MB saving. It loads lazily, so an
install that never renders an emoji never pays the memory.

That stripping is an adaptation, so the vendored file is CC BY-SA 4.0 as well.
Attribution is in `CREDITS.md`; it was **missing entirely** until this landed,
and the obligation was not new.

## `pantheon/` — Pantheon's own skills

Procedures written for this product's own tools, **published and switched on**
(`B1419`, `B1715`). Eleven are the core set (`category: core`), each offered
when the tools it drives are allowed:

| Skill | Teaches | Needs |
| --- | --- | --- |
| `clarify-the-goal` | look first, ask only what changes the work, restate the vision, then plan | `ask_user` |
| `web-research` | several searches, read the sources, cross-check, cite | `web_search`, `web_fetch` |
| `browse-a-website` | the real browser by numbered elements, vault sign-in, stop before anything irreversible | `agent_browser` |
| `debug-a-failure` | reproduce, read the whole error, one hypothesis, smallest fix, rerun | `bash`, `read_file` |
| `change-code-safely` | read the project's conventions, small edits, its own tests | `read_file`, `edit_file`, `bash` |
| `review-code-changes` | read the change and its callers, findings with file and line | `bash`, `read_file` |
| `analyze-data` | inspect before computing, sanity-check, show the derivation | `python` |
| `write-a-document` | reader and purpose, outline, draft in the editor, revise by edits | `create_document` |
| `summarize-for-a-reader` | answer first, exact numbers, attribution, what was left out | — |
| `remember-what-matters` | search before adding, edit not duplicate, no secrets | `manage_memory` |
| `schedule-recurring-work` | a task rather than a one-off, UTC times, dry run | `manage_tasks` |

Four are for the workstation:

| Skill | Teaches |
| --- | --- |
| `workstation-desktop` | the `computer` tool — every action, the 1280×800 frame, the tray, keys, Firefox shortcuts; `references/keys.md` |
| `workstation-apps-and-windows` | starting, finding, focusing, arranging and closing programs from the shell with `xdotool` |
| `workstation-shell` | where commands run, the person's own projects folder (`$PANTHEON_PROJECTS`), root, the network, servers that outlive the call |
| `workstation-self-test` | build, serve, `curl`, look in Firefox, read the console, fix, report with evidence |

Each declares `requires_toolsets` for the tools it drives, so a turn gets them
exactly when the loop offers those tools — for these, when the workstation is
on and this person may use it. Every command in them was run on a desktop built
from the workstation's own `.jwmrc` and Firefox policy before it was written,
and the desktop's again on the XFCE desktop built from its skeleton's
`.config` when that replaced JWM (`D-2026-10-31-02`).

This layer is read **before** `ecc/`, so a first-party skill shadows a vendored
one of the same name, and a person's own skill of the same name shadows both,
for that person. It belongs to the install: every person's model is offered it,
signed in or not. To change one, fork it — the copy is yours and wins (from
the Workshop with sign-in off; signed-in forking is `B1421`).
`tests/test_the_workstation_skills_ship_switched_on.py` holds what they say to
the protocol they describe (screen size, limits, the action list).

## `ecc/` — 286 skills

From [ECC](https://github.com/affaan-m/ECC) by Affaan Mustafa, **MIT licensed**
(`LICENSE` here, and `licenses/ECC-MIT.txt` at the repo root). Attribution is in
`CREDITS.md`.

They needed no conversion. ECC writes `name:` / `description:` YAML frontmatter
in `SKILL.md`; that is exactly what `services/memory/skill_format.py` reads, so
all 286 parse with the reader Pantheon already had.

The model is not shown them by default (`D-2026-10-26-01` §8), and the
Workshop's card list leaves them out. They are on the **Skill library** shelf
at the bottom of the Skills window instead (`GET /api/skills/library`): **Add**
copies one into the person's own skills, published, and from then on their
model is offered it and they can edit it (`B1715`).

**What is vendored:** the `SKILL.md` text. 286 files, about 2.5 MB.

**What is not:** ECC's scripts, assets and documentation. Those are third-party
executables, and a product whose stated intent is to depend on nothing external
should not ship code it has not read to run on someone's machine. Skills are
prose an agent reads — a different risk, and an auditable one.

Six of the 286 name a commercial API in their own text (`videodb`,
`nutrient-document-processing`, `social-publisher`, `ito-baskets`, `x-api`,
`scientific-db-uspto-database`). Each is confined to a directory named after
what it does, and none causes any traffic until a person opens it and supplies
their own credentials. They are kept rather than removed, because deleting a
capability and defaulting it off are different acts, and `Law 16` asks for the
second.

### How it loads

`SkillsManager` reads this as a **read-only layer underneath the user's own
skills** in `data/skills/`. Three consequences worth knowing:

* **`data/` is disposable here.** Wiping it does not cost you the library.
* **A user skill of the same name shadows the bundled one.** That *is* the fork
  mechanism: save over a bundled name and yours wins, with no merge and nothing
  to undo.
* **It is off every write path.** `_iter_skill_files` has three callers and one
  of them rewrites every file it is handed, so the library gets its own
  iterator. There is a test for this.

### Updating

Explicit, never automatic:

```sh
python3 scripts/update-skill-library.py --check    # what would change
python3 scripts/update-skill-library.py --apply    # write it, then review the diff
```

It fetches through the outbound limiter, refuses to apply if any incoming skill
fails to parse with this product's own reader, and regenerates `MANIFEST.json`
with the new commit and per-file checksums so the diff is reviewable.

An auto-updating bundle would be an external dependency wearing a different hat,
and a supply-chain hole besides — it turns *review the diff* into *hope upstream
is fine*. `MANIFEST.json` pins a full upstream commit for exactly that reason.
