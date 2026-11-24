# SPDX-License-Identifier: AGPL-3.0-or-later
"""`B2241`: the reasoning cache (CPU-ARC, arXiv 2611.09891), built in.

* The sandbox runs an entry's plain Python in a child process and refuses
  anything that could reach past it: imports, underscore names, `str.format`,
  files, a loop that never ends.
* Entries belong to one person and one scope; one earns Live by agreeing with
  the model, falls back to Shadow on a disagreement, and is retired by two.
* The gate changes nothing when the person has it off, answers from a Live
  entry only for a person in Live, passes every miss through to the model, and
  builds only from runs that finished cleanly and only read.
* A run inside a space pinned to local models sits the cache out while any
  of its models is a billed one.
* The cache's tools are reads the entry was built with, and nothing else.
"""
import asyncio
import json

import pytest

from src.reasoning_cache import builder, gate, invoke, roles, store
from src.reasoning_cache.sandbox import (FINAL_REPLY_KEY, CodeRefused, EntryFailed,
                                         RunResult, check_code, run_entry)
from tests.helpers.apollo_db import apollo_db  # noqa: F401  (fixture)


def _run(coro):
    return asyncio.run(coro)


# ── the sandbox ─────────────────────────────────────────────────────────────

@pytest.mark.parametrize("code", [
    "import os\ndef solve(p):\n    return {}\n",
    "def solve(p):\n    return {'x': ().__class__}\n",
    "def solve(p):\n    return {'x': '{}'.format(1)}\n",
    "class A:\n    pass\ndef solve(p):\n    return {}\n",
    "def deco(f):\n    return f\n@deco\ndef solve(p):\n    return {}\n",
    "def solve(p):\n    _x = 1\n    return {}\n",
    "print('at import')\ndef solve(p):\n    return {}\n",
])
def test_the_sandbox_refuses_code_that_could_reach_past_it(code):
    with pytest.raises(CodeRefused):
        check_code(code, "solve")


def test_an_entry_runs_and_asks_the_parent_for_its_primitives():
    code = (
        "def solve(p):\n"
        "    a = convert(p['first number'], 'int')\n"
        "    b = convert(p['second number'], 'int')\n"
        "    narrate(f'added {a} and {b}')\n"
        "    tone = lm('say hi')\n"
        f"    return {{{FINAL_REPLY_KEY!r}: f'{{a}} + {{b}} = {{a + b}} ({{tone}})'}}\n")
    calls = []

    async def on_call(name, args):
        calls.append(name)
        return "hi!"

    result = _run(run_entry(code, "solve", {"first number": "2", "second number": "40"},
                            on_call, timeout=30))
    assert result.reply == "2 + 40 = 42 (hi!)"
    assert result.narration == ["added 2 and 40"]
    assert calls == ["lm"]


def test_files_are_not_there_and_a_runaway_loop_is_stopped():
    async def on_call(name, args):
        return ""

    with pytest.raises(EntryFailed):
        _run(run_entry("def solve(p):\n    return {'the final reply': open('x').read()}\n",
                       "solve", {}, on_call, timeout=30))
    with pytest.raises(EntryFailed):
        _run(run_entry("def solve(p):\n    while True:\n        pass\n",
                       "solve", {}, on_call, timeout=2))


# ── the store ───────────────────────────────────────────────────────────────

def _add(db, owner="ada", scope="chat", vec=(1.0, 0.0), tools=()):
    return store.add_entry(db, owner, scope, applies_when="adding two numbers",
                           request="what is 2 + 40", answer="42", embedding=list(vec),
                           parameters=[], code="def solve(p):\n    return {}\n",
                           root="solve", tools=list(tools), source_tokens=500)


def test_scopes_keep_people_spaces_and_tasks_apart(apollo_db):
    assert store.scope_for(space_id="s1", apollo=True) == "space:s1"
    assert store.scope_for(apollo=True) == "apollo"
    assert store.scope_for(agent_id="a1", task_id="t1") == "agent:a1"
    assert store.scope_for(task_id="t1") == "task:t1"
    assert store.scope_for() == "chat"
    db = apollo_db()
    _add(db)
    assert store.best_match(db, "ada", "chat", [1.0, 0.0], 0.88) is not None
    assert store.best_match(db, "bob", "chat", [1.0, 0.0], 0.88) is None
    assert store.best_match(db, "ada", "space:s1", [1.0, 0.0], 0.88) is None
    assert store.best_match(db, "ada", "chat", [0.0, 1.0], 0.88) is None


