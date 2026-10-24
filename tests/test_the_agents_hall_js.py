# SPDX-License-Identifier: AGPL-3.0-or-later
"""`P24-12` / `P24-13` / `P24-14` (first cut) — the Agents hall, driven under node.

The real `static/js/agents/agentsWindow.js` and its data layer `agentsApi.js`,
against the real `modalManager.js` (the workstation screen's harness, which
loads it with the dock's shim) and the real `workbench/refusal.js`, with a
recorded `fetch` answering in the shapes `routes/agent_routes.py` answers.
`windowDrag.js` and `ui.js` are the workstation harness's stubs.

What is pinned, and why each is a defect if it breaks:

  * **the board** — *Your agents* with its count, the search box naming how
    many agents there are, a chip per section that has agents and *All*, the
    sections in the server's order with *Show more* past a row, **Hired** on
    this person's own hires only (also in an admin's Everyone view);
  * **finding one** — the search and a chip narrow the catalogue, and a search
    with no match says so instead of drawing an empty page;
  * **hiring** — an agent's page says what it may do in words, names the tools
    this person's runs will lack, shows its runbook, and its form posts the
    typed values with the browser's zone; the hire's page follows;
  * **running it** — *Run now* is the hire's task's own route, *Pause* and
    *Fire* are the hire's, Fire asks first and a no does nothing;
  * **the server's words** — a refusal is shown as its sentence;
  * **text stays text** — a name with markup in it is drawn as letters.
"""
from __future__ import annotations

import shutil
from pathlib import Path

import pytest

from test_the_workstation_screen_window_js import _SHIM as _WS_SHIM, _STUBS as _WS_STUBS  # noqa: E402
from test_tool_effect_surfaces_js import _make_sandbox, _run  # noqa: E402

ROOT = Path(__file__).resolve().parents[1]
JS = ROOT / "static" / "js"
pytestmark = pytest.mark.skipif(not shutil.which("node"), reason="node binary not on PATH")

