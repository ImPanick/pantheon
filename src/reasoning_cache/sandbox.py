# SPDX-License-Identifier: AGPL-3.0-or-later
"""Where a cache entry's code runs: checked first, then run in its own process.

The code is model-written, so it is held to two fences, either of which would
stop the obvious escapes on its own:

  1. **An allowlist of syntax** (`check_code`): plain functions, loops,
     conditions, literals and calls. No import, class, `with`, `global`,
     `async`, `yield` or `match`; no name or attribute that starts with an
     underscore; none of the frame, code or traceback attributes a generator
     or exception would otherwise lead to; and no `str.format`, whose
     replacement fields can reach attributes the syntax check never sees.
  2. **A separate, limited process** (`run_entry`): `python -I -S` in an empty
     working directory with an empty environment, its builtins cut to the
     plain ones below, no file it may write (`RLIMIT_FSIZE` 0), no process it
     may start, a memory and CPU ceiling, and a wall clock the parent holds.

The code reaches the world only through the primitives, and every primitive
call is a line to the parent, which answers it (`Primitives`): `lm` and
`extract` go to the small model, `invoke_tool` to the tool gate, read-only
tools only. `narrate` and `convert` stay inside the child.
"""
from __future__ import annotations

import ast
import asyncio
import json
import os
import sys
import tempfile
from dataclasses import dataclass, field
from typing import Any, Awaitable, Callable, Dict, List, Optional

#: The key a root function's answer is read from (the paper's natural-language
#: keys, held to one so a run's reply is never guessed from the dict's shape).
FINAL_REPLY_KEY = "the final reply"

MAX_CODE_CHARS = 40_000
MAX_LM_CALLS = 12
MAX_TOOL_CALLS = 6
RUN_TIMEOUT_SECONDS = 120.0
CHILD_MEMORY_BYTES = 1024 * 1024 * 1024
CHILD_CPU_SECONDS = 20
#: The longest single line either side will read: an answer or a tool's output.
MAX_LINE_BYTES = 4 * 1024 * 1024

SAFE_BUILTINS = (
    "abs", "all", "any", "bool", "dict", "divmod", "enumerate", "filter",
    "float", "int", "isinstance", "len", "list", "map", "max", "min", "range",
    "reversed", "round", "set", "sorted", "str", "sum", "tuple", "zip",
    "Exception", "ValueError", "KeyError", "IndexError", "TypeError",
)

PRIMITIVES = ("lm", "extract", "convert", "narrate", "invoke_tool")

_ALLOWED_NODES = (
    ast.Module, ast.FunctionDef, ast.arguments, ast.arg, ast.Return,
    ast.Assign, ast.AugAssign, ast.AnnAssign, ast.For, ast.While, ast.If,
    ast.Break, ast.Continue, ast.Pass, ast.Expr, ast.Try, ast.ExceptHandler,
    ast.Raise, ast.Assert,
    ast.BoolOp, ast.BinOp, ast.UnaryOp, ast.Lambda, ast.IfExp, ast.Dict,
    ast.Set, ast.ListComp, ast.SetComp, ast.DictComp, ast.GeneratorExp,
    ast.Compare, ast.Call, ast.FormattedValue, ast.JoinedStr, ast.Constant,
    ast.Attribute, ast.Subscript, ast.Starred, ast.Name, ast.List, ast.Tuple,
    ast.Slice, ast.comprehension, ast.keyword, ast.NamedExpr,
    ast.Load, ast.Store,
    ast.boolop, ast.operator, ast.unaryop, ast.cmpop,
)
_TRY_STAR = getattr(ast, "TryStar", None)

_DENIED_ATTRS = frozenset({"format", "format_map", "mro"})
_DENIED_ATTR_PREFIXES = ("gi_", "f_", "tb_", "cr_", "ag_", "co_", "func_")


class CodeRefused(ValueError):
    """The code does not pass the allowlist; it is never run."""


class EntryFailed(RuntimeError):
    """The code ran and did not give an answer; the turn falls through."""


