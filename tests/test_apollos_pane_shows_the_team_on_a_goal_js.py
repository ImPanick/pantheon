# SPDX-License-Identifier: AGPL-3.0-or-later
"""The fleet in the pane (phase 5), driven: a task's view shows who is on its
goal, how each came to it, and what they said to each other, and a member's
row opens that member's task.

What the fleet does is the server's (`src/apollo/fleet.py`, tested in
`test_apollos_fleet_hands_off_reviews_and_reports_up`); these cases check the
pane says it plainly. Driven under node: the real `apolloPane.js` and
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

_TEAM = (
    "const goal = T('g1', 'waiting', { title: 'Launch the newsletter', lead_agent: 'lead' });\n"
    "const kid = T('k1', 'needs_you', { title: 'Writer: Write the intro', lead_agent: 'writer', parent_id: 'g1',\n"
    "  question: 'Check Writer’s work before it counts. Answer pass, or say what to change.' });\n"
    "const TEAM = { goal_id: 'g1', members: [\n"
    "  { id: 'g1', title: 'Launch the newsletter', state: 'waiting', parent_id: null, lead: 'lead', lead_name: 'Lead', via: null, review_by: null, stage: null, depth: 0 },\n"
    "  { id: 'k1', title: 'Writer: Write the intro', state: 'needs_you', parent_id: 'g1', lead: 'writer', lead_name: 'Writer', via: 'delegate', review_by: 'person', stage: 'in_review', depth: 1 },\n"
    "  { id: 'k2', title: 'Checker: Is the subject short?', state: 'done', parent_id: 'k1', lead: 'checker', lead_name: 'Checker', via: 'ask', review_by: null, stage: 'done', depth: 2 }],\n"
    "  messages: [\n"
    "  { id: 'm1', kind: 'delegate', from: 'lead', to: 'writer', body: 'Write the intro\\nKeep it short.' },\n"
    "  { id: 'm2', kind: 'ask', from: 'writer', to: 'checker', body: 'Is the subject line under 50 characters?' },\n"
    "  { id: 'm3', kind: 'report', from: 'checker', to: 'writer', body: 'Yes, 41.' },\n"
    "  { id: 'm4', kind: 'review', from: 'writer', to: 'person', body: 'Intro written.' }] };\n"
    "routes['GET /api/apollo/tasks'] = () => [200, { tasks: [goal, kid] }];\n"
    "routes['GET /api/apollo/spaces'] = () => [200, { spaces: [] }];\n"
    "routes['GET /api/apollo/tasks/g1'] = () => [200, goal];\n"
    "routes['GET /api/apollo/tasks/k1'] = () => [200, kid];\n"
    "routes['GET /api/apollo/tasks/k2'] = () => [200, T('k2', 'done', { title: 'Checker: Is the subject short?' })];\n"
    "let teamOf = () => [200, TEAM];\n"
    "for (const id of ['g1', 'k1', 'k2']) routes[`GET /api/apollo/tasks/${id}/team`] = () => teamOf();\n"
    "const sec = (title) => all(pane(), 'apo-sec').find((s) => text(all(s, 'apo-sec-t')[0]) === title);\n"
    "async function openTask(i) {\n"
    "  P.openApolloPane();\n"
    "  await settle();\n"
    "  all(pane(), 'apo-row-b')[i].click();\n"
    "  await settle();\n"
    "}\n"
)


@pytest.fixture(scope="module")
def box(tmp_path_factory):
    return _make_sandbox(tmp_path_factory.mktemp("apolloteam"), PANE, _SHIM, _STUBS)


def _case(box, script):
    return _run(box, _PREAMBLE + _TEAM, script + "\nP.closeApolloPane();\n")


def test_a_task_view_shows_its_goals_team_and_their_log(box):
    o = _case(box, """
        const rowOf = (r) => [text(all(r, 'apo-row-t')[0]), text(all(r, 'apo-row-sp')[0]), r._classes().join(' ')];
        await openTask(0);
        const team = sec('Team');
        out({ rows: all(team, 'apo-team-m').map(rowOf), log: all(team, 'apo-team-l').map(text),
              current: all(team, 'apo-row-b').map((b) => b.getAttribute('aria-current')),
              asked: sent.filter((s) => s.url.endsWith('/team')).map((s) => s.url) });
    """)
    assert [r[:2] for r in o["rows"]] == [
        ["Launch the newsletter", "Lead, leads the goal"],
        ["Writer: Write the intro", "Writer, waiting on your review"],
        ["Checker: Is the subject short?", "Checker, answering a question"]]
    assert ["apo-team-d0" in o["rows"][0][2], "apo-team-d1" in o["rows"][1][2],
            "apo-team-d2" in o["rows"][2][2]] == [True, True, True]
    assert o["log"] == ["Lead handed Writer: Write the intro",
                        "Writer asked Checker: Is the subject line under 50 characters?",
                        "Checker reported to Writer: Yes, 41.",
                        "Writer sent for review to you: Intro written."]
    assert o["current"] == ["true", None, None]
    assert o["asked"] == ["/api/apollo/tasks/g1/team"]


def test_a_members_row_opens_its_task_and_a_lone_task_shows_no_team(box):
    o = _case(box, """
        await openTask(0);
        all(sec('Team'), 'apo-row-b')[2].click();
        await settle();
        const shown = text(all(pane(), 'apo-task-t')[0]);
        teamOf = () => [200, { goal_id: 'g1', members: [TEAM.members[0]], messages: [] }];
        all(pane(), 'apo-back')[0].click();
        await settle();
        all(pane(), 'apo-row-b')[0].click();
        await settle();
        out({ shown, lone: !!sec('Team') });
    """)
    assert o["shown"] == "Checker: Is the subject short?"
    assert o["lone"] is False


def test_a_team_route_that_fails_leaves_the_task_view_whole(box):
    o = _case(box, """
        teamOf = () => [500, { detail: 'boom' }];
        await openTask(1);
        out({ title: text(all(pane(), 'apo-task-t')[0]), team: !!sec('Team'),
              q: text(all(pane(), 'apo-q')[0]) });
    """)
    assert o["title"] == "Writer: Write the intro" and o["team"] is False
    assert o["q"].startswith("Check Writer")
