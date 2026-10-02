# SPDX-License-Identifier: AGPL-3.0-or-later
"""`P22-05`…`P22-08` — every new workflow route is reached, and the route
ceiling holds without moving (`/work/notes/SLICE-B-DESIGN.md` § 5).

`.pantheon/check-unreachable.py` counts the routes no tracked `static/` string
resolves to, and CI holds that count under a ceiling (`ci.yml`, `--max-routes`).
Measured 2026-10-01 on this branch: **89** with `workflowApi.js` tracked, **98**
with it hidden from the checker — the nine `/api/workflows` paths, each with no
caller. So the module that spells every path out literally is what keeps the
gate green, and this file proves it the only way that means anything: it runs
the real checker over the real tree twice, once as it is and once with that one
file taken out of what the checker reads (its `tracked` listing), and the
difference must be exactly the paths `setup_workflow_routes` mounts — read
from the router, not typed here (`Law 6`).
"""

from __future__ import annotations

import json
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
CALLER = "static/js/workbench/workflowApi.js"

_DRIVER = r"""
import importlib.util, io, json, sys, contextlib
spec = importlib.util.spec_from_file_location("check_unreachable", ".pantheon/check-unreachable.py")
cu = importlib.util.module_from_spec(spec)
spec.loader.exec_module(cu)
ceiling = int(sys.argv[1])
caller = sys.argv[2]

def run(hide):
    real = cu.tracked
    cu.tracked = (lambda *g: [f for f in real(*g) if f != caller]) if hide else real
    try:
        findings, total, source = cu.unreachable()
        sys.argv = ["check-unreachable.py", "--max-routes", str(ceiling), "--quiet"]
        with contextlib.redirect_stdout(io.StringIO()):
            code = cu.main()
        return {"findings": sorted(p for p, _ in findings), "source": source, "exit": code}
    finally:
        cu.tracked = real

from routes.workflow.workflow_routes import setup_workflow_routes
mounted = sorted({r.path for r in setup_workflow_routes(None).routes})
out = {"as_is": run(False), "hidden": run(True), "mounted": mounted}
print("RESULT " + json.dumps(out))
"""


def _ceiling() -> int:
    ci = (ROOT / ".github" / "workflows" / "ci.yml").read_text(encoding="utf-8")
    return int(ci.split("check-unreachable.py --max-routes")[1].split()[0])


def test_each_workflow_route_is_reached_by_workflow_api_and_by_nothing_else():
    tracked = subprocess.run(["git", "ls-files", CALLER], cwd=ROOT, capture_output=True,
                             text=True).stdout.split()
    assert tracked == [CALLER], "the checker reads tracked files only; `git add` the caller"
    proc = subprocess.run([sys.executable, "-c", _DRIVER, str(_ceiling()), CALLER], cwd=ROOT,
                          capture_output=True, text=True, timeout=300)
    lines = [ln for ln in proc.stdout.splitlines() if ln.startswith("RESULT ")]
    assert lines, proc.stdout[-2000:] + proc.stderr[-2000:]
    out = json.loads(lines[-1][len("RESULT "):])
    as_is, hidden, mounted = out["as_is"], out["hidden"], out["mounted"]
    assert as_is["source"] == "app", "the checker fell back to a source scan; the app did not import"
    # Nine from Slice B, and wave D's four (`C-W`: palette, waiting, a step's
    # fields, a parked step's answer) — each spelled out in `workflowApi.js`.
    # Wave E's `C-A` adds a step's "why did this fail?" and its fix (`P22-20`)
    # and a workflow's file (`P22-24`), spelled out there the same way
    # (wb-assist; a draft and a file reuse `POST`, a check reuses `PUT`).
    assert len(mounted) == 16 and all(p.startswith("/api/workflows") for p in mounted)
    assert not [p for p in as_is["findings"] if p.startswith("/api/workflows")]
    assert sorted(set(hidden["findings"]) - set(as_is["findings"])) == mounted
    assert as_is["exit"] == 0, f"over the ceiling with the caller: {len(as_is['findings'])}"
    assert hidden["exit"] == 1, "without the caller the gate must fail"
