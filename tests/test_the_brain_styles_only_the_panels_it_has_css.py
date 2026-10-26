# SPDX-License-Identifier: AGPL-3.0-or-later
"""`B1189` — the stylesheet styles only the Brain panels the Brain has.

`P23-02` deleted the Brain's Skills launcher panel, and the rules written for
it stayed: a two-column layout, its narrow-screen collapse, a rule hiding the
Add-Skill card while a skill was expanded, and the Skills panel's place in
three selector lists the Skills window shares. No element carried
`data-memory-panel="skills"` after that row, so every one of them matched
nothing — and a rule that matches nothing reads as intentional forever once
somebody tidies around it.

Measured both ways rather than grepped for the one word (`Law 20`): every
`data-memory-panel` value the sheet selects (comments blanked, so the note
recording the deletion is not a selector) has to be a panel some page or
module actually creates — the shell's markup, or a script that sets the
attribute at runtime.
"""

import re
from pathlib import Path

from tests.helpers.source_text import blank, blank_text

ROOT = Path(__file__).resolve().parents[1]
STATIC = ROOT / "static"


def _styled() -> set:
    return set(re.findall(r'data-memory-panel="([a-z0-9-]+)"', blank(STATIC / "style.css")))


def _created() -> set:
    made = set()
    for page in sorted(STATIC.glob("*.html")):
        made |= set(re.findall(r'data-memory-panel="([a-z0-9-]+)"',
                               page.read_text(encoding="utf-8")))
    for module in sorted((STATIC / "js").rglob("*.js")):
        src = blank_text(module.read_text(encoding="utf-8"))
        # A panel a script builds: `dataset.memoryPanel = 'x'` or
        # `setAttribute('data-memory-panel', 'x')`. A selector a script
        # *queries* (`[data-memory-panel="rag"]`) creates nothing.
        made |= set(re.findall(r"dataset\.memoryPanel\s*=\s*['\"]([a-z0-9-]+)['\"]", src))
        made |= set(re.findall(
            r"setAttribute\(\s*['\"]data-memory-panel['\"]\s*,\s*['\"]([a-z0-9-]+)['\"]", src))
    return made


def test_every_brain_panel_the_sheet_styles_is_one_that_exists():
    styled, created = _styled(), _created()
    assert created >= {"browse", "rag", "settings"}, sorted(created)
    assert styled <= created, (
        "the stylesheet styles Brain panels nothing creates — dead rules: "
        f"{sorted(styled - created)}"
    )


def test_the_skills_window_kept_its_half_of_the_shared_lists():
    """The three selector lists lost one member each, not the rule: the Skills
    window (`#skills-modal`, `#skills-room`) still needs its browse view to
    fill the window on Firefox mobile, which is why those lists exist."""
    css = blank(STATIC / "style.css")
    for selector in (
        '#skills-modal .skills-view[data-skills-view-panel="browse"] > .admin-card:has(.doclib-card-expanded)',
        '#skills-modal .skills-view[data-skills-view-panel="browse"] > .admin-card',
        '#skills-room .skills-view[data-skills-view-panel="browse"] > .admin-card',
    ):
        assert selector in css, selector
