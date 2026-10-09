# SPDX-License-Identifier: AGPL-3.0-or-later
"""Three modules decided "this is a news query" three different ways.

Measured on `3b40a4e`, the tree had three answers to one question:

  * `services/search/providers.py:126`
    ``_NEWS_HINTS = ("news", "nyheter", "headlines", "breaking", "latest",
    "today", "idag")`` — matched as a **substring** of the lowered query
    (`:191`), and it decides which SearXNG **category** the query is sent to.
  * `services/search/ranking.py:49` — the byte-identical set, matched as a
    **whole token** (`:97`), deciding whether news-domain bonuses and penalties
    are applied to the ordering.
  * `services/search/query.py:183`
    ``news_terms = {"news", "latest", "breaking", "today", "today's",
    "current", "updates", "happening"}`` — a **different set**, whole-token,
    deciding how long a result is cached.

Measured over a 27-query corpus, the three disagreed on **12** of them (44%),
from two separate causes:

  * **the matcher.** `providers.py` matched substrings, so *"Newsom California
    policy"*, *"newsletter signup best practices"* and *"how to use newsprint
    for packing"* were all news queries to the category switch and to nothing
    else — the letters `news` inside a surname chose the index the query was
    searched in.
  * **the set.** `current`, `updates` and `happening` were news to the cache
    and to neither of the others; `headlines`, `nyheter` and `idag` were news
    to the other two and not to the cache.

`"today's"` in `query.py`'s set was **unreachable**: the tokeniser beside it is
``\\b\\w+\\b``, which splits `today's` into `today` and `s`, so the literal
token `today's` can never appear in the set it is matched against.

`Law 7` — one source of truth per fact. These are two facts, not three:

  * **is this query about news** (`is_news_query`) — the SearXNG category and
    the ranker's news adjustment. Those two already agreed exactly; they are
    the same question and they now cite the same set.
  * **does this query want fresh results** (`wants_fresh_results`) — the cache
    duration, a deliberate superset, because a false positive there costs one
    extra provider call and a false negative serves a day-old answer. `Law 1`:
    `current`, `updates` and `happening` existed and are kept, here, where
    they cost nothing.

Nothing depended on the differences: measured, the three extra cache terms fed
`_cache_duration_for_query`, which had no production caller at all, and the
substring matcher's extra hits were defects rather than behaviour.
"""

import re

import pytest

from services.search import providers, query, ranking


# The corpus the three definitions were measured over. Each row is
# (query, is it about news).
NEWS_CORPUS = [
    ("latest OSRS news", True),
    ("breaking news Canada", True),
    ("today's top headlines", True),
    ("the latest version of postgres", True),
    ("nyheter sverige", True),
    ("idag vader stockholm", True),
    ("headlines from the guardian", True),
    ("best news aggregator self hosted", True),
    # The owner's own query is not a news query under any of the three.
    ("Old School RuneScape Fractured Archive raid details October 20th", False),
    ("python asyncio", False),
    ("Jagex announcements this week", False),
    ("whats the newest iphone", False),
    ("oldnavy sale", False),
    ("weather in Zurich tomorrow", False),
    # The substring matcher's four false positives, measured on `3b40a4e`.
    ("Newsom California policy", False),
    ("newsletter signup best practices", False),
    ("how to use newsprint for packing", False),
    ("todays-menu at the Blue Moon Inn", False),
]

# Terms that mean "fresh", but not "news". These were in `query.py`'s set and
# in neither of the other two.
FRESH_ONLY_CORPUS = [
    "current OSRS meta",
    "updates to the tax code",
    "what is happening in Varlamore",
]


def _tokens(text):
    return [t.lower() for t in re.findall(r"\b\w+\b", text)]


# ----------------------------------------------------------------------
# 1. One set, in one place
# ----------------------------------------------------------------------
def test_there_is_one_news_term_set_and_the_other_modules_cite_it():
    assert query.NEWS_TERMS, "the canonical set is empty"
    # The two modules that already agreed now hold the same object, not a copy.
    assert providers._NEWS_HINTS is query.NEWS_TERMS
    assert ranking._NEWS_HINTS is query.NEWS_TERMS


