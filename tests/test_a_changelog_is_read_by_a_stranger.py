# SPDX-License-Identifier: AGPL-3.0-or-later
"""`B25` — the changelog claimed an AGPL §13 source link that never shipped.

`CHANGELOG.md` listed *"Source link in the UI footer, per AGPL-3.0 §13"* under
`#### Added` from the fork baseline. There is no such link anywhere in the UI:
the only repository URL in the frontend is an issue-tracker fallback behind the
admin panel (`static/js/admin.js`), and `static/index.html` has no `<footer>`
at all.

`D-2026-09-08-06` settled what to do and settled it the other way round from
what the row assumed: **the line comes out now** rather than waiting for the
repository to go public. A changelog is what a stranger reads to audit
conformance, and a false compliance claim is worse while the repo is private,
not better — nobody can check it. The link itself is `P0-17`, built and left
dark against a repository URL that ships empty.

**This is an engineering read of the licence text and not legal advice**, and
the distinction matters here: §13's obligation attaches to whoever *offers* a
modified version over a network. This repo is private and the default bind is
loopback, so nothing was out of compliance. What was wrong was the sentence.
"""
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
CHANGELOG = (ROOT / "CHANGELOG.md").read_text(encoding="utf-8")


def _added_section() -> str:
    body = CHANGELOG.split("#### Added", 1)[1]
    return body.split("####", 1)[0]


def test_the_changelog_does_not_claim_a_source_link_that_is_not_there():
    added = _added_section()
    # The withdrawal note quotes the old line, which is the point of a
    # withdrawal note — so look at what the section actually LISTS.
    listed = [ln for ln in added.splitlines() if ln.strip().startswith("- ")]
    assert not [ln for ln in listed if "§13" in ln or "AGPL" in ln], listed


def test_the_line_was_withdrawn_rather_than_quietly_deleted():
    """`Law 1`'s cousin: a record of what was claimed is evidence, and a
    silently corrected record is a different kind of dishonesty (`B44`)."""
    assert "B25" in CHANGELOG
    assert "D-2026-09-08-06" in CHANGELOG


def test_the_ui_still_has_no_source_link_so_the_withdrawal_is_current():
    """If `P0-17` lands, this test fails and the changelog line goes back.

    It looks for a repository link in the two shipped HTML surfaces rather
    than trusting the row — the claim is about what a user can see.
    """
    shell = (ROOT / "static" / "index.html").read_text(encoding="utf-8")
    login = (ROOT / "static" / "login.html").read_text(encoding="utf-8")
    for name, page in (("index.html", shell), ("login.html", login)):
        rendered = [ln for ln in page.splitlines()
                    if "github.com" in ln and not ln.lstrip().startswith(("<!--", "*", "//"))]
        assert not rendered, (
            f"{name} now links out — if this is P0-17's source link, restore the "
            f"CHANGELOG entry it withdrew"
        )
