# DECISIONS — settled, with the reasoning that settled them

Recorded so no agent re-litigates them and no reviewer flags them as oversights.
Each entry names what was decided, what it costs, and what would reopen it.

---

## D-2026-08-26-07 · Identity, roles, and the RBAC clean-up

*Written 2026-08-28. The call was made on 2026-08-26 and never recorded — thirteen `P11` rows
have been resting on one subordinate clause inside D-2026-08-26-04, an entry whose stated job is
to list what a change **voids**. `rbac` and `keycloak` both returned zero hits in this file.*

**Decided:** Pantheon plans for real infrastructure. In the owner's words: *"we should probably
plan around someone potentially scaling into actual real infrastructure, OIDC/SSO Support etc…
BYO software (self hosted keycloak/zitadel as an example, and more…)"* and *"this is going to
need some extensive RBAC cleaning and establishment."*

**Identity.**

- **OIDC Authorization Code + PKCE**, discovered from the provider's `.well-known` document.
  Not a bespoke integration per provider.
- **Bring your own provider.** Self-hosted Keycloak and Zitadel are the reference cases because
  they are what a person running this on their own hardware would actually reach for. Anything
  that serves a standard discovery document should work; nothing is hard-coded to a vendor.
- **Local auth stays, alongside.** Not replaced. A single operator on a LAN must never be forced
  to stand up an identity provider to log in — that is the deployment this project started from
  and it remains a first-class one.

**Roles.** Named overlays on `DEFAULT_PRIVILEGES` (`core/auth.py:24-38`, 11 keys, AST-verified),
resolving built-in default → role → user. `is_admin` stays as the superuser role rather than
being replaced, because 103 call sites depend on it and rewriting them at once is how this goes
wrong. This is `Law 14` applied to authorization: the dict is already a control plane, just
under-populated.

**The clean-up half, which is the part with no other home.** "Extensive RBAC cleaning" is four
concrete preconditions, all measured:

1. **Close the fail-open default.** `privs.get(key, True)` at `src/auth_helpers.py:172` grants on
   a typo. `P11-01`.
2. **Audit all 103 `require_admin` sites** against the role model — 83 direct calls plus 20
   `Depends(require_admin)`, non-test Python. `P11-02b`.
3. **Resolve the `_ADMIN_TOOLS` collision.**
4. **Reconcile the fifteen route files with no auth call of their own** — nine of which do in
   fact make one; six are the real unknowns. `P11-02d`.

**What this does not decide.** Where an operator administers any of it. That gap is real and is
now `P11-11`: the answer is to extend the admin panel that already ships, not to invent a second
one.

---

## D-2026-08-26-08 · The Brain keeps its edges and loses its picture

*Written 2026-08-28 for the same reason as the entry above: this is one of the five corrections
the roadmap names as having overturned an earlier plan, and `Brain`, `graph`, `confetti` and
`force-directed` all returned zero hits in this file. It lived only in a phase preamble 1,200
lines into the tracker, which is the shape a fresh agent reads as an omission rather than a call.*

**Decided:** no canvas, no force layout, no starburst, no confetti. The data model survives whole.

**The owner's words:** *"We dont need the visual 'confetti' of memories. Just as long as memories
and persistence/long term knowledge of projects etc has permanence."*

**Why.** The force-directed constellation is the part of a competitor's version that looked most
impressive and was the reason it went unused. A beta screenshot of that product showed 616
entries and 614 connections — about one edge per node, rendering as one hub with a starburst of
spokes and a periphery of dots joined to nothing. A graph at that ratio promises a structure the
data does not have.

**What survives, and it is most of it.** Typed edges — `supersedes`, `contradicts`,
`derived_from`, `co_occurs` — are kept as **data**, because each one changes what retrieval
returns whether or not anyone ever looks at it. A superseded memory stops surfacing; a recorded
contradiction surfaces both sides with the conflict named. The test for an edge is whether a
query is better for it, not whether it draws well: an edge that exists only to be drawn is not
worth storing.

**What the Brain surface becomes.** Something a person can read, search, filter, sort, inspect
and correct. Not something they navigate by dragging.

**What would reopen this:** nothing about rendering. If someone later wants a visualisation, it
is additive and it argues for itself on its own merits — it does not get to shape the data model
on the way in.

---

## D-2026-08-27-01 · `CREDITS.md` is the credits file; `ACKNOWLEDGMENTS.md` merges into it

**Decided:** `CREDITS.md` is authoritative. `ACKNOWLEDGMENTS.md` is merged into it in full and
then deleted. `NOTICE` keeps pointing at `CREDITS.md`, which it already does. `P0-19`.

