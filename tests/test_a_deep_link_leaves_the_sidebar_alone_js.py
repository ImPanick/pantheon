# SPDX-License-Identifier: AGPL-3.0-or-later
"""`B1217` (fx-display) — the `/email` and `/notes` deep links leave the sidebar alone.

`app.js`' `_routeOpen` folded the wide sidebar to the icon rail
(`_collapseSidebarToRail`, `B483`'s fullscreen-with-rail) before opening each.
`P23-06` stopped the Calendar's fold (`NAV-M-15`); these two were the rest of
"nothing behind a window moves" (the UI/UX audit's § 4.2). The windows still
open full-screen — Email's `email-lib-fullscreen`, Notes' `enterFullscreen` —
and the sidebar stays as the person left it. The paired restore stays for the
one thing that still folds the sidebar, a window docked left (`modalSnap.js`).

Driven (`Law 20`): the real `_routeOpen` table cut out of `app.js` (with the
fold it called, where the tree still has one) and run under node over a page
with the sidebar open.
"""

import json
import shutil
import subprocess
from pathlib import Path

import pytest

from tests.helpers.js_source import js_definition
from tests.helpers.source_text import blank_text

ROOT = Path(__file__).resolve().parents[1]
APP = (ROOT / "static" / "app.js").read_text(encoding="utf-8")

pytestmark = pytest.mark.skipif(not shutil.which("node"), reason="node binary not on PATH")


def _cut(signature: str) -> str:
    code = blank_text(APP, "js")
    return js_definition(APP, code.index(signature)) if signature in code else ""


_PAGE = r"""
class El {
  constructor(id, cls = '') { this.id = id; this.className = cls; this.dataset = {}; this.clicks = 0; this.onclick = null; }
  get classList() {
    const s = this;
    const list = () => s.className.split(/\s+/).filter(Boolean);
    return { add: (c) => { if (!list().includes(c)) s.className = [...list(), c].join(' '); },
             remove: (c) => { s.className = list().filter((x) => x !== c).join(' '); },
             contains: (c) => list().includes(c) };
  }
  click() { this.clicks += 1; if (this.onclick) this.onclick(); }
}
const nodes = new Map();
const add = (id, cls) => { const n = new El(id, cls); nodes.set(id, n); return n; };
const sidebar = add('sidebar', 'sidebar');                 // open
const rail = add('icon-rail', 'icon-rail rail-hidden');
const newChat = add('rail-new-session');
const header = new El('', 'section-header-flex');
header.onclick = () => add('email-lib-modal', 'modal');
globalThis.document = {
  body: { dataset: {} },
  getElementById: (id) => nodes.get(id) || null,
  querySelector: (sel) => (sel === '#email-section .section-header-flex' ? header : null),
};
globalThis.window = globalThis;
globalThis.requestAnimationFrame = (fn) => fn();
const fullscreened = [];
const notesModule = { openPanel: () => fullscreened.push('notes-open'), enterFullscreen: () => { fullscreened.push('notes-full'); return true; } };
const calendarModule = { openCalendar() {} };
const sessionModule = { openLibrary() {} };
"""


def _run(path: str) -> dict:
    body = (_PAGE + _cut("const _collapseSidebarToRail = ") + "\n" + _cut("const _routeOpen = {") + ";\n"
            + f"_routeOpen[{json.dumps(path)}]();\n"
            + "setTimeout(() => console.log(JSON.stringify({ sidebar: sidebar.className, rail: rail.className,"
            + " marked: document.body.dataset.routeCollapsedSidebar || null, fullscreened,"
            + " email: (nodes.get('email-lib-modal') || { className: null }).className })), 260);\n")
    out = subprocess.run(["node", "--input-type=module"], input=body, capture_output=True, text=True, timeout=30)
    assert out.returncode == 0, out.stderr
    return json.loads(out.stdout.strip().splitlines()[-1])


def test_email_opens_full_screen_and_the_sidebar_stays_open():
    out = _run("/email")
    assert out["sidebar"] == "sidebar", "the sidebar was folded to the rail"
    assert out["rail"] == "icon-rail rail-hidden" and out["marked"] is None
    assert out["email"] == "modal email-lib-fullscreen"


def test_notes_opens_full_screen_and_the_sidebar_stays_open():
    out = _run("/notes")
    assert out["sidebar"] == "sidebar", "the sidebar was folded to the rail"
    assert out["marked"] is None
    assert out["fullscreened"] == ["notes-open", "notes-full"]
