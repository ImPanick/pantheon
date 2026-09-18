#!/usr/bin/env python3
# SPDX-License-Identifier: AGPL-3.0-or-later
"""Background work does not hit anybody all at once (`P15-10`, `P14-07`).

    python3 .pantheon/check-jitter.py            # report
    python3 .pantheon/check-jitter.py --quiet    # findings only

TWO RULES, AND THEY ARE THE SAME RULE POINTED AT TWO MACHINES.

  BOUNDARY  a recurring job that fires on an exact wall-clock instant, so every
            install in the world hits a shared provider on the same second
            (`P15-10`). About somebody *else's* server.

  UNPACED   a file walk that reads documents flat out, with no ceiling and no
            yield, on the machine a person is sitting in front of (`P14-07`).
            About the operator's *own* box.

The second rule lives here rather than in a file of its own because the subject
is one subject — background work nobody is watching — and because a second
checker would have needed its own scan, its own allowlist and its own orphan
rule, which is `Law 14` exactly.

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

# ---------------------------------------------------------------------------
# P14-07 — the walk that reads documents
# ---------------------------------------------------------------------------
#
# WHAT IT LOOKS FOR: a `for` over `os.walk` / `rglob` / `glob` / `iterdir` whose
# body READS FILE CONTENT. A walk that only stats, lists or deletes is not this
# defect — it is cheap and it is over in a moment. The cost is in opening the
# files, and it is a cost in two currencies at once: the memory the content
# takes while it is held (one 419 MB file measured at 1,384 MB of RSS before
# `P14-07` capped it) and the core it holds while it works.
#
# The fix is never "add a sleep here". It is to take the files from
# `src.index_walk`'s paced walk — `personal_docs.walk_index_candidates` — which
# applies the per-file ceiling, the retained-memory budget and the duty cycle in
# one place, so the two indexers cannot drift apart again (#5559, `B75`).
_READS_CONTENT = {
    "open", "read_text", "read_bytes", "extract_index_text", "decode_text_file",
    "read_text_file", "extract_document_text", "extract_pdf_text",
    "extract_office_text",
}
# A loop is paced when its function drives the pacer or takes its files from the
# walk that does.
_PACED_CALLS = {"tick", "IndexPacer", "walk_index_candidates"}
_WALK_CALLS = {"walk", "rglob", "glob", "iterdir"}
# Wrappers that do not change what is being iterated.
_TRANSPARENT = {"sorted", "list", "enumerate", "reversed", "tuple"}

# (file, enclosing function) -> why this walk does not need the paced one.
#
# Every entry is a walk over METADATA — a sidecar JSON, a manifest, a name — at
# a scale set by the product rather than by whatever a user dropped in a folder.
# None of them is an index. The orphan rule below applies to this list too.
INDEXING_ALLOWED = {
    ("src/research_handler.py", "get_avg_duration"):
        "Reads each research run's small JSON sidecar to average a duration. "
        "Bounded by the number of research runs this install has made, and the "
        "files are metadata, not documents.",
    ("routes/auth_routes.py", "rename_user"):
        "A one-off admin rename, walking the renamed user's own skill files. "
        "Human-triggered, once, and the person is watching it.",
    ("routes/research/research_routes.py", "research_library"):
        "Lists the research library by reading each run's metadata JSON. A "
        "listing, per request, over files this product wrote.",
}


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


def _call_names(node):
    """Every function name called anywhere inside `node`."""
    out = set()
    for call in ast.walk(node):
        if isinstance(call, ast.Call):
            name = getattr(call.func, "attr", None) or getattr(call.func, "id", None)
            if name:
                out.add(name)
    return out


def _walk_iterator(node) -> bool:
    """`for ... in os.walk(x)` / `p.rglob(...)`, through the usual wrappers.

    `walk` is accepted **only** as `os.walk`, and that is not pedantry: the
    first run of this rule flagged `routes/email_helpers.py`'s
    `_extract_attachment_text`, which walks `msg.walk()` — the MIME parts of one
    email. Same verb, no filesystem, already capped at 2 MB a part. A rule that
    cannot tell those apart is a rule people route around.
    """
    if not isinstance(node, ast.For):
        return False
    it = node.iter
    while (isinstance(it, ast.Call)
           and (getattr(it.func, "id", None) in _TRANSPARENT) and it.args):
        it = it.args[0]
    if not isinstance(it, ast.Call):
        return False
    func = it.func
    name = getattr(func, "attr", None) or getattr(func, "id", None)
    if name == "walk":
        return (isinstance(func, ast.Attribute)
                and isinstance(func.value, ast.Name)
                and func.value.id in ("os", "_os"))
    return name in _WALK_CALLS


def scan_indexing(problems, seen):
    """`P14-07`. A content-reading file walk that nothing paces or bounds."""
    for path in _python_files():
        try:
            tree = ast.parse(path.read_text(encoding="utf-8"))
        except (OSError, SyntaxError):
            continue
        rel = path.relative_to(ROOT).as_posix()
        for loop in ast.walk(tree):
            if not _walk_iterator(loop):
                continue
            if not (_call_names(loop) & _READS_CONTENT):
                continue            # a walk that only stats or lists is cheap
            where = _enclosing_function(tree, loop)
            seen.append((rel, where, loop.lineno))
            if (rel, where) in INDEXING_ALLOWED:
                continue
            fn = next((n for n in ast.walk(tree)
                       if isinstance(n, (ast.FunctionDef, ast.AsyncFunctionDef))
                       and n.name == where), None)
            if fn is not None and (_call_names(fn) & _PACED_CALLS):
                continue            # it drives the pacer, or takes the paced walk
            problems.append(
                f"UNPACED     {rel}:{loop.lineno} in {where}()\n"
                f"            A file walk that READS the files it finds, with no\n"
                f"            ceiling on their size and nothing yielding the CPU. One\n"
                f"            419 MB file took this process from 185 MB to 1,384 MB of\n"
                f"            RSS before P14-07 capped it, on the machine somebody is\n"
                f"            using. Take the files from\n"
                f"            `personal_docs.walk_index_candidates`, which applies the\n"
                f"            ceiling, the memory budget and the duty cycle in one\n"
                f"            place — or add an entry to INDEXING_ALLOWED in this file\n"
                f"            with the reason this one is metadata rather than an index."
            )


def orphans(problems, seen, allowed=None, what="recurring sleep",
            listname="ALLOWED", fixed="jittered"):
    """An allowlist entry that matches nothing is a decision about code that no
    longer exists. `check-licences.py` learned this rule first: an allowlist
    that only ever grows stops describing the tree and starts excusing it."""
    allowed = ALLOWED if allowed is None else allowed
    matched = {(rel, where) for rel, where, _ in seen}
    for key in sorted(set(allowed) - matched):
        problems.append(
            f"ORPHAN      {listname}[{key!r}] matches no {what}\n"
            f"            The code it excused is gone or has been {fixed}. Remove the\n"
            f"            entry — an allowlist that only grows stops describing the tree."
        )


def main() -> int:
    quiet = "--quiet" in sys.argv
    problems, seen = [], []
    scan(problems, seen)
    orphans(problems, seen)
    walks = []
    scan_indexing(problems, walks)
    orphans(problems, walks, INDEXING_ALLOWED, "content-reading file walk",
            "INDEXING_ALLOWED", "paced")
    if not quiet:
        print(f"recurring sleeps {len(seen)}  ·  allowed {len(ALLOWED)}  ·  "
              f"indexing walks {len(walks)}  ·  allowed {len(INDEXING_ALLOWED)}  ·  "
              f"PROBLEMS {len(problems)}")
    if problems:
        print()
        for p in problems:
            print(p)
        print(f"\nFAIL: {len(problems)} problem(s).")
        return 1
    if not quiet:
        print("OK — no recurring job fires on an exact boundary, and every "
              "content-reading walk is paced.")
    return 0


if __name__ == "__main__":
    try:
        signal.signal(signal.SIGPIPE, signal.SIG_DFL)
    except (AttributeError, ValueError):
        pass
    sys.exit(main())