# The workstation harness's DOM additions, without its workstation server: a
# second `globalThis.fetch` below replaces that one, answering as the hall's.
_SHIM = _WS_SHIM + r"""
// ── the Agents hall's server ───────────────────────────────────────────────
const agent = (id, section, extra = {}) => ({
  id, name: extra.name || id.replace(/-/g, ' ').replace(/\b\w/g, (c) => c.toUpperCase()),
  tagline: `The ${id} job.`, section, section_label: section, version: '1.0.0', wave: 1,
  starred: !!extra.starred, icon: '', inputs: extra.inputs || [], triggers: [], tools: ['web_search'],
  needs: {}, delivers: [], effects: {}, budget: {}, memory: 'own', runbook: '1. Do it.',
  source: 'shipped', starts_on: 'daily at 07:00',
});
export const hall = {
  me: 'alice', is_admin: false,
  families: [{ id: 'everyday', label: 'Everyday' }],
  sections: [
    { id: 'email', label: 'Email & Inbox', family: 'everyday', count: 2 },
    { id: 'learning', label: 'Learning & Coaching', family: 'everyday', count: 0 },
    { id: 'research', label: 'Research & Intelligence', family: 'knowledge', count: 1 },
  ],
  agents: [agent('inbox-triage', 'email', { starred: true }), agent('meeting-catcher', 'email'),
           agent('topic-watcher', 'research', { inputs: [
             { key: 'topics', kind: 'list', label: 'Topics to watch' },
             { key: 'at', kind: 'time', label: 'When', default: '07:00' },
             { key: 'deep', kind: 'boolean', label: 'Go deep', optional: true }] })],
  broken: [], hires: [], everyone: false, teams: [], projects: [],
  ceilings: { paused: false, max_concurrent: 2 },
  template: '---\nid: my-agent\n---\n1. One numbered step.',
};
export const hallServer = { calls: [], refuse: {} };
const hireOf = (agentId, owner = 'alice') => ({
  id: `h-${agentId}`, agent_id: agentId, name: hall.agents.find((a) => a.id === agentId).name,
  owner, version: '1.0.0', status: 'on', attention: null, inputs: {}, grants: {},
  tasks: [{ id: `t-${agentId}`, trigger_type: 'schedule', webhook_token: null }],
  next_run: '2026-10-23T07:00:00Z', last_run: null, notebook: '', starts_on: 'daily at 07:00',
  effects: { read_public: 'allow', external_side_effect: 'ask' }, lacking: [], runs: [],
});
globalThis.fetch = async (url, opts = {}) => {
  const method = opts.method || 'GET';
  const body = opts.body ? JSON.parse(opts.body) : null;
  hallServer.calls.push({ url, method, body });
  const reply = (status, payload) => ({ ok: status >= 200 && status < 300, status, json: async () => payload });
  const key = `${method} ${String(url).split('?')[0]}`;
  if (hallServer.refuse[key]) return reply(400, { detail: hallServer.refuse[key] });
  if (key === 'GET /api/agents') {
    const everyone = String(url).includes('everyone=1');
    return reply(200, { ...hall, everyone, hires: everyone ? hall.hires : hall.hires.filter((h) => h.owner === 'alice') });
  }
  let m = key.match(/^GET \/api\/agents\/hires\/(.+)$/);
  if (m) {
    const h = hall.hires.find((x) => x.id === decodeURIComponent(m[1]));
    return h ? reply(200, { ...h, agent: hall.agents.find((a) => a.id === h.agent_id) })
             : reply(404, { detail: 'There is no such hire.' });
  }
  m = key.match(/^POST \/api\/agents\/hires\/(.+)\/status$/);
  if (m) { const h = hall.hires.find((x) => x.id === m[1]); h.status = body.status; return reply(200, h); }
  m = key.match(/^DELETE \/api\/agents\/hires\/(.+)$/);
  if (m) {
    const h = hall.hires.find((x) => x.id === m[1]);
    hall.hires = hall.hires.filter((x) => x !== h);
    return reply(200, { ok: true, fired: h.name, tasks_removed: 1 });
  }
  m = key.match(/^POST \/api\/agents\/teams\/(.+)\/hire$/);
  if (m) {
    const t = hall.teams.find((x) => x.id === m[1]);
    const made = t.members.filter((x) => !x.hired).map((x) => hireOf(x.id));
    hall.hires.push(...made);
    t.members.forEach((x) => { x.hired = true; });
    t.hired = t.members.length;
    return reply(200, { team: t.name, hired: made, kept: [] });
  }
  m = key.match(/^POST \/api\/agents\/(.+)\/try$/);
  if (m) { const h = { ...hireOf(m[1]), status: 'trial', started: true }; hall.hires.push(h); return reply(200, h); }
  if (key === 'GET /api/tasks/waiting') return reply(200, { waiting: hallServer.waiting || [] });
  m = key.match(/^POST \/api\/tasks\/(.+)\/runs\/(.+)\/answer$/);
  if (m) {
    hallServer.waiting = [];
    return reply(200, { outcome: body.decision === 'deny' ? 'denied' : 'resumed',
                        sentence: body.decision === 'deny' ? 'Denied by alice.' : 'Allowed once by alice.' });
  }
  // `P24-20`. The workshop's four doors.
  m = key.match(/^GET \/api\/agents\/(.+)\/source$/);
  if (m) {
    const a = hall.agents.find((x) => x.id === m[1]);
    return reply(200, { id: a.id, source: a.source, shadows: false, text: `---\nid: ${a.id}\n---\n1. Do it.` });
  }
  if (key === 'POST /api/agents/own') {
    if (body.text.includes('bad')) return reply(422, { detail: 'The id “Bad” is not lower-case words joined by dashes.' });
    const id = (body.text.match(/id: (\S+)/) || [])[1];
    if (body.dry) return reply(200, { ok: true, id, shadows: false, sentence: 'It passes its check.' });
    let a = hall.agents.find((x) => x.id === id);
    const shadows = !!a;
    if (!a) { a = agent(id, 'research'); hall.agents.push(a); }
    a.source = 'own';
    return reply(200, { ok: true, id, shadows, sentence: shadows ? `Kept. Your copy of ${a.name} is the one you see and summon; everyone else still has the shipped one.` : `Kept. ${a.name} is in the hall, for you.` });
  }
  m = key.match(/^DELETE \/api\/agents\/own\/(.+)$/);
  if (m) { hall.agents.find((x) => x.id === m[1]).source = 'shipped'; return reply(200, { ok: true, back_to_shipped: true }); }
  if (key === 'POST /api/agents/draft') {
    if (!body.description) return reply(400, { detail: 'Say what the agent should do.' });
    return reply(200, { ok: true, text: '---\nid: drafted-one\n---\n1. Drafted.', sentence: 'Drafted. Read every field, then save it.' });
  }
  m = key.match(/^POST \/api\/agents\/(.+)\/hire$/);
  if (m) { const h = hireOf(m[1]); hall.hires.push(h); return reply(200, h); }
  m = key.match(/^GET \/api\/agents\/(.+)$/);
  if (m) {
    const a = hall.agents.find((x) => x.id === decodeURIComponent(m[1]));
    return a ? reply(200, { ...a, effects: { read_public: 'allow', network_egress: 'ask', destructive: 'never' },
                            lacking: [{ tool: 'bash', reason: 'runs commands on the server' }] })
             : reply(404, { detail: 'There is no agent called that in the hall.' });
  }
  m = key.match(/^POST \/api\/tasks\/(.+)\/run$/);
  if (m) return reply(200, { ok: true });
  return reply(404, { detail: 'no such route' });
};
export { hireOf };
export function texts(node, cls) {
  return node.querySelectorAll('.' + cls).map((n) => n.textContent);
}
"""

