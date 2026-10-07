# SPDX-License-Identifier: AGPL-3.0-or-later
r"""`P22-05` (wf-ui) — a workflow's step and its start are the task form, in two more modes.

A workflow is a document of steps (design § 1.2: each step's `config` holds
`ScheduledTask`'s own field names) started by one task. Its side panels could
have been two new forms; they would have copied the 180 lines that draw a
kind's fields — prompt and persona, an action's parameter box from its
`params`, the e-mail accounts, the output targets — and their refusals, and
drifted from them: the `P22-03` incident. So `mountTaskFields` takes a `mode`
(design § 6.4, `Law 7`):

  * `'task'` — the form as it shipped. The 23 cases of
    `test_one_task_form_in_two_places_js.py` hold it, unchanged.
  * `'node'` — a step. Its kind is locked (it was chosen in the palette);
    Trigger, Chain, Time limit and Notifications are the workflow's and are not
    drawn; Output's first choice is "Only hand it to the next step"; the button
    is Done; and Done hands `{ label, kind, config }` to the owner **without a
    request** — the step lives in the workflow's draft until the workflow is
    saved. A Run task step picks the task from the person's own, never a
    workflow.
  * `'trigger'` — a workflow's start: the Trigger section, Time limit and
    Notifications only, saved through the door every task is saved through,
    `PUT /api/tasks/{id}`, carrying none of `task_type`, output, model, chain,
    prompt or name — so a start's Save cannot change what the task is.

Driven: the real `mountTaskFields`, in the form test's own sandbox and route
table (`Law 14`), with the DOM shim's HTML parser so the form's own markup is
what it finds.
"""

from __future__ import annotations

import json
import shutil
import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parent))

pytestmark = pytest.mark.skipif(not shutil.which("node"), reason="node binary not on PATH")

from test_one_task_form_in_two_places_js import sandbox, _case  # noqa: E402,F401

# § 1.2's config keys per kind, plus the label: anything else in a step's
# config is something the form should not have sent.
_NODE_KEYS = {
    "llm": {"prompt", "model", "endpoint_url", "character_id", "crew_member_id", "max_steps", "output_target"},
    "research": {"prompt", "model", "endpoint_url", "output_target"},
    "action": {"action", "prompt", "output_target"},
    "run_task": {"task_id"},
}
_TRIGGER_KEYS = {"trigger_type", "schedule", "scheduled_time", "scheduled_day", "scheduled_date",
                 "cron_expression", "tz_name", "max_retries", "trigger_event", "trigger_count",
                 "timeout_seconds", "notifications_enabled"}

_ACTIONS = {"actions": [
    {"name": "tidy_sessions", "description": "Clean up empty chat sessions", "category": "Chats",
     "icon": "chat", "model_backed": False, "admin_only": False, "params": []},
    {"name": "web_fetch_digest", "description": "Fetch a page and summarise it", "category": "Web",
     "icon": "globe", "model_backed": True, "admin_only": False,
     "params": [{"name": "url", "label": "Page address", "type": "text", "required": True,
                 "source": "prompt", "description": "The address to fetch."}]},
]}

_ROUTES = {"actions": _ACTIONS, "targets": [{"value": "session", "label": "Session"},
                                            {"value": "email", "label": "Email"}]}

_DRAWN = """
const drawn = (host) => ({
  heading: host.querySelector('h2').textContent,
  button: q(host, 'task-form-save').textContent.trim(),
  name: !!q(host, 'task-form-name'), type: !!q(host, 'task-form-type-toggle'),
  typeButtons: q(host, 'task-form-type-toggle') ? q(host, 'task-form-type-toggle').querySelectorAll('button')
    .map((b) => ({ text: b.textContent.trim(), disabled: !!b.disabled })) : null,
  trigger: !!q(host, 'task-form-trigger-toggle'), output: !!q(host, 'task-form-output'),
  outputFirst: q(host, 'task-form-output') && q(host, 'task-form-output').options.length
    ? q(host, 'task-form-output').options[0].textContent : null,
  model: !!q(host, 'task-form-model'), timeout: !!q(host, 'task-form-timeout'),
  chain: !!q(host, 'task-form-chain'), notif: !!q(host, 'task-form-notif'),
  persona: !!q(host, 'task-form-persona'), prompt: !!q(host, 'task-form-prompt'),
});
"""


def _run_case(sandbox, routes, script):
    return _case(sandbox, routes, _DRAWN + script)


