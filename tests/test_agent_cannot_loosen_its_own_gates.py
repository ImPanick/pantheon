"""B42 — the agent could take off the gates that exist to constrain it.

Found while working `H18`, whose framing was "twelve settings the model can
change and a person cannot" and whose own text says `agent_email_confirm` "is
the one that matters". It matters more than that: the row read it as a missing
control, and the missing control is the smaller half.

Measured before anything was written, by the stored value rather than the exit
code (these refusals answer `exit_code: 0` with a message, so an exit code
proves nothing):

    manage_settings set agent_email_confirm false   True -> False

It took effect. The agent could remove the gate requiring a person to approve an
email before it sends — through a tool call that looks identical whether the
instruction came from the operator or from a page the agent was told to read.

`agent_loop.py` already argues this for role profiles: a profile "may only raise
strictness — a profile that lowers the rung hands a user a way to switch their
own confirmation gate off." The same sentence applies with more force to the
agent itself.

**`trust_rung` was in the first version of this and has been removed, and the
removal is the more interesting half.** The measurement was real —
`gate_on_untrusted -> allow_listed` took effect — but calling it "lowering the
ladder" was wrong: `allow_listed` is one of `_RUNGS_THAT_ASK_UNTAINTED`, so it
asks in clean runs that the default lets through. The rungs are not a ladder
that can be read from outside; `decision_for` carries the reproduction showing
"the two stricter rungs were strictly less protected than the one they sit
below". And `test_the_chat_tool_still_sets_a_rung_it_does_implement` sets the
strictest rung from chat on purpose. A refusal here would have been a security
change resting on an ordering the codebase says does not hold. `P7-13`.
"""
import asyncio
import importlib
import json
import pathlib

import pytest

ROOT = pathlib.Path(__file__).resolve().parent.parent
INDEX = (ROOT / "static" / "index.html").read_text(encoding="utf-8")
SETTINGS_JS = (ROOT / "static" / "js" / "settings.js").read_text(encoding="utf-8")


@pytest.fixture
def agent(tmp_path, monkeypatch):
    """`manage_settings` against a data dir of our own, plus a reader."""
    monkeypatch.setenv("PANTHEON_DATA_DIR", str(tmp_path))
    import src.constants, src.settings as S
    importlib.reload(src.constants)
    importlib.reload(S)
    from src.agent_tools.admin_tools import do_manage_settings

    def call(**args):
        result = asyncio.run(do_manage_settings(json.dumps(args)))
        S._invalidate_caches()
        return result

    yield call, S
    monkeypatch.delenv("PANTHEON_DATA_DIR", raising=False)
    importlib.reload(src.constants)
    importlib.reload(S)


GATES = [
    ("agent_email_confirm", False, "the human-approval gate on sending email"),
    ("agent_verifier_subagent", True, "the check on its own claims"),
]


@pytest.mark.parametrize("key,value,what", GATES, ids=[g[0] for g in GATES])
def test_the_agent_cannot_set_it(agent, key, value, what):
    """Asserted on the STORED VALUE. The first version of this measurement read
    `exit_code`, which is 0 for a refusal, and reported three gates as writable
    that were not — and two that were, as if they were the same kind of thing."""
    call, S = agent
    before = S.get_setting(key)
    assert before != value, f"precondition: {key} would have to change to prove anything"
    call(action="set", key=key, value=value)
    assert S.get_setting(key) == before, f"the agent changed {what}"


@pytest.mark.parametrize("key,value,what", GATES, ids=[g[0] for g in GATES])
def test_the_agent_cannot_reset_it_either(agent, key, value, what):
    """`reset` writes the shipped default, which for all three is the SAFE
    direction today — so this refusal is not protecting anything right now. It
    is refused anyway, because "the agent may only move this in the safe
    direction" inverts the day someone changes a default, and a control the
    agent cannot touch is easier to reason about than one it touches
    carefully."""
    call, S = agent
    call(action="set", key=key, value=value)   # blocked, but establishes intent
    result = call(action="reset", key=key)
    assert "Settings" in str(result.get("response", "")), \
        f"reset of {key} did not refuse and point somewhere"


def test_the_refusal_says_where_to_go_instead(agent):
    """A refusal with no destination is one the person works around."""
    call, _ = agent
    response = str(call(action="set", key="agent_email_confirm", value=False).get("response", ""))
    assert "agent_email_confirm" in response, "name the setting"
    assert "Settings" in response, "name where it can be changed"
    assert "including if you ask me to" in response, \
        "the refusal must survive being asked politely, and say so"


