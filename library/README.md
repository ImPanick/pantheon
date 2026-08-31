# `library/` — capability that ships with the product

Everything here is vendored, pinned, and works with **no network at all**. That
is the point: `Law 16` says a fresh Pantheon install reaches nothing until a
person links something, and a skill library that phones home to be useful would
be that rule broken on day one.

## `ecc/` — 286 skills

From [ECC](https://github.com/affaan-m/ECC) by Affaan Mustafa, **MIT licensed**
(`LICENSE` here, and `licenses/ECC-MIT.txt` at the repo root). Attribution is in
`CREDITS.md`.

They needed no conversion. ECC writes `name:` / `description:` YAML frontmatter
in `SKILL.md`; that is exactly what `services/memory/skill_format.py` reads, so
all 286 parse with the reader Pantheon already had.

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
