# SPDX-License-Identifier: AGPL-3.0-or-later
"""`P8-22` / `P8-25` / `P8-30` / `P8-31` — Automations, drawn from the wire.

Four rows, one client file. `/meta/actions` returns whole palette nodes now —
`category`, `icon`, `model_backed`, `admin_only` and `params` beside the `name`
and `description` it always carried — plus `categories` and
`default_trigger_count`; `/meta/events` returns the registry with a
`description` per event; and `TaskRun.steps` is migrated, written by both
executors and served. `static/js/tasks.js` kept its own copies of the first
three, its own eleven-name group order, two literal `5`s, and drew neither the
step log nor an event's description.

Driven under node against the real module, in the sandbox pattern
`tests/test_chat_steer_js.py` established and `tests/test_tool_effect_surfaces_js.py`
owns. The shim, the sandbox builder and the runner are imported from that file
rather than copied — one harness, one place it can be fixed (`Law 14`).

**How the private functions are reached, stated rather than glossed.**
`tasks.js` exports one object of modal entry points; everything this file is
about is module-private. The sandbox copy — and only the copy, never the shipped
file — gets **one appended line**, `export const __t = { … }`, naming those
functions. Nothing else about the copy differs, so what runs is the real
function against the real module state: `_fetchActions()` really fetches (the
shim's mock), really fills `_actionByName`, and `_categoryFor` really reads it.
A mutation that puts an action→category table back in this file survives a grep
and dies here.

`openTasks()` builds its whole modal with `innerHTML`, which the shared DOM shim
stores as a string without parsing, so the two form builders cannot be clicked
under it. Those two are asserted the next way down `Law 20`'s list — **the scope
is resolved first and the assertion made inside it** — paired, where it matters,
with the server's half driven for real.

The distinguishing trick in every palette case below: the served node is given a
category, an icon and a `model_backed` flag that **disagree** with the table
this file used to hold. A client still reading its own copy answers the old way
and is caught; a client reading the node follows the server.
"""

import json
import re
import shutil
import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parent))

from test_a_draft_skill_is_uncatalogued_not_inactive import js_function  # noqa: E402
from test_tool_effect_surfaces_js import _make_sandbox, _run  # noqa: E402

ROOT = Path(__file__).resolve().parents[1]
TASKS_JS = ROOT / "static" / "js" / "tasks.js"

pytestmark = pytest.mark.skipif(not shutil.which("node"), reason="node binary not on PATH")


# ── stubs ───────────────────────────────────────────────────────────────────
#
# Only what `tasks.js` touches at import time and along the paths driven here.
# Anything else it imports is copied from `static/js/` for real by the shared
# sandbox builder, so a dependency-free helper costs nothing.

_STUBS = {
    "ui.js": """
export const calls = { toasts: [], errors: [] };
export default {
  esc: (s) => String(s == null ? '' : s),
  showToast: (m) => { calls.toasts.push(String(m)); },
  showError: (m) => { calls.errors.push(String(m)); },
  styledConfirm: async () => true,
  copyToClipboard: () => {},
  isTouchInsideModal: () => false,
};
""",
    "markdown.js": """
export default {
  processWithThinking: (s) => String(s == null ? '' : s),
  squashOutsideCode: (s) => String(s == null ? '' : s),
};
""",
    "spinner.js": """
export function createLoadingRow(){ return { }; }
export function createWhirlpool(){ return { element: { style: {} }, destroy(){} }; }
export default { createWhirlpool: () => ({ element: { style: {} }, destroy(){} }) };
""",
    "windowDrag.js": "export function makeWindowDraggable(){}\n",
    "toolWindowZOrder.js": "export function topPortalZ(){ return 1; }\n",
    "escMenuStack.js": "export function bindMenuDismiss(){ return () => {}; }\nexport function dismissOrRemove(){}\n",
    "appConfig.js": "export async function getSettings(){ return {}; }\nexport function invalidateSettings(){}\n",
}

