# SPDX-License-Identifier: AGPL-3.0-or-later
"""`B940` — the teacher's run is recorded, labelled and costed on its own route.

The chat route starts the student's run with a route descriptor
(`build_foreground_route_descriptors`): which configured endpoint it is, and
whether its usage is billed. `run_teacher_inline` started the teacher's run
without one, so the teacher's record said `endpoint_id: null`, *Selected route*,
and its usage buckets carried no `endpoint_cost_tracked`. The browser prices a
bucket that says nothing by the chat's *selected* endpoint — the student's — so a
teacher on a paid endpoint behind a local student was not billed, and a local
teacher behind a paid student was billed at the paid rate. And with no endpoint
on the teacher's record, `B922` had to head the teacher's bubbles with none.

Now the teacher's run is started with `resolve_route_descriptor(teacher_url,
teacher_model, teacher_headers, owner)`, and the takeover names that endpoint
when it is a configured one, so the bubble below the banner is on it.

Driven (`Law 20`): the real student and teacher loops (`B939`'s recorded
takeover, the resolver stubbed); the real `recordSessionMetricsCost` with the
real pricing table; the real `_headWithTeacher` and `applyModelMetricsState`.
"""

import json
import shutil
from pathlib import Path

import pytest

from tests.helpers.esc_stub import ui_default_stub  # B874
from tests.helpers.js_source import js_definition  # B876
from tests.helpers.source_text import blank  # B290
from test_tool_effect_surfaces_js import _CARD_SHIM, _CARD_STUBS, _make_sandbox, _run  # noqa: E402
from test_a_teachers_turn_reloads_as_it_streamed import frames, recorded_takeover  # noqa: E402

ROOT = Path(__file__).resolve().parents[1]
JS = ROOT / "static" / "js"
CHAT_JS = JS / "chat.js"

TEACHER = "claude-sonnet-4-5"   # a model the pricing table knows
LAB = {"endpoint_id": "ep-lab", "endpoint_label": "Lab API", "endpoint_cost_tracked": True}
HOME = {"endpoint_id": "ep-home", "endpoint_label": "Home GPU", "endpoint_cost_tracked": False}


def _teacher_frames(monkeypatch, route):
    sent = frames(recorded_takeover(monkeypatch, teacher=TEACHER, route=route))
    [takeover] = [f for f in sent if f.get("type") == "teacher_takeover"]
    [metrics] = [f["data"] for f in sent if f.get("type") == "metrics" and f.get("teacher")]
    return takeover, metrics


def test_the_teachers_run_is_recorded_on_its_endpoint(monkeypatch):
    takeover, metrics = _teacher_frames(monkeypatch, LAB)
    # Looked up for the route the teacher resolved to, in its owner's scope.
    assert recorded_takeover.looked_up == [("http://teacher.example/v1", TEACHER, "alice")]
    assert (metrics["endpoint_id"], metrics["endpoint_label"]) == ("ep-lab", "Lab API")
    assert (metrics["requested_endpoint_id"], metrics["requested_endpoint_label"]) == ("ep-lab", "Lab API")
    assert metrics["endpoint_cost_tracked"] is True
    assert metrics["round_endpoint_labels"] == ["Lab API"] * len(metrics["round_texts"])
    assert metrics["usage_buckets"] and all(
        b.get("endpoint_cost_tracked") is True and b.get("endpoint_label") == "Lab API"
        for b in metrics["usage_buckets"]), metrics["usage_buckets"]
    # The takeover names it, beside the model it named already (`B922`).
    assert (takeover["model"], takeover["endpoint_id"], takeover["endpoint_label"]) == (
        TEACHER, "ep-lab", "Lab API")


def test_a_teacher_no_endpoint_matches_claims_none(monkeypatch):
    """A teacher setting that names no configured endpoint: the descriptor's
    placeholder, and the takeover names no endpoint, as before."""
    takeover, metrics = _teacher_frames(monkeypatch, None)
    assert metrics["endpoint_id"] is None and metrics["endpoint_label"] == "Selected route"
    assert "endpoint_id" not in takeover and "endpoint_label" not in takeover


# ── the browser: what it costs, what it is called ───────────────────────────

_STUBS = dict(_CARD_STUBS, **{
    "ui.js": ui_default_stub(
        "showToast: () => {}, showError: () => {}, copyToClipboard: () => {},\n"
        "el: (id) => document.getElementById(id), debounce: (f) => f,\n"
        "autoResize: () => {}, scrollHistory: () => {}, formatBytes: (n) => String(n),"),
})


