# Pantheon — Implementation Roadmap

> Fork of **Odysseus** (`pewdiepie-archdaemon/odysseus`, AGPL-3.0-or-later).
> Elevation, not rewrite. Read `AGENTS.md` before starting anything.

**Tick format:** `- [x] **P1-03** … — agent:`abc123` — 2026-08-25`

| Phase | Area | Tasks | Done |
|---|---|---|---|
| P0 | Fork identity & licence | 28 | 0 |
| P1 | Token layer — the free wins | 14 | 0 |
| P2 | Un-nerf | 26 | 0 |
| P3 | Mechanical hygiene | 12 | 0 |
| P4 | The wire — the real glass box | 24 | 0 |
| P5 | Trace & composer restyle | 16 | 0 |
| P6 | Queue & Plan | 17 | 0 |
| P7 | Trust ladder & control plane | 11 | 0 |
| P8 | The Workshop | 48 | 0 |
| P9 | Feature surfaces | 14 | 0 |
| P10 | Accessibility & release | 12 | 0 |
| **Total** | | **222** | **0** |

---

## ⚑ ON RECONNECT — do this first

The desktop bridge dropped mid-session. Nothing below can start until it is back.

- [ ] **R-01** Confirm the bridge: `git rev-parse --abbrev-ref HEAD` in the repo returns `custom`.
- [ ] **R-02** `./scripts/pantheon-repo-setup.sh --dry-run` → read it → `--apply`. Creates the private repo, renames `origin`→`upstream`, `custom`→`main`, pushes the scaffolding.
- [ ] **R-03** `./scripts/pantheon-init.sh --dry-run` → read the diff → `--apply`. Covers P0-02/03/04/06/07/08/10/11.
- [ ] **R-04** Edit the live `.env` on the host: `ODYSSEUS_*` → `PANTHEON_*`.
- [ ] **R-05** `docker compose up -d --build`, then confirm the app boots and you can log in.
- [ ] **R-06** **Clone the pushed repo into the build container.** From that point the agents work in the cloud against a real clone and push branches; the desktop only pulls and rebuilds. This is what unblocks parallel agent work — see `ORCHESTRATION.md`.

Once R-06 lands, the bridge stops being on the critical path.

---

Phases are ordered by dependency, not importance. **P0 → P1 → P3 are strictly
sequential.** P2 is independent and can run in parallel with anything from the start.
P4 gates P5. P8 depends only on P1.

---

# P0 · Fork identity & licence
*Area: `identity`, `release` · Blocks: everything*

The rename is ~2,900 occurrences across 371 files, of which ~150 identifiers are
load-bearing.

**Deployment reality: one self-created admin account, one Docker install, a home LAN,
no other users, no downstream consumers, and the data is explicitly disposable.** The
entire "breaking change" analysis collapses — there is nobody to break and nothing to
preserve. **No migration shims. No compatibility layer. No data migration.** Rename,
purge, re-index, log back in. The only manual step is one line in your `.env`.

`scripts/pantheon-init.sh` does the mechanical sweep. Review its diff before committing.

- [ ] **P0-01** Create `.pantheon/` with `AGENTS.md`, `ROADMAP.md`, `FORBIDDEN.md`, `DEFERRED.md`, `handoff/`. Seed one empty handoff file per area.
- [ ] **P0-01b** Run `scripts/pantheon-init.sh --dry-run`, read the diff, then run it for real. It does P0-02, P0-03, P0-04, P0-06, P0-07, P0-08, P0-10 and P0-11 as one reviewable sweep, with the attribution files excluded. Everything after it is by hand.
- [ ] **P0-02** Rename cosmetic surfaces: page titles, wordmark text in `index.html` + `login.html`, 111 UI strings across `static/js/`, tray menu in `launcher.py`, `setup.py` banner. `Verify:` grep for case-insensitive `odysseus` in `static/` returns only attribution strings.
- [ ] **P0-03** Rename env prefix `ODYSSEUS_*` → `PANTHEON_*` (99 distinct names, 560 refs). Update `.env.example`, `docker-compose*.yml`, `Dockerfile`, `docs/`, **and your live `.env` on the host** — that one file is the entire migration. No shim. `Verify:` app boots with only `PANTHEON_*` set.
- [ ] **P0-04** Rename browser storage keys (113 distinct, 206 refs in `static/`). Costs you one theme re-pick and a layout reset. `CI:` none.
- [ ] **P0-05** Rename the six ChromaDB collections. **Data is disposable — do not migrate.** Drop the old collections and let the app re-index. `Verify:` memories, RAG and tool index all return results after a re-index.
- [ ] **P0-06** Rename session cookie `odysseus_session` → `pantheon_session`. You log in again once.
- [ ] **P0-07** Rename outbound HTTP headers (`X-Odysseus-Origin/Kind/Ref/Event/Signature/Owner`) and the four User-Agent strings. No downstream consumers exist yet — do it now, before any do.
- [ ] **P0-08** Rename Docker compose service, container user (`ODY_USER`), and the SearXNG settings sentinel `odysseus-local-searxng-json-2026-05-30`. `Verify:` a clean `docker compose up` produces a working SearXNG.
- [ ] **P0-09** Rename data dir default (`~/.odysseus/data`), systemd unit + installer, PyInstaller spec, macOS `CFBundleIdentifier`, PWA manifest name, service-worker cache name. **Docker mounts `./data` explicitly, so the default path change does not move your live data** — verify that before restarting.
- [ ] **P0-10** Rename the 19 `scripts/odysseus-*` CLI scripts (`git mv`). If you have a crontab or systemd timer pointing at any of them, update it — otherwise nothing references them.
- [ ] **P0-11** Rename Swift package + two executables, the two integration plugin ids (`integrations/{claude,codex}/skills/odysseus/`), `_EMAIL_MCP_OWNER_ARG`, and the 3 custom DOM events. `Depends:` P0-02.
- [ ] **P0-12** Remove or re-point every upstream-identity reference that would misattribute the fork: repology badge, star-history block, 24 `odysseus-dev` URLs, `package.json` repository, `.github/` templates, `cookbook.js:3177`.
- [ ] **P0-13** Design the Pantheon mark. **Do not reuse the red sailing boat, the wordmark, or the per-route favicon shapes** — the licence grants them but they are upstream's identity. Replace `static/icon.ico`, the favicon registry, the inline boat SVG (5 copies), and the programmatic tray drawing. **Keep the ASCII wave loader** — it's a loader, not a logo.
- [ ] **P0-14** **§5(a) + §5(b) notices.** Add to `README.md` and a new `NOTICE`: a prominent statement that this is a modified version of Odysseus, **with a date**, and that it is released under the AGPL. Neither exists today.
- [ ] **P0-15** **§4 copyright line.** There is **no project copyright notice anywhere in the repo today**. Add Pantheon's and preserve any upstream one that can be established.
- [ ] **P0-16** **Apache-2.0 §4(b) change notices** on the research-derived files (`services/research/`, `src/research_handler.py`, `routes/research/`, `services/search/`) — "You changed the files". Absent today.
- [ ] **P0-17** **§13 Source link.** Single footer button in the UI. `href` → the public repo. `title="Built on Odysseus — click to see where Pantheon originated from!"`. Must be present on the logged-in shell and the login page. This is the one licence obligation that is genuinely required and genuinely missing. `Depends:` P0-12.
- [ ] **P0-18** Decide `AGPL-3.0-only` vs `AGPL-3.0-or-later` and state it in `LICENSE`, `README`, and SPDX headers. Today the qualifier lives in exactly one README line with zero SPDX headers.

