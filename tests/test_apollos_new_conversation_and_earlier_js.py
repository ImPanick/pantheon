# SPDX-License-Identifier: AGPL-3.0-or-later
"""Apollo's bar starts a new conversation and lists the earlier ones.

Driven under node against `static/js/apolloConversations.js`, with the server
stubbed: New conversation posts the space Apollo is in, drops what was cached
about the old chat, reads the spaces again and opens the new chat; an empty
chat is left alone and said so; a refusal is said in its own words; Earlier
lists the earlier conversations under the bar and opens one on a press.
"""
from __future__ import annotations

import shutil
import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parent))

from test_tool_effect_surfaces_js import _make_sandbox, _run  # noqa: E402

ROOT = Path(__file__).resolve().parents[1]
SRC = ROOT / "static" / "js" / "apolloConversations.js"

pytestmark = pytest.mark.skipif(not shutil.which("node"), reason="node binary not on PATH")

_SHIM = r"""
import { installDom } from './dom.js';
export const document = installDom();
export const log = { posts: [], opened: [], toasts: [], spacesLoaded: 0, fresh: [] };
export const server = { newReply: null, status: 200, earlier: [] };
export const space = { id: null };
globalThis.fetch = async (url, opts = {}) => {
  if (opts.method === 'POST') log.posts.push({ url, body: JSON.parse(opts.body || 'null') });
  const body = url.endsWith('/earlier') ? { conversations: server.earlier } : server.newReply;
  const status = url.endsWith('/earlier') ? 200 : server.status;
  return { ok: status < 400, status, json: async () => body };
};
export function settle(n = 8) {
  let p = Promise.resolve();
  for (let i = 0; i < n; i++) p = p.then(() => new Promise((r) => setTimeout(r, 0)));
  return p;
}
export function page() {
  const cc = document.createElement('main');
  const hist = document.createElement('div'); hist.id = 'chat-history';
  cc.appendChild(hist);
  document.body.appendChild(cc);
}
"""

_STUBS = {
    "ui.js": "import { log } from './shim.js';\nexport default { showToast: (m) => log.toasts.push(m) };\n",
    "sessions.js": "import { log } from './shim.js';\nexport async function selectSession(id) { log.opened.push(id); }\n",
    "apolloSpaces.js": (
        "import { log, space } from './shim.js';\n"
        "export function currentSpace() { return space.id; }\n"
        "export async function loadSpaces() { log.spacesLoaded += 1; }\n"
    ),
}

_PREAMBLE = (
    "import { document, log, server, space, settle, page } from './shim.js';\n"
    "const C = await import('./apolloConversations.js');\n"
    "const out = (o) => console.log(JSON.stringify(o));\n"
    "page();\n"
    "const [mkNew, mkEarlier] = C.barButtons({ onFresh: (id) => { log.fresh.push(id); } });\n"
    "const newBtn = mkNew(); const earlierBtn = mkEarlier();\n"
    "document.body.appendChild(newBtn); document.body.appendChild(earlierBtn);\n"
)


@pytest.fixture(scope="module")
def box(tmp_path_factory):
    return _make_sandbox(tmp_path_factory.mktemp("apolloconv"), SRC, _SHIM, _STUBS)


def test_new_conversation_posts_the_space_and_opens_the_new_chat(box):
    o = _run(box, _PREAMBLE, """
        space.id = 'sp-work';
        server.newReply = { session_id: 's-new', earlier_id: 's-old', unchanged: false };
        newBtn.click();
        await settle();
        out({ posts: log.posts, fresh: log.fresh, spaces: log.spacesLoaded, opened: log.opened,
              label: newBtn.textContent });
    """)
    assert o["posts"] == [{"url": "/api/apollo/conversations/new", "body": {"space_id": "sp-work"}}]
    assert o["fresh"] == ["s-new"] and o["spaces"] == 1 and o["opened"] == ["s-new"]
    assert "New chat" in o["label"]


def test_an_empty_chat_is_left_alone_and_said_so(box):
    o = _run(box, _PREAMBLE, """
        server.newReply = { session_id: 's-old', earlier_id: null, unchanged: true };
        newBtn.click();
        await settle();
        out({ opened: log.opened, fresh: log.fresh, toasts: log.toasts });
    """)
    assert o == {"opened": [], "fresh": [], "toasts": ["This chat is already empty."]}


def test_a_refusal_is_said_in_its_own_words(box):
    o = _run(box, _PREAMBLE, """
        server.status = 409;
        server.newReply = { detail: 'Apollo is still working in this chat. Stop it or let it finish, then start a new one.' };
        newBtn.click();
        await settle();
        out({ opened: log.opened, toasts: log.toasts });
    """)
    assert o["opened"] == []
    assert o["toasts"] == ["Apollo is still working in this chat. Stop it or let it finish, then start a new one."]


def test_earlier_lists_the_old_chats_and_opens_one(box):
    o = _run(box, _PREAMBLE, """
        server.earlier = [
          { session_id: 's-1', name: 'Apollo, Nov 23, 2026', messages: 12, last_message_at: '2026-11-23T21:05:00Z' },
          { session_id: 's-0', name: 'Apollo, Nov 20, 2026', messages: 4, last_message_at: '2026-11-20T08:00:00Z' },
        ];
        earlierBtn.click();
        await settle();
        const box = document.getElementById('apollo-earlier');
        const rows = box ? box.querySelectorAll('.apo-earlier-row') : [];
        const names = rows.map((r) => r.querySelector('.apo-earlier-name').textContent);
        const expanded = earlierBtn.getAttribute('aria-expanded');
        const kids = box ? box.parentNode.childNodes : [];
        const beforeHistory = !!box && kids.indexOf(box) + 1 === kids.indexOf(document.getElementById('chat-history'));
        rows[0].click();
        await settle();
        out({ names, expanded, beforeHistory, opened: log.opened,
              closed: !document.getElementById('apollo-earlier') });
    """)
    assert o["names"] == ["Apollo, Nov 23, 2026", "Apollo, Nov 20, 2026"]
    assert o["expanded"] == "true" and o["beforeHistory"] is True
    assert o["opened"] == ["s-1"] and o["closed"] is True


def test_earlier_with_none_says_where_they_come_from_and_toggles_shut(box):
    o = _run(box, _PREAMBLE, """
        server.earlier = [];
        earlierBtn.click();
        await settle();
        const text = document.getElementById('apollo-earlier').textContent;
        earlierBtn.click();
        await settle();
        out({ text, shut: !document.getElementById('apollo-earlier'), expanded: earlierBtn.getAttribute('aria-expanded') });
    """)
    assert "No earlier chats yet" in o["text"]
    assert o["shut"] is True and o["expanded"] == "false"
