---
name: workstation-shell
description: Run commands, install tools and keep programs running inside the workstation — its own Ubuntu machine where you may be root — and know which folder is shared with Pantheon.
version: 1.0.0
category: workstation
tags: [workstation, shell, bash, terminal, command, run, install, apt, sudo, root, server, background, vm, sandbox, projects, linux, ubuntu]
requires_toolsets: [computer, bash]
status: published
confidence: 0.95
source: pantheon
---

## When to Use

Running commands, installing packages, building code or starting a server while the workstation is on. It is a separate Ubuntu 24.04 machine: bash, python and the file tools run inside it as the person's own account, so breaking things there cannot harm Pantheon — that is what it is for.

## Procedure

1. Once per task: `echo "$USER $HOME"; pwd; ls /projects`. The result says `ran_in: "workstation"` when it ran there; if not, you are on Pantheon's own machine — install nothing system-wide.
2. Build projects in `/projects/<project-name>/` — the folder Pantheon keeps as its projects folder, so the person sees the work after the turn. `$HOME` is private to the workstation. Pantheon's own data is deliberately out of reach; do not look for it.
3. Every call is a fresh shell; only the current folder carries over. Chain what belongs together: `cd /projects/app && . .venv/bin/activate && pytest -q`.
4. Root: `sudo -n true 2>/dev/null && echo root || echo no-root`. With root: `sudo apt-get update && sudo DEBIAN_FRONTEND=noninteractive apt-get install -y nodejs npm` (any package). Without: `python3 -m venv .venv && .venv/bin/pip install …`, `npm install` in the project, binaries in `~/.local/bin` (on `PATH`). Need root and lack it? Say an admin can turn sudo on.
5. Network: `curl -sS -o /dev/null -w '%{http_code}\n' https://pypi.org`. The admin sets it (full, internet only, none); if off, say so and use what is installed.
6. Long-running programs start detached with a log: `cd /projects/app && nohup python3 -m http.server 8000 > /tmp/server.log 2>&1 < /dev/null &`. Wait for an answer, not a guess: `for i in $(seq 60); do curl -fsS -o /dev/null http://127.0.0.1:8000/ 2>/dev/null && echo up && break; sleep 0.5; done`; no answer → read the log.
7. `pgrep -af <name>` finds processes; `pkill -f '[p]attern'` stops them (the brackets keep it from matching itself). Stop what you started when done unless asked to leave it running.
8. A long build or test run may stay in the foreground — output streams to the person, up to an hour. Add `2>&1 | tail -n 200` when only the end matters.
9. Programs with windows appear on the desktop (`DISPLAY` is set): see workstation-apps-and-windows and workstation-desktop.

## Pitfalls

- `#!bg` is refused in the workstation; use `nohup … > log 2>&1 < /dev/null &`.
- A background program still writing to the call's output holds the call open; redirect it.
- A venv or `export` from an earlier call is gone in the next.
- `sudo` without the rule waits for a password: check `sudo -n true` first; always `apt-get -y`.
- Building in `$HOME` when the person asked for a project hides it from them; use `/projects/<name>`.

## Verification

- Exit code 0 and output that says what you claim; for a server, `curl` answers.
