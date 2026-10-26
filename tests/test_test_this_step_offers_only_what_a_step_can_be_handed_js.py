# SPDX-License-Identifier: AGPL-3.0-or-later
r"""`B1082` — *Test this step* offers only the inputs a step can be handed,
and says why of the rest.

**Measured before this file** (`wf-ui`, on the scratch merge, and here
through the real routes): the source list was `TEST_SOURCES`, a static list of
five, on every step. On the first step of a schedule-started workflow it
offered *What it was handed in the last run*, *Something I type here* and *An
example the model writes*, and the route refused each ("The step is handed
nothing, so a sample would never be used: “Summarise my inbox” is the first
step and the workflow does not start on an event or a webhook."); on a step
not yet run, *last* was offered and refused. The server knew the step's input
shape (`node_input_shape`) and the panel did not.

Now the Doc carries `test_sources` (`test_source_offers`: per step, each
source offered or not, with the route's own sentence), and the panel offers
only what can be used.

Driven end to end (`Law 20`): the real routes over a real SQLite file
(`assist_harness`), the real room, canvas, panels, source and `workflowApi.js`
in node against the REAL server on a loopback port
(`tests/helpers/workflow_live.py`); a run is the real scheduler's walk with the
model recorded.
"""
from __future__ import annotations

import asyncio
import shutil
import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parent))

from test_tool_effect_surfaces_js import _run  # noqa: E402
from test_the_workbench_canvas_js import _SHIM as _CANVAS_SHIM  # noqa: E402
from helpers.workflow_live import LIVE_PREAMBLE, LiveServer, as_js, build_sandbox  # noqa: E402
from tests.helpers.walker_harness import arrow, node, seed_workflow  # noqa: E402

pytestmark = pytest.mark.skipif(not shutil.which("node"), reason="node binary not on PATH")

HANDED_NOTHING = ("The step is handed nothing, so a sample would never be used: “Summarise my "
                  "inbox” is the first step and the workflow does not start on an event or a webhook.")
NOT_RUN = "“Send me the summary” has not run yet, so there is no last input to test it with."
EVERY = ["What it was handed in the last run", "Something I type here",
         "An example the model writes", "Nothing"]


@pytest.fixture(scope="module")
def box(tmp_path_factory):
    return build_sandbox(tmp_path_factory.mktemp("testsources"), _CANVAS_SHIM)


def _world(monkeypatch, tmp_path, *, ran=False, trigger_type="schedule"):
    from tests.helpers.assist_harness import build_world

    w = build_world(monkeypatch, tmp_path)
    seed_workflow(w.factory, [
        node("n1", "Summarise my inbox"),
        node("n2", "Send me the summary", output_target="notification"),
    ], [arrow("n1", "n2")], trigger_type=trigger_type)
    if ran:
        asyncio.run(w.s._execute_task("wf"))
    w.server = LiveServer(w.app)
    return w


@pytest.fixture()
def scheduled(monkeypatch, tmp_path):
    w = _world(monkeypatch, tmp_path)
    try:
        yield w
    finally:
        w.server.close()


_OPEN = """
const sourcesOf = async (r, id) => {
  fire(nodeEl(r, id), 'click'); await quiet();
  const open = all(r, 'wf-test').filter(shown);
  const box = open[open.length - 1];
  const sel = box.querySelector('.wf-test-source');
  const why = box.querySelector('.wf-test-why');
  const got = { offered: sel.querySelectorAll('option').map((o) => o.textContent), value: sel.value,
                why: why && !why.hidden ? why.textContent : '' };
  return got;
};
"""


def _case(box, w, script):
    return _run(box, LIVE_PREAMBLE(w.server.base) + _OPEN + f"const WID = {as_js('w-wf')};\n", script)


def test_the_first_step_of_a_scheduled_workflow_offers_only_nothing_and_says_why(box, scheduled):
    o = _case(box, scheduled, """
        const { r } = await room({ workflowId: WID });
        out({ first: await sourcesOf(r, 'n1'), second: await sourcesOf(r, 'n2') });
    """)
    assert o["first"] == {"offered": ["Nothing"], "value": "none",
                          "why": f"Only “Nothing”: {HANDED_NOTHING}"}
    # The second step is handed the first's result: it can be typed or
    # written, but it has not run, so there is no last input.
    assert o["second"]["offered"] == ["Something I type here", "An example the model writes", "Nothing"]
    assert o["second"]["value"] == "none"
    assert o["second"]["why"] == f"“What it was handed in the last run” is not offered: {NOT_RUN}"


def test_what_the_panel_withholds_is_what_the_route_refuses(scheduled):
    """One rule (`Law 7`): every source the Doc says is not offered, the test
    route refuses with the same sentence; every one it offers, it does not
    refuse for that reason."""
    import httpx

    async def go():
        async with httpx.AsyncClient(base_url=scheduled.server.base,
                                     headers={"x-test-user": "alice"}) as http:
            doc = (await http.get("/api/workflows/w-wf")).json()["workflow"]
            refused = {}
            for n in doc["graph"]["nodes"]:
                for offer in doc["test_sources"][n["id"]]:
                    if offer["offered"] or offer["source"] == "pinned":
                        continue
                    res = await http.post(f"/api/workflows/w-wf/nodes/{n['id']}/test",
                                          json={"node": n, "source": offer["source"],
                                                "input": "hello"})
                    refused[(n["id"], offer["source"])] = (res.status_code, res.json()["detail"],
                                                           offer["why"])
            return doc, refused
    doc, refused = asyncio.run(go())
    assert {k for k in refused} == {("n1", "last"), ("n1", "custom"), ("n1", "example"),
                                    ("n2", "last")}
    for (status, detail, why) in refused.values():
        assert status == 400 and detail.startswith(why), (detail, why)
    assert [o["source"] for o in doc["test_sources"]["n2"] if o["offered"]] == [
        "pinned", "custom", "example", "none"]


def test_a_step_that_has_run_offers_its_last_input(box, monkeypatch, tmp_path):
    w = _world(monkeypatch, tmp_path, ran=True)
    try:
        o = _case(box, w, """
            const { r } = await room({ workflowId: WID });
            out({ second: await sourcesOf(r, 'n2') });
        """)
    finally:
        w.server.close()
    assert o["second"] == {"offered": EVERY, "value": "last", "why": ""}


def test_the_first_step_of_a_webhook_workflow_can_be_handed_a_sample(box, monkeypatch, tmp_path):
    w = _world(monkeypatch, tmp_path, trigger_type="webhook")
    try:
        o = _case(box, w, """
            const { r } = await room({ workflowId: WID });
            out({ first: await sourcesOf(r, 'n1') });
        """)
    finally:
        w.server.close()
    assert o["first"]["offered"] == ["Something I type here", "An example the model writes", "Nothing"]
    assert o["first"]["why"] == ("“What it was handed in the last run” is not offered: “Summarise my "
                                 "inbox” has not run yet, so there is no last input to test it with.")
