#!/usr/bin/env python3
# SPDX-License-Identifier: AGPL-3.0-or-later
"""`B111` — a seventh run status cannot be written without something failing.

`B13`/`B78`/`B84` gave the six run statuses one word table
(`static/js/runStatus.js`) and one stored vocabulary (`core/database.py`), and a
test asserts the two lists are equal. That catches a seventh value **declared**
in either language. It catches nothing about the way all six actually got here:
`src/task_scheduler.py` writes them as bare string literals at fifteen sites,
and a sixteenth site writing `"cancelled"` passed every gate in this repo and
reached the UI, where `runStatusTone` answered `null`, the Activity view fell
back to text-scanning the result for the word *error*, and the notification
client called it a failure.

So this checker asks three questions, and derives both sides of each rather than
holding a list of its own — a transcribed list is the next status missing.

  1. **The two languages agree.** `TASK_RUN_STATUSES` / `TASK_RUN_ACTIVE_STATUSES`
     in `core/database.py` against `RUN_STATUSES` / `RUN_ACTIVE_STATUSES` in
     `static/js/runStatus.js`. Both are read out of the files.

  2. **The word table is exactly as wide as the vocabulary.** Every status has a
     row in `WORDS`, every row has a word for every subject in `RUN_SUBJECTS`,
     and no row names a status that does not exist. A seventh status with no row
     does not fail anything at runtime: `runStatusLabel` falls back to printing
     the stored value at the user, which is the exact defect `B84` closed.
     `TASK_RUN_NOTIFY` is checked the same way — every status, no extras.

  3. **No code writes a status that is not in the vocabulary.** Every string
     literal assigned to, compared against, or passed as `status=` for a row the
     module has bound to `TaskRun` must be one of the six. Comments never reach
     this: it is an AST walk, not a text search (`B87`, `Law 20`).

  4. **Every raw-SQL write to `task_runs.status` is classified.** `B170`:
     question 3 reads ORM *attribute access*, so a migration issuing
     `text("UPDATE task_runs SET status = 'skipped' …")` has no `TaskRun` in it,
     no attribute to bind, and was invisible — a gate with a hole is worth less
     than its output suggests. The shape that works is
     `check-config-writes.py`'s: find the sites, decide about each one, and fail
     on a site nobody has decided about. Matching `task_runs` inside every
     string in the tree would also match the test SQL, the docs and the roadmap
     row, so the scan is narrow on purpose — only SQL text reachable from a CALL
     or an ASSIGNMENT, which is where SQL is actually executed from, and never a
     docstring or a comment.

Question 3 needs to know which locals are `TaskRun` rows, because three other
models in this tree have a `status` column with a different vocabulary
(`ScheduledTask` is active/paused/completed, `CalendarEvent` has "cancelled").
That is derived per FUNCTION: a name assigned from a query whose selected model
is `TaskRun`, a loop variable over one, and anything read off such a name
(`run = q.first()`). Per function and not per file, because the file that owns
most of these writes is one long closure.

Usage:  python3 .pantheon/check-run-statuses.py [--list]
"""
from __future__ import annotations

import argparse
import ast
import re
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
DB = ROOT / "core" / "database.py"
JS = ROOT / "static" / "js" / "runStatus.js"
# This file, spelled the way `git ls-files` spells it. Question 4 reads strings
# out of calls and assignments, and every diagnostic this module prints names
# the table and the column it is complaining about — so without this it reports
# itself, four times, and a checker that cries wolf is a checker somebody
# deletes. Derived from `__file__` so a rename cannot strand the exemption, and
# narrow to one file rather than to `.pantheon/`: nothing here opens a database,
# but a repair script under the same directory could.
SELF = str(Path(__file__).resolve().relative_to(ROOT))

MODEL = "TaskRun"
# Calls on a query that still hand back rows, so the name they are assigned to
# holds one (or a list of them).
QUERY_TERMINALS = {
    "first", "one", "one_or_none", "get", "all",
    "filter", "filter_by", "order_by", "limit", "offset", "options",
    "with_entities", "join", "distinct", "query",
}
# Calls that hand back a number or nothing. `total = db.query(TaskRun).count()`
# binds an int, and treating it as a row is how a name shared with another model
# elsewhere in the same module poisons the whole file.
SCALAR_TERMINALS = {"count", "exists", "delete", "update", "scalar", "scalar_one"}


