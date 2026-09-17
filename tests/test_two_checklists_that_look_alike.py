# SPDX-License-Identifier: AGPL-3.0-or-later
r"""`B11`/`B12` — one row system, two lists, and which is which.

**The rows are identical on purpose and stay identical.** `tests/harness/
checklist_surfaces.js` runs the two real renderers — `planWindow.js`'s
`renderStep` and `chatRenderer.js`'s `buildTodoCard` — over the same three steps
and compares what each emits. Two of the three states come out structurally
equal, class-for-class::

    <li class="plan-step task-item task-done">
      <span class="task-check" role="img" aria-label="done"></span>
      <span class="plan-step-main"><span class="task-text">…</span></span></li>

That is `Law 14` working. A plan step and a todo item *are* the same object, the
sheet joins them by selector (`style.css`, `P6-17`), and forking them would be
the defect, not the fix.

**The defect is one level up, and the row's own framing understates it.** The
two cards mean opposite things — an approved plan is a commitment the user
signed off and the agent is executing; the todo card is the model's scratch
list, which it replaces whenever it likes — and before this change the heads
read::

    Active plan · 1 of 2 done · Executing
    Task list · 1 of 2 done

Measured, not read: the todo card's `aria-label` already said **"Agent task
list"** while its visible title said only **"Task list"**. A screen reader was
being told which list it was looking at and the eye was not, on the surface
whose whole job is to be glanceable. That is `Law 15` failing in the direction
nobody audits, and it is why the fix is words rather than a badge or a tint —
a new symbol is a thing a stranger has to be taught.

**And the four duplications `B12` names had rotted.** Every line number in that
row is stale, one of the four was already closed by a later pass, and the play
triangle is not "twice" — re-measured, the product had seven hand-written play
polygons in two geometries. What this file pins is what survived the
re-measurement.
"""
from __future__ import annotations

import json
import re
import shutil
import subprocess
from pathlib import Path

import pytest
from tests.helpers.source_text import blank, blank_text  # B290

ROOT = Path(__file__).resolve().parent.parent
HARNESS = ROOT / "tests" / "harness" / "checklist_surfaces.js"
CHECKLIST = ROOT / "static" / "js" / "checklist.js"
INDEX = ROOT / "static" / "index.html"
STYLE = ROOT / "static" / "style.css"

pytestmark = pytest.mark.skipif(not shutil.which("node"), reason="node binary not on PATH")


def run(mode: str):
    proc = subprocess.run(["node", str(HARNESS), mode],
                          capture_output=True, text=True, timeout=60)
    assert proc.returncode == 0, proc.stderr
    return json.loads(proc.stdout)


# ---------------------------------------------------------------------------
# The premise: the rows really are one object
# ---------------------------------------------------------------------------


def test_the_two_renderers_emit_the_same_row():
    """Both files build the same `<li>`, so the sheet paints them the same.

    This is the half of the row that must NOT change. If a later pass gives the
    todo card its own row class to tell the two apart, this fails and says so —
    which is the point: the distinction belongs on the card, never on the row.
    """
    rows = run("rows")
    assert [r["state"] for r in rows] == ["done", "in progress", "pending"]
    for row in rows:
        assert row["sameClasses"], (
            f"the {row['state']} row's class lists diverged — "
            f"plan={row['planClasses']} todo={row['todoClasses']}"
        )
    done, in_progress, pending = rows
    assert done["sameShape"] and pending["sameShape"], (
        "a done step and a done todo are one object and must stay one object"
    )
    # The one real row-level difference, and it is the todo card being *more*
    # informative: its active row carries a chip that says "in progress" in
    # words, while the plan window's active step is signalled only by the
    # `plan-step-now` tint. Recorded here because it is the opposite of what
    # the row assumes, and because deleting that chip would pass every other
    # assertion in this file.
    assert not in_progress["sameShape"]
    assert "in progress" in in_progress["todo"]
    assert "plan-step-now" in in_progress["plan"]


