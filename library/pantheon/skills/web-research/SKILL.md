---
name: web-research
description: Answer from the web properly: several searches, read the real sources, cross-check claims and dates, cite where each fact came from; hand big topics to deep research.
version: 1.0.0
category: core
tags: [research, web, search, internet, sources, citations, cite, facts, news, latest, compare, look, find, verify, fact-check, lookup]
requires_toolsets: [web_search, web_fetch]
status: published
confidence: 0.95
source: pantheon
---

## When to Use

The answer depends on facts you cannot be sure of from memory: anything recent, prices, versions, laws, people, products, statistics, or a comparison the person will act on.

## Procedure

1. Pin down the question: what exactly must be true for the answer, and how recent it must be.
2. Search with `web_search`, two or three phrasings rather than one. Add `time_filter` (`day`, `week`, `month`, `year`) for news or "latest". Include the official name, product or site when you know it.
3. Pick sources by who would know: the official site, documentation, the primary paper or filing, a reputable outlet. Avoid content farms and copies of copies.
4. Open the best two to four with `web_fetch` and read the part that answers the question. A search snippet is not a source. If the result says `[partial content: ...]` and you need the rest, call again with `full: true`.
5. Cross-check: a key fact should agree across two independent sources, or come from the primary one. Note the date on each; prefer the newest authoritative one when they differ, and say that they differ.
6. Answer first, then the support: each claim with the source it came from (title and URL), and what you could not confirm.
7. For a broad "research X" job — many sources, a report — say so, and offer a deep research job instead of a long run of searches here.

## Pitfalls

- One search, first result, done.
- Quoting a figure without its date or source.
- Treating a forum post or an AI-generated page as authoritative.
- Filling a gap the sources did not cover with a guess presented as fact.

## Verification

- Every factual claim in the answer can be traced to a page you actually opened, and anything unconfirmed is labelled as such.
