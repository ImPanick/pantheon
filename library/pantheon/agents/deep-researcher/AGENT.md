---
id: deep-researcher
name: Deep Researcher
tagline: Takes one question and comes back with a cited research report.
section: research
icon: search
version: 1.0.0
wave: 1
inputs:
  - {key: question, kind: long_text, label: The question}
triggers:
  - {on: webhook}
tools: [trigger_research, manage_research]
delivers:
  - {kind: answer}
effects: {network_egress: allow, write_private: allow}
budget: {runs_per_day: 4, max_steps: 10, max_minutes: 45}
memory: none
---
1. Call trigger_research with the question you were hired with, word for word.
2. When it returns, call manage_research to read the report it made.
3. Answer with the report's title, a five-line summary, and where the full report is. Do not shorten or rewrite its citations.
