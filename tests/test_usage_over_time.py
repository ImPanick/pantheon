# SPDX-License-Identifier: AGPL-3.0-or-later
"""Usage over time, per model and per owner (`P14-05`).

The question that started `P14`. Not *what has this session cost* — the session
row always knew that — but *what did last Tuesday cost*, and *is this model
cheaper than that one*. Until `P14-01` the timestamp was discarded at write, so
there was nothing to plot.

Two properties here are easy to get wrong and both actively mislead:

  - **quiet days must appear.** A series that omits a day with no traffic draws
    a straight line from Monday to Wednesday, and a gap that reads as continuity
    is the one way a usage chart lies rather than merely disappoints.
  - **it must aggregate in SQL.** `B29` was exactly this function's sibling
    pulling every row into Python to add integers, on a table designed to
    accumulate.
"""
from datetime import timedelta
from pathlib import Path

import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

import core.database as core_db
from core.database import Base, Event, utcnow_naive
from src import events as ev

ROOT = Path(__file__).resolve().parent.parent
_maker = None


@pytest.fixture(autouse=True)
def _db(tmp_path, monkeypatch):
    engine = create_engine(f"sqlite:///{tmp_path}/u.db",
                           connect_args={"check_same_thread": False})
    Base.metadata.create_all(bind=engine)
    maker = sessionmaker(autocommit=False, autoflush=False, bind=engine)
    monkeypatch.setattr(core_db, "SessionLocal", maker)
    monkeypatch.setattr(ev, "_last_prune", 0.0)
    global _maker
    _maker = maker
    yield maker
    engine.dispose()


def seed(rows):
    db = _maker()
    now = utcnow_naive()
    try:
        for days_ago, model, owner, count in rows:
            for _ in range(count):
                db.add(Event(kind="llm_round", ts=now - timedelta(days=days_ago),
                             model=model, owner=owner, input_tokens=100,
                             output_tokens=20, duration_ms=1500))
        db.commit()
    finally:
        db.close()


# --- the series ------------------------------------------------------------

def test_quiet_days_are_present_not_omitted():
    """A gap that reads as continuity is how a usage chart misleads."""
    seed([(0, "qwen", "alice", 3), (5, "qwen", "alice", 1)])
    result = ev.usage_over_time(days=7)
    assert len(result["buckets"]) == 7
    assert [b["rounds"] for b in result["buckets"]].count(0) == 5
    assert result["buckets"][0]["day"] < result["buckets"][-1]["day"]


def test_the_window_is_the_requested_length_even_with_no_data():
    result = ev.usage_over_time(days=30)
    assert len(result["buckets"]) == 30
    assert all(b["rounds"] == 0 for b in result["buckets"])


def test_days_are_in_order_and_end_today():
    seed([(0, "m", "a", 1)])
    result = ev.usage_over_time(days=3)
    days = [b["day"] for b in result["buckets"]]
    assert days == sorted(days)
    assert result["buckets"][-1]["rounds"] == 1


def test_totals_split_by_model_and_by_owner():
    seed([(0, "qwen", "alice", 3), (0, "llama", "bob", 1),
          (2, "qwen", "alice", 2), (5, "qwen", "bob", 1)])
    result = ev.usage_over_time(days=7)
    models = {m["model"]: m for m in result["models"]}
    assert models["qwen"]["rounds"] == 6
    assert models["llama"]["rounds"] == 1
    assert models["qwen"]["input_tokens"] == 600
    owners = {o["owner"]: o for o in result["owners"]}
    assert owners["alice"]["rounds"] == 5
    assert owners["bob"]["rounds"] == 2


def test_models_are_ordered_by_what_they_cost():
    """A table sorted by name makes the operator find the expensive one. The
    point of the view is to put it at the top."""
    seed([(0, "cheap", "a", 1), (0, "expensive", "a", 20)])
    result = ev.usage_over_time(days=2)
    assert result["models"][0]["model"] == "expensive"


def test_an_unattributed_round_is_labelled_not_dropped():
    """Rounds with no owner predate multi-user and must still be counted;
    silently dropping them makes the totals disagree with the summary."""
    seed([(0, "m", None, 2)])
    result = ev.usage_over_time(days=2)
    assert result["owners"][0]["owner"] == "(unattributed)"
    assert result["owners"][0]["rounds"] == 2


def test_filtering_by_owner_narrows_the_series():
    seed([(0, "m", "alice", 3), (0, "m", "bob", 5)])
    result = ev.usage_over_time(days=2, owner="alice")
    assert sum(b["rounds"] for b in result["buckets"]) == 3


def test_only_llm_rounds_are_counted():
    """`P14-02` puts tool calls, retrievals and approvals in the same table.
    A usage chart that silently includes them reports a number nobody can
    reconcile with anything."""
    seed([(0, "m", "a", 2)])
    db = _maker()
    try:
        db.add(Event(kind="tool_call", ts=utcnow_naive(), name="shell"))
        db.add(Event(kind="retrieval", ts=utcnow_naive(), name="rag"))
        db.commit()
    finally:
        db.close()
    result = ev.usage_over_time(days=2)
    assert sum(b["rounds"] for b in result["buckets"]) == 2


def test_the_range_is_clamped():
    assert ev.usage_over_time(days=0)["days"] == 1
    assert ev.usage_over_time(days=9999)["days"] == 365


