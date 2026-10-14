# SPDX-License-Identifier: AGPL-3.0-or-later
"""The owner, 2026-10-14: *"The LLM's use of tools is still very much
intermittent... even with its own MCP's provided. Ensure its capable of using
Pantheon's entire suite of tooling and skills etc.."*

`fx9-suite` made the turn's tool set deterministic and budget-bounded, and the
integrator's matrix then found one cell still empty — the mode the owner uses:

    emb=up mcp=up win=large mode=agent who=admin | suite 79 | ordinary turn 0/76

**An ordinary first message in Agent mode was answered with no tools at all.**
Three mechanisms, measured on `b6a1bbf` before a line was written:

  1. `_user_turn_count` counted every `user`-role message. Four of Pantheon's
     own per-turn additions ride as `user`-role messages on purpose (#2927 — a
     block whose text changes every minute cannot live in the KV-cached system
     prefix), and `routes/chat_helpers.py:1102` inserts the date/time note on
     the Chat route and deliberately not on the Agent route. So the same first
     message counted **2** in Chat and **1** in Agent, and
     `_existing_conversation` — the function's only caller — answered True for
     a conversation that did not exist. That accident was the only thing
     keeping Chat mode out of the hole.
  2. `_classify_agent_request` ended `low_signal = not continuation and not
     domains`, so a request whose words miss all eleven domain regexes was
     "low signal" and `_direct_low_signal` took a tool-less direct reply with
     **no system prompt** and the reply capped at 128 tokens. Measured: the
     harness's own ordinary turn (*"…the leaking pipe under the kitchen sink…"*)
     and *"Use the `send_email` tool now."* are both in that class.
  3. `_detect_admin_intent` was a raw-substring list with `archive` in it, so
     the owner's own question about a raid *"called the fractured archive"*
     force-included fifteen management tools.

And `fx9-proof`'s `B-NEW-8`: five schema-backed tools the prompt names while
the request withholds them, every one of them on a line that also names a tool
the turn **does** have, which is the one case `prune_rules_to_available_tools`
cannot see.

Driven through the real `stream_agent_loop` with a scripted model stream, the
way `tests/test_the_tools_a_local_model_is_offered_reach_it.py` does it, and
through `tests/helpers/tool_suite_probe.py` for the mode axis, because the mode
is carried as the message the route builds rather than as a flag (`Law 20`).
"""
import asyncio
import json
import re

import pytest

import src.agent_loop as al
from src.mcp_manager import McpManager
from src.prompt_security import (
    capability_manifest_message,
    own_context_message,
    turn_note_message,
    untrusted_context_message,
)
from src.tool_policy import ToolPolicy, known_tool_names
from src.tool_security import NON_ADMIN_BLOCKED_TOOLS
from src.user_time import current_datetime_context_message

# The owner's question, verbatim from
# `/work/notes/owner-shots/2026-10-09-osrs-chat-export.md`.
OWNER_QUESTION = (
    "Research: Find out the ins and outs of the new Oldschool RuneScape Raids "
    "releasing on October 20th... its called the fractured archive. I mostly "
    "want to know, what are we going to expect to fight, and a strategy to "
    "defeat the mobs."
)
# `tests/helpers/tool_suite_probe.ORDINARY_TURN`, the sentence the matrix asks
# in every cell. It names no tool and matches no domain regex.
ORDINARY_TURN = (
    "Can you help me work out what to do about the leaking pipe under the "
    "kitchen sink before the weekend?"
)
LOCAL = "http://127.0.0.1:8080/v1"
UNKNOWN_MODEL = "local-unknown-1"
BACKTICKED = re.compile(r"`{1,3}([a-z][a-z0-9_]{2,40})`{1,3}")


# ── the harness ──────────────────────────────────────────────────────────────

def _mcp_manager() -> McpManager:
    mgr = McpManager()
    mgr._connections["osrs"] = {"name": "osrs-wiki", "status": "connected"}
    mgr._tools["osrs"] = [{
        "name": "lookup_raid",
        "description": "Look up an Old School RuneScape raid: bosses, mechanics, strategy.",
        "input_schema": {"type": "object",
                         "properties": {"name": {"type": "string", "description": "The raid"}},
                         "required": ["name"]},
    }]
    return mgr


