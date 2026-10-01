# SPDX-License-Identifier: AGPL-3.0-or-later
r"""`P22-03` — the task form, moved once and used twice; with `B671` and `B802(c)`.

**What was on the tree, measured 2026-10-01 at `f37de0f`.** The New/Edit form was
`_showForm` (`static/js/tasks.js:1445`) and `_saveTaskForm` (`:1992`): one
700-line closure that wrote into the Tasks window's `.modal-body`, found its
fields with `document.getElementById`, and on Cancel or Save switched the Tasks
window's tab. Nothing else could mount it, so the Workbench's side panel
(`P22-02`) would have needed a second copy. `P8-32` had put `tz_name`,
`max_retries` and `timeout_seconds` on the wire with no input for any of them,
and `/meta/events` had served a `payload_summary` per event since `P8-23` that
nothing read.

**What these cases drive.** `mountTaskFields` from `static/js/tasks/taskFields.js`
— the function both places mount — under node, in the shared sandbox, with the
DOM shim's opt-in parser so the form's own markup is what it finds. Where a
case needs the server's half it calls the server: the row a form is filled from
is the real `_task_to_dict`, the event catalogue is the real `/meta/events`
handler, and the Verify loop posts what the form sent to the real create route
and draws the card from the row that comes back (`Law 20`).

Two cases are about the move itself rather than the new fields, because the
move is the row: two forms on one page each read their own fields (a
document-wide lookup would have one form's Save read the other's), and a form
that has been replaced writes nothing when a late fetch lands.
"""

from __future__ import annotations

import asyncio
import json
import shutil
import sys
from datetime import datetime, timezone
from html.parser import HTMLParser
from pathlib import Path
from types import SimpleNamespace
from zoneinfo import ZoneInfo

import pytest

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(Path(__file__).resolve().parent))

TASKS_JS = ROOT / "static" / "js" / "tasks.js"
TASK_FIELDS_JS = ROOT / "static" / "js" / "tasks" / "taskFields.js"

pytestmark = pytest.mark.skipif(not shutil.which("node"), reason="node binary not on PATH")

from tests.helpers.js_source import js_function  # noqa: E402
from tests.helpers.source_text import blank_text  # noqa: E402
from test_the_palette_moves_to_the_server_js import _SHIM, _STUBS  # noqa: E402
from test_tool_effect_surfaces_js import _make_sandbox, _run  # noqa: E402
# The temp-database fixture the dry-run row's tests already use (`Law 14`).
from test_a_dry_run_is_dry import task_db  # noqa: E402,F401


# ── the sandbox ─────────────────────────────────────────────────────────────

_SHIM_PARSED = _SHIM + r"""
import { installHtmlParsing } from './dom.js';
installHtmlParsing();

/** A click as a browser delivers it: on the target, then up its ancestors. */
export function click(node) {
  const ev = { type: 'click', target: node, _stopped: false,
    stopPropagation() { this._stopped = true; }, preventDefault() {} };
  for (let n = node; n && !ev._stopped; n = n.parentNode) n.dispatchEvent(ev);
}
export function change(node) {
  node.dispatchEvent({ type: 'change', target: node, stopPropagation() {}, preventDefault() {} });
}
"""

_TASKS_EXPORT = (
    "\nexport const __t = { _showForm, _fetchTasks, _scheduleLabel, _renderMainView,"
    " _retryWords, _timeLimitWords };\n"
)
_FIELDS_EXPORT = (
    "\nexport const __f = { _eventPayloadSentence, _instantOfWallClock, _zonePlace };\n"
)


@pytest.fixture(scope="module")
def sandbox(tmp_path_factory):
    box = _make_sandbox(tmp_path_factory.mktemp("taskfields"), TASKS_JS, _SHIM_PARSED, _STUBS)
    copy = box / TASKS_JS.name
    copy.write_text(copy.read_text(encoding="utf-8") + _TASKS_EXPORT, encoding="utf-8")
    fields = box / "tasks" / TASK_FIELDS_JS.name
    fields.write_text(fields.read_text(encoding="utf-8") + _FIELDS_EXPORT, encoding="utf-8")
    return box


_PREAMBLE = (
    "import { document, Node, calls, mockFetch, res, tick, click, change, byId } from './shim.js';\n"
    "import { calls as ui } from './ui.js';\n"
    "const { __t } = await import('./tasks.js');\n"
    "const { mountTaskFields, __f } = await import('./tasks/taskFields.js');\n"
)