# ---------------------------------------------------------------------------
# side A — the stored vocabulary
# ---------------------------------------------------------------------------

def _module_constants(path: Path) -> dict[str, object]:
    """Top-level `NAME = <literal>` assignments, evaluated as literals."""
    tree = ast.parse(path.read_text(encoding="utf-8"), filename=str(path))
    out: dict[str, object] = {}
    for node in tree.body:
        targets = []
        if isinstance(node, ast.Assign):
            targets = node.targets
        elif isinstance(node, ast.AnnAssign) and node.value is not None:
            targets = [node.target]
        else:
            continue
        value = node.value
        for t in targets:
            if not isinstance(t, ast.Name):
                continue
            try:
                out[t.id] = ast.literal_eval(value)
            except (ValueError, SyntaxError):
                pass
    return out


# ---------------------------------------------------------------------------
# side B — the word table
# ---------------------------------------------------------------------------

def _blank_comments(js: str) -> str:
    """`B87`. Every file in this area documents the ladder it used to own, so a
    text search finds the vocabulary in the prose explaining why it is not there
    any more. Block and line comments go before anything is read."""
    js = re.sub(r"/\*.*?\*/", "", js, flags=re.S)
    return re.sub(r"^\s*//.*$", "", js, flags=re.M)


def _js_array(js: str, name: str) -> list[str] | None:
    m = re.search(rf"\b{name}\s*=\s*\[(.*?)\]", js, flags=re.S)
    if not m:
        return None
    return re.findall(r"""['"]([^'"]*)['"]""", m.group(1))


def _js_words(js: str) -> dict[str, list[str]] | None:
    """`WORDS` as `{status: [word per subject]}`, read off the object literal."""
    m = re.search(r"\bconst\s+WORDS\s*=\s*\{(.*?)\n\};", js, flags=re.S)
    if not m:
        return None
    out: dict[str, list[str]] = {}
    for key, row in re.findall(r"""(\w+)\s*:\s*\[([^\]]*)\]""", m.group(1)):
        out[key] = re.findall(r"""['"]([^'"]*)['"]""", row)
    return out


# ---------------------------------------------------------------------------
# question 3 — what the code actually writes
# ---------------------------------------------------------------------------

def _root_name(node: ast.AST) -> str | None:
    while True:
        if isinstance(node, ast.Name):
            return node.id
        if isinstance(node, ast.Attribute):
            node = node.value
        elif isinstance(node, ast.Call):
            node = node.func
        elif isinstance(node, ast.Subscript):
            node = node.value
        else:
            return None


def _queried_model(node: ast.AST) -> str | None:
    """The model a `…query(Model)…` chain in `node` selects, if there is one."""
    for sub in ast.walk(node):
        if (isinstance(sub, ast.Call) and isinstance(sub.func, ast.Attribute)
                and sub.func.attr == "query" and sub.args
                and isinstance(sub.args[0], ast.Name)):
            return sub.args[0].id
    return None


def _outer_attr(node: ast.AST) -> str | None:
    if isinstance(node, ast.Call) and isinstance(node.func, ast.Attribute):
        return node.func.attr
    return None


def _binds_taskrun(value: ast.AST, bound: set[str]) -> bool:
    """Does this expression hand back a `TaskRun` row (or a list of them)?

    Deliberately narrow. A name is bound only when the model is unambiguous:
    `TaskRun(...)`, a query whose selected model IS `TaskRun`, or something read
    off a name already bound that way. A query naming a different model binds
    nothing even if `TaskRun` appears elsewhere in the expression, and an
    aggregate binds nothing at all — `ScheduledTask` uses `active/paused/
    completed` in the same files, so a loose rule reports those as bad run
    statuses and the checker becomes noise nobody reads.
    """
    if isinstance(value, ast.Call) and isinstance(value.func, ast.Name) \
            and value.func.id == MODEL:
        return True

    model = _queried_model(value)
    if model is not None:
        return model == MODEL and _outer_attr(value) not in SCALAR_TERMINALS

    if isinstance(value, ast.Call) and isinstance(value.func, ast.Attribute):
        if value.func.attr in QUERY_TERMINALS and _root_name(value.func.value) in bound:
            return True
        return False

    if isinstance(value, ast.Name) and value.id in bound:
        return True
    if isinstance(value, ast.Subscript) and _root_name(value.value) in bound:
        return True
    return False


