# SPDX-License-Identifier: AGPL-3.0-or-later
"""Apollo's spaces in the pane, driven: the switcher, a space's own view, and
what each control asks the server.

The outline's *Spaces*: a switcher at the top of the Apollo chat and in the
pane header; each space has its own Apollo chat, so switching opens it; a
parent sees counts of its children, and an airgapped child only whether
something there needs the person; a space's Context lists what it reads and
what reads it, each grant revocable. What a space may see is the server's
rule (`src/apollo/spaces.py`, tested in `test_apollos_spaces_keep_their_edges`);
these cases check the pane says it and asks for it.

Driven under node: the real `apolloPane.js`, `apolloSpaces.js` and
`apolloPaneModel.js` on the shared DOM shim, the server faked by path.
"""
from __future__ import annotations

import shutil
import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parent))

from test_apollos_pane_shows_the_work_and_what_it_knows_js import _PREAMBLE, _SHIM, _STUBS  # noqa: E402
from test_tool_effect_surfaces_js import _make_sandbox, _run  # noqa: E402

ROOT = Path(__file__).resolve().parents[1]
PANE = ROOT / "static" / "js" / "apolloPane.js"

pytestmark = pytest.mark.skipif(not shutil.which("node"), reason="node binary not on PATH")

_SPACES = (
    "const Sp = await import('./apolloSpaces.js');\n"
    "const M = await import('./apolloPaneModel.js');\n"
    "const SPACES = [\n"
    "  { id: 's-work', name: 'CyberKnox', parent_id: null, depth: 0, airgapped: true, local_only: false,\n"
    "    sealed: true, session_id: 'chat-work', path: 'CyberKnox', needs_you: true, open: null },\n"
    "  { id: 's-home', name: 'Home', parent_id: null, depth: 0, airgapped: false, local_only: false,\n"
    "    sealed: false, session_id: null, path: 'Home', needs_you: 1, open: 3 },\n"
    "  { id: 's-garage', name: 'Garage', parent_id: 's-home', depth: 1, airgapped: false, local_only: false,\n"
    "    sealed: false, session_id: null, path: 'Home › Garage', needs_you: 0, open: 0 },\n"
    "];\n"
    "routes['GET /api/apollo/spaces'] = () => [200, { spaces: SPACES }];\n"
    "routes['GET /api/apollo/tasks'] = (m, url) => [200, { tasks: url.includes('space=all')\n"
    "  ? [T('t1', 'working', { space_id: 's-home' }), T('t2', 'working', { space_id: null })]\n"
    "  : [T('t2', 'working', { space_id: null })] }];\n"
    "routes['GET /api/apollo/state'] = (m, url) => [200, url.includes('space=s-home')\n"
    "  ? { name: 'Apollo', status: { state: 'idle', words: 'Idle' }, goal_token_cap: 1,\n"
    "      space: SPACES[1], children: [{ id: 's-garage', name: 'Garage', sealed: false, open: 0, needs_you: 0 }] }\n"
    "  : { name: 'Apollo', status: { state: 'idle', words: 'Idle' }, goal_token_cap: 1, space: null,\n"
    "      children: [{ id: 's-work', name: 'CyberKnox', sealed: true, needs_you: true },\n"
    "                 { id: 's-home', name: 'Home', sealed: false, open: 3, needs_you: 1 }] }];\n"
    "routes['POST /api/apollo/spaces/*'] = (m, url) => {\n"
    "  if (url.endsWith('/chat')) return [200, { session_id: `chat-${url.split('/')[4]}` }];\n"
    "  return [200, { grant_id: 'g-new' }];\n"
    "};\n"
)


@pytest.fixture(scope="module")
def box(tmp_path_factory):
    return _make_sandbox(tmp_path_factory.mktemp("apollospaces"), PANE, _SHIM, _STUBS)


def _case(box, script):
    return _run(box, _PREAMBLE + _SPACES, script + "\nP.closeApolloPane();\n")