def _base(monkeypatch, mgr=None, *, blocked=()):
    monkeypatch.setattr(al, "get_setting", lambda key, default=None: default, raising=False)
    monkeypatch.setattr(al, "blocked_tools_for_owner", lambda owner: set(blocked), raising=False)
    monkeypatch.setattr(al, "get_mcp_manager", lambda: mgr, raising=False)
    monkeypatch.setattr(al, "_load_mcp_disabled_map", lambda: {}, raising=False)


def _drive(monkeypatch, *, messages=None, message=ORDINARY_TURN, model=UNKNOWN_MODEL,
           url=LOCAL, relevant_tools=None, policy=None, rounds=("Nothing to do.",),
           context_length=None, prompt_type=None):
    """Run the real loop. Answers `[{tools, schemas, prompt, has_tools_key}]`.

    `messages` is the array the route would have built, so a caller can hand
    the Chat route's date/time note or a real second turn; `message` is the
    shorthand for a single first turn.
    """
    sent = []
    script = iter(rounds)

    async def scripted(candidates, msgs, **kwargs):
        sent.append({
            "tools": sorted((t.get("function") or {}).get("name")
                            for t in (kwargs.get("tools") or [])),
            "schemas": list(kwargs.get("tools") or []),
            "prompt": "\n".join(m.get("content") for m in msgs
                                if isinstance(m.get("content"), str)),
            "has_tools_key": kwargs.get("tools") is not None,
            "max_tokens": kwargs.get("max_tokens"),
        })
        step = next(script, "All done.")
        yield "data: " + json.dumps({"delta": step}) + "\n\n"
        yield "data: [DONE]\n\n"

    monkeypatch.setattr(al, "stream_llm_with_fallback", scripted)

    async def _run_tool(block, *a, **k):
        return block.tool_type, {"output": "ok", "exit_code": 0}

    monkeypatch.setattr(al, "execute_tool_block", _run_tool)

    turn = messages if messages is not None else [{"role": "user", "content": message}]

    async def collect():
        return [c async for c in al.stream_agent_loop(
            url, model, turn,
            max_rounds=len(rounds) + 1, owner="local",
            relevant_tools=relevant_tools,
            context_length=context_length,
            prompt_type=prompt_type,
            tool_policy=policy or ToolPolicy())]

    asyncio.run(collect())
    return sent


# ── 1. a machine-written message is never counted as the person's turn ───────

def test_pantheons_own_date_time_note_is_not_the_persons_turn():
    """`routes/chat_helpers.py:1102`'s note is a `user`-role message by design
    (#2927), and counting it made a one-message conversation look like two."""
    turn = [current_datetime_context_message(), {"role": "user", "content": ORDINARY_TURN}]
    assert al._user_turn_count(turn) == 1


@pytest.mark.parametrize("envelope", [
    lambda: turn_note_message("Added by Pantheon for this turn."),
    lambda: own_context_message("memory", "the person's own saved material"),
    lambda: capability_manifest_message("MCP tools", "what this install can call"),
    lambda: untrusted_context_message("a web page", "fetched text"),
])
def test_none_of_the_four_envelopes_counts_as_a_turn(envelope):
    """`fx6-turn` built all four to be identifiable; one reader answers for all
    four (`prompt_security.is_framed_context_content`, `Law 7`)."""
    turn = [envelope(), {"role": "user", "content": ORDINARY_TURN}]
    assert al._user_turn_count(turn) == 1


def test_the_persons_own_second_turn_still_counts():
    turn = [
        {"role": "user", "content": "what is the weather"},
        {"role": "assistant", "content": "Sunny."},
        current_datetime_context_message(),
        {"role": "user", "content": "thanks"},
    ]
    assert al._user_turn_count(turn) == 2


def test_both_modes_count_the_same_first_message_the_same():
    """The whole of mechanism 1: the Chat route inserts the note and the Agent
    route does not, and that must not be the difference between modes."""
    chat = [current_datetime_context_message(), {"role": "user", "content": ORDINARY_TURN}]
    agent = [{"role": "user", "content": ORDINARY_TURN}]
    assert al._user_turn_count(chat) == al._user_turn_count(agent) == 1


