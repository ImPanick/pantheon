# SPDX-License-Identifier: AGPL-3.0-or-later
r"""`P22-20` (wb-canvas-e) — *Why did this fail?* on a failed step, its proposed change, *Apply* and *Undo*.

The browser half of `SLICE-EF-DESIGN.md` § 2 P22-20 (package B, § 3): a failed
step's record (*What went wrong*) gains **Why did this fail?**, whose title
names who is asked; it posts C-A's explain route `{node_id, item}` and shows the
model's reading AS TEXT, labelled as coming from what the step was handed; each
proposed change as a row — what it is now, what it would be — saying in words
when it changes where the request goes (`where`) and when the new value came
out of the run (`from_run`); what was left out (`left_out`); then **Apply**
(C-A's fix route with the proposal's base version) → "Applied as version 7." →
**Undo** (the existing restore door with `undo_version`) → **Run it again**.

Driven: the real room, canvas, panels, source and `workflowApi.js` over the
C-A fake server (`tests/helpers/workflow_ca_fake.py`).
"""

from __future__ import annotations

import shutil
import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parent))

from test_tool_effect_surfaces_js import _run  # noqa: E402
from test_the_workbench_canvas_js import _SHIM as _CANVAS_SHIM  # noqa: E402
from helpers.workflow_ca_fake import ROOM_PREAMBLE, as_js, build_sandbox, palette  # noqa: E402

pytestmark = pytest.mark.skipif(not shutil.which("node"), reason="node binary not on PATH")


def _node(id_, kind, label, config):
    return {"id": id_, "kind": kind, "label": label, "config": config, "position": None, "pinned": None}


_FETCH = {"integration": "int1", "method": "GET", "path": "/v1/entriess", "query": [{"name": "status", "value": "unread"}],
          "body": []}
_GRAPH = {"v": 1, "start": {"position": None}, "nodes": [
    _node("list-feeds", "http", "List feeds", {"integration": "int1", "method": "GET", "path": "/v1/feeds", "query": [], "body": []}),
    _node("fetch-unread", "http", "Fetch unread", _FETCH),
    _node("summarise", "llm", "Summarise", {"prompt": "Summarise {{ steps.fetch-unread.data.json.entries }}"}),
    _node("each", "foreach", "Each entry", {"list": "{{ steps.fetch-unread.data.json.entries }}", "on_error": "continue",
                                             "step": {"kind": "llm", "label": "Title", "config": {"prompt": "x"}}})],
    "edges": [{"from": "start", "port": "success", "to": "list-feeds"},
              {"from": "list-feeds", "port": "success", "to": "fetch-unread"},
              {"from": "fetch-unread", "port": "success", "to": "summarise"},
              {"from": "summarise", "port": "success", "to": "each"}]}
_DOC = {"id": "wf1", "name": "Unread digest", "task_id": "t1", "trigger_status": "active", "version": 6,
        "trigger_task": {"id": "t1", "status": "active"}, "graph": _GRAPH}
_ERROR = "HTTP 404 from Miniflux: Not Found. Did you mean /v1/entries?"


def _explain(why="The path /v1/entriess does not exist on Miniflux: it answered 404 and suggested /v1/entries.",
             changes=None, left_out=None):
    changes = changes if changes is not None else [
        {"field": "path", "words": "Path", "before": "/v1/entriess", "after": "/v1/entries", "where": True, "from_run": True}]
    left_out = left_out if left_out is not None else [
        "It also suggested sending to a different Integration. That is yours to decide, in the step’s panel."]
    return {"why": why, "model": "scripted-demo", "changed_since_run": False,
            "proposal": {"base_version": 6, "node_id": "fetch-unread", "item": None,
                         "config": {**_FETCH, "path": "/v1/entries"}, "changes": changes},
            "left_out": left_out}


def _world(explain=None):
    return (
        f"cw.palette = {as_js(palette())};\n"
        f"seed({as_js(_DOC)});\n"
        f"const ERROR = {as_js(_ERROR)};\n"
        "const rec = (node_id, status, more = {}) => ({ id: node_id + ':' + (more.item == null ? '' : more.item), node_id,\n"
        "  kind: 'http', label: more.label || node_id, seq: 1, status, attempt: 1, dry: false, port: status === 'error' ? 'error' : 'success',\n"
        "  started_at: '2026-10-02T07:00:00Z', finished_at: '2026-10-02T07:00:01Z', input: { json: {} },\n"
        "  output: { text: more.text || '', data: null }, error: more.error || null, steps: [], item: null, ...more });\n"
        "cw.runs = [{ id: 'r1', task_id: 't1', status: 'error', started_at: '2026-10-02T07:00:00Z', steps: [] }];\n"
        "cw.executions.r1 = { run: { id: 'r1', status: 'error' }, graph: JSON.parse(JSON.stringify(cw.doc.graph)),\n"
        "  version_kept: true, cleared: false,\n"
        "  failed: { node_id: 'fetch-unread', label: 'Fetch unread', error: ERROR },\n"
        "  nodes: [rec('list-feeds', 'success', { label: 'List feeds', text: '3 feeds' }),\n"
        "          rec('fetch-unread', 'error', { label: 'Fetch unread', error: ERROR })] };\n"
        "ca.versions = [{ version: 6, name: 'Unread digest', saved_at: '2026-10-02T06:00:00Z', source: 'user', step_count: 4, current: true },\n"
        "  { version: 5, name: 'Unread digest', saved_at: '2026-10-01T06:00:00Z', source: 'user', step_count: 3, current: false }];\n"
        "ca.graphs[6] = JSON.parse(JSON.stringify(cw.doc.graph));\n"
        f"const EXPLAIN = {as_js(explain or _explain())};\n"
        "ca.explain = (body) => ({ status: 200, body: JSON.parse(JSON.stringify(EXPLAIN)) });\n"
        "const openRuns = async () => {\n"
        "  const { r, handle } = await room({ workflowId: 'wf1' });\n"
        "  fire(r.querySelectorAll('.wf-tab').find((t) => t.dataset.tab === 'runs'), 'click');\n"
        "  await settle(30);\n"
        "  return { r, handle, rp: r.querySelector('.wf-run-canvas') };\n"
        "};\n"
    )


