# SPDX-License-Identifier: AGPL-3.0-or-later
"""`P23-07` (`PERF-M-5`, `PERF-U-10`): the sidebar lists a person's own chats.

`/api/sessions` read `SessionManager.sessions`, filled at boot with the 100 most
recently used chats **of every owner**, and filtered that by owner afterwards.
Measured by the perf audit on a copy of the seeded world with 405 chats: 100
listed, `?limit=500` and `?offset=100` ignored, no "older" row. And on a shared
install a person whose chats were older than someone else's last 100 got an
empty sidebar — reproduced here: Bob's 120 newer chats fill the boot cache and
Alice, with 150, is listed none.

Now the owner filter and the cut are in the query (`SessionManager.list_page`),
the cut is a page (`limit`, `offset`, `X-More-Chats: 1`), the first page carries
every pinned and foldered chat (a folder's count and its × act on what the
sidebar holds), and the sidebar ends in *Show older chats*.

Driven: the real manager and the real route over a real SQLite file; the real
app in Chromium for the row.
"""
from __future__ import annotations

import json
import os
import sqlite3
import subprocess
import sys
import types
import uuid
from datetime import timedelta
from pathlib import Path

import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import NullPool
from starlette.responses import Response

import core.database as cdb
from core.database import ChatMessage as DbMessage
from core.database import Session as DbSession


def _stub_multipart_if_missing(monkeypatch):
    try:
        import python_multipart  # noqa: F401
        return
    except ImportError:
        pass
    stub = types.ModuleType("python_multipart")
    stub.__version__ = "0.0.20"
    monkeypatch.setitem(sys.modules, "python_multipart", stub)


def _chat(db, owner, name, when, *, messages=True, **kw):
    sid = str(uuid.uuid4())
    db.add(DbSession(id=sid, owner=owner, name=name, endpoint_url="http://localhost", model="m",
                     archived=kw.pop("archived", False), created_at=when, updated_at=when,
                     last_message_at=when if messages else None, last_accessed=when,
                     message_count=1 if messages else 0, **kw))
    if messages:
        db.add(DbMessage(id="m-" + uuid.uuid4().hex, session_id=sid, role="user", content="hi", timestamp=when))
    return sid


@pytest.fixture()
def world(monkeypatch, tmp_path):
    import core.session_manager as smod
    import routes.session_routes as sr

    _stub_multipart_if_missing(monkeypatch)
    engine = create_engine(f"sqlite:///{tmp_path / 'app.db'}", connect_args={"check_same_thread": False},
                           poolclass=NullPool)
    cdb.Base.metadata.create_all(engine)
    factory = sessionmaker(bind=engine, autoflush=False, autocommit=False)
    monkeypatch.setattr(smod, "SessionLocal", factory)
    monkeypatch.setattr(sr, "SessionLocal", factory)
    now = cdb.utcnow_naive()
    ids = {"alice": [], "bob": []}
    db = factory()
    try:
        # Alice's 150, a day and more ago; Bob's 120, all newer than any of hers.
        for i in range(150):
            ids["alice"].append(_chat(db, "alice", f"alice {i:03d}", now - timedelta(days=1, minutes=i)))
        for i in range(120):
            ids["bob"].append(_chat(db, "bob", f"bob {i:03d}", now - timedelta(minutes=i)))
        ids["pinned_old"] = _chat(db, "alice", "pinned long ago", now - timedelta(days=90), is_important=True)
        ids["filed_old"] = [_chat(db, "alice", f"filed {i}", now - timedelta(days=80 + i), folder="Taxes")
                            for i in range(2)]
        ids["empty_old"] = _chat(db, "alice", "opened, never used", now - timedelta(days=2), messages=False)
        ids["archived"] = _chat(db, "alice", "archived", now, archived=True)
        ids["nobody"] = _chat(db, "alice", "Nobody", now)
        ids["shared"] = _chat(db, None, "shared row", now)
        db.commit()
    finally:
        db.close()
    sm = smod.SessionManager()          # boots its cache the way the server does
    user = {"name": "alice"}
    monkeypatch.setattr(sr, "effective_user", lambda request: user["name"])
    router = sr.setup_session_routes(sm, {})
    endpoint = next(r.endpoint for r in router.routes
                    if getattr(r, "path", "") == "/api/sessions" and "GET" in getattr(r, "methods", set()))

    def ask(**params):
        from unittest.mock import MagicMock
        response = Response()
        rows = endpoint(request=MagicMock(query_params={}), response=response, **params)
        return [r["id"] for r in rows], response.headers.get("X-More-Chats")

    return types.SimpleNamespace(sm=sm, ids=ids, ask=ask, user=user)


