# SPDX-License-Identifier: AGPL-3.0-or-later
"""The reasoning cache: a model's finished work, kept as code a small model can rerun.

NVIDIA's CPU-ARC (*Agentic Reasoning Caching for on-CPU Reasoning Reuse*,
arXiv 2611.09891) in Pantheon. When a run finishes cleanly, a builder model
turns its transcript into small Python functions with the request's inputs
pulled out as parameters. The next request of the same kind, with a different
payload, is answered by running that code: a small model only pulls the
parameters out of the words and does the little reads and checks the code
asks for. The big model is not called at all. Any miss, error or refusal falls
through to the model exactly as before, so the worst case is today's turn plus
one lookup.

  * `sandbox` — checks model-written code against an allowlist and runs it in a
                separate, limited process; the parent answers its calls;
  * `store`   — entries per person and per scope (a chat, an Apollo space, a
                scheduled task, a hired agent), never shared across either;
  * `roles`   — which model builds, which extracts, which judges (settings);
  * `invoke`  — match a request, pull its parameters, run the entry;
  * `builder` — the paper's build: isolate, decompose, parameterise, plan,
                implement, then check against the original and round-trip;
  * `gate`    — the one place a run consults the cache: Off, Shadow, Live.

Every entry starts in Shadow: the model still answers, and the entry's answer
is judged against it afterwards. Only after `reasoning_cache_agreements`
agreements in a row does it go Live, and only a person who chose Live is ever
answered from it. An entry whose code would send, write or delete is never
built: its tools must all be reads (`sandbox.READ_EFFECTS`).
"""
