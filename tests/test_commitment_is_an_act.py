# SPDX-License-Identifier: AGPL-3.0-or-later
"""`P13-05` — commitment as an explicit act, so *committed to memory* means something.

The phase preamble names the failure this exists to prevent, from a shipped
competitor: **"Their 'Avoid' list contains raw venting, promoted to a rule at
95%."** Verbatim frustration sitting in a behavioural policy list at high
confidence, because extraction and commitment were the same event. The preamble's
own conclusion is the row: *extraction should propose; only promotion should
bind.*

**`Law 14` first, and it changed the shape of the work.** The proposal state is
not invented here — `services/memory/skill_extractor.py` has shipped
`status: draft | published` with an `auto_approve_skills` preference since long
before the Brain had one, and the audit can demote a skill back to draft. That is
the same mechanism on the other half of the feature, and this row lifts it across
exactly the way `P13-01` lifted the confidence floor: same shape, same default,
one fewer concept to learn.

**Legacy memories read `committed`, and that is not the same call `P13-01` and
`P13-15` made.** They defaulted to *not recorded*, because a number invented for
a record nobody assessed makes an old memory look freshly checked. Status is the
opposite: every memory already in a store today **is** binding — it is being
injected into prompts right now — so `committed` is the true answer and
`proposed` would be a silent amnesia that stopped the Brain working on upgrade.
"""

import time

import pytest

from src import memory_edges, memory_retrieval
from src.memory import MemoryManager
from services.memory.memory_extractor import commit_memory


@pytest.fixture
def manager(tmp_path):
    return MemoryManager(str(tmp_path))


def mem(mid, text, **extra):
    row = {"id": mid, "text": text, "category": "fact", "timestamp": 1780000000}
    row.update(extra)
    return row


def ids(rows):
    return [row["id"] for row in rows]


# ── the state ─────────────────────────────────────────────────────────────────

def test_a_memory_written_before_this_row_is_committed_not_proposed():
    # The upgrade path, and the only default that is honest. Everything in a
    # store today is already being injected; calling it a proposal would stop
    # the Brain working the moment this shipped, and it would be a lie about
    # what those records are.
    assert memory_edges.status_of({"text": "User drives a van"}) == \
        memory_edges.STATUS_COMMITTED
    assert memory_edges.is_committed({"text": "User drives a van"})


def test_a_store_written_before_this_row_still_works(tmp_path):
    """The migration proof, for the store the memories are actually in.

    `P13-03` re-measured and held the phase's store correction: memory lives in
    `data/memory.json`, and the SQL `memories` table has no reader that returns
    content — re-measured again at `ad7c6f3` and it is **three** non-test
    readers now, not two (`core/database.py` count, `src/builtin_actions.py`,
    and `routes/admin_wipe` count + delete), none of which reads a memory to
    answer anything. So this row adds no column and needs no `ALTER TABLE`, and
    the equivalent obligation — *prove it against a store created without the
    field* — is this test: a file written by a build that had never heard of
    `status`, opened by one that has.
    """
    import json

    legacy = tmp_path / "memory.json"
    legacy.write_text(json.dumps([
        {"id": "a", "text": "User is allergic to shellfish", "timestamp": 1},
        {"id": "b", "text": "User drives a diesel van", "timestamp": 2},
    ]), encoding="utf-8")

    store = MemoryManager(str(tmp_path))
    rows = store.load_all()
    assert [r["status"] for r in rows] == [memory_edges.STATUS_COMMITTED] * 2
    # And they still answer questions, which is the half a status field could
    # silently break for every existing install.
    assert ids(memory_retrieval.retrieve("what van do I drive", rows, k=5)) == ["b"]


def test_a_status_nobody_recognises_is_read_as_committed():
    # A memory store is a file a person can edit. An unreadable status must not
    # make a memory vanish from every prompt — the failure has to be visible,
    # and "it stopped remembering" is the least visible failure there is.
    assert memory_edges.status_of(mem("a", "x", status="banana")) == \
        memory_edges.STATUS_COMMITTED