def check_code(code: str, root: str) -> None:
    """Refuse code the sandbox will not run, with the reason, or return None."""
    if not isinstance(code, str) or not code.strip():
        raise CodeRefused("there is no code")
    if len(code) > MAX_CODE_CHARS:
        raise CodeRefused(f"the code is longer than {MAX_CODE_CHARS} characters")
    try:
        tree = ast.parse(code, mode="exec")
    except SyntaxError as exc:
        raise CodeRefused(f"the code does not parse: {exc.msg} (line {exc.lineno})")
    roots = []
    for stmt in tree.body:
        if isinstance(stmt, ast.FunctionDef):
            roots.append(stmt.name)
        elif isinstance(stmt, ast.Assign) or (
                isinstance(stmt, ast.Expr) and isinstance(stmt.value, ast.Constant)):
            continue
        else:
            raise CodeRefused(
                f"only functions and constants may sit at the top level, not "
                f"{type(stmt).__name__} (line {stmt.lineno})")
    if root not in roots:
        raise CodeRefused(f"the root function {root!r} is not defined")
    for node in ast.walk(tree):
        if _TRY_STAR is not None and isinstance(node, _TRY_STAR):
            raise CodeRefused("except* is not allowed")
        if not isinstance(node, _ALLOWED_NODES):
            line = getattr(node, "lineno", "?")
            raise CodeRefused(f"{type(node).__name__} is not allowed (line {line})")
        if isinstance(node, ast.FunctionDef) and node.decorator_list:
            raise CodeRefused(f"decorators are not allowed (line {node.lineno})")
        if isinstance(node, ast.Name) and node.id.startswith("_"):
            raise CodeRefused(f"the name {node.id!r} is not allowed (line {node.lineno})")
        if isinstance(node, (ast.FunctionDef, ast.arg)):
            name = node.name if isinstance(node, ast.FunctionDef) else node.arg
            if name.startswith("_"):
                raise CodeRefused(f"the name {name!r} is not allowed")
        if isinstance(node, ast.Attribute):
            attr = node.attr
            if (attr.startswith("_") or attr in _DENIED_ATTRS
                    or attr.startswith(_DENIED_ATTR_PREFIXES)):
                raise CodeRefused(f"the attribute {attr!r} is not allowed (line {node.lineno})")
        if isinstance(node, ast.keyword) and node.arg and node.arg.startswith("_"):
            raise CodeRefused(f"the keyword {node.arg!r} is not allowed")


# The child. It reads one line (the job), drops its limits, runs the code with
# plain builtins and the five primitives, and writes one line per primitive
# call and one at the end. Kept as text so it runs under `-I -S` with nothing
# of Pantheon importable, which is the point.
_CHILD = r'''
import sys, json, ast
_out = sys.stdout
_in = sys.stdin
job = json.loads(_in.readline())
try:
    import resource
    for lim, val in ((resource.RLIMIT_AS, job["mem"]), (resource.RLIMIT_CPU, job["cpu"]),
                     (resource.RLIMIT_FSIZE, 0), (resource.RLIMIT_NPROC, 0)):
        try:
            resource.setrlimit(lim, (val, val))
        except (ValueError, OSError):
            pass
except ImportError:
    pass

class PrimitiveFailed(Exception):
    pass

def _ask(name, args):
    _out.write(json.dumps({"call": name, "args": args}) + "\n")
    _out.flush()
    line = _in.readline()
    if not line:
        raise PrimitiveFailed("the parent went away")
    answer = json.loads(line)
    if "error" in answer:
        raise PrimitiveFailed(str(answer["error"]))
    return answer.get("ok")

narration = []

def lm(prompt):
    return str(_ask("lm", [str(prompt)]))

def extract(text, what):
    return str(_ask("extract", [str(text), str(what)]))

def invoke_tool(name, content=""):
    return str(_ask("invoke_tool", [str(name), str(content)]))

def narrate(text):
    narration.append(str(text)[:500])

def convert(value, kind):
    kind = str(kind).strip().lower()
    if kind in ("str", "string", "text"):
        return str(value)
    if isinstance(value, str):
        text = value.strip()
        if kind in ("int", "integer"):
            return int(float(text.replace(",", "")))
        if kind in ("float", "number"):
            return float(text.replace(",", ""))
        if kind in ("bool", "boolean"):
            return text.lower() in ("true", "yes", "1", "y")
        if kind in ("list", "dict", "tuple"):
            parsed = ast.literal_eval(text)
            return {"list": list, "dict": dict, "tuple": tuple}[kind](parsed)
        raise ValueError("unknown kind " + kind)
    return {"int": int, "integer": int, "float": float, "number": float,
            "bool": bool, "boolean": bool, "list": list, "dict": dict,
            "tuple": tuple}[kind](value)

import builtins as _b
safe = {name: getattr(_b, name) for name in job["builtins"]}
scope = {"__builtins__": safe, "lm": lm, "extract": extract, "convert": convert,
         "narrate": narrate, "invoke_tool": invoke_tool}
try:
    exec(compile(job["code"], "<entry>", "exec"), scope)
    result = scope[job["root"]](dict(job["params"]))
    if not isinstance(result, dict):
        raise TypeError("the root function did not return a dict")
    safe_result = {}
    for key, value in result.items():
        try:
            json.dumps(value)
            safe_result[str(key)] = value
        except (TypeError, ValueError):
            safe_result[str(key)] = str(value)
    _out.write(json.dumps({"result": safe_result, "narration": narration}) + "\n")
except BaseException as exc:
    _out.write(json.dumps({"failed": type(exc).__name__ + ": " + str(exc)[:400],
                           "narration": narration}) + "\n")
_out.flush()
'''


