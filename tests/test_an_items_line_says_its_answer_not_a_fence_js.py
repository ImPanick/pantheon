# SPDX-License-Identifier: AGPL-3.0-or-later
r"""`B1109` — a For-each's item lines say a word of each item's answer, not "```json".

Measured by `integrate-d` (`dark-1400-12-runs-failed-item.png`): "Item 1 of 5:
Success — ```json" for every item that answered in shape. The AI step's own
instruction asks for the answer "in a ```json block" (`answer_instruction`),
`parse_answer` reads through the fence into `data`, and the Runs view's item
line showed the first line of the raw `text`. An item's line now says its
answer (`workflowPanels.js:itemAnswer`): an error's first line; an answer in
shape as its fields ("summary: …"); else the first line of its text that is
words — never a fence, never a `<think>` tag.

Driven end to end (`Law 20`): the real walker runs a For-each over an AI step
whose answers (the model's words, recorded at the executor) come fenced, one
out of shape; the real run route serves its records; the real
`workflowPanels.js` draws them in node — the record and item lines the Runs
view draws.
"""
from __future__ import annotations

import json
import shutil
import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parent))

from test_tool_effect_surfaces_js import _run  # noqa: E402
from test_the_workbench_canvas_js import _SHIM as _CANVAS_SHIM  # noqa: E402
from helpers.workflow_live import build_sandbox  # noqa: E402
from tests.helpers.walker_harness import (  # noqa: E402
    app_for, arrow, client_for, make_db, node, recording_scheduler, runs_of, seed_workflow,
)

pytestmark = pytest.mark.skipif(not shutil.which("node"), reason="node binary not on PATH")

FIELDS = [{"name": "summary", "type": "text"}, {"name": "urgent", "type": "yes/no"}]
MAILS = ["The build server is down", "Lunch on Friday", "Invoice 1043", "Release notes", "Your statement"]


def _answer(i):
    if i == 3:
        return "I could not read this one."               # out of shape: the item fails
    body = json.dumps({"summary": MAILS[i - 1], "urgent": i == 1})
    if i == 5:                                            # a reasoning model's block first
        return f"<think>\nThe mail is a statement.\n</think>\n```json\n{body}\n```"
    return f"```json\n{body}\n```"


@pytest.fixture(scope="module")
def box(tmp_path_factory):
    return build_sandbox(tmp_path_factory.mktemp("items"), _CANVAS_SHIM)


@pytest.fixture()
def served(monkeypatch, tmp_path):
    """The run, as `GET /api/workflows/{id}/runs/{run_id}` serves it."""
    import asyncio

    factory = make_db(monkeypatch, tmp_path / "items.db")
    each = node("each", "Each mail", "foreach", list="{{ steps.fetch.data.mails }}", on_error="continue",
                step={"kind": "llm", "label": "Summarise",
                      "config": {"prompt": "Summarise {{ item }}.", "answer_fields": FIELDS}})
    seed_workflow(factory, [node("fetch", "Fetch unread", "set", fields=[{"name": "mails", "value": MAILS}]),
                            each], [arrow("fetch", "each")])

    async def said(i):
        async def answer(task, run_id):
            return _answer(i)
        return answer

    outcomes = {f"Morning digest · Summarise · item {i} of 5": asyncio.run(said(i)) for i in range(1, 6)}
    s = recording_scheduler(outcomes)

    async def go():
        await s._execute_task("wf")
        [run] = runs_of(factory, "wf")
        async with client_for(app_for(factory, s, monkeypatch)) as client:
            res = await client.get(f"/api/workflows/w-wf/runs/{run['id']}", headers={"x-test-user": "alice"})
        assert res.status_code == 200, res.text
        return res.json()

    out = asyncio.run(go())
    return {"each": each, "execution": out}


def test_each_item_line_says_its_answer(box, served):
    nodes = served["execution"]["nodes"]
    own = next(n for n in nodes if n["node_id"] == "each" and n.get("item") is None)
    items = sorted((n for n in nodes if n["node_id"] == "each" and n.get("item") is not None),
                   key=lambda n: n["item"])
    assert [n["status"] for n in items] == ["success", "success", "error", "success", "success"]
    assert items[0]["output"]["text"].startswith("```json"), "the model fenced its answer, as asked"
    o = _run(box, "", f"""
        const {{ host }} = await import('./shim.js');
        const {{ createWorkflowPanels }} = await import('./workflowPanels.js');
        const panels = createWorkflowPanels({{ mountTaskFields: () => ({{ destroy() {{}} }}) }});
        const h = host();
        panels.record(h, {{ node: {json.dumps(served['each'])}, record: {json.dumps(own)},
                           items: {json.dumps(items)}, run: {json.dumps(served['execution']['run'])} }});
        console.log(JSON.stringify(h.querySelectorAll('.wf-record-item-word').map((s) => s.textContent)));
    """)
    assert o[0] == f"Item 1 of 5: Success — summary: {MAILS[0]} · urgent: true"
    assert o[1] == f"Item 2 of 5: Success — summary: {MAILS[1]} · urgent: false"
    assert o[2] == ("Item 3 of 5: Failed — The answer was not in the shape asked for: "
                    "The answer did not end in the JSON object this step asks for.")
    assert o[4] == f"Item 5 of 5: Success — summary: {MAILS[4]} · urgent: false"
    assert not any("```" in line or "<think>" in line for line in o), o


def test_an_answer_with_no_shape_says_its_first_words(box):
    """An item with no `data` (a Prompt step with no answer shape) says the
    first line of its text that is words — past a fence or a think block."""
    o = _run(box, "", """
        const { itemAnswer } = await import('./workflowPanels.js');
        console.log(JSON.stringify([
          itemAnswer({ status: 'success', output: { text: '```\\nThree new posts.\\n```', data: null } }),
          itemAnswer({ status: 'success', output: { text: '<think>\\nhm\\n</think>\\nTwo replies.', data: {} } }),
          itemAnswer({ status: 'error', error: 'Item failed: the model was busy.\\nTraceback…', output: null }),
          itemAnswer({ status: 'success', output: { text: 'Plain words first.\\nmore', data: null } }),
        ]));
    """)
    assert o == ["Three new posts.", "Two replies.", "Item failed: the model was busy.", "Plain words first."]