_SHIM = r"""
import { installDom, Node } from './dom.js';
export const document = installDom();
export { Node };

export const calls = { fetch: [] };

export function mockFetch(handler) {
  globalThis.fetch = async (url, opts) => {
    const entry = { url: String(url), method: (opts && opts.method) || 'GET' };
    if (opts && typeof opts.body === 'string') {
      try { entry.body = JSON.parse(opts.body); } catch { entry.body = opts.body; }
    }
    calls.fetch.push(entry);
    return handler(String(url), opts || {});
  };
}

export function res(status, payload) {
  return { ok: status >= 200 && status < 300, status, json: async () => (payload || {}) };
}

export function tick(n = 8) {
  let p = Promise.resolve();
  for (let i = 0; i < n; i++) p = p.then(() => new Promise((r) => setTimeout(r, 0)));
  return p;
}

/** The form nodes the three extracted readers reach for by id.
 *
 *  `_openTaskForm` writes them as one `innerHTML` string, which this shim
 *  stores without parsing — the same reason the skills shim seeds
 *  `static/index.html`'s ids as standalone elements. Seeded here, the real
 *  functions find the real elements and populate them for real. */
export function seedForm(ids) {
  const made = {};
  for (const id of ids) {
    const n = document.body.appendChild(new Node(id === 'task-form-event' ? 'select' : 'div'));
    n.setAttribute('id', id);
    made[id] = n;
  }
  return made;
}

export function byId(id) { return document.getElementById(id); }

export function fire(node, type) {
  node.dispatchEvent({ type, stopPropagation() {}, preventDefault() {} });
}
"""

# The one line the sandbox copy gains. Every name here is module-private in the
# shipped file; if one is renamed, node fails to parse the copy and says which,
# which is the right failure for a test that claims to drive these.
_TEST_EXPORT = (
    "\nexport const __t = { _taskIcon, _taskAiMark, _categoryFor, _categoryOrder,"
    " _defaultTriggerCount, _actionNode, _actionPromptValue, _fetchActions,"
    " _populateEventPicker, _openStepLogFor, _renderRunSteps,"
    " _renderActivityEntry, _runToActivityEntry, _eventLabel, _scheduleLabel };\n"
)


@pytest.fixture(scope="module")
def tasks_sandbox(tmp_path_factory):
    sandbox = _make_sandbox(tmp_path_factory.mktemp("tasksnodes"), TASKS_JS, _SHIM, _STUBS)
    copy = sandbox / TASKS_JS.name
    copy.write_text(copy.read_text(encoding="utf-8") + _TEST_EXPORT, encoding="utf-8")
    return sandbox


_PREAMBLE = (
    "import { document, calls, mockFetch, res, tick, seedForm, byId, fire }"
    " from './shim.js';\n"
    "const { __t } = await import('./tasks.js');\n"
)


def _tasks(sandbox, script):
    return _run(sandbox, _PREAMBLE, script)


# ── the payload, deliberately at odds with the table this file used to hold ──
#
# `tidy_sessions` was `Chats` + a chat bubble + not model-backed in every one of
# the three client-side maps. Here the server says Forge, a book, and a model.

_PALETTE = {
    "actions": [
        {"name": "tidy_sessions", "description": "Clean up empty chat sessions",
         "category": "Forge", "icon": "book", "model_backed": True,
         "admin_only": False, "params": []},
        {"name": "run_local", "description": "Run a script on this machine",
         "category": "System", "icon": "terminal", "model_backed": False,
         "admin_only": True,
         "params": [{"name": "script", "label": "Script", "type": "text",
                     "required": True, "source": "prompt",
                     "description": "The script body. Always runs on the machine "
                                    "Pantheon is running on."}]},
        {"name": "cookbook_serve", "description": "Start a model serve",
         "category": "Forge", "icon": "book", "model_backed": False,
         "admin_only": True,
         "params": [{"name": "command", "label": "Serve config", "type": "json",
                     "required": True, "source": "prompt",
                     "description": "JSON: {\"preset\": \"name\"}"}]},
    ],
    # Deliberately NOT the eleven names, and not in their order: a client
    # keeping `_CATEGORY_ORDER` answers with the eleven and is caught.
    "categories": ["System", "Forge", "Other"],
    "default_trigger_count": 3,
}

_PALETTE_STORE = """
  mockFetch((url) => {
    if (url.includes('/meta/actions')) return res(200, %s);
    return res(200, {});
  });
  await __t._fetchActions();
""" % json.dumps(_PALETTE)


