# SPDX-License-Identifier: AGPL-3.0-or-later
"""`B943` — a minimized Settings window comes back through the cog.

`_AUTO_WIRE` (`static/js/modalManager.js`) maps each tool window to the rail
and sidebar buttons that open it, and two things read that map: `_setBadge`,
which marks the buttons of a minimized window, and the capture-phase click
handler, which turns a press on one of those buttons into `restore()` while the
window is minimized. Settings' entry named `tool-settings-btn`, which no
template renders (measured: every other id the map names is in
`static/index.html`; that one is not). The live doors are `#rail-settings` and
`#user-bar-settings`, both of which call `settingsModule.open()`. So a
minimized Settings badged nothing, and pressing the cog opened it through
`settings.js` and left the window marked minimized with its chip in the dock.

The command palette (`P9-01`) opened Settings through the same function in the
same state, so a minimized Settings chosen there kept its chip as well; it now
restores, the way the chip does.

`B2000`. Every other opener (the model picker's *Settings*, the empty state's
*Add Models*, `/settings`, the Email and call windows' links) still reached a
minimized Settings through `settings.open()` and `showSettingsModal`, which took
`hidden` away and left `modal-minimized`: the window stayed out of sight with
its chip in the dock and both doors badged. `showSettingsModal` restores it
through the manager now; the last case runs the real `settings/lifecycle.js`
beside it.

Driven under node against the real `modalManager.js` in `P9-11`'s dock sandbox
(`Law 20`), with a click that runs the document's capture listeners before the
button's own, as a browser does; the ids are checked against the shipped
markup, parsed at test time.
"""

import json
import re
import shutil
from pathlib import Path

import pytest

from tests.helpers.js_source import js_binding
from test_background_work_dock_js import _SHIM as _DOCK_SHIM  # noqa: E402
from test_background_work_dock_js import _STUBS  # noqa: E402
from test_tool_effect_surfaces_js import _make_sandbox, _run  # noqa: E402

ROOT = Path(__file__).resolve().parents[1]
MODALS_JS = ROOT / "static" / "js" / "modalManager.js"
LIFECYCLE_JS = ROOT / "static" / "js" / "settings" / "lifecycle.js"
INDEX_HTML = ROOT / "static" / "index.html"

pytestmark = pytest.mark.skipif(not shutil.which("node"), reason="node binary not on PATH")

_SHIM = _DOCK_SHIM + r"""
globalThis.MutationObserver = class { observe() {} disconnect() {} };
Node.prototype.closest = function (sel) {
  for (let n = this; n && n !== document; n = n.parentNode) if (n.matches(sel)) return n;
  return null;
};
// `[id]` — any element that has one. The shared matcher reads attributes from
// `attrs`, and `node.id = …` does not write there.
const _m = Node.prototype._matches;
Node.prototype._matches = function (sel) {
  if (String(sel).trim() === '[id]') return !!this.id;
  return _m.call(this, sel);
};

/** A press, as the browser delivers it: the document's capture listeners
 *  first (where `modalManager.js` listens), then the button's own unless one
 *  of them stopped it. */
export function press(node) {
  const ev = {
    type: 'click', target: node, currentTarget: document, stopped: false, defaultPrevented: false,
    stopPropagation() { this.stopped = true; },
    stopImmediatePropagation() { this.stopped = true; },
    preventDefault() { this.defaultPrevented = true; },
  };
  document.dispatchEvent(ev);
  if (!ev.stopped) node.dispatchEvent(ev);
  return ev;
}

export const opened = [];
export function settingsWindow() {
  const modal = document.createElement('div');
  modal.id = 'settings-modal'; modal.className = 'modal';
  const content = modal.appendChild(document.createElement('div'));
  content.className = 'modal-content settings-modal-content';
  document.body.appendChild(modal);
  for (const id of ['rail-settings', 'user-bar-settings']) {
    const btn = document.body.appendChild(document.createElement('button'));
    btn.id = id;
    // What `app.js` binds on both: `settingsModule.open()`.
    btn.addEventListener('click', () => { opened.push(id); modal.classList.remove('hidden'); });
  }
  return modal;
}
"""

_PREAMBLE = (
    "import { document, press, opened, settingsWindow, readDock } from './shim.js';\n"
    "import * as Modals from './modalManager.js';\n"
)


@pytest.fixture(scope="module")
def dock(tmp_path_factory):
    return _make_sandbox(tmp_path_factory.mktemp("settingsdoor"), MODALS_JS, _SHIM, _STUBS)


def _lifecycle_preamble() -> str:
    """`B2000`. The case imports the manager under the URL `lifecycle.js`
    fetches it by, read out of the file (`B814`: no test writes a cache-buster
    down). Node keys a module on its whole URL, so under any other URL it would
    be a second manager with an empty dock."""
    m = re.search(r"""['"]\.\./(modalManager\.js\?[^'"]*)['"]""",
                  LIFECYCLE_JS.read_text(encoding="utf-8"))
    url = "./" + (m.group(1) if m else "modalManager.js")
    return (
        "import { document, settingsWindow, readDock } from './shim.js';\n"
        f"import * as Modals from {json.dumps(url)};\n"
        "import { showSettingsModal } from './settings/lifecycle.js';\n"
    )