# ---------------------------------------------------------------------------
# The fix: a person can say which list is which
# ---------------------------------------------------------------------------


def test_each_card_says_in_words_what_kind_of_list_it_is():
    """`B11`'s `Verify`: a stranger can say which is the approved plan.

    Asserted against the rendered text of both heads, not against a selector:
    a `.plan-window-blurb` that exists and is empty would satisfy a grep and
    tell a person nothing.
    """
    heads = run("heads")
    plan, todo = heads["plan"], heads["todo"]

    assert plan["blurb"], "the plan window's head says nothing about what it is"
    assert todo["blurb"], "the todo card's head says nothing about what it is"
    assert plan["blurb"] != todo["blurb"]

    # The words that carry the distinction. "approved" is the plan's claim and
    # nothing else on screen may make it; "agent"/"own" is the todo card's.
    assert "approved" in plan["blurb"].lower()
    assert "agent" in todo["blurb"].lower() or "own" in todo["blurb"].lower()
    assert "approved" not in todo["blurb"].lower(), (
        "the scratch list must not claim to be approved — that is the whole row"
    )


def test_the_eye_is_told_what_the_screen_reader_is_told():
    """The defect that was actually measurable: `aria-label` said "Agent task
    list", the visible title said "Task list"."""
    heads = run("heads")
    assert heads["todo"]["aria"] == "Agent task list"
    assert "Agent task list" in heads["todo"]["head"], (
        "the visible title is still narrower than the accessible name"
    )


def test_the_two_titles_are_not_the_same_words():
    """Two surfaces that look alike may not also be called alike."""
    heads = run("heads")
    assert "Active plan" in heads["plan"]["static"]
    assert "Active plan" not in heads["todo"]["head"]


def test_both_sentences_live_in_one_table():
    """They were written as a contrasting pair; keeping them together is what
    stops a later edit from making them agree again (`Law 7`)."""
    src = CHECKLIST.read_text(encoding="utf-8")
    plan_at = src.index("plan:")
    todo_at = src.index("agentTodo:")
    assert plan_at < todo_at
    # Both blurbs inside one object literal, not two modules apart.
    between = src[plan_at:todo_at]
    assert "blurb:" in between and "blurb:" in src[todo_at:]


def test_the_plan_windows_static_title_is_the_one_the_module_writes():
    """`index.html` carries the title so the head is not blank before JS runs.
    That copy is a paint, not a second source — held equal here, because a
    pre-JS paint that disagrees with the module is a flicker into a different
    word."""
    html = INDEX.read_text(encoding="utf-8")
    painted = re.search(r'id="plan-window-title"[^>]*>([^<]*)<', html)
    assert painted, "the plan window's title span lost its id"
    heads = run("heads")
    assert heads["plan"]["title"], "init() no longer writes the title from the table"
    assert painted.group(1).strip() == heads["plan"]["title"], (
        "the pre-JS paint and the value the module writes have drifted — a cold "
        "load would flicker from one word to another"
    )


# ---------------------------------------------------------------------------
# `B12`'s four duplications, re-counted
# ---------------------------------------------------------------------------


def _js(name: str) -> str:
    return (ROOT / "static" / "js" / name).read_text(encoding="utf-8")


def _code(text: str) -> str:
    """The file with its prose blanked.

    `Law 20`'s third case, hit for real while writing this: `checklist.js`
    *documents* the geometry it replaced, so a file-wide search for the old
    polygon found it in the sentence explaining why it is gone. A comment is
    not a declaration and must not be counted as one.
    """
    return blank_text(text)


def test_the_progress_sentence_has_one_implementation():
    """`N of M done` was a template literal in one file and a `+` chain in the
    other. Proved by output, not by grep: both heads print it and the function
    that makes it is called by both."""
    heads = run("heads")
    assert heads["plan"]["count"] == "1 of 2 done"
    assert "1 of 2 done" in heads["todo"]["head"]
    assert "checklistProgress" in _js("planWindow.js")
    assert "checklistProgress" in _js("chatRenderer.js")
    for name in ("planWindow.js", "chatRenderer.js"):
        src = _code(_js(name))
        assert "' of '" not in src and "of ${total} done" not in src, (
            f"{name} still spells the progress sentence itself"
        )


