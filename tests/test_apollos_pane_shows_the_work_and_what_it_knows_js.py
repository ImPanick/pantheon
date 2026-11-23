# SPDX-License-Identifier: AGPL-3.0-or-later
"""Apollo's pane, driven: what it shows, and what each button asks the server.

The pane (`static/js/apolloPane.js`) is the outline's *Surfaces* section: a
status line, Text, Needs you, the Computer card, Activity, Outputs, Open
loops, and What Apollo knows; a task's own view with its budget, Start or Run
again and Chat with this agent. It decides nothing: every answer is
`routes/apollo_routes.py`'s.

Driven under node: the real `apolloPane.js` and `apolloPaneModel.js` on the
shared DOM shim (`test_tool_effect_surfaces_js`), the server faked by path.
Each case says what the person would see or what reached the server.
"""
from __future__ import annotations

import json
import shutil
import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parent))

from test_tool_effect_surfaces_js import _make_sandbox, _run  # noqa: E402

ROOT = Path(__file__).resolve().parents[1]
PANE = ROOT / "static" / "js" / "apolloPane.js"

pytestmark = pytest.mark.skipif(not shutil.which("node"), reason="node binary not on PATH")

_SHIM = r"""
import { installDom, Node } from './dom.js';
export const document = installDom();
export { Node };
export const sent = [];
export const opened = { session: null, screen: 0, phone: 0, calls: 0 };
export const toasts = [];
// Each route's answer: a function of (method, url, body) → [status, json].
export const routes = {};
globalThis.fetch = async (url, opts = {}) => {
  const method = (opts.method || 'GET').toUpperCase();
  const body = typeof opts.body === 'string' ? JSON.parse(opts.body)
    : (opts.body instanceof FormData ? Object.fromEntries(opts.body) : undefined);
  sent.push({ method, url: String(url), body });
  const path = String(url).split('?')[0];
  const key = Object.keys(routes).sort((a, b) => b.length - a.length)
    .find((k) => { const [m, p] = k.split(' '); return m === method && (p === path || (p.endsWith('*') && path.startsWith(p.slice(0, -1)))); });
  const [status, json, raw] = key ? routes[key](method, String(url), body) : [404, { detail: 'not faked' }];
  return { ok: status < 400, status, json: async () => json, text: async () => (raw !== undefined ? raw : JSON.stringify(json)) };
};
export function settle(n = 12) {
  let p = Promise.resolve();
  for (let i = 0; i < n; i++) p = p.then(() => new Promise((r) => setTimeout(r, 0)));
  return p;
}
export function all(root, cls) { return root._walk([]).filter((n) => n._classes && n._classes().includes(cls)); }
export function text(n) { return n ? n.textContent : null; }
export function buttons(root) { return root._walk([]).filter((n) => n.tagName === 'BUTTON'); }
export function button(root, words) { return buttons(root).find((b) => b.textContent === words) || null; }
export function submit(form) { form.dispatchEvent({ type: 'submit', preventDefault() {}, stopPropagation() {} }); }
"""

_STUBS = {
    "modalManager.js": (
        "const reg = new Map();\n"
        "export function register(id, fns) { reg.set(id, fns); }\n"
        "export function isRegistered(id) { return reg.has(id); }\n"
        "export function isMinimized() { return false; }\n"
        "export function restore() {}\n"
        "export function showWindow() {}\n"
        "export function injectMinimizeButton() {}\n"
        "export function close(id) { const f = reg.get(id); reg.delete(id); if (f) f.closeFn(); }\n"
    ),
    "windowDrag.js": "export function makeWindowDraggable() {}\n",
    "sessions.js": (
        "import { opened } from './shim.js';\n"
        "export async function selectSession(id) { opened.session = id; }\n"
    ),
    "ui.js": "import { toasts } from './shim.js';\nexport default { showToast: (m) => toasts.push(m) };\n",
    "voiceCall.js": (
        "import { opened } from './shim.js';\n"
        "export function toggleVoiceCall() { opened.calls += 1; }\n"
        "export function isVoiceCallActive() { return opened.calls % 2 === 1; }\n"
    ),
    "phoneWindow.js": (
        "import { opened } from './shim.js';\n"
        "export function openPhone() { opened.phone += 1; }\n"
    ),
    "workstationScreen.js": (
        "import { opened } from './shim.js';\n"
        "export function openWorkstationScreen() { opened.screen += 1; }\n"
    ),
}

