# SPDX-License-Identifier: AGPL-3.0-or-later
r"""`P22-24` (wb-canvas-e) — a workflow is a file: *Export* downloads it, *Or open a file…* imports it, and what is missing is said with a door.

The browser half of `SLICE-EF-DESIGN.md` § 2 P22-24 (package B, § 3): *Export*
in the workflow bar downloads C-A's export (`GET …/export`, an attachment) as a
file; *Or open a file…* in the New workflow form reads the file and posts it as
C-A's `{file}`; the import opens switched off with every step marked
("Imported — check me") and the reply's `missing` lines listed, each with its
door — `openWorkbench({ room: 'integrations' })` for an Integration or an MCP
tool, `{ room: 'skills' }` for a skill (C-R) — and *Show the step*; each step's
`needs` said on its banner and on the field it is about. The Versions list says
the three new version sources in words.

Driven end to end (`integrate-e`): the real room in node against wb-assist's
REAL server on a loopback port (`tests/helpers/workflow_live.py`). The file is
exported by the real route on an install that has Miniflux and the skill, and
imported by the real route on another that has neither (the row's Verify); a
file a stranger wrote by hand (one need of every kind) is imported the same
way. C-R's door is the room's `loadWorkbench`, recorded here and driven for
real in Chromium. Before the merge these cases ran over a JavaScript stand-in
for the routes (`workflow_ca_fake.py`, deleted — `Law 20`).
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

POST = "mcp__chat__send_message"
ISSUES = {"id": "intg-issues", "name": "Issues", "enabled": True, "base_url": "http://issues.lan:8080",
          "auth_type": "none", "api_key": "", "auth_header": "", "auth_param": "", "description": "Issues",
          "preset": ""}

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


class ToggleChat:
    """The chat server's far end, whose one tool can be taken away — as an
    admin removing the server after a step was saved against it."""

    def __init__(self):
        from tests.helpers.assist_harness import Chat
        self.inner, self.on = Chat(), True
        self.posted = self.inner.posted

    def get_all_tools(self, *a, **k):
        return self.inner.get_all_tools(*a, **k) if self.on else []

    async def call_tool(self, name, args):
        return await self.inner.call_tool(name, args)


class NoChat(ToggleChat):
    def __init__(self):
        super().__init__()
        self.on = False


def _client_calls(w, steps):
    """Run `steps(call)` through the real routes as alice; `call(method, path,
    **kw)` answers the JSON of a 200 (and fails the test otherwise)."""
    from tests.helpers.assist_harness import PERSON
    from tests.helpers.walker_harness import client_for

    async def go():
        async with client_for(w.app) as client:
            async def call(method, path, *, raw=False, **kw):
                res = await client.request(method, path, headers=PERSON, **kw)
                assert res.status_code == 200, (path, res.status_code, res.text)
                return res if raw else res.json()
            return await steps(call)

    return asyncio.run(go())


def _make(w, name, graph):
    async def steps(call):
        made = await call("POST", "/api/workflows", json={"name": name})
        wid = made["workflow"]["id"]
        await call("PUT", f"/api/workflows/{wid}", json={"graph": graph, "base_version": 1})
        return wid
    return _client_calls(w, steps)


def _exported_from_one(monkeypatch, tmp_path):
    """The file, exported by the real route on an install with Miniflux and the
    skill: `(file, its bytes, the name Content-Disposition gives)`."""
    import re

    from tests.helpers.assist_harness import build_world, miniflux

    (tmp_path / "one").mkdir(exist_ok=True)
    one = build_world(monkeypatch, tmp_path / "one", integrations=[miniflux()],
                      skills=[("print-digest", "Print the digest.")], name="one.db")
    wid = _make(one, "Unread digest", _GRAPH1)

    async def steps(call):
        res = await call("GET", f"/api/workflows/{wid}/export", raw=True)
        said = res.headers.get("content-disposition") or ""
        return res.text, re.search(r'filename="?([^";]+)"?', said).group(1)
    text, filename = _client_calls(one, steps)
    return json.loads(text), text, filename


@pytest.fixture(scope="module")
def box(tmp_path_factory):
    return build_sandbox(tmp_path_factory.mktemp("wffile"), _CANVAS_SHIM)


def _serve(w):
    w.server = LiveServer(w.app)
    return w


@pytest.fixture()
def one(monkeypatch, tmp_path):
    """The install the file is exported from, served."""
    from tests.helpers.assist_harness import build_world, miniflux

    w = _serve(build_world(monkeypatch, tmp_path, integrations=[miniflux()],
                           skills=[("print-digest", "Print the digest.")]))
    try:
        yield w
    finally:
        w.server.close()


@pytest.fixture()
def two(monkeypatch, tmp_path):
    """The install the file is imported on — no Miniflux, no skill, no MCP
    tool, the workstation off — served, with the file install one exported."""
    from tests.helpers.assist_harness import build_world, script_model

    file, text, filename = _exported_from_one(monkeypatch, tmp_path)
    (tmp_path / "two").mkdir(exist_ok=True)
    w = build_world(monkeypatch, tmp_path / "two", integrations=[ISSUES], chat=NoChat(), name="two.db")
    w.file, w.export_text, w.filename = file, text, filename
    w.script = lambda *answers: script_model(monkeypatch, *answers)
    _serve(w)
    try:
        yield w
    finally:
        w.server.close()


_HELPERS = (
    "const pick = (input, name, text) => { input.files = [{ name, size: text.length, text: async () => text }];\n"
    "  input.dispatchEvent({ type: 'change', target: input }); };\n"
    "const openFile = async (text) => {\n"
    "  const { r, handle } = await room();\n"
    "  fire(by(r, 'wf-shelf-new'), 'click'); await quiet();\n"
    "  fire(by(r, 'wf-new-file'), 'click');\n"
    "  pick(by(r, 'wf-new-file-input'), 'unread-digest.workflow.json', text); await quiet();\n"
    "  return { r, handle };\n"
    "};\n"
)


def _case(box, w, script, **consts):
    head = "".join(f"const {k} = {as_js(v)};\n" for k, v in consts.items())
    return _run(box, LIVE_PREAMBLE(w.server.base) + _HELPERS + head, script)


def test_export_downloads_the_saved_workflow_as_a_file(box, one):
    wid = _make(one, "Unread digest", _GRAPH1)
    o = _case(box, one, """
        const { r } = await room({ workflowId: WID });
        const offered = !by(r, 'wf-export').hidden;
        fire(by(r, 'wf-export'), 'click'); await quiet();
        const got = replyTo('GET', (u) => u.endsWith('/export'));
        const clean = { said: sayOf(r), clicked: downloads.clicked.slice(), made: downloads.made.length,
          revoked: downloads.revoked.length === 1 && downloads.revoked[0] === downloads.made[0].url,
          bytes: await downloads.made[0].blob.text(), left: document.body.querySelectorAll('a').length };
        typed(by(r, 'wf-name'), 'Unread digest, renamed');
        fire(by(r, 'wf-export'), 'click'); await quiet();
        out({ offered, clean, served: got.reply, gets: calls('GET', (u) => u.endsWith('/export')), dirtySaid: sayOf(r) });
    """, WID=wid)
    assert o["offered"] is True
    assert o["gets"] == [[f"/api/workflows/{wid}/export", None]] * 2
    c = o["clean"]
    assert len(c["clicked"]) == 1 and c["clicked"][0]["tag"] == "A"
    name = c["clicked"][0]["download"]
    assert name.endswith(".workflow.json") and name.startswith("unread-digest"), "the file is named as the server names it"
    assert c["clicked"][0]["href"].startswith("blob:")
    assert c["made"] == 1 and c["revoked"] is True and c["left"] == 0, "the object URL is taken back and the link removed"
    assert json.loads(c["bytes"]) == o["served"], "the file is the server's bytes, as they came"
    assert o["served"]["pantheon_workflow"] == 1
    assert "sekret-api-key-123" not in c["bytes"] and "miniflux.lan" not in c["bytes"]
    assert c["said"] == (f"Downloaded “{name}”. It holds the saved steps and the names of what they "
                         "use; keys, tokens, addresses and pinned samples are left out.")
    assert o["dirtySaid"].endswith("Your unsaved changes are not in it.")


def test_an_export_the_server_refuses_is_said_in_its_words_and_nothing_downloads(box, one):
    wid = _make(one, "Call the API", {"v": 1, "nodes": [
        {"id": "ask", "kind": "llm", "label": "Call the API",
         "config": {"prompt": "Use the key sk-live_abcdefgh12345678 to list the invoices."}}], "edges": []})
    o = _case(box, one, """
        const { r } = await room({ workflowId: WID });
        fire(by(r, 'wf-export'), 'click'); await quiet();
        const got = replyTo('GET', (u) => u.endsWith('/export'));
        out({ said: sayOf(r), clicked: downloads.clicked.length, status: got.status, reply: got.reply });
    """, WID=wid)
    assert o["status"] == 400 and o["reply"]["reason"] == "secret_shape"
    assert o["said"] == "Not exported: " + o["reply"]["detail"]
    assert "looks like a key or a token" in o["said"]
    assert o["clicked"] == 0


def test_open_a_file_posts_it_and_the_import_opens_off_marked_with_what_is_missing_and_its_doors(box, two):
    o = _case(box, two, """
        const { r } = await openFile(TEXT);
        const made = replyTo('POST', (u) => u === '/api/workflows');
        const said = sayOf(r);
        const arrived = by(r, 'wf-arrived');
        const lines = all(arrived, 'wf-arrived-line').map((li) => [by(li, 'wf-arrived-text').textContent,
          li.dataset.nodeId || null, li.querySelectorAll('button').map((b) => [b.textContent, b.dataset.room || null])]);
        const lineOf = (word) => all(arrived, 'wf-arrived-line').find((li) => by(li, 'wf-arrived-text').textContent.includes(word));
        const mcpLine = lineOf('Miniflux');
        fire(mcpLine.querySelector('.wf-arrived-door'), 'click'); await quiet();
        fire(lineOf('print-digest').querySelector('.wf-arrived-door'), 'click'); await quiet();
        const marks = steps(r).map((n) => [n.dataset.itemId, n.dataset.unchecked || null,
          n.querySelectorAll('.wb-node-badge').map((b) => b.textContent)]);
        fire(mcpLine.querySelector('.wf-arrived-show'), 'click'); await quiet();
        const panel = r.querySelector('.wf-edit').querySelector('.wb-panel');
        const banner = by(panel, 'wf-step-check');
        const onField = panel.querySelectorAll('.wf-sf-need').map((p) => [p.dataset.field,
          by(p, 'wf-sf-need-text').textContent, (by(p, 'wf-sf-need-door') || {}).textContent || null]);
        fire(by(panel, 'wf-sf-need-door'), 'click'); await quiet();
        out({ posts: calls('POST', (u) => u === '/api/workflows'), status: made.status, reply: made.reply,
              switchWord: by(r, 'wf-switch').textContent,
              head: by(arrived, 'wf-arrived-head').textContent, subs: all(arrived, 'wf-arrived-sub').map((p) => p.textContent),
              lines, marks, doors: doors.opened, title: panel.querySelector('.wb-panel-title').textContent,
              banner: { head: by(banner, 'wf-step-check-head').textContent,
                        needs: all(banner, 'wf-step-check-need-text').map((s) => s.textContent),
                        doors: all(banner, 'wf-step-check-need-door').map((b) => b.textContent) },
              onField, said });
    """, TEXT=two.export_text)
    assert o["status"] == 200, o["reply"]
    reply = o["reply"]
    assert o["posts"] == [["/api/workflows", {"file": two.file}]], "the file's JSON, as C-A's {file}"
    assert o["switchWord"] == "Off" and reply["workflow"]["trigger_status"] == "paused"
    assert o["head"] == "Imported from a file"
    assert o["subs"] == (["Where it sends things:"] if reply["destinations"] else []) + ["What this Pantheon is missing:"]
    assert [line[0] for line in o["lines"]] == reply["missing"], "each missing line, as the server wrote it"
    assert reply["missing"][0] == ("“Fetch unread” uses an Integration called “Miniflux” (miniflux). Add it in "
                                   "MCP & Integrations, then pick it on the step."), \
        "the server's line names the room its door opens (`B1135`)"
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


def test_a_file_that_is_not_json_is_said_and_nothing_is_sent_and_a_refused_one_in_the_servers_words(box, two):
    o = _case(box, two, """
        const { r } = await openFile('this is not { json');
        const notJson = { said: by(r, 'wf-new-say').textContent, posts: calls('POST', (u) => u === '/api/workflows').length,
          open: !by(r, 'wf-new').hidden };
        pick(by(r, 'wf-new-file-input'), 'next.workflow.json', JSON.stringify({ ...FILE, pantheon_workflow: 2 })); await quiet();
        const made = replyTo('POST', (u) => u === '/api/workflows');
        out({ notJson, status: made.status, detail: made.reply.detail, refused: by(r, 'wf-new-say').textContent,
              view: by(r, 'wf-view').hidden, listed: (await ask('/api/workflows')).workflows.length });
    """, FILE=two.file)
    assert o["notJson"] == {"said": "“unread-digest.workflow.json” is not a workflow file: it is not JSON. Nothing was made.",
                            "posts": 0, "open": True}
    assert o["status"] == 400
    assert o["refused"] == "Not imported: " + o["detail"]
    assert o["view"] is True and o["listed"] == 0, "nothing was made"


def test_the_versions_list_says_the_three_new_sources_in_words(box, two):
    """Each new source made by its own real door — a draft (`drafted`), the
    file (`imported`), a person's save (`user`), *Apply* (`fixed`), *Undo*
    (`restored`) — and read back through the Versions list."""
    from tests.helpers.assist_harness import PERSON, miniflux
    from tests.helpers.walker_harness import client_for

    two.script({"name": "Drafted one", "trigger": {"type": "schedule"},
                "steps": [{"id": "ask", "kind": "llm", "label": "Ask", "config": {"prompt": "Say hi."}}],
                "arrows": [], "missing": []})

    async def make():
        async with client_for(two.app) as client:
            async def call(method, path, **kw):
                res = await client.request(method, path, headers=PERSON, **kw)
                assert res.status_code == 200, (path, res.status_code, res.text)
                return res.json()
            drafted = (await call("POST", "/api/workflows", json={"describe": "Say hi every morning."}))["workflow"]
            doc = (await call("POST", "/api/workflows", json={"file": two.file}))["workflow"]
            wid = doc["id"]
            # The person adds Miniflux here and picks it on the step, takes out
            # the step whose skill they do not have, and saves.
            two.integrations.append(miniflux())
            graph = doc["graph"]
            graph["nodes"] = [n for n in graph["nodes"] if n["id"] != "print-it"]
            graph["edges"] = [e for e in graph["edges"] if e["to"] != "print-it"]
            for n in graph["nodes"]:
                n.pop("unchecked", None)
            next(n for n in graph["nodes"] if n["id"] == "fetch-unread")["config"]["integration"] = "intg-miniflux"
            summarise = next(n for n in graph["nodes"] if n["id"] == "summarise")
            summarise["config"]["prompt"] = "Summarise them briefly."
            await call("PUT", f"/api/workflows/{wid}", json={"graph": graph, "base_version": 1})
            fixed = dict(summarise["config"], prompt="Summarise them in one line.")
            await call("POST", f"/api/workflows/{wid}/nodes/summarise/fix",
                       json={"base_version": 2, "config": fixed})
            await call("POST", f"/api/workflows/{wid}/versions/2/restore", json={"base_version": 3})
            return drafted["id"], wid
    drafted_id, wid = asyncio.run(make())
    o = _case(box, two, """
        const words = async (id) => {
          const { r } = await room({ workflowId: id });
          fire(by(r, 'wf-versions'), 'click'); await quiet();
          return all(r, 'wf-versions-what').map((s) => s.textContent.split(' · ')[3]);
        };
        out({ imported: await words(WID), drafted: await words(DRAFTED) });
    """, WID=wid, DRAFTED=drafted_id)
    assert o["imported"] == ["an older version put back", "a fix you applied", "saved", "imported from a file"]
    assert o["drafted"] == ["drafted by the model"]


def test_a_step_with_nothing_to_pick_names_the_room_and_its_door_opens_it(box, monkeypatch, tmp_path):
    """The MCP step's form said "Add a server in Settings → MCP" — a place that
    does not exist (design § 0.6) — and the HTTP step's "Add one in Settings →
    Integrations" (`B1126`). Both name the room, and both open it
    (`integrate-e` gave the HTTP hint the door the MCP hint had). The steps were
    saved while the server and the Integration existed; an admin removed them."""
    from tests.helpers.assist_harness import build_world, miniflux

    chat = ToggleChat()
    w = build_world(monkeypatch, tmp_path, integrations=[miniflux()], chat=chat)
    wid = _make(w, "Post the feed", {"v": 1, "nodes": [
        {"id": "fetch", "kind": "http", "label": "Fetch it",
         "config": {"integration": "intg-miniflux", "method": "GET", "path": "/v1/entries"}},
        {"id": "post", "kind": "mcp", "label": "Post it",
         "config": {"tool": POST, "args": {"channel": "#dev", "text": "{{ steps.fetch.text }}"}}}],
        "edges": [{"from": "fetch", "port": "success", "to": "post"}]})
    chat.on = False
    w.integrations.clear()
    _serve(w)
    try:
        o = _case(box, w, """
            const { r } = await room({ workflowId: WID });
            const hint = async (id) => {
              fire(nodeEl(r, id), 'click'); await quiet();
              const warns = r.querySelectorAll('.wf-sf-warn');
              const warn = warns.find((x) => x.querySelector('.wf-sf-door'));
              if (!warn) return { all: warns.map((x) => x.textContent) };
              fire(warn.querySelector('.wf-sf-door'), 'click'); await quiet();
              return { words: warn.querySelector('span').textContent, door: warn.querySelector('.wf-sf-door').textContent };
            };
            out({ mcp: await hint('post'), http: await hint('fetch'), doors: doors.opened,
                  palette: replyTo('GET', (u) => u === '/api/workflows/palette').reply });
        """, WID=wid)
    finally:
        w.server.close()
    assert o["palette"]["mcp_tools"] == [] and o["palette"]["integrations"] == []
    assert o["mcp"] == {"words": "No MCP tool is available. Add a server in MCP & Integrations, then pick its tool here.",
                        "door": "Open MCP & Integrations"}
    assert o["http"] == {"words": "No integration is set up yet. Add one in MCP & Integrations, then pick it here.",
                         "door": "Open MCP & Integrations"}
    assert o["doors"] == [{"room": "integrations"}, {"room": "integrations"}]


# A file someone wrote by hand, referring to one thing of every kind this
# install lacks (and to one it has, "Issues", which is rebound by name).
_EVERY_NEED = {"pantheon_workflow": 1, "name": "Every need", "exported_at": "2026-10-02T09:00:00Z",
               "trigger": {"trigger_type": "schedule", "schedule": "daily", "time": "09:00"},
               "graph": {"v": 1, "nodes": [
                   {"id": "call", "kind": "http", "label": "Call it",
                    "config": {"integration": "i-issues", "method": "GET", "path": "/x",
                               "headers": [{"name": "X-Auth-Token", "value": ""}]}},
                   {"id": "each", "kind": "foreach", "label": "Each one",
                    "config": {"list": "{{ steps.call.data.items }}", "on_error": "stop",
                               "step": {"kind": "http", "label": "Fetch",
                                        "config": {"integration": "i-mini", "method": "GET", "path": "/y"}}}},
                   {"id": "each2", "kind": "foreach", "label": "Each again",
                    "config": {"list": "{{ steps.call.data.items }}", "on_error": "stop",
                               "step": {"kind": "skill", "label": "Print",
                                        "config": {"skill": "print-digest", "prompt": "Print it."}}}},
                   {"id": "ask", "kind": "llm", "label": "Ask", "config": {"prompt": "x", "tools": ["no_such_tool"]}},
                   {"id": "tally", "kind": "code", "label": "Tally",
                    "config": {"language": "python", "source": "print(1)"}},
                   {"id": "post", "kind": "mcp", "label": "Post",
                    "config": {"tool": "mcp__c9__send_message", "args": {"channel": "#x", "text": "hi"}}},
                   {"id": "run", "kind": "run_task", "label": "Run it", "config": {"task_id": "t-nightly"}}],
                   "edges": [{"from": "call", "port": "success", "to": "each"},
                             {"from": "call", "port": "success", "to": "each2"},
                             {"from": "call", "port": "success", "to": "ask"},
                             {"from": "call", "port": "success", "to": "tally"},
                             {"from": "call", "port": "success", "to": "post"},
                             {"from": "call", "port": "success", "to": "run"}]},
               "requires": {"integrations": [{"ref": "i-issues", "name": "Issues", "preset": ""},
                                             {"ref": "i-mini", "name": "Miniflux", "preset": "miniflux"}],
                            "mcp_tools": [{"ref": "mcp__c9__send_message", "server": "Chat", "tool": "send_message",
                                           "input_schema": {"type": "object", "properties": {
                                               "channel": {"type": "string"}, "text": {"type": "string"}}}}],
                            "skills": ["print-digest"], "tasks": [{"ref": "t-nightly", "name": "Nightly backup"}],
                            "workstation": True}}


def test_every_kind_of_need_an_import_writes_is_said_in_words_with_a_door_only_where_there_is_a_room(box, two):
    """The real `import_file` writes a need per kind of thing a file may refer
    to — an Integration, an MCP tool, a skill, a task, a header's value, an AI
    step's tool, the workstation — and a For-each's inner step's as
    `step.config.<field>`. Each is said in words; only an Integration, a tool
    and a skill have a room to add them in."""
    o = _case(box, two, """
        const { r } = await openFile(JSON.stringify(FILE));
        const made = replyTo('POST', (u) => u === '/api/workflows');
        const seen = {};
        for (const id of ['call', 'each', 'each2', 'ask', 'tally', 'post', 'run']) {
          fire(nodeEl(r, id), 'click'); await quiet();
          const b = by(r, 'wf-step-check');
          seen[id] = { words: all(b, 'wf-step-check-need-text').map((x) => x.textContent),
                       doors: all(b, 'wf-step-check-need-door').map((x) => x.dataset.room),
                       top: all(r, 'wf-sf-need').map((x) => [x.dataset.field || null, x.parentNode.className]) };
        }
        out({ status: made.status, reply: made.reply, seen });
    """, FILE=_EVERY_NEED)
    assert o["status"] == 200, o["reply"]
    needs = {n["id"]: (n.get("unchecked") or {}).get("needs") for n in o["reply"]["workflow"]["graph"]["nodes"]}
    assert needs["call"] == [{"field": "headers[0].value", "name": "X-Auth-Token"}], "Issues is here: only the header"
    seen = o["seen"]
    assert seen["call"]["words"] == ["It sends the header “X-Auth-Token”, and a file never carries its value. Type it on the step."]
    assert seen["each"]["words"] == ["It uses an Integration called “Miniflux” (miniflux), which this Pantheon does not have. "
                                     "Add it in MCP & Integrations, then pick it on the step."], \
        "an inner step's need is read through its step.config. prefix"
    assert seen["each"]["doors"] == ["integrations"]
    assert seen["each"]["top"] == [[None, "wf-sf-problems"]], "an inner step's need is said at the top of the For-each's form"
    assert seen["each2"]["words"] == ["It follows a skill called “print-digest”, which you do not have. Add it in Skills, "
                                      "then pick it on the step."]
    assert seen["each2"]["doors"] == ["skills"]
    assert seen["ask"]["words"] == ["It may use the tool “no_such_tool”, which you cannot use here. Change its tools on the step."]
    assert seen["tally"]["words"] == ["It runs code in your workstation, which cannot run it now."]
    assert seen["post"]["words"] == ["It uses the tool “send_message” of an MCP server called “Chat”, which this Pantheon "
                                     "does not have. Add the server in MCP & Integrations, then pick the tool on the step."]
    assert seen["post"]["doors"] == ["integrations"]
    assert seen["run"]["words"] == ["It ran a task called “Nightly backup” on the Pantheon it came from. Pick the task it "
                                    "runs on the step."]
    assert all(seen[k]["doors"] == [] for k in ("call", "ask", "tally", "run")), "no room to add these in"


def test_a_step_that_cannot_be_planned_yet_says_why_not_that_the_plan_missed_it(box, two):
    """Measured in Chromium (wb-canvas-e): an imported workflow whose
    Integration is missing is not planned at all — the engine plans no step
    and says why — and the banner said "The plan did not reach this step". It
    says the reason. (`B1132`: the reason is the Doc's `plans_declined`, the
    same sentence the dry run recorded; no dry run is asked.)"""
    o = _case(box, two, """
        const { r } = await openFile(TEXT);
        fire(nodeEl(r, 'fetch-unread'), 'click'); await quiet();
        const doc = replyTo('POST', (u) => u === '/api/workflows').reply.workflow;
        out({ plan: by(r, 'wf-step-check').querySelector('.wf-step-check-plan').querySelectorAll('li').map((x) => x.textContent),
              plans: doc.plans, reason: doc.plans_declined,
              dryRuns: calls('POST', (u) => u.includes('/run?dry=true')).length });
    """, TEXT=two.export_text)
    assert o["plans"] == {}, "the engine planned nothing"
    assert o["reason"], o
    assert o["plan"] == [f"It cannot be planned yet: {o['reason']}"]
    assert o["dryRuns"] == 0