**The problem it settles.** Both files exist, both claim to be the credits file, and they
disagree. `ACKNOWLEDGMENTS.md` is upstream's — 9,409 bytes, dated with the fork, and it still
opens *"Odysseus stands on the shoulders of a lot of open-source work."* `CREDITS.md` is
Pantheon's — 3,782 bytes, written on 2026-08-26, and it leads with Odysseus as it should. The
detail lives in the upstream file; the correct framing lives in ours. Neither is currently
complete, which is why `P0-20` … `P0-26` all stall behind this call.

**Why `CREDITS.md` wins.** Three reasons, in order of weight:

1. **`ACKNOWLEDGMENTS.md` speaks in upstream's voice about upstream's project.** That is the
   same defect as the root `ROADMAP.md` in `P0-28` — inherited prose flying this project's
   name. A credits file that opens by describing a different project is wrong regardless of how
   good its contents are.
2. **`NOTICE` already names `CREDITS.md`**, and `NOTICE` is the AGPL §5(a) artefact. Moving the
   licence-bearing pointer is riskier than moving the prose it points at.
3. **`Law 7`.** Two files claiming the same fact is exactly the condition that law exists to
   end, and it has already cost us: `P0-14` could not be re-ticked because there was no
   agreed place to put the second upstream identity.

**Nothing is subtracted.** Every credited party, every licence note and every adapted-code
attribution in `ACKNOWLEDGMENTS.md` moves into `CREDITS.md` first, and the merge is verified
party-by-party before the file goes. This is consolidation, not removal — `Law 1` still
applies, so the deletion is marked on the task line and named in the commit.

**What it unblocks.** `P0-20`, `P0-24`, `P0-25` and `P0-26` all write into "the credits file"
and now know which one. `P0-14` can be re-ticked once the second upstream identity —
`odysseus-dev/odysseus`, which the code and docs referenced 47 times before the sweep — is
named in both `NOTICE` and `CREDITS.md`. Until it is, the AGPL §5(a) attribution names one of
two upstreams, and this repo cannot go public.

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

Of the 799 `var(--accent…)` sites in `style.css`, **521 are `var(--accent, var(--red))`**.
They resolve today to the theme's own `red`, which `applyColors()` sets at
`static/js/theme.js:263`. A `:root` definition beats a fallback — so all 521 would have
flipped to one global colour, and all 16 themes would have converged on it in one commit.
The task would have reported success. Every screenshot would have looked deliberate.

`P1-01` now sets `--accent` **per theme**, seeded from that theme's `red`, beside the
existing `--red` line in `applyColors()`. The 521 fallback sites resolve to exactly what
they resolve to now, the bare sites resolve for the first time, and each theme keeps its
identity. Strictly better than the original plan, and it costs less.

> **Corrected 2026-08-27, and the correction is its own lesson.** This entry said **508**
> and named a function called **`applyTheme()`**. The real count is **521** — four
> independent methods agree, and `static/style.css` has one commit in this repo, so the
> figure was wrong when written rather than gone stale. There is no `applyTheme()` in
> `theme.js`; the function is `applyColors()` at `:257`, and the only `applyTheme` in the
> tree is a dead call at `slashCommands.js:876` guarded by an `||` that can never be
> satisfied. **A third correction matters more than either:** `--red` is set at **three**
> sites, not one — `theme.js:263`, the first-paint inline script at `index.html:29`, and
> `login.html:54`. One line in `applyColors()` alone leaves a flash on every cold load and
> leaves the login page without `--accent` permanently. All three get the line.
>
> The 508 had been copied into three documents, including this one and `FORBIDDEN.md`.
> That is `Law 6`'s exact failure mode occurring inside the documents that define it.

> **LANDED 2026-08-30, and the count moved a fourth time.** 508 → 521 → 535 → and at
> implementation **816 sites, 553 of them `var(--accent, var(--red))`**. Every figure above
> is kept because the sequence *is* the argument for `Law 6`; none of them was right for
> longer than a few days, and `static/style.css` turned out to have three commits in this
> repo rather than the one this entry claimed.
>
> **What the numbers hid, and no version of this entry saw:** the population is not two
> classes but three. 562 sites resolve to the theme's red and do not move; 204 paint for
> the first time; and **63 carry a hand-picked fallback that is not red, so defining the
> token changes their colour.** Twelve of those were never accent sites at all — a green
> *verified* badge, two link blues, an amber supervisor rung — reaching for
> `var(--accent, <the real colour>)` because `--accent` did not exist and the fallback was
> the actual intent. Left alone, `.skill-verified` would have rendered in the same hue as
> `.skill-needsmark` on all sixteen themes. They now name the semantic token they meant.
> The remaining fifty are hover borders, focus rings and drag ghosts, which is what
> `var(--accent, …)` asks for and what this row exists to deliver.