@pytest.fixture(scope="module")
def box(tmp_path_factory):
    return build_sandbox(tmp_path_factory.mktemp("why"), _CANVAS_SHIM)


def _case(box, script, **world):
    return _run(box, ROOM_PREAMBLE + _world(**world), script)


def test_the_button_is_only_on_a_failed_record_and_its_title_names_who_is_asked(box):
    o = _case(box, """
        const { r, rp } = await openRuns();
        const failed = { title: rp.querySelector('.wb-panel-title').textContent,
          ask: rp.querySelectorAll('.wf-why-ask').map((b) => [b.textContent, b.title]) };
        fire(nodeEl(rp, 'list-feeds'), 'click'); await settle(20);
        const worked = { title: rp.querySelector('.wb-panel-title').textContent, ask: rp.querySelectorAll('.wf-why-ask').length };
        fire(nodeEl(rp, 'summarise'), 'click'); await settle(20);
        const notReached = { title: rp.querySelector('.wb-panel-title').textContent, ask: rp.querySelectorAll('.wf-why-ask').length };
        out({ failed, worked, notReached, explains: calls('POST', (u) => u.endsWith('/explain')).length });
    """)
    assert o["failed"]["title"] == "Fetch unread"
    assert o["failed"]["ask"] == [["Why did this fail?",
                                   "Asks a model — your utility model, or your default one if none is set — to read what "
                                   "this step was handed and what came back. Nothing changes unless you press Apply."]]
    assert o["worked"] == {"title": "List feeds", "ask": 0}, "a step that worked has nothing to explain"
    assert o["notReached"] == {"title": "Summarise", "ask": 0}
    assert o["explains"] == 0, "nothing is asked until the person presses it"


