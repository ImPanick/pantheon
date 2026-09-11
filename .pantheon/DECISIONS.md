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

---

## D-2026-08-31-01 · Telemetry is allowed. Phoning home is not. The test is the address.

`Law 16` landed in the morning as *self-hosted by default*. The owner amended it the same day,
and the amendment is worth its own entry because it converts a restriction into a specification:

> *"telemetry is fine, but 'phone home' to an external destination is not allowed. if the user
> wants to establish their own telemetry endpoint, they can bypass this law and do so… like
> Prometheus or Grafana etc.. maybe even enrolling other services to connect like OpenSEO, or
> other CRM products"*

**The rule is about the destination, not the activity.** Measuring is not the sin; sending what
you measured somewhere the user did not choose is. Every question of the form *"is X allowed?"*
is rewritten as ***"who owns the address at the other end?"***

**Why this needed writing down.** The obvious misreading — *no telemetry, we are privacy-first* —
is the one an agent reaches for, and it is wrong in both directions. It would ban the operator's
own Grafana, which the owner explicitly wants, and it would leave someone running Pantheon on
their own hardware with no way to see what it is doing. That is `Law 15` failing in a different
costume: the capability exists, nobody can reach it. Meanwhile the same misreading would *permit*
"anonymous aggregated usage stats" to a vendor, because it sounds harmless and is not the word
"telemetry". The address test gets both right and needs no judgement call.

**What follows from it, concretely:**

1. **Collect freely, locally.** `P14`'s events table is not a `Law 16` problem and never was.
   Storing measurements on the machine that produced them is not egress.
2. **Export only to a configured address, with no default.** An empty destination is not a
   disabled feature — it is the *only* correct shipped state. A default endpoint here would be
   the whole defect, whatever its value.
3. **There is no consent ceremony that makes vendor telemetry acceptable.** Not opt-in, not a
   dialog, not "anonymised". This is deliberately stricter than the industry norm, and it is the
   owner's call to be stricter.
4. **The same shape covers integrations generally** — Prometheus, Grafana, OTLP, a CRM webhook,
   OpenSEO. They are not special cases needing new policy; they are instances of *the user owns
   the far end*, which is what the existing Integrations system already models.

**Cost, stated honestly.** Nobody upstream will ever know how Pantheon is used, so there is no
crash-rate signal, no adoption data, and no way to learn that a feature is broken for everyone
except by being told. That is a real price and it is paid on purpose: this is a product people
run on their own machines, and the one thing they are buying is that it does not report on them.

**Filed as:** `P16-12` (the export), `P16-13` (the guard that keeps it honest). `P14` is unchanged
by this — it was always local.

---

## D-2026-09-01-01 · Who this is for, and what that settles

The owner, closing the telemetry question and setting the product's shape in the same breath:

> *"I don't plan to openly host Pantheon. This is legitimately for my own private stack and
> whoever else wants to make it their private stack as well. Even companies. […] the thing I lose
> is negligible because I'll be using my own product here. Extensively.. Fully. Therefore - I will
> likely find the bugs. And it being open source, people can create issues on GitHub."*

And the north star, from the same message:

> *"I'd love for this platform to be able to automate anything I don't want to do on the
> computer/internet or on my network (even my parallel networks etc)"*

**The telemetry question is closed, and closed on evidence rather than principle.** The argument
for a vendor pipe was that bug reports do not happen. Here the primary user is the maintainer,
using it fully, daily. He is the sensor, and he is a better one than any crash-rate curve —
he sees the bug *and* knows what he was doing when it happened, which is the half telemetry
never captures. GitHub issues carry the rest. `D-2026-08-31-01` stands; this is why it costs
nothing.

**What that re-ranks, and it inverts the order I had:**

* **`P16-15` (local self-checks) goes first.** If the maintainer is the instrument, give the
  instrument a dial. `H01` is the proof: a year of staged, invisible email that a local count in
  front of a person would have surfaced in a week. This is now the highest-value row in `P16`.
* **`P16-14` (diagnostic bundle) is about *other people's* issues, not ours.** Open source means
  strangers file bugs; a bundle is what makes those reports usable rather than *"it broke"*.
* **`P16-12` (Prometheus/OTLP) is an operator feature, not a bug-signal.** Still wanted — for the
  person running it, on their own Grafana — but it is no longer the answer to anything.

**"Not openly hosted" is a default, not a guarantee, and the security posture does not relax.**
*"Whoever else wants to make it their private stack, even companies"* means multi-user, roles and
an auth boundary all still matter (`P11`), and it means somebody will eventually put this on a
public address whatever the intent. Every control in `FORBIDDEN.md` Part 2 stays. The correct
reading of "private stack" is *this is not a SaaS and has no tenant model*, not *the boundary can
be weaker*.

**"Even my parallel networks" is a capability requirement and is not currently met.**
`model_discovery` scans loopback, `host.docker.internal`, the local LAN and Tailscale peers —
one network at a time, implicitly. Reaching several segments deliberately is a different feature.
Filed as `P16-16` rather than assumed.

**And the north star is worth writing down because it settles arguments about scope:** the target
is *automate anything the owner does not want to do on his machines, his internet, or his
networks*. That is why the tool surface is wide, why `P8`'s Workshop matters, and why `Law 16`
is about **defaults** rather than capability — a product meant to automate everything cannot be
one that refuses to reach anything. It reaches what it is pointed at, and nothing else.

---

## D-2026-09-01-02 — the events table keeps shape, not content, and the window is finite

`P14-01`. Two decisions were needed to build the append-only events table, and both cut against
an instinct this project otherwise holds.

**1. `session_id` is a plain column, not a cascading foreign key.**

The tidy choice is `ForeignKey("sessions.id", ondelete="CASCADE")`, and it would delete the cost
of a conversation along with the conversation. That defeats the point: *"what did last month
cost"* has to survive tidying up, and sessions are archived and deleted routinely — that is what
`cleanup_service.py` is for.

This is in tension with **"data is disposable"**, so the reasoning has to be explicit rather than
convenient. What makes it defensible is what the table holds: timestamp, session id, owner, model,
endpoint **label**, token counts, outcome. **No message text, no prompts, no responses, no
thinking.** Deleting a session removes the conversation; keeping its rows here leaks none of what
the deletion was for. What survives is the *shape* of the usage, which is the only thing the phase
was ever about.

There is a test that fails if a foreign key is ever added, and one that greps every column of a
recorded row for planted secrets.

**2. Retention ships finite — 90 days — and `0` means keep everything.**

An append-only table with no ceiling is a defect on somebody's home server, not a feature. Ninety
days answers every question this phase asks (*what did last month cost*, *did that change help*)
without the table becoming the largest thing in the database. Keeping everything stays available
and is a choice someone makes, rather than one they inherit from nobody having thought about it.

