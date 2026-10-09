# SPDX-License-Identifier: AGPL-3.0-or-later
"""The rest of the result path the owner hit, measured end to end.

The owner's export says *"Searched 5 results, fetched 3 pages"*. Reproduced
here with a fake provider and a fetcher that refuses IMDb and YouTube the way
the real ones do: the two that failed were **[2] IMDb** and **[5] YouTube**,
which is what the `fx6-search` lane had to infer and now reads off the block.

Two defects were measured on `3b40a4e` in the same path, and both are in the
lines between "the provider answered" and "the model reads the block".

**1. A filter shrank the fetch set instead of selecting within it.**

    filtered_urls = [r["url"] for r in search_results[:max_pages]
                     if url_passes_filters(r["url"])]

The slice runs **before** the filter, so a result excluded by
`domain_blacklist` / `domain_whitelist` / `content_type` / `language` costs a
page rather than yielding to the next result that passes. Measured: five
results, `max_pages=3`, one domain blacklisted -> **two** pages fetched, with
two passing results sitting unread at [4] and [5]. The caller asked for three
pages and the filter it supplied silently reduced that to two.

**2. The relevance verdict ignored the strongest evidence it had.**

`relevance_report` (`ranking.py:230`, added by the `fx6-search` lane) reads
titles and snippets only. SearXNG's parse is ``"snippet": r.get("content", "")``
and plenty of its engines return no content at all — so measured, three
genuinely on-topic pages (the OSRS wiki, the Jagex news post, the game's own
site) with empty snippets scored **2 of 9**, verdict `weak`, and the block told
the model *"These results do not match the query... Tell the person the search
did not find it rather than answering from general knowledge"* while handing it
three pages that said exactly what was asked. A false `weak` is the same defect
as the owner's turn wearing the opposite coat: the fx6 lane built the verdict
to stop the model answering around a bad search, and on snippet-free results it
would have stopped it answering a good one.

The fetched content is built forty lines above the report and was unused. It is
the best evidence available and it is now what the verdict is measured on, with
the snippets as the fallback for a result that was not fetched.

Nothing here touches the network.
"""

import pytest

from services.search import core
from services.search.ranking import relevance_report

from tests.test_a_search_sends_the_persons_words import (
    OWNER_QUERY,
    OWNER_RESULTS,
)


# Three results that answer the owner's question and whose engine returned no
# snippet — the shape `searxng_search_api` produces when an engine has no
# `content` field.
SNIPPETLESS_GOOD = [
    {"title": "Fractured Archive",
     "url": "https://oldschool.runescape.wiki/w/Fractured_Archive", "snippet": ""},
    {"title": "Update: a new raid",
     "url": "https://secure.runescape.com/m=news/a-new-raid", "snippet": ""},
    {"title": "Old School RuneScape",
     "url": "https://oldschool.runescape.com/", "snippet": ""},
]

ON_TOPIC_BODY = (
    "The Fractured Archive raid releases on October 20th in Old School "
    "RuneScape. Full details of the raid mechanics, the Archive's three wings "
    "and the school of thought puzzles are below. "
) * 10


@pytest.fixture
def path(monkeypatch, tmp_path):
    """The live orchestrator with a fake provider and a recording fetcher.

    `fetched` records every URL the fetcher was asked for; `bodies` maps a
    URL substring to what it should return, and `refuse` to an error string.
    """
    state = {"results": [dict(r) for r in OWNER_RESULTS],
             "bodies": {}, "refuse": {}, "fetched": []}

    monkeypatch.setattr(core, "SEARCH_CACHE_DIR", tmp_path, raising=False)
    monkeypatch.setattr(core, "_get_search_settings",
                        lambda: {"search_provider": "searxng"}, raising=False)
    monkeypatch.setattr(core, "_get_result_count", lambda: 5, raising=False)
    monkeypatch.setattr(core, "_record_query", lambda *a, **k: None, raising=False)
    monkeypatch.setattr(core, "_call_provider",
                        lambda p, q, c, t=None: [dict(r) for r in state["results"]],
                        raising=False)

    def _fetch(url, *a, **kw):
        state["fetched"].append(url)
        for frag, reason in state["refuse"].items():
            if frag in url:
                return {"url": url, "title": "", "content": "",
                        "success": False, "error": reason}
        body = "generic page text " * 60
        for frag, text in state["bodies"].items():
            if frag in url:
                body = text
        return {"url": url, "title": "T", "content": body,
                "success": True, "error": ""}

    monkeypatch.setattr(core, "fetch_webpage_content", _fetch, raising=False)
    core.search_cache_index.clear()
    yield state
    core.search_cache_index.clear()