def test_the_step_chip_class_has_one_implementation():
    """The chip is built as DOM in one renderer and as a string in the other,
    and that stays — what they must not each decide is the class."""
    rows = run("rows")
    chip = [r for r in rows if r["state"] == "in progress"][0]["todo"]
    assert 'class="plan-step-chip todo-now-chip"' in chip
    for name in ("planWindow.js", "chatRenderer.js"):
        src = _code(_js(name))
        assert "stepChipClass" in src, f"{name} does not use the shared class"
        # The bare name, not a quoted spelling. A mutation that re-inlined the
        # class as `class="plan-step-chip todo-now-chip"` — one interpolation
        # short of the real thing, and inside a differently-quoted string —
        # walked straight through an assertion that looked for `'…'` and `"…"`.
        # Absence from a whole scope is the one thing a substring may be asked
        # (`Law 20`), and this is that: the name lives in `checklist.js`.
        assert "plan-step-chip" not in src, (
            f"{name} still writes the chip's base class itself"
        )


def test_the_product_draws_one_play_triangle():
    """Re-measured twice. `B12` said the polygon was hand-written twice; it was
    seven times in two geometries, and `B83` re-counted the whole client at
    NINETEEN in five. This test pinned the five that survived as the evidence
    for that row, with the note that the count moves when the row is done rather
    than silently. `B83` is done: every one of them is gone.

    The census itself lives in `tests/test_one_icon_table.py`, which classifies a
    polygon by its shape rather than against a list of spellings — that is how
    the fifth geometry, `tasks.js`'s `active` badge, was found. What stays here
    is the claim this file is about: the two builders of the one
    `.plan-inline-execute` control still draw the same glyph."""
    js_dir = ROOT / "static" / "js"
    literals = []
    for path in js_dir.rglob("*.js"):
        if "/lib/" in str(path):
            continue
        text = _code(path.read_text(encoding="utf-8", errors="ignore"))
        for spelling in ("7 4 20 12 7 20 7 4", "6 4 20 12 6 20 6 4",
                         "5 3 19 12 5 21 5 3", "6 3 20 12 6 21 6 3",
                         "7 4 19 12 7 20 7 4"):
            literals.extend([f"{path.name}:{spelling}"] * text.count(spelling))
    assert literals == [], (
        f"a hand-written play triangle is back in {sorted(literals)} — "
        "one control, one glyph"
    )
    # The glyph's home moved to the shared icon table; `checklist.js` re-exports
    # it so the docked window keeps importing it from where `B12` put it.
    assert "export { PLAY_POINTS } from './icons.js';" in _js("checklist.js")
    assert "PLAY_POINTS" in _js("planWindow.js")
    # `chat.js` builds its markup as a string, so it takes the wrapped icon
    # rather than the points — the same table, one call further in.
    assert "playIcon(" in _js("chat.js")


def test_the_two_card_heads_are_styled_as_one_pair_where_they_agree():
    """`B12` calls the head chrome a duplication at "2 of 6 declarations
    shared". Re-measured: the two declarations still shared are `display:flex`
    and `align-items:center` — the generic flex-row idiom, not duplication —
    and the parts that genuinely were the same, the icon and the title, were
    already joined by a later pass. What this pins is the new identity line,
    which is joined from the start: the sentences differ, their treatment must
    not, or the difference reads as decoration rather than as content."""
    css = STYLE.read_text(encoding="utf-8")
    joined = re.search(
        r"\.plan-window-blurb,\s*\n\.todo-card-note\s*\{([^}]*)\}", css)
    assert joined, "the identity line is styled twice, or not at all"
    body = joined.group(1)
    assert "font-size" in body and "color" in body
    assert "--accent" not in body, (
        "this line sits under the title and must never be louder than it"
    )