# ── 2. a first message is not a lesser message ───────────────────────────────

def test_an_ordinary_first_message_in_agent_mode_carries_tools(monkeypatch):
    """The matrix cell this row exists for: `ordinary turn 0/76`."""
    _base(monkeypatch, _mcp_manager())
    sent = _drive(monkeypatch, message=ORDINARY_TURN, prompt_type="agent")
    assert sent[0]["has_tools_key"], "Agent mode's first message carried no `tools` key at all"
    assert len(sent[0]["tools"]) > 3, sent[0]["tools"]


def test_the_same_first_message_is_offered_the_same_suite_in_both_modes(monkeypatch):
    """Chat mode escaped the hole by accident. Parity, not a second accident."""
    _base(monkeypatch, _mcp_manager())
    agent = _drive(monkeypatch, message=ORDINARY_TURN, prompt_type="agent")
    chat = _drive(monkeypatch, messages=[current_datetime_context_message(),
                                         {"role": "user", "content": ORDINARY_TURN}])
    assert agent[0]["tools"] == chat[0]["tools"]


def test_a_first_message_that_names_a_tool_is_offered_it(monkeypatch):
    """`tool_suite_probe.bare_naming_turn`: the turn the brief says must never
    be silently dropped. `send_email` has an underscore, so no domain regex
    matches it and the whole turn read as low signal."""
    _base(monkeypatch, _mcp_manager())
    sent = _drive(monkeypatch,
                  message="Use the `send_email` tool now. Call `send_email` to do it.",
                  prompt_type="agent")
    assert "send_email" in sent[0]["tools"]


def test_a_registered_mcp_tool_reaches_a_first_message(monkeypatch):
    """*"even with its own MCP's provided"* — on the turn that had nothing."""
    _base(monkeypatch, _mcp_manager())
    sent = _drive(monkeypatch, message=ORDINARY_TURN, prompt_type="agent")
    assert "mcp__osrs__lookup_raid" in sent[0]["tools"]


@pytest.mark.parametrize("greeting", ["hi", "hey there", "thanks", "lol", "   ", "..."])
def test_a_greeting_still_takes_the_cheap_direct_path(monkeypatch, greeting):
    """`Law 1`, and the measurement that decided it (see
    `_direct_low_signal`'s comment): the path is worth **34,235 tokens** on a
    greeting — 12,800 of system prompt and 21,435 of schemas it does not send —
    which is a saving `fx9-suite`'s budget cannot make, because the budget is
    about the window and not about the request."""
    _base(monkeypatch, _mcp_manager())
    sent = _drive(monkeypatch, message=greeting, prompt_type="agent")
    assert sent[0]["has_tools_key"] is False, sent[0]["tools"]
    assert sent[0]["prompt"].strip() == greeting.strip()
    assert sent[0]["max_tokens"] == 128


def test_a_greeting_takes_the_same_path_in_both_modes(monkeypatch):
    """The other half of parity: Chat mode used to spend the whole suite on
    "hi" because its own date/time note said the conversation existed."""
    _base(monkeypatch, _mcp_manager())
    agent = _drive(monkeypatch, message="hi", prompt_type="agent")
    chat = _drive(monkeypatch, messages=[current_datetime_context_message(),
                                         {"role": "user", "content": "hi"}])
    assert agent[0]["has_tools_key"] is False
    assert chat[0]["has_tools_key"] is False


def test_a_greeting_in_a_real_conversation_keeps_the_contextual_path(monkeypatch):
    """The direct path throws the conversation away, so it may only be taken
    when there is no conversation to throw away. Unchanged by this row."""
    _base(monkeypatch, _mcp_manager())
    sent = _drive(monkeypatch, messages=[
        {"role": "user", "content": "serve qwen3 on the gpu box"},
        {"role": "assistant", "content": "Started it."},
        {"role": "user", "content": "thanks"},
    ], prompt_type="agent")
    assert sent[0]["has_tools_key"], "a greeting mid-conversation lost its context"


