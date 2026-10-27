# SPDX-License-Identifier: AGPL-3.0-or-later
"""Regression coverage for llama-server style /v1 model-list endpoints (#3330)."""

import httpx

from src import endpoint_resolver, llm_core, model_context


# `B1022`: the model probes and lookups go through `paced_http` now, so the
# fakes stand in at that seam (`paced_http.get_sync` / `post_sync`) rather
# than at `httpx.get` / `httpx.post`, which those calls no longer use.

def test_build_models_url_accepts_v1_base_and_chat_url(monkeypatch):
    monkeypatch.setattr(endpoint_resolver, "resolve_url", lambda url: url)

    assert (
        endpoint_resolver.build_models_url("http://127.0.0.1:8080/v1")
        == "http://127.0.0.1:8080/v1/models"
    )
    assert (
        endpoint_resolver.build_models_url("http://127.0.0.1:8080/v1/chat/completions")
        == "http://127.0.0.1:8080/v1/models"
    )


def test_llm_core_list_model_ids_queries_models_for_v1_base(monkeypatch):
    monkeypatch.setattr(endpoint_resolver, "resolve_url", lambda url: url)
    monkeypatch.setattr(llm_core, "_configured_cached_model_ids", lambda url, **kwargs: [])
    seen = []

    def fake_get(url, headers=None, timeout=None, **_kw):
        seen.append(url)
        request = httpx.Request("GET", url)
        return httpx.Response(200, json={"data": [{"id": "qwen3"}]}, request=request)

    monkeypatch.setattr("src.paced_http.get_sync", fake_get)

    assert llm_core.list_model_ids("http://127.0.0.1:8080/v1", timeout=1) == ["qwen3"]
    assert seen == ["http://127.0.0.1:8080/v1/models"]


def test_model_context_queries_models_for_v1_base(monkeypatch):
    monkeypatch.setattr(endpoint_resolver, "resolve_url", lambda url: url)
    seen = []

    def fake_get(url, timeout=None, headers=None, **_kw):
        seen.append(url)
        request = httpx.Request("GET", url)
        if url.endswith("/slots"):
            return httpx.Response(404, request=request)
        return httpx.Response(
            200,
            json={"data": [{"id": "qwen3", "context_length": 32768}]},
            request=request,
        )

    monkeypatch.setattr(model_context.paced_http, "get_sync", fake_get)

    # `B1369`: the basis is `reported`, because this value came out of the
    # endpoint's own `/v1/models` entry rather than the name table — which is
    # the distinction the third element exists to make.
    assert model_context._query_context_length("http://127.0.0.1:8080/v1", "qwen3") == (
        32768, True, model_context.BASIS_REPORTED)
    assert seen == [
        "http://127.0.0.1:8080/slots",
        "http://127.0.0.1:8080/v1/models",
    ]