def test_the_switcher_lists_the_spaces_and_opens_the_one_picked(box):
    o = _case(box, """
        P.openApolloPane();
        await settle();
        const sw = all(pane(), 'apo-space-b')[0];
        const before = text(all(sw, 'apo-space-name')[0]);
        sw.click();
        await settle();
        const items = all(pane(), 'apo-space-i');
        const listed = items.map((b) => ({ t: b.textContent, locked: all(b, 'apo-lock').length > 0,
          checked: b.getAttribute('aria-checked') }));
        sent.length = 0;
        items.find((b) => b.textContent === 'Home').click();
        await settle(30);
        out({ before, listed, after: text(all(all(pane(), 'apo-space-b')[0], 'apo-space-name')[0]),
          session: opened.session, here: Sp.currentSpace(),
          asked: sent.map((s) => `${s.method} ${s.url}`).filter((u) => u.includes('/api/apollo/')) });
    """)
    assert o["before"] == "Apollo"
    assert o["listed"] == [
        {"t": "Apollo", "locked": False, "checked": "true"},
        {"t": "CyberKnox", "locked": True, "checked": "false"},
        {"t": "Home", "locked": False, "checked": "false"},
        {"t": "Garage", "locked": False, "checked": "false"},
    ]
    assert o["session"] == "chat-s-home" and o["here"] == "s-home"
    assert o["after"] == "Home"
    assert o["asked"][0] == "POST /api/apollo/spaces/s-home/chat"
    # The pane follows: it now reads that space.
    assert "GET /api/apollo/state?space=s-home" in o["asked"]
    assert "GET /api/apollo/tasks?space=s-home" in o["asked"]


def test_the_top_layer_shows_its_spaces_by_count_and_a_locked_one_only_by_need(box):
    o = _case(box, """
        Sp.noteSpace(null);
        P.openApolloPane();
        await settle();
        const p = pane();
        const rooms = all(p, 'apo-sec').find((s) => text(all(s, 'apo-sec-t')[0]) === 'Spaces');
        const lines = all(rooms, 'apo-row').map((r) => [text(all(r, 'apo-row-t')[0]), text(all(r, 'apo-row-s')[0])]);
        const locked = all(p, 'apo-need-locked').map((r) => text(all(r, 'apo-q')[0]));
        sent.length = 0;
        button(p, 'Go there').click();
        await settle(30);
        out({ lines, locked, went: sent.map((s) => `${s.method} ${s.url}`)[0], session: opened.session });
    """)
    assert o["lines"] == [["CyberKnox", "Locked. Something there needs you."],
                          ["Home", "3 open, 1 needs you."]]
    assert o["locked"] == ["CyberKnox is locked. Something there needs you."]
    assert o["went"] == "POST /api/apollo/spaces/s-work/chat"
    assert o["session"] == "chat-s-work"


def test_activity_reads_this_space_or_all_and_all_names_each_tasks_space(box):
    o = _case(box, """
        Sp.noteSpace(null);
        P.openApolloPane();
        await settle();
        const act = () => all(pane(), 'apo-sec').find((s) => text(all(s, 'apo-sec-t')[0]) === 'Activity');
        const here = all(act(), 'apo-row-t').map(text);
        sent.length = 0;
        button(act(), 'All').click();
        await settle();
        const rows = all(act(), 'apo-row-b').map((b) => b.getAttribute('aria-label'));
        const asked = sent.map((s) => `${s.method} ${s.url}`);
        const pressed = button(act(), 'All').getAttribute('aria-pressed');
        out({ here, rows, asked, pressed });
    """)
    assert o["here"] == ["Task t2"]
    assert sorted(o["rows"]) == ["Task t1, in Home, Working", "Task t2, Working"]
    assert "GET /api/apollo/tasks?space=all" in o["asked"]
    assert "GET /api/apollo/approvals?space=all" in o["asked"]
    assert "GET /api/apollo/notebook?kind=open_loop&state=open&space=all" in o["asked"]
    # The status line still reads where Apollo is.
    assert "GET /api/apollo/state?space=top" in o["asked"]
    assert o["pressed"] == "true"


def test_a_new_space_is_made_from_the_switcher_and_opened(box):
    o = _case(box, """
        Sp.noteSpace('s-home');
        let made = null;
        routes['POST /api/apollo/spaces'] = (m, url, body) => { made = body;
          return [200, { id: 's-new', name: body.name, parent_id: body.parent_id, depth: 1, sealed: true }]; };
        P.openApolloPane();
        await settle();
        all(pane(), 'apo-space-b')[0].click();
        await settle();
        const form = all(pane(), 'apo-space-new')[0];
        all(form, 'apo-input')[0].value = '  Taxes  ';
        const boxes = form._walk([]).filter((n) => n.tagName === 'INPUT' && n.type === 'checkbox');
        boxes[0].checked = true;   // inside Home
        boxes[1].checked = true;   // airgapped
        const insideWords = all(form, 'apo-check').map(text);
        sent.length = 0;
        submit(form);
        await settle(30);
        out({ made, insideWords, opened: opened.session, asked: sent.map((s) => `${s.method} ${s.url}`) });
    """)
    assert o["made"] == {"name": "Taxes", "parent_id": "s-home", "airgapped": True}
    assert o["insideWords"] == ["Inside Home", "Airgapped"]
    assert "POST /api/apollo/spaces/s-new/chat" in o["asked"]
    assert o["opened"] == "chat-s-new"


