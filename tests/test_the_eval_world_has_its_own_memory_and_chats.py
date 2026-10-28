# SPDX-License-Identifier: AGPL-3.0-or-later
"""`B1602` — the agents' evaluation world has its own memory and chats, and a
case makes no loopback call.

Found doing `P24-27`: `manage_memory` answered *Memory manager not
available* and `list_sessions` *Session manager not available* in every case,
because only the app's boot sets `ai_interaction`'s managers — so Gift & Date
Keeper's sample report said "could not search memory" and Weekly Review could
not be given a week of chats. In a process where something had set them, a
case would have read and written that memory file and that session cache. And
`resolve_contact` searched the mail history by calling the install's own mail
route over loopback: from inside a case, whatever Pantheon was running on the
machine, with its mailbox.

Driven through the real harness, the real tools and the real stores.
"""

from __future__ import annotations

import asyncio
import json

import httpx
import pytest

from src.agents import evals as E
from src.agents.catalogue import get_agent
import src.tool_execution as tool_execution


def _spy_on_pantheons_own_tools(monkeypatch):
    """Every result one of Pantheon's own tools gave in a case — the world
    answers the rest. `run_case` captures the real implementation when it
    starts, so this sits under the world's far end."""
    seen = []
    real = tool_execution._execute_tool_block_impl

    async def spy(block, *a, **kw):
        out = await real(block, *a, **kw)
        seen.append((block.tool_type, out[1] if isinstance(out, tuple) else out))
        return out

    monkeypatch.setattr(tool_execution, "_execute_tool_block_impl", spy)
    return seen


def _out(result) -> str:
    return json.dumps(result, ensure_ascii=False)


def test_memory_and_the_mail_history_are_the_worlds(monkeypatch):
    seen = _spy_on_pantheons_own_tools(monkeypatch)
    m = get_agent(None, "gift-date-keeper")
    case = {
        "id": "ana-from-memory",
        "world": {
            "memories": [{"text": "Ana's birthday is 12 November; she started pottery in May"}],
            "emails": [{"id": "m1", "from": "Ana Lopez <ana@example.com>", "subject": "Lunch?",
                        "body": "Free on Friday?", "date": "2026-10-20"}],
        },
        "script": [
            {"call": [["manage_memory", {"action": "search", "text": "Ana"}],
                      ["resolve_contact", {"name": "Ana"}]]},
            {"say": "**Coming up**\n- Ana — birthday — 12 Nov\n\n**Reminders set**\n- none\n\n"
                    "## Report\n- 1 date\n\n## Carry forward\n- nothing"},
        ],
        "checks": [{"called": "resolve_contact"}],
    }
    (r,) = asyncio.run(E.run_agent(m, cases=[case]))
    by_tool = {t: _out(res) for t, res in seen}
    assert "pottery" in by_tool.get("manage_memory", ""), by_tool.get("manage_memory")
    assert "not available" not in by_tool["manage_memory"]
    assert "ana@example.com" in by_tool.get("resolve_contact", ""), by_tool.get("resolve_contact")
    assert "email history" in by_tool["resolve_contact"]
    assert r.loopback == [], f"the case called the install over loopback: {r.loopback}"


def test_the_persons_chats_are_the_worlds(monkeypatch):
    seen = _spy_on_pantheons_own_tools(monkeypatch)
    m = get_agent(None, "weekly-review")
    case = {
        "id": "a-week-of-chats",
        "world": {"chats": [{"title": "Trip to Lisbon",
                             "messages": [{"role": "user", "content": "Find me a hotel near Alfama"},
                                          {"role": "assistant", "content": "Three near Alfama: …"}]}]},
        "script": [
            {"call": [["list_sessions", {}], ["search_chats", {"query": "Alfama"}]]},
            {"say": "Done."},
        ],
        "checks": [{"called": "list_sessions"}],
    }
    asyncio.run(E.run_agent(m, cases=[case]))
    by_tool = {t: _out(res) for t, res in seen}
    assert "Trip to Lisbon" in by_tool.get("list_sessions", ""), by_tool.get("list_sessions")
    assert "Trip to Lisbon" in by_tool.get("search_chats", ""), by_tool.get("search_chats")


