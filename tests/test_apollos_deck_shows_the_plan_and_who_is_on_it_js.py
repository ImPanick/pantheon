# SPDX-License-Identifier: AGPL-3.0-or-later
"""Apollo's deck shows the work: goals, the plan, who is on it, what needs you.

The owner's verdict on the first cut (2026-11-24): Apollo was "another
ordinary chat ... no tells that it spawned another agent, there's no planning,
delegation, nothing". The shape he chose: a goals rail, a live board of the
open goal (its plan with an owner per step, who is running now, the handoffs),
Needs you answered in place, and home.

Driven under node: the deck model (`apolloDeckModel.js`) on its own, then the
deck (`apolloDeck.js`) against a stubbed server. New goal posts a goal that the
server staffs and starts, then opens its board; the board shows each step with
its owner and the handoffs between agents in their names; Needs you answers a
question and an approval in place; leaving takes the deck and the lead's chat
off the page.
"""
from __future__ import annotations

import shutil
import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parent))

from test_tool_effect_surfaces_js import _make_sandbox, _run  # noqa: E402

ROOT = Path(__file__).resolve().parents[1]
DECK = ROOT / "static" / "js" / "apolloDeck.js"

pytestmark = pytest.mark.skipif(not shutil.which("node"), reason="node binary not on PATH")

_GOALS = r"""
export const GOAL = { id: 'g1', title: 'Ship the re-theme', state: 'working', lead_agent: 'a-dev', lead_name: 'Forge',
  next_step: 'Forge is fixing the contrast check.', spent_tokens: 12000, budget_limit: null, hire_id: 'h1',
  updated_at: '2026-11-24T09:10:00Z', created_at: '2026-11-24T08:00:00Z' };
export const ASK = { id: 'g2', title: 'Pick a launch date', state: 'needs_you', lead_agent: 'a-pm', lead_name: 'Compass',
  question: 'Friday or Monday?', updated_at: '2026-11-24T09:05:00Z', created_at: '2026-11-24T07:00:00Z' };
export const DONE = { id: 'g3', title: 'Write the README', state: 'done', lead_agent: null, lead_name: 'Apollo',
  outcome: 'README rewritten.', updated_at: '2026-11-23T20:00:00Z', created_at: '2026-11-23T10:00:00Z' };
export const CHILD = { id: 'c1', title: 'Fix contrast', state: 'working', parent_id: 'g1', lead_agent: 'a-css',
  lead_name: 'Prism', updated_at: '2026-11-24T09:11:00Z' };
export const TEAM = {
  goal_id: 'g1',
  members: [
    { id: 'g1', title: 'Ship the re-theme', state: 'working', parent_id: null, lead: 'a-dev', lead_name: 'Forge', depth: 0 },
    { id: 'c1', title: 'Fix contrast', state: 'working', parent_id: 'g1', lead: 'a-css', lead_name: 'Prism', via: 'delegate', depth: 1 },
    { id: 'c2', title: 'Review the theme', state: 'waiting', parent_id: 'g1', lead: 'a-rev', lead_name: 'Lens', via: 'review', depth: 1 },
  ],
  messages: [
    { id: 'm1', kind: 'delegate', task_id: 'g1', child_id: 'c1', from: 'a-dev', to: 'a-css', body: 'Fix the contrast check', at: '2026-11-24T09:00:00Z' },
    { id: 'm2', kind: 'review', task_id: 'g1', child_id: 'c2', from: 'a-dev', to: 'a-rev', body: 'Check the theme', at: '2026-11-24T09:02:00Z' },
  ],
};
"""

_SHIM = _GOALS + r"""
import { installDom } from './dom.js';
export const document = installDom();
export const log = { calls: [], toasts: [], chats: [], destroyed: [] };
export const server = { tasks: [], approvals: [], created: null };
export const space = { id: 'sp-work' };
globalThis.fetch = async (url, opts = {}) => {
  const method = opts.method || 'GET';
  const body = opts.body ? JSON.parse(opts.body) : undefined;
  log.calls.push({ method, url, body });
  let out = {};
  if (method === 'POST' && url === '/api/apollo/tasks') {
    out = server.created;
    server.tasks = [out, ...server.tasks];
  } else if (url.startsWith('/api/apollo/tasks?')) out = { tasks: server.tasks };
  else if (url.startsWith('/api/apollo/approvals')) out = { approvals: server.approvals };
  else if (url.endsWith('/team')) out = TEAM;
  else if (url.endsWith('/answer')) out = { started: true };
  else if (url.startsWith('/api/apollo/tasks/')) out = server.tasks.find((t) => url.endsWith(t.id)) || {};
  return { ok: true, status: 200, json: async () => out };
};
export function settle(n = 20) {
  let p = Promise.resolve();
  for (let i = 0; i < n; i++) p = p.then(() => new Promise((r) => setTimeout(r, 0)));
  return p;
}
export function page() {
  const cc = document.createElement('main'); cc.id = 'chat-container';
  const top = document.createElement('div'); top.className = 'chat-top-bar';
  const hist = document.createElement('div'); hist.id = 'chat-history';
  cc.appendChild(top); cc.appendChild(hist);
  document.body.appendChild(cc);
  return { cc, top, hist };
}
export const texts = (root, cls) => root.querySelectorAll(cls).map((n) => n.textContent);
"""

