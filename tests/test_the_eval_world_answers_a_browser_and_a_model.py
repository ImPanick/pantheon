# SPDX-License-Identifier: AGPL-3.0-or-later
"""`B1607` — the evaluation world answers a browser and a model.

Found doing `P24-27`. `computer` — the workstation's screen — reached the
world only through its shell rules, matched on the action word: every
`screenshot` gave the same answer whatever had been typed or clicked, so a
case could not show an agent a page, let alone the page after a click. And
`chat_with_model` was refused in every case ("This world has no
chat_with_model"), so an agent that asks other models could not be measured
at all. That blocked UX Auditor, Conversion Auditor, AI Visibility Check and
the AI Engineering section.

A world now has `screens` — what the screen shows before any action, and
after the actions that change it, kept until the next change — and `models`
— each model's replies — listed by `list_models` as the install lists an
endpoint's. A world with neither answers as before (Site Builder's cases
keep their shell rule for a screenshot).

Driven through the real harness, the real scheduler and the real tools.
"""

from __future__ import annotations

import asyncio
import json

import pytest

from src.agents import evals as E
from src.agents.catalogue import get_agent

PAGE_HOME = "Shop home — https://shop.example/ — a [Basket] button at (1180, 40)."
PAGE_BASKET = "Basket — https://shop.example/basket — 1 item, total £12.00; a [Checkout] button at (1100, 600)."
PAGE_CHECKOUT = "Checkout — asks for an account before showing the delivery cost."


def _spy(monkeypatch):
    seen = []
    real = E.World.answer

    def spy(self, tool, content):
        out = real(self, tool, content)
        if out is not None:
            seen.append((tool, out[1]["output"]))
        return out

    monkeypatch.setattr(E.World, "answer", spy)
    return seen


INPUTS = {"ux-auditor": {"site": "https://shop.example/", "flows": "Buy one thing"},
          "ai-visibility-check": {"name": "Rosa's Bakery", "questions": ["Which bakery in Leeds is best?"],
                                  "models": ["qwen3-8b", "llama-3.1-8b", "mistral-7b"]},
          "model-steward": {}}


def _case(world, calls, checks=None, agent="ux-auditor"):
    # After the screen's first answer every further action waits for a yes
    # (the gate after outside content): the person says yes to each.
    return {"id": "drive", "world": world, "inputs": INPUTS[agent],
            "answers": ["approve_task"] * len(calls),
            "script": [{"call": [c]} for c in calls] + [{"say": "Done."}],
            "checks": checks or [{"called": calls[0][0]}]}


def test_the_screen_follows_what_the_agent_does(monkeypatch):
    seen = _spy(monkeypatch)
    m = get_agent(None, "ux-auditor")
    world = {"screens": [
        {"screen": PAGE_HOME},
        {"after": "https://shop.example/basket", "screen": PAGE_BASKET},
        {"after": "click at (1100, 600)", "screen": PAGE_CHECKOUT},
    ]}
    calls = [["computer", {"action": "screenshot"}],
             ["computer", {"action": "type", "text": "https://shop.example/basket\n"}],
             ["computer", {"action": "screenshot"}],
             ["computer", {"action": "scroll", "x": 640, "y": 400, "dy": 3}],
             ["computer", {"action": "click", "x": 1100, "y": 600}]]
    asyncio.run(E.run_agent(m, cases=[_case(world, calls)]))
    shots = [out for tool, out in seen if tool == "computer"]
    assert len(shots) == 5, shots
    assert "Shop home" in shots[0]
    assert "Basket" in shots[1] and "Did: type" in shots[1]
    assert "Basket" in shots[2], "a screenshot shows the page the last action left"
    assert "Basket" in shots[3], "an action that changes nothing leaves the page as it was"
    assert "Checkout" in shots[4] and "click at (1100, 600)" in shots[4]
    assert "no machine" not in " ".join(shots)


def test_an_action_the_tool_does_not_know_is_refused_in_its_words(monkeypatch):
    seen = _spy(monkeypatch)
    m = get_agent(None, "ux-auditor")
    world = {"screens": [{"screen": PAGE_HOME}]}
    asyncio.run(E.run_agent(m, cases=[_case(world, [["computer", {"action": "teleport"}]])]))
    (out,) = [o for t, o in seen if t == "computer"]
    assert "is not an action `computer` knows" in out, out


