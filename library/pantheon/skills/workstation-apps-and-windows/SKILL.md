---
name: workstation-apps-and-windows
description: Open, find, focus, arrange and close programs on the workstation's desktop from its shell — Firefox, terminals, anything installed — with xdotool, instead of hunting for them with the mouse.
version: 1.1.0
category: workstation
tags: [workstation, desktop, apps, application, launch, open, start, window, windows, focus, close, firefox, browser, xfce4-terminal, terminal, thunar, files, xdotool, vm, gui]
requires_toolsets: [computer, bash]
status: published
confidence: 0.95
source: pantheon
---

## When to Use

Opening a program or a page on the workstation's screen, bringing a window forward, listing what is open, resizing or closing a window, installing a missing program. In the workstation every bash command already has `DISPLAY` set, so what it starts appears on the screen the `computer` tool sees.

## Procedure

1. Check the bash result says `ran_in: "workstation"`. If not, the shell is Pantheon's own machine: use the panel's buttons with `computer` instead.
2. Start a program detached, output to a file, so the call returns at once: `nohup firefox 'http://127.0.0.1:8000/' > ~/firefox.log 2>&1 < /dev/null &` — same shape for anything (`nohup xfce4-terminal > /dev/null 2>&1 < /dev/null &`; files: `thunar ~`).
3. Firefox already open? Reuse it — one command does either: `if pgrep -f '[f]irefox' > /dev/null; then xdotool windowactivate --sync "$(xdotool search --onlyvisible --class firefox | tail -1)" key --clearmodifiers ctrl+t && sleep 0.5 && xdotool type --delay 15 'URL' && xdotool key Return; else nohup firefox 'URL' > ~/firefox.log 2>&1 < /dev/null & fi`.
4. Wait for the window, not a guessed sleep: `timeout 30 xdotool search --sync --onlyvisible --class firefox | head -1` prints its id (`--class xfce4-terminal`, `--class thunar`, or `--name 'regex'` for a title).
5. List windows: `xdotool search --onlyvisible --name . 2>/dev/null | while read id; do echo "$id $(xdotool getwindowname "$id")"; done` (`Desktop`, `xfce4-panel`, `Xfwm4`, `wrapper-2.0` are XFCE's own).
6. Bring one forward with the keyboard: `xdotool windowactivate --sync <id>`; send it keys with `xdotool key --clearmodifiers ctrl+l` and text with `xdotool type --delay 15 'text'`.
7. Maximise, or restore: `xdotool windowactivate --sync <id> key --clearmodifiers alt+F10`.
8. Close with keys (`ctrl+w` tab, `ctrl+q` Firefox) or `xdotool windowclose <id>`; a hung program with `pkill -f '[f]irefox'`, then wait until `pgrep -f '[f]irefox'` prints nothing before starting it again.
9. Missing program: `sudo -n true 2>/dev/null && echo root` — with root, `sudo apt-get update && sudo DEBIAN_FRONTEND=noninteractive apt-get install -y <package>`; without it, say an admin can turn sudo on.
10. End with a `computer` screenshot showing the window.

## Pitfalls

- A foreground `firefox …` never returns; the call hangs to its timeout.
- `firefox --new-tab URL` against a running Firefox hangs or shows "already running, but is not responding" — use step 3. If that dialog is up, press its OK or `windowclose` it.
- `#!bg` is refused in the workstation; `nohup … &` is the way.
- `xdotool search --sync` without `timeout` can wait forever.
- Find Firefox by `--class firefox`; its title changes with the page.
- Count terminals by window, not process: the panel's terminals share one.

## Verification

- `xdotool search --onlyvisible --class <program>` prints a window id and a screenshot shows it in front.
