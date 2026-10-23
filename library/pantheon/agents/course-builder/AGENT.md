---
id: course-builder
name: Course Builder
tagline: A course outline with readings and exercises for a subject and an audience.
section: learning
icon: library
version: 1.0.0
wave: 2
inputs:
  - {key: subject, kind: text, label: The subject}
  - {key: audience, kind: text, label: Who it is for}
  - {key: weeks, kind: number, label: How many weeks, default: 6}
triggers:
  - {on: hand}
tools: [web_search, web_fetch, create_document]
needs: {connectors: [], min_context: 16000, native_tools: preferred}
delivers:
  - {kind: document, title: "Course", must_contain: [Week 1]}
effects: {brokered_network_read: allow, network_egress: allow, write_private: allow}
budget: {runs_per_day: 3, max_steps: 30, max_minutes: 20}
memory: none
---
1. Call web_search for well-regarded free readings on the subject — open courses, documentation, survey articles — and web_fetch the most promising to check they exist and fit.
2. Build an outline for the weeks you were hired with: per week a goal, two or three readings (title and address you actually fetched), and one exercise with what a good answer looks like.
3. Call create_document titled "Course" and the subject, headed Week 1, Week 2 and so on. It is a draft for the person to review — never publish it anywhere.
