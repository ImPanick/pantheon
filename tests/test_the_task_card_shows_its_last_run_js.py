# SPDX-License-Identifier: AGPL-3.0-or-later
r"""`B1043`, the client half — the Tasks card's last-run badge renders.

`tasks.js` draws `.task-lastrun` on a card from `task.last_run_status` (`B84`
and `B110` worked on its words and colours), but `_fetchTasks` asked
`GET /api/tasks` with no parameters, and the route puts the last run on a row
only when asked (`include_last_run=true`). Before `P22-02` no client in
`static/` passed it: the badge was dead code. `P22-02`'s canvas asks; this asks
too. (The server half — the last runs read in one statement, and a dry run never
a last run, `B1054` — is `wb-runs`'.)

Driven: the real `tasks.js` list (the shared `tasks.js` sandbox with the shim's
HTML layer), fed by the real `GET /api/tasks` handler over a real SQLite file —
called with whatever the client asked for, so a client that does not ask gets
the rows the server sends a client that does not ask (`Law 20`).
"""

from __future__ import annotations

import asyncio
import json
import shutil
import sys
from datetime import datetime
from pathlib import Path
from types import SimpleNamespace

import pytest

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(Path(__file__).resolve().parent))

TASKS_JS = ROOT / "static" / "js" / "tasks.js"

pytestmark = pytest.mark.skipif(not shutil.which("node"), reason="node binary not on PATH")

from test_tool_effect_surfaces_js import _make_sandbox, _run  # noqa: E402
from test_the_palette_moves_to_the_server_js import _STUBS  # noqa: E402
from test_one_task_form_in_two_places_js import _SHIM_PARSED  # noqa: E402
from test_a_dry_run_is_dry import task_db  # noqa: E402,F401


@pytest.fixture(scope="module")
def sandbox(tmp_path_factory):
    box = _make_sandbox(tmp_path_factory.mktemp("lastrun"), TASKS_JS, _SHIM_PARSED, _STUBS)
    copy = box / TASKS_JS.name
    copy.write_text(copy.read_text(encoding="utf-8")
                    + "\nexport const __t = { _fetchTasks, _renderMainView };\n", encoding="utf-8")
    return box


def _served(task_db, monkeypatch) -> dict:
    """`GET /api/tasks` as the real handler answers it, with and without the
    parameter: a backup whose last run failed, and a step that never ran."""
    from core.database import ScheduledTask, TaskRun
    import routes.task.task_routes as task_routes
    db = task_db()
    try:
        db.add(ScheduledTask(id="t1", owner=None, name="Nightly backup", task_type="llm", prompt="Back up",
                             trigger_type="schedule", schedule="daily", scheduled_time="02:00",
                             status="active", output_target="session", run_count=1))
        db.add(ScheduledTask(id="t2", owner=None, name="Message me", task_type="llm", prompt="Tell me",
                             trigger_type="webhook", status="active", output_target="session", run_count=0))
        db.commit()
        db.add(TaskRun(id="r1", task_id="t1", status="error", result=None,
                       error="RuntimeError: No model/endpoint configured",
                       started_at=datetime(2026, 10, 1, 2, 0), finished_at=datetime(2026, 10, 1, 2, 0, 3)))
        db.commit()
    finally:
        db.close()
    monkeypatch.setattr(task_routes, "SessionLocal", task_db)
    router = task_routes.setup_task_routes(SimpleNamespace())
    handler = next(r.endpoint for r in router.routes
                   if getattr(r, "path", None) == "/api/tasks" and "GET" in getattr(r, "methods", set()))
    request = SimpleNamespace(state=SimpleNamespace(current_user=None))
    out = {}
    for asked in (True, False):
        out[asked] = json.loads(json.dumps(asyncio.run(handler(request, include_last_run=asked))))
    return out


def _cards(sandbox, served) -> dict:
    return _run(sandbox, (
        "import { document, Node, calls, mockFetch, res, tick } from './shim.js';\n"
        "const { __t } = await import('./tasks.js');\n"
    ), """
        const SERVED = %s;
        mockFetch(async (url, opts) => {
          if (/\\/api\\/tasks(\\?|$)/.test(url) && (!opts || !opts.method || opts.method === 'GET')) {
            return res(200, url.includes('include_last_run=true') ? SERVED.asked : SERVED.plain);
          }
          if (url.includes('/meta/actions')) return res(200, { actions: [] });
          return res(200, {});
        });
        await __t._fetchTasks();
        const modal = document.body.appendChild(new Node('div'));
        modal.setAttribute('id', 'tasks-modal');
        const body = modal.appendChild(new Node('div'));
        body.className = 'modal-body';
        __t._renderMainView();
        await tick();
        const card = (id) => body.querySelectorAll('.task-card').find((c) => c.dataset.id === id);
        const badge = (id) => { const b = card(id) && card(id).querySelector('.task-lastrun');
          return b && { cls: b.className, mark: b.querySelector('.task-lastrun-mark').textContent,
                        text: b.querySelector('.task-lastrun-text').textContent, title: b.title }; };
        console.log(JSON.stringify({
          asked: calls.fetch.filter((c) => c.url.includes('/api/tasks')).map((c) => c.url.replace('http://test.local', '')),
          backup: badge('t1'), message: badge('t2'), cards: body.querySelectorAll('.task-card').length,
        }));
    """ % json.dumps({"asked": served[True], "plain": served[False]}))


def test_a_task_whose_last_run_failed_shows_failed_on_its_card(sandbox, task_db, monkeypatch):
    """The row's `Verify:`."""
    o = _cards(sandbox, _served(task_db, monkeypatch))
    assert o["cards"] == 2
    assert o["asked"][0] == "/api/tasks?include_last_run=true"
    assert o["backup"] == {"cls": "task-lastrun task-lastrun-error", "mark": "✗",
                           "text": "RuntimeError: No model/endpoint configured",
                           "title": "Open full history"}


def test_a_task_that_never_ran_has_no_badge(sandbox, task_db, monkeypatch):
    o = _cards(sandbox, _served(task_db, monkeypatch))
    assert o["message"] is None


def test_the_rows_differ_only_when_asked(task_db, monkeypatch):
    """The premise, re-measured against the real handler (`Law 3`): without the
    parameter no row carries a last run, so a client that does not ask can
    never draw one."""
    served = _served(task_db, monkeypatch)
    plain = {t["id"]: t for t in served[False]["tasks"]}
    asked = {t["id"]: t for t in served[True]["tasks"]}
    assert "last_run_status" not in plain["t1"]
    assert asked["t1"]["last_run_status"] == "error"
