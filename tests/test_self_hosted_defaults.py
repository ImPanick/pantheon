"""`Law 16` — a fresh install must not reach the public internet.

The owner's directive, 2026-08-31:

    "we drop external dependence. i dont want things that'll may route to
     external services unless the user (or sysadmin) explicitly links it. the
     intent is fully self hosted everything, with options to add cloud providers
     via api in which case the cloud provider being API linked will have
     everything the users subscription allows."

A law nothing enforces is a preference. These are the clauses that can be
checked mechanically: shipped defaults. They deliberately do NOT check that a
*configured* provider is limited -- clause 2 of the law says the opposite, and
capping a provider the user paid for is the mistake `P2` exists to undo.
"""
import os
import sys

import pytest


@pytest.fixture(scope="module")
def defaults():
    from src.settings import DEFAULT_SETTINGS

    return DEFAULT_SETTINGS


def test_no_search_provider_is_contacted_until_one_is_configured(defaults):
    """Shipped as ["duckduckgo"] because it is free and keyless.

    Both true, and neither is the question -- on a native install SearXNG never
    starts, so the primary always failed and every search a user typed left the
    machine, scraped under a spoofed desktop user-agent.
    """
    assert defaults["search_fallback_chain"] == [], (
        f"a search fallback ships on by default: {defaults['search_fallback_chain']}"
    )


def test_a_fresh_install_does_not_install_from_a_package_registry_at_boot():
    """The sharpest case: this fired ~3s after every startup, pre-login."""
    import importlib

    saved = os.environ.pop("PANTHEON_BROWSER_MCP_REQUIRE_CACHE", None)
    try:
        sys.modules.pop("src.builtin_mcp", None)
        mod = importlib.import_module("src.builtin_mcp")
        assert mod.BROWSER_MCP_REQUIRE_CACHE is True, (
            "the default boot path runs `npx -y ...@latest` against the npm registry"
        )
    finally:
        if saved is not None:
            os.environ["PANTHEON_BROWSER_MCP_REQUIRE_CACHE"] = saved
        sys.modules.pop("src.builtin_mcp", None)


@pytest.mark.parametrize("key", [
    "default_endpoint_id", "default_model",
    "task_model", "utility_model", "research_model",
])
def test_no_cloud_provider_is_the_shipped_default_model(defaults, key):
    """Clause 1. A default that points at somebody's cloud is a bug however
    convenient. (These are all "" today -- this pins that they stay so.)"""
    value = str(defaults.get(key, "") or "")
    assert value == "" or "localhost" in value or "127.0.0.1" in value, (
        f"{key} defaults to {value!r}, which is not local"
    )


def test_speech_ships_disabled(defaults):
    """TTS/STT defaults name cloud models; both must ship off."""
    assert defaults["tts_provider"] == "disabled"
    assert defaults["stt_provider"] == "disabled"
    assert defaults["stt_enabled"] is False


def test_env_example_names_no_third_party_host():
    """`.env.example` is what an operator copies. It must not seed egress."""
    import pathlib
    import re

    text = pathlib.Path(__file__).resolve().parent.parent.joinpath(".env.example").read_text(
        encoding="utf-8"
    )
    live = [
        ln.strip() for ln in text.splitlines()
        if ln.strip() and not ln.strip().startswith("#") and "=" in ln
    ]
    offenders = []
    for ln in live:
        value = ln.split("=", 1)[1].strip().strip('"\'')
        for host in re.findall(r"https?://([A-Za-z0-9.-]+)", value):
            if host not in ("localhost", "127.0.0.1", "0.0.0.0", "host.docker.internal"):
                offenders.append(ln)
    assert not offenders, f"uncommented .env.example lines point off-box: {offenders}"


def test_the_law_is_written_down():
    """A law that lives only in a commit message is not a law."""
    import pathlib

    agents = pathlib.Path(__file__).resolve().parent.parent.joinpath(
        ".pantheon/AGENTS.md"
    ).read_text(encoding="utf-8")
    assert "Law 16" in agents
    assert "fully self hosted" in agents, "the owner's own words are not on the law"
