# SPDX-License-Identifier: AGPL-3.0-or-later
"""`B807`, `B891`, `B1502` and `B1503` — comments cite names, not line numbers,
and the task code and the Mermaid path state no caller counts.

**`B807`, measured:** `TaskCreate.crew_member_id`'s comment in
`routes/task/task_routes.py` said its claim was "verified against the source,
not assumed" and cited four line ranges of `src/task_scheduler.py` — a
stale-run branch, a comment, the foreground gate and a notify comment, none of
them what the sentence named. `P8-32` had already found the fifth one in that
block stale by three weeks. The claim was true; the addresses rotted (`Law 6`).

**`B891`, measured:** `static/js/tasks/workflowDiagram.js` said "all four
callers of `renderMermaid`" and "a fourth caller" while the tree had seven call
sites in six files; `tasks.js` said "four call sites and two tests".

**`B1502`** is the remainder of `B807`: the same citations across the rest of
the code — 127 in 50 files under `src/`, `routes/`, `core/`, `services/`,
`static/js/` and `app.py` when it was swept, plus six in the `line N` spelling.
`routes/mcp/mcp_routes.py` cited a line of `src/task_scheduler.py` that had
moved. **`B1503`**: `markdown.js` said *seven call sites in six files* for
`renderMermaid` while the tree held eight in seven.

Every one is a name now. A whole-file absence check is `Law 20`'s one permitted
use of one — a line-number citation anywhere in these files is the defect.
Port numbers (`:445`) and line *lengths* are not citations, and none is left in
a form these patterns would mistake for one.
"""
from __future__ import annotations

import re
import subprocess
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]

TASK_FILES = sorted({
    *(ROOT / "routes" / "task").glob("*.py"),
    ROOT / "src" / "task_scheduler.py",
    ROOT / "static" / "js" / "tasks.js",
    *(ROOT / "static" / "js" / "tasks").glob("*.js"),
})

#: `B1502`'s scope: the product's code, as the row names it.
CODE_ROOTS = ("src", "routes", "core", "services", "static/js", "app.py")


def _code_files() -> list:
    out = subprocess.run(["git", "ls-files", "-z", "--", *CODE_ROOTS], cwd=ROOT,
                         capture_output=True, text=True, check=True).stdout
    return sorted(ROOT / rel for rel in dict.fromkeys(out.split("\0"))
                  if rel.endswith((".py", ".js", ".mjs")))


# `file.py:123`, `markdown.js:94`, and the bare `` `:1685-1686` `` form a
# citation block continues with.
LINE_CITATION = re.compile(r"\b[\w./-]+\.(?:py|js|mjs|css|html):\d+|`:\d+(?:-\d+)?`")
# `B1502`: the same claim in words — `chat.js line 3062`, `(~line 3217)`,
# `(line 1053 of index.html)`, `at line 839`.
LINE_IN_WORDS = re.compile(
    r"\b[\w./-]+\.(?:py|js|mjs|css|html)\s+line\s+\d+"
    r"|\(~?line \d+(?:\)| of)"
    r"|\bat line \d+")
CALLER_COUNT = re.compile(
    r"\b(?:one|two|three|four|five|six|seven|eight|nine|ten|~?\d+) (?:callers|call sites)\b")


def _hits(files, pattern):
    return [f"{p.relative_to(ROOT)}:{n}: {m.group(0)}"
            for p in files
            for n, line in enumerate(p.read_text(encoding="utf-8", errors="replace").splitlines(), 1)
            for m in pattern.finditer(line)]


def _prose_lines(path: Path):
    """`(line, text)` for the comments and docstrings of one file — the prose,
    not the code. `"Image prompt is required (line 1)"` is a message about the
    person's input and is not a citation; a comment saying the same is."""
    import ast
    import io
    import tokenize
    raw = path.read_text(encoding="utf-8", errors="replace")
    if path.suffix == ".py":
        for tok in tokenize.generate_tokens(io.StringIO(raw).readline):
            if tok.type == tokenize.COMMENT:
                yield tok.start[0], tok.string
        for node in ast.walk(ast.parse(raw)):
            if (isinstance(node, ast.Expr) and isinstance(node.value, ast.Constant)
                    and isinstance(node.value.value, str)):
                for k, text in enumerate(node.value.value.splitlines()):
                    yield node.lineno + k, text
        return
    from tests.helpers.source_text import blank
    for n, (a, b) in enumerate(zip(raw.splitlines(), blank(path, raw).splitlines()), 1):
        comment = "".join(x for x, y in zip(a, b) if x != y)
        if comment.strip():
            yield n, comment


