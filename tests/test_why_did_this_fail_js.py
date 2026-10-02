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

Driven end to end (`integrate-e`): the real room in node against wb-assist's
REAL server on a loopback port (`tests/helpers/workflow_live.py`). The failed
run is the real walker's, over a loopback Integration whose `/v1/entriess`
answers 404 with a hint; the explanation is the real route's, its model a
script behind `workflow_assist._complete` that proposes the right path and a
different Integration (which the real `fix_problem` leaves out); *Apply*,
Versions, *Undo* and *Run it again* are the real routes. Before the merge
these cases ran over a JavaScript stand-in for them (`workflow_ca_fake.py`,
deleted — `Law 20`).
"""

from __future__ import annotations

import asyncio
import json
import shutil
import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parent))

from test_tool_effect_surfaces_js import _run  # noqa: E402
from test_the_workbench_canvas_js import _SHIM as _CANVAS_SHIM  # noqa: E402
from helpers.workflow_live import LIVE_PREAMBLE, LiveServer, as_js, build_sandbox  # noqa: E402

pytestmark = pytest.mark.skipif(not shutil.which("node"), reason="node binary not on PATH")


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
# What the scripted model answers the real route (`explain_step`'s shape):
# the right path, and a different Integration a fix may not choose.
_ANSWER = {"why": "The server says /v1/entriess does not exist and suggests /v1/entries. The path is wrong.",
           "change": {"path": "/v1/entries", "integration": "admin-api"}, "say": "Fix the path."}


def _make_and_fail(w, graph):
    """Through the real routes: make the workflow, save `graph`, switch it on,
    run it once with the real walker. `(workflow id, task id, run id)`."""
    from core.database import TaskRun
    from tests.helpers.assist_harness import PERSON, rows
    from tests.helpers.walker_harness import client_for

    async def go():
        async with client_for(w.app) as client:
            async def call(method, path, **kw):
                res = await client.request(method, path, headers=PERSON, **kw)
                assert res.status_code == 200, (path, res.status_code, res.text)
                return res.json()
            made = await call("POST", "/api/workflows", json={"name": "Unread digest"})
            wid, task_id = made["workflow"]["id"], made["workflow"]["task_id"]
            await call("PUT", f"/api/workflows/{wid}", json={"graph": graph, "base_version": 1})
            await call("POST", f"/api/workflows/{wid}/switch", json={"on": True})
            await w.s._execute_task(task_id)
            [run] = rows(w.factory, TaskRun, task_id=task_id)
            assert run.status == "error", (run.status, run.error)
            return wid, task_id, run.id

    return asyncio.run(go())


@pytest.fixture(scope="module")
def box(tmp_path_factory):
    return build_sandbox(tmp_path_factory.mktemp("why"), _CANVAS_SHIM)


@pytest.fixture()
def live(monkeypatch, tmp_path):
    from tests.helpers.assist_harness import Feeds, build_world, miniflux, resolve_to_loopback, script_model

    feeds = Feeds()
    try:
        resolve_to_loopback(monkeypatch)
        w = build_world(monkeypatch, tmp_path, integrations=[miniflux(feeds.base_url)])
        w.feeds = feeds
        w.script = lambda *answers: script_model(monkeypatch, *answers)
        w.wid, w.task_id, w.run_id = _make_and_fail(w, _GRAPH)
        w.server = LiveServer(w.app)
        try:
            yield w
        finally:
            w.server.close()
    finally:
        feeds.close()


def _case(box, live, script, wid=None, run_id=None):
    world = (f"const WID = {as_js(wid or live.wid)}, RUN_ID = {as_js(run_id or live.run_id)}, "
             f"TASK = {as_js(live.task_id)};\n"
             "const openRuns = async () => {\n"
             "  const { r, handle } = await room({ workflowId: WID });\n"
             "  fire(r.querySelectorAll('.wf-tab').find((t) => t.dataset.tab === 'runs'), 'click');\n"
             "  await quiet();\n"
             "  return { r, handle, rp: r.querySelector('.wf-run-canvas') };\n"
             "};\n")
    return _run(box, LIVE_PREAMBLE(live.server.base) + world, script)


def test_the_button_is_only_on_a_failed_record_and_its_title_names_who_is_asked(box, live):
    o = _case(box, live, """
        const { r, rp } = await openRuns();
        const failed = { title: rp.querySelector('.wb-panel-title').textContent,
          ask: rp.querySelectorAll('.wf-why-ask').map((b) => [b.textContent, b.title]) };
        fire(nodeEl(rp, 'list-entries'), 'click'); await quiet();
        const worked = { title: rp.querySelector('.wb-panel-title').textContent, ask: rp.querySelectorAll('.wf-why-ask').length };
        fire(nodeEl(rp, 'summarise'), 'click'); await quiet();
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