Pruning is time-gated in-process, following `rate_limiter.py`'s pattern, because this product has
no daily job runner and adding one to run a `DELETE` would be the larger change.

**`events_retention_days` is settings-only, and the absence of an env var is the decision.**
`get_setting` merges `DEFAULT_SETTINGS` on every read, so an env fallback beneath a **truthy**
default can never execute. That shape was found dead twice (`H06`, `B20`) and turned on exactly
this distinction in `P16-05`. It was registered in `.env.example` and all three compose files here
before the same check caught it a fourth time — and then removed rather than left as decoration,
because a knob that cannot move is worse than no knob. Retention is not a boot-time concern.

**What this does not decide.** `duration_ms` exists and is NULL: round latency is not available at
`accumulate_token_usage`, and threading it through is `P14-02`. The column ships now so that row
needs no migration. Saying so on the row is cheaper than a column added later by a migration
nobody wants to write.

---

## D-2026-09-01-03 — this is an orchestration harness; LAN-to-LAN is not a threat model

The owner, on `P16-16` and the `P16-20` I filed beside it:

> *"internal comms, LAN to LAN etc is totally fine. we arent building fort knox. just an
> orchestration harness etc.."*

**That corrects an emphasis I was drifting into, and it is worth stating precisely rather than
just softening the language.** `P16-16` shipped network scoping and I wrote it up as a *boundary* —
"enforced, not advisory", "refused before DNS" — and then filed `P16-20` to close the remaining
hole with a network namespace or an nftables rule set. All of that is coherent engineering for a
product whose threat model includes *the agent, or something wearing it, trying to get out*.

That is not this product's threat model, and pretending otherwise costs real things.

**What the scoping is actually for: directing the agent, not defending against it.** An operator
who says *"work on the lab"* wants the lab's machines discovered, the lab's endpoints offered, and
the agent's attention on the lab — not a jail. The failure it prevents is a **mistake**: a model
list that mixes the lab GPU with the production GPU, a sweep that wanders into the printer VLAN, an
agent that helpfully "fixes" the wrong box. Those are orchestration failures, and scoping fixes
them completely.

**What it is not for: containing a hostile or compromised run.** If something is executing arbitrary
shell on the operator's machine, it is already inside the network. Chasing that with per-run egress
jails buys a guarantee nobody asked for, in exchange for a large amount of platform-specific
plumbing — netns on Linux, pf on macOS, something else on Windows, all of it able to break a working
install in ways that look like the product is broken rather than the sandbox.

**Consequences, so this does not get re-derived:**

* **`P16-20` is reframed and deprioritised**, not deleted. It stays available for whoever
  eventually wants a hard boundary — a company running this shared, most plausibly — and its text
  now says that is who it is for. It is not on the path to a good version of this product.
* **`P16-16`'s honesty clause stays, and stops apologising.** The docs still say a shell tool
  running `curl` reaches whatever the process routes to. That sentence is *accurate*, and accuracy
  is the reason to keep it — not because a missing control needs excusing. The test that fails if
  the disclosure is removed stays too.
* **What does NOT relax:** the auth boundary. `D-2026-09-01-01` already settled this — "not openly
  hosted" is a default rather than a guarantee, somebody will eventually put this on a public
  address, and every control in `FORBIDDEN.md` Part 2 stands. *LAN-to-LAN is fine* is a statement
  about traffic between machines the operator owns. It is not a statement about who may log in,
  about SSRF from a hostile document, or about what a tool may do with an approval it never got.
  Those have a real adversary and this does not.

**The general form, since this is the second time a scope has needed narrowing** (`Law 16` was the
first, when "no external dependence" nearly became "no capability"): the question is always *who is
the adversary, and did anyone ask for one?* Where the answer is "nobody, this is a mistake we are
preventing", build the thing that prevents mistakes and stop there.

---

## D-2026-09-05-01 — the address is the switch; there is no `otlp_enabled`

`P16-19` ships the metrics push exporter with exactly one control: `otlp_endpoint`, a string that
ships empty. There is no separate boolean beside it, and this records why — because adding one is
the obvious "improvement", and the next agent to look at this will want to.

**The argument for a second switch.** An operator who wants to pause pushing without losing their
collector's address has nowhere to put that intent. They must clear the field, keep the URL
somewhere else, and paste it back. That is a real cost and it is the whole case against this
decision.

**The argument that wins.** Two controls can disagree, and the disagreement is silent in the
direction that matters. `otlp_enabled: true` with a blank address is an operator watching a
dashboard that will never populate, with nothing anywhere saying why — the failure mode `P16-12`
and `P16-19` exist to eliminate. The reverse pairing, an address with the feature off, at least
produces a question the operator can answer by looking at one field.

**And the empty default is not merely a default.** `.pantheon/check-destinations.py` enforces that
destination-shaped keys ship falsy, for `Law 16` clause 4 (`D-2026-08-31-01`), *and* the falsiness
is what keeps `PANTHEON_OTLP_ENDPOINT` reachable beneath it — a truthy default makes the env layer
dead code (`H06`, `B20`). A boolean beside it would be a third thing that has to stay consistent
with both of those, for a convenience that is one paste.

**`Law 14` is the general form**: the address already answers the question the boolean would ask.
Where an existing field's *value* fully determines a behaviour, a flag that repeats it is not a
control, it is a second source of truth.

**What would reopen this**: an operator asking for it, having actually used the exporter. Not a
reviewer's intuition that features have on/off switches, and not symmetry with `metrics_enabled` —
that one is a genuine boolean because a scrape endpoint has no address to be empty.

---

## D-2026-09-07-01 — DOMPurify: Apache-2.0, not MPL-2.0

**What it decides.** `html2pdf.bundle.min.js` ships DOMPurify 2.3.0, which Cure53 offers under
Apache-2.0 **or** MPL-2.0. A dual offer is not paperwork to copy; it is a choice the recipient
makes and then has to live with. Pantheon takes **Apache-2.0**.

**Why.** MPL-2.0 is a file-level copyleft with a source-availability obligation: §3.2 says anyone
who receives the Executable Form must be able to obtain the Source Code Form of the Covered
Software. DOMPurify arrives here inside a 906 KB minified webpack bundle — that *is* Executable
Form — so taking the MPL branch would commit this project to distributing or offering DOMPurify's
own source alongside it, forever, for a dependency of a dependency of the PDF export button.
AGPL §13 already obliges us to offer *our* source; this would be a second, separate obligation
about somebody else's, bought for nothing.