def test_a_workflow_step_with_a_short_prompt_is_offered_its_tools(monkeypatch):
    """`B1170`, closed by the same change. A step limited to `web_search` whose
    prompt read *"what are tide tables, roughly?"* took the direct path: the
    bare prompt, no system prompt, no tools. `_direct_low_signal` stands down
    for a caller's `relevant_tools`, and the walker hands a step's list as its
    `ToolPolicy` instead."""
    _base(monkeypatch, _mcp_manager())
    sent = _drive(monkeypatch, message="what are tide tables, roughly?",
                  policy=ToolPolicy(allowed_tools=["web_search"]), prompt_type="agent")
    assert sent[0]["has_tools_key"], "an AI step that named its tools was offered none"
    assert sent[0]["tools"] == ["web_search"]


def test_one_definition_of_small_talk(monkeypatch):
    """`Law 7`. The same three-part test was written out in three places and
    `_direct_low_signal` wanted a fourth."""
    for text, small in [
        ("hi", True), ("hey man", True), ("thanks", True), ("", True), ("...", True),
        (ORDINARY_TURN, False), (OWNER_QUESTION, False),
        ("what are tide tables, roughly?", False),
        ("Use the `send_email` tool now.", False),
        ("hey can you serve qwen3 on the gpu box", False),
    ]:
        assert al._is_small_talk_turn(text) is small, text
        # `_skills_may_ship_for_turn` is the same question, asked the other way.
        assert al._skills_may_ship_for_turn(text) is (not small), text
        if small:
            assert al._classify_agent_request([{"role": "user", "content": text}],
                                              text)["low_signal"] is True, text


# ── 3. intent matching stops guessing from substrings ────────────────────────

@pytest.mark.parametrize("text", [
    OWNER_QUESTION,
    "its called the fractured archive",
    "the preference shares were in the archive of the old bank",
    "this document is unreadable",
    "fix the typo in the second paragraph of the document",
    "draft an essay on the history of the fork",
    "nothing of note happened today",
    "the setting sun over the harbour",
    "the conversation at dinner turned to politics",
    "that's a tidy sum for a kitchen",
    ORDINARY_TURN,
])
def test_a_management_word_mentioned_as_a_thing_is_not_an_admin_turn(text):
    """The owner's raid is *called* "the fractured archive". A noun is not a
    request, and `archive` in it force-included fifteen management tools."""
    assert al._detect_admin_intent([{"role": "user", "content": text}]) is False


@pytest.mark.parametrize("text", [
    "my dog ate the chateau cheese",          # chat
    "the doctor docked my pay",               # doc
    "she manages a flock of geese on the moor",  # manage
    "serverless is a silly word",             # server
    "chatter from the next table drowned us out",  # chat
    "i taskmastered my way through the week",  # task
    "a skilled carpenter notices everything",  # skill / note
])
def test_a_management_word_inside_another_word_is_not_a_match(text):
    """The substring half: `in content_lower` matched `chat` in "chateau"."""
    assert al._detect_admin_intent([{"role": "user", "content": text}]) is False


@pytest.mark.parametrize("text", [
    "archive this chat",
    "please archive this conversation",
    "rename this conversation",
    "delete that chat",
    "fork this conversation from here",
    "truncate the session after my last message",
    "list my sessions",
    "rename the last twelve chats to match their topics",
    "add an endpoint for my local llama.cpp",
    "rotate the api key",
    "create a webhook for the build",
    "revoke that token",
    "register an mcp server",
    "which mcp servers are connected",
    "show me my skills",
    "write a skill for triaging the inbox",
    "list my tasks",
    "schedule a task every morning at 7",
    "set up a cron job for the backup",
    "change the setting for dark mode",
    "configure my preferences",
    "update the config",
    "run that through the pipeline",
    "get a second opinion from the teacher model",
    "list models",
    "switch model to the local one",
    "set the theme to paper",
    "create theme from this screenshot",
    "show me my documents",
    "open my notes file",
    "tidy my library",
])
def test_a_management_request_is_still_an_admin_turn(text):
    """`Law 1`. Narrowing a matcher that was too wide must not make it narrow:
    measured over the corpus in the note, 20 false positives became 2 and the
    false negatives did not move."""
    assert al._detect_admin_intent([{"role": "user", "content": text}]) is True


