# DECISIONS — settled, with the reasoning that settled them

Recorded so no agent re-litigates them and no reviewer flags them as oversights.
Each entry names what was decided, what it costs, and what would reopen it.

---

## D-2026-08-26-01 · P2-01 — delete `is_safe_file_type` entirely

**Decided:** delete the function and its call site whole. Both blocklists go: the
9 blocked MIME types *and* the 9 blocked extensions
(`.exe .dll .bat .cmd .vbs .ps1 .jsp .asp .aspx`).

**Why this is defensible and not just permissive.** The scouts verified all four
load-bearing facts against the source:

- **Nothing on the server executes an upload.** No exec path touches `UPLOAD_DIR`,
  and `UPLOAD_DIR` is not a static mount — `app.py:509` mounts only `/static`.
- Every download that names a file carries `Content-Disposition: attachment`.
- `X-Content-Type-Options: nosniff` is set, and the app CSP applies.
- `.svg` — the one genuine stored-XSS vector in this area — was **never** in either
  blocklist, so the check was not buying what it appeared to buy.

**What this costs, stated plainly.** Two things the check really did do, and now
does not:

1. The extension blocklist is libmagic-independent, so it caught `.exe` on every
   install regardless of whether python-magic was present. That goes away.
2. The `?thumb=1` branch (`routes/upload_routes.py:402`) passes no `filename=`, so it
   emits **no** `Content-Disposition` at all. "Every download carries attachment" is
   true of the named-file path, not that one.

Accepted deliberately. This is a single-admin box on a home LAN with no other users,
where the operator uploading a `.exe` is the operator who owns the machine.

**What would reopen this.** A second user account. Any route that serves an upload
without forcing disposition. Any exec path that reaches `UPLOAD_DIR`. If Pantheon
ever grows a multi-user or hosted mode, this decision is void and the check comes
back — stronger than upstream's, with `.svg` in it.

**Not in scope.** `P2-24`'s font-upload allowlist stays and gets stronger: those
files land under the static mount and are served with no forced disposition. That is
the genuine exception, and it is not affected by this decision.

---

## D-2026-08-26-02 · R-06 — stay private, close the licence gaps, flip public when ready

**Decided:** the repo stays private. `P0-14 … P0-27` — the notices, the credits and
the AGPL §13 source link — close first. Public comes after, on our timing.

**What that means for the build loop.** Agents cannot clone the fork, so until the
flip:

```
agents → read /work/base (upstream at b4d1293) → produce patches
       → cybertooth applies → commit → push
```

The desktop bridge stays on the critical path for writes. It has dropped three
times, so every batch of agent work lands as a reviewable patch rather than a live
edit, and nothing is left half-applied when the link goes.

**Why this is the right order anyway.** The §13 source link is not paperwork — it is
the one obligation that attaches the moment other people can reach the software.
Publishing first and fixing after would mean shipping the fork in exactly the state
the audit was written to prevent.

**What would reopen this.** Nothing in the plan. The flip is a P0 completion event,
not a decision to revisit.

---

## D-2026-08-26-03 · The themes stay, and so do the animated backgrounds

**Decided:** Odysseus's theme system is kept intact — all 16 built-in themes, the 8 custom
slots, and the per-theme animated backgrounds. This is a **keep**, and it constrains
everything downstream that touches colour.

**What is protected, precisely.**

- The 16 entries in `THEMES` (`static/js/theme.js:11`) and their `bg / fg / panel / border
  / red` values. Tune a value if it is genuinely wrong; do not restyle a theme wholesale
  and do not remove one.
- `THEME_DEFAULT_PATTERN` — the map that gives each theme its own background. This is the
  feature that makes the themes feel authored rather than recoloured: `midnight` gets
  rain, `cyberpunk` gets synapse, `forest` gets petals, `ocean` gets constellations,
  `terminal` gets perlin-flow, `retrowave` gets embers, `cute` gets sparkles.
