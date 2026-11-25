# SPDX-License-Identifier: AGPL-3.0-or-later
"""`B2192`. `from_json` refused text "nested deeper than Python reads", which
was the recursion limit. Python 3.14 bounds the JSON decoder by the C stack
instead, so CI's first run on 3.14 parsed 100,000 nested brackets that 3.11
refused. The bound is now the module's own, whatever the interpreter allows."""
import sys

import pytest

from src import workflow_refs as wr


@pytest.fixture
def a_generous_interpreter():
    """An interpreter that would read far deeper than the bound."""
    before = sys.getrecursionlimit()
    sys.setrecursionlimit(200_000)
    try:
        yield
    finally:
        sys.setrecursionlimit(before)


def test_text_deeper_than_the_bound_is_missing_however_deep_python_reads(a_generous_interpreter):
    deep = "[" * (wr.FROM_JSON_MAX_DEPTH + 1) + "]" * (wr.FROM_JSON_MAX_DEPTH + 1)
    assert wr.read_json(deep) is wr.MISSING


def test_text_at_the_bound_is_read(a_generous_interpreter):
    depth = wr.FROM_JSON_MAX_DEPTH
    got = wr.read_json("[" * depth + "]" * depth)
    for _ in range(depth - 1):
        got = got[0]
    assert got == []


def test_brackets_inside_strings_do_not_count():
    text = '{"a": "' + "[" * (wr.FROM_JSON_MAX_DEPTH * 2) + '", "b": [1, "\\"]"]}'
    assert wr.read_json(text) == {"a": "[" * (wr.FROM_JSON_MAX_DEPTH * 2), "b": [1, '"]']}
