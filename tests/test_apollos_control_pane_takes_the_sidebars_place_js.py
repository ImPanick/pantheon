# SPDX-License-Identifier: AGPL-3.0-or-later
"""Apollo's control pane takes the sidebar's place, and its page reads cleanly.

The owner's second test of Apollo's page (2026-11-24): "this looks extremely
sloppy, visually", the workspace opening "compressed the page immensely" (the
board went to a word a line), and "If we have apollo up we don't need the
pantheon panel with chats and email ... these should be merged into the Apollo
control pane".

Checked here:
  * the control pane (goals, the person's other chats, their mail) sits in the
    sidebar's place when the sidebar shows, and in the deck when it is tucked
    or on a phone, and leaving Apollo gives the sidebar back;
  * Chats lists what the sidebar lists and opens a chat on a press; Email shows
    the unread count and opens the inbox through the sidebar's own control;
  * the deck's columns follow the width it has (container queries), so the
    workspace restacks it rather than crushing it;
  * a lead's report is drawn as a report, from text only, never as HTML;
  * the line a lead's run starts from shows as Apollo's handoff, not as "You".
"""
from __future__ import annotations

import re
import shutil
import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parent))

from test_tool_effect_surfaces_js import _make_sandbox, _run  # noqa: E402

ROOT = Path(__file__).resolve().parents[1]
DECK = ROOT / "static" / "js" / "apolloDeck.js"
TEXT = ROOT / "static" / "js" / "apolloText.js"
COCKPIT = ROOT / "static" / "cockpit.css"

node = pytest.mark.skipif(not shutil.which("node"), reason="node binary not on PATH")

_SHIM = r"""
import { installDom } from './dom.js';
export const document = installDom();
document.documentElement = document.createElement('html');
export const log = { toasts: [], opened: [], library: 0, pressed: [] };
export const media = { wide: true };
globalThis.matchMedia = () => ({ get matches() { return media.wide; }, addEventListener() {}, removeEventListener() {} });
globalThis.fetch = async (url) => {
  let out = {};
  if (url.startsWith('/api/apollo/tasks?')) out = { tasks: [] };
  else if (url.startsWith('/api/apollo/approvals')) out = { approvals: [] };
  return { ok: true, status: 200, json: async () => out };
};
export function settle(n = 20) {
  let p = Promise.resolve();
  for (let i = 0; i < n; i++) p = p.then(() => new Promise((r) => setTimeout(r, 0)));
  return p;
}
function press(id) {
  const b = document.createElement('button'); b.id = id;
  b.addEventListener('click', () => log.pressed.push(id));
  return b;
}
export function page({ mailShown = true, unread = '3' } = {}) {
  const sb = document.createElement('nav'); sb.id = 'sidebar'; sb.className = 'sidebar';
  const inner = document.createElement('div'); inner.className = 'sidebar-inner';
  inner.appendChild(press('sidebar-search-btn'));
  const sessions = document.createElement('div'); sessions.id = 'sessions-section'; inner.appendChild(sessions);
  const mail = document.createElement('div'); mail.id = 'email-section';
  if (!mailShown) mail.style.display = 'none';
  mail.appendChild(press('email-section-title'));
  mail.appendChild(press('email-compose-btn'));
  const dot = document.createElement('span'); dot.id = 'email-unread-dot';
  if (unread) dot.textContent = unread; else dot.style.display = 'none';
  mail.appendChild(dot);
  inner.appendChild(mail);
  sb.appendChild(inner);
  const user = document.createElement('div'); user.id = 'sidebar-user-bar'; sb.appendChild(user);
  const cc = document.createElement('main'); cc.id = 'chat-container';
  const hist = document.createElement('div'); hist.id = 'chat-history'; cc.appendChild(hist);
  document.body.appendChild(sb); document.body.appendChild(cc);
  return { sb, cc };
}
"""

_SESSIONS = r"""
import { log } from './shim.js';
const rows = [
  { id: 'apollo', name: 'Apollo', folder: 'Assistant', last_message_at: '2026-11-24T10:00:00Z' },
  { id: 'cur', name: 'This one', last_message_at: '2026-11-24T09:59:00Z' },
  { id: 'a', name: 'Rack power plan', last_message_at: '2026-11-24T08:00:00Z' },
  { id: 'b', name: 'Old notes', last_message_at: '2026-11-20T08:00:00Z' },
  { id: 'c', name: 'Pinned runbook', is_important: true, last_message_at: '2026-11-01T08:00:00Z' },
  { id: 'd', name: 'Gone', archived: true, last_message_at: '2026-11-24T09:00:00Z' },
  { id: 'e', name: 'Nobody', last_message_at: '2026-11-24T09:00:00Z' },
  { id: 'f', name: 'Secret', last_message_at: '2026-11-24T09:30:00Z' },
];
export function getSessions() { return rows; }
export function getCurrentSessionId() { return 'cur'; }
export function isIncognitoSession(id) { return id === 'f'; }
export async function selectSession(id) { log.opened.push(id); }
export function openLibrary() { log.library += 1; }
"""