def test_an_entry_earns_live_and_loses_it(apollo_db):
    db = apollo_db()
    entry = _add(db)
    assert store.record_shadow(db, "ada", entry, True, 2) == store.SHADOW
    assert store.record_shadow(db, "ada", entry, True, 2) == store.LIVE
    assert store.record_shadow(db, "bob", entry, False, 2) is None   # not his
    assert store.record_shadow(db, "ada", entry, False, 2) == store.SHADOW
    assert store.record_shadow(db, "ada", entry, False, 2) == store.RETIRED
    assert store.best_match(db, "ada", "chat", [1.0, 0.0], 0.5) is None


# ── the gate ────────────────────────────────────────────────────────────────

def _sse(payload):
    return f"data: {json.dumps(payload)}\n\n"


class _Run:
    """A stand-in agent loop that records whether it ever started."""

    def __init__(self, chunks):
        self.chunks = chunks
        self.started = False

    async def __call__(self):
        self.started = True
        for c in self.chunks:
            yield c


def _collect(stream):
    async def go():
        out = [c async for c in stream]
        if gate._background:
            await asyncio.gather(*list(gate._background))
        return out
    return _run(go())


@pytest.fixture
def cache(apollo_db, monkeypatch):
    """The cache on for ada, with vectors that put every request on one entry."""
    state = {"mode": "live", "built": [], "shadowed": []}
    monkeypatch.setattr(roles, "mode_for", lambda owner: state["mode"] if owner else "off")
    monkeypatch.setattr(roles, "embed", lambda text: [1.0, 0.0])
    monkeypatch.setattr(roles, "match_threshold", lambda: 0.88)

    async def fake_build(owner, scope, t):
        state["built"].append((owner, scope, t))

    async def fake_shadow(owner, entry, request, reply, *args):
        state["shadowed"].append((entry["id"], reply))

    monkeypatch.setattr(builder, "build", fake_build)
    monkeypatch.setattr(gate, "_shadow", fake_shadow)
    state["db"] = apollo_db
    return state


MESSAGES = [{"role": "user", "content": "what is 2 + 40"}]
MODEL_TURN = [_sse({"delta": "It is 42, the sum of 2 and 40."}), "data: [DONE]\n\n"]


def test_off_changes_not_a_byte(cache):
    cache["mode"] = "off"
    run = _Run(MODEL_TURN)
    out = _collect(gate.around(run(), owner="ada", scope="chat", messages=MESSAGES,
                               build_from=True))
    assert out == MODEL_TURN
    assert cache["built"] == [] and cache["shadowed"] == []


def test_a_live_entry_answers_for_a_person_in_live_without_starting_the_model(cache, monkeypatch):
    db = cache["db"]()
    entry = _add(db)
    store.record_shadow(db, "ada", entry, True, 1)

    async def answer(e, request, owner, **kw):
        assert e["id"] == entry and request == "what is 2 + 40"
        return RunResult(reply="42", result={}, narration=["added 2 and 40"])

    monkeypatch.setattr(invoke, "answer", answer)
    run = _Run(MODEL_TURN)
    out = _collect(gate.around(run(), owner="ada", scope="chat", messages=MESSAGES))
    assert not run.started
    note = json.loads(out[0][6:])
    assert note["type"] == "reasoning_cache" and note["state"] == "served"
    assert note["narration"] == ["added 2 and 40"]
    assert json.loads(out[1][6:]) == {"delta": "42"}
    assert out[2] == "data: [DONE]\n\n"
    row = store.best_match(cache["db"](), "ada", "chat", [1.0, 0.0], 0.5)[0]
    assert row["served"] == 1 and row["tokens_saved"] == 500


def test_a_miss_goes_to_the_model_untouched(cache, monkeypatch):
    db = cache["db"]()
    store.record_shadow(db, "ada", _add(db), True, 1)

    async def answer(*a, **kw):
        raise invoke.Miss("the request does not say 'first number'")

    monkeypatch.setattr(invoke, "answer", answer)
    out = _collect(gate.around(_Run(MODEL_TURN)(), owner="ada", scope="chat",
                               messages=MESSAGES))
    assert out == MODEL_TURN


def test_in_shadow_the_model_answers_and_the_entry_is_checked_after(cache):
    cache["mode"] = "shadow"
    db = cache["db"]()
    entry = _add(db)
    store.record_shadow(db, "ada", entry, True, 1)   # live, but the person is in Shadow
    out = _collect(gate.around(_Run(MODEL_TURN)(), owner="ada", scope="chat",
                               messages=MESSAGES))
    assert out == MODEL_TURN
    assert cache["shadowed"] == [(entry, "It is 42, the sum of 2 and 40.")]


