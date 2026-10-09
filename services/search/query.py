# SPDX-License-Identifier: AGPL-3.0-or-later
"""Query enhancement, entity extraction, and cache duration helpers."""

import re
import logging
from datetime import timedelta
from typing import Dict, List, Optional, Tuple

logger = logging.getLogger(__name__)


# ----------------------------------------------------------------------
# Query processing helpers
# ----------------------------------------------------------------------
def _detect_question_type(query: str) -> Optional[str]:
    """Return the leading question word if present (who, what, when, where, why, how)."""
    if not isinstance(query, str):
        return None
    q = query.strip().lower()
    for word in ("who", "what", "when", "where", "why", "how"):
        # Require a whole-word match: a bare prefix mis-flags ordinary queries
        # like "whatsapp pricing" (-> what) or "however ..." (-> how), which
        # then get spurious boost terms OR-appended in enhance_query.
        if q == word or q.startswith(word + " "):
            return word
    return None


def _extract_entities(query: str) -> Dict[str, List[str]]:
    """Lightweight entity extraction: capitalized words and date patterns."""
    if not isinstance(query, str):
        return {"names": [], "dates": []}
    entities: Dict[str, List[str]] = {"names": [], "dates": []}
    qtype = _detect_question_type(query)
    cleaned = query
    if qtype:
        cleaned = re.sub(rf"^{qtype}\b", "", cleaned, flags=re.I).strip()
    # Unicode-aware capitalized-word (name) detection. The old [A-Z][a-zA-Z]+
    # class missed non-ASCII names like "İstanbul"/"Zürich" (dropped) and
    # "São" (shredded). Keep the ASCII behaviour — the word boundary already
    # excludes camelCase mid-word capitals — by requiring an all-alphabetic
    # token of length > 1 whose first character is uppercase.
    for token in re.findall(r"\b\w+\b", cleaned):
        if len(token) > 1 and token[0].isupper() and token.isalpha():
            entities["names"].append(token)
    for year in re.findall(r"\b(?:19|20)\d{2}\b", cleaned):
        entities["dates"].append(year)
    month_day_year = re.findall(
        r"\b(?:Jan|January|Feb|February|Mar|March|Apr|April|May|Jun|June|Jul|July|Aug|August|Sep|Sept|September|Oct|October|Nov|November|Dec|December)\s+\d{1,2},?\s*\d{4}\b",
        cleaned,
        flags=re.I,
    )
    entities["dates"].extend(month_day_year)
    return entities


def _split_multi_part(query: str) -> List[str]:
    """Split a query into sub-queries on common conjunctions.

    **No longer on the sent-query path** (the 2026-10-09 owner report, item 4).
    `" and "` in English prose is almost never a boolean operator: measured,
    this turns *"bread and butter pudding"* into `["bread", "butter pudding"]`
    and *"rock and roll hall of fame"* into `["rock", "roll hall of fame"]`.
    `enhance_query` joined the parts with `AND`, so the conjunction was deleted
    and the person's one subject became two that both had to match. Kept
    because `Law 1` does not delete what exists, and because a caller that
    genuinely wants sub-queries (deep research fanning out) is a reasonable
    future use — it is just not what a single search should do to a sentence.
    """
    if not isinstance(query, str):
        return []
    parts = re.split(r"\s+and\s+|\s+or\s+|;", query, flags=re.I)
    return [p.strip() for p in parts if p.strip()]


def _extract_site_filter(query: str) -> Tuple[str, Optional[str]]:
    """Detect a 'site:example.com' token. Returns (query_without_token, site_or_None)."""
    if not isinstance(query, str):
        return "", None
    match = re.search(r"\bsite:([^\s]+)", query, flags=re.I)
    if match:
        site = match.group(1)
        new_query = re.sub(r"\bsite:[^\s]+", "", query, flags=re.I).strip()
        return new_query, site
    return query, None


