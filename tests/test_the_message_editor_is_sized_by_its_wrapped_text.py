# SPDX-License-Identifier: AGPL-3.0-or-later
"""`B2001`. Editing a long sent message showed only the top of it.

✎ on one of your own messages swaps its text for an editor (`chat.js`
`editUserMessage`) whose height came from `rows = max(2, its newlines)` over an
80px floor (`.edit-textarea`, `static/style.css`). One long paragraph has no
newlines, so it opened at the floor, and the rest had to be scrolled inside the
box to be read before Send. Measured in Chromium on the shipped stylesheet: the
589-character paragraph below needs 206px at 1440 wide and 434px at 390, and
the editor was 80px tall at both.

The editor is sized by its wrapped text now (`field-sizing: content`), still
the message's full width, and the 30lh cap every textarea has (the `textarea`
rule) bounds it: a longer message than that still scrolls inside the box. A
browser without `field-sizing` ignores it and draws the box as before.

Ported from upstream Odysseus 0c8a06a9 (#6943), its `field-sizing` only:
`resize: both` and `max-width: 100%` change how the editor is dragged, and
`box-sizing: border-box` is already every element's here.

Read (`Law 20` option 2, `tests/helpers/css_rules.py`), then driven: the real
`static/style.css`, whole, in headless Chromium, on the markup
`editUserMessage` draws, at a desktop's width and a phone's.
"""

from __future__ import annotations

from pathlib import Path

import pytest

from tests.helpers.css_rules import css_rules, decl
from tests.helpers.source_text import blank
from test_the_command_palette_in_a_browser import NODE, _SKIP  # noqa: E402
from test_display_and_motion_in_a_browser import _drive, _page  # noqa: E402

ROOT = Path(__file__).resolve().parents[1]
STYLE = ROOT / "static" / "style.css"

#: One paragraph, no newline: `rows` gives it 2.
_LONG = " ".join(["Could you compare the three backup plans we talked about and say which one "
                  "keeps the most history for the least disk?"] * 5)

#: What `editUserMessage` puts in a user message's `.body`.
_EDITING = """
<div id="chat-history" class="chat-history">
 <div class="msg msg-user">
  <div class="role">You</div>
  <div class="body"><textarea class="edit-textarea" rows="2">%s</textarea><div class="edit-row"
   style="display:flex; gap:6px; margin-top:4px;"><button class="edit-save-btn">Send</button><button
   class="edit-cancel-btn">Cancel</button></div></div>
 </div>
</div>
"""

_MEASURE = r"""
  return await page.evaluate(() => {
    const editor = document.querySelector('.edit-textarea');
    return { scroll: editor.scrollHeight, client: editor.clientHeight,
             width: editor.getBoundingClientRect().width,
             room: document.querySelector('.edit-row').getBoundingClientRect().width };
  });
"""


def test_the_editor_is_sized_by_its_text_at_the_message_s_width_and_under_a_cap():
    rules = css_rules(blank(STYLE))
    editor = [body for sel, body in rules if sel == ".edit-textarea"]
    assert len(editor) == 1, "the message editor's rule moved"
    assert decl(editor[0], "field-sizing") == "content", "the editor's height comes from `rows`"
    # Sized by its text, the box would also shrink to the text's width.
    assert decl(editor[0], "width") == "100%"
    every_textarea = [decl(body, "max-height") for sel, body in rules if sel == "textarea"]
    assert decl(editor[0], "max-height") or any(every_textarea), "nothing bounds how tall it grows"


@pytest.mark.skipif(NODE is None, reason=_SKIP or "")
@pytest.mark.parametrize("viewport", [(1440, 900), (390, 844)], ids=["desktop", "phone"])
def test_a_long_paragraph_opens_for_editing_with_all_of_it_in_view(tmp_path, viewport):
    out = _drive(tmp_path, html=_page(_EDITING % _LONG), steps=_MEASURE, viewport=viewport)
    assert not out["errors"], out["errors"]
    got = out["result"]
    assert got["scroll"] > 100, f"the text fits the old box, so this case shows nothing: {got}"
    assert got["scroll"] <= got["client"] + 1, f"part of the message is scrolled out of the editor: {got}"
    assert abs(got["width"] - got["room"]) < 1, f"the editor no longer spans the message: {got}"
