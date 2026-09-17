# SPDX-License-Identifier: AGPL-3.0-or-later
"""P1-05 — the icon-rail gear opens Settings.

Until 2026-08-30 `#rail-settings` (`static/app.js`) unhid `#sidebar`, called
`syncRailSide()` and smooth-scrolled `.sidebar-inner` to the bottom, under the
comment *"Scroll to bottom where settings typically are"*. It never opened
Settings. `Law 15` — the reason this project exists — is a person saying *"I'm
genuinely confused how to work it"*; a gear that scrolls a list instead of
opening settings is that failure in miniature.

**The premise this row shipped with was corrected before the work started, and
the correction is kept here rather than replaced.** The row originally claimed
the guided tour was the victim. It is not: `/tour-settings`
(`slashCommands.js:3337`) opens Settings through `#user-bar-settings`, which
works, and reaches its `#rail-settings` fallback only when that element is
absent — which `ui_visibility.js:32` guarantees it never is. That branch was
unreachable dead code, and **the row's previous `Verify:` passed on an unfixed
tree** because it exercised the tour rather than the gear. The rewritten
`Verify:` — *click the rail gear on a cold load with the sidebar hidden; the
Settings panel opens and the sidebar does not scroll* — is what the node cases
below drive, on the DOM a cold load actually has.

**Route taken, and why.** `static/app.js` cannot be imported into the node
sandbox: it is 4.6k lines behind 39 static imports, its top-level body patches
`window.fetch` and issues real requests, and the handler lives inside
`initializeEventListeners()`, which is not exported and touches several hundred
elements before it reaches the rail. So rather than a source scan
(`tests/test_deleted_session_sidebar_regression.py`, which pins the sibling
`#rail-delete-session` block that way) this file takes the middle route: the
handler's **real source text is sliced out of `static/app.js` and executed**
under the shared DOM shim from `tests/test_tool_effect_surfaces_js.py`. Nothing
here re-types the handler, so a case cannot pass against a paraphrase of it, and
the shim, sandbox and runner are imported rather than copied — one harness, one
place it can be fixed.

What is pinned, and why each is a defect if it breaks:

  * **the gear opens Settings.** Asserted as DOM state — `#settings-modal` loses
    `hidden` — and not merely as a call, because `Law 13` is about handlers that
    fire and leave nothing on screen;

  * **the sidebar is not scrolled, and not unhidden.** Both halves matter.
    `#settings-modal` is a body-level `.modal` overlay (`static/index.html:1512`,
    `static/style.css:6168` — `position:fixed`, full viewport), so there is no
    sidebar location to scroll to and no reason to change sidebar state. Worse,
    the old pair was self-defeating: `syncRailSide()`
    (`sidebar-layout.js:78-113`) sets `iconRail.style.display = 'none'` whenever
    the sidebar is *not* hidden, so unhiding the sidebar took the gear the user
    had just clicked off the screen;

  * **it still works with `#user-bar-settings` gone.** The decision this row
    made was to call `settingsModule.open()` — the opener `#user-bar-settings`
    itself is bound to at `static/app.js:1299`, and the one `/open settings`,
    `/settings`, the model picker and `emailLibrary.js` already call — rather
    than to click that button. So there is no fallback to keep: the rail path
    never touches the sidebar's button, which is both inside `#sidebar` (hidden
    exactly when the rail is showing) and user-hideable through Customize UI
    (`ui_visibility.js:32`, `'sidebar-settings-btn'`). Both absence and the
    realistic `display:none` case are driven below. A regression to the guess
    would fail these, not just the two above;

  * **`sidebar-layout.js` still excludes `#rail-settings`** from its delegated
    open-the-sidebar-and-scroll-to-a-section handler. That module already
    decided, in a list that names this button, that the gear is not a section
    launcher — and if the exclusion is dropped the scroll returns on top of a
    correct handler, where nothing in `app.js` would show it;

  * **both ends of the wire.** The handler registers only `if (_railSettings)`
    and calls a module `app.js` must import, so deleting the button from
    `index.html` or the import from the top of `app.js` would take the fix out
    without turning a single behavioural case red. `Law 13` cuts both ways: a
    button with no handler is the same defect as a handler with no button.
"""

