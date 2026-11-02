---
name: review-code-changes
description: Review a diff, branch or pull request for real bugs: read the change and its surroundings, trace what breaks, check the tests, and rank findings with file and line.
version: 1.0.0
category: core
tags: [review, code, diff, pull, request, pr, branch, bugs, correctness, security, feedback, changes, audit, quality]
requires_toolsets: [bash, read_file]
status: published
confidence: 0.95
source: pantheon
---

## When to Use

Asked to review a change, check a pull request or branch, or look over code before it ships.

## Procedure

1. Get the change: `git diff <base>...HEAD --stat` then `git diff <base>...HEAD` (or the files the person names). Note what it claims to do.
2. Read each changed file around the change with `read_file`, not just the hunk — a bug is often in what the hunk now calls or no longer handles.
3. For each change ask: wrong logic or off-by-one; missing case (empty, null, error, concurrency); a caller elsewhere that breaks (search the tree for the changed names); security (input reaching a shell, a query, a path, HTML; secrets in code); and resources not closed.
4. Check the tests exercise the new behaviour. Run them if you can.
5. Confirm each suspected bug by reading the path that triggers it; drop anything you cannot show.
6. Report findings most severe first, each with `file:line`, what goes wrong and the input that triggers it, and a suggested fix. Keep style nits separate and few.

## Pitfalls

- Reviewing only the diff hunks.
- A long list of style opinions burying the one real bug.
- Claiming a bug without the input or path that triggers it.

## Verification

- Every finding names a file and line and a concrete way it fails, and you would stand behind each one.
