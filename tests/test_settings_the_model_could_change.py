"""H18 — settings the model could change and a person could not.

Each of these is read by live code, settable by `manage_settings` under its
exact key, and had **zero references under `static/`**. The row's headline is
the whole of it: the assistant could change them and you could not.

`agent_email_confirm` shipped separately with `B42`, because it turned out the
agent could not only change it but *remove a gate with it*, and that is a
different kind of problem from a missing box.

Two of the twelve are deliberately still without a control, and both are
recorded rather than quietly skipped: `teacher_tier2_enabled` sits inside a card
`index.html` says is "hidden as part of the 2.0 harden-the-core pass… Re-add
this card once the core experience is faster" — a documented decision, not an
oversight — and `task_concurrency_cap` was fixed at the resolution layer by
`H06` without gaining a panel.
"""
import pathlib
import re

import pytest

ROOT = pathlib.Path(__file__).resolve().parent.parent
INDEX = (ROOT / "static" / "index.html").read_text(encoding="utf-8")
JS = (ROOT / "static" / "js" / "settings.js").read_text(encoding="utf-8")


def _fn(name):
    start = JS.index(f"function {name}(")
    i = JS.index("{", start)
    depth, j = 0, i
    while j < len(JS):
        if JS[j] == "{":
            depth += 1
        elif JS[j] == "}":
            depth -= 1
            if depth == 0:
                return JS[start:j + 1]
        j += 1
    raise AssertionError(f"unbalanced braces reading {name}")


SETTINGS_WITH_NEW_CONTROLS = [
    ("document_writing_style", "set-doc-style", "initDocStyle"),
    ("search_safesearch", "set-searchSafesearch", "initSafesearch"),
    ("agent_input_token_budget", "set-agentBudgetMode", "initAgentBudget"),
    ("agent_input_token_hard_max", "set-agentBudgetMax", "initAgentBudget"),
    ("task_endpoint_id", "set-taskEndpoint", "initTaskModel"),
    ("task_model", "set-taskModel", "initTaskModel"),
    ("research_planning_timeout_seconds", "set-researchPlanTimeout", None),
    ("research_query_timeout_seconds", "set-researchQueryTimeout", None),
]


@pytest.mark.parametrize("key,element_id,init", SETTINGS_WITH_NEW_CONTROLS,
                         ids=[c[0] for c in SETTINGS_WITH_NEW_CONTROLS])
def test_the_setting_has_a_control_that_is_wired(key, element_id, init):
    """Markup, a reader, and a writer. Any one of the three missing is a
    control that looks like it works."""
    assert f'id="{element_id}"' in INDEX, f"no markup for {key}"
    assert element_id in JS, f"nothing reads or writes {element_id}"
    assert key in JS, f"{key} is never sent to the settings route"
    if init:
        assert f"{init}();" in JS, f"{init} is defined but never called"


def test_the_token_budget_control_knows_its_default_is_a_sentinel():
    """The trap in this row. `agent_input_token_budget: 6000` means "scale to
    the model's window", not "cap at 6000" — so a plain number box would let
    someone type 6000 meaning a cap and silently get auto. A mode picker, and
    6000 is refused as a fixed value with the setting's own advice."""
    body = _fn("initAgentBudget")
    assert "_AGENT_BUDGET_AUTO" in body
    assert "n === _AGENT_BUDGET_AUTO" in body, "6000 must be refused as a fixed budget"
    assert "scale to the window" in body
    assert "const _AGENT_BUDGET_AUTO = 6000;" in JS


def test_the_sentinel_matches_the_backend():
    """Two files, no link between them. If `DEFAULT_BUDGET` moves and this does
    not, the picker silently starts storing a fixed budget where it meant
    auto."""
    from src.context_budget import DEFAULT_BUDGET
    assert f"const _AGENT_BUDGET_AUTO = {DEFAULT_BUDGET};" in JS


