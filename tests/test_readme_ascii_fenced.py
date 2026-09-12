# SPDX-License-Identifier: AGPL-3.0-or-later
"""Regression guard for the README title presentation.

Originally (#1390) the README opened with an ASCII-art banner that had to live
inside a ``` code fence, otherwise GitHub's markdown collapsed its leading
whitespace and box-drawing rules and rendered it misaligned. The README refresh
(#4306) dropped that banner in favour of a centered wordmark image, so the guard
pinned the wordmark image instead, while still catching the original failure
mode if an un-fenced ASCII banner is ever reintroduced.

**THIS FORK HAS NO WORDMARK IMAGE, AND THAT IS A RECORDED DECISION.** `P0-13`
says so directly: *"Do not reuse the red sailing boat, the wordmark, or the
per-route favicon shapes — the licence grants them but they are upstream's
identity."* `docs/pantheon-wordmark.png` was upstream's mark **renamed and never
repainted** — the file said `pantheon` and the pixels said `Odysseus` — so it was
orphaned rather than shipped, and `B71` removes it. The README opens with a
centered `<h1>` until the mark `P0-13` is blocked on exists.

So the guard pins the **intent** — a recognisable Pantheon title in the first few
lines — and accepts either form. It is not weakened: the `#1390` ASCII-fence
guard below is untouched, and an image is still accepted the moment there is an
honest one to use.
"""
from pathlib import Path

README = Path(__file__).resolve().parent.parent / "README.md"

# Box-drawing rule from the legacy ASCII banner (the #1390 failure mode).
_RULE = "─" * 10


def _fenced_segments(text: str):
    """Return the segments of *text* that sit INSIDE ``` fences."""
    parts = text.split("```")
    # parts[0] is before the first fence, parts[1] is inside the first fence, ...
    return parts[1::2]


def test_readme_opens_with_a_pantheon_title():
    # Either form: the wordmark image once one exists (`P0-13`), or the centered
    # H1 the fork uses meanwhile. What must not happen is the README opening
    # with neither, or with upstream's identity.
    head = "\n".join(README.read_text(encoding="utf-8").splitlines()[:15])
    assert 'alt="Pantheon"' in head or "<h1" in head, (
        "README must open with a recognisable Pantheon title"
    )
    assert "Pantheon" in head
    assert "Odysseus" not in head.replace("forked%20from-Odysseus", "").replace(
        'alt="Forked from Odysseus"', ""
    ), "the README must not open under upstream's identity (the badge is fine)"


def test_reintroduced_ascii_banner_stays_fenced():
    # Defensive: if a box-drawing banner is ever added back, it must be fenced so
    # GitHub renders it monospace-as-typed (the original #1390 regression).
    text = README.read_text(encoding="utf-8")
    if _RULE not in text:
        return
    inside = "\n".join(_fenced_segments(text))
    assert _RULE in inside, "ASCII banner rule must be inside a ``` code fence"
