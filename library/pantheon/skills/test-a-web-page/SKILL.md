---
name: test-a-web-page
description: QA a web page or web app in the real browser: smoke-test it, click through every journey, try bad input, check narrow and wide windows, and report each step with what the page showed.
version: 1.0.0
category: qa
tags: [qa, test, testing, browser, web, page, app, site, frontend, ui, smoke, form, journey, responsive, regression, visual]
requires_toolsets: [agent_browser]
status: published
confidence: 0.95
source: pantheon
---

## When to Use

A web page, site or web app needs checking from a visitor's side: after building or changing a frontend, before a release, or when the person asks to QA, test or click through a site.

## Procedure

1. Agree the target address and what the page is for. Use a test or staging address and test accounts; never run a journey that pays, sends, deletes or changes real data without the person saying yes for that address.
2. Smoke test: `agent_browser` `open` the address, then `read`. The page loads, the title and main heading are right, nothing reads as an error, and the main controls are numbered in the read.
3. Walk every journey the page offers, one action per call with a short `why`: each navigation link, each button, each form. `read` again after every action and confirm the new state from the page itself.
4. Forms: submit once correctly and see the success state; then empty, too long, wrong format and a double submit, and see a clear error each time with the typed values kept.
5. Look at it: `screenshot` the key states. Check the layout at a phone width and a desktop width if the page can be resized, and in dark mode if it has one. Note anything overlapping, cut off, unreadable or misaligned.
6. Keyboard: `press` `Tab` through the page and check the focus is visible and in a sensible order, and that Enter and Escape do what they should.
7. Report each journey as Pass or Fail with the step, what you expected, what the page showed and a screenshot for each failure. List what you could not reach.

## Pitfalls

- Reusing an element number from before the page changed.
- Calling a click a success because the call returned, without reading the page.
- Testing only the happy path.
- Signing in by typing a password: use a vault login, or ask the person to take over.

## Verification

- Every journey has a result taken from a read or a screenshot of the page after the last step.