_PREAMBLE = (
    "import { document, fire, settle, hallServer as server, hall, hireOf, texts } from './shim.js';\n"
    "const mod = await import('./agents/agentsWindow.js');\n"
    "const win = () => mod._test.win();\n"
    "const body = () => win().body;\n"
    "const q = (sel) => body().querySelectorAll(sel);\n"
    "const press = async (node) => { fire(node, 'click'); await settle(30); };\n"
    "const out = (o) => { console.log(JSON.stringify(o)); process.exit(0); };\n"
    "Intl.DateTimeFormat = () => ({ resolvedOptions: () => ({ timeZone: 'Australia/Sydney' }) });\n"
)


@pytest.fixture(scope="module")
def sandbox(tmp_path_factory):
    d = tmp_path_factory.mktemp("agents-hall")
    # The workstation window's sandbox lays out `static/js/` at its root with
    # the dock's real `modalManager.js`; the hall's three files go where their
    # own relative imports look for them.
    _make_sandbox(d, JS / "workstationScreen.js", _SHIM, _WS_STUBS)
    for rel in ("agents/agentsWindow.js", "agents/agentsApi.js", "workbench/refusal.js"):
        (d / rel).parent.mkdir(parents=True, exist_ok=True)
        shutil.copy(JS / rel, d / rel)
    return d


def _hall(sandbox, script):
    return _run(sandbox, _PREAMBLE, script)


# ── the pure parts ──────────────────────────────────────────────────────────

def test_a_search_and_a_chip_narrow_the_catalogue(sandbox):
    out = _hall(sandbox, """
        const ids = (xs) => xs.map((a) => a.id);
        out({
          all: ids(mod.filterAgents(hall.agents, '', '')),
          word: ids(mod.filterAgents(hall.agents, 'MEETING', '')),
          tag: ids(mod.filterAgents(hall.agents, 'topic-watcher job', '')),
          chip: ids(mod.filterAgents(hall.agents, '', 'email')),
          both: ids(mod.filterAgents(hall.agents, 'inbox', 'research')),
          groups: mod.groupBySection(hall.sections, hall.agents).map((g) => [g.id, g.agents.length]),
        });
    """)
    assert out == {"all": ["inbox-triage", "meeting-catcher", "topic-watcher"], "word": ["meeting-catcher"],
                   "tag": ["topic-watcher"], "chip": ["inbox-triage", "meeting-catcher"], "both": [],
                   "groups": [["email", 2], ["research", 1]]}


# ── the board ───────────────────────────────────────────────────────────────

