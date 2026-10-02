# SPDX-License-Identifier: AGPL-3.0-or-later
r"""`P22-20` (wb-canvas-e) — *Why did this fail?* on a failed step, its proposed change, *Apply* and *Undo*.

The browser half of `SLICE-EF-DESIGN.md` § 2 P22-20 (package B, § 3): a failed
step's record (*What went wrong*) gains **Why did this fail?**, whose title
names who is asked; it posts C-A's explain route `{node_id, item}` and shows the
model's reading AS TEXT, labelled as coming from what the step was handed; each
proposed change as a row — what it is now, what it would be — saying in words
when it changes where the request goes (`where`) and when the new value came
out of the run (`from_run`); what was left out (`left_out`); then **Apply**
(C-A's fix route with the proposal's base version) → "Applied as version N." →
**Undo** (the existing restore door with `undo_version`) → **Run it again**.

Driven: the real room, canvas, panels, source and `workflowApi.js` over the
C-A fake server (`tests/helpers/workflow_ca_fake.py`). The world — the
workflow, its failed run, the run's records, the Runs and Versions lists, and
the explanation — is RECORDED from wb-assist's real routes wherever its explain
route is in the tree (the real walker over a loopback server whose
`/v1/entriess` answers 404 with a hint; a scripted model that proposes the
right path and a different Integration); C-A's literal shapes on this branch
alone.
"""

from __future__ import annotations

import shutil
import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parent))

from test_tool_effect_surfaces_js import _run  # noqa: E402
from test_the_workbench_canvas_js import _SHIM as _CANVAS_SHIM  # noqa: E402
from helpers.workflow_ca_fake import (  # noqa: E402
    ROOM_PREAMBLE, as_js, build_sandbox, palette, recorded_explain,
)

pytestmark = pytest.mark.skipif(not shutil.which("node"), reason="node binary not on PATH")

INTEGRATION = {"id": "intg-miniflux", "name": "Miniflux", "preset": "miniflux", "description": "My feeds"}


def _node(id_, kind, label, config):
    return {"id": id_, "kind": kind, "label": label, "config": config, "position": None, "pinned": None}


_FETCH = {"integration": "intg-miniflux", "method": "GET", "path": "/v1/entriess",
          "query": [{"name": "status", "value": "unread"}]}
_GRAPH = {"v": 1, "nodes": [
    _node("list-entries", "http", "List entries", {"integration": "intg-miniflux", "method": "GET", "path": "/v1/entries"}),
    _node("fetch-unread", "http", "Fetch unread", _FETCH),
    _node("summarise", "llm", "Summarise", {"prompt": "Summarise {{ steps.fetch-unread.data.json.entries }}"}),
    _node("each", "foreach", "Each entry", {"list": "{{ steps.fetch-unread.data.json.entries }}", "on_error": "continue",
                                             "step": {"kind": "llm", "label": "Title", "config": {"prompt": "Name it."}}})],
    "edges": [{"from": "list-entries", "port": "success", "to": "fetch-unread"},
              {"from": "fetch-unread", "port": "success", "to": "summarise"},
              {"from": "summarise", "port": "success", "to": "each"}]}
_HINT = {"error": "not found", "hint": "Did you mean /v1/entries?"}
_ERROR = 'HTTP 404 from Miniflux: {"error": "not found", "hint": "Did you mean /v1/entries?"}'
# What the scripted model answers the real route (`explain_step`'s shape):
# the right path, and a different Integration a fix may not choose.
_ANSWER = {"why": "The server says /v1/entriess does not exist and suggests /v1/entries. The path is wrong.",
           "change": {"path": "/v1/entries", "integration": "admin-api"}, "say": "Fix the path."}


