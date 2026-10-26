# SPDX-License-Identifier: AGPL-3.0-or-later
"""`B812` — the unread count existed only while the mail window was minimized.

`emailLibrary.js`'s `_syncUnreadTabBadge` wrote *"7 unread"* onto the minimized
dock chip, which exists only in the middle of the mail window's three states.
Closed, there is no chip and `#email-unread-dot` was a dot with no number —
and it showed only for mail above the last-seen mark, so read-and-left mail
showed nothing at all; open, the count is in the window.

Now the sidebar dot carries the number whenever there is unread mail
(`emailShared.paintUnreadDot`, capped *"99+"*, named *"7 unread"* for a screen
reader), keeps its glow (`is-new`) for mail new since the person last looked,
and opening the inbox drops the glow and keeps the number. The chip's label
comes from the same `unreadLabel`. No permanent dock chip (`P9-11`).

Driven under node (`Law 20`): the real `emailShared.js`, and
`_refreshUnreadCount` / `markInboxAsSeen` cut from `emailInbox.js` as shipped,
run against a recorded `/api/email/unread-state` answer and a dot element.
"""
from __future__ import annotations

import json
import shutil
import subprocess
import textwrap
from pathlib import Path

import pytest

from tests.helpers.js_source import js_definition, js_function

ROOT = Path(__file__).resolve().parents[1]
INBOX = ROOT / "static" / "js" / "emailInbox.js"

pytestmark = pytest.mark.skipif(not shutil.which("node"), reason="node binary not on PATH")

_WORLD = r"""
globalThis.window = { location: { origin: 'http://pantheon.test' } };
class ClassList {
  constructor() { this.s = new Set(); }
  add(...c) { c.forEach((x) => this.s.add(x)); }
  remove(...c) { c.forEach((x) => this.s.delete(x)); }
  toggle(c, on) { if (on === undefined ? !this.s.has(c) : on) this.s.add(c); else this.s.delete(c); }
  contains(c) { return this.s.has(c); }
}
export const dot = {
  style: { display: 'none', backgroundColor: '', color: '' }, textContent: '', title: '',
  classList: new ClassList(), attrs: {},
  setAttribute(k, v) { this.attrs[k] = String(v); }, removeAttribute(k) { delete this.attrs[k]; },
};
globalThis.document = {
  getElementById: (id) => (id === 'email-unread-dot' ? dot : null),
  visibilityState: 'visible',
};
const store = {};
globalThis.localStorage = { getItem: (k) => (k in store ? store[k] : null),
                            setItem: (k, v) => { store[k] = String(v); } };
export const answers = { state: null, urgency: { max_score: 0 } };
globalThis.fetch = async (url) => {
  if (String(url).includes('/unread-state')) {
    if (answers.state === 'down') throw new Error('network');
    return { ok: true, json: async () => answers.state };
  }
  return { ok: true, json: async () => answers.urgency };
};
export function look() {
  return { shown: dot.style.display !== 'none', text: dot.textContent,
           label: dot.attrs['aria-label'] || null, isNew: dot.classList.contains('is-new'),
           hasCount: dot.classList.contains('has-count'), bg: dot.style.backgroundColor };
}
"""


def _cut(signature: str) -> str:
    """One declaration of `emailInbox.js` as shipped, from its signature."""
    src = INBOX.read_text(encoding="utf-8")
    return js_definition(src, src.index(signature))