import re
import shutil
import textwrap
from pathlib import Path

import pytest

# One harness. `_DOM` is the shim `tests/test_tool_effect_surfaces_js.py` built
# and `tests/test_trust_ladder_js.py` reuses; `_run` writes the case and drives
# node. Imported, never copied.
from test_tool_effect_surfaces_js import _DOM, _run  # noqa: E402
from tests.helpers.source_text import blank, blank_text  # B290

ROOT = Path(__file__).resolve().parents[1]
APP_JS = ROOT / "static" / "app.js"
INDEX = ROOT / "static" / "index.html"
STYLE = ROOT / "static" / "style.css"
SIDEBAR_LAYOUT = ROOT / "static" / "js" / "sidebar-layout.js"

pytestmark = pytest.mark.skipif(not shutil.which("node"), reason="node binary not on PATH")

_BLOCK_START = "// Rail: settings button"
_BLOCK_END = "// Rail: admin button"


def _rail_settings_block() -> str:
    """The real `#rail-settings` wiring, sliced out of `static/app.js`.

    Same idiom as `_extract_between` in `tests/test_email_open_dedup_js.py`. The
    markers are the section comments `app.js` already uses to separate its rail
    handlers; losing either is itself a signal worth failing on.
    """
    source = APP_JS.read_text(encoding="utf-8")
    assert _BLOCK_START in source, f"{_BLOCK_START!r} marker gone from static/app.js"
    start = source.index(_BLOCK_START)
    assert _BLOCK_END in source[start:], f"{_BLOCK_END!r} marker gone from static/app.js"
    end = source.index(_BLOCK_END, start)
    return source[start:end].rstrip()


def _strip_comments(js: str) -> str:
    """Executable half of a block, so prose about the old code cannot satisfy a
    test about the new code. Line comments only — the block has no block
    comments and no string literal containing `//`."""
    return blank_text(js)


# ── Sandbox ─────────────────────────────────────────────────────────────────
# The cold load the rewritten `Verify:` names: sidebar hidden, icon rail
# showing, Settings closed. `#user-bar-settings` is present because
# `ui_visibility.js` guarantees it is — the cases that remove or hide it say so.

