# SPDX-License-Identifier: AGPL-3.0-or-later
"""`B1960`. On a phone, the on-screen keyboard closed the sidebar drawer the person had just opened.

`static/index.html` asks for `interactive-widget=resizes-content`, so on
Chromium (Android) the keyboard opening or closing resizes the page and fires
`resize` with the width unchanged. `initSidebarLayout`'s resize listener took
every resize for a window resize: it cleared `_userToggledSidebar`, the flag
that says the person opened the sidebar themselves, and ran
`checkSidebarAutoCollapse`, which below 700 px hides an open sidebar. So the
drawer closed behind the + New Folder prompt (and renaming a folder) as soon
as the keyboard came up for it, and ☰ tapped while typing opened the drawer
and shut it again, in whichever order the keyboard's resize and the opening
arrived. Renaming a chat was spared only because `_guardSidebarDuringRename`
re-opens the drawer while that input lives.

Now a resize that leaves the width as it was is the keyboard, and changes
nothing. A width change (a phone turned, a desktop window narrowed or widened)
collapses and restores as before, and `_guardSidebarDuringRename` stays, the
older and narrower defence.

Upstream Odysseus fixed the same defect in 297ad192 by never auto-collapsing
below 768 px; that is not what this does, because it would also stop a
narrowed desktop window from folding its sidebar.

Driven (`Law 20`): `checkSidebarAutoCollapse`, the resize listener and the
body-class observer are cut out of `static/js/sidebar-layout.js` by name, with
the drawer's two real openers (`window._odyOpenSidebar`, the swipe's, and the
☰ handler), and run under node on the shared DOM shim with its
`MutationObserver`; `syncRailSide` is a stand-in that sets the body class the
real one sets.
"""

import shutil
import sys
from pathlib import Path

import pytest

from tests.helpers.js_source import js_binding, js_code, js_definition

sys.path.insert(0, str(Path(__file__).resolve().parent))
from test_tool_effect_surfaces_js import _DOM, _run  # noqa: E402

pytestmark = pytest.mark.skipif(not shutil.which("node"), reason="node binary not on PATH")

ROOT = Path(__file__).resolve().parents[1]
LAYOUT = (ROOT / "static" / "js" / "sidebar-layout.js").read_text(encoding="utf-8")
CODE = js_code(LAYOUT)


def _statement(start_text: str) -> str:
    return js_definition(LAYOUT, CODE.index(start_text)) + ";"


def _auto_collapse() -> str:
    """From `AUTO_COLLAPSE_WIDTH` to the body-class observer: the check, the
    resize listener and the observer, as they ship."""
    start = CODE.index("const AUTO_COLLAPSE_WIDTH")
    observer = CODE.index(".observe(document.body", CODE.index("function checkSidebarAutoCollapse("))
    return LAYOUT[start:LAYOUT.index("\n", observer)]


_HARNESS = r"""
installMutationObserver();
const listeners = {};
window.addEventListener = (type, fn) => { (listeners[type] = listeners[type] || []).push(fn); };
window.innerWidth = WIDTH;
window.innerHeight = 800;
const make = (tag, id, cls) => { const n = document.createElement(tag); if (id) n.id = id; if (cls) n.className = cls;
  document.body.appendChild(n); return n; };
const sidebar = make('aside', 'sidebar', 'hidden');
const backdrop = make('div', 'sidebar-backdrop');
const iconRail = make('nav', 'icon-rail');
const hamburgerBtn = make('button', 'hamburger-btn');
const chat = make('div', 'chat-container', 'chat-container');
Object.defineProperty(chat, 'offsetWidth', { get: () => window.innerWidth });
const composer = make('textarea', 'message-input');
composer.blur = () => { document.activeElement = document.body; };
const Storage = { set() {}, KEYS: { SIDEBAR_SIDE: 'side' } };
const documentModule = null;
function _saveSidebarMode() {}
// Stand-in: the body class the real `_syncRailSideCore` sets from the sidebar.
function syncRailSide() { document.body.classList.toggle('sidebar-collapsed', sidebar.classList.contains('hidden')); }
// The page's frames, and a resize as the browser fires it.
const frames = [];
globalThis.requestAnimationFrame = (fn) => { frames.push(fn); return frames.length; };
async function settle() {
  for (let i = 0; i < 8; i += 1) {
    await new Promise((r) => setTimeout(r, 0));
    frames.splice(0).forEach((fn) => fn());
  }
}
async function resize(width, height) {
  window.innerWidth = width; window.innerHeight = height;
  (listeners.resize || []).forEach((fn) => fn());
  await settle();
}
const tapHamburger = () => hamburgerBtn.dispatchEvent({ type: 'click', stopPropagation() {} });
const drawer = () => (sidebar.classList.contains('hidden') ? 'closed' : 'open');
"""

_LAYOUT_CODE = "\n".join([
    js_binding(LAYOUT, "_userToggledSidebar") + ";",
    js_binding(LAYOUT, "_wasAutoCollapsed") + ";",
    _statement("window._odyOpenSidebar = function"),
    _statement("hamburgerBtn.addEventListener("),
    _auto_collapse(),
])


@pytest.fixture(scope="module")
def page(tmp_path_factory):
    d = tmp_path_factory.mktemp("b1960")
    (d / "dom.js").write_text(_DOM)
    return d


def run(page, width: int, script: str) -> dict:
    preamble = ("import { installDom, installMutationObserver } from './dom.js';\n"
                "const document = installDom();\n")
    return _run(page, preamble, _HARNESS.replace("WIDTH", str(width)) + _LAYOUT_CODE + "\n" + script)


def test_the_keyboard_coming_up_leaves_an_open_drawer_open(page):
    """Drawer opened (the swipe's opener), then a prompt from the drawer
    focuses its input and the keyboard takes 300 px of height."""
    out = run(page, 390, """
        window._odyOpenSidebar();
        await settle();
        const opened = drawer();
        await resize(390, 500);
        console.log(JSON.stringify({ opened, after: drawer() }));
    """)
    assert out == {"opened": "open", "after": "open"}


def test_hamburger_tapped_while_typing_opens_the_drawer_and_it_stays(page):
    """☰ blurs the composer and opens 250 ms later; the keyboard's going
    away resizes the page in between."""
    out = run(page, 390, """
        window.innerHeight = 500;
        document.activeElement = composer;
        tapHamburger();
        await resize(390, 800);
        await new Promise((r) => setTimeout(r, 300));
        await settle();
        console.log(JSON.stringify({ after: drawer() }));
    """)
    assert out == {"after": "open"}


def test_turning_the_phone_still_closes_the_drawer(page):
    out = run(page, 390, """
        window._odyOpenSidebar();
        await settle();
        await resize(360, 800);
        console.log(JSON.stringify({ after: drawer() }));
    """)
    assert out == {"after": "closed"}


def test_a_narrowed_desktop_window_still_folds_the_sidebar_and_widened_unfolds_it(page):
    out = run(page, 1200, """
        sidebar.classList.remove('hidden');
        await settle();
        await resize(650, 800);
        const narrowed = drawer();
        await resize(1200, 800);
        console.log(JSON.stringify({ narrowed, widened: drawer() }));
    """)
    assert out == {"narrowed": "closed", "widened": "open"}
