# SPDX-License-Identifier: AGPL-3.0-or-later
"""`P22-09` / `P22-17` — a `never` slot never fills (`src/workflow_slots.py`,
`SLICE-CD-DESIGN` § 5, the pure layer's half).

**The adversary (`Law 17`, `D-2026-10-01-05` §4):** whoever writes an inbound
mail or webhook body, and through a model's output whoever steered it. Their
bytes may reach a `value` slot — the words of a message the author already
decided to send. They must never choose the tool, the destination, a
recipient, a URL, a host or a command. Held here by calling the real registry,
the real classifier, the real `render_call` and the real `validate_document`
(`Law 20`, option 1):

  1. **Registry completeness** — every setting of every kind, and every
     parameter of every built-in action, resolves to a `Slot` whose mapping is
     one of the two words; a setting added without a declaration turns red.
  2. **The classifier table** — the names § 5.2 lists come out `never` and
     `value` as listed; a `format: uri`/`email` field named `text` is `never`;
     fuzzed names not on the allowlist are `never`.
  3. **Refused at save** — a reference in every `never` setting § 5.3 lists,
     and its obfuscations; a reference to a step that does not run before it.
  4. **Refused at run** — a document written straight to the database: the
     call is not built (`SlotError`), so nothing could be dispatched.
  5. **Injection into value slots** — a value is a dict value, dumped once: it
     never becomes JSON structure, a key, a path or a URL.

The route-level half of § 5.3 (the real save routes) and § 5.4's empty
`execute_tool_block` recorder are `wf-walker`'s, over these same functions.
"""

import json
import random
import string

import pytest

from tests.helpers.import_state import clear_fake_database_modules

clear_fake_database_modules()

from src import workflow_document as wd  # noqa: E402
from src import workflow_refs as wr  # noqa: E402
from src import workflow_slots as ws  # noqa: E402
from src.builtin_actions import BUILTIN_ACTION_META  # noqa: E402
from src.task_action_policy import ADMIN_ONLY_TASK_ACTIONS  # noqa: E402

CHAT_SCHEMA = {"type": "object", "properties": {
    "channel": {"type": "string"}, "chat_id": {"type": "integer"},
    "to": {"type": "string", "format": "email"}, "text": {"type": "string"},
    "count": {"type": "integer"}, "urgent": {"type": "boolean"},
    "details": {"type": "integer"}, "answer": {"type": "boolean"},
    "subject": {"type": "string", "enum": ["Daily", "Weekly"]},
    "body_html": {"type": ["string", "null"]},
    "attachments": {"type": "array"}, "meta": {"type": "object"},
    "link_text": {"type": "string", "format": "uri"},
    # Allowlisted NAMES whose schema still says never: the schema decides too.
    "caption": {"type": "string", "format": "uri"}, "notes": {"type": "array"},
    "summary": {"type": "object"},
}}
RES = wd.WorkflowResources(
    integrations={"miniflux": {"name": "Miniflux", "enabled": True}},
    mcp_tools={"mcp__chat__send_message": {"input_schema": CHAT_SCHEMA, "disabled": False,
                                           "is_readonly": False}},
    skills=frozenset({"print-queue"}), ai_tools=frozenset({"web_search"}),
    workstation_why=None)


def step(node_id, kind="llm", label=None, **config):
    if kind == "llm" and "prompt" not in config:
        config["prompt"] = "Summarise."
    return {"id": node_id, "kind": kind, "label": label or node_id.upper(),
            "config": config, "position": None, "pinned": None}


def after_fetch(node, *, admin=True):
    """`node` after a step `fetch`, checked as at save."""
    graph = wd.parse_graph({"v": 1, "nodes": [step("fetch"), node],
                            "edges": [{"from": "fetch", "port": "success", "to": node["id"]}]})
    return wd.validate_document(graph, owner="alice", tasks_by_id={}, crew_ids=set(),
                                owner_is_admin=admin, own_task_id="trigger", resources=RES)


# ── 1. Registry completeness ─────────────────────────────────────────────────

