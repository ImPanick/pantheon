"""What is quietly wrong, and whether anyone would ever see it.

`service_health.py` answers *can I reach X* — liveness. This module answers *is
something accumulating, or has something quietly stopped*, and the distinction is
the reason it exists: when a year of agent-written email sat staged and invisible
(`H01`), the mail server was **reachable the entire time**. Liveness said green.

So these tests check two things a health feature usually forgets:

  * a check that finds trouble must *say what to do*, not just colour a dot;
  * the whole thing must have a reader. A diagnostic nobody can see is the exact
    defect this project keeps finding in its own product.
"""
import sqlite3
import pathlib
import time

import pytest

from src import self_checks as sc

REPO = pathlib.Path(__file__).resolve().parent.parent


# ── the shape every check must honour ────────────────────────────────────

def test_every_check_returns_the_agreed_shape():
    for fn in sc.CHECKS:
        r = fn()
        assert r["status"] in (sc.OK, sc.ATTENTION, sc.STUCK, sc.UNKNOWN), (fn.__name__, r)
        for key in ("name", "title", "summary", "count", "action"):
            assert key in r, (fn.__name__, key)
        assert r["title"] and r["summary"], fn.__name__


def test_a_check_that_raises_is_reported_not_dropped(monkeypatch):
    """A self-check module that fails silently is a joke with a long setup."""
    def boom():
        raise RuntimeError("kaboom")
    boom.__name__ = "exploding_check"

    monkeypatch.setattr(sc, "CHECKS", (boom,))
    out = sc.run_self_checks()
    assert len(out["checks"]) == 1
    assert out["checks"][0]["status"] == sc.UNKNOWN
    assert "kaboom" in out["checks"][0]["summary"]


def test_unknown_is_not_reported_as_ok(monkeypatch):
    """"The check could not run" and "nothing is wrong" are different answers.

    Exercised with a passing check alongside, deliberately. With only the unknown
    one present the rollup takes `results[0]` and the ordering never runs -- a
    mutation that ranks unknown *below* ok survived that version of this test.
    """
    monkeypatch.setattr(sc, "CHECKS", (
        lambda: sc._check("fine", "Fine", sc.OK, "all good"),
        lambda: sc._check("dunno", "Dunno", sc.UNKNOWN, "no idea"),
    ))
    out = sc.run_self_checks()
    assert out["status"] == sc.UNKNOWN, (
        "a check that could not run was rolled up as healthy"
    )
    assert out["checks"][0]["name"] == "dunno", "unknown must sort above ok"


def test_the_worst_status_wins_and_sorts_first(monkeypatch):
    monkeypatch.setattr(sc, "CHECKS", (
        lambda: sc._check("a", "A", sc.OK, "fine"),
        lambda: sc._check("b", "B", sc.STUCK, "bad"),
        lambda: sc._check("c", "C", sc.ATTENTION, "hmm"),
    ))
    out = sc.run_self_checks()
    assert out["status"] == sc.STUCK
    assert [c["name"] for c in out["checks"]] == ["b", "c", "a"]
    assert [c["name"] for c in out["needs_attention"]] == ["b", "c"]


# ── H01: the check this module was built for ─────────────────────────────

def _mail_db(tmp_path, rows):
    db = tmp_path / "scheduled_emails.db"
    conn = sqlite3.connect(db)
    conn.execute("CREATE TABLE scheduled_emails (id INTEGER PRIMARY KEY, status TEXT, created_at TEXT)")
    conn.executemany("INSERT INTO scheduled_emails (status, created_at) VALUES (?, ?)", rows)
    conn.commit(); conn.close()
    return db


def test_staged_agent_mail_is_counted_and_named(tmp_path, monkeypatch):
    """The number that would have caught a year-long data loss in week one."""
    _mail_db(tmp_path, [("agent_draft", "2026-01-05"), ("agent_draft", "2026-02-01"),
                        ("sent", "2026-03-01")])
    monkeypatch.setattr("src.constants.DATA_DIR", str(tmp_path))

    r = sc.agent_email_backlog()
    assert r["status"] == sc.STUCK
    assert r["count"] == 2, "sent mail was counted as staged, or staged mail was missed"
    assert "2026-01-05" in (r.get("oldest") or ""), "the age of the backlog is not reported"
    assert r["action"], "a stuck check with no next step is just a red dot"