def test_the_board_is_laid_out_as_the_server_says(sandbox):
    out = _hall(sandbox, """
        hall.hires = [hireOf('meeting-catcher'), hireOf('inbox-triage', 'bob')];
        await mod.openAgents(); await settle(30);
        const cards = q('.agents-card').filter((c) => c.dataset.agent);
        out({
          inBody: document.getElementById('agents-modal') === win().modal,
          strip: texts(body(), 'agents-count'),
          search: q('.agents-search')[0].placeholder,
          chips: texts(body(), 'agents-chip'),
          sections: q('.agents-section').map((s) => s.dataset.section),
          hired: cards.filter((c) => c.querySelectorAll('.agents-hired').length).map((c) => c.dataset.agent),
          starred: cards.filter((c) => c.querySelectorAll('.agents-star').length).map((c) => c.dataset.agent),
          gets: server.calls.map((c) => c.url),
        });
    """)
    assert out["inBody"] is True
    assert out["strip"] == ["1 summoned"], "the strip is this person's own hires"
    assert out["search"] == "Search 3 agents…"
    assert out["chips"] == ["All 3", "Email & Inbox 2", "Research & Intelligence 1"]
    assert out["sections"] == ["email", "research"], "an empty section is not drawn"
    assert out["hired"] == ["meeting-catcher"] and out["starred"] == ["inbox-triage"]
    assert out["gets"] == ["/api/agents"]


def test_searching_with_no_match_says_so_and_a_chip_keeps_its_section(sandbox):
    out = _hall(sandbox, """
        await mod.openAgents(); await settle(30);
        const box = q('.agents-search')[0];
        box.value = 'zebra'; fire(box, 'input');
        const none = texts(body(), 'agents-empty');
        box.value = ''; fire(box, 'input');
        await press(q('.agents-chip').find((c) => c.dataset.section === 'research'));
        out({ none, sections: q('.agents-section').map((s) => s.dataset.section),
              selected: q('.agents-chip').filter((c) => c.getAttribute('aria-selected') === 'true')
                .map((c) => c.dataset.section) });
    """)
    assert "No agent matches that. Try fewer words." in out["none"]
    assert out["sections"] == ["research"] and out["selected"] == ["research"]


def test_a_section_past_one_row_shows_more_on_request(sandbox):
    out = _hall(sandbox, """
        for (let i = 0; i < 9; i++) hall.agents.push({ ...hall.agents[1], id: `extra-${i}`, name: `Extra ${i}` });
        await mod.openAgents(); await settle(30);
        const email = () => q('.agents-section').find((s) => s.dataset.section === 'email');
        const before = email().querySelectorAll('.agents-card').length;
        const more = email().querySelectorAll('.agents-link')[0];
        const label = more.textContent;
        await press(more);
        out({ before, label, after: email().querySelectorAll('.agents-card').length });
    """)
    assert out == {"before": 6, "label": "Show more (5)", "after": 11}


# ── hiring ──────────────────────────────────────────────────────────────────

def test_an_agents_page_says_what_it_may_do_and_the_form_hires_it(sandbox):
    out = _hall(sandbox, """
        await mod.openAgents(); await settle(30);
        await press(q('.agents-card').find((c) => c.dataset.agent === 'topic-watcher'));
        const page = {
          effects: q('.agents-effect').map((li) => li.textContent),
          lacking: texts(body(), 'agents-lacking'),
          runbook: q('.agents-runbook')[0].querySelectorAll('.agents-pre')[0].textContent,
          fields: q('[data-input]').map((f) => [f.dataset.input, f.tagName, f.type || '', f.value]),
        };
        q('[data-input="topics"]')[0].value = 'solar\\nwind, tides';
        q('[data-input="deep"]')[0].checked = true;
        fire(q('.agents-form')[0], 'submit');
        await settle(60);
        const post = server.calls.find((c) => c.method === 'POST');
        out({ page, post, view: mod._test.state().view, note: win().note.textContent });
    """)
    page = out["page"]
    assert page["effects"] == ["read public pageswithout asking", "reach other sites and machinesasks you first",
                               "delete thingsnever"]
    assert "bash — runs commands on the server" in page["lacking"][0]
    assert page["runbook"] == "1. Do it."
    assert page["fields"] == [["topics", "TEXTAREA", "", ""], ["at", "INPUT", "time", "07:00"],
                              ["deep", "INPUT", "checkbox", ""]]
    assert out["post"] == {"url": "/api/agents/topic-watcher/hire", "method": "POST", "body": {
        "inputs": {"topics": ["solar", "wind", "tides"], "at": "07:00", "deep": True},
        "tz_name": "Australia/Sydney", "project": None}}
    assert out["view"] == "hire" and out["note"].startswith("Topic Watcher is summoned.")