# ── P8-22 · the taxonomy is the server's ───────────────────────────────────

def test_an_actions_group_comes_from_the_node_and_not_from_a_table_here(tasks_sandbox):
    """`_CATEGORY_MAP` held nineteen action→category entries, two of them for
    actions that no longer exist. The server answers `Forge` for an action the
    old table filed under `Chats`; the client has to follow it."""
    out = _tasks(tasks_sandbox, _PALETTE_STORE + """
        console.log(JSON.stringify({
          served: __t._categoryFor({ task_type: 'action', action: 'tidy_sessions' }),
          unknown: __t._categoryFor({ task_type: 'action', action: 'no_such_action' }),
          llm: __t._categoryFor({ task_type: 'llm' }),
        }));
    """)
    assert out["served"] == "Forge", (
        "a client still holding `_CATEGORY_MAP` answers `Chats` here"
    )
    assert out["unknown"] == "Other", "the fallback the row asks to keep"
    assert out["llm"] == "Other"


def test_the_group_order_is_the_served_one(tasks_sandbox):
    """`_CATEGORY_ORDER` was eleven names written out here. The chips and the
    list both sort by it, so a server that reorders its palette has to move the
    UI with it or the two disagree about where `Forge` sits."""
    out = _tasks(tasks_sandbox, _PALETTE_STORE + """
        console.log(JSON.stringify({ order: __t._categoryOrder() }));
    """)
    assert out["order"] == ["System", "Forge", "Other"]


def test_the_icon_is_the_nodes_semantic_name(tasks_sandbox):
    """`_TASK_ICONS` was keyed by action name, so an eighteenth action drew the
    generic gear until somebody edited this file. It is keyed by the server's
    icon name now — and the two actions `/meta/actions` never offered,
    `run_local` and `cookbook_serve`, are the proof: both were gear."""
    out = _tasks(tasks_sandbox, _PALETTE_STORE + """
        console.log(JSON.stringify({
          served:   __t._taskIcon({ task_type: 'action', action: 'tidy_sessions' }),
          local:    __t._taskIcon({ task_type: 'action', action: 'run_local' }),
          serve:    __t._taskIcon({ task_type: 'action', action: 'cookbook_serve' }),
          unknown:  __t._taskIcon({ task_type: 'action', action: 'no_such_action' }),
          llm:      __t._taskIcon({ task_type: 'llm' }),
        }));
    """)
    # `book` and `terminal` are the two glyphs that did not exist before.
    assert out["served"] == out["serve"], "both are the server's `book`"
    assert out["local"] != out["unknown"], (
        "`run_local` drew the generic gear because nothing was keyed for it"
    )
    assert "<polyline" in out["local"], "the terminal glyph"
    assert out["served"] != out["llm"], (
        "a client still keyed by action name draws `tidy_sessions` as a chat "
        "bubble, which is byte-identical to the LLM fallback"
    )
    for svg in out.values():
        assert svg.startswith("<svg ") and svg.endswith("</svg>")


def test_the_model_badge_reads_the_flag_the_scheduler_reads(tasks_sandbox):
    """`model_backed` was two lists of one fact — `TaskScheduler._MODEL_BACKED_ACTIONS`
    gating the model slot and a `Set` here drawing the badge. The server sends
    the flag; a badge that disagrees with the semaphore is the failure this
    merge exists to make impossible."""
    out = _tasks(tasks_sandbox, _PALETTE_STORE + """
        console.log(JSON.stringify({
          on:  __t._taskAiMark({ task_type: 'action', action: 'tidy_sessions' }),
          off: __t._taskAiMark({ task_type: 'action', action: 'run_local' }),
          llm: __t._taskAiMark({ task_type: 'llm' }),
        }));
    """)
    assert "task-ai-mark" in out["on"], (
        "a client holding its own set answers '' for `tidy_sessions`"
    )
    assert out["off"] == "", "`run_local` runs no model"
    assert "task-ai-mark" in out["llm"], "an LLM task is model-backed by kind"


