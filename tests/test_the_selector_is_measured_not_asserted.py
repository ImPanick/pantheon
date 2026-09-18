# SPDX-License-Identifier: AGPL-3.0-or-later
"""`P17-14` — the tool selector, scored rather than asserted.

`.pantheon/GAP-ANALYSIS.md` measured the selector on the owner's deployment and
found its top pick was the least-used tool: `web_search` offered 37 of 39 runs
and called **0**, `create_document` offered **once** and called **19**, with 69
of 81 tools offered and never picked. The row's `Verify:` asks for two things —
*the selector is measured against calls rather than asserted*, and *each of the
top unused entries is classified into one of the three problems rather than
swept*.

**What the measurement found, and it is a `Law 13` defect rather than a tuning
one.** The selector was written **twice**. `ToolIndex.get_tools_for_query`
matched keyword hints on word boundaries and ran two structural signals;
`src/agent_loop.py` carried a second copy for the case where the embedding
backend is unavailable or exceeds the selection timeout — the path a deployment
with no vector service runs on **every** turn — and that copy matched raw
substrings and ran no structural signal at all. It was wrong in both directions
at once:

    "this document is unreadable"              16 tools there, 3 here
    "visit https://example.com and ..."         3 tools there, 5 here

The first is issue #1707 exactly, whose fix is quoted in `_KEYWORD_HINTS` and
was applied to one of the two call sites. The second is worse than noise: on the
fallback path a pasted URL selected **no web tools**, so the degraded selector
could not fetch a link the user had just handed it.

**These tests drive the real code, not the file.** `test_the_fallback_block...`
lifts the fallback's own `if` statement out of `src/agent_loop.py` with `ast`
and executes it — the same technique `tests/harness/*.js` uses on JS modules,
for the same reason (`Law 20`): the block lives inside a 1,500-line async
function that cannot be called from a test, and asserting on its source text
would test the text. On the tree as it stood the extracted block returns 16
tools for the first query and no web tools for the second, and both assertions
below fail.

The scored half lives in `.pantheon/retrieval_eval.py --kind tools`, which is
`P13-13`'s harness extended rather than a second evaluator (`Law 14`): the same
corpus loader, the same provenance discipline, the same "a report, never a
gate". `score_selection` is its own function because a set has no rank, so
recall transfers from memory retrieval and MRR does not.
"""
import ast
import json
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / ".pantheon"))

from src.tool_index import ALWAYS_AVAILABLE, ToolIndex  # noqa: E402

_EVAL = ROOT / ".pantheon" / "retrieval_eval.py"
_CORPUS = ROOT / ".pantheon" / "fixtures" / "tool_selection_probe.json"


def _eval_module():
    """`retrieval_eval.py` as a module. It is a script, not a package member."""
    import importlib.util

    spec = importlib.util.spec_from_file_location("_retrieval_eval", _EVAL)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


# ── the fallback block, executed out of the shipped source ───────────────────


def _fallback_block() -> ast.If:
    """The keyword-fallback `if` from `src/agent_loop.py`, as an AST node.

    Located by its own test expression rather than by line number or by a
    comment, so it is still found after the file moves — and so that deleting
    the branch makes this test fail loudly instead of quietly passing over
    nothing.
    """
    tree = ast.parse((ROOT / "src" / "agent_loop.py").read_text(encoding="utf-8"))
    found = []
    for node in ast.walk(tree):
        if not isinstance(node, ast.If):
            continue
        test = ast.unparse(node.test)
        if "guide_only" in test and "_retrieval_query" in test and "_relevant_tools" in test:
            assigns = {ast.unparse(t) for stmt in node.body
                       if isinstance(stmt, ast.Assign) for t in stmt.targets}
            if "_relevant_tools" in assigns:
                found.append(node)
    assert len(found) == 1, (
        f"expected exactly one keyword-fallback branch in agent_loop.py, found "
        f"{len(found)} — the selector's second call site has moved or multiplied")
    return found[0]


def _run_fallback(query: str) -> set:
    """Execute the real fallback branch for one query and return its selection."""
    import logging

    block = _fallback_block()
    module = ast.Module(body=[block], type_ignores=[])
    ast.fix_missing_locations(module)
    scope = {
        "guide_only": False,
        "_relevant_tools": None,
        "_retrieval_query": query,
        "logger": logging.getLogger("test-fallback"),
    }
    exec(compile(module, "<agent_loop-fallback>", "exec"), scope, scope)
    return set(scope["_relevant_tools"] or ())