Apache-2.0 asks for the notice to travel and adds an express patent grant, which MPL-2.0's §2.1(b)
is narrower than. It is also already one-way compatible with AGPL-3.0-or-later, which is what this
work is under (`P0-18`), so nothing about the combination becomes a question.

**What is filed.** The upstream `LICENSE` **verbatim, with both texts in it**, as
`licenses/DOMPurify-Apache-2.0-or-MPL-2.0.txt`. Shipping a trimmed copy of the Apache half would
misrepresent what Cure53 offered. `CREDITS.md` and `.pantheon/check-licences.py` both record the
offer and the branch taken, so the choice is visible rather than implied by which file is on disk.

**What would reopen this.** Cure53 dropping the dual offer in a version we upgrade to, or a
downstream user who needs the MPL branch for their own combination — in which case nothing here
stops them taking it; the dual offer is Cure53's and it reaches them too.

**Cost.** Anyone auditing this has to read a licence file that contains two licences and a line
elsewhere saying which one applies. That is the price of not editing somebody else's licence file.

---

## D-2026-09-08-01 — the send button's contrast is a setting, not a computation

**What it decides.** `P1-08` proposed one computed `--on-accent` token, derived per theme, replacing
the hard-coded `color:#fff` on `.send-btn` and the 33 rules that paint text on an undiluted accent.
The owner's call: *"Honestly let the user pick the global button design."*

**Why that is a different row than the one filed.** The measurement stands — white-on-accent misses
4.5:1 on **15 of 16** themes and the accent itself misses on **8 of 16** — but a computed token
answers *"which foreground is legible on this background"* and the owner is answering a question one
level up: **whether the button is a filled accent block at all.** A ghost button, an outline button
or a tinted button changes the background the foreground has to clear, and two of the sixteen
(`cute`, `retrowave`, `B15`) cannot reach the floor by any foreground choice — so for those the only
fix available *is* a different button design. The computed token is one of the options the picker
offers, not the thing that replaces it.

**What this constrains.** The picker is **global** — one choice, all sixteen themes — because the
owner said global and because a per-theme choice re-creates the sixteen-way divergence `P1-08` was
filed to end. Every option the picker offers must clear 4.5:1 on all sixteen themes *by
construction*, so the contrast guard `P1-09` describes moves from "validate what the user picked" to
"only offer what passes". The themes remain protected territory: this adds a variable, and any new
token extends `ADV_KEYS` **and** `computeAdvancedDefaults()` in lockstep or all sixteen break.

**Cost.** A setting is a surface with a default, a migration and a place in the UI, where a computed
token would have been invisible and automatic. That cost is accepted: the owner wants the choice
visible, and the *automatic* version has been provably wrong on fifteen themes for the entire life
of the fork without anyone being offered a way to notice.

**What would reopen this.** Nothing about contrast. Only a finding that the option set cannot be
made to pass on all sixteen without one of the options being a design nobody would pick — at which
point the honest move is to fix `B15` first and re-derive.

---

## D-2026-09-08-02 — `max_tokens` on local inference belongs to the machine, not the preset

**What it decides.** `P3-21` asked whether the local-inference lift should keep flattening every
preset's `max_tokens` to 1,000,000, erasing Code Analyze's 8000, Reason's 6000 and Brainstorm's 4096.
The owner: *"This is the machines defined max_tokens integer — it can change if I put everything on
stronger hardware instead of my gaming pc."*

**What that settles.** The number is **a property of the deployment, not of the preset**. It is not a
product opinion about how long a brainstorm should be; it is the ceiling the hardware can actually
serve, and it moves when the hardware moves. So the lift is correct in kind and the row's framing —
*"4096 on Brainstorm is not a cost control, it is the preset"* — was wrong: the preset was never
expressing a length preference through `max_tokens`, it inherited a cloud-era cost cap and nobody
separated the two.

**What follows, and it is not "leave it alone".** A number that describes the machine has to be
**settable and visible as such**. Today it is a literal buried in `_resolve_local_lifts`, which means
the owner cannot answer the question they just posed — *what does this box actually do* — without
editing source. This becomes an operator-facing local-inference ceiling with the same shape `H08`
gave `agent_max_rounds`: a configured value wins, `setting_is_explicit` pins it, and the 1,000,000
becomes the default rather than the law. The presets keep their numbers untouched (`Law 1`) and are
then read as **floors** — a preset never *lowers* the machine ceiling, which is exactly the middle
path the row named and found no caller for.

**Cost.** One more setting, and an operator who has never thought about it sees a very large number.
Accepted: the alternative is a silent 1,000,000 that three layers of validation already failed to
defend against once (`H08`).

**What would reopen this.** A preset that genuinely wants a *short* answer for product reasons. That
is a different field — a length preference the prompt expresses — not this ceiling.

---

## D-2026-09-08-03 — a late reminder arrives late and says so

**What it decides.** `P3-26`: a note reminder missed by more than sixty seconds was retired without
ever being shown. The row framed it as a trade-off between two window widths — one minute (never
show anything stale) versus five (`calendar/reminders.js`, deleted by `P3-10`). The owner took a
third option that was not in the row: **show it, and state its age.** Max lookback **12 hours**.

**Why the trade-off dissolves.** The original tension — *"take the pasta off"* wants the late one,
*"standup starts now"* does not — exists only because the notification **pretended to be on time**.
A reminder that reads *"Standup — was due 4 hours ago"* is not a wrong notification; it is a correct
one about a past event, and the person reading it can tell in one glance which of the two cases they
are in. Nothing has to be guessed on their behalf. The window then only has to answer a much smaller
question: how far back is worth mentioning at all.

**Why twelve hours.** It covers the two absences that actually generate this bug — a night's sleep
and a working day — and it stops short of the failure the deleted module was guarding against, which
was a fresh browser firing every two-week-old reminder at once on first poll. It is the owner's
number, and it is now a named constant with the reasoning beside it rather than a bare `60000`.

**What ships.** `REMINDER_LOOKBACK_MS = 12 * 60 * 60 * 1000` in `static/js/notes.js`;
`_reminderLateness(dueMs, nowMs)` returning `''` under a minute and otherwise *"was due N minutes
ago"* / *"was due N hours ago"* / *"was due Nh Mm ago"*; the age on the notification **title**, where
it is read before the body. Anything older than the window still retires silently, as before.

**Cost.** A reminder can now arrive up to twelve hours late. That is the point, and the title says so.

**What would reopen this.** A person reporting a wake-up flood — which would mean twelve hours is too
wide for how they use notes, not that the third option was wrong.

---

## D-2026-09-08-04 — the agent may set its own loop caps, because full automation is the goal

