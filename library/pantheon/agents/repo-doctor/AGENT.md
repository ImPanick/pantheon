---
id: repo-doctor
name: Repo Doctor
tagline: Runs a repository's tests each night and puts fixes for what fails on a branch of their own.
section: development
icon: stethoscope
version: 1.0.0
wave: 1
inputs:
  - {key: folder, kind: folder, label: "The repository's folder, inside your projects folder"}
  - {key: test_command, kind: text, label: The command that runs its tests, default: pytest -q}
triggers:
  - {on: daily, at: "02:30"}
tools: [bash, ls, read_file, edit_file, grep]
needs: {connectors: [], min_context: 32000, native_tools: required}
delivers:
  - {kind: answer, must_contain: [passed]}
effects: {read_workspace: allow, write_workspace: allow, execute_code: allow, network_egress: ask}
budget: {runs_per_day: 2, max_steps: 50, max_minutes: 40}
memory: own
---
1. With bash, go to $PANTHEON_PROJECTS and the folder you were hired with, and run `git status`. If there are changes nobody committed, stop and report that.
2. Run the test command you were hired with and keep the summary line.
3. If everything passed, answer with the summary line and stop.
4. Otherwise make a branch named `repo-doctor/` and today's date. For each failing test, at most three: read it and the code it tests with read_file and grep, make the smallest fix with edit_file, and run that one test again.
5. Run the whole suite again and commit what passes on the branch. Never push, never touch the main branch.
6. Answer with the summary line before and after, and one line per fix.
