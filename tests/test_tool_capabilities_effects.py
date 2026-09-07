# SPDX-License-Identifier: AGPL-3.0-or-later
"""P7-06: the severity ordering itself, beside the table it ranks.

`tests/test_tool_effect_wire.py` opens by saying it pins the wire and not the
ranking, "the ordering itself is covered beside the table it ranks". That
sentence was false when it was written and it licensed a real gap: no test
anywhere imported `effect_severity`, `effect_band` or `describe_effects`, and
refutation walked five mutations straight through a green suite —

  * an unrecognised effect ranked LOWEST instead of highest, so a value nobody
    has classified renders as the most harmless thing on the card;
  * the `serious` threshold raised by one rung, quietly demoting every
    "changes something outside this app" action to `notable`;
  * `DESTRUCTIVE`'s phrase reworded to "Reads public information", which is the
    exact inversion `Law 15` exists to prevent — the sentence a person reads
    before consenting saying the opposite of what will happen;
  * effect keys dropped from the `ask_user` card payload and from both
    persisted tool events.

The last of those is closed in the wire file, beside the emits it belongs to.
This file is the first four: the ordering, the words, the bands, and the
resolver that hands all three to a surface.

Why this is worth a file of its own. `src/tool_capabilities.py` is the single
home for "which of these two effects should worry you more" — `Law 14`, and the
reason the wire carries a resolved rank instead of thirteen values a frontend
would have to order itself. A single home is only a safeguard while something
checks that what lives there is right; unchecked, it is just a single point of
failure with better documentation.
"""

import re
from pathlib import Path

import pytest

from src.tool_capabilities import (
    EFFECT_BAND_NOTABLE,
    EFFECT_BAND_ROUTINE,
    EFFECT_BAND_SERIOUS,
    ToolCapabilities,
    ToolEffect,
    _EFFECT_PHRASE,
    _EFFECT_SEVERITY,
    capabilities_for_tool,
    describe_effects,
    effect_band,
    effect_severity,
)

ROOT = Path(__file__).resolve().parents[1]

# The shape `describe_effects()` puts on the wire, spelled out here rather than
# derived from the function, so a renamed key fails instead of following along.
WIRE_KEYS = frozenset(
    {
        "effects",
        "effect",
        "effect_label",
        "effect_labels",
        "effect_severity",
        "effect_band",
    }
)

# Read off the thresholds as they stand. Written out as membership rather than
# recomputed from `effect_band`, because a test that asks the function which
# band it chose agrees with the function by construction and moves with it.
EXPECTED_BANDS = {
    EFFECT_BAND_ROUTINE: {
        ToolEffect.UI_SIDE_EFFECT,
        ToolEffect.USER_INTERACTION,
        ToolEffect.READ_PUBLIC,
        ToolEffect.READ_WORKSPACE,
        ToolEffect.BROKERED_NETWORK_READ,
    },
    EFFECT_BAND_NOTABLE: {
        ToolEffect.WRITE_WORKSPACE,
        ToolEffect.READ_PRIVATE,
        ToolEffect.EXECUTE_CODE,
        ToolEffect.NETWORK_EGRESS,
        ToolEffect.WRITE_PRIVATE,
    },
    EFFECT_BAND_SERIOUS: {
        ToolEffect.EXTERNAL_SIDE_EFFECT,
        ToolEffect.ADMIN_CHANGE,
        ToolEffect.DESTRUCTIVE,
    },
}


# ── The tables are total ────────────────────────────────────────────────────


def test_every_effect_has_both_a_rank_and_a_phrase():
    """A partly-filled table is worse than an empty one.

    An effect with a rank and no phrase renders its own identifier in the lead
    slot of the approval card — `admin_change`, set in 15px bold prose type,
    dressed as a sentence. An effect with a phrase and no rank falls to the
    unknown branch and is treated as the most severe thing on the card. Either
    way the surface looks like it knows what it is showing.
    """
    assert set(_EFFECT_SEVERITY) == set(ToolEffect), (
        "unranked: " + str(sorted(e.value for e in set(ToolEffect) - set(_EFFECT_SEVERITY)))
    )
    assert set(_EFFECT_PHRASE) == set(ToolEffect), (
        "unphrased: " + str(sorted(e.value for e in set(ToolEffect) - set(_EFFECT_PHRASE)))
    )


def test_no_two_effects_share_a_rank():
    # Equal ranks make "which of these matters more" unanswerable; the resolver
    # falls back to alphabetical order, so the card's lead becomes whichever
    # identifier sorts first, which is not a judgement about anything.
    ranks = list(_EFFECT_SEVERITY.values())
    assert len(set(ranks)) == len(ranks), f"duplicate ranks in {_EFFECT_SEVERITY}"


