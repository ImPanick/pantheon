# SPDX-License-Identifier: AGPL-3.0-or-later
"""`B1204` (`CHAT-U-25`) — a highlight says what is open, not what was pressed last.

Two of the row's three lies, fixed and driven under node (`Law 20`):

  * **after Search ↵ the *Search* row stayed lit beside the opened chat.** The
    palette hands the focus back to whatever had it when it opened — right for
    Escape, wrong for a choice made from a Search door: focused from the
    keyboard's Enter, the sidebar's *Search* row wore its `:focus-visible` ring
    next to the chat's own highlight. A chat chosen from a Search door now goes
    on in its message box (not on a phone, where that would push the keyboard
    up); nothing chosen from a door gives the focus back to the door. Opened
    from the message box, the focus still goes back there.
  * ***manage* lit *Library*.** The Chats section's *manage* opens the Library
    window on its Chats tab, and `documentLibrary.js` lit the sidebar's
    *Library* row on every open — the documents library, which nobody opened.
    The row is lit while the window shows its documents (`libraryRowLit`), on
    open and on every tab change.

The third — the fork drawn ⫝ in the toast and tab title but ⤓ in the header and
row — is a font's rendering of U+2ADD, which only a browser can show; it is
filed as its own row.

The real `search-chat.js` in `P9-01`'s sandbox (the sidebar parsed out of
`index.html`), and the real `documentLibrary.js` in `B1194`'s.
"""

import shutil

import pytest

from test_the_search_box_is_the_command_palette_js import _palette, box  # noqa: F401
from test_hiding_the_library_keeps_the_archive_js import _WIN_PREAMBLE, window_sandbox  # noqa: F401
from test_tool_effect_surfaces_js import _run

pytestmark = pytest.mark.skipif(not shutil.which("node"), reason="node binary not on PATH")


def _choose_a_chat(box, opener, width=1280):  # noqa: F811
    return _palette(box, """
        window.innerWidth = %d;
        answer('budget', { status: 200, body: [row('s7', 'Budget', 'the budget for May')] });
        $('%s').focus();
        Search.openSearch();
        type('budget');
        await chatsArrive();
        enter();
        console.log(JSON.stringify(read()));
    """ % (width, opener))


def test_a_chat_chosen_from_the_search_row_leaves_the_row(box):  # noqa: F811
    out = _choose_a_chat(box, "sidebar-search-btn")
    assert out["selected"] == ["s7"] and out["open"] is False
    assert out["focus"] == "message", "the Search row kept the focus (and its ring) beside the chat"


def test_from_the_rail_door_too_and_on_a_phone_no_keyboard_is_pushed_up(box):  # noqa: F811
    rail = _choose_a_chat(box, "rail-search-btn")
    assert rail["focus"] == "message"
    phone = _choose_a_chat(box, "sidebar-search-btn", width=390)
    assert phone["focus"] not in ("sidebar-search-btn", "message")


def test_opened_from_the_message_box_the_focus_goes_back_there(box):  # noqa: F811
    out = _choose_a_chat(box, "message")
    assert out["focus"] == "message"


def test_a_settings_panel_chosen_from_the_search_row_does_not_light_it(box):  # noqa: F811
    out = _palette(box, """
        globalThis._isAdmin = true;
        $('sidebar-search-btn').focus();
        Search.openSearch();
        type('egress');
        enter();
        console.log(JSON.stringify(read()));
    """)
    assert out["settings"] == ["networks"]
    assert out["focus"] != "sidebar-search-btn"


def test_the_library_row_is_lit_for_the_library_not_for_manage(window_sandbox):  # noqa: F811
    out = _run(window_sandbox, _WIN_PREAMBLE, """
        const row = document.body.appendChild(document.createElement('button'));
        row.id = 'tool-library-btn';
        const lit = () => row.classList.contains('active');
        L.openLibrary({ tab: 'chats' });           // *manage*
        await tick();
        const manage = lit();
        press('documents'); await tick();
        const documents = lit();
        press('archive'); await tick();
        const archive = lit();
        L.closeLibrary();
        await new Promise((r) => setTimeout(r, 300));
        const closed = lit();
        L.openLibrary();                           // the Library row itself
        await tick();
        console.log(JSON.stringify({ manage, documents, archive, closed, library: lit() }));
    """)
    assert out == {"manage": False, "documents": True, "archive": False, "closed": False, "library": True}
