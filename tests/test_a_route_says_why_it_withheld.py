# SPDX-License-Identifier: AGPL-3.0-or-later
"""`B1399` — the chat route names a reason for every tool it withholds.

`D-2026-10-17-02` §2. `WITHHELD_BY_CALLER` is liftable now, and the order of
the two changes is the whole of the safety argument.

Before this, `routes/chat_routes.py` composed its denylist as a plain `set`
across sixteen `update()` calls and three `difference_update()` calls, and
`stream_agent_loop` tagged the entire result `WITHHELD_BY_CALLER`. One bucket
held two different facts: a neutral starting set, *and* every deliberate
restriction the route makes — incognito's `manage_memory`, `search_chats` and
`manage_skills`; the email reader's `send_email` and `create_document`; and
chat-mode compare's **`manage_tasks`**, which is one of the exact three names
both `TurnToolAccess.lift()` call sites pass. So `caller` could not be lifted
without letting `#6020`'s notes clamp re-enable `manage_tasks` in a mode whose
own comment reads *"disable ALL agent tools"* — which is what happened when the
first ruling was implemented, and `test_the_caller_s_own_set_is_recorded_as_the_caller_s`
caught it.

**The risk has moved and this file is where it lives.** With `caller` liftable,
a deliberate set the route forgets to attribute becomes liftable — a privacy
control defeated by an omission rather than by a decision. So the rule asserted
here is not *the clamp works* (`tests/test_pr6020_rebase_regressions.py` holds
that, and its two `xfail`s are gone). It is that **the route composes its
denylist through nothing but `RouteWithholds`**, derived from the source by
walking it, so a seventeenth restriction added later fails here rather than
leaking. `RouteWithholds.deny` takes `because` positionally and has no default,
so there is nothing to fall through to.
"""

from __future__ import annotations

import ast
from pathlib import Path

import pytest

from src.tool_policy import (
    LIFTABLE_REASONS,
    WITHHELD_BY_CALLER,
    WITHHELD_BY_FEATURE,
    WITHHELD_BY_PLAN_MODE,
    WITHHELD_BY_POLICY,
    WITHHELD_BY_PRIVILEGE,
    WITHHELD_REASONS,
    RouteWithholds,
    TurnToolAccess,
)

ROOT = Path(__file__).resolve().parent.parent
ROUTE = ROOT / "routes" / "chat_routes.py"

#: The name the route composes its denylist under.
VAR = "_withholds"


def _route_function() -> ast.AST:
    """The function that composes the denylist, found by what it does.

    The **innermost** one: `ast.walk` descends through nested definitions, so an
    outer function that merely contains the handler matches too — the first
    draft of this helper found two and asserted there was one.
    """
    tree = ast.parse(ROUTE.read_text(encoding="utf-8"))
    FUNC = (ast.FunctionDef, ast.AsyncFunctionDef)

    def builds(node) -> bool:
        """Does this function's **own** body construct a `RouteWithholds`?"""
        for child in ast.walk(node):
            if isinstance(child, FUNC) and child is not node:
                continue      # a nested definition is its own scope
            if (isinstance(child, ast.Call) and isinstance(child.func, ast.Name)
                    and child.func.id == "RouteWithholds"):
                # Only when it is not inside a nested definition.
                if not any(child in set(ast.walk(inner))
                           for inner in ast.walk(node)
                           if isinstance(inner, FUNC) and inner is not node):
                    return True
        return False

    hits = [node for node in ast.walk(tree) if isinstance(node, FUNC) and builds(node)]
    assert len(hits) == 1, (
        f"{len(hits)} functions construct a RouteWithholds in their own body "
        f"({[h.name for h in hits]}); this rule assumes one place composes the "
        "chat route's denylist")
    return hits[0]


# ── the rule: nothing composes the denylist but RouteWithholds ─────────────


def test_the_route_withholds_only_through_the_type_that_demands_a_reason():
    """The exhaustiveness rule, read off the source.

    A bare `disabled_tools.update(...)`, `.add(...)` or `|=` anywhere in this
    function would land names in `caller` with nobody having decided anything —
    and `caller` is liftable now.
    """
    func = _route_function()
    offenders = []
    for node in ast.walk(func):
        if not isinstance(node, ast.Call) or not isinstance(node.func, ast.Attribute):
            continue
        target = node.func.value
        if not isinstance(target, ast.Name) or target.id != "disabled_tools":
            continue
        if node.func.attr in ("update", "add", "difference_update", "discard",
                              "remove", "withhold"):
            offenders.append(f"disabled_tools.{node.func.attr}() at line {node.lineno}")
    for node in ast.walk(func):
        if (isinstance(node, ast.AugAssign)
                and isinstance(node.target, ast.Name)
                and node.target.id == "disabled_tools"):
            offenders.append(f"disabled_tools {type(node.op).__name__} at line {node.lineno}")
    assert not offenders, (
        "the chat route adds to its denylist without naming a reason:\n  "
        + "\n  ".join(offenders)
        + f"\n\nUse `{VAR}.deny(names, WITHHELD_BY_...)`. `caller` is liftable "
          "(D-2026-10-17-02 §2), so an unattributed name is a restriction a "
          "later clamp can undo.")