_SHIM = r"""
import { installDom, Node } from './dom.js';
export const document = installDom();
export { Node };

// The shim has scrollIntoView but not scrollTo, and the behaviour under test is
// precisely whether scrollTo is reached. Recording rather than throwing keeps a
// reverted handler runnable, so the mutation these cases catch fails on an
// assertion instead of on a TypeError that any change would also produce.
Node.prototype.scrollTo = function scrollTo(opts) {
  this.scrolledTo = opts === undefined ? {} : opts;
};

// Likewise `click()`, which the shim also lacks and every other rail handler in
// app.js uses (`_railToolMap`, #rail-documents). A rail gear implemented as
// `document.getElementById('user-bar-settings').click()` has to actually RUN
// here and open Settings through app.js:1299, or the absent-button case below
// would be passing on a TypeError instead of on the behaviour it names.
Node.prototype.click = function click() {
  this.dispatchEvent({ type: 'click' });
};

function node(tag, id, className, parent) {
  const n = (parent || document.body).appendChild(new Node(tag));
  if (id) n.setAttribute('id', id);
  if (className) n.className = className;
  return n;
}

/** #icon-rail — sibling of #sidebar, visible only while the sidebar is hidden. */
export const iconRail = node('div', 'icon-rail');
export const railSettings = node('button', 'rail-settings', 'icon-rail-btn', iconRail);

/** #sidebar — collapsed on a cold load, which is when the rail gear exists. */
export const sidebar = node('nav', 'sidebar', 'sidebar hidden');
export const sidebarInner = node('div', '', 'sidebar-inner', sidebar);
sidebarInner.scrollHeight = 4200;
const userBar = node('div', 'sidebar-user-bar', '', sidebar);
export let userBarSettings = node('button', 'user-bar-settings', 'user-bar-btn', userBar);

/** #settings-modal — a body-level overlay, not a sidebar section. */
export const settingsModal = node('div', 'settings-modal', 'modal hidden');

/** app.js:213 — `const el = uiModule.el`, i.e. getElementById. */
export const el = (id) => document.getElementById(id);

export const calls = { open: [], syncRailSide: 0, userBarClicks: 0 };

/**
 * `settings.js`'s real `open()` in miniature: it clears `hidden` on
 * #settings-modal exactly as `showSettingsModal()` does, so "Settings opened"
 * is observable as screen state and not only as a call count.
 */
export const settingsModule = {
  open(tab) {
    calls.open.push(tab === undefined ? null : tab);
    settingsModal.classList.remove('hidden');
  },
};

// app.js:1299 — `userBarSettings.addEventListener('click', () => settingsModule.open())`.
// Wired here so a rail handler that clicks #user-bar-settings instead of calling
// the module DOES open Settings in this sandbox, exactly as it would in a
// browser. Without it the absent-button case below would look decisive while
// actually being satisfied by a harness that models no click-through at all.
userBarSettings.addEventListener('click', () => {
  calls.userBarClicks += 1;
  settingsModule.open();
});

/** `sidebar-layout.js`'s syncRailSide, in the one respect that matters here. */
export function syncRailSide() {
  calls.syncRailSide += 1;
  const hidden = sidebar.classList.contains('hidden');
  iconRail.style.display = (hidden && !iconRail.classList.contains('rail-hidden')) ? '' : 'none';
}

/** Take #user-bar-settings out of the DOM, as the tour's fallback assumes. */
export function removeUserBarSettings() {
  userBarSettings.remove();
  userBarSettings = null;
}

/** What Customize UI actually does: display:none, element still in the DOM. */
export function hideUserBarSettings() {
  userBarSettings.style.display = 'none';
}

/** Everything a reader would check after clicking the gear. */
export function state() {
  return {
    settingsOpen: !settingsModal.classList.contains('hidden'),
    opens: calls.open.length,
    openArgs: calls.open,
    sidebarHidden: sidebar.classList.contains('hidden'),
    sidebarScrolledTo: sidebarInner.scrolledTo === undefined ? null : sidebarInner.scrolledTo,
    sidebarScrollTop: sidebarInner.scrollTop,
    sidebarScrolledIntoView: sidebarInner.scrolledIntoView,
    railDisplay: iconRail.style.display === undefined ? '' : iconRail.style.display,
    syncRailSideCalls: calls.syncRailSide,
    userBarClicks: calls.userBarClicks,
  };
}
"""

_WRAPPER_HEAD = (
    "import { el, settingsModule, syncRailSide, document } from './shim.js';\n"
    "\n"
    "/** The real block, verbatim from static/app.js. */\n"
    "export function wireRailSettings() {\n"
)
_WRAPPER_TAIL = "\n}\n"

_PREAMBLE = (
    "import { railSettings, state, removeUserBarSettings, hideUserBarSettings }"
    " from './shim.js';\n"
    "import { wireRailSettings } from './railSettings.js';\n"
    "const click = () => railSettings.dispatchEvent({ type: 'click' });\n"
)


@pytest.fixture(scope="module")
def rail_sandbox(tmp_path_factory):
    directory = tmp_path_factory.mktemp("railsettings")
    (directory / "dom.js").write_text(_DOM)
    (directory / "shim.js").write_text(_SHIM)
    block = textwrap.indent(textwrap.dedent(_rail_settings_block()), "  ")
    (directory / "railSettings.js").write_text(_WRAPPER_HEAD + block + _WRAPPER_TAIL)
    return directory


def _drive(sandbox: Path, script: str) -> dict:
    return _run(sandbox, _PREAMBLE, script)


# ── The rewritten Verify:, driven ───────────────────────────────────────────


