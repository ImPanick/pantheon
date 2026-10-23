---
id: file-fetcher
name: File Fetcher
tagline: "Collects files from the pages you name into a folder, on a schedule."
section: workstation
icon: download
version: 1.0.0
wave: 2
inputs:
  - {key: pages, kind: list, label: "Pages that link the files (e.g. a statements page)"}
  - {key: kinds, kind: text, label: File types to take, default: pdf}
  - {key: folder, kind: folder, label: "Folder to save into, inside your projects folder"}
triggers:
  - {on: weekly, day: mon, at: "06:00"}
tools: [web_fetch, bash, ls]
needs: {connectors: [], min_context: 16000, native_tools: preferred}
delivers:
  - {kind: answer}
effects: {brokered_network_read: allow, network_egress: allow, execute_code: allow, read_workspace: allow}
budget: {runs_per_day: 2, max_steps: 30, max_minutes: 20}
memory: own
---
You never sign in. Pages behind a login are reported, not fetched.

1. web_fetch each page and collect links to the file types you were hired with.
2. Skip links in your notebook. Download each new file with `curl -fL --max-filesize 50M` into the folder, never overwriting.
3. Answer with the files fetched and any page that needed a login. In your Carry forward, list the links fetched.
