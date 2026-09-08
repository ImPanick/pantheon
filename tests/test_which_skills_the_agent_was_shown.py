# SPDX-License-Identifier: AGPL-3.0-or-later
r"""`P4-16` — up to a dozen procedures enter a request and nothing said which.

The row's words: *"The loop knows all of it and emits none."* A skill is a
procedure the agent is told to follow, written by the user or by a **teacher
model after a prior failure**, and until now the only way to know which ones
were in front of the model was to reason about the store yourself.

Two things had to be true before the report could be honest:

  **the index had to carry its own provenance.** `index_for` returned name,
  description, category and status. "Written by the teacher escalation loop
  after a failure, by *this* model" is the part that matters when the answer
  turns out to be wrong, and it was not in there.

  **there had to be one answer.** In agent mode the index is injected **twice**
  — once by the chat preface and once by the agent loop — and the two are gated
  differently, which is `B60`. Reporting both separately would list the same
  procedure twice and make the count meaningless, so they are merged by name and
  `via` records every site that showed it. When `B60` is fixed one site stops
  contributing and the merged list does not change shape, which is the whole
  reason it merges rather than concatenates.
"""

import asyncio
import json
import tempfile
from pathlib import Path

import pytest

import src.agent_loop as agent_loop
from services.memory.skills import SkillsManager


def _write_skill(root: Path, name: str, *, category="general", source="learned",
                 status="published", teacher="", requires=""):
    d = root / category / name
    d.mkdir(parents=True, exist_ok=True)
    fm = ["---", f"name: {name}", "description: a test procedure", "version: 1.0.0",
          f"category: {category}", "tags: []"]
    if requires:
        fm.append(f"requires_toolsets: [{requires}]")
    if teacher:
        fm.append(f"teacher_model: {teacher}")
    fm += [f"status: {status}", "confidence: 0.9", f"source: {source}",
           "created: 2026-01-01T00:00:00Z", "---", "",
           "## When to Use", "- a test", "", "## Procedure", "1. do it", ""]
    (d / "SKILL.md").write_text("\n".join(fm), encoding="utf-8")


# ── the index carries its provenance ──────────────────────────────────────────


@pytest.fixture
def store(tmp_path):
    root = tmp_path / "skills"
    _write_skill(root, "tidy-logs", category="ops")
    _write_skill(root, "retry-with-backoff", category="general",
                 source="teacher-escalation", status="draft", teacher="big-teacher:70b")
    return SkillsManager(str(tmp_path))


def test_the_index_says_where_each_procedure_came_from(store):
    entries = {e["name"]: e for e in store.index_for()}
    assert entries["tidy-logs"]["source"] == "learned"
    assert entries["retry-with-backoff"]["source"] == "teacher-escalation"


def test_the_index_names_the_teacher_that_wrote_one(store):
    # The sharpest part of the row. A procedure a model wrote after watching a
    # smaller model fail is a different kind of claim from one a person wrote,
    # and which model wrote it is what you need when it turns out to be wrong.
    entries = {e["name"]: e for e in store.index_for()}
    assert entries["retry-with-backoff"]["teacher_model"] == "big-teacher:70b"
    assert entries["tidy-logs"]["teacher_model"] == ""


@pytest.fixture
def loop_store(tmp_path, monkeypatch):
    """Point the agent loop's own skill store at a tree we control.

    `_build_base_prompt` builds its `SkillsManager` from `src.constants.DATA_DIR`
    at call time, so this is the seam. Without it every assertion about the
    loop's half of the index is made against whatever happens to be on this
    machine — which is how a test comes to pass by describing an empty list.
    """
    import src.constants as constants
    root = tmp_path / "skills"
    _write_skill(root, "tidy-logs", category="ops")
    _write_skill(root, "retry-with-backoff", category="general",
                 source="teacher-escalation", status="draft", teacher="big-teacher:70b")
    monkeypatch.setattr(constants, "DATA_DIR", str(tmp_path), raising=False)
    monkeypatch.setattr(agent_loop, "_cached_base_prompt", None, raising=False)
    monkeypatch.setattr(agent_loop, "_cached_base_prompt_key", None, raising=False)
    return tmp_path


