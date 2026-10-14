#!/usr/bin/env python3
# SPDX-License-Identifier: AGPL-3.0-or-later
"""tool-suite-matrix.py — does Pantheon's whole tool suite reach the model?

One command. It enumerates the suite from the registers the product reads
(`src/tool_schemas.py`'s `FUNCTION_TOOL_SCHEMAS`, a real `McpManager` holding a
real stdio MCP server, `SkillsManager`), drives the product's own agent loop
across a configuration matrix, and prints the table:

    python3 scripts/tool-suite-matrix.py                  # the full matrix
    python3 scripts/tool-suite-matrix.py --quick          # one cell per axis value
    python3 scripts/tool-suite-matrix.py --cells 'emb=up mcp=up'   # a filter
    python3 scripts/tool-suite-matrix.py --json out.json  # the rows, for a diff

The owner's word is *intermittent*, so **variance is the measurement**: every
cell is repeated (`--repeats`, 5 by default) and a cell whose offered set is not
identical across its own repeats is reported as a finding even when every
individual run looks fine.

`Law 19`: a run is evidence about the tree it started with. The commit is
printed, and a dirty tree says so. `Law 10`: every tool in every cell gets one
of three verdicts — `reached`, `held` (a named gate withheld it, with the gate's
own sentence: a **pass**, and `FORBIDDEN.md` Part 2 is why), or `missing` (every
gate allowed it and it still did not reach the model).

Two processes are spawned, one per embedding state, because the tool index is a
process singleton and `src/constants.py` reads the data directory at import —
the same reason a real install's embedding backend is decided before boot. Each
writes a throwaway data directory under `--scratch` and deletes it on the way
out.

The harness itself is `tests/helpers/tool_suite_probe.py`; this file is its
command line. Nothing here changes product code.
"""
from __future__ import annotations

import argparse
import json
import os
import shutil
import subprocess
import sys
import tempfile
import time

REPO_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, REPO_ROOT)


def _child(args) -> int:
    """One embedding state, in its own process, printing JSON rows on stdout."""
    scratch = args.scratch
    os.makedirs(scratch, exist_ok=True)
    os.environ["PANTHEON_DATA_DIR"] = os.path.join(scratch, "data")
    os.environ["DATABASE_URL"] = "sqlite:///" + os.path.join(scratch, "app.db")
    os.environ["TMPDIR"] = os.path.join(scratch, "tmp")
    os.makedirs(os.environ["TMPDIR"], exist_ok=True)
    if args.embeddings == "up":
        # The real local model, the real in-process vector index. `Law 16`'s
        # download gate is untouched: this points at a cache that already
        # holds the model, and refuses rather than fetching if it does not.
        if args.fastembed_cache:
            os.environ["FASTEMBED_CACHE_PATH"] = args.fastembed_cache
    else:
        # The state a fresh install is in: no embedding server configured and
        # no local model cached, so `build_embedding_lanes` has no lane,
        # `ToolIndex()` raises and `get_tool_index()` answers None — exactly
        # the path `select_without_embeddings` exists for.
        empty = os.path.join(scratch, "no-embeddings")
        os.makedirs(empty, exist_ok=True)
        os.environ["FASTEMBED_CACHE_PATH"] = empty
        os.environ.pop("EMBEDDING_URL", None)

    from tests.helpers import tool_suite_probe as probe

    cells = [c for c in probe.full_matrix() if c.embeddings == args.embeddings]
    if args.quick:
        cells = [c for c in cells if _in_quick(c)]
    if args.cells:
        cells = [c for c in cells if all(bit in c.id for bit in args.cells.split())]
    async def sweep():
        rows = []
        async with probe.probe_world(scratch) as world:
            if args.embeddings == "up":
                # Build the index before the first turn, the way a booted
                # server does: `get_tool_index()` runs at startup there, and a
                # cold 1.5-second race on the very first chat message is
                # `B1330`'s subject rather than this harness's.
                import asyncio as _aio
                from src.tool_index import get_tool_index
                await _aio.to_thread(get_tool_index)
            boot = await probe.boot_connect_report(scratch)
            print("BOOT " + json.dumps({
                "verdict": boot.verdict, "registered": boot.registered,
                "raised": boot.raised, "connected": boot.connected,
                "tools": boot.tools}), flush=True)
            for cell in cells:
                result = await probe.run_cell(
                    world, cell, repeats=args.repeats,
                    reach=not args.no_reach,
                    calls=args.calls,
                    real_calls=args.real_calls,
                )
                rows.append(_row_json(result))
                print("ROW " + json.dumps(rows[-1]), flush=True)
        return rows

    import asyncio
    asyncio.run(sweep())
    return 0


def _in_quick(cell) -> bool:
    """One cell per axis value: the baseline, plus one change at a time."""
    from tests.helpers.tool_suite_probe import Cell

    base = Cell()
    changed = sum(1 for f in ("embeddings", "mcp", "window", "mode", "privilege")
                  if getattr(cell, f) != getattr(base, f))
    return changed <= 1


