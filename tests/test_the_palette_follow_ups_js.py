# SPDX-License-Identifier: AGPL-3.0-or-later
"""`B947` — the follow-ups the first cut of `P9-01` left out on purpose.

The row listed six, each "its own row if taken". None needed an owner's
decision, so all six are here, each through a registry the product already
keeps (`Law 14`):

  (a) **published skills as commands** — the composer's `/` popup merges
      `/api/skills/slash-catalog`; the palette now reads it through the popup's
      own loader and merge (`loadSkillEntries` / `mergeSkillEntries`);
  (b) **Email as a tool** — it has no `_AUTO_WIRE` door on purpose (its own
      unread dot), so it was reachable only as `/email`; it opens through the
      door `/email` presses, and is not offered while Customize UI hides it;
  (c) **Compare is a mode** — its button turns an active comparison off, so
      choosing Compare while one is on keeps the palette open and says so;
  (d) **shortcut hints** — a tool row names its key from `KEYBIND_TOOL_DOORS`,
      the dispatcher's own table, as bound;
  (e) **state on tool rows** — "Open" or "Minimized", from
      `modalManager.windowState`, the reading `showWindow` acts on;
  (f) **focus into the window it opened** — chosen from the keyboard, the
      palette tells `a11y.js` the press was a launch from where the focus is
      returning, and `a11y.js` (`P10-06`) hands the window its move handle and
      takes the focus back there when the window closes. In Chromium:
      `tests/test_the_windows_in_a_browser.py`.

Driven under node in `P9-01`'s palette sandbox — the real `search-chat.js`,
`modalManager.js`, `slashAutocomplete.js` and `keyboard-shortcuts.js`, the rail
and sidebar parsed out of `index.html` — and `P10-06`'s `a11y.js` sandbox.
"""

import json
import shutil

import pytest

from test_a_tool_window_moves_from_the_keyboard import _A11Y_SHIM, _focus  # noqa: E402
from test_the_search_box_is_the_command_palette_js import (  # noqa: E402
    JS, SEARCH_JS, _REAL, _SHIM, _STUBS, _markup, _preamble, _slash_stub)
from test_tool_effect_surfaces_js import _copy_unstubbed_imports, _make_sandbox, _run  # noqa: E402

pytestmark = pytest.mark.skipif(not shutil.which("node"), reason="node binary not on PATH")


@pytest.fixture(scope="module")
def box(tmp_path_factory):
    stubs = dict(_STUBS)
    stubs["slashCommands.js"] = _slash_stub()
    shim = _SHIM.replace("__MARKUP__", json.dumps(_markup()))
    sandbox = _make_sandbox(tmp_path_factory.mktemp("palette-b947"), SEARCH_JS, shim, stubs)
    for rel in _REAL:
        (sandbox / rel).parent.mkdir(parents=True, exist_ok=True)
        shutil.copy(JS / rel, sandbox / rel)
        _copy_unstubbed_imports(sandbox, JS / rel, stubs)
    return sandbox


_HELPERS = """
const launches = [];
document.addEventListener('pantheon:window-launch', (e) => launches.push(e.detail && e.detail.from ? (e.detail.from.id || e.detail.from.tagName) : null));
const tools = () => (read().groups.find((g) => g.label === 'Tools') || { options: [] }).options;
const toolRow = (label) => tools().find((o) => o.label === label) || null;
"""


def _palette(box, script):
    return _run(box, "globalThis._pantheonKeybinds = undefined;\n" + _preamble() + _HELPERS, script)


# ── (a) published skills ───────────────────────────────────────────────────

def test_a_published_skill_is_offered_as_a_command_and_goes_into_the_box(box):
    out = _palette(box, """
        const real = globalThis.fetch;
        globalThis.fetch = async (url, o) => String(url).startsWith('/api/skills/slash-catalog')
          ? { ok: true, status: 200, json: async () => ({ skills: [
              { name: 'weekly-report', token: '/weekly-report', help: 'Write the weekly report', category: 'Skills' }] }) }
          : real(url, o);
        open(); await settle(5);
        type('weekly');
        const found = read();
        enter();
        console.log(JSON.stringify({ found, after: read() }));
    """)
    commands = next(g for g in out["found"]["groups"] if g["label"] == "Commands")
    assert [o["label"] for o in commands["options"]] == ["/weekly-report"]
    assert commands["options"][0]["detail"] == "Write the weekly report"
    assert out["after"]["message"] == "/weekly-report "
    assert out["after"]["ran"] == [], "the palette puts a command in the box and runs nothing"


def test_a_skill_named_like_a_built_in_command_is_listed_once(box):
    out = _palette(box, """
        const real = globalThis.fetch;
        globalThis.fetch = async (url, o) => String(url).startsWith('/api/skills/slash-catalog')
          ? { ok: true, status: 200, json: async () => ({ skills: [{ name: 'rename', token: '/rename', help: 'a skill' }] }) }
          : real(url, o);
        open(); await settle(5); type('/rename');
        console.log(JSON.stringify(read()));
    """)
    commands = next(g for g in out["groups"] if g["label"] == "Commands")
    labels = [o["label"] for o in commands["options"]]
    assert labels.count("/rename") == 1


# ── (b) Email ──────────────────────────────────────────────────────────────

def test_email_is_a_tool_and_opens_through_the_door_email_presses(box):
    out = _palette(box, """
        open(); type('email');
        const offered = toolRow('Email');
        enter();
        console.log(JSON.stringify({ offered, after: read() }));
    """)
    assert out["offered"] is not None, "Email is not offered under Tools"
    assert out["after"]["clicked"] == ["rail-email"]
    assert out["after"]["open"] is False


