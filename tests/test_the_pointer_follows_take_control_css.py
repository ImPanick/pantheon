# SPDX-License-Identifier: AGPL-3.0-or-later
r"""Whose pointer is over the live desktop, in `static/style.css`.

Found by hand on the dev build: with the agent holding the workstation, the
person's cursor vanished as it crossed the live desktop. KasmVNC's client is
an `<iframe>` over the whole stage and hides the page's cursor wherever it has
the pointer, and nothing kept the pointer from it while the person was only
watching. The phone and the agent's browser never had this: a glass lies over
each client until the person holds it.

`Law 20` option 2: the rule is found first and asserted inside
(`tests/helpers/css_rules.py`). `workstationScreen.js` sets `.wsv-driving` on
the screen while the person holds a live desktop
(`test_the_workstation_screen_window_js.py`); the cascade is driven in
Chromium by `test_the_pointer_follows_take_control_in_a_browser.py`.
"""
from __future__ import annotations

import re
from pathlib import Path

from tests.helpers.css_rules import css_rules, decl
from tests.helpers.source_text import blank

CSS = Path(__file__).resolve().parents[1] / "static" / "style.css"


def _rules():
    return [(" ".join(sel.split()), body) for sel, body in css_rules(blank(CSS))]


def _pointer_events(body):
    return (decl(body, "pointer-events") or "").strip()


def test_watching_the_live_desktop_its_frame_takes_no_pointer():
    found = [body for sel, body in _rules() if "@" not in sel
             and sel == ".wsv-screen.wsv-is-live:not(.wsv-driving) .wsv-live"]
    assert found, "nothing keeps the pointer off the live desktop's frame while the person watches"
    assert all(_pointer_events(b) == "none" for b in found)


def test_holding_it_nothing_keeps_the_pointer_off_the_frame():
    # Any rule that reaches the frame while driving must leave it the pointer.
    for sel, body in _rules():
        if "wsv-live" not in sel or ":not(.wsv-driving)" in sel:
            continue
        assert _pointer_events(body) in ("", "auto"), f"{sel} takes the pointer from the held desktop"


def test_no_rule_hides_the_persons_cursor_over_a_live_screen():
    for sel, body in _rules():
        if re.search(r"\b(wsv|phw|abw)-", sel):
            assert (decl(body, "cursor") or "").strip() != "none", f"{sel} hides the person's cursor"