def test_the_owners_question_does_not_force_the_management_tools_in(monkeypatch):
    """The consequence, not the predicate. With a caller's own `relevant_tools`
    the force-include is the only road those fifteen names have."""
    _base(monkeypatch, _mcp_manager())
    sent = _drive(monkeypatch, message=OWNER_QUESTION,
                  relevant_tools={"web_search", "trigger_research", "ask_user"})
    forced = sorted(set(sent[0]["tools"]) & al._ADMIN_PROMPT_FORCE_INCLUDE)
    assert forced == [], forced
    assert "trigger_research" in sent[0]["tools"], "the tool the request names"


def test_a_real_admin_request_still_gets_the_management_tools(monkeypatch):
    _base(monkeypatch, _mcp_manager())
    sent = _drive(monkeypatch, message="archive this chat and rename the other one",
                  relevant_tools={"web_search", "ask_user"})
    assert "manage_session" in sent[0]["tools"]


@pytest.mark.parametrize("text,wants", [
    ("can you preview this slide for me", False),
    ("the preview pane is broken", False),
    ("review this paragraph", True),
    ("reviewing the budget now", True),
    ("any suggestions for the intro", True),
    ("improve the second line", True),
    ("proofread it", True),
    ("look over my draft", True),
    ("check my spelling", True),
])
def test_suggestion_mode_reads_words_and_not_substrings(text, wants):
    """The same substring class in the document path: `review` is inside
    **preview**, so *"can you preview this slide"* turned the open document
    into suggestion mode. Anchoring the left edge only keeps every inflection
    a person types."""
    assert bool(al._SUGGEST_INTENT_RE.search(text)) is wants


def test_the_domain_matchers_already_match_words(monkeypatch):
    """`Law 3`, recorded rather than assumed: the eleven domain regexes in
    `_classify_agent_request` are already `\\b`-anchored, so the substring
    defect this row fixes was in the two keyword *lists*, not in them. The
    case that proves it both ways: `chat` in "chateau" matched the admin list
    and never matched the `sessions` domain."""
    def domains(text):
        return al._classify_agent_request([{"role": "user", "content": text}], text)["domains"]
    assert domains("my dog ate the chateau cheese") == set()
    assert "sessions" in domains("archive chat please")
    assert domains("serverless is a silly word") == set()
    assert "cookbook" in domains("is the server running")


# ── 4. the prompt promises only what the request carries ─────────────────────

def _named_but_not_offered(prompt: str, offered) -> list:
    """Schema-backed tool names the prompt backticks and the array withholds.

    Stricter than `fx6-tools`' `_promised_but_absent`, which asks whether a
    **line** names no offered tool — and so cannot see a line that names one
    tool the turn has and one it does not. That is every one of the five names
    `fx9-proof` measured. Schema-less names are excluded because the prompt is
    their only channel by design (`P17-06`, `H09`'s `_schema_backed_tool_names`).
    """
    known = set(known_tool_names()) & set(al._schema_backed_tool_names())
    return sorted({n for n in BACKTICKED.findall(prompt) if n in known} - set(offered))


@pytest.mark.parametrize("name", [
    "adopt_served_model", "app_api", "manage_memory", "serve_model", "write_file",
])
def test_the_prompt_does_not_promise_a_tool_a_gate_holds(monkeypatch, name):
    """`fx9-proof` `B-NEW-8`, measured per name: for a non-admin these five
    were `prompt_only` in every cell of the matrix, each on a line that also
    named a tool the turn did have."""
    _base(monkeypatch, _mcp_manager(), blocked=NON_ADMIN_BLOCKED_TOOLS)
    sent = _drive(monkeypatch, message=OWNER_QUESTION, prompt_type="agent")
    # Not vacuous: on the base tree this turn carried no prompt at all, so an
    # assertion about what the prompt names would have passed for the wrong
    # reason. There has to be a prompt before there is a promise in it.
    assert sent[0]["prompt"].count("\n") > 20, "no system prompt was built at all"
    assert name not in sent[0]["tools"], "the gate stopped holding it"
    assert name not in _named_but_not_offered(sent[0]["prompt"], sent[0]["tools"])


