# SPDX-License-Identifier: AGPL-3.0-or-later
r"""`B1041` (with `B1064` folded in) — with the Tasks window's form and a
Workbench form open at once, every label names its own form's field, and no
id is on the page twice.

**Measured before this file** (`wb-polish`, Chromium, 2026-10-01; and here on
the form as it stands): the form wrote the same `task-form-*` ids wherever it
was mounted, and ids are document-wide to a browser — so with both forms open,
the Tasks window's *Time zone*, *Retry* and *Time limit* labels focused the
Workbench's fields and the Tasks window's own had none. And most labels named
nothing at all: 16 of the 25 `task-form-label`s had no `for` (*Name*, *Type*,
*Prompt*, *Persona*, *Trigger*, *Frequency*, *Time*, *Action*, *Output*,
*Model*, *Chain*, *Event*, …), plus the four the schedule builds (*Day of
week*, *Day of month*, *Date*, *Cron expression*), so their fields had no
accessible name.

Now a Workbench mount has ids of its own (`ownIds`, passed by
`workbench.js`; `tf3-task-form-name`), the Tasks window's form keeps
`#task-form-*` (the page's, which `tasks.js` and the tour address), and every
label is tied: `for` its field, or named by a group's `aria-labelledby`
(*Type*, *Trigger*, *Chain*, *Time*, *Date*).

Driven (`Law 20`): the real `mountTaskFields`, twice in one document, in the
form tests' sandbox with the DOM shim's HTML parser; each label's `for` is
resolved the way a browser resolves it — the FIRST element in the document
with that id — and must land inside its own form.
"""
from __future__ import annotations

import json
import shutil
import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parent))

from test_one_task_form_in_two_places_js import (  # noqa: E402,F401
    _case, _served_events, _served_row, sandbox, task_db,
)

pytestmark = pytest.mark.skipif(not shutil.which("node"), reason="node binary not on PATH")

_AUDIT = r"""
const FIELD = new Set(['INPUT', 'SELECT', 'TEXTAREA']);
const inside = (host, n) => { for (let x = n; x; x = x.parentNode) if (x === host) return true; return false; };
const forOf = (l) => l.getAttribute('for') || l.htmlFor || '';
const field = (host, name) => host._walk([]).find((n) => n.id === name || n.id.replace(/^tf\d+-/, '') === name) || null;
const audit = (host) => {
  const all = host._walk([]);
  const labels = all.filter((n) => n.tagName === 'LABEL');
  const named = new Set();
  const misfire = [], untied = [];
  for (const l of labels) {
    const words = l.textContent.replace(/\s+/g, ' ').trim();
    const f = forOf(l);
    const wraps = l._walk([]).filter((n) => n !== l && FIELD.has(n.tagName));
    wraps.forEach((n) => named.add(n));
    const groups = l.id ? all.filter((n) => n.getAttribute && n.getAttribute('aria-labelledby') === l.id) : [];
    groups.forEach((g) => g._walk([]).filter((n) => FIELD.has(n.tagName)).forEach((n) => named.add(n)));
    if (f) {
      const target = document.getElementById(f);          // as a browser resolves it: the first in the page
      if (!target || !inside(host, target)) misfire.push(words);
      else named.add(target);
    } else if (!wraps.length && !groups.length) untied.push(words);
  }
  const unnamed = all.filter((n) => FIELD.has(n.tagName) && n.type !== 'hidden' && !named.has(n)
    && !(n.getAttribute('aria-label') || '')).map((n) => n.id || n.tagName);
  return { labels: labels.length, misfire, untied, unnamed };
};
const dupes = () => {
  const seen = new Map();
  for (const n of document._walk([])) if (n.id && /task-form-/.test(n.id)) seen.set(n.id, (seen.get(n.id) || 0) + 1);
  return [...seen].filter(([, c]) => c > 1).map(([id]) => id);
};
const both = async (opts, prep) => {
  document.body.childNodes = [];
  const page = hostIn(), bench = hostIn();
  bench.className = 'workbench-panel';
  // The Workbench's panel comes first in the document, as measured.
  document.body.childNodes = [bench, page];
  mountTaskFields(bench, { ...opts, ownIds: true });
  mountTaskFields(page, { ...opts });
  await tick(4);
  if (prep) { await prep(bench); await prep(page); await tick(4); }
  return { page: audit(page), bench: audit(bench), dupes: dupes(),
           benchIds: bench._walk([]).filter((n) => /task-form-/.test(n.id)).map((n) => n.id).slice(0, 3),
           pageIds: page._walk([]).filter((n) => /task-form-/.test(n.id)).map((n) => n.id).slice(0, 3) };
};
const schedule = (value) => async (host) => { const s = field(host, 'task-form-schedule'); s.value = value; change(s); };
"""


