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


# ── Law 16 clause 4: the destination is the whole test ────────────────────
#
# Amended by the owner on 2026-08-31: "telemetry is fine, but 'phone home' to an
# external destination is not allowed. if the user wants to establish their own
# telemetry endpoint, they can bypass this law and do so... like Prometheus or
# Grafana." So these do NOT assert that Pantheon collects nothing -- that would
# ban the operator's own Grafana, which is the opposite of what was asked. They
# assert that no destination ships pre-filled.
#
# Armed before the hole exists. `P16-12` will build the first legitimate place
# for an outbound metrics URL, which makes it the first place a well-meant
# default could land -- a "community stats" endpoint, or an SDK whose
# constructor has a hosted collector baked in. Better this is already red.

# Hosts that exist to receive telemetry. A hit is not automatically a defect --
# a doc link or a test fixture is fine -- but it must be looked at.
_COLLECTOR_HOSTS = (
    "sentry.io", "ingest.sentry.io", "posthog.com", "app.posthog.com",
    "mixpanel.com", "api-js.mixpanel.com", "amplitude.com", "api.amplitude.com",
    "segment.io", "api.segment.io", "google-analytics.com", "analytics.google.com",
    "googletagmanager.com", "bugsnag.com", "datadoghq.com", "newrelic.com",
    "rollbar.com", "logrocket.com", "fullstory.com", "hotjar.com",
    "plausible.io", "umami.is", "matomo.cloud", "statsig.com", "launchdarkly.com",
)

_CODE_ROOTS = ("src", "routes", "services", "core", "companion", "integrations", "mcp_servers")


def _source_files():
    import pathlib

    repo = pathlib.Path(__file__).resolve().parent.parent
    for root in _CODE_ROOTS:
        for p in (repo / root).rglob("*.py"):
            if "test" in p.parts or p.name.startswith("test_"):
                continue
            yield p
    yield repo / "app.py"
    for p in (repo / "static").rglob("*.js"):
        yield p


def test_no_analytics_or_crash_reporting_endpoint_is_compiled_in():
    """Clause 4's absolute half: a build that reports to us is never acceptable,
    at any sample rate, in any aggregation, with or without a consent dialog."""
    hits = []
    for f in _source_files():
        try:
            text = f.read_text(encoding="utf-8", errors="replace")
        except OSError:
            continue
        low = text.lower()
        for host in _COLLECTOR_HOSTS:
            if host in low:
                hits.append(f"{f}: {host}")
    assert not hits, "a telemetry collector host appears in shipped code:\n  " + "\n  ".join(hits[:10])


def test_no_telemetry_destination_ships_pre_filled(defaults):
    """`P16-12` may add these keys. When it does, empty is the only correct value.

    An empty destination is not a disabled feature here -- it is the shipped
    state the law requires. This test passes today because the keys do not exist
    yet, and keeps passing only while whoever adds them ships them empty.
    """
    suspects = [
        k for k in defaults
        if any(w in k.lower() for w in ("telemetry", "analytics", "otlp", "collector", "metrics_endpoint"))
    ]
    for key in suspects:
        value = defaults[key]
        assert value in ("", None, False, [], {}), (
            f"{key} ships as {value!r}; a telemetry destination must ship empty (Law 16 clause 4)"
        )


def test_the_law_records_that_telemetry_itself_is_allowed():
    """The misreading this guards against is 'no telemetry, we are privacy-first'.

    That is wrong in both directions: it bans the operator's own Grafana, and it
    would wave through 'anonymous aggregated usage stats' to a vendor because
    that phrasing avoids the word. The address is the test, and the law has to
    say so in words or the next reader will re-derive the wrong rule.
    """
    import pathlib

    agents = pathlib.Path(__file__).resolve().parent.parent.joinpath(
        ".pantheon/AGENTS.md"
    ).read_text(encoding="utf-8")
    assert "telemetry is fine" in agents, "the owner's amendment is not on the law"
    assert "Prometheus" in agents
    assert "who owns the address at the other end" in agents


def test_the_law_is_written_down():
    """A law that lives only in a commit message is not a law."""
    import pathlib

    agents = pathlib.Path(__file__).resolve().parent.parent.joinpath(
        ".pantheon/AGENTS.md"
    ).read_text(encoding="utf-8")
    assert "Law 16" in agents
    assert "fully self hosted" in agents, "the owner's own words are not on the law"
