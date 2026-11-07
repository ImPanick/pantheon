# SPDX-License-Identifier: AGPL-3.0-or-later
"""How long a piece of code takes, timed in an interpreter of its own (`B1902`).

A test that a parser is linear has to hand it an input big enough that a
quadratic or cubic version takes far longer than the budget, and the old code
can run on such an input for hours. Run in the test process, a regression would
wedge the suite; run here, it is killed at a deadline and the test fails. The
clock starts after the program's own imports, which take seconds by themselves
and are not what is being measured.
"""
import subprocess
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[2]

#: Generous on purpose. It only ends a run that has already failed, and the
#: imports before the clock starts can take many seconds on a loaded machine.
DEADLINE_S = 90


def seconds_in_a_fresh_process(setup: str, timed: str, *, deadline: float = DEADLINE_S) -> float:
    """Run `setup`, then `timed`, as top-level code in a fresh interpreter at the
    repository root, and return the seconds `timed` took.

    The test fails when the program raises, and when it is still running at
    `deadline`, which is what the old code does on the inputs these tests use.
    """
    program = (
        "import time as _time\n"
        f"{setup}\n"
        "_started = _time.perf_counter()\n"
        f"{timed}\n"
        "print(_time.perf_counter() - _started)\n"
    )
    try:
        proc = subprocess.run([sys.executable, "-c", program], cwd=str(ROOT),
                              capture_output=True, text=True, timeout=deadline)
    except subprocess.TimeoutExpired as exc:
        # What it printed (and flushed) before it was killed; bytes on POSIX.
        printed = exc.stdout or b""
        if isinstance(printed, bytes):
            printed = printed.decode("utf-8", "replace")
        pytest.fail(f"still running after {deadline:.0f} s:\n{timed}\n"
                    f"-- printed before then --\n{printed}", pytrace=False)
    assert proc.returncode == 0, proc.stderr[-3000:]
    return float(proc.stdout.split()[-1])
