# SPDX-License-Identifier: AGPL-3.0-or-later
r"""`P22-04`, the canvas half — *Show me what this would do* on a step, and every
step of its chain says what it would have done.

The row's `Verify:` — someone presses it on a chain that sends mail: no mail
goes, every node says what it would have done, and the two actions a dry run
cannot describe say so. The Tasks card's half (one task's plan) and the server's
(`manage_tasks dry_run`) closed earlier; this is the canvas's. The server half of
a **chain** dry run is `wb-runs`', on its own branch, to the contract both code
to (`/work/notes/P22-WAVE-B.md`):

    POST /api/tasks/{id}/run?dry=true&chain=true
      → 200 { ok, dry: true, message, run_id, run,
              chain: [ { task_id, name, when, depth, steps, declined }, ... ] }

So the reply here is faked **in exactly that shape**, and its words are the
server's own: every plan line is produced by calling the real
`src.builtin_actions.dry_run_plan` for that step, the head's run carries the
real `DRY_RUN_HEADLINE` first as `_record_dry_run` writes it, and the steps are
`{kind: 'dry-run', detail}`, a run's step shape. A plan line the scheduler
rewords reaches these assertions (`Law 20`).

Driven: the real `static/js/workbench/canvas.js` in the shared DOM shim (the
sandbox and fake server of `tests/test_the_workbench_canvas_js.py`, with the
shim's opt-in HTML layer so markup is parsed into nodes), and — for the whole
plan on demand — the real `_renderRunSteps` cut out of `static/js/tasks.js`
with `js_definition`, escaping through the shipped `esc`
(`tests/helpers/esc_stub.ui_default_stub`). That the glue hands the canvas that
very function is pinned in `tests/test_the_workbench_window_js.py`.
"""

from __future__ import annotations

import json
import shutil
import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parent))

from src.builtin_actions import dry_run_plan  # noqa: E402
from src.task_scheduler import DRY_RUN_HEADLINE  # noqa: E402
from test_tool_effect_surfaces_js import _make_sandbox, _run  # noqa: E402
from test_the_workbench_canvas_js import _SHIM as _CANVAS_SHIM, _UP  # noqa: E402
from tests.helpers.esc_stub import ui_default_stub  # noqa: E402
from tests.helpers.js_source import js_binding, js_definition  # noqa: E402
from tests.helpers.source_text import blank_text  # noqa: E402

ROOT = Path(__file__).resolve().parents[1]
JS = ROOT / "static" / "js"
CANVAS_JS = JS / "workbench" / "canvas.js"
TASKS_JS = JS / "tasks.js"

pytestmark = pytest.mark.skipif(not shutil.which("node"), reason="node binary not on PATH")


# ── the chain: a digest that mails you if it works, a memory tidy if it fails ─
#
#   E "Fetch feed"  --if it works-->  A "Morning digest" (daily_brief)
#   A --if it works--> B "Mail me the digest" (a prompt whose result goes to email:self)
#   A --if it fails--> C "Tidy memories" (consolidate_memory — a dry run cannot describe it)
#   B --if it works--> G "Ping the server" (ssh_command: the engine would not plan it here)
#   B --if it fails--> H "Weekly report" (paused: planned, and says so)
#   C --if it works--> D "Audit skills" (audit_skills — the other one)
#   L "Lone task", chained to nothing.

def _task(tid, name, task_type, action=None, then=None, otherwise=None, status="active", output="session"):
    return {"id": tid, "name": name, "task_type": task_type, "action": action, "status": status,
            "output_target": output, "then_task_id": then, "else_task_id": otherwise,
            "last_run_status": "success" if tid == "A" else None}


_TASKS = [
    _task("E", "Fetch feed", "llm", then="A"),
    _task("A", "Morning digest", "action", "daily_brief", then="B", otherwise="C"),
    _task("B", "Mail me the digest", "llm", then="G", otherwise="H", output="email:self"),
    _task("C", "Tidy memories", "action", "consolidate_memory", then="D"),
    _task("D", "Audit skills", "action", "audit_skills"),
    _task("G", "Ping the server", "action", "ssh_command"),
    _task("H", "Weekly report", "llm", status="paused"),
    _task("L", "Lone task", "llm"),
]
_BY_ID = {t["id"]: t for t in _TASKS}