def test_the_agent_can_still_read_them(agent):
    """Read-only, not invisible. The agent should be able to say "email is held
    for approval" when asked why a message has not gone out."""
    call, _ = agent
    result = call(action="get", key="agent_email_confirm")
    assert "True" in str(result.get("response", "")) or result.get("value") is not None


def test_ordinary_settings_are_untouched(agent):
    """The restriction has to be narrow or it stops being kept."""
    call, S = agent
    call(action="set", key="agent_max_rounds", value=42)
    assert S.get_setting("agent_max_rounds") == 42


def test_the_loop_caps_are_deliberately_not_in_the_set(agent):
    """`agent_max_rounds` and `agent_max_tool_calls` are runaway and cost caps
    with no approval semantics, and "give yourself more steps" is a real thing
    to ask for. Filed as `P7-12` rather than swept in — a restriction that has
    to be argued each time is one nobody keeps."""
    from src.agent_tools import admin_tools
    source = pathlib.Path(admin_tools.__file__).read_text(encoding="utf-8")
    block = source.split("_SELF_RESTRAINT_KEYS = {", 1)[1].split("}", 1)[0]
    assert "agent_max_rounds" not in block
    assert "agent_max_tool_calls" not in block
    assert "P7-12" in source, "the deliberate omission must point at where it is argued"


# ── the other half of the trade ──

def test_the_person_can_reach_the_email_gate(agent):
    """Taking the setting away from the agent is only a trade if the person has
    it. Before this, `agent_email_confirm` had zero references under `static/`
    except comments about it."""
    assert 'id="set-emailConfirm"' in INDEX
    assert "initEmailConfirm();" in SETTINGS_JS
    assert "agent_email_confirm: !!input.checked" in SETTINGS_JS


def test_a_stored_false_is_not_read_as_missing():
    """The worst direction for this control to be wrong in: showing the gate as
    on while mail goes out unapproved."""
    body = SETTINGS_JS.split("async function initEmailConfirm(", 1)[1].split("\n}", 1)[0]
    assert "settings.agent_email_confirm !== undefined" in body


def test_a_failed_save_puts_the_switch_back():
    """A control that looks changed and did not save is worse here than one
    that visibly refused."""
    body = SETTINGS_JS.split("async function initEmailConfirm(", 1)[1].split("\n}", 1)[0]
    assert "input.checked = !input.checked;" in body
    assert "left unchanged" in body


def test_the_panel_says_the_agent_cannot_turn_it_off():
    """Otherwise the first thing anyone does is ask the agent to.

    Whitespace-normalised: prose in HTML wraps, and the first version of this
    test failed on a sentence that was present and merely had a line break in
    the middle of it. `Law 20`'s point about matching text rather than meaning,
    in its mildest form."""
    import re as _re
    card = _re.sub(r"\s+", " ", INDEX.split('id="set-emailConfirm"', 1)[1][:900])
    assert "the agent cannot turn it off" in card
    assert "looks the same whether it came from you" in card


def test_the_trust_ladder_already_had_a_control():
    """Checked rather than assumed: if `trust_rung` had no UI either, `B42`
    would be a lockout rather than a trade. It has one — and in the end
    `trust_rung` was left writable from chat anyway, so this stands as the
    check that a person can reach it either way."""
    ladder = ROOT / "static" / "js" / "trustLadder.js"
    assert ladder.exists()
    assert "trust_rung" in ladder.read_text(encoding="utf-8")


def test_the_trust_rung_is_deliberately_still_writable(agent):
    """The correction, pinned so it is not quietly undone.

    A future reader looking at `agent_email_confirm` will reasonably ask why the
    confirmation ladder is not beside it. The answer is that no strictness order
    exists to judge a write against, and `P7-13` is where that is argued."""
    call, S = agent
    call(action="set", key="trust_rung", value="ask_every_time")
    assert S.get_setting("trust_rung") == "ask_every_time", \
        "a person asking for MORE confirmation from chat must still work"
    from src.agent_tools import admin_tools
    source = pathlib.Path(admin_tools.__file__).read_text(encoding="utf-8")
    assert "P7-13" in source, "the omission must point at where it is argued"