def test_every_reason_the_route_names_is_in_the_vocabulary():
    """A typo'd reason would raise at runtime on the turn that hit that branch,
    which is the wrong place to find out. Read statically instead."""
    func = _route_function()
    used = set()
    for node in ast.walk(func):
        if (isinstance(node, ast.Call) and isinstance(node.func, ast.Attribute)
                and node.func.attr == "deny"
                and isinstance(node.func.value, ast.Name)
                and node.func.value.id == VAR):
            assert len(node.args) == 2, (
                f"`deny` at line {node.lineno} does not pass a reason positionally")
            reason = node.args[1]
            assert isinstance(reason, ast.Name), (
                f"the reason at line {node.lineno} is not one of the module's "
                "constants; a literal would not be checked against the vocabulary")
            used.add(reason.id)
    assert used, "the route names no reasons at all; the walk is wrong"
    allowed = {f"WITHHELD_BY_{n.upper()}" for n in
               ("policy", "privilege", "feature", "plan_mode", "caller",
                "workstation", "step_tools", "turn")}
    assert used <= allowed, f"unknown reason constant(s): {sorted(used - allowed)}"
    # And the one that must NOT appear: attributing a deliberate set to the
    # bucket that is liftable is the defect this row is about.
    assert "WITHHELD_BY_CALLER" not in used, (
        "the route names `caller` explicitly — that bucket is for names nobody "
        "decided anything about, and it is liftable")


def test_the_deliberate_restrictions_are_each_attributed():
    """Named, because *the route uses the type* does not say *the privacy sets
    are the ones it attributed*. Each of these is a real restriction with a real
    reason, and the reason is read off the call that makes it."""
    func = _route_function()
    by_name: dict = {}
    for node in ast.walk(func):
        if not (isinstance(node, ast.Call) and isinstance(node.func, ast.Attribute)
                and node.func.attr == "deny"
                and isinstance(node.func.value, ast.Name)
                and node.func.value.id == VAR):
            continue
        if len(node.args) != 2 or not isinstance(node.args[1], ast.Name):
            continue
        reason = node.args[1].id
        for literal in ast.walk(node.args[0]):
            if isinstance(literal, ast.Constant) and isinstance(literal.value, str):
                by_name.setdefault(literal.value, set()).add(reason)

    expected = {
        # incognito: identity-linked stores
        "manage_memory": "WITHHELD_BY_POLICY",
        "search_chats": "WITHHELD_BY_POLICY",
        "manage_skills": "WITHHELD_BY_POLICY",
        # the open email reader: no compose path but the reviewable one
        "send_email": "WITHHELD_BY_POLICY",
        "reply_to_email": "WITHHELD_BY_POLICY",
        "mcp__email__send_email": "WITHHELD_BY_POLICY",
        # chat-mode compare — the collision that made this row
        "manage_tasks": "WITHHELD_BY_POLICY",
        # the shell toggle, which governs three tools at once (`P17-11`)
        "host_shell": "WITHHELD_BY_POLICY",
        # a privilege switch
        "generate_image": "WITHHELD_BY_PRIVILEGE",
    }
    for name, reason in expected.items():
        assert name in by_name, f"{name} is no longer withheld by name in the route"
        assert reason in by_name[name], (
            f"{name} is withheld for {sorted(by_name[name])} and this rule "
            f"expects {reason} — if the route's reasoning changed, change it here "
            f"too, but a deliberate restriction must never be `caller`")


# ── the seam: the loop keeps what the route decided ────────────────────────


