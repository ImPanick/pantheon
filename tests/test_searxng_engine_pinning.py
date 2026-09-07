# SPDX-License-Identifier: AGPL-3.0-or-later
"""A failed search does not quietly widen who sees the query.

`P16-10`. SearXNG is a metasearch engine: self-hosting it means the aggregator
runs on your hardware, not that the searching does. Queries reach other people's
engines by definition, and that is not the defect.

The defect was the third retry. When a pinned search returned nothing,
`services/search/providers.py` dropped the `engines` parameter — and
`use_default_settings: true` handed the query to SearXNG's full default set:
Google, DuckDuckGo, Brave, Startpage. The exact engines an operator excluded by
pinning. Silently, on the third attempt, logged at INFO as a detail.

So "self-hosted search" became "Google" without the person who chose it being
told. Default-off now, one setting away, the same shape as `P16-01`'s inverted
opt-out and `P16-02`'s empty fallback chain.
"""
import re
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parent.parent
PROVIDERS = ROOT / "services" / "search" / "providers.py"


@pytest.fixture
def calls(monkeypatch):
    """Record every params dict SearXNG is asked with, answering 0 results."""
    seen = []
    import services.search.providers as prov

    class _Resp:
        status_code = 200
        def json(self):
            return {"results": []}
        def raise_for_status(self):
            return None

    def fake_get(url, params=None, headers=None, timeout=None, **kw):
        seen.append(dict(params or {}))
        return _Resp()

    monkeypatch.setattr(prov, "_get_search_instance", lambda: "http://localhost:8080")
    for name in ("httpx", "requests"):
        mod = getattr(prov, name, None)
        if mod is not None:
            monkeypatch.setattr(mod, "get", fake_get, raising=False)
    return seen, prov


def test_default_never_retries_without_an_engine_pin(calls, monkeypatch):
    seen, prov = calls
    monkeypatch.delenv("SEARXNG_WIDEN_ENGINES", raising=False)
    monkeypatch.setattr(prov, "_widen_engines_allowed", lambda: False)
    prov.searxng_search_api("some query that finds nothing", categories="general")
    assert seen, "no request was made — the test would be vacuous"
    unpinned = [p for p in seen if p.get("categories") == "general" and "engines" not in p]
    assert not unpinned, (
        "a general search went out with no engine pin, which hands it to this "
        f"instance's defaults: {unpinned}"
    )


def test_the_widening_retry_still_exists_when_asked_for(calls, monkeypatch):
    """Default-off, not removed. `Law 1` — we add, never subtract."""
    seen, prov = calls
    monkeypatch.setattr(prov, "_widen_engines_allowed", lambda: True)
    prov.searxng_search_api("some query that finds nothing", categories="general")
    unpinned = [p for p in seen if p.get("categories") == "general" and "engines" not in p]
    assert unpinned, "the opt-in path no longer widens; the capability was removed, not defaulted off"


def test_the_setting_ships_off():
    from src.settings import DEFAULT_SETTINGS
    assert DEFAULT_SETTINGS["searxng_widen_engines"] is False


def test_the_env_layer_is_reachable(monkeypatch):
    """Falsy default, so the env fallback is live — `H06`/`B20`, and `P16-05`
    from the other side."""
    import services.search.providers as prov
    monkeypatch.setenv("SEARXNG_WIDEN_ENGINES", "1")
    assert prov._widen_engines_allowed() is True
    monkeypatch.setenv("SEARXNG_WIDEN_ENGINES", "0")
    assert prov._widen_engines_allowed() is False


def test_the_refusal_names_the_engines_and_the_setting():
    """A log line that says 'not retrying' and stops there costs a person an
    afternoon. It must say what was tried and what to change."""
    src = PROVIDERS.read_text(encoding="utf-8")
    # The REFUSAL branch alone. Two earlier versions of this test were vacuous:
    # `index("_widen_engines_allowed()")` lands on the function definition and
    # reads its docstring, and a window from the call site swallows the opt-in
    # branch — whose own log line says "searxng_widen_engines is on", satisfying
    # the assertion while the refusal said nothing at all.
    i = src.index("if _widen_engines_allowed():")
    j = src.index("            else:", i)
    refusal = src[j:src.index("logger.info(", j) + 900]
    assert "searxng_widen_engines" in refusal, "the refusal does not name the setting"
    assert "active_params.get(\"engines\")" in refusal, "the refusal does not say what was tried"
    assert "Google" in refusal, "the refusal does not say what widening would reach"


def test_registered_in_all_five_places():
    assert "searxng_widen_engines" in (ROOT / "src" / "settings.py").read_text(encoding="utf-8")
    assert "SEARXNG_WIDEN_ENGINES" in (ROOT / ".env.example").read_text(encoding="utf-8")
    for f in ("docker-compose.yml", "docker-compose.gpu-amd.yml", "docker-compose.gpu-nvidia.yml"):
        assert "SEARXNG_WIDEN_ENGINES" in (ROOT / f).read_text(encoding="utf-8"), f


def test_the_documentation_says_what_self_hosted_search_actually_means():
    """The row's alternative verify: documented where a person choosing SearXNG
    will read it. Both halves shipped, because the honest sentence — 'queries
    reach other people's engines by definition' — is not one a setting can make
    true."""
    doc = (ROOT / "docs" / "setup.md").read_text(encoding="utf-8")
    # Anchor on the HEADING. The table above it references the section by name,
    # so a plain `index` lands on the cross-reference and reads the wrong page.
    i = doc.index("### What self-hosted search does and does not mean")
    section = doc[i:i + 3000]
    assert "metasearch" in section.lower()
    assert "SEARXNG_WIDEN_ENGINES" in section
    assert "SEARXNG_GENERAL_ENGINES" in section
    # and it must not overclaim
    # Wrapped across a line in the source; normalise before asserting on prose.
    flat = " ".join(section.split())
    assert "no index of its own" in flat
    assert "queries that stay on your network" in flat