# A sample of every kind with every setting filled, so each path is asked.
FULL = {
    "llm": {"prompt": "p", "model": "m", "endpoint_url": "http://x", "character_id": "c",
            "crew_member_id": "c", "max_steps": 5, "output_target": "session",
            "tools": ["web_search"], "answer_fields": [{"name": "t", "type": "text",
                                                       "description": "d"}]},
    "research": {"prompt": "p", "model": "m", "endpoint_url": "u", "output_target": "o"},
    "action": {"action": "ssh_command", "prompt": "ls", "output_target": "o"},
    "run_task": {"task_id": "t"},
    "if": {"conditions": [{"left": "l", "op": "equals", "right": "r"}], "join": "all"},
    "switch": {"cases": [{"id": "a", "label": "A", "join": "any",
                          "conditions": [{"left": "l", "op": "one_of", "right": ["x", "y"]}]}]},
    "set": {"fields": [{"name": "n", "value": "v"}]},
    "merge": {"mode": "all"},
    "wait": {"mode": "until", "minutes": 5, "time": "08:00", "tz": "UTC"},
    "foreach": {"list": "{{ steps.a.data.l }}", "on_error": "stop",
                "step": {"kind": "llm", "label": "L", "config": {"prompt": "p", "model": "m"}}},
    "http": {"integration": "i", "method": "POST", "path": "/p",
             "headers": [{"name": "H", "value": "v"}], "query": [{"name": "text", "value": "v"}],
             "body": [{"name": "url", "value": "v"}], "body_mode": "json"},
    "mcp": {"tool": "mcp__chat__send_message", "args": {"text": "v", "channel": "c"}},
    "skill": {"skill": "s", "prompt": "p", "model": "m", "endpoint_url": "u", "max_steps": 3,
              "output_target": "o"},
    "code": {"language": "python", "source": "print(1)", "timeout_seconds": 30,
             "input": [{"name": "x", "value": "v"}]},
}


def test_every_kind_is_in_the_registry_and_nothing_else_is():
    assert set(ws.NODE_SLOTS) == set(wd.NODE_KINDS) == set(FULL)


@pytest.mark.parametrize("kind", wd.NODE_KINDS)
def test_every_setting_of_every_kind_declares_value_or_never(kind):
    """Adding a field to `NODE_CONFIG_FIELDS` without a declaration fails
    here: the table must name it explicitly, not reach it by falling closed."""
    assert set(wd.NODE_CONFIG_FIELDS[kind]) == set(ws.declared_fields(kind)), kind
    assert set(FULL[kind]) == set(wd.NODE_CONFIG_FIELDS[kind]), "the sample fills every setting"
    node = {"kind": kind, "config": FULL[kind]}
    leaves = list(ws.config_leaves(FULL[kind]))
    for path, _value in leaves:
        slot = ws.slot_for(node, path, mcp_schema=CHAT_SCHEMA)
        assert isinstance(slot, ws.Slot) and slot.mapping in ws.MAPPINGS, (kind, path)
        assert (slot.carry in ws.CARRIES) if slot.mapping == ws.MAPPING_VALUE \
            else (slot.carry is None and slot.why in ws.WHYS), (kind, path, slot)


def test_every_action_parameter_declares_its_mapping_and_all_four_are_never():
    params = [(name, p) for name, meta in BUILTIN_ACTION_META.items()
              for p in meta.get("params") or ()]
    assert len(params) == 4, "§ 0.7: four actions take a parameter"
    for name, param in params:
        assert param["mapping"] in ws.MAPPINGS, (name, param)
        assert param["mapping"] == ws.MAPPING_NEVER, (name, param)
        assert ws.action_param_slots(name)[param["name"]].mapping == ws.MAPPING_NEVER
    assert {name for name, _ in params} == set(ADMIN_ONLY_TASK_ACTIONS)


def test_an_action_prompt_with_no_declared_parameter_is_never():
    for action, meta in BUILTIN_ACTION_META.items():
        slot = ws.slot_for({"kind": "action", "config": {"action": action}}, ("prompt",))
        assert slot.mapping == ws.MAPPING_NEVER, action
    assert ws.slot_for({"kind": "action", "config": {"action": "no_such"}}, ("prompt",)) \
        .mapping == ws.MAPPING_NEVER