def _bind_targets(target: ast.AST) -> list[str]:
    return [n.id for n in ast.walk(target) if isinstance(n, ast.Name)]


_NESTED = (ast.FunctionDef, ast.AsyncFunctionDef, ast.ClassDef, ast.Lambda)


def _scopes(tree: ast.AST) -> list[ast.AST]:
    """One scope per function or class body, plus the module itself.

    Names are resolved per function, not per file. `task` is a `ScheduledTask`
    in eleven handlers of `routes/task/task_routes.py` and a `TaskRun` query
    sits in a twelfth; a file-wide name set makes every `task.status = "paused"`
    in that file look like a bad run status, and a checker that cries wolf is a
    checker somebody deletes.
    """
    out: list[ast.AST] = [tree]
    for node in ast.walk(tree):
        if isinstance(node, _NESTED):
            out.append(node)
    return out


def _own_nodes(scope: ast.AST):
    """Every node in `scope` that is not inside a nested function or class.

    `ast.walk` cannot do this: `routes/task/task_routes.py` is one 800-line
    `setup_task_routes` with every handler nested inside it, so walking the
    outer function is walking the file.
    """
    stack = []
    for field, value in ast.iter_fields(scope):
        if isinstance(value, list):
            stack.extend(v for v in value if isinstance(v, ast.AST))
        elif isinstance(value, ast.AST):
            stack.append(value)
    while stack:
        node = stack.pop()
        yield node
        if isinstance(node, _NESTED):
            continue
        stack.extend(ast.iter_child_nodes(node))


def taskrun_names(tree: ast.AST) -> set[str]:
    """Locals in this scope that hold a `TaskRun` row. Fixed point, because
    `q = db.query(TaskRun)` and `run = q.first()` are two statements apart."""
    bound: set[str] = set()
    for _ in range(8):
        before = len(bound)
        for node in _own_nodes(tree):
            pairs: list[tuple[ast.AST, ast.AST]] = []
            if isinstance(node, ast.Assign):
                pairs = [(t, node.value) for t in node.targets]
            elif isinstance(node, ast.AnnAssign) and node.value is not None:
                pairs = [(node.target, node.value)]
            elif isinstance(node, (ast.For, ast.AsyncFor)):
                pairs = [(node.target, node.iter)]
            for target, value in pairs:
                if _binds_taskrun(value, bound):
                    bound.update(_bind_targets(target))
        if len(bound) == before:
            break
    return bound


def _literals(node: ast.AST) -> list[str]:
    """Every string constant reachable from a value used as a status."""
    out = []
    for sub in ast.walk(node):
        if isinstance(sub, ast.Constant) and isinstance(sub.value, str):
            out.append(sub.value)
    return out


def _is_status_attr(node: ast.AST, bound: set[str]) -> bool:
    return (isinstance(node, ast.Attribute) and node.attr == "status"
            and isinstance(node.value, ast.Name)
            and (node.value.id in bound or node.value.id == MODEL))


def status_sites(path: Path) -> list[tuple[int, str, str]]:
    """`(line, literal, how)` for every status literal this module writes or
    tests against a `TaskRun` row."""
    tree = ast.parse(path.read_text(encoding="utf-8"), filename=str(path))
    found: list[tuple[int, str, str]] = []
    for scope in _scopes(tree):
        found.extend(_scope_sites(scope))
    return sorted(set(found))


def _scope_sites(tree: ast.AST) -> list[tuple[int, str, str]]:
    bound = taskrun_names(tree)
    found: list[tuple[int, str, str]] = []

    for node in _own_nodes(tree):
        if isinstance(node, (ast.Assign, ast.AnnAssign)):
            targets = node.targets if isinstance(node, ast.Assign) else [node.target]
            if node.value is not None and any(_is_status_attr(t, bound) for t in targets):
                for lit in _literals(node.value):
                    found.append((node.lineno, lit, "assigned"))
        elif isinstance(node, ast.Compare):
            if _is_status_attr(node.left, bound):
                for comp in node.comparators:
                    if isinstance(comp, (ast.Constant, ast.Tuple, ast.List, ast.Set)):
                        for lit in _literals(comp):
                            found.append((node.lineno, lit, "compared"))
            for comp in node.comparators:
                if _is_status_attr(comp, bound) and isinstance(node.left, ast.Constant):
                    for lit in _literals(node.left):
                        found.append((node.lineno, lit, "compared"))
        elif isinstance(node, ast.Call):
            func = node.func
            if isinstance(func, ast.Attribute) and func.attr in {"in_", "notin_"} \
                    and _is_status_attr(func.value, bound):
                for arg in node.args:
                    if isinstance(arg, (ast.Constant, ast.Tuple, ast.List, ast.Set)):
                        for lit in _literals(arg):
                            found.append((node.lineno, lit, "compared"))
            if isinstance(func, ast.Name) and func.id == MODEL:
                for kw in node.keywords:
                    if kw.arg == "status":
                        for lit in _literals(kw.value):
                            found.append((node.lineno, lit, "constructed"))
    return found


