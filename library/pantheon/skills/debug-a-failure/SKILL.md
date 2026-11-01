---
name: debug-a-failure
description: Find and fix the cause of an error, crash or wrong result — reproduce it, read the whole error, narrow it down with evidence, make the smallest fix, and show the same check passing.
version: 1.0.0
category: core
tags: [debug, bug, error, fix, crash, traceback, exception, failing, broken, test, stack, trace, issue, wrong, regression, troubleshoot]
requires_toolsets: [bash, read_file, grep, edit_file]
status: published
confidence: 0.95
source: pantheon
---

## When to Use

Something fails or behaves wrongly — an exception, a failing test, a command exiting non-zero, output that is not what it should be — and the job is to fix the cause rather than the symptom.

## Procedure

1. Reproduce it with one command you can rerun (`bash`), and capture the full output: `<command> 2>&1 | tail -n 80`. No reproduction yet → ask for the exact steps, input and error.
2. Read the whole error: the exception type, the message, and the deepest frame in the person's own code. Open that file at that line with `read_file` (`offset`/`limit` for big files).
3. Find what the code depends on with `grep` — the definitions, callers and config it reads.
4. State one hypothesis that explains every symptom, and test it cheaply — print the value, run the smallest input, check the version — before changing anything.
5. Narrow down when the cause is not obvious: compare a working and a failing case, cut the input in half, or check what changed recently (`git log -p -5 -- <file>`, `git diff`).
6. Fix the cause with the smallest change, using `edit_file` (never `sed` or redirects).
7. Rerun the reproduction from step 1, then the surrounding tests, and confirm both pass.
8. Report the cause in one or two sentences, the change, and the command that now passes.

## Pitfalls

- Changing code before reproducing the failure.
- Catching and silencing the exception, or loosening a test, to make it go away.
- Several speculative edits at once: you will not know which one mattered.
- Stopping at the first line of a traceback, which is usually a library, not the cause.

## Verification

- The exact command that failed now passes, and the related tests still pass.