def test_a_refused_hire_shows_the_servers_sentence(sandbox):
    out = _hall(sandbox, """
        server.refuse['POST /api/agents/topic-watcher/hire'] = '“Topics to watch” needs an answer.';
        await mod.openAgents(); await settle(30);
        await press(q('.agents-card').find((c) => c.dataset.agent === 'topic-watcher'));
        fire(q('.agents-form')[0], 'submit'); await settle(40);
        out({ note: win().note.textContent, error: win().note.classList.contains('agents-note-error'),
              view: mod._test.state().view });
    """)
    assert out == {"note": "“Topics to watch” needs an answer.", "error": True, "view": "agent"}


# ── a hire's page ───────────────────────────────────────────────────────────

def test_run_now_pause_and_fire(sandbox):
    out = _hall(sandbox, """
        hall.hires = [hireOf('meeting-catcher')];
        await mod.openAgents(); await settle(30);
        await press(q('.agents-hire-card')[0]);
        const buttons = () => q('.agents-actions')[0].querySelectorAll('button').map((b) => b.textContent);
        const first = buttons();
        await press(q('.agents-actions')[0].querySelectorAll('button').find((b) => b.textContent === 'Run now'));
        await press(q('.agents-actions')[0].querySelectorAll('button').find((b) => b.textContent === 'Pause'));
        const afterPause = buttons();
        globalThis.__confirmAnswer = false;
        await press(q('.agents-actions')[0].querySelectorAll('button').find((b) => b.textContent === 'Dismiss…'));
        const keptOnNo = hall.hires.length;
        globalThis.__confirmAnswer = true;
        await press(q('.agents-actions')[0].querySelectorAll('button').find((b) => b.textContent === 'Dismiss…'));
        await settle(40);
        out({ first, afterPause, keptOnNo, left: hall.hires.length, view: mod._test.state().view,
              note: win().note.textContent,
              writes: server.calls.filter((c) => c.method !== 'GET').map((c) => [c.method, c.url, c.body]) });
    """)
    assert out["first"] == ["Run now", "Pause", "Dismiss…"]
    assert out["afterPause"] == ["Switch on", "Dismiss…"], "a paused hire's task does not run, so it is not offered"
    assert out["keptOnNo"] == 1 and out["left"] == 0 and out["view"] == "hall"
    assert out["note"] == "Meeting Catcher is dismissed; 1 task removed."
    assert out["writes"] == [
        ["POST", "/api/tasks/t-meeting-catcher/run", {}],
        ["POST", "/api/agents/hires/h-meeting-catcher/status", {"status": "paused"}],
        ["DELETE", "/api/agents/hires/h-meeting-catcher", None],
    ]


def test_an_admin_sees_everyone_and_hired_stays_their_own(sandbox):
    out = _hall(sandbox, """
        hall.is_admin = true;
        hall.hires = [hireOf('inbox-triage', 'bob')];
        await mod.openAgents(); await settle(30);
        const box = q('.agents-everyone')[0].querySelectorAll('input')[0];
        box.checked = true; fire(box, 'change'); await settle(40);
        const cards = q('.agents-card').filter((c) => c.dataset.agent);
        out({ heading: texts(body(), 'agents-h')[0], strip: texts(body(), 'agents-count'),
              owners: q('.agents-hire-card').map((c) => c.textContent.includes('bob')),
              hired: cards.filter((c) => c.querySelectorAll('.agents-hired').length).length,
              urls: server.calls.map((c) => c.url) });
    """)
    assert out["heading"] == "Everyone's agents" and out["strip"] == ["1 summoned"]
    assert out["owners"] == [True] and out["hired"] == 0
    assert out["urls"] == ["/api/agents", "/api/agents?everyone=1"]