def test_a_person_typing_into_the_brain_is_already_the_explicit_act(manager):
    # `P13-01` made the matching call for confidence: a person writing a memory
    # is not a producer anybody has to second-guess. They did the act; asking
    # them to do it twice is a modal dialog, not a quality gate.
    assert manager.add_entry("User drives a van")["status"] == \
        memory_edges.STATUS_COMMITTED


# ── what a proposal does not do ───────────────────────────────────────────────

def test_a_proposal_does_not_change_an_answer():
    corpus = [mem("live", "User drives a diesel van for site visits"),
              mem("draft", "User drives a van on Tuesdays",
                  status=memory_edges.STATUS_PROPOSED)]
    assert ids(memory_retrieval.retrieve("what van do I drive", corpus, k=5)) == ["live"]


def test_a_proposal_is_excluded_by_the_same_predicate_that_hides_an_archived_one():
    # `P13-09` archives what an audit merged away and `memory_edges.live` is
    # documented as the one place that decides what still surfaces: "records
    # kept on purpose that must not be shown, re-audited, re-indexed or
    # counted". A proposal is exactly that, so it is the same predicate and not
    # a second one — which also means the boot-time vector rebuild in
    # `src/app_initializer.py` excludes proposals without being edited.
    rows = [mem("live", "a"), mem("draft", "b", status=memory_edges.STATUS_PROPOSED)]
    assert ids(memory_edges.live(rows)) == ["live"]


def test_a_proposal_is_hidden_even_when_nothing_is_superseded():
    # The guard `if graph["superseded"]` used to short-circuit the whole filter,
    # so on the overwhelmingly common corpus — no edges at all — a proposal
    # would have gone straight into the prompt.
    corpus = [mem("draft", "User drives a diesel van",
                  status=memory_edges.STATUS_PROPOSED)]
    assert memory_retrieval.retrieve("what van do I drive", corpus, k=5) == []


# ── the act, and the gate on it ───────────────────────────────────────────────

def test_committing_a_proposal_binds_it(manager):
    manager.save([mem("draft", "User is allergic to shellfish",
                      status=memory_edges.STATUS_PROPOSED)])
    result = commit_memory(manager, "draft", by="felix")
    assert result["verdict"] == "committed"
    entry = manager.load_all()[0]
    assert entry["status"] == memory_edges.STATUS_COMMITTED
    assert entry["committed_by"] == "felix"
    assert entry["committed_at"] >= 1


def test_a_committed_memory_answers_a_question_the_proposal_did_not(manager):
    manager.save([mem("draft", "User is allergic to shellfish",
                      status=memory_edges.STATUS_PROPOSED)])
    corpus = manager.load_all()
    assert memory_retrieval.retrieve("allergic", corpus, k=5) == []
    commit_memory(manager, "draft", by="felix")
    assert ids(memory_retrieval.retrieve("allergic", manager.load_all(), k=5)) == ["draft"]


def test_the_verdict_is_an_enum_and_never_a_boolean(manager):
    # `Law 10`. `ok: true/false` beside a reason is read two ways — "the commit
    # worked" and "the memory was acceptable" — and the automation downstream
    # picks the wrong one while every step looks right.
    manager.save([mem("draft", "x" * 20, status=memory_edges.STATUS_PROPOSED)])
    assert commit_memory(manager, "draft", by="f")["verdict"] in ("committed", "refused")
    assert "ok" not in commit_memory(manager, "draft", by="f")


def test_committing_something_already_committed_is_refused_and_says_so(manager):
    manager.save([mem("done", "User drives a van")])
    result = commit_memory(manager, "done", by="felix")
    assert result["verdict"] == "refused"
    assert "already" in result["reason"].lower()


def test_an_unknown_id_is_refused_rather_than_silently_doing_nothing(manager):
    manager.save([mem("a", "User drives a van")])
    assert commit_memory(manager, "nope", by="felix")["verdict"] == "refused"