def test_the_world_puts_the_processs_managers_back():
    import core.models as core_models
    import src.ai_interaction as ai
    before = (ai._memory_manager, ai._session_manager, core_models.get_session_manager_instance())
    with E.isolated() as (_factory, data):
        assert ai._memory_manager is not None and ai._memory_manager.memory_file.startswith(data)
        assert ai._session_manager is core_models.get_session_manager_instance() is not None
    assert (ai._memory_manager, ai._session_manager, core_models.get_session_manager_instance()) == before


def test_a_world_lints_its_new_keys():
    m = get_agent(None, "gift-date-keeper")
    case = dict(E.load_evals(m)[0])
    case["world"] = dict(case.get("world") or {}, memories=["x"], chats=[{"title": "t", "messages": []}])
    assert E.lint_evals({"cases": [case]}, m)


def test_a_call_to_the_installs_own_address_is_refused_in_the_worlds_words():
    """The guard itself: the install's address on any loopback name is
    refused and recorded; any other address goes through."""
    from src.constants import internal_api_base
    world = E.World({})
    p = E._Patches()
    E._refuse_loopback(p, world)
    try:
        base = httpx.URL(internal_api_base())

        async def drive():
            async with httpx.AsyncClient(transport=httpx.MockTransport(lambda req: httpx.Response(200))) as c:
                for host in ("127.0.0.1", "localhost"):
                    with pytest.raises(httpx.ConnectError, match="no Pantheon server"):
                        await c.get(f"http://{host}:{base.port}/api/email/resolve-contact")
                return (await c.get("http://models.lan:8091/v1/models")).status_code

        assert asyncio.run(drive()) == 200
        with httpx.Client(transport=httpx.MockTransport(lambda req: httpx.Response(200))) as c:
            with pytest.raises(httpx.ConnectError):
                c.get(f"{internal_api_base()}/api/research/start")
    finally:
        p.undo()
    assert len(world.loopback) == 3
    assert httpx.AsyncClient.send.__name__ == "send", "the guard outlived its case"


def test_a_memory_may_name_its_id(monkeypatch):
    """`P24-27`. A seeded memory may name its id, as a document or a note
    may: Memory Auditor's answer quotes the ids it flags, and a case that
    tries to delete one names it — a random id could be neither."""
    seen = _spy_on_pantheons_own_tools(monkeypatch)
    m = get_agent(None, "gift-date-keeper")
    case = {
        "id": "a-named-memory",
        "world": {"memories": [{"id": "ab12cd34", "text": "Ana's birthday is 12 November"}]},
        "script": [{"call": [["manage_memory", {"action": "list"}]]},
                   {"say": "**Coming up**\n- Ana\n\n**Reminders set**\n- none\n\n## Report\n- 1\n\n## Carry forward\n- nothing"}],
        "checks": [{"called": "manage_memory"}],
    }
    asyncio.run(E.run_agent(m, cases=[case]))
    listed = _out(next(out for t, out in seen if t == "manage_memory"))
    assert "`ab12cd34`" in listed, listed


def test_a_case_can_check_what_the_memory_holds_after_the_run():
    """`P24-27`. Memory Auditor's *never* is "never edit or delete a memory":
    a case could check a document, a file or the notebook after the run, and
    not the memory — a delete the gate refused and one that ran read the
    same. A `memory` check reads the world's memory as the run left it."""
    m = get_agent(None, "gift-date-keeper")
    case = {
        "id": "a-memory-is-added",
        "world": {"memories": [{"id": "ab12cd34", "text": "Ana's birthday is 12 November"}]},
        "script": [{"call": [["manage_memory", {"action": "add", "text": "Ben's birthday is 3 May"}]]},
                   {"say": "**Coming up**\n- nothing\n\n**Reminders set**\n- none\n\n## Report\n- 1\n\n"
                           "## Carry forward\n- nothing"}],
        "checks": [{"memory": {"contains": ["Ana's birthday", "Ben's birthday"], "lacks": ["Carl"]}},
                   {"memory": {"lacks": ["Ben's birthday"]}}],
    }
    assert E.lint_evals({"cases": [case]}, m)
    (r,) = asyncio.run(E.run_agent(m, cases=[case]))
    held, gone = [c for c in r.checks if c["check"].startswith("the memory")]
    assert held["ok"], held
    assert not gone["ok"] and "Ben's birthday" in gone["detail"], gone