def _header(block):
    """The lines between the first rule and the summary — what the model reads
    first, and what the owner's export preserved."""
    return block.split("SEARCH RESULTS SUMMARY")[0]


# ----------------------------------------------------------------------
# 1. The owner's "fetched 3 pages", reproduced and named
# ----------------------------------------------------------------------
def test_the_two_pages_that_failed_are_named_with_their_reason(path):
    path["refuse"] = {"imdb.com": "HTTP 403: Client error '403 Forbidden'",
                      "youtube.com": "HTTP 403: Client error '403 Forbidden'"}

    out = core.comprehensive_web_search(OWNER_QUERY, max_pages=5)
    head = _header(out)

    assert "Searched 5 results, fetched 3 pages" in head
    assert "Not fetched [2] https://www.imdb.com/title/tt10954652/" in head
    assert "Not fetched [3] https://www.youtube.com/watch?v=84xAD4r-9kE" in head
    assert "403" in head


def test_a_page_that_fetched_but_held_no_text_is_named_too(path):
    path["bodies"] = {"merriam-webster": ""}
    out = core.comprehensive_web_search(OWNER_QUERY, max_pages=5)
    head = _header(out)
    assert "merriam-webster.com/dictionary/old" in head
    assert "no readable text" in head


def test_a_failed_fetch_does_not_lose_the_other_pages(path):
    path["refuse"] = {"imdb.com": "NetworkError: timed out"}
    out = core.comprehensive_web_search(OWNER_QUERY, max_pages=5)
    assert "fetched 4 pages" in out
    assert "FETCHED PAGE CONTENT:" in out


def test_a_fetcher_that_raises_is_reported_rather_than_swallowed(path, monkeypatch):
    def _boom(url, *a, **kw):
        raise RuntimeError("the fetcher fell over")

    monkeypatch.setattr(core, "fetch_webpage_content", _boom, raising=False)
    out = core.comprehensive_web_search(OWNER_QUERY, max_pages=2)
    head = _header(out)
    assert "fetched 0 pages" in head
    assert "RuntimeError: the fetcher fell over" in head


# ----------------------------------------------------------------------
# 2. A filter selects within the budget; it does not shrink it
# ----------------------------------------------------------------------
def test_a_blacklisted_domain_yields_to_the_next_passing_result(path):
    out = core.comprehensive_web_search(
        OWNER_QUERY, max_pages=3, domain_blacklist={"en.wikipedia.org"})

    assert len(path["fetched"]) == 3, (
        "the caller asked for three pages and the filter reduced it to "
        f"{len(path['fetched'])}: {path['fetched']}"
    )
    assert not any("en.wikipedia.org" in u for u in path["fetched"])


def test_a_whitelist_selects_within_the_budget(path):
    out = core.comprehensive_web_search(
        OWNER_QUERY, max_pages=2,
        domain_whitelist={"www.merriam-webster.com", "oldnavy.gap.com"})

    assert len(path["fetched"]) == 2, path["fetched"]
    for url in path["fetched"]:
        assert ("merriam-webster.com" in url) or ("oldnavy.gap.com" in url)


def test_a_filter_that_excludes_everything_still_says_so(path):
    out = core.comprehensive_web_search(
        OWNER_QUERY, max_pages=3, domain_whitelist={"nowhere.example"})
    assert path["fetched"] == []
    assert "No suitable results after applying filters." in out


def test_a_filter_that_passes_fewer_than_the_budget_fetches_what_passes(path):
    out = core.comprehensive_web_search(
        OWNER_QUERY, max_pages=5, domain_whitelist={"oldnavy.gap.com"})
    assert len(path["fetched"]) == 1, path["fetched"]


