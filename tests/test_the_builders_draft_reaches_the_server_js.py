# SPDX-License-Identifier: AGPL-3.0-or-later
"""The builder's draft calls in `workflowApi.js`, driven against the REAL
server (`tests/helpers/workflow_live.py`): each sends its route's method, URL
and body, and the reply or refusal it hands back is the real route's.

  * `listDraftFields(id, nodeId, graph)` — `B1850`, `POST …/fields`: a step
    only the draft has is offered what runs before it on the draft's arrows.

`Law 13`: a route ships with its caller; this file is the caller reaching it.
"""

from __future__ import annotations

import shutil
import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parent))

from test_tool_effect_surfaces_js import _run  # noqa: E402
from test_the_workbench_canvas_js import _SHIM as _CANVAS_SHIM  # noqa: E402
from helpers.workflow_live import LIVE_PREAMBLE, LiveServer, as_js, build_sandbox  # noqa: E402

pytestmark = pytest.mark.skipif(not shutil.which("node"), reason="node binary not on PATH")

_API = ("const { createWorkflowApi, WorkflowRefusal } = await import('./workflowApi.js');\n"
        "const api = createWorkflowApi({ fetch: net });\n"
        "const refusal = async (p) => { try { await p; return null; } catch (e) {\n"
        "  return { name: e.name, status: e.status, sentence: e.sentence, reason: e.reason,\n"
        "           nodeIds: e.nodeIds, field: e.field }; } };\n")


@pytest.fixture(scope="module")
def box(tmp_path_factory):
    return build_sandbox(tmp_path_factory.mktemp("wfdraft"), _CANVAS_SHIM)


@pytest.fixture()
def served(monkeypatch, tmp_path):
    from tests.helpers.walker_harness import (
        app_for, arrow, make_db, node, recording_scheduler, seed_workflow,
    )
    factory = make_db(monkeypatch, tmp_path / "draft-js.db")
    seed_workflow(factory, [node("n1", "Fetch issue", "set", fields=[{"name": "title", "value": "x"}]),
                            node("n2", "Summarise")], [arrow("n1", "n2")])
    server = LiveServer(app_for(factory, recording_scheduler(), monkeypatch))
    try:
        yield server
    finally:
        server.close()


def _case(box, server, script, **consts):
    head = "".join(f"const {k} = {as_js(v)};\n" for k, v in consts.items())
    return _run(box, LIVE_PREAMBLE(server.base) + _API + head, script)


DRAFT = {"v": 1, "nodes": [
    {"id": "n1", "kind": "set", "label": "Fetch issue",
     "config": {"fields": [{"name": "title", "value": "x"}]}},
    {"id": "n2", "kind": "llm", "label": "Summarise", "config": {"prompt": "Do Summarise."}},
    {"id": "n3", "kind": "llm", "label": "Not written yet", "config": {"prompt": ""}}],
    "edges": [{"from": "n1", "port": "success", "to": "n2"},
              {"from": "n2", "port": "success", "to": "n3"}]}


def test_list_draft_fields_sends_the_draft_and_reads_the_real_answer(box, served):
    o = _case(box, served, """
        const reply = await api.listDraftFields('w-wf', 'n3', DRAFT);
        const missing = await refusal(api.listDraftFields('w-wf', 'zz', DRAFT));
        out({ wire: calls('POST'), sources: reply.sources.map((s) => [s.node_id, s.origin,
              s.fields.map((f) => f.ref)]), missing });
    """, DRAFT=DRAFT)
    assert o["wire"][0] == ["/api/workflows/w-wf/fields", {"node_id": "n3", "graph": DRAFT}]
    assert o["sources"] == [["n1", "declared", ["{{ steps.n1.data.title }}"]]]
    assert o["missing"] == {"name": "WorkflowRefusal", "status": 404,
                            "sentence": "No such step in this draft.", "reason": None,
                            "nodeIds": [], "field": None}
