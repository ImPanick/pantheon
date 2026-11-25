# SPDX-License-Identifier: AGPL-3.0-or-later
"""`B2177`: every "is this host local?" check reads `src/local_hosts.py`, and
each still answers as it did — except the refusing checks, which now refuse
the union of what any of them refused.

The rule (`D-2026-11-24-02`, the owner's "delete duplicates"): a set that
*allows* something must not widen, and a set that *refuses* something must not
narrow. `ANSWERS` is every call site's answer for every probe host, taken on
`ba5c65c4` and kept; `NEWLY_REFUSED` lists each refusing site's additions,
which are the only answers that moved. DNS is stubbed to a public address so
only the name checks are measured.
"""

from __future__ import annotations

import ast
import ipaddress
from pathlib import Path

import pytest

REPO = Path(__file__).resolve().parents[1]

PROBES = (
    "localhost", "127.0.0.1", "::1", "0.0.0.0", "::", "host.docker.internal",
    "gateway.docker.internal", "127.0.0.2", "10.0.0.1", "100.64.0.1", "foo.local", "nas.lan",
    "box.home", "x.test", "example.com", "ip6-localhost", "ip6-loopback", "localhost.",
    "a.localhost", "metadata", "metadata.google.internal", "ollama",
)
PUBLIC = [ipaddress.ip_address("93.184.216.34")]


def _url(host: str, rest: str = "") -> str:
    return f"http://[{host}]:1234{rest}" if ":" in host else f"http://{host}:1234{rest}"


def _refuses(fn) -> bool:
    try:
        fn()
    except Exception:
        return True
    return False


def _sites(monkeypatch) -> dict:
    """Each call site, as a function of the host."""
    from routes import model_routes
    from src import (caldav_sync, chat_helpers, endpoint_resolver, llm_core, mail_reach,
                     model_context, outbound_fetch, rate_limiter, url_security, vault,
                     webhook_manager)
    from src.agents import evals

    monkeypatch.setattr(webhook_manager, "_resolve_hostname_ips", lambda h: PUBLIC)
    monkeypatch.setattr(caldav_sync, "_resolve_caldav_host_ips", lambda h: PUBLIC)
    monkeypatch.setattr(url_security, "_resolve_hostname_ips", lambda h: PUBLIC)
    monkeypatch.setattr(outbound_fetch, "lan_allowed", lambda: False)
    monkeypatch.setattr(model_context, "_configured_endpoint_kind", lambda url: None)
    monkeypatch.setattr(model_routes, "_docker_host_gateway_reachable", lambda: True)
    monkeypatch.delenv("PANTHEON_ALLOW_PRIVATE_CALDAV", raising=False)
    resolver = lambda h: PUBLIC  # noqa: E731
    return {
        # allowing (local is free / probed / unpaced / plain http)
        "endpoint_resolver.endpoint_cost_tracked":
            lambda h: endpoint_resolver.endpoint_cost_tracked(_url(h, "/v1")),
        "endpoint_resolver.build_models_url":
            lambda h: endpoint_resolver.build_models_url(_url(h)).endswith("/v1/models"),
        "llm_core._is_ollama_native_url": lambda h: llm_core._is_ollama_native_url(_url(h, "/api/tags")),
        "llm_core._is_ollama_openai_compat_url":
            lambda h: llm_core._is_ollama_openai_compat_url(_url(h, "/v1")),
        "llm_core._provider_label": lambda h: llm_core._provider_label(_url(h, "/v1")) == "local endpoint",
        "chat_helpers._is_local_host": lambda h: chat_helpers._is_local_host(h),
        "model_context.is_local_endpoint": lambda h: model_context.is_local_endpoint(_url(h, "/v1")),
        "model_routes._classify_endpoint": lambda h: model_routes._classify_endpoint(_url(h, "/v1")),
        "model_routes._rewrite_loopback_for_docker":
            lambda h: model_routes._rewrite_loopback_for_docker(_url(h, "/v1")) != _url(h, "/v1"),
        "rate_limiter.host_is_local": lambda h: rate_limiter.host_is_local(h),
        "vault._is_local_host": lambda h: vault._is_local_host(h),
        # refusing (SSRF guards, the eval world's loopback wall)
        "evals._is_loopback": lambda h: evals._is_loopback(_url(h, "/x"), "http://pantheon:1234"),
        "webhook_manager._is_private_url": lambda h: webhook_manager._is_private_url(_url(h, "/hook")),
        "caldav_sync.validate_caldav_url":
            lambda h: _refuses(lambda: caldav_sync.validate_caldav_url(_url(h, "/dav"))),
        "url_security._host_resolves_publicly": lambda h: not url_security._host_resolves_publicly(h),
        "outbound_fetch._public_http_url":
            lambda h: not outbound_fetch._public_http_url(_url(h), resolver=resolver),
        "outbound_fetch._resolve_public_ips":
            lambda h: _refuses(lambda: outbound_fetch._resolve_public_ips(_url(h), resolver=resolver)),
        "mail_reach._typed_refusal":
            lambda h: mail_reach._typed_refusal(h, 993, mail_reach.LAN)[2] is not None,
    }


