## Landed

- **P2-01** — upload type blocklist deleted whole; only surviving mention is the rationale comment at `src/upload_handler.py:1246` (no `is_safe_file_type`, no `dangerous_types`/`dangerous_extensions` anywhere in the file).
- **P2-02** — upload CSP sandbox branch added to the middleware, `core/middleware.py:106` (`is_upload` flag) → `core/middleware.py:138` (`elif is_upload:`), 46 insertions / 0 deletions, three pre-existing branches byte-identical.
- **P2-03** — four dead config blocks gone; `src/config.py:34` and `:103` hold the NOTEs where the allowlist and the two blocklists were. `hasattr(config.data,'allowed_extensions')` is False, module-scope `validate_config()→create_directories()` still fires.
- **P2-04** — `validate_file_upload` deleted, NOTE at `src/chat_helpers.py:226`; live cap coverage retained via `UploadHandler.save_upload` in `tests/test_chat_upload_limit_config.py`.
- **P2-06** — `_is_text_file` 10→28 suffixes at `src/document_processor.py:45`, `.htm` added to `language_map` `:55` and `code_extensions` `:120`. I reproduced the fix: `.xml .yml .yaml .sql .bash .go .rs .php .rb .jsx .tsx` previously reached the model as a bare `[Attached document file]` banner and now render fenced.
- **P2-07** — text-decode fallback for email attachments, `routes/email_routes.py:3728` (`_looks_like_text`) called at `:3754`, ahead of the unchanged rejection at `:3762`. Backend only — see *Needs a human decision*.
- **P2-11** — `MAX_FILES_PER_REQUEST = 25` at `src/upload_handler.py:227`, enforced pre-loop at `routes/upload_routes.py:274`; partial-write hazard fixed via the `rejected` list at `routes/upload_routes.py:282`/`:358`.
- **P2-15** — self-contradicting bash prompt fixed, `src/agent_loop.py:574`; repo-wide grep now shows 10 heredoc-ban sites and 0 instruction sites.
- **P2-16** — `privilege_denied_message` at `src/auth_helpers.py:127`, called at `:173`; hardcoded twin fixed at `routes/research/research_routes.py:505`. Fail-open `privs.get(key, True)` at `:172` untouched.
- **P2-17** — `BACKUP_IMPORT_MAX_BYTES` at `routes/backup_routes.py:26`, enforced at `:134` *after* `require_admin` at `:131`.

## Needs a fix

1. **P2-17 env override is inert in production.** `PANTHEON_BACKUP_IMPORT_MAX_BYTES` appears in **no** compose file, not in `.env.example`, not in `docs/setup.md` — I checked; every one of its seven siblings (e.g. `PANTHEON_MEMORY_IMPORT_MAX_BYTES`, `docker-compose.yml:54`, `.env.example:214`) is present in all three. The report sells "env-overridable" as delivered. Fix: add the var to the three compose files and `.env.example`, or move the constant into `src/upload_limits.py` **together with** the three compose files (`tests/test_docker_devops_hardening.py` regex-scans only that module and asserts every name it finds is forwarded).
2. **P2-07 threshold comment is wrong.** I re-ran the shipped sniff: latin-1/cp1252 prose is not a flat 0.13 — German 0.148, Spanish 0.125, French 0.193, Icelandic 0.229, and **Polish cp1250 scores 0.396 and is rejected today**. The comment at `routes/email_routes.py:3749-3751` advertises headroom that does not exist, and the "cost: UTF-16/32" note understates it (cp1251 Russian 0.815 — every non-Western legacy encoding is rejected too). Failure direction is safe (reject == status quo), so fix the comment, not the code.
3. **P2-01 comment presents an already-met reopen trigger as hypothetical.** `src/upload_handler.py:1246-1259` lists forced disposition among the facts making deletion defensible and names "an upload route that serves without forcing disposition" as a reopen condition. That route exists now: `routes/upload_routes.py:444` returns `FileResponse(thumb_path, media_type="image/jpeg", headers=UPLOAD_RESPONSE_HEADERS)` with no `filename=`. Not a live vector (PIL-regenerated JPEG, nosniff set) but the comment is misleading. One-sentence fix.
4. **P2-02 policy carries no fetch directives.** `sandbox allow-downloads; frame-ancestors 'none'` — adding `default-src 'none'` is one word, strictly tighter, and cannot affect `?thumb=1` (CSP is not applied to subresources).
5. **Law 4 across every batch.** `check-tracker.py` reports `P2 ready 26 claimed 0 blocked 0 done 0` while ten P2 tasks are complete on disk. Every agent flagged this honestly and correctly refused to touch `.pantheon/`. The integrator ticks `.pantheon/ROADMAP.md:313-337` and re-runs the checker.

