# SPDX-License-Identifier: AGPL-3.0-or-later
"""`B530` — every privilege a route reads goes through `resolve_privilege`.

Eight sites spelled the rule out longhand, `privs.get("<key>", True)`: seven in
`routes/chat_routes.py` deciding which tools a run is denied, one in
`routes/research/research_routes.py` (the delegated-owner research check).
Harmless while `AuthManager.get_privileges` hands them a map holding every
declared key — and a silent **grant** the day anything hands them one it did
not build (a role overlay, a cached partial map, a test double): the `True`
default answered for a key the registry declares off (`can_use_bash`).

Driven: the real chat route's tool-withholding step, given a deliberately
unmerged map, withholds what the registry says to withhold; an empty map is
resolved to the registry, not skipped as one that grants everything.
"""
from __future__ import annotations

import re
from pathlib import Path

import pytest

from core.auth import DEFAULT_PRIVILEGES

ROOT = Path(__file__).resolve().parents[1]


def test_the_registry_still_declares_the_shell_off():
    """The premise the driven cases rest on."""
    assert DEFAULT_PRIVILEGES["can_use_bash"] is False
    assert DEFAULT_PRIVILEGES["can_use_documents"] is True


async def _disabled(monkeypatch, privileges) -> set:
    """`disabled_tools` as the real chat route hands them to the agent loop,
    for a turn sent with the shell switched on in the composer — so whatever
    withholds it is the privilege step."""
    import routes.chat_routes as chat_routes
    from test_foreground_model_routing import _RouteRequest, _chat_stream_endpoint

    captured = {}
    endpoint = _chat_stream_endpoint(monkeypatch, "agent", captured)

    async def capturing_loop(endpoint_url, model, messages, **kwargs):
        captured["disabled"] = set(kwargs.get("disabled_tools") or ())
        yield "data: [DONE]\n\n"

    monkeypatch.setattr(chat_routes, "stream_agent_loop", capturing_loop)
    request = _RouteRequest("agent", privileges=privileges)
    request._form.update({"compare_mode": "false", "allow_bash": "true"})
    response = await endpoint(request)
    async for _ in response.body_iterator:
        pass
    return captured["disabled"]


@pytest.mark.asyncio
async def test_the_harness_offers_the_shell_when_nothing_withholds_it(monkeypatch):
    assert "bash" not in await _disabled(monkeypatch, {"can_use_bash": True})


@pytest.mark.asyncio
@pytest.mark.parametrize("privileges", [
    {"can_use_documents": True},    # a map the manager did not build: no `can_use_bash`
    {},                             # nothing at all
])
async def test_an_unmerged_map_gets_the_registrys_answer_not_true(monkeypatch, privileges):
    disabled = await _disabled(monkeypatch, dict(privileges))
    assert {"bash", "python", "read_file", "write_file"} <= disabled, disabled


@pytest.mark.asyncio
async def test_a_switch_the_person_holds_still_wins(monkeypatch):
    disabled = await _disabled(monkeypatch, {"can_use_bash": True, "can_use_documents": False})
    assert "manage_documents" in disabled and "bash" not in disabled


def test_no_route_spells_the_rule_out_longhand():
    """Absence from every non-test Python file (`Law 20`: the one use a
    file-wide search is for)."""
    longhand = re.compile(r"""privs\.get\(\s*["'][a-z_]+["']\s*,\s*True\s*\)""")
    hits = []
    for base in ("routes", "src", "core", "services"):
        for path in sorted((ROOT / base).rglob("*.py")):
            text = path.read_text(encoding="utf-8")
            hits += [f"{path.relative_to(ROOT)}:{text.count(chr(10), 0, m.start()) + 1}"
                     for m in longhand.finditer(text)]
    assert hits == [], hits