def test_the_answer_is_the_models_reading_the_diff_rows_with_their_words_and_what_was_left_out(box, live):
    live.script(_ANSWER)
    o = _case(box, live, """
        const { r, rp } = await openRuns();
        fire(rp.querySelector('.wf-why-ask'), 'click'); await quiet();
        const a = rp.querySelector('.wf-why-answer');
        out({ posted: calls('POST', (u) => u.endsWith('/explain')),
              ex: replyTo('POST', (u) => u.endsWith('/explain')).reply,
              head: by(a, 'wf-why-head').textContent, notes: all(a, 'wf-why-note').map((p) => p.textContent),
              why: by(a, 'wf-why-text').textContent, model: (by(a, 'wf-why-model') || {}).textContent || null,
              rows: all(a, 'wf-why-change').map((li) => ({ field: li.dataset.field, words: by(li, 'wf-why-field').textContent,
                labels: all(li, 'wf-why-label').map((s) => s.textContent),
                before: by(li, 'wf-why-before').textContent, after: by(li, 'wf-why-after').textContent,
                where: (by(li, 'wf-why-where') || {}).textContent || null,
                fromRun: (by(li, 'wf-why-from-run') || {}).textContent || null })),
              left: by(a, 'wf-why-left').querySelectorAll('li').map((li) => li.textContent),
              buttons: a.querySelectorAll('button').filter((b) => !b.hidden).map((b) => b.textContent),
              fixes: calls('POST', (u) => u.endsWith('/fix')).length });
    """)
    ex = o["ex"]
    assert o["posted"] == [[f"/api/workflows/{live.wid}/runs/{live.run_id}/explain",
                            {"node_id": "fetch-unread", "item": None}]]
    assert o["head"] == "The model’s reading"
    assert o["notes"][0].startswith("It read what this step was handed and what came back — text someone else may have written")
    assert o["why"] == ex["why"] and ex["why"].startswith(_ANSWER["why"])
    assert o["model"] == (f"Asked: {ex['model']}" if ex["model"] else None)
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


