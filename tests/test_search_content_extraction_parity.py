# SPDX-License-Identifier: AGPL-3.0-or-later
"""Content extraction behavior for the canonical services.search.content module."""

import httpx
import pytest

pytest.importorskip("bs4")

from services.search import content as service_content


class _FakeResponse:
    status_code = 200
    headers = {"Content-Type": "text/html; charset=utf-8"}
    content = b""

    def __init__(self, text: str):
        self.text = text

    def raise_for_status(self):
        return None


class _FakeErrorResponse:
    """Mimics an httpx.Response that fails raise_for_status with a given status code."""

    headers = {"Content-Type": "text/html; charset=utf-8"}
    content = b""
    text = ""

    def __init__(self, status_code: int):
        self.status_code = status_code

    def raise_for_status(self):
        raise httpx.HTTPStatusError(
            f"{self.status_code} error", request=None, response=self
        )


@pytest.mark.parametrize("module", [service_content])
def test_content_fetcher_extracts_og_image_and_body_fallback(module, tmp_path, monkeypatch):
    html = """
    <html>
      <head>
        <title>Example</title>
        <meta property="og:image" content="https://example.com/cover.jpg">
      </head>
      <body>
        <nav>Navigation text should not win</nav>
        <div class="content">Tiny</div>
        <main>
          <p>This is the substantive body text that should be retained.</p>
          <p>It is much longer than the tiny class-matched wrapper.</p>
        </main>
        <script>window.secret = "not content";</script>
      </body>
    </html>
    """

    monkeypatch.setattr(module, "CONTENT_CACHE_DIR", tmp_path)
    module.content_cache_index.clear()
    monkeypatch.setattr(module, "_get_public_url", lambda url, headers, timeout, **kwargs: _FakeResponse(html))

    result = module.fetch_webpage_content("https://example.com/parity-test")

    assert result["og_image"] == "https://example.com/cover.jpg"
    assert "substantive body text" in result["content"]
    assert "much longer than the tiny" in result["content"]
    assert "window.secret" not in result["content"]


@pytest.mark.parametrize("status_code", [403, 404])
def test_fetch_webpage_content_returns_empty_result_on_http_status_error(status_code, tmp_path, monkeypatch):
    """A 403/404 response should degrade to an empty result instead of raising.

    This exercises the real fetch_webpage_content() path: _get_public_url returns
    a response whose raise_for_status() raises httpx.HTTPStatusError, and the
    function must catch it and hand back the standard empty-result shape rather
    than letting the exception bubble up (which previously surfaced as a 500).
    """
    monkeypatch.setattr(service_content, "CONTENT_CACHE_DIR", tmp_path)
    service_content.content_cache_index.clear()
    monkeypatch.setattr(
        service_content,
        "_get_public_url",
        lambda url, headers, timeout, **kwargs: _FakeErrorResponse(status_code),
    )

    result = service_content.fetch_webpage_content(f"https://example.com/status-{status_code}")

    assert result["success"] is False
    assert result["content"] == ""
    assert str(status_code) in result["error"]


def test_fetch_webpage_content_429_takes_distinct_rate_limit_path(tmp_path, monkeypatch):
    """A 429 response must be handled by the dedicated rate-limit branch.

    The status_code == 429 check runs before raise_for_status() is ever called,
    so a 429 should be reported as a rate-limit error rather than falling through
    the generic HTTPStatusError handling added for 403/404. We assert on the
    error message to prove it took the RateLimitError path, not the HTTP-status
    empty-result path.
    """
    monkeypatch.setattr(service_content, "CONTENT_CACHE_DIR", tmp_path)
    service_content.content_cache_index.clear()

    raise_for_status_called = False

    class _FakeRateLimitResponse:
        status_code = 429
        headers = {"Content-Type": "text/html; charset=utf-8"}
        content = b""
        text = ""

        def raise_for_status(self):
            nonlocal raise_for_status_called
            raise_for_status_called = True

    monkeypatch.setattr(
        service_content,
        "_get_public_url",
        lambda url, headers, timeout, **kwargs: _FakeRateLimitResponse(),
    )

    result = service_content.fetch_webpage_content("https://example.com/rate-limited")

    assert result["success"] is False
    assert result["content"] == ""
    assert "Rate limit hit" in result["error"]
    assert "HTTP 429" not in result["error"]
    # The 429 short-circuit must happen before raise_for_status() is reached.
    assert raise_for_status_called is False