def _plan(tid, *, headline=False):
    t = _BY_ID[tid]
    lines = dry_run_plan(task_type=t["task_type"], action=t["action"], prompt="Summarise it",
                         owner="polish", extra=[f"Where the result would go: {t['output_target']}"])
    lines = ([DRY_RUN_HEADLINE] if headline else []) + lines
    return [{"kind": "dry-run", "detail": line, "at": "2026-10-01T09:00:00Z"} for line in lines]


def _reply():
    """`POST /api/tasks/A/run?dry=true&chain=true`, per the contract: the head's
    recorded run, and the chain breadth first, the head first."""
    head_steps = _plan("A", headline=True)
    run = {"id": "r1", "task_id": "A", "status": "skipped", "result": "\n".join(s["detail"] for s in head_steps),
           "error": None, "steps": head_steps, "step_count": len(head_steps)}
    chain = [
        {"task_id": "A", "name": "Morning digest", "when": None, "depth": 0, "steps": head_steps, "declined": None},
        {"task_id": "B", "name": "Mail me the digest", "when": "success", "depth": 1, "steps": _plan("B"), "declined": None},
        {"task_id": "C", "name": "Tidy memories", "when": "error", "depth": 1, "steps": _plan("C", headline=True),
         "declined": None},
        {"task_id": "G", "name": "Ping the server", "when": "success", "depth": 2, "steps": [],
         "declined": "Action 'ssh_command' requires admin privileges"},
        # A paused successor is planned, with `declined: null`, and its plan says
        # a real run would not start it — wb-runs' reading of the contract
        # (`ce6111e`), whose last line is quoted here as the reply's text.
        {"task_id": "H", "name": "Weekly report", "when": "error", "depth": 2,
         "steps": _plan("H") + [{"kind": "dry-run", "detail": "It is paused, so a real run would not start it."}],
         "declined": None},
        {"task_id": "D", "name": "Audit skills", "when": "success", "depth": 2, "steps": _plan("D"), "declined": None},
    ]
    return {"ok": True, "dry": True, "message": "Dry run — planned, nothing executed", "run_id": "r1",
            "run": run, "chain": chain}


def _renderer() -> str:
    """`tasks.js`'s step renderer and what it needs, as shipped."""
    src = TASKS_JS.read_text(encoding="utf-8")
    code = blank_text(src, "js")
    parts = [js_binding(src, "_STEP_KIND_WORDS") + ";", js_binding(src, "_TOOL_STEP_STATUS_WORDS") + ";"]
    for name in ("_escHtml", "_stepKindWord", "_renderRunSteps"):
        assert code.count(f"function {name}(") == 1, name
        parts.append(js_definition(src, code.index(f"function {name}(")))
    return "\n".join(parts)


_SHIM = _CANVAS_SHIM + r"""
import { installHtmlParsing } from './dom.js';
installHtmlParsing();

// ── the chain dry run, answered in the contract's shape ─────────────────────
export const dry = { reply: null, status: 200, detail: null };
export async function net2(url, init = {}) {
  url = String(url);
  if ((init.method || 'GET') === 'POST' && /\/run(\?|$)/.test(url)) {
    server.calls.push({ url, method: 'POST', body: undefined });
    const body = dry.status === 200 ? dry.reply : { detail: dry.detail };
    return { ok: dry.status === 200, status: dry.status, json: async () => JSON.parse(JSON.stringify(body)) };
  }
  return net(url, init);
}
export function plan(root, id) {
  const n = root.querySelectorAll('.wb-node').find((x) => x.dataset.taskId === id);
  if (!n) return null;
  const row = n.querySelector('.wb-node-plan');
  return { state: n.dataset.plan || null, outcome: n.dataset.outcome || null,
           sub: n.querySelector('.wb-node-sub').textContent,
           line: row ? row.querySelector('.wb-node-plan-line').textContent : null,
           mark: row ? row.querySelector('.wb-node-mark').textContent : null,
           last: n.querySelector('.wb-node-last') ? n.querySelector('.wb-node-last').readable : null,
           label: n.getAttribute('aria-label'), planBtn: !!n.querySelector('.wb-node-plan-btn') };
}
"""

