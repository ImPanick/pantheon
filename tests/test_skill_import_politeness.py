# SPDX-License-Identifier: AGPL-3.0-or-later
"""The skill importer must not get its user banned again.

On 2026-08-31 the owner pasted a GitHub link into the skills importer and GitHub
soft-banned his IP. Four things compounded:

  1. no pacing -- a repository tree walked at wire speed;
  2. no authentication -- unauthenticated api.github.com is **60 requests an
     hour**, and the `MAX_FILES = 64` cap counted *files kept*, not requests
     made, so a tree of empty or binary folders cost unbounded API calls while
     the counter never moved;
  3. no `User-Agent` -- every request went out as `python-httpx/x.y`;
  4. a rate limit that was *detected* purely to write "try again in a bit".

These pin all four. They use a fake transport: nothing here touches the network.
"""
import time

import httpx
import pytest

from services.memory import skill_importer
from services.memory.skill_importer import SkillImportError
from src.rate_limiter import OutboundHostLimiter, HostPolicy


PUBLIC = "140.82.121.4"


@pytest.fixture
def calls(monkeypatch):
    """Capture every outbound request without making one."""
    seen = []

    monkeypatch.setattr(skill_importer, "_resolve_and_check_url", lambda url: [PUBLIC])

    class _Client:
        def __init__(self, **kw):
            pass

        def __enter__(self):
            return self

        def __exit__(self, *a):
            return False

        def get(self, url, headers=None):
            seen.append((url, dict(headers or {})))
            return httpx.Response(200, content=b"# hi", request=httpx.Request("GET", url))

    monkeypatch.setattr(skill_importer.httpx, "Client", _Client)
    # Pace at zero so these assert behaviour, not wall-clock.
    monkeypatch.setattr(
        skill_importer, "_request_budget", skill_importer._request_budget
    )
    return seen


def _no_pacing(monkeypatch):
    fast = OutboundHostLimiter({})
    fast._default = HostPolicy(min_interval=0.0, jitter=0.0)
    import src.rate_limiter as rl

    monkeypatch.setattr(rl, "outbound", fast)
    return fast


def test_every_request_identifies_itself(calls, monkeypatch):
    _no_pacing(monkeypatch)
    skill_importer._get_checked("https://raw.githubusercontent.com/o/r/main/SKILL.md")
    assert calls, "no request was made"
    for _url, sent in calls:
        assert sent.get("User-Agent", "").startswith("Pantheon-"), (
            "requests still go out as the default python-httpx bot signature"
        )


def test_a_token_becomes_an_authorization_header(calls, monkeypatch):
    _no_pacing(monkeypatch)
    monkeypatch.setattr(skill_importer, "_github_credentials", lambda: "ghp_example")
    skill_importer._get_checked("https://api.github.com/repos/o/r/contents")
    assert calls[0][1]["Authorization"] == "Bearer ghp_example"


def test_no_token_sends_no_authorization_header(calls, monkeypatch):
    _no_pacing(monkeypatch)
    monkeypatch.setattr(skill_importer, "_github_credentials", lambda: "")
    skill_importer._get_checked("https://api.github.com/repos/o/r/contents")
    assert "Authorization" not in calls[0][1]


def test_the_budget_caps_requests_not_just_files(calls, monkeypatch):
    """The cap that was missing. MAX_FILES counts files kept; this counts calls."""
    _no_pacing(monkeypatch)
    budget = skill_importer._Budget(3, authenticated=False)
    token = skill_importer._request_budget.set(budget)
    try:
        for _ in range(3):
            skill_importer._get_checked("https://api.github.com/repos/o/r/contents")
        with pytest.raises(SkillImportError, match="stopped after 3 requests"):
            skill_importer._get_checked("https://api.github.com/repos/o/r/contents")
    finally:
        skill_importer._request_budget.reset(token)
    assert len(calls) == 3, "a request was made after the budget was spent"


def test_an_unauthenticated_import_gets_the_smaller_budget():
    assert skill_importer.MAX_REQUESTS_UNAUTHENTICATED < 60, (
        "unauthenticated GitHub allows 60 requests an hour; one import must not spend them all"
    )
    assert skill_importer.MAX_REQUESTS_AUTHENTICATED > skill_importer.MAX_REQUESTS_UNAUTHENTICATED


def test_a_rate_limited_host_stops_the_import_with_a_time(monkeypatch):
    """The replacement for 'try again in a bit'."""
    import src.rate_limiter as rl

    lim = OutboundHostLimiter({"api.github.com": HostPolicy(min_interval=0.0, max_wait=1.0)})
    monkeypatch.setattr(rl, "outbound", lim)
    monkeypatch.setattr(skill_importer, "_resolve_and_check_url", lambda url: [PUBLIC])
    lim.observe("api.github.com", 429, {"Retry-After": "900"})

    with pytest.raises(SkillImportError) as caught:
        skill_importer._get_checked("https://api.github.com/repos/o/r/contents")
    msg = str(caught.value)
    assert "minutes" in msg, f"the error must say when: {msg}"
    assert "in a bit" not in msg


def test_a_github_403_rate_limit_reaches_the_limiter(monkeypatch):
    """A 403 is how GitHub says 'rate limit'. It must set a cooldown, not pass by."""
    import src.rate_limiter as rl

    lim = OutboundHostLimiter({"api.github.com": HostPolicy(min_interval=0.0, max_wait=1.0)})
    monkeypatch.setattr(rl, "outbound", lim)
    monkeypatch.setattr(skill_importer, "_resolve_and_check_url", lambda url: [PUBLIC])

    class _Client:
        def __init__(self, **kw):
            pass

        def __enter__(self):
            return self

        def __exit__(self, *a):
            return False

        def get(self, url, headers=None):
            return httpx.Response(
                403,
                headers={
                    "X-RateLimit-Remaining": "0",
                    "X-RateLimit-Reset": str(int(time.time() + 1200)),
                },
                json={"message": "API rate limit exceeded for 1.2.3.4."},
                request=httpx.Request("GET", url),
            )

    monkeypatch.setattr(skill_importer.httpx, "Client", _Client)
    skill_importer._get_checked("https://api.github.com/repos/o/r/contents")
    assert lim.blocked_for("api.github.com") > 900, (
        "a GitHub 403 rate limit did not put the host into cooldown"
    )


def test_an_ordinary_403_does_not_silence_github(monkeypatch):
    """A private repo must not lock the importer out of GitHub for 20 minutes."""
    import src.rate_limiter as rl

    lim = OutboundHostLimiter({"api.github.com": HostPolicy(min_interval=0.0)})
    monkeypatch.setattr(rl, "outbound", lim)
    monkeypatch.setattr(skill_importer, "_resolve_and_check_url", lambda url: [PUBLIC])

    class _Client:
        def __init__(self, **kw):
            pass

        def __enter__(self):
            return self

        def __exit__(self, *a):
            return False

        def get(self, url, headers=None):
            return httpx.Response(403, json={"message": "Not Found"},
                                  request=httpx.Request("GET", url))

    monkeypatch.setattr(skill_importer.httpx, "Client", _Client)
    skill_importer._get_checked("https://api.github.com/repos/o/r/contents")
    assert lim.blocked_for("api.github.com") == 0


def test_a_response_without_headers_does_not_crash_the_error_path():
    """The guard exists so a rate-limit message never becomes a stack trace."""

    class _Bare:
        status_code = 403

        def json(self):
            return {"message": "API rate limit exceeded"}

    err = skill_importer._github_response_error(_Bare())
    assert isinstance(err, SkillImportError)
    assert "rate limit" in str(err).lower()
