# SPDX-License-Identifier: AGPL-3.0-or-later
"""`B807` and `B891` — the task code's comments cite names, not line numbers,
and state no caller counts.

**`B807`, measured:** `TaskCreate.crew_member_id`'s comment in
`routes/task/task_routes.py` said its claim was "verified against the source,
not assumed" and cited `src/task_scheduler.py:1625-1636`, `:1685-1686`,
`:1719-1727` and `:1817-1824` — a stale-run branch, a comment, the foreground
gate and a notify comment, none of them what the sentence named. `P8-32` had
already found the fifth one in that block stale by three weeks. The claim was
true; the addresses rotted (`Law 6`). Four more such citations were in the task
form, the workflow drawing and the Tasks window (`src/task_scheduler.py:112`,
`:130`, `task_routes.py:927-929`, `markdown.js:94`, and three `:NNNN`s for an
escaper that no longer exists).

**`B891`, measured:** `static/js/tasks/workflowDiagram.js` said "all four
callers of `renderMermaid`" and "a fourth caller" while the tree had seven call
sites in six files; `tasks.js` said "four call sites and two tests".

Every one is a name now. This holds the task code to it: a whole-file absence
check, `Law 20`'s one permitted use of one — a line-number citation, or a
caller count, anywhere in these files is the defect. (The repo's other
citations are another area's; filed as a new row, not fixed here.)
"""
from __future__ import annotations

import re
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]

TASK_FILES = sorted({
    *(ROOT / "routes" / "task").glob("*.py"),
    ROOT / "src" / "task_scheduler.py",
    ROOT / "static" / "js" / "tasks.js",
    *(ROOT / "static" / "js" / "tasks").glob("*.js"),
})

# `file.py:123`, `markdown.js:94`, and the bare `` `:1685-1686` `` form a
# citation block continues with.
LINE_CITATION = re.compile(r"\b[\w./-]+\.(?:py|js|mjs|css|html):\d+|`:\d+(?:-\d+)?`")
CALLER_COUNT = re.compile(
    r"\b(?:one|two|three|four|five|six|seven|eight|nine|ten|~?\d+) (?:callers|call sites)\b")


def test_the_task_files_are_the_ones_meant():
    names = {p.relative_to(ROOT).as_posix() for p in TASK_FILES}
    assert {"routes/task/task_routes.py", "src/task_scheduler.py", "static/js/tasks.js",
            "static/js/tasks/taskFields.js", "static/js/tasks/workflowDiagram.js"} <= names


def test_no_comment_in_the_task_code_cites_a_line_number():
    found = [f"{p.relative_to(ROOT)}:{n}: {m.group(0)}"
             for p in TASK_FILES
             for n, line in enumerate(p.read_text(encoding="utf-8").splitlines(), 1)
             for m in LINE_CITATION.finditer(line)]
    assert found == [], "cite the function's name, not its line:\n" + "\n".join(found)


def test_no_comment_in_the_task_code_states_a_caller_count():
    found = [f"{p.relative_to(ROOT)}:{n}: {m.group(0)}"
             for p in TASK_FILES
             for n, line in enumerate(p.read_text(encoding="utf-8").splitlines(), 1)
             for m in CALLER_COUNT.finditer(line)]
    assert found == [], "a count in a comment is a measurement nobody re-takes:\n" + "\n".join(found)