def test_an_empty_proposal_cannot_be_committed(manager):
    manager.save([mem("draft", "   ", status=memory_edges.STATUS_PROPOSED)])
    result = commit_memory(manager, "draft", by="felix")
    assert result["verdict"] == "refused"
    assert manager.load_all()[0]["status"] == memory_edges.STATUS_PROPOSED


def test_a_proposal_that_restates_a_committed_memory_is_refused(manager):
    # The gate that does real work. Promoting a restatement is how a Brain
    # fills with four sentences saying the same thing, which is then the audit's
    # problem — and the audit is an LLM round the person pays for.
    manager.save([mem("live", "User is allergic to shellfish"),
                  mem("draft", "User is allergic to shellfish",
                      status=memory_edges.STATUS_PROPOSED)])
    result = commit_memory(manager, "draft", by="felix")
    assert result["verdict"] == "refused"
    assert result["duplicate_of"] == "live"


def test_a_refused_restatement_is_recorded_as_evidence_rather_than_dropped(manager):
    # `P13-15`'s lesson applied to this gate: the moment a fact is confirmed is
    # exactly the moment the observation gets thrown away. Somebody proposing
    # the same thing again is a mention of the memory that already says it.
    manager.save([mem("live", "User is allergic to shellfish", mentions=0),
                  mem("draft", "User is allergic to shellfish",
                      status=memory_edges.STATUS_PROPOSED)])
    commit_memory(manager, "draft", by="felix")
    live = next(m for m in manager.load_all() if m["id"] == "live")
    assert live["mentions"] == 1


def test_a_near_duplicate_is_caught_by_the_function_that_already_answers_that(manager):
    # `_text_duplicate_of`, not a second comparison. Its limit is stated rather
    # than left to be discovered: Jaccard at 0.6 catches a restatement and not a
    # rewording, which `P13-09` already documents.
    manager.save([mem("live", "User is allergic to shellfish"),
                  mem("draft", "User is allergic to shellfish badly",
                      status=memory_edges.STATUS_PROPOSED)])
    assert commit_memory(manager, "draft", by="felix")["verdict"] == "refused"


def test_the_gate_does_not_re_apply_the_confidence_floor(manager):
    # Deliberate, and it is the standing principle `D-2026-09-09-01` names for
    # the fourth time: a thing a person typed beats a thing the system
    # inferred. The floor belongs at extraction, where nobody has looked yet.
    # Re-applying it here would mean a person cannot commit a memory they have
    # read and decided to keep, which is the one act this row exists to honour.
    manager.save([mem("draft", "User is allergic to shellfish",
                      confidence=0.05, status=memory_edges.STATUS_PROPOSED)])
    assert commit_memory(manager, "draft", by="felix")["verdict"] == "committed"


def test_a_refusal_changes_nothing_on_the_record(manager):
    manager.save([mem("live", "User is allergic to shellfish"),
                  mem("draft", "User is allergic to shellfish",
                      status=memory_edges.STATUS_PROPOSED)])
    commit_memory(manager, "draft", by="felix")
    draft = next(m for m in manager.load_all() if m["id"] == "draft")
    assert draft["status"] == memory_edges.STATUS_PROPOSED
    assert draft.get("committed_at") is None


def test_an_unreadable_store_refuses_rather_than_rewriting_it(manager, monkeypatch):
    # The `#5673` rule. A read-modify-write that degrades to `[]` saves one
    # memory over everything a person had, atomically — and the writes are
    # atomic, so the loss is durable.
    #
    # The proposal is really in the store and the REASON is asserted, not just
    # the verdict: a first draft of this test passed against a version that had
    # swapped the strict read for the lenient one, because an empty view made
    # the id look unknown and "no memory with that id" is also a refusal.
    from src.memory import MemoryStoreUnreadable

    manager.save([mem("draft", "User is allergic to shellfish",
                      status=memory_edges.STATUS_PROPOSED)])

    def _boom():
        raise MemoryStoreUnreadable("scanner holding the file")

    monkeypatch.setattr(manager, "load_all_for_update", _boom)
    result = commit_memory(manager, "draft", by="felix")
    assert result["verdict"] == "refused"
    assert "could not be read" in result["reason"]
    assert manager.load_all()[0]["status"] == memory_edges.STATUS_PROPOSED


