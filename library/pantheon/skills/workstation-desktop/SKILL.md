---
name: workstation-desktop
description: Drive the workstation's desktop with the computer tool — look at the screen, click, type, press keys, scroll and drag, checking every result before the next action.
version: 1.3.0
category: workstation
tags: [workstation, computer, desktop, screen, mouse, click, keyboard, type, gui, vm, firefox, browser, screenshot]
requires_toolsets: [computer]
status: published
confidence: 0.95
source: pantheon
---

## When to Use

Anything a person does at a computer: a page or app, a form, a setting, how something looks, text only on screen. The workstation is an Ubuntu machine separate from Pantheon, desktop 1280×800. With Computer Use on, steps here run unasked: carry the task through. Commands and files are quicker in bash and the file tools.

## Procedure

1. Start with `computer` action `screenshot`. Never click from memory or an old picture.
2. **Point by mark.** Each screenshot numbers what you can click, listed as `[7] button “Terminal” at (20, 780)`. Send `"mark": 7` with `click`, `move`, `scroll`, `drag` (`to_mark`) or `type` (clicks it first). Numbers are the last screenshot's only.
3. Else use the screenshot's own pixels: x 0–1279, y 0–799, no scaling; aim at a control's middle.
4. The panel is the bottom 40 pixels: **menu** (20, 780) — every program, `type` to search — **Terminal** (60, 780), **Firefox** (100, 780), **Files** (140, 780), a button per open window (click to bring it forward), the clock. Title bars end in minimise, maximise, close; double-click one to maximise.
5. Click a field before `type` (text, up to 20,000 characters; it does not press Enter). Then `key` `Return` to submit.
6. `key` takes xdotool names: `Return` `Escape` `Tab` `BackSpace` `Delete` `Up` `Down` `Page_Down` `End` `F5`, combos like `ctrl+a` `ctrl+c` `ctrl+v` `alt+Left`; several separated by spaces are pressed in turn (`ctrl+a BackSpace`).
7. Firefox: `ctrl+l` address bar, then `type` the URL and `key` `Return`; `ctrl+t` / `ctrl+w` open / close a tab; `F5` reload, `ctrl+shift+r` without cache; `ctrl+shift+k` web console (page errors in red), `F12` closes it; `ctrl+f` find.
8. `scroll` at a point inside the pane to move: `dy` positive is down, in wheel clicks (3–5 ≈ a third of a page, at most 50); `dx` sideways.
9. The mouse: `click`; `double_click` opens or selects a word; `triple_click` selects a line or field; `right_click` context menu; `middle_click` pastes in a terminal or opens a link in a tab; `move` hovers; `drag` from x,y to to_x,to_y (sliders, selecting, moving a window by its title bar); `mouse_down` / `mouse_up` hold and release.
10. Read each returned screenshot before acting again. Nothing changed? `wait` (ms, up to 30,000) and `screenshot` again instead of clicking again.
11. Finish by saying what the last screenshot shows — what you saw, not what you expected.

## Pitfalls

- Clicking again because a slow page "did nothing" submits twice; wait and look first.
- Typing before the field has focus sends the text elsewhere.
- "Busy" means a person holds the screen and nothing was done: ask them, or stop and say you are waiting. Do not retry in a loop.
- A dialog blocks the window behind it; handle it first.

## Verification

- The last screenshot shows the intended end state, and the answer describes it.

## Reference

All key names and shortcuts: `manage_skills action=view_ref name=workstation-desktop path=references/keys.md`.