@dataclass
class RunResult:
    reply: str
    result: Dict[str, Any]
    narration: List[str] = field(default_factory=list)
    lm_calls: int = 0
    tool_calls: int = 0


#: `(name, args) -> value`. `name` is `lm`, `extract` or `invoke_tool`.
CallHandler = Callable[[str, List[str]], Awaitable[Any]]


async def run_entry(code: str, root: str, params: Dict[str, Any], on_call: CallHandler,
                    *, timeout: float = RUN_TIMEOUT_SECONDS) -> RunResult:
    """Run checked code in a child process and return its final reply.

    Raises `CodeRefused` before anything runs, and `EntryFailed` for anything
    that goes wrong after: an exception in the code, a primitive the parent
    refused, a missing final reply, the clock or a limit.
    """
    check_code(code, root)
    job = {"code": code, "root": root, "params": params or {},
           "builtins": list(SAFE_BUILTINS),
           "mem": CHILD_MEMORY_BYTES, "cpu": CHILD_CPU_SECONDS}
    counts = {"lm": 0, "tool": 0}
    with tempfile.TemporaryDirectory(prefix="reasoning-cache-") as cwd:
        proc = await asyncio.create_subprocess_exec(
            sys.executable, "-I", "-S", "-c", _CHILD,
            stdin=asyncio.subprocess.PIPE, stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.DEVNULL, cwd=cwd,
            env={"PATH": os.environ.get("PATH", "")} if os.name == "nt" else {},
            limit=MAX_LINE_BYTES)

        async def _converse() -> RunResult:
            assert proc.stdin is not None and proc.stdout is not None
            proc.stdin.write((json.dumps(job) + "\n").encode())
            await proc.stdin.drain()
            while True:
                line = await proc.stdout.readline()
                if not line:
                    raise EntryFailed("the entry stopped without an answer")
                msg = json.loads(line)
                if "call" in msg:
                    answer = await _answer(msg.get("call"), msg.get("args") or [])
                    proc.stdin.write((json.dumps(answer) + "\n").encode())
                    await proc.stdin.drain()
                    continue
                if "failed" in msg:
                    raise EntryFailed(str(msg["failed"]))
                result = msg.get("result") or {}
                reply = result.get(FINAL_REPLY_KEY)
                if not isinstance(reply, str) or not reply.strip():
                    raise EntryFailed(f"the entry gave no {FINAL_REPLY_KEY!r}")
                return RunResult(reply=reply, result=result,
                                 narration=[str(n) for n in msg.get("narration") or []],
                                 lm_calls=counts["lm"], tool_calls=counts["tool"])

        async def _answer(name: Any, args: List[Any]) -> Dict[str, Any]:
            if name in ("lm", "extract"):
                counts["lm"] += 1
                if counts["lm"] > MAX_LM_CALLS:
                    return {"error": f"more than {MAX_LM_CALLS} model calls"}
            elif name == "invoke_tool":
                counts["tool"] += 1
                if counts["tool"] > MAX_TOOL_CALLS:
                    return {"error": f"more than {MAX_TOOL_CALLS} tool calls"}
            else:
                return {"error": f"{name!r} is not a primitive"}
            try:
                return {"ok": await on_call(str(name), [str(a) for a in args])}
            except Exception as exc:   # the child raises it; the turn falls through
                return {"error": f"{type(exc).__name__}: {exc}"[:400]}

        try:
            return await asyncio.wait_for(_converse(), timeout=timeout)
        except asyncio.TimeoutError:
            raise EntryFailed(f"the entry took longer than {int(timeout)} seconds")
        except (ValueError, json.JSONDecodeError) as exc:
            raise EntryFailed(f"the entry wrote something unreadable: {exc}")
        finally:
            if proc.returncode is None:
                try:
                    proc.kill()
                except ProcessLookupError:
                    pass   # it ended on its own between the check and the kill
                await proc.wait()
