# SPDX-License-Identifier: AGPL-3.0-or-later
r"""`P22-19` (wb-canvas-e) — describe it, and a draft workflow arrives switched off, every step marked until a person checks it.

The browser half of `SLICE-EF-DESIGN.md` § 2 P22-19 (package B, § 3): *New
workflow* gains *Or describe it* — a box, *Draft it*, and at most six example
sentences that fill the box (`D-2026-10-02-02` §1; nothing is installed or
fetched) — sending C-A's `POST /api/workflows {describe, tz}`. The draft opens
on what arrived (where it sends things, what the model could not draft); each
step carries the server's mark (`unchecked`), drawn as words ("Drafted — check
me") with a dashed border; its panel opens on a banner — who decided it, what
it would do (the dry run's plan, nothing run), *Looks right* (C-A's
`PUT {checked}`). Switching on while marks remain is refused (409, `reason:
"unchecked"`) and the refusal offers *Check them now*: every marked step with
what it would do, *Looks right* each, *All look right*, then *Switch on*. A
label the model wrote stays text.

Driven: the real room, canvas, panels, source and `workflowApi.js` over the
C-A fake server (`tests/helpers/workflow_ca_fake.py`). The drafter's replies —
the create door's answer to `{describe}`, the switch's 409 and the palette's
example sentences — are RECORDED from wb-assist's real routes wherever its
drafter is in the tree (a scripted model answering this file's draft), and are
C-A's literal shapes on this branch alone; the palette is `build_palette`'s and
every plan line is `plan_lines`'.
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
    ROOM_PREAMBLE, as_js, build_sandbox, palette, plan_of, recorded_draft,
)

pytestmark = pytest.mark.skipif(not shutil.which("node"), reason="node binary not on PATH")

_AT = "2026-10-02T09:00:00Z"


def _node(id_, kind, label, config):
    return {"id": id_, "kind": kind, "label": label, "config": config, "position": None, "pinned": None,
            "unchecked": {"origin": "drafted", "at": _AT, "needs": []}}


def _drafted(label_summarise="Summarise"):
    """The design's Verify: "when a GitHub webhook says an issue opened,
    summarise it and post it to my chat server" → If → Summarise → Post."""
    nodes = [
        _node("is-it-new", "if", "Is it a new issue?", {"join": "all", "conditions": [
            {"left": "{{ steps.start.data.json.action }}", "op": "equals", "right": "opened"}]}),
        _node("summarise", "llm", label_summarise,
              {"prompt": "Summarise the issue in two lines: {{ steps.start.data.json.issue.title }}"}),
        _node("post", "mcp", "Post to #dev",
              {"tool": "mcp__chat__send_message", "args": {"channel": "#dev", "text": "{{ steps.summarise.text }}"}}),
    ]
    edges = [{"from": "start", "port": "success", "to": "is-it-new"},
             {"from": "is-it-new", "port": "then", "to": "summarise"},
             {"from": "summarise", "port": "success", "to": "post"}]
    return {"id": "wf9", "name": "New issues to #dev", "task_id": "t9", "trigger_status": "paused", "version": 1,
            "trigger_task": {"id": "t9", "status": "paused", "trigger_type": "webhook"},
            "graph": {"v": 1, "start": {"position": None}, "nodes": nodes, "edges": edges}}


_DESCRIBE = "when a GitHub webhook says an issue opened, summarise it and post it to my chat server"


def _record(tmp_path, doc=None, *, missing=(), destinations=("Posts with Chat: send_message to #dev",)):
    doc = doc or _drafted()
    return recorded_draft(tmp_path, doc, describe=_DESCRIBE,
                          notes=[f"Drafted “{doc['name']}”: 3 steps, switched off."],
                          missing=missing, destinations=destinations)


