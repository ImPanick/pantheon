# SPDX-License-Identifier: AGPL-3.0-or-later
"""P3-04 / P3-05 / P3-06 — one name, one animation, and every name defined.

`@keyframes` are global and unscoped, and the **last** definition of a name
wins for every consumer in the document regardless of where either sits. So a
second definition under an existing name is not a duplicate — it is a silent
override of code somebody else wrote, and there is no error, no warning, and
nothing in a screenshot to notice.

`static/style.css` shipped 149 blocks under 143 names:

* **`P3-05`, two live defects.** `#research-toggle-btn.research-running` asked
  for `research-pulse` — the background glow defined three lines under it — and
  got the *other* `research-pulse`, an opacity-and-scale throb 6,800 lines
  further down. The comment said "glow" and the button pulsed in size instead,
  with its background never changing. And a plain-opacity `fadeIn` in the
  compare-pane section had been overridden by a `fadeIn` that adds a 10px
  slide, so nothing near it could get a plain fade. Both are renamed rather
  than deleted: two animations, both wanted, and the shared name was the whole
  bug.
* **`P3-04`, four exact duplicates.** `spin` three times, `loading-bounce` and
  `pulse` twice each, plus the entire three-weight Fira Code `@font-face` set
  declared twice. Byte-identical bodies, so nothing changed by removing them.
* **`P3-06`, seven names for one animation.** `to { transform: rotate(360deg) }`
  under `admin-spin`, `email-spin`, `email-inline-image-spin`, `ge-canvas-spin`,
  `model-picker-refresh-spin`, `whirlpool-spin` and `spin`. Nothing was broken
  by that; the cost was the seventh name, invented by someone who could not
  find the previous six.

The last test here is the one that will keep earning: **every animation name
used anywhere resolves to a definition**. A typo in an `animation:` shorthand
produces no error and no animation, which is the same failure this file spent
three rows on, pointed the other way.
"""
import pathlib
import re

import pytest

ROOT = pathlib.Path(__file__).resolve().parent.parent
CSS_PATH = ROOT / "static" / "style.css"
CSS = CSS_PATH.read_text(encoding="utf-8")
NO_COMMENTS = re.sub(r"/\*.*?\*/", " ", CSS, flags=re.S)

# Keywords a `animation:` shorthand can hold that are not the name.
_NOT_A_NAME = {
    "none", "infinite", "alternate", "alternate-reverse", "reverse", "normal",
    "forwards", "backwards", "both", "running", "paused", "linear", "ease",
    "ease-in", "ease-out", "ease-in-out", "step-start", "step-end", "initial",
    "inherit", "unset", "revert",
}


def _blocks(kind, src):
    out = []
    for m in re.finditer(rf"@{kind}\b\s*([A-Za-z0-9_-]*)\s*\{{", src):
        i, depth = m.end(), 1
        while i < len(src) and depth:
            if src[i] == "{":
                depth += 1
            elif src[i] == "}":
                depth -= 1
            i += 1
        out.append((m.group(1), re.sub(r"\s+", " ", src[m.end():i - 1]).strip()))
    return out


def _defined_names():
    return [name for name, _ in _blocks("keyframes", NO_COMMENTS)]


def _used_names():
    """Animation names out of every `animation`/`animation-name` declaration.

    Values are stripped of durations, functions and keywords, which is enough
    for a shorthand and exact for the longhand. A `var()` is skipped rather
    than guessed at."""
    used = set()
    for m in re.finditer(r"animation(?:-name)?\s*:([^;{}]*)", NO_COMMENTS):
        value = m.group(1)
        if "var(" in value:
            value = re.sub(r"var\([^)]*\)", " ", value)
        for token in re.split(r"[,\s]+", value):
            token = token.strip()
            if not token or token in _NOT_A_NAME:
                continue
            if re.fullmatch(r"[A-Za-z_-][A-Za-z0-9_-]*", token):
                used.add(token)
    return used


def test_no_name_is_defined_twice():
    names = _defined_names()
    assert names, "the parser found no @keyframes at all"
    seen, dupes = set(), []
    for n in names:
        (dupes.append(n) if n in seen else seen.add(n))
    assert not dupes, (
        "these names are defined more than once, and the later definition wins "
        "for every consumer of the earlier one: " + repr(sorted(set(dupes)))
    )


def test_no_two_font_faces_are_identical():
    bodies = [body for _, body in _blocks("font-face", NO_COMMENTS)]
    assert bodies, "the parser found no @font-face at all"
    assert len(bodies) == len(set(bodies)), "an identical @font-face ships twice"


def test_every_animation_name_used_is_defined():
    """The one that keeps earning. A misspelt name in an `animation:` shorthand
    is not an error — the declaration is simply dropped and nothing moves."""
    defined = set(_defined_names())
    missing = sorted(n for n in _used_names() if n not in defined)
    assert not missing, (
        "animation names with no @keyframes: " + repr(missing)
    )


def test_one_name_owns_the_spinner():
    """P3-06. Seven names for `to { transform: rotate(360deg) }`; a test rather
    than a comment, because the eighth will be invented the same way the
    seventh was."""
    rotators = [n for n, b in _blocks("keyframes", NO_COMMENTS)
                if b == "to { transform: rotate(360deg); }"]
    assert rotators == ["spin"], (
        "more than one keyframe is a plain 360° rotation: " + repr(rotators)
    )
    for gone in ("admin-spin", "email-spin", "email-inline-image-spin",
                 "ge-canvas-spin", "model-picker-refresh-spin", "whirlpool-spin"):
        assert not re.search(rf"(?<![A-Za-z0-9-]){gone}(?![A-Za-z0-9-])", NO_COMMENTS), gone


def test_the_two_collisions_are_resolved_and_both_animations_survive():
    """P3-05. Renamed, not deleted — the point was that both were wanted."""
    names = set(_defined_names())
    assert {"research-pulse", "research-glow", "fadeIn", "compare-fade-in"} <= names
    glow = dict(_blocks("keyframes", NO_COMMENTS))["research-glow"]
    assert "background" in glow, "the glow lost its background"
    assert re.search(r"animation:\s*research-glow", NO_COMMENTS), (
        "the research button is not pointed at the animation its comment describes"
    )
    pulse = dict(_blocks("keyframes", NO_COMMENTS))["research-pulse"]
    assert "scale" in pulse, "the surviving research-pulse is not the scale one"


def test_the_spinner_alias_in_javascript_moved_too():
    """`settings.js` writes `animation: whirlpool-spin` into an inline style, so
    the sweep had to leave the stylesheet to finish. A CSS-only rename would
    have left that spinner still."""
    js = (ROOT / "static" / "js" / "settings.js").read_text(encoding="utf-8")
    assert "whirlpool-spin" not in js
    assert re.search(r"animation:\s*spin\s", js), "the inline spinner lost its animation"


@pytest.mark.parametrize("gone", ["admin-spinner", "email-spinner"])
def test_the_sweep_did_not_eat_a_class_that_merely_starts_the_same(gone):
    """`admin-spin` is a prefix of `admin-spinner`, and a rename without word
    boundaries would have renamed a live class to `spinner`. Both classes are
    still here."""
    assert gone in CSS, gone