def _loop_index(**kwargs):
    report: dict = {}
    _, block = agent_loop._build_base_prompt(
        [], None, False, owner=None, suppress_local_context=False,
        suppress_skills=False, context_report=report, **kwargs,
    )
    return block, report.get("skill_index") or []


def test_the_loop_reports_the_index_it_injected(loop_store):
    block, used = _loop_index()
    assert "tidy-logs" in block, "the fixture did not reach the prompt builder"
    by_name = {e["name"]: e for e in used}
    assert set(by_name) == {"tidy-logs", "retry-with-backoff"}
    assert all(e["via"] == "agent" for e in used), (
        "the loop's own entries are attributed to the wrong site"
    )


def test_the_loop_carries_the_provenance_too(loop_store):
    _, used = _loop_index()
    taught = next(e for e in used if e["name"] == "retry-with-backoff")
    assert taught["source"] == "teacher-escalation"
    assert taught["teacher_model"] == "big-teacher:70b"
    assert taught["status"] == "draft"
    assert taught["category"] == "general"


def test_the_prompt_still_reads_only_the_three_fields_it_always_did(loop_store):
    # The index goes into the model's context. Adding reporting fields to it
    # must not add anything to the prompt, or this row changed what the agent
    # sees in order to describe what the agent sees.
    block, used = _loop_index()
    assert used, "nothing was injected, so this asserts nothing"
    assert "big-teacher:70b" not in block
    assert "teacher_model" not in block
    # The block's own framing paragraph names the teacher-escalation loop as
    # prose — that is the explanation of the `(draft)` badge, not a field — so
    # the assertion is on the skill *lines*, which are what carry per-skill
    # data. Asserting on the whole block instead would have been a test of my
    # own sentence (Law 20), and it failed that way first.
    entries = [ln for ln in block.splitlines() if ln.startswith("- `")]
    assert entries, "no skill lines in the block, so this asserts nothing"
    for line in entries:
        assert "source" not in line and "escalation" not in line
    # …and what it always did read is still there.
    assert "tidy-logs" in block and "a test procedure" in block


def test_the_prompt_builder_hands_the_index_back_to_its_caller(loop_store):
    # The out-parameter is how the loop learns what the prompt contained
    # without asking the store a second time.
    report: dict = {}
    agent_loop._build_system_prompt(
        [{"role": "user", "content": "hi"}], "small-local-model", None, None,
        disabled_tools=set(), owner=None, context_report=report,
    )
    assert {e["name"] for e in report.get("skill_index") or []} == {
        "tidy-logs", "retry-with-backoff"}


def test_a_caller_that_wants_no_report_gets_no_surprises(loop_store):
    # Every other caller of `_build_system_prompt` passes nothing.
    messages = agent_loop._build_system_prompt(
        [{"role": "user", "content": "hi"}], "small-local-model", None, None,
        disabled_tools=set(), owner=None,
    )
    assert messages and isinstance(messages, tuple) or isinstance(messages, (list, tuple))


def test_suppressing_the_index_suppresses_the_report(loop_store):
    # A report of what was injected has to be empty when nothing was.
    report: dict = {}
    _, block = agent_loop._build_base_prompt(
        [], None, False, owner=None, suppress_local_context=False,
        suppress_skills=True, context_report=report,
    )
    assert block == "" and report["skill_index"] == []


# ── one answer, not two ───────────────────────────────────────────────────────


def test_the_two_injection_sites_report_as_one_list():
    # `B60`. Both sites inject the same index and neither knows about the other,
    # so a naive report lists every skill twice.
    merged = agent_loop._merge_injected_skills(
        [{"name": "tidy-logs", "category": "ops", "via": "preface"}],
        [{"name": "tidy-logs", "category": "ops", "via": "agent"}],
    )
    assert len(merged) == 1
    assert merged[0]["via"] == ["preface", "agent"]


def test_a_skill_only_one_site_showed_says_which_one():
    # The toolset-gated site hides a skill whose required toolset is off; the
    # ungated one does not. Recording which site showed a procedure is what
    # makes that difference visible instead of averaged away.
    merged = agent_loop._merge_injected_skills(
        [{"name": "needs-bash", "via": "preface"}],
        [{"name": "always", "via": "agent"}],
    )
    by_name = {e["name"]: e for e in merged}
    assert by_name["needs-bash"]["via"] == ["preface"]
    assert by_name["always"]["via"] == ["agent"]


