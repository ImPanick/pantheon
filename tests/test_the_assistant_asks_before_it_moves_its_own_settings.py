# SPDX-License-Identifier: AGPL-3.0-or-later
"""`B897` and `B912` — `manage_settings` asks before it widens the assistant's reach.

`D-2026-10-25-01`: *"self switch is good with user consent."* `P7-02` made a
`ui_control` switch turned on ask every time. Through `manage_settings` the same
widening went unasked: measured against a scratch data dir in a clean run at the
default rung, the executor switched `image_gen_enabled`, `teacher_enabled`,
`teacher_tier2_enabled`, `stt_enabled`, `allow_model_download` and
`metrics_enabled` on, moved `remote_images` up, wrote a new address into four
destinations, and `enable_tool shell` took `bash` out of the `disabled_tools` an
admin wrote. The gate let every one of those calls through.

Now each asks through `P7-02`'s one mechanism (`self_escalation_for`), at every
rung, tainted or clean and past any blanket yes; nothing moves until the person
says yes; narrowing stays unasked. Driven against a real settings file, the real
gate, the real executor and the real agent loop (`Law 20`).
"""

import asyncio
import importlib
import json

import pytest

import src.agent_tools  # noqa: F401  (break the agent_tools <-> tool_parsing import cycle)
from src.tool_approvals import tool_approval_store
from src.tool_capabilities import (
    POST_EXTERNAL_BLOCKED_EFFECTS,
    ToolRunSecurityContext,
    TrustRung,
    self_escalation_for,
)


@pytest.fixture
def stored(tmp_path, monkeypatch):
    """A settings file of our own, read the way the product reads it."""
    monkeypatch.setenv("PANTHEON_DATA_DIR", str(tmp_path))
    for name in ("PANTHEON_ALLOW_MODEL_DOWNLOAD", "PANTHEON_METRICS_ENABLED",
                 "SEARXNG_WIDEN_ENGINES", "PANTHEON_OTLP_ENDPOINT"):
        monkeypatch.delenv(name, raising=False)
    import src.constants
    import src.settings as settings
    importlib.reload(src.constants)
    importlib.reload(settings)

    def write(values=None):
        (tmp_path / "settings.json").write_text(json.dumps(values or {}), encoding="utf-8")
        settings._invalidate_caches()
        return settings

    yield write
    monkeypatch.delenv("PANTHEON_DATA_DIR", raising=False)
    importlib.reload(src.constants)
    importlib.reload(settings)


def _call(**args):
    return json.dumps(args)


def _set(key, value):
    return _call(action="set", key=key, value=value)


def _manage(content):
    from src.agent_tools.admin_tools import do_manage_settings
    return asyncio.run(do_manage_settings(content))


# Each widening the row measured, the stored state it starts from, and what the
# executor stores when it runs. The keys the row listed, plus the same shape the
# gate's table holds beside them.
_WIDENINGS = [
    ("image_gen_enabled", {}, _set("image_gen_enabled", True), True),
    ("teacher_enabled", {}, _set("teacher", "on"), True),
    ("teacher_tier2_enabled", {}, _set("teacher_tier2_enabled", "yes"), True),
    ("stt_enabled", {}, _set("speech to text", "enabled"), True),
    ("allow_model_download", {}, _set("allow_model_download", "true"), "true"),
    ("metrics_enabled", {}, _set("metrics_enabled", "true"), "true"),
    ("searxng_widen_engines", {}, _set("searxng_widen_engines", "true"), "true"),
    ("agent_lan_reach", {"agent_lan_reach": False}, _set("agent_lan_reach", True), True),
    ("remote_images", {}, _set("remote_images", "proxy"), "proxy"),
    ("remote_images", {"remote_images": "block"}, _set("remote_images", "ask"), "ask"),
    ("otlp_endpoint", {}, _set("otlp_endpoint", "https://collector.attacker.example"),
     "https://collector.attacker.example"),
    ("search_url", {}, _set("search_url", "https://search.attacker.example"),
     "https://search.attacker.example"),
    ("reminder_email_to", {}, _set("reminder_email_to", "someone@attacker.example"),
     "someone@attacker.example"),
    ("reminder_ntfy_topic", {}, _set("ntfy topic", "leaked-reminders"), "leaked-reminders"),
    ("search_provider", {}, _set("search engine", "duckduckgo"), "duckduckgo"),
    ("netagent_url", {}, _set("netagent_url", "http://10.9.9.9:7000"), "http://10.9.9.9:7000"),
]
_IDS = [f"{key}<-{json.loads(content)['value']}" for key, _, content, _ in _WIDENINGS]


@pytest.mark.parametrize("key,start,content,written", _WIDENINGS, ids=_IDS)
def test_the_executor_really_moves_each_of_these(stored, key, start, content, written):
    """The premise, measured: each call below writes the change it asks for."""
    settings = stored(start)
    result = _manage(content)
    assert result["exit_code"] == 0, result
    assert settings.load_settings()[key] == written