def _world(rec, pal=None):
    reply = rec["reply"]
    plans = {n["id"]: plan_of(n) for n in reply["workflow"]["graph"]["nodes"]}
    p = pal or palette()
    p["examples"] = rec["examples"]
    return (
        f"cw.palette = {as_js(p)};\n"
        f"const REPLY = {as_js(reply)};\n"
        f"ca.dryNodes = {as_js(plans)};\n"
        f"ca.switchRefusal = {as_js(rec['switch_refusal'])};\n"
        "ca.draft = () => ({ status: 200, body: JSON.parse(JSON.stringify(REPLY)) });\n"
        "const WID = REPLY.workflow.id;\n"
        "const draftAndOpen = async () => {\n"
        "  const { r, handle } = await room();\n"
        "  fire(by(r, 'wf-shelf-new'), 'click'); await settle(10);\n"
        f"  typed(by(r, 'wf-new-text'), {as_js(_DESCRIBE)});\n"
        "  fire(by(r, 'wf-new-draft'), 'click'); await settle(40);\n"
        "  return { r, handle };\n"
        "};\n"
    )


@pytest.fixture(scope="module")
def box(tmp_path_factory):
    return build_sandbox(tmp_path_factory.mktemp("describe"), _CANVAS_SHIM)


@pytest.fixture(scope="module")
def rec(tmp_path_factory):
    """The drafter's replies for this file's draft: recorded, or literal."""
    return _record(tmp_path_factory.mktemp("drafter"))


def _case(box, rec, script):
    return _run(box, ROOM_PREAMBLE + _world(rec), script)


def _ids(rec):
    return [n["id"] for n in rec["reply"]["workflow"]["graph"]["nodes"]]


def test_the_describe_box_posts_describe_and_tz_and_the_draft_opens_marked_and_off(box, rec):
    o = _case(box, rec, """
        const { r } = await room();
        fire(by(r, 'wf-shelf-new'), 'click'); await settle(10);
        const offered = all(r, 'wf-new-example').map((b) => b.textContent);
        const before = ca.calls.length;
        fire(all(r, 'wf-new-example')[1], 'click'); await settle(5);
        const filled = by(r, 'wf-new-text').value;
        const afterPick = ca.calls.length - before;
        fire(by(r, 'wf-new-draft'), 'click'); await settle(40);
        const arrived = by(r, 'wf-arrived');
        out({ offered, filled, afterPick, tz: Intl.DateTimeFormat().resolvedOptions().timeZone,
              posts: calls('POST', (u) => u === '/api/workflows'),
              formHidden: by(r, 'wf-new').hidden,
              steps: steps(r).map((n) => [n.dataset.itemId, n.dataset.unchecked || null,
                n.querySelectorAll('.wb-node-badge').map((b) => b.textContent)]),
              start: nodeEl(r, '__start__').dataset.unchecked || null,
              switchWord: by(r, 'wf-switch').textContent,
              arrived: { head: by(arrived, 'wf-arrived-head').textContent, lede: by(arrived, 'wf-arrived-lede').textContent,
                         where: all(arrived, 'wf-arrived-destinations').map((u) => u.textContent),
                         buttons: arrived.querySelectorAll('button').map((b) => b.textContent) },
              said: sayOf(r),
              shelf: all(r, 'wf-shelf-name').map((s) => s.textContent) });
    """)
    examples = rec["examples"]
    assert o["offered"] == examples[:6], "at most six example sentences, the palette's, in its order"
    assert o["filled"] == examples[1] and o["afterPick"] == 0, "picking one fills the box and sends nothing"
    assert o["posts"] == [["/api/workflows", {"describe": examples[1], "tz": o["tz"]}]], "C-A's create door, describe and tz"
    assert o["formHidden"] is True
    word = ["Drafted — check me"]
    assert o["steps"] == [[i, "drafted", word] for i in _ids(rec)] and len(o["steps"]) == 3, \
        "every drafted step says so in words, and carries its origin for the dashed border"
    assert o["start"] is None, "the start is the trigger's, never marked"
    assert o["switchWord"] == "Off"
    assert o["arrived"]["head"] == "Drafted by the model"
    assert o["arrived"]["lede"].startswith("It is switched off, and each step is marked “check me”")
    assert o["arrived"]["where"] == ["".join(rec["reply"]["destinations"])], "where it sends things, in the server's words"
    assert rec["reply"]["destinations"], "the reply names where it sends things"
    assert o["arrived"]["buttons"] == ["Check them now", "Close"]
    assert o["said"] == " ".join(rec["reply"]["notes"]), "the server's notes, said once it is drawn"
    assert rec["reply"]["workflow"]["name"] in o["shelf"]