def test_a_world_without_screens_still_answers_by_its_shell_rules():
    """Backward compatible: Site Builder's cases answer a screenshot from a
    shell rule, and every one of them still passes."""
    m = get_agent(None, "site-builder")
    results = asyncio.run(E.run_agent(m))
    assert all(r.passed for r in results), {r.case: [c for c in r.checks if not c["ok"]]
                                            for r in results if not r.passed}
    # And the screenshot is taken: the loop withheld `computer` in every
    # world (no workstation is set up there), so its sample said "screenshot
    # taken" over "Tool 'computer' is disabled by the current request policy".
    first = next(r for r in results if r.case == "a-one-page-bakery")
    assert "computer" in first.report["wrote"], first.report
    assert not [x for x in first.report.get("refused") or [] if x.get("tool") == "computer"], first.report


WORLD_MODELS = {
    "qwen3-8b": [{"match": "bakery", "reply": "Rosa's Bakery on Mill Street is well liked."}],
    "llama-3.1-8b": "I don't know of a bakery by that name.",
    "mistral-7b": [{"match": "bakery", "error": "the endpoint timed out"}],
}


def test_a_model_answers_from_the_world(monkeypatch):
    seen = _spy(monkeypatch)
    m = get_agent(None, "ai-visibility-check")
    calls = [["chat_with_model", {"model": "qwen3-8b", "message": "Which bakery in Leeds is best?"}],
             ["chat_with_model", {"model": "llama-3.1-8b@World models", "message": "Which bakery in Leeds is best?"}],
             ["chat_with_model", {"model": "mistral-7b", "message": "Which bakery in Leeds is best?"}],
             ["chat_with_model", {"model": "gpt-9", "message": "Which bakery in Leeds is best?"}]]
    asyncio.run(E.run_agent(m, cases=[_case({"models": WORLD_MODELS}, calls, agent="ai-visibility-check")]))
    replies = [out for tool, out in seen if tool == "chat_with_model"]
    assert len(replies) == 4, replies
    assert "Rosa's Bakery" in replies[0] and "qwen3-8b" in replies[0]
    assert "don't know of a bakery" in replies[1], "model@endpoint is the same model"
    assert "Failed to get response from mistral-7b" in replies[2] and "timed out" in replies[2]
    assert "is not listed by any endpoint now" in replies[3], "an unknown model is refused as the tool refuses it"
    assert "This world has no chat_with_model" not in " ".join(replies)


def test_the_worlds_models_are_listed_as_an_endpoints_are(monkeypatch):
    import src.tool_execution as tool_execution
    own = []
    real = tool_execution._execute_tool_block_impl

    async def spy_own(block, *a, **kw):
        out = await real(block, *a, **kw)
        own.append((block.tool_type, json.dumps(out[1] if isinstance(out, tuple) else out)))
        return out

    monkeypatch.setattr(tool_execution, "_execute_tool_block_impl", spy_own)
    m = get_agent(None, "model-steward")
    asyncio.run(E.run_agent(m, cases=[_case({"models": WORLD_MODELS}, [["list_models", {}]], agent="model-steward")]))
    listed = next(out for tool, out in own if tool == "list_models")
    for name in WORLD_MODELS:
        assert name in listed, listed


def test_without_models_a_model_is_still_refused(monkeypatch):
    """A world that gives no models keeps the old answer: nothing leaves it."""
    seen = _spy(monkeypatch)
    m = get_agent(None, "ai-visibility-check")
    asyncio.run(E.run_agent(m, cases=[_case({}, [["chat_with_model", {"model": "x", "message": "hi"}]], agent="ai-visibility-check")]))
    (out,) = [o for t, o in seen if t == "chat_with_model"]
    assert "This world has no chat_with_model" in out


@pytest.mark.parametrize("key, value", [
    ("screens", [{"screen": "a page"}, {"after": "click", "screen": "another"}]),
    ("models", {"m": "hello", "n": [{"match": "x", "reply": "y"}]}),
])
def test_a_world_lints_its_new_keys(key, value):
    m = get_agent(None, "ux-auditor")
    assert E.lint_evals({"cases": [{"id": "a-case", "world": {key: value}, "checks": [{"status": "success"}]}]}, m)


@pytest.mark.parametrize("key, value, words", [
    ("screens", [{"after": "click"}], "screen"),
    ("screens", {"a": "b"}, "screen"),
    ("models", {"m": [{"match": "x"}]}, "reply"),
    ("models", ["m"], "model"),
])
def test_a_malformed_screen_or_model_is_refused_in_a_sentence(key, value, words):
    m = get_agent(None, "ux-auditor")
    with pytest.raises(E.EvalRefused) as exc:
        E.lint_evals({"cases": [{"id": "a-case", "world": {key: value}, "checks": [{"status": "success"}]}]}, m)
    assert words in exc.value.sentence
