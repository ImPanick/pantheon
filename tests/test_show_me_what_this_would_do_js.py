# SPDX-License-Identifier: AGPL-3.0-or-later
r"""`P22-04`, the Tasks window's half — *Show me what this would do*, and a run
log that names its steps. Folds `B802`'s first two parts and `B670`.

**What was on the tree, measured 2026-10-01 at `f37de0f`.** `P8-33` built a dry
run that is a `return` above every executor — `POST /api/tasks/{id}/run?dry=true`
writes a `skipped` run whose steps are the plan — and nothing in the browser
sent it: `_runNow` (`static/js/tasks.js:206`) built `/run` with `?force` and
nothing else. And `_renderRunSteps` (`:2178`) read
`kind === 'tool' ? 'tool' : 'progress'`, so a run's cause (`P8-23`'s `trigger`
step, step one of every fired run) and every line of a plan (`dry-run`) were
drawn under the word *progress*.

**What these cases drive.** The real `tasks.js` under node, with the DOM
shim's opt-in parser, so the card's own button is the thing clicked. The plan
the card draws is not written here: the real scheduler runs a real dry run
against a temp database, the real `_run_to_dict` serialises the row, and that
is what the mocked `GET /runs` answers with — so a plan line the scheduler
changes, or a step kind it adds, reaches these assertions (`Law 20`). The same
for the run fired by an event: the real scheduler writes its `trigger` step.

The canvas half of the row — each node's outcome by shape and weight — is
`wb-canvas`'s, and `manage_tasks`'s `dry_run` is `wb-graph`'s.
"""

from __future__ import annotations

import json
import shutil
import sys
from html.parser import HTMLParser
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(Path(__file__).resolve().parent))

TASKS_JS = ROOT / "static" / "js" / "tasks.js"

pytestmark = pytest.mark.skipif(not shutil.which("node"), reason="node binary not on PATH")

import src.builtin_actions as ba  # noqa: E402
from src.event_bus import build_trigger  # noqa: E402
from test_tool_effect_surfaces_js import _make_sandbox, _run  # noqa: E402
from test_the_palette_moves_to_the_server_js import _STUBS  # noqa: E402
from test_one_task_form_in_two_places_js import _SHIM_PARSED  # noqa: E402
# The dry-run row's own temp database, seed and scheduler (`Law 14`).
from test_a_dry_run_is_dry import _scheduler, _seed, task_db  # noqa: E402,F401


_EXPORT = (
    "\nexport const __t = { _runNow, _doDryRun, _drawDryPlan,"
    " _renderRunSteps, _fetchTasks, _renderMainView };\n"
)


@pytest.fixture(scope="module")
def sandbox(tmp_path_factory):
    box = _make_sandbox(tmp_path_factory.mktemp("dryrun"), TASKS_JS, _SHIM_PARSED, _STUBS)
    copy = box / TASKS_JS.name
    copy.write_text(copy.read_text(encoding="utf-8") + _EXPORT, encoding="utf-8")
    return box


_PREAMBLE = (
    "import { document, Node, calls, mockFetch, res, tick, click } from './shim.js';\n"
    "import { calls as ui } from './ui.js';\n"
    "const { __t } = await import('./tasks.js');\n"
)