def test_the_three_client_side_copies_are_gone(tasks_sandbox):
    """`Law 20`'s one permitted whole-file check: these names must not be
    *declared* anywhere in this file. Matched as declarations rather than as
    words, because the comment that records why they went names all three —
    which is `H10` exactly, and the reason an absence test asserts a shape."""
    source = TASKS_JS.read_text(encoding="utf-8")
    for name in ("_CATEGORY_MAP", "_CATEGORY_ORDER", "_MODEL_BACKED_ACTIONS"):
        assert not re.search(rf"\b(?:const|let|var)\s+{name}\s*=", source), name


def test_the_fetch_keeps_the_two_keys_beside_the_actions(tasks_sandbox):
    """`categories` and `default_trigger_count` ride on the same response. A
    `_fetchActions` that kept only `data.actions` would leave the group order
    and the trigger default with nowhere to come from."""
    out = _tasks(tasks_sandbox, _PALETTE_STORE + """
        console.log(JSON.stringify({
          urls: calls.fetch.map(c => c.url),
          names: (await __t._fetchActions()).map(a => a.name),
          order: __t._categoryOrder(),
          count: __t._defaultTriggerCount(),
        }));
    """)
    assert [u for u in out["urls"] if u.endswith("/meta/actions")], out["urls"]
    assert out["names"] == ["tidy_sessions", "run_local", "cookbook_serve"]
    assert out["order"] == ["System", "Forge", "Other"]
    assert out["count"] == 3


def test_a_palette_that_never_answers_still_draws_a_list(tasks_sandbox):
    """The fetch is lazy and the list paints before it lands. Every reader has
    to hold a task with an unknown action without throwing, or the first frame
    of the Tasks modal is an empty box."""
    out = _tasks(tasks_sandbox, """
        mockFetch(() => { throw new Error('no network'); });
        await __t._fetchActions();
        console.log(JSON.stringify({
          cat: __t._categoryFor({ task_type: 'action', action: 'tidy_sessions' }),
          icon: __t._taskIcon({ task_type: 'action', action: 'tidy_sessions' }).slice(0, 4),
          mark: __t._taskAiMark({ task_type: 'action', action: 'tidy_sessions' }),
          order: __t._categoryOrder(),
          count: __t._defaultTriggerCount(),
        }));
    """)
    assert out["cat"] == "Other"
    assert out["icon"] == "<svg"
    assert out["mark"] == ""
    assert out["order"] == []
    assert out["count"] == 1, "the bus reads a missing count as one; never five"


def test_the_action_form_draws_its_field_from_the_nodes_param(tasks_sandbox):
    """`Law 20` option 2 — the scope resolved first, because this builder lives
    inside a modal `openTasks` assembles with `innerHTML`.

    Four built-ins take an argument and the form had a box for none of them:
    picking `ssh_command`, `run_script`, `run_local` or `cookbook_serve` in the
    UI produced a task with an empty `prompt`, and the only surface that said so
    was the run that failed later.
    """
    body = js_function(TASKS_JS.read_text(encoding="utf-8"), "const syncActionExtra")
    assert "params?.[0]" in body or "params[0]" in body, (
        "the field must come from the node's own schema, not from a list of "
        "action names this file would have to keep in step with the registry"
    )
    for key in ("param.label", "param.description", "param.type"):
        assert key in body, key
    assert "task-form-action-param" in body


def test_the_save_reads_the_box_it_drew(tasks_sandbox):
    """The other end of the same field, driven rather than read. `required` is
    on the wire for all four of them and a blank `run_local` is a task that runs
    nothing — which the save has to refuse rather than discover at fire time."""
    out = _tasks(tasks_sandbox, _PALETTE_STORE + """
        seedForm(['task-form-action-param']);
        byId('task-form-action-param').value = '  ./build.sh  ';
        const typed = __t._actionPromptValue('run_local');
        byId('task-form-action-param').value = '';
        const blank = __t._actionPromptValue('run_local');
        console.log(JSON.stringify({
          typed, blank,
          none: __t._actionPromptValue('tidy_sessions'),
          unknown: __t._actionPromptValue('no_such_action'),
        }));
    """)
    assert out["typed"]["value"] == "./build.sh", "trimmed, and read from the box"
    assert out["typed"]["param"]["required"] is True
    assert out["typed"]["param"]["label"] == "Script"
    assert out["blank"]["value"] == "", "an empty required box is what the save refuses"
    assert out["none"] is None, "an action with no parameter must not claim one"
    assert out["unknown"] is None