def test_text_from_a_manifest_is_drawn_as_letters(sandbox):
    out = _hall(sandbox, """
        hall.agents[0].name = '<img src=x onerror=alert(1)>';
        hall.agents[0].tagline = '<b>bold</b>';
        await mod.openAgents(); await settle(30);
        const card = q('.agents-card').find((c) => c.dataset.agent === 'inbox-triage');
        const name = card.querySelectorAll('.agents-card-name')[0];
        out({ text: name.textContent, html: name.innerHTML,
              tag: card.querySelectorAll('.agents-card-tag')[0].textContent });
    """)
    assert out == {"text": "<img src=x onerror=alert(1)>", "html": "", "tag": "<b>bold</b>"}


# ── wave B: teams, a trial, questions, checks, the brakes ───────────────────

_TEAM = """
hall.teams = [{ id: 'inbox-zero', name: 'Inbox Zero', tagline: 'A clear mailbox.', about: 'Two hires.',
  members: [{ id: 'inbox-triage', name: 'Inbox Triage', hired: false },
            { id: 'meeting-catcher', name: 'Meeting Catcher', hired: false }],
  inputs: [{ key: 'vip', kind: 'list', label: 'People who matter', optional: true }], hired: 0 }];
"""


def test_team_action_words(sandbox):
    out = _hall(sandbox, """
        const t = (hired, n) => ({ hired, members: Array.from({ length: n }, (_, i) => ({ id: String(i) })) });
        out([mod.teamAction(t(0, 3)), mod.teamAction(t(1, 3)), mod.teamAction(t(3, 3))]);
    """)
    assert out == ["Summon all", "+2", "All summoned"]


def test_a_team_is_hired_from_its_page_with_its_shared_inputs_and_a_project(sandbox):
    out = _hall(sandbox, _TEAM + """
        hall.projects = ['shop', 'blog'];
        await mod.openAgents(); await settle(30);
        const card = q('.agents-team-card')[0];
        const onCard = [card.dataset.team, texts(card, 'agents-team-action')[0], card.querySelectorAll('.agents-avatar-small').length];
        await press(card);
        const members = q('.agents-card').filter((c) => c.dataset.agent).map((c) => c.dataset.agent);
        q('[data-input="vip"]')[0].value = 'ana@example.com';
        q('[data-project]')[0].value = 'shop';
        fire(q('.agents-form')[0], 'submit'); await settle(60);
        out({ onCard, members, post: server.calls.find((c) => c.method === 'POST'),
              note: win().note.textContent, view: mod._test.state().view,
              action: texts(body(), 'agents-team-action') });
    """)
    assert out["onCard"] == ["inbox-zero", "Summon all", 2]
    assert out["members"] == ["inbox-triage", "meeting-catcher"]
    assert out["post"] == {"url": "/api/agents/teams/inbox-zero/hire", "method": "POST", "body": {
        "inputs": {"vip": ["ana@example.com"]}, "tz_name": "Australia/Sydney", "project": "shop"}}
    assert out["note"] == "Inbox Zero: 2 agents summoned." and out["view"] == "hall"
    assert out["action"] == ["All summoned"]


def test_try_it_once_makes_a_trial_whose_page_offers_hire_and_discard(sandbox):
    out = _hall(sandbox, """
        await mod.openAgents(); await settle(30);
        await press(q('.agents-card').find((c) => c.dataset.agent === 'meeting-catcher'));
        await press(q('.agents-try')[0]); await settle(40);
        const buttons = q('.agents-actions')[0].querySelectorAll('button').map((b) => b.textContent);
        mod._test.stopPoll && mod._test.stopPoll();
        out({ post: server.calls.find((c) => c.method === 'POST'), buttons,
              status: texts(body(), 'agents-status'), note: win().note.textContent });
    """)
    assert out["post"]["url"] == "/api/agents/meeting-catcher/try"
    assert out["buttons"] == ["Run now", "Summon", "Discard…"]
    assert out["status"] == ["Trial"]
    assert out["note"].startswith("Trying Meeting Catcher once.")