def test_the_loop_keeps_the_reasons_the_route_attributed(monkeypatch, tmp_path):
    """Driven through the real `stream_agent_loop`, because this is the one
    place the whole scheme can be undone in a single line.

    `stream_agent_loop` used to wrap its `disabled_tools` kwarg unconditionally:
    `TurnToolAccess(disabled_tools or [], because=WITHHELD_BY_CALLER)`. With the
    route attributing its sets, that line flattens `policy`, `privilege`,
    `feature` and `plan_mode` back into one liftable bucket — the exact defect
    `B1399` names, reintroduced by a wrapper that looks harmless.

    **A mutation run is why this case exists.** Removing the `isinstance` guard
    left every other test in this file and in
    `tests/test_pr6020_rebase_regressions.py` green, because flattening to
    `caller` makes the notes clamp succeed *more* easily. Nothing noticed until
    the seam itself was driven.
    """
    import test_one_answer_to_what_a_turn_can_call as harness

    attributed = (RouteWithholds()
                  .deny({"manage_memory", "search_chats"}, WITHHELD_BY_POLICY)
                  .deny({"generate_image"}, WITHHELD_BY_PRIVILEGE)
                  .finish({"manage_memory", "search_chats", "generate_image",
                           "manage_notes"}))
    assert attributed.reasons_for("manage_memory") == frozenset({WITHHELD_BY_POLICY})

    turn = harness.run_turn(monkeypatch, tmp_path, owner=harness.ADMIN,
                            relevant_tools=harness.WIDE,
                            disabled_tools=attributed)
    assert turn.loop_access, "the loop never reached `_build_base_prompt`"
    live = turn.loop_access[0]
    assert isinstance(live, TurnToolAccess)
    for name, reason in (("manage_memory", WITHHELD_BY_POLICY),
                         ("search_chats", WITHHELD_BY_POLICY),
                         ("generate_image", WITHHELD_BY_PRIVILEGE)):
        assert reason in live.reasons_for(name), (
            f"the loop lost why {name} was withheld — it holds "
            f"{sorted(live.reasons_for(name))}, and a clamp can lift `caller`")
    # And the consequence, stated as the thing a person would notice: a clamp
    # asking for these three gets none of them.
    assert live.lift({"manage_memory", "search_chats", "generate_image"}) == set()


# ── the type itself ────────────────────────────────────────────────────────


def test_a_reason_is_required_and_checked():
    with pytest.raises(TypeError):
        RouteWithholds().deny({"bash"})            # no reason at all
    with pytest.raises(ValueError):
        RouteWithholds().deny({"bash"}, "made_up")  # not in the vocabulary


def test_composition_churn_is_not_a_clamp():
    """The route denies the web tools and takes them back on the branch where
    the chat's own setting enabled them — three times. `allow` has to do that
    even though the deny was `policy`, because nothing in one assembly is
    *later* than anything else; `lift`'s rule is about a clamp reaching a
    decision already made."""
    w = RouteWithholds()
    w.deny({"web_search", "web_fetch"}, WITHHELD_BY_POLICY)
    assert w.names() == {"web_search", "web_fetch"}
    w.allow({"web_search", "web_fetch"})
    assert w.names() == set()


def test_finish_attributes_the_policy_layers_own_additions():
    """`build_effective_tool_policy` can disable every tool in the product on a
    guide-only turn. Those are the policy's, not the caller's — if they landed
    in `caller` a clamp could lift them."""
    w = RouteWithholds().deny({"bash"}, WITHHELD_BY_PRIVILEGE)
    access = w.finish({"bash", "web_search", "manage_notes"})
    assert isinstance(access, TurnToolAccess)
    assert access.reasons_for("bash") == frozenset({WITHHELD_BY_PRIVILEGE})
    assert access.reasons_for("web_search") == frozenset({WITHHELD_BY_POLICY})
    assert access.reasons_for("manage_notes") == frozenset({WITHHELD_BY_POLICY})


def test_a_privilege_survives_a_clamp_and_a_neutral_name_does_not():
    """The property the whole row is about, stated on the type."""
    assert WITHHELD_BY_CALLER in LIFTABLE_REASONS
    for unliftable in (WITHHELD_BY_POLICY, WITHHELD_BY_PRIVILEGE,
                       WITHHELD_BY_FEATURE, WITHHELD_BY_PLAN_MODE):
        assert unliftable not in LIFTABLE_REASONS
        assert unliftable in WITHHELD_REASONS

    access = TurnToolAccess()
    access.withhold({"manage_notes", "manage_calendar"}, because=WITHHELD_BY_CALLER)
    access.withhold({"manage_tasks"}, because=WITHHELD_BY_POLICY)
    lifted = access.lift({"manage_notes", "manage_calendar", "manage_tasks"})
    assert lifted == {"manage_notes", "manage_calendar"}
    assert access == {"manage_tasks"}, (
        "a deliberate restriction was lifted by a per-turn clamp")


def test_a_name_withheld_twice_keeps_the_stricter_reason():
    """The route withholds `manage_memory` for incognito *and* for the
    `can_manage_memory` privilege. Both reasons have to survive, or whichever
    was recorded second decides whether a clamp can lift it."""
    w = RouteWithholds()
    w.deny({"manage_memory"}, WITHHELD_BY_POLICY)
    w.deny({"manage_memory"}, WITHHELD_BY_PRIVILEGE)
    access = w.finish({"manage_memory"})
    assert access.reasons_for("manage_memory") == frozenset(
        {WITHHELD_BY_POLICY, WITHHELD_BY_PRIVILEGE})
    assert access.lift({"manage_memory"}) == set()