@pytest.mark.parametrize("key,start,content,written", _WIDENINGS, ids=_IDS)
def test_a_clean_default_run_asks_before_each_widening(stored, key, start, content, written):
    stored(start)
    decision = ToolRunSecurityContext().decision_for("manage_settings", content)

    assert decision.allowed is False, key
    assert decision.reason.startswith("The assistant wants to "), decision.reason
    assert "every time" in decision.reason
    assert "untrusted" not in decision.reason.lower()
    blocked = {effect.value for effect in POST_EXTERNAL_BLOCKED_EFFECTS}
    assert decision.tripped_effects and set(decision.tripped_effects) <= blocked


@pytest.mark.parametrize("rung", list(TrustRung))
@pytest.mark.parametrize("tainted", [False, True])
@pytest.mark.parametrize("bypassed", [False, True])
def test_it_asks_at_every_rung_in_every_run_and_past_any_blanket_approval(
    stored, rung, tainted, bypassed
):
    context = ToolRunSecurityContext(
        rung=rung, external_untrusted_context_seen=tainted, approval_gate_bypassed=bypassed,
    )
    for key, start, content, _written in _WIDENINGS:
        stored(start)
        assert context.decision_for("manage_settings", content).allowed is False, key
    stored({"disabled_tools": ["bash", "host_shell", "web_search"]})
    assert context.decision_for(
        "manage_settings", _call(action="enable_tool", tool="shell")).allowed is False


def test_a_destination_card_names_the_address(stored):
    stored({})
    reason = ToolRunSecurityContext().decision_for(
        "manage_settings", _set("otlp_endpoint", "https://collector.attacker.example")).reason
    assert reason.startswith(
        "The assistant wants to push this instance's metrics to "
        "“https://collector.attacker.example”. Only you can choose where Pantheon sends things")


# ── B912: an admin-disabled tool ─────────────────────────────────────────────

def test_enable_tool_for_a_disabled_tool_asks_and_moves_nothing_until_yes(stored, monkeypatch):
    settings = stored({"disabled_tools": ["bash", "host_shell", "web_search"]})
    content = _call(action="enable_tool", tool="shell")

    # The premise: run unasked, the executor hands the agent its shell back.
    assert _manage(content)["disabled"] == ["web_search"]
    settings = stored({"disabled_tools": ["bash", "host_shell", "web_search"]})

    decision = ToolRunSecurityContext().decision_for("manage_settings", content)
    assert decision.allowed is False
    assert "turn shell back on (bash, host_shell)" in decision.reason
    # Ranked by what it hands over: the host shell can destroy.
    assert decision.tripped_effects[0] == "destructive"
    assert settings.load_settings()["disabled_tools"] == ["bash", "host_shell", "web_search"]


def test_enable_tool_for_a_tool_nobody_disabled_moves_nothing_so_asks_nothing(stored):
    stored({"disabled_tools": ["web_search"]})
    assert self_escalation_for("manage_settings", _call(action="enable_tool", tool="shell")) is None
    assert ToolRunSecurityContext().decision_for(
        "manage_settings", _call(action="enable_tool", tool="shell")).allowed is True


# ── Narrowing, and calls that move nothing, stay exactly as unasked ─────────

_NARROWINGS = [
    ({"image_gen_enabled": True}, _set("image_gen_enabled", False)),
    ({}, _set("image_gen_enabled", False)),
    ({"image_gen_enabled": True}, _set("image_gen_enabled", True)),   # already on
    ({}, _set("remote_images", "block")),
    ({"remote_images": "proxy"}, _set("remote_images", "ask")),
    ({}, _set("remote_images", "allow")),            # not a mode: refused, moves nothing
    ({"otlp_endpoint": "https://mine.example"}, _set("otlp_endpoint", "")),
    ({"otlp_endpoint": "https://mine.example"}, _set("otlp_endpoint", "https://mine.example")),
    ({"metrics_enabled": "true"}, _call(action="reset", key="metrics_enabled")),
    ({}, _call(action="disable_tool", tool="shell")),
    ({}, _call(action="get", key="otlp_endpoint")),
    ({}, _call(action="list")),
    ({}, _set("tts_voice", "nova")),                   # not reach
]


@pytest.mark.parametrize("start,content", _NARROWINGS)
def test_narrowing_and_no_op_calls_are_not_asked_about(stored, start, content):
    stored(start)
    assert self_escalation_for("manage_settings", content) is None, content
    assert ToolRunSecurityContext().decision_for("manage_settings", content).allowed is True


def test_a_value_that_is_not_a_mode_is_refused_rather_than_stored(stored):
    settings = stored({})
    result = _manage(_set("remote_images", "allow"))
    assert result["exit_code"] == 1
    assert "ask, proxy, block" in result["error"]
    assert settings.load_settings()["remote_images"] == "ask"


def test_an_unreadable_store_fails_high(stored, monkeypatch):
    settings = stored({})

    def _broken():
        raise OSError("disk gone")

    monkeypatch.setattr(settings, "load_settings", _broken)
    assert self_escalation_for("manage_settings", _set("image_gen_enabled", True)) is not None
    assert self_escalation_for(
        "manage_settings", _call(action="enable_tool", tool="shell")) is not None