_STUBS = {
    "ui.js": "import { log } from './shim.js';\nexport default { showToast: (m) => log.toasts.push(m) };\n",
    "apolloSpaces.js": (
        "export function currentSpace() { return null; }\n"
        "export function spaceParam() { return 'top'; }\n"
        "export function onSpaceChange() { return () => {}; }\n"
    ),
    "apolloTaskChat.js": (
        "import { document } from './shim.js';\n"
        "export function createTaskChat(id) { const el = document.createElement('section');"
        " return { el, taskId: String(id), destroy() { el.remove(); } }; }\n"
    ),
    "sessions.js": _SESSIONS,
}

_PREAMBLE = (
    "import { document, log, media, settle, page } from './shim.js';\n"
    "const D = await import('./apolloDeck.js');\n"
    "const out = (o) => console.log(JSON.stringify(o));\n"
)


@pytest.fixture(scope="module")
def box(tmp_path_factory):
    return _make_sandbox(tmp_path_factory.mktemp("apollocontrol"), DECK, _SHIM, _STUBS)


@pytest.fixture(scope="module")
def textbox(tmp_path_factory):
    return _make_sandbox(tmp_path_factory.mktemp("apollotext"), TEXT, _SHIM, {})


# ── where the control pane sits ────────────────────────────────────────────

@node
def test_with_the_sidebar_showing_the_control_pane_takes_its_place(box):
    o = _run(box, _PREAMBLE, """
        const P = page();
        D.mountDeck();
        await settle();
        const control = document.getElementById('apollo-control');
        const deck = document.getElementById('apollo-deck');
        const kids = P.sb.childNodes.map((n) => n.id || n.className);
        out({ inSidebar: control.parentNode === P.sb, beforeUser: kids.indexOf('apollo-control') + 1 === kids.indexOf('sidebar-user-bar'),
              docked: document.documentElement.classList.contains('apollo-docked'),
              railOut: deck.classList.contains('rail-out'),
              goals: !!control.querySelector('.apo-deck-goals'), newGoal: !!control.querySelector('.apo-newgoal') });
        D.unmountDeck();
    """)
    assert o == {"inSidebar": True, "beforeUser": True, "docked": True, "railOut": True, "goals": True, "newGoal": True}


@node
def test_a_tucked_sidebar_or_a_phone_puts_the_pane_back_in_the_deck_and_leaving_gives_the_sidebar_back(box):
    o = _run(box, _PREAMBLE, """
        const P = page();
        D.mountDeck();
        await settle();
        P.sb.classList.add('hidden');
        D.placeControl();
        const deck = document.getElementById('apollo-deck');
        const tucked = { inDeck: document.getElementById('apollo-control').parentNode === deck,
                         first: deck.childNodes[0].id, docked: document.documentElement.classList.contains('apollo-docked'),
                         railOut: deck.classList.contains('rail-out') };
        P.sb.classList.remove('hidden');
        media.wide = false;
        D.placeControl();
        const phone = document.getElementById('apollo-control').parentNode === deck;
        media.wide = true;
        D.placeControl();
        D.unmountDeck();
        out({ tucked, phone, gone: !document.getElementById('apollo-control'),
              undocked: !document.documentElement.classList.contains('apollo-docked') });
    """)
    assert o["tucked"] == {"inDeck": True, "first": "apollo-control", "docked": False, "railOut": False}
    assert o["phone"] is True
    assert o["gone"] is True and o["undocked"] is True


# ── Chats and Email ────────────────────────────────────────────────────────

@node
def test_chats_lists_what_the_sidebar_lists_and_opens_one(box):
    o = _run(box, _PREAMBLE, """
        page();
        D.mountDeck();
        await settle();
        const control = document.getElementById('apollo-control');
        const chats = control.querySelector('.apo-ctl-chats');
        const rows = chats.querySelectorAll('.apo-nav').filter((b) => b.dataset.sessionId);
        const names = rows.map((b) => b.textContent);
        rows.find((b) => b.dataset.sessionId === 'a').click();
        chats.querySelectorAll('.apo-ctl-act').find((b) => b.getAttribute('aria-label') === 'Search chats').click();
        await settle();
        out({ hidden: chats.hidden, names, opened: log.opened, pressed: log.pressed });
        D.unmountDeck();
    """)
    assert o["hidden"] is False
    # Pinned first, then most recent; not Apollo's own, not this chat, not archived, not Nobody.
    assert o["names"] == ["Pinned runbook", "Rack power plan", "Old notes"]
    assert o["opened"] == ["a"] and o["pressed"] == ["sidebar-search-btn"]


