# SPDX-License-Identifier: AGPL-3.0-or-later
r"""`B1099` — an HTTP step's query and body values offer the picker by their
entry's name, and say why not before Done.

**Measured before this file:** whether another step may fill `query[i].value`
/ `body[i].value` depends on that entry's name
(`workflow_slots.classify_argument`), which the palette answers once per kind
— so it said every one `never` with the classifier's sentence, and the panel
offered *Insert a field…* on none of them; a body entry named `text`, which
the save route takes a reference in, could only be typed into.
`test_the_halves_are_one_product.py` filed it as "the one gap" (`http
body[0].value`).

Now `POST /api/workflows/slot` answers the rule's slot (`slot_for`) for one
field of a step as it stands, and the HTTP form asks it as an entry's name is
typed: `text` offers the picker, `to` and `url` say why not — before Done.

Driven (`Law 20`): the route through the real workflow router; the panel —
the real room, canvas, panels, step forms, source and `workflowApi.js` in node
— against the REAL server on a loopback port (`tests/helpers/workflow_live.py`).
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

WHY_NOT_TEXT = "Typed only: this could be an address or a command."


# ── the door ────────────────────────────────────────────────────────────────

@pytest.fixture()
def client(monkeypatch, tmp_path):
    from fastapi.testclient import TestClient
    from tests.helpers.walker_harness import app_for, make_db, recording_scheduler
    factory = make_db(monkeypatch, tmp_path / "slot.db")
    return TestClient(app_for(factory, recording_scheduler(), monkeypatch))


def _slot(client, node, field):
    return client.post("/api/workflows/slot", headers={"x-test-user": "alice"},
                       json={"node": node, "field": field})


@pytest.mark.parametrize("name, mapping", [("text", "value"), ("message", "value"), ("subject", "value"),
                                           ("to", "never"), ("url", "never"), ("", "never")])
def test_the_door_answers_the_rule_for_an_entry_by_its_name(client, name, mapping):
    from src import workflow_slots as ws
    for lst in ("query", "body"):
        node = {"kind": "http", "config": {lst: [{"name": name, "value": ""}]}}
        r = _slot(client, node, f"{lst}[0].value")
        assert r.status_code == 200, r.text
        rule = ws.slot_for(node, (lst, 0, "value"))
        assert r.json() == {"mapping": rule.mapping, "why": rule.why}
        assert r.json()["mapping"] == mapping
    if mapping == "never":
        assert r.json()["why"] == WHY_NOT_TEXT


def test_the_door_answers_any_declared_field_and_refuses_what_it_cannot_say(client):
    assert _slot(client, {"kind": "http", "config": {}}, "path").json()["mapping"] == "never"
    assert _slot(client, {"kind": "code", "config": {}}, "input[0].value").json()["mapping"] == "value"
    for node, field in [({"kind": "mcp", "config": {"tool": "x"}}, "args.text"),
                        ({"kind": "http"}, "body[0]value"),
                        ({"config": {}}, "path"),
                        ({"kind": "http", "config": []}, "path")]:
        r = _slot(client, node, field)
        assert r.status_code == 400 and r.json()["detail"], (node, field, r.text)


# ── the panel ───────────────────────────────────────────────────────────────

pytestmark_js = pytest.mark.skipif(not shutil.which("node"), reason="node binary not on PATH")


@pytest.fixture(scope="module")
def box(tmp_path_factory):
    return build_sandbox(tmp_path_factory.mktemp("httpslot"), _CANVAS_SHIM)


@pytest.fixture()
def world(monkeypatch, tmp_path):
    from tests.helpers.assist_harness import build_world, miniflux
    from test_a_workflow_file_js import _make

    w = build_world(monkeypatch, tmp_path, integrations=[miniflux()])
    w.wid = _make(w, "Post the digest", {"v": 1, "nodes": [
        {"id": "read", "kind": "llm", "label": "Read the mail", "config": {"prompt": "Read it."}},
        {"id": "post", "kind": "http", "label": "Post it",
         "config": {"integration": "intg-miniflux", "method": "POST", "path": "/v1/entries",
                    "body": [{"name": "text", "value": ""}], "body_mode": "json"}}],
        "edges": [{"from": "read", "port": "success", "to": "post"}]})
    w.server = LiveServer(w.app)
    try:
        yield w
    finally:
        w.server.close()


_READ = (
    "const byField = (root, f) => root.querySelectorAll('[data-field]').find((n) => n.dataset.field === f) || null;\n"
    "const slotOf = (root, f) => { const b = root.querySelectorAll('.wf-slot').find((x) => x.dataset.slotFor === f);\n"
    "  if (!b) return null;\n"
    "  const never = b.querySelector('.wf-slot-never');\n"
    "  return { mapping: b.dataset.mapping || null, picker: !!b.querySelector('.wf-slot-pick'),\n"
    "           why: never ? never.textContent : null }; };\n"
    "const slotsFor = (root, f) => root.querySelectorAll('.wf-slot').filter((x) => x.dataset.slotFor === f).length;\n"
)


@pytestmark_js
def test_a_body_entry_named_text_offers_the_picker_and_one_named_url_says_why(box, world):
    o = _run(box, LIVE_PREAMBLE(world.server.base) + _READ + f"const WID = {as_js(world.wid)};\n", """
        const { r } = await room({ workflowId: WID });
        fire(nodeEl(r, 'post'), 'click'); await quiet();
        const named = slotOf(r, 'body[0].value');
        typed(byField(r, 'body[0].name'), 'url');
        await new Promise((res) => setTimeout(res, 400)); await quiet();
        const url = slotOf(r, 'body[0].value');
        typed(byField(r, 'body[0].name'), 'to');
        await new Promise((res) => setTimeout(res, 400)); await quiet();
        const to = slotOf(r, 'body[0].value');
        typed(byField(r, 'body[0].name'), 'message');
        await new Promise((res) => setTimeout(res, 400)); await quiet();
        out({ named, url, to, message: slotOf(r, 'body[0].value'), boxes: slotsFor(r, 'body[0].value'),
              asked: calls('POST', (u) => u === '/api/workflows/slot').map(([, b]) => [b.field, b.node.config.body[0].name]),
              saved: calls('PUT', (u) => u.startsWith('/api/workflows/')).length });
    """)
    assert o["named"] == {"mapping": "value", "picker": True, "why": None}, "`text` offers Insert a field…"
    assert o["url"] == {"mapping": "never", "picker": False, "why": WHY_NOT_TEXT}, "`url` says why, before Done"
    assert o["to"] == {"mapping": "never", "picker": False, "why": WHY_NOT_TEXT}
    assert o["message"]["picker"] is True
    assert o["boxes"] == 1, "one line under the value, not one per answer"
    assert o["asked"] == [["body[0].value", n] for n in ("text", "url", "to", "message")]
    assert o["saved"] == 0, "asking is reading: nothing is saved"
