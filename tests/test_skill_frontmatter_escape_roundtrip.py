# SPDX-License-Identifier: AGPL-3.0-or-later
"""Regression for issue #5210 — SKILL.md frontmatter scalars must round-trip.

``_emit_scalar`` quotes a scalar with ``json.dumps`` whenever it contains
punctuation that would change how the line reads back. ``_parse_scalar`` used
to undo that with a bare ``raw[1:-1]``: it stripped the quotes but never
decoded the escapes. So ``"Pr\\u00fcfung"`` was read back as the literal text
``Pr\\u00fcfung``, and the next save escaped *that* backslash again.

The damage compounds — each save doubles the backslash run — so a German or
Japanese skill description degrades into backslash noise after a handful of
edits, and the same happens to a plain-ASCII description that merely contains
a quote character. The escapes are also shown verbatim in the skills list and
the ``/skills`` catalog.

The fix is symmetric: emit with ``ensure_ascii=False`` (SKILL.md is UTF-8 at
both ends) and parse double-quoted scalars with ``json.loads``.
"""

import json

import pytest

from services.memory.skill_format import (
    Skill,
    _emit_scalar,
    _parse_scalar,
    emit_frontmatter,
    parse_frontmatter,
)
from services.memory.skills import SkillsManager

# Umlauts plus a comma — the comma is what forces the quoted form, which is the
# only path that was corrupted. Reported verbatim in issue #5210.
GERMAN = "Einstiegs- und Pr\u00fcfungslinie f\u00fcr AGB, Datenschutz"
JAPANESE = "\u30b9\u30ad\u30eb: \u30c6\u30b9\u30c8\u7528\u306e\u8aac\u660e"
QUOTED_ASCII = 'Use the "grep" tool, then summarise'


def _cycle(skill: Skill, times: int = 1) -> Skill:
    """Save to markdown and read it straight back, `times` times over."""
    for _ in range(times):
        skill = Skill.from_markdown(skill.to_markdown())
    return skill


# ---------------------------------------------------------------------------
# The reported corruption
# ---------------------------------------------------------------------------


@pytest.mark.parametrize(
    "description",
    [GERMAN, JAPANESE, QUOTED_ASCII],
    ids=["german", "japanese", "quoted-ascii"],
)
def test_description_survives_repeated_saves(description):
    """Five load/save cycles must leave the text byte-identical.

    One cycle is enough to corrupt it; five is where the doubling became
    obvious in the field.
    """
    result = _cycle(Skill(name="demo", description=description), times=5)
    assert result.description == description


def test_corruption_does_not_compound_across_saves():
    """Pin the *growth*, not just the mismatch.

    The original defect was not a one-off mangling — the escaped form was
    re-escaped on every save, so the value grew without bound. A regression
    that reintroduced single-level mangling would still be caught by the test
    above; this one catches the runaway specifically.
    """
    skill = Skill(name="demo", description=GERMAN)
    lengths = []
    for _ in range(5):
        skill = _cycle(skill)
        lengths.append(len(skill.description))
    assert len(set(lengths)) == 1, f"description length drifted across saves: {lengths}"


# ---------------------------------------------------------------------------
# What actually lands on disk
# ---------------------------------------------------------------------------


def test_non_ascii_is_written_as_utf8_not_ascii_escapes():
    """SKILL.md is opened as UTF-8 at both ends, so \\uXXXX buys nothing and
    only makes the file unreadable to a human editing it."""
    markdown = Skill(name="demo", description=GERMAN).to_markdown()
    line = next(l for l in markdown.splitlines() if l.startswith("description:"))
    assert "Pr\u00fcfungslinie" in line
    assert "\\u00fc" not in line


def test_quoted_scalar_is_valid_json():
    """The emitted form is what the parser now feeds to json.loads, so the two
    halves cannot drift apart without this failing."""
    emitted = _emit_scalar(QUOTED_ASCII)
    assert json.loads(emitted) == QUOTED_ASCII


# ---------------------------------------------------------------------------
# Existing files
# ---------------------------------------------------------------------------


def test_legacy_ascii_escaped_file_is_read_correctly():
    """Files already written by the old emitter hold real JSON escapes, so the
    new parser recovers the intended text instead of the escape source."""
    markdown = '---\nname: demo\ndescription: "Pr\\u00fcfung, x"\n---\n\n'
    assert Skill.from_markdown(markdown).description == "Pr\u00fcfung, x"


def test_already_corrupted_file_heals_one_level_per_load():
    """A file that took one round of damage carries a doubled backslash. That
    is still valid JSON, so reading it yields the single-backslash form and the
    value stops degrading."""
    markdown = '---\nname: demo\ndescription: "Pr\\\\u00fcfung, x"\n---\n\n'
    once = Skill.from_markdown(markdown)
    assert once.description == "Pr\\u00fcfung, x"
    # And it is now stable rather than growing on every subsequent save.
    assert _cycle(once, times=3).description == "Pr\\u00fcfung, x"


def test_non_json_escape_falls_back_to_literal_reading():
    """A hand-written frontmatter value can hold escapes JSON rejects (a bare
    Windows path is the common one). Those must keep their previous literal
    reading rather than raising."""
    assert _parse_scalar('"C:\\Users\\demo"') == "C:\\Users\\demo"


# ---------------------------------------------------------------------------
# Unchanged behaviour
# ---------------------------------------------------------------------------


