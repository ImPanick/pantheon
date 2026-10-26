# SPDX-License-Identifier: AGPL-3.0-or-later
"""`B595` — "two broad terms" means two, counted as words.

`should_check_retrieval_precision` decides whether the nightly audit spends a
90-second `llm_call_async` on a skill's retrieval metadata. Its free-text branch
counted `sum(1 for t in BROAD_TAGS if t in text) >= 2` over a **substring**
match, and the list holds nested pairs — `install`/`installation`,
`network`/`networking`, `document`/`documents` — and `arch`, which is inside
`search`, itself a broad term. So one word tripped a two-word threshold.

Driven through the real prefilter, and through the lint that reuses it
(`broad-retrieval`), so the author-facing advice moved with it.
"""
import pytest

from services.memory.skill_lint import (
    broad_terms_in,
    lint_skill,
    should_check_retrieval_precision,
)


@pytest.mark.parametrize("description", [
    "Installation of the widget",
    "Networking basics",
    "Documents overview",
    "Search the knowledge base",          # `search` held `arch`
    "Arch Linux setup for a new laptop",  # one system, not two words
])
def test_one_broad_term_does_not_trip_the_prefilter(description):
    assert not should_check_retrieval_precision({"name": "x", "description": description})


@pytest.mark.parametrize("description", [
    "Install the network driver",
    "Search my email for the invoice",
    "Arch Linux on the server",
])
def test_two_distinct_broad_terms_do(description):
    assert should_check_retrieval_precision({"name": "x", "description": description})


def test_the_forms_of_one_term_are_counted_once():
    assert broad_terms_in("install the installation") == {"install"}
    assert broad_terms_in("documents and a document") == {"document"}
    assert broad_terms_in("march to the archive") == set()


def test_a_broad_tag_still_trips_it_on_its_own():
    """The tag branch was already a whole-token set intersection; unchanged."""
    assert should_check_retrieval_precision({"name": "x", "tags": ["network"]})


def test_the_lint_stops_calling_one_word_broad():
    skill = {"name": "widget-install", "description": "Installation of the widget",
             "when_to_use": "a new widget arrived", "procedure": ["unpack it"],
             "tags": ["widget"]}
    codes = {f["code"] for f in lint_skill(skill, [])["findings"]}
    assert "broad-retrieval" not in codes
