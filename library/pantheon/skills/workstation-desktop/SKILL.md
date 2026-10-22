---
name: workstation-desktop
description: Drive the workstation's desktop with the computer tool — look at the screen, click, type, press keys, scroll and drag, checking every result before the next action.
version: 1.0.0
category: workstation
tags: [workstation, computer, desktop, screen, mouse, click, keyboard, type, gui, vm, firefox, browser, screenshot]
requires_toolsets: [computer]
status: published
confidence: 0.95
source: pantheon
---

## When to Use

A task needs the workstation's screen: clicking through a page or app, filling a form, checking how something looks, reading text only on screen. The workstation is an Ubuntu machine separate from Pantheon, desktop 1280×800. Commands and files go through bash and the file tools instead — same machine, faster, exact.

## Procedure

1. Start with `computer` action `screenshot`. Never click from memory or an old picture.
2. Coordinates are the screenshot's own pixels: x 0–1279 left to right, y 0–799 top to bottom, no scaling. Aim at the middle of a control.
3. The tray is the bottom 32 pixels: **Terminal** button about (33, 784), **Firefox** about (99, 784), then one button per open window (click to bring it forward), then the clock. Right-click the empty desktop for the same programs.
4. Click a field before `type` (text, up to 20,000 characters; it does not press Enter). Then `key` `Return` to submit.
5. `key` takes xdotool names: `Return` `Escape` `Tab` `BackSpace` `Delete` `Up` `Down` `Page_Down` `End` `F5`, combos like `ctrl+a` `ctrl+c` `ctrl+v` `alt+Left`; several separated by spaces are pressed in turn (`ctrl+a BackSpace`).
6. Firefox: `ctrl+l` address bar, then `type` the URL and `key` `Return`; `ctrl+t` / `ctrl+w` open / close a tab; `F5` reload, `ctrl+shift+r` without cache; `ctrl+shift+k` web console (page errors in red), `F12` closes it; `ctrl+f` find.
7. `scroll` at a point inside the pane to move: `dy` positive is down, in wheel clicks (3–5 ≈ a third of a page, at most 50); `dx` sideways.
8. The mouse: `click`; `double_click` opens or selects a word; `triple_click` selects a line or field; `right_click` context menu; `middle_click` pastes in a terminal or opens a link in a tab; `move` hovers; `drag` from x,y to to_x,to_y (sliders, selecting, moving a window by its title bar); `mouse_down` / `mouse_up` hold and release.
9. Read the screenshot every action returns before the next one. Nothing changed? `wait` (ms, up to 30,000) and `screenshot` again instead of clicking again.
10. Finish by saying what the last screenshot shows — what you saw, not what you expected.

## Pitfalls

- Clicking again because a slow page "did nothing" submits twice; wait and look first.
- Typing before the field has focus sends the text elsewhere.
- Launching programs, reading files or checking a URL by mouse — bash does those (workstation-apps-and-windows, workstation-shell).
- "Busy" means a person holds the screen and nothing was done: ask them, or stop and say you are waiting. Do not retry in a loop.
- A dialog blocks the window behind it; handle it first.

## Verification

- The last screenshot shows the intended end state, and the answer describes it.

## Reference

All key names and shortcuts: `manage_skills action=view_ref name=workstation-desktop path=references/keys.md`.