### P0 · Credits — the licence gaps you inherit
*Do not publish before these close.*

- [ ] **P0-19** Rewrite `ACKNOWLEDGMENTS.md` as Pantheon's credits file. **Lead with Odysseus.** Preserve every credited party. Update paths that moved.
- [ ] **P0-20** Add missing licence bodies to `licenses/`: highlight.js (BSD-3), SheetJS/xlsx (Apache-2.0 — check upstream for a `NOTICE`), docx (MIT), mammoth.js (BSD-2), jsPDF (MIT), html2canvas (MIT), node-qrcode (MIT). MIT and both BSDs require the notice to travel with redistributed copies.
- [ ] **P0-21** Fetch the missing `html2pdf.bundle.min.js.LICENSE.txt` — the bundle's own banner references a file that is not in the repo.
- [ ] **P0-22** Add OFL text for Fira Code and Inter, and list the **20 KaTeX font faces** — all carry Reserved Font Names and are currently credited as MIT-only. Do not subset any font, or OFL §3 bites.
- [ ] **P0-23** **Resolve `static/fonts/custom/GohuFont.ttf`.** The shipped file is 1,468 bytes / 3 glyphs, metadata reads `Untitled1 / Copyright (c) 2025, Unknown`. It is not GohuFont. Replace with the real WTFPL font + licence, or remove it and drop the credits row.
- [ ] **P0-24** Add undisclosed deps to credits: `nh3`, `python-dateutil`, `httpcore`, `httpx2`, `python-magic`, Real-ESRGAN wheels, the two MLX Swift packages. Update `duckduckgo-search` → `ddgs`.
- [ ] **P0-25** Correct the PyMuPDF scope statement — it is documented as form-filling only; it also backs the PDF viewer's page render and the annotation-fill endpoint (three route handlers). Fix the stale docstring at `routes/email_helpers.py:1453` that credits it for text extraction it does not perform.
- [ ] **P0-26** Reconcile the credits file's "the core ships fully permissive (MIT-compatible)" framing against the AGPL `LICENSE`, or state which is authoritative for Pantheon.
- [ ] **P0-27** README statement of intent: *"Pantheon is free software under the AGPL. I don't sell it, and I'd rather you didn't."* **Social, not legal — do not add a non-commercial clause.** AGPL §10 prohibits further restrictions and §7 lets any recipient strip one.

---

# P1 · Token layer — the free wins
*Area: `tokens` · Depends: P0-01 · Blocks: P5, P8*

More visible change than any redesign step, and zero markup touched.

- [ ] **P1-01** **Define `--accent` in `:root` + the light variant.** 799 references; **205 are bare with no fallback** and currently resolve to `unset`. **This repaints all 799 sites at once — do it as its own step with the app open.** `Verify:` rail hover backgrounds appear; both resize handles become visible; the session rename input gets a border; the scroll-to-bottom button gets its colour.
- [ ] **P1-02** Define `--accent-primary` (121 uses, never defined) — or replace those uses with `--accent`.
- [ ] **P1-03** **Define `--fg-muted`** (93 bare uses, zero definitions). Every one of those elements was authored as secondary text and renders at full strength. `Depends:` P1-01.
- [ ] **P1-04** **Delete `#sidebar-backdrop { display:none !important }`** at top-level nesting depth 0 — it beats the media-query rule everywhere. Thirteen call sites across four modules already toggle the element. `Verify:` mobile drawer dims the page and tap-to-close works.
- [ ] **P1-05** **Fix `#rail-settings`** — it unhides the sidebar and scrolls to the bottom instead of opening Settings. The guided tour uses it as its opener, polls 25 times, and gives up with an error. `Verify:` the tour completes.
- [ ] **P1-06** Add 4–6 semantic status tokens (`--ok --warn --danger --info` + optional `--think`) derived from the five theme tokens. Absorbs **420 of 517 unthemed colour occurrences across 68 distinct hex values** — 21 reds meaning danger, 22 blues meaning info.
- [ ] **P1-07** Separate the ~120 Dracula/One-Dark syntax-palette occurrences into their own token set. They are code-block theming that was never wired to the theme system — not app status colours.
- [ ] **P1-08** **Computed `--on-accent`.** `.send-btn` hardcodes `color:#fff`; white-on-accent fails 4.5:1 on **all 16 themes**, and the accent itself fails on 7 of 16. One token fixes all sixteen.
- [ ] **P1-09** Add a contrast guard inside `generateHarmonyColors()` and `applyColors()` (~15 lines) so every future custom theme clears the floor too. `Depends:` P1-08. **`CI:`** any new theme token must extend `ADV_KEYS` **and** `computeAdvancedDefaults()` in lockstep or all 16 themes break.
- [ ] **P1-10** **Normalise z-index to 7 named tiers.** 261 declarations, 63 distinct values, range −1 to 1,000,000. Use the order-preserving remap: strictly increasing in the same sorted order ⇒ no element can change stacking. `Verify:` the remap list is strictly increasing; nothing moves visually.
- [ ] **P1-11** Fix the toast occlusion the tiering surfaces — toasts sit at 9999, below every image-editor popover at 10001–10006. Deliberate second pass, needs visual review. `Depends:` P1-10.
- [ ] **P1-12** **One global `prefers-reduced-motion` guard.** 18 narrow opt-outs against 148 keyframes and 7 unguarded canvas animators — the background effects run continuously with nothing.
- [ ] **P1-13** Elevation tokens: 4 theme-aware shadows replacing 274 declarations / 198 unique values. 110 hardcode `rgba(0,0,0,α)` — on the four light themes those read as grey smudges. The good theme-aware form already exists and is used 6 times.
- [ ] **P1-14** Name the signature curve. `cubic-bezier(0.34, 1.56, 0.64, 1)` is used 34 times and has never had a token.

---

# P2 · Un-nerf
*Area: `unnerf` · Depends: nothing · Runs in parallel from day one*

