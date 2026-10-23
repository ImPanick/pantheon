---
id: api-mocker
name: API Mocker
tagline: A runnable mock server and fixtures from an API spec.
section: development
icon: server-cog
version: 1.0.0
wave: 2
inputs:
  - {key: spec, kind: text, label: "The OpenAPI file, inside your projects folder"}
  - {key: out, kind: text, label: Folder to write the mock into}
triggers:
  - {on: hand}
tools: [read_file, write_file, bash, ls]
needs: {connectors: [], min_context: 32000, native_tools: required}
delivers:
  - {kind: answer}
effects: {read_workspace: allow, write_workspace: allow, execute_code: allow}
budget: {runs_per_day: 4, max_steps: 40, max_minutes: 25}
memory: none
---
1. Read the spec with read_file.
2. Write a small mock server (Python, standard library or FastAPI if installed) into the folder you were hired with: one handler per operation answering an example from the spec, and a fixtures/ folder with those examples as JSON.
3. Start it in the background for a few seconds with bash and call two endpoints with curl to check, then stop it.
4. Answer with how to run it and which operations have no example (they answer an empty object).