# Every case answers the form's own requests from one table, so a case states
# only what it is about. `saved` is what a POST or PUT answers with.
_ROUTES_JS = r"""
const ROUTES = %s;
mockFetch(async (url, opts) => {
  const method = (opts && opts.method) || 'GET';
  if (url.includes('/api/tasks/meta/events')) return res(200, ROUTES.events || { events: [] });
  if (url.includes('/api/tasks/meta/actions')) return res(200, ROUTES.actions || { actions: [] });
  if (url.includes('/api/tasks/meta/output-targets')) {
    return res(200, { targets: ROUTES.targets || [{ value: 'session', label: 'Session' }] });
  }
  if (url.includes('/api/models')) {
    if (ROUTES.modelsGate) await globalThis[ROUTES.modelsGate];
    return res(200, { items: ROUTES.models || [] });
  }
  if (url.includes('/api/email/accounts')) return res(200, { accounts: [] });
  if (method === 'POST' && /\/api\/tasks$/.test(url)) return res(ROUTES.status || 200, ROUTES.saved || {});
  if (method === 'PUT') return res(ROUTES.status || 200, ROUTES.saved || {});
  if (method === 'GET' && /\/api\/tasks$/.test(url)) {
    return res(200, { tasks: ROUTES.tasks || [],
      graph: { nodes: [], edges: [], conditions: ['success', 'error'], max_depth: 10 } });
  }
  return res(200, {});
});
const writes = () => calls.fetch.filter((c) => c.method === 'PUT' || c.method === 'POST');
const q = (root, id) => root.querySelector('#' + id);
const hostIn = (parent) => {
  const h = (parent || document.body).appendChild(new Node('div'));
  h.className = 'panel-host';
  return h;
};
"""


def _case(sandbox, routes: dict, script: str) -> dict:
    return _run(sandbox, _PREAMBLE, (_ROUTES_JS % json.dumps(routes)) + script)


# ── the server's half, called rather than copied ────────────────────────────

_REQUEST = SimpleNamespace(state=SimpleNamespace(current_user=None))


def _endpoint(path: str, method: str = "GET"):
    import routes.task.task_routes as task_routes
    router = task_routes.setup_task_routes(SimpleNamespace())
    return next(r.endpoint for r in router.routes
                if getattr(r, "path", None) == path and method in getattr(r, "methods", set()))


def _served_events() -> dict:
    """What `GET /api/tasks/meta/events` answers, from the real handler."""
    out = asyncio.run(_endpoint("/api/tasks/meta/events")(_REQUEST))
    return json.loads(json.dumps(out))


def _served_row(task_db, **columns) -> dict:
    """A task row exactly as `GET /api/tasks` serves it: a real `ScheduledTask`
    through the real `_task_to_dict`."""
    from core.database import ScheduledTask
    import routes.task.task_routes as task_routes
    db = task_db()
    try:
        # The chain targets are real rows too: the edge columns are foreign keys.
        for other in _OTHERS:
            if not db.query(ScheduledTask).filter(ScheduledTask.id == other["id"]).first():
                db.add(ScheduledTask(id=other["id"], owner=None, name=other["name"],
                                     task_type="llm", prompt="x", trigger_type="webhook",
                                     status="active"))
        db.commit()
        row = ScheduledTask(**{
            "id": "t1", "owner": None, "name": "Morning brief", "task_type": "llm",
            "prompt": "Summarise my inbox", "trigger_type": "schedule", "schedule": "daily",
            "scheduled_time": "09:00", "status": "active", "output_target": "session",
            "run_count": 0, **columns})
        db.add(row)
        db.commit()
        db.refresh(row)
        return json.loads(json.dumps(task_routes._task_to_dict(row)))
    finally:
        db.close()


def _create(task_db, monkeypatch, body: dict) -> dict:
    """POST what the form sent to the real create route; the row it returns."""
    import routes.task.task_routes as task_routes
    monkeypatch.setattr(task_routes, "SessionLocal", task_db)
    endpoint = _endpoint("/api/tasks", "POST")
    out = asyncio.run(endpoint(_REQUEST, task_routes.TaskCreate(**body)))
    return json.loads(json.dumps(out))


_OTHERS = [{"id": "t2", "name": "Post the summary"}, {"id": "t3", "name": "Tell me it broke"}]