def test_apply_sends_the_base_version_and_undo_puts_the_version_it_was_made_on_back(box, live):
    live.script(_ANSWER)
    o = _case(box, live, """
        const { r, rp } = await openRuns();
        fire(rp.querySelector('.wf-why-ask'), 'click'); await quiet();
        const ex = replyTo('POST', (u) => u.endsWith('/explain')).reply;
        fire(rp.querySelector('.wf-why-apply'), 'click'); await quiet();
        const fetchNow = async () => (await ask('/api/workflows/' + WID)).workflow.graph.nodes.find((n) => n.id === 'fetch-unread').config.path;
        const applied = { said: by(rp, 'wf-why-applied').textContent, path: await fetchNow(),
          shown: rp.querySelector('.wf-why-answer').querySelectorAll('button').filter((b) => !b.hidden).map((b) => b.textContent) };
        fire(by(r, 'wf-versions'), 'click'); await quiet();
        const versions = all(r, 'wf-versions-what').map((s) => s.textContent.split(' · ')
          .filter((x) => !/\\d{4}|\\//.test(x) && !/AM|PM/.test(x)));
        fire(by(r, 'wf-versions-close'), 'click'); await quiet();
        fire(rp.querySelector('.wf-why-undo'), 'click'); await quiet();
        const undone = { said: by(rp, 'wf-why-applied').textContent, path: await fetchNow(),
          undoShown: !rp.querySelector('.wf-why-undo').hidden };
        fire(rp.querySelector('.wf-why-again'), 'click'); await quiet();
        const sources = (await ask('/api/workflows/' + WID + '/versions')).versions.map((v) => [v.version, v.source]);
        out({ ex, applied, versions, undone, sources, fix: calls('POST', (u) => u.endsWith('/fix')),
              restore: calls('POST', (u) => u.includes('/versions/')),
              runs: calls('POST', (u) => u === '/api/tasks/' + TASK + '/run') });
    """)
    p = o["ex"]["proposal"]
    base = p["base_version"]
    steps = len(_GRAPH["nodes"])
    assert o["fix"] == [[f"/api/workflows/{live.wid}/nodes/fetch-unread/fix", {"base_version": base, "config": p["config"]}]], \
        "Apply sends the base version the proposal was made on"
    assert o["applied"]["said"] == f"Applied as version {base + 1}."
    assert o["applied"]["path"] == "/v1/entries"
    assert o["applied"]["shown"] == ["Undo", "Run it again"]
    assert [f"Version {base + 1}", f"{steps} steps", "a fix you applied", "the one in use"] in o["versions"], \
        "the version the fix made says so in Versions…"
    assert o["restore"] == [[f"/api/workflows/{live.wid}/versions/{base}/restore", {"base_version": base + 1}]], \
        "Undo is restoreVersion(id, undo_version, the fix's version)"
    assert o["undone"]["said"] == f"Undone: version {base} is back, saved as version {base + 2}. The fix is still in Versions…."
    assert o["undone"]["path"] == "/v1/entriess" and o["undone"]["undoShown"] is False
    assert sorted(o["sources"])[-2:] == [[base + 1, "fixed"], [base + 2, "restored"]], "as the server kept them"
    assert o["runs"] == [[f"/api/tasks/{live.task_id}/run", None]], "Run it again is the workflow's own Run now"


_HOSTILE = "<img src=x onerror=alert(1)>"


def test_a_hostile_reason_and_proposal_stay_text(box, live):
    """What the model writes reaches the page in two places — its reading and
    the value it proposes — and both are text. (The field's words and the
    left-out lines are the server's own sentences.)"""
    live.script({"why": _HOSTILE + " the path is wrong", "change": {"path": "/v1/" + _HOSTILE}, "say": ""})
    o = _case(box, live, """
        const { r, rp } = await openRuns();
        fire(rp.querySelector('.wf-why-ask'), 'click'); await quiet();
        const a = rp.querySelector('.wf-why-answer');
        out({ ex: replyTo('POST', (u) => u.endsWith('/explain')).reply,
              why: by(a, 'wf-why-text').textContent, after: (by(a, 'wf-why-after') || {}).textContent || null,
              imgs: r.querySelectorAll('img').length, markup: markup(r).filter((m) => m.includes('onerror')) });
    """)
    assert o["why"] == o["ex"]["why"] and o["why"].startswith(_HOSTILE)
    assert o["after"] == "/v1/" + _HOSTILE, o["ex"]
    assert o["imgs"] == 0 and o["markup"] == [], "a reason the model wrote never becomes markup"


