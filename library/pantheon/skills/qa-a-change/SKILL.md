---
name: qa-a-change
description: QA a feature or fix before calling it done: write down what done looks like, run the tests, exercise the real thing, push on the edges, and report what passed with evidence.
version: 1.0.0
category: qa
tags: [qa, quality, test, testing, verify, verification, regression, acceptance, check, done, release, smoke, edge, cases]
requires_toolsets: [bash, read_file]
status: published
confidence: 0.95
source: pantheon
---

## When to Use

Work is about to be called finished, shipped or handed back: a feature, a fix, a refactor, a configuration change. Also when the person asks you to QA, test, verify or sign off something.

## Procedure

1. Write the acceptance list first: three to eight plain sentences saying what must be true when this works, taken from the request. Add the one or two things that must still work and could have broken (the regression list).
2. Find how the project checks itself: read the README, the test folder and any CI file with `read_file`. Note the exact commands.
3. Run the existing checks with `bash`: the tests nearest the change first, then the wider suite if it is quick. Read failures in full before deciding whether the change caused them; run a failure again on the untouched code if you are unsure.
4. Exercise the real behaviour, not only the tests: run the command, call the endpoint, start the app and use it. Do what the person will do.
5. Push on the edges for each acceptance line: empty input, the largest input, wrong types, a missing file or network, doing it twice, doing it out of order, a second user.
6. When something fails, stop and record it exactly: the steps, what you expected, what happened, the output. Fix it only if fixing is part of the task, then run steps 3 to 5 again.
7. Report a table: each acceptance and regression line with Pass, Fail or Not checked, and the evidence for each (the command and its output, or what you saw). Say plainly what you could not run and why.

## Pitfalls

- Calling it done because the code compiles or one happy-path test passed.
- Writing the acceptance list after testing, so it describes what happened rather than what was asked.
- Hiding a failure the change did not cause. Report it and say it was there before.
- Reporting Pass for something you did not actually run.

## Verification

- Every line of the acceptance list has a result and evidence, and anything Not checked says why.