# ── one form, rendered into its host ────────────────────────────────────────

def test_the_form_renders_into_its_host_and_owns_nothing_outside_it(sandbox):
    """The contract's first clause: `host` gets the form, and only `host`."""
    out = _case(sandbox, {}, """
        const elsewhere = hostIn();
        elsewhere.innerHTML = '<p id="not-the-form">untouched</p>';
        const host = hostIn();
        mountTaskFields(host, { task: null, tasks: [] });
        await tick();
        const name = byId('task-form-name');
        console.log(JSON.stringify({
          inHost: !!q(host, 'task-form-name') && !!q(host, 'task-form-save'),
          nameIsTheHosts: host.contains(name),
          heading: host.querySelector('h2').textContent,
          elsewhere: byId('not-the-form').textContent,
          button: q(host, 'task-form-save').textContent.trim(),
        }));
    """)
    assert out["inHost"] and out["nameIsTheHosts"], out
    assert out["heading"] == "New Task" and out["button"] == "Create", out
    assert out["elsewhere"] == "untouched"


def test_it_is_filled_from_a_row_as_get_api_tasks_serves_it(sandbox, task_db):
    """`task` is "a row exactly as GET /api/tasks serves it" — so it is built by
    the real `_task_to_dict`, with all three `P8-32` settings set, and the form
    has to show each one back. The prompt carries `</textarea>` because the
    moved form interpolated it raw: the element closed early and the rest of
    the prompt became markup. It is escaped now and comes back intact."""
    row = _served_row(task_db, tz_name="Australia/Sydney", max_retries=3,
                      timeout_seconds=600, then_task_id="t2", else_task_id="t3",
                      prompt="Summarise </textarea><b>this</b>")
    out = _case(sandbox, {}, """
        const host = hostIn();
        mountTaskFields(host, { task: %s, tasks: %s });
        await tick();
        const sel = (id) => q(host, id).value;
        const active = q(host, 'task-form-type-toggle').querySelector('.task-toggle-btn.active');
        console.log(JSON.stringify({
          heading: host.querySelector('h2').textContent,
          name: sel('task-form-name'), prompt: sel('task-form-prompt'),
          type: active && active.dataset.val, schedule: sel('task-form-schedule'),
          hour: String(sel('task-form-time-wrap-hour')), min: String(sel('task-form-time-wrap-min')),
          zone: sel('task-form-tz'), note: q(host, 'task-form-tz-note').textContent,
          retries: sel('task-form-retries'),
          limit: sel('task-form-timeout'), unit: String(sel('task-form-timeout-unit')),
          then: sel('task-form-chain'), otherwise: sel('task-form-chain-else'),
          bold: host.querySelectorAll('b').length,
        }));
    """ % (json.dumps(row), json.dumps([row] + _OTHERS)))
    assert out["heading"] == "Edit Task"
    assert out["name"] == "Morning brief"
    assert out["prompt"] == "Summarise </textarea><b>this</b>", out["prompt"]
    assert out["bold"] == 0, "the stored prompt became markup"
    assert out["type"] == "llm" and out["schedule"] == "daily"
    # A zoned task's time is on that zone's clock and is shown as stored.
    assert (out["hour"], out["min"]) == ("9", "0"), out
    assert out["zone"] == "Australia/Sydney" and out["note"] == "The time above is Sydney time."
    assert out["retries"] == "3"
    assert (out["limit"], out["unit"]) == ("10", "60"), "600 seconds is shown as 10 minutes"
    assert (out["then"], out["otherwise"]) == ("t2", "t3")


# ── what a save sends ───────────────────────────────────────────────────────

def _edit_and_save(sandbox, row: dict, edits: str, routes: dict | None = None) -> dict:
    return _case(sandbox, routes or {"saved": row}, """
        const host = hostIn();
        mountTaskFields(host, { task: %s, tasks: %s });
        await tick();
        %s
        click(q(host, 'task-form-save'));
        await tick();
        console.log(JSON.stringify({ writes: writes(), errors: ui.errors }));
    """ % (json.dumps(row), json.dumps([row] + _OTHERS), edits))


