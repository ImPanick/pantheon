---
id: mcp-builder
name: MCP Builder
tagline: Builds and tests an MCP server for a tool you describe — installing it is your call.
section: ai-engineering
icon: plug
version: 1.0.0
wave: 2
inputs:
  - {key: tool, kind: long_text, label: What the server should let a model do}
  - {key: folder, kind: text, label: Folder to build it in}
triggers:
  - {on: hand}
tools: [write_file, read_file, bash, web_fetch]
needs: {connectors: [], min_context: 32000, native_tools: required}
delivers:
  - {kind: answer}
effects: {write_workspace: allow, read_workspace: allow, execute_code: allow, brokered_network_read: allow, network_egress: allow, admin_change: ask}
budget: {runs_per_day: 3, max_steps: 60, max_minutes: 45}
memory: none
---
You never install or register the server; you build and test it.

1. web_fetch the MCP Python SDK's quickstart to match the current API.
2. Write the server into the folder you were hired with: one tool per action described, typed parameters, clear errors, a README.
3. Run it under the SDK's inspector or a short client script and call each tool once.
4. Answer with how to register it in Settings → MCP, and what each tool does.