def test_the_save_refuses_an_empty_required_param(tasks_sandbox):
    """`Law 20` option 2 for the refusal itself, which lives in a 145-line
    closure nothing can call. What it decides ON is driven above."""
    body = js_function(TASKS_JS.read_text(encoding="utf-8"), "const _saveTaskForm")
    assert "_actionPromptValue(action)" in body
    assert "chosen.param.required" in body
    assert "payload.prompt = chosen.value" in body


# ── P8-31 · the two literal fives ──────────────────────────────────────────

def test_neither_five_is_left_in_the_trigger_count_field(tasks_sandbox):
    """`:1541` pre-filled the field with `5` and `:1884` posted
    `parseInt(value || '5')`, in front of an API that had no default and a bus
    that has always read a missing count as one. Three answers to one question.
    Asserted as the absence of the literal from the two scopes that held it —
    a whole-file check would trip on `max="1000"`'s neighbours and on prose."""
    source = TASKS_JS.read_text(encoding="utf-8")
    trigger = js_function(source, "function renderTriggerOpts")
    save = js_function(source, "const _saveTaskForm")
    assert "_defaultTriggerCount()" in trigger
    assert "_defaultTriggerCount()" in save
    assert "|| 5}" not in trigger, "the form default"
    assert "|| '5'" not in save, "the payload default"


def test_the_served_default_is_what_the_form_offers(tasks_sandbox):
    """`DEFAULT_TRIGGER_COUNT` lives beside the bus that reads it and ships on
    `/meta/actions`. The number a person is handed is that one, or — before the
    palette lands — the one the bus applies to a NULL. Never five."""
    out = _tasks(tasks_sandbox, _PALETTE_STORE + """
        console.log(JSON.stringify({ served: __t._defaultTriggerCount() }));
    """)
    assert out["served"] == 3


# ── P8-30 · an event's own sentence, where it is being chosen ──────────────

_EVENTS = {
    "events": [
        {"name": "document_created", "description": "Fires when a document is created"},
        {"name": "document_updated", "description": "Fires when an existing document is edited"},
    ]
}

_EVENT_STORE = """
  mockFetch((url) => {
    if (url.includes('/meta/events')) return res(200, %s);
    return res(200, {});
  });
  seedForm(['task-form-event', 'task-form-event-desc']);
""" % json.dumps(_EVENTS)


def test_the_picker_renders_the_registrys_description(tasks_sandbox):
    """The description has been on the wire and in the `<option>` label; what it
    was not was readable. A `<select>` shows one option and truncates it, so
    somebody deciding between "document created" and "document updated" saw
    neither sentence. It goes under the select, for whatever is chosen."""
    out = _tasks(tasks_sandbox, _EVENT_STORE + """
        await __t._populateEventPicker('document_updated');
        const sel = byId('task-form-event');
        const before = byId('task-form-event-desc').textContent;
        sel.value = 'document_created';
        fire(sel, 'change');
        console.log(JSON.stringify({
          before,
          after: byId('task-form-event-desc').textContent,
          labels: sel.querySelectorAll('option').map(o => o.textContent),
          values: sel.querySelectorAll('option').map(o => o.value),
          titles: sel.querySelectorAll('option').map(o => o.title),
        }));
    """)
    assert "Fires when an existing document is edited" in out["before"], (
        "the sentence the registry wrote, under the control that chose it"
    )
    assert "Fires when a document is created" in out["after"], (
        "a description that does not follow the selection is worse than none — "
        "it describes a trigger the person just moved away from"
    )
    # The stored value stays reachable — it is what a person matches against a
    # log line, and `ScheduledTask.trigger_event` holds those bytes (`Law 1`).
    assert out["values"] == ["document_created", "document_updated"]
    assert out["titles"] == out["values"]
    assert "document_updated" in out["before"], "the stored name is still shown"
    assert out["labels"][1].startswith("Document updated — "), out["labels"]