def test_the_merge_survives_the_junk_a_wire_can_carry():
    merged = agent_loop._merge_injected_skills(
        None, [], [None, "a string", {}, {"name": "  "}, {"name": "real", "via": "agent"}],
    )
    assert [e["name"] for e in merged] == ["real"]


def test_the_same_site_twice_does_not_double_its_own_entry():
    merged = agent_loop._merge_injected_skills(
        [{"name": "x", "via": "agent"}, {"name": "x", "via": "agent"}],
    )
    assert len(merged) == 1 and merged[0]["via"] == ["agent"]


def test_the_merged_list_is_ordered_and_not_whatever_arrived_first():
    merged = agent_loop._merge_injected_skills(
        [{"name": "zeta", "category": "ops", "via": "agent"},
         {"name": "alpha", "category": "ops", "via": "agent"},
         {"name": "beta", "category": "general", "via": "agent"}],
    )
    assert [e["name"] for e in merged] == ["beta", "alpha", "zeta"]


# ── the report reaches the user ───────────────────────────────────────────────


def _events(generator):
    async def _drain():
        return [chunk async for chunk in generator]

    events = []
    for chunk in asyncio.run(_drain()):
        if not chunk.startswith("data: ") or chunk.startswith("data: [DONE]"):
            continue
        try:
            events.append(json.loads(chunk[6:]))
        except json.JSONDecodeError:
            pass
    return events


def _patch(monkeypatch, replies):
    monkeypatch.setattr(agent_loop, "get_setting", lambda k, d=None: d, raising=False)
    monkeypatch.setattr(agent_loop, "get_mcp_manager", lambda: None, raising=False)
    monkeypatch.setattr(agent_loop, "estimate_tokens", lambda *a, **k: 10, raising=False)
    monkeypatch.setattr(agent_loop, "blocked_tools_for_owner", lambda o: set(), raising=False)
    it = iter(replies)

    async def fake_stream(*a, **k):
        yield f"data: {json.dumps({'delta': next(it, 'Done.')})}\n\n"
        yield "data: [DONE]\n\n"

    async def fake_execute(block, *a, **k):
        return (block.tool_type, {"output": "ok", "exit_code": 0})

    monkeypatch.setattr(agent_loop, "stream_llm_with_fallback", fake_stream, raising=False)
    monkeypatch.setattr(agent_loop, "execute_tool_block", fake_execute, raising=False)


def _run(monkeypatch, *, preface_skills=None):
    _patch(monkeypatch, ["Done."])
    return _events(
        agent_loop.stream_agent_loop(
            "http://local.test/v1", "small-local-model",
            [{"role": "user", "content": "do the thing"}],
            max_rounds=1, relevant_tools={"bash"},
            preface_injected_skills=preface_skills,
        )
    )


PREFACE_HALF = [
    {"name": "tidy-logs", "category": "ops", "status": "published",
     "source": "learned", "teacher_model": "", "via": "preface"},
    {"name": "retry-with-backoff", "category": "general", "status": "draft",
     "source": "teacher-escalation", "teacher_model": "big-teacher:70b",
     "via": "preface"},
]


def test_the_stream_says_which_skills_were_injected(monkeypatch):
    events = _run(monkeypatch, preface_skills=PREFACE_HALF)
    reported = [e for e in events if e.get("type") == "skills_injected"]
    assert reported, "the loop still emits nothing about the skills it was given"
    names = {s["name"] for s in reported[0]["data"]}
    assert {"tidy-logs", "retry-with-backoff"} <= names


def test_the_report_carries_the_provenance_the_row_asks_for(monkeypatch):
    events = _run(monkeypatch, preface_skills=PREFACE_HALF)
    by_name = {s["name"]: s
               for s in next(e for e in events
                             if e.get("type") == "skills_injected")["data"]}
    taught = by_name["retry-with-backoff"]
    assert taught["source"] == "teacher-escalation"
    assert taught["teacher_model"] == "big-teacher:70b"
    assert taught["status"] == "draft"


