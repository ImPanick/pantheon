---
name: write-automated-tests
description: Write automated tests that catch real breakage: follow the project's framework, test behaviour not internals, cover edges and the bug, and prove each test fails without the code.
version: 1.0.0
category: qa
tags: [test, tests, testing, unit, integration, pytest, jest, vitest, coverage, regression, tdd, qa, assertion, fixture]
requires_toolsets: [bash, read_file, edit_file]
status: published
confidence: 0.95
source: pantheon
---

## When to Use

Asked to add or write tests, to cover a function or a fix, to raise coverage, or to work test-first. Also after fixing a bug, to keep it fixed.

## Procedure

1. Find the project's test setup with `read_file`: the framework, where tests live, how they are named, the shared fixtures and helpers. Write new tests the same way.
2. Run the existing tests once with `bash` so you know the starting state and the exact command.
3. List the behaviours to cover before writing code: the normal case, each boundary (empty, one, many, the limit), each error path, and for a bug the exact input that triggered it.
4. Write one test per behaviour with `edit_file`. Name it after what it proves. Arrange, act, assert; assert on results a caller sees, not on private details.
5. Keep tests independent and repeatable: no order dependence, no real network or clock unless the test is about them, temporary folders for files.
6. Prove each new test can fail: break the code it covers (or run it against the unfixed version) and watch it go red, then put the code back and watch it go green.
7. Run the whole affected suite again and report the command, the counts, and what each new test covers.

## Pitfalls

- Tests that pass whatever the code does, because they assert on a mock or on nothing.
- Copying the implementation's logic into the test, so both are wrong together.
- One huge test that checks ten things and says nothing useful when it fails.
- Leaving a test skipped or marked expected-to-fail to get green.

## Verification

- Every new test has been seen failing for the right reason and then passing, and the suite command and result are in the report.
