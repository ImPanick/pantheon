# SPDX-License-Identifier: AGPL-3.0-or-later
r"""`B1916`. A model's answer of unclosed `<think>` tags held the server for minutes.

Six places read a model's JSON answer after dropping its closed `<think>` and
`<thinking>` blocks with a lazy `re.sub`: the skill test's judge, its
necessity and retrieval-precision checks and the skill rewrite
(`routes/skills_routes.py`), the memory tidy (`audit_memories`) and the chat
tidy (`POST /api/sessions/auto-sort`). The lazy body went back to the end of
the answer from every opener that had no closer, so the time grew with the
square of the answer: 12,000 openers (84 KB, inside the judge's 32,768-token
budget) took 10 to 12 seconds in each place on the loaded test machine, and
26 in the judge, which reads its answer twice. A model steered by a skill's
text or by a chat's title can answer that way, and the regex holds the GIL,
so every request waited.

Now each place calls `src.text_helpers.strip_closed_think_blocks`, which drops
the same blocks in one forward pass on the scan `strip_think` already uses
(`_sub_delimited`, `Law 14`). Upstream Odysseus 3d91ad82 changed the first
five places; the chat tidy's copy is Pantheon's. The helper is compared with
the old pattern; each place is driven with a stand-in model that answers the
flood, and each of those fails on the old code.
"""
from __future__ import annotations

import ast
import asyncio
import json
import random
import re
import time
from datetime import datetime
from pathlib import Path

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import NullPool

import core.database as cdb
import routes.skills_routes as skills_routes
import services.memory.memory_extractor as memory_extractor
from core.database import ChatMessage as DbMessage
from core.database import Session as DbSession
from src.memory import MemoryManager

ROOT = Path(__file__).resolve().parents[1]
# The pattern the six places used before `B1916`.
_LAZY = r"<think(?:ing)?>[\s\S]*?</think(?:ing)?>"
_REFERENCE = re.compile(_LAZY, re.IGNORECASE)
_FLOOD = "<think>" * 12_000
_BUDGET_S = 2.0  # the old pattern took 10 s and more on _FLOOD; the helper takes milliseconds


class _Model:
    """A stand-in model that gives one answer and notes when it first gave it."""

    def __init__(self, answer):
        self.answer = answer
        self.first_answered = None

    def _give(self):
        if self.first_answered is None:
            self.first_answered = time.perf_counter()
        return self.answer

    async def call_async(self, *_a, **_k):
        return self._give()

    def call(self, *_a, **_k):
        return self._give()

    def seconds_since_it_answered(self):
        return time.perf_counter() - self.first_answered


# ── the helper reads exactly what the old pattern read ──────────────────────

@pytest.mark.parametrize("text", [
    "",
    "plain",
    "<think>x</think>{\"ok\": true}",
    "a<thinking>b</thinking>c<think>d</think>e",
    "<think>a<think>nested</think>rest</think>",
    "orphan</think> then <think>unclosed",
    "<THINK>case</Thinking>kept",
    "<think>\nmulti\nline\n</think>\n{}",
    "<think time=\"0.4\">attr</think>kept",
    "</think></think><think>a</thinking><thinking>",
])
def test_the_helper_drops_exactly_what_the_old_pattern_dropped(text):
    from src.text_helpers import strip_closed_think_blocks

    assert strip_closed_think_blocks(text) == _REFERENCE.sub("", text)


def test_random_answers_lose_exactly_what_the_old_pattern_took():
    from src.text_helpers import strip_closed_think_blocks

    pieces = ["<think>", "<THINKING>", "</think>", "</Thinking>", "<thin", "k>", "<", ">",
              "/", "x", " ", "\n", "{\"verdict\": \"pass\"}", "ing>"]
    rng = random.Random(1916)
    for _ in range(3000):
        text = "".join(rng.choice(pieces) for _ in range(rng.randint(0, 30)))
        assert strip_closed_think_blocks(text) == _REFERENCE.sub("", text), repr(text)


def test_the_helper_reads_a_flood_of_openers_in_one_pass():
    from src.text_helpers import strip_closed_think_blocks

    flood = "<think>" * 40_000
    started = time.perf_counter()
    assert strip_closed_think_blocks(flood) == flood
    assert time.perf_counter() - started < _BUDGET_S


# ── each place that used the old pattern, driven ────────────────────────────

_SKILL = "---\nname: tidy-downloads\ndescription: tidy\n---\n1. Sort the files."
_JUDGES = {
    "skill-judge": lambda: skills_routes._eval_skill_run(
        _SKILL, "task", "transcript", "http://model.test", "scripted", {}),
    "necessity-check": lambda: skills_routes._eval_skill_necessity(
        _SKILL, [], "http://model.test", "scripted", {}),
    "retrieval-check": lambda: skills_routes._eval_skill_retrieval_precision(
        _SKILL, [], "http://model.test", "scripted", {}),
    "skill-rewrite": lambda: skills_routes._improve_skill_md(
        _SKILL, {"summary": "vague", "issues": ["step 1 is vague"]}, "transcript",
        "http://model.test", "scripted", {}),
}
_UNREAD = {
    "skill-judge": lambda out: out["verdict"] == "unknown"
    and out["summary"] == "The judge's answer could not be read — try again.",
    "necessity-check": lambda out: out is None,
    "retrieval-check": lambda out: out is None,
    "skill-rewrite": lambda out: out is None,
}