_PREAMBLE = (
    "import { document, sent, opened, toasts, routes, settle, all, text, buttons, button, submit } from './shim.js';\n"
    "const P = await import('./apolloPane.js');\n"
    "const out = (o) => console.log(JSON.stringify(o));\n"
    "const pane = () => document.getElementById('apollo-pane-modal');\n"
    "const T = (id, state, extra = {}) => ({ id, title: `Task ${id}`, state, state_words: state,\n"
    "  updated_at: `2026-11-2${id.length}T10:00:0${id.slice(-1)}Z`, created_at: '2026-11-20T00:00:00Z',\n"
    "  lead_agent: 'researcher', hire_id: null, session_id: null, budget_tokens: null, spent_tokens: 0,\n"
    "  budget_limit: 2000000, ...extra });\n"
    "routes['GET /api/workstation/status'] = () => [200, { state: 'up', sentence: 'Your workstation is running.' }];\n"
    "routes['GET /api/apollo/notebook'] = () => [200, { notes: [{ id: 'n1', kind: 'open_loop', text: 'Reply to the landlord', state: 'open' }] }];\n"
    "routes['GET /api/apollo/state'] = () => [200, { name: 'Apollo', status: { state: 'needs_you', words: 'Needs you' }, goal_token_cap: 2000000 }];\n"
    "routes['GET /api/apollo/approvals'] = () => [200, { approvals: [] }];\n"
    "routes['GET /api/workstation/phone'] = () => [200, { state: 'off', device: 'pixel', devices: [{ id: 'pixel', name: 'Pixel 9' }] }];\n"
)


@pytest.fixture(scope="module")
def box(tmp_path_factory):
    return _make_sandbox(tmp_path_factory.mktemp("apollopane"), PANE, _SHIM, _STUBS)


def _case(box, script):
    return _run(box, _PREAMBLE, script + "\nP.closeApolloPane();\n")


def test_the_main_view_shows_what_needs_you_and_the_work(box):
    o = _case(box, """
        const many = Array.from({ length: 9 }, (_, i) => T(`w${i}`, 'working'));
        routes['GET /api/apollo/tasks'] = () => [200, { tasks: [
          T('a1', 'needs_you', { question: 'Which week suits you?' }),
          T('d1', 'done', { outcome: 'Booked the plumber for Tuesday.', done_at: '2026-11-22T00:00:00Z' }),
          ...many,
        ] }];
        P.openApolloPane();
        await settle();
        const p = pane();
        out({
          status: text(all(p, 'apo-status')[0]),
          questions: all(p, 'apo-q').map(text),
          rows: all(p, 'apo-row').length,
          more: buttons(p).map((b) => b.textContent).filter((t) => /more/.test(t)),
          outputs: all(p, 'apo-out-line').map(text),
          loops: all(p, 'apo-loop-t').map(text),
          computer: text(all(p, 'apo-card-state')[0]),
        });
    """)
    assert o["status"] == "Needs you"
    assert o["questions"] == ["Which week suits you?"]
    assert o["rows"] == 6
    assert o["more"] == ["Show 5 more"]
    assert o["outputs"] == ["Booked the plumber for Tuesday."]
    assert o["loops"] == ["Reply to the landlord"]
    assert o["computer"] == "Running"


def test_an_answer_goes_to_its_task_and_a_loop_settles(box):
    o = _case(box, """
        routes['GET /api/apollo/tasks'] = () => [200, { tasks: [T('a1', 'needs_you', { question: 'Which week?' })] }];
        routes['POST /api/apollo/tasks/*'] = () => [200, { ...T('a1', 'working'), started: true }];
        routes['PATCH /api/apollo/notebook/*'] = () => [200, { id: 'n1', state: 'settled' }];
        P.openApolloPane();
        await settle();
        const p = pane();
        const form = all(p, 'apo-answer')[0];
        all(form, 'apo-input')[0].value = 'The second week';
        submit(form);
        await settle();
        button(pane(), 'Settled').click();
        await settle();
        out({ writes: sent.filter((s) => s.method !== 'GET'), toasts });
    """)
    assert o["writes"][0] == {"method": "POST", "url": "/api/apollo/tasks/a1/answer",
                              "body": {"answer": "The second week"}}
    assert o["writes"][1] == {"method": "PATCH", "url": "/api/apollo/notebook/n1",
                              "body": {"state": "settled"}}
    assert "Sent. The lead is back on it." in o["toasts"]