# --- it aggregates in SQL --------------------------------------------------

def test_the_series_is_aggregated_in_sql(_db):
    """`B29` was this function's sibling loading every row into Python to add
    integers. Captured at the driver, so it cannot pass by reading the source."""
    from sqlalchemy import event as sa_event
    seed([(0, "a", "x", 3), (1, "b", "y", 2)])

    statements = []

    def before(conn, cursor, statement, params, context, many):
        statements.append(statement)

    engine = _db.kw["bind"]
    sa_event.listen(engine, "before_cursor_execute", before)
    try:
        ev.usage_over_time(days=7)
    finally:
        sa_event.remove(engine, "before_cursor_execute", before)

    selects = [s for s in statements if s.lstrip().upper().startswith("SELECT")]
    assert selects, "no query ran — the test would be vacuous"
    assert all("count(" in s.lower() or "sum(" in s.lower() for s in selects), selects
    assert any("group by" in s.lower() for s in selects)


def test_a_broken_query_returns_an_error_rather_than_raising(monkeypatch):
    """A diagnostics view must not be able to take down the page it sits on."""
    monkeypatch.setattr(core_db, "SessionLocal",
                        lambda: (_ for _ in ()).throw(RuntimeError("no db")))
    result = ev.usage_over_time(days=7)
    assert "error" in result
    assert result["buckets"] == []


# --- the reading -----------------------------------------------------------

def test_the_route_serves_the_series_with_the_summary():
    """One request draws the chart. A caller that needs two will eventually
    draw it from one of them."""
    src = (ROOT / "routes" / "diagnostics_routes.py").read_text(encoding="utf-8")
    i = src.index('@router.get("/api/diagnostics/usage")')
    block = src[i:i + 1800]
    assert "usage_over_time" in block
    assert '"over_time"' in block


def test_the_panel_exists_and_is_wired():
    html = (ROOT / "static" / "index.html").read_text(encoding="utf-8")
    js = (ROOT / "static" / "js" / "admin.js").read_text(encoding="utf-8")
    assert 'id="usage-panel"' in html and 'id="usage-body"' in html
    assert "function loadUsage()" in js
    assert "setupUsagePanel();" in js, "the panel is never wired up"


def test_the_panel_queries_only_when_opened():
    """It is a query over the events table. Nobody opening Settings to change a
    theme should pay for it."""
    js = (ROOT / "static" / "js" / "admin.js").read_text(encoding="utf-8")
    i = js.index("function setupUsagePanel()")
    block = js[i:i + 900]
    assert "'toggle'" in block and "panel.open" in block
    assert "loadUsage();\n}" not in block.replace("if (panel.open) loadUsage();", "")


def test_the_chart_uses_no_charting_library():
    """One series of daily totals. Vendoring a library to draw rectangles would
    be a third-party dependency for something the browser already does."""
    js = (ROOT / "static" / "js" / "admin.js").read_text(encoding="utf-8")
    i = js.index("function usageBars(")
    block = js[i:js.index("function usageTable(")]
    assert "createElementNS" in block
    # Look for a library being USED, not for its name appearing. The first
    # version searched for the substring "chart" and matched this panel's own
    # `usage-chart` CSS class — a test that a class rename can break is a test
    # that a class rename can also satisfy.
    import re
    for lib in ("Chart", "d3", "Plotly", "echarts", "ApexCharts"):
        used = re.search(rf"\bnew\s+{lib}\b|\b{lib}\.\w|from\s+['\"][^'\"]*{lib}",
                         block, re.I)
        assert not used, f"{lib} is used in the chart builder: {used.group(0)}"


def test_the_chart_is_built_with_dom_calls_not_innerhtml():
    """Model and owner names come from the server."""
    js = (ROOT / "static" / "js" / "admin.js").read_text(encoding="utf-8")
    i = js.index("function usageBars(")
    block = js[i:js.index("async function loadUsage()")]
    assert "innerHTML" not in block


def test_the_chart_has_an_accessible_name_carrying_the_numbers():
    """A chart nobody can read aloud excludes people from the only place this
    data lives."""
    js = (ROOT / "static" / "js" / "admin.js").read_text(encoding="utf-8")
    i = js.index("function usageBars(")
    block = js[i:js.index("function usageTable(")]
    assert "'title'" in block and "role" in block


def test_an_empty_window_says_so_rather_than_drawing_nothing():
    """A blank chart reads as broken. A fresh install has no history and that
    is not an error."""
    js = (ROOT / "static" / "js" / "admin.js").read_text(encoding="utf-8")
    i = js.index("async function loadUsage()")
    block = js[i:i + 3000]
    assert "usage-empty" in block
    assert "No model rounds recorded" in block


def test_the_panel_defines_no_accent():
    """Sixteen themes define --accent and only they may."""
    css = (ROOT / "static" / "style.css").read_text(encoding="utf-8")
    i = css.index("/* Usage over time (P14-05)")
    block = css[i:css.index("/* Report a bug (P16-14)")]
    # Strip comments first: the block opens by SAYING it defines no --accent,
    # and the first version of this test read its own explanation as a
    # violation. Same shape as the docstring-read-as-code trap in P16-12.
    import re
    code = re.sub(r"/\*.*?\*/", "", block, flags=re.S)
    assert "usage-panel" in code, "comment stripping ate the rules"
    assert "--accent" not in code