REFUSING = {"evals._is_loopback", "webhook_manager._is_private_url", "caldav_sync.validate_caldav_url",
            "url_security._host_resolves_publicly", "outbound_fetch._public_http_url",
            "outbound_fetch._resolve_public_ips", "mail_reach._typed_refusal"}

# Each site's answer per probe on `ba5c65c4`, as the probe hosts that answered
# True (or, for `_classify_endpoint`, "local").
ANSWERS: dict[str, set[str]] = {
    'caldav_sync.validate_caldav_url': {'0.0.0.0', '10.0.0.1', '127.0.0.1', '127.0.0.2', '::', '::1', 'a.localhost', 'ip6-localhost', 'localhost', 'localhost.', 'metadata.google.internal'},
    'chat_helpers._is_local_host': {'0.0.0.0', '10.0.0.1', '100.64.0.1', '127.0.0.1', '127.0.0.2', '::', '::1', 'foo.local', 'host.docker.internal', 'ip6-localhost', 'ip6-loopback', 'localhost', 'metadata', 'ollama'},
    'endpoint_resolver.build_models_url': {'host.docker.internal'},
    'endpoint_resolver.endpoint_cost_tracked': {'a.localhost', 'box.home', 'example.com', 'gateway.docker.internal', 'metadata.google.internal', 'nas.lan', 'x.test'},
    'evals._is_loopback': {'0.0.0.0', '127.0.0.1', '::1', 'localhost'},
    'llm_core._is_ollama_native_url': {'0.0.0.0', '127.0.0.1', '::1', 'localhost'},
    'llm_core._is_ollama_openai_compat_url': {'0.0.0.0', '127.0.0.1', '::1', 'localhost'},
    'llm_core._provider_label': {'0.0.0.0', '127.0.0.1', '::1', 'localhost'},
    'mail_reach._typed_refusal': {'0.0.0.0', '127.0.0.1', '127.0.0.2', '::', '::1', 'a.localhost', 'ip6-localhost', 'ip6-loopback', 'localhost', 'localhost.', 'metadata', 'metadata.google.internal'},
    'model_context.is_local_endpoint': {'0.0.0.0', '10.0.0.1', '100.64.0.1', '127.0.0.1', '::1', 'host.docker.internal', 'localhost'},
    'model_routes._classify_endpoint': {'0.0.0.0', '10.0.0.1', '100.64.0.1', '127.0.0.1', '::1', 'localhost'},
    'model_routes._rewrite_loopback_for_docker': {'0.0.0.0', '127.0.0.1', '::', '::1', 'localhost'},
    'outbound_fetch._public_http_url': {'0.0.0.0', '10.0.0.1', '100.64.0.1', '127.0.0.1', '127.0.0.2', '::', '::1', 'a.localhost', 'localhost', 'metadata', 'metadata.google.internal'},
    'outbound_fetch._resolve_public_ips': {'0.0.0.0', '10.0.0.1', '100.64.0.1', '127.0.0.1', '127.0.0.2', '::', '::1', 'localhost', 'metadata', 'metadata.google.internal'},
    'rate_limiter.host_is_local': {'0.0.0.0', '10.0.0.1', '100.64.0.1', '127.0.0.1', '127.0.0.2', '::', '::1', 'foo.local', 'gateway.docker.internal', 'host.docker.internal', 'ip6-localhost', 'ip6-loopback', 'localhost', 'metadata', 'metadata.google.internal', 'nas.lan', 'ollama'},
    'url_security._host_resolves_publicly': {'0.0.0.0', '10.0.0.1', '100.64.0.1', '127.0.0.1', '127.0.0.2', '::', '::1', 'a.localhost', 'foo.local', 'gateway.docker.internal', 'host.docker.internal', 'localhost', 'metadata', 'metadata.google.internal', 'nas.lan'},
    'vault._is_local_host': {'0.0.0.0', '10.0.0.1', '127.0.0.1', '127.0.0.2', '::', '::1', 'box.home', 'foo.local', 'gateway.docker.internal', 'host.docker.internal', 'ip6-localhost', 'ip6-loopback', 'localhost', 'metadata', 'metadata.google.internal', 'nas.lan', 'ollama', 'x.test'},
    'webhook_manager._is_private_url': {'0.0.0.0', '10.0.0.1', '100.64.0.1', '127.0.0.1', '127.0.0.2', '::', '::1', 'a.localhost', 'foo.local', 'gateway.docker.internal', 'host.docker.internal', 'localhost', 'metadata', 'metadata.google.internal', 'nas.lan'},
}
# What the union added: the loopback aliases and metadata names one guard had
# and another lacked, `::` for the eval wall, `.localhost` for the pinned resolve.
NEWLY_REFUSED: dict[str, set[str]] = {
    'caldav_sync.validate_caldav_url': {'ip6-loopback', 'metadata'},
    'evals._is_loopback': {'::'},
    'outbound_fetch._public_http_url': {'ip6-localhost', 'ip6-loopback', 'localhost.'},
    'outbound_fetch._resolve_public_ips': {'a.localhost', 'ip6-localhost', 'ip6-loopback', 'localhost.'},
    'url_security._host_resolves_publicly': {'ip6-localhost', 'ip6-loopback', 'localhost.'},
    'webhook_manager._is_private_url': {'ip6-localhost', 'ip6-loopback', 'localhost.'},
}