def test_the_prompt_names_no_schema_backed_tool_the_request_withholds(monkeypatch):
    """The whole property, both privileges."""
    for blocked in ((), NON_ADMIN_BLOCKED_TOOLS):
        _base(monkeypatch, _mcp_manager(), blocked=blocked)
        sent = _drive(monkeypatch, message=OWNER_QUESTION, prompt_type="agent")
        assert sent[0]["prompt"].count("\n") > 20, "no system prompt was built at all"
        assert _named_but_not_offered(sent[0]["prompt"], sent[0]["tools"]) == []


@pytest.mark.parametrize("fragment", [
    "`list_serve_presets` for a preset",
    "the presets do not cover with `serve_model`",
    "`serve_preset` so the UI can track",
    "`serve_model` so the UI can track",
    "verify with `list_served_models`",
    "invisible, use `adopt_served_model`",
    "Journal that progress to `manage_notes`",
    "store it with `manage_rag`",
    "can go to `write_file`",
    "Use `manage_memory` ONLY for durable facts",
    "do NOT `web_fetch` the `/api/research/report/{id}` URL",
    "Do NOT `app_api` it either",
    "goes in `manage_contact`",
])
def test_the_split_rules_still_ship_when_their_tools_do(fragment):
    """`Law 1`. Every clause the split came out of is still in the prompt when
    the whole register is available — the split moved guidance onto its own
    line so the existing filter can drop it, it did not delete any."""
    whole = al._assemble_prompt(set(al._schema_backed_tool_names())
                                | set(al.TOOL_SECTIONS), set())
    assert fragment in whole, fragment


def test_no_one_tool_prompt_names_more_tools_than_it_used_to():
    """A census, so the five cannot come back by a new line being written the
    old way (`Law 20` — it calls `_assemble_prompt`, it does not grep it).

    Measured on `b6a1bbf`: **148 of 148** one-tool prompts (74 schema-backed
    tools x full and compact) named a schema-backed tool the turn withheld —
    **551** name-instances, because `manage_memory`'s own section and the
    working-memory rule shipped on every one of them and between them named
    `manage_contact`, `manage_notes`, `manage_rag` and `write_file`.
    After the split: **28 of 148**, 28 instances, and every one is a pair of sibling
    tools cross-referencing each other — `glob`/`grep`, `web_search`/
    `web_fetch`, `edit_file`/`write_file`, `edit_document`/`update_document`,
    `list_sessions`/`manage_session`, `list_downloads`/`list_served_models`.
    Those two are always in the same `_DOMAIN_TOOL_MAP` family, so the product
    offers them together and no cell of the matrix sees it; a workflow AI step
    whose `allowed_tools` is one of a pair does, which is filed rather than
    guessed at. The bound only goes down.
    """
    schema_backed = set(al._schema_backed_tool_names())
    pinned = {"ask_user", "update_plan", "manage_memory"}
    gaps = []
    for tool in sorted(schema_backed):
        included = {tool} | pinned
        for compact in (False, True):
            prompt = al._assemble_prompt(set(included), set(), compact=compact)
            gap = _named_but_not_offered(prompt, included)
            if gap:
                gaps.append((tool, compact, gap))
    assert len(gaps) <= 28, [g for g in gaps if len(g[2]) > 1 or g[0] in (
        "serve_model", "tail_serve_output", "manage_memory", "manage_research")]


def test_a_tool_a_gate_holds_is_still_not_offered(monkeypatch):
    """`FORBIDDEN.md` Part 2. Nothing here widens what may be run: a first
    message now carries the suite, and the suite is still the complement of
    `disabled_tools`."""
    _base(monkeypatch, _mcp_manager(), blocked=NON_ADMIN_BLOCKED_TOOLS)
    sent = _drive(monkeypatch, message=ORDINARY_TURN, prompt_type="agent")
    assert sent[0]["has_tools_key"]
    held = sorted(set(sent[0]["tools"]) & set(NON_ADMIN_BLOCKED_TOOLS))
    assert held == [], held
    assert "bash" not in sent[0]["tools"]