# `B1799`. A bot-protection interstitial served with a 2xx status went through
# the HTML branch and came back as the page, `success` True, so a search counted
# the source as fetched and handed the model the challenge text as evidence.
# Cloudflare's own challenge is a 403 and already failed before extraction; the
# case this exists for is Fastly's "Client Challenge" (PyPI), a 200. Ported from
# upstream Odysseus 7a11de9c, naming Pantheon's `agent_browser`.
@pytest.mark.parametrize('title,body,blocked', [
    ('Client Challenge', 'A required part of this site couldn’t load. Try using a different browser.', True),
    ('Just a moment...', 'Checking your browser. Enable JavaScript to continue.', True),
    ('Understanding browser challenges', 'Checking your browser is a common security message.', False),
    ('Client Challenge', 'An article about designing client challenges for a programming exercise.', False),
    ('Client Challenge', 'A required part of this site ' + 'substantive discussion ' * 150, False),
], ids=['client-challenge', 'just-a-moment', 'an-article-on-challenges', 'an-article-titled-so',
        'a-long-page-titled-so'])
def test_access_interstitial_is_not_article_evidence(title, body, blocked, tmp_path, monkeypatch):
    monkeypatch.setattr(service_content, 'CONTENT_CACHE_DIR', tmp_path)
    html = f'<html><title>{title}</title><body><main>{body}</main></body></html>'
    monkeypatch.setattr(service_content, '_get_public_url', lambda *a, **k: _FakeResponse(html))
    result = service_content.fetch_webpage_content('https://example.com/challenge')
    assert result['success'] is not blocked
    if blocked:
        assert result['content'] == ''
        assert result['error_kind'] == 'access_challenge'
        assert 'agent_browser' in result['error']
        assert not list(tmp_path.iterdir()), 'Transient challenge must not be cached as article content'
    else:
        assert body.strip() in result['content']


# The page PyPI's Fastly front serves a client it scores as a bot, with HTTP 200.
FASTLY_CHALLENGE = """<!DOCTYPE html>
<html lang="en"><head><title>Client Challenge</title>
<style>#loading-error { font-size: 16px; }</style></head>
<body>
<noscript><div class="noscript">Please enable JavaScript to proceed.</div></noscript>
<div id="loading-error" class="loading-error" role="alert" style="display: none;">A required part
of this site couldn’t load. This may be due to a browser extension, network issues, or browser
settings. Please check your connection, disable any ad blockers, or try using a different
browser.</div>
<script src="/_fs-ch-1T1wmsGaOgGaSxcX/script.js?reload=true"></script>
</body></html>"""


def test_a_challenge_page_served_with_200_is_a_fetch_failure(tmp_path, monkeypatch):
    """Fastly's page as it arrives: the fetch fails and says why, keeps the
    title it saw, caches nothing — and the model's `web_fetch` reads the
    failure, not the challenge text as the page."""
    import asyncio
    import json
    from src.agent_tools.web_tools import WebFetchTool

    monkeypatch.setattr(service_content, 'CONTENT_CACHE_DIR', tmp_path)
    service_content.content_cache_index.clear()
    monkeypatch.setattr(service_content, '_get_public_url',
                        lambda *a, **k: _FakeResponse(FASTLY_CHALLENGE))

    result = service_content.fetch_webpage_content('https://pypi.org/project/requests/')
    assert result['success'] is False
    assert result['content'] == ''
    assert result['title'] == 'Client Challenge'
    assert result['error'].startswith('Page access challenge')
    assert not list(tmp_path.iterdir())

    out = asyncio.run(WebFetchTool().execute(
        json.dumps({'url': 'https://pypi.org/project/requests/'}), ctx={}))
    assert out['exit_code'] == 1
    assert 'Page access challenge' in out['error']
    assert 'couldn’t load' not in out.get('output', '')


# `B1807`. The text heuristic took every `main`, `article`, `section` and `div`
# whose class says content, and their wrappers with them, in document order,
# and joined the first three. A WordPress post sits in `div.site-content >
# div.content-area > main.site-main > article`, so it came back three times
# with the sidebar inside the first copy, and a Wikipedia article three times
# over. That spent `web_fetch`'s budget and deep research's on repeats, and
# the "this page is N characters" notice counted them. Now `<main>` (or
# `role="main"`) is the page's text, then its `<article>`s, then the class
# heuristic; an area inside another is read once, with its parent; navigation,
# footers and sidebars are dropped first, but an aside inside an article (a
# docs callout) is kept, and a thin result still falls back to the whole body.
# After upstream Odysseus cfb9315e, whose nested-wrapper case is kept.
def _fetch_html(monkeypatch, tmp_path, html, url):
    monkeypatch.setattr(service_content, "CONTENT_CACHE_DIR", tmp_path)
    service_content.content_cache_index.clear()
    monkeypatch.setattr(service_content, "_get_public_url", lambda *a, **k: _FakeResponse(html))
    return service_content.fetch_webpage_content(url)


def _sentences(tag, n=20):
    return " ".join(f"{tag} sentence {i:02d} says something of substance." for i in range(n))