def _literal():
    """The same world in C-A's literal shapes (this branch alone)."""
    def rec(node_id, label, status, **more):
        return {"id": f"{node_id}:", "node_id": node_id, "kind": "http", "label": label, "seq": 1, "status": status,
                "attempt": 1, "dry": False, "port": "error" if status == "error" else "success", "workflow_version": 6,
                "started_at": "2026-10-02T07:00:00Z", "finished_at": "2026-10-02T07:00:01Z", "input": {"json": {}},
                "output": {"text": more.pop("text", ""), "data": None}, "error": more.pop("error", None), "steps": [],
                "item": None, **more}
    doc = {"id": "wf1", "name": "Unread digest", "task_id": "t1", "trigger_status": "active", "version": 6,
           "trigger_task": {"id": "t1", "status": "active"},
           "graph": {**_GRAPH, "start": {"position": None}}}
    return {
        "doc": doc, "run_id": "r1",
        "runs": [{"id": "r1", "task_id": "t1", "status": "error", "started_at": "2026-10-02T07:00:00Z", "steps": []}],
        "execution": {"run": {"id": "r1", "status": "error"}, "graph": doc["graph"], "version": 6, "version_kept": True,
                      "cleared": False, "failed": {"node_id": "fetch-unread", "label": "Fetch unread", "error": _ERROR},
                      "nodes": [rec("list-entries", "List entries", "success", text="2 entries"),
                                rec("fetch-unread", "Fetch unread", "error", error=_ERROR)]},
        "versions": [{"version": 6, "name": "Unread digest", "saved_at": "2026-10-02T06:00:00Z", "source": "user",
                      "step_count": 4, "current": True},
                     {"version": 5, "name": "Unread digest", "saved_at": "2026-10-01T06:00:00Z", "source": "user",
                      "step_count": 3, "current": False}],
        "explain": {"why": _ANSWER["why"], "model": "scripted-demo", "changed_since_run": False,
                    "proposal": {"base_version": 6, "node_id": "fetch-unread", "item": None,
                                 "config": {**_FETCH, "path": "/v1/entries"},
                                 "changes": [{"field": "path", "words": "Path", "before": "/v1/entriess",
                                              "after": "/v1/entries", "where": True, "from_run": True}]},
                    "left_out": ["It also suggested sending to a different Integration. That is yours to decide, "
                                 "in the step’s panel."]},
    }


@pytest.fixture(scope="module")
def rec(tmp_path_factory):
    return recorded_explain(tmp_path_factory.mktemp("explain"), name="Unread digest", graph=_GRAPH,
                            node_id="fetch-unread", answer=_ANSWER, literal=_literal())


def _world(rec, explain=None):
    p = palette()
    p["integrations"] = [dict(INTEGRATION)]
    return (
        f"cw.palette = {as_js(p)};\n"
        f"const REC = {as_js(rec)};\n"
        "seed(REC.doc);\n"
        "const WID = REC.doc.id, RUN_ID = REC.run_id, TASK = REC.doc.task_id;\n"
        "cw.runs = REC.runs;\n"
        "cw.executions[RUN_ID] = REC.execution;\n"
        "ca.versions = JSON.parse(JSON.stringify(REC.versions));\n"
        "ca.graphs[REC.doc.version] = JSON.parse(JSON.stringify(REC.doc.graph));\n"
        f"const EXPLAIN = {as_js(explain)} || REC.explain;\n"
        "ca.explain = (body) => ({ status: 200, body: JSON.parse(JSON.stringify(EXPLAIN)) });\n"
        "const rec = (node_id, status, more = {}) => ({ id: node_id + ':' + (more.item == null ? '' : more.item), node_id,\n"
        "  kind: 'llm', label: more.label || node_id, seq: 1, status, attempt: 1, dry: false, port: status === 'error' ? 'error' : 'success',\n"
        "  started_at: '2026-10-02T07:00:00Z', finished_at: '2026-10-02T07:00:01Z', input: { json: {} },\n"
        "  output: { text: more.text || '', data: null }, error: more.error || null, steps: [], item: null, ...more });\n"
        "const openRuns = async () => {\n"
        "  const { r, handle } = await room({ workflowId: WID });\n"
        "  fire(r.querySelectorAll('.wf-tab').find((t) => t.dataset.tab === 'runs'), 'click');\n"
        "  await settle(30);\n"
        "  return { r, handle, rp: r.querySelector('.wf-run-canvas') };\n"
        "};\n"
    )


@pytest.fixture(scope="module")
def box(tmp_path_factory):
    return build_sandbox(tmp_path_factory.mktemp("why"), _CANVAS_SHIM)