## Reverted

**P2-09** — revert `services/memory/skills.py` in full and hunks 2–5 of `src/agent_loop.py` (the `context_length` kwarg at `:2240`, the import widening at `:2649`, the clamp replacement at `:2677`, and the call site at `:4338`). Hunk 1 (`:574`, P2-15) is separable and stays.

The reviewer wins and the agent's evidence is not decisive — its end-to-end table fed synthetic `context_length` values straight into `_build_system_prompt` and never exercised the function production actually uses. I reproduced the defect:

- The prompt is built at `src/agent_loop.py:4342`; `_route_context_lengths` is only populated by `_trim_route_request_messages`, first invoked at `:4404`. So round one always takes the `.get(..., context_length)` fallback.
- That `context_length` comes from `routes/chat_helpers.py:791 get_context_length(...)`, which returns `DEFAULT_CONTEXT = 128000` and **discards** the `known` flag. Measured: `get_context_length_known(<unreachable endpoint>) == (128000, False)`, `get_context_length(...) == 128000`.
- `compute_skill_injection_limit(3, 128000, explicit=False) == 12`.

So on any endpoint whose window cannot be proven — including a local llama.cpp box that really holds 8K — the default install now injects **12** skill blocks of user-editable untrusted content instead of 3. That is precisely the failure `src/model_context.py:313-315` warns against, committed by a function whose docstring cites that warning. Second, confirmed by reading: `skill_limit_is_explicit(3)` is False, so a user who deliberately types `3` into `static/index.html:495` — an input labelled **"Max skills per request"**, `min="0" max="12"`, with no auto affordance — also gets 12.

Re-land is cheap once the human settles the semantics: at `:4342` call `budget_context_for_model(candidate_url, candidate_model, fallback=0)` (returns 0 for an unproven window, no extra probe — it shares the same cache the `:4245` call uses), which restores the flat 3. The pure functions in `services/memory/skills.py` are correct in isolation and worth keeping for the re-land.

## Stopped on a false premise

- **P2-13 (BLOCKED, correctly).** Premise verified true — both clamps exist where the spec says (`src/llm_core.py:1071`, `src/agent_loop.py:2212`). The stop is on a blocker the spec never names: four assertions in two files outside the batch pin the current cap (`tests/test_llm_core_temperature_reasoning.py:104`, `tests/test_pr6020_rebase_regressions.py:182/:201/:216`). `git diff src/llm_core.py` is empty; the Anthropic clamp at `:1572` is untouched as required. Refusing to ship a hidden env escape hatch with no UI was the right call.
- **P2-02's roadmap line is a no-op.** `.pantheon/ROADMAP.md:317` says "add `Content-Security-Policy: sandbox` to `UPLOAD_RESPONSE_HEADERS`. One line." No route in this app can set a CSP — starlette's `MutableHeaders.__setitem__` replaces, and the middleware runs after the handler. The middleware branch is the only place this can live.
- **P2-01's roadmap Verify line proves nothing.** It says "uploading `static/js/chat.js` succeeds." `mimetypes.guess_type('f.js')` = `text/javascript`, which was never in `dangerous_types`, and `.js` was never in `dangerous_extensions` — chat.js uploaded fine at baseline. The real delta is the extension half: `.exe` guesses to `application/x-msdos-program` (not MIME-blocked) but *was* in the extension list, so `installer.exe` was a 400 and now saves.
- **`.h` was never in the "black hole"** — `mimetypes.guess_type('f.h')` = `text/x-chdr`, already passing the `text/` arm. Added anyway for determinism, per spec.
- **The roadmap's P2-06 extension list is partly dead.** `.scss .toml .ini .vue .svelte` are in `ROADMAP.md:323` but **none** of them is in `is_document_file`'s `document_extensions` — adding them to `_is_text_file` would be unreachable code. Correctly omitted; the roadmap line should be corrected in place.
- **P2-07's brief carried a bound belonging to P2-12** ("any diff past `email_routes.py:3378` has left its scope"). P2-07's own dispatch is at `:3472`, so that bound is unsatisfiable. What it protected is intact: lines 3330–3430 are byte-identical to HEAD, ZIP builder and the `415 "Content-ID is not an image"` guard included.