def test_a_steps_form_is_the_task_form_with_the_workflows_parts_left_out(sandbox):
    out = _run_case(sandbox, _ROUTES, """
        const host = hostIn();
        mountTaskFields(host, { mode: 'node', task: { name: 'Summarise my inbox', task_type: 'llm',
          prompt: 'Summarise my unread mail' }, tasks: [] });
        await tick();
        console.log(JSON.stringify({ d: drawn(host), prompt: q(host, 'task-form-prompt').value }));
    """)
    d = out["d"]
    assert d["heading"] == "Edit step" and d["button"] == "Done"
    assert d["typeButtons"] == [{"text": "Prompt", "disabled": True}], "the kind is shown, locked"
    assert (d["trigger"], d["timeout"], d["chain"], d["notif"]) == (False, False, False, False), d
    assert d["name"] and d["output"] and d["model"] and d["persona"]
    assert d["outputFirst"] == "Only hand it to the next step"
    assert out["prompt"] == "Summarise my unread mail"


def test_done_hands_the_step_over_and_sends_nothing(sandbox):
    out = _run_case(sandbox, _ROUTES, """
        const got = [];
        const host = hostIn();
        mountTaskFields(host, { mode: 'node', task: { name: 'Summarise my inbox', task_type: 'llm',
          prompt: 'old', crew_member_id: 'crew-1', max_steps: 6 }, tasks: [], onSaved: (r) => got.push(r) });
        await tick();
        q(host, 'task-form-name').value = 'Summarise the inbox';
        q(host, 'task-form-prompt').value = 'Summarise my unread mail in five lines';
        click(q(host, 'task-form-save'));
        await tick();
        console.log(JSON.stringify({ got, writes: writes(), errors: ui.errors }));
    """)
    assert out["writes"] == [], "a step lives in the draft: Done makes no request"
    assert out["errors"] == []
    (step,) = out["got"]
    assert step["label"] == "Summarise the inbox" and step["kind"] == "llm"
    assert step["config"]["prompt"] == "Summarise my unread mail in five lines"
    assert step["config"].get("crew_member_id") == "crew-1" and step["config"].get("max_steps") == 6, \
        "what the form draws no input for is kept as it came"
    assert "output_target" not in step["config"], "only handed to the next step, by default"
    assert set(step["config"]) <= _NODE_KEYS["llm"], step["config"]


def test_a_research_step_has_no_persona_and_a_prompt_is_still_required(sandbox):
    out = _run_case(sandbox, _ROUTES, """
        const got = [];
        const host = hostIn();
        mountTaskFields(host, { mode: 'node', task: { name: 'Look it up', task_type: 'research' }, tasks: [],
          onSaved: (r) => got.push(r) });
        await tick();
        const d = drawn(host);
        click(q(host, 'task-form-save'));
        await tick();
        const refused = { got: got.length, errors: ui.errors.slice() };
        q(host, 'task-form-prompt').value = 'Which banks changed their fees this month?';
        click(q(host, 'task-form-save'));
        await tick();
        console.log(JSON.stringify({ d, refused, got, writes: writes() }));
    """)
    assert out["d"]["persona"] is False and out["d"]["prompt"] is True
    assert out["refused"] == {"got": 0, "errors": ["Prompt is required"]}, "the form's own refusal, kept"
    (step,) = out["got"]
    assert step["kind"] == "research" and set(step["config"]) <= _NODE_KEYS["research"]
    assert out["writes"] == []


def test_an_action_step_reads_its_parameter_the_way_a_task_does(sandbox):
    out = _run_case(sandbox, _ROUTES, """
        const got = [];
        const host = hostIn();
        mountTaskFields(host, { mode: 'node', task: { name: 'Fetch it', task_type: 'action',
          action: 'web_fetch_digest' }, tasks: [], onSaved: (r) => got.push(r) });
        await tick(3);
        const d = drawn(host);
        click(q(host, 'task-form-save'));
        await tick();
        const errors = ui.errors.slice();
        q(host, 'task-form-action-param').value = 'https://example.com/fees';
        click(q(host, 'task-form-save'));
        await tick();
        console.log(JSON.stringify({ d, errors, got, writes: writes() }));
    """)
    assert out["d"]["model"] is False, "an action step has no model"
    assert out["errors"] == ["Page address is required for web_fetch_digest"]
    (step,) = out["got"]
    assert step == {"label": "Fetch it", "kind": "action",
                    "config": {"action": "web_fetch_digest", "prompt": "https://example.com/fees"}}
    assert out["writes"] == []