def test_no_filter_still_fetches_the_top_of_the_ranking(path):
    out = core.comprehensive_web_search(OWNER_QUERY, max_pages=2)
    assert len(path["fetched"]) == 2
    # The ranked order is what the sources list shows, so the fetched pages are
    # the first two of it.
    sources = [ln for ln in out.splitlines() if ln.startswith("    http")]
    assert set(path["fetched"]) == {sources[0].strip(), sources[1].strip()}


# ----------------------------------------------------------------------
# 3. The verdict is measured on the best evidence available
# ----------------------------------------------------------------------
def test_snippetless_results_are_a_weak_match_on_titles_alone():
    """The premise, before the fix: titles and snippets alone call three
    on-topic pages a bad match."""
    report = relevance_report(OWNER_QUERY, SNIPPETLESS_GOOD)
    assert report["verdict"] in ("weak", "none"), report
    assert report["matched"] <= 3, report


def test_the_fetched_content_is_what_the_verdict_is_measured_on():
    report = relevance_report(
        OWNER_QUERY, SNIPPETLESS_GOOD,
        fetched=[{"url": SNIPPETLESS_GOOD[0]["url"], "content": ON_TOPIC_BODY}],
    )
    assert report["verdict"] == "strong", report
    assert report["best_coverage"] > 0.8, report


def test_a_good_search_with_no_snippets_is_not_called_a_miss(path):
    path["results"] = [dict(r) for r in SNIPPETLESS_GOOD]
    path["bodies"] = {"runescape": ON_TOPIC_BODY}

    out = core.comprehensive_web_search(OWNER_QUERY, max_pages=3)
    head = _header(out)

    assert "Relevance: strong" in head, head
    assert "These results do not match the query" not in out
    assert "6. The Relevance line above" not in out, (
        "the model was told to say the search missed, with three pages in front "
        "of it that answer the question"
    )


def test_the_owners_search_is_still_called_a_miss(path):
    """The fix must not disarm the fx6 lane's verdict. The owner's five pages
    fetch fine and still say nothing about the query."""
    out = core.comprehensive_web_search(OWNER_QUERY, max_pages=5)
    head = _header(out)

    assert "Relevance: weak" in head or "Relevance: none" in head, head
    assert "These results do not match the query" in out
    assert "6. The Relevance line above" in out


def test_content_that_is_off_topic_does_not_rescue_a_bad_match(path):
    path["bodies"] = {"": "an essay about bread and butter pudding " * 40}
    out = core.comprehensive_web_search(OWNER_QUERY, max_pages=5)
    assert "Relevance: weak" in _header(out) or "Relevance: none" in _header(out)


def test_a_term_only_the_fetched_page_mentions_is_not_reported_missing(path):
    path["results"] = [dict(r) for r in SNIPPETLESS_GOOD]
    path["bodies"] = {"runescape": ON_TOPIC_BODY}
    out = core.comprehensive_web_search(OWNER_QUERY, max_pages=3)
    assert "No result mentions" not in _header(out)


def test_a_result_that_was_not_fetched_still_counts_through_its_snippet():
    """A page the fetcher could not reach is still evidence: its snippet is
    what there is, and dropping it would under-report the match."""
    report = relevance_report(OWNER_QUERY, SNIPPETLESS_GOOD + [
        {"title": "Fractured Archive raid details for October 20th",
         "url": "https://osrs.example/x",
         "snippet": "Old School RuneScape raid, full details"},
    ], fetched=[])
    assert report["verdict"] in ("strong", "partial"), report


def test_the_report_tolerates_rubbish_in_the_fetched_rows():
    for junk in (None, [], ["a string"], [{"content": None}], [{}], 7):
        report = relevance_report(OWNER_QUERY, SNIPPETLESS_GOOD, fetched=junk)
        assert report["verdict"] in ("strong", "partial", "weak", "none"), junk


def test_the_report_is_unchanged_when_no_fetched_rows_are_passed():
    assert (relevance_report(OWNER_QUERY, OWNER_RESULTS)
            == relevance_report(OWNER_QUERY, OWNER_RESULTS, fetched=None))