_PREAMBLE = (
    "import { document, Node, server, net2, dry, plan, panel, mountPanel, fire, settle, host, nodeOf,"
    " edgeEls, said, refused, writes, reads } from './shim.js';\n"
    "import { dismissTopMenu } from '../escMenuStack.js';\n"
    "const uiModule = (await import('./ui.js')).default;\n"
    "%s\n"
    "const { mountCanvas } = await import('./canvas.js');\n"
    "const mount = async (opts = {}) => {\n"
    "  const root = host();\n"
    "  const c = mountCanvas(root, { fetch: net2, mountPanel, renderSteps: _renderRunSteps, ...opts });\n"
    "  await c.ready; await settle();\n"
    "  return { root, c };\n"
    "};\n"
    "const press = async (root, id) => {\n"
    "  fire(nodeOf(root, id), 'click');\n"
    "  fire(root.querySelector('.wb-panel-dry'), 'click');\n"
    "  await settle(5);\n"
    "};\n"
    "const ids = ['E', 'A', 'B', 'C', 'D', 'G', 'H', 'L'];\n"
    "const all = (root) => Object.fromEntries(ids.map((id) => [id, plan(root, id)]));\n"
    "const out = (o) => console.log(JSON.stringify(o));\n"
)


@pytest.fixture(scope="module")
def box(tmp_path_factory):
    root = tmp_path_factory.mktemp("wbdry")
    (root / "workbench").mkdir()
    sandbox = _make_sandbox(root / "workbench", CANVAS_JS, _SHIM, {"ui.js": ui_default_stub()})
    for rel in _UP:
        (root / rel).parent.mkdir(parents=True, exist_ok=True)
        shutil.copy(JS / rel, root / rel)
    (root / "windowDrag.js").write_text(
        "export const KEY_STEP = 16;\nexport const MOVE_THRESHOLD = 4;\n"
        "export function makeWindowDraggable() {}\n", encoding="utf-8")
    return sandbox


def _case(box, script, reply=None, status=200, detail=None, tasks=None):
    setup = "server.tasks = %s;\ndry.reply = %s;\ndry.status = %d;\ndry.detail = %s;\n" % (
        json.dumps(tasks if tasks is not None else _TASKS), json.dumps(reply if reply is not None else _reply()),
        status, json.dumps(detail))
    return _run(box, _PREAMBLE % _renderer() + setup, script)


def _lines(tid):
    return [s["detail"] for s in _plan(tid)]


# ── the control and the request ─────────────────────────────────────────────

def test_the_control_is_on_an_open_step_and_asks_one_dry_chain_run(box):
    """"No mail goes": the only request is the dry run of the chain — no real
    run, no write, no history fetch. That nothing is sent or run on the server
    is the server's promise (`P8-33`, `wb-runs`); this half never asks for
    anything else."""
    o = _case(box, """
        const { root } = await mount();
        fire(root.querySelector('.wb-tool-new'), 'click');
        const onNew = root.querySelector('.wb-panel-dry').hidden;
        fire(nodeOf(root, 'A'), 'click');
        const btn = root.querySelector('.wb-panel-dry');
        const shown = { hidden: btn.hidden, text: btn.textContent };
        const before = server.calls.length;
        fire(btn, 'click');
        const busy = { text: btn.textContent, disabled: btn.disabled, said: said(root) };
        await settle(5);
        out({ onNew, shown, busy, after: { text: btn.textContent, disabled: btn.disabled },
              calls: server.calls.slice(before).map((c) => c.method + ' ' + c.url) });
    """)
    assert o["onNew"] is True, "a new step has nothing saved to plan"
    assert o["shown"] == {"hidden": False, "text": "Show me what this would do"}
    assert o["busy"] == {"text": "Working it out…", "disabled": True,
                         "said": "Working out what a run of Morning digest would do. Nothing is running."}
    assert o["after"] == {"text": "Show me what this would do", "disabled": False}
    assert o["calls"] == ["POST /api/tasks/A/run?dry=true&chain=true"]