def test_a_marked_steps_panel_opens_on_its_banner_and_looks_right_checks_it_and_writes_no_version(box, rec):
    o = _case(box, rec, """
        const { r } = await draftAndOpen();
        fire(nodeEl(r, 'summarise'), 'click'); await settle(30);
        const b = by(r, 'wf-step-check');
        const banner = { origin: b.dataset.origin, head: by(b, 'wf-step-check-head').textContent,
          note: by(b, 'wf-step-check-note').textContent,
          plan: by(b, 'wf-step-check-plan').querySelectorAll('li').map((li) => li.textContent),
          yes: by(b, 'wf-step-check-yes').textContent };
        fire(by(b, 'wf-step-check-yes'), 'click'); await settle(30);
        const checked = { head: by(r, 'wf-step-check').querySelectorAll('p').map((p) => p.textContent),
          marks: steps(r).map((n) => [n.dataset.itemId, n.dataset.unchecked || null]) };
        fire(nodeEl(r, 'post'), 'click'); await settle(30);
        const postPlan = by(r, 'wf-step-check').querySelector('.wf-step-check-plan').querySelectorAll('li').map((li) => li.textContent);
        out({ banner, checked, postPlan,
              puts: calls('PUT', (u) => u === '/api/workflows/' + WID),
              dryRuns: calls('POST', (u) => u.endsWith('/run?dry=true')).length,
              versions: ca.versions.length, version: cw.doc.version, dirty: by(r, 'wf-dirty').textContent });
    """)
    b = o["banner"]
    assert b["origin"] == "drafted" and b["head"] == "Drafted by the model — check it."
    assert b["note"].startswith("The model wrote this step from your description")
    nodes = rec["reply"]["workflow"]["graph"]["nodes"]
    assert b["plan"] == plan_of(nodes[1]), "what it would do: the dry run's plan, plan_lines' words"
    assert b["yes"] == "Looks right"
    assert o["puts"] == [[f"/api/workflows/{rec['reply']['workflow']['id']}", {"checked": ["summarise"]}]], \
        "C-A's check: the one step, nothing else"
    assert o["checked"]["head"] == ["Checked. It runs as it is once the workflow is switched on."]
    assert o["checked"]["marks"] == [["is-it-new", "drafted"], ["summarise", None], ["post", "drafted"]], \
        "the canvas is drawn again: the checked step's mark is gone, the others keep theirs"
    assert o["postPlan"] == plan_of(nodes[2])
    assert o["dryRuns"] == 1, "the saved version is planned once, however many panels open"
    assert o["versions"] == 1 and o["version"] == 1, "a check writes no version"
    assert o["dirty"] == "", "and leaves the draft clean"


