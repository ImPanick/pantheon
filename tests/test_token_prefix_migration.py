# SPDX-License-Identifier: AGPL-3.0-or-later
"""P0-31 — the fork's old name was on the credential you paste into a machine.

`ody_` is Odysseus. Every API token this product minted began with it, and an
API token is not an internal identifier: it is the one string a user copies out
of Pantheon and into something else — a Prometheus scrape config, a phone that
was paired once, an `.env` on a box in another room, a Claude Code session's
environment. The row that was scoped to find the `ody` residue looked past it
three times, because its own regex matched `ody-` and `ody.` and not `ody_`.

So this is a migration and not a rename, and the difference is the whole row.
A rename mints `pan_` and stops accepting `ody_`, which revokes every token
already issued, at once, silently, on upgrade — a phone that cannot be
re-paired without physically holding it, a scrape that starts 401ing at 3am.
A migration mints one prefix and honours two.

These tests are the promise. The first three say new tokens carry the new name;
the rest say the old ones keep working, and that nothing in the shipped docs
tells a new user to expect the old one.
"""
import pathlib

import pytest

from core.api_tokens import (
    ACCEPTED_TOKEN_PREFIXES,
    TOKEN_PREFIX,
    TOKEN_PREFIX_LEN,
    bearer_credential,
    mint_raw_token,
)

ROOT = pathlib.Path(__file__).resolve().parent.parent

# The prefix this fork inherited. Written out rather than indexed out of the
# tuple: a test that says "the second entry keeps working" stops meaning
# anything the moment a third is added.
LEGACY_PREFIX = "ody_"


def test_new_tokens_carry_the_new_name():
    assert TOKEN_PREFIX == "pan_"
    assert mint_raw_token().startswith("pan_")


def test_nothing_mints_the_inherited_prefix_any_more():
    assert TOKEN_PREFIX != LEGACY_PREFIX
    for _ in range(20):
        assert not mint_raw_token().startswith(LEGACY_PREFIX)


def test_the_inherited_prefix_is_still_honoured():
    """The migration, in one line. Delete this test and you have a rename."""
    assert LEGACY_PREFIX in ACCEPTED_TOKEN_PREFIXES, (
        "dropping the inherited prefix revokes every token minted before "
        "2026-09-07 — including ones on machines nobody can reach to re-pair"
    )
    legacy = LEGACY_PREFIX + "x" * 43
    assert bearer_credential(f"Bearer {legacy}") == legacy


def test_both_prefixes_bucket_the_same_way():
    """`_refresh_token_cache` keys on the row's stored `token_prefix` and the
    middleware looks up `raw[:TOKEN_PREFIX_LEN]`. A prefix of a different length
    would put the two on different sides of the same map."""
    assert len({len(p) for p in ACCEPTED_TOKEN_PREFIXES}) == 1
    for prefix in ACCEPTED_TOKEN_PREFIXES:
        raw = prefix + "x" * 43
        assert len(raw[:TOKEN_PREFIX_LEN]) == TOKEN_PREFIX_LEN
        assert raw[:TOKEN_PREFIX_LEN].startswith(prefix)


def test_both_prefixes_survive_the_middleware_length_window():
    """`app.py` rejects anything outside 12..100 characters before it looks at
    a hash. Both shapes are 47."""
    for prefix in ACCEPTED_TOKEN_PREFIXES:
        raw = prefix + "x" * 43
        assert 12 <= len(raw) <= 100, prefix


def test_the_new_prefix_is_first():
    """Not load-bearing today, and it is the documented convention: whatever is
    being minted leads, and everything after it is legacy."""
    assert ACCEPTED_TOKEN_PREFIXES[0] == TOKEN_PREFIX


# --- what a new user is told ----------------------------------------------

DOCUMENTED = (
    ".env.example",
    "docs/setup.md",
    "integrations/claude/README.md",
    "integrations/codex/README.md",
)


@pytest.mark.parametrize("rel", DOCUMENTED)
def test_no_shipped_example_hands_out_the_old_prefix(rel):
    """These four files are read by someone setting up a token for the first
    time, and all four printed `ody_…` as the shape to expect."""
    text = (ROOT / rel).read_text(encoding="utf-8")
    assert LEGACY_PREFIX not in text, (
        f"{rel} still shows the inherited prefix in an example a new user "
        "will copy"
    )
    assert TOKEN_PREFIX in text, (
        f"{rel} lost its example entirely — the point was to update it, not "
        "to delete it"
    )
