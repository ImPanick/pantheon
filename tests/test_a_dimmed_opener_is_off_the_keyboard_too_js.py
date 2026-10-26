# SPDX-License-Identifier: AGPL-3.0-or-later
"""`B1221` — the dimmed opener is off the keyboard too.

`P23-06` dims the window beneath a window opened from it and takes the pointer
off it (`static/style.css`, read off the `← <opener>` button that
`modalManager.drawBackButton` writes `data-back-to` on). Tab still walked into
it: with *MCP & Integrations* (the Workbench) open from Settings, the keyboard
reached Settings' controls beneath the room. Keyboard inertness is the `inert`
attribute, and `backStack.js` knows the pairs — nothing in it set `inert`.

Now its reconcile (`_readPage`, and `noteOpener` on a window already up) sets
`inert` on each open opener of an open window and takes it off when that
window closes, before the opener is raised and focused.

Driven: the real `static/js/backStack.js` under node in the back-stack sandbox
`tests/test_one_back_stack_js.py` builds (its shim and preamble, imported).
"""

import shutil

import pytest

from test_tool_effect_surfaces_js import _make_sandbox, _run  # noqa: E402
from test_one_back_stack_js import BACK_JS, _PREAMBLE, _SHIM  # noqa: E402

pytestmark = pytest.mark.skipif(not shutil.which("node"), reason="node binary not on PATH")


@pytest.fixture(scope="module")
def box(tmp_path_factory):
    return _make_sandbox(tmp_path_factory.mktemp("b1221"), BACK_JS, _SHIM, {})


def _case(box, script):
    pre = (_PREAMBLE + "makeWin('workbench-modal');\nB.init(); B.ready(); await settle();\n"
           + "const inert = (id) => document.getElementById(id).inert === true"
             " && document.getElementById(id).getAttribute('inert') != null;\n"
           + "const focused = [];\n"
             "B.configure({ focusWindow: (id) => focused.push([id, inert(id)]) });\n")
    return _run(box, pre, script)


def test_the_room_open_from_settings_leaves_settings_inert_until_it_closes(box):
    """The row's `Verify:` — with MCP & Integrations (the Workbench) open from
    Settings, nothing in Settings takes the keyboard until the room closes."""
    o = _case(box, """
        up('settings-modal'); await step();
        const before = inert('settings-modal');
        B.noteOpener('workbench-modal', 'settings-modal');
        up('workbench-modal'); await step();
        const open = { settings: inert('settings-modal'), room: inert('workbench-modal') };
        down('workbench-modal'); await step();
        out({ before, open, after: inert('settings-modal'), log, focused });
    """)
    assert o["before"] is False
    assert o["open"] == {"settings": True, "room": False}
    assert o["after"] is False, "Settings stayed off the keyboard after the room closed"
    assert "raise settings-modal" in o["log"]
    assert o["focused"] == [["settings-modal", False]], "the opener was focused while still inert"


def test_an_opener_noted_after_the_window_is_up_goes_inert_at_once(box):
    o = _case(box, """
        up('memory-modal'); await step();
        up('skills-modal'); await step();
        const unpaired = inert('memory-modal');
        B.noteOpener('skills-modal', 'memory-modal');
        out({ unpaired, paired: inert('memory-modal') });
    """)
    assert o == {"unpaired": False, "paired": True}


def test_a_window_open_on_its_own_leaves_nothing_inert(box):
    o = _case(box, """
        up('settings-modal'); await step();
        up('calendar-modal'); await step();
        out({ settings: inert('settings-modal'), calendar: inert('calendar-modal') });
    """)
    assert o == {"settings": False, "calendar": False}


def test_an_inert_someone_else_set_is_not_taken_off(box):
    """Only what this module set is lifted."""
    o = _case(box, """
        up('settings-modal'); await step();
        const s = document.getElementById('settings-modal');
        s.inert = true; s.setAttribute('inert', '');
        B.noteOpener('workbench-modal', 'settings-modal');
        up('workbench-modal'); await step();
        down('workbench-modal'); await step();
        out({ still: inert('settings-modal') });
    """)
    assert o == {"still": True}


def test_an_opener_that_holds_the_window_is_never_made_inert(box):
    """`inert` would take the window inside it too."""
    o = _case(box, """
        const outer = document.getElementById('settings-modal');
        const inner = document.getElementById('workbench-modal');
        outer.appendChild(inner);
        up('settings-modal'); await step();
        B.noteOpener('workbench-modal', 'settings-modal');
        up('workbench-modal'); await step();
        out({ settings: inert('settings-modal') });
    """)
    assert o == {"settings": False}