def test_the_picker_is_what_the_trigger_form_calls(tasks_sandbox):
    """`Law 20` option 2 on the one line that cannot be driven: the builder
    lives inside `_openTaskForm`, which assembles its markup as a string."""
    body = js_function(TASKS_JS.read_text(encoding="utf-8"), "function renderTriggerOpts")
    assert "_populateEventPicker(existing?.trigger_event)" in body
    assert 'id="task-form-event-desc"' in body


def test_a_stored_event_name_reads_as_a_sentence(tasks_sandbox):
    """`_eventLabel` is a *reading* of the stored value and never a rename:
    `FORBIDDEN.md` Part 1 and `ScheduledTask.trigger_event` both depend on the
    bytes, and renaming one disables every task using it."""
    out = _tasks(tasks_sandbox, """
        console.log(JSON.stringify({
          updated: __t._eventLabel('document_updated'),
          empty: __t._eventLabel(''),
          none: __t._eventLabel(null),
        }));
    """)
    assert out["updated"] == "Document updated"
    assert out["empty"] == "" and out["none"] == ""


def test_the_card_no_longer_says_every_1_document_updated(tasks_sandbox):
    """`P8-31` makes one the common case, and `Every ${n} ${evt}${n>1?'s':''}`
    was pluralising a verb. The count only appears when there is one to make."""
    out = _tasks(tasks_sandbox, """
        console.log(JSON.stringify({
          one: __t._scheduleLabel({ trigger_type: 'event', trigger_event: 'document_updated', trigger_count: 1 }),
          none: __t._scheduleLabel({ trigger_type: 'event', trigger_event: 'document_updated' }),
          many: __t._scheduleLabel({ trigger_type: 'event', trigger_event: 'document_updated', trigger_count: 5 }),
        }));
    """)
    assert out["one"] == "On document updated"
    assert out["none"] == out["one"], "a missing count is one, as the bus reads it"
    assert "5" in out["many"] and "updateds" not in out["many"]


# ── P8-25 · what the run actually did ──────────────────────────────────────

_STEPS = [
    {"kind": "progress", "at": "2026-09-18T10:00:00Z", "detail": "Scanning 41 sessions"},
    {"kind": "tool", "at": "2026-09-18T10:00:01Z", "tool": "run_shell", "round": 2,
     "detail": "rm -rf /tmp/build", "status": "blocked",
     "output": "Waiting for an exact user approval."},
    {"kind": "tool", "at": "2026-09-18T10:00:09Z", "tool": "read_file", "round": 3,
     "detail": "/etc/hosts", "status": "ok", "output": "127.0.0.1 localhost"},
]


def test_the_run_history_draws_the_step_log(tasks_sandbox):
    """`TaskRun.steps` is migrated, written by both executors and serialised,
    and until this nothing drew it: the history showed one result string for the
    whole task — for an action task the LAST line its `progress_cb` reported,
    with the rest existing nowhere."""
    out = _tasks(tasks_sandbox, """
        const html = __t._renderRunSteps({ steps: %s });
        console.log(JSON.stringify({ html }));
    """ % json.dumps(_STEPS))
    html = out["html"]
    for expected in ("Scanning 41 sessions", "run_shell", "round 2",
                     "rm -rf /tmp/build", "read_file", "/etc/hosts",
                     "Waiting for an exact user approval."):
        assert expected in html, expected
    assert "3 steps" in html, "the summary is what makes one run findable in twenty"
    assert "1 did not finish" in html, (
        "the run somebody opens a step log for is usually the one that went wrong"
    )
    assert "task-run-step-blocked" in html and "task-run-step-ok" in html


def test_a_run_with_no_steps_draws_no_empty_shell(tasks_sandbox):
    """Every run written before the column was migrated reads as an empty list,
    and so does one that genuinely did nothing. A `0 steps` disclosure on every
    row of a twenty-run history is noise about the past."""
    out = _tasks(tasks_sandbox, """
        console.log(JSON.stringify({
          none: __t._renderRunSteps({ steps: [] }),
          missing: __t._renderRunSteps({}),
          junk: __t._renderRunSteps({ steps: 'not a list' }),
        }));
    """)
    assert out["none"] == "" and out["missing"] == "" and out["junk"] == ""