def test_a_save_sends_the_three_settings_and_both_branches(sandbox, task_db):
    """`B802(c)`: on the wire in `_task_to_dict`, validated on create and edit,
    and no input for any of them. The time goes out as typed because the zone
    says whose clock it is on (`compute_next_run` reads it that way)."""
    row = _served_row(task_db, tz_name="Australia/Sydney", max_retries=3, timeout_seconds=600)
    out = _edit_and_save(sandbox, row, """
        q(host, 'task-form-tz').value = 'Europe/Berlin';
        q(host, 'task-form-time-wrap-hour').value = '7';
        q(host, 'task-form-time-wrap-min').value = '30';
        q(host, 'task-form-retries').value = '5';
        q(host, 'task-form-timeout').value = '2';
        q(host, 'task-form-timeout-unit').value = '3600';
        q(host, 'task-form-chain').value = 't2';
        q(host, 'task-form-chain-else').value = 't3';
    """)
    assert out["errors"] == [], out["errors"]
    (write,) = out["writes"]
    assert write["method"] == "PUT" and write["url"].endswith("/api/tasks/t1"), write
    body = write["body"]
    assert body["tz_name"] == "Europe/Berlin"
    assert body["scheduled_time"] == "07:30", "a zoned time is sent as typed"
    assert body["max_retries"] == 5
    assert body["timeout_seconds"] == 7200
    assert (body["then_task_id"], body["else_task_id"]) == ("t2", "t3")
    assert body["prompt"] == "Summarise my inbox" and body["schedule"] == "daily"


def test_without_a_zone_the_time_is_converted_exactly_as_before(sandbox, task_db):
    """`Law 1`. A task with no zone keeps `_localTimeToUtc`: run with the
    browser in Kolkata (UTC+05:30, no daylight saving), a stored 03:30 UTC is
    shown as 09:00 and goes back out as 03:30."""
    row = _served_row(task_db, scheduled_time="03:30")
    out = _case(sandbox, {"saved": row}, """
        process.env.TZ = 'Asia/Kolkata';
        const host = hostIn();
        mountTaskFields(host, { task: %s, tasks: [] });
        await tick();
        const shown = [String(q(host, 'task-form-time-wrap-hour').value), String(q(host, 'task-form-time-wrap-min').value)];
        const note = q(host, 'task-form-tz-note').textContent;
        click(q(host, 'task-form-save'));
        await tick();
        console.log(JSON.stringify({ shown, note, body: writes()[0].body,
          label: __t._scheduleLabel(%s) }));
    """ % (json.dumps(row), json.dumps(row)))
    assert out["shown"] == ["9", "0"], out["shown"]
    assert out["body"]["scheduled_time"] == "03:30"
    assert out["body"]["tz_name"] == "", "Not set is sent as the empty string that clears a zone"
    assert out["note"].startswith("Not set:"), out["note"]
    assert "09:00" in out["label"] and "time" not in out["label"], out["label"]


def test_clearing_the_three_boxes_sends_what_clears_them(sandbox, task_db):
    """Each is optional and blank means "no opinion". On an edit, blank has to
    reach the server as the value that clears — `0`, `0` and `""` — or a
    retry count, once set, could never be taken off."""
    row = _served_row(task_db, tz_name="Australia/Sydney", max_retries=3, timeout_seconds=600)
    out = _edit_and_save(sandbox, row, """
        q(host, 'task-form-tz').value = '';
        q(host, 'task-form-retries').value = '';
        q(host, 'task-form-timeout').value = '';
    """)
    body = out["writes"][0]["body"]
    assert (body["tz_name"], body["max_retries"], body["timeout_seconds"]) == ("", 0, 0), body


@pytest.mark.parametrize("edits,message", [
    ("q(host, 'task-form-retries').value = '11';",
     "Retries must be a whole number from 0 to 10"),
    ("q(host, 'task-form-retries').value = '1.5';",
     "Retries must be a whole number from 0 to 10"),
    ("q(host, 'task-form-timeout').value = '10'; q(host, 'task-form-timeout-unit').value = '1';",
     "The time limit must be between 30 seconds and 24 hours"),
    ("q(host, 'task-form-timeout').value = '25'; q(host, 'task-form-timeout-unit').value = '3600';",
     "The time limit must be between 30 seconds and 24 hours"),
    # And the messages the form already had, carried over unchanged.
    ("q(host, 'task-form-prompt').value = '   ';", "Prompt is required"),
])
def test_a_value_the_server_would_refuse_is_refused_in_words_first(sandbox, task_db, edits, message):
    """The server's refusal names fields (`max_retries must be between 0 and
    10`); the person is told in words, and nothing is sent."""
    row = _served_row(task_db)
    out = _edit_and_save(sandbox, row, edits)
    assert out["writes"] == [], out["writes"]
    assert out["errors"] == [message], out["errors"]