def test_a_question_its_run_waits_on_is_answered_in_place(sandbox):
    out = _hall(sandbox, """
        hall.hires = [hireOf('meeting-catcher')];
        server.waiting = [
          { task_id: 't-meeting-catcher', run_id: 'r1', tool_label: 'bash',
            approval: { approval_id: 'ap-1', description: 'Runs a command.',
                        action: { tool: 'bash', content: 'printf <b>hi</b>' } } },
          { task_id: 't-someone-else', run_id: 'r2', tool_label: 'send_email', approval: { approval_id: 'ap-2' } },
        ];
        await mod.openAgents(); await settle(30);
        await press(q('.agents-hire-card')[0]);
        const asked = { what: texts(body(), 'agents-question-what'),
                        shown: q('.agents-question')[0].querySelectorAll('.agents-pre')[0].textContent };
        await press(q('.agents-question')[0].querySelectorAll('button').find((b) => b.textContent === 'Allow once'));
        await settle(40);
        out({ asked, post: server.calls.find((c) => c.method === 'POST'), note: win().note.textContent,
              after: q('.agents-question').length });
    """)
    assert out["asked"] == {"what": ["It wants to use bash."], "shown": "printf <b>hi</b>"}, \
        "only this hire's own question, its action as letters"
    assert out["post"] == {"url": "/api/tasks/t-meeting-catcher/runs/r1/answer", "method": "POST",
                           "body": {"approval_id": "ap-1", "decision": "approve_task"}}
    assert out["note"] == "Allowed once by alice." and out["after"] == 0


def test_a_runs_checks_are_listed_with_its_report(sandbox):
    out = _hall(sandbox, """
        const h = hireOf('meeting-catcher');
        h.runs = [{ id: 'r1', status: 'error', started_at: '2026-10-23T06:00:00Z', error: 'It did not deliver.',
                    report: { answer: 'x', summary: '', read: [], wrote: [], refused: [], repaired: true,
                      checks: [{ check: 'the answer', ok: true, detail: 'It answered.' },
                               { check: 'a document', ok: false, detail: 'No document was written in this run.' }] } }];
        hall.hires = [h];
        await mod.openAgents(); await settle(30);
        await press(q('.agents-hire-card')[0]);
        out({ ok: texts(body(), 'agents-check-ok'), failed: texts(body(), 'agents-check-failed'),
              repaired: texts(body(), 'agents-small').filter((t) => t.includes('one more try')) });
    """)
    assert out == {"ok": ["✓ It answered."], "failed": ["✗ No document was written in this run."],
                   "repaired": ["It took one more try to deliver."]}


@pytest.mark.parametrize("admin,tail", [(True, " in Settings → Agents."), (False, ".")])
def test_the_hall_says_when_an_admin_paused_every_agent(sandbox, admin, tail):
    out = _hall(sandbox, f"""
        hall.ceilings.paused = true; hall.is_admin = {str(admin).lower()};
        await mod.openAgents(); await settle(30);
        out(texts(body(), 'agents-paused-all'));
    """)
    assert out == ["An admin has paused all agents: nothing runs until they are switched back on" + tail]


def test_a_skipped_run_says_why(sandbox):
    out = _hall(sandbox, """
        const h = hireOf('meeting-catcher');
        h.runs = [{ id: 'r1', status: 'skipped', started_at: '2026-10-23T06:00:00Z', error: null, report: null,
                    said: 'An admin has paused all agents (Settings → Agents), so this run did not start.' }];
        hall.hires = [h];
        await mod.openAgents(); await settle(30);
        await press(q('.agents-hire-card')[0]);
        out({ line: texts(body(), 'agents-run-line'), status: texts(body(), 'agents-run-status') });
    """)
    assert out["status"] == ["Skipped"]
    assert out["line"] == ["An admin has paused all agents (Settings → Agents), so this run did not start."]


