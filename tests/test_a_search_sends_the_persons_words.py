# SPDX-License-Identifier: AGPL-3.0-or-later
"""The query a person typed is the query that goes to the search engine.

The owner searched *"Old School RuneScape Fractured Archive raid details
October 20th"* and got back **Old (film)**, **Old (2021) on IMDb**, **Old on
YouTube**, Merriam-Webster's definition of *"old"*, and **Old Navy** — five
results, none about the game, and the model then invented generic raid advice
from them.

Measured on `99134cf`: `services/search/query.py` built the sent query by
appending every capitalised token as an **OR alternative**, so the owner's
query left as

    (Old School RuneScape Fractured Archive raid details October 20th "Old"
     OR "School" OR "RuneScape" OR "Fractured" OR "Archive" OR "October")

— 64 characters in, 140 out, and a page containing only the word *Old* matches
it. Three more mechanisms in the same function were measured to damage the
query rather than narrow it, and each has a case below:

  * `_split_multi_part` split on a bare `" and "`/`" or "`, so
    *"bread and butter pudding"* became `(bread) AND (butter pudding)` — the
    conjunction deleted and the dish turned into two unrelated queries.
  * `_detect_question_type` OR-appended a bare keyword, so *"who is the CEO of
    Jagex"* became `(... ) OR (person)` — any page containing the word
    *person* matches.
  * `build_enhanced_query` appended `after:d` / `after:w` for a time filter.
    No provider parses that (Brave has no `after:` operator and Google's wants
    a date), and Brave was *also* being sent the correct `freshness` parameter
    — the filter applied twice, once as a parameter and once as literal text.

And the enhancement reached exactly **one of six** providers: measured on the
base, `build_enhanced_query` was called only from `_brave_search_impl`, so the
same query meant two different things depending on a setting, and nothing
anywhere recorded which string had been sent.

These drive: the person's words reach every provider unchanged, the two
filters a search engine really understands (`site:`, the time filter) still
work, and the result block the model reads names the provider, the query as
sent, and how well the results matched.

Every case uses a fake provider that records the query string it was handed.
Nothing here touches the network.
"""

import pytest

from services.search import core, providers
from services.search.query import build_enhanced_query, enhance_query

# The owner's query, verbatim from `/work/notes/owner-shots/2026-10-09-osrs-chat-export.md:10`.
OWNER_QUERY = "Old School RuneScape Fractured Archive raid details October 20th"

# The owner's five results, verbatim from the same export (lines 36-50).
OWNER_RESULTS = [
    {
        "title": "Old (film) - Wikipedia",
        "url": "https://en.wikipedia.org/wiki/Old_(film)",
        "snippet": (
            "Old is a 2021 American mystery thriller film written, directed, and "
            "produced by M. Night Shyamalan. It is based on the French graphic novel."
        ),
    },
    {
        "title": "Old (2021) - IMDb",
        "url": "https://www.imdb.com/title/tt10954652/",
        "snippet": (
            "Jul 23, 2021 - Old: Directed by M. Night Shyamalan. With Gael Garcia "
            "Bernal, Vicky Krieps, Rufus Sewell, Alex Wolff. A vacationing family."
        ),
    },
    {
        "title": "Old - YouTube",
        "url": "https://www.youtube.com/watch?v=84xAD4r-9kE",
        "snippet": (
            "Old is a Blinding Edge Pictures production, directed and produced by "
            "M. Night Shyamalan, from his screenplay based on the graphic novel."
        ),
    },
    {
        "title": "OLD Definition & Meaning - Merriam-Webster",
        "url": "https://www.merriam-webster.com/dictionary/old",
        "snippet": (
            "2 days ago - The meaning of OLD is dating from the remote past : "
            "ancient. How to use old in a sentence. Synonym Discussion of Old."
        ),
    },
    {
        "title": "Old Navy | Affordable Clothing for Women, Men, Kids & Baby",
        "url": "https://oldnavy.gap.com/?msockid=2d2403890cb86fbf30c414640d656e10",
        "snippet": (
            "Old Navy provides the latest fashions at great prices for the whole "
            "family. Shop men's, women's, women's plus, kids' and baby clothing."
        ),
    },
]

