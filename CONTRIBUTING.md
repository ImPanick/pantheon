# Contributing to Pantheon

Thanks for helping. The project is moving quickly, so the best contributions are focused, easy to review, and easy to test.

## Branch model

**`main` is the only branch.** Open your PR against it; cloning gives you it.

Upstream Odysseus's `dev` branch is reachable on the `upstream` remote if you need to compare
against it, but nothing here lands there.

*Corrected 2026-08-30. This section described upstream's two-branch model — "open your PR
against `dev`, not `main`", "end-users cloning will land on `dev` by default" — which survived
the fork rename and was never true of this repository. `git branch -a` has only ever shown one.
`README.md` said the opposite and was right; three documents said this and were wrong, at the
three places a newcomer meets the project first: cloning, contributing, and hardening CI.*

## Before You Start

- Search existing issues and pull requests before opening a new one.
- Prefer one bug fix or feature per pull request.
- Avoid broad rewrites, formatting-only changes, or moving many files unless the issue is specifically about structure.
- If you want to work on a large feature, open an issue first and describe the approach.

## How work is tracked, and what "done" means here

This project does not work the way most repositories of its size do, and a first-time contributor
who guesses will guess wrong. It is worth the five minutes.

**Every change is a row.** [`.pantheon/ROADMAP.md`](.pantheon/ROADMAP.md) is the only tracker —
no GitHub Projects board, no milestones, no per-area handoff files. A row states the defect, what
was measured, what the fix is, and a `Verify:` clause naming the observation that would prove it.
Marks are `- [ ]` ready, `- [~]` blocked, `- [·]` claimed, `- [x]` done. If what you are fixing has
no row, write one. If you find a second defect on the way, that is a second row — not a second
paragraph in the first, and not a quiet extra commit in the same PR.

**The roadmap is updated every turn.** Ticked a row, corrected a premise, found a bug, got blocked,
did nothing — it goes in. `python3 .pantheon/check-tracker.py` recounts the ticks and fails if the
status table has drifted from the rows beneath it, so a stale tracker is a red check rather than a
thing somebody notices in a month.

**A row cannot be ticked on a claim nobody can check.** "I wrote a test and it passes" is not
evidence that a defect is gone: a test written after the fix passes on a tree where the bug never
existed. The evidence is a test that **fails on the tree as it stood before your change**. Produce
it, and put the result in the PR:

```bash
git stash                                     # set your fix aside
python -m pytest -q tests/test_the_thing.py   # must FAIL here — record what it says
git stash pop
python -m pytest -q tests/test_the_thing.py   # must PASS here
```

A test that passes in both states is testing something other than your fix. Say which test and what
it reported on the unfixed tree; "added tests" on its own does not carry a review.

**Then try to break the test.** The internal standard is mutation testing, and you can do the
useful part of it by hand: change the line you fixed — revert it, invert the condition, drop the
argument — and confirm your test goes red. If the mutation survives, the test is passing for a
reason that is not your fix. This is where most nearly-good patches are caught.

**A test that greps a file is testing the file, not the code.** A substring search cannot tell you
whether it found code or a comment about code, or which function it landed in — the project has
been burned three separate ways by exactly that. Call the thing you are asserting about: build the
router and invoke the handler, evaluate the module, run the function. If you genuinely must assert
on source text, resolve the scope first (`ast.get_source_segment` for Python, a delimited split for
JS) and strip comments.

**Half-wiring is the defect, not a smaller version of the fix.** If a behaviour is set in five
places and you fix one, the row is not done. Find the other four before you open the PR — this is
the single most common reason a correct-looking patch gets sent back.

**Read [`.pantheon/FORBIDDEN.md`](.pantheon/FORBIDDEN.md) before touching anything security-shaped.**
Part 1 lists names that cannot be renamed — class names, tool ids, enum values, storage keys —
because renaming them silently resets user data or breaks a join. Part 2 lists security controls
that never lift, each with the property it holds. A PR that removes one of those will be closed
even if the surrounding change is good; if a task seems to require it, open an issue and say so.