# ── every node says what it would have done ─────────────────────────────────

def test_every_step_the_run_would_reach_says_what_it_would_do(box):
    o = _case(box, """
        const { root } = await mount();
        await press(root, 'A');
        out({ steps: all(root), said: said(root), action: root.querySelector('.wb-say-action').textContent,
              panel: !root.querySelector('.wb-panel').hidden, focusedA: !!nodeOf(root, 'A').focused });
    """)
    s = o["steps"]
    assert s["A"]["state"] == "planned" and s["A"]["sub"] == "Starts here · Action"
    assert s["A"]["line"] == _lines("A")[0] and s["A"]["line"].startswith("Would run: daily_brief")
    assert s["B"]["state"] == "planned"
    assert s["B"]["sub"] == "After Morning digest, if it works · Prompt"
    assert s["B"]["line"] == "Would send this task's prompt to a model, with tools."
    assert s["B"]["label"] == ("Mail me the digest. After Morning digest, if it works · Prompt. "
                               "Would send this task's prompt to a model, with tools.")
    for k in ("A", "B", "C", "D", "H"):
        assert s[k]["mark"] in ("→", "?"), k
        assert s[k]["planBtn"] is True, k
        assert s[k]["outcome"] is None and s[k]["last"] is None, "the plan replaces the last-run line"
    # P23-05 (COPY-U-24, Doc 2 § 5): what happened, counted once.
    assert o["said"] == "Dry run of Morning digest — nothing ran. 6 steps planned; 2 unreachable, dimmed."
    assert o["action"] == "Clear the plan"
    assert o["panel"] is False and o["focusedA"] is True


def test_the_two_actions_a_dry_run_cannot_describe_say_so_on_their_steps(box):
    o = _case(box, """
        const { root } = await mount();
        await press(root, 'A');
        out({ C: plan(root, 'C'), D: plan(root, 'D') });
    """)
    for k, after in (("C", "After Morning digest, if it fails · Action"),
                     ("D", "After Tidy memories, if it works · Action")):
        assert o[k]["state"] == "cannot", o[k]
        assert o[k]["sub"] == after
        assert o[k]["line"] == "A dry run cannot tell you what this would change."
        assert o[k]["mark"] == "?"


def test_a_step_the_engine_would_not_plan_shows_its_sentence(box):
    o = _case(box, """
        const { root } = await mount();
        await press(root, 'A');
        out({ G: plan(root, 'G'), H: plan(root, 'H') });
    """)
    assert o["G"]["state"] == "declined" and o["G"]["mark"] == "⊘"
    assert o["G"]["line"] == "Would not run: Action 'ssh_command' requires admin privileges"
    assert o["G"]["sub"] == "After Mail me the digest, if it works · Action"
    # A paused step is planned, and says it is paused (`B1036`'s ruling), from
    # its own status: the reply says it only in the plan's last line.
    assert o["H"]["state"] == "planned"
    assert o["H"]["sub"] == "After Mail me the digest, if it fails · Prompt · paused"
    assert o["H"]["line"] == "Would send this task's prompt to a model, with tools."


def test_a_declined_sentence_beside_a_plan_is_said_with_it(box):
    """The contract allows `declined` with steps; the server half sends none
    today. Said on the step all the same, ahead of what it would do."""
    reply = _reply()
    reply["chain"][4]["declined"] = "Weekly report is paused"
    o = _case(box, """
        const { root } = await mount();
        await press(root, 'A');
        out({ H: plan(root, 'H') });
    """, reply=reply)
    assert o["H"]["line"] == "Weekly report is paused · Would send this task's prompt to a model, with tools."


def test_a_step_the_run_would_not_reach_is_set_aside(box):
    """Upstream of the step pressed, or in no workflow at all: dimmed, and
    saying why — and the arrow into the chain from upstream is set aside too."""
    o = _case(box, """
        const { root } = await mount();
        await press(root, 'A');
        const arrows = Object.fromEntries(edgeEls(root).map((g) => [g.getAttribute('data-from') + g.getAttribute('data-to'),
          g.getAttribute('data-plan')]));
        out({ E: plan(root, 'E'), L: plan(root, 'L'), arrows });
    """)
    for k, kind in (("E", "Prompt"), ("L", "Prompt")):
        assert o[k]["state"] == "aside" and o[k]["line"] == "Not reached by this run" and o[k]["mark"] == "–"
        assert o[k]["sub"] == kind and o[k]["planBtn"] is False
        assert o[k]["label"].endswith("Not reached by this run.")
    assert o["arrows"]["EA"] == "aside"
    assert o["arrows"]["AB"] is None and o["arrows"]["AC"] is None and o["arrows"]["CD"] is None