@pytest.mark.parametrize("wrapper", ["main", "article", 'div class="content"'])
def test_a_page_nested_in_content_wrappers_is_read_once_without_its_navigation(
        wrapper, tmp_path, monkeypatch):
    closing = wrapper.split()[0]
    html = (f'<html><body><nav>{"Navigation item " * 100}</nav><{wrapper}>'
            '<header>Article title and publication date</header>'
            '<div class="article-body"><div class="entry-content">'
            '<p>Unique substantive evidence.</p></div></div>'
            f'</{closing}><footer>Unrelated links</footer></body></html>')
    result = _fetch_html(monkeypatch, tmp_path, html, "https://example.com/nested")
    assert result["content"].count("Unique substantive evidence.") == 1
    assert "Navigation item" not in result["content"]
    assert "Unrelated links" not in result["content"]
    assert "Article title" in result["content"]


WORDPRESS_POST = f"""<html><head><title>A post</title></head><body>
<div id="page" class="site">
 <header class="site-header"><nav><ul><li>Home</li><li>About</li><li>Contact</li></ul></nav></header>
 <div id="content" class="site-content">
  <div id="primary" class="content-area">
   <main id="main" class="site-main">
    <article class="post type-post">
     <header class="entry-header"><h1>Title of the post</h1></header>
     <div class="entry-content"><p>{_sentences("Post")}</p></div>
    </article>
   </main>
  </div>
  <aside id="secondary" class="widget-area">Recent posts, archives and categories</aside>
 </div>
 <footer id="colophon">Proudly powered by a theme</footer>
</div></body></html>"""


def test_a_wordpress_post_is_read_once_without_its_sidebar(tmp_path, monkeypatch):
    result = _fetch_html(monkeypatch, tmp_path, WORDPRESS_POST, "https://example.com/a-post")
    assert result["content"].count("Post sentence 00") == 1, result["content"][:300]
    assert result["content"].startswith("Title of the post")
    assert "Recent posts" not in result["content"]
    assert "Proudly powered" not in result["content"]
    # The page's lists are still read from the whole page, navigation and all.
    assert ["Home", "About", "Contact"] in result["lists"]


WIKIPEDIA_ARTICLE = f"""<html><head><title>Topic - Wikipedia</title></head><body>
<header class="vector-header"><nav>Main page Contents Current events</nav></header>
<div class="mw-page-container">
 <div class="vector-sidebar" role="navigation">Tools What links here</div>
 <main id="content" class="mw-body">
  <header class="mw-body-header"><h1>Topic</h1></header>
  <div id="bodyContent" class="vector-body">
   <div id="mw-content-text" class="mw-body-content">
    <div class="mw-parser-output"><p>{_sentences("Wiki")}</p></div>
   </div>
  </div>
 </main>
</div></body></html>"""


def test_a_wikipedia_article_is_read_once_without_its_tools(tmp_path, monkeypatch):
    result = _fetch_html(monkeypatch, tmp_path, WIKIPEDIA_ARTICLE, "https://example.org/wiki/Topic")
    assert result["content"].count("Wiki sentence 00") == 1, result["content"][:300]
    assert "Tools What links here" not in result["content"]
    assert "Main page Contents" not in result["content"]


def test_a_thin_main_beside_the_article_still_yields_the_article(tmp_path, monkeypatch):
    """A `<main>` holding only a headline and a standfirst, with the story in
    a sibling `div.content`: the thin result falls back to the body, so both
    are read. Upstream's version skipped the fallback wherever a `<main>` was
    found, and gave the headline alone."""
    html = (f'<html><head><title>T</title></head><body>'
            f'<main><h1>Headline</h1><p>The standfirst says what the story is.</p></main>'
            f'<div class="content"><p>{_sentences("Story")}</p></div></body></html>')
    result = _fetch_html(monkeypatch, tmp_path, html, "https://example.com/thin-main")
    assert result["content"].count("Story sentence 00") == 1
    assert "The standfirst says what the story is." in result["content"]


def test_a_callout_inside_an_article_is_kept_once(tmp_path, monkeypatch):
    """A docs page's `<aside class="caution">` is part of the article; the
    sidebar `<aside>` beside the article is not."""
    html = (f'<html><head><title>API guide</title></head><body>'
            f'<main role="main" class="devsite-main-content">'
            f'<article class="devsite-article"><h1>API guide</h1><p>{_sentences("Doc", 10)}</p>'
            f'<aside class="caution">Caution: this method is deprecated; do not use it in new code.</aside>'
            f'<p>{_sentences("Tail", 5)}</p></article></main>'
            f'<aside class="devsite-sidebar">Related guides</aside></body></html>')
    result = _fetch_html(monkeypatch, tmp_path, html, "https://example.com/api-guide")
    assert result["content"].count("this method is deprecated") == 1, result["content"][:300]
    assert result["content"].count("Doc sentence 00") == 1
    assert "Tail sentence 04" in result["content"]
    assert "Related guides" not in result["content"]