def test_a_task_view_sets_a_budget_starts_it_and_keeps_its_chat_under_the_report(box):
    o = _case(box, """
        const t = T('r1', 'waiting', { brief: 'Find a dentist open Saturdays', hire_id: 'h1', session_id: 's-r1',
                                       budget_tokens: 100000, budget_limit: 100000, spent_tokens: 12000 });
        routes['GET /api/apollo/tasks'] = () => [200, { tasks: [t] }];
        routes['GET /api/apollo/tasks/*'] = () => [200, t];
        routes['PATCH /api/apollo/tasks/*'] = (m, u, b) => [200, { ...t, budget_tokens: b.budget_tokens }];
        routes['POST /api/apollo/tasks/*'] = () => [200, { ...t, state: 'working', started: true }];
        routes['GET /api/apollo/tasks/r1/chat'] = () => [200, { task_id: 'r1', session_id: 's-r1', title: t.title, lead: 'Researcher', lead_agent: 'researcher', state: 'waiting' }];
        routes['GET /api/history/*'] = () => [200, { history: [
          { role: 'user', content: 'Saturdays only, please' },
          { role: 'tool', content: 'search results' },
          { role: 'assistant', content: 'Two are open Saturdays.' },
        ] }];
        P.openApolloPane();
        await settle();
        all(pane(), 'apo-row-b')[0].click();
        await settle();
        const p = pane();
        const facts = all(p, 'apo-fact-v').map(text);
        const budget = text(all(p, 'apo-budget-line')[0]);
        const form = all(p, 'apo-budget-form')[0];
        all(form, 'apo-input')[0].value = '250k';
        submit(form);
        await settle();
        button(pane(), 'Run again').click();
        await settle();
        const chat = all(pane(), 'apo-chat')[0];
        const lines = all(chat, 'apo-msg-t').map(text);
        const wide = pane()._classes().includes('apo-wide');
        const before = chat;
        P.closeApolloPane(); P.openApolloPane(); await settle();
        all(pane(), 'apo-row-b')[0].click();
        await settle(30);
        const kept = all(pane(), 'apo-chat').length;
        out({ facts, budget, writes: sent.filter((s) => s.method !== 'GET'), opened, lines, wide,
              popOut: !!button(pane(), 'Pop out chat'), kept, sessionOpened: opened.session });
    """)
    assert "Find a dentist open Saturdays" in o["facts"]
    assert o["budget"] == "12k of 100k tokens on paid models. Local models run uncapped."
    assert o["writes"][0] == {"method": "PATCH", "url": "/api/apollo/tasks/r1",
                              "body": {"budget_tokens": 250000}}
    assert o["writes"][1]["url"] == "/api/apollo/tasks/r1/start"
    # The task's chat sits under the report, in the lead's words, and the main
    # chat is never switched away (the outline: the main chat stays live).
    assert o["lines"] == ["Saturdays only, please", "Two are open Saturdays."]
    assert o["wide"] is True
    assert o["popOut"] is True
    assert o["kept"] == 1
    assert o["sessionOpened"] is None