def test_a_spaces_own_view_lists_its_reads_and_each_control_asks_the_server(box):
    o = _case(box, """
        Sp.noteSpace('s-home');
        routes['GET /api/apollo/spaces/*'] = () => [200, {
          space: SPACES[1],
          reads_from: [
            { space_id: null, name: 'Apollo', how: 'above' },
            { grant_id: 'g1', scope: 'outcomes', space_id: 's-garage', name: 'Garage', how: 'grant' },
          ],
          read_by: [{ space_id: 's-garage', name: 'Garage', how: 'below' }],
          children: [], uses: [{ grant_id: 'g1', what: 'Read what Garage finished', at: null }],
        }];
        const writes = [];
        routes['PATCH /api/apollo/spaces/*'] = (m, url, body) => { writes.push(['PATCH', url, body]); return [200, SPACES[1]]; };
        routes['DELETE /api/apollo/spaces/*'] = (m, url) => { writes.push(['DELETE', url]); return [200, { deleted: true }]; };
        routes['DELETE /api/apollo/grants/*'] = (m, url) => { writes.push(['DELETE', url]); return [200, { revoked: true }]; };
        P.openApolloPane();
        await settle();
        button(pane(), 'About this space').click();
        await settle();
        const p = pane();
        const sec = (t) => all(p, 'apo-sec').find((s) => text(all(s, 'apo-sec-t')[0]) === t);
        const heading = text(all(p, 'apo-task-t')[0]);
        const from = all(sec('Reads from'), 'apo-line-t').map(text);
        const by = all(sec('Read by'), 'apo-line-t').map(text);
        const revokes = buttons(sec('Reads from')).filter((b) => b.textContent === 'Revoke').length;
        const switches = all(sec('Edges'), 'apo-switch').map((r) => {
          const box = r._walk([]).find((n) => n.tagName === 'INPUT');
          return { t: text(all(r, 'apo-switch-t')[0]), on: box.checked, disabled: box.disabled };
        });
        // The give-read form offers no space above this one, itself or a locked one.
        const give = all(p, 'apo-give')[0];
        const selects = give._walk([]).filter((n) => n.tagName === 'SELECT');
        const offered = selects[1]._walk([]).filter((n) => n.tagName === 'OPTION').map(text);
        const uses = all(sec('Last reads'), 'apo-line-t').map(text);
        button(sec('Reads from'), 'Revoke').click();
        await settle();
        sent.length = 0;
        submit(all(pane(), 'apo-give')[0]);
        await settle();
        const granted = sent.find((s) => s.method === 'POST');
        const gap = all(sec('Edges'), 'apo-switch')[0]._walk([]).find((n) => n.tagName === 'INPUT');
        gap.checked = true;
        gap.dispatchEvent({ type: 'change' });
        await settle();
        const rename = all(pane(), 'apo-add')[0];
        all(rename, 'apo-input')[0].value = 'House';
        submit(rename);
        await settle();
        out({ heading, from, by, revokes, switches, offered, uses, writes,
          granted: granted && [granted.url, granted.body] });
    """)
    assert o["heading"] == "Home"
    assert o["from"] == ["Apollo: everything, because it's above this space.",
                         "Garage: what its tasks came to, read only."]
    assert o["by"] == ["Garage: everything here, because it's inside this space."]
    assert o["revokes"] == 1
    assert o["switches"] == [{"t": "Airgapped", "on": False, "disabled": False},
                             {"t": "Local models only", "on": False, "disabled": True}]
    assert o["offered"] == ["Home › Garage"]
    assert o["uses"] == ["Read what Garage finished"]
    assert o["granted"] == ["/api/apollo/spaces/s-home/grants", {"source_id": "s-garage", "scope": "memory"}]
    assert o["writes"] == [
        ["DELETE", "/api/apollo/grants/g1"],
        ["PATCH", "/api/apollo/spaces/s-home", {"airgapped": True}],
        ["PATCH", "/api/apollo/spaces/s-home", {"name": "House"}],
    ]