# ---------------------------------------------------------------------------
# question 4 — raw SQL, which question 3 cannot see (`B170`)
# ---------------------------------------------------------------------------

# SQL text that names the run table AND does something with a `status` column.
# Both must match: `DELETE FROM task_runs WHERE task_id IN …` (core/database.py)
# touches the table and not the column, and a status comparison against some
# other table is not this vocabulary.
_SQL_TABLE = re.compile(r"\btask_runs\b", re.I)
_SQL_STATUS = re.compile(r"\bstatus\b\s*(?:=|!=|<>|\bIN\b|\bNOT\s+IN\b)", re.I)
# The literals such a statement writes or tests against.
_SQL_STATUS_LITERAL = re.compile(
    r"""\bstatus\b\s*(?:=|!=|<>)\s*(['"])([^'"]*)\1"""
    r"""|\bstatus\b\s*(?:NOT\s+)?IN\s*\(([^)]*)\)""",
    re.I)

LIVE, FIXTURE = "live", "fixture"

# (file, enclosing function) -> (kind, why). Classified rather than merely
# counted, because "there is one and it is fine" is a statement about today that
# nothing re-checks; an entry here is a decision somebody has to repeat before a
# second one lands.
#
#   live      SQL that reaches the database. Its status literals are checked
#             against the vocabulary exactly like an ORM write.
#   fixture   SQL that never reaches a database — the material the tests below
#             feed to this checker to prove it fails. Its literals are
#             deliberately outside the six; checking them would make the test
#             that proves the gate works the thing the gate fails on.
#
# Do not quote a statement inside a `why`: this scan reads the strings in
# assignments, so a statement spelled out here is a site.
RAW_SQL_STATUS_SITES: dict[tuple[str, str], tuple[str, str]] = {
    ("core/database.py", "_migrate_reclassify_admin_refusals"): (
        LIVE,
        "`B07`'s one-time re-file of pre-`B07` admin-privilege refusals from "
        "`error` to `skipped`. Raw SQL rather than the ORM because it runs "
        "inside `_run_migrations()`, where the work is a single set-based "
        "UPDATE over rows nothing has loaded"),
    ("tests/test_run_status_is_one_vocabulary.py",
     "test_the_raw_sql_scan_reads_statements_and_not_prose"): (
        FIXTURE,
        "`B170`. Writes two throwaway modules and runs the detector over them, "
        "to show a docstring and a comment are not statements and a call is"),
    ("tests/test_run_status_is_one_vocabulary.py",
     "test_a_raw_sql_status_write_fails_the_checker_by_name"): (
        FIXTURE,
        "`B170`'s `Verify`. The mutations it applies to a COPY of the tree "
        "(`Law 19`), one of which is a status outside the six"),
    ("tests/test_run_status_is_one_vocabulary.py", "<module>"): (
        FIXTURE,
        "the anchor string the two mutation tests above share, kept at module "
        "level so both of them cut at the same text"),
}