def test_what_apollo_knows_splits_stated_from_inferred_and_each_can_be_changed(box):
    o = _case(box, """
        routes['GET /api/apollo/tasks'] = () => [200, { tasks: [] }];
        routes['GET /api/apollo/knows'] = () => [200, { lines: [
          { id: 'k1', text: 'Never book me before 10', basis: 'stated', since: 2 },
          { id: 'k2', text: 'Prefers aisle seats', basis: 'inferred', evidence: 'picked the aisle twice', since: 1 },
        ] }];
        routes['POST /api/apollo/knows'] = (m, u, b) => [200, { id: 'k3', text: b.text, basis: 'stated' }];
        routes['POST /api/apollo/knows/*'] = () => [200, { id: 'k2', basis: 'stated' }];
        routes['DELETE /api/apollo/knows/*'] = () => [200, { forgotten: true }];
        P.openApolloPane();
        await settle();
        button(pane(), 'What Apollo knows').click();
        await settle();
        let p = pane();
        const stated = all(p, 'apo-line-stated').map((n) => text(all(n, 'apo-line-t')[0]));
        const inferred = all(p, 'apo-line-inferred').map((n) => text(all(n, 'apo-line-t')[0]));
        const why = all(p, 'apo-line-why').map(text);
        const confirmOnStated = all(p, 'apo-line-stated').some((n) => button(n, 'That is right'));
        button(all(p, 'apo-line-inferred')[0], 'That is right').click();
        await settle();
        button(all(pane(), 'apo-line-stated')[0], 'Forget').click();
        await settle();
        const add = all(pane(), 'apo-add')[0];
        all(add, 'apo-input')[0].value = 'My sister is Maya';
        submit(add);
        await settle();
        out({ stated, inferred, why, confirmOnStated, writes: sent.filter((s) => s.method !== 'GET') });
    """)
    assert o["stated"] == ["Never book me before 10"]
    assert o["inferred"] == ["Prefers aisle seats"]
    assert o["why"] == ["From: picked the aisle twice"]
    assert o["confirmOnStated"] is False
    assert [(w["method"], w["url"]) for w in o["writes"]] == [
        ("POST", "/api/apollo/knows/k2/confirm"),
        ("DELETE", "/api/apollo/knows/k1"),
        ("POST", "/api/apollo/knows"),
    ]
    assert o["writes"][2]["body"] == {"text": "My sister is Maya"}


def test_server_words_are_text_never_markup(box):
    """A title someone else could have written (a lead's report, a forwarded
    ask) is drawn as text: no node's markup carries it."""
    o = _case(box, """
        const evil = '<img src=x onerror=alert(1)>';
        routes['GET /api/apollo/tasks'] = () => [200, { tasks: [T('x1', 'needs_you', { title: evil, question: evil })] }];
        P.openApolloPane();
        await settle();
        const nodes = pane()._walk([]);
        out({ asText: nodes.filter((n) => n.textContent === evil).length,
              inMarkup: nodes.filter((n) => (n.innerHTML || '').includes('onerror')).length });
    """)
    assert o["asText"] >= 2
    assert o["inMarkup"] == 0


def test_a_refusal_is_shown_in_the_servers_words(box):
    o = _case(box, """
        routes['GET /api/apollo/tasks'] = () => [200, { tasks: [T('z1', 'waiting')] }];
        routes['GET /api/apollo/tasks/*'] = () => [404, { detail: "That task isn't one of yours." }];
        P.openApolloPane();
        await settle();
        all(pane(), 'apo-row-b')[0].click();
        await settle();
        out({ error: text(all(pane(), 'apo-error')[0]), back: !!button(pane(), '‹ Back') });
    """)
    assert o["error"] == "That task isn't one of yours."
    assert o["back"] is True


def test_closing_the_pane_removes_it(box):
    o = _case(box, """
        routes['GET /api/apollo/tasks'] = () => [200, { tasks: [] }];
        P.openApolloPane();
        await settle();
        const had = !!pane();
        P.closeApolloPane();
        out({ had, gone: !pane(), open: P.isApolloPaneOpen() });
    """)
    assert o == {"had": True, "gone": True, "open": False}


# ── the dock and the door, read from source ─────────────────────────────────

def test_the_pane_docks_and_opens_only_from_the_apollo_chat():
    ws = (ROOT / "static" / "js" / "cockpitWorkspace.js").read_text(encoding="utf-8")
    assistant = (ROOT / "static" / "js" / "assistant.js").read_text(encoding="utf-8")
    css = (ROOT / "static" / "cockpit.css").read_text(encoding="utf-8")
    assert "apollo: { label: 'Apollo'" in ws and "'.modal.apo-modal'" in ws
    assert "m.openApolloPane()" in ws
    assert 'html.cockpit .ck-switch .ck-surf[data-surf="apollo"] { display: none; }' in css
    assert 'html.cockpit.apollo-chat .ck-switch .ck-surf[data-surf="apollo"] { display: inline-flex; }' in css
    # The header button is built only after the Apollo session check passes.
    body = assistant[assistant.index("async function _ensureHeaderAffordances("):]
    assert body.index("if (!isApollo) return;") < body.index("_ensurePaneButton(headerRight)")
