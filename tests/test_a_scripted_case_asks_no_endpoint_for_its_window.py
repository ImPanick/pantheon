# SPDX-License-Identifier: AGPL-3.0-or-later
"""`P24-27` — a scripted evaluation asks no endpoint how large its model is.

The harness promises that a case "never reaches the internet, a mailbox or a
host". With the scripted model it still asked the scripted endpoint
(`127.0.0.1:9`, the discard port) for its context window — about twice per
run, each through a fresh HTTP client that loads the system's certificates —
and always got the same answer: nothing there, so the default window. Measured
on Fact Checker's seven cases: 4.1 of 9.2 seconds, 45% of the time, which at
104 agents is most of the bar's nine minutes. The scripted model's window is
the default, said once; a real endpoint (a proof run) is still asked.
"""

from __future__ import annotations

import asyncio

from src.agents import evals as E
from src.agents.catalogue import get_agent

CASE = {"id": "probe", "about": "probe", "script": [{"say": "**Answer**\nx\n\n**From the handbook**\n- nothing\n\n## Report\n- x"}],
        "inputs": {"handbook": "Staff handbook", "question": "Anything?"}, "checks": []}


def test_a_scripted_case_sends_nothing_to_the_scripted_endpoint(monkeypatch):
    import src.paced_http as paced_http
    asked = []
    real = paced_http.request_sync

    def spy(method, url, *a, **kw):
        asked.append(url)
        return real(method, url, *a, **kw)

    monkeypatch.setattr(paced_http, "request_sync", spy)
    m = get_agent(None, "policy-answerer")
    results = asyncio.run(E.run_agent(m, cases=[CASE]))
    assert results and results[0].status == "success", results[0].to_dict() if results else "no result"
    assert not [u for u in asked if "127.0.0.1:9" in u], asked


def test_the_window_it_is_given_is_the_one_the_endpoint_would_have_given():
    """The same answer the real query gives for the scripted endpoint — the
    default window, marked as a fallback — so nothing downstream changes."""
    from src import model_context as mc
    url = E.SCRIPTED_URL + "/chat/completions"   # what a run asks with
    real = mc._query_context_length(url, E.SCRIPTED_MODEL)
    assert E.scripted_window(url, E.SCRIPTED_MODEL) == real == (mc.DEFAULT_CONTEXT, False, mc.BASIS_FALLBACK)