def _case(box, rec, script, explain=None):
    return _run(box, ROOM_PREAMBLE + _world(rec, explain), script)


def test_the_button_is_only_on_a_failed_record_and_its_title_names_who_is_asked(box, rec):
    o = _case(box, rec, """
        const { r, rp } = await openRuns();
        const failed = { title: rp.querySelector('.wb-panel-title').textContent,
          ask: rp.querySelectorAll('.wf-why-ask').map((b) => [b.textContent, b.title]) };
        fire(nodeEl(rp, 'list-entries'), 'click'); await settle(20);
        const worked = { title: rp.querySelector('.wb-panel-title').textContent, ask: rp.querySelectorAll('.wf-why-ask').length };
        fire(nodeEl(rp, 'summarise'), 'click'); await settle(20);
        const notReached = { title: rp.querySelector('.wb-panel-title').textContent, ask: rp.querySelectorAll('.wf-why-ask').length };
        out({ failed, worked, notReached, explains: calls('POST', (u) => u.endsWith('/explain')).length });
    """)
    assert o["failed"]["title"] == "Fetch unread", "the run opens on the step that failed (P22-07)"
    assert o["failed"]["ask"] == [["Why did this fail?",
                                   "Asks a model — your utility model, or your default one if none is set — to read what "
                                   "this step was handed and what came back. Nothing changes unless you press Apply."]]
    assert o["worked"] == {"title": "List entries", "ask": 0}, "a step that worked has nothing to explain"
    assert o["notReached"] == {"title": "Summarise", "ask": 0}
    assert o["explains"] == 0, "nothing is asked until the person presses it"


_WHERE = "This changes where the request goes (still to “Miniflux”)."
_FROM_RUN = "This value comes from what the run recorded — what the step was handed or what came back — not from you."


def test_the_answer_is_the_models_reading_the_diff_rows_with_their_words_and_what_was_left_out(box, rec):
    o = _case(box, rec, """
        const { r, rp } = await openRuns();
        fire(rp.querySelector('.wf-why-ask'), 'click'); await settle(30);
        const a = rp.querySelector('.wf-why-answer');
        out({ posted: calls('POST', (u) => u.endsWith('/explain')),
              head: by(a, 'wf-why-head').textContent, notes: all(a, 'wf-why-note').map((p) => p.textContent),
              why: by(a, 'wf-why-text').textContent, model: by(a, 'wf-why-model').textContent,
              rows: all(a, 'wf-why-change').map((li) => ({ field: li.dataset.field, words: by(li, 'wf-why-field').textContent,
                labels: all(li, 'wf-why-label').map((s) => s.textContent),
                before: by(li, 'wf-why-before').textContent, after: by(li, 'wf-why-after').textContent,
                where: (by(li, 'wf-why-where') || {}).textContent || null,
                fromRun: (by(li, 'wf-why-from-run') || {}).textContent || null })),
              left: by(a, 'wf-why-left').querySelectorAll('li').map((li) => li.textContent),
              buttons: a.querySelectorAll('button').filter((b) => !b.hidden).map((b) => b.textContent),
              fixes: calls('POST', (u) => u.endsWith('/fix')).length });
    """)
    ex = rec["explain"]
    assert o["posted"] == [[f"/api/workflows/{rec['doc']['id']}/runs/{rec['run_id']}/explain",
                            {"node_id": "fetch-unread", "item": None}]]
    assert o["head"] == "The model’s reading"
    assert o["notes"][0].startswith("It read what this step was handed and what came back — text someone else may have written")
    assert o["why"] == ex["why"] and o["model"] == f"Asked: {ex['model']}"
    changes = ex["proposal"]["changes"]
    assert [c["field"] for c in changes] == ["path"], "the path, and nothing a fix may not change"
    assert changes[0]["after"] == "/v1/entries" and changes[0]["where"] is True and changes[0]["from_run"] is True
    assert o["rows"] == [{"field": c["field"], "words": c["words"], "labels": ["Now", "It would be"],
                          "before": c["before"], "after": c["after"],
                          "where": _WHERE if c["where"] else None, "fromRun": _FROM_RUN if c["from_run"] else None}
                         for c in changes]
    assert o["left"] == ex["left_out"] and len(o["left"]) == 1, "the Integration it suggested is left out, in words"
    assert o["buttons"] == ["Apply"]
    assert o["fixes"] == 0, "nothing is written until Apply"