def _node(tmp_path: Path, script: str) -> dict:
    (tmp_path / "emailShared.js").write_text((ROOT / "static/js/emailShared.js").read_text())
    (tmp_path / "world.mjs").write_text(_WORLD)
    body = textwrap.dedent(f"""
        import {{ dot, answers, look }} from './world.mjs';
        const {{ paintUnreadDot, unreadLabel, unreadShort }} = await import('./emailShared.js');
        let _unreadCheckedAt = 0;
        const isLibOpen = () => false;
        const prewarmUnreadEmails = async () => {{}};
        const noteMailboxSync = () => {{}};
        const emailApiUrl = (p) => 'http://pantheon.test' + p;
        const API_BASE = '';
        // `B1542`: the look asks the real visibility table first; Email is on.
        const {{ toolPollMayAsk, applyToolVisibility }} = await import({json.dumps((ROOT / "static/js/ui_visibility.js").as_uri())});
        applyToolVisibility({{ features: {{}} }}, null);
        {_cut('function _urgencyColor(')}
        {_cut('async function _refreshUnreadCount(')}
        {_cut('export function markInboxAsSeen(').removeprefix('export ')}
    """) + textwrap.dedent(script)
    (tmp_path / "case.mjs").write_text(body)
    done = subprocess.run(["node", str(tmp_path / "case.mjs")], cwd=tmp_path,
                          capture_output=True, text=True, timeout=30)
    assert done.returncode == 0, done.stderr
    return json.loads(done.stdout.strip().splitlines()[-1])


def test_seven_unread_with_the_window_closed_shows_seven(tmp_path):
    """The row's `Verify:` — read-and-left mail, nothing new, window closed."""
    out = _node(tmp_path, """
        localStorage.setItem('pantheon-email-last-seen-uid', '40');
        answers.state = { unread_count: 7, max_uid: 40 };
        await _refreshUnreadCount();
        console.log(JSON.stringify(look()));
    """)
    assert out == {"shown": True, "text": "7", "label": "7 unread", "isNew": False,
                   "hasCount": True, "bg": ""}


def test_new_mail_glows_and_opening_the_inbox_keeps_the_count(tmp_path):
    out = _node(tmp_path, """
        localStorage.setItem('pantheon-email-last-seen-uid', '40');
        answers.state = { unread_count: 8, max_uid: 41 };
        await _refreshUnreadCount();
        const arrived = look();
        markInboxAsSeen();
        await new Promise((r) => setTimeout(r, 20));
        console.log(JSON.stringify({ arrived, seen: look(),
          mark: localStorage.getItem('pantheon-email-last-seen-uid') }));
    """)
    assert out["arrived"]["text"] == "8" and out["arrived"]["isNew"] is True
    assert out["arrived"]["label"] == "8 unread — new since you last looked"
    assert out["seen"] == {"shown": True, "text": "8", "label": "8 unread", "isNew": False,
                           "hasCount": True, "bg": ""}
    assert out["mark"] == "41"


def test_nothing_unread_or_no_answer_hides_it(tmp_path):
    out = _node(tmp_path, """
        answers.state = { unread_count: 3, max_uid: 5 };
        await _refreshUnreadCount();
        answers.state = { unread_count: 0, max_uid: 5 };
        await _refreshUnreadCount();
        const none = look();
        answers.state = { unread_count: 3, max_uid: 5 };
        await _refreshUnreadCount();
        answers.state = 'down';
        await _refreshUnreadCount();
        console.log(JSON.stringify({ none, down: look() }));
    """)
    assert out["none"]["shown"] is False and out["none"]["text"] == ""
    assert out["down"]["shown"] is False and out["down"]["label"] is None


def test_a_large_count_is_capped_and_an_urgent_one_is_readable(tmp_path):
    out = _node(tmp_path, """
        answers.state = { unread_count: 1234, max_uid: 9 };
        answers.urgency = { max_score: 2 };
        await _refreshUnreadCount();
        console.log(JSON.stringify({ ...look(), color: dot.style.color,
          chip: unreadLabel(1234), short: unreadShort(100) }));
    """)
    assert out["text"] == "99+" and out["chip"] == "999+ unread" and out["short"] == "99+"
    assert out["label"].startswith("999+ unread")
    # The orange urgency tint with dark text: white on #f0ad4e is ~2:1.
    assert out["bg"] == "#f0ad4e" and out["color"] == "#111"


def test_the_minimized_chip_says_the_same_words():
    """The chip's label is `unreadLabel`'s, not a second spelling of it."""
    lib = (ROOT / "static/js/emailLibrary.js").read_text(encoding="utf-8")
    body = js_function(lib, "function _syncUnreadTabBadge")
    assert "unreadLabel(count)" in body and "'999+ unread'" not in body