_STUBS = {
    "ui.js": "import { log } from './shim.js';\nexport default { showToast: (m) => log.toasts.push(m) };\n",
    "apolloSpaces.js": (
        "import { space } from './shim.js';\n"
        "export function currentSpace() { return space.id; }\n"
        "export function spaceParam() { return space.id || 'top'; }\n"
        "export function onSpaceChange(fn) { space.fn = fn; return () => { space.fn = null; }; }\n"
    ),
    "apolloTaskChat.js": (
        "import { document, log } from './shim.js';\n"
        "export function createTaskChat(id) {\n"
        "  log.chats.push(id);\n"
        "  const el = document.createElement('section'); el.className = 'tc-stub'; el.textContent = `chat with ${id}`;\n"
        "  return { el, taskId: String(id), destroy() { log.destroyed.push(id); el.remove(); } };\n"
        "}\n"
    ),
}

_PREAMBLE = (
    "import { document, log, server, space, settle, page, texts, GOAL, ASK, DONE, CHILD, TEAM } from './shim.js';\n"
    "const D = await import('./apolloDeck.js');\n"
    "const out = (o) => console.log(JSON.stringify(o));\n"
    "const P = page();\n"
)


@pytest.fixture(scope="module")
def box(tmp_path_factory):
    return _make_sandbox(tmp_path_factory.mktemp("apollodeck"), DECK, _SHIM, _STUBS)


# ── the model ──────────────────────────────────────────────────────────────

def test_the_rail_puts_what_needs_you_first_and_hides_delegates(box):
    o = _run(box, "import { GOAL, ASK, DONE, CHILD, TEAM } from './shim.js';\n"
                  "const M = await import('./apolloDeckModel.js');\n"
                  "const out = (o) => console.log(JSON.stringify(o));\n", """
        const r = M.railRows([DONE, GOAL, CHILD, ASK]);
        out({ open: r.open.map((t) => t.id), done: r.done.map((t) => t.id),
              card: M.cardOf(GOAL), ask: M.cardOf(ASK).line });
    """)
    assert o["open"] == ["g2", "g1"] and o["done"] == ["g3"]
    assert o["card"]["lead"] == "Led by Forge" and o["card"]["spend"] == "12k tokens"
    assert o["card"]["line"] == "Forge is fixing the contrast check."
    assert o["ask"] == "Friday or Monday?"


def test_the_plan_has_an_owner_per_step_and_the_handoffs_name_the_agents(box):
    o = _run(box, "import { TEAM, GOAL, ASK } from './shim.js';\n"
                  "const M = await import('./apolloDeckModel.js');\n"
                  "const out = (o) => console.log(JSON.stringify(o));\n", """
        out({ steps: M.planSteps(TEAM).map((s) => [s.title, s.owner, s.role, s.depth]),
              moves: M.handoffs(TEAM).map((m) => m.line),
              now: M.runningNow(TEAM),
              home: M.home([GOAL, ASK], [{ approval_id: 'x' }], '2026-11-24T09:06:00Z') });
    """)
    assert o["steps"] == [["Ship the re-theme", "Forge", "Leads the goal", 0],
                          ["Fix contrast", "Prism", "Delegate", 1],
                          ["Review the theme", "Lens", "Reviewing", 1]]
    assert o["moves"] == ["Forge handed Prism: Fix the contrast check",
                          "Forge sent for review to Lens: Check the theme"]
    assert o["now"] == [{"owner": "Forge", "on": "Ship the re-theme"}, {"owner": "Prism", "on": "Fix contrast"}]
    assert o["home"]["headline"] == "2 things need you"
    assert [m["id"] for m in o["home"]["moved"]] == ["g1"]
    assert o["home"]["running"] == [{"id": "g1", "title": "Ship the re-theme", "lead": "Forge"}]


# ── the deck ───────────────────────────────────────────────────────────────