@pytest.mark.parametrize("name", list(_JUDGES))
def test_a_skill_judge_reads_a_flood_of_openers_in_one_pass(monkeypatch, name):
    model = _Model(_FLOOD)
    monkeypatch.setattr("src.llm_core.llm_call_async", model.call_async)
    out = asyncio.run(_JUDGES[name]())
    assert model.seconds_since_it_answered() < _BUDGET_S
    assert _UNREAD[name](out), out


def test_the_skill_judge_still_reads_past_a_think_block(monkeypatch):
    """The block after the answer holds a verdict that would win if it stayed."""
    model = _Model('{"verdict": "pass", "confidence": 0.9, "summary": "works", "issues": []}'
                   '<think>{"verdict": "fail", "summary": "decoy"}</think>')
    monkeypatch.setattr("src.llm_core.llm_call_async", model.call_async)
    out = asyncio.run(_JUDGES["skill-judge"]())
    assert (out["verdict"], out["summary"]) == ("pass", "works")


@pytest.fixture()
def store(tmp_path):
    manager = MemoryManager(str(tmp_path))
    manager.save([manager.add_entry("The user keeps sourdough starter in the fridge",
                                    source="auto", confidence=0.8)])
    return manager


def test_the_memory_tidy_reads_a_flood_of_openers_in_one_pass(monkeypatch, store):
    model = _Model(_FLOOD)
    monkeypatch.setattr("src.llm_core.llm_call_async", model.call_async)
    out = asyncio.run(memory_extractor.audit_memories(store, None, "http://x", "m"))
    assert model.seconds_since_it_answered() < _BUDGET_S
    assert out["error"] == "bad_json"


def test_the_memory_tidy_still_reads_past_a_think_block(monkeypatch, store):
    entry = store.load_all()[0]
    model = _Model(f'<think>[{{"id": "{entry["id"]}", "text": "decoy"}}]</think>'
                   + json.dumps([{"id": entry["id"], "text": "Keeps sourdough starter in the fridge",
                                  "category": "fact"}]))
    monkeypatch.setattr("src.llm_core.llm_call_async", model.call_async)
    out = asyncio.run(memory_extractor.audit_memories(store, None, "http://x", "m"))
    assert "error" not in out, out
    assert [row["text"] for row in store.load_all()] == ["Keeps sourdough starter in the fridge"]


_CHATS = {"ann-0001-aaaa": "Sourdough starter", "ann-0002-bbbb": "Rye loaf",
          "ann-0003-cccc": "Bike gears"}


@pytest.fixture()
def chat_tidy(monkeypatch, tmp_path):
    """The real auto-sort handler over a real SQLite file; only its model is a stand-in."""
    import core.session_manager as smod
    import routes.session_routes as session_routes
    import src.llm_core as llm_core
    import src.task_endpoint as task_endpoint

    engine = create_engine(f"sqlite:///{tmp_path / 'app.db'}",
                           connect_args={"check_same_thread": False}, poolclass=NullPool)
    cdb.Base.metadata.create_all(engine)
    factory = sessionmaker(bind=engine, autoflush=False, autocommit=False)
    for mod in (smod, session_routes, cdb):
        monkeypatch.setattr(mod, "SessionLocal", factory)
    db = factory()
    t = datetime(2026, 1, 1)
    for sid, name in _CHATS.items():
        db.add(DbSession(id=sid, owner="ann", name=name, endpoint_url="x", model="m",
                         created_at=t, updated_at=t, last_accessed=t, last_message_at=t))
        for i in range(4):
            db.add(DbMessage(id=f"{sid}-{i}", session_id=sid,
                             role="user" if i % 2 == 0 else "assistant",
                             content=f"{name} {i}", timestamp=t))
    db.commit()
    db.close()
    monkeypatch.setattr(session_routes, "effective_user", lambda request: "ann")
    monkeypatch.setattr(task_endpoint, "resolve_task_endpoint",
                        lambda *a, **k: ("http://u/v1", "utility", {}))
    app = FastAPI()
    app.include_router(session_routes.setup_session_routes(smod.SessionManager(), {}))

    def tidy(answer):
        model = _Model(answer)
        monkeypatch.setattr(llm_core, "llm_call", model.call)
        return TestClient(app).post("/api/sessions/auto-sort"), model

    return tidy


def test_the_chat_tidy_reads_a_flood_of_openers_in_one_pass(chat_tidy):
    res, model = chat_tidy(_FLOOD)
    assert model.seconds_since_it_answered() < _BUDGET_S
    assert res.status_code == 502, res.text


def test_the_chat_tidy_still_reads_past_a_think_block(chat_tidy):
    res, _model = chat_tidy('<think>{"folders": {"Wrong": ["ann-0001"]}}</think>'
                            + json.dumps({"folders": {"Baking": ["ann-0001", "ann-0002"],
                                                      "Bikes": ["ann-0003"]}}))
    assert res.status_code == 200, res.text
    assert sorted(res.json()["folders"]) == ["Baking", "Bikes"]


def test_no_answer_parser_passes_the_lazy_pattern_to_a_call():
    """`Law 20`: looked for in the arguments of calls, not in comments or prose."""
    for rel in ("routes/skills_routes.py", "services/memory/memory_extractor.py",
                "routes/session_routes.py"):
        tree = ast.parse((ROOT / rel).read_text(encoding="utf-8"))
        found = [arg.lineno for node in ast.walk(tree) if isinstance(node, ast.Call)
                 for arg in [*node.args, *(k.value for k in node.keywords)]
                 if isinstance(arg, ast.Constant) and isinstance(arg.value, str) and _LAZY in arg.value]
        assert not found, f"{rel} still passes the lazy pattern at lines {found}"
