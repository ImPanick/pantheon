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

Driven end to end (`integrate-e`): the real room, canvas, panels, source and
`workflowApi.js` in node, against wb-assist's REAL server on a loopback port
(`tests/helpers/workflow_live.py`) — the drafter (a scripted model behind
`workflow_assist._complete`, the one seam), the store, the switch, the check,
the dry run. Every reply drawn is the real route's, read back from `wire`.
Before the merge these cases ran over a JavaScript stand-in for those routes
(`workflow_ca_fake.py`, deleted — `Law 20`); the case that guarded the branch
without C-A ("the form offers no describe") skipped itself on every merged
tree and went with it.
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

POST = "mcp__chat__send_message"
_DESCRIBE = "when a GitHub webhook says an issue opened, summarise it and post it to my chat server"


def _answer(label_summarise="Summarise", channel="#dev", missing=()):
    """What the scripted model answers the drafter: the design's Verify —
    If → Summarise → Post, started by a webhook."""
    return {
        "name": "New issues to #dev",
        "trigger": {"type": "webhook"},
        "steps": [
            {"id": "is-it-new", "kind": "if", "label": "Is it a new issue?",
             "config": {"join": "all", "conditions": [
                 {"left": "{{ steps.start.data.json.action }}", "op": "equals", "right": "opened"}]}},
            {"id": "summarise", "kind": "llm", "label": label_summarise,
             "config": {"prompt": "Summarise the issue in two lines: {{ steps.start.data.json.issue.title }}"}},
            {"id": "post", "kind": "mcp", "label": "Post to #dev",
             "config": {"tool": POST, "args": {"channel": channel, "text": "{{ steps.summarise.text }}"}}},
        ],
        "arrows": [{"from": "is-it-new", "port": "then", "to": "summarise"},
                   {"from": "summarise", "port": "success", "to": "post"}],
        "missing": list(missing),
    }


IDS = ["is-it-new", "summarise", "post"]


@pytest.fixture(scope="module")
def box(tmp_path_factory):
    return build_sandbox(tmp_path_factory.mktemp("describe"), _CANVAS_SHIM)


@pytest.fixture()
def live(monkeypatch, tmp_path):
    from tests.helpers.assist_harness import build_world, miniflux, script_model

    w = build_world(monkeypatch, tmp_path, integrations=[miniflux()])
    w.script = lambda *answers: script_model(monkeypatch, *answers)
    w.server = LiveServer(w.app)
    try:
        yield w
    finally:
        w.server.close()


_DRAFT_AND_OPEN = (
    "const draftAndOpen = async () => {\n"
    "  const { r, handle } = await room();\n"
    "  fire(by(r, 'wf-shelf-new'), 'click'); await quiet();\n"
    f"  typed(by(r, 'wf-new-text'), {as_js(_DESCRIBE)});\n"
    "  fire(by(r, 'wf-new-draft'), 'click'); await quiet();\n"
    "  const made = replyTo('POST', (u) => u === '/api/workflows');\n"
    "  return { r, handle, made, WID: made && made.reply && made.reply.workflow ? made.reply.workflow.id : null };\n"
    "};\n"
    "// `B1132`: what a marked step would do is the Doc's `plans` (the dry run's\n"
    "// planner, nothing recorded) — the reply that made the draft carries them.\n"
    "const planOf = (made) => (made && made.reply && made.reply.workflow && made.reply.workflow.plans) || {};\n"
    "const dryRunsAsked = () => calls('POST', (u) => u.includes('/run?dry=true')).length;\n"
)


def _case(box, live, script):
    return _run(box, LIVE_PREAMBLE(live.server.base) + _DRAFT_AND_OPEN, script)