def test_no_staged_mail_is_ok(tmp_path, monkeypatch):
    _mail_db(tmp_path, [("sent", "2026-03-01")])
    monkeypatch.setattr("src.constants.DATA_DIR", str(tmp_path))
    assert sc.agent_email_backlog()["status"] == sc.OK


def test_a_missing_mail_database_is_ok_not_unknown(tmp_path, monkeypatch):
    """A fresh install has no mail db. That is not a fault to report."""
    monkeypatch.setattr("src.constants.DATA_DIR", str(tmp_path))
    assert sc.agent_email_backlog()["status"] == sc.OK


def test_a_corrupt_mail_database_is_unknown_not_ok(tmp_path, monkeypatch):
    (tmp_path / "scheduled_emails.db").write_bytes(b"not a database at all")
    monkeypatch.setattr("src.constants.DATA_DIR", str(tmp_path))
    assert sc.agent_email_backlog()["status"] == sc.UNKNOWN


# ── P15-11: the snapshot that had no reader ──────────────────────────────

def test_throttled_hosts_are_surfaced(monkeypatch):
    """`OutboundHostLimiter.snapshot()` was written for this and had no caller."""
    from src.rate_limiter import HostPolicy, OutboundHostLimiter
    import src.rate_limiter as rl

    lim = OutboundHostLimiter({"h.test": HostPolicy(min_interval=0.0)})
    lim.observe("h.test", 429, {"Retry-After": "600"})
    monkeypatch.setattr(rl, "outbound", lim)

    r = sc.outbound_cooldowns()
    assert r["status"] == sc.ATTENTION
    assert r["count"] == 1
    assert "h.test" in r["hosts"]
    assert "minutes" in r["summary"] or "min" in r["summary"]


def test_no_cooldowns_is_ok(monkeypatch):
    from src.rate_limiter import OutboundHostLimiter
    import src.rate_limiter as rl

    monkeypatch.setattr(rl, "outbound", OutboundHostLimiter({}))
    assert sc.outbound_cooldowns()["status"] == sc.OK


# ── the part health features usually forget ──────────────────────────────

def test_every_actionable_check_says_what_to_do():
    """A dot that goes red and offers nothing is worse than no dot: it costs
    attention and returns none."""
    import inspect

    for fn in sc.CHECKS:
        src = inspect.getsource(fn)
        if f'{sc.STUCK}' in src or "STUCK" in src:
            assert "action=" in src, f"{fn.__name__} can report stuck without a next step"


def test_the_route_exists_and_is_admin_gated():
    src = (REPO / "routes/diagnostics_routes.py").read_text(encoding="utf-8")
    i = src.index("/api/diagnostics/self-check")
    # Stop at the NEXT route, so a neighbouring handler's `require_admin` cannot
    # satisfy this. A fixed 1200-character window did exactly that, and the
    # mutation that removed the gate survived.
    nxt = src.find("@router.", i + 1)
    body = src[i:nxt if nxt != -1 else len(src)]
    assert "require_admin" in body, "the self-check route is not admin-gated"
    assert "run_self_checks" in body


def test_the_panel_has_a_reader_and_a_caller():
    """Law 13. A diagnostic nobody can see is the defect this product keeps
    finding in itself — and it would be a particularly poor joke here."""
    js = (REPO / "static/js/admin.js").read_text(encoding="utf-8")
    html = (REPO / "static/index.html").read_text(encoding="utf-8")

    assert 'id="self-check-panel"' in html, "no markup for the panel"
    assert "'self-check-panel'" in js, "the panel is never looked up"
    assert "/api/diagnostics/self-check" in js, "the route has no frontend caller"

    # Count CALL sites, not the definition. `js.count("loadSelfChecks()") >= 2`
    # was the first version and it passes with every call site deleted, because
    # `async function loadSelfChecks()` matches the same substring.
    calls = js.count("loadSelfChecks()") - js.count("function loadSelfChecks()")
    assert calls >= 1, "loadSelfChecks is defined but never called"


def test_the_panel_does_not_build_markup_from_strings():
    """This surface reports trouble, which makes it the one most likely to be
    handed a hostile string — from a mail subject, or a host name."""
    js = (REPO / "static/js/admin.js").read_text(encoding="utf-8")
    start = js.index("async function loadSelfChecks()")
    body = js[start:js.index("async function loadLogs(")]
    assert "innerHTML" not in body, "the self-check panel builds markup from strings"
    assert "textContent" in body