> ### Scouted. Read `P2-CORRECTED.md` first — the task text below is superseded.
>
> Six scouts and six adversarial reviewers checked all 26 premises against the source.
> The reviewers overturned the scouts on **twelve of twelve** contested calls. What the
> pass changed:
>
> - **26 findings, not 29.** The count below was unsupported.
> - **P2-01 is blocked on a decision, not ready.** libmagic does *not* refuse every `.js`
>   — plain `function`/`console.log` files sniff as `text/plain` and upload fine today;
>   only IIFE, UMD, `"use strict"`, shebang and React-import shapes trip it. And deleting
>   the function also deletes the only block on `.exe .dll .bat .cmd .vbs .ps1`.
> - **P2-02 as written is a no-op.** A route cannot set a CSP in this app — the security
>   middleware overwrites it. The route it "mirrors" is already dead at the wire.
> - **P2-06 is bigger than stated.** Files that fail the check do not lose a code fence;
>   they return a literal `[Attached document file]` banner and **zero bytes reach the
>   model** — `.go .bash .tsx .jsx .php .yaml .rs .sql .rb .xml`.
> - **P2-19 and half of P2-20 are missing *wiring*, not missing markup.** Five entries are
>   omitted from `admin.js`'s `inits` and `refreshAll`. Adding HTML alone yields a panel
>   that renders empty and never fetches.
> - **P2-25's safe prune count is zero**, and a second admin gate the roadmap never named
>   (`_ADMIN_TOOLS`, checked *before* the blocklist) means a wrong prune can pass a manual
>   test and still be wrong.
> - **P2-13 and P2-09 need the fork head.** Both sit in the guardrail-caps commit's
>   subject area; editing them against upstream would redo or silently revert it.
>
> Eighteen cross-cutting surprises are listed there too. Several apply outside P2.

Read `FORBIDDEN.md` § Never Lift before starting — ~30 controls on the other side of the
line stay exactly where they are, and `P2-CORRECTED.md` § A names the five tasks that will
cross one if implemented carelessly.

### The archetype
- [ ] **P2-01** **Delete the upload type check whole** — `is_safe_file_type()` and its call site. The blocked-MIME set contains `application/javascript`, so libmagic refuses every real `.js` file; `.js` isn't even in the extension list. **Nothing on the server executes an upload**, and every download carries `Content-Disposition: attachment` + `nosniff` ×2 + CSP. `.svg` — the actual stored-XSS vector — was never blocked. `CI:` none; no test references either constant. `Verify:` uploading `static/js/chat.js` succeeds.
- [ ] **P2-02** Optional belt-and-braces: add `Content-Security-Policy: sandbox` to `UPLOAD_RESPONSE_HEADERS`. One line, mirrors the emoji route. `Depends:` P2-01.
- [ ] **P2-03** **Delete four dead config blocks** (two allowlists, two blocklists) with zero readers. One blocks `.py`, `.sh` and `.js` — a live landmine if anyone wires it up.
- [ ] **P2-04** Delete the dead chat-upload validator that advertises a policy with no route callers.

### Widen
- [ ] **P2-05** Memory import allowlist → add `.yaml .yml .ts .tsx .jsx .sh .xml .toml .ini .sql .rs .go .java .c .cpp .rb .php .docx`, or replace with a size+decodability check. Content is decoded to text and fed to an LLM; nothing is served back. Update the frontend `accept` to match.
- [ ] **P2-06** `_is_text_file` → add `.ts .tsx .jsx .css .scss .yaml .yml .sh .bash .sql .toml .ini .c .cpp .h .go .rs .rb .php .java .xml .vue .svelte` — matching the fence-language set already in the same file.
- [ ] **P2-07** Email attachment-as-doc → add a text fallback for any decodable attachment instead of `Unsupported attachment type`. The editor renders every language already.
- [ ] **P2-08** Raise `MAX_INLINE_ATTACHMENT_CHARS` (24,000 shared across **all** attachments in a turn — with 10 files that is 2.4 K each). Make it per-attachment or scale it off the input token budget.
- [ ] **P2-09** Make `skill_max_injected` (default 3) context-window-scaled instead of a flat cap.

### Fix
- [ ] **P2-10** **The fake concurrency limit.** "max concurrent uploads: 3" is enforced as "≤3 uploads in the last ten seconds" and fires on a normal multi-file drag. Drop it; the 60/min rate limit already exists. `CI:` the test sets it locally, so the default is not pinned.
- [ ] **P2-11** Raise `MAX_FILES` (10 → 25) **and** add a server-side `len(files)` cap, which does not exist. **`CI:` a test regex-parses this literal** and asserts `upload_rate_limit >= MAX_FILES`.
- [ ] **P2-12** **Stop hiding small email attachments.** The signature heuristic also returns true for *any* image under 30 KB — a real screenshot is silently invisible **and** excluded from the ZIP. Keep the filename patterns, drop the size clause.
- [ ] **P2-13** Relax the two per-model sampling clamps that silently overwrite user presets (one also forces top-p, top-k, penalties and stop tokens). Make them defaults, not caps. **Keep** the cloud-provider clamp — that API 400s above the ceiling.
- [ ] **P2-14** Loosen the guide-only trigger: seven regexes fire on any mention of the phrasing and then strip every tool **and all MCP** for the turn. Require whole-message match, or an explicit toggle.
- [ ] **P2-15** Fix the self-contradicting bash prompt — one line forbids heredocs, seven lines later another instructs the model to use one. Prompt-only; enforces nothing.
- [ ] **P2-16** Fix the grammar bug producing `Your account is not allowed to can use research.`
- [ ] **P2-17** Cap the backup import — `await request.json()` with no size limit on an admin route.
- [ ] **P2-18** Fix the feature-flag story: `deep_research` defaults off, the frontend hides four buttons, and **no server route checks it**. Either enforce server-side or delete the three flags with zero consumers. Flip `deep_research` on.

### Re-surface what was built and never wired
- [ ] **P2-19** **Webhooks admin panel** — backend complete, **no UI whatsoever**. Add `adm-whList` / `adm-whAddBtn` markup. Add the null guards at the two functions that currently throw on `null.innerHTML` inside a silent `try` — which is why nobody noticed.
- [ ] **P2-20** MCP admin panel markup (`adm-mcp*`) — this also makes the OAuth-file registration path reachable for the first time. Feature toggles (`adm-featureToggles`), API tokens (`adm-tokenList`), RAG (`adm-rag*`). All four backends exist.
- [ ] **P2-21** Built-in skills editor: flip `showBuiltin = false` → `true`. `_buildBuiltinCards()` and its three admin endpoints are fully implemented, including a per-tool instruction-block override editor.
- [ ] **P2-22** Re-attach the gallery upscaler controls (`ge-upscale-*`). Backend + local Real-ESRGAN both implemented, zero UI.
- [ ] **P2-23** Give RAG upload a UI — the module expects three elements that do not exist. The endpoint works and has **no extension restriction at all**.
- [ ] **P2-24** Add a custom-font upload route. **Keep the extension allowlist here** — these files land under the static mount and are served with no forced disposition. This is the exception that proves the rule.
- [ ] **P2-25** Prune `NON_ADMIN_BLOCKED_TOOLS` of owner-scoped read-only tools. **Must stay:** shell, python, all filesystem tools, vault, settings, tokens, endpoints, MCP, webhooks, api_call, app_api, and the `mcp__*` prefix rule. **`CI:` two tests cover this partition.**
- [ ] **P2-26** Trim the "use the nicer tool" half of the app-API blocklist. **Must stay:** the cookbook install/rebuild/kill entries and every prefix rule.