# ── the whole plan, on demand, as text ──────────────────────────────────────

def test_the_whole_plan_is_drawn_by_the_tasks_cards_renderer_as_text(box):
    reply = _reply()
    hostile = '<img src=x onerror="globalThis.__pwned=1">'
    reply["chain"][1]["steps"].append({"kind": "dry-run", "detail": "Command, exactly as it would be sent: " + hostile})
    o = _case(box, """
        const { root } = await mount();
        await press(root, 'A');
        fire(nodeOf(root, 'B').querySelector('.wb-node-plan-btn'), 'click');
        const b = root.querySelector('.wb-plan-box');
        out({ label: b.getAttribute('aria-label'), head: b.querySelector('.wb-plan-head').textContent,
              when: b.querySelector('.wb-plan-when').textContent,
              summary: b.querySelector('summary').textContent,
              open: b.querySelector('details').getAttribute('open') != null,
              lines: b.querySelectorAll('.task-run-step-detail').map((d) => d.textContent),
              words: b.querySelectorAll('.task-run-step-kind').map((d) => d.textContent),
              imgs: b.querySelectorAll('img').length, pwned: globalThis.__pwned || 0,
              focused: b.querySelector('.wb-plan-close').focused });
    """, reply=reply)
    assert o["label"] == "What Mail me the digest would do" == o["head"]
    assert o["when"] == "After Morning digest, if it works."
    assert o["summary"] == "What a real run would do" and o["open"] is True
    assert o["lines"] == _lines("B") + ["Command, exactly as it would be sent: " + hostile]
    assert set(o["words"]) == {"dry run"}, "drawn under the Tasks card's own word for a plan line"
    assert o["imgs"] == 0 and o["pwned"] == 0
    assert o["focused"] is True


def test_a_declined_steps_plan_says_why(box):
    o = _case(box, """
        const { root } = await mount();
        await press(root, 'A');
        fire(nodeOf(root, 'G').querySelector('.wb-node-plan-btn'), 'click');
        const b = root.querySelector('.wb-plan-box');
        out({ declined: b.querySelector('.wb-plan-declined').textContent,
              steps: b.querySelector('.wb-plan-steps').childNodes.length });
    """)
    assert o == {"declined": "Action 'ssh_command' requires admin privileges", "steps": 0}


# ── putting the steps back ──────────────────────────────────────────────────

def test_escape_closes_the_plan_box_then_the_plan_and_clear_does_too(box):
    o = _case(box, """
        const { root } = await mount();
        await press(root, 'A');
        fire(nodeOf(root, 'B').querySelector('.wb-node-plan-btn'), 'click');
        const first = dismissTopMenu();
        const afterBox = { box: !!root.querySelector('.wb-plan-box'), B: plan(root, 'B').state,
                           focusedB: !!nodeOf(root, 'B').focused };
        const second = dismissTopMenu();
        const afterPlan = { A: plan(root, 'A'), E: plan(root, 'E'), focusedA: !!nodeOf(root, 'A').focused,
                            marked: root.dataset.escLayer != null, said: said(root) };
        await press(root, 'A');
        fire(root.querySelector('.wb-say-action'), 'click');
        out({ first, afterBox, second, afterPlan, cleared: plan(root, 'C'), third: dismissTopMenu() });
    """)
    assert o["first"] is True and o["afterBox"] == {"box": False, "B": "planned", "focusedB": True}
    assert o["second"] is True
    a = o["afterPlan"]
    assert a["A"]["state"] is None and a["A"]["outcome"] == "ok" and a["A"]["last"] == "✓ Last run: Success"
    assert a["E"]["state"] is None and a["focusedA"] is True and a["marked"] is False and a["said"] == ""
    assert o["cleared"]["state"] is None and o["third"] is False