def test_a_refusal_from_the_server_is_shown_in_its_own_words(sandbox, task_db):
    """Both writes threw one fixed sentence whatever the server said, so a
    refusal that names its cause — a zone this machine does not know, a chain
    that would loop (`P22-01`) — reached the person as "Failed to update task"."""
    row = _served_row(task_db)
    out = _edit_and_save(sandbox, row, "", {
        "status": 400,
        "saved": {"detail": "Not a timezone this machine knows: 'Mars/Olympus'."},
    })
    assert out["errors"] == ["Not a timezone this machine knows: 'Mars/Olympus'."], out


def test_a_one_off_in_a_zone_is_the_instant_on_that_zones_clock(sandbox):
    """`Once` is the one schedule the server takes as an absolute instant
    (`compute_next_run` returns `scheduled_date` as it is), so "09:00 on the
    3rd, Sydney time" has to be turned into that instant before it is sent.
    The expected value is Python's `zoneinfo`, not a number written here."""
    expected = (datetime(2026, 11, 3, 9, 0, tzinfo=ZoneInfo("Australia/Sydney"))
                .astimezone(timezone.utc).strftime("%Y-%m-%dT%H:%M:%S.000Z"))
    out = _case(sandbox, {"saved": {"id": "new"}}, """
        process.env.TZ = 'America/New_York';
        const host = hostIn();
        mountTaskFields(host, { task: { task_type: 'llm', trigger_type: 'schedule', schedule: 'once',
                                        prompt: 'Renew the domain' }, tasks: [] });
        await tick();
        q(host, 'task-form-tz').value = 'Australia/Sydney';
        q(host, 'task-form-date-year').value = '2026';
        q(host, 'task-form-date-month').value = '10';
        q(host, 'task-form-date-day').value = '3';
        q(host, 'task-form-time-wrap-hour').value = '9';
        q(host, 'task-form-time-wrap-min').value = '0';
        click(q(host, 'task-form-save'));
        await tick();
        console.log(JSON.stringify({ write: writes()[0] }));
    """)
    body = out["write"]["body"]
    assert out["write"]["method"] == "POST", "a draft is created, not edited"
    assert body["scheduled_date"] == expected, (body["scheduled_date"], expected)
    assert body["tz_name"] == "Australia/Sydney"


# ── the owner's callbacks, and destroy ──────────────────────────────────────

def test_a_save_hands_the_owner_the_row_the_server_returned(sandbox, task_db):
    """`onSaved` gets the POST/PUT response's row. Both routes answer with the
    row itself; a `{ task }` envelope is read too."""
    row = _served_row(task_db)
    saved = dict(row, name="Renamed by the server")
    out = _case(sandbox, {"saved": saved}, """
        const got = [];
        const host = hostIn();
        mountTaskFields(host, { task: %s, tasks: [], onSaved: (r) => got.push(r) });
        await tick();
        click(q(host, 'task-form-save'));
        await tick();
        console.log(JSON.stringify({ got, toasts: ui.toasts }));
    """ % json.dumps(row))
    assert out["got"] == [saved], out["got"]
    assert out["toasts"] == ["Task updated"], "the form's own confirmation is kept"
    out = _case(sandbox, {"saved": {"ok": True, "task": saved}}, """
        const got = [];
        const host = hostIn();
        mountTaskFields(host, { task: { task_type: 'llm', prompt: 'x' }, tasks: [], onSaved: (r) => got.push(r) });
        await tick();
        click(q(host, 'task-form-save'));
        await tick();
        console.log(JSON.stringify({ got, method: writes()[0].method, toasts: ui.toasts }));
    """)
    assert out["got"] == [saved] and out["method"] == "POST", out
    assert out["toasts"] == ["Task created"]


def test_cancel_calls_the_owner_and_writes_nothing(sandbox, task_db):
    row = _served_row(task_db)
    out = _case(sandbox, {}, """
        let cancelled = 0;
        const host = hostIn();
        mountTaskFields(host, { task: %s, tasks: [], onCancel: () => { cancelled += 1; } });
        await tick();
        click(q(host, 'task-form-cancel'));
        await tick();
        console.log(JSON.stringify({ cancelled, writes: writes() }));
    """ % json.dumps(row))
    assert out == {"cancelled": 1, "writes": []}, out


