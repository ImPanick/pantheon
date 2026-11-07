# SPDX-License-Identifier: AGPL-3.0-or-later
"""`B1806`. A web search on a cloud model lost most of the pages it had fetched.

`web_search` cut the search block at the tool's 10,000-character budget with a
prefix cut and no marker. The block puts the sources list, its header and the
results summary first, then every fetched page (3,000 characters of text, a
TL;DR, quotes and statistics, about 4,000 a page) and the closing instructions
last. Measured with five pages of 6,000 characters: 23,004 characters, cut
after the first page and part of the second. Pages three to five and the
instructions (among them the one that says weak results must be called a miss)
never reached the model, while the header still said five pages were fetched.
A local endpoint lifts the cap and was never affected.

Now `web_tools` decides whether the request is capped, in its own coroutine
(the search runs in a worker thread, where the local-endpoint flag is not
set), and passes that budget to `comprehensive_web_search`, which shares it
out: the sources, the header, the summary and the instructions stay whole, each
page keeps its own lines and a share of the rest for its text, and a notice
leading the page section says the pages are shortened. A share too small for
text names the page without it, and `search_excerpt` spends a small share on
one passage rather than two slivers. A block that fits is returned unchanged,
and the hard cut stays as the last guard.

After upstream Odysseus 144c8a3d. Its `bounded_search_observation` kept only
the sources list and the `Query:` line around the pages, which would drop
Pantheon's provider, query-as-sent, not-fetched and relevance lines and the
instructions, so it is not reused.
"""
import asyncio
import json

import pytest

from services.search import core
from src import runtime_limits
from src.agent_tools.web_tools import WebSearchTool
from src.constants import MAX_OUTPUT_CHARS

QUERY = "measured battery evidence"


def _results(n, title_words=6, failing=()):
    rows = []
    for i in range(1, n + 1):
        title = " ".join([f"Battery report {i}"] + ["measured"] * (title_words - 3))
        rows.append({
            "title": title,
            "url": f"https://example.org/report-{i}" + ("-gone" if i in failing else ""),
            "snippet": f"Snippet for report {i}: measured battery evidence and more. " * 5,
        })
    return rows


def _page(url):
    i = url.rsplit("-", 1)[-1]
    return (f"Unique evidence for page {i}. "
            + "Battery cells were measured under load and the evidence recorded. " * 90)


@pytest.fixture
def search(monkeypatch, tmp_path):
    """A search with five results, no network and no cache. Result 3's page
    fails to fetch; every other page is 6,000 characters."""
    state = {"results": _results(5, failing=(3,))}
    monkeypatch.setattr(core, "SEARCH_CACHE_DIR", tmp_path)
    core.search_cache_index.clear()
    monkeypatch.setattr(core, "_read_search_cache", lambda *a, **k: None)
    monkeypatch.setattr(core, "_write_search_cache", lambda *a, **k: None)
    monkeypatch.setattr(core, "_get_search_settings", lambda: {"search_provider": "searxng"})
    monkeypatch.setattr(core, "_get_result_count", lambda: len(state["results"]))
    monkeypatch.setattr(core, "_record_query", lambda *a, **k: None)
    monkeypatch.setattr(core, "rank_search_results", lambda q, rows: rows)
    monkeypatch.setattr(core, "_call_provider",
                        lambda *a, **k: [dict(r) for r in state["results"]])

    def fetch(url, *a, **k):
        if url.endswith("-gone"):
            return {"url": url, "title": "", "content": "", "success": False,
                    "error": "HTTP 403: Forbidden"}
        return {"url": url, "title": f"Page at {url}", "content": _page(url),
                "success": True, "error": ""}

    monkeypatch.setattr(core, "fetch_webpage_content", fetch)
    monkeypatch.setattr(runtime_limits, "_LIFT_WHEN_LOCAL", True)
    monkeypatch.setattr(runtime_limits, "_FORCE_UNLIMITED", False)
    return state


def _web_search(args, local=False):
    async def run():
        runtime_limits.set_local_mode(local)
        return await WebSearchTool().execute(json.dumps(args), {})
    return asyncio.run(run())


def _split(output):
    text, _, tail = output.partition("\n\n<!-- SOURCES:")
    return text, json.loads(tail.rsplit(" -->", 1)[0]) if tail else None