def test_the_bands_partition_the_taxonomy_exactly():
    # A threshold that moves silently is how "changes something outside this
    # app" ends up drawn in the same treatment as "writes workspace files".
    actual = {name: set() for name in EXPECTED_BANDS}
    for effect in ToolEffect:
        actual[effect_band(effect_severity(effect))].add(effect)
    assert actual == EXPECTED_BANDS, (
        "band membership moved; if this is deliberate, the surfaces in "
        "static/style.css draw three treatments and the change has to be "
        "reviewed against them"
    )
    assert set().union(*EXPECTED_BANDS.values()) == set(ToolEffect)
    assert sum(len(members) for members in EXPECTED_BANDS.values()) == len(ToolEffect)


def test_the_bands_run_in_the_same_direction_as_the_ranks():
    order = [EFFECT_BAND_ROUTINE, EFFECT_BAND_NOTABLE, EFFECT_BAND_SERIOUS]
    seen = [
        order.index(effect_band(_EFFECT_SEVERITY[effect]))
        for effect in sorted(ToolEffect, key=lambda e: _EFFECT_SEVERITY[e])
    ]
    assert seen == sorted(seen), (
        f"the bands are not monotonic in the ranking: {seen}"
    )


# ── Unknown values fail high ────────────────────────────────────────────────


@pytest.mark.parametrize(
    "unknown",
    ["", "nonsense", "read_publik", "DESTRUCTIVE", None, 7, object()],
)
def test_an_unrecognised_effect_ranks_highest_and_bands_serious(unknown):
    """The module's stated fail-high rule, which a mutation inverted unnoticed.

    Ranking an unknown value LOWEST is the failure mode worth naming: a value
    added to the enum but not to the table renders as the most harmless thing
    on a card, on the one surface whose entire job is to tell someone what they
    are about to allow. Nothing else in this module fails open, and neither
    does this.
    """
    rank = effect_severity(unknown)
    assert rank > max(_EFFECT_SEVERITY.values()), (
        f"{unknown!r} ranked {rank}, at or below a classified effect"
    )
    assert effect_band(rank) == EFFECT_BAND_SERIOUS


def test_an_unknown_value_leads_a_mixed_set():
    described = describe_effects(("read_workspace", "not_a_real_effect"))
    assert described["effect"] == "not_a_real_effect"
    assert described["effect_band"] == EFFECT_BAND_SERIOUS
    # It has no words, so it is shown as the identifier it is rather than being
    # given English nobody wrote for it.
    assert described["effect_label"] == "not_a_real_effect"


# ── The words are words ─────────────────────────────────────────────────────


def test_every_phrase_is_prose_and_not_the_identifier():
    for effect, phrase in _EFFECT_PHRASE.items():
        assert phrase != effect.value, f"{effect.value} is a name for the code"
        assert "_" not in phrase, f"{phrase!r} still reads like an identifier"
        assert " " in phrase, f"{phrase!r} is one word, so it is a label not a phrase"
        assert phrase[0].isupper(), f"{phrase!r} does not start a sentence"
        assert phrase == phrase.strip()
        # The plan window gives this one line beside four other chips.
        assert len(phrase) <= 40, f"{phrase!r} is too long for a plan-step row"


def test_no_two_effects_are_described_with_the_same_words():
    phrases = list(_EFFECT_PHRASE.values())
    assert len(set(phrases)) == len(phrases), (
        "two effects share a phrase, so the card cannot say which one it means"
    )


def test_the_destructive_phrase_says_something_about_deleting():
    """`Law 15`, in one assertion.

    The phrase is the whole warning: it is what survives greyscale, colour
    blindness, a narrow phone and a screen reader, and refutation reworded this
    one to "Reads public information" without a single test noticing. A person
    reading that would have approved a deletion believing it was a read.
    """
    phrase = _EFFECT_PHRASE[ToolEffect.DESTRUCTIVE].lower()
    assert "delete" in phrase or "overwrite" in phrase, (
        f"{phrase!r} does not warn about what DESTRUCTIVE actually does"
    )
    assert "read" not in phrase


@pytest.mark.parametrize(
    ("effect", "must_mention"),
    [
        (ToolEffect.EXECUTE_CODE, ("run", "execut")),
        (ToolEffect.READ_PRIVATE, ("private", "personal")),
        (ToolEffect.WRITE_PRIVATE, ("private", "personal")),
        (ToolEffect.NETWORK_EGRESS, ("internet", "out", "send")),
        (ToolEffect.ADMIN_CHANGE, ("setting", "everyone", "admin")),
        (ToolEffect.USER_INTERACTION, ("ask", "question")),
    ],
)
def test_the_phrase_describes_the_effect_it_is_attached_to(effect, must_mention):
    # Not a spell-check: these are the pairings where a swap between two
    # neighbouring phrases would be a lie rather than a wording preference.
    phrase = _EFFECT_PHRASE[effect].lower()
    assert any(word in phrase for word in must_mention), (
        f"{_EFFECT_PHRASE[effect]!r} does not describe {effect.value}"
    )


# ── The resolver ────────────────────────────────────────────────────────────


