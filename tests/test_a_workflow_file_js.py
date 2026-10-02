# SPDX-License-Identifier: AGPL-3.0-or-later
r"""`P22-24` (wb-canvas-e) — a workflow is a file: *Export* downloads it, *Or open a file…* imports it, and what is missing is said with a door.

The browser half of `SLICE-EF-DESIGN.md` § 2 P22-24 (package B, § 3): *Export*
in the workflow bar downloads C-A's export (`GET …/export`, an attachment) as a
file; *Or open a file…* in the New workflow form reads the file and posts it as
C-A's `{file}`; the import opens switched off with every step marked
("Imported — check me") and the reply's `missing` lines listed, each with its
door — `openWorkbench({ room: 'integrations' })` for an Integration or an MCP
tool, `{ room: 'skills' }` for a skill (C-R, wb-rooms', stubbed here) — and
*Show the step*; each step's `needs` said on its banner and on the field it is
about. The Versions list says the three new version sources in words.

Driven: the real room, canvas, panels, step forms, source and `workflowApi.js`
over the C-A fake server (`tests/helpers/workflow_ca_fake.py`); C-R's door is
the shim's `loadWorkbench` stand-in. The file and the import's reply are
RECORDED from wb-assist's real routes wherever its share is in the tree — the
file exported on an install that has Miniflux and the skill, imported on one
that has neither (the row's Verify) — and are C-A's literal shapes on this
branch alone.
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
from helpers.workflow_ca_fake import ROOM_PREAMBLE, as_js, build_sandbox, palette, recorded_file  # noqa: E402

pytestmark = pytest.mark.skipif(not shutil.which("node"), reason="node binary not on PATH")

_AT = "2026-10-02T09:00:00Z"


def _node(id_, kind, label, config, needs=None, origin="imported"):
    n = {"id": id_, "kind": kind, "label": label, "config": config, "position": None, "pinned": None}
    if origin:
        n["unchecked"] = {"origin": origin, "at": _AT, "needs": needs or []}
    return n


_NEED_MINIFLUX = {"field": "integration", "name": "Miniflux", "preset": "miniflux"}
_NEED_SKILL = {"field": "skill", "name": "print-digest"}


def _imported():
    nodes = [
        _node("fetch-unread", "http", "Fetch unread",
              {"integration": "", "method": "GET", "path": "/v1/entries", "query": [{"name": "status", "value": "unread"}],
               "body": []}, [_NEED_MINIFLUX]),
        _node("summarise", "llm", "Summarise", {"prompt": "Summarise {{ steps.fetch-unread.data.json.entries }}"}),
        _node("print-it", "skill", "Print it", {"skill": "", "prompt": "Print the summary"}, [_NEED_SKILL]),
    ]
    edges = [{"from": "start", "port": "success", "to": "fetch-unread"},
             {"from": "fetch-unread", "port": "success", "to": "summarise"},
             {"from": "summarise", "port": "success", "to": "print-it"}]
    return {"id": "wf7", "name": "Unread digest", "task_id": "t7", "trigger_status": "paused", "version": 1,
            "trigger_task": {"id": "t7", "status": "paused"},
            "graph": {"v": 1, "start": {"position": None}, "nodes": nodes, "edges": edges}}


_MISSING = [
    "“Fetch unread” uses an Integration called “Miniflux” (miniflux). Add it in Integrations, then pick it on the step.",
    "“Summarise” used a model of the Pantheon it came from; it uses your default model here.",
    "“Print it” follows a skill called “print-digest”, which you do not have. Add it, then pick it on the step.",
]
_FILE = {"pantheon_workflow": 1, "name": "Unread digest", "exported_at": _AT, "trigger": {"trigger_type": "schedule"},
         "graph": {"nodes": [], "edges": []},
         "requires": {"integrations": [{"ref": "i9", "name": "Miniflux", "preset": "miniflux"}], "mcp_tools": [],
                      "skills": ["print-digest"], "tasks": [], "workstation": False}}


# The workflow on the install it is exported from (Miniflux and the skill there).
_GRAPH1 = {"v": 1, "nodes": [
    {"id": "fetch-unread", "kind": "http", "label": "Fetch unread", "position": None, "pinned": None,
     "config": {"integration": "intg-miniflux", "method": "GET", "path": "/v1/entries",
                "query": [{"name": "status", "value": "unread"}]}},
    {"id": "summarise", "kind": "llm", "label": "Summarise", "position": None, "pinned": None,
     "config": {"prompt": "Summarise {{ steps.fetch-unread.data.entries }}"}},
    {"id": "print-it", "kind": "skill", "label": "Print it", "position": None, "pinned": None,
     "config": {"skill": "print-digest", "prompt": "Print the summary"}}],
    "edges": [{"from": "fetch-unread", "port": "success", "to": "summarise"},
              {"from": "summarise", "port": "success", "to": "print-it"}]}
_LITERAL = {"file": _FILE, "filename": "unread-digest.workflow.json", "export_text": json.dumps(_FILE),
            "import_reply": {"workflow": _imported(), "notes": ["Imported “Unread digest”: 3 steps, switched off."],
                             "missing": _MISSING, "destinations": ["Would call Miniflux — GET /v1/entries"]}}


@pytest.fixture(scope="module")
def rec(tmp_path_factory):
    return recorded_file(tmp_path_factory.mktemp("share"), name="Unread digest", graph=_GRAPH1, skill="print-digest",
                         literal=_LITERAL)


def _world(rec, pal=None):
    p = pal or palette()
    p["integrations"] = []          # this Pantheon has no Miniflux
    return (
        f"cw.palette = {as_js(p)};\n"
        f"const REC = {as_js(rec)};\n"
        "const FILE = REC.file;\n"
        "ca.importFile = () => ({ status: 200, body: JSON.parse(JSON.stringify(REC.import_reply)) });\n"
        "const pick = (input, name, text) => { input.files = [{ name, size: text.length, text: async () => text }];\n"
        "  input.dispatchEvent({ type: 'change', target: input }); };\n"
        "const openFile = async (text = JSON.stringify(FILE)) => {\n"
        "  const { r, handle } = await room();\n"
        "  fire(by(r, 'wf-shelf-new'), 'click'); await settle(10);\n"
        "  fire(by(r, 'wf-new-file'), 'click');\n"
        "  pick(by(r, 'wf-new-file-input'), 'unread-digest.workflow.json', text); await settle(40);\n"
        "  return { r, handle };\n"
        "};\n"
        "const SAVED = { id: 'wf1', name: 'Unread digest', task_id: 't1', trigger_status: 'active', version: 4,\n"
        "  trigger_task: { id: 't1', status: 'active' }, graph: { v: 1, start: { position: null }, nodes: [\n"
        "    { id: 'summarise', kind: 'llm', label: 'Summarise', config: { prompt: 'x' }, position: null, pinned: null }],\n"
        "    edges: [{ from: 'start', port: 'success', to: 'summarise' }] } };\n"
    )


@pytest.fixture(scope="module")
def box(tmp_path_factory):
    return build_sandbox(tmp_path_factory.mktemp("wffile"), _CANVAS_SHIM)


def _case(box, rec, script):
    return _run(box, ROOM_PREAMBLE + _world(rec), script)


def test_export_downloads_the_saved_workflow_as_a_file(box, rec):
    o = _case(box, rec, """
        seed(SAVED);
        ca.exportBody = JSON.parse(REC.export_text);
        ca.exportName = REC.filename;
        const { r } = await room({ workflowId: 'wf1' });
        const offered = !by(r, 'wf-export').hidden;
        fire(by(r, 'wf-export'), 'click'); await settle(30);
        const clean = { said: sayOf(r), clicked: downloads.clicked.slice(), made: downloads.made.length,
          revoked: downloads.revoked.length === 1 && downloads.revoked[0] === downloads.made[0].url,
          bytes: await downloads.made[0].blob.text(), left: document.body.querySelectorAll('a').length };
        typed(by(r, 'wf-name'), 'Unread digest, renamed');
        fire(by(r, 'wf-export'), 'click'); await settle(30);
        out({ offered, clean, gets: calls('GET', (u) => u.endsWith('/export')), dirtySaid: sayOf(r) });
    """)
    assert o["offered"] is True
    assert o["gets"] == [["/api/workflows/wf1/export", None]] * 2
    c = o["clean"]
    assert len(c["clicked"]) == 1 and c["clicked"][0]["tag"] == "A"
    assert c["clicked"][0]["download"] == rec["filename"] and rec["filename"].endswith(".json"), \
        "the file is named as the server names it"
    assert c["clicked"][0]["href"].startswith("blob:")
    assert c["made"] == 1 and c["revoked"] is True and c["left"] == 0, "the object URL is taken back and the link removed"
    assert json.loads(c["bytes"]) == json.loads(rec["export_text"]), "the file is the server's bytes, as they came"
    assert rec["file"]["pantheon_workflow"] == 1
    assert c["said"] == (f"Downloaded “{rec['filename']}”. It holds the saved steps and the names of what they "
                         "use; keys, tokens, addresses and pinned samples are left out.")
    assert o["dirtySaid"].endswith("Your unsaved changes are not in it.")


def test_an_export_the_server_refuses_is_said_in_its_words_and_nothing_downloads(box, rec):
    o = _case(box, rec, """
        seed(SAVED);
        ca.exportRefusal = { status: 400, detail: '“Call the API” has what looks like a key in its header “X-Auth-Token”. Take it out of the step, then export.' };
        const { r } = await room({ workflowId: 'wf1' });
        fire(by(r, 'wf-export'), 'click'); await settle(30);
        out({ said: sayOf(r), clicked: downloads.clicked.length });
    """)
    assert o["said"] == ("Not exported: “Call the API” has what looks like a key in its header “X-Auth-Token”. Take it out "
                         "of the step, then export.")
    assert o["clicked"] == 0


def test_open_a_file_posts_it_and_the_import_opens_off_marked_with_what_is_missing_and_its_doors(box, rec):
    o = _case(box, rec, """
        const { r } = await openFile();
        const said = sayOf(r);
        const arrived = by(r, 'wf-arrived');
        const lines = all(arrived, 'wf-arrived-line').map((li) => [by(li, 'wf-arrived-text').textContent,
          li.dataset.nodeId || null, li.querySelectorAll('button').map((b) => [b.textContent, b.dataset.room || null])]);
        const lineOf = (word) => all(arrived, 'wf-arrived-line').find((li) => by(li, 'wf-arrived-text').textContent.includes(word));
        const mcpLine = lineOf('Miniflux');
        fire(mcpLine.querySelector('.wf-arrived-door'), 'click'); await settle(10);
        fire(lineOf('print-digest').querySelector('.wf-arrived-door'), 'click'); await settle(10);
        const marks = steps(r).map((n) => [n.dataset.itemId, n.dataset.unchecked || null,
          n.querySelectorAll('.wb-node-badge').map((b) => b.textContent)]);
        fire(mcpLine.querySelector('.wf-arrived-show'), 'click'); await settle(30);
        const panel = r.querySelector('.wf-edit').querySelector('.wb-panel');
        const banner = by(panel, 'wf-step-check');
        const onField = panel.querySelectorAll('.wf-sf-need').map((p) => [p.dataset.field,
          by(p, 'wf-sf-need-text').textContent, (by(p, 'wf-sf-need-door') || {}).textContent || null]);
        fire(by(panel, 'wf-sf-need-door'), 'click'); await settle(10);
        out({ posts: calls('POST', (u) => u === '/api/workflows'), switchWord: by(r, 'wf-switch').textContent,
              head: by(arrived, 'wf-arrived-head').textContent, subs: all(arrived, 'wf-arrived-sub').map((p) => p.textContent),
              lines, marks, doors: doors.opened, title: panel.querySelector('.wb-panel-title').textContent,
              banner: { head: by(banner, 'wf-step-check-head').textContent,
                        needs: all(banner, 'wf-step-check-need-text').map((s) => s.textContent),
                        doors: all(banner, 'wf-step-check-need-door').map((b) => b.textContent) },
              onField, said });
    """)
    reply = rec["import_reply"]
    assert o["posts"] == [["/api/workflows", {"file": rec["file"]}]], "the file's JSON, as C-A's {file}"
    assert o["switchWord"] == "Off"
    assert o["head"] == "Imported from a file"
    assert o["subs"] == (["Where it sends things:"] if reply["destinations"] else []) + ["What this Pantheon is missing:"]
    assert [line[0] for line in o["lines"]] == reply["missing"], "each missing line, as the server wrote it"
    for text, node, doors in o["lines"]:
        if "Miniflux" in text:
            assert (node, doors) == ("fetch-unread", [["Open MCP & Integrations", "integrations"], ["Show the step", None]])
        elif "print-digest" in text:
            assert (node, doors) == ("print-it", [["Open Skills", "skills"], ["Show the step", None]])
        else:
            assert (node, doors) == (None, []), "a line that names no need has no door"
    assert sum("Miniflux" in t or "print-digest" in t for t, _, _ in o["lines"]) == 2
    assert o["doors"][:2] == [{"room": "integrations"}, {"room": "skills"}], "C-R: openWorkbench({ room })"
    assert o["marks"] == [["fetch-unread", "imported", ["Imported — check me"]],
                          ["summarise", "imported", ["Imported — check me"]],
                          ["print-it", "imported", ["Imported — check me"]]]
    assert o["title"] == "Fetch unread", "Show the step opens it"
    assert o["banner"]["head"] == "Imported from a file — check it."
    assert o["banner"]["needs"] == ["It uses an Integration called “Miniflux” (miniflux), which this Pantheon does not "
                                    "have. Add it in MCP & Integrations, then pick it on the step."]
    assert o["banner"]["doors"] == ["Open MCP & Integrations"]
    assert o["onField"] == [["integration", "It uses an Integration called “Miniflux” (miniflux), which this Pantheon does "
                             "not have. Add it in MCP & Integrations, then pick it here.", "Open MCP & Integrations"]], \
        "said on the field it is about"
    assert o["doors"][2:] == [{"room": "integrations"}]
    assert o["said"] == " ".join(reply["notes"]), "the server's notes, said once it is drawn"


def test_a_file_that_is_not_json_is_said_and_nothing_is_sent_and_a_refused_one_in_the_servers_words(box, rec):
    o = _case(box, rec, """
        const { r } = await openFile('this is not { json');
        const notJson = { said: by(r, 'wf-new-say').textContent, posts: calls('POST', (u) => u === '/api/workflows').length,
          open: !by(r, 'wf-new').hidden };
        ca.importFile = () => ({ status: 400, body: { detail: 'This file is from a newer Pantheon (pantheon_workflow 2). Nothing was made.' } });
        pick(by(r, 'wf-new-file-input'), 'next.workflow.json', JSON.stringify({ ...FILE, pantheon_workflow: 2 })); await settle(30);
        out({ notJson, refused: by(r, 'wf-new-say').textContent, view: by(r, 'wf-view').hidden });
    """)
    assert o["notJson"] == {"said": "“unread-digest.workflow.json” is not a workflow file: it is not JSON. Nothing was made.",
                            "posts": 0, "open": True}
    assert o["refused"] == "Not imported: This file is from a newer Pantheon (pantheon_workflow 2). Nothing was made."
    assert o["view"] is True


def test_the_versions_list_says_the_three_new_sources_in_words(box, rec):
    o = _case(box, rec, """
        seed(SAVED);
        ca.versions = ['fixed', 'imported', 'drafted', 'restored', 'converted', 'user'].map((source, i) => ({
          version: 6 - i, name: 'Unread digest', saved_at: '2026-10-02T06:00:00Z', source, step_count: 1, current: i === 0 }));
        const { r } = await room({ workflowId: 'wf1' });
        fire(by(r, 'wf-versions'), 'click'); await settle(20);
        out({ words: all(r, 'wf-versions-what').map((s) => s.textContent.split(' · ')[3]) });
    """)
    assert o["words"] == ["a fix you applied", "imported from a file", "drafted by the model",
                          "an older version put back", "made from a chain", "saved"]


def test_an_mcp_step_with_no_tool_here_names_the_room_and_its_door_opens_it(box, rec):
    """The MCP step's form said "Add a server in Settings → MCP" — a place that
    does not exist (design § 0.6: MCP servers are a card of Integrations, the
    Workbench's MCP & Integrations room since `P22-21`). It names the room and
    opens it, as an imported step's need does."""
    o = _case(box, rec, """
        cw.palette.mcp_tools = [];
        seed({ ...SAVED, graph: { v: 1, start: { position: null }, nodes: [
          { id: 'post', kind: 'mcp', label: 'Post it', config: { tool: '', args: {} }, position: null, pinned: null }],
          edges: [{ from: 'start', port: 'success', to: 'post' }] } });
        const { r } = await room({ workflowId: 'wf1' });
        fire(nodeEl(r, 'post'), 'click'); await settle(30);
        const warn = r.querySelector('.wf-sf-warn');
        fire(warn.querySelector('.wf-sf-door'), 'click'); await settle(10);
        out({ words: warn.textContent, door: warn.querySelector('.wf-sf-door').textContent, doors: doors.opened });
    """)
    assert o["words"] == "No MCP tool is available. Add a server in MCP & Integrations, then pick its tool here.Open MCP & Integrations"
    assert o["door"] == "Open MCP & Integrations"
    assert o["doors"] == [{"room": "integrations"}]


def test_every_kind_of_need_an_import_writes_is_said_in_words_with_a_door_only_where_there_is_a_room(box, rec):
    """wb-assist's `import_file` writes a need per kind of thing a file may
    refer to — an Integration, an MCP tool, a skill, a task, a header's value,
    an AI step's tool, the workstation — and a For-each's inner step's as
    `step.config.<field>`. Each is said in words; only an Integration, a tool
    and a skill have a room to add them in."""
    o = _case(box, rec, """
        const mark = (needs) => ({ origin: 'imported', at: '2026-10-02T09:00:00Z', needs });
        const n = (id, kind, label, config, needs) => ({ id, kind, label, config, position: null, pinned: null, unchecked: mark(needs) });
        seed({ ...SAVED, graph: { v: 1, start: { position: null }, nodes: [
          n('call', 'http', 'Call it', { integration: '', method: 'GET', path: '/x', headers: [{ name: 'X-Auth-Token', value: '' }] },
            [{ field: 'headers[0].value', name: 'X-Auth-Token' }]),
          n('each', 'foreach', 'Each one', { list: '{{ steps.call.data.items }}', on_error: 'stop',
            step: { kind: 'http', label: 'Fetch', config: { integration: '', method: 'GET', path: '/y' } } },
            [{ field: 'step.config.integration', name: 'Miniflux', preset: 'miniflux' }]),
          n('ask', 'llm', 'Ask', { prompt: 'x', tools: ['web_fetch'] }, [{ field: 'tools', name: 'web_fetch' }]),
          n('tally', 'code', 'Tally', { language: 'python', source: 'print(1)' }, [{ field: 'language', name: 'workstation' }]),
          n('post', 'mcp', 'Post', { tool: '', args: {} }, [{ field: 'tool', name: 'Chat · send_message', server: 'Chat', tool: 'send_message' }]),
          n('run', 'run_task', 'Run it', { task_id: '__missing__' }, [{ field: 'task_id', name: 'Nightly backup' }])],
          edges: [] } });
        const { r } = await room({ workflowId: 'wf1' });
        const seen = {};
        for (const id of ['call', 'each', 'ask', 'tally', 'post', 'run']) {
          fire(nodeEl(r, id), 'click'); await settle(30);
          const b = by(r, 'wf-step-check');
          seen[id] = { words: all(b, 'wf-step-check-need-text').map((x) => x.textContent),
                       doors: all(b, 'wf-step-check-need-door').map((x) => x.dataset.room),
                       top: all(r, 'wf-sf-need').map((x) => [x.dataset.field || null, x.parentNode.className]) };
        }
        out(seen);
    """)
    assert o["call"]["words"] == ["It sends the header “X-Auth-Token”, and a file never carries its value. Type it on the step."]
    assert o["call"]["doors"] == []
    assert o["each"]["words"] == ["It uses an Integration called “Miniflux” (miniflux), which this Pantheon does not have. "
                                  "Add it in MCP & Integrations, then pick it on the step."]
    assert o["each"]["doors"] == ["integrations"]
    assert o["each"]["top"] == [[None, "wf-sf-problems"]], "an inner step's need is said at the top of the For-each's form"
    assert o["ask"]["words"] == ["It may use the tool “web_fetch”, which you cannot use here. Change its tools on the step."]
    assert o["tally"]["words"] == ["It runs code in your workstation, which cannot run it now."]
    assert o["post"]["words"] == ["It uses the tool “send_message” of an MCP server called “Chat”, which this Pantheon "
                                  "does not have. Add the server in MCP & Integrations, then pick the tool on the step."]
    assert o["post"]["doors"] == ["integrations"]
    assert o["run"]["words"] == ["It ran a task called “Nightly backup” on the Pantheon it came from. Pick the task it "
                                 "runs on the step."]
    assert all(o[k]["doors"] == [] for k in ("call", "ask", "tally", "run")), "no room to add these in"


def test_a_step_that_cannot_be_planned_yet_says_why_not_that_the_plan_missed_it(box, rec):
    """Measured in Chromium on the merged tree: an imported workflow whose
    Integration is missing is not planned at all — the dry run records no step
    and its run carries the engine's reason — and the banner said "The plan did
    not reach this step". It says the reason."""
    o = _case(box, rec, """
        const doc = JSON.parse(JSON.stringify(REC.import_reply.workflow));
        doc.id = 'wf1'; doc.task_id = 't1';
        seed(doc);
        ca.dryNodes = {};
        // The dry run's reply: no step entries, and the run's reason.
        ca.dryReason = '“Fetch unread” uses an Integration this Pantheon does not have.';
        const { r } = await room({ workflowId: 'wf1' });
        fire(nodeEl(r, 'fetch-unread'), 'click'); await settle(40);
        out({ plan: by(r, 'wf-step-check').querySelector('.wf-step-check-plan').querySelectorAll('li').map((x) => x.textContent) });
    """)
    assert o["plan"] == ["It cannot be planned yet: “Fetch unread” uses an Integration this Pantheon does not have."]
