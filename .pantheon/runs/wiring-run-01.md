Verification complete. Writing up.

## The number

**78 → 2.**

```
lookups 892  ·  in markup 211  ·  made at runtime 679  ·  UNRESOLVED 2
    1  adv-*   adv-
    1  cmp-*   cmp-history-0
```

The remaining two are **checker artifacts, not drift** — three reviewers reached this independently:

- **`adv-`** — a truncation of `getElementById('adv-' + key)` at seven sites in `theme.js` (`:518, :777, :849, :908, :988, :1003, :1083`). Never an id. All 14 `ADV_KEYS` now have markup; the last gap (`adv-brandMixTo`) was closed this run.
- **`cmp-history-0`** — the element *is* built, at `compare/index.js:457` and `panes.js:423/517`, as `'cmp-history-' + i`. The checker's `made` regex `[A-Za-z0-9_-]+` stops at the closing quote and banks `cmp-history-`, so the literal never matches. 22 sibling sites are invisible the same way.

Neither can be closed without editing `.pantheon/check-wiring.py`, which is off-limits.

**I applied three fragments the markup agent skipped.** It read `stands: false` as "refuted, skip" — but in the challenge schema `stands: false` means *the reviewer's challenge failed*, i.e. the fragment survived scrutiny cleanly. It skipped exactly the three best-validated fragments and applied the five that had *actual* defects (correcting for them). That inversion accounted for 8 of the 10 remaining ids.

## Deleted

| id | evidence it was dead |
|---|---|
| `doc-close-btn`, `doc-footer-close-btn` | Removal notes in-source at `document.js:4883`/`:5038`, verified verbatim at HEAD. `closePanel`/`closeTab` retain 2 and 3 live surfaces |
| `doc-import-btn` | Import is the first unconditional push in `showExportMenu`; anchor `#doc-footer-export-btn` is real |
| `doc-email-attach-btn` | `#md-toolbar-attach-btn` calls the identical `_showComposeAttachMenu`, and lacks `.md-toolbar-email-hide` so it survives the email sweep |
| `doc-language-icon` | `_initLangPicker()` unconditionally `.remove()`d it at init — markup was never an option |
| `doc-overflow-wrapper/-toggle/-menu` (120 lines) | `git grep initActionOverflow HEAD` → one hit, its own definition. And `_syncOverflow = syncOverflow` at HEAD:6829 is an undeclared assignment: ReferenceError under module strict mode, so it provably never completed. The identically-named *class* is live and untouched |
| `doc-suggestions-container` | One card at a time via `card.id='doc-suggestion-active'` + `body.appendChild`. All three uses were `if (container)` no-ops |
| `md-toolbar-undo` | `#doc-undo-btn`'s handler is a strict superset (PDF undo + focus + execCommand + mobile-kb dismiss) |
| `doclib-bulk-delete/-export/-archive/-clone` | The code's own comment: "Legacy per-action buttons no longer rendered". `#doclib-bulk-actions` menu wires all four to the same functions |
| `cookbook-download-card-toggle/-body` | `#cookbook-dl-tab-fold` + `_setFolded` is live in the same function. Retargeting would have **double-bound** the same `h2` |
| `cookbook-ollama-toggle/-arrow/-list/-refresh` (77 lines) | Two independent first-party removal notes; Engine=ollama filter covers it. Route left alone — still called by `_ensureOllamaLib` |
| `cookbook-rebuild-engine` | Moved into the `llama_cpp` dep-row menu; `_rebuildLlamaCpp` does the server-selection step itself at its own first two lines |
| `hwfit-cache-dir` | Data model moved singular `modelDir` → plural `modelDirs`; a single input cannot represent it |
| `hwfit-host` | **Write-only binding** — assigned, never read. Strongest proof in the run |
| `hwfit-rescan` | `_refreshScanDownloadTarget` is a strict superset (`allSettled([_hwfitFetch(true), _fetchCachedModels(true)])`) |
| `ge-ai-model`, `ge-resize-menu(-btn)`, `ge-topbar-mask-color`, `ge-wand-rembg` | All behind permanently-null guards; each has a live replacement surface |
| `email-list`, `email-load-more`, `email-folder-select` | `loadEmails`/`loadFolders` had **zero callers tree-wide**; `#email-section` in markup is title + compose + unread-dot only |
| `message-input` | Second operand of a `\|\|` whose first operand (`#message`) always resolves |
| `gallery-edit-btn` | `#gallery-edit-direct-btn` already binds the *same* `_openInEditor` — retargeting would double-bind |
| `gallery-toolbar-more-btn/-menu` | Zero markup, zero CSS; its one action lives in the Settings card |
| `models` (565 lines), `openai-model` | `if (!box) return;` on an id absent from HEAD *and* upstream `/work/base`. Three working UIs already cover it |
| `mobile-new-chat-btn` | `index.html:723` reads verbatim: `<!-- new session button removed — use + in send button instead -->` |
| `save-as-template-btn`, `open-theme-btn`, `chat-new-btn`, `session-select-btn`, `task-preset-cancel` | No markup, no CSS, live replacement in each case |

