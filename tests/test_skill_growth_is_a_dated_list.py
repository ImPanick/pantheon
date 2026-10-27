# SPDX-License-Identifier: AGPL-3.0-or-later
"""`P13-08` — observable skill growth, as a list with dates.

`Verify:` *a cold reader can say which skills got better this week, and why,
from the page alone* (`Law 15`). Nothing recorded a skill's life: the events
table's kinds were approval, memory, replay, retrieval, run_config, tool_call
and vault_*, and a skill's confidence and status were overwritten in place, so
"what did the system learn this week, and was it right" had no answer anywhere
— and `GET /api/memory/timeline`, which the row pointed at, had been deleted
for having no caller (`B1482`).

Now every write of a skill (`SkillsManager._write_skill`), every use
(`record_use`), every test (`set_audit`) and every delete leaves a dated
`kind="skill"` row with what changed and why, `GET /api/skills/growth` reads a
person's rows back as a list, and the Skills window's *Growth* view draws it as
a table to sort and act on.

Driven: a real `SkillsManager` on a temp directory writing to a real temp
SQLite, the audit's own finalising helper, the real router behind a signed-in
person, and the shipped `skillGrowth.js` under node.
"""
from __future__ import annotations

import json
import shutil
import subprocess
from datetime import timedelta
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
OWNER, OTHER = "ada", "bob"


@pytest.fixture
def db(monkeypatch):
    import core.database as database
    from tests.helpers.sqlite_db import make_temp_sqlite

    SessionLocal, engine, tmp = make_temp_sqlite(database.Base.metadata)
    monkeypatch.setattr(database, "SessionLocal", SessionLocal)
    yield SessionLocal
    engine.dispose()
    Path(tmp.name).unlink(missing_ok=True)


@pytest.fixture
def sm(tmp_path, db):
    from services.memory.skills import SkillsManager

    return SkillsManager(str(tmp_path / "data"), library_root=str(tmp_path / "library"))


def _add(sm, name, *, owner=OWNER, confidence=0.7, source="learned", session_id="chat-1"):
    out = sm.add_skill(name=name, description=f"How to {name.replace('-', ' ')}",
                       when_to_use=f"When asked to {name}", procedure=[f"Do {name} step {i}" for i in range(3)],
                       source=source, confidence=confidence, owner=owner, status="draft",
                       session_id=session_id)
    assert not out.get("_deduped"), out
    return out["name"]


def _a_week(sm):
    """Three skills' week: one learned and proved right, one that failed its
    test and fell back, one a person deleted — and the first one used."""
    from routes.skills_routes import _audit_finalize_status

    good = _add(sm, "rotate-the-logs")
    sm.update_skill(good, {"confidence": 0.95}, owner=OWNER, why="it passed the audit's test")
    sm.set_audit(good, "pass", owner=OWNER)
    _audit_finalize_status(sm, good, OWNER, "pass", 0.95)
    for _ in range(3):
        sm.record_use(good, owner=OWNER)

    bad = _add(sm, "guess-the-password-policy", confidence=0.8, source="user")
    sm.update_skill(bad, {"status": "published"}, owner=OWNER, why="you changed it")
    sm.set_audit(bad, "fail", owner=OWNER)
    sm.update_skill(bad, {"status": "draft", "confidence": 0.35}, owner=OWNER,
                    why="it still failed the audit's test")

    gone = _add(sm, "print-the-weekly-report")
    assert sm.delete_skill(gone, owner=OWNER, why="you deleted it")
    return good, bad, gone


def _rows(growth, skill, change):
    return [r for r in growth["rows"] if r["skill"] == skill and r["change"] == change]


def test_which_skills_got_better_this_week_and_why(sm):
    """The row's `Verify:`, as the list says it."""
    good, bad, gone = _a_week(sm)
    growth = sm.growth(OWNER, days=7)
    assert growth["error"] is None

    [stronger] = _rows(growth, good, "strengthened")
    assert stronger["said"] == "Stronger: 70% → 95%"
    assert stronger["why"] == "it passed the audit's test"
    [published] = _rows(growth, good, "published")
    assert published["why"] == "the audit passed it"
    [tested] = _rows(growth, good, "tested")
    assert tested["said"] == "Tested: passed", "whether what it learned was right"
    [formed] = _rows(growth, good, "formed")
    assert formed["said"] == "Formed at 70%" and formed["why"] == "learned from a chat"
    [used] = _rows(growth, good, "used")
    assert used["said"] == "Used 3 times" and used["uses"] == 3

    [weaker] = _rows(growth, bad, "weakened")
    assert weaker["said"] == "Weaker: 80% → 35%"
    assert weaker["why"] == "it still failed the audit's test"
    assert _rows(growth, bad, "drafted")[0]["said"].startswith("Back to draft")
    assert _rows(growth, bad, "tested")[0]["said"] == "Tested: failed"
    assert _rows(growth, bad, "formed")[0]["why"] == "you wrote it"

    [removed] = _rows(growth, gone, "removed")
    assert removed["why"] == "you deleted it" and removed["exists"] is False
    assert stronger["exists"] is True and stronger["confidence_now"] == pytest.approx(0.95)

    assert growth["sentence"] == ("Your skills this week: 3 formed, 1 got stronger, 1 got weaker, "
                                  "2 were published, 1 went back to draft, 1 was removed, "
                                  "1 was used 3 times.")
    stamps = [r["at"] for r in growth["rows"]]
    assert all(stamps) and stamps == sorted(stamps, reverse=True), "dated, newest first"