@node
def test_email_shows_the_unread_count_and_opens_the_inbox_through_the_sidebars_control(box):
    o = _run(box, _PREAMBLE, """
        page({ unread: '3' });
        D.mountDeck();
        await settle();
        const mail = document.getElementById('apollo-control').querySelector('.apo-ctl-mail');
        const inbox = mail.querySelector('.apo-inbox');
        const count = inbox.querySelector('.apo-nav-n');
        inbox.click();
        mail.querySelectorAll('.apo-ctl-act').find((b) => b.getAttribute('aria-label') === 'Compose email').click();
        out({ hidden: mail.hidden, count: count.textContent, countHidden: count.hidden,
              label: inbox.getAttribute('aria-label'), pressed: log.pressed });
        D.unmountDeck();
    """)
    assert o == {"hidden": False, "count": "3", "countHidden": False, "label": "Inbox, 3 unread",
                 "pressed": ["email-section-title", "email-compose-btn"]}


@node
def test_email_the_person_hid_stays_hidden(box):
    o = _run(box, _PREAMBLE, """
        page({ mailShown: false });
        D.mountDeck();
        await settle();
        out({ hidden: document.getElementById('apollo-control').querySelector('.apo-ctl-mail').hidden });
        D.unmountDeck();
    """)
    assert o == {"hidden": True}


@node
def test_the_chats_model_on_its_own(box):
    o = _run(box, "const D = await import('./apolloDeckModel.js');\n"
                  "const out = (o) => console.log(JSON.stringify(o));\n", """
        const many = Array.from({ length: 9 }, (_, i) => ({ id: 's' + i, name: i === 4 ? '  ' : 'Chat ' + i,
          last_message_at: '2026-11-2' + i + 'T00:00:00Z' }));
        const r = D.chatRows(many, 's8', { limit: 3 });
        out({ ids: r.rows.map((x) => x.id), more: r.more, untitled: D.chatRows(many, null, { limit: 9 }).rows.find((x) => x.id === 's4').name });
    """)
    assert o == {"ids": ["s7", "s6", "s5"], "more": 5, "untitled": "Untitled chat"}


# ── the layout follows the width the deck has ──────────────────────────────

def test_the_deck_restacks_by_its_own_width_and_the_docked_pane_hides_the_sidebars_list():
    css = COCKPIT.read_text(encoding="utf-8")
    block = css[css.index("/* Apollo's deck (`static/js/apolloDeck.js`)"):]
    assert "html.cockpit.apollo-view #chat-container { container: apollo / inline-size; }" in block
    widths = re.findall(r"@container apollo \(max-width: (\d+)px\)", block)
    assert widths == ["1099", "899", "719"]
    assert "html.cockpit.apollo-view.apollo-docked .sidebar-inner { display: none !important; }" in block
    # The goal's header stays in view while the board scrolls.
    assert re.search(r"\.apo-board-h \{[^}]*position: sticky", block)


# ── a lead's report, and Apollo's handoff ──────────────────────────────────

@node
def test_a_report_is_drawn_from_text_never_parsed_as_html(textbox):
    o = _run(textbox, "import { document } from './shim.js';\n"
                      "const T = await import('./apolloText.js');\n"
                      "const out = (o) => console.log(JSON.stringify(o));\n", """
        const box = document.createElement('div');
        T.renderText(box, '**Built**\\n- `server.py`: tools <b>x</b>\\n- README.md\\n\\n## Report\\nfound **no** mcp package\\n<script>alert(1)</script>');
        const kids = box.childNodes.map((n) => [n.tagName, n.className, n.textContent]);
        const html = box._walk([]).some((n) => n._html);
        const strong = box.querySelectorAll('strong').map((n) => n.textContent);
        const code = box.querySelectorAll('.apo-tx-code').map((n) => n.textContent);
        out({ kids, html, strong, code });
    """)
    assert o["kids"] == [
        ["P", "apo-tx-h", "Built"],
        ["UL", "apo-tx-list", "server.py: tools <b>x</b>README.md"],
        ["P", "apo-tx-h", "Report"],
        ["P", "apo-tx-p", "found no mcp package <script>alert(1)</script>"],
    ]
    assert o["html"] is False
    assert o["strong"] == ["no"] and o["code"] == ["server.py"]


@node
def test_the_line_a_leads_run_starts_from_is_apollos_handoff(box):
    o = _run(box, "const M = await import('./apolloPaneModel.js');\n"
                  "const out = (o) => console.log(JSON.stringify(o));\n", """
        out({ kick: M.APOLLO_KICKOFF, roles: M.chatEntries([
          { role: 'user', content: M.APOLLO_KICKOFF },
          { role: 'assistant', content: 'Done.' },
          { role: 'user', content: 'Thanks' },
        ]).map((e) => e.role) });
    """)
    from src.apollo.runs import APOLLO_TASK_PROMPT
    assert o["kick"] == APOLLO_TASK_PROMPT
    assert o["roles"] == ["apollo", "assistant", "user"]
