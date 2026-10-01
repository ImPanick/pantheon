# SPDX-License-Identifier: AGPL-3.0-or-later
"""`P20-04`, at the merge: the workstation's desktop is withheld wherever a
shell is.

`computer` drives a desktop with a terminal one click away and a browser on
it. So the chat's *enable shell* toggle, an explicit web lookup (which must not
drift into personal tools or shell fallbacks, `B972`) and a light promotion each take
it with `bash` — otherwise switching the shell off would leave a second way to
run commands on (`Law 14`, `P17-11`'s argument), and "search the web for X"
would be offered a whole desktop (found by `P20-04`).

Driven through the real chat route (`_chat_stream_endpoint`) and the real
`escalation_withholds`, not read from the source (`Law 20`).
"""
from __future__ import annotations

from typing import Any, Dict

import pytest

from routes.chat_helpers import escalation_withholds


async def _disabled(monkeypatch, **form) -> set:
    import routes.chat_routes as chat_routes
    from test_foreground_model_routing import _RouteRequest, _chat_stream_endpoint

    captured: Dict[str, Any] = {}
    endpoint = _chat_stream_endpoint(monkeypatch, "agent", captured)

    async def capturing_loop(endpoint_url, model, messages, **kwargs):
        captured["disabled"] = set(kwargs.get("disabled_tools") or ())
        yield "data: [DONE]\n\n"

    monkeypatch.setattr(chat_routes, "stream_agent_loop", capturing_loop)
    request = _RouteRequest("agent")
    request._form["compare_mode"] = "false"
    request._form.update(form)
    response = await endpoint(request)
    async for _ in response.body_iterator:
        pass
    return captured["disabled"]


@pytest.mark.asyncio
async def test_the_shell_toggle_off_takes_the_desktop_too(monkeypatch):
    disabled = await _disabled(monkeypatch, allow_bash="false")
    assert {"bash", "host_shell", "computer"} <= disabled


@pytest.mark.asyncio
async def test_the_shell_toggle_on_leaves_the_desktop_alone(monkeypatch):
    disabled = await _disabled(monkeypatch, allow_bash="true")
    assert "computer" not in disabled and "bash" not in disabled


@pytest.mark.asyncio
async def test_a_direct_web_lookup_is_not_offered_the_desktop(monkeypatch):
    disabled = await _disabled(monkeypatch, message="search the web for the weather in Oslo",
                               allow_web_search="true")
    assert {"bash", "python", "computer"} <= disabled


@pytest.mark.parametrize("kwargs", [
    dict(promoted=True, workspace_intent=False, allow_browser=False),
    dict(promoted=True, workspace_intent=False, allow_browser=True),
    dict(promoted=True, workspace_intent=True, allow_browser=False, shell_granted=False),
])
def test_a_promotion_that_withholds_the_shell_withholds_the_desktop(kwargs):
    assert "computer" in escalation_withholds(browser_tools={"browser_click"}, **kwargs)


def test_a_promotion_that_grants_the_shell_withholds_nothing():
    assert escalation_withholds(promoted=True, workspace_intent=True, allow_browser=False,
                                browser_tools={"browser_click"}) == []
