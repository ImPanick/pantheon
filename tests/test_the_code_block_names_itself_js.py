# SPDX-License-Identifier: AGPL-3.0-or-later
"""`P5-06` — the code block's header, out of two halves that already existed.

Neither half was missing. They had never been connected:

  * **`data-lang`** has been written onto every `<code>` the markdown renderer
    emits since the renderer was written, and nothing ever displayed it. The
    only reader in the tree is `codeRunner.js`, which uses it to decide which
    interpreter to send the block to. A person reading a reply could not tell
    `sh` from `zsh` from `python` except by reading the code.
  * **`langIcons.js`** has held a drawn glyph per language the whole time.
    Re-measured 2026-09-18: it is imported by `document.js` and
    `documentLibrary.js` and **by nothing else** — so the document library
    named its languages and chat, where people actually read code, did not.

The row's third clause — *"moving copy/edit/run into the header also solves
buttons-covering-text"* — is the same change seen from the other side. Those
three buttons were `position: absolute` over the first line of the block, and
two workarounds had grown around that: a click on the code body toggled
`.buttons-hidden` so a reader on a phone could get them off the text, and a
`mouseenter` handler flipped them to the bottom of the block when it sat high
in the viewport (its own comment records that this had to be disabled on
mobile because the buttons moved out from under the finger reaching for them).
`pre.pre-compact` also reserved **200px** of right padding for them — and
because `_markCompactPre` tags every short `<pre>` in the app, that gutter was
being applied to one-line blocks with no buttons at all.

Driven through the real renderer, in the sandbox `test_markdown_rendering_js.py`
owns; its `_run_markdown_case` is imported rather than copied (`Law 14`).
"""

import re

import pytest

from test_markdown_rendering_js import _run_markdown_case, node_available  # noqa: F401


def _render(markdown: str) -> str:
    return _run_markdown_case(markdown)


def _header(html: str) -> str:
    """The one code-block header, resolved before anything is asserted in it."""
    start = html.index('<div class="code-block-header">')
    return html[start:html.index("<code", start)]


def _lang_slot(html: str) -> str:
    """Just the language half of the header — the actions carry `<svg>` of
    their own, so "does the language have a glyph" has to be asked of the slot
    and not of the row (`Law 20`: resolve the scope, then assert in it)."""
    start = html.index('<span class="code-block-lang">')
    return html[start:html.index('<span class="code-block-actions">', start)]


def _actions(html: str) -> str:
    start = html.index('<span class="code-block-actions">')
    return html[start:html.index("</div>", start)]


# ── the language, finally shown ─────────────────────────────────────────────


@pytest.mark.parametrize("fence, shown", [
    ("python", "python"),
    ("bash", "bash"),
    ("json", "json"),
    ("rust", "rust"),
])
def test_the_block_says_which_language_it_is(node_available, fence, shown):
    html = _render(f"```{fence}\nx = 1\n```")
    assert shown in _lang_slot(html)
    # `data-lang` keeps its job as well as gaining a second one: `codeRunner.js`
    # reads it to pick an interpreter.
    assert f'data-lang="{fence}"' in html


def test_the_language_is_drawn_with_the_icons_that_already_existed(node_available):
    """`langIcons.js` was imported by two document modules and never by chat.
    An inline `<svg>` in the header is that import finally arriving — and it is
    `currentColor`, so it is right on all sixteen palettes."""
    slot = _lang_slot(_render("```python\nx = 1\n```"))
    assert "<svg" in slot
    assert 'stroke="currentColor"' in slot
    assert 'fill="none"' in slot


def test_a_language_with_no_glyph_still_gets_its_name(node_available):
    """`langIcon` returns an empty string for anything it does not know, and a
    header that vanishes because of that would be worse than the one line of
    text it was replacing."""
    slot = _lang_slot(_render("```brainfuck\n+++\n```"))
    assert "brainfuck" in slot
    assert "<svg" not in slot