def test_a_command_in_a_step_cannot_close_the_element_it_is_drawn_in(tasks_sandbox):
    """A step's `detail` is a shell command and its `output` is whatever the
    tool printed. Both are drawn into an HTML string."""
    hostile = [{"kind": "tool", "tool": "run_shell", "round": 1, "status": "ok",
                "detail": "</ol><img src=x onerror=alert(1)>",
                "output": "<script>alert(2)</script>"}]
    out = _tasks(tasks_sandbox, """
        console.log(JSON.stringify({ html: __t._renderRunSteps({ steps: %s }) }));
    """ % json.dumps(hostile))
    assert "<img" not in out["html"] and "<script>" not in out["html"]
    assert "&lt;img" in out["html"]


def test_an_activity_row_says_how_many_steps_and_opens_the_log(tasks_sandbox):
    """`/runs/recent` serves `step_count` with `steps` emptied — 200 runs of up
    to 200 steps is a response in megabytes for a list drawing one line each. So
    the row carries the count and a door, not a second copy of the log."""
    out = _tasks(tasks_sandbox, """
        const entry = __t._runToActivityEntry({
          task_id: 't1', task_name: 'Tidy sessions', task_type: 'action',
          action: 'tidy_sessions', status: 'success', result: 'Tidied 3',
          started_at: '2026-09-18T10:00:00Z', step_count: 6,
        });
        const quiet = __t._runToActivityEntry({
          task_id: 't2', task_name: 'Daily brief', task_type: 'llm',
          status: 'success', result: 'ok', step_count: 0,
        });
        console.log(JSON.stringify({
          stepCount: entry.stepCount,
          row: __t._renderActivityEntry(entry),
          quietRow: __t._renderActivityEntry(quiet),
        }));
    """)
    assert out["stepCount"] == 6
    assert "6 steps" in out["row"]
    assert "task-log-steps" in out["row"], "the chip is the door into the history"
    assert "steps" not in out["quietRow"].split("task-log-row")[0], (
        "a run with no step log gets no chip"
    )
    assert "task-log-steps" not in out["quietRow"]


def test_the_chip_opens_that_tasks_own_history(tasks_sandbox):
    """One renderer for the steps: the chip is a door to the task's run history
    rather than a second copy of the log. Driven — the run history really
    fetches, and the URL it fetches names the task the row was about."""
    out = _tasks(tasks_sandbox, """
        mockFetch(() => res(200, { runs: [] }));
        // `task-history-back` is inside the history's own `innerHTML`, which
        // the shim stores without parsing, and `_showRunHistory` binds it
        // without an optional chain. Seeded so the drive reaches the end.
        seedForm(['tasks-modal', 'task-history-back']);
        const modal = byId('tasks-modal');
        const body = document.createElement('div');
        body.className = 'modal-body';
        modal.appendChild(body);
        const opened = __t._openStepLogFor({ taskId: 't1', taskName: 'Tidy sessions' });
        const nothing = __t._openStepLogFor({ taskName: 'A source row with no task' });
        const nullish = __t._openStepLogFor(null);
        await tick();
        console.log(JSON.stringify({
          opened, nothing, nullish, urls: calls.fetch.map(c => c.url),
        }));
    """)
    assert out["opened"] is True
    assert any("/api/tasks/t1/runs" in u for u in out["urls"]), out["urls"]
    # A registered Activity source can put rows in this list with no task behind
    # them (`P6-07`); a chip on one of those must not try to open a history.
    assert out["nothing"] is False and out["nullish"] is False


def test_the_chip_is_wired_to_that_door(tasks_sandbox):
    """`Law 20` option 2 for the click itself, in `_wireActivityRows`, against
    markup the shim does not parse. What the click *does* is driven above."""
    body = js_function(TASKS_JS.read_text(encoding="utf-8"), "function _wireActivityRows")
    assert ".task-log-steps" in body
    assert "_openStepLogFor(_activityEntries[" in body


def test_the_history_renders_the_steps_it_fetched(tasks_sandbox):
    """`GET /api/tasks/{id}/runs` returns `steps` parsed, and `_showRunHistory`
    is the only place they are drawn."""
    body = js_function(TASKS_JS.read_text(encoding="utf-8"), "async function _showRunHistory")
    assert "_renderRunSteps(run)" in body
    assert "task-run-result" in body, "the result line is not replaced, it is joined"
