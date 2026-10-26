# SPDX-License-Identifier: AGPL-3.0-or-later
"""The plan an agent turn is executing, as `update_plan` last accepted it. `B1415`.

A leaf: the loop binds it, `update_plan` reads and writes it.
"""
from __future__ import annotations

import re
from contextvars import ContextVar

# ── `B1415` · the plan the turn holds ───────────────────────────────────────
#
# Measured from the owner's transcript: an eleven-step plan was rewritten by a
# model whose output ran out mid-line (the plan text ends `  - Card`), and
# `update_plan` took it as a full replacement — the window went from "0 of 11
# done" to "Plan updated (4/6 steps complete)" with no event and no warning.
# "Pass the COMPLETE checklist every time" makes a truncated write look, to
# the tool alone, exactly like a deliberate shorter plan; the loop knows the
# plan the turn started with, so it hands the tool a holder for it, and a
# write that would delete steps nobody named is answered in-band so the model
# resends. A mutable holder rather than the plan itself, because each tool
# call runs in a copy of the loop's context (`bind_run_limits`' shape): the
# accepted plan has to be seen by the next call.
class ActivePlan:
    """The plan this turn is executing, as last accepted."""

    def __init__(self, plan=None):
        self.plan = str(plan or "").strip() or None


_active_plan: ContextVar = ContextVar("pantheon_active_plan", default=None)


def active_plan():
    """The holder bound for this tool call, or `None` outside a plan turn."""
    return _active_plan.get()


def bind_active_plan(holder) -> None:
    """Bind the turn's plan holder for the tool call about to run."""
    _active_plan.set(holder)


_STEP = re.compile(r"^\s*[-*+]\s*\[( |x|X)\]", re.M)


def plan_step_counts(plan) -> tuple:
    """`(steps, done)` in a markdown checklist."""
    marks = _STEP.findall(str(plan or ""))
    return len(marks), sum(1 for mark in marks if mark in "xX")
