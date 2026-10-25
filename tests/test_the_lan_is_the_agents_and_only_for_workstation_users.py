# SPDX-License-Identifier: AGPL-3.0-or-later
"""`B1459` — LAN reach is the agent's, and only for a person allowed the workstation.

`D-2026-10-25-02` opened the LAN to server-side fetches so an agent can read a
router page by URL, and said who for: *"Workstation users get it… a
non-workstation account keeps today's limits."* As first shipped, the switch
(`agent_lan_reach`) was install-wide and read on every call: the image proxy
(`/api/img`, which fetches whatever `<img src>` a stranger's email names), the
search-result fetcher and a non-workstation account's agent all reached the LAN.
The 2026-10-25 docs audit found it.

Now the default is no LAN, and a grant is explicit: the agent's `web_fetch`
opens `lan_reach_for(owner)` around its fetch, which allows the LAN only when
the install does AND that person may use the workstation. The page cache keeps
granted and ungranted fetches apart, because it is read before any address is.
"""

from __future__ import annotations

import asyncio
import ipaddress

import httpx
import pytest

import src.outbound_fetch as of


def test_no_grant_means_no_lan_whatever_the_setting(monkeypatch):
    monkeypatch.setattr(of, "_lan_reach_on", lambda: True)
    assert of.lan_allowed() is False
    assert of._is_private_address(ipaddress.ip_address("192.168.1.1")) is True
    with pytest.raises(httpx.RequestError):
        of._resolve_public_ips("http://192.168.1.1/")
    assert of._public_http_url("http://10.0.0.5/") is False


@pytest.mark.parametrize("setting, person, expected", [
    (True, True, True),     # the install allows it and the person has the workstation
    (True, False, False),   # a non-workstation account keeps today's limits
    (False, True, False),   # the admin switched LAN reach off
])
def test_a_grant_needs_the_install_and_the_person(monkeypatch, setting, person, expected):
    monkeypatch.setattr(of, "_lan_reach_on", lambda: setting)
    monkeypatch.setattr(of, "may_reach_lan", lambda owner: person)
    with of.lan_reach_for("ada") as allowed:
        assert allowed is expected and of.lan_allowed() is expected
        assert of._is_private_address(ipaddress.ip_address("192.168.1.1")) is (not expected)
        # loopback and metadata never, inside a grant or out
        assert of._is_private_address(ipaddress.ip_address("127.0.0.1")) is True
        assert of._is_private_address(ipaddress.ip_address("169.254.169.254")) is True
    assert of.lan_allowed() is False, "the grant ends with the block"


def test_the_agents_web_fetch_opens_the_grant_for_its_owner_only(monkeypatch):
    """The fetch runs in an executor thread; the grant is opened there, around
    the fetch, for the turn's owner."""
    import src.search.content as content
    from src.agent_tools.web_tools import WebFetchTool
    seen = {}

    def fake_fetch(url, timeout=10, max_bytes=None):
        seen[url] = of.lan_allowed()
        return {"content": "router page", "title": "Router"}

    monkeypatch.setattr(content, "fetch_webpage_content", fake_fetch)
    monkeypatch.setattr(of, "_lan_reach_on", lambda: True)
    monkeypatch.setattr(of, "may_reach_lan", lambda owner: owner == "ada")
    tool = WebFetchTool()
    loop = asyncio.new_event_loop()
    try:
        loop.run_until_complete(tool.execute("http://192.168.1.1/", {"owner": "ada"}))
        loop.run_until_complete(tool.execute("http://192.168.1.2/", {"owner": "bob"}))
    finally:
        loop.close()
    assert seen == {"http://192.168.1.1/": True, "http://192.168.1.2/": False}


def test_the_image_proxy_fetches_outside_any_grant():
    """`/api/img` calls `_get_public_url` with no grant, so a LAN `<img src>` in
    an email is refused at resolution, before a socket opens."""
    from pathlib import Path
    src = (Path(__file__).resolve().parent.parent / "routes" / "image_proxy_routes.py").read_text()
    assert "lan_reach_for" not in src
    with pytest.raises(httpx.RequestError):
        of._resolve_public_ips("http://192.168.1.1/tracker.png")


def test_the_page_cache_keeps_granted_fetches_apart(monkeypatch, tmp_path):
    """A router page an allowed agent read must not be served from the cache to
    a fetch without a grant — the cache is read before any address is checked."""
    import src.search.content as content
    keys = []
    real = content.generate_cache_key
    monkeypatch.setattr(content, "generate_cache_key", lambda s: (keys.append(s), real(s))[1])
    monkeypatch.setattr(content, "CONTENT_CACHE_DIR", tmp_path)
    monkeypatch.setattr(content, "_get_public_url",
                        lambda *a, **k: (_ for _ in ()).throw(httpx.RequestError("stop")))
    content.fetch_webpage_content("http://192.168.1.1/")
    monkeypatch.setattr(of, "_lan_reach_on", lambda: True)
    monkeypatch.setattr(of, "may_reach_lan", lambda owner: True)
    with of.lan_reach_for("ada"):
        content.fetch_webpage_content("http://192.168.1.1/")
    assert len(keys) == 2 and keys[0] != keys[1]
    assert keys[0].endswith("#lan=0") and keys[1].endswith("#lan=1")