def test_destroy_empties_the_host_and_a_late_answer_writes_nothing(sandbox, task_db):
    """The panel mounts a node's form, and the next node's into the same host.
    A model list that lands late must not fill the next form with this one's
    pinned model — the race the old document-wide lookup had in the Tasks
    window already, now with two windows to lose it in."""
    row = _served_row(task_db, model="old-model", endpoint_url="http://gpu-a")
    out = _case(sandbox, {"modelsGate": "__gate"}, """
        let open;
        globalThis.__gate = new Promise((r) => { open = r; });
        const host = hostIn();
        const first = mountTaskFields(host, { task: %s, tasks: [] });
        await tick(2);
        first.destroy();
        const emptied = host.childNodes.length;
        first.destroy();   // a second destroy is harmless
        mountTaskFields(host, { task: { id: 't9', name: 'Next node', task_type: 'llm', prompt: 'y' }, tasks: [] });
        open();
        await tick();
        const options = q(host, 'task-form-model').options.map((o) => o.textContent);
        console.log(JSON.stringify({ emptied, options, name: q(host, 'task-form-name').value }));
    """ % json.dumps(row))
    assert out["emptied"] == 0
    assert out["name"] == "Next node"
    assert not any("old-model" in o for o in out["options"]), out["options"]


def test_a_second_mount_into_the_same_host_retires_the_first(sandbox, task_db):
    """The panel may mount the next node's form without destroying the last
    one first. The first form is retired by the mount itself, so its late
    model list cannot reach the form that replaced it."""
    row = _served_row(task_db, model="old-model", endpoint_url="http://gpu-a")
    out = _case(sandbox, {"modelsGate": "__gate"}, """
        let open;
        globalThis.__gate = new Promise((r) => { open = r; });
        const host = hostIn();
        mountTaskFields(host, { task: %s, tasks: [] });
        await tick(2);
        mountTaskFields(host, { task: { id: 't9', name: 'Next node', task_type: 'llm', prompt: 'y' }, tasks: [] });
        open();
        await tick();
        console.log(JSON.stringify({
          forms: host.querySelectorAll('input').filter((n) => n.id === 'task-form-name').length,
          options: q(host, 'task-form-model').options.map((o) => o.textContent),
        }));
    """ % json.dumps(row))
    assert out["forms"] == 1, out
    assert not any("old-model" in o for o in out["options"]), out["options"]


def test_two_forms_on_one_page_each_save_their_own_fields(sandbox, task_db):
    """The reason the move changed the lookups. The Tasks window and the
    Workbench panel can both have a form open, with the same ids; with
    `document.getElementById` the second form's Save reads the FIRST form's
    prompt and writes it into the second task."""
    a = _served_row(task_db)
    b = dict(a, id="t2", name="Other task", prompt="Other prompt")
    out = _case(sandbox, {"saved": b}, """
        const one = hostIn();
        const two = hostIn();
        mountTaskFields(one, { task: %s, tasks: [] });
        mountTaskFields(two, { task: %s, tasks: [] });
        await tick();
        q(two, 'task-form-prompt').value = 'Edited in the second form';
        q(two, 'task-form-retries').value = '2';
        click(q(two, 'task-form-save'));
        await tick();
        console.log(JSON.stringify({ writes: writes(), first: q(one, 'task-form-prompt').value }));
    """ % (json.dumps(a), json.dumps(b)))
    (write,) = out["writes"]
    assert write["url"].endswith("/api/tasks/t2"), write["url"]
    assert write["body"]["prompt"] == "Edited in the second form", write["body"]["prompt"]
    assert write["body"]["max_retries"] == 2
    assert out["first"] == "Summarise my inbox", "the first form was not touched"


# ── `B671`: what the trigger carries, before the prompt is written ──────────

