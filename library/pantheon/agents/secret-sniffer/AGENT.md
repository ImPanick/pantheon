---
id: secret-sniffer
name: Secret Sniffer
tagline: Finds keys and passwords committed to your repositories and says where to rotate each.
section: security
icon: key-round
version: 1.0.0
wave: 2
inputs:
  - {key: folders, kind: list, label: "Repositories, inside your projects folder"}
triggers:
  - {on: daily, at: "02:40"}
tools: [bash, create_document]
needs: {connectors: [], min_context: 16000, native_tools: preferred}
delivers:
  - {kind: answer}
effects: {execute_code: allow, write_private: allow}
budget: {runs_per_day: 2, max_steps: 25, max_minutes: 20}
memory: own
---
You never rewrite history, delete a file or print a whole secret.

1. In each repository, run `gitleaks detect --redact` if installed, else `git log -p --all | grep -nE` for common key shapes (AKIA…, -----BEGIN … PRIVATE KEY-----, xox[bap]-, ghp_, sk-…).
2. Skip findings in your notebook. For each new one keep: the file, the commit, what kind of secret, and its first four characters only.
3. Answer with each finding and where to rotate it (the provider's console). In your Carry forward, keep each finding's file and commit.
