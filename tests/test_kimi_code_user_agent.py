# SPDX-License-Identifier: AGPL-3.0-or-later
"""`P15-07`, `D-2026-10-26-01` §7 — Kimi Code is sent one honest name.

Kimi Code's subscription endpoint answers only clients naming themselves as one
of the coding agents it lists. Until the owner's ruling Pantheon re-sent a
refused request as `claude-code`, `KimiCLI`, `Kilo-Code`, `Roo-Code` and
`Cursor` in turn. Now it sends `Pantheon/<version>`, once, as everywhere, and a
refusal of that name reaches the person as a sentence saying so and what to use
instead (`D-2026-10-25-03`: nothing evasive).
"""
import json

import pytest

from src import llm_core
from src.constants import APP_VERSION, PANTHEON_USER_AGENT
from src.llm_core import (
    KIMI_CODE_REFUSED,
    KIMI_CODE_USER_AGENT,
    _format_upstream_error,
    _is_kimi_code_access_denied,
    _is_kimi_code_url,
    httpx_get_kimi_aware,
    httpx_post_kimi_aware,
)

KIMI_CHAT_URL = "https://api.kimi.com/coding/v1/chat/completions"
DENIED = '{"error":{"message":"only available for Coding Agents","type":"access_terminated_error"}}'


# `B1022`: the model probes and lookups go through `paced_http` now, so the
# fakes stand in at that seam (`paced_http.get_sync` / `post_sync`) rather
# than at `httpx.get` / `httpx.post`, which those calls no longer use.

class _Resp:
    def __init__(self, status, text="{}"):
        self.status_code = status
        self.content = text.encode()
        self.text = text
        self.request = None


class _FakeStreamResp(_Resp):
    async def aiter_lines(self):
        yield "data: [DONE]"

    async def aread(self):
        return self.content


class _FakeStreamCtx:
    def __init__(self, response):
        self.response = response

    async def __aenter__(self):
        return self.response

    async def __aexit__(self, *args):
        return False


def test_the_name_is_pantheons_own():
    assert KIMI_CODE_USER_AGENT == PANTHEON_USER_AGENT == f"Pantheon/{APP_VERSION}"
    assert not hasattr(llm_core, "KIMI_CODE_USER_AGENTS"), "the list of other products' names is gone"
    src = open(llm_core.__file__, encoding="utf-8").read()
    for borrowed in ("claude-code/", "KimiCLI/", "Kilo-Code/", "Roo-Code/", "Cursor/1"):
        assert borrowed not in src, borrowed


def test_only_kimi_codes_endpoint_is_meant():
    assert _is_kimi_code_url(KIMI_CHAT_URL)
    assert not _is_kimi_code_url("https://api.moonshot.ai/v1/chat/completions")
    assert _is_kimi_code_access_denied(403, DENIED) and not _is_kimi_code_access_denied(401, DENIED)


def test_one_request_with_its_own_name_and_a_refusal_said_in_words(monkeypatch):
    calls = []

    def fake_post(url, headers=None, **kwargs):
        calls.append(headers.get("User-Agent"))
        return _Resp(403, DENIED)

    # `B1022`: the non-streamed model call is `llm_core._post_routed` (routed
    # by a `NO_PROXY` range) rather than `httpx.post`, so the fake stands there.
    monkeypatch.setattr(llm_core, "_post_routed", fake_post)
    r = httpx_post_kimi_aware(KIMI_CHAT_URL, {"Authorization": "Bearer x"}, json={})
    assert calls == [PANTHEON_USER_AGENT], "sent once, never again under another name"
    assert r.status_code == 403
    assert json.loads(r.text)["error"]["message"] == KIMI_CODE_REFUSED
    assert "Moonshot API key" in KIMI_CODE_REFUSED


def test_an_accepted_answer_comes_back_as_it_was(monkeypatch):
    monkeypatch.setattr("src.paced_http.get_sync", lambda url, headers=None, **k: _Resp(200, '{"data":[]}'))
    r = httpx_get_kimi_aware("https://api.kimi.com/coding/v1/models", {})
    assert r.status_code == 200 and r.text == '{"data":[]}'


def test_other_endpoints_are_untouched(monkeypatch):
    seen = []
    # `B1022`: the non-streamed model call is `llm_core._post_routed` (routed
    # by a `NO_PROXY` range) rather than `httpx.post`, so the fake stands there.
    monkeypatch.setattr(llm_core, "_post_routed",
                        lambda url, headers=None, **k: seen.append(dict(headers)) or _Resp(403, DENIED))
    r = httpx_post_kimi_aware("https://api.openai.com/v1/chat/completions", {"A": "b"}, json={})
    assert seen == [{"A": "b"}] and r.text == DENIED


def test_a_streams_refusal_is_the_same_sentence():
    assert _format_upstream_error(403, DENIED, KIMI_CHAT_URL) == KIMI_CODE_REFUSED


@pytest.mark.asyncio
async def test_the_async_post_sends_once_with_its_own_name():
    class FakeClient:
        def __init__(self):
            self.post_user_agents = []

        async def post(self, url, headers=None, **kwargs):
            self.post_user_agents.append(headers.get("User-Agent"))
            return _Resp(200)

        async def get(self, *a, **k):
            raise AssertionError("nothing is probed first any more")

    client = FakeClient()
    r = await llm_core.httpx_post_kimi_aware_async(client, KIMI_CHAT_URL, {"Authorization": "Bearer x"}, json={})
    assert r.status_code == 200 and client.post_user_agents == [PANTHEON_USER_AGENT]


@pytest.mark.asyncio
async def test_the_stream_sends_its_own_name(monkeypatch):
    class FakeClient:
        def __init__(self):
            self.stream_headers = []

        async def get(self, *a, **k):
            raise AssertionError("nothing is probed first any more")

        def stream(self, method, url, **kwargs):
            self.stream_headers.append(kwargs.get("headers") or {})
            return _FakeStreamCtx(_FakeStreamResp(200))

    client = FakeClient()
    monkeypatch.setattr(llm_core, "_get_http_client", lambda: client)
    monkeypatch.setattr(llm_core, "_is_host_dead", lambda url: False)
    monkeypatch.setattr(llm_core, "note_model_activity", lambda *args, **kwargs: None)
    monkeypatch.setattr(llm_core, "_clear_host_dead", lambda *args, **kwargs: None)
    chunks = [c async for c in llm_core.stream_llm(KIMI_CHAT_URL, "kimi-for-coding",
                                                   [{"role": "user", "content": "hi"}],
                                                   headers={"Authorization": "Bearer x"})]
    assert chunks == ["data: [DONE]\n\n"]
    assert client.stream_headers[0]["User-Agent"] == PANTHEON_USER_AGENT
