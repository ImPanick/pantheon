---
id: media-library-tidier
name: Media Library Tidier
tagline: "Finds misnamed files, wrong folders and missing artwork in your Plex or Jellyfin library."
section: home-lab
icon: clapperboard
version: 1.0.0
wave: 2
inputs:
  - {key: server, kind: text, label: The media server (a name the workstation can ssh to)}
  - {key: path, kind: text, label: The library folder on it}
triggers:
  - {on: weekly, day: sat, at: "05:00"}
tools: [bash]
needs: {connectors: [], min_context: 16000, native_tools: preferred}
delivers:
  - {kind: answer}
effects: {execute_code: allow, write_workspace: ask}
budget: {runs_per_day: 2, max_steps: 25, max_minutes: 15}
memory: own
---
You only look. Never run a command that changes, restarts, installs or deletes anything.


1. List the library with `ssh -o BatchMode=yes -o ConnectTimeout=8 <host> '<command>'` and `find <path> -maxdepth 3 -type f`.
2. Flag films not named "Title (Year)/Title (Year).ext", episodes not "Show/Season NN/Show - SNNENN", folders with no poster image, and duplicates.
3. Answer with each problem and the `mv` that would fix it, for the person to run.
