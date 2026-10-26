# SPDX-License-Identifier: AGPL-3.0-or-later
"""`B721` — `settings-modal` announces that it opened, the first time.

`modalManager.js` emits `pantheon:modal-opened` from a `MutationObserver` that
`register()` installs, and `settings-modal` is in `_AUTO_WIRE` but is only
registered by `minimize(id)` — so the observer existed only after the window
had been minimised once, and Settings (opened by dropping `.hidden`) opened in
silence on a fresh page. A panel inside it that shows live state could only
poll or be stale.

Now every wired window is watched from the boot scan for the one thing a
listener needs — *it opened* — without being registered, so it gains no dock
chip or badge it did not have; `register()` takes the watch over when the
window is registered, so an opening is announced once, not twice.

Driven: the real `modalManager.js` under node, with a `MutationObserver` that
fires on the attribute changes the shim makes (the shim has none of its own).
"""
import shutil

import pytest

from test_background_work_dock_js import _SHIM, _STUBS, MODALS_JS  # noqa: E402
from test_tool_effect_surfaces_js import _make_sandbox, _run  # noqa: E402

pytestmark = pytest.mark.skipif(not shutil.which("node"), reason="node binary not on PATH")

_OBSERVED = _SHIM + r"""
// A MutationObserver the shim lacks: each observer is told when the class list
// or the style of the node it watches changes — the two the module observes.
const _observers = new Set();
globalThis.MutationObserver = class {
  constructor(cb) { this.cb = cb; this.target = null; }
  observe(target) { this.target = target; _observers.add(this); }
  disconnect() { _observers.delete(this); }
};
export function mutated(node) {
  for (const o of [..._observers]) if (o.target === node) o.cb([{ type: 'attributes', target: node }]);
}
export const opened = [];
globalThis.dispatchEvent = (ev) => {
  if (ev && ev.type === 'pantheon:modal-opened') opened.push(ev.detail.id);
  return true;
};
// The settings window exists before the module's boot scan, as in the page.
const settings = new Node('div');
settings.setAttribute('id', 'settings-modal');
settings.classList.add('hidden');
document.body.appendChild(settings);
export { settings };
"""

_PREAMBLE = (
    "import { document, Node, mutated, opened, settings } from './shim.js';\n"
    "import * as Modals from './modalManager.js';\n"
    "const wait = (ms) => new Promise((r) => setTimeout(r, ms));\n"
    "await wait(150);   // the boot scan runs 100 ms after the module loads\n"
    "const show = () => { settings.classList.remove('hidden'); mutated(settings); };\n"
    "const hide = () => { settings.classList.add('hidden'); mutated(settings); };\n"
)


@pytest.fixture(scope="module")
def sandbox(tmp_path_factory):
    return _make_sandbox(tmp_path_factory.mktemp("opened"), MODALS_JS, _OBSERVED, _STUBS)


def test_the_first_open_on_a_fresh_page_is_announced(sandbox):
    """The row's `Verify:`: no minimise first."""
    out = _run(sandbox, _PREAMBLE, """
        show();
        console.log(JSON.stringify({ opened, registered: Modals.isRegistered('settings-modal') }));
    """)
    assert out["opened"] == ["settings-modal"]
    assert out["registered"] is False, "announcing is not registering: no dock chip"


def test_each_opening_is_announced_once(sandbox):
    out = _run(sandbox, _PREAMBLE, """
        show(); mutated(settings);           // a second attribute change while open
        hide(); show();
        console.log(JSON.stringify({ opened }));
    """)
    assert out["opened"] == ["settings-modal", "settings-modal"]


def test_registering_an_open_window_does_not_announce_it_again(sandbox):
    """Minimise registers the window; the opening it is in was already
    announced, and the next one is announced by `register()`'s own observer —
    once."""
    out = _run(sandbox, _PREAMBLE, """
        show();
        Modals.register('settings-modal', {});
        const afterRegister = opened.length;
        hide(); show();
        console.log(JSON.stringify({ afterRegister, opened }));
    """)
    assert out["afterRegister"] == 1
    assert out["opened"] == ["settings-modal", "settings-modal"]