# What a result set that actually answers the owner's question looks like.
GOOD_RESULTS = [
    {
        "title": "Fractured Archive raid details and release date - Old School RuneScape",
        "url": "https://secure.runescape.com/m=news/fractured-archive",
        "snippet": (
            "Our new raid, the Fractured Archive, arrives October 20th. Here are the "
            "details on the bosses you will fight and the mechanics of each room."
        ),
    },
    {
        "title": "Fractured Archive - OSRS Wiki",
        "url": "https://oldschool.runescape.wiki/w/Fractured_Archive",
        "snippet": (
            "The Fractured Archive is a raid in Old School RuneScape released on "
            "October 20th. It scales for teams of one to five players."
        ),
    },
]


# ----------------------------------------------------------------------
# A fake provider that records the query it was given
# ----------------------------------------------------------------------
class _Recorder:
    """Stands in for every search provider and records each call.

    `calls` is a list of `(provider_name, query, count, time_filter)`.
    """

    def __init__(self, results=None):
        self.calls = []
        self.results = results if results is not None else list(OWNER_RESULTS)

    def install(self, monkeypatch, *, only=None):
        """Replace `core._call_provider` with this recorder.

        `only` restricts which provider name is allowed to answer, so a test
        can prove the chain reached a specific one.
        """

        def _fake(provider_name, query, count, time_filter=None):
            self.calls.append((provider_name, query, count, time_filter))
            if only is not None and provider_name != only:
                return []
            return [dict(r) for r in self.results]

        monkeypatch.setattr(core, "_call_provider", _fake)

    @property
    def queries(self):
        return [c[1] for c in self.calls]

    @property
    def last_query(self):
        assert self.calls, "no provider was called"
        return self.calls[-1][1]


@pytest.fixture
def offline(monkeypatch):
    """No settings, no network, no page fetching, no cache, no analytics file."""
    monkeypatch.setattr(core, "_get_search_settings", lambda: {}, raising=False)
    monkeypatch.setattr(core, "_get_result_count", lambda: 5, raising=False)
    monkeypatch.setattr(core, "_record_query", lambda *a, **k: None, raising=False)
    # No page content: these cases are about the query and the result block.
    monkeypatch.setattr(
        core,
        "fetch_webpage_content",
        lambda url, *a, **k: {"success": False, "content": "", "title": "", "url": url},
        raising=False,
    )
    monkeypatch.setattr(providers, "_get_search_settings", lambda: {}, raising=False)
    return monkeypatch


# ----------------------------------------------------------------------
# 1. The owner's own query, as a string sent to a provider
# ----------------------------------------------------------------------
def test_the_owners_query_reaches_the_provider_exactly_as_typed(offline):
    rec = _Recorder()
    rec.install(offline)

    core.comprehensive_web_search(OWNER_QUERY, max_pages=5)

    sent = rec.last_query
    assert sent == OWNER_QUERY, f"the provider was handed a different query: {sent!r}"
    # The three shapes the base appended, named so a regression says which came back.
    assert " OR " not in sent, "an OR alternative is back in the sent query"
    assert '"Old"' not in sent, "the capitalised-token boost is back"
    assert not sent.startswith("("), "the sent query is wrapped in parentheses"


def test_build_enhanced_query_returns_the_owners_words(offline):
    assert build_enhanced_query(OWNER_QUERY) == OWNER_QUERY
    # 64 characters in, 64 out. On the base this was 140.
    assert len(build_enhanced_query(OWNER_QUERY)) == len(OWNER_QUERY)


def test_every_capitalised_token_in_the_owners_query_stays_a_plain_word(offline):
    sent = build_enhanced_query(OWNER_QUERY)
    for token in ("Old", "School", "RuneScape", "Fractured", "Archive", "October"):
        assert f'"{token}"' not in sent, f"{token} is still OR-boosted as a quoted alternative"