# `GET /runs` answers `before` until the dry run has been asked for, then
# `after` — which is how the server behaves: the plan's run exists only once
# the request has been made.
_ROUTES_JS = r"""
const ROUTES = %s;
let asked = false;
mockFetch(async (url, opts) => {
  const method = (opts && opts.method) || 'GET';
  if (method === 'POST' && url.includes('/run')) {
    asked = true;
    if (ROUTES.runStatus && ROUTES.runStatus !== 200) {
      return res(ROUTES.runStatus, { detail: ROUTES.runDetail || 'refused' });
    }
    const dry = url.includes('dry=true');
    // The real route's dry reply: the run holding the plan, in `GET /runs`'
    // shape (`P22-04`'s server half). `reply` overrides it for the odd cases.
    const planned = (ROUTES.after || []).slice(-1)[0];
    if (ROUTES.reply) return res(200, ROUTES.reply);
    return res(200, dry && planned ? { ok: true, dry, message: 'Dry run — planned, nothing executed',
      run_id: planned.id, run: planned } : { ok: true, dry });
  }
  if (url.includes('/runs')) return res(200, { runs: asked ? (ROUTES.after || []) : (ROUTES.before || []) });
  if (method === 'GET' && /\/api\/tasks(\?|$)/.test(url)) {
    return res(200, { tasks: ROUTES.tasks || [],
      graph: { nodes: [], edges: [], conditions: ['success', 'error'], max_depth: 10 } });
  }
  if (url.includes('/meta/actions')) return res(200, { actions: [] });
  return res(200, {});
});
const posts = () => calls.fetch.filter((c) => c.method === 'POST').map((c) => c.url.replace('http://test.local', ''));
const wait = (ms) => new Promise((r) => setTimeout(r, ms));
async function openTasksList() {
  await __t._fetchTasks();
  const modal = document.body.appendChild(new Node('div'));
  modal.setAttribute('id', 'tasks-modal');
  const body = modal.appendChild(new Node('div'));
  body.className = 'modal-body';
  __t._renderMainView();
  await tick();
  return body;
}
"""


def _case(sandbox, routes: dict, script: str) -> dict:
    return _run(sandbox, _PREAMBLE, (_ROUTES_JS % json.dumps(routes)) + script)


# ── the server's half: real rows, serialised by the real route helper ───────

def _rows(task_db) -> tuple[dict, dict]:
    """The task as `GET /api/tasks` serves it, and run `r1` as `GET /runs` does."""
    import routes.task.task_routes as task_routes
    from core.database import ScheduledTask, TaskRun
    db = task_db()
    try:
        task = db.query(ScheduledTask).filter(ScheduledTask.id == "t1").first()
        run = db.query(TaskRun).filter(TaskRun.id == "r1").first()
        return (json.loads(json.dumps(task_routes._task_to_dict(task))),
                json.loads(json.dumps(task_routes._run_to_dict(run))))
    finally:
        db.close()


async def _planned(task_db, monkeypatch, action: str, *, prompt=None, status=None):
    """A real dry run of a real task, by the real scheduler."""
    _seed(task_db, action=action, prompt=prompt)
    if status:
        from core.database import ScheduledTask
        db = task_db()
        try:
            db.query(ScheduledTask).filter(ScheduledTask.id == "t1").first().status = status
            db.commit()
        finally:
            db.close()

    async def _must_not_run(**kwargs):  # the guarantee P8-33 owns; asserted again
        raise AssertionError("a dry run called the action")
    monkeypatch.setitem(ba.BUILTIN_ACTIONS, action, _must_not_run)
    await _scheduler()._execute_task_locked(
        "t1", "r1", gate_foreground=False, release_executing=False, dry=True)
    return _rows(task_db)


class _Steps(HTMLParser):
    """Each `<li>` of a step log: its classes, the word it is drawn under, and
    a tool step's status word with the stored value it came from."""

    def __init__(self):
        super().__init__(convert_charrefs=True)
        self.rows, self._in = [], None

    def handle_starttag(self, tag, attrs):
        a = dict(attrs)
        cls = a.get("class") or ""
        if tag == "li":
            self.rows.append({"class": cls, "kind": "", "status": "", "title": None, "detail": ""})
        elif self.rows and tag == "span":
            self._in = cls
            if cls == "task-run-step-status":
                self.rows[-1]["title"] = a.get("title")

    def handle_endtag(self, tag):
        if tag == "span":
            self._in = None

    def handle_data(self, data):
        if not self.rows or not self._in:
            return
        key = {"task-run-step-kind": "kind", "task-run-step-status": "status",
               "task-run-step-detail": "detail"}.get(self._in)
        if key:
            self.rows[-1][key] += data