---

# P3 · Mechanical hygiene
*Area: `css-hygiene` · Depends: P1 · Blocks: P5*

Provably safe, and each one removes a trap the restyle would otherwise fall into.

- [ ] **P3-01** **Resolve `#message` declared 4×.** The composer never renders at its authored 14px — a later `!important` forces 13px, and a third rule forces 16px on touch. One of the conflicting blocks sits under a class that does not exist. **Do this before any composer work.** *(Note: `max-height` is fine — 200px wins on specificity; only the font-size conflict is real.)*
- [ ] **P3-02** Resolve `.attach-strip` declared 3× with conflicting margin and padding.
- [ ] **P3-03** Delete the 510 confidently-dead rule blocks (**2,590 lines, 6.3%**). Verified 0/55 false positives on two random samples. **Do not touch the 349 UNCERTAIN blocks** — they are dynamically constructed.
- [ ] **P3-04** Delete duplicate `@font-face` (the whole Fira Code set is declared twice) and the 3 exact-duplicate `@keyframes`.
- [ ] **P3-05** **Fix the 2 conflicting `@keyframes` redefinitions** — `research-pulse` and `fadeIn`. These are live bugs: the later definition silently wins for every consumer, including code written against the earlier one.
- [ ] **P3-06** Collapse the 9 clone-body animations (nine names for one 360° rotation) into one.
- [ ] **P3-07** **Canonicalise breakpoints to three.** 13 distinct widths today. One 560-line block switches to mobile at 700px while 3,066 lines switch at 768px — **between those widths the UI is in a mixed state**, and there is a 20px dead zone (701–719) where an unpaired min/max leaves neither rule applying.
- [ ] **P3-08** Add paired-rule comments so a desktop rule points at its mobile override — the roadmap's own "CSS did not move" item.
- [ ] **P3-09** Delete `:root.light` (21 lines + 3 other sites) — unreachable by construction, since light themes push values through the five tokens and never add a class. **Recover the well-tuned light syntax palette inside it first.** `Verify:` the four light themes stop rendering dark native dropdowns.
- [ ] **P3-10** Delete the 3 dead modules: the RAG module (its three DOM targets exist nowhere, and two app-level call sites invoke a function it does not export), the calendar reminder poller (complete, zero callers, browser-notification path inert), and the tour autoplay module (its entire body is a "Disabled for v1 stability" comment, and it still imports a 6,500-line module for a side effect that never runs). **Two are still precached by the service worker** — update `sw.js`. `Depends:` P2-23 must land first if you want RAG's UI, else delete.
- [ ] **P3-11** Fix the duplicate module specifier — `chatRenderer.js` is imported under 3 distinct specifiers, so a 3,126-line module is parsed three times per page load. A config module's header documents the symptom and works around it; the root cause was never fixed. One-line change per import.
- [ ] **P3-12** Delete the 6 verified-dead elements and handlers: two elements killed by CSS with zero JS references, four ids appearing once in markup and nowhere in script, a handler wired to a nonexistent element, and section drag-reorder (queries a `draggable` attribute nothing ever adds).

---

# P4 · The wire — the real glass box
*Area: `wire`, `trace` · Depends: P1 · Blocks: P5*

The backend emits ~50 distinct SSE event types through a single `if/else if` chain;
anything without a branch is silently discarded. **Thirty-plus fields are computed,
serialised, sent to the browser and never read.** None of this needs backend work.

### Prerequisite — do this first
- [ ] **P4-01** **Unify the six drifted agent-thread templates into one builder.** They exist across the live path, history replay and compare mode, and **zero pairs are byte-identical**. They diverged three ways: compare mode hardcodes the fallback icon so it can never show the search glyph; one copy omits the diff block; the labels differ. **This is not a mechanical extract — you must decide which behaviour is correct and record the decision in your handoff note.** Every other P4/P5 trace task depends on this.
- [ ] **P4-02** Fix the key-name mismatch: the shell tool sends elapsed time under one name and the frontend reads another, so the displayed timer is a client-side guess rather than server truth. One rename. `Depends:` P4-01.
- [ ] **P4-03** Delete the dead handler for a skill-saved event the server never emits.

### Free — already on the wire, zero backend work
- [ ] **P4-04** **The approval card's own reason.** The server sends a written explanation naming the exact effects that tripped the gate; the renderer never reads the field. *(Style-only — see `DEFERRED.md` for the markup constraint.)*
- [ ] **P4-05** **The full fallback chain** — every model candidate tried with its HTTP status. Render `gpt-4o ✗502 → claude ✗429 → llama ✓` instead of a six-second "retrying" toast.
- [ ] **P4-06** **`failed` and `failure{status,message}` on terminal metrics.** **A failed turn currently renders identically to a successful one.** This is a correctness bug, not polish. Highest priority in P4.
- [ ] **P4-07** Per-round token buckets — round, model, endpoint, input/output tokens, cost-tracked flag. Currently summed into one cost number and discarded.
- [ ] **P4-08** Live prep breakdown — request setup, tool selection, prompt build, context trim, each timed. Replaces a static spinner label.
- [ ] **P4-09** `full_command` on every tool start — expand-to-full-arguments on the running card. The truncated version is what you see now. `Depends:` P4-01.
- [ ] **P4-10** Loop-breaker detail and the unkept-promise phrase — `"Stopped: called bash with identical arguments 15 times"` instead of a generic message.
- [ ] **P4-11** Round numbers on every step and tool event. `Depends:` P4-01.
- [ ] **P4-12** `approved: true` badge on tool events — the action you personally authorised is currently indistinguishable from a routine call. `Depends:` P4-01.
- [ ] **P4-13** Trim and compaction figures — tokens before/after, messages before/after.
- [ ] **P4-14** Real decode speed, prefill speed, time-to-first-token, context tokens — separating prefill from decode and measured from computed.
- [ ] **P4-15** `tmux_session` on long shell runs → an "attach to this session" affordance.