@pytest.fixture(scope="module")
def sandbox(tmp_path_factory):
    if not shutil.which("node"):
        pytest.skip("node binary not on PATH")
    d = _make_sandbox(tmp_path_factory.mktemp("teacherroute"), JS / "chatRenderer.js", _CARD_SHIM, _STUBS)
    # The real pricing lookup: the card stubs answer "unknown model" for every name.
    shutil.copy(JS / "model" / "matchKey.js", d / "model" / "matchKey.js")
    shutil.copy(JS / "chatModelProvenance.js", d / "chatModelProvenance.js")
    return d


def _cost(sandbox, metrics, selected_url):
    return _run(sandbox, "", """
        import './shim.js';
        const { recordSessionMetricsCost } = await import('./chatRenderer.js');
        // From history: priced, not added to the session's ledger again.
        const cost = recordSessionMetricsCost(Object.assign(%s, { _fromHistory: true }), 's1', %s);
        console.log(JSON.stringify({ cost }));
    """ % (json.dumps(metrics), json.dumps(selected_url)))["cost"]


def test_a_paid_teacher_behind_a_local_student_is_billed(monkeypatch, sandbox):
    _, metrics = _teacher_frames(monkeypatch, LAB)
    cost = _cost(sandbox, metrics, "http://127.0.0.1:8080/v1")
    assert isinstance(cost, (int, float)) and cost > 0, (
        f"the teacher's paid usage was priced by the student's local endpoint: {cost}")


def test_a_local_teacher_behind_a_paid_student_is_not_billed(monkeypatch, sandbox):
    _, metrics = _teacher_frames(monkeypatch, HOME)
    assert _cost(sandbox, metrics, "https://api.openai.com/v1") is None, (
        "the teacher's local usage was billed at the student's paid endpoint")


def _head_with_teacher() -> str:
    code = blank(CHAT_JS)
    return js_definition(CHAT_JS.read_text(encoding="utf-8"), code.index("function _headWithTeacher("))


def test_the_teachers_bubbles_are_on_its_endpoint_to_the_end_of_the_turn(monkeypatch, sandbox):
    """The heading the takeover gives the teacher's first bubble, the next
    step's, and the end-of-turn relabel by the teacher's own record — through
    the real provenance functions and the label the final render draws. On its
    endpoint throughout, and never read as a change of route."""
    takeover, metrics = _teacher_frames(monkeypatch, LAB)
    out = _run(sandbox, "", """
        import { document, Node, history } from './shim.js';
        const { modelRouteLabel, applyModelColor } = await import('./chatRenderer.js');
        const { inheritModelRouteState, applyModelMetricsState } = await import('./chatModelProvenance.js');
        const _modelRouteLabel = modelRouteLabel;
        const _applyModelColor = applyModelColor;
        %s
        const bubble = (route) => {
          const b = history.appendChild(new Node('div'));
          b.className = 'msg msg-ai';
          b.appendChild(new Node('div')).className = 'role';
          return Object.assign(b, route);
        };
        const student = bubble({ _requestedModel: 'small-local-model', _actualModel: 'small-local-model',
          _requestedEndpointId: 'ep-gpu', _requestedEndpointLabel: 'Desk GPU',
          _actualEndpointId: 'ep-gpu', _actualEndpointLabel: 'Desk GPU' });
        const first = bubble({});
        inheritModelRouteState(student, student, first, 'small-local-model');
        _headWithTeacher(first, %s);
        const next = bubble({});
        inheritModelRouteState(student, first, next, 'small-local-model');
        const end = applyModelMetricsState(%s, student, next, 'small-local-model');
        const route = (b) => [b._actualEndpointId, b._actualEndpointLabel];
        const label = (b) => modelRouteLabel(b._requestedModel, b._actualModel, b._requestedEndpointLabel,
          b._actualEndpointLabel, b._requestedEndpointId, b._actualEndpointId);
        console.log(JSON.stringify({ first: [label(first), ...route(first)], next: [label(next), ...route(next)],
                                     end: [label(end), ...route(end)] }));
    """ % (_head_with_teacher(), json.dumps(takeover), json.dumps(metrics)))
    assert out == {"first": [TEACHER, "ep-lab", "Lab API"], "next": [TEACHER, "ep-lab", "Lab API"],
                   "end": [TEACHER, "ep-lab", "Lab API"]}, out