def _steps_of(html: str) -> list:
    p = _Steps()
    p.feed(html)
    return p.rows


# ── `B802(a)`: the request ──────────────────────────────────────────────────

def test_the_dry_run_is_the_run_route_with_dry_true(sandbox):
    """The route `P8-33` extended, not a second one: same owner check, admin
    gate and 409. `force` and a plain run are unchanged (`Law 1`)."""
    out = _case(sandbox, {}, """
        await __t._runNow('t1', false, true);
        await __t._runNow('t1');
        await __t._runNow('t1', true);
        console.log(JSON.stringify({ posts: posts() }));
    """)
    assert out["posts"] == ["/api/tasks/t1/run?dry=true", "/api/tasks/t1/run",
                            "/api/tasks/t1/run?force=true"], out["posts"]


# ── the card: a button, and the plan drawn where it was pressed ─────────────

@pytest.mark.asyncio
async def test_the_card_draws_the_plan_the_scheduler_wrote(sandbox, task_db, monkeypatch):
    """`Verify` (Tasks half): pressed on a task, nothing runs — the only request
    is `?dry=true` — and the card says what a real run would have done. Run on
    `consolidate_memory`, one of the two actions a dry run cannot describe, so
    the card has to say that too, in the scheduler's own sentence."""
    task, run = await _planned(task_db, monkeypatch, "consolidate_memory")
    assert run["status"] == "skipped" and run["steps"], run
    out = _case(sandbox, {"tasks": [task], "after": [run]}, """
        const body = await openTasksList();
        const btn = body.querySelector('.task-detail-dry-btn');
        const label = btn.textContent;
        click(btn);
        const during = { disabled: btn.disabled, text: btn.textContent };
        await wait(400);
        const plan = body.querySelector('.task-dry-plan');
        console.log(JSON.stringify({ label, during, after: { disabled: btn.disabled, text: btn.textContent },
          hidden: plan.hidden, text: plan.textContent, html: plan.innerHTML, posts: posts() }));
    """)
    assert out["label"] == "Show me what this would do"
    assert out["during"] == {"disabled": True, "text": "Working it out…"}, out["during"]
    assert out["after"] == {"disabled": False, "text": "Show me what this would do"}
    assert out["posts"] == ["/api/tasks/t1/run?dry=true"], "nothing but the plan was asked for"
    assert out["hidden"] is False
    assert "What a real run would do" in out["text"]
    for step in run["steps"]:
        assert step["detail"] in out["text"], step["detail"]
    assert "Dry run — nothing ran, nothing changed." in out["text"]
    assert "A dry run cannot tell you what this would change" in out["text"]
    rows = _steps_of(out["html"])
    assert rows and all("task-run-step-dry-run" in r["class"] for r in rows), rows
    assert all(r["kind"] == "dry run" for r in rows), "every plan line is named for what it is"


@pytest.mark.asyncio
async def test_the_kebab_offers_it_beside_run_now_and_opens_the_card(sandbox, task_db, monkeypatch):
    task, run = await _planned(task_db, monkeypatch, "ssh_command", prompt="shutdown -h now")
    out = _case(sandbox, {"tasks": [task], "after": [run]}, """
        const body = await openTasksList();
        const card = body.querySelector('.task-card');
        click(card.querySelector('.memory-item-btn'));
        const menu = document.body.querySelector('.task-dropdown');
        const labels = menu.querySelectorAll('button').map((b) => b.textContent.trim());
        const item = menu.querySelectorAll('button').find((b) => b.textContent.trim() === 'Show me what this would do');
        click(item);
        await wait(400);
        console.log(JSON.stringify({ labels, expanded: card.classList.contains('expanded'),
          text: card.querySelector('.task-dry-plan').textContent, posts: posts() }));
    """)
    assert out["labels"][:3] == ["Run now", "Show me what this would do", "Edit"], out["labels"]
    assert out["expanded"], "the plan is drawn inside the card, so the card opens"
    assert out["posts"] == ["/api/tasks/t1/run?dry=true"]
    assert "shutdown -h now" in out["text"], "the command is shown verbatim, before it runs"