def test_a_card_says_what_was_measured_and_the_page_shows_a_sample(sandbox):
    out = _hall(sandbox, """
        hall.agents[2].fit = { badge: 'runs-well', words: 'Runs well', model: 'gpt-oss-20b',
          row: { model: 'gpt-oss-20b', runs: 10, pass_rate: 0.9, median_minutes: 2 } };
        hall.agents[1].fit = { badge: 'not-measured', words: 'Not measured', model: null, row: null };
        hall.agents[2].sample = { from: 'its evaluation, with a scripted model', read: ['web_search'], wrote: [],
                                  answer: '## solar\\n- <b>A record</b>' };
        hall.agents[2].eval_cases = 4;
        await mod.openAgents(); await settle(30);
        const badge = (id) => q('.agents-card').find((c) => c.dataset.agent === id).querySelectorAll('.agents-fit')[0];
        const cards = { tw: badge('topic-watcher').textContent, mc: badge('meeting-catcher').textContent,
                        none: q('.agents-card').find((c) => c.dataset.agent === 'inbox-triage').querySelectorAll('.agents-fit').length };
        await press(q('.agents-card').find((c) => c.dataset.agent === 'topic-watcher'));
        out({ cards, line: q('.agents-fit-line')[0].textContent,
              sample: q('.agents-sample')[0].querySelectorAll('.agents-pre')[0].textContent });
    """)
    assert out["cards"] == {"tw": "Runs well", "mc": "Not measured", "none": 0}
    assert out["line"] == "Runs well on gpt-oss-20b: 90% of 10 runs passed, median 2 min."
    assert out["sample"] == "## solar\n- <b>A record</b>", "a report is drawn as letters"


# ── `P24-20` · the workshop ─────────────────────────────────────────────────

def test_new_agent_drafts_checks_and_saves_and_the_hall_says_yours(sandbox):
    out = _hall(sandbox, """
        await mod.openAgents(); await settle(30);
        await press(q('.agents-new')[0]);
        const editor = () => q('.agents-editor')[0];
        const started = editor().value;
        const btn = (t) => q('button').find((b) => b.textContent === t);
        await press(btn('Draft it'));
        const empty = win().note.textContent;
        q('.agents-describe-text')[0].value = 'Watch my inbox';
        await press(btn('Draft it'));
        const drafted = editor().value;
        editor().value = '---\\nid: bad\\n---'; fire(editor(), 'input');
        await press(btn('Check'));
        const refused = win().note.textContent;
        editor().value = drafted; fire(editor(), 'input');
        await press(btn('Save')); await settle(30);
        const view = mod._test.state().view;
        const saved = win().note.textContent;
        await press(q('.agents-back')[0]);
        const yours = q('.agents-card').filter((c) => c.querySelectorAll('.agents-own').length).map((c) => c.dataset.agent);
        out({ started, empty, drafted, refused, view, saved, yours,
              posts: server.calls.filter((c) => c.method === 'POST').map((c) => [c.url, c.body.dry || false]) });
    """)
    assert out["started"] == "---\nid: my-agent\n---\n1. One numbered step.", "the server's template, one spelling"
    assert out["empty"] == "Say what the agent should do."
    assert "id: drafted-one" in out["drafted"]
    assert "not lower-case words" in out["refused"]
    assert out["view"] == "agent" and out["saved"].startswith("Kept. Drafted One is in the hall")
    assert out["yours"] == ["drafted-one"]
    assert out["posts"] == [["/api/agents/draft", False], ["/api/agents/draft", False],
                            ["/api/agents/own", True], ["/api/agents/own", False]]


def test_customise_loads_its_file_and_remove_my_copy_gives_the_shipped_one_back(sandbox):
    out = _hall(sandbox, """
        await mod.openAgents(); await settle(30);
        await press(q('.agents-card').find((c) => c.dataset.agent === 'inbox-triage'));
        const btn = (t) => q('button').find((b) => b.textContent === t);
        const noRemove = !btn('Remove my copy');
        await press(btn('Customise'));
        const text = q('.agents-editor')[0].value;
        const note = win().note.textContent;
        await press(btn('Save')); await settle(30);
        const saved = win().note.textContent;
        const edit = !!btn('Edit your file');
        await press(btn('Remove my copy')); await settle(30);
        out({ noRemove, text, note, saved, edit, removed: win().note.textContent,
              view: mod._test.state().view });
    """)
    assert out["noRemove"] is True, "a shipped agent has no copy of yours to remove"
    assert out["text"].startswith("---\nid: inbox-triage")
    assert "Saved, it is yours alone" in out["note"]
    assert "Your copy of Inbox Triage is the one you see" in out["saved"] and out["edit"] is True
    assert out["removed"] == "Your copy is removed; Inbox Triage is the shipped one again."
    assert out["view"] == "hall"