### Cheap — one emit line or one field
- [ ] **P4-16** **Which skills were injected** — name, source, teacher model. Up to twelve enter a request and **nothing says which**. The loop knows all of it and emits none. Highest-value gap in P4; mirrors how memories already work.
- [ ] **P4-17** The verifier's findings — a second model checks the work and its issue list is injected into the prompt, never shown.
- [ ] **P4-18** Auto-escalation and its hidden tool blocklist — "Promoted to Agent (shell and file tools withheld)". Currently silent in both directions. The flag is computed and never sent.
- [ ] **P4-19** **stderr, separated.** The model sees stdout and stderr labelled separately; the user only sees stderr when stdout is empty. Add a separate pane and the actual numeric exit code.
- [ ] **P4-20** Policy-blocked calls emit **no tool card at all** — the call vanishes and the thread's state pointer goes stale, so an approval card appears with no visible cause. Add a distinct "blocked by policy" node. `Depends:` P4-01.
- [ ] **P4-21** Approval expiry — a ten-minute TTL that is computed and never sent. Today the card silently stops working.
- [ ] **P4-22** Prompt-cache read/write tokens — extracted from the provider, written to a log line, dropped. **Cache hit ratio is the single biggest lever on real cost.**
- [ ] **P4-23** Live tool-budget and round meter — a progress bar instead of a surprise stop at the limit. The agent already streams step events.
- [ ] **P4-24** **Background sessions get none of this.** When a stream is resumed after navigating away, a second and much poorer dispatch chain collapses every tool, research and source payload to a single "this was rich" boolean. A background agent run is currently unobservable after the fact. `Depends:` P4-01.

---

# P5 · Trace & composer restyle
*Area: `trace`, `composer` · Depends: P3, P4-01*

- [ ] **P5-01** Replace the three nested 300px scrollers with a `grid-template-rows: 0fr → 1fr` transition. Long reasoning currently clips into a 300px inner scroller inside the page scroller — the worst UX defect in the trace.
- [ ] **P5-02** Give tool nodes the same open/close transition as reasoning. They hard show/hide today while a sibling inches away animates.
- [ ] **P5-03** **Stop cards renaming themselves on completion.** A node reading *Running* becomes *bash*; *Searching* becomes *web_search*. 21 tools affected, and history replay shows raw ids for all of them. Compare mode already does it right — proof it is a bug. `Depends:` P4-01.
- [ ] **P5-04** Per-tool icons — the map has **one entry** against 21 labels; everything else falls back to a triangle. Inline monochrome SVG. `Depends:` P4-01.
- [ ] **P5-05** One disclosure idiom. Two compete today: left-▶-rotate for generic details, right-▼-flip for reasoning, sources and tool output. Pick the right-side chevron and retire the global left marker.
- [ ] **P5-06** **Code block headers.** `data-lang` is already on every `<code>` and never displayed; `langIcons.js` already has the icons and is imported by two document modules and never by chat. Both halves exist and have never been connected. Moving copy/edit/run into the header also solves buttons-covering-text.
- [ ] **P5-07** Make the executed command copyable — `.agent-thread-cmd` has no highlight, no copy, no expansion, and it is the most copy-worthy string in the UI. `Depends:` P4-09.
- [ ] **P5-08** Expand-all, tool-argument pretty-printing, and copy-on-tool-output. `createCollapsible()` is the ready-made primitive — written, inheriting the delegated toggle and hash persistence, reachable from nothing.
- [ ] **P5-09** Injection disclosure as a collapsible peer of `.sources-section`, reusing that idiom verbatim so it inherits styling and behaviour. `Depends:` P4-16.
- [ ] **P5-10** Restore prose heading hierarchy. `h1`–`h6` map to keyword/function/string/builtin/variable/number — a five-heading answer renders as five hues across a 20% size range. **Keep the syntax hue on h1 and h2 only**; that pairing is the tell, the rest is noise.
- [ ] **P5-11** Fix the section-header inversion — headers are 10px/400 over 13px rows. Both sizes already exist; this is a swap.
- [ ] **P5-12** Consolidate the six hand-styled tool chips and the two bare-icon toggles into **one chip component**. Cleanest large win in the composer, and it makes the strip themeable for the first time.
- [ ] **P5-13** Icon normalisation — three sizes and one stroke token replacing 8 sizes and 9 stroke widths across 1,182 inline SVGs. A stroke-2 glyph from a 24 viewBox at 11px has an effective stroke under one pixel. **Attributes only; no SVG markup is rewritten.**
- [ ] **P5-14** Type scale — collapse 27 ad-hoc steps onto a ramp drawn from the existing values, with **11px as the floor rather than the median** (827 of 1,222 sizes are 10–12px; 118 are ≤9px).
- [ ] **P5-15** **Populate `#pinned-tools-bar`** — an empty div appearing once in the whole codebase with zero CSS and zero JS. Unclaimed composer real estate, no layout risk.
- [ ] **P5-16** Make the send button's five states legible without changing the machine. **Eight modules mutate it**; any composer rework must reproduce `newchat · mic · send · streaming(processing/receiving/queue) · recording` exactly. Note Enter-on-empty opens a new chat, and the mic state appears from a silent server capability check.

---

# P6 · Queue & Plan
*Area: `queue`, `plan` · Depends: P4-01*