def _boost_entities_in_query(base_query: str, entities: Dict[str, List[str]]) -> str:
    """Append extracted entities to the query using OR to increase relevance.

    **No longer on the sent-query path** (`B-NEW` / the 2026-10-09 owner report).
    It is kept because it is public-ish, imported by tests, and `Law 1` does not
    delete what exists — but `enhance_query` stopped calling it, because what it
    does is the opposite of what its name says.

    Measured: the owner searched *"Old School RuneScape Fractured Archive raid
    details October 20th"* and this turned it into

        (Old School RuneScape Fractured Archive raid details October 20th "Old"
         OR "School" OR "RuneScape" OR "Fractured" OR "Archive" OR "October")

    64 characters in, 140 out — and every capitalised token became an **OR
    alternative**, so a page containing only the word *Old* satisfies the query.
    The five results that came back were a Shyamalan film, its IMDb page, its
    trailer, a dictionary entry for *"old"* and Old Navy. Over a 27-query
    corpus (see `/work/notes/fx6-search.md`) there was no query it narrowed and
    none it left alone except those with no capital letter at all — so
    non-Latin scripts got no "enhancement" and Latin ones got damage.
    """
    parts = [base_query]
    if entities.get("names"):
        parts.append(" OR ".join(f'"{n}"' for n in entities["names"]))
    if entities.get("dates"):
        parts.append(" OR ".join(f'"{d}"' for d in entities["dates"]))
    return " ".join(parts)


def enhance_query(original_query: str) -> Tuple[str, Optional[str]]:
    """Return ``(query_as_sent, site_or_None)`` for a person's query.

    The person's words, with runs of whitespace collapsed. Nothing is added,
    removed, re-ordered or quoted, and the `site:` token stays where the person
    put it — engines parse it, and it is reported in the second element so a
    caller can say what it saw.

    **What this used to do, and why it stopped** (the 2026-10-09 owner report,
    item 4). Three mechanisms, each measured against a 27-query corpus:

      * `_boost_entities_in_query` OR-appended every capitalised token — see
        its docstring for the owner's own query, 64 characters in and 140 out.
      * `_split_multi_part` split on a bare `" and "` / `" or "` / `";"`, so
        *"bread and butter pudding"* was sent as `(bread) AND (butter pudding)`:
        the conjunction **deleted** and one dish turned into two queries that
        have to both match. *"Laurel and Hardy filmography"* became
        `(Laurel "Laurel") AND (Hardy filmography "Hardy")`.
      * the question-type keywords OR-appended a bare part-of-speech word, so
        *"who is the CEO of Jagex"* ended `... OR (person)` — satisfied by any
        page containing the word *person*.

    It also wrapped the result in parentheses and re-appended the `site:` token
    it had just stripped, which on the one provider that received any of this
    (Brave — `build_enhanced_query` was called from `_brave_search_impl` alone)
    meant the person's own quoted phrases were broken apart and the grouping
    was literal text.

    `_detect_question_type`, `_extract_entities`, `_split_multi_part` and
    `_boost_entities_in_query` all survive (`Law 1`) and `_extract_entities` is
    now put to honest use by `ranking.relevance_report`, which uses the same
    tokens to measure whether the results came back about the right thing.
    """
    if not isinstance(original_query, str):
        return "", None
    _, site = _extract_site_filter(original_query)
    return " ".join(original_query.split()), site


def build_enhanced_query(query: str, time_filter: str = None) -> str:
    """The one place the string sent to a search engine is derived (`Law 7`).

    ``time_filter`` is accepted and deliberately **not** written into the query
    text. Every provider takes it as a native parameter — `freshness` (Brave),
    `time_range` (SearXNG), `timelimit` (DuckDuckGo), `dateRestrict` (Google
    PSE), `days` (Tavily), `tbs` (Serper) — and `services/search/core.py`
    passes it to each of them. This function used to *also* append
    ``after:d`` / ``after:w`` / ``after:m`` / ``after:y``, which no engine
    parses (Brave has no ``after:`` operator; Google's wants a date, not a
    letter), so on Brave the filter was applied twice: once correctly as
    ``freshness`` and once as four characters of literal text inside ``q``.
    """
    sent, _ = enhance_query(query)
    if sent != query:
        logger.info("Search query as sent: %r (from %r)", sent, query)
    else:
        logger.info("Search query as sent: %r", sent)
    return sent


