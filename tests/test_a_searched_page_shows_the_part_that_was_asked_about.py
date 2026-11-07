# SPDX-License-Identifier: AGPL-3.0-or-later
"""`B1808`. A searched page showed its first 3,000 characters, whatever was asked.

`comprehensive_web_search` gave every fetched page the opening 3,000
characters of its text and `... [truncated]`, so a page that answered the
question in its fourth screen reached the model without the answer. That held
on every search path, local endpoints included, where no other cap applies.
`B1403` measured the same failure for `web_fetch`: the section asked about
fell past the cut, and the model invented it and called it sourced.

Now each page shows its opening (where a page says its scope and date) and the
passages that carry the query's own words, `ranking.subject_terms`, cut from
the text as it stands and kept in order. A marker stands where text is left
out, and only there.

Ported from upstream Odysseus 31e03c9e, whose five cases are kept with the
import changed. Its helper is re-implemented: the terms are Pantheon's
`subject_terms` rather than a list of its own, two passages that touch are one
passage (upstream printed the marker between the opening and a passage that
began where the opening ended), and a passage that ends at the end of the page
grows backward to use its budget.
"""
import pytest

from services.search import core
from services.search.ranking import search_excerpt

from tests.test_a_search_sends_the_persons_words import offline  # noqa: F401  (fixture)

MARKER = "text omitted"


# ----------------------------------------------------------------------
# Upstream's cases
# ----------------------------------------------------------------------
def test_late_relevant_passage_survives_budget_and_preserves_negation():
    text = ('Archived overview; check current documentation. ' + 'Browser navigation and features. ' * 180
            + 'Privacy Guide does not block every tracker. It explains cookie settings and their limitations. '
            + 'Other unrelated material. ' * 100)
    result = search_excerpt(text, 'browser privacy cookie settings', 1200)
    assert len(result) <= 1200
    assert result.startswith('Archived overview;')
    assert 'Privacy Guide does not block every tracker.' in result
    assert MARKER in result


def test_short_evidence_is_not_modified():
    text = 'A small complete source.'
    assert search_excerpt(text, 'source', 500) == text


def test_no_match_uses_bounded_explicitly_incomplete_opening():
    result = search_excerpt('Other material. ' * 300, 'privacy', 500)
    assert len(result) <= 500
    assert result.startswith('Other material.')
    assert MARKER in result


def test_distinct_topics_retain_original_order_and_literal_text():
    text = ('Introduction. ' + 'Filler. ' * 100 + 'Alpha evidence is limited. ' + 'Filler. ' * 200
            + 'Beta evidence is preliminary. ' + 'Filler. ' * 200)
    result = search_excerpt(text, 'alpha beta', 1000)
    assert 'Alpha evidence is limited.' in result
    assert 'Beta evidence is preliminary.' in result
    assert result.index('Alpha evidence') < result.index('Beta evidence')


def test_relevant_evidence_survives_both_search_and_observation_caps():
    text = 'Page introduction. ' + 'Navigation and performance features. ' * 180
    text += 'Privacy Guide explains how to choose cookie settings. These do not prevent every form of tracking. '
    text += 'Other features and links. ' * 200
    first = search_excerpt(text, 'browser privacy cookie settings', 3000)
    final = search_excerpt(first, 'browser privacy cookie settings', 1100)
    assert len(final) <= 1100
    assert 'Privacy Guide explains how to choose cookie settings.' in final
    assert 'These do not prevent every form of tracking.' in final


# ----------------------------------------------------------------------
# Where upstream's helper was wrong
# ----------------------------------------------------------------------
def _news_page():
    lead = "Oslo, 3 November. The city council met on Tuesday to decide the tram budget. "
    body = "".join(
        f"Paragraph {i} on the tram budget vote and what the council decided about it. "
        for i in range(60))
    return lead + body + "Related: weather, sport, culture, letters to the editor. " * 5


def test_a_passage_that_begins_where_the_opening_ends_has_no_marker_between():
    """An intro-led page whose query words run through the body: the passage
    picked starts where the opening stops, so nothing was left out there."""
    text = _news_page()
    result = search_excerpt(text, "tram budget council vote", 3000)
    assert len(result) <= 3000
    assert result.count(MARKER) == 1, result[:400]
    body_end = result.index("\n[...")
    assert text.startswith(result[:body_end]), "the excerpt is not the page's own text, in order"
    assert body_end > 2500


def test_a_passage_at_the_end_of_the_page_still_fills_its_budget():
    """The query's words only in a trailing block: the passage there grows
    backward instead of leaving the budget unspent."""
    text = ("Introduction to the site. " + "General material about many things. " * 200
            + "Related reading: the tram budget council vote, in full.")
    result = search_excerpt(text, "tram budget council vote", 3000)
    assert "the tram budget council vote, in full." in result
    assert 2800 <= len(result) <= 3000, len(result)


def test_a_term_found_only_in_the_opening_keeps_the_opening_whole():
    text = "The tram budget passed. " + "Unrelated material follows here. " * 300
    result = search_excerpt(text, "tram budget", 3000)
    assert text.startswith(result[:result.index("\n[...")])
    assert len(result) > 2800


# ----------------------------------------------------------------------
# The block the model reads
# ----------------------------------------------------------------------
def test_the_answer_past_the_opening_3000_characters_reaches_the_block(offline):  # noqa: F811
    """A fetched page answers the question after its first 3,000 characters.
    The block used to carry the opening only."""
    results = [{"title": "Council minutes", "url": "https://example.org/minutes",
                "snippet": "Minutes of the council meeting."}]
    offline.setattr(core, "_call_provider", lambda *a, **k: [dict(r) for r in results])
    page = ("Minutes of the meeting. " + "Apologies, attendance and procedural matters. " * 90
            + "Item 7: the tram budget was approved by 31 votes to 12. "
            + "Any other business and closing remarks. " * 40)
    assert page.index("Item 7") > 3000
    offline.setattr(core, "fetch_webpage_content", lambda url, *a, **k: {
        "url": url, "title": "Council minutes", "content": page, "success": True, "error": ""})

    out = core.comprehensive_web_search("tram budget vote", max_pages=1)

    block = out[out.index("[CONTENT 1]"):out.index("END OF WEB SEARCH RESULTS")]
    assert "Item 7: the tram budget was approved by 31 votes to 12." in block
    assert block.count("Minutes of the meeting.") >= 1