def test_email_switched_off_in_customize_ui_is_not_offered(box):
    """Customize UI writes `display: none` on `#email-section` and `#rail-email`
    (`ui_visibility.js`); a tool the person switched off is not offered back."""
    out = _palette(box, """
        $('rail-email').style.display = 'none';
        $('email-section').style.display = 'none';
        open(); type('email');
        console.log(JSON.stringify({ offered: toolRow('Email') }));
    """)
    assert out["offered"] is None


# ── (c) Compare ────────────────────────────────────────────────────────────

def test_compare_while_a_comparison_is_on_is_not_turned_off(box):
    out = _palette(box, """
        window.compareModule = { isActive: () => true };
        open(); type('compare'); enter();
        const on = read();
        window.compareModule = { isActive: () => false };
        type('compare'); enter();
        console.log(JSON.stringify({ on, off: read() }));
    """)
    assert out["on"]["clicked"] == [], "the palette pressed Compare's button and ended the comparison"
    assert out["on"]["open"] is True
    assert out["on"]["status"] == "Compare is already on. Its button in the sidebar turns it off."
    assert out["off"]["clicked"] == ["rail-compare"]


# ── (d) the key, (e) the state ─────────────────────────────────────────────

def test_a_tool_row_names_its_key_as_bound(box):
    out = _palette(box, """
        open(); type('calendar'); const cal = toolRow('Calendar');
        window._pantheonKeybinds = Object.assign({}, KEYS_DEFAULTS(), { open_tasks: 'ctrl+alt+t', open_calendar: '' });
        type('tasks'); const tasks = toolRow('Tasks');
        type('calendar'); const unbound = toolRow('Calendar');
        console.log(JSON.stringify({ cal, tasks, unbound }));
    """.replace("KEYS_DEFAULTS()", "(await import('./keyboard-shortcuts.js')).KEYBIND_DEFAULTS"))
    assert out["cal"]["detail"] == "Ctrl+Alt+C"
    assert out["tasks"]["detail"] == "Ctrl+Alt+T"
    assert out["unbound"]["detail"] is None, "an unbound key is not named"


def test_a_tool_row_says_when_its_window_is_already_up(box):
    out = _palette(box, """
        const cal = document.createElement('div');
        cal.id = 'calendar-modal'; cal.className = 'modal';
        document.body.appendChild(cal);
        const gal = document.createElement('div');
        gal.id = 'gallery-modal'; gal.className = 'modal';
        document.body.appendChild(gal);
        Modals.register('gallery-modal', { railBtnId: 'rail-gallery', sidebarBtnId: 'tool-gallery-btn' });
        Modals.minimize('gallery-modal');
        open(); type('calendar'); const open_ = toolRow('Calendar');
        type('gallery'); const minimized = toolRow('Gallery');
        type('tasks'); const closed = toolRow('Tasks');
        console.log(JSON.stringify({ open_, minimized, closed,
          states: ['calendar-modal', 'gallery-modal', 'tasks-modal'].map((id) => Modals.windowState(id)) }));
    """)
    assert out["states"] == ["open", "minimized", "closed"]
    assert out["open_"]["detail"] == "Open · Ctrl+Alt+C"
    assert out["minimized"]["detail"] == "Minimized"
    assert out["closed"]["detail"] is None


# ── (f) the focus ──────────────────────────────────────────────────────────

def test_a_tool_chosen_from_the_keyboard_is_announced_as_a_launch(box):
    """From the message box: the launch names it, so `a11y.js` can hand the
    window the focus and give it back there. A mouse choice is not a launch;
    nor is a command (it goes into the box, where the focus already is)."""
    out = _palette(box, """
        open(); type('calendar'); enter();
        const byKey = launches.slice();
        open(); type('tasks');
        const opt = document.getElementById(read().activeId);
        opt.dispatchEvent({ type: 'click', target: opt });
        const byMouse = launches.slice(byKey.length);
        open(); type('/help'); enter();
        console.log(JSON.stringify({ byKey, byMouse, total: launches.length }));
    """)
    assert out["byKey"] == ["message"]
    assert out["byMouse"] == []
    assert out["total"] == 1


@pytest.fixture(scope="module")
def a11y_sandbox(tmp_path_factory):
    return _make_sandbox(tmp_path_factory.mktemp("winlaunch"), JS / "a11y.js", _A11Y_SHIM, {})


def test_a11y_hands_a_launched_window_the_focus_and_takes_it_back(a11y_sandbox):
    out = _focus(
        """
        const w = makeWindow('tasks-modal');
        composer.focus();
        document.dispatchEvent({ type: 'pantheon:window-launch', detail: { from: composer } });
        show(w);
        await tick(120);
        const inside = who();
        hide(w);
        focusFallsToBody(w.handle);
        await tick(20);
        console.log(JSON.stringify({ inside, back: who() }));
        """,
        a11y_sandbox,
    )
    assert out["inside"] == "window-move-handle"
    assert out["back"] == "message"


def test_a11y_leaves_a_person_who_moved_on(a11y_sandbox):
    out = _focus(
        """
        const w = makeWindow('tasks-modal');
        composer.focus();
        document.dispatchEvent({ type: 'pantheon:window-launch', detail: { from: composer } });
        elsewhere.focus();
        show(w);
        await tick(120);
        console.log(JSON.stringify({ focused: who() }));
        """,
        a11y_sandbox,
    )
    assert out["focused"] == "elsewhere"