def test_a_parameter_that_declares_value_or_nothing_is_read_as_declared(monkeypatch):
    """The declaration is read off the parameter — and a missing or misspelt
    one fails closed."""
    meta = dict(BUILTIN_ACTION_META)
    meta["probe"] = {"params": [{"name": "words", "source": "prompt", "mapping": "value"}]}
    meta["probe2"] = {"params": [{"name": "words", "source": "prompt"}]}
    meta["probe3"] = {"params": [{"name": "words", "source": "prompt", "mapping": "Value"}]}
    monkeypatch.setattr("src.builtin_actions.BUILTIN_ACTION_META", meta)
    assert ws.slot_for({"kind": "action", "config": {"action": "probe"}}, ("prompt",)) \
        == ws.VALUE_INLINE
    for action in ("probe2", "probe3"):
        assert ws.slot_for({"kind": "action", "config": {"action": action}},
                           ("prompt",)).mapping == ws.MAPPING_NEVER


@pytest.mark.parametrize("kind,path,mapping", [
    ("llm", ("prompt",), "value"), ("llm", ("model",), "never"),
    ("llm", ("endpoint_url",), "never"), ("llm", ("output_target",), "never"),
    ("llm", ("tools", 0), "never"), ("llm", ("answer_fields", 0, "name"), "never"),
    ("research", ("prompt",), "value"), ("run_task", ("task_id",), "never"),
    ("if", ("conditions", 0, "left"), "value"), ("if", ("conditions", 3, "right"), "value"),
    ("if", ("conditions", 0, "right", 2), "value"), ("if", ("conditions", 0, "op"), "never"),
    ("if", ("join",), "never"), ("switch", ("cases", 0, "label"), "never"),
    ("switch", ("cases", 1, "id"), "never"), ("switch", ("cases", 0, "conditions", 0, "left"), "value"),
    ("switch", ("cases", 0, "conditions", 0, "op"), "never"),
    ("set", ("fields", 0, "name"), "never"), ("set", ("fields", 0, "value"), "value"),
    ("set", ("fields", 0, "value", "nested"), "value"),
    ("merge", ("mode",), "never"), ("wait", ("time",), "never"), ("wait", ("tz",), "never"),
    ("wait", ("minutes",), "never"), ("foreach", ("list",), "value"),
    ("foreach", ("on_error",), "never"), ("foreach", ("step", "kind"), "never"),
    ("foreach", ("step", "config", "prompt"), "value"),
    ("foreach", ("step", "config", "model"), "never"),
    ("http", ("integration",), "never"), ("http", ("method",), "never"),
    ("http", ("path",), "never"), ("http", ("headers", 0, "value"), "never"),
    ("http", ("query", 0, "name"), "never"), ("http", ("query", 0, "value"), "value"),
    ("http", ("body", 0, "value"), "never"),  # its name is `url`
    ("http", ("body_mode",), "never"), ("mcp", ("tool",), "never"),
    ("mcp", ("args", "text"), "value"), ("mcp", ("args", "channel"), "never"),
    ("mcp", ("args",), "never"), ("skill", ("skill",), "never"), ("skill", ("prompt",), "value"),
    ("code", ("source",), "never"), ("code", ("language",), "never"),
    ("code", ("timeout_seconds",), "never"), ("code", ("input", 0, "value"), "value"),
    ("code", ("input", 0, "name"), "never"),
    ("llm", ("no_such_setting",), "never"), ("teleport", ("anything",), "never"),
    ("llm", (), "never"),
])
def test_the_table_reads_as_the_design_s_table(kind, path, mapping):
    assert ws.slot_for({"kind": kind, "config": FULL.get(kind, {})}, path,
                       mcp_schema=CHAT_SCHEMA).mapping == mapping


def test_prompt_slots_ride_in_the_untrusted_block_and_research_inline():
    assert ws.slot_for({"kind": "llm"}, ("prompt",)).carry == ws.CARRY_CONTEXT
    assert ws.slot_for({"kind": "skill"}, ("prompt",)).carry == ws.CARRY_CONTEXT
    assert ws.slot_for({"kind": "research"}, ("prompt",)).carry == ws.CARRY_INLINE


# ── 2. The classifier table ──────────────────────────────────────────────────