- [ ] **P6-01** **Session-bind the queue — live bug.** Queue items carry no session id. Switching chats wipes the message list, destroying every queued bubble's element while the array keeps the items; when the old stream ends the prompt **fires into whichever chat is now open**, invisibly. Add the field, filter the drain on it, re-render bubbles on session switch.
- [ ] **P6-02** Persist the queue. `_queuedAgentRequests` is a bare module array — a reload loses it silently.
- [ ] **P6-03** Allow queueing with attachments — currently refused with an error that swallows the send.
- [ ] **P6-04** Build the queue panel: drag-reorder, edit in place, per-item mode/model/trust rung, start-now force bypass, pause, remove. **Clone the research job engine** (382 self-contained lines) rather than writing a new one — only two lines are research-specific.
- [ ] **P6-05** Adopt the shipped status vocabulary: `queued → running → success | error | skipped | aborted`. `skipped` and `aborted` are load-bearing — `aborted` keeps infrastructure events out of error-rate stats.
- [ ] **P6-06** Sequential-vs-parallel picker. **Already built** in the research panel — reuse it. Parallel must allocate a session per item: one agent run per session is enforced.
- [ ] **P6-07** Point the existing Tasks activity view at queue items rather than building a second queue UI. It already renders every status with shared elapsed timers, a force button and a stop button.
- [ ] **P6-08** Make `_concurrency_cap` actually configurable — it sits next to `Semaphore(1)` and is documented as "a hard guarantee, not configurable".
- [ ] **P6-09** Rewrite the todo "solve with an agent" button to enqueue instead of firing an unbounded raw stream. **Click ten todos and ten agent loops run at once**, with no progress and no cancel.
- [ ] **P6-10** Expose `crew_member_id` in the task create/update schemas and the `manage_tasks` tool. It is read-only today and honoured by the executor — **this one field closes the roadmap's "todos assignable to an agent from the UI" item at the API layer.**
- [ ] **P6-11** **Build the docked plan window.** Three prompt strings tell the model it exists and a code comment claims it renders. **Nothing has ever rendered it** — mid-execution `update_plan` writes to browser storage with zero visible effect, and the prompt is telling the model something false about its own interface. Structured steps with per-step status, bound tool, effect, elapsed and result.
- [ ] **P6-12** Give plan mode a real entry control. The toggle button resolves to nothing — the element does not exist; entry is Tab-in-composer or a mobile swipe, and the status pill can only turn it **off**. Its CSS is written and dead. **Do not use the three-up mode toggle** — it belongs to the model-serving panel.
- [ ] **P6-13** Add a step model with ids. A plan is an opaque markdown string everywhere — storage, form field, prompt, tool argument — and progress is computed by counting ticked boxes in that string. `Depends:` P6-11.
- [ ] **P6-14** **Let planning mode ask a question.** The clarifying-question tool is absent from the read-only allowlist, so the gate blocks it. A planning mode that cannot ask what you meant is planning blind.
- [ ] **P6-15** **Pass the plan to the verifier.** It judges against the last user message, which during plan execution is literally the string *"Execute the approved plan"* — naming no deliverables. **The verifier is blind for the entire run.** One line.
- [ ] **P6-16** Guard the narrating-without-acting supervisor against plan mode, where narrating **is** the job. One line.
- [ ] **P6-17** Render the agent's own todo list. A structured todo tool exists, persists to disk, is instructed for multi-step work, and **has no renderer** — it surfaces only as raw tool output text.

---

# P7 · Trust ladder & control plane
*Area: `trust` · Depends: P4*

The approval store is better than anything that would replace it. Do not rebuild it.

- [ ] **P7-01** **Stop the mode toggle lying.** A 60-word keyword regex — including *change, update, review, test, run, build, source, system, device, app* — silently promotes Chat to Agent, and 35 lines later a single line **overwrites the user's own shell toggle to true**. The backend escalates again on tool intent, search and web intent, computes an escalation flag, and never sends it. `Depends:` P4-18.
- [ ] **P7-02** Stop the model raising its own trust level — it can currently flip the mode toggle through a UI-control event with no confirmation.
- [ ] **P7-03** Add rung **"ask every time"**. Does not exist: the gate is conditional on untrusted content having entered, so a clean session never prompts. Change the gate condition from *taint seen* to *taint seen **or** the current rung requires confirmation*. **Reuse `PendingToolApproval` unchanged.**
- [ ] **P7-04** Add rung **"allow-listed"** — a rule store mapping tool + argument pattern to auto-allow, consulted before the blocked-effect check. Does not exist.
- [ ] **P7-05** Record the correction in the UI: **Auto-Pilot is already the default** for every untainted conversation. The ladder is added *below* current behaviour, not above it.
- [ ] **P7-06** Rank prompts by effect. A destructive action and a UI side effect produce an identical card. The 13-value taxonomy is written and used to rank nothing.
- [ ] **P7-07** Send only the effects that actually **tripped** the gate, not all of them — and surface the unrecognised-tool case, which is the riskiest and currently invisible.
- [ ] **P7-08** **Surface the taint trail.** The security context builds a complete list of which tools introduced untrusted content into a run, and it is read **nowhere** — server or client. Built in memory and thrown away.
- [ ] **P7-09** Grant inspector — once a session-wide grant is given, nothing lists it and nothing revokes it.
- [ ] **P7-10** Surface run limits at the moment of decision. "How far can it run unattended" sits in a settings tab, invisible when you choose. `Depends:` P4-23.
- [ ] **P7-11** Real file export — Markdown, JSON, HTML download. PDF is `window.print()`, which cannot run headless or be scheduled. Nothing exports the approval trail at all.

---

# P8 · The Workshop
*Area: `skills`, `automations`, `mcp` · Depends: P1*

Three authoring surfaces over three engines that already run.

### Skill Crafter
- [ ] **P8-01** **Add the five phantom inputs** — `#new-skill-name`, `-description`, `-when`, `-procedure`, `-category`. The handler already reads them, they are in the clear-on-success list, and one has an Enter binding. **Zero JavaScript change.** Do this first; it is the cheapest win in the whole roadmap.
- [ ] **P8-02** Add pitfalls, verification, platforms and required-toolsets inputs. All four are supported by the API and reachable from nowhere — **half the structure of every hand-written skill is currently unusable.**
- [ ] **P8-03** Relabel "draft". A draft is excluded from the catalogue the model browses and **still keyword-injected** when it matches — "uncatalogued", not "inactive".
- [ ] **P8-04** Fix the confidence-slider trap: maximum position stores **zero**, labelled "All", which disables the gate entirely. Dragging right is "let everything in", not "only perfect skills".
- [ ] **P8-05** Surface the hidden coupling: turning auto-approve off sets the injection floor to 2.0, silently making injection published-only.
- [ ] **P8-06** **Prompt preview** — call `GET /api/skills/index`, which exists to answer exactly this and **no frontend file has ever called**. Extract the injection renderer into a shared function so the preview is the truth, not a re-implementation.
- [ ] **P8-07** Show what the preview reveals: **verification and body text are never injected.** They surface only through an on-demand view action.
- [ ] **P8-08** Wire the test's `task` field — the endpoint has accepted a user task all along and the UI has never sent one. One textarea.
- [ ] **P8-09** **Before/after behaviour diff.** The runner is parameterised on arbitrary markdown *and* an arbitrary task and never reads from disk — call it twice with old and new against the same task. `Depends:` P8-08, P8-10.
- [ ] **P8-10** **Versioning.** Every write overwrites in place and the audit rewrites destructively with no copy kept; the version field is decorative and never bumped. A skill is a *directory* — a `versions/` sibling costs one line in the writer, and the rewrite path still holds the old markdown in a local when it writes the new one.
- [ ] **P8-11** Rollback from a version. `Depends:` P8-10.
- [ ] **P8-12** Pre-save lint — the necessity and retrieval-precision judges are pure functions of `(skill, siblings)`, already run nightly, callable with no refactor.
- [ ] **P8-13** "Improve this draft" — the existing rewrite prompt with a synthetic verdict, a trick the audit itself already uses to force a metadata-only fix.
- [ ] **P8-14** "Draft from my last session" — retarget the teacher's skill-from-trace prompt, which already emits the full modern schema, from a failure trace to a user description.
- [ ] **P8-15** Surface duplicate overlap at authoring time. Similarity is already computed client-side for a badge and server-side at audit — neither runs when you type. Note hand-written skills post a source value that **exempts them from creation-time dedup**.
- [ ] **P8-16** Single-skill export — `read_skill_md` plus a directory walk, ~20 lines. Unlocks share, backup and rollback-by-hand.
- [ ] **P8-17** Fix the extractor's output schema — it still writes the old shape and never populates pitfalls, verification, category or when-to-use. Everything it makes is structurally impoverished relative to what the schema supports.
- [ ] **P8-18** Say that injecting a skill raises the security posture — skills arrive as untrusted context, which arms the approval gate. Correct behaviour, completely invisible, and the reason a skill test can pause mid-run.
- [ ] **P8-19** Add an mtime-keyed cache to the skills manager before any live-preview UI. Every read is an `os.walk` parsing every file, on every request that injects skills. `Depends:` P8-06.
- [ ] **P8-20** *(Stretch)* Vector-index skills. Retrieval is Jaccard overlap against the last user message only — no embeddings, no conversation context. **Memories are already vector-indexed; skills are not.** Same template, unapplied.
- [ ] **P8-21** *(Stretch)* Budget the index. It costs ~15 tokens per published skill on **every single request** and participates in no budget. Also: the usage counter records *retrievals*, not successes, so "most-used" measures keyword luck.

