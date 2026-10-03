# SPDX-License-Identifier: AGPL-3.0-or-later
"""`B1125` — the integration form has one Escape rule, and it is the room's.

Two page-wide Escape paths looked for `#unified-intg-form` **inside
`#settings-modal`** to close it before Settings: the arbiter in
`static/js/ui.js` and Settings' own keydown in `static/js/settings/lifecycle.js`.
`P22-21` moved the form, with its id, into the Workbench's MCP & Integrations
room (`#workbench-room-integrations`), and the room holds its own layer on the
Escape stack while the form is open (`workbench.js`, `mountIntegrationsRoom`;
driven in `test_skills_and_integrations_are_rooms_js.py::
test_escape_closes_the_integration_form_before_the_window`). So both lookups
could only ever find nothing. They are removed rather than pointed at the room:
a second rule for one form is the drift `Law 7` names.

What is pinned:

  * the premise, from the shipped markup — the form exists once, inside the
    room, and Settings holds none (if it ever moves back, this case says why the
    rules went, before anyone wonders where they are);
  * no page-wide Escape path names the form. This is `Law 20`'s one allowed use
    of a file-wide check — a string whose presence anywhere is wrong — and it is
    run over code with comments blanked, so the comments explaining the removal
    are free to name the form.
"""

from __future__ import annotations

from html.parser import HTMLParser
from pathlib import Path

from tests.helpers.source_text import blank_text

ROOT = Path(__file__).resolve().parents[1]
INDEX = ROOT / "static" / "index.html"
ESCAPE_PATHS = ("static/js/ui.js", "static/js/settings/lifecycle.js")

_VOID = {"area", "base", "br", "col", "embed", "hr", "img", "input", "link", "meta",
         "param", "source", "track", "wbr"}


class _Ancestry(HTMLParser):
    """Each element's id, with the ids of the elements around it."""

    def __init__(self):
        super().__init__()
        self.stack, self.found = [], {}

    def handle_starttag(self, tag, attrs):
        own = dict(attrs).get("id")
        if own:
            self.found.setdefault(own, []).append([i for _, i in self.stack if i])
        if tag not in _VOID:
            self.stack.append((tag, own))

    def handle_startendtag(self, tag, attrs):
        own = dict(attrs).get("id")
        if own:
            self.found.setdefault(own, []).append([i for _, i in self.stack if i])

    def handle_endtag(self, tag):
        for k in range(len(self.stack) - 1, -1, -1):
            if self.stack[k][0] == tag:
                del self.stack[k:]
                break


def test_the_form_lives_in_the_room_and_settings_holds_none():
    page = _Ancestry()
    page.feed(INDEX.read_text(encoding="utf-8"))
    (around,) = page.found["unified-intg-form"]
    assert "workbench-room-integrations" in around and "workbench-modal" in around
    assert "settings-modal" not in around
    assert "settings-modal" in page.found, "the page still has a Settings window"


def test_no_page_wide_escape_path_looks_for_the_form():
    for rel in ESCAPE_PATHS:
        code = blank_text((ROOT / rel).read_text(encoding="utf-8"), "js")
        assert "unified-intg-form" not in code, f"{rel} still looks for the integration form"