NEVER_NAMES = (
    "to", "cc", "bcc", "recipient", "recipients", "email", "address", "channel", "chat_id",
    "room", "user_id", "url", "uri", "href", "webhook", "host", "hostname", "server", "port",
    "ip", "path", "file", "command", "cmd", "script", "code", "sql", "query", "method",
    "headers", "token", "key", "secret", "action", "id", "target", "dest", "phone", "reply_to",
    "replyTo", "message_id", "messageId", "text_to", "toText", "text2", "", "text.to", "tеxt",
    "ｔｅｘｔ", "text ", "body/url", "x" * 65, "__", "-_-",
)
VALUE_NAMES = ("text", "message", "body", "subject", "title", "summary", "body_html",
               "message_text", "messageText", "HTMLBody", "bodyHTML", "TEXT", "msg", "md",
               "plain_text", "reply", "answer", "markdown", "caption", "comment-text")


@pytest.mark.parametrize("name", NEVER_NAMES)
def test_a_name_that_could_be_a_destination_is_never(name):
    assert ws.classify_argument(name, {"type": "string"}).mapping == ws.MAPPING_NEVER, name


@pytest.mark.parametrize("name", VALUE_NAMES)
def test_a_name_that_only_ever_holds_words_is_value(name):
    assert ws.classify_argument(name, {"type": "string"}) == ws.VALUE_INLINE, name


@pytest.mark.parametrize("schema", [
    {"type": "object"}, {"type": "array"}, {"type": ["string", "object"]}, {}, None, "string",
    {"type": "string", "format": "uri"}, {"type": "string", "format": "email"},
    {"type": "string", "format": "hostname"}, {"type": "string", "format": "uri-template"},
    {"type": "string", "format": "ipv4"}, {"type": "string", "format": "date-time"},
    {"type": "string", "format": "anything-else"}, {"type": 7}, {"type": ["null"]},
])
def test_a_text_name_with_a_structured_or_address_schema_is_never(schema):
    assert ws.classify_argument("text", schema).mapping == ws.MAPPING_NEVER, schema


def test_an_address_format_says_where_and_a_number_or_flag_named_as_words_is_value():
    assert ws.classify_argument("text", {"type": "string", "format": "uri"}).why == ws.WHY_WHERE
    assert ws.classify_argument("text", {"type": "string", "format": "email"}).why == ws.WHY_WHERE
    for kind in ("number", "integer", "boolean", ["string", "null"]):
        assert ws.classify_argument("summary", {"type": kind}) == ws.VALUE_INLINE, kind


def test_fuzzed_names_off_the_allowlist_are_never():
    """§ 5.2: random names. A name is `value` only if every part of it is one
    of the allowlisted words — checked here against the list itself, so the
    classifier failing open on any name is caught."""
    rng = random.Random(1709)
    chars = string.ascii_letters + string.digits + "_-.$ /:@"
    allowed = ws.ARGUMENT_WORDS
    for _ in range(5000):
        if rng.random() < 0.3:
            name = rng.choice(["_", "-", ""]).join(
                rng.choice(sorted(allowed) + ["to", "url", "id", "x"]) for _ in range(rng.randint(1, 3)))
        else:
            name = "".join(rng.choice(chars) for _ in range(rng.randint(0, 24)))
        slot = ws.classify_argument(name, {"type": "string"})
        parts = ws.name_parts(name)
        if slot.mapping == ws.MAPPING_VALUE:
            assert parts and all(p in allowed for p in parts), name
        if not parts or any(p not in allowed for p in parts):
            assert slot.mapping == ws.MAPPING_NEVER, name


# ── 3. Refused at save ───────────────────────────────────────────────────────

