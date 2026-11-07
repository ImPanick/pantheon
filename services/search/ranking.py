# SPDX-License-Identifier: AGPL-3.0-or-later
"""Search result ranking based on relevance, source quality, and recency."""

import math
import re
import logging
from bisect import bisect_left
from datetime import datetime, timezone
from typing import List, Optional
from urllib.parse import urlparse

from .query import NEWS_TERMS, is_news_query

logger = logging.getLogger(__name__)

_AGE_FORMATS = ("%Y-%m-%d", "%Y-%m-%dT%H:%M:%S", "%Y-%m-%d %H:%M:%S")


def _utcnow_naive() -> datetime:
    """Naive UTC 'now'. Matches the naive, UTC-style published dates parsed below,
    and is safe on Python 3.14 where ``datetime.utcnow()`` is removed (#1116)."""
    return datetime.now(timezone.utc).replace(tzinfo=None)


def recency_score(age_str: Optional[str], now: Optional[datetime] = None) -> float:
    """Score how recent a result is: 1.0 for <=7 days old, 0.0 for >=30 days.

    The age is measured against UTC, not local time. The previous code used
    ``datetime.now()`` (local) against UTC-style published dates, so the age was
    skewed by the host's UTC offset; it was also a latent crash once neighbouring
    code moves to timezone-aware datetimes (#1116). ``now`` is injectable for tests.
    """
    if not age_str:
        return 0.0
    dt = None
    for fmt in _AGE_FORMATS:
        try:
            dt = datetime.strptime(age_str, fmt)
            break
        except Exception:
            dt = None
    if not dt:
        return 0.0
    now = now or _utcnow_naive()
    days_old = (now - dt).days
    if days_old <= 7:
        return 1.0
    if days_old >= 30:
        return 0.0
    return (30 - days_old) / 23


# One definition of "this is a news query", in `services/search/query.py`
# (`Law 7`). This module's own copy was byte-identical to `providers.py`'s and
# matched the same way this does — whole tokens — but the two were separate
# literals and `query.py` held a third, different set. The name stays bound
# here (`Law 1`); the set it points at is now the only one in the package.
_NEWS_HINTS = NEWS_TERMS
_SPORTS_HINTS = {
    "sport", "sports", "soccer", "football", "hockey", "nba", "nfl", "mlb",
    "fifa", "world cup", "championship", "quarterfinal", "eliminates",
}
# Word-boundary match so "sport" does not fire inside "transport"/"passport"
# and a domain like "transport.gov" is not mistaken for a sports site.
_SPORTS_HINT_RE = re.compile(
    r"\b(?:" + "|".join(re.escape(h) for h in _SPORTS_HINTS) + r")\b"
)
_LOW_VALUE_NEWS_DOMAINS = {
    "facebook.com", "www.facebook.com", "sports.yahoo.com", "yahoo.com",
    "www.yahoo.com", "msn.com", "www.msn.com",
}
_TRUSTED_NEWS_DOMAINS = {
    "apnews.com", "www.apnews.com", "reuters.com", "www.reuters.com",
    "bbc.com", "www.bbc.com", "cbc.ca", "www.cbc.ca",
    "ctvnews.ca", "www.ctvnews.ca", "globalnews.ca", "www.globalnews.ca",
    "theguardian.com",
    "www.theguardian.com", "euronews.com", "www.euronews.com",
    "dw.com", "www.dw.com", "government.se", "www.government.se",
}


def _domain(url: str) -> str:
    try:
        return urlparse(url).netloc.lower()
    except Exception:
        return ""


def _has_word(text: str, term: str) -> bool:
    """True if ``term`` appears in ``text`` as a whole word.

    Query terms are matched on word boundaries so a short term doesn't match
    inside an unrelated word: "us" must not match "business"/"music", "port"
    must not match "transport"/"support". This mirrors the tokenization used to
    build ``query_terms`` (``\\b\\w+\\b``). #1473 converted the title and sports
    checks to word boundaries; the snippet and subject-term checks below use
    the same helper so the whole file stays consistent.
    """
    return re.search(rf"\b{re.escape(term)}\b", text) is not None


