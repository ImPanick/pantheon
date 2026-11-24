# SPDX-License-Identifier: AGPL-3.0-or-later
"""Missing agents in the pane (phase 5b), driven: the person sees the agents
being made for them and can try a failed one again, and an admin sees each
drafted agent's tools, effects and proof beside Approve, Edit and Reject, and
can roll a platform agent back. A person who isn't an admin sees no review.

What happens to a proposal is the server's (`src/apollo/gaps.py`, tested in
`test_apollos_gaps_draft_prove_and_publish_agents`); these cases check the
pane says it plainly and sends the right request. Driven under node: the real
`apolloPane.js` and `apolloPaneModel.js` on the shared DOM shim.
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

_MADE = (
    "const now = new Date().toISOString();\n"
    "const Pr = (id, state, extra = {}) => ({ id, need: 'Answer leave questions', why: 'None fits.', state,\n"
    "  state_words: { drafting: 'Drafting it', waiting: 'Waiting on your admin', failed: \"Couldn't be made\" }[state],\n"
    "  sentence: 'It says why.', created_at: now, updated_at: now, ...extra });\n"
    "routes['GET /api/apollo/tasks'] = () => [200, { tasks: [] }];\n"
    "routes['GET /api/apollo/spaces'] = () => [200, { spaces: [] }];\n"
    "routes['GET /api/apollo/agents/proposals'] = () => [200, { proposals: [Pr('p1', 'waiting', { agent_name: 'Leave Answerer' }),\n"
    "  Pr('p2', 'failed'), Pr('old', 'rejected', { updated_at: '2026-01-01T00:00:00Z' })] }];\n"
    "routes['POST /api/apollo/agents/proposals/*'] = () => [200, Pr('p2', 'drafting')];\n"
    "const W = { ...Pr('p1', 'waiting', { agent_name: 'Leave Answerer' }), version: '1.0.0', owner: 'bob', badge: 'runs-well',\n"
    "  model: 'qwen3-8b', text: '---\\nid: leave-answerer\\n---\\nRunbook', proof: { runs: 6, pass_rate: 0.833 },\n"
    "  asks_for: { name: 'Leave Answerer', tools: ['manage_documents'], effects: { read_private: 'allow', destructive: 'never' } } };\n"
    "let review = () => [200, { waiting: [W], published: [{ id: 'leave-answerer', name: 'Leave Answerer', live: '1.1.0',\n"
    "  versions: [{ version: '1.0.0' }, { version: '1.1.0' }] }] }];\n"
    "routes['GET /api/apollo/agents/review'] = () => review();\n"
    "routes['POST /api/apollo/agents/review/*'] = () => [200, { ...W, state: 'published' }];\n"
    "routes['POST /api/apollo/agents/platform/*'] = () => [200, { id: 'leave-answerer', live: '1.0.0', versions: [] }];\n"
    "const sec = (title) => all(pane(), 'apo-sec').find((s) => text(all(s, 'apo-sec-t')[0]) === title);\n"
    "const btn = (root, words) => all(root, 'apo-btn').find((b) => text(b) === words);\n"
    "const posts = () => sent.filter((s) => s.method === 'POST').map((s) => [s.url, s.body]);\n"
)


@pytest.fixture(scope="module")
def box(tmp_path_factory):
    return _make_sandbox(tmp_path_factory.mktemp("apollomade"), PANE, _SHIM, _STUBS)


def _case(box, script):
    return _run(box, _PREAMBLE + _MADE, script + "\nP.closeApolloPane();\n")


def test_the_person_sees_agents_being_made_and_tries_a_failed_one_again(box):
    o = _case(box, """
        P.openApolloPane();
        await settle();
        const made = sec('Agents being made');
        const rows = all(made, 'apo-made').map((li) => all(li, 'apo-out-t').concat(all(li, 'apo-out-line')).map(text));
        btn(made, 'Try again').click();
        await settle();
        out({ rows, posts: posts(), again: all(made, 'apo-btn').filter((b) => text(b) === 'Try again').length });
    """)
    assert o["rows"] == [["Leave Answerer: Answer leave questions", "Waiting on your admin. It says why."],
                         ["Answer leave questions", "Couldn't be made. It says why."]]
    assert o["again"] == 1
    assert o["posts"] == [["/api/apollo/agents/proposals/p2/retry", None]]


def test_an_admin_weighs_what_it_asks_for_and_approves_or_rolls_back(box):
    o = _case(box, """
        P.openApolloPane();
        await settle();
        const rev = sec('New agents to approve');
        const first = all(rev, 'apo-review')[0];
        const lines = all(first, 'apo-out-t').concat(all(first, 'apo-out-line')).map(text);
        btn(first, 'Approve').click();
        await settle();
        btn(sec('New agents to approve'), 'Roll back to 1.0.0').click();
        await settle();
        out({ lines, posts: posts(), toasts: toasts.slice() });
    """)
    assert o["lines"] == ["Leave Answerer 1.0.0", "For: Answer leave questions", "Why: None fits.",
                          "Uses manage_documents. Effects: read_private allow, destructive never.",
                          "Proven on qwen3-8b: Runs well. 5 of 6 runs passed."]
    assert o["posts"] == [["/api/apollo/agents/review/p1/approve", {}],
                          ["/api/apollo/agents/platform/leave-answerer/rollback", {"version": "1.0.0"}]]
    assert o["toasts"] == ["Published. Anyone on this server can hire it.", "Leave Answerer is back on 1.0.0."]


def test_an_admins_edit_is_sent_to_be_proven_again(box):
    o = _case(box, """
        P.openApolloPane();
        await settle();
        btn(sec('New agents to approve'), 'Edit').click();
        await settle();
        const box = all(pane(), 'apo-review-text')[0];
        const was = box.value;
        box.value = was + '\\nMore.';
        box.dispatchEvent(new Event('input'));
        btn(sec('New agents to approve'), 'Prove it again').click();
        await settle();
        out({ was, posts: posts(), editing: all(pane(), 'apo-review-text').length });
    """)
    assert o["was"].startswith("---\nid: leave-answerer")
    assert o["posts"] == [["/api/apollo/agents/review/p1/edit", {"text": o["was"] + "\nMore."}]]
    assert o["editing"] == 0


def test_an_admin_proves_a_new_version_of_a_platform_agent(box):
    o = _case(box, """
        routes['GET /api/agents/leave-answerer/source'] = () => [200, { id: 'leave-answerer', text: 'v1 file' }];
        review = () => [200, { waiting: [], published: [{ id: 'leave-answerer', name: 'Leave Answerer', live: '1.0.0',
          versions: [{ version: '1.0.0' }] }] }];
        P.openApolloPane();
        await settle();
        const s = sec('Agents made here');
        const head = text(all(s, 'apo-out-t')[0]);
        const back = all(s, 'apo-btn').filter((b) => text(b).startsWith('Roll back')).length;
        btn(s, 'New version').click();
        await settle();
        const box = all(pane(), 'apo-review-text')[0];
        box.value = 'v2 file';
        box.dispatchEvent(new Event('input'));
        btn(sec('Agents made here'), 'Prove it').click();
        await settle();
        out({ head, back, was: box.value, posts: posts() });
    """)
    assert o["head"] == "Leave Answerer: version 1.0.0 is live" and o["back"] == 0
    assert o["posts"] == [["/api/apollo/agents/platform/leave-answerer/update", {"text": "v2 file"}]]


def test_someone_who_isnt_an_admin_sees_no_review(box):
    o = _case(box, """
        review = () => [403, { detail: 'Admin only' }];
        P.openApolloPane();
        await settle();
        out({ review: !!sec('New agents to approve') || !!sec('Agents made here'), made: !!sec('Agents being made') });
    """)
    assert o == {"review": False, "made": True}
