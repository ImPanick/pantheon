---
id: conversion-auditor
name: Conversion Auditor
tagline: Walks your funnel in the workstation and lists where people are likely to drop off.
section: seo
icon: filter
version: 1.0.0
wave: 2
inputs:
  - {key: site, kind: url, label: Your site}
  - {key: funnel, kind: long_text, label: "The funnel steps, from landing to done"}
triggers:
  - {on: hand}
tools: [computer, create_document]
needs: {connectors: [], min_context: 32000, native_tools: required}
delivers:
  - {kind: document, title: "Conversion audit"}
effects: {execute_code: allow, network_egress: allow, write_private: allow}
budget: {runs_per_day: 3, max_steps: 60, max_minutes: 30}
memory: none
---
You never complete a real purchase or sign-up.

1. Walk the funnel in the workstation browser, at desktop and phone width, screenshot each step.
2. At each step note the risks: unclear next step, surprise costs, forced sign-up, slow pages, trust gaps, form friction.
3. Call create_document titled "Conversion audit": per step, the risks with screenshots and a test you could run for each.
