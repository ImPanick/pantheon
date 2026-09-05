#!/usr/bin/env python3
"""No recurring job fires on an exact boundary (`P15-10`).

    python3 .pantheon/check-jitter.py            # report
    python3 .pantheon/check-jitter.py --quiet    # findings only

WHY THIS IS A CHECKER AND NOT JUST A FIX.

`P15`'s audit opened with a grep that returned nothing: not one recurring job in
the product had jitter. That state did not arrive through a decision — nobody
ever chose an exact sixty seconds, it is simply what you write. So fixing the
call sites without leaving something behind guarantees the next loop somebody
adds is bare again, and the defect is invisible from inside any single install:
the herd is *across* installs, hitting a shared provider at the same instant.

WHAT IT LOOKS FOR.

An `await asyncio.sleep(X)` whose enclosing loop runs for the life of the
process — `while True:` or `while self._running:` — where `X` is a constant or a
plain module attribute. Those are the recurring jobs. A sleep whose argument is
COMPUTED is left alone: the interesting ones in this codebase are already
deliberate (the scheduler waking near the next due boundary, a backoff derived
from a response header), and a rule that could not tell those apart would be a
rule people route around.

The allowlist below is the honest part of this file. Each entry is a recurring
sleep that should NOT be jittered, with the reason.

THE ORPHAN RULE, AND WHY IT IS HERE ON DAY ONE.

An `ALLOWED` entry matching nothing is a decision about code that no longer
exists, and an allowlist that only ever grows stops describing the tree and
starts excusing it. `check-licences.py` learned that rule first; this file was
written with it, and it immediately caught five entries its own author had added
from *reading* the code rather than from running the check — every one of them
covering a sleep whose argument is computed, which this checker never flags. The
reasons that were worth keeping live in `src/jitter.py`'s docstring instead,
where somebody choosing an interval will actually read them.
"""
import ast
import pathlib
import signal
import sys

ROOT = pathlib.Path(__file__).resolve().parent.parent

# The commonest exemption by far, and the reason the allowlist is not empty.
#
# `while True:` inside a per-REQUEST coroutine — a generator pumping tmux output
# to an open SSE stream, a progress emitter, a watchdog that lives as long as one
# task run — looks identical to a recurring job from the AST and is nothing like
# one. It starts when a person does something, ends when that thing ends, and
# talks to a local process. There is no herd: the population is one user, and the
# start time is already random because a human chose it.
#
# The heuristic could try to tell these apart structurally and would be wrong in
# both directions. Naming them is honest, and it means a NEW one has to be added
# deliberately rather than sliding in behind a clever rule.
_REQUEST_SCOPED = ("Request-scoped: starts when a person does something, ends "
                   "with it, and polls a LOCAL process. Not a recurring job — "
                   "the start time is already random because a human chose it.")

# (file, enclosing function) -> why this one is exempt.
ALLOWED = {
    ("src/agent_tools/subprocess_tools.py", "_run_tmux_bash"): _REQUEST_SCOPED,
    ("src/agent_tools/subprocess_tools.py", "_progress_emitter"): _REQUEST_SCOPED,
    ("src/ai_interaction.py", "_poll_progress"): _REQUEST_SCOPED,
    ("routes/chat_routes.py", "stream_with_save"): _REQUEST_SCOPED,
    ("routes/research/research_routes.py", "_generate"): _REQUEST_SCOPED,
    ("routes/shell_routes.py", "_generate_tmux"): _REQUEST_SCOPED,
    ("routes/shell_routes.py", "_generate_win_detached"): _REQUEST_SCOPED,
    ("src/task_scheduler.py", "_cancel_if_foreground_active"):
        "A watchdog inside one task run, polling LOCAL foreground state at "
        "0.25s. Spreading it would make 'background means background' arrive "
        "late, which is the behaviour it exists to guarantee.",
}

_SCANNED = ("app.py", "src", "services", "routes", "core")
_FOREVER_CALLS = {"sleep_jittered"}


