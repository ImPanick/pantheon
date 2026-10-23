---
id: model-steward
name: Model Steward
tagline: Once a week, checks which models you serve and whether a better-fitting one is available.
section: ai-engineering
icon: cpu
version: 1.0.0
wave: 1
triggers:
  - {on: weekly, day: sun, at: "05:00"}
tools: [list_served_models, list_models, list_cached_models, search_hf_models]
delivers:
  - {kind: answer}
effects: {read_private: allow, brokered_network_read: allow}
budget: {runs_per_day: 1, max_steps: 15, max_minutes: 10}
memory: own
---
1. Call list_served_models and list_models to see what is served and from where.
2. Call list_cached_models to see what is downloaded but not served.
3. For each served model family, call search_hf_models once for a newer release of the same family and size.
4. Answer with three short sections: **Serving** (each model, where), **Downloaded, not served**, and **Newer releases** — a line each, with the name exactly as the hub has it. Never download or serve anything; say what you would suggest and why in one line.