def test_switching_on_with_unchecked_steps_offers_check_them_now_and_all_look_right_then_switch_on(box, rec):
    o = _case(box, rec, """
        const { r } = await draftAndOpen();
        fire(by(r, 'wf-switch'), 'click'); await settle(30);
        const refused = { said: sayOf(r), action: sayButton(r) && sayButton(r).textContent };
        fire(sayButton(r), 'click'); await settle(30);
        const layer = by(r, 'wf-check');
        const listed = { role: layer.getAttribute('role'), lede: by(layer, 'wf-check-lede').textContent,
          rows: all(layer, 'wf-check-step').map((li) => [li.dataset.nodeId, by(li, 'wf-check-label').textContent,
            by(li, 'wf-check-origin').textContent, by(li, 'wf-check-plan').querySelectorAll('li').map((x) => x.textContent)]),
          foot: by(layer, 'wf-check-foot').querySelectorAll('button').map((x) => x.textContent) };
        fire(by(layer, 'wf-check-all'), 'click'); await settle(30);
        const after = { lede: by(layer, 'wf-check-lede').textContent,
          said: all(layer, 'wf-check-said').map((p) => p.textContent),
          foot: by(layer, 'wf-check-foot').querySelectorAll('button').map((x) => x.textContent),
          marks: steps(r).filter((n) => n.dataset.unchecked).length };
        fire(by(layer, 'wf-check-switch'), 'click'); await settle(30);
        out({ refused, listed, after,
              switches: calls('POST', (u) => u.endsWith('/switch')),
              puts: calls('PUT', (u) => u === '/api/workflows/' + WID),
              on: by(r, 'wf-switch').textContent, layerGone: !by(r, 'wf-check') });
    """)
    assert o["refused"]["said"] == "Not switched on: " + rec["switch_refusal"]["detail"], "the server's sentence, as it wrote it"
    assert rec["switch_refusal"]["reason"] == "unchecked" and rec["switch_refusal"]["node_ids"] == _ids(rec)
    assert o["refused"]["action"] == "Check them now"
    nodes = rec["reply"]["workflow"]["graph"]["nodes"]
    assert o["listed"]["role"] == "dialog"
    assert o["listed"]["lede"].startswith("3 steps nobody has checked yet.")
    assert o["listed"]["rows"] == [[n["id"], n["label"], "Drafted by the model", plan_of(n)] for n in nodes], \
        "every step the refusal names, with what it would do"
    assert o["listed"]["foot"] == ["All look right", "Close"]
    assert o["puts"] == [[f"/api/workflows/{rec['reply']['workflow']['id']}", {"checked": _ids(rec)}]], "one check for the rest"
    assert o["after"]["lede"] == "Every step is checked."
    assert o["after"]["said"] == ["Checked.", "Checked.", "Checked."]
    assert o["after"]["foot"] == ["Switch on", "Close"] and o["after"]["marks"] == 0
    assert o["switches"] == [[f"/api/workflows/{rec['reply']['workflow']['id']}/switch", {"on": True}]] * 2, \
        "refused once, then switched on"
    assert o["on"] == "On" and o["layerGone"] is True


_HOSTILE = "<img src=x onerror=alert(1)>Summarise"


def test_a_label_a_reason_and_a_line_the_model_wrote_stay_text(box, tmp_path):
    hostile = _record(tmp_path, _drafted(_HOSTILE), missing=["<img src=x onerror=alert(2)> could not be drafted"],
                      destinations=["<b>Posts</b> with Chat"])
    o = _run(box, ROOM_PREAMBLE + _world(hostile), """
        const { r } = await draftAndOpen();
        fire(nodeEl(r, 'summarise'), 'click'); await settle(30);
        fire(by(r, 'wf-switch'), 'click'); await settle(20);
        fire(sayButton(r), 'click'); await settle(30);
        const text = (cls) => all(r, cls).map((x) => x.textContent);
        out({ title: nodeEl(r, 'summarise').querySelector('.wb-node-title').textContent,
              layer: text('wf-check-label'), missing: text('wf-arrived-text'), where: text('wf-arrived-destinations'),
              imgs: r.querySelectorAll('img').length,
              markup: markup(r).filter((m) => m.includes('onerror') || m.includes('<b>')) });
    """)
    reply = hostile["reply"]
    label = reply["workflow"]["graph"]["nodes"][1]["label"]
    if hostile["source"] == "literal":
        assert label == _HOSTILE and reply["destinations"] == ["<b>Posts</b> with Chat"]
    assert o["title"] == label, "the label as the server kept it, as text"
    assert label in o["layer"]
    assert o["missing"] == reply["missing"]
    assert o["where"] == ["".join(reply["destinations"])]
    assert o["imgs"] == 0 and o["markup"] == [], "nothing the model wrote was ever markup"


