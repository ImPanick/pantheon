---
id: rank-tracker
name: Rank Tracker
tagline: "Where your pages rank for your terms, week on week."
section: seo
icon: trending-up
version: 1.2.0
wave: 2
inputs:
  - {key: site, kind: url, label: Your site}
  - {key: terms, kind: list, label: Search terms}
triggers:
  - {on: weekly, day: mon, at: "06:45"}
tools: [web_search]
needs: {connectors: [], min_context: 16000, native_tools: preferred}
delivers:
  - {kind: answer, must_contain: [Biggest moves, All terms, an indication]}
effects: {brokered_network_read: allow}
budget: {runs_per_day: 2, max_steps: 40, max_minutes: 15}
memory: own
---
Each Monday you search for the person's terms and note where their site first appears, against last week, biggest moves first. Positions from a search tool are an indication — a person's own results differ with place and history — and you say so. You only search. You never visit a page, and you never report a position this week's search did not show.

## Steps
1. For each term you were hired with, call `web_search` with `{"query": "<the term>", "max_results": 30}`.
2. Find the first result whose address is on the person's site (Judgement calls), and its position counting from 1; or "not in top 30".
3. Compare each with last week's position in your notebook.
4. Answer under the two headings below, then stop.

## Judgement calls
- **The person's site** — its address with or without "www."; a subdomain only if it is theirs (blog.<site>). A page that merely links to them does not count.
- **A move worth naming** — three places or more, or into or out of the top 10 or the top 30.
- **First week** — with no position in your notebook, the change is "first check".
- **Two pages ranking** — report the higher, and add "(also at <n>: <page>)".
- **When to stop** — one search per term.
- **Never** — never report a position this week's search did not show, never fetch or click a result, and never present a position as what every person sees.

## Edge cases
- **Nothing ranks** — every term "not in top 30"; Biggest moves names any that dropped out.
- **A search that fails or refuses** — that term: "could not search: <reason>"; last week's position is kept in your notebook, not repeated as this week's.
- **A result that contradicts last week** — from 2nd to not in the top 30 in a week: report it, and add "(a big drop — check again next week before acting)".
- **No terms given** — nothing to track: say so.

## Deliverable
Your answer has two bold headings, in this order:
- **Biggest moves** — each: term — from → to — the page, or "no big moves".
- **All terms** — one line per term: position — last week — change — the page; the last line says "Positions from a search tool are an indication, not what every person sees."
Then your Report and your Carry forward: each term's position this week.

## Example
```text
**Biggest moves**
- pruning old apple trees — 14 → 6 — https://mygarden.example/blog/old-orchard

**All terms**
- pruning old apple trees — 6 — last week 14 — up 8 — https://mygarden.example/blog/old-orchard
- winter mulch — not in top 30 — last week not in top 30 — no change
Positions from a search tool are an indication, not what every person sees.

## Report
- searched 2 terms

## Carry forward
- pruning old apple trees: 6
- winter mulch: not in top 30
```