@pytest.mark.parametrize("query", [
    "this document is unreadable",
    "i am replying to your github comment",
    "prefix the output with a label",
    "the deadline is online already",
    "please observe the reserve levels",
    "concurrent requests are timing out",
])
def test_the_fallback_block_no_longer_matches_inside_a_word(query):
    """#1707's fix reached the second call site.

    Before `P17-14` the extracted block returned 16 tools for the first two
    queries — the entire email family, because `"unread"` is a substring of
    `"unreadable"` and `"reply"` of `"replying"`.
    """
    assert _run_fallback(query) == ToolIndex.select_without_embeddings(
        query, set(ALWAYS_AVAILABLE))


def test_the_fallback_block_runs_the_structural_signals_too():
    """A pasted URL selects web tools on the path that runs without embeddings.

    `_WEB_RE` lived only in `ToolIndex`, so the fallback — the path a
    deployment with no vector service takes on every turn — could not reach
    `web_fetch` for a link the user had just given it.
    """
    selected = _run_fallback("visit https://example.com and tell me the title")
    assert {"web_fetch", "web_search"} <= selected


def test_the_fallback_block_carries_the_contact_steering():
    """`manage_memory` is discarded for a clear save-a-contact ask.

    `get_tools_for_query` drops it deliberately — the model was observed
    reaching for memory with `manage_contact` in the set — and the second copy
    never had that steering at all.
    """
    selected = _run_fallback("save this address for alex: 14 mill lane")
    assert "manage_contact" in selected
    assert "manage_memory" not in selected


def test_extracting_the_shared_half_did_not_drop_the_retrieved_half():
    """`get_tools_for_query` still hands retrieval's answer through.

    Added because a mutation survived: replacing
    `set(base if base is not None else ALWAYS_AVAILABLE)` with
    `set(ALWAYS_AVAILABLE)` passed every other test here, and that change would
    silently discard **every embedding-retrieved tool** while the keyword half
    kept working — the failure would read as "retrieval is bad" rather than
    "retrieval is thrown away". Nothing above could see it because the fallback
    path, which is what the rest of this file drives, passes no retrieval
    results by construction.
    """
    index = ToolIndex.__new__(ToolIndex)
    index.retrieve = lambda query, k=8: ["manage_skills", "search_chats"]
    selected = index.get_tools_for_query("something with no keyword hint at all")
    assert {"manage_skills", "search_chats"} <= selected

    # And the caller's `always_include` is honoured rather than replaced.
    assert "manage_skills" in ToolIndex.select_without_embeddings(
        "hello", {"manage_skills"})


def test_the_fallback_block_delegates_rather_than_reimplementing():
    """One rule, one place — checked on behaviour over the whole corpus.

    Not a source assertion: every probe in the corpus is run through the
    extracted block and through `ToolIndex`, and the two sets must be equal.
    A re-divergence of any kind fails here whatever it looks like in the file.
    """
    corpus = json.loads(_CORPUS.read_text(encoding="utf-8"))
    for probe in corpus["probes"]:
        query = probe["query"]
        assert _run_fallback(query) == ToolIndex.select_without_embeddings(
            query, set(ALWAYS_AVAILABLE)), query


# ── the scored measurement ───────────────────────────────────────────────────


# What the second copy did, quoted from `src/agent_loop.py` as it stood before
# `P17-14`. Kept as the historical baseline for the same reason
# `DELETED_SCORER_BASELINE` is kept in the eval: "never worse than what we
# removed" is the one comparison a replacement owes, and a baseline that is a
# historical fact needs no calibration.
def _pre_p17_14_fallback(query: str) -> set:
    base = set(ALWAYS_AVAILABLE)
    ql = query.lower()
    for keywords, tools in ToolIndex._KEYWORD_HINTS.items():
        if any(kw in ql for kw in keywords):
            base.update(tools)
    return base