## Needs a human decision

1. **Two governing documents contradict each other on P2-09, and neither the agent nor the reviewer cited the contradiction.** `.pantheon/P2-CORRECTED.md:127` puts P2-09 in "§D UNVERIFIABLE — needs the fork head first" and ends "reconcile against fork commit 1 before editing `agent_loop.py:2660`". `.pantheon/ROADMAP.md:326` says "**Fork-head check done — no conflict, this is ready.**" This tree is a single squashed commit (`f4364bf`) with no fork history, so the reconciliation cannot be performed here regardless. Same contradiction applies to P2-13 (`ROADMAP.md:332` vs `P2-CORRECTED.md:124`, with a specific `git diff b4d1293..pre-rename-backup` citation on the ROADMAP side). **Which document wins?** Every agent assumed P2-CORRECTED supersedes; that assumption is undocumented.
2. **P2-09's UI semantics.** `0` is already the documented off switch, so "auto" needs a different sentinel or an explicit affordance. Until that is decided, any re-land silently overrides a user-typed "Max".
3. **P2-13's relaxation semantics.** `_apply_local_generation_stability` receives only a payload dict and cannot tell "user asked for 0.9" from "0.9 is a default". A faithful "default, not cap" needs an explicitness signal threaded from the builder, plus a rewrite (not a weakening) of the four pinning assertions — the two qwen tests at `:185`/`:204` exist to prove a mixed fallback chain leaks temperature in neither direction, and that property must survive.
4. **P2-07 is unreachable from the UI.** `static/js/emailLibrary.js:6807` — `_OPENABLE_RE = /\.(pdf|docx|txt|md|markdown|eml)$/i` — gates the "Open in document editor" button on exactly the six pre-existing suffixes. No `.log/.csv/.json/.yaml/extensionless` attachment can reach the new branch from the reader. Nobody owns that file this run, and P2-CORRECTED §B never mentions the gate. Suggested: drop the extension gate entirely and let the backend sniff be the single decision point. **Do not tick P2-07 as user-visible until this moves.**
5. **P2-11's response contract changed.** Partial-failure batches now return 200 with `files` + `rejected` where they previously returned the failure status with nothing. `static/js/fileHandler.js:325` does `pendingFiles = []` on any 2xx, so the rejected subset silently vanishes from the composer with no message. A one-line toast reading `rejected` closes it; that file is unowned.
6. **P2-16's message is duplicated by value, not by call.** `routes/research/research_routes.py:505` holds a literal equal to `privilege_denied_message('can_use_research')` rather than calling it, deliberately, because the raise sits inside a `try` whose `except Exception: pass` fails open. Nothing pins the pair. Accept the duplication or add a one-line test.
7. **Untested new controls.** The P2-17 413 cap, its boundary, and its ordering behind `require_admin` have **zero** coverage in `tests/`; `attachment_as_doc` has zero coverage and always did. Both agents own no test files. Someone needs to own promoting the two scratchpad harnesses into `tests/`.
8. **P2-08 now bites in practice.** `MAX_INLINE_ATTACHMENT_CHARS = 24000` is shared across a whole turn, and P2-06 just turned 11 extensions from a ~26-char banner into real content. Still BLOCKED in §C.