REF = "{{ steps.fetch.data.x }}"
SAVE_CASES = [
    ("HTTP path", step("h", "http", integration="miniflux", method="GET", path=REF), "path"),
    ("HTTP path, mid-path", step("h", "http", integration="miniflux", method="GET",
                                 path="/v1/" + REF + "/entries"), "path"),
    ("HTTP integration", step("h", "http", integration=REF, method="GET", path="/"), "integration"),
    ("HTTP method", step("h", "http", integration="miniflux", method=REF, path="/"), "method"),
    ("HTTP header", step("h", "http", integration="miniflux", method="GET", path="/",
                         headers=[{"name": "X-To", "value": REF}]), "headers[0].value"),
    ("HTTP body key not a word", step("h", "http", integration="miniflux", method="POST", path="/",
                                      body=[{"name": "url", "value": REF}]), "body[0].value"),
    ("HTTP query key not a word", step("h", "http", integration="miniflux", method="GET", path="/",
                                       query=[{"name": "q", "value": REF}]), "query[0].value"),
    ("MCP channel", step("m", "mcp", tool="mcp__chat__send_message",
                         args={"channel": REF, "text": "hi"}), "args.channel"),
    ("MCP to", step("m", "mcp", tool="mcp__chat__send_message", args={"to": REF}), "args.to"),
    ("MCP text with a uri format", step("m", "mcp", tool="mcp__chat__send_message",
                                        args={"link_text": REF}), "args.link_text"),
    ("MCP object", step("m", "mcp", tool="mcp__chat__send_message",
                        args={"meta": {"text": REF}}), "args.meta.text"),
    ("MCP caption, a word, with a uri format", step("m", "mcp", tool="mcp__chat__send_message",
                                                    args={"caption": REF}), "args.caption"),
    ("MCP notes, a word, that is a list", step("m", "mcp", tool="mcp__chat__send_message",
                                               args={"notes": REF}), "args.notes"),
    ("MCP summary, a word, that is an object", step("m", "mcp", tool="mcp__chat__send_message",
                                                    args={"summary": REF}), "args.summary"),
    ("MCP message, a word the schema does not have", step("m", "mcp",
                                                          tool="mcp__chat__send_message",
                                                          args={"message": REF}), "args.message"),
    ("ssh_command's command", step("a", "action", action="ssh_command",
                                   prompt="echo " + REF), "prompt"),
    ("run_local's script", step("a", "action", action="run_local", prompt=REF), "prompt"),
    ("an email action's account", step("a", "action", action="summarize_emails",
                                       prompt='{"account": "' + REF + '"}'), "prompt"),
    ("output_target email:{{…}}", step("p", output_target="email:" + REF), "output_target"),
    ("a model", step("p", model=REF), "model"),
    ("an endpoint", step("p", endpoint_url="http://" + REF), "endpoint_url"),
    ("run_task's target", step("r", "run_task", task_id=REF), "task_id"),
    ("Code's source", step("c", "code", language="python", source="print('" + REF + "')"),
     "source"),
    ("Code's language", step("c", "code", language=REF, source="x"), "language"),
    ("a skill name", step("s", "skill", skill=REF), "skill"),
    ("an AI tool list", step("p", tools=[REF]), "tools[0]"),
    ("an answer shape", step("p", answer_fields=[{"name": "t", "type": "text",
                                                  "description": REF}]),
     "answer_fields[0].description"),
    ("Wait's time", step("w", "wait", mode="until", time=REF), "time"),
    ("Wait's zone", step("w", "wait", mode="until", time="08:00", tz=REF), "tz"),
    ("an If operator", step("i", "if", conditions=[{"left": "a", "op": REF, "right": "b"}]),
     "conditions[0].op"),
    ("a Switch label", step("s", "switch", cases=[{"id": "u", "label": REF, "conditions": [
        {"left": "a", "op": "equals", "right": "b"}]}]), "cases[0].label"),
    ("a Set field's name", step("s", "set", fields=[{"name": REF, "value": "v"}]),
     "fields[0].name"),
    ("a Merge mode", step("m", "merge", mode=REF), "mode"),
    ("a For-each's on_error", step("f", "foreach", list=REF, on_error=REF,
                                   step={"kind": "llm", "config": {"prompt": "p"}}), "on_error"),
    ("a For-each inner command", step("f", "foreach", list=REF, step={
        "kind": "action", "config": {"action": "ssh_command", "prompt": "rm {{ item.name }}"}}),
     "step.config.prompt"),
    ("a For-each inner kind", step("f", "foreach", list=REF, step={"kind": REF}), "step.kind"),
]


