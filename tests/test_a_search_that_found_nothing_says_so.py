# SPDX-License-Identifier: AGPL-3.0-or-later
"""A search that found nothing useful says so, in the block the model reads.

The owner's turn (`/work/notes/owner-shots/2026-10-09-osrs-chat-export.md`) did
not only search wrong. It then *answered* — the model wrote generic raid advice
("Prioritize gear with higher magic/prayer attenuation", lines 239-248) out of
five results about an M. Night Shyamalan film, a dictionary entry and a
clothing shop, after noting in its own reasoning that it had "zero record of
searching for IMDb or Old Navy".

Measured on `99134cf`, the block handed to the model said:

    Query: Old School RuneScape Fractured Archive raid details October 20th
    Searched 5 results, fetched 3 pages

Two counts and the query. Nothing about the match, and no provider name — so
neither the model nor, afterwards, a person reading the export could tell
whether the search had worked.

`rank_search_results` already measured it and threw the number away: it scored
each result, sorted on the score and returned bare dicts (keys `title`, `url`,
`snippet` — no score anywhere). Measured over the owner's five, every one
matched **1 of 9** query terms in its title, scoring 1.20-1.81; a result that
actually answers the question scores 2.84 at 7 of 9. The signal existed and
was discarded one line before the output was built.

These drive the measured verdict (`relevance_report`), an enum rather than a
boolean because "relevant: false" can be read two ways (`Law 10`), and the
three lines the block gains: the provider that answered, the query as sent, and
how well the results matched — with a plain sentence when they do not.
"""

import pytest

from services.search import core, providers
from services.search.ranking import (
    RELEVANCE_VERDICTS,
    rank_search_results,
    relevance_report,
)

from tests.test_a_search_sends_the_persons_words import (
    GOOD_RESULTS,
    OWNER_QUERY,
    OWNER_RESULTS,
    _Recorder,
    offline,  # noqa: F401  (pytest fixture, used by the cases below)
)


# ----------------------------------------------------------------------
# The verdict
# ----------------------------------------------------------------------
def test_the_owners_five_results_are_measured_as_a_bad_match():
    report = relevance_report(OWNER_QUERY, OWNER_RESULTS)

    assert report["verdict"] in ("weak", "none"), report
    # Measured: one of the nine words in the query appears in the best result.
    assert report["best_coverage"] < 0.25, report
    assert report["matched"] == 1, report


def test_results_that_answer_the_question_are_measured_as_a_good_match():
    report = relevance_report(OWNER_QUERY, GOOD_RESULTS)

    assert report["verdict"] == "strong", report
    assert report["best_coverage"] > 0.8, report


def test_the_verdict_is_one_of_a_named_set():
    for results in (OWNER_RESULTS, GOOD_RESULTS, []):
        assert relevance_report(OWNER_QUERY, results)["verdict"] in RELEVANCE_VERDICTS


def test_no_results_at_all_is_its_own_verdict():
    report = relevance_report(OWNER_QUERY, [])
    assert report["verdict"] == "none"
    assert report["best_coverage"] == 0.0


def test_the_report_names_the_query_words_no_result_mentioned():
    report = relevance_report(OWNER_QUERY, OWNER_RESULTS)

    missing = {t.lower() for t in report["missing"]}
    # These are the words that make the query the owner's question, and not one
    # of the five results contains any of them.
    for term in ("school", "runescape", "fractured", "archive", "raid"):
        assert term in missing, f"{term!r} is in no result but was not reported missing"
    # "old" IS in every result, so it is not missing.
    assert "old" not in missing


def test_a_good_result_set_leaves_nothing_important_missing():
    assert relevance_report(OWNER_QUERY, GOOD_RESULTS)["missing"] == []


def test_question_and_filler_words_are_not_counted_as_subject_terms():
    """A short question is mostly stop words; counting them would make every
    search look like a bad match."""
    report = relevance_report(
        "who is the CEO of Jagex",
        [{"title": "Jagex - Wikipedia", "url": "https://en.wikipedia.org/wiki/Jagex",
          "snippet": "Jagex Limited is a British video game developer. Its CEO is named here."}],
    )
    assert report["verdict"] == "strong", report
    assert report["terms"] == 2, report["terms"]  # ceo, jagex


def test_a_query_of_nothing_but_stop_words_does_not_divide_by_zero():
    report = relevance_report("what is it", [{"title": "What is it", "url": "u", "snippet": ""}])
    assert report["verdict"] in RELEVANCE_VERDICTS
    assert report["terms"] > 0