def test_picking_an_event_says_what_the_prompt_can_refer_to(sandbox):
    """`Verify:` someone who has never opened Tasks picks "Document updated"
    and can tell, from the form, that their prompt can refer to the document's
    title. Driven against the real `/meta/events` answer."""
    events = _served_events()
    summaries = {e["name"]: e["payload_summary"] for e in events["events"]}
    out = _case(sandbox, {"events": events}, """
        const host = hostIn();
        mountTaskFields(host, { task: { task_type: 'llm', trigger_type: 'event' }, tasks: [] });
        await tick();
        const sel = q(host, 'task-form-event');
        sel.value = 'document_updated';
        change(sel);
        const asPrompt = q(host, 'task-form-event-payload').textContent;
        const desc = q(host, 'task-form-event-desc').textContent;
        const actionBtn = q(host, 'task-form-type-toggle').querySelector('[data-val="action"]');
        click(actionBtn);
        await tick();
        const asAction = q(host, 'task-form-event-payload').textContent;
        console.log(JSON.stringify({ asPrompt, asAction, desc }));
    """)
    title = summaries["document_updated"]
    assert "title" in title, "the catalogue's own words name the title"
    assert out["asPrompt"] == f"When it fires, your prompt can refer to {title}.", out
    # Only the prompt executor is handed the trigger; an Action is not.
    assert out["asAction"] == (f"When it fires, the run's log notes {title}. "
                               "Only a Prompt task can refer to that."), out
    assert "Stored as document_updated." in out["desc"], "P8-30's line is unchanged"


def test_an_event_that_declares_nothing_gets_no_sentence(sandbox):
    out = _case(sandbox, {}, """
        console.log(JSON.stringify({
          none: __f._eventPayloadSentence({ name: 'x', payload_summary: '' }, 'llm'),
          missing: __f._eventPayloadSentence({ name: 'x' }, 'llm'),
          research: __f._eventPayloadSentence({ name: 'x', payload_summary: 'the topic' }, 'research'),
        }));
    """)
    assert out["none"] == "" and out["missing"] == ""
    assert out["research"].startswith("When it fires, the run's log notes the topic.")


# ── the Tasks window mounts this form, and the card says what it set ────────

def test_the_tasks_window_form_is_this_form(sandbox, task_db):
    """The Tasks window's New/Edit view is `mountTaskFields` into its body:
    the form is drawn there, Cancel goes back to the Tasks tab, and a save
    refetches the list and goes back to it."""
    row = _served_row(task_db)
    out = _case(sandbox, {"saved": row, "tasks": [row]}, """
        await __t._fetchTasks();
        const modal = document.body.appendChild(new Node('div'));
        modal.setAttribute('id', 'tasks-modal');
        const body = modal.appendChild(new Node('div'));
        body.className = 'modal-body';
        __t._showForm(%s);
        await tick();
        const drawn = !!q(body, 'task-form-name') && !!q(body, 'task-form-tz');
        click(q(body, 'task-form-cancel'));
        await tick();
        const afterCancel = !!q(body, 'tasks-list') && !q(body, 'task-form-name');
        __t._showForm(%s);
        await tick();
        calls.fetch.length = 0;
        click(q(body, 'task-form-save'));
        await tick();
        console.log(JSON.stringify({
          drawn, afterCancel,
          sequence: calls.fetch.map((c) => c.method + ' ' + c.url.replace('http://test.local', '')),
          afterSave: !!q(body, 'tasks-list'),
        }));
    """ % (json.dumps(row), json.dumps(row)))
    assert out["drawn"] and out["afterCancel"], out
    assert out["sequence"][:2] == ["PUT /api/tasks/t1", "GET /api/tasks"], out["sequence"]
    assert out["afterSave"]


def test_tasks_js_holds_no_second_copy_of_the_form():
    """`Law 7`, and the one place `Law 20` allows a whole-file check: a field's
    markup anywhere in `tasks.js` would be a second form. Comments are blanked
    first, because the comments that explain the move name the ids."""
    tasks = blank_text(TASKS_JS.read_text(encoding="utf-8"))
    for marker in ('id="task-form-name"', 'id="task-form-save"', 'id="task-form-chain"'):
        assert marker not in tasks, marker
    fields = blank_text(TASK_FIELDS_JS.read_text(encoding="utf-8"))
    assert 'id="task-form-name"' in fields
    # And `_showForm` reaches it through the shared mount, not around it.
    assert "mountTaskFields(body," in js_function(TASKS_JS.read_text(encoding="utf-8"),
                                                 "function _showForm")


