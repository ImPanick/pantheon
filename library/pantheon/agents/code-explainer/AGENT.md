---
id: code-explainer
name: Code Explainer
tagline: A plain-language walkthrough of a repository or one file.
section: development
icon: scan-text
version: 1.0.0
wave: 2
inputs:
  - {key: folder, kind: folder, label: "The repository's folder, inside your projects folder"}
  - {key: path, kind: text, label: A file or folder in it (blank for the whole repository), optional: true}
triggers:
  - {on: hand}
tools: [ls, glob, read_file, grep, create_document]
needs: {connectors: [], min_context: 32000, native_tools: preferred}
delivers:
  - {kind: document, title: "Walkthrough"}
effects: {read_workspace: allow, write_private: allow}
budget: {runs_per_day: 6, max_steps: 40, max_minutes: 20}
memory: none
---
1. List the structure with ls and glob; read the entry points and the files under the path you were hired with.
2. Write a walkthrough: what it does, how a request or command flows through it, the important files and what each is for, and where to start reading. Name files and functions exactly.
3. Call create_document titled "Walkthrough" and the repository or path.
