# SPDX-License-Identifier: AGPL-3.0-or-later
"""`P22-07` — a workflow step's record speaks the run vocabulary and no other.

`task_run_nodes.status` is `TASK_RUN_STATUSES`' six words: a step runs,
works, fails, is skipped or is stopped, exactly as a run does, and the Runs
view draws it with `runStatus.js`. `.pantheon/check-run-statuses.py` reads
`TaskRunNode` as it reads `TaskRun` (`MODELS`), so a seventh word written to
a step record fails CI by name (`Law 8`). Driven by running the real checker
over a small copy of the tree (`Law 19`: the tree a suite reads is not edited).
"""

import shutil
import subprocess
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]

# What the checker reads, and the one test file its raw-SQL register names
# (it insists every entry still describes a site).
NEEDED = (".pantheon/check-run-statuses.py", "core/database.py",
          "static/js/runStatus.js", "src/workflow_runs.py",
          "tests/test_run_status_is_one_vocabulary.py")


def _tree(tmp_path: Path) -> Path:
    dest = tmp_path / "tree"
    for rel in NEEDED:
        (dest / rel).parent.mkdir(parents=True, exist_ok=True)
        shutil.copyfile(ROOT / rel, dest / rel)
    return dest


def _check(tree: Path):
    proc = subprocess.run([sys.executable, str(tree / ".pantheon" / "check-run-statuses.py")],
                          cwd=str(tree), capture_output=True, text=True, timeout=120)
    return proc.returncode, proc.stdout + proc.stderr


def test_the_step_records_module_passes_as_written(tmp_path):
    code, out = _check(_tree(tmp_path))
    assert code == 0, out


@pytest.mark.parametrize("old,new", [
    # constructed
    ('        status="running",\n', '        status="pending",\n'),
    ('        status="skipped",\n', '        status="planned",\n'),
])
def test_a_seventh_word_on_a_step_record_fails_the_checker_by_name(tmp_path, old, new):
    tree = _tree(tmp_path)
    path = tree / "src" / "workflow_runs.py"
    src = path.read_text(encoding="utf-8")
    assert src.count(old) == 1, "anchor moved"
    path.write_text(src.replace(old, new), encoding="utf-8")
    code, out = _check(tree)
    word = new.split('"')[1]
    assert code == 1 and f"`{word}`" in out, out


def test_a_query_on_step_records_is_held_to_the_six_too(tmp_path):
    tree = _tree(tmp_path)
    (tree / "src" / "probe.py").write_text(
        "from core.database import TaskRunNode\n"
        "def stuck(db):\n"
        "    return db.query(TaskRunNode).filter(TaskRunNode.status == 'stuck').all()\n",
        encoding="utf-8")
    code, out = _check(tree)
    assert code == 1 and "`stuck`" in out, out