def test_a_confidence_or_status_written_again_unchanged_adds_nothing(sm):
    name = _add(sm, "rotate-the-logs")
    before = len(sm.growth(OWNER)["rows"])
    sm.update_skill(name, {"confidence": 0.7, "status": "draft"}, owner=OWNER, why="no change")
    assert len(sm.growth(OWNER)["rows"]) == before


def test_one_persons_week_is_theirs(sm):
    _a_week(sm)
    _add(sm, "bobs-own-skill", owner=OTHER)
    mine = {r["skill"] for r in sm.growth(OWNER)["rows"]}
    theirs = {r["skill"] for r in sm.growth(OTHER)["rows"]}
    assert "bobs-own-skill" not in mine
    assert theirs == {"bobs-own-skill"}


def test_the_period_is_the_one_asked_for(sm, db):
    from core.database import Event, utcnow_naive

    name = _add(sm, "rotate-the-logs")
    s = db()
    try:
        s.add(Event(kind="skill", name=name, owner=OWNER, outcome="strengthened",
                    ts=utcnow_naive() - timedelta(days=10),
                    detail=json.dumps({"confidence": 0.9, "previous": 0.7, "why": "an old test"})))
        s.commit()
    finally:
        s.close()
    assert not _rows(sm.growth(OWNER, days=7), name, "strengthened")
    assert _rows(sm.growth(OWNER, days=30), name, "strengthened")[0]["why"] == "an old test"
    assert sm.growth(OWNER, days=7)["sentence"] == "Your skills this week: 1 formed."
    assert sm.growth(OWNER, days=400)["days"] == 90, "held to the retention the view offers"


def test_a_quiet_week_says_so(sm):
    assert sm.growth(OWNER)["sentence"] == "Nothing happened to your skills this week."


def test_the_route_answers_the_signed_in_person_only(sm):
    from fastapi import FastAPI
    from fastapi.testclient import TestClient

    from routes.skills_routes import setup_skills_routes
    from tests.helpers.signed_in import as_person

    _a_week(sm)
    _add(sm, "bobs-own-skill", owner=OTHER)
    app = as_person(FastAPI(), OWNER)
    app.include_router(setup_skills_routes(sm))
    r = TestClient(app).get("/api/skills/growth", params={"days": 7})
    assert r.status_code == 200, r.text
    body = r.json()
    assert {row["skill"] for row in body["rows"]} == {
        "rotate-the-logs", "guess-the-password-policy", "print-the-weekly-report"}
    assert body["sentence"].startswith("Your skills this week:")
    nobody = as_person(FastAPI(), None)
    nobody.include_router(setup_skills_routes(sm))
    assert TestClient(nobody).get("/api/skills/growth").status_code == 401


# ── the view: the shipped `skillGrowth.js` under node ───────────────────────

_FAKE_DOM = r"""
class El {
  constructor(tag) { this.tagName = tag.toUpperCase(); this.children = []; this.attrs = {};
    this.dataset = {}; this.listeners = {}; this._text = ''; this.className = ''; }
  appendChild(c) { this.children.push(c); return c; }
  replaceChildren(...c) { this.children = c; }
  setAttribute(k, v) { this.attrs[k] = String(v); }
  getAttribute(k) { return this.attrs[k]; }
  addEventListener(t, f) { (this.listeners[t] = this.listeners[t] || []).push(f); }
  click() { (this.listeners.click || []).forEach((f) => f()); }
  set textContent(v) { this._text = String(v); this.children = []; }
  get textContent() { return this._text + this.children.map((c) => c.textContent).join(''); }
  all(tag) { const out = []; const walk = (n) => { for (const c of n.children) {
    if (c.tagName === tag) out.push(c); walk(c); } }; walk(this); return out; }
}
const document = { createElement: (t) => new El(t) };
globalThis.document = document;
"""

