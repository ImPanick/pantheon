# SPDX-License-Identifier: AGPL-3.0-or-later
"""`B2023`. One malformed row hid every model a discovered server lists.

Discover (`GET /api/discover`) and the boot warm-up scan the LAN's model
servers and read each one's `/v1/models` (`ModelDiscovery._check_port`). The
reader kept any row whose `id` was truthy, so a row whose id was a number, a
list, `true` or an object got in beside the names. Tidying the names for
display (`lstrip("/")`) then failed on it, the failure was swallowed, and the
server came back as having no models at all, whatever else it listed.

Now a row counts only when its id is a non-empty string, the rule the endpoint
listing already reads with (`routes/model_routes._openai_model_ids`), so the
server's real models are found beside the bad row. A list that names nothing
usable is still no server, and a well-formed list reads as it did.

Ported from upstream Odysseus b46aa02c (#6954); the cases are upstream's, with
the probe patched where Pantheon makes it (`paced_http.get_sync`, `B1022`).
"""
from __future__ import annotations

import pytest

from src.model_discovery import ModelDiscovery


class _Listing:
    """A `/v1/models` answer: the one probe `_check_port` makes once the
    provider fingerprint is fixed."""
    is_success = True

    def __init__(self, payload):
        self._payload = payload

    def json(self):
        return self._payload


def _check(monkeypatch, payload):
    discovery = ModelDiscovery(default_host="localhost")
    monkeypatch.setattr("src.model_discovery.paced_http.get_sync",
                        lambda url, timeout=None, **kw: _Listing(payload))
    monkeypatch.setattr(discovery, "_fingerprint_provider", lambda host, port: "fixture")
    return discovery._check_port("localhost", 8080)


# Ids that name no model: the truthy ones got in before, the falsy ones never did.
_NOT_A_NAME = [7, True, ["qwen3-8b"], {"bad": "id"}, 0, False, [], {}, None, ""]


@pytest.mark.parametrize("wrapped", [True, False], ids=["the openai shape", "a bare list"])
def test_a_row_whose_id_is_not_a_name_does_not_hide_the_servers_other_models(monkeypatch, wrapped):
    def body(rows):
        return {"data": rows} if wrapped else rows

    rows = [{"id": "/qwen3-8b"}, *({"id": bad} for bad in _NOT_A_NAME), "not a row", None,
            {"id": "llama-3.1-8b"}]
    found = _check(monkeypatch, body(rows))
    assert found is not None, "one malformed row hid every model the server lists"
    assert found["models"] == ["/qwen3-8b", "llama-3.1-8b"]
    assert found["models_display"] == ["qwen3-8b", "llama-3.1-8b"]
    assert found["provider"] == "fixture"
    # What did not change: a list that names nothing usable is still no
    # server, and a well-formed one reads as it did.
    assert _check(monkeypatch, body([{"id": bad} for bad in _NOT_A_NAME] + ["not a row"])) is None
    assert _check(monkeypatch, body([{"id": "/qwen3-8b"}, {"id": "llama-3.1-8b"}])) == found