@pytest.mark.asyncio
async def test_a_task_the_scheduler_will_not_plan_says_why(sandbox, task_db, monkeypatch):
    """A run the scheduler declined to plan is recorded `skipped` with its
    reason and no plan — the card says so rather than waiting for a plan that
    will not come. A paused task was this case until `B1036` (it plans now);
    what is left is a task the engine will not run for this owner."""
    monkeypatch.setattr("src.task_scheduler.owner_has_admin_task_privileges",
                        lambda owner: False)
    task, run = await _planned(task_db, monkeypatch, "ssh_command", prompt="reboot")
    assert run["steps"] == [] and run["error"], run
    out = _case(sandbox, {"tasks": [task], "after": [run]}, """
        const body = await openTasksList();
        click(body.querySelector('.task-detail-dry-btn'));
        await wait(400);
        console.log(JSON.stringify({ text: body.querySelector('.task-dry-plan').textContent }));
    """)
    assert out["text"] == f"Nothing was planned: {run['error']}.", out["text"]


def test_a_task_already_running_is_told_so(sandbox):
    out = _case(sandbox, {"runStatus": 409}, """
        const plan = document.body.appendChild(new Node('div'));
        const ran = await __t._doDryRun('t1', plan, null);
        console.log(JSON.stringify({ ran, text: plan.textContent }));
    """)
    assert out["ran"] is None
    assert out["text"] == "Task is already running"


def test_a_reply_without_its_run_says_where_the_plan_will_be(sandbox):
    """The route always names the run since `P22-04`'s server half; if a reply
    ever comes back without it, the card says where the plan will be rather
    than inventing one."""
    out = _case(sandbox, {"reply": {"ok": True, "dry": True}}, """
        const plan = document.body.appendChild(new Node('div'));
        const ran = await __t._doDryRun('t1', plan, null);
        console.log(JSON.stringify({ ran, text: plan.textContent }));
    """)
    assert out["ran"] is None
    assert "History" in out["text"] and "not ready" in out["text"], out["text"]


def test_the_plan_drawn_is_the_one_the_reply_names(sandbox):
    """The route answers with the run it wrote, so the card draws that run and
    asks the history for nothing — not whichever finished run is newest."""
    old = {"id": "old", "status": "skipped", "steps": [{"kind": "dry-run", "detail": "an old plan"}]}
    new = {"id": "new", "status": "skipped", "steps": [{"kind": "dry-run", "detail": "this plan"}]}
    out = _case(sandbox, {"before": [old], "after": [old, new],
                          "reply": {"ok": True, "dry": True, "run_id": "new", "run": new}}, """
        const plan = document.body.appendChild(new Node('div'));
        const ran = await __t._doDryRun('t1', plan, null);
        const gets = calls.fetch.filter((c) => c.method !== 'POST').map((c) => c.url);
        console.log(JSON.stringify({ id: ran && ran.id, text: plan.textContent, gets }));
    """)
    assert out["id"] == "new" and "this plan" in out["text"] and "an old plan" not in out["text"], out
    assert not [g for g in out["gets"] if "/runs" in g], "one request: the plan is on the reply"


# ── `B670` / `B802(b)`: each step in words ──────────────────────────────────

