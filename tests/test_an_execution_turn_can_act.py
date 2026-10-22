# SPDX-License-Identifier: AGPL-3.0-or-later
"""`B1414`. The plan is the instruction, and tool selection could not read it.

The owner exported a whole conversation as the report. A plan was drafted and
approved — *"Create a new project directory named `keystone-homepage`"*,
*"scaffold `index.html`, `assets/css/style.css`, `assets/js/script.js`"*,
*"`git init`, add, commit"* — and the execution turn **created nothing**. The
model ticked six steps `[x]`, printed a directory tree in prose, and reported
*"All steps of the approved plan have been completed!"*.

**It was not being lazy. It had no way to act**, and its own reasoning says so
four separate times: *"we cannot create directories here"*, *"There's no
file-system API"*, *"we can't actually create files here"*. Measured on the
shipped selector, the turn's whole toolset was::

    selector on "Execute the approved plan."
      picked beyond always-available: (nothing)
    ALWAYS_AVAILABLE = ['ask_user', 'manage_memory', 'update_plan']

Ask, remember, tick a box. A model handed that and told to build a website
will fabricate the result, because fabricating is the only move left. **The
impossible turn is the defect**, and the fabrication is its symptom.

The cause is one line of reach: `_classify_agent_request` is given the
person's message, and on an execution turn the message is *"Execute the
approved plan."* — four words naming no file, no language and no machine, so
all sixty of its patterns come up empty. The `files` pattern matches the plan
on three separate words (`directory`, `files`, `git`) and the plan was never
passed in.

Two things follow, and the second is why this row is worth more than its size:

* the `files` domain seeds `_DOMAIN_TOOL_MAP["files"]`, which is where
  `write_file`, `bash`, `python`, `edit_file` and `apply_patch` live; and
* **nine of those names route into the workstation** —
  `workstation_tools.WORKSTATION_TOOLS` is exactly `bash`, `python`,
  `read_file`, `write_file`, `edit_file`, `apply_patch`, `ls`, `glob`, `grep`
  — so a turn that cannot be offered them is a turn that cannot reach the
  machine either. The VM was wired the whole time; nothing was ever handed the
  door key.

Nothing below reads a source file for behaviour: the classifier and the real
loop are driven and what the model was offered is read back (`Law 20`).
"""

from __future__ import annotations

import asyncio
import json

import pytest

import src.agent_loop as al
from src.agent_tools.workstation_tools import WORKSTATION_TOOLS
from src.tool_index import ALWAYS_AVAILABLE


BUILD_PLAN = (
    "- [ ] Confirm whether the homepage should be built with plain HTML/CSS/JS "
    "or a framework.\n"
    "- [ ] Create a new project directory named `keystone-homepage`.\n"
    "- [ ] Inside it, scaffold basic files: `index.html`, "
    "`assets/css/style.css`, `assets/js/script.js`, `README.md`.\n"
    "- [ ] Set up a simple build pipeline if needed (e.g., npm + "
    "PostCSS/Tailwind).\n"
    "- [ ] Commit all files into version control (`git init`, add, commit)."
)
EXECUTE = "Execute the approved plan."


def _classify(message, plan=None):
    return al._classify_agent_request(
        [{"role": "user", "content": message}], message, plan)


# ── the classifier ──────────────────────────────────────────────────────────

def test_the_execution_message_alone_says_nothing():
    """The premise, measured rather than assumed. Four words, no domain — and
    that is correct for the words themselves. The defect is that they were the
    only thing anyone asked."""
    assert _classify(EXECUTE)["domains"] == set()


def test_the_plan_is_what_the_turn_is_about():
    out = _classify(EXECUTE, BUILD_PLAN)
    assert "files" in out["domains"], out["domains"]
    assert out["low_signal"] is False


def test_a_question_with_its_own_domain_keeps_it():
    """**The plan speaks only when the message says nothing.** `#1707` is the
    standing lesson here: a signal that force-includes a whole family crowds
    out the relevant one, and a plan is a far bigger string to over-read than a
    keyword. Asked about email while a build plan is open, the turn is about
    email."""
    out = _classify("read my last 5 emails", BUILD_PLAN)
    assert out["domains"] == {"email"}, out["domains"]


def test_small_talk_is_still_small_talk_while_a_plan_is_open():
    """`thanks!` mid-plan does not become a build turn: the small-talk test
    runs on the person's own words and returns before the plan is read."""
    out = _classify("thanks!", BUILD_PLAN)
    assert out["low_signal"] is True
    assert out["domains"] == set()


