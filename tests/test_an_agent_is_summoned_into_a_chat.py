# SPDX-License-Identifier: AGPL-3.0-or-later
"""`P24-26` — an agent summoned into a chat brings its runbook, exactly its
tools and its effects table; the hall says *Summon* where it said *Hire*.

The owner, 2026-10-24: *"we need a way to attach agents in agent mode. The up
arrow here should also have an agents option — and for the Agents menu as well
— instead of hire agent we should say Summon."*

`src/agents/summon.py` against the real shipped manifests and a person's real
hire (the `world` of `test_a_hired_agent_runs_as_its_file_says.py`); the real
chat route (`test_foreground_model_routing`'s driver) for what reaches the
loop; and `static/js/summon.js` under node for the composer's half.

**Measured before this file, on `60372cf`:** there was no Agents entry in the
composer and the chat route had no `agent` field.
"""

from __future__ import annotations

import asyncio
import json
import shutil
from pathlib import Path

import pytest

from src.agents.summon import AGENT_MODE_ONLY, NO_SUCH_AGENT, SummonRefused, summon
from src.tool_policy import ToolPolicy

ROOT = Path(__file__).resolve().parents[1]


def test_a_summoned_agent_brings_its_runbook_and_only_its_tools():
    s = summon("alice", "topic-watcher")
    assert s.tools == ["web_search", "web_fetch"]
    brief = s.messages[0]["content"]
    assert "alice summoned Topic Watcher into this chat" in brief
    assert "1. For each topic you were hired with" in brief, "its runbook, every word"
    policy = s.policy(ToolPolicy())
    assert policy.allowed_tools == frozenset({"web_search", "web_fetch"})
    assert policy.reason_for("send_email") == "“send_email” is not one of this agent's tools."
    narrowed = s.policy(ToolPolicy(allowed_tools=frozenset({"web_search", "bash"})))
    assert narrowed.allowed_tools == frozenset({"web_search"}), "it narrows a turn, never widens it"


def test_its_brief_goes_after_the_system_messages():
    s = summon("alice", "morning-brief")
    out = s.into([{"role": "system", "content": "sys"}, {"role": "user", "content": "hi"}])
    assert [m.get("content", "")[:3] for m in out][0] == "sys"
    assert out[1] is s.messages[0] and out[-1]["content"] == "hi"


def test_a_summoned_agent_follows_its_skills():
    s = summon("alice", "site-builder")
    assert s.skill_lines == ["Followed the skill “workstation-shell”.", "Followed the skill “workstation-desktop”.",
                             "Followed the skill “workstation-self-test”."]
    assert len(s.messages) == 4


@pytest.mark.parametrize("agent,mode,sentence", [("no-such", "agent", NO_SUCH_AGENT),
                                                 ("topic-watcher", "chat", AGENT_MODE_ONLY)])
def test_what_cannot_be_summoned_says_why(agent, mode, sentence):
    with pytest.raises(SummonRefused) as caught:
        summon("alice", agent, mode=mode)
    assert caught.value.sentence == sentence


from tests.test_a_hired_agent_runs_as_its_file_says import _hire, world  # noqa: E402,F401
from tests.test_a_workflow_is_kept_as_one_document import wf_db  # noqa: E402,F401


def test_the_persons_own_hire_keeps_what_they_tightened(world):
    factory, _sched, _seen = world
    db = factory()
    assert summon("alice", "topic-watcher", db=db).never_effects == frozenset()
    _hire(db, "topic-watcher", inputs={"topics": ["x"]}, grants={"network_egress": "never"})
    s = summon("alice", "topic-watcher", db=db)
    assert s.never_effects == frozenset({"network_egress"}) and s.tools == ["web_search"]


# ── the chat route ──────────────────────────────────────────────────────────

