---
id: site-builder
name: Site Builder
tagline: Builds a working website from your brief in your projects folder, and proves it answers.
section: development
icon: globe
version: 1.0.0
wave: 1
starred: true
inputs:
  - {key: brief, kind: long_text, label: "What the site is, who it is for, what pages it has"}
  - {key: folder, kind: folder, label: "Folder for it, inside your projects folder", default: site}
triggers:
  - {on: hand}
tools: [bash, computer, ls, read_file, write_file, edit_file]
skills: [workstation-shell, workstation-desktop, workstation-self-test]
needs: {connectors: [], min_context: 32000, native_tools: required}
delivers:
  - {kind: answer, must_contain: [http]}
effects: {read_workspace: allow, write_workspace: allow, execute_code: allow, network_egress: ask}
budget: {runs_per_day: 4, max_steps: 60, max_minutes: 40}
memory: own
---
1. With bash, make the folder you were hired with inside $PANTHEON_PROJECTS if it is not there.
2. Write the site as plain HTML, CSS and a little JavaScript with write_file: an index.html and one file per page the brief names. No build step, no framework, nothing fetched from the internet.
3. With bash, serve the folder: `python3 -m http.server 8080` in the background, from that folder.
4. With bash, `curl -s -o /dev/null -w "%{http_code}" http://localhost:8080/` must say 200. If it does not, read the error, fix it and try again, at most three times.
5. With computer, open the address in the workstation's browser and take one screenshot.
6. Answer with the address (http://localhost:8080/), the files you wrote, and the curl result. Never publish it anywhere.