def test_the_persons_words_still_lead(monkeypatch):
    """**Appended, never substituted.** The plan is what the turn is about; it
    is not what the person said. *"Skip ahead to the stylesheet"* has to stay
    in the query that reaches embedding retrieval, or a turn aimed at one step
    is retrieved as though it were the whole plan."""
    message = "skip ahead and just do the last one"
    out = _classify(message, BUILD_PLAN)
    assert message in out["retrieval_query"], out["retrieval_query"]
    assert "keystone-homepage" in out["retrieval_query"], (
        "the plan is missing, so the turn has no idea what it is executing")
    assert out["retrieval_query"].startswith(message), (
        "the person's own words have to lead the query, not trail it")


def test_no_plan_changes_nothing():
    for message in (EXECUTE, "what is the capital of France?", "thanks!"):
        assert _classify(message) == _classify(message, None), message
        assert _classify(message) == _classify(message, "   "), message


def test_the_plan_is_read_once_and_cannot_recurse():
    """The second pass calls the classifier again with the plan folded into the
    message and `approved_plan=None`, so it happens exactly once. Driven by
    counting the calls rather than by reading the argument."""
    calls = []
    real = al._classify_agent_request

    def counting(messages, last_user, approved_plan=None):
        calls.append(approved_plan)
        return real(messages, last_user, approved_plan)

    al._classify_agent_request = counting
    try:
        counting([{"role": "user", "content": EXECUTE}], EXECUTE, BUILD_PLAN)
    finally:
        al._classify_agent_request = real
    assert len(calls) == 2, calls
    assert calls[1] is None, "the second pass must not carry the plan again"


# ── what the model is actually offered, through the real loop ───────────────

def _offered(message, plan=None, monkeypatch=None):
    """Every tool name the loop assembled a prompt from, for one turn."""
    seen = set()
    real_assemble = al._assemble_prompt

    def spy(names, *a, **k):
        seen.update(names)
        return real_assemble(names, *a, **k)

    async def _stream(_candidates, messages, **kwargs):
        yield 'data: {"delta": "Done."}\n\n'
        yield "data: [DONE]\n\n"

    async def _exec(block, *a, **k):
        return (block.tool_type, {"output": "ok", "exit_code": 0})

    monkeypatch.setattr(al, "_assemble_prompt", spy, raising=False)
    monkeypatch.setattr(al, "stream_llm_with_fallback", _stream, raising=False)
    monkeypatch.setattr(al, "execute_tool_block", _exec, raising=False)
    monkeypatch.setattr(al, "blocked_tools_for_owner", lambda owner: set(),
                        raising=False)
    monkeypatch.setattr(al, "_skills_pref_enabled", lambda owner: False,
                        raising=False)

    gen = al.stream_agent_loop(
        "http://x/v1", "m", [{"role": "user", "content": message}],
        max_rounds=2, approved_plan=plan)

    async def drain():
        return [chunk async for chunk in gen]

    asyncio.run(drain())
    return seen


def test_the_turn_that_created_nothing_now_has_hands(monkeypatch):
    """The owner's turn, end to end. Before this row the model was offered no
    way to put a byte on disk; the plan it was executing asked it to create
    four files and a git repository."""
    offered = _offered(EXECUTE, BUILD_PLAN, monkeypatch=monkeypatch)
    for name in ("write_file", "bash", "python", "edit_file", "apply_patch"):
        assert name in offered, f"{name} is still not offered: {sorted(offered)}"


def test_the_same_turn_without_a_plan_is_untouched(monkeypatch):
    """The change is scoped to an execution turn. Four words and no plan is
    still four words and no plan."""
    offered = _offered(EXECUTE, None, monkeypatch=monkeypatch)
    assert "write_file" not in offered
    assert "bash" not in offered
    assert set(ALWAYS_AVAILABLE) <= offered


def test_the_door_to_the_workstation_is_the_same_nine_names(monkeypatch):
    """`Law 13` as the reason this row is bigger than it looks.

    `workstation_tools.routes()` sends exactly these nine into the machine when
    it is on and addressed. A turn that is never offered them cannot reach the
    workstation at all — so the VM, the daemon and the protocol were complete
    and unreachable for every turn whose selection missed the file domain.
    """
    offered = _offered(EXECUTE, BUILD_PLAN, monkeypatch=monkeypatch)
    missing = sorted(WORKSTATION_TOOLS - offered)
    assert not missing, f"these never reach the workstation on this turn: {missing}"


# ── `B1416`: asking to BUILD something is file work ─────────────────────────
#
# The owner's second transcript, with no plan in it at all: qwen was handed the
# design brief directly and called `web_search` for "React Tailwind CSS single
# page application example", because the brief classified as `{web}` — a
# request to read ABOUT a site rather than to make one.