- The 8 patterns and their machinery: `_BG_CLASSES`, `_CANVAS_PATTERNS`, the seven
  `createElement('canvas')` animators, the `bg-pattern-*` classes and the `*-canvas`
  element ids. `dots` is the CSS-only one (`style.css:209`); the other seven are canvas.
- The per-theme controls layered on top: `--bg-effect-color`, `--bg-effect-intensity`,
  `--bg-effect-size`, and the frosted toggle.

**What this cost — and it was worth finding.** `P1-01`, the headline task of the entire
token phase, was written as *"define `--accent` in `:root`"*. Auditing it against this
decision showed it would have destroyed the thing being protected:

Of the 799 `var(--accent…)` sites in `style.css`, **508 are `var(--accent, var(--red))`**.
They resolve today to the theme's own `red`, which `applyTheme()` sets at
`static/js/theme.js:263`. A `:root` definition beats a fallback — so all 508 would have
flipped to one global colour, and all 16 themes would have converged on it in one commit.
The task would have reported success. Every screenshot would have looked deliberate.

`P1-01` now sets `--accent` **per theme**, seeded from that theme's `red`, one line inside
`applyTheme()`. The 508 fallback sites resolve to exactly what they resolve to now, the
bare sites resolve for the first time, and each theme keeps its identity. Strictly better
than the original plan, and it costs less.

**Still allowed.** `P10-04` (contrast audit across all 16 themes) and `P10-05`
(reduced-motion guard over the 7 animators) both stand. A reduced-motion guard **respects
an operating-system setting** — it does not disable the feature, and an agent that reads
it that way has misread it. New themes may be added; new patterns may be added.

**What would reopen this.** Nothing. This is a product decision, not a technical one.

---

## D-2026-08-26-04 · The deployment assumption changed — what that voids

**What changed.** Pantheon was planned for one self-created admin on a home LAN with
disposable data. It is now being planned to survive **real infrastructure**: OIDC/SSO against
a bring-your-own provider, roles, and admin-controlled throttling and quotas. `P11` and `P12`
exist because of this.

**This is not a rewrite of the earlier decisions. It is their trigger condition arriving.**
Each of the following was decided honestly for a single-admin box, and each named the
condition that would void it. The conditions are now foreseeable rather than hypothetical.

| Decision | What it assumed | What now |
|---|---|---|
| **D-2026-08-26-01** — delete the upload type blocklist | "a second user account" listed as a voiding condition | Stands for today's deployment. `P11-09` restores it — **with `.svg` in it this time** — gated on multi-user being enabled, not unconditionally. |
| **P2-10** — delete the upload concurrency guard | one operator cannot meaningfully denial-of-service themselves | Reasoning collapses under real users. Becomes `P12-06`: an admin-controlled per-role setting, default off. |
| **P2-05** — drop the memory-import allowlist | nothing is persisted or re-served, so extension filtering guards nothing | Still true, and still the right call. But the **size and rate** limits become the real control, which means they must be per-role and adjustable — `P12-01`, `P12-05`. |
| **P2-08** — scale the attachment budget off the context window | one operator, one machine, one window | Right shape, wrong ceiling. Under `P12-04` it gets a per-role cap, which is also what stops a proven-window scale-up from handing someone twelve untrusted skill blocks. |
| **P2-21** — admin-gate the built-in capability reads | argued as cheap insurance on a single-admin box | No longer insurance. `P11-10` makes it required. |

**The one that does not move.** `P2-25` and `P2-26` — do not prune the tool blocklists — get
*stronger* under multi-user, not weaker. Every argument for keeping them assumed a trusted
operator; none of them assumed an untrusted one.

**What this decision explicitly does not do.** It does not turn Pantheon into a SaaS product,
add a subscription surface, or introduce a hosted tier. It makes a self-hosted platform
survivable at organisational scale, which is a different thing — and it is what makes "use it
internally at your company" from the README an honest offer rather than a slogan.

**Sequencing.** `P11` and `P12` depend on nothing in `P0`–`P10` and block nothing in them.
They are a parallel track. The one real ordering constraint inside it: **`D-05` telemetry comes
before anything adaptive**, because you cannot tune a limit you cannot measure, and today token
usage is stored as a running counter with the time dimension discarded at write.