@pytest.fixture(scope="module")
def dock_and_settings(tmp_path_factory):
    """The dock sandbox with `settings/lifecycle.js` where the tree puts it."""
    stubs = dict(_STUBS)
    stubs["modalSnap.js"] = _STUBS["modalSnap.js"] + "export function clearDockSide(){}\n"
    stubs["windowDrag.js"] = "export function makeWindowDraggable(){}\n"
    box = _make_sandbox(tmp_path_factory.mktemp("settingsopen"), MODALS_JS, _SHIM, stubs)
    (box / "settings").mkdir()
    shutil.copy(LIFECYCLE_JS, box / "settings" / "lifecycle.js")
    return box


def test_every_door_the_map_names_is_rendered_by_the_markup(tmp_path):
    """The defect's shape, for the whole map: a door named and never drawn is a
    badge on nothing and a restore that never fires."""
    src = MODALS_JS.read_text(encoding="utf-8")
    entry = tmp_path / "wire.mjs"
    entry.write_text(js_binding(src, "_AUTO_WIRE") + ";\nconsole.log(JSON.stringify(_AUTO_WIRE));\n")
    import subprocess
    proc = subprocess.run(["node", str(entry)], capture_output=True, text=True, timeout=30)
    assert proc.returncode == 0, proc.stderr
    wire = json.loads(proc.stdout)
    rendered = set(re.findall(r'\bid="([^"]+)"', INDEX_HTML.read_text(encoding="utf-8")))
    missing = sorted(f"{mid}: {door}" for mid, w in wire.items()
                     for door in (w.get("rail"), w.get("sidebar")) if door and door not in rendered)
    assert not missing, f"doors no template renders: {missing}"
    assert wire["settings-modal"] == {"rail": "rail-settings", "sidebar": "user-bar-settings"}


def test_a_minimized_settings_badges_both_of_its_doors(dock):
    out = _run(dock, _PREAMBLE, """
        const modal = settingsWindow();
        Modals.minimize('settings-modal');
        console.log(JSON.stringify({
          rail: document.getElementById('rail-settings').classList.contains('rail-minimized'),
          cog: document.getElementById('user-bar-settings').classList.contains('rail-minimized'),
          dock: readDock(),
        }));
    """)
    assert out["rail"] is True and out["cog"] is True
    assert [c["id"] for c in out["dock"]] == ["settings-modal"]


@pytest.mark.parametrize("door", ["user-bar-settings", "rail-settings"])
def test_pressing_a_door_restores_it_and_the_chip_goes(dock, door):
    """The row's `Verify`: minimize Settings, press the cog — Settings comes
    back, its chip goes, and `settings.js` was not asked to open it again."""
    out = _run(dock, _PREAMBLE, """
        const modal = settingsWindow();
        Modals.minimize('settings-modal');
        const ev = press(document.getElementById(%s));
        console.log(JSON.stringify({
          minimized: Modals.isMinimized('settings-modal'),
          hidden: modal.classList.contains('hidden'),
          dock: (readDock() || []).map((c) => c.id),
          opened, stopped: ev.stopped,
          badge: document.getElementById('user-bar-settings').classList.contains('rail-minimized'),
        }));
    """ % json.dumps(door))
    assert out["minimized"] is False, "the window is still marked minimized"
    assert out["hidden"] is False
    assert "settings-modal" not in out["dock"], f"its chip stayed in the dock: {out['dock']}"
    assert out["opened"] == [], "the press reached settings.js and opened Settings a second way"
    assert out["badge"] is False


def test_a_press_with_settings_closed_opens_it_through_settings_js(dock):
    """The guard: nothing minimized, so the capture handler steps aside and the
    door does what it always did."""
    out = _run(dock, _PREAMBLE, """
        const modal = settingsWindow();
        modal.classList.add('hidden');
        press(document.getElementById('user-bar-settings'));
        console.log(JSON.stringify({ opened, hidden: modal.classList.contains('hidden') }));
    """)
    assert out["opened"] == ["user-bar-settings"]
    assert out["hidden"] is False


def test_a_minimized_settings_opened_through_settings_js_comes_back_and_its_chip_goes(dock_and_settings):
    """`B2000`. What `settings.open()` does from every other opener, against
    the real manager: Settings is open, its chip is gone and neither door is
    badged, as when its chip is pressed."""
    out = _run(dock_and_settings, _lifecycle_preamble(), """
        const modal = settingsWindow();
        Modals.minimize('settings-modal');
        showSettingsModal(modal);
        for (let i = 0; i < 200 && Modals.windowState('settings-modal') !== 'open'; i++) {
          await new Promise((r) => setTimeout(r, 10));
        }
        console.log(JSON.stringify({
          state: Modals.windowState('settings-modal'),
          dock: (readDock() || []).map((c) => c.id),
          badged: ['rail-settings', 'user-bar-settings']
            .filter((id) => document.getElementById(id).classList.contains('rail-minimized')),
        }));
    """)
    assert out["state"] == "open", f"Settings did not come back: {out['state']}"
    assert "settings-modal" not in out["dock"], f"its chip stayed in the dock: {out['dock']}"
    assert out["badged"] == [], f"its doors are still badged: {out['badged']}"