# ── One reading, shared by the executor and the gate (`Law 7`) ──────────────

def test_an_alias_added_in_one_place_is_learned_by_both(stored, monkeypatch):
    from types import MappingProxyType

    import src.settings_requests as settings_requests

    widened = dict(settings_requests.SETTING_ALIASES)
    widened["pictures"] = "image_gen_enabled"
    monkeypatch.setattr(settings_requests, "SETTING_ALIASES", MappingProxyType(widened))
    settings = stored({})

    assert ToolRunSecurityContext().decision_for(
        "manage_settings", _set("pictures", "on")).allowed is False
    assert _manage(_set("pictures", "on"))["exit_code"] == 0
    assert settings.load_settings()["image_gen_enabled"] is True


def test_an_exact_allow_rule_for_a_widening_is_refused(stored):
    from src import tool_allow_rules

    stored({})
    with pytest.raises(tool_allow_rules.AllowRuleError):
        tool_allow_rules.create_rule(
            "alice", "manage_settings", "exact", _set("image_gen_enabled", True))


# ── Through the real agent loop ─────────────────────────────────────────────

def _drive(monkeypatch, *, rounds):
    import src.agent_loop as agent_loop

    monkeypatch.setattr(
        agent_loop, "get_setting",
        lambda key, default=None: "gate_on_untrusted" if key == "trust_rung" else default,
        raising=False,
    )
    monkeypatch.setattr(agent_loop, "get_mcp_manager", lambda: None, raising=False)
    monkeypatch.setattr(agent_loop, "estimate_tokens", lambda *a, **k: 10)
    monkeypatch.setattr(agent_loop, "blocked_tools_for_owner", lambda owner: set(), raising=False)
    # `manage_settings` is an admin's tool; the person here is one.
    import src.tool_execution as tool_execution
    monkeypatch.setattr(tool_execution, "_owner_is_admin", lambda owner: True)
    scripted = iter(rounds)

    async def fake_stream(*args, **kwargs):
        yield f"data: {json.dumps({'delta': next(scripted, 'Done.')})}\n\n"
        yield "data: [DONE]\n\n"

    monkeypatch.setattr(agent_loop, "stream_llm_with_fallback", fake_stream)
    return agent_loop


def _events(agent_loop, *, session_id, exact_approval=None, message="go"):
    async def _collect():
        return [
            chunk
            async for chunk in agent_loop.stream_agent_loop(
                "http://local.test/v1", "small-local-model",
                [{"role": "user", "content": message}],
                max_rounds=2, relevant_tools={"manage_settings"}, owner="alice",
                session_id=session_id, exact_approval=exact_approval,
            )
        ]

    out = []
    for chunk in asyncio.run(_collect()):
        if chunk.startswith("data: ") and not chunk.startswith("data: [DONE]"):
            try:
                out.append(json.loads(chunk[6:]))
            except json.JSONDecodeError:
                pass
    return out


def _cards(events):
    return [
        event["ask_user"] for event in events
        if event.get("type") == "tool_output"
        and (event.get("ask_user") or {}).get("kind") == "tool_approval"
    ]


def test_through_the_loop_the_shell_stays_off_until_the_person_says_yes(stored, monkeypatch):
    settings = stored({"disabled_tools": ["bash", "host_shell", "web_search"]})
    call = '```manage_settings\n{"action": "enable_tool", "tool": "shell"}\n```'
    session = "b912-loop"
    loop = _drive(monkeypatch, rounds=[call, "Done."])
    first = _events(loop, session_id=session)

    cards = _cards(first)
    assert len(cards) == 1
    assert "turn shell back on" in cards[0]["description"]
    assert settings.load_settings()["disabled_tools"] == ["bash", "host_shell", "web_search"]

    grant = tool_approval_store.consume(
        cards[0]["approval_id"], decision="approve_task", owner="alice", session_id=session)
    loop = _drive(monkeypatch, rounds=["Done."])
    _events(loop, session_id=session, exact_approval=grant, message="approved")
    settings._invalidate_caches()
    assert settings.load_settings()["disabled_tools"] == ["web_search"]


def test_through_the_loop_a_destination_is_not_written_unasked(stored, monkeypatch):
    settings = stored({})
    call = ('```manage_settings\n{"action": "set", "key": "otlp_endpoint", '
            '"value": "https://collector.attacker.example"}\n```')
    loop = _drive(monkeypatch, rounds=[call, "Done."])
    events = _events(loop, session_id="b897-loop")

    cards = _cards(events)
    assert len(cards) == 1
    assert "https://collector.attacker.example" in cards[0]["description"]
    tool_approval_store.consume(
        cards[0]["approval_id"], decision="deny", owner="alice", session_id="b897-loop")
    settings._invalidate_caches()
    assert settings.load_settings()["otlp_endpoint"] == ""