def _actions():
    from src.builtin_actions import ACTION_CATEGORY_ORDER, build_action_palette
    return {"actions": build_action_palette(), "categories": list(ACTION_CATEGORY_ORDER)}


def _cases(task_db):
    row = _served_row(task_db)
    hook = dict(row, id="t9", task_type="action", action="run_local", prompt="echo hi",
                trigger_type="webhook", webhook_token="tok123")
    return {
        "a prompt task on a schedule": ({"task": row, "tasks": []}, None),
        "weekly": ({"task": row, "tasks": []}, "weekly"),
        "monthly": ({"task": row, "tasks": []}, "monthly"),
        "once": ({"task": row, "tasks": []}, "once"),
        "cron": ({"task": row, "tasks": []}, "cron"),
        "a research task on an event": ({"task": dict(row, task_type="research", trigger_type="event",
                                                      trigger_event="document_updated", trigger_count=1),
                                         "tasks": []}, None),
        "an action on a webhook": ({"task": hook, "tasks": []}, None),
        "a new task": ({"task": None, "tasks": []}, None),
        "a step": ({"task": {"name": "Summarise", "task_type": "llm", "prompt": "Sum it"}, "tasks": [],
                    "mode": "node"}, None),
        "an action step": ({"task": {"name": "Tidy", "task_type": "action", "action": "run_local",
                                     "prompt": "ls"}, "tasks": [], "mode": "node"}, None),
        "a start": ({"task": dict(row, task_type="workflow"), "tasks": [], "mode": "trigger"}, None),
    }


def test_both_forms_open_every_label_names_its_own_field_and_no_id_is_twice(sandbox, task_db):
    cases = _cases(task_db)
    script = _AUDIT + "const CASES = %s;\nconst got = {};\n" % json.dumps(
        {k: [opts, sched] for k, (opts, sched) in cases.items()}) + """
        for (const [name, [opts, sched]] of Object.entries(CASES)) {
          got[name] = await both(opts, sched ? schedule(sched) : null);
        }
        console.log(JSON.stringify(got));
    """
    out = _case(sandbox, {"events": _served_events(), "actions": _actions()}, script)
    for name, o in out.items():
        assert o["dupes"] == [], f"{name}: ids on the page twice: {o['dupes']}"
        for which in ("page", "bench"):
            a = o[which]
            assert a["labels"] > 0, (name, which)
            assert a["misfire"] == [], f"{name} ({which}): a label names the other form's field: {a['misfire']}"
            assert a["untied"] == [], f"{name} ({which}): a label names no field: {a['untied']}"
            assert a["unnamed"] == [], f"{name} ({which}): a field no label names: {a['unnamed']}"
        assert all(i.startswith("task-form-") for i in o["pageIds"]), "the page's form keeps #task-form-*"
        assert all(i.startswith("tf") and "-task-form-" in i for i in o["benchIds"]), o["benchIds"]


def test_each_form_still_saves_its_own_fields_with_ids_of_its_own(sandbox, task_db):
    """`P22-03`'s promise, with the Workbench's form on ids of its own: its
    Save reads its own fields, and the page's form is untouched."""
    a = _served_row(task_db)
    b = dict(a, id="t2", name="Other task", prompt="Other prompt")
    out = _case(sandbox, {"saved": b}, _AUDIT + """
        const page = hostIn(), bench = hostIn();
        mountTaskFields(page, { task: %s, tasks: [] });
        mountTaskFields(bench, { task: %s, tasks: [], ownIds: true });
        await tick();
        field(bench, 'task-form-prompt').value = 'Edited in the Workbench';
        field(bench, 'task-form-retries').value = '2';
        click(field(bench, 'task-form-save'));
        await tick();
        console.log(JSON.stringify({ writes: writes(), page: q(page, 'task-form-prompt').value,
                                     benchSave: field(bench, 'task-form-save').id }));
    """ % (json.dumps(a), json.dumps(b)))
    (write,) = out["writes"]
    assert write["url"].endswith("/api/tasks/t2")
    assert write["body"]["prompt"] == "Edited in the Workbench" and write["body"]["max_retries"] == 2
    assert out["page"] == "Summarise my inbox"
    assert out["benchSave"] != "task-form-save", "the Workbench's Save is its own"


def test_the_workbench_mounts_every_form_with_ids_of_its_own():
    """The one place the Workbench is handed the form (`workbench.js`) passes
    `ownIds` for every mode — scope-resolved, not a file grep (`Law 20` 2)."""
    from tests.helpers.js_source import js_binding
    src = (Path(__file__).resolve().parents[1] / "static" / "js" / "workbench" / "workbench.js").read_text(
        encoding="utf-8")
    rooms = js_binding(src, "ROOMS")
    mount = rooms[rooms.index("mountTaskFields: (h, o) =>"):rooms.index("renderSteps:")]
    assert mount.count("ownIds: true") == 2, mount
