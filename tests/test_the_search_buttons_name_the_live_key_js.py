# SPDX-License-Identifier: AGPL-3.0-or-later
"""`B946` — the Search buttons name the key that opens the palette, as bound.

`static/index.html` gave `#rail-search-btn` and `#sidebar-search-btn`
`title="Search chats and commands (Ctrl+K)"`. The key is the `search` keybind:
rebindable in Settings → Shortcuts (`keybinds.search`), and the tooltip kept
saying Ctrl+K whatever it was bound to. `search-chat.js` — the module that owns
the box — now writes both titles and their `aria-keyshortcuts` from the live
table (`window._pantheonKeybinds`, falling back to `KEYBIND_DEFAULTS`), through
the same `formatKeybind`/`ariaKeyshortcuts` the Plan button uses (`B948`), and
re-reads it on hover and focus because the saved binds arrive after first
paint and Settings can change them at any time.

Driven under node in `P9-01`'s palette sandbox — the real `search-chat.js` and
`keyboard-shortcuts.js`, the rail and sidebar parsed out of `index.html` at
test time (`Law 20`).
"""

import json
import shutil

import pytest

from test_the_search_box_is_the_command_palette_js import (  # noqa: E402
    JS, SEARCH_JS, _REAL, _SHIM, _STUBS, _markup, _preamble, _slash_stub)
from test_tool_effect_surfaces_js import _copy_unstubbed_imports, _make_sandbox, _run  # noqa: E402

pytestmark = pytest.mark.skipif(not shutil.which("node"), reason="node binary not on PATH")


@pytest.fixture(scope="module")
def box(tmp_path_factory):
    stubs = dict(_STUBS)
    stubs["slashCommands.js"] = _slash_stub()
    shim = _SHIM.replace("__MARKUP__", json.dumps(_markup()))
    sandbox = _make_sandbox(tmp_path_factory.mktemp("searchdoors"), SEARCH_JS, shim, stubs)
    for rel in _REAL:
        (sandbox / rel).parent.mkdir(parents=True, exist_ok=True)
        shutil.copy(JS / rel, sandbox / rel)
        _copy_unstubbed_imports(sandbox, JS / rel, stubs)
    return sandbox


_READ = """
const doors = () => Object.fromEntries(['rail-search-btn', 'sidebar-search-btn'].map((id) => [id, {
  title: $(id).title || $(id).getAttribute('title'),
  keys: $(id).getAttribute('aria-keyshortcuts'),
}]));
"""


def _doors(box, script: str) -> dict:
    # The keybind table is set before the module initialises, the way
    # `initKeyboardShortcuts` publishes it, so `init` reads what is there.
    return _run(box, "globalThis._pantheonKeybinds = undefined;\n" + _preamble() + _READ, script)


def test_both_buttons_name_the_default_key_and_announce_it(box):
    out = _doors(box, "console.log(JSON.stringify(doors()));")
    for door in ("rail-search-btn", "sidebar-search-btn"):
        assert out[door]["title"] == "Search chats and commands (Ctrl+K)", out[door]
        assert out[door]["keys"] == "Control+K", out[door]


def test_a_rebound_key_is_what_the_tooltip_says_on_hover_and_focus(box):
    """The row: the key is rebindable, and the tooltip was wrong for anyone who
    rebinds it. Rebound after load (the saved binds arrive late; Settings can
    change them), the next hover or focus reads the new one."""
    out = _doors(box, """
        window._pantheonKeybinds = Object.assign({}, window._pantheonKeybinds || {}, { search: 'ctrl+alt+j' });
        $('sidebar-search-btn').dispatchEvent({ type: 'focus', target: $('sidebar-search-btn') });
        const focused = doors()['sidebar-search-btn'];
        window._pantheonKeybinds = Object.assign({}, window._pantheonKeybinds, { search: 'ctrl+shift+f' });
        $('rail-search-btn').dispatchEvent({ type: 'pointerenter', target: $('rail-search-btn') });
        const hovered = doors()['rail-search-btn'];
        console.log(JSON.stringify({ focused, hovered }));
    """)
    assert out["focused"] == {"title": "Search chats and commands (Ctrl+Alt+J)", "keys": "Control+Alt+J"}
    assert out["hovered"] == {"title": "Search chats and commands (Ctrl+Shift+F)",
                              "keys": "Control+Shift+F"}


def test_an_unbound_key_is_not_named(box):
    """Settings → Shortcuts can clear a binding. A tooltip naming a key that
    does nothing is the defect in a different spelling."""
    out = _doors(box, """
        window._pantheonKeybinds = { search: '' };
        $('rail-search-btn').dispatchEvent({ type: 'pointerenter', target: $('rail-search-btn') });
        console.log(JSON.stringify(doors()));
    """)
    assert out["rail-search-btn"]["title"] == "Search chats and commands"
    assert out["rail-search-btn"]["keys"] is None
