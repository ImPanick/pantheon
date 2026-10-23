---
id: story-writer
name: Story Writer
tagline: "Fiction, bedtime stories or game lore in a voice you set."
section: creative
icon: feather
version: 1.0.0
wave: 2
inputs:
  - {key: brief, kind: long_text, label: What the story is about}
  - {key: voice, kind: text, label: The voice or style, optional: true}
  - {key: words, kind: number, label: About how many words, default: 800}
triggers:
  - {on: hand}
tools: [create_document]
needs: {connectors: [], min_context: 16000, native_tools: preferred}
delivers:
  - {kind: document, title: "Story"}
effects: {write_private: allow}
budget: {runs_per_day: 6, max_steps: 6, max_minutes: 8}
memory: own
---
1. Write an original story from the brief, in the voice you were hired with, close to the length asked. Never borrow characters, names or passages from published work.
2. Call create_document titled "Story" and a title you give it.
3. In your Carry forward, keep the names and facts you invented, so a later story in the same world stays consistent.