@pytest.mark.parametrize("name,node,field", SAVE_CASES, ids=[c[0] for c in SAVE_CASES])
def test_a_reference_in_a_never_setting_is_refused_at_save_on_that_field(name, node, field):
    refusal = after_fetch(node)
    assert refusal is not None and refusal.reason == wd.REFUSE_MAPPED_NEVER, (name, refusal)
    assert refusal.field == field, refusal
    assert refusal.node_ids == (node["id"],)
    assert any(why in refusal.sentence for why in ws.WHYS), refusal.sentence


@pytest.mark.parametrize("text", [
    "{{steps.fetch.data.x}}", "{{\tsteps.fetch.data.x\n}}", "{{ steps.fetch.text }}",
    "{{ item }}", "\\{{ steps.fetch.data.x }}", "{{ {{ steps.fetch.data.x }} }}",
    "x{{{ steps.fetch.data.x }}}", "{{ steps.start.data.body }}", "{{ steps.nobody.text }}",
])
def test_every_spelling_of_a_reference_in_a_command_is_refused(text):
    refusal = after_fetch(step("a", "action", action="ssh_command", prompt=f"echo {text}"))
    assert refusal.reason == wd.REFUSE_MAPPED_NEVER, (text, refusal)


@pytest.mark.parametrize("text", [
    "docker ps --format '{{.Names}}'", "kubectl get -o go-template='{{range .items}}{{end}}'",
    "echo ｛｛ steps.fetch.data.x ｝｝", "echo { { steps.fetch.data.x } }",
    "echo {{ STEPS.fetch.data.x }}", "echo {{ steps . fetch.data.x }}",
])
def test_a_command_s_own_braces_are_its_own_text(text):
    """`Law 1`: a Go template in a command was saved before this row and still
    is — what is not a reference stays the person's text, verbatim, and can
    never fill (a `never` setting is never rendered)."""
    assert after_fetch(step("a", "action", action="ssh_command", prompt=text)) is None


@pytest.mark.parametrize("text", [
    "{{ STEPS.fetch.data.x }}", "{{ steps . fetch.data.x }}", "{{ {{ steps.fetch.data.x }} }}",
    "{{ steps.fetch.data.x | upper }}", "{{ steps.fetch.status }}", "{{ steps.fetch.data.x",
])
def test_a_value_setting_refuses_a_brace_that_is_not_a_reference(text):
    refusal = after_fetch(step("p", prompt=f"Summarise {text}"))
    assert refusal.reason == wd.REFUSE_BAD_REFERENCE and refusal.field == "prompt", refusal


@pytest.mark.parametrize("text", ["｛｛ steps.fetch.data.x ｝｝", "\\{{ steps.fetch.data.x }}",
                                  "{ { steps.fetch.data.x } }"])
def test_text_that_only_looks_like_a_reference_saves_and_stays_text(text):
    assert after_fetch(step("p", prompt=f"Summarise {text}")) is None


def test_a_reference_names_only_the_start_or_a_step_before_it():
    two = lambda prompt: wd.validate_document(  # noqa: E731
        wd.parse_graph({"v": 1, "nodes": [step("fetch"), step("sum", prompt=prompt),
                                          step("side")],
                        "edges": [{"from": "fetch", "port": "success", "to": "sum"},
                                  {"from": "fetch", "port": "error", "to": "side"}]}),
        owner="alice", tasks_by_id={}, crew_ids=set(), owner_is_admin=True,
        own_task_id="t", resources=RES)
    assert two("{{ steps.fetch.data.title }}") is None
    assert two("{{ steps.start.data.body }}") is None
    for prompt, words in (("{{ steps.sum.text }}", "reads from itself"),
                          ("{{ steps.side.text }}", "which does not run before it"),
                          ("{{ steps.ghost.text }}", "which is not a step here")):
        refusal = two(prompt)
        assert refusal.reason == wd.REFUSE_NOT_UPSTREAM and words in refusal.sentence, refusal
        assert refusal.field == "prompt"