def test_plain_scalars_are_still_emitted_bare():
    """Only values needing quotes get them — the common case must not suddenly
    start quoting, which would churn every SKILL.md on disk."""
    assert _emit_scalar("open-pr-from-branch") == "open-pr-from-branch"
    assert _emit_scalar("1.0.0") == "1.0.0"
    assert _emit_scalar(True) == "true"
    assert _emit_scalar(None) == "null"
    assert _emit_scalar(0.8) == "0.8"


def test_single_quoted_scalar_keeps_literal_reading():
    """Only double-quoted scalars are JSON. Single-quoted ones are read the way
    they always were."""
    assert _parse_scalar("'plain, text'") == "plain, text"


def test_lists_round_trip_with_non_ascii_entries():
    skill = Skill(name="demo", tags=["b\u00fcro", "recht, steuern"])
    assert _cycle(skill, times=3).tags == ["b\u00fcro", "recht, steuern"]


# ---------------------------------------------------------------------------
# Line-break characters
# ---------------------------------------------------------------------------


@pytest.mark.parametrize(
    "sep",
    ["\u2028", "\u2029", "\x85", "\r", "\v", "\f", "\x1c"],
    ids=["ls", "ps", "nel", "cr", "vt", "ff", "fs"],
)
def test_line_break_characters_do_not_split_the_frontmatter(sep):
    """parse_frontmatter() reads one scalar per line via str.splitlines(),
    which breaks on far more than \\n. Any of these landing unescaped in the
    file would silently truncate the value and shift the remainder into a
    bogus key.

    json.dumps covers the C0 ones, but with ensure_ascii=False it passes NEL,
    LINE SEPARATOR and PARAGRAPH SEPARATOR through as themselves — so those
    three are re-escaped explicitly.
    """
    description = f"before{sep}after, x"
    markdown = Skill(name="demo", description=description).to_markdown()

    frontmatter_text = markdown.split("---")[1]
    assert len(frontmatter_text.strip().splitlines()) == len(
        [l for l in frontmatter_text.strip().split("\n") if l.strip()]
    ), "a scalar leaked a line break into the frontmatter"

    fm, _body = parse_frontmatter(markdown)
    assert fm["description"] == description


# ---------------------------------------------------------------------------
# End to end, through real files
# ---------------------------------------------------------------------------


def test_description_survives_real_save_load_cycles_on_disk(tmp_path):
    """The unit tests above go straight through to_markdown/from_markdown.
    This drives the same path the app does — SkillsManager writing UTF-8 files
    with atomic_write_text and reading them back — because the encoding used at
    either end is part of the fix.
    """
    manager = SkillsManager(str(tmp_path))
    manager.add_skill(name="agb-pruefung", description=GERMAN, category="general")

    for _ in range(4):
        assert manager.update_skill("agb-pruefung", {"status": "published"})

    stored = [s for s in manager.load_all() if s["name"] == "agb-pruefung"]
    assert len(stored) == 1
    assert stored[0]["description"] == GERMAN

    on_disk = (tmp_path / "skills" / "general" / "agb-pruefung" / "SKILL.md").read_text(
        encoding="utf-8"
    )
    assert GERMAN in on_disk


# ---------------------------------------------------------------------------
# `B1976`. A quote inside a list item
# ---------------------------------------------------------------------------
#
# Every list is written inline, `tags: [a, "b, c"]`, and an item that needs
# quotes is written with json.dumps, so a `"` inside it goes to disk as `\"`.
# `_split_top_level`, which cuts a list into items, ended a quoted item at the
# next `"` whether or not a backslash came before it. An item holding an odd
# number of quotes, anywhere but last, ran on into the items after it:
# `['12" pipe', 'plumbing']` read back as one item, and the next save wrote
# that. The tags of the Add form, the raw editor and the model's own edits all
# take this path. Ported from upstream Odysseus 2019a973 (#6265), with its
# cases and a few more.


@pytest.mark.parametrize(
    "tags",
    [
        ['review "release, notes', 'use "search", then summarize', "publish"],
        ['12" pipe', "plumbing"],
        ['a"b', "c"],
        ['a"b"c"d', "e"],
    ],
    ids=["quote-and-comma", "inch-mark", "one-quote", "three-quotes"],
)
def test_a_list_item_holding_a_quote_survives_repeated_saves(tags):
    skill = Skill(name="release-review", tags=tags)
    for _ in range(5):
        skill = _cycle(skill)
        assert skill.tags == tags


@pytest.mark.parametrize("field", ["tags", "platforms", "requires_toolsets", "fallback_for_toolsets"])
def test_every_list_field_keeps_a_quoted_item_whole(field):
    values = ['review "release, notes', "publish"]
    restored = _cycle(Skill(name="release-review", **{field: values}))
    assert getattr(restored, field) == values


def test_a_backslash_escapes_inside_double_quotes_and_is_literal_inside_single_ones():
    for count in range(1, 5):
        values = ["review " + "\\" * count + '"release, notes', "path, " + "\\" * count, "publish"]
        parsed, _ = parse_frontmatter(f"---\n{emit_frontmatter({'tags': values})}\n---\n")
        assert parsed["tags"] == values, f"{count} backslash(es)"
    # Only a double-quoted item is JSON; a single-quoted one reads as written.
    parsed, _ = parse_frontmatter("---\ntags: ['C:\\', next]\n---\n")
    assert parsed["tags"] == ["C:\\", "next"]


def test_a_nested_list_keeps_a_quoted_bracket_and_comma():
    values = [['review "], notes', "publish"], "archive"]
    parsed, _ = parse_frontmatter(f"---\n{emit_frontmatter({'tags': values})}\n---\n")
    assert parsed["tags"] == values
