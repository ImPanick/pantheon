---
id: dependency-watch
name: Dependency Watch
tagline: Each week, finds a project's outdated and vulnerable packages and tries an upgrade on a branch.
section: development
icon: package
version: 1.0.0
wave: 1
inputs:
  - {key: folder, kind: folder, label: "The project's folder, inside your projects folder"}
  - {key: test_command, kind: text, label: The command that runs its tests, default: pytest -q}
triggers:
  - {on: weekly, day: mon, at: "03:00"}
tools: [bash, read_file, edit_file]
needs: {connectors: [], min_context: 24000, native_tools: required}
delivers:
  - {kind: answer, must_contain: [outdated]}
effects: {read_workspace: allow, write_workspace: allow, execute_code: allow, network_egress: allow}
budget: {runs_per_day: 1, max_steps: 40, max_minutes: 40}
memory: own
---
1. With bash, go to $PANTHEON_PROJECTS and the folder you were hired with. Find what manages its packages: requirements.txt or pyproject.toml (pip), or package.json (npm).
2. List what is outdated: `pip list --outdated` or `npm outdated`. For npm, also run `npm audit --omit=dev`.
3. Make a branch named `dependency-watch/` and today's date. Raise each outdated package one minor version at a time, then run the test command you were hired with.
4. Keep the upgrades that pass, put back the ones that fail, and commit on the branch. Never push.
5. Answer with a list headed "outdated": each package, from and to, and whether it passed — then the audit's warnings.
