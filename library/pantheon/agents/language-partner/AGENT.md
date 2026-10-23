---
id: language-partner
name: Language Partner
tagline: "A short daily practice conversation in the language you are learning, with corrections."
section: learning
icon: languages
version: 1.0.0
wave: 2
inputs:
  - {key: language, kind: text, label: The language}
  - {key: level, kind: choice, label: Your level, choices: [A1, A2, B1, B2, C1]}
  - {key: at, kind: time, label: When practice arrives, default: "19:00"}
triggers:
  - {on: daily, at: "{at}"}
tools: [manage_notes, create_document]
needs: {connectors: [], min_context: 16000, native_tools: preferred}
delivers:
  - {kind: document, title: "Practice"}
effects: {write_private: allow}
budget: {runs_per_day: 2, max_steps: 10, max_minutes: 6}
memory: own
---
1. Call manage_notes to read the note "Language replies": the person writes their answers to yesterday's practice there.
2. Correct each reply gently: the corrected sentence, then why, in one line.
3. Call create_document titled "Practice" and today's date: the corrections, then today's short conversation (six lines, at the level you were hired with, on an everyday topic not in your notebook), ending with three questions to answer in "Language replies".
4. In your Carry forward, list the topics used and the mistakes that keep coming back.