## Fixed (renames)

| stale id | real id | why it was a bug, not cosmetics |
|---|---|---|
| `ge-controls` → `.ge-controls` | class, never an id (`right-panel.js:35`) | The add-site used the class handle, the remove-site the id handle — so `ge-inpaint-popover-host` was **never removed** on close |
| `email-attachments-btn` → `email-attach-btn` | `emailLibrary.js:2656` | Filter reset left the pill visually `.active` |
| `submit` → `.send-btn` | the button has **no id** | Tab-recovery called `updateSubmitButton('idle')`, which bailed at `if (!submitBtn) return;` — button stuck in stop/streaming state after recovery |
| `tool-settings-btn` → `user-bar-settings` | opener moved to the user bar | `/tour settings` opened nothing |
| `tasks-btn` → `tool-tasks-btn` | `#tools-section` | Deep-link to a task silently died on chunk-load failure |
| `cookbook-download-card-arrow` → `-dl-tab-fold*` | `cookbook.js:2930/2932` | Filling a hidden input swallowed the click |
| `toolbar.js?v=20260827upscale1` → `?v=20260708sam3` | **my revert** — see Refuted |

## Wired

| id | what it now does |
|---|---|
| `doc-pdf-ai-fill-btn` | Runs `_aiFillAnnotations()` → `POST /api/document/{id}/ai-fill-annotations`. Textbook Law 13: complete frontend, complete route, zero callers. Text-only on purpose — the handler does `btn.textContent = 'Thinking…'` then restores `'AI fill'`, which would destroy an SVG child |
| `doclib-archived-btn`, `doclib-research-archived-btn` | `_libraryArchivedView` / `_researchArchivedView` were written in exactly one place each — inside these missing buttons' handlers. Archiving was a **one-way trip**; the backends supported retrieval all along |
| `ge-upscale-section/-2x/-4x/-ai` | Section + resamples + Real-ESRGAN. `_runExistingButton('ge-upscale-ai')` was reachable from a shipped Quick Edit chip and fell through to "That edit is not available" |
| `ge-image-action-fill` | `_doFillSelection`. Placed at the *preferred* spot (after Canvas…, before the Transform label) — the fragment's own `position: inside-start` would have filed "Canvas…" under a Selection heading |
| `new-skill-{name,description,when,procedure,category}` | Every hand-made skill was written with `description == name` (the value the model reads when choosing a skill) and category permanently `general` |
| `rag-upload-zone`, `rag-file-input`, `docs-view` | The exact Law 13 incident AGENTS.md quotes: a RAG module called on every startup that bails on a missing element |
| `adv-brandMixTo` | + the required `style.css:2028` consumer. Markup alone would set a token zero rules read |
| **`ge-edge-wrap/-menu-btn/-menu/-width/-feather/-delete`** | **applied by me.** `edge-feather.js` is a complete two-pass chamfer distance transform with distinct fade and hard-delete branches. Hard-delete exists on no other surface |
| **`create-persistent-chat-btn`** | **applied by me.** Sole writer of `pantheon-char-sessions`; without it `onSessionSwitch`/`isPersistentChat`/`removePersistentChat` — consumed from three sites in `sessions.js` — were unreachable |
| **`doc-indicator-btn`** | **applied by me.** Fixes a live bug: `document.js:197` does `btn.style.display = hasDocs ? 'none' : ''` on `#overflow-doc-btn`, assuming the indicator shows outside. The doc toggle **vanished entirely** once a session had documents |