### Automations
- [ ] **P8-22** Node palette endpoint — merge the three `/meta/*` routes, move the client-side category/icon taxonomy server-side, emit param schemas and a `model_backed` flag (currently maintained twice: once to gate the semaphore, once to draw a badge).
- [ ] **P8-23** **Give triggers payloads.** The event bus takes a name and an owner — a "document created" trigger cannot say *which* document. The webhook route has **no request parameter**: body, query and headers are read by nobody. It is a doorbell. **Highest-leverage change in Automations; everything downstream depends on it.** Do not change the webhook URL shape — it is CI-pinned.
- [ ] **P8-24** Widen the node output contract from `(text, success)` to `(payload, status)` with a back-compat adapter for the 18 existing actions. The no-op and defer-with-backoff signals already encode skip and retry — generalise them.
- [ ] **P8-25** **Write `TaskRun.steps`** — declared, migrated, never written. A run records one result string for the whole task. Filling it upgrades the shipped activity view instantly with no new UI.
- [ ] **P8-26** Add the graph document. One nullable successor today; the cycle check doubles as a **silent depth cap of ten**. Project the existing successor as a single edge on read.
- [ ] **P8-27** Run-scoped execution identity — the current one is keyed by task, so a task cannot be in flight twice. Required before fan-out. `Depends:` P8-26.
- [ ] **P8-28** Branch node — the only conditional in the engine is `status == "success"`. `Depends:` P8-26.
- [ ] **P8-29** Data mapping between nodes. `Depends:` P8-23, P8-24.
- [ ] **P8-30** Collapse the three parallel event catalogues into one registry, and **add `document_updated`** — it is fired in production and appears in neither catalogue, so nothing can trigger on it.
- [ ] **P8-31** Default a user-built automation's event count to 1. The UI defaults to 5; anyone arriving from a workflow tool expects every event.
- [ ] **P8-32** Per-task timezone, retries, and a per-task timeout — none exist. Timezone today comes only via a crew member.
- [ ] **P8-33** A dry run that is actually dry. "Run now" is a real run with real side effects — no mocking, no pinned input, no per-node execution.
- [ ] **P8-34** The canvas, last, against a stable API. **Ship a Mermaid rendering of a workflow first** — it is already vendored and wired, works today, and needs no graph library. `Depends:` P8-22, P8-25, P8-26.

### MCP Creator
- [ ] **P8-35** **An update endpoint — the structural blocker.** The only mutation is an enable/disable toggle; editing a command means delete-and-recreate, which mints a new id and **orphans every stored `mcp__<id>__<tool>` reference**, including the server's own disabled-tool list and any scheduled task pointing at one. Iterate-and-refine is impossible until this exists.
- [ ] **P8-36** Test-call endpoint — no route invokes a tool; the manager's call method is public with a normalised envelope. ~15 lines behind an admin check.
- [ ] **P8-37** **Add a timeout to the MCP call path — there is none.** A hung tool hangs the agent turn indefinitely. Do this in the same change as P8-36.
- [ ] **P8-38** Keep the handshake. The initialize result is discarded at exactly three connect sites; it carries server name and version, protocol version, advertised capabilities and the server's own instructions, and **nothing in the app records any of it.** One line each.
- [ ] **P8-39** **Encrypt server env vars.** Every other secret in the schema is encrypted at rest; this one is plain text, and it is where the tokens live. The CLI already redacts on read behind a reveal flag. Storage migration only — no wire or JSON shape changes. **Do this before a Creator multiplies the rows holding them.**
- [ ] **P8-40** Capture `annotations` on the HTTP transport — stdio and SSE both do, HTTP does not, so a remote server gets no plan-mode read-only credit however it advertises itself.
- [ ] **P8-41** Fix three stale comments claiming MCP is dropped in plan mode. It is not — read-only tools are kept via annotations with a fail-closed verb heuristic.
- [ ] **P8-42** Fix the empty-env trap: an empty env dict yields `None`, so the SDK substitutes a minimal environment instead of inheriting the parent's. A generated server relying on inherited `PATH`/`HOME` starts on a fresh install and fails on a bare one.
- [ ] **P8-43** Let `builtin_browser` auto-reconnect — the reconnect helper hard-returns false for anything outside a four-entry map, despite the browser server counting as built-in. A crashed Playwright server stays dead until a manual reconnect.
- [ ] **P8-44** Server-id validation. One `split("__", 2)` is the sole parse of the namespaced name; **an id containing `__` routes the call to the wrong server.** Unreachable today because ids are uuid4-derived — the moment a Creator lets people name servers, this field holds the invariant.
- [ ] **P8-45** Surface the 23-entry preset catalogue (14 with setup walkthroughs) currently sitting in ~400 lines of unreachable code. Its two entry points look up DOM ids no template has ever rendered. `Depends:` P2-20.
- [ ] **P8-46** Replace the single-line JSON inputs — a parse failure is caught and **silently discarded**, posting empty args and env, after which the server fails to connect for a reason nothing explains.
- [ ] **P8-47** Scaffold generator, writing to the **data volume** — the source tree is baked into the image with no bind mount, so generated servers cannot be built-ins and must register as ordinary rows with an absolute path. **That path is denied on the agent's registration path by design.** Author here; register through the admin route. **Do not weaken the command validation** — it closes a reported RCE and is pinned by 10 tests.
- [ ] **P8-48** Tool schema editor + `readOnlyHint` / `destructiveHint` annotation UI. The schema is already carried end-to-end and nothing edits it; `manage_mcp list_tools` drops it entirely, so the LLM cannot see a tool's parameters through its own tool.