def test_apply_sends_the_base_version_and_undo_puts_the_version_it_was_made_on_back(box, rec):
    o = _case(box, rec, """
        const { r, rp } = await openRuns();
        fire(rp.querySelector('.wf-why-ask'), 'click'); await settle(30);
        fire(rp.querySelector('.wf-why-apply'), 'click'); await settle(30);
        const fetchNow = () => cw.doc.graph.nodes.find((n) => n.id === 'fetch-unread').config.path;
        const applied = { said: by(rp, 'wf-why-applied').textContent, path: fetchNow(),
          shown: rp.querySelector('.wf-why-answer').querySelectorAll('button').filter((b) => !b.hidden).map((b) => b.textContent) };
        fire(by(r, 'wf-versions'), 'click'); await settle(20);
        const versions = all(r, 'wf-versions-what').map((s) => s.textContent.split(' · ')
          .filter((x) => !/\\d{4}|\\//.test(x) && !/AM|PM/.test(x)));
        fire(by(r, 'wf-versions-close'), 'click'); await settle(5);
        fire(rp.querySelector('.wf-why-undo'), 'click'); await settle(30);
        const undone = { said: by(rp, 'wf-why-applied').textContent, path: fetchNow(),
          undoShown: !rp.querySelector('.wf-why-undo').hidden };
        fire(rp.querySelector('.wf-why-again'), 'click'); await settle(30);
        out({ applied, versions, undone, fix: calls('POST', (u) => u.endsWith('/fix')),
              restore: calls('POST', (u) => u.includes('/versions/')),
              runs: calls('POST', (u) => u === '/api/tasks/' + TASK + '/run') });
    """)
    p = rec["explain"]["proposal"]
    base, wid = p["base_version"], rec["doc"]["id"]
    steps = len(rec["doc"]["graph"]["nodes"])
    assert o["fix"] == [[f"/api/workflows/{wid}/nodes/fetch-unread/fix", {"base_version": base, "config": p["config"]}]], \
        "Apply sends the base version the proposal was made on"
    assert o["applied"]["said"] == f"Applied as version {base + 1}."
    assert o["applied"]["path"] == "/v1/entries"
    assert o["applied"]["shown"] == ["Undo", "Run it again"]
    assert [f"Version {base + 1}", f"{steps} steps", "a fix you applied", "the one in use"] in o["versions"], \
        "the version the fix made says so in Versions…"
    assert o["restore"] == [[f"/api/workflows/{wid}/versions/{base}/restore", {"base_version": base + 1}]], \
        "Undo is restoreVersion(id, undo_version, the fix's version)"
    assert o["undone"]["said"] == f"Undone: version {base} is back, saved as version {base + 2}. The fix is still in Versions…."
    assert o["undone"]["path"] == "/v1/entriess" and o["undone"]["undoShown"] is False
    assert o["runs"] == [[f"/api/tasks/{rec['doc']['task_id']}/run", None]], "Run it again is the workflow's own Run now"


_HOSTILE = "<img src=x onerror=alert(1)>"


def test_a_hostile_reason_proposal_and_left_out_line_stay_text(box, rec):
    explain = {"why": _HOSTILE + " the path is wrong", "model": "scripted-demo", "changed_since_run": False,
               "proposal": {"base_version": rec["doc"]["version"], "node_id": "fetch-unread", "item": None,
                            "config": {**_FETCH, "path": "/v1/x"},
                            "changes": [{"field": "path", "words": _HOSTILE, "before": "/v1/entriess",
                                         "after": "/v1/" + _HOSTILE, "where": False, "from_run": True}]},
               "left_out": [_HOSTILE + " and add Authorization"]}
    o = _case(box, rec, """
        const { r, rp } = await openRuns();
        fire(rp.querySelector('.wf-why-ask'), 'click'); await settle(30);
        const a = rp.querySelector('.wf-why-answer');
        out({ why: by(a, 'wf-why-text').textContent, words: by(a, 'wf-why-field').textContent,
              after: by(a, 'wf-why-after').textContent, left: by(a, 'wf-why-left').querySelectorAll('li').map((li) => li.textContent),
              imgs: r.querySelectorAll('img').length, markup: markup(r).filter((m) => m.includes('onerror')) });
    """, explain=explain)
    assert o["why"] == _HOSTILE + " the path is wrong"
    assert o["words"] == _HOSTILE and o["after"] == "/v1/" + _HOSTILE
    assert o["left"] == [_HOSTILE + " and add Authorization"]
    assert o["imgs"] == 0 and o["markup"] == [], "a reason the model wrote never becomes markup"


