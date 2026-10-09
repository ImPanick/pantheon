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
# Cache duration helpers
# ----------------------------------------------------------------------
def _is_news_query(query: str) -> bool:
    """Lightweight heuristic to decide if a query is news-oriented."""
    news_terms = {"news", "latest", "breaking", "today", "today's", "current", "updates", "happening"}
    if not isinstance(query, str):
        return False
    tokens = set(re.findall(r"\b\w+\b", query.lower()))
    return bool(tokens & news_terms)


def _cache_duration_for_query(query: str) -> timedelta:
    """News queries -> 30 minutes, reference queries -> 24 hours."""
    if _is_news_query(query):
        return timedelta(minutes=30)
    return timedelta(hours=24)
