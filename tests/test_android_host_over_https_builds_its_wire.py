# SPDX-License-Identifier: AGPL-3.0-or-later
"""`B2113`. A dedicated Android host reached over https never got past its
first request.

`src.phone_runtime.phone_for` builds every dedicated Android client with
`tls_pin_override=os.environ.get(PIN_ENV, '')`, which is never `None`, so
`WorkstationClient._wire` always takes its override branch for an https
address. That branch named `SOURCE_ENV`, which the module never defines (it is
`SOURCE_ENVIRONMENT`), so the call raised `NameError` before any request:
every https `PANTHEON_ANDROID_URL` was unusable, pinned or not. Plain http was
untouched because the branch is https-only, which is why nothing caught it.
"""
from __future__ import annotations

import asyncio
import ssl

import pytest

from src.workstation_client import (
    SOURCE_ENVIRONMENT,
    WorkstationClient,
    WorkstationError,
)

PIN = ":".join(["AB"] * 32)  # 64 hex digits, the form install.py prints


@pytest.fixture(autouse=True)
def _no_proxy_ranges(monkeypatch):
    # `_direct` only looks a host up when NO_PROXY names a range.
    for name in ("NO_PROXY", "no_proxy"):
        monkeypatch.delenv(name, raising=False)


def _client(pin: str) -> WorkstationClient:
    return WorkstationClient("https://android-host.example.test:8443", "token",
                             android_vm_endpoint=True, tls_pin_override=pin)


def test_an_unpinned_https_android_host_is_verified_by_the_system_store():
    client = _client("")
    assert asyncio.run(client._wire()) is True
    assert client._pin_source == SOURCE_ENVIRONMENT


def test_a_pinned_https_android_host_gets_a_pinned_context():
    client = _client(PIN)
    verify = asyncio.run(client._wire())
    assert isinstance(verify, ssl.SSLContext)
    assert client._pin_source == SOURCE_ENVIRONMENT


def test_a_malformed_android_pin_is_refused_in_words_not_a_name_error():
    client = _client("not-a-fingerprint")
    with pytest.raises(WorkstationError) as caught:
        asyncio.run(client._wire())
    assert "SHA-256 fingerprint" in str(caught.value)