def test_a_search_on_a_capped_model_names_every_page_it_fetched(search):
    result = _web_search({"query": QUERY})
    assert result["exit_code"] == 0
    text, sources = _split(result["output"])

    assert len(text) <= MAX_OUTPUT_CHARS, len(text)
    for i in (1, 2, 4, 5):
        assert f"[CONTENT {i}] From: https://example.org/report-{i}" in text, i
        assert f"Unique evidence for page {i}." in text, i
    assert "Not fetched [3] https://example.org/report-3-gone — HTTP 403" in text
    assert "Relevance: " in text
    assert "END OF WEB SEARCH RESULTS" in text
    assert "IMPORTANT INSTRUCTIONS" in text
    assert "5. Be explicit if the search results" in text
    head = text[text.index("FETCHED PAGE CONTENT:"):text.index("[CONTENT 1]")]
    assert "[SHORTENED" in head and "web_fetch" in head, head
    assert sources == [{"url": r["url"], "title": r["title"]} for r in search["results"]]

    # A local endpoint lifts the cap: the tool hands over the block the
    # search built, byte for byte. Decided in the coroutine, because the
    # search's worker thread does not carry the local-endpoint flag.
    local = _web_search({"query": QUERY}, local=True)
    whole, whole_sources = core.comprehensive_web_search(
        QUERY, max_pages=5, time_filter=None, return_sources=True)
    assert local["output"] == whole + "\n\n<!-- SOURCES:" + json.dumps(whole_sources) + " -->"
    assert len(whole) > MAX_OUTPUT_CHARS


@pytest.mark.parametrize("title_words,shown", [(6, "all"), (18, "some"), (30, "none")],
                         ids=["ten-pages", "long-titles", "very-long-titles"])
def test_ten_pages_are_all_named_within_the_budget(search, title_words, shown):
    """Ten pages, and the longer the result titles the less room for text: the
    summary snippets are shortened first, then the last pages are named
    without their text, and last the summary loses its snippets. Every page is
    named and the instructions stay, whatever is left out."""
    search["results"] = _results(10, title_words=title_words)
    result = _web_search({"query": QUERY, "max_pages": 10})
    text, sources = _split(result["output"])

    assert len(text) <= MAX_OUTPUT_CHARS, len(text)
    assert "IMPORTANT INSTRUCTIONS" in text
    assert len(sources) == 10
    with_text = []
    for i in range(1, 11):
        assert f"[CONTENT {i}] From: https://example.org/report-{i}\n" in text, i
        with_text.append(f"Unique evidence for page {i}." in text)
    # The pages left without text are the last ones, and the notice says so.
    assert with_text == sorted(with_text, reverse=True), with_text
    assert {"all": all(with_text), "some": any(with_text) and not all(with_text),
            "none": not any(with_text)}[shown], with_text
    notice = text[text.index("[SHORTENED"):text.index("]", text.index("[SHORTENED"))]
    if shown == "some":
        assert f"the first {sum(with_text)} pages below" in notice, notice
    if shown == "none":
        assert "no page's text is shown" in notice, notice


def test_a_block_that_fits_its_budget_is_the_block_unchanged(search):
    search["results"] = _results(2)
    plain = core.comprehensive_web_search(QUERY, max_pages=2)
    assert core.comprehensive_web_search(QUERY, max_pages=2, budget=len(plain)) == plain
    assert core.comprehensive_web_search(QUERY, max_pages=2, budget=None) == plain


def test_a_small_share_is_one_passage_rather_than_two_slivers():
    """Ten pages leave each about 300 characters. Two passages in that went
    two slivers of 37 characters and three markers, more marker than page:
    a share that small is spent on one passage."""
    from services.search.ranking import search_excerpt

    text = ("Opening line of the page. " + "Filler about other matters. " * 40
            + "Alpha evidence is described here in some detail. " + "Filler. " * 200
            + "Beta evidence is described there in some detail. " + "Filler. " * 200)
    out = search_excerpt(text, "alpha beta evidence", 400)
    assert len(out) <= 400
    assert out.count("text omitted") <= 2, out
    shown = out.replace("\n[...text omitted; web_fetch the source for the full page...]\n", "")
    assert len(shown) >= 250, (len(shown), out)
    assert "Alpha evidence is described here" in out or "Beta evidence is described there" in out
