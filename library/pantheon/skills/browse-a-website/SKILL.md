---
name: browse-a-website
description: Do things on a website in the real browser: open, read the numbered elements, click and type by number, confirm each step, and sign in only with a vault login.
version: 1.0.0
category: core
tags: [browser, browse, website, web, page, click, form, fill, login, sign, navigate, tab, firefox, screenshot, interactive, site, button]
requires_toolsets: [agent_browser]
status: published
confidence: 0.95
source: pantheon
---

## When to Use

A task needs a live page rather than its text: clicking through a site, filling in a form, a page that needs JavaScript or a sign-in, checking how something looks. For only reading a known page's text, fetching the page is faster.

## Procedure

1. Every `agent_browser` call is one action and takes a short `why` — the person can watch and take over, and reads it.
2. `open` with the `url`, then `read`. `read` returns the page text and its clickable and typable elements numbered `[1]`, `[2]`, …
3. Act on those numbers: `click` with `ref`; `type` with `ref` and `text` (add `submit: true` to press Enter); `press` with `keys` such as `Enter`, `Tab` or `ctrl+a`; `scroll` with `dy` (positive is down).
4. `read` again after every action that changes the page — numbers change when the page does. Never reuse a number from an older read.
5. Confirm each step from the page, not from the call succeeding: the new heading, the success message, the filled field.
6. Signing in: `login` with `item` set to the name of a login in the person's vault. Never type a password, and never ask the person to paste one into the chat. No matching login → say so and stop.
7. Several pages: `tab_new`, `tabs`, `tab_switch`, `tab_close`; `back`, `forward`, `reload` as on any browser. `screenshot` when the person should see the state, `inspect` for one element by `ref` or `selector`.
8. Before anything irreversible — paying, sending, deleting, submitting an application — stop and ask the person, quoting what will be submitted.

## Pitfalls

- Clicking a stale number from a read before the page changed.
- Reporting success because a click returned without error.
- Filling a form with guessed personal details. Ask for anything you do not have.
- Getting stuck on a captcha or a two-factor prompt: hand it to the person, who can take over the browser.

## Verification

- The last `read` or `screenshot` shows the outcome the person asked for.