def test_the_answer_is_the_models_reading_the_diff_rows_with_their_words_and_what_was_left_out(box):
    o = _case(box, """
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
    assert o["posted"] == [["/api/workflows/wf1/runs/r1/explain", {"node_id": "fetch-unread", "item": None}]]
    assert o["head"] == "The model’s reading"
    assert o["notes"][0].startswith("It read what this step was handed and what came back — text someone else may have written")
    assert o["why"] == "The path /v1/entriess does not exist on Miniflux: it answered 404 and suggested /v1/entries."
    assert o["model"] == "Asked: scripted-demo"
    assert o["rows"] == [{"field": "path", "words": "Path", "labels": ["Now", "It would be"],
                          "before": "/v1/entriess", "after": "/v1/entries",
                          "where": "This changes where the request goes (still to “Miniflux”).",
                          "fromRun": "This value comes from what the run recorded — what the step was handed or what came "
                                     "back — not from you."}]
    assert o["left"] == ["It also suggested sending to a different Integration. That is yours to decide, in the step’s panel."]
    assert o["buttons"] == ["Apply"]
    assert o["fixes"] == 0, "nothing is written until Apply"


def test_apply_sends_the_base_version_and_undo_puts_the_version_it_was_made_on_back(box):
    o = _case(box, """
        const { r, rp } = await openRuns();
        fire(rp.querySelector('.wf-why-ask'), 'click'); await settle(30);
        fire(rp.querySelector('.wf-why-apply'), 'click'); await settle(30);
        const applied = { said: by(rp, 'wf-why-applied').textContent, path: cw.doc.graph.nodes[1].config.path,
          shown: rp.querySelector('.wf-why-answer').querySelectorAll('button').filter((b) => !b.hidden).map((b) => b.textContent) };
        fire(by(r, 'wf-versions'), 'click'); await settle(20);
        const versions = all(r, 'wf-versions-what').map((s) => s.textContent.split(' · ').filter((x) => !/\\d{4}|\\//.test(x) && !/AM|PM/.test(x)));
        fire(by(r, 'wf-versions-close'), 'click'); await settle(5);
        fire(rp.querySelector('.wf-why-undo'), 'click'); await settle(30);
        const undone = { said: by(rp, 'wf-why-applied').textContent, path: cw.doc.graph.nodes[1].config.path,
          undoShown: !rp.querySelector('.wf-why-undo').hidden };
        fire(rp.querySelector('.wf-why-again'), 'click'); await settle(30);
        out({ applied, versions, undone, fix: calls('POST', (u) => u.endsWith('/fix')),
              restore: calls('POST', (u) => u.includes('/versions/')),
              runs: calls('POST', (u) => u === '/api/tasks/t1/run') });
    """)
    assert o["fix"] == [["/api/workflows/wf1/nodes/fetch-unread/fix",
                         {"base_version": 6, "config": {**_FETCH, "path": "/v1/entries"}}]], "Apply sends the base version"
    assert o["applied"]["said"] == "Applied as version 7."
    assert o["applied"]["path"] == "/v1/entries"
    assert o["applied"]["shown"] == ["Undo", "Run it again"]
    assert ["Version 7", "4 steps", "a fix you applied", "the one in use"] in o["versions"], \
        "the version the fix made says so in Versions…"
    assert o["restore"] == [["/api/workflows/wf1/versions/6/restore", {"base_version": 7}]], \
        "Undo is restoreVersion(id, undo_version, the fix's version)"
    assert o["undone"]["said"] == "Undone: version 6 is back, saved as version 8. The fix is still in Versions…."
    assert o["undone"]["path"] == "/v1/entriess" and o["undone"]["undoShown"] is False
    assert o["runs"] == [["/api/tasks/t1/run", None]], "Run it again is the workflow's own Run now"


_HOSTILE = "<img src=x onerror=alert(1)>"


def test_a_hostile_reason_proposal_and_left_out_line_stay_text(box):
    o = _case(box, """
        const { r, rp } = await openRuns();
        fire(rp.querySelector('.wf-why-ask'), 'click'); await settle(30);
        const a = rp.querySelector('.wf-why-answer');
        out({ why: by(a, 'wf-why-text').textContent, words: by(a, 'wf-why-field').textContent,
              after: by(a, 'wf-why-after').textContent, left: by(a, 'wf-why-left').querySelectorAll('li').map((li) => li.textContent),
              imgs: r.querySelectorAll('img').length, markup: markup(r).filter((m) => m.includes('onerror')) });
    """, explain=_explain(why=_HOSTILE + " the path is wrong",
                          changes=[{"field": "path", "words": _HOSTILE, "before": "/v1/entriess", "after": "/v1/" + _HOSTILE,
                                    "where": False, "from_run": True}],
                          left_out=[_HOSTILE + " and add Authorization"]))
    assert o["why"] == _HOSTILE + " the path is wrong"
    assert o["words"] == _HOSTILE and o["after"] == "/v1/" + _HOSTILE
    assert o["left"] == [_HOSTILE + " and add Authorization"]
    assert o["imgs"] == 0 and o["markup"] == [], "a reason the model wrote never becomes markup"


def test_a_failed_item_has_its_own_button_and_asks_for_that_item(box):
    o = _case(box, """
        const items = [0, 1, 2].map((i) => rec('each', i === 1 ? 'error' : 'success',
          { item: i, label: 'Title · item ' + (i + 1) + ' of 3', text: 'T' + i, error: i === 1 ? 'The model refused.' : null }));
        cw.executions.r1.failed = { node_id: 'each', label: 'Each entry', error: 'Item 2 of 3 failed: The model refused.' };
        cw.executions.r1.nodes = [rec('list-feeds', 'success'), rec('fetch-unread', 'success'), rec('summarise', 'success'),
          ...items, rec('each', 'error', { label: 'Each entry', error: 'Item 2 of 3 failed: The model refused.' })];
        ca.explain = (body) => ({ status: 200, body: { why: 'Item 2 was too long.', model: 'scripted-demo',
          changed_since_run: true, proposal: null, left_out: [] } });
        const { r, rp } = await openRuns();
        const lines = all(rp, 'wf-record-item').map((li) => [li.dataset.tone, li.querySelectorAll('.wf-why-ask').length]);
        const failedItem = all(rp, 'wf-record-item').find((li) => li.dataset.tone === 'error');
        fire(failedItem.querySelector('.wf-why-ask'), 'click'); await settle(30);
        const a = failedItem.querySelector('.wf-why-answer');
        out({ title: rp.querySelector('.wb-panel-title').textContent, lines,
              posted: calls('POST', (u) => u.endsWith('/explain')),
              notes: all(a, 'wf-why-note').map((p) => p.textContent), apply: a.querySelectorAll('.wf-why-apply').length });
    """)
    assert o["title"] == "Each entry"
    assert o["lines"] == [["ok", 0], ["error", 1], ["ok", 0]], "only the item that failed is asked about"
    assert o["posted"] == [["/api/workflows/wf1/runs/r1/explain", {"node_id": "each", "item": 1}]]
    assert "This step has changed since this run. A change below is to the step as it is now." in o["notes"]
    assert "It proposes no change that can be applied here." in o["notes"] and o["apply"] == 0


def test_apply_waits_for_unsaved_changes_and_a_refused_explain_is_said(box):
    o = _case(box, """
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
