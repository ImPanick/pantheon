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