**What it decides.** `P7-12` asked whether `agent_max_rounds` and `agent_max_tool_calls` should stay
writable by the agent's own `manage_settings` tool. The owner: *"Yes. If its needed, the idea is to
be able to allow full automation. Full automation only works if the LLM in agent mode can define its
own parameters (with failsafes and safeguards.. a smarter 'loop detection' than PewDiePie put in)."*

**What that settles, and what it does not.** The caps stay writable — `B42`'s `_SELF_RESTRAINT_KEYS`
does not grow. But the sentence has two halves and the second is a **precondition, not a caveat**:
the reason a cap is safe to hand over is that something else is watching the loop. Today
`agent_max_rounds` is the *only* thing standing between a stuck agent and an unbounded run on the
owner's electricity, which is precisely why handing it to the agent reads as reckless. Loop
detection is what makes it not reckless, and it must land **with or before** any widening of these
writes.

**"Smarter than PewDiePie put in"** is a specification, so it is written down rather than left as
tone: round-count is not a loop signal. Repeating the same tool call with the same arguments is.
Cycling between two states is. Producing no new information across N rounds — no new file read, no
new command, no new content — is. A cap that fires at round 100 cannot tell a productive long run
from a two-round cycle repeated fifty times, and treating those the same is the defect the owner is
naming.

**The failsafe that is not negotiable.** A raise the agent grants itself is **scoped to the run that
asked for it** and does not become the stored default. That keeps *"give yourself more steps for
this"* — the real and reasonable request `B42` protected — while refusing the one-way ratchet where
every session inherits the last session's emergency. The `setting_is_explicit` distinction from
`H06`/`H08` applies on top: a number the owner typed is not raised by the agent without saying so.

**Cost.** More machinery than a refusal would have been, and loop detection is a real row rather than
a line. Accepted: the owner is asking for autonomy, and autonomy without a governor is not a feature.

**What would reopen this.** A runaway that loop detection did not catch. The answer then is better
detection, not a restored refusal — that path was already measured and rejected here.

---

## D-2026-09-08-05 — we define the trust rungs ourselves; the inherited ones are not a ladder

**What it decides.** `P7-13` asked whether an ordering exists among the trust rungs, since
`agent_loop.py` says a role profile *"may only raise strictness"* — a sentence that presumes an order
nothing defines — while `decision_for` carries a reproduction in which *"the two 'stricter' rungs
were strictly less protected than the one they sit below"*. The owner: *"we make our own trust rungs.
Because the current posturing of failure detection etc is incorrectly done."*

**The answer to the question as asked is: no such ordering exists**, and `P7-13`'s two candidate
outcomes were "name the order" or "record that there is none". The owner takes a third: **replace the
rungs**. `ASK_EVERY_TIME`, `ALLOW_LISTED` and `GATE_ON_UNTRUSTED` are inherited names whose behaviour
does not line up with what they suggest — two of them ask in an untainted run where the default does
not, so `gate_on_untrusted → allow_listed` is plausibly a *tightening* and plausibly a loosening, and
which one it is cannot be read from outside.