def test_the_boot_cache_is_someone_elses_and_the_list_is_still_hers(world):
    # The premise, measured: the 100 the server boots with hold none of hers.
    assert len(world.sm.sessions) == 100
    assert not set(world.ids["alice"]) & set(world.sm.sessions)
    listed, more = world.ask()
    alice = set(world.ids["alice"])
    assert len(alice & set(listed)) == 100, len(alice & set(listed))
    assert not set(world.ids["bob"]) & set(listed)
    assert more == "1"


def test_the_first_page_is_newest_first_and_carries_pinned_and_filed_chats(world):
    listed, _ = world.ask()
    assert listed[:100] == world.ids["alice"][:100]
    assert world.ids["pinned_old"] in listed
    assert set(world.ids["filed_old"]) <= set(listed)
    assert len(listed) == 103


def test_older_chats_come_by_asking(world):
    listed, more = world.ask(limit=1000)
    assert set(world.ids["alice"]) <= set(listed)
    assert more is None
    # The second page, by recency: her last 50, then the filed and the pinned
    # (on the first page as well; the sidebar keeps one row per id).
    page2, more2 = world.ask(offset=100)
    assert page2 == world.ids["alice"][100:150] + world.ids["filed_old"] + [world.ids["pinned_old"]]
    assert more2 is None


def test_the_cache_rules_hold(world):
    listed, _ = world.ask(limit=1000)
    for key in ("empty_old", "archived", "nobody", "shared"):
        assert world.ids[key] not in listed, key
    # A chat made in this run is listed before its first message, as before.
    fresh = str(uuid.uuid4())
    world.sm.create_session(fresh, "New chat", "http://localhost", "m", owner="alice")
    assert fresh in world.ask()[0]


def test_with_no_person_every_owner_is_listed(world):
    world.user["name"] = None
    listed, _ = world.ask(limit=1000)
    assert set(world.ids["alice"]) | set(world.ids["bob"]) <= set(listed)


# ── the row, in the real app ────────────────────────────────────────────────

from test_the_command_palette_in_a_browser import NODE, _SKIP, app_url  # noqa: E402,F401

