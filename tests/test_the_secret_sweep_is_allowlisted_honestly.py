# SPDX-License-Identifier: AGPL-3.0-or-later
"""`B851` — every gitleaks allowlist entry is one literal with a reason.

The first CI run this repository ever completed scanned 2,202 commits and
reported four findings, all of them fake secrets on purpose and three of them
inside the tests that prove this product redacts secrets. An allowlist was
needed. An allowlist is also the easiest place in a repository to hide a real
credential, so this file is the thing that stops that.

Two rules, both driven off `.gitleaks.toml` itself:

  * **no path allowlists.** Allowlisting `tests/` means a real key pasted into a
    test while debugging is never seen again, and a test is exactly where
    somebody pastes one.
  * **no commit fingerprints.** The transfer procedure in `.pantheon/` re-authors
    commits, so a fingerprint changes for reasons unrelated to what it pins —
    the shape `B520` names, and the ninth instance of it cost a red suite.

And one rule about the entries themselves: each must still match something in
the tree. An allowlist entry for a literal nobody writes any more is a hole kept
open for no reason.
"""
import pathlib
import re

import pytest

ROOT = pathlib.Path(__file__).resolve().parents[1]
CONFIG = ROOT / ".gitleaks.toml"


def _config() -> str:
    assert CONFIG.exists(), (
        ".gitleaks.toml is gone — the secret scan then runs on defaults and "
        "goes red on the redaction fixtures again")
    return CONFIG.read_text(encoding="utf-8")


def _allowlisted_literals() -> list[str]:
    """Every regex inside a `[rules.allowlist] regexes = [...]` block."""
    text = _config()
    block = re.search(r"regexes\s*=\s*\[(.*?)\]", text, re.S)
    assert block, "no allowlist regexes in .gitleaks.toml"
    found = re.findall(r"'''(.*?)'''", block.group(1), re.S)
    assert found, "the allowlist block parsed to nothing"
    return [f.strip() for f in found]


def _uncommented_lines() -> list[str]:
    """The config with its `#` comments dropped.

    The first version of the test below read the whole file and asserted the
    *word* `paths` was absent — and went red on its own explanatory comment,
    which says *"no path allowlists"*. A predicate about prose is not a
    predicate about configuration (`Law 20`), and this is the smallest possible
    instance of it.
    """
    return [ln for ln in _config().splitlines()
            if not ln.lstrip().startswith("#")]


def test_the_allowlist_is_literals_and_not_paths():
    """A path allowlist silences a whole file for ever."""
    for key in ("paths", "commits", "stopwords"):
        offenders = [ln for ln in _uncommented_lines()
                     if re.match(rf"\s*{key}\s*=", ln)]
        assert not offenders, (
            f"`{key}` is set in .gitleaks.toml: {offenders}. A path or commit "
            "allowlist silences far more than the literal it was added for — a "
            "real key pasted into that file, or into any commit, is never "
            "reported again.")


def test_every_allowlisted_literal_carries_a_reason():
    """A bare regex in an allowlist is a hole with no name on it."""
    text = _config()
    for literal in _allowlisted_literals():
        line_no = next(i for i, ln in enumerate(text.splitlines())
                       if literal in ln)
        above = text.splitlines()[max(0, line_no - 6):line_no]
        assert any(ln.lstrip().startswith("#") and len(ln.strip()) > 8
                   for ln in above), (
            f"{literal!r} is allowlisted with no comment above it saying why "
            "it is not a credential")


@pytest.mark.parametrize("literal", _allowlisted_literals())
def test_every_allowlisted_literal_is_still_written_somewhere(literal):
    """An entry for a string nobody writes any more is a hole kept open for
    nothing. This is the entry's own expiry check."""
    hits = [p for p in ROOT.rglob("*")
            if p.is_file()
            and p.suffix in (".py", ".md", ".txt", ".js", ".html")
            and ".git/" not in p.as_posix()
            and "node_modules" not in p.as_posix()
            and "__pycache__" not in p.as_posix()
            and p.name != CONFIG.name
            and literal in p.read_text(encoding="utf-8", errors="ignore")]
    assert hits, (
        f"{literal!r} is allowlisted and appears nowhere in the tree — delete "
        "the entry rather than leaving the hole open")


@pytest.mark.parametrize("literal", _allowlisted_literals())
def test_no_allowlisted_literal_looks_like_a_real_credential(literal):
    """The narrow judgement, written down so it can be argued with.

    Every current entry is fake by construction: a sequential alphabet, a run of
    repeated letters, a patient-record string that is an obvious test persona, or
    `abc123`. A future entry that is none of those should have to justify itself
    here rather than slide in beside them.
    """
    fake_markers = (
        "ABCDEFGHIJKLMNOP",   # sequential
        "AAAABBBBCCCCDDDD",   # repeated runs
        "Jane-Doe",           # a test persona
        "abc123",             # the universal placeholder
    )
    assert any(m in literal for m in fake_markers), (
        f"{literal!r} does not carry any of the markers that make the existing "
        "entries obviously fake — say in this test why it is safe, or do not "
        "allowlist it")


def test_the_config_does_not_redefine_a_rule_gitleaks_already_ships():
    """`B863`. `useDefault = true` REPLACES a rule of the same id; it does not
    merge into it.

    The first version of this file put the allowlist inside a `[[rules]]` block
    with `id = "generic-api-key"`, which is the id of a rule gitleaks ships. The
    default rule's own allowlist and stopwords went with it, its regex had to be
    hand-copied here — a second copy of something upstream maintains (`Law 13`)
    — and the next CI run reported a finding the original four had never
    included, because the stopword that had been suppressing it was gone.

    The allowlist belongs at the top level, where it applies to every rule and
    replaces none of them. This is asserted structurally rather than by reading
    the prose: a `[[rules]]` table is either absent, or it declares an id that is
    not one of gitleaks' own.
    """
    lines = _uncommented_lines()
    rule_ids = []
    in_rule = False
    for line in lines:
        stripped = line.strip()
        if stripped == "[[rules]]":
            in_rule = True
            continue
        if stripped.startswith("[") and stripped != "[[rules]]":
            in_rule = False
        if in_rule:
            match = re.match(r'id\s*=\s*["\']([^"\']+)["\']', stripped)
            if match:
                rule_ids.append(match.group(1))

    shipped = {"generic-api-key", "github-pat", "github-fine-grained-pat",
               "openai-api-key", "stripe-access-token", "private-key",
               "aws-access-token", "slack-bot-token"}
    overridden = sorted(set(rule_ids) & shipped)
    assert not overridden, (
        f"this config redefines {overridden}, which `useDefault = true` "
        "replaces rather than extends — the shipped rule's own allowlist, "
        "stopwords and regex are all lost. Put the exception in the top-level "
        "[allowlist] instead (`B863`)")


def test_the_allowlist_is_global_and_not_bolted_to_one_rule():
    """The positive half: there IS a top-level allowlist, and it is where the
    literals live."""
    lines = _uncommented_lines()
    assert any(ln.strip() == "[allowlist]" for ln in lines), (
        "the literals are excused somewhere other than the top-level allowlist")
    assert _allowlisted_literals(), "the allowlist is empty"