def test_the_deck_mounts_above_the_chat_with_goals_home_and_needs_you(box):
    o = _run(box, _PREAMBLE, """
        server.tasks = [GOAL, ASK, DONE];
        D.mountDeck();
        await settle();
        const deck = document.getElementById('apollo-deck');
        const kids = P.cc.childNodes;
        const beforeHistory = kids.indexOf(deck) + 1 === kids.indexOf(P.hist);
        const goals = deck.querySelectorAll('.apo-goal').map((b) => [b.dataset.taskId, b.textContent]);
        const board = deck.querySelector('.apo-deck-board').textContent;
        const needs = deck.querySelector('.apo-deck-needs').textContent;
        D.unmountDeck();
        out({ beforeHistory, goals, board, needs,
              gone: !document.getElementById('apollo-deck'), spaceUnhooked: !space.fn });
    """)
    assert o["beforeHistory"] is True
    assert [g[0] for g in o["goals"]] == ["g2", "g1", "g3"]
    assert "Led by Forge" in o["goals"][1][1] and "Led by Compass" in o["goals"][0][1]
    assert "1 thing needs you" in o["board"] and "Ship the re-theme" in o["board"]
    assert "Friday or Monday?" in o["needs"]
    assert o["gone"] is True and o["spaceUnhooked"] is True


def test_new_goal_is_staffed_by_the_server_and_opens_its_board(box):
    o = _run(box, _PREAMBLE, """
        server.tasks = [];
        server.created = GOAL;
        D.mountDeck();
        await settle();
        const deck = document.getElementById('apollo-deck');
        const form = deck.querySelector('.apo-newgoal');
        const [title, brief] = form.querySelectorAll('.apo-input');
        title.value = 'Ship the re-theme';
        brief.value = 'Use the site look';
        form.dispatchEvent({ type: 'submit', preventDefault() {} });
        await settle();
        const posted = log.calls.find((c) => c.method === 'POST');
        const board = deck.querySelector('.apo-deck-board');
        const steps = board.querySelectorAll('.apo-step').map((s) => s.textContent);
        const moves = texts(board, '.apo-move');
        const chatIn = !!board.querySelector('.tc-stub');
        const open = D.openGoalId();
        D.unmountDeck();
        out({ posted, toasts: log.toasts, open, steps, moves, chatIn, chats: log.chats, destroyed: log.destroyed });
    """)
    assert o["posted"] == {"method": "POST", "url": "/api/apollo/tasks",
                           "body": {"title": "Ship the re-theme", "brief": "Use the site look",
                                    "space_id": "sp-work", "start": True}}
    assert o["toasts"] == ["On it. Forge is leading it."]
    assert o["open"] == "g1"
    assert any("Fix contrast" in s and "Prism" in s and "Delegate" in s for s in o["steps"])
    assert any("Review the theme" in s and "Lens" in s and "Reviewing" in s for s in o["steps"])
    assert o["moves"] == ["Forge handed Prism: Fix the contrast check",
                          "Forge sent for review to Lens: Check the theme"]
    assert o["chatIn"] is True and o["chats"] == ["g1"] and o["destroyed"] == ["g1"]


def test_needs_you_answers_a_question_and_an_approval_in_place(box):
    o = _run(box, _PREAMBLE, """
        server.tasks = [ASK];
        server.approvals = [{ task_id: 'g2', title: 'Pick a launch date', run_task_id: 'rt9', run_id: 'r9',
                              approval_id: 'ap1', tool: 'send_email', question: 'Send it?', why: 'Mail goes out' }];
        D.mountDeck();
        await settle();
        const needs = document.getElementById('apollo-deck').querySelector('.apo-deck-needs');
        const count = needs.querySelector('.apo-count').textContent;
        const form = needs.querySelector('.apo-answer');
        form.querySelector('.apo-input').value = 'Friday';
        form.dispatchEvent({ type: 'submit', preventDefault() {} });
        await settle();
        const allow = needs.querySelectorAll('.apo-btn').find((b) => b.textContent === 'Allow once');
        allow.click();
        await settle();
        const posts = log.calls.filter((c) => c.method === 'POST').map((c) => [c.url, c.body]);
        D.unmountDeck();
        out({ count, posts });
    """)
    assert o["count"] == "2"
    assert o["posts"] == [
        ["/api/apollo/tasks/g2/answer", {"answer": "Friday"}],
        ["/api/tasks/rt9/runs/r9/answer", {"approval_id": "ap1", "decision": "approve_task"}],
    ]


def test_a_space_change_takes_the_board_home(box):
    o = _run(box, _PREAMBLE, """
        server.tasks = [GOAL];
        D.mountDeck();
        await settle();
        await D.openGoal('g1');
        await settle();
        const before = D.openGoalId();
        space.id = 'sp-home';
        space.fn();
        await settle();
        const after = D.openGoalId();
        const asked = log.calls.some((c) => c.url === '/api/apollo/tasks?space=sp-home');
        D.unmountDeck();
        out({ before, after, asked });
    """)
    assert o == {"before": "g1", "after": None, "asked": True}