**Still allowed.** `P10-04` (contrast audit across all 16 themes) and `P10-05`
(reduced-motion guard over the 7 animators) both stand. A reduced-motion guard **respects
an operating-system setting** — it does not disable the feature, and an agent that reads
it that way has misread it. New themes may be added; new patterns may be added.

**And the owner named two directions, unprompted, twice — they belong in the decision that
governs what this system may grow into rather than only in a task row.** First, more themes,
including unique ones. Second: *"possibly even ASCII art subtle in the background for the entire
platform depending on the theme selected."* That second one is specified as `P9-16` and is
additive by construction — one entry in `_BG_CLASSES`, one in `_CANVAS_PATTERNS`, one init
function beside the seven that already exist. Neither direction touches an existing theme, which
is why both are allowed under a decision whose whole purpose is that the existing ones survive.

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
running inference service comes out.

**Why not Olympus** — and this is worth recording, because it is a positioning decision rather
than a naming one. Olympus would have cast the models as gods in residence. AI is already
under heavy and often fair criticism for exactly that framing, and a self-hosted tool has no
business adding to it. The name would have made a claim about what these things *are*. Forge
makes a claim about what the operator *does*, which is the honest one and the better story.

**`recipe` survives.** 242 occurrences, and a vLLM recipe genuinely is a parameterised launch
config — the confusion was never about recipes, it was the section name. Renaming it would be
churn for its own sake.

