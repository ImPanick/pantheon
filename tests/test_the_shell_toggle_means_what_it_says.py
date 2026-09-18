# SPDX-License-Identifier: AGPL-3.0-or-later
"""P7-01 (backend half) — the promotion that turned the shell back on.

Two sites in `chat_routes.chat_stream` promoted a chat turn to agent mode for a
shell or workspace intent and then wrote `allow_bash = "true"` outright. A
person who had switched the shell **off** got it back by typing a message the
classifier reads as workspace work. The toggle said off; the engine ran
commands. That is what the row means by the toggle lying.

`P4-18`'s `withheld` list already exists to say what a promotion took away, so
the refusal travels on the wire people already read instead of on a new one.

**The other half of the row is `static/js/chat.js` and is not fixed here** —
the browser sets `allow_bash=true` itself before the request leaves, so the
browser path is unchanged until that lands. This file covers the engine.
"""

import ast
from pathlib import Path

import pytest

from routes.chat_helpers import escalation_grants_shell, escalation_withholds

_CHAT_ROUTES = Path(__file__).resolve().parent.parent / "routes" / "chat_routes.py"


# ── the rule, called rather than read ───────────────────────────────────────


@pytest.mark.parametrize("allow_bash, granted, why", [
    (None, True, "no preference sent — granting is what already happened"),
    ("true", True, "already on"),
    ("TRUE", True, "the gate that enforces this is case-insensitive too"),
    ("false", False, "an explicit no"),
    ("0", False, "an explicit no in another spelling"),
    ("", False, "an explicit no; empty is not absent"),
    ("1", False,
     "`B97`: widening this field's spellings turns denied into granted"),
])
def test_a_promotion_may_grant_the_shell_but_never_overrule_a_no(
    allow_bash, granted, why
):
    assert escalation_grants_shell(allow_bash) is granted, why


def test_a_workspace_promotion_that_was_refused_the_shell_says_so():
    # The same list that already reports what a light promotion withheld, so
    # the fix cannot be a capability quietly disappearing.
    assert escalation_withholds(
        promoted=True, workspace_intent=True, allow_browser=False,
        browser_tools={"browser_click"}, shell_granted=False,
    ) == ["bash", "host_shell"]


def test_the_granted_case_is_byte_for_byte_what_it_was():
    # `Law 1`. Every pre-existing caller passes no `shell_granted` and must get
    # the answer it got before.
    for kwargs in (
        dict(promoted=True, workspace_intent=True, allow_browser=False),
        dict(promoted=True, workspace_intent=False, allow_browser=False),
        dict(promoted=True, workspace_intent=False, allow_browser=True),
        dict(promoted=False, workspace_intent=False, allow_browser=False),
    ):
        assert escalation_withholds(browser_tools={"browser_click"}, **kwargs) == \
            escalation_withholds(
                browser_tools={"browser_click"}, shell_granted=True, **kwargs
            )


def test_host_shell_travels_with_bash():
    # `P17-11` made them one switch, and the host one is the consequential one.
    withheld = escalation_withholds(
        promoted=True, workspace_intent=True, allow_browser=True,
        browser_tools=set(), shell_granted=False,
    )
    assert "host_shell" in withheld


# ── the route, scoped before it is asserted on (Law 20) ─────────────────────


def _chat_stream_node():
    source = _CHAT_ROUTES.read_text(encoding="utf-8")
    tree = ast.parse(source)
    for node in ast.walk(tree):
        if isinstance(node, ast.AsyncFunctionDef) and node.name == "chat_stream":
            return source, node
    raise AssertionError("chat_stream not found")


def _shell_grants_by_guard():
    """Every `allow_bash = "true"` inside `chat_stream`, keyed by its guard.

    Scoped to the enclosing `if` rather than grepped, because the string
    `allow_bash = "true"` appears in this file's own prose about the defect —
    which is exactly the confusion `Law 20` is about.
    """
    source, node = _chat_stream_node()
    found = []
    for branch in ast.walk(node):
        if not isinstance(branch, ast.If):
            continue
        for child in ast.walk(branch):
            if not isinstance(child, ast.Assign):
                continue
            if not any(
                isinstance(t, ast.Name) and t.id == "allow_bash"
                for t in child.targets
            ):
                continue
            value = ast.get_source_segment(source, child.value)
            if value not in ('"true"', "'true'"):
                continue
            found.append((ast.get_source_segment(source, branch.test), child.lineno))
    return found


def test_no_intent_classifier_grants_the_shell_unguarded():
    grants = _shell_grants_by_guard()
    # Every site is reachable only through a guard naming the decision, so a
    # seventh promotion site cannot grant the shell by writing one line.
    innermost = {}
    for test_src, lineno in grants:
        innermost[lineno] = test_src
    guards = set(innermost.values())
    assert guards, "no allow_bash grant found — has chat_stream been renamed?"
    for guard in guards:
        assert (
            "_escalation_shell_granted" in guard
            or "pending_tool_approval" in guard
        ), f"an allow_bash grant is guarded only by {guard!r}"


def test_the_approval_replay_keeps_its_own_grant():
    """A sealed `bash` action a **person** approved is not the model promoting
    itself, and `Law 1` says it keeps working."""
    guards = {guard for guard, _ in _shell_grants_by_guard()}
    assert any("pending_tool_approval" in guard for guard in guards)


def test_the_route_reports_the_refusal_it_enforces():
    source, _ = _chat_stream_node()
    assert "shell_granted=_escalation_shell_granted," in source
    assert "disabled_tools.update(_escalation_withheld)" in source