def rank_search_results(query: str, results: List[dict]) -> List[dict]:
    """Rank search results by title relevance, snippet quality, domain authority, and recency."""
    query_terms = [t.lower() for t in re.findall(r"\b\w+\b", query)]
    query_lc = query.lower()
    # The one definition (`Law 7`). Same answer as the SearXNG category switch
    # and the cache, for the same query, which was not true before.
    is_news = is_news_query(query)
    is_sports_query = bool(_SPORTS_HINT_RE.search(query_lc))

    def title_score(title: str) -> float:
        if not title:
            return 0.0
        title_lc = title.lower()
        matches = sum(1 for term in query_terms if _has_word(title_lc, term))
        return matches / len(query_terms) if query_terms else 0.0

    def snippet_score(snippet: str) -> float:
        if not snippet:
            return 0.0
        length_factor = min(len(snippet), 200) / 200
        term_hits = sum(1 for term in query_terms if _has_word(snippet.lower(), term))
        term_factor = term_hits / len(query_terms) if query_terms else 0.0
        return (length_factor + term_factor) / 2

    def domain_score(url: str) -> float:
        netloc = _domain(url)
        if not netloc:
            return 0.0
        if netloc in _TRUSTED_NEWS_DOMAINS:
            return 1.0
        if netloc.endswith(".edu") or netloc.endswith(".gov"):
            return 1.0
        if netloc.endswith(".org"):
            return 0.7
        return 0.4

    def news_quality_adjustment(title: str, snippet: str, url: str) -> float:
        if not is_news:
            return 0.0
        text = f"{title} {snippet}".lower()
        netloc = _domain(url)
        adjustment = 0.0
        if netloc in _TRUSTED_NEWS_DOMAINS:
            adjustment += 1.2
        if any(term in text for term in ("latest news", "breaking news", "daily coverage", "news from")):
            adjustment += 0.4
        if netloc in _LOW_VALUE_NEWS_DOMAINS:
            adjustment -= 0.8
        if not is_sports_query and (_SPORTS_HINT_RE.search(text) or _SPORTS_HINT_RE.search(netloc)):
            adjustment -= 1.5
        # A country/news query should not rank a page whose title/snippet barely
        # mentions the country above actual news pages for that country.
        subject_terms = [t for t in query_terms if t not in _NEWS_HINTS]
        if subject_terms and not any(_has_word(text, t) or _has_word(netloc, t) for t in subject_terms):
            adjustment -= 1.0
        return adjustment

    ranked = []
    for result in results:
        title = result.get("title", "")
        snippet = result.get("snippet", "")
        url = result.get("url", "")
        age = result.get("age", None)

        score = (
            2.0 * title_score(title)
            + 1.0 * snippet_score(snippet)
            + 1.5 * domain_score(url)
            + 1.0 * recency_score(age)
            + news_quality_adjustment(title, snippet, url)
        )
        ranked.append((score, result))

    ranked.sort(key=lambda x: x[0], reverse=True)
    return [r for _, r in ranked]


# ----------------------------------------------------------------------
# How well did the results match? (the 2026-10-09 owner report, items 4 and 5)
# ----------------------------------------------------------------------
# An enum, not a boolean: `relevant: false` reads both as "the results are not
# relevant" and "the relevance check did not apply", and the thing downstream of
# it is a language model (`Law 10`).
RELEVANCE_VERDICTS = ("strong", "partial", "weak", "none")

# Coverage is the fraction of the query's *subject* terms that appear in a
# result's title or snippet. The boundaries are the measured gap between the
# owner's five results (best coverage 1/9 = 0.11) and a result set that answers
# the same question (9/9 = 1.0); `partial` is where a result shares the subject
# but not the specifics, which is worth reading and worth saying.
_STRONG_COVERAGE = 0.6
_PARTIAL_COVERAGE = 0.35

