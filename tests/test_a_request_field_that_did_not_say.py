# SPDX-License-Identifier: AGPL-3.0-or-later
"""`B190`. The HTTP boundary's three-valued rule, and the one answer it must
refuse to invent.

`B97` unified sixteen hand-written truthiness sites onto `request_flag` and
`request_truthy`, and the unification was right. What it carried in was a
single line — `if not isinstance(raw, str): return bool(raw)` — that turns
*any* object into a definite yes or no. Two callers were already relying on the
third answer, and both broke in ways no test in the converted files could see,
because each needed a value the converted files never pass:

  * `routes.model_routes._parse_supports_tools({})` returned `None` for eight
    months and began returning `False`. `None` is the tri-state's *work it out*;
    `False` is *this endpoint has no native tool calling*. The docstring at
    `P3-22` names the consequence in its own words — "guessing `False` and
    quietly taking tools away from an endpoint that had them".
  * `read_email_by_uid` called directly, rather than through FastAPI, sees
    `full=Query(False)` — a `Query` object, which is truthy. The old two-line
    re-parse asked `is True` first and got `False`; `bool(Query(False))` is
    `True`, so a truncated fetch became `(BODY.PEEK[])`, the whole message body,
    every time.

The rule this file pins: a request field answers `True` or `False` only from a
`bool`, from the integers 1 and 0, or from a word in the vocabulary. Anything
else did not say, which is the same answer an unrecognised word already got.
"""

import pytest

from src.env_flags import request_flag, request_truthy


class _Truthy:
    """An object with no opinion about booleans, which is most objects."""

    def __repr__(self) -> str:  # pragma: no cover - diagnostics only
        return "<object that never answered>"


@pytest.mark.parametrize(
    "raw",
    [{}, [], set(), _Truthy(), object(), {"a": 1}, [0], "banana", "1.5", "-"],
)
def test_a_value_outside_the_vocabulary_did_not_say(raw):
    assert request_truthy(raw) is None


@pytest.mark.parametrize(
    "raw,expected",
    [
        (True, True),
        (False, False),
        (1, True),
        (0, False),
        ("true", True),
        ("false", False),
        (" TRUE ", True),
        (None, None),
    ],
)
def test_the_answers_it_does_give(raw, expected):
    assert request_truthy(raw) is expected


def test_an_integer_outside_one_and_zero_did_not_say():
    """`2` is not a spelling of yes. It is a number that reached a boolean
    field, and the honest answer is that the field did not say."""
    assert request_truthy(2) is None
    assert request_truthy(-1) is None


def test_request_flag_still_judges_a_number_by_its_truthiness():
    """`Law 1`, and the line `request_flag`'s own docstring promises: a number
    that is not 0 or 1 keeps the answer it had before `B97` ever ran. Only the
    tri-state reader stops guessing."""
    assert request_flag(2) is True
    assert request_flag(-1) is True
    assert request_flag(0.0) is False
    assert request_flag(0) is False
    assert request_flag(1) is True


def test_request_flag_falls_back_to_its_default_for_an_object():
    """An object's truthiness is not the operator's intent. `default` is."""
    assert request_flag(_Truthy()) is False
    assert request_flag(_Truthy(), default=True) is True
    assert request_flag({}, default=True) is True
    assert request_flag("banana", default=True) is True


def test_the_tri_state_caller_that_this_protects():
    """`routes.model_routes._parse_supports_tools`, driven directly. Every one
    of these returned `None` before `B97` and must again."""
    from routes.model_routes import _parse_supports_tools

    for junk in ({}, [], "banana", object(), 2):
        assert _parse_supports_tools(junk) is None, junk

    assert _parse_supports_tools(True) is True
    assert _parse_supports_tools(False) is False
    assert _parse_supports_tools(1) is True
    assert _parse_supports_tools(0) is False
    assert _parse_supports_tools("yes") is True
    assert _parse_supports_tools("no") is False
    assert _parse_supports_tools(None) is None


def test_a_fastapi_query_default_is_not_a_yes():
    """The email half. A `Query` object is truthy and means nothing; reading it
    as a yes is what made a truncated body fetch a whole one."""
    from fastapi import Query

    assert request_truthy(Query(False)) is None
    assert request_flag(Query(False)) is False
    assert request_flag(Query(True)) is False
