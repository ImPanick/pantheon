---
name: change-code-safely
description: Change code in an existing project without breaking it: read how it is built, follow its conventions, edit in small steps, and run its own tests before calling it done.
version: 1.0.0
category: core
tags: [code, coding, feature, implement, change, refactor, edit, program, project, repo, repository, tests, build, script, function, develop]
requires_toolsets: [read_file, edit_file, bash]
status: published
confidence: 0.95
source: pantheon
---

## When to Use

Writing a feature, a script or a fix inside a codebase that already exists, where a careless edit can break what is there.

## Procedure

1. Find your bearings: list the layout; read the README and the manifest (`package.json`, `pyproject.toml`, `Cargo.toml`, …) to learn how it builds and tests.
2. Read the code you will touch and one similar piece that already works, so yours matches its naming, structure, error handling and comment style.
3. Run the existing tests once before changing anything, so you know which failures were already there.
4. Make the change in small steps with `edit_file` (exact `old_string`, unique, with its indentation). Create new files with the file tools, not through `bash` redirects or heredocs.
5. Add or update a test that would have failed without your change, when the project has tests.
6. Run the project's own checks: tests, linter, type checker, build. Fix what you broke; leave what was already broken alone and mention it.
7. Summarise for the person: what changed and where, how you checked it, and anything left undone.

## Pitfalls

- Editing a file you have not read in full around the change.
- Rewriting whole files or reformatting code you did not need to touch.
- New dependencies without saying so.
- Saying "done" when the tests were not run.

## Verification

- The project's tests and checks pass (or fail only where they failed before you started), and a test or run shows the new behaviour.