def test_deleting_a_space_takes_two_presses_and_goes_to_its_parent(box):
    o = _case(box, """
        Sp.noteSpace('s-garage');
        routes['GET /api/apollo/state'] = () => [200, { name: 'Apollo', status: { state: 'idle', words: 'Idle' },
          goal_token_cap: 1, space: SPACES[2], children: [] }];
        routes['GET /api/apollo/spaces/*'] = () => [200, { space: SPACES[2], reads_from: [], read_by: [], children: [], uses: [] }];
        const writes = [];
        routes['DELETE /api/apollo/spaces/*'] = (m, url) => { writes.push(url); return [200, { deleted: true }]; };
        P.openApolloPane();
        await settle();
        button(pane(), 'About this space').click();
        await settle();
        button(pane(), 'Delete this space').click();
        await settle();
        const first = writes.length;
        const second = button(pane(), 'Press again to delete');
        second.click();
        await settle(30);
        out({ first, writes, here: Sp.currentSpace(), session: opened.session });
    """)
    assert o["first"] == 0
    assert o["writes"] == ["/api/apollo/spaces/s-garage"]
    assert o["here"] == "s-home" and o["session"] == "chat-s-home"


def test_in_a_space_what_apollo_knows_marks_a_granted_line_read_only(box):
    o = _case(box, """
        Sp.noteSpace('s-home');
        routes['GET /api/apollo/knows'] = () => [200, { lines: [
          { id: 'k1', text: 'The boiler is in the garage', basis: 'stated', space_id: 's-home', space: 'Home', via_grant: null },
          { id: 'k2', text: 'Never book me before 10', basis: 'stated', space_id: null, space: 'Apollo', via_grant: null },
          { id: 'k3', text: 'The mower is a Honda', basis: 'stated', space_id: 's-garage', space: 'Garage', via_grant: 'g1' },
        ] }];
        P.openApolloPane();
        await settle();
        button(pane(), 'What Apollo knows').click();
        await settle();
        const rows = all(pane(), 'apo-line-stated').map((li) => ({
          t: text(all(li, 'apo-line-t')[0]), why: all(li, 'apo-line-why').map(text),
          acts: buttons(li).map((b) => b.textContent) }));
        out({ rows, asked: sent.filter((s) => s.url.startsWith('/api/apollo/knows')).map((s) => s.url) });
    """)
    assert o["rows"] == [
        {"t": "The boiler is in the garage", "why": [], "acts": ["Edit", "Forget"]},
        {"t": "Never book me before 10", "why": ["Kept in Apollo."], "acts": ["Edit", "Forget"]},
        {"t": "The mower is a Honda", "why": ["From Garage, read only."], "acts": []},
    ]
    assert o["asked"] == ["/api/apollo/knows?space=s-home"]


def test_the_space_helpers_say_it_plainly(box):
    o = _case(box, """
        out({
          label: [M.spaceLabel(null), M.spaceLabel(SPACES[2])],
          child: [M.childLine({ sealed: true, needs_you: false }), M.childLine({ open: 0 }),
                  M.childLine({ open: 2, needs_you: 2 })],
          locked: M.lockedNeeds(SPACES, null).map((s) => s.id),
          lockedInside: M.lockedNeeds(SPACES, 's-work').map((s) => s.id),
          sources: M.grantSources(SPACES, 's-garage', { reads_from: [] }, 'memory').map((s) => s.id),
          fromLocked: M.grantSources(SPACES, 's-work', {}, 'memory').length,
          already: M.grantSources(SPACES, 's-home',
            { reads_from: [{ how: 'grant', scope: 'memory', space_id: 's-garage' }] }, 'memory').length,
        });
    """)
    assert o["label"] == ["Apollo", "Home › Garage"]
    assert o["child"] == ["Locked.", "Nothing open.", "2 open, 2 need you."]
    assert o["locked"] == ["s-work"]
    assert o["lockedInside"] == []
    # Garage already reads Home (it's inside it); CyberKnox is locked.
    assert o["sources"] == []
    assert o["fromLocked"] == 0
    assert o["already"] == 0