def test_it_is_reported_once_and_before_the_agent_starts_working(monkeypatch):
    # It is context, not something the agent did, and a card that arrives after
    # the first step reads as an action.
    events = _run(monkeypatch, preface_skills=PREFACE_HALF)
    types = [e.get("type") for e in events]
    assert types.count("skills_injected") == 1
    first = types.index("skills_injected")
    for later in ("agent_step", "tool_start"):
        if later in types:
            assert first < types.index(later)


def test_a_turn_with_no_skills_reports_nothing(monkeypatch):
    # Silence is the honest report for an empty list, and a pill reading
    # "0 skills" on every message is noise the footer does not need.
    events = _run(monkeypatch, preface_skills=[])
    assert not [e for e in events if e.get("type") == "skills_injected"]


def test_the_reloaded_thread_says_what_the_live_one_did(monkeypatch):
    # Same invariant as `P4-11` and `P4-09`: one action, two surfaces, one
    # answer. Without the metrics key the pill vanishes on refresh.
    events = _run(monkeypatch, preface_skills=PREFACE_HALF)
    live = next(e for e in events if e.get("type") == "skills_injected")["data"]
    metrics = next(e for e in events if e.get("type") == "metrics")["data"]
    assert metrics.get("skills_injected") == live


def test_the_report_does_not_reach_into_the_prompt(monkeypatch):
    # The report describes the context; it must not become part of it.
    _patch(monkeypatch, ["Done."])
    seen = {}

    async def capture(*a, **k):
        # `stream_llm_with_fallback` is called entirely by keyword here, so
        # positional unpacking is what breaks; take everything and look for the
        # message array wherever it arrived.
        seen["messages"] = k.get("messages") or (a[2] if len(a) > 2 else [])
        yield f"data: {json.dumps({'delta': 'Done.'})}\n\n"
        yield "data: [DONE]\n\n"

    monkeypatch.setattr(agent_loop, "stream_llm_with_fallback", capture, raising=False)
    _events(
        agent_loop.stream_agent_loop(
            "http://local.test/v1", "small-local-model",
            [{"role": "user", "content": "do the thing"}],
            max_rounds=1, relevant_tools={"bash"},
            preface_injected_skills=PREFACE_HALF,
        )
    )
    blob = json.dumps(seen.get("messages") or [])
    assert "skills_injected" not in blob
    assert "big-teacher:70b" not in blob, (
        "the preface's reporting half leaked into the model's context"
    )


def test_a_caller_that_knows_nothing_of_this_still_works(monkeypatch):
    # Five other callers reach `stream_agent_loop` — the skill runner, the
    # background monitor, the teacher, the scheduler, compare mode — and none
    # of them passes a preface list.
    events = _run(monkeypatch)
    assert [e for e in events if e.get("type") == "metrics"], "the stream did not finish"


# ── the pill ──────────────────────────────────────────────────────────────────


_REPO = Path(__file__).resolve().parent.parent


def test_the_footer_popover_is_written_once():
    # `Law 14`. The memory pill grew ~50 lines of viewport arithmetic and the
    # skills pill needs exactly that; two copies of "flip above or below, clamp
    # to the edge, dismiss on Escape" drift.
    src = (_REPO / "static" / "js" / "chatRenderer.js").read_text(encoding="utf-8")
    assert src.count("export function bindFooterPopover") == 1
    assert src.count("getBoundingClientRect()") >= 1
    body_start = src.index("export function bindFooterPopover")
    body = src[body_start:body_start + 3000]
    assert "window.innerHeight" in body and "window.innerWidth" in body
    before = src[:body_start]
    assert "window.innerHeight - pillRect.bottom" not in before, (
        "a second copy of the popover positioning survives outside the helper"
    )


@pytest.mark.parametrize("hook", ["_skillsInjected", "skills_injected"])
def test_both_surfaces_feed_the_pill(hook):
    # The live stream sets it over SSE and a reloaded thread reads it off the
    # saved metadata; the pill is the same either way.
    renderer = (_REPO / "static" / "js" / "chatRenderer.js").read_text(encoding="utf-8")
    chat = (_REPO / "static" / "js" / "chat.js").read_text(encoding="utf-8")
    assert hook in renderer or hook in chat
    assert renderer.count("_skillsInjected") >= 2, "history replay does not set it"
    assert "skills_injected" in chat, "the live stream does not read the event"
