# SPDX-License-Identifier: AGPL-3.0-or-later
"""`B1252` — Escape's stop reads what a person can see, not what a module wrote.

`keyboard-shortcuts.js` decides whether an Escape "closed something" by
comparing a print of `<body>`'s children taken before the first listener with
one taken after the last (`B945`). The print held each child's raw
`style.display`, so a module that wrote `display: none` onto an element its
stylesheet already hid changed the print, `escapeClaim` answered `'closed'`, and
the reply streaming behind went on — found on `cdf040f` working `B1243`, where
`sessions.js`' chat-row menus did exactly that on every first Escape after a
list render (fixed in that module); nothing stopped the next module doing the
same. The print now says whether each child can be **seen**
(`checkVisibility`, else the computed style) beside its class.

Driven under node (`Law 20`): the real `keyboard-shortcuts.js` and its real
`initKeyboardShortcuts`, in `B945`'s event model, with a stylesheet that hides
a menu class the way `style.css` does.
"""
import shutil

import pytest

from test_escape_stops_the_reply_only_when_it_closed_nothing_js import _go, box  # noqa: F401

pytestmark = pytest.mark.skipif(not shutil.which("node"), reason="node binary not on PATH")


def test_writing_display_none_on_a_hidden_menu_still_stops_the_reply(box):  # noqa: F811
    out = _go(box, """
        globalThis.__sheet = { 'ctx-menu': 'none' };   // hidden by the stylesheet
        const menu = document.body.append(new El('div', 'ctx', 'ctx-menu'));
        document.addEventListener('keydown', (e) => { if (e.key === 'Escape') menu.style.display = 'none'; });
        press(composer);
        console.log(JSON.stringify({ stops: said() }));
    """)
    assert out["stops"] == 1, "a write nobody could see held the stop"


def test_hiding_a_menu_that_was_on_screen_is_the_escape(box):  # noqa: F811
    out = _go(box, """
        globalThis.__sheet = { 'ctx-menu': 'none' };
        const menu = document.body.append(new El('div', 'ctx', 'ctx-menu'));
        menu.style.display = 'block';                   // opened
        document.addEventListener('keydown', (e) => { if (e.key === 'Escape') menu.style.display = 'none'; });
        press(composer);
        const first = said();
        press(composer);
        console.log(JSON.stringify({ first, second: said() }));
    """)
    assert out == {"first": 0, "second": 1}


def test_the_browsers_own_answer_is_asked_first(box):  # noqa: F811
    """Where the element can say (`checkVisibility`), that is the answer — an
    element hidden by an ancestor rule the computed `display` of the child
    itself does not show."""
    out = _go(box, """
        const panel = document.body.append(new El('div', 'panel', 'side-panel'));
        let seen = true;
        panel.checkVisibility = () => seen;
        document.addEventListener('keydown', (e) => { if (e.key === 'Escape') seen = false; });
        press(composer);
        const closedIt = said();
        document.addEventListener('keydown', (e) => { if (e.key === 'Escape') panel.style.display = 'none'; });
        press(composer);
        console.log(JSON.stringify({ closedIt, unseenWrite: said() }));
    """)
    assert out == {"closedIt": 0, "unseenWrite": 1}