def raw_sql_status_sites(path: Path) -> list[tuple[int, str, list[str]]]:
    """`(line, enclosing function, status literals)` for every raw-SQL
    statement in *path* that writes or tests `task_runs.status`.

    Only strings reachable from a **call** or an **assignment** are read. That
    is not a shortcut, it is the whole reason this can be narrow: SQL is
    executed from a call (`conn.execute(text(...))`) or built into a name that
    is then executed, and restricting to those two shapes means a docstring —
    including this module's own register entries, and `core/database.py`'s
    migration docstring, which spells the statement out in prose — can never be
    mistaken for a statement. `Law 20` in the same direction as question 3.
    """
    tree = ast.parse(path.read_text(encoding="utf-8"), filename=str(path))
    parents: dict[ast.AST, ast.AST] = {}
    for node in ast.walk(tree):
        for child in ast.iter_child_nodes(node):
            parents[child] = node

    def enclosing(node: ast.AST) -> str:
        cur: ast.AST | None = node
        while cur is not None:
            if isinstance(cur, (ast.FunctionDef, ast.AsyncFunctionDef)):
                return cur.name
            cur = parents.get(cur)
        return "<module>"

    def _blob(scope: ast.AST) -> str:
        return "\n".join(
            sub.value for sub in ast.walk(scope)
            if isinstance(sub, ast.Constant) and isinstance(sub.value, str))

    found: list[tuple[int, str, list[str]]] = []
    # Top-down, and a match is not descended into: `conn.execute(text("UPDATE
    # task_runs …"))` is two nested Calls carrying one statement, and counting
    # it twice makes the register look like it is missing an entry.
    stack: list[ast.AST] = [tree]
    while stack:
        node = stack.pop()
        scope: ast.AST | None = None
        if isinstance(node, ast.Call):
            scope = node
        elif isinstance(node, (ast.Assign, ast.AnnAssign)) and node.value is not None:
            scope = node.value
        if scope is not None:
            blob = _blob(scope)
            if _SQL_TABLE.search(blob) and _SQL_STATUS.search(blob):
                literals: set[str] = set()
                for m in _SQL_STATUS_LITERAL.finditer(blob):
                    if m.group(2) is not None:
                        literals.add(m.group(2))
                    else:
                        literals.update(
                            re.findall(r"""['"]([^'"]*)['"]""", m.group(3) or ""))
                found.append((node.lineno, enclosing(node), sorted(literals)))
                continue
        stack.extend(ast.iter_child_nodes(node))
    return sorted(found)


# Directories that are not ours to parse, spelled the way `check-licences.py`
# spells them.
_SKIP_DIRS = {".git", "node_modules", "library", "venv", ".venv", "__pycache__"}


def _python_files() -> list[str]:
    """Every tracked `.py`, or every `.py` on disk when there is no index.

    The fallback is not defensive padding: the test that proves this checker
    catches a seventh status runs it over a COPY of the tree, because editing
    the tree a suite run is reading is `Law 19`. A copy has no git index.
    """
    out = subprocess.run(["git", "ls-files", "*.py"], cwd=str(ROOT),
                         capture_output=True, text=True)
    tracked = [f for f in out.stdout.split() if f]
    if tracked:
        return tracked
    found = []
    for path in ROOT.rglob("*.py"):
        rel = path.relative_to(ROOT)
        if _SKIP_DIRS & set(rel.parts):
            continue
        found.append(str(rel))
    return sorted(found)


# ---------------------------------------------------------------------------

