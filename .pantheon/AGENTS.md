# Pantheon — Working Agreement

Read this before touching anything. It is short on purpose.

Pantheon is a fork of **Odysseus** (`pewdiepie-archdaemon/odysseus`, AGPL-3.0).
The whole programme is **elevation, not rewrite**. The engines already work. What was
missing was the surface, the lighting, and the room you stand in to build things.

---

## The three rules

**1. Add. Never subtract.**
If a feature exists, it survives. If you think something should go, it goes in your
handoff note as a proposal — you do not delete it. The only exceptions are the items
explicitly marked `DELETE` in the roadmap, each of which was proven dead by audit.

**2. Names in `FORBIDDEN.md` do not move.**
Class names, data attributes, storage keys, env vars and wire values listed there are
load-bearing. Renaming one silently breaks the accessibility shim, a CI test, or a
user's stored preferences. Style freely; rename nothing on that list.

**3. Verify against the code, not against the plan.**
The roadmap was written from six audit passes and it still contained wrong numbers when
an adversarial pass checked it. If a task's premise does not match what you find in the
source, **stop and write it in your handoff note**. Do not implement a task whose
premise is false.

---

## Before you start a task

```
□ Read the task's full entry in ROADMAP.md — including `Depends`
□ Read the handoff note for your area (.pantheon/handoff/<area>.md)
□ Confirm every dependency is ticked
□ Confirm the task's premise is true in the current source
□ Check the `CI` flag — if set, read the named test before editing
```

## Before you tick a task

```
□ The change is made and verified by the task's own Verify line
□ `python -m pytest -q` passes
□ `python -m py_compile app.py routes/*.py src/*.py` passes
□ `node --check static/js/<each file you touched>.js` passes
□ You ran the app and looked at it (any visual change)
□ Your handoff note is updated
□ The cache-buster is bumped if you touched a static asset
```

Tick by changing `- [ ]` to `- [x]` in `ROADMAP.md` and appending your agent id and the
date to the task line. Never tick a task you did not finish. A partially done task stays
open with a note.

---

## Handoff notes

One file per area, at `.pantheon/handoff/<area>.md`. Append; never rewrite history.

Areas:

```
identity     tokens      unnerf      css-hygiene
wire         trace       composer    queue
plan         trust       skills      automations
mcp          surfaces    a11y        release
```

Entry format — keep it to what the next agent actually needs:

```markdown
## [P4-07] Unify the agent-thread builder — 2026-08-25 — agent:a3f9c21b

**Done.** Extracted one builder into `static/js/agentThread.js`. All six call sites
now import it.

**Found that wasn't in the roadmap.** Compare mode had a seventh copy inside a
`setTimeout` at `compare/stream.js:611`. Folded in.

**Chose deliberately.** The six copies had drifted three ways. I took compare mode's
friendly-label behaviour as correct (it matches the ledger's Replace verdict) and
dropped the raw tool id everywhere.

**Left undone.** History replay still renders the diff block differently — it omits
the stat line. Not blocking; filed as P4-07b.

**Next agent needs to know.** The builder takes `(event, mode)` where mode is
`'live' | 'replay' | 'compare'`. Do not add a fourth mode without reading the drift
notes at the top of the file.

**Touched.** static/js/agentThread.js (new) · chat.js · chatRenderer.js ·
compare/stream.js · compare/index.js · style.css (agent-thread block)
```

If you found a bug you did not fix, it goes in the note **and** as a new `Bxx` task at
the bottom of the roadmap. Nothing gets lost in a note nobody re-reads.

---

## Ground truth

- **The ledger** — the decision document. Every task traces to a row in it.
- **The mockup** (`design/pantheon-v10.html`) — what it should look like when done.
  It is a mockup: it fakes its data and it does not reproduce every state. Where it
  disagrees with the ledger, **the ledger wins** and you file the discrepancy.
- **The source** — beats both. See rule 3.

---

## Operational facts that bite

- **`static/` has no bind mount.** Every CSS or JS change needs
  `docker compose up -d --build`. A restart serves the old files.
- **Bump the cache-buster** on any changed static asset, or browsers keep the old one.
- **The approval-path modules share one version string** and must be bumped together,
  or a browser pairs new code with a cached interceptor and the approval click lands
  on the wrong branch. The list is in `FORBIDDEN.md`.
- **No build step, no bundler, no framework.** ES modules load directly.
- **Nonce every inline script.** The CSP requires it.
- **Add zero external requests.** Self-host anything new.

---

## When to stop and ask

- A task's premise is false in the source.
- A change would touch something in `FORBIDDEN.md`.
- A change would touch the approval card's markup (see `DEFERRED.md`).
- You are about to remove a security control. Read `FORBIDDEN.md` § Never Lift first;
  if it is on that list, the answer is no.
- Two tasks conflict and the roadmap does not say which wins.
