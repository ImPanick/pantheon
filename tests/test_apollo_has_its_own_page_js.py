# SPDX-License-Identifier: AGPL-3.0-or-later
"""Apollo has its own page, not the generic chat's.

The owner's test on a fresh deploy (2026-11-24): Apollo "is acting like
another generic Chat page ... same controls ... just now, it has an orb". The
pane, Space switcher and settings gear were mounted into a chat header the page
does not have (`.chat-header-right, #chat-header .actions, .chat-header`), so
none was ever drawn, and every generic control stayed on.

These check that the page Apollo mounts into is the page that ships, that the
controls it hides exist (so the list can't silently rot), and, driven under
node, that entering Apollo builds its bar, mounts its deck (the work is the
page; the pane stays one press away), switches to Agent mode and changes the
prompt, and that leaving puts all of it back.
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
VIEW = ROOT / "static" / "js" / "apolloView.js"
ASSISTANT = ROOT / "static" / "js" / "assistant.js"
INDEX = ROOT / "static" / "index.html"
COCKPIT = ROOT / "static" / "cockpit.css"


def _html() -> str:
    return INDEX.read_text(encoding="utf-8")


# ── the page it mounts into is the page that ships ─────────────────────────

def test_the_header_apollo_used_to_mount_into_does_not_exist_and_is_no_longer_used():
    html = _html()
    for gone in ("chat-header-right", 'id="chat-header"'):
        assert gone not in html
    assert "chat-header-right" not in ASSISTANT.read_text(encoding="utf-8")


def test_everything_apollos_view_mounts_into_is_in_the_page():
    html = _html()
    src = VIEW.read_text(encoding="utf-8")
    assert "querySelector('.chat-top-bar')" in src and 'class="chat-top-bar"' in html
    for ident in re.findall(r"byId\('([a-z0-9-]+)'\)", src):
        assert f'id="{ident}"' in html, f"apolloView looks for #{ident}, which the page does not have"


def test_every_control_apollo_hides_is_one_the_page_has():
    css = COCKPIT.read_text(encoding="utf-8")
    block = css[css.index("Apollo's own page"):]
    hidden = re.findall(r"html\.cockpit\.apollo-view (?:\.chat-top-bar )?#([a-z0-9-]+)", block)
    assert len(hidden) >= 20
    html = _html()
    for ident in hidden:
        assert f'id="{ident}"' in html, f"#{ident} is hidden for Apollo but is not on the page"
    assert "html.cockpit.apollo-view .mode-toggle" in block and 'class="mode-toggle"' in html
    assert "#model-picker-wrap" not in block, "Apollo keeps the model picker"


# ── driven ────────────────────────────────────────────────────────────────

pytestmark_node = pytest.mark.skipif(not shutil.which("node"), reason="node binary not on PATH")

_SHIM = r"""
import { installDom } from './dom.js';
export const document = installDom();
if (!document.documentElement) document.documentElement = document.createElement('html');
export const pane = { open: false, opens: 0 };
export const deck = { mounted: 0, unmounted: 0 };
export const dock = { untucked: 0 };
globalThis.window = globalThis.window || globalThis;
window.pantheonCockpit = { toggleWorkspace: (force) => { if (force === false) dock.untucked += 1; } };
export function settle(n = 8) {
  let p = Promise.resolve();
  for (let i = 0; i < n; i++) p = p.then(() => new Promise((r) => setTimeout(r, 0)));
  return p;
}
export function page() {
  const cc = document.createElement('main'); cc.id = 'chat-container'; cc.className = 'chat-container welcome-active';
  const top = document.createElement('div'); top.className = 'chat-top-bar';
  const meta = document.createElement('span'); meta.id = 'current-meta'; top.appendChild(meta);
  const hist = document.createElement('div'); hist.id = 'chat-history';
  const input = document.createElement('textarea'); input.id = 'message'; input.placeholder = 'Message Pantheon';
  const agent = document.createElement('button'); agent.id = 'mode-agent-btn';
  const chat = document.createElement('button'); chat.id = 'mode-chat-btn'; chat.classList.add('active');
  const pick = (on, off) => () => { on.classList.add('active'); off.classList.remove('active'); };
  agent.addEventListener('click', pick(agent, chat));
  chat.addEventListener('click', pick(chat, agent));
  cc.appendChild(top); cc.appendChild(hist); cc.appendChild(input); cc.appendChild(agent); cc.appendChild(chat);
  document.body.appendChild(cc);
  return { top, hist, input, agent, chat };
}
"""

_STUBS = {
    "apolloPane.js": (
        "import { pane } from './shim.js';\n"
        "export function openApolloPane() { pane.open = true; pane.opens += 1; }\n"
        "export function closeApolloPane() { pane.open = false; }\n"
        "export function isApolloPaneOpen() { return pane.open; }\n"
    ),
    "apolloDeck.js": (
        "import { deck } from './shim.js';\n"
        "export function mountDeck() { deck.mounted += 1; }\n"
        "export function unmountDeck() { deck.unmounted += 1; }\n"
    ),
    "apolloSpaces.js": (
        "import { document } from './shim.js';\n"
        "export function createSwitcher() { const el = document.createElement('span'); el.className = 'sp-switch'; return { el }; }\n"
    ),
}

_PREAMBLE = (
    "import { document, pane, dock, deck, settle, page } from './shim.js';\n"
    "const V = await import('./apolloView.js');\n"
    "const out = (o) => console.log(JSON.stringify(o));\n"
    "const P = page();\n"
    "let settingsOpened = 0;\n"
    "const html = document.documentElement;\n"
)


@pytest.fixture(scope="module")
def box(tmp_path_factory):
    return _make_sandbox(tmp_path_factory.mktemp("apolloview"), VIEW, _SHIM, _STUBS)


@pytestmark_node
def test_entering_apollo_makes_the_page_apollos(box):
    o = _run(box, _PREAMBLE, """
        V.enterApolloView({ openSettings: () => { settingsOpened += 1; } });
        await settle();
        const bar = document.getElementById('apollo-bar');
        document.getElementById('assistant-header-gear').click();
        out({
          viewClass: html.classList.contains('apollo-view'),
          barInTop: bar && bar.parentNode === P.top,
          barText: bar && bar.textContent,
          paneBtn: !!document.getElementById('apollo-pane-btn'),
          switcher: !!document.getElementById('apollo-space-switcher'),
          settingsOpened,
          paneOpen: pane.open, deck: deck.mounted,
          agent: P.agent.classList.contains('active'), chat: P.chat.classList.contains('active'),
          prompt: P.input.placeholder,
          on: V.isApolloView(),
        });
    """)
    assert o["viewClass"] is True
    assert o["barInTop"] is True
    assert "Apollo" in o["barText"]
    assert o["paneBtn"] and o["switcher"]
    assert o["settingsOpened"] == 1
    assert o["paneOpen"] is False, "the deck is the page; the pane waits on its button"
    assert o["deck"] == 1
    assert o["agent"] is True and o["chat"] is False
    assert o["prompt"] == "Tell Apollo what you need"
    assert o["on"] is True


@pytestmark_node
def test_leaving_apollo_puts_the_generic_page_back(box):
    o = _run(box, _PREAMBLE, """
        V.enterApolloView({});
        await settle();
        V.leaveApolloView();
        await settle();
        out({
          viewClass: html.classList.contains('apollo-view'),
          bar: !!document.getElementById('apollo-bar'),
          deck: [deck.mounted, deck.unmounted],
          paneOpen: pane.open,
          chat: P.chat.classList.contains('active'),
          prompt: P.input.placeholder,
          on: V.isApolloView(),
        });
    """)
    assert o == {"viewClass": False, "bar": False, "deck": [1, 1], "paneOpen": False,
                 "chat": True, "prompt": "Message Pantheon", "on": False}


@pytestmark_node
def test_entering_twice_builds_one_bar_and_keeps_the_persons_mode_to_restore(box):
    o = _run(box, _PREAMBLE, """
        V.enterApolloView({});
        V.enterApolloView({});
        await settle();
        const bars = document.body._walk([]).filter((n) => n.id === 'apollo-bar').length;
        V.leaveApolloView();
        await settle();
        out({ bars, mounts: deck.mounted, chat: P.chat.classList.contains('active'), prompt: P.input.placeholder });
    """)
    assert o == {"bars": 1, "mounts": 1, "chat": True, "prompt": "Message Pantheon"}


@pytestmark_node
def test_the_pane_button_toggles_the_pane(box):
    o = _run(box, _PREAMBLE, """
        V.enterApolloView({});
        await settle();
        const b = document.getElementById('apollo-pane-btn');
        b.click(); await settle();
        const afterOpen = pane.open;
        const untucked = dock.untucked;
        b.click(); await settle();
        out({ afterOpen, untucked, afterClose: pane.open });
    """)
    assert o == {"afterOpen": True, "untucked": 1, "afterClose": False}