def test_a_non_string_query_or_rows_do_not_raise():
    assert relevance_report(None, OWNER_RESULTS)["verdict"] in RELEVANCE_VERDICTS
    assert relevance_report(OWNER_QUERY, None)["verdict"] == "none"
    assert relevance_report(OWNER_QUERY, [None, "x", {}])["verdict"] in RELEVANCE_VERDICTS


def test_ranking_still_returns_plain_rows_in_score_order():
    """The report is added beside the ranker, not instead of it: callers and
    four existing test files read `rank_search_results`' list of dicts."""
    ranked = rank_search_results(OWNER_QUERY, [dict(r) for r in OWNER_RESULTS])
    assert isinstance(ranked, list) and len(ranked) == len(OWNER_RESULTS)
    assert all(isinstance(r, dict) for r in ranked)
    assert ranked[0]["title"] == "Old (film) - Wikipedia"


# ----------------------------------------------------------------------
# The block the model reads
# ----------------------------------------------------------------------
def test_the_result_block_says_the_results_do_not_match(offline):  # noqa: F811
    rec = _Recorder(results=OWNER_RESULTS)
    rec.install(offline)

    out = core.comprehensive_web_search(OWNER_QUERY, max_pages=5)

    assert "Relevance: weak" in out or "Relevance: none" in out, out[:800]
    assert "do not match" in out, "the block does not say the results miss the query"
    # The measurement, not an adjective.
    assert "1 of 9" in out, out[:800]
    # And the words that are missing, so the model can say what it could not find.
    assert "runescape" in out.lower()


def test_the_result_block_stays_quiet_when_the_results_are_good(offline):  # noqa: F811
    rec = _Recorder(results=GOOD_RESULTS)
    rec.install(offline)

    out = core.comprehensive_web_search(OWNER_QUERY, max_pages=5)

    assert "Relevance: strong" in out
    assert "do not match" not in out


def test_the_result_block_names_the_provider_that_answered(offline):  # noqa: F811
    offline.setattr(core, "_get_search_settings", lambda: {"search_provider": "duckduckgo"})
    rec = _Recorder(results=GOOD_RESULTS)
    rec.install(offline, only="duckduckgo")

    out = core.comprehensive_web_search(OWNER_QUERY, max_pages=3)

    assert "Provider: duckduckgo" in out, out[:800]


def test_the_result_block_says_the_query_as_sent(offline):  # noqa: F811
    rec = _Recorder(results=GOOD_RESULTS)
    rec.install(offline)

    out = core.comprehensive_web_search(OWNER_QUERY, max_pages=3)

    assert f"Query: {OWNER_QUERY}" in out
    assert f"Query as sent: {OWNER_QUERY}" in out, (
        "the block must state the string that went to the engine, so a bad search "
        "is diagnosable from the transcript alone"
    )


def test_the_instructions_tell_the_model_what_to_do_with_a_bad_match(offline):  # noqa: F811
    rec = _Recorder(results=OWNER_RESULTS)
    rec.install(offline)

    out = core.comprehensive_web_search(OWNER_QUERY, max_pages=5)

    tail = out[out.index("IMPORTANT INSTRUCTIONS"):]
    assert "do not answer from general knowledge" in tail.lower(), tail


def test_a_search_with_no_results_at_all_still_reports_honestly(offline):  # noqa: F811
    rec = _Recorder(results=[])
    rec.install(offline)

    out = core.comprehensive_web_search(OWNER_QUERY, max_pages=3)

    # The existing "no results" path is unchanged; it must not gain a relevance
    # line it cannot measure.
    assert "No search results found" in out
    assert "Relevance:" not in out


def test_return_sources_shape_is_unchanged(offline):  # noqa: F811
    rec = _Recorder(results=GOOD_RESULTS)
    rec.install(offline)

    out, sources = core.comprehensive_web_search(
        OWNER_QUERY, max_pages=3, return_sources=True
    )

    assert isinstance(out, str) and isinstance(sources, list)
    assert sources and set(sources[0]) == {"url", "title"}


# ----------------------------------------------------------------------
# The cache keeps the person's words, not the enhanced string
# ----------------------------------------------------------------------
def test_the_cache_duration_reads_the_persons_query(offline):  # noqa: F811
    from services.search.query import _cache_duration_for_query

    # `_cache_duration_for_query` lives in services/search/query.py:146 (not
    # cache.py, which is 64 lines long) and is called by
    # `searxng_search_results` with the person's own query.
    assert _cache_duration_for_query("latest OSRS news").total_seconds() == 30 * 60
    assert _cache_duration_for_query(OWNER_QUERY).total_seconds() == 24 * 3600