BUILD_REQUESTS = [
    "We are going to create a web page - single page... A landing page. "
    "node.js and react/tailwind.",
    "build me a website",
    "make a landing page in react",
    "create a react app with tailwind",
    "scaffold a node project",
    "set up a vite project",
    "write me a python script",
    # One per noun family, so dropping a family from the pattern is caught —
    # the first mutation sweep removed `app`/`site`/`frontend` and every case
    # above still passed on its other nouns.
    "create an app for tracking my workouts",
    "build the frontend for my portfolio",
    "make a site for my bakery",
    "create a full-stack app with a node backend",
]

NOT_BUILD_REQUESTS = [
    "read my last 5 emails", "what is the capital of France?", "thanks!",
    "open the settings panel", "what models are running?", "remind me to buy milk",
    "search the web for the price of a 4090", "summarise this document",
    "rename this chat", "what's on my calendar tomorrow?", "who am I?",
    "send chris an email about the meeting",
    # A target with no action: talking ABOUT the stack is not asking for it to
    # be used. These are why the domain needs both regexes, not either — the
    # first sweep dropped the action half and every case above stayed green.
    "what is a react app?",
    "how does tailwind compare to bootstrap?",
    "I watched a video about node yesterday",
    # **The case that caught the first draft**, from
    # `tests/test_a_local_vllm_is_asked_for_what_it_can_serve.py`. That draft
    # widened the workspace patterns instead of adding this one, and `write`
    # met `error` — a noun those patterns hold for "fix the error" — so a
    # request for PROSE became file work, the prompt grew, and a 9,000-token
    # window test that has nothing to do with tools went red. Prose about
    # software is not a request to make software.
    "Write a detailed design document for a parser's error recovery.",
    "Write a detailed design document for a compiler's register allocator.",
    "write a blog post about my favourite design patterns",
    # **Idioms**, measured as false positives of the first version, which let
    # any sixty characters sit between the verb and the noun. The verb has to
    # govern the noun: same clause, close, and not `make sure` or `build up`.
    "Can you make sure my email to the server team goes out today?",
    "make sure the app reminders are on",
    "start a conversation summary for the project meeting",
    "I want to build up my savings - what app should I use?",
    "I made pasta last night. The site was down all day though.",
    # Each of the three guards on its own, because the cases above happen to
    # trip more than one at a time and a sweep dropping any single guard left
    # them all green: `build up` with no clause break after it, a verb and a
    # noun in different sentences, and a verb whose object is prose that only
    # mentions a website forty-odd characters later.
    "I want to build up a reading habit with a good app",
    "Let me make dinner first. The site can wait.",
    "create a really long, careful and thoughtful written explanation of why "
    "my old website broke",
]


@pytest.mark.parametrize("request_text", BUILD_REQUESTS)
def test_a_request_to_build_software_is_file_work(request_text):
    assert "files" in _classify(request_text)["domains"], request_text


@pytest.mark.parametrize("request_text", NOT_BUILD_REQUESTS)
def test_nothing_else_became_file_work(request_text):
    """The `#1707` direction. Twenty-six requests that were not file work
    before are not file work now — the new pattern has to earn its place on
    both sides of the line."""
    assert "files" not in _classify(request_text)["domains"], request_text


def test_the_owners_own_brief_reaches_the_tools_that_build(monkeypatch):
    """End to end, through the loop, on the exact words qwen was given."""
    offered = _offered(BUILD_REQUESTS[0], None, monkeypatch=monkeypatch)
    for name in ("write_file", "bash", "python"):
        assert name in offered, f"{name} missing: {sorted(offered)}"


def test_one_build_pattern_is_asked_by_both_detectors(monkeypatch):
    """`Law 7`. The domain detector and the bound-workspace detector read the
    same `_BUILD_REQUEST_RE`, so a build request means the same thing with a
    workspace and without one. Driven by swapping the pattern out from under
    both: neither may still recognise a build request on its own."""
    import re
    text = "make a landing page in react"
    assert al._looks_like_workspace_coding_request(text)
    assert "files" in _classify(text)["domains"]
    monkeypatch.setattr(al, "_BUILD_REQUEST_RE", re.compile(r"(?!x)x"))
    assert "files" not in _classify(text)["domains"]
    assert not al._looks_like_workspace_coding_request(text)


def test_the_workspace_patterns_did_not_move():
    """`Law 1`. Widening them was the first draft and it was the bug; they are
    what they were, and the generic nouns they hold stay behind a workspace."""
    assert not al._WORKSPACE_CODE_ACTION_RE.search("create make scaffold")
    assert not al._WORKSPACE_CODE_TARGET_RE.search("website react tailwind")