def test_a_fence_with_no_language_still_gets_its_buttons(node_available):
    """Most blocks a model emits are unfenced. The header has to be the place
    the actions live whether or not there is a language to name."""
    html = _render("```\nplain text\n```")
    actions = _actions(html)
    assert 'class="copy-code"' in actions
    assert 'class="edit-code"' in actions
    assert 'data-lang=""' in html


# ── the buttons, out of the code's way ──────────────────────────────────────


def test_the_three_actions_are_in_the_header_and_not_over_the_code(node_available):
    html = _render("```python\nprint(1)\n```")
    actions = _actions(html)
    for cls in ("run-code", "edit-code", "copy-code"):
        assert f'class="{cls}"' in actions, cls
    # Nothing is left floating between the `</code>` and the `</pre>`, which is
    # where all three used to sit.
    tail = html[html.index("</code>"):html.index("</pre>")]
    assert "<button" not in tail, tail


def test_the_header_is_inside_the_pre_because_four_things_depend_on_that(node_available):
    """A wrapper `<div>` around the block would have looked like the tidier
    change and broken all four: the copy, edit and run handlers find their code
    element with `closest('pre')`, `_markCompactPre` reads
    `pre.querySelector('code')`, and the highlight sweep matches `pre code`."""
    html = _render("```bash\nls\n```")
    block = html[html.index("<pre>"):html.index("</pre>") + len("</pre>")]
    assert block.startswith('<pre><div class="code-block-header">')
    assert "<code" in block
    # The header is a sibling of `<code>`, not its parent — otherwise the
    # highlighter would paint the language name.
    assert block.index("code-block-header") < block.index("<code")
    assert "</div><code" in block


def test_only_runnable_languages_offer_to_run(node_available):
    """Unchanged by this row, and worth holding: a Run button on a `json` block
    is a control that does nothing, which `Law 15` counts as worse than none."""
    assert "run-code" in _render("```python\nprint(1)\n```")
    assert "run-code" not in _render("```json\n{}\n```")


def test_the_copy_button_says_what_it_is(node_available):
    """It was an unlabelled icon with no title at all. A person meeting it for
    the first time had to hover, guess, or click and find out."""
    actions = _actions(_render("```python\nprint(1)\n```"))
    assert 'aria-label="Copy code"' in actions
    assert 'title="Copy code"' in actions


# ── the workarounds that existed only because of the overlay ────────────────


def test_tapping_a_code_block_no_longer_makes_its_controls_disappear():
    """`.buttons-hidden` was the mobile escape hatch for buttons sitting on the
    text. With them in a header it has nothing to do — and a tap that hides a
    block's controls for no visible reason is itself a `Law 15` defect."""
    from pathlib import Path
    root = Path(__file__).resolve().parents[1]
    chat = (root / "static" / "js" / "chat.js").read_text(encoding="utf-8")
    css = (root / "static" / "style.css").read_text(encoding="utf-8")
    # Absent from the whole file is the one thing a substring search can
    # honestly prove (`Law 20`), and the class's presence anywhere would mean
    # the workaround survived in one half or the other.
    assert "classList.toggle('buttons-hidden')" not in chat
    assert "pre.buttons-hidden" not in css


def test_the_buttons_no_longer_move_out_from_under_the_finger():
    from pathlib import Path
    root = Path(__file__).resolve().parents[1]
    chat = (root / "static" / "js" / "chat.js").read_text(encoding="utf-8")
    assert "btnPosComputed" not in chat
    assert "classList.toggle('bottom', isBottom)" not in chat


def test_a_one_line_block_no_longer_reserves_a_gutter_for_absent_buttons():
    """`pre.pre-compact { padding-right: 200px }` reserved room for three
    floating buttons. `_markCompactPre` tags **every** short `<pre>` in the
    app, so blocks that never had buttons were being indented by 200px for
    controls they did not own."""
    from pathlib import Path
    css = (Path(__file__).resolve().parents[1] / "static" / "style.css").read_text(
        encoding="utf-8"
    )
    rule = re.search(r"pre\.pre-compact\s*\{([^}]*)\}", css)
    assert rule, "the compact rule is gone entirely"
    assert "padding-right" not in rule.group(1), rule.group(1)
