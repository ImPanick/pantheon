# SPDX-License-Identifier: AGPL-3.0-or-later
"""`B922` — a teacher takeover's bubbles are headed with the teacher's model.

A step's bubble copies the route of the bubble above it
(`inheritModelRouteState`), and nothing in the teacher's stream relabelled the
bubbles the takeover opened: `model_actual` is sent only when a provider
resolves a different model from the one requested, and the teacher's `metrics`
relabel only the last bubble, at the end. So directly under *Teacher takeover:
escalating to big-model* the teacher's reply was headed with the student's
model until the turn ended, and earlier teacher bubbles kept it.

Now the takeover event names the model the teacher's run requests (`model`,
beside `teacher_model`, the setting it was resolved from), and `_headWithTeacher`
(`static/js/chat.js`) heads the teacher's first bubble with it in both streams;
later steps inherit it. The row also asked for the teacher's endpoint on the
event. Measured instead: the teacher's run is started without a route
descriptor, so its own record names no endpoint ("Selected route"), and a
bubble that kept one — the student's, or the teacher's — was relabelled at the
end of the turn as a change of route. The bubble claims none.

Both halves are driven (`Law 20`): `run_teacher_inline` with the settings, the
resolver, the model and the skill writer stubbed; and the end-of-turn relabel
through the real `applyModelMetricsState` and `modelRouteLabel`. Both streams'
headings are compared in `test_a_resumed_stream_draws_what_the_live_one_drew.py`.
"""

import asyncio
import json
import shutil
from pathlib import Path

import pytest

import src.teacher_escalation as teacher_escalation
from tests.helpers.esc_stub import ui_default_stub  # B874
from tests.helpers.js_source import js_definition  # B876
from tests.helpers.source_text import blank  # B290
from test_tool_effect_surfaces_js import _CARD_SHIM, _CARD_STUBS, _make_sandbox, _run  # noqa: E402

ROOT = Path(__file__).resolve().parents[1]
CHAT_JS = ROOT / "static" / "js" / "chat.js"
CHAT_RENDERER = ROOT / "static" / "js" / "chatRenderer.js"


def _takeover_events(monkeypatch, spec="big-model@lab", resolved="big-model-2026-09"):
    import src.agent_loop as agent_loop
    import src.ai_interaction as ai_interaction
    import src.settings as settings

    values = {"teacher_enabled": True, "teacher_model": spec}
    monkeypatch.setattr(settings, "get_setting", lambda k, d=None: values.get(k, d))
    verdicts = iter([("failure", "agent reply matched give-up pattern"), ("ok", None)])
    monkeypatch.setattr(teacher_escalation, "evaluate_turn_regex", lambda *a, **k: next(verdicts))
    monkeypatch.setattr(ai_interaction, "_resolve_model",
                        lambda s, owner=None: ("http://teacher.local/v1", resolved, {}))

    async def teacher_run(**kwargs):
        yield f"data: {json.dumps({'delta': 'On it.'})}\n\n"
        yield "data: [DONE]\n\n"

    monkeypatch.setattr(agent_loop, "stream_agent_loop", teacher_run)

    async def no_skill(*a, **k):
        return "NO_SKILL"

    monkeypatch.setattr(teacher_escalation, "_call_teacher", no_skill)

    async def drain():
        return [c async for c in teacher_escalation.run_teacher_inline(
            student_endpoint_url="http://student.local/v1",
            student_messages=[{"role": "user", "content": "find the backups"}],
            student_tool_events=[], student_reply="I can't find them.",
            owner="alice", session_id="s1")]

    events = []
    for chunk in asyncio.run(drain()):
        if chunk.startswith("data: {"):
            events.append(json.loads(chunk[6:]))
    return events


def test_the_takeover_names_the_model_the_teachers_run_requests(monkeypatch):
    events = _takeover_events(monkeypatch)
    takeover = next(e for e in events if e.get("type") == "teacher_takeover")
    assert takeover["model"] == "big-model-2026-09"
    # What the banner prints is unchanged (`Law 1`): the setting as written.
    assert takeover["teacher_model"] == "big-model@lab"
    assert takeover["student_failure"] == "agent reply matched give-up pattern"


# ── the end of the turn ─────────────────────────────────────────────────────

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
    d = _make_sandbox(tmp_path_factory.mktemp("teacherhead"), CHAT_RENDERER, _CARD_SHIM, _STUBS)
    shutil.copy(ROOT / "static" / "js" / "chatModelProvenance.js", d / "chatModelProvenance.js")
    return d


def _head_with_teacher() -> str:
    code = blank(CHAT_JS)
    return js_definition(CHAT_JS.read_text(encoding="utf-8"), code.index("function _headWithTeacher("))


def test_the_teachers_last_bubble_keeps_the_teachers_name_at_the_end(sandbox):
    """At the end of the turn the teacher's `metrics` relabel its last bubble,
    through `applyModelMetricsState` and the label the final render draws. The
    teacher's record names no endpoint ("Selected route"); a bubble that still
    held the student's endpoint was then labelled as a change of route. The
    teacher's heading carries none, so the name is all the label says."""
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
          const role = b.appendChild(new Node('div'));
          role.className = 'role';
          return Object.assign(b, route);
        };
        const student = bubble({ _requestedModel: 'small-model', _actualModel: 'small-model',
          _requestedEndpointId: 'ep-home', _requestedEndpointLabel: 'Home GPU',
          _actualEndpointId: 'ep-home', _actualEndpointLabel: 'Home GPU' });
        // The teacher's first bubble, opened as a step's is: it inherits the student's route.
        const first = bubble({});
        inheritModelRouteState(student, student, first, 'small-model');
        const takeover = { type: 'teacher_takeover', teacher_model: 'big-model@lab', model: 'big-model' };
        _headWithTeacher(first, takeover);
        const heading = first.querySelector('.role').textContent;
        // The teacher's next step inherits it.
        const next = bubble({});
        inheritModelRouteState(student, first, next, 'small-model');
        // The teacher's metrics, as its run reports them, relabel the last bubble.
        const metrics = { model: 'big-model', requested_model: 'big-model', round_models: ['big-model', 'big-model'],
          requested_endpoint_id: null, requested_endpoint_label: 'Selected route', endpoint_id: null,
          endpoint_label: 'Selected route', round_endpoint_ids: [null, null],
          round_endpoint_labels: ['Selected route', 'Selected route'] };
        const t = applyModelMetricsState(metrics, student, next, 'small-model');
        const label = (b) => modelRouteLabel(b._requestedModel, b._actualModel, b._requestedEndpointLabel,
          b._actualEndpointLabel, b._requestedEndpointId, b._actualEndpointId);
        console.log(JSON.stringify({ heading, next: label(next), end: label(t) }));
    """ % _head_with_teacher())
    assert out == {"heading": "big-model", "next": "big-model", "end": "big-model"}, out