---

# P9 · Feature surfaces
*Area: `surfaces` · Depends: P5*

- [ ] **P9-01** **Command palette**, framed as extending the existing search rather than a parallel component. Every data source is already a registry: slash commands, settings panels with keywords, the modal auto-wire map, the route table. **`#search-overlay`, `#search-input` and `#search-results` must stay in the DOM** — five call sites including the rail button and `/find`.
- [ ] **P9-02** Render the settings nav from its own registry. Two sources of truth for one information architecture; the registry was built for this and is consumed only by search. **Keep the class name and data attribute identical** — four modules query them. There is also a `getSettingsRegistryIssues()` self-check that diffs registry against DOM — run it while you work.
- [ ] **P9-03** Unify the library. Chats, Documents, Research and Archive are already tabs of one modal; make it *the* library with Gallery and Email as facets, and settle the three names for one thing (`rail-archive` labelled "Library", `rail-documents` labelled "Docs", modal id `doclib`).
- [ ] **P9-04** Consolidate email settings — they live in three places. Highest-priority IA fix. **Keep compose-in-document-editor** (it is why AI drafting works); present it as a composer.
- [ ] **P9-05** Full views for Calendar and Compare — a month grid and an N-way comparison inside ~780px draggable boxes. **Compare deliberately shows/hides the original container's children rather than replacing markup**, so listeners on the input bar and mode toggle survive; any rework must honour that.
- [ ] **P9-06** Promote Skills out of the Brain modal — different object, different lifecycle (draft → audit → publish). `Depends:` P8-01.
- [ ] **P9-07** **Empty states.** A named roadmap item, and **not one empty state exists anywhere.** Include the cookbook's, which should show the actual command and output instead of "crashed".
- [ ] **P9-08** Honest error messages, same lane. `Depends:` P9-07.
- [ ] **P9-09** Provenance on everything the model produced — memories, skills, tidy results, research reports, calendar parses, generated images. Chat bubbles show it; nothing else does. The formatter already exists.
- [ ] **P9-10** Preview before destructive AI operations. **Chat tidy deletes sessions *and* re-folders them with no preview at all**; memory tidy has an animation, not a reviewable diff. Calendar has a real undo stack and is the only surface that does — proof it is solvable here.
- [ ] **P9-11** Make background work visible with its window closed — skills audit, research jobs, cookbook downloads, memory tidy and email sync all report into windows the user has closed. **Extend the minimized-dock chips**, which already carry per-window status; email writes an unread label onto its own.
- [ ] **P9-12** Fix "non-passing" in the skills bulk delete — it currently catches **never-audited** skills, so a brand-new hand-written skill counts as failing. Add an undo path. `Depends:` P8-10.
- [ ] **P9-13** Surface the theme zone highlighter — hovering a colour picker outlines the element it controls on the live page behind the modal. **The best explainability feature in the app**, with no label, legend or hint that it exists. The map is keyed by picker id, so extending it is a data edit.
- [ ] **P9-14** Add the selection count to the bulk bar — it is computed and never rendered — and stop looping bulk archive/delete one row at a time with no progress and no partial-failure reporting.

---

# P10 · Accessibility & release
*Area: `a11y`, `release` · Depends: P1, P5*

The accessibility pass is the upstream roadmap's own item, unclaimed, and historically
the only lane through which the theme file gets touched.

- [ ] **P10-01** One focus ring through `:focus-visible`. **97 `outline:none` suppressions** against 35 `:focus-visible` rules and six competing ring styles. The a11y shim's own header notes the ring already exists and never fired because rows were never focusable. Most suppressions can then be deleted.
- [ ] **P10-02** Author sidebar rows as real buttons. **Keep `.list-item`** — the a11y shim and the drag-sort module both query it, and rows *contain* nested buttons, which is exactly why the shim declines `role="button"` on them. **Change the tag, not the class.**
- [ ] **P10-03** Make both resize handles visible and keyboard-reachable. They are mouse-only and invisible because their entire treatment routes through the accent token. `Depends:` P1-01.
- [ ] **P10-04** Contrast audit across all 16 themes with the guard from P1-09 enforcing it. `Depends:` P1-09.
- [ ] **P10-05** Verify the reduced-motion guard covers all 148 keyframes and the 7 canvas animators. `Depends:` P1-12.
- [ ] **P10-06** Keyboard navigation pass over the rail, the sidebar, the composer, the window system and the Workshop.
- [ ] **P10-07** Give the loader a stage line so boot is not silent, move it off `innerHTML`-per-frame, and add a reduced-motion guard. **Keep the wave.**
- [ ] **P10-08** Any new modal needs its own `ui-scale-125` height compensation — otherwise zoom pushes the draggable header and close button off-screen, and you cannot reach the control to turn the size back down.
- [ ] **P10-09** Rebuild, redeploy, bump the cache-buster, verify in-container imports. **`static/` has no bind mount.**
- [ ] **P10-10** Full regression: `pytest -q`, `py_compile` across app/routes/src, `node --check` across every touched module, and a manual pass over every surface in the mockup.
- [ ] **P10-11** Run the `SECURITY.md` fork checklist before the first public push — `git status --short`, the ignore check, and the secret grep.
- [ ] **P10-12** Write the release notes. Lead with the Odysseus credit. Enumerate the breaking renames: env vars, storage keys, vector collections, cookie, CLI scripts, systemd unit, bundle id.

---

# Deferred

- **D-01 · The approval card's new markup.** Effect chips, fingerprint badge, expiry countdown, taint trail. Two CI tests assert literal source strings from that file and the upstream cluster around it is the hottest code in the project — 15 commits in 4 weeks, a revert inside the most recent PR. **Style through existing selectors only; add no markup.** Revisit when the upstream commits stop landing daily. *(P4-04 and P7-06/07/08 are the style-only subset and can proceed.)*
- **D-02 · Container station.** See `FRONTIER-NOTES.md`. The strongest framing is as the sandbox the threat model says does not exist, not as a deploy feature. ~70% of the machinery is in Cookbook.
- **D-03 · VM station.** Held. If the need proves real, wire to Proxmox or libvirt through an MCP server rather than building a hypervisor. `Depends:` P8 complete.

---

# Bugs found during implementation

*Agents append here. Format: `- [ ] **B01** … — found during P4-07 — agent:`id``*

---

**Provenance.** Every task traces to a row in the Elevation Ledger. Six audit passes,
one adversarial. Two claims were caught wrong and corrected; assume more remain and
verify against the source before implementing. See `AGENTS.md` rule 3.