---

## D-2026-08-26-05 · Cookbook becomes the Forge

**Decided:** `Cookbook` → `Forge`. `P0-29`.

**Why the old name failed.** It reads as a recipe box. It is a model-serving control plane:
remote host registry with SSH keys and connection testing, GPU detection and hardware fit,
weight downloads from HuggingFace and Ollama, vLLM / llama.cpp / Ollama launches held open in
tmux, process kill, task-status polling. Seventeen routes. Raw weights and hardware go in; a
running inference service comes out. That is a forge.

**Why not Olympus** — and this is worth recording, because it is a positioning decision rather
than a naming one. Olympus would have cast the models as gods in residence. AI is already
under heavy and often fair criticism for exactly that framing, and a self-hosted tool has no
business adding to it. The name would have made a claim about what these things *are*. Forge
makes a claim about what the operator *does*, which is the honest one and the better story.

**`recipe` survives.** 242 occurrences, and a vLLM recipe genuinely is a parameterised launch
config — the confusion was never about recipes, it was the section name. Renaming it would be
churn for its own sake.

**Scale.** 3,533 occurrences, 172 files, 43 paths — larger than the Odysseus→Pantheon sweep
was at 2,929. `scripts/pantheon-init.sh` is proven and parameterises cleanly, and it now
carries four fixes learned the hard way. Use it; do not hand-roll a second sweep.

---

## D-2026-08-26-06 · The decision ledger, answered — all eighteen

**All eighteen open calls are settled.** Recommendations taken, hybridised with the scaling
track that opened after the ledger was written. Five answers shifted because the deployment
assumption changed mid-conversation; those are marked **amended** and the reason is on each.

The ledger itself is superseded by this entry.

### Finishing P2

| | Answer | Note |
|---|---|---|
| **P2-05** | **Drop the allowlist entirely.** Decode; reject only what fails. Keep the PDF extractor and the `.json` fast path as branches. | Nothing is persisted or re-served, so extension filtering guards nothing. **Amended:** size and rate become the real control, which makes them `P12-01` / `P12-05` per-role settings rather than constants. |
| **P2-08** | **Scale the budget off the model's context window**, falling back to today's 24,000 when the window cannot be proven. Keep first-come-first-served. | **Amended:** gets a per-role ceiling under `P12-04`. Must use `budget_context_for_model(…, fallback=0)` — the same function `P2-09` got wrong. Reconcile all three numbers together: shared 24,000, PDF 15,000, per-file 30,000. |
| **P2-10** | **AMENDED — do not delete it. Make it an admin control, default off.** | The original recommendation was delete, reasoned on "one operator cannot denial-of-service themselves". That reasoning does not survive `P11`. Lands as `P12-06`. |
| **P2-12** | **Drop the size clause in both files, and pin `_has_visible_attachments` to the old predicate.** Keep the two filename patterns. | Fixes the visible bug and changes nothing else. The related-thread lookup is out of scope and stays out. Write the first test — there is no coverage anywhere. |
| **P2-14** | **Anchor patterns 1–6 to a whole-message match; convert pattern 7 into a confirmation mode** that arms the approval gate instead of stripping tools. | "Ask me before using tools" currently costs 81 tools plus all MCP. That is not an over-eager filter, it is an inverted one. `blocks()` and `block_all_tool_calls` stay intact. |
| **P2-18** | **Fix the precedence bug generally, delete the three consumerless flags, flip `deep_research` on.** Flags stay UI hints. | No server-side enforcement: `/api/auth/features` is auth-exempt, so flag state is world-readable and never was a boundary. Leave `sensitive_filter` and the `can_use_research` privilege alone. |
| **P2-20 + P2-23** | **Build only what is genuinely dead — RAG and feature toggles — and resurface the user-facing RAG module**, not the admin one. Wire both into `inits` and `refreshAll`. | MCP and tokens already have live UIs in settings; rebuilding them in the admin panel is `Law 14` in miniature. Three ids and a wiring fix turn a module that already runs every boot into a working feature. |
| **P2-21** | **Gate the two GETs, write the missing list loader, then flip the flag.** | **Amended from "cheap insurance" to required** — `P11-10`. Any logged-in non-admin can currently read all 60 built-in tool instruction blocks. |
| **P2-22** | **Target `/api/image/upscale-local`** — local Real-ESRGAN. Add the `controls.js` section and the `toolbar.js` entry. | Self-hosted is the premise; a feature that silently needs a second server is not shipped. A backend selector is the right destination once a GPU host exists — file it then, defaulting to local. |
| **P2-25 · P2-26** | **Prune nothing.** Correct the must-stay documentation and close both. | The measured prunable set was effectively empty, and both lists match with `startswith`, so removing one pair silently unprotects its children. **These get stronger under `P11`, not weaker** — every argument for them assumed a trusted operator. |

