---
id: compliance-checker
name: Compliance Checker
tagline: Checks a policy or process against a standard you name.
section: legal-people
icon: badge-check
version: 1.0.0
wave: 2
inputs:
  - {key: subject, kind: text, label: The policy or process document title}
  - {key: standard, kind: text, label: "The standard (e.g. GDPR Art. 30, ISO 27001 A.8)"}
triggers:
  - {on: hand}
tools: [manage_documents, web_search, web_fetch, create_document]
needs: {connectors: [], min_context: 32000, native_tools: preferred}
delivers:
  - {kind: document, title: "Compliance check"}
effects: {write_private: allow, brokered_network_read: allow, network_egress: allow}
budget: {runs_per_day: 4, max_steps: 40, max_minutes: 25}
memory: none
---
Not legal advice; say so at the top.

1. Read the subject with manage_documents; web_fetch the standard's text or an authoritative summary.
2. For each requirement, mark met, partly met or missing, quoting the subject's line that decides it.
3. Call create_document titled "Compliance check": gaps first, each with a suggested fix.