## Suite

Honest state, all from `/work/pantheon`:

- `python3 -m pytest -q` **does not complete** — it aborts with `Interrupted: 5 errors during collection`. All five are `ModuleNotFoundError: No module named 'nh3'` from `src/visual_report.py:28`, in `tests/test_visual_report{,_icon_url,_nonstring,_slug_unique,_toc_code_fence}.py`. **That is an environment fact — a missing optional dependency — not a verdict on these changes.** `import nh3` fails standalone.
- Ignoring those five, `-p no:randomly`: **44 failed, 5742 passed, 6 skipped** in 205s.
- I did not take that on trust. I ran the identical invocation against a clean `git worktree` at baseline `f4364bf`: **44 failed, 5731 passed, 6 skipped**. The 44 failure names are identical between the two runs. **Zero regressions; +11 net new passing tests** (the P2-01/P2-11/P2-04 additions). Worktree removed.
- The 44 pre-existing failures cluster in `test_hwfit_*` (18), `test_caldav_*` (7), `test_security_regressions` (6, all nh3), `test_markdown_lazy_lib_loading_js` (4), `test_lmstudio_vision` (2), plus nine singletons. None is in any area touched this run.
- `git diff --name-only | grep '\.py$' | xargs python3 -m py_compile` → **clean, all 14 files**.
- `node --check` → **not applicable, zero `.js` files were modified**. Every JS coupling identified this run (`fileHandler.js:23`/`:325`, `emailLibrary.js:6807`, `index.html:495`) is an untouched follow-up.

**Collisions: none.** Fourteen files modified, fourteen files claimed, one owner each — `git status --short` matches the seven ownership lists exactly with no overlap. Two files carry two tasks from the *same* batch: `src/agent_loop.py` (P2-15 at `:574`, P2-09 in four later hunks — separable, verified) and `src/upload_handler.py` + `routes/upload_routes.py` (P2-01 and P2-11 — disjoint regions). One real cross-file coupling with no collision: `src/upload_handler.py`'s `document_extensions` (upload-pipeline) must stay a subset of `src/document_processor.py`'s `_is_text_file` (document-ingest); the invariant is now written into the docstring but nothing enforces it.

## For the tracker

```
P2-01 | IMPLEMENTED | blocklist and call site deleted whole per D-2026-08-26-01; rationale comment at src/upload_handler.py:1246
P2-02 | IMPLEMENTED | sandbox CSP branch at core/middleware.py:138, three pre-existing branches byte-identical
P2-03 | IMPLEMENTED | four zero-reader config blocks deleted, src/config.py:34 and :103; import side effect verified intact
P2-04 | IMPLEMENTED | validate_file_upload deleted, src/chat_helpers.py:226; live-path cap coverage retained
P2-06 | IMPLEMENTED | _is_text_file 10->28 at src/document_processor.py:45; 11 extensions verified to flip banner->content
P2-07 | IMPLEMENTED (backend only) | decode fallback at routes/email_routes.py:3728; unreachable from UI until emailLibrary.js:6807 moves
P2-09 | REVERTED | scaling keyed off get_context_length's unproven 128000 fallback; unknown-window endpoints got 12 skills, not 3
P2-11 | IMPLEMENTED | MAX_FILES_PER_REQUEST=25 at src/upload_handler.py:227, enforced pre-loop at routes/upload_routes.py:274
P2-13 | BLOCKED | nothing shipped; four assertions in two unowned test files pin the cap that must be relaxed
P2-15 | IMPLEMENTED | heredoc instruction removed at src/agent_loop.py:574; 10 ban sites, 0 instruction sites
P2-16 | IMPLEMENTED | privilege_denied_message at src/auth_helpers.py:127 plus the hardcoded twin at research_routes.py:505
P2-17 | IMPLEMENTED (env override not wired) | 413 cap at routes/backup_routes.py:134, after require_admin at :131
```

Nothing was committed.