def test_the_shipped_selector_beats_the_copy_it_replaced():
    """The before/after number, over the corpus, on both axes.

    `Law 9` wants a measurement rather than an assertion that a function was
    called. Recall is *did the tool the query needs get offered at all* — the
    ceiling on everything the call column can say — and refusal is the half
    `GAP-ANALYSIS.md` has no column for, since 69 of 81 offered and never
    picked is a precision failure and a scorer that measures only recall
    rewards offering everything.
    """
    ev = _eval_module()
    corpus = ev._load(_CORPUS)

    before = ev.score_selection(
        corpus, {p["query"]: _pre_p17_14_fallback(p["query"]) for p in corpus["probes"]})
    after = ev.score_selection(corpus, ev._selector(corpus, 5))

    assert after["recall"] > before["recall"], (before, after)
    assert after["refusal"] > before["refusal"], (before, after)
    assert after["offered"] < before["offered"], (before, after)
    # Pinned so a later change that trades one axis for the other is visible
    # rather than absorbed. Measured on this corpus, this tree.
    assert before["recall"] < 0.90 and after["recall"] >= 0.95
    assert before["refusal"] < 0.80 and after["refusal"] >= 0.90


def test_the_corpus_is_validated_against_the_real_tool_surface():
    """A probe cannot expect a tool that does not exist.

    The failure this prevents is a corpus that scores a permanent miss on a
    renamed tool and reads as a retrieval defect forever.
    """
    ev = _eval_module()
    from src.agent_tools import TOOL_TAGS

    corpus = ev._load(_CORPUS)
    named = set()
    for probe in corpus["probes"]:
        named |= set(probe.get("expect") or ()) | set(probe.get("reject") or ())
    assert named <= set(TOOL_TAGS)
    assert len(corpus["probes"]) >= 20

    bad = json.loads(_CORPUS.read_text(encoding="utf-8"))
    bad["probes"][0]["expect"] = ["a_tool_that_was_renamed"]
    tmp = ROOT / ".pantheon" / "fixtures" / "_tmp_bad_tool_corpus.json"
    tmp.write_text(json.dumps(bad), encoding="utf-8")
    try:
        with pytest.raises(SystemExit):
            ev._load(tmp)
    finally:
        tmp.unlink()


def test_the_report_says_its_probes_are_not_an_operators(capsys):
    """Provenance discipline carries over, or the number gets quoted as product.

    `P13-13` put this warning on the memory eval because a score over
    hand-written probes is a fact about whoever wrote them. It is no less true
    of tool probes and the same sentence has to appear.
    """
    ev = _eval_module()
    args = ev.argparse.Namespace(corpus=_CORPUS, engine="selector", k=5,
                                 kind="tools", verbose=False, json=False)
    assert ev._main_tools(args) == 0
    out = capsys.readouterr().out
    assert "provenance: fixture" in out
    assert "not typed by an operator" in out
    assert "recall" in out and "refusal" in out
    assert "MRR" not in out, "a set has no rank; reporting one invents an order"


# ── the classification the row asks for, pinned where it is structural ───────


def test_three_of_the_top_unused_entries_are_not_selector_decisions():
    """`ask_user`, `update_plan` and `manage_memory` are unconditional.

    The row lists them among the selector's top picks — 39/1, 30/5, 22/0 — and
    they are not picks. They are `ALWAYS_AVAILABLE`, offered on every run
    whatever the query, and `ask_user`/`update_plan` are force-included a
    second time when the prompt is assembled. Classifying them as retrieval
    faults would send somebody tuning a selector that never chose them.
    """
    assert {"ask_user", "update_plan", "manage_memory"} == set(ALWAYS_AVAILABLE)
    for query in ("hello", "thanks, that worked", "serve qwen3 on the gpu box"):
        assert set(ALWAYS_AVAILABLE) <= ToolIndex.select_without_embeddings(
            query, set(ALWAYS_AVAILABLE))


def test_the_prompt_forces_the_loop_primitives_back_in_whatever_was_selected():
    """The second, independent reason `ask_user` is offered on every run.

    Driven through `_build_base_prompt` rather than read out of the source:
    handed a selection containing neither, the assembled prompt still names
    both.
    """
    from src import agent_loop

    prompt = agent_loop._build_base_prompt(
        disabled_tools=set(), mcp_mgr=None, needs_admin=False,
        relevant_tools={"read_file"}, compact=True)
    text = prompt if isinstance(prompt, str) else str(prompt)
    assert "ask_user" in text
    assert "update_plan" in text