### Re-landing run 01

| | Answer | Note |
|---|---|---|
| **P2-09** | **A checkbox — "scale to the model's context window"** — that disables the number field when ticked. The number becomes the ceiling. | A magic `-1` in a field labelled "Max" is something you rediscover by reading source. Re-land via `budget_context_for_model(url, model, fallback=0)` at `agent_loop.py:4342`. The ceiling matters: skills arrive as untrusted context. |
| **P2-13** | **Thread an `explicit_params` set from the payload builder.** The clamp becomes a setdefault for everything else. | Dropping both clamps was the purer un-nerf and is not crazy, but that model family genuinely degenerates above 0.2. The explicitness signal is worth having for every future "default, not cap" question. **Keep the Anthropic ceiling** — that API 400s above 1.0. |

### Before the repo goes public

| | Answer | Note |
|---|---|---|
| **P0-18** | **`AGPL-3.0-or-later`**, with real SPDX headers. | Matches upstream. Narrowing below the parent creates a compatibility puzzle for anyone combining the two, in exchange for control over a future revision there is no reason to fear. |
| **P0-14 prereq** | **Name both, and say which is which** — forked from the clone source, upstream project referenced as the other. | Unless the operator knows one is a mirror or a rename, in which case say so and this becomes simpler. The git remote is verifiable evidence; so are the 47 in-code references. An attribution that reports both cannot be wrong. |
| **P0-23** | **Delete the file and its credits row.** | 1,468 bytes, three glyphs, metadata reading `Untitled1 / Copyright (c) 2025, Unknown`. The only licensing item that is affirmatively false rather than merely incomplete. Nothing uses three glyphs. |
| **P0-28** | **Delete the root `ROADMAP.md`.** Point everything at `.pantheon/ROADMAP.md`. | Two files with the same name saying different things is `Law 7`'s exact failure mode — it is how `FRONTIER-NOTES.md` ended up still calling the project Odysseus. A public "help wanted" page is a real thing to want and `CONTRIBUTING.md` already is it. |
| **P0-13** | **Its own session.** Three or four directions, pick one, then favicon, tray icon and the five inline SVG copies follow. | The identity is what people see before reading a line of the README, it is cheapest to get right while nothing depends on it, and it is a different kind of work from everything else here. A placeholder reliably becomes permanent. |

### The two couplings

| | Answer | Note |
|---|---|---|
| **B02** | **Drop the extension gate entirely.** The backend sniff becomes the single decision point. | Two lists that must agree is the bug we keep having. Worst case the button opens something that turns out not to be text, and the backend says so. |
| **B03** | **One toast naming what was rejected and why.** | Silent data loss is the worst failure mode — the person believes something happened that did not. Keeping rejected files in the composer is nicer and is a follow-up, not a blocker. |

**What did not change under the scaling track.** `P2-01`'s deletion stands for today's deployment
and is restored under `P11-09`, with `.svg` in it — the condition it named has arrived, not
passed. `P2-25` and `P2-26` get stronger. Everything else is as recommended.

