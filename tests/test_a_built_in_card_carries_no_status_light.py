# SPDX-License-Identifier: AGPL-3.0-or-later
"""`B690` — the built-in capability card has no status light that is not a status.

The row: `_buildBuiltinCards` opened every built-in card with a
`.skill-conf-dot` painted one fixed colour (`--accent`, opacity 0.55), the same
on all of them, while on a user skill card a coloured mark *is* the confidence
(`_confColor`: 90%+ green, 50% red). The reader is trained that a coloured mark
on a skill card means something, and the built-in card's meant nothing. Its
`Verify:` — *"the mark on a built-in card either says something the reader can
name, or it is gone"* — takes the second branch (the owner's
*"you go and just pick"*, `D-2026-10-17-02`): *built-in* and *edited* are
already said in words beside the name, and a user card has no leading mark
either (`_auditDot` is empty), so the two now line up. `.skill-conf-dot`'s one
consumer was this card, so the rule went with it.

Driven under node through the real `skills.js` with the built-in route
answering, in the harness `tests/test_builtin_capabilities_are_admin_only.py`
owns.
"""
from __future__ import annotations

from pathlib import Path

from test_builtin_capabilities_are_admin_only import (  # noqa: F401
    _SKILLS_PREAMBLE,
    _run,
    _store,
    pytestmark_node,
    sandbox,
)

ROOT = Path(__file__).resolve().parents[1]


@pytestmark_node
def test_no_built_in_card_opens_with_a_fixed_colour_dot(sandbox):  # noqa: F811
    out = _run(sandbox, _SKILLS_PREAMBLE, _store() + """
        ready();
        await tick();
        const cards = byId('skills-list').querySelectorAll('.skill-builtin-card');
        console.log(JSON.stringify({
          n: cards.length,
          headers: cards.map(c => String(c.querySelector('.skill-card-header').innerHTML)),
          text: cards.map(c => readable(c)),
        }));
    """)
    assert out["n"] == 2, "no built-in cards were drawn, so this asserts nothing"
    for html in out["headers"]:
        assert "skill-conf-dot" not in html, html[:200]
        assert "border-radius:50%" not in html.replace(" ", ""), "a round mark is still drawn"
    # What a built-in card does say about itself, in words.
    assert all("built-in" in t for t in out["text"])
    assert sum("edited" in t for t in out["text"]) == 1


def test_the_rule_whose_only_consumer_it_was_is_gone():
    """A file-wide absence is the one thing a substring may prove (`Law 20`)."""
    css = (ROOT / "static" / "style.css").read_text(encoding="utf-8")
    js = (ROOT / "static" / "js" / "skills.js").read_text(encoding="utf-8")
    assert ".skill-conf-dot {" not in css
    assert 'class="skill-conf-dot"' not in js