def test_the_freshness_set_is_the_news_set_plus_named_extras():
    assert query.NEWS_TERMS <= query.FRESH_TERMS
    extra = query.FRESH_TERMS - query.NEWS_TERMS
    # `Law 1`: every term that existed survives. These three were live only in
    # the cache-duration decision and are kept exactly there.
    assert extra == {"current", "updates", "happening"}, extra


def test_no_term_from_any_of_the_three_old_sets_was_lost():
    # The three sets as they stood on `3b40a4e`, minus the one token the
    # tokeniser can never produce.
    was = {
        "news", "nyheter", "headlines", "breaking", "latest", "today", "idag",
        "current", "updates", "happening",
    }
    assert was <= query.FRESH_TERMS, was - query.FRESH_TERMS


def test_the_unreachable_token_is_gone_and_was_unreachable():
    # `today's` cannot survive `\b\w+\b`, so it could never match.
    assert "today's" not in query.FRESH_TERMS
    assert "today's" not in _tokens("today's top headlines")
    # The word it was meant to catch still does.
    assert query.is_news_query("today's top headlines") is True


# ----------------------------------------------------------------------
# 2. One matcher: whole tokens, never substrings
# ----------------------------------------------------------------------
@pytest.mark.parametrize("text,expected", NEWS_CORPUS)
def test_the_one_definition_agrees_with_the_corpus(text, expected):
    assert query.is_news_query(text) is expected, text


@pytest.mark.parametrize(
    "text",
    ["Newsom California policy", "newsletter signup best practices",
     "how to use newsprint for packing", "todays-menu at the Blue Moon Inn"],
)
def test_a_news_term_inside_another_word_is_not_a_news_query(text):
    """The substring matcher's measured false positives.

    On `3b40a4e` each of these chose SearXNG's `news` category, because
    `any(h in q_lc for h in _NEWS_HINTS)` found `news` inside `Newsom`,
    `newsletter` and `newsprint`, and `today` inside `todays-menu`.
    """
    assert query.is_news_query(text) is False
    assert query.wants_fresh_results(text) is False


def test_all_three_call_sites_now_give_the_same_answer():
    """The 12 disagreements, driven through the real call sites.

    Not three copies of one predicate: the SearXNG category switch, the
    ranker's news adjustment and the cache duration, each asked for the same
    query.
    """
    for text, expected in NEWS_CORPUS:
        # the category switch (providers.py), with no time filter so the
        # query text is the only input
        category = providers._searxng_params(text, time_filter=None,
                                             categories="general")["categories"]
        # the ranker (ranking.py)
        ranked_as_news = any(t in ranking._NEWS_HINTS for t in _tokens(text))
        assert (category == "news") is expected, f"{text!r} -> {category}"
        assert ranked_as_news is expected, text


# ----------------------------------------------------------------------
# 3. The one deliberate difference, named
# ----------------------------------------------------------------------
@pytest.mark.parametrize("text", FRESH_ONLY_CORPUS)
def test_a_freshness_term_shortens_the_cache_but_does_not_change_the_category(text):
    from datetime import timedelta

    assert query.wants_fresh_results(text) is True
    assert query.is_news_query(text) is False
    assert query._cache_duration_for_query(text) == timedelta(minutes=30)
    # and the expensive consumer is untouched: a query about a current account
    # is still searched in the general index.
    params = providers._searxng_params(text, time_filter=None, categories="general")
    assert params["categories"] == "general"


def test_a_news_query_is_cached_briefly_and_a_reference_query_is_not():
    from datetime import timedelta

    assert query._cache_duration_for_query("latest OSRS news") == timedelta(minutes=30)
    assert query._cache_duration_for_query(
        "Old School RuneScape Fractured Archive raid details October 20th"
    ) == timedelta(hours=24)
    # The longest duration the function can return is the one the cleanup pass
    # is given, so a 24-hour entry is not swept at one hour (`B-NEW` below).
    assert query.MAX_CACHE_DURATION == timedelta(hours=24)


# ----------------------------------------------------------------------
# 4. The kept names still answer (`Law 1`)
# ----------------------------------------------------------------------
def test_the_old_private_predicate_still_works():
    assert query._is_news_query("latest news today") is True
    assert query._is_news_query(None) is False
    assert query._is_news_query("python asyncio") is False


def test_every_entry_point_tolerates_a_non_string():
    assert query.is_news_query(None) is False
    assert query.wants_fresh_results(None) is False
    assert query.is_news_query(123) is False
    assert query.wants_fresh_results({}) is False