def _prose_hits(files, pattern):
    return [f"{p.relative_to(ROOT)}:{n}: {m.group(0)}"
            for p in files for n, text in _prose_lines(p)
            for m in pattern.finditer(text)]


def test_the_task_files_are_the_ones_meant():
    names = {p.relative_to(ROOT).as_posix() for p in TASK_FILES}
    assert {"routes/task/task_routes.py", "src/task_scheduler.py", "static/js/tasks.js",
            "static/js/tasks/taskFields.js", "static/js/tasks/workflowDiagram.js"} <= names


def test_the_code_files_are_the_whole_scope():
    """A scope that silently shrank would pass on anything (`Law 5`)."""
    files = _code_files()
    names = {p.relative_to(ROOT).as_posix() for p in files}
    assert {"app.py", "src/agent_loop.py", "routes/mcp/mcp_routes.py",
            "core/database.py", "services/search/core.py", "static/js/markdown.js",
            "static/js/chatRenderer.js"} <= names
    assert len(files) > 500, len(files)
    assert set(TASK_FILES) <= set(files)


def test_no_comment_in_the_code_cites_a_line_number():
    """`B1502`. Was `test_no_comment_in_the_task_code_cites_a_line_number`,
    over the task files only (`B807`); the rest of the code is held to it now."""
    found = _hits(_code_files(), LINE_CITATION)
    assert found == [], "cite the function's name, not its line:\n" + "\n".join(found)


def test_no_comment_in_the_code_cites_a_line_number_in_words():
    """Read from comments and docstrings only: the words *line 1* in an error
    message about the person's input are not a citation."""
    found = _prose_hits(_code_files(), LINE_IN_WORDS)
    assert found == [], "cite the function's name, not its line:\n" + "\n".join(found)


def test_the_patterns_catch_the_spellings_that_were_swept():
    """Each spelling the sweep removed, so a pattern that stopped matching one
    cannot pass on an empty tree."""
    for text in ("`src/task_scheduler.py:2956`", "(`:1457`)", "`notes.js:4517`, `:4586`",
                 "sidebar-layout.js:57).", "`routes/skills_routes.py:193-196`"):
        assert LINE_CITATION.search(text), text
    for text in ("identical to chat.js line 3062", "rearrangement (~line 3217) moves",
                 "toggle (line 1053 of index.html)", "the source-introspection at line 839"):
        assert LINE_IN_WORDS.search(text), text
    for text in ("its SMB, port 445", "entry line 275 characters", "(lines 110-115: …"):
        assert not LINE_CITATION.search(text) and not LINE_IN_WORDS.search(text), text


def test_no_comment_in_the_task_code_states_a_caller_count():
    found = _hits(TASK_FILES, CALLER_COUNT)
    assert found == [], "a count in a comment is a measurement nobody re-takes:\n" + "\n".join(found)


def _comment_blocks(path: Path):
    """`(first line, text)` for each run of comment lines in a JS file, read
    as what the one blanker removes — so a string is never a comment."""
    from tests.helpers.source_text import blank
    raw = path.read_text(encoding="utf-8")
    blanked = blank(path, raw)
    block, start = [], None
    for n, (a, b) in enumerate(zip(raw.splitlines(), blanked.splitlines()), 1):
        comment = "".join(x for x, y in zip(a, b) if x != y).strip()
        if comment:
            block.append(comment)
            start = start or n
        elif block:
            yield start, " ".join(block)
            block, start = [], None
    if block:
        yield start, " ".join(block)


def test_no_comment_in_static_js_counts_the_callers_of_render_mermaid():
    """`B1503`'s `Verify`. Read per comment block, so a block that names the
    function and a count in different sentences of one paragraph is caught."""
    found = []
    for path in sorted((ROOT / "static" / "js").rglob("*.js")):
        if "/lib/" in path.as_posix():
            continue
        for line, text in _comment_blocks(path):
            if ("renderMermaid" in text or "ensureMermaid" in text) and CALLER_COUNT.search(text):
                found.append(f"{path.relative_to(ROOT)}:{line}: {CALLER_COUNT.search(text).group(0)}")
    assert found == [], ("a caller count in a comment is a measurement nobody "
                         "re-takes (`B891`, `B1503`):\n" + "\n".join(found))
