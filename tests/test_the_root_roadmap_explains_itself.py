# SPDX-License-Identifier: AGPL-3.0-or-later
"""`B356` — the root `ROADMAP.md` may not justify itself with somebody else's link.

The file is a pointer page: the tracker is `.pantheon/ROADMAP.md`. It is kept
rather than deleted, and the reason it is kept is load-bearing — it is the only
thing standing between the path and the next person who tidies up.

For a while that reason was *"`.github/ISSUE_TEMPLATE/feature_request.yml`
links it by absolute URL, and a link that 404s is not an improvement on a link
that lies"*. True when written. The template was then repointed at
`.pantheon/ROADMAP.md`, so the page spent some time justified by a link that no
longer came to it, and `B355` repointed the template back — which made the
sentence true again **by coincidence**. A reason that is true by coincidence is
not a reason, and nothing noticed either move.

So the page states a reason that is a property of the tracker — 1.4 MB does not
render on GitHub, and no anchor into it survives an edit — and these tests hold
it there. They are about the *shape* of the argument, not its wording: the file
may say whatever it likes as long as it does not hang its existence on a link
it does not control.
"""
import re
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
ROOT_ROADMAP = ROOT / "ROADMAP.md"
TRACKER = ROOT / ".pantheon" / "ROADMAP.md"


def _text() -> str:
    return ROOT_ROADMAP.read_text(encoding="utf-8")


def test_the_pointer_page_exists_and_names_the_tracker():
    assert ROOT_ROADMAP.exists(), (
        "root ROADMAP.md is the address people and tools try by convention, and "
        "for three days it served upstream's roadmap under our name. See B356.")
    assert ".pantheon/ROADMAP.md" in _text()


def test_the_tracker_is_still_too_large_for_github_to_render():
    """The stated reason, re-measured rather than quoted.

    GitHub stops rendering Markdown at 1 MB and refuses to serve the blob view
    at 5 MB. If this ever drops below the threshold the argument on the page
    has stopped being true and somebody has to write a different one — which is
    the whole point of measuring it here instead of trusting the sentence.
    """
    size = TRACKER.stat().st_size
    assert size > 1_000_000, (
        f".pantheon/ROADMAP.md is {size:,} bytes. Root ROADMAP.md says it is too "
        f"large for GitHub to render; below 1 MB that is no longer true and the "
        f"page needs a different reason or no page (B356).")


def test_the_reason_it_exists_does_not_depend_on_a_link_somebody_else_owns():
    """No `.github/` path may appear in the paragraph that keeps this file.

    The page is allowed to *narrate* the history of the template link — it
    does, because that history is why this rule exists — but it may not carry a
    sentence of the form "this file is kept because <a template> links it".
    """
    text = _text()
    for match in re.finditer(r"\.github/[\w/.-]+", text):
        sentence_start = max(text.rfind(".", 0, match.start()),
                             text.rfind("\n\n", 0, match.start()))
        sentence = text[sentence_start + 1:text.find(".", match.end()) + 1]
        claim = re.search(r"\b(kept|keep|exists?|reason)\b", sentence, re.I)
        assert not claim or "was repointed" in sentence or "justified" in sentence, (
            f"root ROADMAP.md appears to justify its own existence with "
            f"{match.group(0)}: {sentence.strip()!r}. That link has already moved "
            f"twice. State a reason the tracker gives you (B356).")


def test_the_page_says_why_it_is_kept_at_all():
    """A pointer page with no argument gets deleted by the next tidy-up."""
    text = _text().lower()
    assert "why this path is kept" in text or "kept rather than deleted" in text, (
        "root ROADMAP.md no longer says why it exists. It is two lines of "
        "redirect; without the reason, deleting it looks like an improvement.")