def test_rail_gear_opens_settings_on_a_cold_load(rail_sandbox):
    """Half one of `Verify:`. The panel is open afterwards, on screen."""
    out = _drive(rail_sandbox, """
        wireRailSettings();
        const before = state();
        click();
        console.log(JSON.stringify({ before, after: state() }));
    """)

    assert out["before"]["settingsOpen"] is False, "sandbox did not start on a cold load"
    assert out["after"]["settingsOpen"] is True
    assert out["after"]["opens"] == 1
    # Bare open() — the gear lands on whatever tab was last used, exactly like
    # #user-bar-settings (app.js:1299). Only #user-bar-profile forces a tab.
    assert out["after"]["openArgs"] == [None]


def test_rail_gear_does_not_scroll_or_unhide_the_sidebar(rail_sandbox):
    """Half two of `Verify:`, and the whole of the old behaviour, refused.

    `scrolledTo` is `null` if and only if nothing called `scrollTo` on
    `.sidebar-inner`; `scrollTop` and `scrolledIntoView` close the two other
    ways a handler could smuggle the same guess back in.
    """
    out = _drive(rail_sandbox, """
        wireRailSettings();
        click();
        console.log(JSON.stringify(state()));
    """)

    assert out["sidebarScrolledTo"] is None, "the gear still scrolls .sidebar-inner"
    assert out["sidebarScrollTop"] == 0
    assert out["sidebarScrolledIntoView"] is False
    assert out["sidebarHidden"] is True, "the gear still unhides the sidebar"
    # syncRailSide() reconciles the rail *from* the sidebar's classes. This path
    # changes none, so there is nothing to reconcile — and the old call, paired
    # with the unhide above, set the clicked gear's own container to display:none.
    assert out["syncRailSideCalls"] == 0
    assert out["railDisplay"] == "", "the click took the icon rail off screen"


def test_rail_gear_opens_settings_with_user_bar_settings_absent(rail_sandbox):
    """The decision, pinned: the rail path does not go through the sidebar.

    `ui_visibility.js:32` guarantees `#user-bar-settings` exists, but a
    guarantee in one module is not a null check in another — and this is the
    exact DOM `slashCommands.js:3337` falls through to `#rail-settings` on. The
    branch the audit called unreachable dead code is live here, and now leads
    somewhere. A handler that clicked `#user-bar-settings` instead would open
    nothing in this case; one that fell back to the old guess would fail the
    sidebar assertions below rather than pass quietly.
    """
    out = _drive(rail_sandbox, """
        removeUserBarSettings();
        wireRailSettings();
        click();
        console.log(JSON.stringify(state()));
    """)

    assert out["settingsOpen"] is True
    assert out["opens"] == 1
    assert out["sidebarScrolledTo"] is None
    assert out["sidebarHidden"] is True


def test_rail_gear_opens_settings_when_customize_ui_hides_the_user_bar_button(rail_sandbox):
    """The realistic version of the case above.

    `applyUIVis` (`static/app.js:2754`) sets `display:none`; it never removes
    the node. So a click-through implementation would survive this and die only
    in the absent case — both are driven so neither can be the one that slips.
    """
    out = _drive(rail_sandbox, """
        hideUserBarSettings();
        wireRailSettings();
        click();
        console.log(JSON.stringify(state()));
    """)

    assert out["settingsOpen"] is True
    assert out["opens"] == 1
    assert out["sidebarScrolledTo"] is None
    assert out["sidebarHidden"] is True


def test_repeated_clicks_stay_one_open_each(rail_sandbox):
    """No accumulating listeners and no second opener behind the first."""
    out = _drive(rail_sandbox, """
        wireRailSettings();
        click(); click(); click();
        console.log(JSON.stringify(state()));
    """)

    assert out["opens"] == 3
    assert out["sidebarScrolledTo"] is None
    assert out["sidebarHidden"] is True


# ── Source guards ───────────────────────────────────────────────────────────