The full set of rules is in [`.pantheon/AGENTS.md`](.pantheon/AGENTS.md). It is written for agents
working on this repository, but the reasoning is the same for people, and every rule cites the
incident that produced it.

## Setup

Docker is the recommended path for normal testing:

```bash
git clone https://github.com/ImPanick/pantheon.git
cd pantheon
cp .env.example .env
docker compose up -d --build
```

Manual development uses Python 3.11+:

```bash
python3 -m venv venv
source venv/bin/activate
pip install -r requirements.txt
python -m uvicorn app:app --host 127.0.0.1 --port 7000
```

Windows is not actively tested. Docker on Linux or a Linux/macOS manual install is the safer path for now.

## Running Checks

**While you work**, run the files your change touches. The suite is large — around a thousand test
files — and running all of it on every edit is not a workflow:

```bash
python -m pytest -q tests/test_the_thing.py tests/test_the_other_thing.py
python -m py_compile app.py routes/*.py src/*.py
# Redirect the file in rather than passing a path: `node --check <path>` picks
# the module type from the nearest package.json and silently passes anything
# with an `import` in it when that resolves to CommonJS.
node --input-type=module --check < <file-you-changed>
```

**Before you open the PR**, run the gate. It is one command instead of a memory, and it runs the
same checkers CI runs — it reads the list out of `.github/workflows/ci.yml` rather than keeping a
second copy of it, so it cannot drift from what will actually block your merge:

```bash
python3 .pantheon/release-gate.py --list    # what will run, and where it came from
python3 .pantheon/release-gate.py --fast    # every checker, skipping the suite
python3 .pantheon/release-gate.py           # everything, including the suite
```

Exit code zero is the gate. `--fast` takes about a minute and catches the things reviews
otherwise spend time on: tracker drift, an element lookup that resolves to nothing, an env var read
but never declared in `.env.example`, a vendored file nobody attributed, a source file with no SPDX
header, a recurring job scheduled on an exact boundary, an outbound call that is not rate-limited.
Each checker prints a one-line summary and several carry a ceiling — if you push a number up, the
checker fails and tells you which one.

Run the suite once before you push, and **do not edit the tree while it runs.** Fifteen files under
`tests/`, at twenty call sites, read their own source with `inspect.getsource` (counted 2026-09-16),
and `getsource` finds a function by the line number recorded when the module was *imported* and then
reads the file from *disk*. Adding so much as a comment mid-run makes it return a different
function's body, and the failure arrives looking exactly like a regression in whatever the offset
happened to land on. If an edit cannot wait, the run is spent — make the edit and start a new one.

For Docker-related changes:

```bash
docker compose config
docker compose up -d --build
docker compose logs --tail=120 pantheon
```

Mention what you ran in the pull request description. If you could not run a check, say so.

## Pull Requests

Good pull requests usually include:

- A short explanation of the bug or feature.
- The files or areas changed.
- Manual test steps or automated test results from running the actual app, not just the test suite.
- Screenshots or short recordings for UI changes.
- Links to related issues, for example `Fixes #123`.

Please keep PRs small. Large PRs that mix unrelated cleanup, formatting, refactors, and behavior changes are much harder to review.

> **Auto-generated PRs.** If you are running an LLM agent (Devin, Cursor, OpenHands, Claude Code, etc.) against this repo: please open an issue describing the problem first instead of opening a PR directly. Bulk agent-generated PRs that don't match the project's visual style or contribution format will be closed without review, even when the underlying fix is correct.

## Style and visual changes

Pantheon has an intentional visual style. PRs that ignore it will be closed without merge, no matter how correct the underlying code is.

Before submitting any change that affects what the app looks like — buttons, icons, fonts, colors, spacing, layout, CSS, HTML, SVG, or any `static/js/` module that draws to the DOM — please:

1. **Run the app locally** and view the change in a browser. Type-checks and unit tests are not enough.
2. **Attach a screenshot or short clip** of the change in the running app. Add a mobile screenshot too if the change affects mobile.
3. **Match the existing visual language.** Specifically:
   - Reuse existing CSS variables (`--red`, `--fg`, `--bg`, `--card`, `--border`, …). Do not introduce new color values, font sizes, or spacing units.
   - Reuse existing button, input, card, and border classes. Don't invent parallel styling for similar widgets.
   - **No Unicode emoji in UI or code.** Use inline SVG (matching the monochrome icon style already in `static/index.html`) or plain text.
   - Monospaced font (`Fira Code`) for primary UI text. Don't override.
   - Dark theme is the default; any light-mode work goes through the existing theme system, not hard-coded.
4. **Don't add parallel components.** If a similar widget already exists in the app, extend it instead of writing a new one.

If you are unsure whether a change is "visual," it is. Default to attaching a screenshot.

## Code conventions

Don't hardcode values that the project already exposes through a constant or a helper. Hardcoded literals drift out of sync, break on non-default deployments, and reintroduce bugs we've already fixed.

- **Filesystem paths:** never build writable paths from `Path(__file__)...` into the source tree, hardcode `/app/...`, or use a relative `"data/..."` string. Every persisted file and directory has a named constant in `src/constants.py` (for example `AUTH_FILE`, `USER_PREFS_FILE`, `SETTINGS_FILE`, `TTS_CACHE_DIR`, `CHROMA_DIR`). Import and use that named constant; do not re-derive the path locally with `os.path.join(DATA_DIR, "x.json")` or `DATA_DIR / "x.json"`. `DATA_DIR` is the single place that reads `PANTHEON_DATA_DIR`, so use it directly only for dynamic paths that have no fixed name (for example per-owner files). If a data file or directory has no constant yet, add one to `src/constants.py`. The source tree is read-only in Docker and `/app/...` does not exist on native runs; guard directory creation so an unwritable path degrades gracefully instead of crashing at import.
- **Internal API / loopback URLs:** don't hardcode `http://localhost:7000`. Use `internal_api_base()` from `src.constants` (it honors `PANTHEON_INTERNAL_BASE` / `APP_PORT`).
- **Ports, limits, model lists, and similar:** reuse the existing constant if one exists; if it doesn't and the value is used in more than one place, add a constant rather than copying the literal.

If you need a value that has no constant or helper yet, add it to `src/constants.py` (the single source of truth for paths and config; `core/constants.py` only re-exports it for backward compatibility) and import it, rather than repeating a literal across files.

**Commits:** use [Conventional Commits](https://www.conventionalcommits.org), `type(scope): summary` (e.g. `fix(search): ...`, `feat(notes): ...`, `docs(contributing): ...`). Common types: `fix`, `feat`, `refactor`, `docs`, `test`, `chore`, `ci`. Keep the subject short and imperative; put the "why" in the body when it isn't obvious.

## Issue Reports

For bugs, include:

- Install method: Docker, manual Python, WSL, etc.
- OS, browser, and device if relevant.
- Exact steps to reproduce.
- Expected behavior and actual behavior.
- Logs, screenshots, or terminal output.

For model-serving issues, include:

- Backend: Ollama, vLLM, SGLang, llama.cpp, LM Studio, etc.
- Model name.
- GPU/CPU and operating system.
- Cookbook task logs or server logs.

Issues with only "help", "does not work", or a screenshot without context may be closed as not actionable.

## Security

Do not post secrets, API keys, private logs, personal documents, or public IPs in issues or pull requests.

**Never report a vulnerability as an issue.** [`SECURITY.md`](SECURITY.md) has the private channel,
what to put in a report, and what response to expect. For this project in particular, naming the
affected component is often most of the exploit — it ships shell execution, file read/write, mail,
and MCP process launch — so the usual "I'll file a vague issue" instinct does real harm here.

## Code of conduct

[`CODE_OF_CONDUCT.md`](CODE_OF_CONDUCT.md) applies to issues, pull requests, reviews and
discussions. It is the Contributor Covenant v2.1 with an enforcement section written for a project
run by one person, and it says how to report and what happens next.

Worth separating from it: a review that says your pull request is wrong, cites the file and the
line, and declines to merge it is not a conduct problem. This document sets a high evidence bar and
applies it to everyone. Being told the bar was not met is the process working.