def _row_json(result) -> dict:
    return {
        "cell": {
            "embeddings": result.cell.embeddings, "mcp": result.cell.mcp,
            "window": result.cell.window, "mode": result.cell.mode,
            "privilege": result.cell.privilege, "id": result.cell.id,
        },
        "suite": result.suite, "builtins": result.builtins,
        "mcp_tools": result.mcp, "skills": result.skills,
        "repeats": result.repeats,
        "turns": result.turns,
        "identical": result.identical, "drift": result.drift,
        "reach": [
            {"tool": r.tool, "kind": r.kind, "verdict": r.verdict,
             "channels": r.channels, "turn": r.turn,
             "gate": r.gate, "sentence": r.sentence}
            for r in result.reach
        ],
        "skill_reach": [
            {"tool": r.tool, "verdict": r.verdict} for r in result.skill_rows
        ],
        "calls": [
            {"tool": r.tool, "kind": r.kind, "shape": r.shape,
             "verdict": r.verdict, "detail": r.detail}
            for r in result.calls
        ],
        "control": (None if result.control is None else
                    {"tool": result.control.tool, "verdict": result.control.verdict,
                     "detail": result.control.detail}),
        "seconds": round(result.seconds, 2),
    }


class _Row:
    """A child's JSON row, rendered by the parent's table code."""

    def __init__(self, data: dict):
        self._d = data
        cell = data["cell"]
        self.cell = type("C", (), {k: cell[k] for k in cell})
        self.suite = data["suite"]
        self.builtins = data["builtins"]
        self.mcp = data["mcp_tools"]
        self.skills = data["skills"]
        self.repeats = data["repeats"]
        self.turns = data.get("turns") or {}
        self.reach = [type("R", (), r) for r in data["reach"]]
        self.skill_rows = [type("R", (), r) for r in data["skill_reach"]]
        self.calls = [type("R", (), r) for r in data["calls"]]
        self.control = data["control"]
        self.seconds = data["seconds"]

    ordinary_counts = property(lambda self: [len(r) for r in self.repeats])
    identical = property(lambda self: self._d["identical"])
    drift = property(lambda self: self._d["drift"])
    reached = property(lambda self: sum(1 for r in self.reach if r.verdict == "reached"))
    held = property(lambda self: sum(1 for r in self.reach if r.verdict == "held"))
    missing = property(lambda self: [r.tool for r in self.reach if r.verdict == "missing"])
    prompt_only = property(
        lambda self: [r.tool for r in self.reach if r.verdict == "prompt_only"])


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description=__doc__,
                                 formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--repeats", type=int, default=5,
                    help="runs per cell; variance across them is the finding (default 5)")
    ap.add_argument("--quick", action="store_true",
                    help="the baseline cell plus one axis change at a time")
    ap.add_argument("--cells", default="",
                    help="space-separated filter on the cell id, e.g. 'emb=up who=admin'")
    ap.add_argument("--calls", action="store_true",
                    help="also drive a call for every tool in every reply shape")
    ap.add_argument("--real-calls", action="store_true",
                    help="with --calls, execute the read-only tools for real")
    ap.add_argument("--no-reach", action="store_true",
                    help="skip the per-tool reach probe (ordinary-turn counts only)")
    ap.add_argument("--json", default="", help="write the rows to this file")
    ap.add_argument("--scratch", default="",
                    help="scratch directory (default: a temp dir, removed afterwards)")
    ap.add_argument("--fastembed-cache", default=os.environ.get("FASTEMBED_CACHE_PATH", ""),
                    help="a cache that already holds the local embedding model")
    ap.add_argument("--embeddings", default="",
                    help=argparse.SUPPRESS)   # the child's own state
    args = ap.parse_args(argv)

    if args.embeddings:
        return _child(args)

    started = time.time()
    owned_scratch = not args.scratch
    scratch = args.scratch or tempfile.mkdtemp(prefix="tool-suite-matrix-")
    rows: list[dict] = []
    boots: list[dict] = []
    failures = []
    try:
        from tests.helpers.tool_suite_probe import EMBEDDINGS, commit_sha, render_table
        print(f"commit: {commit_sha()}")
        print(f"scratch: {scratch}")
        for state in EMBEDDINGS:
            child_scratch = os.path.join(scratch, f"emb-{state}")
            argv_child = [sys.executable, os.path.abspath(__file__),
                          "--embeddings", state,
                          "--repeats", str(args.repeats),
                          "--scratch", child_scratch]
            if args.quick:
                argv_child.append("--quick")
            if args.cells:
                argv_child += ["--cells", args.cells]
            if args.calls:
                argv_child.append("--calls")
            if args.real_calls:
                argv_child.append("--real-calls")
            if args.no_reach:
                argv_child.append("--no-reach")
            if args.fastembed_cache:
                argv_child += ["--fastembed-cache", args.fastembed_cache]
            print(f"\n— embeddings {state} —", flush=True)
            proc = subprocess.Popen(argv_child, cwd=REPO_ROOT, stdout=subprocess.PIPE,
                                    stderr=subprocess.PIPE, text=True)
            assert proc.stdout is not None
            for line in proc.stdout:
                if line.startswith("BOOT "):
                    boot = json.loads(line[5:])
                    boots.append(boot)
                    print(f"  boot connect over {boot['registered']} registered stdio "
                          f"servers (one dead): {boot['verdict']}, "
                          f"{len(boot['connected'])} connected, "
                          f"{len(boot['tools'])} MCP tools"
                          + (f", raised {boot['raised']}" if boot["raised"] else ""),
                          flush=True)
                    continue
                if line.startswith("ROW "):
                    data = json.loads(line[4:])
                    rows.append(data)
                    row = _Row(data)
                    print(f"  {data['cell']['id']}: "
                          f"ordinary {min(row.ordinary_counts)}–{max(row.ordinary_counts)}"
                          f"/{row.builtins + row.mcp}, reached {row.reached}, "
                          f"prompt-only {len(row.prompt_only)}, "
                          f"held {row.held}, missing {len(row.missing)}, "
                          f"{'identical' if row.identical else 'VARIES'}"
                          f"  [{data['seconds']}s]", flush=True)
            proc.wait()
            err = (proc.stderr.read() if proc.stderr else "")
            if proc.returncode != 0:
                failures.append(f"embeddings={state} exited {proc.returncode}\n{err[-4000:]}")

        seconds = time.time() - started
        print("\n" + render_table([_Row(r) for r in rows]))
        print()
        print(_summary(rows, seconds, boots))
        if args.json:
            with open(args.json, "w", encoding="utf-8") as fh:
                json.dump({"commit": commit_sha(), "seconds": round(seconds, 1),
                           "rows": rows}, fh, indent=1)
            print(f"\nrows written to {args.json}")
        for text in failures:
            print("\nFAILED: " + text, file=sys.stderr)
        return 1 if failures else 0
    finally:
        if owned_scratch:
            shutil.rmtree(scratch, ignore_errors=True)