## Refuted

**One serious verdict. The reviewer was right — FIXED.**

`gallery-editor` bumped `galleryEditor.js:57` to `toolbar.js?v=20260827upscale1` while `sw.js:114` still precached `?v=20260708sam3`. Reviewer called it undisclosed, unforced, and internally inconsistent (sibling files edited in the same batch kept their busters), and noted JS is network-first so no bump was needed for freshness.

It was not theoretical — **CI caught it**: `test_panel_loader_js.py::test_every_lazy_editor_module_is_precached_for_offline_use` failed with exactly that URL. Reverted to `?v=20260708sam3`; test green.

**Four serious verdicts on `skills-and-rag` — reviewer right, and the markup agent had already handled three.** All three fragments named an anchor that was not a sibling of the insertion point (`skills-count` is a `<span>` *inside* the Skills button; `skills-list` is *inside* the Skills panel's `.admin-card`; `new-skill-title` is the `<input>`, not its wrapper). Applied literally that gives a nested-interactive tab, a panel invisible in every state, and a mis-centred overlay hint. I verified the shipped HTML: RAG tab is a sibling in `.memory-tabs`, RAG panel is a sibling at 8-space indent, the five skill wrappers precede `#new-skill-title`'s wrapper. Correct.

The fourth — **`BATCH:add-skill-card-duplication`** — was still open. **FIXED by me.** Nine visible inputs, four duplicated pairs. Applied the fix all three parties converged on: `hidden` on the three legacy `.skill-ph-wrap` wrappers, plus reworded the lead-in `<p>`. Removes nothing — ids, elements and the `||` chain intact. Verified no display trap: `.skill-ph-wrap { position: relative; }` declares no display, so UA `[hidden]` applies. No test pins any of it.

**One confirmed regression nobody owned — FIXED by me.** `models.js` deleted `refreshProviders`; `app.js:4344` still called it. Graded cosmetic (swallowed by a try/catch into one console warning per boot) but the tree was strictly worse than before the edit. Removed the call; zero `refreshProviders` references remain.

**Reviewers were right to stop nothing else.** Refutation failed on all six batches for the classifications themselves. The genuinely valuable catches were process, not code: the false CRLF verification claim on `documentLibrary.js` (the file is pure LF and always was), systematic stale line citations in `forge`, and asymmetric evidence standards — `email-and-gallery` used "zero CSS rules" as affirmative proof of deadness for the gallery ids while `.email-list`/`.email-item`/`.email-avatar` styling *does* exist. The email call still holds (no host element in markup, section header deliberately rewired to `openEmailLibrary()`), but the reviewer was right that the standard should have been applied both ways.

## Still unsure

- **`wire-topbar-menus.js:108`** — `else if (action === 'selection') getElementById('ge-edge-menu-btn')?.click();`. Now that I applied the edge cluster this resolves to a real button, but no menu item carries `data-image-action="selection"`, so nothing triggers it. The agent deliberately declined to add one: `#ge-edge-wrap` is selection-gated, so an always-visible item would open a dropdown anchored to a hidden wrapper. **Settled by:** either add the item *and* un-gate the wrap, or drop the branch. A judgement call, not a lookup.
- **`modalManager.js:1417`** — `'settings-modal': { rail: null, sidebar: 'tool-settings-btn' }` still names the dead id. A map value, not a `getElementById`, so the metric never counted it. Left it: not required, and it is the same rename I already made in `slashCommands.js`. **Settled by:** one-line change to `'user-bar-settings'`.
- **`/api/providers`** — `model_routes.py:1906` comments "It's fetched on every page load". It never was; the guard sat above the fetch. Now zero frontend callers. Law 1 says don't delete the route. **Settled by:** a decision about what the endpoint is for.
- **`index.html:74` FOUC `advMap`** — a third copy of the theme key map, drifted from `ADV_KEYS` in both directions (still missing `hamburgerColor`; carries `sectionAccent`, `toggleBg`, `accentPrimary`, `accentError` which `ADV_KEYS` lacks). `brandMixTo` was added. **Settled by:** deciding whether the extra four are live tokens or fossils — that is a removal, so it needs an owner.
- **Orphaned CSS** — `.doc-close-btn`, `#doc-language-icon`, `.doc-overflow-toggle`, `.hwfit-toolbar .hwfit-host`, `.ge-resize-*`, `.ge-topbar-mask-color*`, `.chat-new-btn`, `.mobile-new-chat-btn`, `~30 .models-row` selectors, the `.email-*` inbox block. **Two traps for whoever sweeps:** `#doc-actions-footer #doc-footer-close-btn` (13338/13341) is *comma-grouped* with `#doc-actions-footer #doc-undo-btn`, which is alive — edit the selector, don't delete the line. And `.doc-overflow-menu`/`.doc-overflow-item` are live classes despite the dead id of the same name.
- **`.pantheon/check-wiring.py`** carries an uncommitted 6-line SIGPIPE guard that four batches disclaimed and nobody claimed. I read it: `signal.signal(SIGPIPE, SIG_DFL)` inside `__main__` only, no counting logic touched. Numbers are honest. Authorship unresolvable from an uncommitted worktree.

## Suite

**44 failed, 5742 passed, 6 skipped — dead level with baseline.**

The intermediate state was 45/5741: `test_panel_loader_js.py::test_every_lazy_editor_module_is_precached_for_offline_use`, the cache-buster regression above. After the revert, and after all my other edits, re-ran clean at 44/5742/6.

The five ignored files fail on missing `nh3` and always have. `node --check` passes on all 27 changed `.js` files. `index.html` parses (2512 start tags). `topbar.js` is 152/152 CRLF, zero bare LF. Every new id appears exactly once.

**Q6 — two batches touching one file: none.** All 30 changed files partition cleanly across the six batches, and the near-miss is only nominal (`gallery-editor` owns `galleryEditor.js`; `email-and-gallery` owns `gallery.js`). Multi-writer files are all mine: `index.html` and `editor/build/topbar.js` (markup agent + me), `galleryEditor.js` (gallery-editor + my revert), `app.js` (me only).

## New ceiling

```
python3 .pantheon/check-wiring.py --max 2
```

**2** is the floor, not a target — both remaining entries are dynamic-lookup artifacts of the checker's own regex, and the script's docstring already concedes this ("Dynamic lookups built from variables are invisible to this and always will be"). Do not chase them; reaching 0 requires editing the checker.

**Blocking before deploy, not done here:** the cache-buster. `sw.js` `CACHE_NAME` is still `pantheon-v380-…` with 28 static assets changed beneath it, and the shared approval string `20260815approvalsave1` (18 occurrences, pinned across ten paths by `test_external_context_tool_gate.py:1326`) is unbumped. Every batch correctly declined to touch it — six agents bumping one string is the Law 11 failure mode. It needs **one serial pass**. Nothing is committed.