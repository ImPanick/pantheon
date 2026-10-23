---
id: policy-checker
name: Policy Checker
tagline: "Checks a document or config against a policy you supply, rule by rule."
section: security
icon: file-check
version: 1.0.0
wave: 2
inputs:
  - {key: subject, kind: text, label: The document or config file to check}
  - {key: policy, kind: text, label: The policy document title}
triggers:
  - {on: hand}
tools: [manage_documents, read_file, create_document]
needs: {connectors: [], min_context: 16000, native_tools: preferred}
delivers:
  - {kind: document, title: "Policy check"}
effects: {write_private: allow, read_workspace: allow}
budget: {runs_per_day: 6, max_steps: 20, max_minutes: 10}
memory: none
---
1. Read the policy and the subject (manage_documents for a document, read_file for a file in your projects folder).
2. For each rule in the policy, mark the subject **meets**, **breaks** or **not covered**, quoting the line that decides it.
3. Call create_document titled "Policy check" and the subject: breaks first.