# ── the halves that make it wired rather than built (`Law 13`) ────────────────

class _Session:
    session_id = "s1"
    owner = "felix"

    @staticmethod
    def get_context_messages():
        return [{"role": "user", "content": "I am allergic to shellfish, remember that"},
                {"role": "assistant", "content": "Noted."}]


def _extract(manager, monkeypatch, prefs):
    """Run background extraction with the LLM stubbed and prefs stated."""
    import asyncio

    import services.memory.memory_extractor as mx

    monkeypatch.setattr("src.llm_core.llm_call_async", _fake_llm)
    monkeypatch.setitem(
        __import__("sys").modules, "routes.prefs_routes",
        type("m", (), {"_load_for_user": staticmethod(lambda owner=None: dict(prefs))}))
    asyncio.run(mx.extract_and_store(_Session(), manager, None,
                                     "http://x", "m", None))
    return manager.load_all()


async def _fake_llm(url, model, messages, **kwargs):
    return '[{"text": "User is allergic to shellfish", "category": "fact", ' \
           '"confidence": 0.9}]'


def test_extraction_binds_by_default_so_an_upgrade_changes_nothing(manager, monkeypatch):
    rows = _extract(manager, monkeypatch, {})
    assert rows, "nothing was extracted, so this test proves nothing"
    assert all(r["status"] == memory_edges.STATUS_COMMITTED for r in rows)


def test_extraction_only_proposes_when_the_person_turned_binding_off(manager, monkeypatch):
    rows = _extract(manager, monkeypatch, {"auto_approve_memories": False})
    assert rows, "nothing was extracted, so this test proves nothing"
    assert all(r["status"] == memory_edges.STATUS_PROPOSED for r in rows)
    # And it is genuinely out of the prompt, not merely labelled.
    assert memory_retrieval.retrieve("allergies", rows, k=5) == []


def test_the_preference_is_read_the_same_way_the_skill_one_is(monkeypatch, manager):
    # `Law 14`: the shape is lifted from `skill_extractor`'s auto-publish gate,
    # including that a prefs store which cannot be read leaves the default
    # alone rather than failing extraction.
    import services.memory.memory_extractor as mx

    def _explode(owner=None):
        raise RuntimeError("prefs unreadable")

    monkeypatch.setitem(__import__("sys").modules, "routes.prefs_routes",
                        type("m", (), {"_load_for_user": staticmethod(_explode)}))
    monkeypatch.setattr("src.llm_core.llm_call_async", _fake_llm)
    import asyncio
    asyncio.run(mx.extract_and_store(_Session(), manager, None, "http://x", "m", None))
    assert all(r["status"] == memory_edges.STATUS_COMMITTED for r in manager.load_all())


# ── the route ─────────────────────────────────────────────────────────────────

def _commit_route(manager, monkeypatch, caller="felix"):
    from types import SimpleNamespace
    from unittest.mock import MagicMock

    import routes.memory_routes as mr

    monkeypatch.setattr(mr, "get_current_user", lambda request: caller, raising=False)
    monkeypatch.setattr("src.auth_helpers.require_privilege",
                        lambda request, privilege: caller)
    sm = MagicMock()
    router = mr.setup_memory_routes(manager, sm)
    for route in router.routes:
        if route.path == "/api/memory/{memory_id}/commit":
            return route.endpoint
    raise AssertionError("no commit route")


def test_the_route_exists_and_binds(manager, monkeypatch):
    manager.save([mem("draft", "User is allergic to shellfish", owner="felix",
                      status=memory_edges.STATUS_PROPOSED)])
    endpoint = _commit_route(manager, monkeypatch)
    out = endpoint(request=None, memory_id="draft")
    assert out["verdict"] == "committed"
    assert manager.load_all()[0]["committed_by"] == "felix"