def test_zero_means_no_trimming_and_is_reachable():
    """`0` disables soft-trimming entirely and is a real, documented value —
    not a number to type, which is why it is a mode."""
    body = _fn("initAgentBudget")
    assert "'off'" in body
    assert "payload.agent_input_token_budget = 0;" in body


def test_safesearch_only_adopts_a_value_the_control_can_show():
    """A stored value outside the three would leave the select on its first
    option while the backend used something else — a control that lies about
    the state it is displaying."""
    body = _fn("initSafesearch")
    assert "v === 'strict' || v === 'moderate' || v === 'off'" in body


def test_safesearch_offers_exactly_the_documented_levels():
    from src.settings import DEFAULT_SETTINGS
    assert DEFAULT_SETTINGS["search_safesearch"] == "strict"
    card = INDEX.split('id="set-searchSafesearch"', 1)[1].split("</select>", 1)[0]
    for level in ("strict", "moderate", "off"):
        assert f'value="{level}"' in card


def test_safesearch_says_which_providers_it_reaches():
    """Seventeen lines of documentation existed and none of it reached anyone.
    The two exceptions matter most: Tavily has no such knob, and a custom
    backend keeps its own behaviour."""
    text = re.sub(r"\s+", " ", INDEX.split('id="set-searchSafesearch"', 1)[1][:1400])
    assert "Tavily" in text
    assert "custom backend" in text


def test_the_research_timeouts_are_clamped_like_their_sibling():
    """15..3600, the same window as the extraction timeout beside them."""
    for var in ("pt", "qt"):
        assert f"{var} >= 15 && {var} <= 3600" in JS


def test_the_document_style_is_separate_from_the_email_one():
    """The email card says "keep this email-specific", which is why a second
    key exists. A control that wrote the email key would defeat the point."""
    body = _fn("initDocStyle")
    assert "document_writing_style" in body
    assert "email_writing_style" not in body
    text = re.sub(r"\s+", " ", INDEX.split('id="set-doc-style"', 1)[0][-900:])
    assert "Separate from the email style" in text


def test_the_task_model_pair_falls_back_rather_than_forcing_a_choice():
    """Empty means "use the default chat model", which is the shipped state and
    has to stay selectable — a required picker here would change behaviour for
    everyone who never wanted a separate task model."""
    body = _fn("initTaskModel")
    assert "task_endpoint_id: epSel.value" in body
    assert "task_model: modelSel.value" in body
    card = INDEX.split('id="set-taskEndpoint"', 1)[1][:400]
    assert 'value=""' in card, "the empty option must exist"


# ── the two that deliberately still have none ──

def test_the_teacher_tier_stays_without_a_control():
    """Its card is hidden by a decision recorded in `index.html`, not by an
    oversight. Adding a switch for one field of a parked feature would be
    re-opening that decision sideways."""
    assert "teacher_tier2_enabled" not in INDEX
    assert "teacher_tier2_enabled" not in JS
    text = re.sub(r"\s+", " ", INDEX)
    assert "Teacher Model settings card hidden" in text, \
        "the reason it has no control must stay written down"


def test_every_other_named_setting_now_has_one():
    """The row lists twelve. This asserts the arithmetic so a future reader can
    see at a glance what is left, rather than re-deriving it."""
    named = {
        "agent_email_confirm",            # B42
        "agent_input_token_budget", "agent_input_token_hard_max",
        "agent_stream_timeout_seconds",   # H08 — resolution layer, no panel
        "document_writing_style",
        "research_planning_timeout_seconds", "research_query_timeout_seconds",
        "search_safesearch",
        "task_concurrency_cap",           # H06 — resolution layer, no panel
        "task_endpoint_id", "task_model",
        "teacher_tier2_enabled",          # parked card, deliberately
    }
    assert len(named) == 12
    without = {k for k in named if k not in INDEX and k not in JS}
    assert without == {
        "agent_stream_timeout_seconds",
        "task_concurrency_cap",
        "teacher_tier2_enabled",
    }, f"unexpected set still without a control: {sorted(without)}"