# ----------------------------------------------------------------------
# 2. "and" / "or" in ordinary prose is not an operator
# ----------------------------------------------------------------------
@pytest.mark.parametrize(
    "query",
    [
        "bread and butter pudding",
        "Laurel and Hardy filmography",
        "should I use Postgres or MySQL for a small app",
        "rock and roll hall of fame",
    ],
)
def test_a_conjunction_in_prose_survives_into_the_sent_query(offline, query):
    sent = build_enhanced_query(query)
    assert sent == query
    assert " AND (" not in sent, "the query was split into sub-queries"


def test_bread_and_butter_pudding_is_one_query_at_the_provider(offline):
    rec = _Recorder()
    rec.install(offline)

    core.comprehensive_web_search("bread and butter pudding", max_pages=3)

    assert rec.last_query == "bread and butter pudding"


# ----------------------------------------------------------------------
# 3. A question is a question, not an OR over a part-of-speech word
# ----------------------------------------------------------------------
@pytest.mark.parametrize(
    "query,keyword",
    [
        ("who is the CEO of Jagex", "person"),
        ("when does the Fractured Archive release", "date"),
        ("where is Varlamore", "location"),
        ("why did Jagex delay the raid", "reason"),
        ("how do I beat the Fractured Archive", "method"),
    ],
)
def test_a_question_word_adds_no_or_keyword(offline, query, keyword):
    sent = build_enhanced_query(query)
    assert sent == query
    assert f"({keyword})" not in sent, f"the {keyword!r} OR-keyword is back"
    assert " OR " not in sent


def test_what_questions_keep_their_words(offline):
    # "what" never had a boost keyword of its own, but it did get the entity
    # OR-boost, which is the half that broke the owner's search.
    assert build_enhanced_query("what is the Fractured Archive") == "what is the Fractured Archive"


# ----------------------------------------------------------------------
# 4. The filters a search engine really does understand
# ----------------------------------------------------------------------
def test_a_site_filter_stays_in_the_query_once_and_is_reported(offline):
    sent, site = enhance_query("release notes site:jagex.com")
    assert site == "jagex.com", "the site: token is no longer reported to the caller"
    assert sent.count("site:jagex.com") == 1, "the site: token was duplicated or dropped"
    assert sent == "release notes site:jagex.com"


def test_a_site_filter_reaches_the_provider_intact(offline):
    rec = _Recorder()
    rec.install(offline)

    core.comprehensive_web_search("release notes site:jagex.com", max_pages=3)

    assert rec.last_query == "release notes site:jagex.com"
    assert "(" not in rec.last_query, "the query was wrapped in parentheses around site:"


@pytest.mark.parametrize("time_filter", ["day", "week", "month", "year"])
def test_a_time_filter_is_a_parameter_not_text_in_the_query(offline, time_filter):
    sent = build_enhanced_query(OWNER_QUERY, time_filter)
    assert sent == OWNER_QUERY
    assert "after:" not in sent, "the invalid after:<letter> operator is back in the query text"


def test_the_time_filter_still_reaches_the_provider_as_an_argument(offline):
    rec = _Recorder()
    rec.install(offline)

    core.comprehensive_web_search("latest OSRS news", max_pages=3, time_filter="day")

    assert rec.calls, "no provider was called"
    assert rec.calls[-1][3] == "day", "the time filter was lost on the way to the provider"
    assert "after:" not in rec.last_query


def test_brave_sends_the_time_filter_once_as_its_freshness_parameter(offline, monkeypatch):
    """Brave took the filter twice on the base: `freshness=day` *and* `after:d`
    inside `q`. It keeps the parameter and loses the text."""
    seen = {}

    class _Resp:
        status_code = 200

        def raise_for_status(self):
            return None

        def json(self):
            return {"web": {"results": []}}

    def _fake_get(url, headers=None, params=None, timeout=None, **kw):
        seen.update(params or {})
        return _Resp()

    monkeypatch.setattr(providers.httpx, "get", _fake_get)
    monkeypatch.setattr(providers, "_safesearch_for", lambda *_a, **_k: None, raising=False)
    monkeypatch.setenv("DATA_BRAVE_API_KEY", "k")

    providers.brave_search(OWNER_QUERY, 5, "day")

    assert seen.get("freshness") == "day"
    assert seen.get("q") == OWNER_QUERY
    assert "after:" not in seen.get("q", "")