def test_nine_sydney_retry_three_reads_back_the_same_on_the_card(sandbox, task_db, monkeypatch):
    """`P22-03`'s Verify, closed through the server: set "09:00 Sydney, retry 3
    times" in the form, send what the form sends to the real create route, and
    draw the Tasks card from the row it returns. The card says the same, the
    stored next run is 09:00 on Sydney's clock, and opening the form on that row
    shows the same four settings back."""
    first = _case(sandbox, {"saved": {"id": "pending"}}, """
        process.env.TZ = 'Europe/London';
        const host = hostIn();
        mountTaskFields(host, { task: null, tasks: [] });
        await tick();
        q(host, 'task-form-name').value = 'Morning brief';
        q(host, 'task-form-prompt').value = 'Summarise my inbox';
        q(host, 'task-form-tz').value = 'Australia/Sydney';
        q(host, 'task-form-time-wrap-hour').value = '9';
        q(host, 'task-form-time-wrap-min').value = '0';
        q(host, 'task-form-retries').value = '3';
        q(host, 'task-form-timeout').value = '10';
        q(host, 'task-form-timeout-unit').value = '60';
        click(q(host, 'task-form-save'));
        await tick();
        console.log(JSON.stringify({ write: writes()[0], errors: ui.errors }));
    """)
    assert first["errors"] == [], first["errors"]
    assert first["write"]["method"] == "POST"
    row = _create(task_db, monkeypatch, first["write"]["body"])

    assert (row["tz_name"], row["max_retries"], row["timeout_seconds"]) == ("Australia/Sydney", 3, 600)
    next_run = datetime.fromisoformat(row["next_run"].rstrip("Z")).replace(tzinfo=timezone.utc)
    sydney = next_run.astimezone(ZoneInfo("Australia/Sydney"))
    assert (sydney.hour, sydney.minute) == (9, 0), sydney

    out = _case(sandbox, {"tasks": [row]}, """
        process.env.TZ = 'Europe/London';
        await __t._fetchTasks();
        const modal = document.body.appendChild(new Node('div'));
        modal.setAttribute('id', 'tasks-modal');
        const body = modal.appendChild(new Node('div'));
        body.className = 'modal-body';
        __t._renderMainView();
        await tick();
        const card = body.querySelector('.task-card');
        const meta = card.querySelector('.memory-item-meta').textContent;
        const detail = card.querySelectorAll('div').map((d) => d.textContent).filter((t) => t.startsWith('time limit') || t.includes('time limit'));
        const again = hostIn();
        mountTaskFields(again, { task: %s, tasks: [] });
        await tick();
        console.log(JSON.stringify({ meta, detail,
          back: [q(again, 'task-form-tz').value, String(q(again, 'task-form-time-wrap-hour').value),
                 q(again, 'task-form-retries').value, q(again, 'task-form-timeout').value] }));
    """ % json.dumps(row))
    assert out["meta"].startswith("Daily at 09:00"), out["meta"]
    assert "Sydney time" in out["meta"] and "3 retries if it fails" in out["meta"], out["meta"]
    assert any("time limit: 10 min" in d for d in out["detail"]), out["detail"]
    assert out["back"] == ["Australia/Sydney", "9", "3", "10"], out["back"]


def test_the_card_names_retries_only_where_they_happen(sandbox):
    """An event or webhook task that fails waits for its next trigger and is
    never re-run on a clock (`failure_next_run`), so it does not say it
    retries even if a count is stored."""
    out = _case(sandbox, {}, """
        console.log(JSON.stringify({
          one: __t._retryWords({ trigger_type: 'schedule', max_retries: 1 }),
          none: __t._retryWords({ trigger_type: 'schedule', max_retries: 0 }),
          event: __t._retryWords({ trigger_type: 'event', max_retries: 3 }),
          limits: [__t._timeLimitWords(45), __t._timeLimitWords(600), __t._timeLimitWords(7200), __t._timeLimitWords(0)],
          cron: __t._scheduleLabel({ trigger_type: 'schedule', schedule: 'cron', cron_expression: '0 9 * * 1', tz_name: 'America/Argentina/Buenos_Aires' }),
          place: __f._zonePlace('UTC'),
        }));
    """)
    assert out["one"] == "1 retry if it fails" and out["none"] == "" and out["event"] == ""
    assert out["limits"] == ["45 s", "10 min", "2 h", ""]
    assert out["cron"] == "Cron: 0 9 * * 1 (Buenos Aires time)"
    assert out["place"] == "UTC"