# Words that carry no subject. Counting them makes a short question look like a
# bad match ("who is the CEO of Jagex" is 6 tokens and 2 of them are the point).
_FILLER_TERMS = frozenset({
    # question words — `_detect_question_type` names the same six
    "who", "what", "when", "where", "why", "how", "which", "whose", "whom",
    # articles, conjunctions, prepositions, auxiliaries
    "a", "an", "the", "and", "or", "but", "if", "of", "in", "on", "at", "to",
    "for", "from", "by", "with", "about", "into", "over", "after", "before",
    "is", "are", "was", "were", "be", "been", "being", "am", "do", "does",
    "did", "has", "have", "had", "can", "could", "will", "would", "shall",
    "should", "may", "might", "must", "it", "its", "this", "that", "these",
    "those", "i", "me", "my", "we", "us", "our", "you", "your", "he", "she",
    "they", "them", "their", "there", "here", "as", "so", "than", "then",
    "up", "out", "off", "down", "not", "no", "any", "all", "some", "more",
    "most", "very", "just", "also", "like", "get", "got", "want", "need",
})


def subject_terms(query: str) -> List[str]:
    """The words that make a query *this* query, in order, de-duplicated.

    Tokenised the way `rank_search_results` tokenises (``\\b\\w+\\b``), minus
    `_FILLER_TERMS`. A query made of nothing but filler falls back to its own
    tokens so coverage is never divided by zero.
    """
    if not isinstance(query, str):
        return []
    tokens = [t.lower() for t in re.findall(r"\b\w+\b", query)]
    terms = [t for t in tokens if t not in _FILLER_TERMS]
    if not terms:
        terms = tokens
    seen = set()
    out = []
    for t in terms:
        if t not in seen:
            seen.add(t)
            out.append(t)
    return out


def _result_text(result) -> str:
    if not isinstance(result, dict):
        return ""
    return f"{result.get('title') or ''} {result.get('snippet') or ''}".lower()


# ----------------------------------------------------------------------
# The part of a page the block shows (`B1808`)
# ----------------------------------------------------------------------
# `core.comprehensive_web_search` gave each fetched page its first 3000
# characters, whatever was asked, so an answer in a page's fourth screen never
# reached the model — on every search path, local endpoints included. `B1403`
# measured the same failure for `web_fetch`. `search_excerpt` spends the same
# budget on the page's opening and the passages that carry the query's own
# words, cut from the text as it stands and kept in order. After upstream
# Odysseus 31e03c9e's `search_excerpt`, with this file's `subject_terms` in
# place of its own word list (`Law 7`), and a marker only where text is left
# out (`Law 10`).
_EXCERPT_MARKER = "\n[...text omitted; web_fetch the source for the full page...]\n"
# `site:` and `filetype:` are operators for the engine, not words on the page.
_EXCERPT_OPERATORS = re.compile(r"(?<!\S)-?(?:site|filetype):\S+", re.I)
_EXCERPT_LEAD = 240     # the opening every excerpt keeps: scope, date, byline
_EXCERPT_FLOOR = 200    # a budget below this is only ever a prefix
_EXCERPT_TRIES = 24     # terms used, and passages tried around each term
# `B1806`. A second passage narrower than this is mostly its own marker: a
# page shared down to ~300 characters got two 37-character passages and three
# markers, so a small budget is spent on one passage.
_EXCERPT_PASSAGE = 200


def _excerpt_prefix(text: str, limit: int) -> str:
    """``text`` cut to ``limit`` at the last space, when there is one near."""
    cut = text.rfind(" ", 0, limit)
    return text[:cut] if cut > limit // 2 else text[:limit]