**Law 1 applies and shapes the work.** This is not a deletion. The existing rungs keep working and
keep their names; the new ladder is defined alongside, with each old rung mapped onto it, so nothing
that reads a rung today breaks. What changes is that there is finally **one place** that says what
"stricter" means, which both the role-profile rule and any chat-side rule read instead of assuming
(`Law 13` — the rule currently exists in prose in one file and in nobody's code).

**What a rung has to be, for the ordering to be real.** Not a name. A set of conditions under which
the agent stops and asks, such that rung N's set is a strict superset of rung N−1's. If two rungs
cannot be ordered by that test, they are not two rungs — they are two independent switches wearing
one field, which is what the current three are.

**The second half of the owner's sentence is a separate finding**: *"the current posturing of failure
detection etc is incorrectly done."* Failure detection and trust are coupled here — an agent that
cannot tell a failure from a refusal cannot decide whether to escalate — and that is the same
observation as `D-2026-09-08-04`'s loop-detection precondition, reached from the other side. The two
rows are one design conversation.

**Until it lands**, `trust_rung` stays writable from chat, which is what `P7-03` intended and what
six suite failures said when `B42` tried otherwise.

**What would reopen this.** Nothing about the diagnosis. Only the shape of the replacement, which is
not yet designed.

---

## D-2026-09-08-06 — the repo is primed for public, and stays private until the owner says otherwise

**What it decides.** `P0-16` (Apache-2.0 §4(b) change notices) and `P0-17` (the AGPL §13 source link)
both wait on the repository being public. The owner: *"The repo is not ready to go public. prime it,
but dont flip that switch yet. I intend to later."*

**What "prime it" means concretely**, so no agent reads this as "stop":

- **`P0-16` proceeds to completion now.** Change notices do not depend on visibility; they are
  accurate or they are not.
- **`P0-17` is built and left dark.** The footer link, its `title` — *"Built on Odysseus — click to
  see where Pantheon originated from!"* — and its presence on both the logged-in shell and the login
  page are all implementable against a configured repository URL that **ships empty**. Empty means
  the control does not render. This is the `D-2026-09-05-01` shape exactly: the address is the
  switch, and there is no second boolean beside it.
- **`B25` is closed the other way, immediately.** `CHANGELOG.md:37` claims under **#### Added** that
  the §13 source link shipped. It has not, and a changelog is what a stranger reads to audit AGPL
  conformance. The line comes out now rather than waiting for the flip — a false compliance claim is
  worse while the repo is private, not better, because nobody can check it.
- **`P0-13`** stays blocked on its own design decision; it is not unblocked by this.

**Why not just flip it.** Not our call, and the owner has given the reason implicitly by scoping it:
*ready* is a state the repository has to reach, and the priming work is what gets it there. Flipping
early would also make `P0-17` true by accident — the obligation attaches on distribution — which is
the wrong order to satisfy a licence term in.

**Cost.** `P0-17` ships as code nobody can see working until the URL is set, so its test has to prove
both branches: link present when configured, absent when not.

**What would reopen this.** The owner saying go.

---

## D-2026-09-08-07 — the Brain: measure it, tell the truth about it, then give it one path

**What it decides.** `P13-11` asked two retrieval-quality judgements and I brought back five options.
The owner took three: **honest reporting + a golden set + one retrieval path** (in that order), then
**cross-session frequency**, then **two-stage retrieval where a model does the selecting**. The
fourth option — restructuring what extraction *stores* into retrieval-shaped records — was **not
taken**, and that is coherent rather than an omission: two-stage selection buys the same *"context
matters more"* win at **query** time, against the memories that already exist, with no migration of
anybody's `memory.json` and no second record format to keep in step with the first.

**Not a fine-tune, and the reason is worth keeping.** The owner's phrasing was *"the vecetore store
should be an LLM created fine tune etc."* The instinct — the representation should be made by a
model, not by word overlap — is right, and is already half-shipped: that is what an embedding is,
and `fastembed` (local ONNX, ~50MB, zero-config, no network) does it today. But a fine-tune is the
wrong **mechanism** for facts: it cannot be edited, cannot be deleted when someone says *forget
that*, cannot be cited, and cannot be told apart from a hallucination. It also contradicts two
standing calls of this project — training is parked, and data is disposable. A fine-tune is the
least disposable artefact there is.

**The finding that reordered everything: nothing measures retrieval quality.** `P14-02` records
`asked` and `returned` per search, and *returned 5* is not *returned the right 5*. Every option here
would otherwise have shipped on taste, which is the unverifiable self-referential claim `Law 9`
forbids. So the golden set comes **before** the path change, not after — otherwise *"the new one is
better"* is a row that cannot honestly be ticked.

**Deleting the Jaccard scorer is `Law 13`/`Law 14`, not a `Law 1` subtraction.** The capability —
searching memories — survives and improves on `_hybrid_retrieve` (BM25 + corpus IDF + optional
vectors), which already has the two best callers and already degrades sanely without a vector store.
What goes is a *duplicate implementation* serving five surfaces worse, including the agent's own
`memory_search`. This is the same argument `P3-10` used to delete `calendar/reminders.js`, and it
carries the same obligation: the safety case must be executable before anything is removed. It also
makes `P13-11`'s (a) and (b) — `_is_identity_memory`'s breadth and identity-above-preference group
order — **moot rather than answered**, because the scorer they live in is gone.

**Two `Law 14` traps found before writing anything, and both change the shape of the work.**

1. **Reinforcement already ships.** `src/memory.py` keeps a `uses` counter, `chat_processor.py:353`
   calls `increment_uses` on every injected memory, and the Brain's *"Most used"* sort is that
   signal on screen. `P13-04` already records this. So *cross-session frequency* is **not** that
   counter and must not become a second one: `uses` counts **recalls** (how often the system reached
   for a fact), and what is missing counts **mentions** (how often the person said it, across how
   many distinct sessions). Both belong on the same record, named apart, or the Brain grows two
   numbers that disagree.
2. **The retrieval trace already ships end to end.** `chat_processor` → `chat_helpers:1195` →
   `chat_routes:1729` (`memories_used`) → `chatRenderer:2134` (`.memory-used-pill`), with a detail
   popover. `P13-10` records this. So `B61`'s engine attribution rides **that** payload and **that**
   pill — one more field and one more line of pill text — rather than a second trace surface.

**Order of work.** `B61` (say which engine answered) → the golden set → one retrieval path →
cross-session mentions → two-stage selection. `B61` is first because it is what makes the golden set
readable: a scored run whose engine is unknown cannot be compared to another.

**Cost.** Two-stage selection spends one utility-model call per memory-using turn. That is a real
cost on the owner's own hardware and it is accepted **only** once the golden set can show what it
buys — which is the same discipline as the ordering above, applied to the most expensive option.

**What would reopen this.** The golden set showing `_hybrid_retrieve` is *not* better than the
scorer it replaces — in which case the deletion is wrong and the measurement did its job.

---

## D-2026-09-09-01 — the assistant learns how you talk, and changes its register rather than its mood

**What the owner asked for**, in their words: *"the idea the llm can build a profile on the user based
around topics of conversation… much deeper than just 'User's settings say use this level of warmth in
the response'. It builds off it… recognizes tone by the way the user types, shifts in emotion by the
amount of swears or laughing, which ties into humor etc… thats how we get a much more 'human'-ized
LLM — A chat box that does more than thinks and replies, it actually engages and conversates."*

**The seed already ships, in the narrowest form it could take.** `src/agent_loop.py`
`_is_casual_low_signal` reads *how* a message is written — a short greeting with a two-word tail —
and changes what the model receives, suppressing skills and stale context. So the product already
adjusts itself from typing style. It is one regex, one bit, per turn, with one effect. Everything
below is the general case of a mechanism this codebase already trusts, which is why it is `Law 1`
growth rather than a new subsystem.

**Nothing here is a "warmth setting".** That phrase describes the pattern the owner is contrasting
against, and it is worth recording that Pantheon does not have one: there is no `warmth` key
anywhere in the tree. What exists is **personas** (`src/reminder_personas.py`, `presets.js`) — Razor,
Socrates, Spark, Nietzsche — which are the **assistant's** voice, chosen explicitly. This work is the
mirror of that: the **user's** voice, observed.

### The three layers, and why conflating them is the whole failure mode

1. **Style — slow, stable, months.** How this person writes: sentence length, capitalisation,
   whether profanity is punctuation or emphasis, emoji, technical density, whether they instruct or
   ask. This is a **profile**.
2. **State — volatile, this session, expires.** Deviation from *their own* style right now. Shorter
   than usual, more swearing than usual, no greeting = under pressure. This is a **reading**, and it
   must decay; a reading that persists becomes a belief.
3. **Register — the output.** What the assistant does about it. Length, directness, whether to ask a
   clarifying question or just act, whether a joke is welcome.

An assistant that decided you were angry in March and has been careful with you ever since is what
happens when 2 is stored like 1.

### The measurement that makes any of it work: the baseline is personal, never population

**A swear count is not an emotion signal. A swear count against this person's own baseline is.**
The owner writes *"PRESS!!"* and *"lol"* as ordinary register; a population-trained sentiment model
reads that as elevated and would be wrong every single time. The same three words from someone whose
baseline is flat prose mean something entirely different. Every signal in this design is a delta
against the individual, computed from their own history, and a person with no history yet gets no
reading at all.

### What the assistant does about it: register, not mood

**The assistant must not mirror the mood, and this is the line the whole feature lives or dies on.**
Detecting pressure and responding with sympathy is the failure everyone ships: it answers impatience
with *more words*, which is exactly backwards. The useful move is shorter, no caveats, lead with the
fix, stop asking clarifying questions and make the obvious call. That *is* engagement. Performed
concern is its opposite.

Put as a rule: **a reading may change how much is said, how directly, and whether the assistant asks
or acts. It may not change what is true, and it may not add feelings the assistant does not have.**

### Humour is the hardest signal and the most valuable, so it does nothing until it is learned

Detecting that someone jokes is trivial. Knowing what their humour *means* is the whole problem,
because the same observable has opposite meanings across people:

- joking to defuse → the joke is a **stress** signal;
- joking when relaxed → the joke is a **green light**;
- joking to soften a complaint → the complaint is real and the joke is the wrapper.

A counter cannot separate those, so humour is a **learned per-person association** and produces no
register change until there is evidence for which one this person is. Guessing here is worse than
abstaining: mistaking a wrapped complaint for a good mood is the single most alienating error the
feature could make.

### Getting it wrong is worse than doing nothing, so confidence gates action

Softening everything for someone who is not upset is patronising, and it is the failure people
actually notice and resent. Low confidence means **behave normally** — not "behave gently".

### A profile you cannot see is a profile you cannot correct

It lives in the Brain, in plain sentences, editable and deletable, like a memory. `P13-00` already
makes legibility the acceptance criterion for the whole phase and this is the row where it matters
most. **Edits are the error signal**: there is no golden set for this and there cannot be, but "did
the person change what we wrote about them" is a real measurement and it is the one to keep.

### An explicit choice always beats an inferred one

A chosen persona wins over a reading, every time. This is `setting_is_explicit` — `H06`, `H08`,
`D-2026-09-08-02` — on its fourth application, and it is now plainly a standing principle of this
codebase: **a thing a person typed beats a thing the system inferred.** Someone running Razor asked
for blunt and minimal; a reading that they seem playful today does not get to soften it.

### Law 16, and why this is not a fine-tune either

This is the most intimate data the product would ever hold. It never leaves the machine, it is
deletable in one action, and deleting it takes effect immediately rather than at the next retrain —
which is the same argument that ruled out a fine-tune for memory in `D-2026-09-08-07`, reaching the
same conclusion from a different direction.

**The line between this and surveillance is stated once and enforced by what gets written down:**
the profile records *how to be useful to this person* and not *how this person is doing*. *"Writes
shorter under pressure; wants the fix before the explanation"* is a working note. *"Seems anxious
lately"* is not something a text box should be keeping about anybody, and no row here may produce it.

**What would reopen this.** The owner disliking the result, which for this feature means it feels
like being watched rather than being known — and that judgement is theirs alone.

---

## D-2026-09-10-01 — the agent gets the LAN, and the container still does not

**What the owner asked for**, in their words: *"It appears the Agent cant touch outside of the
dockers container network. So we need to give this thing the ability to have an agent that plays as
the network administrator/engineer. It should have an MCP that allows this. This stemmed from me
wanting to make an agent perform and organize an ARP table on my network but its stuck inside the
docker sandbox."*

### The measurement, which states the problem better than the sentence does

From inside the running container, on the owner's own machine:

    192.168.1.1:80    TimeoutError      ← the gateway in the next room
    192.168.1.1:443   TimeoutError
    1.1.1.1:53        REACHABLE         ← the public internet

**The agent has more reach to the outside world than to the network it is hosted on.** For a
project whose first law about dependence is *"we drop external dependence"*, that is precisely
backwards.

And the ARP case is not a permissions problem, it is topology. The container's ARP table is:

    172.18.0.1 / 172.18.0.3 / 172.18.0.5

— the Docker bridge, its gateway and two sibling containers. ARP is link-layer; a bridged
container's neighbour table is the bridge's and can never be anything else. The host has 24 real
entries. **No flag on the container makes the second list appear in the first.**

### Why the obvious fixes do not work here

- **`network_mode: host`** binds the container to the host's network namespace — and on Docker
  Desktop for Windows the "host" is the **WSL2 VM**, which is itself NAT'd behind Windows. It would
  move the problem one hop, not solve it. This is the owner's platform, so this option is out on
  their box specifically.
- **`macvlan`** gives a container a real address on the LAN and is the right answer on Linux with a
  physical NIC. It is not available on Docker Desktop for Windows.
- Both are also **Linux-only answers to a question three shipped deployments ask differently**,
  which is the shape `B64` just finished punishing.

**So the capability lives in a process on the host, and Pantheon talks to it.** It is the only
option that works on the owner's topology, and it happens to be the better one anyway — see below.

### The container staying unable to reach the LAN is a feature, not a consolation

The instinct is to read the host process as a workaround with a cost: something else to install and
keep running. That cost is real. But the alternative is handing LAN reach to a 2.9GB container that
runs arbitrary agent-authored code, executes bash and python, fetches web pages it was told to
fetch, and loads skills. **The blast radius of a compromised Pantheon would then include the
owner's network by construction.**

Splitting it means the LAN capability lives in a small process that does a short list of things and
can be read in one sitting, and Pantheon holds a token for it. That is the same argument
`D-2026-09-01-01` makes about the auth boundary, applied one layer out.

### How this sits with `FORBIDDEN.md` Part 2, which never lifts

`FORBIDDEN.md:158` lists *"the five SSRF validators + pinned-IP transports"* against
*"cloud-metadata and internal-network SSRF"*, and Part 2 does not relax. `Law 17` says
*"internal comms, LAN to LAN etc is totally fine"*. Both hold, because **they are about different
surfaces**:

- The SSRF validators guard URLs that arrive **from content** — a page the agent was told to read, a
  skill it imported, a webhook body. Their threat model is the confused deputy, and it is unchanged
  by any of this. `web_fetch` still refuses `192.168.1.1`, and that must never become negotiable.
- The network tools are **operator-initiated against the operator's own named network**.

**What keeps the second from becoming a hole in the first:** the network agent answers only for
CIDRs the operator wrote down. *"My network is 192.168.1.0/24"* is configuration; a target outside
it is refused whoever asks and however the asking is phrased. A prompt injection reading *"enumerate
10.0.0.0/8"* is refused because 10.x was never named — **not because the model declined, which is not
a security control.**

And that allowlist is **operator-set and not agent-writable**: `_SELF_RESTRAINT_KEYS` (`B42`) is the
existing mechanism and this is its clearest case yet — a setting the agent may read and may not
write, because a gate the gated party can widen is not a gate.

### Read before write

Phase one is **observation only**: neighbours (ARP), reachability, DNS, service discovery
(mDNS/SSDP), open-port checks against named hosts, and DHCP lease reading where the router exposes
it. *Organising an ARP table* — the owner's actual ask — is entirely inside that.

**Configuration is a separate decision and does not ride in on this one.** Changing firewall rules
or router settings is a different risk class, and bundling it here would mean the first version of a
network capability could also break the network it is describing.

### `Law 14`: this is not the companion

`companion/` exists and is **inbound** — a phone discovering and pairing *to* Pantheon. This is
outbound. Different direction, different process, not a duplicate. But `companion/pairing.py` is
exactly the right machinery to authenticate Pantheon *to* the network agent, and reusing it is the
point of noticing.

**What would reopen this.** A deployment where the container genuinely can reach the LAN — Linux
with macvlan — where the host process is redundant. The design should let that case skip the extra
process rather than pretend it needs one.

---

## D-2026-09-10-02 — the operator sets the ceiling; the agent moves inside it

**What the owner decided**, on whether the network agent may ever *configure* rather than only
observe (`P17-05`): *"The user decides how 'powerful' the LLM agent is... So it is up to the user."*

**So configuration is in scope**, and the boundary this project keeps arriving at is not
read-versus-write. It is **who set the ceiling**.

That is `setting_is_explicit` on its fifth application — `H06`, `H08` (`agent_max_rounds`),
`D-2026-09-08-02` (`max_tokens`), `D-2026-09-08-04` (loop caps) — and at five it stops being a
pattern and becomes the spine of this project's authority model, worth stating once in general
terms: **a thing a person typed beats a thing the system inferred, and the agent may move within
the ceiling but never raise it.**

**What follows mechanically:**

- Configuration capability ships **off**.
- **Each capability is its own switch, not one god-flag.** An operator who turned on DHCP
  reservations has not thereby asked for firewall rules, and bundling them would make the owner's
  sentence mean less than they said it.
- Every switch lives in `_SELF_RESTRAINT_KEYS` (`B42`): the agent reads it and cannot write it,
  because a gate the gated party can widen is not a gate.
- `P17-02`'s CIDR allowlist still bounds **where**, regardless of **what**. The two are independent
  and both apply.

**The one thing this does not license.** A change with no way back. Anything that could sever the
operator's own access — to their network, or to Pantheon itself — needs a stated undo before it is
offered, because *"the user decides"* stops meaning anything the moment the user cannot reach the
surface where deciding happens. That is not a hedge against the owner's answer; it is the condition
that keeps their answer true.

**What would reopen this.** The owner narrowing it, or a capability whose undo cannot be stated —
which is a reason not to ship that capability rather than a reason to revisit this.

---

## D-2026-09-10-03 — the native-vs-MCP question is not where the defects come from

**What `P17-06` asked**: *"The tool surface is 28 tools and 4 built-in MCP servers, and there is no
rule for which a new capability should be… the first honest step is not a list of ideas — it is the
rule that decides where a new capability goes, because `Law 13` says a capability in one of N places
is the defect and right now the choice looks like taste."*

The row is right that the choice looks like taste. Counting the surface before writing the rule
produced a different answer to a better question.

### The rule as asked, and it does predict

A capability is an **MCP server** when it must run in its own process — because it carries a
dependency set, holds a connection or a client of its own, or has a blast radius the app should not
take on. It is a **native tool** otherwise. Tested against the four:

| server | lines | own state | rule predicts | actual |
|---|---|---|---|---|
| `email` | 2913 | IMAP/SMTP per call, its own sqlite cache | **MCP** | MCP ✓ |
| `rag` | 243 | `_rag_manager`, `_personal_docs_manager`, a Chroma client | **MCP** | MCP ✓ |
| `memory` | 286 | imports the app's own `src.memory` | **native** | MCP ✗ — and native in practice |
| `image_gen` | 185 | none; one `httpx` call and a file write | **native** | MCP ✗ |

Three of four are predicted, and the two misses are informative rather than embarrassing.
`manage_memory` **is** dispatched natively (`dispatch_ai_tool` → `do_manage_memory`), so the rule
predicts the behaviour and the *placement* is the error — the connected `memory` server is a second
`MemoryVectorStore` in a second process serving nothing (`B67`). `image_gen` is 185 lines doing what
`web_fetch` does natively.

**The rationale in the tree does not survive counting.** `src/builtin_mcp.py` says the four *"each
carry hundreds of LOC of unique IMAP / HTTP / manager logic not worth duplicating into the native
path"*. `wc -l` says 2913, 286, 243, 185, and all four import from `src/` — so three of the four are
refuted by the sentence's own test, and "duplicating into the native path" was never the cost,
because they already run the native path's code inside a subprocess.

### The rule that actually prevents defects, which is a different rule

Placing a capability has never broken anything here. **Registering one has, four times** — and the
fourth was found by the ninth register while this was being written, which is the argument for a
checker made by the surface itself. A tool name has to appear in up to **nine** independent places,
and a name missing from any one of them fails silently and *differently*:

1. `TOOL_TAGS` — the fence gate; a miss here drops the block with no error at all
2. `FUNCTION_TOOL_SCHEMAS` — the function-call channel
3. a dispatch branch, `TOOL_HANDLERS`, or `_MCP_TOOL_MAP`
4. `TOOL_CAPABILITIES` — what the approval card is allowed to say
5. `_FEATURE_TOOLS` — the operator's feature flag
6. the `disable_tool` group alias
7. the system prompt
8. the MCP server, when it has one
9. `BUILTIN_TOOL_DESCRIPTIONS` — the descriptions agent mode embeds to retrieve a tool at all

`TOOL_TAGS` carries its own comment about the first two incidents — the whole cookbook family, then
`tail_serve_output`, which `do_serve_model` *orders* the agent to call after every serve
(*"Do not tell the user to check logs; you have the log tool"*), and which both call channels
rejected. The third is recorded in another test's docstring: `api_call` went missing the same way in `tool_index.py`'s `BUILTIN_TOOL_DESCRIPTIONS`, the ninth register, whose parity test says so in its own docstring — and agent mode selects tools by embedding those descriptions, so a schema without one is never retrieved and never shown to the model. `B66` is the fourth: `manage_rag`, named twice in the system prompt as the place to offload
large tool results, in no tag set. `parse_tool_blocks` gates on `TOOL_TAGS`, so no `ToolBlock` was
ever built — which means not even the *"Unknown tool"* branch ran. No error, no `events` row, nothing
in the receipt, and `strip_tool_blocks` gates on the same set so the raw fence stayed **visible in
the reply** underneath a sentence saying the data was stored.

**So the rule is `.pantheon/check-tool-surface.py` and not this document.** A paragraph is what was
missing all four times; a paragraph is not a check. Register 9 is named there and deliberately not
re-checked — `tests/test_tool_index_schema_parity.py` already pins it in both directions and a
second copy of a rule is what `Law 14` is about — but the header lists all nine, because a reader
who cannot see every register cannot tell which one they missed. The checker asserts each of the four things a
real defect has already exploited, reads the dispatch chain with `ast` rather than a regex (`Law 20`
— a comment naming a tool is not a dispatch), and refuses a connected built-in server nothing routes
to.

### What this decides for `P17`

The network capability is an MCP server under the rule above: it holds its own process on the host
by construction (`D-2026-09-10-01`), which is the whole point of it. That was going to be the answer
anyway — **the value of asking was the three defects the counting turned up**, which is the same
shape as `P13-13`, where measuring retrieval before improving it found `B61` and `B62`.

### What is deliberately not decided here

**The gap analysis is not written, and cannot be from this tree.** `P17-06`'s second clause asks for
one *"derived from what the agent is actually asked to do rather than from imagination"*. This
checkout holds 0 sessions, 0 chat messages and 1 `events` row; the only fixture in the tree declares
its own `provenance: "fixture"` and says *"pairs written from imagination test the imagination"*.
The data exists only on the owner's running deployment. Worse, the single best signal for it is
computed and thrown away: `src/teacher_escalation.py` classifies *"I don't have a tool for that"* /
*"I'm not sure which"* replies as a turn failure and `escalate_and_learn` is a stub that logs and
returns `None`. **A gap analysis needs a gap detector, and one exists unwired.** `P17-07` records
the signal; `P17-08` runs the analysis against real traffic. `P17-06` stays open until they land,
because ticking it on the half that could be done here is exactly what `Law 9` forbids.

**What would reopen this.** A capability that is neither clearly in-process nor clearly its own
process — at which point the table above is the argument, not the taste.

---

## D-2026-09-11-01 — the container reaches the host, and the list that stops it lives where Pantheon cannot edit it

**What the owner asked**, 2026-09-11: *"the intent was the agent has 'Shell' mcp and permissions but
it doesn't reach outside of the docker host. I want to be able to have something for agents inside of
Pantheon to reach out and touch **beyond** docker's sandbox... with explicit permission gating
(bypassable with the permissions bypass setting) - and there must be a definitive non-bypassable
blacklist of things like 'formatting the users C: drive' etc.. Super **nuclear level** dangerous
commands."*

Two halves, and they pull in opposite directions on purpose. That tension is the decision.

### The premise is correct and the reason is not a defect

`bash` runs in the container. It cannot reach the host, and the containment is the feature, not an
oversight to route around. There are exactly four ways past it:

| Way | What it costs |
| --- | --- |
| Mount the Docker socket | Root on the host, permanently, for anything that can talk to the socket |
| `--privileged` | The same, with fewer steps |
| Host SSH credentials in the container | A credential that survives the container and works from anywhere |
| A small process on the host that answers a narrow protocol | Only what that process chooses to do |

The first three hand over the host and then try to claw capability back with rules **inside** the
thing being constrained. The fourth puts the rules on the far side of a boundary the constrained
party cannot cross. `FORBIDDEN.md` Part 2 already pins the Host-Docker flag off, and
`docker/host-docker.yml` stays the opt-in overlay it was. `P17-01` already built the fourth for
observation, deliberately with **no writer**: every route but one is a `GET`. `P17-11` adds the one
writer.

### The three forks, and the owner picked the most permissive of each

They were put as a question with recommendations, and all three recommendations were declined in the
permissive direction. Recorded because the alternative — quietly implementing what was recommended —
is how a tracker starts lying.

| Fork | Offered | **Chosen** |
| --- | --- | --- |
| What may the host agent run? | Allowlist / allowlist+denylist / **denylist only** | **Denylist only** |
| What privilege does it run with? | Never elevates / **elevates for named commands** / always | **Can elevate for specific named commands** |
| How is host execution approved? | Its own always-ask gate / its own rung / **inherits the existing rung** | **Inherits the existing trust rung** |

*Denylist only* means the default answer is **yes**, and anything not named runs. That is the
owner's machine and the owner's call, and it is exactly why the denylist has to be somewhere
Pantheon cannot reach: when the default is yes, the list is the whole boundary.

### So the guard is compiled into the host process, not stored in settings

`netagent/guard.py` holds **52 rules**. Pantheon cannot read past them, edit them, or switch them
off — not because a flag forbids it but because they are in a different process on the other side of
an HTTP call, started by the operator, with no route that writes them. `FORBIDDEN.md`'s standing
rule — *"a bypass exists to be left on"* — is why there is no bypass at all rather than an
admin-gated one.

Three checks run, and **only the third is a boundary**:

1. `src/host_exec_policy.py` — the operator's denylist and allowlist, in settings, editable in the
   Networks panel, substrings rather than regexes. It narrows what Pantheon will *send*. The panel
   says in as many words that it is not the boundary, because an operator who believes it is will
   under-protect the real one.
2. The trust rung, inherited, per the owner's third answer. `host_shell` is classified
   `EXECUTE_CODE` + `DESTRUCTIVE`, so the approval card names both, and the permissions bypass the
   owner asked for is the one that already exists.
3. `netagent/guard.py` — the list that never lifts.

**Five of the 52 rules exist to keep the other 47 enforceable.** `base64 -d | sh`,
`powershell -EncodedCommand`, `curl | sh`, `eval` on a variable, `xxd -r`: none is dangerous by
itself, and each makes string inspection meaningless. A denylist that can be handed an opaque
payload is a denylist with one rule.

**The refusal never says which list caught it.** The rule's name and reason go to the person; the
agent gets *blocked, and why the class is blocked*. Telling an agent that the operator's editable
list stopped it teaches it where the soft edge is.

### Elevation is delegated to the OS, and that is not a hedge

The agent runs as the person who started it and never elevates itself. `elevated: true` on a named
command routes to `Start-Process -Verb RunAs` or `sudo` — a UAC dialog, a sudo password, or a
NOPASSWD rule the operator wrote. An unelevated process has no other honest way to elevate, and the
side effect is that the OS keeps a veto that a string denylist does not have. The cost is stated
where it will be met: a background agent raising UAC with nobody at the keyboard times out, and the
result says *timed out waiting for consent*, not *the command failed*.

### Knowingly accepted: `trust_rung` is agent-writable and host execution now inherits it

`trust_rung` is deliberately **not** in `_SELF_RESTRAINT_KEYS`, so the agent can lower its own
approval requirement through `manage_settings` — and as of this decision that rung also governs
`host_shell`. The loop is real: an agent that can write its own rung can reduce the approval it
needs to run a command on the host.

It is accepted rather than closed, and the reasons are stated so a future reader can reverse it
knowing what they are reversing:

- The guard is unaffected. The rung governs *whether a person is asked*, never *what may run*, so
  the loop widens approval and not capability.
- The owner's answer to fork three was *inherit*. Adding `trust_rung` to `_SELF_RESTRAINT_KEYS`
  because of this row would be answering a question the owner already answered.
- `allow_bash` is still upstream of all of it and is per-turn and off by default.

**What would reopen this.** Any path by which Pantheon can change what the host agent will run —
a settings-sourced guard, a route that writes rules, an agent-reachable restart with different
arguments. At that point the boundary is gone and the denylist-only choice has to be re-put to the
owner, because it was made on the assumption the list holds.