def test_the_handler_calls_the_one_settings_opener():
    """`Law 14` — one implementation, not two.

    `settingsModule.open()` is what `#user-bar-settings` is bound to
    (`app.js:1299`), what `/open settings` and `/settings` prefer
    (`slashCommands.js:1363`, `1431`), and what `modelPicker.js`,
    `emailLibrary.js` and `calendar.js` call. The gear joins them rather than
    growing a second way in.
    """
    source = APP_JS.read_text(encoding="utf-8")
    block = _strip_comments(_rail_settings_block())

    assert "settingsModule.open()" in block
    # The call above resolves to nothing without this. A handler that throws on
    # click is the same defect class as one that opens nothing.
    assert re.search(r"^import settingsModule from '\./js/settings\.js", source, re.M)
    # The two moves that made up the guess, refused in source as well as in
    # behaviour — a reader changing this block should have to read why first.
    assert "scrollTo" not in block
    assert "sidebar-inner" not in block
    assert "classList.remove('hidden')" not in block
    assert "syncRailSide" not in block


def test_the_button_the_handler_wires_actually_exists():
    """`Law 13` — nothing half-wired, read from both ends.

    The handler is registered only `if (_railSettings)`, so deleting the button
    from `index.html` would make the whole of this row's fix vanish without a
    single behavioural case going red: `el('rail-settings')` would simply return
    null. The rail markup is another batch's file, which is exactly why the
    dependency is pinned from here.
    """
    index = INDEX.read_text(encoding="utf-8")
    block = _strip_comments(_rail_settings_block())

    assert "el('rail-settings')" in block
    button = re.search(r'<button[^>]*id="rail-settings"[^>]*>', index)
    assert button, "#rail-settings is gone from static/index.html"
    assert "icon-rail-btn" in button.group(0)
    # Inside #icon-rail, which is a sibling of #sidebar rather than inside it —
    # the gear has to be reachable on precisely the loads where the sidebar is not.
    rail = index.index('<div class="icon-rail" id="icon-rail">')
    assert rail < index.index('id="rail-settings"') < index.index('<nav class="sidebar"')


def test_the_guess_is_recorded_rather_than_quietly_deleted():
    """This programme corrects claims in place.

    The next reader needs to know the guess was tried, or someone re-derives it
    from the same reasoning — the panel *looks* like it belongs at the bottom of
    the sidebar. The sentence stays; only its status changes.
    """
    block = _rail_settings_block()
    comments = "\n".join(line for line in block.splitlines() if "//" in line)

    assert "Scroll to bottom where settings typically are" in comments
    assert "CORRECTED" in comments


def test_settings_is_a_body_level_overlay_not_a_sidebar_section():
    """Why unhiding the sidebar was a side effect nobody asked for.

    If Settings ever moves inside `#sidebar`, the handler above needs the unhide
    back and this test is the one that says so.
    """
    index = INDEX.read_text(encoding="utf-8")
    style = STYLE.read_text(encoding="utf-8")

    modal = re.search(r'^(\s*)<div id="settings-modal" class="([^"]*)">', index, re.M)
    assert modal, "#settings-modal is not where index.html put it"
    assert "modal" in modal.group(2).split()
    # Two spaces of indent — a direct child of <body>, outside <nav id="sidebar">.
    assert len(modal.group(1)) == 2, "settings-modal is no longer a top-level element"

    base = re.search(r"\n\s*\.modal \{(.*?)\}", style, re.S)
    assert base, ".modal base rule not found in style.css"
    assert "position:fixed" in base.group(1).replace(" ", "")
    assert "height:100%" in base.group(1).replace(" ", "")


def test_sidebar_layout_still_excludes_the_gear_from_its_scroll_handler():
    """The other place the scroll could come back from.

    `sidebar-layout.js` delegates clicks on `.icon-rail-btn` to
    open-the-sidebar-and-scroll-to-a-section, and names `#rail-settings` in the
    list of buttons that are *not* section launchers. Dropping it from that list
    restores the exact behaviour this row removed, on top of a correct handler —
    where nothing in `app.js` would reveal it.
    """
    layout = SIDEBAR_LAYOUT.read_text(encoding="utf-8")

    guard = re.search(r"const btn = e\.target\.closest\('\.icon-rail-btn'\);\n(.*?)\n", layout)
    assert guard, "the delegated icon-rail handler changed shape"
    assert "btn.id === 'rail-settings'" in guard.group(1)
    assert "scrollIntoView" in layout