def _is_forever_loop(node) -> bool:
    """`while True:` or `while self._running:` — a loop that outlives a request."""
    if not isinstance(node, ast.While):
        return False
    test = node.test
    if isinstance(test, ast.Constant) and test.value is True:
        return True
    if isinstance(test, ast.Attribute) and test.attr in ("_running", "running"):
        return True
    return False


def _is_bare_interval(node) -> bool:
    """A literal, or a plain NAME/ATTRIBUTE constant. Not a computed value."""
    if isinstance(node, ast.Constant):
        return isinstance(node.value, (int, float))
    if isinstance(node, ast.Name):
        return node.id.isupper()
    if isinstance(node, ast.Attribute):
        return node.attr.isupper()
    if isinstance(node, ast.Call):
        # `max(60, something_computed)` — the floor is a constant but the value
        # is not, so this is a computed sleep and out of scope.
        return False
    return False


def _enclosing_function(tree, target):
    best = None
    for node in ast.walk(tree):
        if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
            if node.lineno <= target.lineno <= (node.end_lineno or node.lineno):
                if best is None or node.lineno > best.lineno:
                    best = node
    return best.name if best else "<module>"


def _python_files():
    for entry in _SCANNED:
        path = ROOT / entry
        if path.is_file():
            yield path
        elif path.is_dir():
            for f in sorted(path.rglob("*.py")):
                if "test" in f.parts or f.name.startswith("test_"):
                    continue
                yield f


def scan(problems, seen):
    for path in _python_files():
        try:
            tree = ast.parse(path.read_text(encoding="utf-8"))
        except (OSError, SyntaxError):
            continue
        rel = path.relative_to(ROOT).as_posix()
        for loop in ast.walk(tree):
            if not _is_forever_loop(loop):
                continue
            for call in ast.walk(loop):
                if not isinstance(call, ast.Call):
                    continue
                func = call.func
                name = getattr(func, "attr", None) or getattr(func, "id", None)
                if name in _FOREVER_CALLS:
                    continue
                if name != "sleep" or not call.args:
                    continue
                if not _is_bare_interval(call.args[0]):
                    continue
                where = _enclosing_function(tree, call)
                seen.append((rel, where, call.lineno))
                if (rel, where) in ALLOWED:
                    continue
                problems.append(
                    f"BOUNDARY    {rel}:{call.lineno} in {where}()\n"
                    f"            A recurring sleep on a fixed interval. Every install\n"
                    f"            runs it at the same instant, so a shared provider sees a\n"
                    f"            spike rather than a rate (P15-10). Use\n"
                    f"            `src.jitter.sleep_jittered(...)`, or add an entry to\n"
                    f"            ALLOWED in this file with the reason it must not move."
                )


def orphans(problems, seen):
    """An allowlist entry that matches nothing is a decision about code that no
    longer exists. `check-licences.py` learned this rule first: an allowlist
    that only ever grows stops describing the tree and starts excusing it."""
    matched = {(rel, where) for rel, where, _ in seen}
    for key in sorted(set(ALLOWED) - matched):
        problems.append(
            f"ORPHAN      ALLOWED[{key!r}] matches no recurring sleep\n"
            f"            The code it excused is gone or has been jittered. Remove the\n"
            f"            entry — an allowlist that only grows stops describing the tree."
        )


def main() -> int:
    quiet = "--quiet" in sys.argv
    problems, seen = [], []
    scan(problems, seen)
    orphans(problems, seen)
    if not quiet:
        print(f"recurring sleeps {len(seen)}  ·  allowed {len(ALLOWED)}  ·  "
              f"PROBLEMS {len(problems)}")
    if problems:
        print()
        for p in problems:
            print(p)
        print(f"\nFAIL: {len(problems)} problem(s).")
        return 1
    if not quiet:
        print("OK — no recurring job fires on an exact boundary.")
    return 0


if __name__ == "__main__":
    try:
        signal.signal(signal.SIGPIPE, signal.SIG_DFL)
    except (AttributeError, ValueError):
        pass
    sys.exit(main())