def test_only_a_clean_run_of_a_repeating_kind_is_built_from(cache):
    tool_turn = [
        _sse({"type": "tool_start", "tool": "read_file", "command": "a.txt",
              "effects": ["read_workspace"]}),
        _sse({"type": "tool_output", "tool": "read_file", "output": "2 40"}),
    ] + MODEL_TURN
    _collect(gate.around(_Run(tool_turn)(), owner="ada", scope="task:t1",
                         messages=MESSAGES, build_from=True))
    assert len(cache["built"]) == 1
    owner, scope, t = cache["built"][0]
    assert (owner, scope) == ("ada", "task:t1")
    assert t.tools[0].output == "2 40" and t.finished_cleanly

    cache["built"].clear()
    _collect(gate.around(_Run(MODEL_TURN)(), owner="ada", scope="chat",
                         messages=MESSAGES))                         # a chat turn
    _collect(gate.around(_Run([_sse({"type": "ask_user"})] + MODEL_TURN)(), owner="ada",
                         scope="task:t1", messages=MESSAGES, build_from=True))
    _collect(gate.around(_Run(MODEL_TURN)(), owner="ada", scope="task:t1",
                         messages=MESSAGES, build_from=True, consult=False))
    assert cache["built"] == []


def test_a_write_is_never_built_from():
    t = builder.Transcript(request="save it", answer="Saved the file for you, as asked.",
                           tools=[builder.ToolStep("write_file", "a.txt", ["write_workspace"])],
                           finished_cleanly=True)
    assert builder.worth_building(t) == "write_file does more than read"
    t.tools = [builder.ToolStep("read_file", "a.txt", ["read_workspace"])]
    assert builder.worth_building(t) is None


def test_a_local_only_space_sits_out_while_any_role_is_billed(cache, monkeypatch):
    monkeypatch.setattr(roles, "all_local", lambda owner: False)
    out = _collect(gate.around(_Run(MODEL_TURN)(), owner="ada", scope="space:s1",
                               messages=MESSAGES, build_from=True, local_only=True))
    assert out == MODEL_TURN and cache["built"] == []

    from src.apollo import budget
    monkeypatch.undo()
    monkeypatch.setattr(roles, "resolve",
                        lambda role, owner: ("https://api.openai.com/v1", "gpt", {}))
    monkeypatch.setattr(budget, "billed", lambda url: "openai" in url)
    assert roles.all_local("ada") is False
    monkeypatch.setattr(roles, "resolve",
                        lambda role, owner: ("http://localhost:1234/v1", "qwen", {}))
    assert roles.all_local("ada") is True


# ── the tools ───────────────────────────────────────────────────────────────

def test_the_cache_uses_only_reads_it_was_built_with():
    tools = invoke.ReadOnlyTools("ada", allowed={"read_file", "write_file", "bash"})
    with pytest.raises(PermissionError, match="not a tool this entry was built with"):
        _run(tools("web_search", "cats"))
    with pytest.raises(PermissionError, match="not a read"):
        _run(tools("write_file", "a.txt\nhi"))
    with pytest.raises(PermissionError, match="not a read"):
        _run(tools("bash", "ls"))
    off = invoke.ReadOnlyTools("ada", allowed={"read_file"}, disabled_tools={"read_file"})
    with pytest.raises(PermissionError, match="switched off"):
        _run(off("read_file", "a.txt"))


def test_a_value_the_request_does_not_state_is_a_miss(monkeypatch):
    async def call(role, owner, messages, **kw):
        assert role == "target"
        return '```json\n{"first number": "2", "second number": null}\n```'

    monkeypatch.setattr(roles, "call", call)
    params = [{"name": "first number"}, {"name": "second number"}]
    with pytest.raises(invoke.Miss):
        _run(invoke.extract_params("ada", "add 2 to something", params))


# ── the person's mode ───────────────────────────────────────────────────────

def test_the_mode_is_one_of_three_and_off_unless_chosen(monkeypatch):
    assert roles.checked_mode(" Live ") == "live"
    with pytest.raises(ValueError):
        roles.checked_mode("always")
    import routes.prefs_routes as prefs
    monkeypatch.setattr(prefs, "_load_for_user", lambda u: {"reasoning_cache": "shadow"})
    assert roles.mode_for("ada") == "shadow"
    assert roles.mode_for(None) == "off"
    monkeypatch.setattr(prefs, "_load_for_user", lambda u: {"reasoning_cache": "bogus"})
    assert roles.mode_for("ada") == "off"
    monkeypatch.setattr(prefs, "_load_for_user", lambda u: {})
    assert roles.mode_for("ada") == "off"