# ----------------------------------------------------------------------
# "Is this a news query?" — one definition (`Law 7`)
# ----------------------------------------------------------------------
# Three modules answered this three ways on `3b40a4e`, and 12 of a 27-query
# corpus got different answers depending on which one you asked:
#
#   * `providers.py:126` — this set as a tuple, matched as a **substring** of
#     the lowered query, deciding which SearXNG *category* the search goes to.
#     So *"Newsom California policy"*, *"newsletter signup best practices"* and
#     *"how to use newsprint for packing"* were news queries because the
#     letters `news` sit inside a surname and two common words, and
#     *"todays-menu at the Blue Moon Inn"* was one because `today` sits inside
#     `todays`. The index a person's query is searched in was chosen on
#     orthography — the same mistake `_boost_entities_in_query` made above.
#   * `ranking.py:49` — the byte-identical set, matched as a **whole token**,
#     deciding whether news-domain bonuses and penalties move the ordering.
#   * here — a **different** set, whole-token, deciding the cache duration.
#
# Two of the three already agreed exactly, and they are asking the same
# question, so `NEWS_TERMS` is that set and `is_news_query` is that question.
# The matcher is whole-token, which is what two of three already did and what
# the substring match got wrong.
NEWS_TERMS = frozenset({
    "news", "nyheter", "headlines", "breaking", "latest", "today", "idag",
})

# The one deliberate difference, named here rather than discovered later.
# "Does this query want fresh results" is a different question from "is this
# query about news", and only the cache duration asks it: a false positive
# costs one extra provider call, while a false negative serves a day-old answer
# to someone asking what is happening now. These three terms were live in the
# old cache set and in neither of the other two, so `Law 1` keeps them —
# exactly where they were already used and nowhere they were not.
#
# The old set also held `"today's"`, which was **unreachable**: the tokeniser
# below is `\b\w+\b`, which splits `today's` into `today` and `s`, so the
# literal token could never appear in the set it was matched against. `today`
# catches the same queries and is in `NEWS_TERMS`.
_FRESH_ONLY_TERMS = frozenset({"current", "updates", "happening"})
FRESH_TERMS = NEWS_TERMS | _FRESH_ONLY_TERMS


def _query_tokens(query) -> set:
    """The query's words, lowered. Non-strings tokenise to nothing."""
    if not isinstance(query, str):
        return set()
    return {t.lower() for t in re.findall(r"\b\w+\b", query)}


def is_news_query(query) -> bool:
    """True when the query is about news. The one definition (`Law 7`).

    Cited by `providers._searxng_params` (which SearXNG category) and
    `ranking.rank_search_results` (whether news-domain scoring applies).
    Whole-token, never substring.
    """
    return bool(_query_tokens(query) & NEWS_TERMS)


def wants_fresh_results(query) -> bool:
    """True when the query wants *fresh* results, which is a wider question.

    `NEWS_TERMS` plus `_FRESH_ONLY_TERMS`. Only `_cache_duration_for_query`
    asks this, for the reason written on `_FRESH_ONLY_TERMS`.
    """
    return bool(_query_tokens(query) & FRESH_TERMS)


# Kept name (`Law 1`): the private predicate two test files and any older
# caller reach for. It is the news question, which is what the name says.
_is_news_query = is_news_query


# ----------------------------------------------------------------------
# Cache duration helpers
# ----------------------------------------------------------------------
NEWS_CACHE_DURATION = timedelta(minutes=30)
REFERENCE_CACHE_DURATION = timedelta(hours=24)

# The longest duration `_cache_duration_for_query` can return. The LRU sweep in
# `core.py` is given this, so it never retires an entry whose own expiry says
# it has longer to live. Measured on `3b40a4e`: the sweep was handed
# `timedelta(hours=1)` while the write path stamped a reference query with 24
# hours, so the entry was deleted by the next search once its index timestamp
# was 90 minutes old — one hour was the real ceiling and the news/reference
# split had never had any effect. `Law 7`: the expiry in the file is the one
# source of truth for when an entry dies, and this is the window the sweep is
# allowed to disagree with it over, which is none.
MAX_CACHE_DURATION = REFERENCE_CACHE_DURATION


def _cache_duration_for_query(query: str) -> timedelta:
    """Fresh-sounding queries -> 30 minutes, reference queries -> 24 hours."""
    if wants_fresh_results(query):
        return NEWS_CACHE_DURATION
    return REFERENCE_CACHE_DURATION