def _measure(monkeypatch) -> dict[str, set[str]]:
    out = {}
    for site, fn in _sites(monkeypatch).items():
        out[site] = {h for h in PROBES if fn(h) in (True, "local")}
    return out


@pytest.mark.parametrize("site", sorted(ANSWERS))
def test_each_site_answers_as_it_did(monkeypatch, site):
    now = _measure(monkeypatch)[site]
    want = ANSWERS[site] | NEWLY_REFUSED.get(site, set())
    assert now == want, (f"{site}: now also {sorted(now - want)}, no longer {sorted(want - now)}")


def test_no_allowing_site_widens_and_no_refusing_site_narrows():
    for site, added in NEWLY_REFUSED.items():
        assert site in REFUSING, f"{site} allows something; its answers may not move"
        assert not (added & ANSWERS[site]), site


def test_the_local_names_are_written_in_one_module():
    """No module but `src/local_hosts.py` spells a set that holds `localhost`."""
    found = []
    for root in ("src", "routes", "core", "services", "mcp_servers"):
        for path in (REPO / root).rglob("*.py"):
            rel = path.relative_to(REPO).as_posix()
            if rel == "src/local_hosts.py":
                continue
            for node in ast.walk(ast.parse(path.read_text(encoding="utf-8"))):
                if isinstance(node, (ast.Set, ast.Tuple, ast.List)) and any(
                        isinstance(e, ast.Constant) and e.value == "localhost" for e in node.elts):
                    found.append((rel, ast.unparse(node)))
    assert sorted(found) == sorted(KEPT_ELSEWHERE), found


# Spelled in place on purpose: each reads a word the person or the agent typed
# ("local", "this machine") to choose running here over SSH, a default, or a
# hint — not whether an address is this machine. Folding them into a host set
# would change what they do (`::1` would run a command here instead of over
# SSH), so they stay.
KEPT_ELSEWHERE = [
    ("src/builtin_actions.py", "('localhost', '127.0.0.1', 'local')"),
    ("src/builtin_actions.py", "('', 'localhost', '127.0.0.1', 'local')"),
    ("src/tools/cookbook.py", "('local', 'localhost', 'this machine', 'here')"),
    ("src/tools/cookbook.py", "('localhost', True)"),
    ("routes/auth_routes.py", "('127.0.0.1', 'localhost')"),
    ("routes/cookbook_routes.py", "('local', 'localhost')"),
]
