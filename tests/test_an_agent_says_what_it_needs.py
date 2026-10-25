# SPDX-License-Identifier: AGPL-3.0-or-later
"""`B1448` — an agent's declared `needs` is checked against the model it would
run on, and says so.

The 2026-10-25 audit: `needs.min_context` and `needs.native_tools` were
validated by `manifest.py` and returned by the hall's API, and nothing read
them — 162 shipped agents named a window and 20 required native tool calls, and
an agent hired on an 8K fenced-only model ran with no word about either.

Now (`src/agents/needs.py`): the hall's card and detail page carry a
`needs_check`, and a hired agent's run records a progress line, whenever the
route has *less than the agent declared* — a window known to be smaller, or an
endpoint set to the fenced tool form when the agent requires native calls. It
warns; it never refuses. And it says nothing it can't back: an unknown window
is not evidence a model is too small.
"""

from __future__ import annotations

from types import SimpleNamespace

from src.agents import needs as NE


# ── the rule ─────────────────────────────────────────────────────────────────

def test_a_known_smaller_window_is_named():
    short = NE.shortfall({"min_context": 32000}, {"model": "tiny-8k", "context": 8192, "tools": "both"})
    assert len(short) == 1 and "32K" in short[0] and "tiny-8k" in short[0]


def test_an_unknown_window_warns_nothing():
    assert NE.shortfall({"min_context": 32000}, {"model": "m", "context": None, "tools": "both"}) == []


def test_a_big_enough_window_warns_nothing():
    assert NE.shortfall({"min_context": 16000}, {"model": "m", "context": 131072, "tools": "native"}) == []


def test_required_native_tools_on_a_fenced_endpoint_is_named():
    short = NE.shortfall({"native_tools": "required"}, {"model": "m", "context": None, "tools": "fenced"})
    assert len(short) == 1 and "natively" in short[0]


def test_preferred_or_undeclared_tool_transport_warns_nothing():
    # `both` means nobody said — the schemas are sent, so it is not a shortfall.
    assert NE.shortfall({"native_tools": "required"}, {"model": "m", "context": None, "tools": "both"}) == []
    assert NE.shortfall({"native_tools": "preferred"}, {"model": "m", "context": None, "tools": "fenced"}) == []


# ── the facts come from the same places the loop reads ───────────────────────

def test_route_facts_reads_the_known_window_and_the_schema_offer(monkeypatch):
    import src.model_context as MC
    import src.agent_loop as AL
    monkeypatch.setattr(MC, "get_context_length_known", lambda url, model: (8192, True))
    monkeypatch.setattr(AL, "_agent_route_schema_offer", lambda url, model, owner=None: "fenced")
    f = NE.route_facts("http://gpu.lan:8000/v1", "small", "ada")
    assert f == {"model": "small", "context": 8192, "tools": "fenced"}
    # a fallback window is not a fact
    monkeypatch.setattr(MC, "get_context_length_known", lambda url, model: (131072, False))
    assert NE.route_facts("http://gpu.lan:8000/v1", "small")["context"] is None
    # no route, no facts
    assert NE.route_facts(None, None) == {"model": None, "context": None, "tools": None}


# ── a shipped agent, end to end through the hall's check and the run's lines ──

def test_a_shipped_agent_that_requires_native_tools_is_warned_about(monkeypatch):
    from src.agents.catalogue import get_agent
    m = get_agent(None, "browser-runner")
    assert m is not None and m.needs["native_tools"] == "required" and m.needs["min_context"] == 32000
    got = NE.check(m, {"model": "small", "context": 8192, "tools": "fenced"})
    assert got["model"] == "small" and len(got["short"]) == 2

    monkeypatch.setattr(NE, "route_facts",
                        lambda url, model, owner=None: {"model": model, "context": 8192, "tools": "fenced"})
    plan = SimpleNamespace(owner=None, agent_id="browser-runner", name="Browser runner")
    lines = NE.run_warnings(plan, "http://gpu.lan:8000/v1", "small")
    assert len(lines) == 2 and all(line.startswith("Browser runner: ") for line in lines)
    assert NE.run_warnings(None, "u", "m") == []


def test_a_warning_that_cannot_be_worked_out_never_stops_the_run(monkeypatch):
    def boom(*a, **k):
        raise RuntimeError("endpoint table unreadable")
    monkeypatch.setattr(NE, "route_facts", boom)
    plan = SimpleNamespace(owner=None, agent_id="browser-runner", name="Browser runner")
    assert NE.run_warnings(plan, "u", "m") == []


def test_the_scheduler_and_the_hall_both_ask():
    """Both doors read the one module — the scheduler records the lines, the
    hall's list and detail carry `needs_check`."""
    from pathlib import Path
    root = Path(__file__).resolve().parent.parent
    sched = (root / "src" / "task_scheduler.py").read_text(encoding="utf-8")
    routes = (root / "routes" / "agent_routes.py").read_text(encoding="utf-8")
    ui = (root / "static" / "js" / "agents" / "agentsWindow.js").read_text(encoding="utf-8")
    assert "run_warnings" in sched
    assert routes.count("needs_check") >= 2
    assert "needs_check" in ui