_SCRIPT = r"""
const { chromium } = require('playwright');
const BASE = process.argv[2];
(async () => {
  const browser = await chromium.launch({ args: ['--no-sandbox'] });
  const out = { errors: [] };
  const context = await browser.newContext({ viewport: { width: 1280, height: 860 }, serviceWorkers: 'block' });
  await context.addInitScript(() => {
    try { localStorage.setItem('pantheon-ui-visibility', JSON.stringify({ 'first-run-tours': false })); } catch (_) {}
  });
  const page = await context.newPage();
  page.on('pageerror', (e) => out.errors.push(String((e && e.message) || e)));
  await page.request.post(BASE + '/api/auth/login', { data: { username: 'helper', password: 'helper-pass-1', remember: true } });
  const asked = [];
  page.on('request', (r) => { const u = r.url(); if (/\/api\/sessions(\?|$)/.test(u)) asked.push(u.replace(BASE, '')); });
  await page.goto(BASE + '/', { waitUntil: 'load' });
  await page.waitForFunction(() => window.__pantheonAppStarted === true, null, { timeout: 90000 });
  await page.waitForTimeout(1500);
  const rows = () => page.evaluate(() => document.querySelectorAll('#session-list .list-item[data-session-id]').length);
  const older = () => page.locator('#session-list .session-show-older-btn');
  // Open the chats section if it is folded, then expand the client-side cut,
  // as a person would.
  const listShown = await page.evaluate(() => { const l = document.getElementById('session-list'); return !!(l && l.offsetParent); });
  if (!listShown && await page.locator('#chats-section-title').count()) {
    await page.locator('#chats-section-title').click();
    await page.waitForTimeout(400);
  }
  const more = page.locator('#session-list .session-show-more-btn:not(.session-show-older-btn)');
  if (await more.count()) { await more.first().click(); await page.waitForTimeout(500); }
  out.before = await rows();
  out.olderShown = await older().count();
  out.olderText = out.olderShown ? (await older().first().textContent()).trim() : null;
  if (out.olderShown) {
    await older().first().click();
    await page.waitForTimeout(2000);
  }
  out.after = await rows();
  out.olderAfter = await older().count();
  // A later reload of the list keeps what was shown.
  await page.evaluate(() => window.sessionModule && window.sessionModule.loadSessions && window.sessionModule.loadSessions());
  await page.waitForTimeout(1500);
  out.afterReloadList = await rows();
  out.asked = asked;
  console.log(JSON.stringify(out));
  await browser.close();
})().catch((e) => { console.error(e); process.exit(1); });
"""


@pytest.fixture(scope="module")
def seeded_database(tmp_path_factory):
    """130 chats for `helper`, written before the server starts."""
    path = tmp_path_factory.mktemp("sidebar-db") / "app.db"
    before = os.environ.get("DATABASE_URL")
    os.environ["DATABASE_URL"] = f"sqlite:///{path}"
    engine = create_engine(f"sqlite:///{path}", poolclass=NullPool)
    cdb.Base.metadata.create_all(engine)
    db = sessionmaker(bind=engine)()
    now = cdb.utcnow_naive()
    for i in range(130):
        _chat(db, "helper", f"chat {i:03d}", now - timedelta(hours=i))
    db.commit(); db.close(); engine.dispose()
    yield path
    if before is None:
        os.environ.pop("DATABASE_URL", None)
    else:
        os.environ["DATABASE_URL"] = before


@pytest.fixture(scope="module")
def sidebar(seeded_database, app_url, tmp_path_factory):  # noqa: F811
    import urllib.request
    req = urllib.request.Request(app_url + "/api/auth/setup", method="POST",
                                 data=json.dumps({"username": "helper", "password": "helper-pass-1"}).encode(),
                                 headers={"Content-Type": "application/json"})
    try:
        urllib.request.urlopen(req, timeout=30).read()
    except Exception:
        pass
    script = tmp_path_factory.mktemp("sidebar-pw") / "sidebar.cjs"
    script.write_text(_SCRIPT, encoding="utf-8")
    proc = subprocess.run([NODE, str(script), app_url], capture_output=True, text=True,
                          timeout=300, cwd=str(script.parent))
    assert proc.returncode == 0, proc.stderr[-4000:]
    return json.loads([ln for ln in proc.stdout.splitlines() if ln.strip()][-1])


@pytest.mark.skipif(NODE is None, reason=_SKIP or "")
def test_the_sidebar_ends_in_show_older_chats_and_it_shows_them(sidebar):
    assert sidebar["before"] == 100, sidebar
    assert sidebar["olderShown"] == 1 and sidebar["olderText"] == "Show older chats"
    assert sidebar["after"] == 130, sidebar
    assert sidebar["olderAfter"] == 0
    assert sidebar["afterReloadList"] == 130, "a reload of the list dropped what was shown"
    assert any("limit=" in u for u in sidebar["asked"]), sidebar["asked"]
    assert sidebar["errors"] == []