def test_the_value_settings_the_design_names_take_a_reference():
    for node in (
        step("p", prompt="Summarise " + REF),
        step("r", "research", prompt="Research " + REF),
        step("h", "http", integration="miniflux", method="POST", path="/v1/entries",
             query=[{"name": "title", "value": REF}], body=[{"name": "text", "value": REF}]),
        step("m", "mcp", tool="mcp__chat__send_message", args={"channel": "#ops", "text": REF,
                                                               "details": REF, "answer": REF}),
        step("s", "set", fields=[{"name": "headline", "value": REF}]),
        step("i", "if", conditions=[{"left": REF, "op": "contains", "right": REF}]),
        step("c", "code", language="python", source="print(1)", input=[{"name": "x", "value": REF}]),
        step("k", "skill", skill="print-queue", prompt="Print " + REF),
        step("f", "foreach", list=REF, step={"kind": "llm", "config": {"prompt": "{{ item.s }}"}}),
    ):
        assert after_fetch(node) is None, node


# ── 4. Refused at run: a document written straight to the database ─────────

@pytest.mark.parametrize("node", [
    step("h", "http", integration="miniflux", method="GET", path="/v1/" + REF),
    step("h", "http", integration=REF, method="GET", path="/"),
    step("h", "http", integration="miniflux", method="GET", path="/",
         headers=[{"name": "Authorization", "value": "Bearer " + REF}]),
    step("h", "http", integration="miniflux", method="GET", path="/",
         query=[{"name": "q", "value": REF}]),
    step("m", "mcp", tool="mcp__chat__send_message", args={"channel": REF}),
    step("m", "mcp", tool=REF, args={}),
    step("c", "code", language="python", source="print('" + REF + "')"),
    step("a", "action", action="ssh_command", prompt="echo \\" + REF),
], ids=["path", "integration", "header", "query-q", "mcp-channel", "mcp-tool", "code", "ssh"])
def test_render_call_refuses_a_reference_in_a_never_slot(node):
    ctx = wr.build_context({"fetch": {"data": {"x": "/admin"}, "text": "t"}})
    with pytest.raises(ws.SlotError) as err:
        ws.render_call(node, ctx, mcp_schema=CHAT_SCHEMA)
    assert err.value.field and "nothing was sent" in err.value.sentence


def test_render_call_refuses_what_is_not_a_call():
    for node in (step("p"), step("i", "if"), {"kind": "teleport"}, None):
        with pytest.raises(ws.SlotError):
            ws.render_call(node, {}, mcp_schema=None)


# ── 5. Injection into value slots ────────────────────────────────────────────

HOSTILE = wr.build_context({
    "fetch": {"text": "{{ steps.secret.data.x }}", "data": {
        "quote": '", "path": "/admin", "x": "',
        "obj": {"to": "x@evil", "channel": "#all"},
        "url": "http://169.254.169.254/latest/meta-data/",
        "ref": "{{ steps.secret.data.x }}", "n": "12", "big": "y" * (ws.SLOT_MAX_CHARS + 1),
        "list": ["a", {"to": "b"}], "flag": "yes", "words": "Weekly",
    }},
    "secret": {"data": {"x": "TOP-SECRET"}, "text": "TOP-SECRET"},
})


def http(**over):
    config = {"integration": "miniflux", "method": "POST", "path": "/v1/entries",
              "query": [{"name": "status", "value": "unread"}],
              "body": [{"name": "text", "value": "{{ steps.fetch.data.quote }}"}]}
    config.update(over)
    return step("h", "http", **config)


def test_a_quote_in_a_value_never_becomes_json_structure():
    call = ws.render_call(http(), HOSTILE)
    args = json.loads(call.content)
    assert (call.kind, call.tool) == ("http", "api_call")
    assert args["path"] == "/v1/entries" and args["integration"] == "miniflux"
    assert args["method"] == "POST" and args["params"] == {"status": "unread"}
    assert args["body"] == {"text": '", "path": "/admin", "x": "'}
    assert set(args) == {"integration", "method", "path", "params", "body", "structured"}
    assert call.value_paths == ("body[0].value",) and call.missing == ()


def test_an_object_mapped_into_text_arrives_as_a_string_with_no_new_key():
    call = ws.render_call(step("m", "mcp", tool="mcp__chat__send_message",
                               args={"channel": "#ops", "text": "{{ steps.fetch.data.obj }}"}),
                          HOSTILE, mcp_schema=CHAT_SCHEMA)
    args = json.loads(call.content)
    assert args == {"channel": "#ops", "text": '{"to": "x@evil", "channel": "#all"}'}
    assert call.tool == "mcp__chat__send_message"
    body = json.loads(ws.render_call(http(body=[{"name": "text",
                                                  "value": "{{ steps.fetch.data.list }}"}]),
                                     HOSTILE).content)["body"]
    assert body == {"text": '["a", {"to": "b"}]'}