@pytest.mark.asyncio
async def test_a_run_fired_by_an_event_shows_its_cause_as_a_cause(sandbox, task_db, monkeypatch):
    """`B670`'s `Verify`, through the real writer: the scheduler runs a task
    fired by `document_updated` and records its `trigger` step; the log draws
    it under *cause*, not *progress*."""
    _seed(task_db, action="tidy_sessions")

    async def _ran(**kwargs):
        return "Tidied 3 sessions", True
    monkeypatch.setitem(ba.BUILTIN_ACTIONS, "tidy_sessions", _ran)
    trigger = build_trigger("event", "document_updated", {"document_id": "d7", "title": "Q3 plan"})
    await _scheduler()._execute_task_locked(
        "t1", "r1", gate_foreground=False, release_executing=False, trigger=trigger)
    _, run = _rows(task_db)
    assert run["steps"][0]["kind"] == "trigger", run["steps"]
    out = _case(sandbox, {}, """
        console.log(JSON.stringify({ html: __t._renderRunSteps(%s) }));
    """ % json.dumps(run))
    first = _steps_of(out["html"])[0]
    assert first["kind"] == "cause", first
    assert "task-run-step-trigger" in first["class"]
    assert first["detail"].startswith("Triggered by document_updated"), first


def test_every_kind_of_step_is_named_in_words(sandbox):
    """One word per kind, a kind nobody taught this file is drawn as itself
    rather than as a word that is not true of it, and a tool step's stored
    status is said in words with the stored value kept in the `title`."""
    steps = [
        {"kind": "trigger", "detail": "Continued from Morning digest — no payload"},
        {"kind": "dry-run", "detail": "Would run: tidy_sessions"},
        {"kind": "progress", "detail": "Continued to Post the summary"},
        {"kind": "tool", "tool": "read_file", "round": 1, "status": "ok", "detail": "/etc/hosts"},
        {"kind": "tool", "tool": "run_shell", "round": 2, "status": "error", "detail": "make"},
        {"kind": "tool", "tool": "run_shell", "round": 3, "status": "blocked", "detail": "rm -rf /"},
        {"kind": "hand-off", "detail": "a kind added later"},
        {"detail": "a step written with no kind"},
    ]
    out = _case(sandbox, {}, """
        console.log(JSON.stringify({ html: __t._renderRunSteps({ steps: %s }) }));
    """ % json.dumps(steps))
    rows = _steps_of(out["html"])
    assert [r["kind"] for r in rows] == [
        "cause", "dry run", "progress", "tool", "tool", "tool", "hand off", "step"], rows
    assert [r["status"] for r in rows[3:6]] == ["done", "failed", "blocked"]
    assert [r["title"] for r in rows[3:6]] == ["ok", "error", "blocked"]
    assert "progress" not in (rows[0]["kind"], rows[1]["kind"]), "B670"
    # The classes the sheet styles by stay the stored values.
    assert "task-run-step-dry-run" in rows[1]["class"]
    assert "task-run-step-error" in rows[4]["class"] and "task-run-step-blocked" in rows[5]["class"]
    assert "2 did not finish" in out["html"]


def test_a_kind_from_the_wire_cannot_break_out_of_its_class(sandbox):
    """`kind` used to be reduced to one of two literals before it reached the
    markup; it is drawn now, so it is the one wire value in this list that
    lands in an attribute. Letters, digits and dashes only, there."""
    out = _case(sandbox, {}, """
        console.log(JSON.stringify({ html: __t._renderRunSteps({ steps: [
          { kind: 'x" onmouseover="alert(1)', detail: '<img src=x onerror=alert(2)>' }] }) }));
    """)

    class _Attrs(HTMLParser):
        def __init__(self):
            super().__init__(convert_charrefs=True)
            self.tags = []

        def handle_starttag(self, tag, attrs):
            self.tags.append((tag, dict(attrs)))

    p = _Attrs()
    p.feed(out["html"])
    names = {name for _, attrs in p.tags for name in attrs}
    assert names <= {"class", "title"}, names
    assert [t for t, _ in p.tags if t == "img"] == [], "the detail became markup"
    li = next(attrs for tag, attrs in p.tags if tag == "li")
    assert li["class"] == "task-run-step task-run-step-xonmouseoveralert1", li