def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("--list", action="store_true",
                    help="print every status literal the tree writes, and where")
    args = ap.parse_args()

    problems: list[str] = []

    consts = _module_constants(DB)
    stored = list(consts.get("TASK_RUN_STATUSES") or [])
    active = list(consts.get("TASK_RUN_ACTIVE_STATUSES") or [])
    notify = consts.get("TASK_RUN_NOTIFY") or {}
    if not stored:
        print("core/database.py declares no TASK_RUN_STATUSES — nothing to check against.")
        return 1

    js = _blank_comments(JS.read_text(encoding="utf-8"))
    js_six = _js_array(js, "RUN_STATUSES")
    js_active = _js_array(js, "RUN_ACTIVE_STATUSES")
    subjects = _js_array(js, "RUN_SUBJECTS") or []
    words = _js_words(js)

    # 1 — the two languages
    if js_six is None:
        problems.append(f"{JS.relative_to(ROOT)}: no RUN_STATUSES array to read.")
    elif js_six != stored:
        problems.append(
            f"{JS.relative_to(ROOT)} RUN_STATUSES is {js_six} and "
            f"core/database.py TASK_RUN_STATUSES is {stored} — one language has "
            "learned a status the other has not.")
    if js_active is not None and js_active != active:
        problems.append(
            f"RUN_ACTIVE_STATUSES {js_active} != TASK_RUN_ACTIVE_STATUSES {active}.")

    # 2 — the word table and the notification policy, against the vocabulary
    if words is None:
        problems.append(f"{JS.relative_to(ROOT)}: no WORDS table to read.")
    else:
        for status in stored:
            row = words.get(status)
            if row is None:
                problems.append(
                    f"{JS.relative_to(ROOT)}: `{status}` is a stored status with no "
                    "row in WORDS — runStatusLabel would print the stored value at "
                    "the user, which is what `B84` closed.")
            elif len(row) != len(subjects) or not all(w.strip() for w in row):
                problems.append(
                    f"{JS.relative_to(ROOT)}: WORDS[{status}] is {row}, and "
                    f"RUN_SUBJECTS is {subjects} — every subject needs a word.")
        for status in sorted(set(words) - set(stored)):
            problems.append(
                f"{JS.relative_to(ROOT)}: WORDS has `{status}`, which is not a "
                "stored status. Delete it or add the value.")

    if not notify:
        problems.append(
            "core/database.py declares no TASK_RUN_NOTIFY — which outcomes are "
            "worth telling the owner about is the statement `B112` put there, and "
            "without it the silence is an omission again.")
    else:
        for status in stored:
            if status not in notify:
                problems.append(
                    f"core/database.py: TASK_RUN_NOTIFY has no entry for `{status}` "
                    "— every status needs a stated yes or no with a reason (`B112`).")
            elif not str(notify[status][1]).strip():
                problems.append(
                    f"core/database.py: TASK_RUN_NOTIFY[{status!r}] has no reason.")
        for status in sorted(set(notify) - set(stored)):
            problems.append(
                f"core/database.py: TASK_RUN_NOTIFY has `{status}`, which is not a "
                "stored status.")

    # 3 — what the code writes, and 4 — what raw SQL writes (`B170`)
    vocabulary = set(stored)
    sites = 0
    scanned = 0
    raw_sites = 0
    classified: set[tuple[str, str]] = set()
    for rel in _python_files():
        path = ROOT / rel
        try:
            found = status_sites(path)
            raw_found = [] if rel == SELF else raw_sql_status_sites(path)
        except SyntaxError as e:
            problems.append(f"{rel}: will not parse ({e})")
            continue
        scanned += 1
        for line, literal, how in found:
            sites += 1
            if args.list:
                print(f"{literal:<10} {how:<12} {rel}:{line}")
            if literal not in vocabulary:
                problems.append(
                    f"{rel}:{line}: `{literal}` is {how} as a TaskRun.status and is "
                    f"not one of {stored}. Add it to TASK_RUN_STATUSES, "
                    "static/js/runStatus.js and TASK_RUN_NOTIFY, or use a value "
                    "that exists.")
        for line, fn, literals in raw_found:
            raw_sites += 1
            key = (rel, fn)
            classified.add(key)
            if args.list:
                kind = (RAW_SQL_STATUS_SITES.get(key) or ("?", ""))[0]
                print(f"{'|'.join(literals) or '-':<10} {'raw-sql/' + kind:<12} "
                      f"{rel}:{line}  ({fn})")
            entry = RAW_SQL_STATUS_SITES.get(key)
            if entry is None:
                problems.append(
                    f"{rel}:{line}: `{fn}` writes or tests task_runs.status in raw "
                    "SQL, which the ORM walk above cannot see, and nothing has "
                    "classified it. Add ('" + rel + "', '" + fn + "') to "
                    "RAW_SQL_STATUS_SITES as `live` or `fixture` with the reason, "
                    "or use the ORM so question 3 covers it (`B170`).")
            elif entry[0] == LIVE:
                for literal in literals:
                    if literal not in vocabulary:
                        problems.append(
                            f"{rel}:{line}: `{literal}` is written to "
                            f"task_runs.status in raw SQL by `{fn}` and is not one "
                            f"of {stored}. Add it to TASK_RUN_STATUSES, "
                            "static/js/runStatus.js and TASK_RUN_NOTIFY, or use a "
                            "value that exists.")

    for key in sorted(set(RAW_SQL_STATUS_SITES) - classified):
        problems.append(
            f"RAW_SQL_STATUS_SITES classifies `{key[1]}` in {key[0]} and there is no "
            "raw-SQL status statement there any more — remove the entry so the "
            "register stays a description of the tree.")

    print(f"run statuses {len(stored)}  ·  files scanned {scanned}  ·  "
          f"status literals {sites}  ·  raw-SQL status sites {raw_sites}  ·  "
          f"PROBLEMS {len(problems)}")
    for p in problems:
        print(f"  {p}")
    return 1 if problems else 0


if __name__ == "__main__":
    sys.exit(main())