def test_a_reference_inside_a_value_arrives_literally_and_the_secret_appears_nowhere():
    for value in ("{{ steps.fetch.data.ref }}", "{{ steps.fetch.text }}",
                  "say {{ steps.fetch.text }}!"):
        content = ws.render_call(http(body=[{"name": "text", "value": value}]), HOSTILE).content
        assert "TOP-SECRET" not in content
        assert "{{ steps.secret" in json.loads(content)["body"]["text"]


def test_a_metadata_url_in_a_value_leaves_the_request_where_the_author_sent_it():
    args = json.loads(ws.render_call(http(body=[{"name": "text",
                                                 "value": "{{ steps.fetch.data.url }}"}]),
                                     HOSTILE).content)
    assert (args["integration"], args["path"]) == ("miniflux", "/v1/entries")
    assert args["body"]["text"] == "http://169.254.169.254/latest/meta-data/"


def test_values_coerce_to_the_schema_and_refuse_what_does_not_parse():
    def mcp(**args):
        return ws.render_call(step("m", "mcp", tool="mcp__chat__send_message", args=args),
                              HOSTILE, mcp_schema=CHAT_SCHEMA)
    assert json.loads(mcp(details="{{ steps.fetch.data.n }}").content) == {"details": 12}
    assert json.loads(mcp(answer="{{ steps.fetch.data.flag }}").content) == {"answer": True}
    assert json.loads(mcp(subject="{{ steps.fetch.data.words }}").content) == {"subject": "Weekly"}
    assert json.loads(mcp(body_html="{{ steps.fetch.data.none }}").content) == {"body_html": None}
    for args in ({"details": "{{ steps.fetch.data.quote }}"}, {"answer": "{{ steps.fetch.data.n }}"},
                 {"subject": "{{ steps.fetch.data.quote }}"},
                 # a number or a flag NOT named as words is never, whatever its type
                 {"count": "{{ steps.fetch.data.n }}"}, {"urgent": "{{ steps.fetch.data.flag }}"}):
        with pytest.raises(ws.SlotError):
            mcp(**args)
    literal = mcp(channel="#ops", chat_id=42, meta={"k": [1]})
    assert json.loads(literal.content) == {"channel": "#ops", "chat_id": 42, "meta": {"k": [1]}}
    assert literal.value_paths == ()


def test_the_caps_refuse_rather_than_cut():
    with pytest.raises(ws.SlotError) as err:
        ws.render_call(http(body=[{"name": "text", "value": "{{ steps.fetch.data.big }}"}]),
                       HOSTILE)
    assert "20,000" in err.value.sentence
    huge = wr.build_context({"fetch": {"data": {"s": "z" * 19_000}}})
    body = [{"name": f"text{'_text' * i}", "value": "{{ steps.fetch.data.s }}"} for i in range(4)]
    with pytest.raises(ws.SlotError) as err:
        ws.render_call(http(body=body), huge)
    assert "64 KiB" in err.value.sentence


def test_code_hands_values_on_stdin_as_json_and_never_in_the_source():
    node = step("c", "code", language="python", source="import sys; print(sys.stdin.read())",
                input=[{"name": "prices", "value": "{{ steps.fetch.data.list }}"},
                       {"name": "who", "value": "{{ steps.fetch.text }}"}, {"name": "n", "value": 3}])
    call = ws.render_call(node, HOSTILE)
    assert (call.kind, call.tool) == ("code", "python")
    assert json.loads(call.content) == {"prices": ["a", {"to": "b"}],
                                        "who": "{{ steps.secret.data.x }}", "n": 3}
    assert node["config"]["source"] == "import sys; print(sys.stdin.read())"


def test_an_action_call_is_its_command_verbatim():
    call = ws.render_call(step("a", "action", action="ssh_command", prompt="ls -la /srv"), HOSTILE)
    assert call == ws.RenderedCall("action", "ssh_command", "ls -la /srv", (), ())