def test_a_failed_item_has_its_own_button_and_asks_for_that_item(box, live, monkeypatch):
    """A For-each whose second item fails (the real walker; the model's stand-in
    refuses item 2), and the step changed after the run — the answer says so."""
    from tests.helpers.assist_harness import PERSON
    from tests.helpers.walker_harness import client_for

    graph = json.loads(json.dumps(_GRAPH))
    graph["nodes"][1]["config"]["path"] = "/v1/entries"
    graph["nodes"][2]["config"]["prompt"] = "Summarise {{ steps.fetch-unread.data.entries }}"
    graph["nodes"][3]["config"]["list"] = "{{ steps.fetch-unread.data.entries }}"
    real = live.s._execute_llm_task
    seen = {"title": 0}

    async def llm(task, db, run_id=None):
        if task.name and "Title" in task.name:
            seen["title"] += 1
            if seen["title"] == 2:
                raise RuntimeError("The model refused.")
        return await real(task, db, run_id)
    monkeypatch.setattr(live.s, "_execute_llm_task", llm)
    wid, _task, run_id = _make_and_fail(live, graph)

    async def change_the_step():
        async with client_for(live.app) as client:
            doc = (await client.get(f"/api/workflows/{wid}", headers=PERSON)).json()["workflow"]
            g = doc["graph"]
            each = next(n for n in g["nodes"] if n["id"] == "each")
            each["config"]["step"]["config"]["prompt"] = "Name it in five words."
            res = await client.put(f"/api/workflows/{wid}", headers=PERSON,
                                   json={"graph": g, "base_version": doc["version"]})
            assert res.status_code == 200, res.text
    asyncio.run(change_the_step())
    live.script({"why": "Item 2 was too long.", "change": None, "say": ""})
    o = _case(box, live, """
        const { r, rp } = await openRuns();
        const lines = all(rp, 'wf-record-item').map((li) => [li.dataset.tone, li.querySelectorAll('.wf-why-ask').length]);
        const failedItem = all(rp, 'wf-record-item').find((li) => li.dataset.tone === 'error');
        fire(failedItem.querySelector('.wf-why-ask'), 'click'); await quiet();
        const a = failedItem.querySelector('.wf-why-answer');
        out({ title: rp.querySelector('.wb-panel-title').textContent, lines,
              posted: calls('POST', (u) => u.endsWith('/explain')),
              ex: replyTo('POST', (u) => u.endsWith('/explain')).reply,
              notes: all(a, 'wf-why-note').map((p) => p.textContent), apply: a.querySelectorAll('.wf-why-apply').length });
    """, wid=wid, run_id=run_id)
    assert o["title"] == "Each entry"
    assert o["lines"] == [["ok", 0], ["error", 1]], "only the item that failed is asked about"
    assert o["posted"] == [[f"/api/workflows/{wid}/runs/{run_id}/explain", {"node_id": "each", "item": 1}]]
    assert o["ex"]["changed_since_run"] is True
    assert "This step has changed since this run. A change below is to the step as it is now." in o["notes"]
    assert "It proposes no change that can be applied here." in o["notes"] and o["apply"] == 0


def test_apply_waits_for_unsaved_changes_and_a_refused_explain_is_said(box, live):
    from src import workflow_assist as wa

    live.script(_ANSWER, wa.NoModelSetUp())
    o = _case(box, live, """
        const { r, rp } = await openRuns();
        typed(by(r, 'wf-name'), 'Unread digest, renamed');
        fire(rp.querySelector('.wf-why-ask'), 'click'); await quiet();
        fire(rp.querySelector('.wf-why-apply'), 'click'); await quiet();
        const dirty = { said: by(rp, 'wf-why-applied').textContent, fixes: calls('POST', (u) => u.endsWith('/fix')).length,
          apply: !rp.querySelector('.wf-why-apply').hidden };
        fire(rp.querySelector('.wf-why-ask'), 'click'); await quiet();
        const second = replyTo('POST', (u) => u.endsWith('/explain'));
        out({ dirty, refused: by(rp, 'wf-why-said').textContent, status: second.status, detail: second.reply.detail });
    """)
    assert o["dirty"] == {"said": "Not applied: This workflow has changes that are not saved. Save them or throw them "
                                  "away first (in Edit), then apply the fix.", "fixes": 0, "apply": True}
    assert o["status"] == 503 and o["detail"] == wa.NO_MODEL_TO_EXPLAIN
    assert o["refused"] == f"Not answered: {wa.NO_MODEL_TO_EXPLAIN}"
