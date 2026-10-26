# SPDX-License-Identifier: AGPL-3.0-or-later
"""`B1261` — a failed GGUF scan answered 500 instead of its sentence.

`GET /api/cookbook/hf-gguf-files`'s `except` logged
`logger.exception("HF GGUF file scan failed for %s", repo)`, and no scope in
that handler defines `repo` (its parameter is `repo_id`). So the arm written to
say *"HF API request failed"* raised `NameError` itself, and the Forge's Direct
Download box read *"GGUF scan failed: HTTP 500"*.

Driven through the real Forge router (`Law 20`) with the hubs switched on and
the one outbound call — `paced_http.get` — failing the way a dropped network
does. The limiter is not touched: the stub stands where the request would be.
"""
from __future__ import annotations

import httpx
import pytest

from tests.test_the_forge_reaches_hugging_face_only_when_an_admin_says import (  # noqa: F401
    _forge,
    _switch,
    datadir,
)


@pytest.fixture
def hf_unreachable(monkeypatch):
    import src.paced_http as paced_http

    asked = []

    async def get(url, *a, **k):
        asked.append(url)
        raise httpx.ConnectError("network is unreachable")

    monkeypatch.setattr(paced_http, "get", get)
    return asked


def test_a_scan_that_cannot_reach_hugging_face_says_so(datadir, hf_unreachable):
    _switch(True)
    res = _forge().get("/api/cookbook/hf-gguf-files?repo_id=Qwen/Qwen3-8B-GGUF")

    assert res.status_code == 200, res.text
    assert res.json() == {"ok": False, "files": [], "error": "HF API request failed"}
    assert hf_unreachable == ["https://huggingface.co/api/models/Qwen/Qwen3-8B-GGUF"]


def test_the_failure_is_logged_against_the_repo_it_was_for(datadir, hf_unreachable, caplog):
    _switch(True)
    with caplog.at_level("ERROR", logger="routes.cookbook_routes"):
        _forge().get("/api/cookbook/hf-gguf-files?repo_id=Qwen/Qwen3-8B-GGUF")
    said = [r.getMessage() for r in caplog.records if "GGUF file scan failed" in r.getMessage()]
    assert said == ["HF GGUF file scan failed for Qwen/Qwen3-8B-GGUF"], said
