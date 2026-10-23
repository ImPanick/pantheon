---
id: tax-folder-builder
name: Tax Folder Builder
tagline: "Gathers the year's tax documents into one folder with a checklist."
section: finance
icon: folder-check
version: 1.0.0
wave: 2
inputs:
  - {key: year, kind: number, label: The tax year}
  - {key: folder, kind: folder, label: "Where to build it, inside your projects folder"}
triggers:
  - {on: hand}
tools: [search_emails, read_email, download_attachment, ls, create_document]
needs: {connectors: [], min_context: 16000, native_tools: preferred}
delivers:
  - {kind: document, title: "Tax checklist"}
effects: {read_private: allow, write_workspace: allow, read_workspace: allow, write_private: allow}
budget: {runs_per_day: 3, max_steps: 60, max_minutes: 30}
memory: none
---
This is organisation, not tax advice; say so at the top of the checklist.

1. Call search_emails for the year's income statements, interest and dividend statements, donation receipts, pension and insurance statements.
2. download_attachment each into the folder under a subfolder per kind.
3. Call create_document titled "Tax checklist" and the year: what was found, and what is usually needed but missing.