def test_the_describe_box_posts_describe_and_tz_and_the_draft_opens_marked_and_off(box, live):
    from src import workflow_assist as wa

    live.script(_answer())
    o = _case(box, live, """
        const { r } = await room();
        fire(by(r, 'wf-shelf-new'), 'click'); await quiet();
        const offered = all(r, 'wf-new-example').map((b) => b.textContent);
        const before = wire.length;
        fire(all(r, 'wf-new-example')[1], 'click'); await quiet();
        const filled = by(r, 'wf-new-text').value;
        const afterPick = wire.length - before;
        fire(by(r, 'wf-new-draft'), 'click'); await quiet();
        const arrived = by(r, 'wf-arrived');
        const made = replyTo('POST', (u) => u === '/api/workflows');
        out({ offered, filled, afterPick, tz: Intl.DateTimeFormat().resolvedOptions().timeZone,
              posts: calls('POST', (u) => u === '/api/workflows'), status: made.status, reply: made.reply,
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
    examples = list(wa.EXAMPLE_SENTENCES)
    assert o["offered"] == examples[:6], "at most six example sentences, the palette's, in its order"
    assert o["filled"] == examples[1] and o["afterPick"] == 0, "picking one fills the box and sends nothing"
    assert o["posts"] == [["/api/workflows", {"describe": examples[1], "tz": o["tz"]}]], "C-A's create door, describe and tz"
    assert o["status"] == 200, o["reply"]
    reply = o["reply"]
    assert reply["workflow"]["trigger_status"] == "paused"
    assert o["formHidden"] is True
    word = ["Drafted — check me"]
    assert o["steps"] == [[i, "drafted", word] for i in IDS], \
        "every drafted step says so in words, and carries its origin for the dashed border"
    assert o["start"] is None, "the start is the trigger's, never marked"
    assert o["switchWord"] == "Off"
    assert o["arrived"]["head"] == "Drafted by the model"
    assert o["arrived"]["lede"] == "It is off until you check each step."  # P23-05 (Doc 2 § 5)
    # `integrate-e` (`B1134`): one line, only where it sends things.
    assert reply["destinations"] == ["“Post to #dev” sends to Chat: send_message — channel: #dev."]
    assert o["arrived"]["where"] == ["".join(reply["destinations"])], "where it sends things, in the server's words"
    assert o["arrived"]["buttons"] == ["Check them now", "Close"]
    assert o["said"] == " ".join(reply["notes"]), "the server's notes, said once it is drawn"
    assert reply["workflow"]["name"] in o["shelf"]


def test_a_marked_steps_panel_opens_on_its_banner_and_looks_right_checks_it_and_writes_no_version(box, live):
    live.script(_answer())
    o = _case(box, live, """
        const { r, WID, made } = await draftAndOpen();
        fire(nodeEl(r, 'summarise'), 'click'); await quiet();
        const b = by(r, 'wf-step-check');
        const banner = { origin: b.dataset.origin, head: by(b, 'wf-step-check-head').textContent,
          note: by(b, 'wf-step-check-note').textContent,
          plan: by(b, 'wf-step-check-plan').querySelectorAll('li').map((li) => li.textContent),
          yes: by(b, 'wf-step-check-yes').textContent };
        fire(by(b, 'wf-step-check-yes'), 'click'); await quiet();
        const checked = { head: by(r, 'wf-step-check').querySelectorAll('p').map((p) => p.textContent),
          marks: steps(r).map((n) => [n.dataset.itemId, n.dataset.unchecked || null]) };
        fire(nodeEl(r, 'post'), 'click'); await quiet();
        const postPlan = by(r, 'wf-step-check').querySelector('.wf-step-check-plan').querySelectorAll('li').map((li) => li.textContent);
        const plans = planOf(made);
        const dryRuns = dryRunsAsked();
        const runs = (await ask('/api/tasks/' + made.reply.workflow.task_id + '/runs')).runs;
        const puts = calls('PUT', (u) => u === '/api/workflows/' + WID);
        const stored = (await ask('/api/workflows/' + WID)).workflow;
        const versions = (await ask('/api/workflows/' + WID + '/versions')).versions;
        out({ banner, checked, postPlan, plans, puts, dryRuns, runs, WID,
              versions: versions.map((v) => v.source), version: stored.version,
              storedMarks: stored.graph.nodes.map((n) => [n.id, n.unchecked ? n.unchecked.origin : null]),
              dirty: by(r, 'wf-dirty').textContent });
    """)
    b = o["banner"]
    assert b["origin"] == "drafted" and b["head"] == "Drafted by the model — check it."
    assert b["note"].startswith("The model wrote this step from your description")
    assert b["plan"] == o["plans"]["summarise"] and b["plan"], "what it would do: the real dry run's plan"
    assert b["yes"] == "Looks right"
    assert o["puts"] == [[f"/api/workflows/{o['WID']}", {"checked": ["summarise"]}]], \
        "C-A's check: the one step, nothing else"
    assert o["checked"]["head"] == ["Checked. It runs as it is once the workflow is switched on."]
    assert o["checked"]["marks"] == [["is-it-new", "drafted"], ["summarise", None], ["post", "drafted"]], \
        "the canvas is drawn again: the checked step's mark is gone, the others keep theirs"
    assert o["storedMarks"] == o["checked"]["marks"], "…as the server stored it"
    assert o["postPlan"] == o["plans"]["post"]
    # `B1132`: checking reads the Doc's plans; it asks no dry run and records none.
    assert o["dryRuns"] == 0 and o["runs"] == [], "checking a step leaves its Runs list empty"
    assert o["versions"] == ["drafted"] and o["version"] == 1, "a check writes no version"
    assert o["dirty"] == "", "and leaves the draft clean"


def test_switching_on_with_unchecked_steps_offers_check_them_now_and_all_look_right_then_switch_on(box, live):
    live.script(_answer())
    o = _case(box, live, """
        const { r, WID } = await draftAndOpen();
        fire(by(r, 'wf-switch'), 'click'); await quiet();
        const first = replyTo('POST', (u) => u.endsWith('/switch'));
        const refused = { said: sayOf(r), action: sayButton(r) && sayButton(r).textContent,
                          status: first.status, reply: first.reply };
        fire(sayButton(r), 'click'); await quiet();
        const layer = by(r, 'wf-check');
        const listed = { role: layer.getAttribute('role'), lede: by(layer, 'wf-check-lede').textContent,
          rows: all(layer, 'wf-check-step').map((li) => [li.dataset.nodeId, by(li, 'wf-check-label').textContent,
            by(li, 'wf-check-origin').textContent, by(li, 'wf-check-plan').querySelectorAll('li').map((x) => x.textContent)]),
          foot: by(layer, 'wf-check-foot').querySelectorAll('button').map((x) => x.textContent) };
        fire(by(layer, 'wf-check-all'), 'click'); await quiet();
        const after = { lede: by(layer, 'wf-check-lede').textContent,
          said: all(layer, 'wf-check-said').map((p) => p.textContent),
          foot: by(layer, 'wf-check-foot').querySelectorAll('button').map((x) => x.textContent),
          marks: steps(r).filter((n) => n.dataset.unchecked).length };
        fire(by(layer, 'wf-check-switch'), 'click'); await quiet();
        const plans = planOf(replyTo('POST', (u) => u === '/api/workflows'));
        const stored = (await ask('/api/workflows/' + WID)).workflow;
        out({ refused, listed, after, plans, WID, labels: stored.graph.nodes.map((n) => n.label),
              switches: calls('POST', (u) => u.endsWith('/switch')),
              puts: calls('PUT', (u) => u === '/api/workflows/' + WID),
              on: by(r, 'wf-switch').textContent, layerGone: !by(r, 'wf-check'),
              storedOn: stored.trigger_status });
    """)
    rf = o["refused"]
    assert rf["status"] == 409 and rf["reply"]["reason"] == "unchecked" and rf["reply"]["node_ids"] == IDS
    assert rf["said"] == "Not switched on: " + rf["reply"]["detail"], "the server's sentence, as it wrote it"
    assert rf["reply"]["detail"].startswith("The model drafted 3 steps nobody has checked yet:")
    assert rf["action"] == "Check them now"
    assert o["listed"]["role"] == "dialog"
    assert o["listed"]["lede"].startswith("3 steps to check.")  # P23-05 (Doc 2 § 5)
    assert o["listed"]["rows"] == [[i, label, "Drafted by the model", o["plans"][i]]
                                   for i, label in zip(IDS, o["labels"])], \
        "every step the refusal names, with what it would do"
    assert o["listed"]["foot"] == ["All look right", "Close"]
    assert o["puts"] == [[f"/api/workflows/{o['WID']}", {"checked": IDS}]], "one check for the rest"
    assert o["after"]["lede"] == "Every step is checked."
    assert o["after"]["said"] == ["Checked.", "Checked.", "Checked."]
    assert o["after"]["foot"] == ["Switch on", "Close"] and o["after"]["marks"] == 0
    assert o["switches"] == [[f"/api/workflows/{o['WID']}/switch", {"on": True}]] * 2, \
        "refused once, then switched on"
    assert o["on"] == "On" and o["layerGone"] is True and o["storedOn"] == "active"


_HOSTILE = "<img src=x onerror=alert(1)>Summarise"


def test_a_label_a_reason_and_a_line_the_model_wrote_stay_text(box, live):
    live.script(_answer(_HOSTILE, channel="#dev<b>bold</b>",
                        missing=["<img src=x onerror=alert(2)> could not be drafted"]))
    o = _case(box, live, """
        const { r, made } = await draftAndOpen();
        const text = (cls) => all(r, cls).map((x) => x.textContent);
        const missing = text('wf-arrived-text'), where = text('wf-arrived-destinations');
        fire(nodeEl(r, 'summarise'), 'click'); await quiet();
        fire(by(r, 'wf-switch'), 'click'); await quiet();
        fire(sayButton(r), 'click'); await quiet();
        out({ reply: made.reply, title: nodeEl(r, 'summarise').querySelector('.wb-node-title').textContent,
              layer: text('wf-check-label'), missing, where, arrivedGone: !by(r, 'wf-arrived'),
              imgs: r.querySelectorAll('img').length,
              markup: markup(r).filter((m) => m.includes('onerror') || m.includes('<b>')) });
    """)
    reply = o["reply"]
    label = reply["workflow"]["graph"]["nodes"][1]["label"]
    assert "<img" in label and any("<b>bold</b>" in d for d in reply["destinations"]), \
        "the server kept what the model wrote, as data"
    assert o["title"] == label, "the label as the server kept it, as text"
    assert label in o["layer"]
    assert o["missing"] == reply["missing"] and any("<img" in m for m in o["missing"])
    assert o["where"] == ["".join(reply["destinations"])]
    assert o["arrivedGone"] is True, "Check them now takes the arrival box's place"
    assert o["imgs"] == 0 and o["markup"] == [], "nothing the model wrote was ever markup"


def test_a_refused_draft_is_said_in_the_servers_words_and_nothing_opens(box, live):
    from src import workflow_assist as wa

    live.script(wa.NoModelSetUp())
    o = _case(box, live, """
        const { r } = await room();
        fire(by(r, 'wf-shelf-new'), 'click'); await quiet();
        fire(by(r, 'wf-new-draft'), 'click'); await quiet();
        const empty = { said: by(r, 'wf-new-say').textContent, posts: calls('POST').length };
        typed(by(r, 'wf-new-text'), 'summarise my mail every morning');
        fire(by(r, 'wf-new-draft'), 'click'); await quiet();
        const made = replyTo('POST', (u) => u === '/api/workflows');
        out({ empty, status: made.status, detail: made.reply.detail,
              said: by(r, 'wf-new-say').textContent, formOpen: !by(r, 'wf-new').hidden,
              kept: by(r, 'wf-new-text').value, view: by(r, 'wf-view').hidden,
              refusal: by(r, 'wf-new-say')._classes().includes('wf-new-refusal'),
              listed: (await ask('/api/workflows')).workflows.length });
    """)
    assert o["empty"] == {"said": "Say what it should do first: when it starts, and each thing it does.", "posts": 0}
    assert o["status"] == 503 and o["detail"] == wa.NO_MODEL_TO_DRAFT
    assert o["said"] == f"Not drafted: {wa.NO_MODEL_TO_DRAFT}"
    assert o["formOpen"] is True and o["kept"] == "summarise my mail every morning", "nothing typed is lost"
    assert o["view"] is True and o["refusal"] is True
    assert o["listed"] == 0, "nothing was saved"


def test_a_step_changed_in_the_draft_is_the_persons_and_drops_its_mark_before_save(box, live):
    live.script(_answer())
    o = _case(box, live, """
        const { r } = await draftAndOpen();
        fire(nodeEl(r, 'post'), 'click'); await quiet();
        // Done on the MCP step's form with a new label: the step is the person's now.
        const name = r.querySelector('.wf-sf').querySelectorAll('[data-field]').find((x) => x.dataset.field === 'label');
        typed(name, 'Post it to #dev');
        fire(r.querySelector('.wf-step-done'), 'click'); await quiet();
        const marks = steps(r).map((n) => [n.dataset.itemId, n.dataset.unchecked || null]);
        fire(by(r, 'wf-switch'), 'click'); await quiet();
        fire(sayButton(r), 'click'); await quiet();
        const row = all(r, 'wf-check-step').find((li) => li.dataset.nodeId === 'post');
        out({ marks, note: all(row, 'wf-check-note').map((p) => p.textContent),
              layerNote: by(r, 'wf-check').querySelectorAll('.wf-check-note').map((p) => p.textContent)[0] });
    """)
    assert o["marks"] == [["is-it-new", "drafted"], ["summarise", "drafted"], ["post", None]], \
        "a step changed here is the person's, as it will be once saved (the server's _marks_kept)"
    assert o["note"] == ["You changed this step. Save, and it is yours: it needs no check."]
    assert o["layerNote"] == "You have changes that are not saved: this checks the steps as they are saved."


def test_a_step_the_assistant_changed_reads_as_its_and_waits_for_a_person(box, live):
    """`integrate-e` (the integrator's call on `B1117`): a person
    checked every step; the assistant then changed one through the save route
    (its loopback — not a person). That step is marked again, origin
    `assistant`, and the room says so in words — on the canvas, on its banner,
    and in *Check them now* when the switch refuses."""
    import asyncio

    from tests.helpers.assist_harness import ASSISTANT, PERSON
    from tests.helpers.walker_harness import client_for

    live.script(_answer())

    async def draft_check_and_touch():
        async with client_for(live.app) as client:
            made = (await client.post("/api/workflows", headers=PERSON,
                                      json={"describe": _DESCRIBE, "tz": "UTC"})).json()["workflow"]
            wid = made["id"]
            ok = await client.put(f"/api/workflows/{wid}", headers=PERSON, json={"checked": IDS})
            assert ok.status_code == 200, ok.text
            doc = (await client.get(f"/api/workflows/{wid}", headers=PERSON)).json()["workflow"]
            graph = doc["graph"]
            for n in graph["nodes"]:
                n.pop("unchecked", None)
            graph["nodes"][2]["config"]["args"]["channel"] = "#leak"
            saved = await client.put(f"/api/workflows/{wid}", headers=ASSISTANT,
                                     json={"graph": graph, "base_version": doc["version"]})
            assert saved.status_code == 200, saved.text
            return wid
    wid = asyncio.run(draft_check_and_touch())
    o = _case(box, live, f"""
        const {{ r }} = await room({{ workflowId: {as_js(wid)} }});
        const marks = steps(r).map((n) => [n.dataset.itemId, n.dataset.unchecked || null,
          n.querySelectorAll('.wb-node-badge').map((b) => b.textContent)]);
        fire(nodeEl(r, 'post'), 'click'); await quiet();
        const b = by(r, 'wf-step-check');
        const banner = {{ origin: b.dataset.origin, head: by(b, 'wf-step-check-head').textContent,
                          note: by(b, 'wf-step-check-note').textContent }};
        fire(by(r, 'wf-switch'), 'click'); await quiet();
        const refused = sayOf(r);
        fire(sayButton(r), 'click'); await quiet();
        const rows = all(by(r, 'wf-check'), 'wf-check-step').map((li) => [li.dataset.nodeId,
          by(li, 'wf-check-origin').textContent]);
        out({{ marks, banner, refused, rows }});
    """)
    assert o["marks"] == [["is-it-new", None, []], ["summarise", None, []],
                          ["post", "assistant", ["Changed by your assistant — check me"]]]
    assert o["banner"]["origin"] == "assistant"
    assert o["banner"]["head"] == "Changed by your assistant — check it."
    assert o["banner"]["note"].startswith("Your assistant, or something holding an API token, changed this step")
    assert o["refused"].startswith("Not switched on: Your assistant (or an API token) changed 1 step nobody has "
                                   "checked yet: “Post to #dev”.")
    assert o["rows"] == [["post", "Changed by your assistant"]]