# ----------------------------------------------------------------------
# 5. One query, every provider — the string no longer depends on a setting
# ----------------------------------------------------------------------
_ALL_PROVIDERS = ["searxng", "brave", "duckduckgo", "google_pse", "tavily", "serper"]


@pytest.mark.parametrize("provider", _ALL_PROVIDERS)
def test_each_provider_is_handed_the_same_string(offline, provider):
    offline.setattr(core, "_get_search_settings", lambda: {"search_provider": provider})
    rec = _Recorder()
    rec.install(offline, only=provider)

    core.comprehensive_web_search(OWNER_QUERY, max_pages=3)

    assert provider in [c[0] for c in rec.calls], f"{provider} was never reached"
    for name, query, _count, _tf in rec.calls:
        assert query == OWNER_QUERY, f"{name} was handed {query!r}"


def test_no_provider_derives_its_own_query_string(monkeypatch):
    """`build_enhanced_query` is the one place the sent query is derived
    (`Law 7`). On the base `_brave_search_impl` called it a second time — and
    was its only production caller — so enhancement happened on one provider in
    six and the sent string depended on a setting.

    Driven rather than grepped: each provider is called directly and the string
    it puts on the wire is compared to the string it was given.
    """
    wire = []

    class _Resp:
        status_code = 200
        is_success = True
        text = "<html></html>"

        def raise_for_status(self):
            return None

        def json(self):
            return {"results": [], "web": {"results": []}, "items": [], "organic": []}

    def _get(url, params=None, headers=None, timeout=None, **kw):
        wire.append((url, (params or {}).get("q")))
        return _Resp()

    def _post(url, json=None, headers=None, timeout=None, **kw):
        body = json or {}
        wire.append((url, body.get("q") or body.get("query")))
        return _Resp()

    monkeypatch.setattr(providers.httpx, "get", _get)
    monkeypatch.setattr(providers.httpx, "post", _post)
    monkeypatch.setattr(providers, "_get_search_settings", lambda: {}, raising=False)
    monkeypatch.setattr(providers, "_safesearch_for", lambda *_a, **_k: None, raising=False)
    for var in ("DATA_BRAVE_API_KEY", "GOOGLE_API_KEY", "TAVILY_API_KEY", "SERPER_API_KEY"):
        monkeypatch.setenv(var, "k")
    monkeypatch.setenv("GOOGLE_PSE_CX", "cx")

    for fn in (
        providers.searxng_search_api,
        providers.brave_search,
        providers.google_pse_search,
        providers.tavily_search,
        providers.serper_search,
    ):
        wire.clear()
        fn(OWNER_QUERY, 5)
        assert wire, f"{fn.__name__} made no request"
        for url, sent in wire:
            assert sent == OWNER_QUERY, f"{fn.__name__} sent {sent!r} to {url}"


# ----------------------------------------------------------------------
# 6. Non-English and operator-bearing queries are not rewritten
# ----------------------------------------------------------------------
@pytest.mark.parametrize(
    "query",
    [
        "Wetter in Zürich morgen",
        "オールドスクール ルーンスケープ レイド",
        "İstanbul hava durumu",
        '"Fractured Archive" OSRS',
        "jaguar -car",
        "NASA JWST images",
        "docker compose; kubernetes",
        "patch notes October 20, 2026",
    ],
)
def test_a_query_is_passed_through_unchanged(offline, query):
    assert build_enhanced_query(query) == query


def test_a_persons_own_quoted_phrase_is_not_broken_apart(offline):
    sent = build_enhanced_query('"Fractured Archive" OSRS')
    # On the base the words inside the quotes were pulled out and OR-ed back in,
    # which is exactly the constraint the person was asking for, removed.
    assert sent.count('"') == 2
    assert " OR " not in sent


def test_whitespace_is_collapsed_but_words_are_not_touched(offline):
    assert build_enhanced_query("  bread   and \n butter  ") == "bread and butter"


def test_a_non_string_query_still_returns_a_string(offline):
    # Pinned by tests/test_search_query_nonstring.py; kept here so the
    # pass-through path cannot regress it.
    assert build_enhanced_query(None) == ""
    assert build_enhanced_query(123) == ""
    assert enhance_query(None) == ("", None)
