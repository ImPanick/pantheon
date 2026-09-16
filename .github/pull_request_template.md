## Summary

<!-- One paragraph: what changed and why. "Fixed bug" and "Added feature" are not summaries. -->

## Target branch

- [ ] This PR targets **`main`**. It is the only branch here, so this is also the default base — you should not have to change anything.

<!-- Until 2026-09-16 this box said the opposite: "This PR targets `dev`, not `main`", with
     instructions to edit the base. `dev` is upstream Odysseus's branch and has never existed in
     this repository — `git branch -a` has only ever shown one — so every contributor who followed
     it went looking for a base that is not there. CONTRIBUTING.md corrected the same mistake on
     2026-08-30; this template and the bug report form were missed in that sweep. -->


## Linked Issue

<!-- Every PR should be linked to an issue.
     Use one of:  Fixes #NNN  |  Part of #NNN  |  Closes #NNN  -->

Fixes #

## Type of Change

- [ ] Bug fix (non-breaking — fixes a confirmed issue)
- [ ] New feature (non-breaking — adds new behaviour)
- [ ] Breaking change (changes or removes existing behaviour)
- [ ] Refactor / cleanup (behaviour unchanged)
- [ ] Documentation only
- [ ] CI / tooling / configuration

## Checklist

- [ ] I searched [open issues](https://github.com/ImPanick/pantheon/issues) and [open PRs](https://github.com/ImPanick/pantheon/pulls) — this is not a duplicate.
- [ ] This PR targets `main` (the only branch, and the default base)
- [ ] My changes are limited to the scope described above — no unrelated refactors or whitespace changes mixed in.
- [ ] I actually ran the app (`docker compose up` or `uvicorn app:app`) and verified the change works end-to-end. Type-checks and unit tests are not enough.
- [ ] I did not run the app/runtime validation and stated that gap in **How to Test**. Leave this unchecked when the app-run box above is checked.
- [ ] `python3 .pantheon/release-gate.py --fast` passes on my branch. If a checker fails for a reason my change did not cause, I named it in **How to Test** rather than leaving it red.
- [ ] **Evidence, not assertion.** I have a test that *fails* on the tree as it stood before my change and passes after it, and **How to Test** says which test and what it reported on the unfixed tree. Leave this unchecked for a change with no testable behaviour (a typo, a comment, a docs edit) and say which it is.

## How to Test

<!-- Step-by-step instructions a reviewer can follow to verify this works.
     Do not leave this empty — a PR without test steps will be sent back. -->

1.
2.
3.

## Visual / UI changes — REQUIRED if you touched anything that renders

**Anything that changes what the UI looks like — buttons, icons, padding, colors, fonts, spacing, layout, CSS, HTML, SVG, or any `static/js/` module that draws to the DOM — needs all of the following. PRs that change rendering without these WILL be closed.**

- [ ] **Screenshot or short clip** of the change in the running app, attached below. Mobile screenshot too if the change affects mobile.
- [ ] **Style match**: the change uses Pantheon's existing visual language. Specifically:
  - Reuse existing CSS variables (`--red`, `--fg`, `--bg`, `--card`, `--border`, etc.) — do not introduce new color values, font sizes, or spacing units.
  - Reuse existing button/input/card/border classes. Don't invent parallel styling.
  - **No Unicode emoji in UI or code.** Use inline SVG (matching the monochrome icon style already in `static/index.html`) or plain text.
  - Monospaced font (`Fira Code`) for primary UI text. Don't override.
  - Dark theme is the default; any light-mode work must be wired through the existing theme system, not hard-coded.
- [ ] **No new component patterns.** If a similar widget already exists in the app, extend it instead of writing a parallel one.
- [ ] **I am not an LLM agent submitting a bulk PR.** If you are, please open an issue describing the problem first — bulk auto-generated PRs that don't match the project's visual style are closed on sight, even when the underlying fix is correct.

### Screenshots / clips

<!-- Drag and drop images or a screen recording here. Required for any UI/visual change. -->