**Scale.** **3,529** occurrences, **171** files, 43 paths (re-measured 2026-08-27; the old 3,533 / 172 counted this tracker's own text) — larger than the Odysseus→Pantheon sweep
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
| **P0-13** | **Its own session.** Three or four directions, pick one, then favicon, tray icon and the nine inline SVG copies follow. | The identity is what people see before reading a line of the README, it is cheapest to get right while nothing depends on it, and it is a different kind of work from everything else here. A placeholder reliably becomes permanent. |

### The two couplings

| | Answer | Note |
|---|---|---|
| **B02** | **Drop the extension gate entirely.** The backend sniff becomes the single decision point. | Two lists that must agree is the bug we keep having. Worst case the button opens something that turns out not to be text, and the backend says so. |
| **B03** | **One toast naming what was rejected and why.** | Silent data loss is the worst failure mode — the person believes something happened that did not. Keeping rejected files in the composer is nicer and is a follow-up, not a blocker. |

**What did not change under the scaling track.** `P2-01`'s deletion stands for today's deployment
and is restored under `P11-09`, with `.svg` in it — the condition it named has arrived, not
passed. `P2-25` and `P2-26` get stronger. Everything else is as recommended.


---

## D-2026-08-29-01 · One severity ordering, in Python, and what "unknown" means

`P7-06` needed an answer to a question the 13-value `ToolEffect` taxonomy does not contain:
**which of two effects should a person worry about more.** Three decisions came out of it and all
three are the kind someone re-derives differently in six months, so they are written down.

**The ordering lives in Python and nowhere else.** `_EFFECT_SEVERITY` and `_EFFECT_PHRASE` sit in
`src/tool_capabilities.py`, beside the enum they rank, and the wire carries the resolved rank and
the resolved words. No JavaScript copy of either exists and two tests enforce that. The reason is
not tidiness: a second home for an ordering drifts the first time a value is added to the enum,
and the failure mode is that the same action reads as harmless on one surface and severe on
another — which is not a cosmetic disagreement when the surface is a consent card. The cost is
that a purely presentational choice now requires a backend change; that is accepted.

**The ordering itself, lowest to highest:** `ui_side_effect · user_interaction · read_public ·
read_workspace · brokered_network_read · write_workspace · read_private · execute_code ·
network_egress · write_private · external_side_effect · admin_change · destructive`. The two
arguable placements: **`read_private` above `write_workspace`**, because a scoped workspace write
is reversible and reading private data is an exfiltration precursor; and **`admin_change` above
`external_side_effect`**, because changing settings for everyone outlives the run. Ranks are
spaced by ten so a value can be inserted later without renumbering; only the order is meaningful.

**Unknown fails high.** An effect value nobody has classified ranks *above* `destructive`, not
below `ui_side_effect`, and bands to `serious`. This is the same rule the module already applied
to unknown tools, and it is the only safe direction: the alternative is that a new enum member
renders as "no consequence" on a surface that has not been updated. A mutation that inverted this
survived the entire suite until `tests/test_tool_capabilities_effects.py` was written for it.

**What the seal actually protects, corrected here because three files got it wrong.**
`_canonical_digest` hashes `_binding_payload`, a server-side dict that includes the alphabetically
sorted `effects` tuple. `public_payload()` is a *derived view*, built fresh on each call and never
read back as authority. Three comments claimed the public payload's shape fed the digest and that
the sealed record therefore "cannot carry more"; that premise sent the presentation threading
through every event and every consumer, and refutation found three card producers shipping
unranked as a result. The presentation now lives inside `public_payload()`, all five producers get
it from one place, and `action.effects` stays alphabetical because *that* list is the sealed one.
**`FORBIDDEN.md` Part 2 still stands unchanged** — the seal, the TTL, the single-use consumption
and the owner binding are untouched. What was lifted was a misreading of it.

---

## D-2026-08-29-02 · The trust ladder — three rungs, and what a "yes" is worth

`P7-03` and `P7-04` built the ladder. Six decisions came out of them that someone will
re-derive differently in six months, and two of the six were only settled because refutation
proved the first answer inverted the control it was meant to strengthen.

**Three rungs, not the design's five.** `TrustRung` is `ask_every_time · allow_listed ·
gate_on_untrusted`, the last being the default and today's behaviour. `.pantheon/design/pantheon-v10.html:1721`
draws five, and two of them are not gate settings. **"Plan only"** is a mode you enter — a tool
allowlist plus a directive — so putting it in an enum `decision_for` switches on would claim a
control this code does not have. **"Auto-pilot"** is what `gate_on_untrusted` feels like in a
clean chat, and the design's own note says so: *"auto-pilot isn't a new top rung. It's already
the default. The ladder is added below current behaviour, not above it."* That is `P7-05`,
superseded and re-filed as an acceptance criterion; it is discharged in the ladder's copy, where
the default leads and is badged *"What you have now"*.

**A blanket approval does not outrank a rung that asks.** This is the one that inverted.
`approval_gate_bypassed` short-circuited `decision_for` before the rung, and both allow buttons
set `allow_remaining_actions` — so on `ask_every_time`, approving one harmless action in a clean
run disarmed the gate, and a later round fetched a hostile page and ran an exfiltration command
**with no prompt**, an action the *default* rung stops. The two stricter rungs were strictly less
protected than the one below them. The reason it happened is worth keeping: before this row a
card could only exist once taint had armed the gate, so a bypass was always granted under the
same threat model it then relaxed. A rung mints cards in clean runs, and **a yes given when
nothing was wrong must not spend itself after something is**. The approved action still runs —
it is authorised by the sealed exact grant, bound to that owner, session, tool and content.

**A standing allow-rule does not survive taint**, for the same reason in a different costume. A
rule is a standing yes to a *routine* action; a run carrying someone else's text is not routine.
Without this, a *"anything starting with git"* rule let `git push --force` run unprompted in a
tainted run that the default rung stops.

**No regular expressions in the allow-list, ever.** A regex here is two problems: users cannot
write them correctly, and a catastrophic-backtracking pattern is a denial of service on a live
tool-dispatch path. Three explicit kinds — `any`, `exact`, `prefix` — normalised with `strip()`
and nothing more, because matching *less* is the safe failure direction for a control that only
ever grants. A person picks a scope on the approval card; nobody authors a pattern. A `git s`
prefix rule *does* match `git shove-everything`, and that is pinned rather than papered over: a
token-boundary rule would equally block `git status`, separating nothing while making the control
impossible to predict from its own name — and a control that is hard to aim gets aimed wide.

**`coerce_trust_rung` fails to the *default*, not the strictest rung** — the opposite of
`effect_severity`'s fail-high rule, and deliberately. An unknown *effect* is something we might be
under-warning about; an unknown *rung* is a corrupt setting, and answering it by switching a
working install to confirm-everything reads as the product breaking. **But that only holds if a
bad value cannot be stored**, and it could: `ask_every_tim` returned `200`, echoed the typo back,
and left the install on the default, while `manage_settings` answered *"Set trust_rung = ask every
time."* Both write paths now reject an unknown rung at the door. `trust_rung` deliberately has
**no env layer**, because `set_settings` materialises every key on the first admin save and the
instance setting outranks the env var from then on — an operator's hardening silently undone by
someone opening Settings. `B20` carries that defect where it already exists.

**Rules are owner-scoped and revocable, and the revoke screen shipped with them.** The store's
five-second snapshot TTL is defended on the grounds that a revocation lands before the user
finishes reading the confirmation — which was an empty argument while nothing in the product could
revoke anything. A grant nobody can see is one nobody thinks to take back, and the widest grant
here is one click on an approval card.