def search_excerpt(text: str, query: str, max_chars: int) -> str:
    """At most ``max_chars`` of ``text``: its opening and the passages ``query`` asks about.

    Text that fits is returned unchanged; text in which no term of the query
    appears is its opening and one marker. Otherwise up to two passages are
    chosen, each for the query words it holds (a rare word counts for more than
    a common one), and a second only when it holds a word the first does not.
    One passage alone is grown to the whole budget, backward when it reaches
    the end of the page. Every passage is the page's own text, in page order,
    so a qualifier or a negation inside one is kept, and the marker stands
    wherever text is left out and nowhere else.
    """
    if len(text) <= max_chars:
        return text
    if max_chars < _EXCERPT_FLOOR:
        return text[:max_chars]
    marker = _EXCERPT_MARKER
    words = _EXCERPT_OPERATORS.sub(" ", query) if isinstance(query, str) else ""
    # A number or a single letter is a word of the query but a poor place to
    # look: it matches every date, price and list item on the page, and a
    # links block naming the year outscored the article that answers.
    terms = [t for t in subject_terms(words)
             if len(t) > 1 and not t.isdigit()][:_EXCERPT_TRIES]
    # The page's words, read once and tokenised as `subject_terms` tokenises the
    # query, so a match is a whole word and a 2 MB page costs one pass however
    # many terms there are.
    index = {t: i for i, t in enumerate(terms)}
    found = [[] for _t in terms]
    if index:
        for m in re.finditer(r"\w+", text):
            i = index.get(m.group(0).lower())
            if i is not None:
                found[i].append((m.start(), m.end()))
    if not any(found):
        return _excerpt_prefix(text, max_chars - len(marker)) + marker
    starts = [[s for s, _e in hits] for hits in found]
    weights = [1 / (1 + math.log1p(len(hits))) for hits in found]

    def held(start, end):
        """The terms with a match wholly inside ``text[start:end]``."""
        out = set()
        for i, hits in enumerate(found):
            j = bisect_left(starts[i], start)
            if j < len(hits) and hits[j][1] <= end:
                out.add(i)
        return out

    def word_start(at, floor):
        """``at``, or the next word's start when it falls inside one; never before ``floor``."""
        if at <= floor:
            return floor
        if text[at - 1].isspace():
            return at
        space = text.find(" ", at, min(len(text), at + 60))
        return space + 1 if space >= 0 else at

    def word_end(start, end):
        if end >= len(text):
            return len(text)
        space = text.rfind(" ", start, end)
        return space if space > start else end

    lead_end = min(_EXCERPT_LEAD, max_chars // 5)
    space = text.rfind(" ", 0, lead_end)
    if space > 0:
        lead_end = space
    room = max_chars - lead_end - 2 * len(marker)       # for one passage
    width = (max_chars - lead_end - 3 * len(marker)) // 2  # for each of two
    passages = 2 if width >= _EXCERPT_PASSAGE else 1
    if passages == 1:
        width = max(1, room)
    candidates = {}
    for hits in found:
        for at, _e in hits[:_EXCERPT_TRIES]:
            start = word_start(max(lead_end, min(len(text) - width, at - width // 3)), lead_end)
            end = word_end(start, min(len(text), start + width))
            if end > start:
                hit = held(start, end)
                candidates[(start, end)] = (sum(weights[i] for i in hit), hit)

    chosen, covered = [], set()
    for (start, end), (score, hit) in sorted(candidates.items(),
                                             key=lambda kv: (-kv[1][0], kv[0][0])):
        if score <= 0 or any(start < b and end > a for a, b in chosen):
            continue
        if chosen and not hit - covered:
            continue
        chosen.append((start, end))
        covered |= hit
        if len(chosen) == passages:
            break
    if not chosen:
        # The query's words are in the opening alone: the opening is the passage.
        return _excerpt_prefix(text, max_chars - len(marker)) + marker
    if len(chosen) == 1:
        # Spend the budget on one passage's context rather than a weaker second
        # one, and when the passage meets the end of the page, grow it backward:
        # it used to stop there with a third of the budget unspent.
        start, _end = chosen[0]
        end = word_end(start, min(len(text), start + room))
        if end == len(text) and end - start < room:
            start = word_start(max(lead_end, end - room), lead_end)
        chosen = [(start, end)]

    # What is skipped between two passages, or after the last, is kept when it
    # is no longer than the marker that would stand for it: then nothing is
    # left out there, and the marker would say something was.
    spans = [(0, lead_end)]
    for start, end in sorted(chosen):
        if start - spans[-1][1] <= len(marker):
            spans[-1] = (spans[-1][0], max(spans[-1][1], end))
        else:
            spans.append((start, end))
    if len(text) - spans[-1][1] <= len(marker):
        spans[-1] = (spans[-1][0], len(text))
    out = marker.join(text[a:b] for a, b in spans)
    if spans[-1][1] < len(text):
        out += marker
    return out[:max_chars]


# How much of a fetched page the verdict reads. A long page mentions a lot of
# words, and the question is whether it is *about* the query, so the window is
# the head of the document — title, lede and first screens, where an article
# says what it is. The same 3000 characters `core.py` gives each page in the
# block, where since `B1808` they go to the passages the query asks about.
_CONTENT_WINDOW = 3000


def _fetched_text_by_url(fetched) -> dict:
    """``{url: page text}`` from `comprehensive_web_search`'s fetched rows.

    Tolerant by construction: this is called from the output path of a search,
    and a malformed row must cost its own evidence and nothing else.
    """
    out = {}
    if not isinstance(fetched, (list, tuple)):
        return out
    for row in fetched:
        if not isinstance(row, dict):
            continue
        url = row.get("url")
        body = row.get("content")
        if isinstance(url, str) and isinstance(body, str) and body:
            out[url] = body[:_CONTENT_WINDOW].lower()
    return out


def relevance_report(query: str, results, fetched=None) -> dict:
    """Measure how well ``results`` match ``query``. Never raises.

    Returns ``{"verdict", "best_coverage", "matched", "terms", "missing"}``:

      * ``verdict``   one of `RELEVANCE_VERDICTS`.
      * ``best_coverage``  the best single result's share of the subject terms,
        0.0-1.0, because the model reads the best result rather than the mean.
      * ``matched`` / ``terms``  that share as the integers behind it, so the
        block can print *"1 of 9"* rather than an adjective (`Law 5`).
      * ``missing``  subject terms that appear in **no** result — the most
        useful line of the lot. For the owner's search it is
        `school, runescape, fractured, archive, raid, details, 20th`: six of the
        nine words that made it a question about a video game were in none of
        the five results, and nothing said so.

    ``fetched`` is `comprehensive_web_search`'s fetched-page rows. **Each
    result is measured on the better of its two readings** — its fetched page
    text, and its title plus snippet — because either can be the poorer
    evidence and neither is reliably the richer.

    Why the page text is read at all: SearXNG's parse is
    ``"snippet": r.get("content", "")`` and a good many of its engines return
    no content, so a snippet-only verdict called three genuinely on-topic pages
    a miss. Measured — the OSRS wiki, the Jagex news post and the game's own
    front page, with empty snippets, scored **2 of 9** and the block told the
    model *"these results do not match the query"* while handing it three pages
    that answered it. That is the owner's defect with the signs reversed, and
    the content was assembled forty lines above this call and unused.

    Why the snippet is still read: `content.py` extracts boilerplate from a
    good many real pages — it carries a `THIN_CONTENT_CHARS` fallback for
    exactly that — so reading the page *instead of* the snippet made things
    worse, not better. Measured on the first pass of this change: two results
    whose titles and snippets carry all nine of the owner's query terms scored
    **0 of 9, verdict `none`** as soon as their bodies came back as a cookie
    notice. Taking the better of the two cannot score a result below what it
    scored before, and off-topic content still does not rescue a bad match,
    because in that case the snippet is off-topic too.

    `rank_search_results` has always computed a per-result score and returned
    bare rows, discarding it one line before the output was built. This is that
    measurement, kept.
    """
    terms = subject_terms(query)
    rows = [r for r in (results or []) if isinstance(r, dict)]
    if not terms or not rows:
        return {
            "verdict": "none",
            "best_coverage": 0.0,
            "matched": 0,
            "terms": len(terms),
            "missing": list(terms),
        }

    bodies = _fetched_text_by_url(fetched)
    best_hits = 0
    covered_anywhere = set()
    for row in rows:
        # One result, two readings, and the result scores the better of them —
        # so "the closest result matches N of M" is still a statement about one
        # result, and neither a missing snippet nor a boilerplate page can drag
        # it below what the other reading already proved.
        readings = [_result_text(row)]
        body = bodies.get(row.get("url"))
        if body:
            readings.append(body)
        row_best = []
        for text in readings:
            hits = [t for t in terms if _has_word(text, t)]
            covered_anywhere.update(hits)
            if len(hits) > len(row_best):
                row_best = hits
        best_hits = max(best_hits, len(row_best))

    coverage = best_hits / len(terms)
    if coverage >= _STRONG_COVERAGE:
        verdict = "strong"
    elif coverage >= _PARTIAL_COVERAGE:
        verdict = "partial"
    elif best_hits > 0:
        verdict = "weak"
    else:
        verdict = "none"

    return {
        "verdict": verdict,
        "best_coverage": coverage,
        "matched": best_hits,
        "terms": len(terms),
        "missing": [t for t in terms if t not in covered_anywhere],
    }
