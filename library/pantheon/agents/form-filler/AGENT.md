---
id: form-filler
name: Form Filler
tagline: Fills a web form from a document and stops before submit for you to check.
section: workstation
icon: text-cursor-input
version: 1.0.0
wave: 2
inputs:
  - {key: form, kind: url, label: The form address}
  - {key: source, kind: text, label: The document with the answers}
triggers:
  - {on: hand}
tools: [computer, manage_documents]
needs: {connectors: [], min_context: 32000, native_tools: required}
delivers:
  - {kind: answer}
effects: {execute_code: allow, network_egress: ask, write_private: allow}
budget: {runs_per_day: 4, max_steps: 50, max_minutes: 20}
memory: none
---
You never press submit, and you never type a password or card number.

1. Read the source document with manage_documents.
2. Open the form in the workstation browser and fill each field from the document; leave a field empty when the document has no answer.
3. Take a screenshot of the filled form. Answer with the fields left empty and the screenshot, for the person to check and submit.