_CASE = r"""
import { renderGrowth, sortGrowthRows, GROWTH_COLUMNS } from %(module)s;
const data = { rows: [
  { at: '2026-10-21T09:00:00Z', skill: 'rotate-the-logs', change: 'strengthened', exists: true,
    said: 'Stronger: 70% → 95%', why: "it passed the audit's test" },
  { at: '2026-10-23T12:00:00Z', skill: 'print-the-weekly-report', change: 'removed', exists: false,
    said: 'Removed', why: 'you deleted it' },
  { at: '2026-10-22T08:00:00Z', skill: 'guess-the-password-policy', change: 'weakened', exists: true,
    said: 'Weaker: 80% → 35%', why: '' },
] };
const out = {};
const host = new El('div');
const opened = [], sorted = [];
out.count = renderGrowth(host, data, { state: { key: 'at', dir: 'desc' },
  onOpen: (n) => opened.push(n), onSort: (k) => sorted.push(k) });
out.headers = host.all('TH').map((th) => [th.textContent, th.getAttribute('aria-sort')]);
const rows = host.all('TR').slice(1);
out.byDate = rows.map((tr) => tr.children.map((td) => td.textContent));
const buttons = host.all('BUTTON').filter((b) => b.className === 'skills-growth-open');
out.openable = buttons.map((b) => b.textContent);
buttons[0].click();
host.all('BUTTON').find((b) => b.dataset.sort === 'skill').click();
out.opened = opened; out.sorted = sorted;
renderGrowth(host, data, { state: { key: 'skill', dir: 'asc' } });
out.byName = host.all('TR').slice(1).map((tr) => tr.children[1].textContent);
out.nameSort = host.all('TH')[1].getAttribute('aria-sort');
const empty = new El('div');
out.emptyCount = renderGrowth(empty, { rows: [] });
out.empty = empty.textContent;
out.stable = sortGrowthRows([{ k: 'a', n: 1 }, { k: 'a', n: 2 }], 'k', 'asc').map((r) => r.n);
out.columns = GROWTH_COLUMNS.map((c) => c.key);
console.log(JSON.stringify(out));
"""


@pytest.mark.skipif(shutil.which("node") is None, reason="node is not installed")
def test_the_view_is_a_table_to_read_sort_and_act_on(tmp_path):
    module = (ROOT / "static" / "js" / "skillGrowth.js").as_uri()
    script = tmp_path / "case.mjs"
    script.write_text(_FAKE_DOM + _CASE.replace("%(module)s", json.dumps(module)), encoding="utf-8")
    run = subprocess.run(["node", str(script)], capture_output=True, text=True, timeout=60)
    assert run.returncode == 0, run.stderr
    out = json.loads(run.stdout.strip().splitlines()[-1])

    assert out["columns"] == ["at", "skill", "said", "why"]
    assert [h[0] for h in out["headers"]] == ["When ↓", "Skill", "What happened", "Why"]
    assert out["headers"][0][1] == "descending" and out["headers"][1][1] == "none"
    assert out["count"] == 3
    assert [r[1] for r in out["byDate"]] == [
        "print-the-weekly-report", "guess-the-password-policy", "rotate-the-logs"], "newest first"
    assert out["byDate"][2][2:] == ["Stronger: 70% → 95%", "it passed the audit's test"]
    assert out["byDate"][1][3] == "—", "no reason is said as no reason, not as a blank"
    assert sorted(out["openable"]) == ["guess-the-password-policy", "rotate-the-logs"], \
        "a removed skill has nothing to open"
    assert out["opened"] == ["guess-the-password-policy"] and out["sorted"] == ["skill"]
    assert out["byName"] == ["guess-the-password-policy", "print-the-weekly-report", "rotate-the-logs"]
    assert out["nameSort"] == "ascending"
    assert out["emptyCount"] == 0 and out["empty"].startswith("Nothing to list for this period.")
    assert out["stable"] == [1, 2]


def test_the_window_has_the_view_and_asks_the_route():
    """The tab, its panel and its controls are in the page the window stamps
    the Workbench room from, and the module asks the route this file drives."""
    html = (ROOT / "static" / "index.html").read_text(encoding="utf-8")
    modal = html[html.index('<div id="skills-modal"'):html.index("── Workbench window")]
    for needle in ('data-skills-view="growth"', 'data-skills-view-panel="growth"',
                   'id="skills-growth-days"', 'id="skills-growth-sentence"', 'id="skills-growth"'):
        assert needle in modal, needle
    js = (ROOT / "static" / "js" / "skillGrowth.js").read_text(encoding="utf-8")
    assert "`/api/skills/growth?days=${encodeURIComponent(days)}`" in js
