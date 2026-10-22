---
name: workstation-self-test
description: Prove what you built works by running it in the workstation — build, start, check it answers, look at it in Firefox, read its errors, fix, repeat — before telling the person it is done.
version: 1.0.0
category: workstation
tags: [workstation, test, testing, verify, check, run, preview, website, site, web, app, page, html, server, localhost, browser, firefox, screenshot, console, debug, build, vm]
requires_toolsets: [computer, bash]
status: published
confidence: 0.95
source: pantheon
---

## When to Use

After building or changing anything that runs — a site, a web app, a script, a CLI, an API — and before saying it works. The workstation is a real machine with a browser: "it works" should rest on something you ran and saw.

## Procedure

1. Put the project in `/projects/<name>/` and write files with the file tools.
2. Cheapest check first: the project's tests or a syntax check (`python3 -m py_compile app.py`, `node --check app.js`, `pytest -q`). Fix failures before going on.
3. Start it detached with a log: `cd /projects/<name> && nohup python3 -m http.server 8000 > /tmp/<name>.log 2>&1 < /dev/null &` (or `nohup npm run dev -- --port 5173 > …`).
4. Wait, then fetch: `for i in $(seq 60); do curl -fsS -o /dev/null http://127.0.0.1:8000/ 2>/dev/null && break; sleep 0.5; done; curl -sS -w '\nHTTP %{http_code}\n' http://127.0.0.1:8000/ | tail -n 20`. No answer → read `/tmp/<name>.log`, fix, restart. Check every route you added.
5. Open it in the desktop's Firefox (workstation-apps-and-windows, step 3), take a `computer` `screenshot`, and click through what you built — links, buttons, forms — with a screenshot after each.
6. Errors: `ctrl+shift+k` in Firefox shows the console — red lines are JavaScript errors with file and line; `F12` closes it. Server errors are in the log.
7. Fix, reload (`ctrl+shift+r` skips the cache) and look again; repeat 4–7 until page, console and log are clean.
8. A picture for the person, no screen needed: `firefox --headless --no-remote --profile "$(mktemp -d)" --window-size=1280,800 --screenshot /projects/<name>/screenshot.png http://127.0.0.1:8000/` (works beside an open Firefox). File tools return text, so you see pages through `computer`.
9. Report with evidence — commands run, HTTP codes, what the last screenshot shows, anything unchecked and why — then stop the server unless asked to keep it (`pkill -f '[h]ttp.server 8000'`).

## Pitfalls

- Success from the code or a 200 alone: a page can answer 200 and render blank from one JavaScript error. Look at it and at the console.
- A server in the foreground never returns.
- "Address already in use": stop the old server or use another port.
- Without `--no-remote` and a fresh `--profile`, the headless shot collides with the desktop's Firefox.

## Verification

- `curl` answers 200 on each route, the console has no red errors, and the last screenshot shows the feature working.
