# SPDX-License-Identifier: AGPL-3.0-or-later
"""`B450` — the version the app reports and the version the changelog documents.

Before 2026-09-17 `CHANGELOG.md` had one section, `## [Unreleased]`, and the app
reported `1.0.3`. Neither could be checked against the other, because there was
nothing to check: no dated heading, no tag, no release. `SECURITY.md` said as
much — *"Tagged releases: None exist yet"* — and the one identifier it offered a
self-hoster was `git show -s HEAD`.

The cost is not abstract. `CHANGELOG.md` already carried two *Changed — read this
before upgrading* blocks (`B96`, `B152`) describing behaviour changes that alter
what an operator's host does without them editing anything. Those are release
notes. An operator could not be told *which upgrade* contains them, because
upgrades had no names.

These tests hold the three-way agreement the scheme depends on — the constant,
the newest dated heading, and (by hand, at tag time) the tag — and they hold the
shape a reader needs to diff two versions: an `[Unreleased]` section above the
newest release, and the same sub-headings under each release in the same order.
"""
import re
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

CHANGELOG = (ROOT / "CHANGELOG.md").read_text(encoding="utf-8")

RELEASE_HEADING = re.compile(r"^## \[(\d+\.\d+\.\d+)\](?: — (\d{4}-\d{2}-\d{2}))?\s*$", re.M)
UNRELEASED = re.compile(r"^## \[Unreleased\]\s*$", re.M)


def _app_version() -> str:
    from src.constants import APP_VERSION
    return APP_VERSION


def _releases() -> list[tuple[str, str, int]]:
    """`(version, date, offset)` for every dated release heading, newest first."""
    return [(m.group(1), m.group(2), m.start())
            for m in RELEASE_HEADING.finditer(CHANGELOG) if m.group(2)]


def test_the_changelog_names_at_least_one_release():
    """Fails on the tree as it stood: the only section was `[Unreleased]`."""
    assert _releases(), (
        "CHANGELOG.md has no `## [x.y.z] — YYYY-MM-DD` section. A changelog "
        "with one open section cannot answer 'what changed between the version "
        "I run and the one I am about to pull' — see § Versions."
    )


def test_the_newest_release_heading_is_the_version_the_app_reports():
    version, _date, _at = _releases()[0]
    assert version == _app_version(), (
        f"CHANGELOG.md's newest release is {version} and the app reports "
        f"{_app_version()}. Cutting a release moves both, or the tag matches "
        f"neither."
    )


def test_an_unreleased_section_exists_and_sits_above_the_newest_release():
    m = UNRELEASED.search(CHANGELOG)
    assert m, "no `## [Unreleased]` — new entries have nowhere to land"
    assert m.start() < _releases()[0][2], (
        "`[Unreleased]` is below the newest release. Newest first, or a reader "
        "diffing two versions reads them in the wrong order."
    )


def test_release_headings_descend():
    versions = [tuple(int(p) for p in v.split(".")) for v, _d, _at in _releases()]
    assert versions == sorted(versions, reverse=True), versions


def test_the_released_section_carries_the_headings_a_reader_diffs_on():
    """The four sub-headings, in order, under the newest release.

    The order is the contract: *Changed — read this before upgrading* is the one
    block that can alter a host's behaviour without the operator editing
    anything, and the file's own opening paragraph links straight to it. A
    release that drops it or moves it breaks that link.
    """
    _v, _d, at = _releases()[0]
    body = CHANGELOG[at:]
    nxt = RELEASE_HEADING.search(body, 1)
    if nxt:
        body = body[:nxt.start()]
    wanted = ["#### Renamed", "#### Added",
              "#### Changed — read this before upgrading", "#### Fixed"]
    found = [h for h in re.findall(r"^#### .+$", body, re.M) if h in wanted]
    assert found == wanted, f"{found} != {wanted}"


def test_the_upgrade_anchor_at_the_top_still_resolves():
    """The first paragraph links `#changed--read-this-before-upgrading`. Moving
    the heading under a release heading must not change the anchor GitHub
    generates for it."""
    assert "(#changed--read-this-before-upgrading)" in CHANGELOG
    assert re.search(r"^#### Changed — read this before upgrading\s*$",
                     CHANGELOG, re.M)


def test_the_scheme_is_written_down_where_the_next_person_will_look():
    """`Law 9` — a number with no stated rule is a number the next author
    guesses at. The section names the three things that have to agree."""
    assert re.search(r"^## Versions\s*$", CHANGELOG, re.M)
    section = CHANGELOG.split("## Versions", 1)[1].split("\n## ", 1)[0]
    for needle in ("APP_VERSION", "git tag", "1.0.0", "SHIP-LINE"):
        assert needle in section, f"§ Versions does not mention {needle!r}"