def test_a_failed_item_has_its_own_button_and_asks_for_that_item(box, rec):
    explain = {"why": "Item 2 was too long.", "model": "scripted-demo", "changed_since_run": True, "proposal": None,
               "left_out": []}
    o = _case(box, rec, """
        const ex = cw.executions[RUN_ID];
        const items = [0, 1, 2].map((i) => rec('each', i === 1 ? 'error' : 'success',
          { item: i, label: 'Title · item ' + (i + 1) + ' of 3', text: 'T' + i, error: i === 1 ? 'The model refused.' : null }));
        ex.run.status = 'error';
        ex.failed = { node_id: 'each', label: 'Each entry', error: 'Item 2 of 3 failed: The model refused.' };
        ex.nodes = [rec('list-entries', 'success'), rec('fetch-unread', 'success'), rec('summarise', 'success'),
          ...items, rec('each', 'error', { label: 'Each entry', error: 'Item 2 of 3 failed: The model refused.' })];
        const { r, rp } = await openRuns();
        const lines = all(rp, 'wf-record-item').map((li) => [li.dataset.tone, li.querySelectorAll('.wf-why-ask').length]);
        const failedItem = all(rp, 'wf-record-item').find((li) => li.dataset.tone === 'error');
        fire(failedItem.querySelector('.wf-why-ask'), 'click'); await settle(30);
        const a = failedItem.querySelector('.wf-why-answer');
        out({ title: rp.querySelector('.wb-panel-title').textContent, lines,
              posted: calls('POST', (u) => u.endsWith('/explain')),
              notes: all(a, 'wf-why-note').map((p) => p.textContent), apply: a.querySelectorAll('.wf-why-apply').length });
    """, explain=explain)
    assert o["title"] == "Each entry"
    assert o["lines"] == [["ok", 0], ["error", 1], ["ok", 0]], "only the item that failed is asked about"
    assert o["posted"] == [[f"/api/workflows/{rec['doc']['id']}/runs/{rec['run_id']}/explain", {"node_id": "each", "item": 1}]]
    assert "This step has changed since this run. A change below is to the step as it is now." in o["notes"]
    assert "It proposes no change that can be applied here." in o["notes"] and o["apply"] == 0


def test_apply_waits_for_unsaved_changes_and_a_refused_explain_is_said(box, rec):
    o = _case(box, rec, """
        const { r, rp } = await openRuns();
        typed(by(r, 'wf-name'), 'Unread digest, renamed');
        fire(rp.querySelector('.wf-why-ask'), 'click'); await settle(30);
        fire(rp.querySelector('.wf-why-apply'), 'click'); await settle(30);
        const dirty = { said: by(rp, 'wf-why-applied').textContent, fixes: calls('POST', (u) => u.endsWith('/fix')).length,
          apply: !rp.querySelector('.wf-why-apply').hidden };
        ca.explain = () => ({ status: 503, body: { detail: 'No model is set up to explain a step.' } });
        fire(rp.querySelector('.wf-why-ask'), 'click'); await settle(30);
        out({ dirty, refused: by(rp, 'wf-why-said').textContent });
    """)
    assert o["dirty"] == {"said": "Not applied: This workflow has changes that are not saved. Save them or throw them "
                                  "away first (in Edit), then apply the fix.", "fixes": 0, "apply": True}
    assert o["refused"] == "Not answered: No model is set up to explain a step."