def test_the_route_refuses_rather_than_erroring_on_a_gate_decision(manager, monkeypatch):
    # A refusal is an answer. A 4xx would make the panel show a failure banner
    # for "the Brain already knows this", which is the most useful sentence the
    # gate can produce.
    manager.save([mem("live", "User is allergic to shellfish", owner="felix"),
                  mem("draft", "User is allergic to shellfish", owner="felix",
                      status=memory_edges.STATUS_PROPOSED)])
    out = _commit_route(manager, monkeypatch)(request=None, memory_id="draft")
    assert out["verdict"] == "refused"
    assert out["duplicate_of"] == "live"


def test_the_route_will_not_commit_another_tenants_proposal(manager, monkeypatch):
    import pytest as _pytest
    from fastapi import HTTPException

    manager.save([mem("draft", "Alice is allergic to shellfish", owner="alice",
                      status=memory_edges.STATUS_PROPOSED)])
    endpoint = _commit_route(manager, monkeypatch, caller="bob")
    with _pytest.raises(HTTPException) as exc:
        endpoint(request=None, memory_id="draft")
    assert exc.value.status_code == 404
    assert manager.load_all()[0]["status"] == memory_edges.STATUS_PROPOSED


def test_the_route_says_503_when_it_could_not_look_rather_than_404(manager, monkeypatch):
    # "There is no such memory" and "I could not read the store" are different
    # answers and only one of them tells the person to try again. A lenient read
    # here collapses the second into the first, which is how a transient file
    # lock becomes "that memory is gone".
    from fastapi import HTTPException

    from src.memory import MemoryStoreUnreadable

    manager.save([mem("draft", "User is allergic to shellfish", owner="felix",
                      status=memory_edges.STATUS_PROPOSED)])
    endpoint = _commit_route(manager, monkeypatch)

    def _boom():
        raise MemoryStoreUnreadable("scanner holding the file")

    monkeypatch.setattr(manager, "load_all_for_update", _boom)
    with pytest.raises(HTTPException) as exc:
        endpoint(request=None, memory_id="draft")
    assert exc.value.status_code == 503


# ── "and can be audited afterwards", which is the row's own second clause ─────

def _recorded(monkeypatch):
    rows = []
    import src.events as events
    monkeypatch.setattr(events, "record_event",
                        lambda kind, **kw: rows.append((kind, kw)) or True)
    return rows


def test_a_commitment_lands_in_the_event_log(manager, monkeypatch):
    # No store of its own. `P14-01` built one table so "what happened at 14:02"
    # has one place to look, and a commitment is the same kind of thing as the
    # tool calls, retrievals and approvals already in it (`Law 14`).
    rows = _recorded(monkeypatch)
    manager.save([mem("draft", "User is allergic to shellfish",
                      status=memory_edges.STATUS_PROPOSED)])
    commit_memory(manager, "draft", by="felix")
    kinds = [(kind, kw["name"], kw["outcome"], kw["detail"]["memory_id"])
             for kind, kw in rows]
    assert ("memory", "commit", "committed", "draft") in kinds, kinds


def test_a_refusal_lands_there_too(manager, monkeypatch):
    # A log that only records successes cannot answer the question anybody
    # actually asks it, which is why a promotion was refused.
    rows = _recorded(monkeypatch)
    manager.save([mem("live", "User is allergic to shellfish"),
                  mem("draft", "User is allergic to shellfish",
                      status=memory_edges.STATUS_PROPOSED)])
    commit_memory(manager, "draft", by="felix")
    refusals = [kw for kind, kw in rows if kw["outcome"] == "refused"]
    assert refusals, rows
    assert refusals[0]["detail"]["duplicate_of"] == "live"
    assert refusals[0]["owner"] == "felix"


def test_the_log_never_costs_a_commitment(manager, monkeypatch):
    # A commitment that fails because its audit row failed is a button that
    # does nothing for a reason nobody can see.
    import src.events as events

    def _boom(kind, **kw):
        raise RuntimeError("no database here")

    monkeypatch.setattr(events, "record_event", _boom)
    manager.save([mem("draft", "User is allergic to shellfish",
                      status=memory_edges.STATUS_PROPOSED)])
    assert commit_memory(manager, "draft", by="felix")["verdict"] == "committed"