def test_a_change_puts_the_steps_back(box):
    o = _case(box, """
        const { root } = await mount();
        await press(root, 'A');
        const port = nodeOf(root, 'L').querySelectorAll('.wb-port').find((p) => p.dataset.when === 'success');
        const e = nodeOf(root, 'E');
        fire(port, 'pointerdown', {});
        fire(port, 'pointerup', { clientX: parseFloat(e.style.left) + 5, clientY: parseFloat(e.style.top) + 5 });
        await settle(5);
        out({ A: plan(root, 'A').state, L: plan(root, 'L').state, writes: writes().length });
    """)
    assert o == {"A": None, "L": None, "writes": 1}


# ── when there is no plan to draw ───────────────────────────────────────────

@pytest.mark.parametrize("status, detail, said", [
    (400, "The chain loops back on itself: if “Morning digest” works it runs “Mail me the digest”, and if "
          "“Mail me the digest” works it runs “Morning digest” again. Remove one of those links to save it.",
     "Nothing was planned: The chain loops back on itself: if “Morning digest” works it runs “Mail me the "
     "digest”, and if “Mail me the digest” works it runs “Morning digest” again. Remove one of those links "
     "to save it."),
    (409, "Task is already running", "Nothing was planned: Task is already running."),
    (403, "Access denied", "Nothing was planned: Access denied."),
], ids=["loop", "running", "denied"])
def test_a_refusal_is_said_and_nothing_is_marked(box, status, detail, said):
    o = _case(box, """
        const { root } = await mount();
        await press(root, 'A');
        out({ said: said(root), refused: refused(root), states: Object.values(all(root)).map((p) => p.state) });
    """, status=status, detail=detail)
    assert o["said"] == said and o["refused"] is True
    assert set(o["states"]) == {None}


def test_a_reply_without_a_chain_draws_the_head_and_claims_nothing_of_the_rest(box):
    """A server that does not know `chain=true` answers as today (`run` only):
    the head's plan is drawn, and nothing is set aside, because whether the run
    would reach the rest is not known."""
    reply = _reply()
    del reply["chain"]
    o = _case(box, """
        const { root } = await mount();
        await press(root, 'A');
        out({ steps: all(root), said: said(root) });
    """, reply=reply)
    assert o["steps"]["A"]["state"] == "planned" and o["steps"]["A"]["line"] == _lines("A")[0]
    assert all(o["steps"][k]["state"] is None for k in "EBCDGHL")
    assert o["said"] == ("Dry run of Morning digest — nothing ran. Only Morning digest was "
                         "planned: this Pantheon did not plan the steps after it.")  # P23-05


def test_unsaved_edits_are_kept_open_and_said_to_be_left_out(box):
    o = _case(box, """
        const { root } = await mount();
        fire(nodeOf(root, 'A'), 'click');
        fire(panel.mounts[0].host, 'input');
        fire(root.querySelector('.wb-panel-dry'), 'click');
        await settle(5);
        out({ panel: !root.querySelector('.wb-panel').hidden, destroyed: panel.mounts[0].destroyed,
              A: plan(root, 'A').state, said: said(root) })
    """)
    assert o["panel"] is True and o["destroyed"] is False and o["A"] == "planned"
    assert o["said"].endswith("Your unsaved changes to Morning digest are not in this plan.")


def test_a_hostile_name_in_a_plan_stays_a_name(box):
    tasks = json.loads(json.dumps(_TASKS))
    evil = '<img src=x onerror="globalThis.__pwned=1">'
    tasks[1]["name"] = evil
    o = _case(box, """
        const { root } = await mount();
        await press(root, 'A');
        out({ sub: plan(root, 'B').sub, said: said(root), pwned: globalThis.__pwned || 0,
              markup: root._walk([]).filter((n) => n._html).length });
    """, tasks=tasks)
    assert o["sub"] == f"After {evil}, if it works · Prompt"
    assert evil in o["said"] and o["pwned"] == 0
    assert o["markup"] == 0, "no markup is assigned until a full plan is opened"
