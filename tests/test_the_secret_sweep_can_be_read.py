# SPDX-License-Identifier: AGPL-3.0-or-later
"""`B770` — the pre-publication secret grep fired on the word `task-`.

`SECURITY.md` carries the checklist a fork runs before its first public push, and
`P10-11` is the row that says to run it. Its `sk-` alternation had no left anchor,
so `sk-[A-Za-z0-9_-]{20,}` matched inside `task-card-delete-busy-label` and
`task-form-output-email-account` — over a hundred lines of `static/`, with a real
key indistinguishable among them. A check whose output nobody can read is a check
nobody runs, which is the same defect class as a ratchet with slack in it.

These tests drive the patterns rather than reading the file (`Law 20`): the
document's own regexes are extracted and run against strings that are secrets and
strings that are not.
"""
import pathlib
import re

import pytest

SECURITY = pathlib.Path(__file__).resolve().parents[1] / "SECURITY.md"


def _patterns():
    """Every `-E '...'` regex in the fork checklist, as the shell would see it."""
    text = SECURITY.read_text(encoding="utf-8")
    block = text.split("Before pushing a public fork, run:")[1].split("```")[1]
    found = re.findall(r"-[aoE]*E\s+'([^']+)'", block)
    assert found, "the checklist no longer carries an -E pattern"
    return found


def _secret_patterns():
    """The ones about credentials, not the one about filenames."""
    out = [p for p in _patterns() if "sk-" in p]
    assert out, "no credential pattern in the checklist"
    return out


NOT_SECRETS = [
    "task-card-delete-busy-label",
    "task-form-output-email-account",
    "task-completed-preview-row",
    "disk-usage-indicator-wrapper",
    "risk-assessment-panel-header",
]

SECRETS = [
    "sk-abcdefghijklmnopqrstuvwxyz",
    "xoxb-1234567890-abcdefghij",
    "ghp_aaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaa",
    "AKIAIOSFODNN7EXAMPLE",
    "-----BEGIN RSA PRIVATE KEY-----",
]


@pytest.mark.parametrize("text", NOT_SECRETS)
def test_an_ordinary_class_name_is_not_a_secret(text):
    for pattern in _secret_patterns():
        assert not re.search(pattern, text), (
            f"the checklist's own regex calls {text!r} a credential — "
            "that is how a hundred false positives hide one real key")


@pytest.mark.parametrize("text", SECRETS)
def test_a_real_credential_shape_is_still_caught(text):
    """The anchor must not have been bought by narrowing the net."""
    assert any(re.search(pattern, " " + text) for pattern in _secret_patterns()), (
        f"{text!r} is not matched by any pattern in the checklist")


def test_the_checklist_looks_at_history_and_not_only_the_working_tree():
    """A public repository exposes every commit, and a rewrite afterwards does
    not un-publish one. Checking `git grep` alone answers a smaller question
    than the one being asked."""
    block = SECURITY.read_text(encoding="utf-8").split(
        "Before pushing a public fork, run:")[1].split("```")[1]
    assert "git log --all" in block, (
        "the sweep only reads the working tree; a secret removed in a later "
        "commit is still published")


def test_the_checklist_looks_for_credential_files_too():
    """A committed `auth.json` or `.pem` carries no `sk-` string and is worse
    than one that does."""
    block = SECURITY.read_text(encoding="utf-8").split(
        "Before pushing a public fork, run:")[1].split("```")[1]
    assert "--diff-filter=A" in block, (
        "nothing in the sweep would notice a credential *file* being added")