def test_describe_effects_ranks_most_severe_first():
    described = describe_effects(
        ToolCapabilities(frozenset({ToolEffect.READ_PRIVATE, ToolEffect.DESTRUCTIVE}))
    )
    assert described["effects"] == ["destructive", "read_private"]
    assert described["effect"] == "destructive"
    assert described["effect_label"] == _EFFECT_PHRASE[ToolEffect.DESTRUCTIVE]
    assert described["effect_labels"] == [
        _EFFECT_PHRASE[ToolEffect.DESTRUCTIVE],
        _EFFECT_PHRASE[ToolEffect.READ_PRIVATE],
    ]
    assert described["effect_severity"] == _EFFECT_SEVERITY[ToolEffect.DESTRUCTIVE]
    assert described["effect_band"] == EFFECT_BAND_SERIOUS
    assert set(described) == WIRE_KEYS


def test_describe_effects_takes_a_bare_tuple_of_values_too():
    # `PendingToolApproval` keeps its effects as a tuple of strings for digest
    # stability; if this branch broke, every approval card would go blank while
    # the live tool events stayed ranked, and the two would disagree in exactly
    # the place the disagreement matters most.
    from_capabilities = describe_effects(
        ToolCapabilities(frozenset({ToolEffect.DESTRUCTIVE, ToolEffect.ADMIN_CHANGE}))
    )
    from_values = describe_effects(("admin_change", "destructive"))
    assert from_values == from_capabilities
    assert from_values["effect"] == "destructive"
    assert from_values["effect_labels"][0] == _EFFECT_PHRASE[ToolEffect.DESTRUCTIVE]


def test_describe_effects_ignores_the_order_it_is_handed():
    ordered = describe_effects(("admin_change", "destructive", "read_workspace"))
    reversed_ = describe_effects(("read_workspace", "destructive", "admin_change"))
    assert ordered == reversed_
    assert ordered["effects"] == ["destructive", "admin_change", "read_workspace"]


@pytest.mark.parametrize("empty", [(), [], set(), frozenset(), None, {}, ""])
def test_describe_effects_returns_an_empty_dict_for_nothing(empty):
    # An empty dict and not a dict of empty strings: callers spread this into an
    # SSE event, so "nothing known" has to mean the keys are absent. A surface
    # reading `effect` then gets `undefined`, which it already handles, instead
    # of a falsy string it would have to special-case in five places.
    assert describe_effects(empty) == {}
    assert describe_effects(ToolCapabilities(frozenset())) == {}


def test_a_single_effect_still_produces_a_list_shaped_payload():
    described = describe_effects((ToolEffect.UI_SIDE_EFFECT,))
    assert described["effects"] == ["ui_side_effect"]
    assert described["effect_labels"] == ["Changes what is on screen"]
    assert described["effect_band"] == EFFECT_BAND_ROUTINE


def test_an_unclassified_tool_describes_as_serious():
    # The end-to-end reading of the fail-high rule: an unknown MCP tool is the
    # only way an unclassified name reaches a card, and it must not arrive
    # looking harmless.
    described = describe_effects(capabilities_for_tool("mcp__whoever__do_something"))
    assert described["effect_band"] == EFFECT_BAND_SERIOUS
    assert described["effects"], "an unknown tool must not resolve to no effects"


# ── `Law 14`: one home for the ordering and the words ───────────────────────


def _executable_js(path: Path) -> str:
    """The file with its comments removed.

    Crude on purpose. It strips `/* */` blocks and everything after `//` on a
    line, which also eats the tail of any line containing a URL — that makes
    this check more permissive, never less, and the alternative is a JavaScript
    parser in a test about where a lookup table lives.
    """
    text = path.read_text(encoding="utf-8")
    text = re.sub(r"/\*.*?\*/", " ", text, flags=re.S)
    return "\n".join(line.split("//")[0] for line in text.splitlines())


def test_no_javascript_carries_a_second_copy_of_the_phrases():
    offenders = {}
    for path in sorted((ROOT / "static" / "js").rglob("*.js")):
        source = _executable_js(path)
        found = [p for p in _EFFECT_PHRASE.values() if p in source]
        if found:
            offenders[path.name] = found
    assert not offenders, (
        "the phrasing lives in src/tool_capabilities.py only; a copy in the "
        f"browser drifts the first time the enum grows: {offenders}"
    )


def test_no_javascript_decides_a_band_for_itself():
    # The stylesheet may name a band — `[data-effect-band="serious"]` is
    # drawing what it was handed. JavaScript naming one is deciding.
    bands = (EFFECT_BAND_ROUTINE, EFFECT_BAND_NOTABLE, EFFECT_BAND_SERIOUS)
    offenders = {}
    for path in sorted((ROOT / "static" / "js").rglob("*.js")):
        source = _executable_js(path)
        found = [b for b in bands if f"'{b}'" in source or f'"{b}"' in source]
        if found:
            offenders[path.name] = found
    assert not offenders, (
        "a surface comparing against a band name has re-implemented the "
        f"threshold that lives in src/tool_capabilities.py: {offenders}"
    )