def test_a_refused_draft_is_said_in_the_servers_words_and_nothing_opens(box, rec):
    o = _case(box, rec, """
        ca.draft = () => ({ status: 503, body: { detail: 'No model is set up to draft a workflow. Make it by hand.' } });
        const { r } = await room();
        fire(by(r, 'wf-shelf-new'), 'click'); await settle(10);
        fire(by(r, 'wf-new-draft'), 'click'); await settle(10);
        const empty = { said: by(r, 'wf-new-say').textContent, posts: calls('POST').length };
        typed(by(r, 'wf-new-text'), 'summarise my mail every morning');
        fire(by(r, 'wf-new-draft'), 'click'); await settle(30);
        out({ empty, said: by(r, 'wf-new-say').textContent, formOpen: !by(r, 'wf-new').hidden,
              kept: by(r, 'wf-new-text').value, view: by(r, 'wf-view').hidden,
              refusal: by(r, 'wf-new-say')._classes().includes('wf-new-refusal') });
    """)
    assert o["empty"] == {"said": "Say what it should do first: when it starts, and each thing it does.", "posts": 0}
    assert o["said"] == "Not drafted: No model is set up to draft a workflow. Make it by hand."
    assert o["formOpen"] is True and o["kept"] == "summarise my mail every morning", "nothing typed is lost"
    assert o["view"] is True and o["refusal"] is True


def test_without_c_as_calls_the_form_offers_no_describe_and_no_file(box, rec):
    o = _case(box, rec, """
        const { createWorkflowApi } = await import('./workflowApi.js');
        const real = createWorkflowApi({ fetch: canet });
        const bare = typeof real.checkSteps === 'function' ? null : real;
        const { r } = await room(bare ? { loadWorkflowModules: async () => ({ createWorkflowApi: () => bare, createWorkflowSource }) } : {});
        fire(by(r, 'wf-shelf-new'), 'click'); await settle(10);
        out({ hasCa: !bare, describe: by(r, 'wf-new-describe').hidden, file: by(r, 'wf-new-file-group').hidden,
              name: !by(r, 'wf-new-name').hidden });
    """)
    if o["hasCa"]:
        pytest.skip("workflowApi.js has C-A's calls (wb-assist merged): this guards the branch alone")
    assert o["describe"] is True and o["file"] is True, \
        "a describe or a file sent to a data layer without C-A would make an empty workflow (Law 13)"
    assert o["name"] is True


def test_a_step_changed_in_the_draft_is_the_persons_and_drops_its_mark_before_save(box, rec):
    o = _case(box, rec, """
        const { r } = await draftAndOpen();
        fire(nodeEl(r, 'post'), 'click'); await settle(30);
        // Done on the MCP step's form with a new label: the step is the person's now.
        const name = r.querySelector('.wf-sf').querySelectorAll('[data-field]').find((x) => x.dataset.field === 'label');
        typed(name, 'Post it to #dev');
        fire(r.querySelector('.wf-step-done'), 'click'); await settle(30);
        const marks = steps(r).map((n) => [n.dataset.itemId, n.dataset.unchecked || null]);
        fire(by(r, 'wf-switch'), 'click'); await settle(20);
        fire(sayButton(r), 'click'); await settle(30);
        const row = all(r, 'wf-check-step').find((li) => li.dataset.nodeId === 'post');
        out({ marks, note: all(row, 'wf-check-note').map((p) => p.textContent),
              layerNote: by(r, 'wf-check').querySelectorAll('.wf-check-note').map((p) => p.textContent)[0] });
    """)
    assert o["marks"] == [["is-it-new", "drafted"], ["summarise", "drafted"], ["post", None]], \
        "a step changed here is the person's, as it will be once saved (the server's _marks_kept)"
    assert o["note"] == ["You changed this step. Save, and it is yours: it needs no check."]
    assert o["layerNote"] == "You have changes that are not saved: this checks the steps as they are saved."