def _summary(rows: list[dict], seconds: float, boots: list[dict] | None = None) -> str:
    from tests.helpers.tool_suite_probe import commit_sha

    varying = [r["cell"]["id"] for r in rows if not r["identical"]]
    missing: dict[str, int] = {}
    for row in rows:
        for entry in row["reach"]:
            if entry["verdict"] == "missing":
                missing[entry["tool"]] = missing.get(entry["tool"], 0) + 1
    prompt_only: dict[str, int] = {}
    for row in rows:
        for entry in row["reach"]:
            if entry["verdict"] == "prompt_only":
                prompt_only[entry["tool"]] = prompt_only.get(entry["tool"], 0) + 1
    skills_missing = {e["tool"] for r in rows for e in r["skill_reach"]
                      if e["verdict"] == "missing"}
    dropped = sorted({f"{e['tool']}/{e['shape']}" for r in rows for e in r["calls"]
                      if e["verdict"] == "dropped"})
    controls = [r["control"] for r in rows if r["control"]]
    bad_control = [c for c in controls if c["verdict"] == "dropped"]
    lines = [
        f"commit: {commit_sha()}   cells: {len(rows)}   wall clock: {seconds:.1f}s",
        f"cells whose offered set VARIED across its own repeats: {len(varying)}"
        + (f" — {', '.join(varying[:6])}" if varying else ""),
        f"tools MISSING (every gate allowed them, they did not reach the model) "
        f"in at least one cell: {len(missing)}",
    ]
    if missing:
        worst = sorted(missing.items(), key=lambda kv: -kv[1])[:12]
        lines.append("  " + ", ".join(f"{n} ({c} cells)" for n, c in worst))
    lines.append(f"tools the prompt named while the request withheld them "
                 f"(prompt_only) in at least one cell: {len(prompt_only)}"
                 + (f" — {', '.join(sorted(prompt_only)[:8])}" if prompt_only else ""))
    lines.append(f"skills that did not reach the model in some cell: {len(skills_missing)}"
                 + (f" — {', '.join(sorted(skills_missing)[:6])}" if skills_missing else ""))
    lines.append(f"tool/shape pairs whose call was DROPPED: {len(dropped)}"
                 + (f" — {', '.join(dropped[:8])}" if dropped else ""))
    for boot in (boots or []):
        lines.append(
            f"boot connect over {boot['registered']} registered stdio servers, one of "
            f"them dead: {boot['verdict']} — {len(boot['connected'])} connected, "
            f"{len(boot['tools'])} MCP tools reached the model"
            + (f" (raised {boot['raised']})" if boot["raised"] else ""))
    if controls:
        lines.append(f"unknown-name control (a call to a name nobody registered must be "
                     f"refused, never routed): {len(controls) - len(bad_control)}"
                     f"/{len(controls)} cells refused it")
    return "\n".join(lines)


if __name__ == "__main__":
    raise SystemExit(main())