def test_a_run_task_step_picks_one_of_the_persons_tasks_and_never_a_workflow(sandbox):
    tasks = [{"id": "t2", "name": "Post the summary", "task_type": "llm"},
             {"id": "t5", "name": "Backup", "task_type": "action"},
             {"id": "tw", "name": "Morning brief", "task_type": "workflow"}]
    out = _run_case(sandbox, _ROUTES, """
        const got = [];
        const host = hostIn();
        mountTaskFields(host, { mode: 'node', task: { name: 'Run the backup', task_type: 'run_task', task_id: 't5' },
          tasks: %s, onSaved: (r) => got.push(r) });
        await tick();
        const sel = q(host, 'task-form-run-task');
        const options = sel.options.map((o) => [o.value, o.textContent]);
        const chosen = sel.value;
        const d = drawn(host);
        sel.value = '';
        click(q(host, 'task-form-save'));
        await tick();
        const errors = ui.errors.slice();
        sel.value = 't2';
        click(q(host, 'task-form-save'));
        await tick();
        console.log(JSON.stringify({ options, chosen, d, errors, got, writes: writes() }));
    """ % json.dumps(tasks))
    assert out["options"] == [["", "Choose a task…"], ["t5", "Backup"], ["t2", "Post the summary"]]
    assert out["chosen"] == "t5"
    assert out["d"]["output"] is False and out["d"]["model"] is False, "it runs with the task's own settings"
    assert out["errors"] == ["Choose the task this step runs"]
    assert out["got"] == [{"label": "Run the backup", "kind": "run_task", "config": {"task_id": "t2"}}]
    assert out["writes"] == []


def test_a_starts_form_is_the_trigger_and_saves_only_the_trigger(sandbox):
    trigger = {"id": "tw", "name": "Morning brief", "task_type": "workflow", "status": "paused",
               "trigger_type": "schedule", "schedule": "daily", "scheduled_time": "08:00",
               "tz_name": "Europe/London", "max_retries": 0, "timeout_seconds": 0,
               "notifications_enabled": True, "prompt": "", "output_target": "session"}
    out = _run_case(sandbox, dict(_ROUTES, saved=dict(trigger, scheduled_time="07:30")), """
        const got = [];
        const host = hostIn();
        mountTaskFields(host, { mode: 'trigger', task: %s, tasks: [], onSaved: (r) => got.push(r) });
        await tick();
        const d = drawn(host);
        q(host, 'task-form-time-wrap-hour').value = '7';
        q(host, 'task-form-time-wrap-min').value = '30';
        q(host, 'task-form-timeout').value = '5';
        q(host, 'task-form-timeout-unit').value = '60';
        click(q(host, 'task-form-save'));
        await tick();
        console.log(JSON.stringify({ d, writes: writes(), got, errors: ui.errors }));
    """ % json.dumps(trigger))
    d = out["d"]
    assert d["heading"] == "What starts it" and d["button"] == "Save"
    assert (d["trigger"], d["timeout"], d["notif"]) == (True, True, True)
    assert (d["name"], d["type"], d["output"], d["model"], d["chain"]) == (False, False, False, False, False), d
    assert out["errors"] == []
    (write,) = out["writes"]
    assert write["method"] == "PUT" and write["url"].endswith("/api/tasks/tw")
    body = write["body"]
    assert set(body) <= _TRIGGER_KEYS, sorted(set(body) - _TRIGGER_KEYS)
    assert body["trigger_type"] == "schedule" and body["scheduled_time"] == "07:30"
    assert body["timeout_seconds"] == 300 and body["notifications_enabled"] is True
    assert out["got"] and out["got"][0]["scheduled_time"] == "07:30", "the owner gets the saved row"


def test_a_start_on_an_event_says_which_step_is_handed_it(sandbox):
    from test_one_task_form_in_two_places_js import _served_events
    events = _served_events()
    out = _run_case(sandbox, dict(_ROUTES, events=events), """
        const host = hostIn();
        mountTaskFields(host, { mode: 'trigger', task: { id: 'tw', name: 'Morning brief', task_type: 'workflow',
          trigger_type: 'event', trigger_event: 'document_updated' }, tasks: [] });
        await tick(4);
        console.log(JSON.stringify({ carries: q(host, 'task-form-event-payload').textContent }));
    """)
    assert out["carries"] == ("When it fires, the workflow's first step is handed the document's id and title. "
                              "A Prompt step can refer to it; other steps run with their own settings.")


def test_the_task_form_is_the_same_form_with_no_mode_or_mode_task(sandbox):
    out = _run_case(sandbox, _ROUTES, """
        const row = { id: 't1', name: 'Morning brief', task_type: 'llm', prompt: 'x', trigger_type: 'schedule' };
        const a = hostIn(), b = hostIn();
        mountTaskFields(a, { task: row, tasks: [] });
        mountTaskFields(b, { task: row, tasks: [], mode: 'task' });
        await tick();
        console.log(JSON.stringify({ same: a.innerHTML === b.innerHTML, d: drawn(a) }));
    """)
    assert out["same"] is True
    d = out["d"]
    assert d["heading"] == "Edit task" and d["button"] == "Save"  # P23-05
    assert all(d[k] for k in ("name", "type", "trigger", "output", "model", "timeout", "chain", "notif"))