async def _turn(monkeypatch, form):
    import routes.chat_routes as chat_routes
    from test_foreground_model_routing import _RouteRequest, _chat_stream_endpoint
    captured = {}
    endpoint = _chat_stream_endpoint(monkeypatch, "agent", captured)
    monkeypatch.setattr(chat_routes, "coerce_message_and_session",
                        lambda *a, **k: (form.get("message", "hello"), "session-1"))

    async def loop(endpoint_url, model, messages, **kwargs):
        captured["policy"] = kwargs.get("tool_policy")
        captured["relevant"] = kwargs.get("relevant_tools")
        captured["messages"] = messages
        yield "data: [DONE]\n\n"

    monkeypatch.setattr(chat_routes, "stream_agent_loop", loop)
    request = _RouteRequest("agent")
    request._form.update({"compare_mode": "false", **form})
    response = await endpoint(request)
    async for _ in response.body_iterator:
        pass
    return captured


@pytest.mark.asyncio
async def test_the_chat_route_hands_the_loop_the_agents_kit(monkeypatch):
    captured = await _turn(monkeypatch, {"message": "what's new on solar?", "agent": "topic-watcher"})
    assert captured["policy"].allowed_tools == frozenset({"web_search", "web_fetch"})
    assert captured["policy"].allowed_owner == "this agent's"
    assert captured["relevant"] == {"web_search", "web_fetch"}, "offered as they are, not guessed from the message"
    assert any("summoned Topic Watcher" in str(m.get("content")) for m in captured["messages"])
    plain = await _turn(monkeypatch, {"message": "hi"})
    assert plain["policy"].allowed_tools is None, "`Law 1`: a turn with no agent is as it was"
    assert plain["relevant"] is None


@pytest.mark.asyncio
async def test_an_unknown_agent_is_refused_before_anything_streams(monkeypatch):
    from fastapi import HTTPException
    with pytest.raises(HTTPException) as caught:
        await _turn(monkeypatch, {"message": "hi", "agent": "no-such"})
    assert caught.value.status_code == 400 and caught.value.detail == NO_SUCH_AGENT


# ── the composer ────────────────────────────────────────────────────────────

pytestmark_node = pytest.mark.skipif(not shutil.which("node"), reason="node binary not on PATH")


def test_the_composer_has_an_agents_entry_and_a_chip():
    html = (ROOT / "static" / "index.html").read_text(encoding="utf-8")
    menu = html[html.index('id="overflow-menu"'):html.index('id="overflow-preset-btn"')]
    assert 'id="overflow-agents-btn"' in menu and "<span>Agents</span>" in menu
    assert 'id="summon-indicator-btn"' in html and 'id="summon-indicator-name"' in html
    chat = (ROOT / "static" / "js" / "chat.js").read_text(encoding="utf-8")
    assert "fd.append('agent', _summoned.id)" in chat


@pytestmark_node
def test_the_picker_puts_your_own_agents_first_and_filters(tmp_path):
    import subprocess
    (tmp_path / "storage.js").write_text(
        "const m = new Map(); export const KEYS = { SUMMONED_AGENT: 's' };"
        "export default { get: (k, d) => m.has(k) ? m.get(k) : d, set: (k, v) => m.set(k, v), remove: (k) => m.delete(k) };")
    shutil.copy(ROOT / "static" / "js" / "summon.js", tmp_path / "summon.js")
    (tmp_path / "case.mjs").write_text("""
        globalThis.document = { getElementById: () => null, dispatchEvent: () => {}, addEventListener: () => {} };
        globalThis.CustomEvent = class { constructor(n) { this.type = n; } };
        const m = await import('./summon.js');
        const agents = [{ id: 'a', name: 'Alpha', tagline: 'reads mail' }, { id: 'b', name: 'Beta', tagline: 'web' },
                        { id: 'c', name: 'Gamma', tagline: 'mail too' }];
        const order = m.pickerRows(agents, ['c'], '').map((x) => x.id);
        const mail = m.pickerRows(agents, ['c'], 'MAIL').map((x) => x.id);
        m.summon({ id: 'b', name: 'Beta', tagline: 'web' });
        const got = m.getSummoned();
        m.dismiss();
        console.log(JSON.stringify({ order, mail, got, after: m.getSummoned() }));
    """)
    out = subprocess.run(["node", "case.mjs"], cwd=tmp_path, capture_output=True, text=True, timeout=30)
    assert out.returncode == 0, out.stderr
    assert json.loads(out.stdout) == {"order": ["c", "a", "b"], "mail": ["c", "a"],
                                      "got": {"id": "b", "name": "Beta"}, "after": None}
