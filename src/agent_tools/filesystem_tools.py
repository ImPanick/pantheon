# SPDX-License-Identifier: AGPL-3.0-or-later
import asyncio
import json
import os
import re
import difflib
import fnmatch
import shutil
from typing import Optional, Dict, Any, Tuple, List

from src.constants import MAX_READ_CHARS, MAX_DIFF_LINES, MAX_OUTPUT_CHARS

from . import codenav_walk as _codenav

_CODENAV_SKIP_DIRS = frozenset({
    ".git", ".hg", ".svn", "node_modules", "venv", ".venv", "__pycache__",
    ".mypy_cache", ".pytest_cache", ".ruff_cache", "dist", "build",
    ".next", ".cache", "site-packages", ".idea", ".tox",
})
_CODENAV_MAX_HITS = 200
_CODENAV_MAX_LINE = 400


# `P20-03`. The glob translation and both code-nav walks live in
# `codenav_walk.py` now, because the workstation runs the same text; this name is
# kept for anything that reached for it here.
_glob_to_regex = _codenav.glob_to_regex

def _unified_diff(old: str, new: str, path: str) -> Optional[Dict[str, Any]]:
    if old == new:
        return None
    old_lines = old.splitlines()
    new_lines = new.splitlines()
    label = path or "file"
    diff_lines = list(difflib.unified_diff(
        old_lines, new_lines,
        fromfile=f"a/{label}", tofile=f"b/{label}",
        lineterm="",
    ))
    added = sum(1 for line in diff_lines if line.startswith("+") and not line.startswith("+++"))
    removed = sum(1 for line in diff_lines if line.startswith("-") and not line.startswith("---"))
    truncated = False
    if len(diff_lines) > MAX_DIFF_LINES:
        diff_lines = diff_lines[:MAX_DIFF_LINES]
        truncated = True
    text = "\n".join(diff_lines)
    if truncated:
        text += f"\n… diff truncated at {MAX_DIFF_LINES} lines"
    return {
        "text": text,
        "added": added,
        "removed": removed,
        "new_file": old == "",
        "file": os.path.basename(path) or (path or "file"),
    }

# ── `P20-03`: the parts of each file tool that do not care where the file is ──
#
# With the workstation on, these tools run against a file in the person's
# workstation home instead of one on this machine (`workstation_tools.py`).
# Everything below — how the arguments are read, how a file is read into text,
# how an edit or a patch transforms it, how the answer is worded — is shared by
# both, so the two places cannot answer the same call differently. The host
# classes further down call these exactly as their bodies used to run inline.


def _edit_file_args(content: str) -> Tuple[str, Any, Any, bool]:
    """`(path, old_string, new_string, replace_all)` out of an `edit_file` call."""
    try:
        args = json.loads(content) if content.strip().startswith("{") else {}
    except (json.JSONDecodeError, TypeError):
        args = {}
    return ((args.get("path") or "").strip(), args.get("old_string", ""),
            args.get("new_string", ""), bool(args.get("replace_all", False)))


def _edit_args_error(old: Any, new: Any) -> Optional[Dict[str, Any]]:
    """The refusals `edit_file` gives before it touches the file."""
    if old == "":
        return {"error": "edit_file: old_string required (use write_file to create a file)", "exit_code": 1}
    if old == new:
        return {"error": "edit_file: old_string and new_string are identical", "exit_code": 1}
    return None


def _replace_exact(original: str, old: str, new: str, replace_all: bool) -> Tuple[Optional[str], str]:
    """`edit_file`'s transformation: `(updated, "ok")`, or `(None, why)` when
    `old` is missing or ambiguous."""
    count = original.count(old)
    if count == 0:
        return None, "not_found"
    if count > 1 and not replace_all:
        return None, f"not_unique:{count}"
    updated = original.replace(old, new) if replace_all else original.replace(old, new, 1)
    return updated, "ok"


def _edit_result(path: str, original: str, updated: Optional[str], status: str,
                 old: str) -> Dict[str, Any]:
    """What `edit_file` answers once the transformation has run."""
    if status == "not_found":
        return {"error": f"edit_file: old_string not found in {path}. Read the file and match it exactly.", "exit_code": 1}
    if status.startswith("not_unique"):
        n = status.split(":", 1)[1]
        return {"error": f"edit_file: old_string is not unique in {path} ({n} matches). Add surrounding context or set replace_all=true.", "exit_code": 1}

    n = original.count(old)
    result = {"output": f"Edited {path} ({n} replacement{'s' if n != 1 else ''})", "exit_code": 0}
    diff = _unified_diff(original, updated, path)
    if diff:
        result["diff"] = diff
    return result


def _read_file_args(content: str) -> Tuple[str, int, int]:
    """`(path, offset, limit)` out of a `read_file` call — a JSON object, or a
    bare path on the first line."""
    raw_path, offset, limit = content.split("\n", 1)[0].strip(), 0, 0
    _stripped = content.strip()
    if _stripped.startswith("{"):
        try:
            _a = json.loads(_stripped)
            raw_path = str(_a.get("path", "")).strip()
            offset = int(_a.get("offset") or 0)
            limit = int(_a.get("limit") or 0)
        except (json.JSONDecodeError, TypeError, ValueError):
            pass
    return raw_path, offset, limit


def _read_cap() -> Optional[int]:
    """`MAX_READ_CHARS`, or None when the run's caps are lifted (`runtime_limits`)."""
    try:
        from src.runtime_limits import unlimited as _unlimited
        return None if _unlimited() else MAX_READ_CHARS
    except Exception:
        return MAX_READ_CHARS


def _read_text(open_text, offset: int, limit: int, read_cap: Optional[int]) -> str:
    """`read_file`'s read, from whatever `open_text()` opens: a text stream
    decoded as UTF-8 with `errors="replace"` and universal newlines, which is
    what `open(path, "r", ...)` gives and what the workstation's reader gives
    too (it is the same `io.TextIOWrapper` over a different raw layer)."""
    if offset > 0 or limit > 0:
        start = max(offset, 1)
        out, n, budget = [], 0, (MAX_READ_CHARS if read_cap is not None else (1 << 62))
        with open_text() as f:
            for i, line in enumerate(f, 1):
                if i < start:
                    continue
                if limit > 0 and n >= limit:
                    break
                out.append(line)
                n += 1
                budget -= len(line)
                if budget <= 0:
                    out.append(f"\n... [truncated at {MAX_READ_CHARS} chars]")
                    break
        return "".join(out)
    with open_text() as f:
        data = f.read((MAX_READ_CHARS + 1) if read_cap is not None else -1)
    if read_cap is not None and len(data) > MAX_READ_CHARS:
        data = data[:MAX_READ_CHARS] + f"\n... [truncated at {MAX_READ_CHARS} chars]"
    return data


def _write_file_args(content: str) -> Tuple[str, str]:
    """`(path, body)` out of a `write_file` call: the path on the first line and
    the body after it, or a JSON object carrying both."""
    lines = content.split("\n", 1)
    raw_path = lines[0].strip()
    body = lines[1] if len(lines) > 1 else ""
    # Decode JSON-object args (the fenced inline-args shape
    # ```write_file {"path": "...", "content": "..."}```), matching
    # ReadFileTool above. Without this the whole JSON string becomes the
    # path and the file is written under a garbage name. This is the live
    # path: there is no filesystem MCP server, so write_file always runs
    # here via _direct_fallback, not through _build_mcp_args.
    _stripped = content.strip()
    if _stripped.startswith("{"):
        try:
            _a = json.loads(_stripped)
            if isinstance(_a, dict) and "path" in _a:
                raw_path = str(_a.get("path", "")).strip()
                body = str(_a.get("content", ""))
        except (json.JSONDecodeError, TypeError, ValueError):
            pass
    return raw_path, body


def _previous_text(open_text) -> str:
    """What a file held before `write_file` replaces it, for the diff. Anything
    that cannot be read as UTF-8 text — missing, a directory, binary — is "",
    so the diff shows a new file rather than failing the write."""
    try:
        with open_text() as f:
            return f.read()
    except (FileNotFoundError, IsADirectoryError, UnicodeDecodeError, OSError):
        return ""


def _write_result(path: str, old: str, body: str) -> Dict[str, Any]:
    diff = _unified_diff(old, body, path)
    result = {"output": f"Wrote {len(body)} bytes to {path}", "exit_code": 0}
    if diff:
        result["diff"] = diff
    return result


class EditFileTool:
    async def execute(self, content: str, ctx: dict) -> dict:
        from src.tool_execution import _resolve_tool_path, _resolve_search_root, _truncate
        raw_path, old, new, replace_all = _edit_file_args(content)
        if not raw_path:
            return {"error": "edit_file: path required", "exit_code": 1}
        try:
            path = _resolve_tool_path(raw_path)
        except ValueError as e:
            return {"error": f"edit_file: {e}", "exit_code": 1}
        refused = _edit_args_error(old, new)
        if refused:
            return refused

        def _apply():
            """Read, transform (`_replace_exact`, shared with the workstation), write."""
            with open(path, "r", encoding="utf-8") as f:
                original = f.read()
            updated, status = _replace_exact(original, old, new, replace_all)
            if status != "ok":
                return original, None, status
            with open(path, "w", encoding="utf-8") as f:
                f.write(updated)
            return original, updated, "ok"

        try:
            original, updated, status = await asyncio.to_thread(_apply)
        except FileNotFoundError:
            return {"error": f"edit_file: {path}: not found (use write_file to create it)", "exit_code": 1}
        except (IsADirectoryError, UnicodeDecodeError):
            return {"error": f"edit_file: {path}: not an editable text file", "exit_code": 1}
        except PermissionError:
            return {"error": f"edit_file: {path}: permission denied", "exit_code": 1}
        except OSError as e:
            return {"error": f"edit_file: {path}: {e}", "exit_code": 1}

        return _edit_result(path, original, updated, status, old)

class ReadFileTool:
    async def execute(self, content: str, ctx: dict) -> dict:
        from src.tool_execution import _resolve_tool_path, _resolve_search_root, _truncate
        raw_path, offset, limit = _read_file_args(content)
        try:
            path = _resolve_tool_path(raw_path)
        except ValueError as e:
            return {"error": f"read_file: {e}", "exit_code": 1}
        read_cap = _read_cap()
        try:
            data = await asyncio.to_thread(
                _read_text, lambda: open(path, "r", encoding="utf-8", errors="replace"),
                offset, limit, read_cap)
        except FileNotFoundError:
            return {"error": f"read_file: {path}: not found", "exit_code": 1}
        except PermissionError:
            return {"error": f"read_file: {path}: permission denied", "exit_code": 1}
        except IsADirectoryError:
            return {"error": f"read_file: {path}: is a directory (use ls)", "exit_code": 1}
        except OSError as e:
            return {"error": f"read_file: {path}: {e}", "exit_code": 1}
        return {"output": data, "exit_code": 0}

class WriteFileTool:
    async def execute(self, content: str, ctx: dict) -> dict:
        from src.tool_execution import _resolve_tool_path, _resolve_search_root, _truncate
        raw_path, body = _write_file_args(content)
        try:
            path = _resolve_tool_path(raw_path)
        except ValueError as e:
            return {"error": f"write_file: {e}", "exit_code": 1}
        try:
            def _write():
                old = _previous_text(lambda: open(path, "r", encoding="utf-8"))
                d = os.path.dirname(path)
                if d:
                    os.makedirs(d, exist_ok=True)
                with open(path, "w", encoding="utf-8") as f:
                    f.write(body)
                return old
            old_content = await asyncio.to_thread(_write)
        except PermissionError:
            return {"error": f"write_file: {path}: permission denied", "exit_code": 1}
        except OSError as e:
            return {"error": f"write_file: {path}: {e}", "exit_code": 1}
        return _write_result(path, old_content, body)

class ApplyPatchTool:
    async def execute(self, content: str, ctx: dict) -> dict:
        """Apply a small Codex-style patch using exact context matching.

        This is deliberately stricter than git-apply: if an update hunk's old
        text is not found exactly once, the whole patch is rejected before any
        file is changed. That keeps agent edits reviewable and avoids fuzzy
        corruption when the model patches stale context.
        """
        from src.tool_execution import _resolve_tool_path

        patch_text = _patch_text(content)
        if not patch_text.strip():
            return {"error": "apply_patch: patch_text required", "exit_code": 1}
        return _run_patch(patch_text, _HostFiles(_resolve_tool_path))


def _patch_text(content: str) -> str:
    """The patch out of an `apply_patch` call: the raw text, or a JSON object's
    `patch_text` (or its `patchText`/`patch` spellings)."""
    patch_text = content or ""
    stripped = patch_text.strip()
    if stripped.startswith("{"):
        try:
            args = json.loads(stripped)
            if isinstance(args, dict):
                patch_text = str(args.get("patch_text") or args.get("patchText") or args.get("patch") or "")
        except (json.JSONDecodeError, TypeError):
            pass
    return patch_text


class _HostFiles:
    """The six file operations a patch needs, on this machine. The workstation
    has its own set (`workstation_tools._WorkstationFiles`); `_run_patch` is
    written against these six so the parse, the all-or-nothing preparation and
    the wording are one implementation (`P20-03`, `Law 14`)."""

    def __init__(self, resolve):
        self.resolve = resolve

    exists = staticmethod(os.path.exists)
    isfile = staticmethod(os.path.isfile)
    remove = staticmethod(os.remove)

    @staticmethod
    def read_text(path: str) -> str:
        with open(path, "r", encoding="utf-8") as f:
            return f.read()

    @staticmethod
    def write_text(path: str, text: str) -> None:
        directory = os.path.dirname(path)
        if directory:
            os.makedirs(directory, exist_ok=True)
        with open(path, "w", encoding="utf-8") as f:
            f.write(text)


def _run_patch(patch_text: str, files) -> Dict[str, Any]:
    """Parse, prepare every file, then write — `apply_patch`'s whole body, over
    `files` (`_HostFiles` or the workstation's)."""
    try:
        ops = _parse_agent_patch(patch_text)
        if not ops:
            return {"error": "apply_patch: no file operations found", "exit_code": 1}
        prepared = []
        for op in ops:
            path = files.resolve(op["path"])
            kind = op["kind"]
            if kind == "add":
                if files.exists(path):
                    return {"error": f"apply_patch: {op['path']}: already exists", "exit_code": 1}
                old = ""
                new = op["content"]
            elif kind == "delete":
                if not files.isfile(path):
                    return {"error": f"apply_patch: {op['path']}: not found", "exit_code": 1}
                old = files.read_text(path)
                new = ""
            else:
                if not files.isfile(path):
                    return {"error": f"apply_patch: {op['path']}: not found", "exit_code": 1}
                old = files.read_text(path)
                new = _apply_patch_hunks(old, op["hunks"], op["path"])
            prepared.append((kind, path, old, new))

        diffs = []
        for kind, path, old, new in prepared:
            if kind == "delete":
                files.remove(path)
            else:
                files.write_text(path, new)
            diff = _unified_diff(old, new, path)
            if diff:
                diffs.append(diff)
    except (ValueError, UnicodeDecodeError, PermissionError, OSError) as e:
        return {"error": f"apply_patch: {e}", "exit_code": 1}

    added = sum(int(d.get("added") or 0) for d in diffs)
    removed = sum(int(d.get("removed") or 0) for d in diffs)
    text_parts = [d.get("text", "") for d in diffs if d.get("text")]
    diff_text = "\n".join(text_parts)
    if len(diff_text.splitlines()) > MAX_DIFF_LINES:
        diff_text = "\n".join(diff_text.splitlines()[:MAX_DIFF_LINES]) + f"\n... diff truncated at {MAX_DIFF_LINES} lines"
    result = {
        "output": f"Applied patch ({len(prepared)} file{'s' if len(prepared) != 1 else ''}, +{added}/-{removed})",
        "exit_code": 0,
    }
    if diffs:
        result["diff"] = {
            "text": diff_text,
            "added": added,
            "removed": removed,
            "new_file": any(d.get("new_file") for d in diffs),
            "file": "patch",
        }
    return result

def _parse_agent_patch(patch_text: str) -> List[Dict[str, Any]]:
    lines = patch_text.replace("\r\n", "\n").replace("\r", "\n").split("\n")
    while lines and not lines[0].strip():
        lines.pop(0)
    while lines and not lines[-1].strip():
        lines.pop()
    if not lines or lines[0].strip() != "*** Begin Patch":
        raise ValueError("patch must start with *** Begin Patch")
    if lines[-1].strip() != "*** End Patch":
        raise ValueError("patch must end with *** End Patch")

    ops: List[Dict[str, Any]] = []
    i = 1
    while i < len(lines) - 1:
        line = lines[i]
        if not line:
            i += 1
            continue
        if line.startswith("*** Add File: "):
            path = line[len("*** Add File: "):].strip()
            body = []
            i += 1
            while i < len(lines) - 1 and not lines[i].startswith("*** "):
                if not lines[i].startswith("+"):
                    raise ValueError(f"add file {path}: every content line must start with +")
                body.append(lines[i][1:])
                i += 1
            ops.append({"kind": "add", "path": path, "content": "\n".join(body) + ("\n" if body else "")})
            continue
        if line.startswith("*** Delete File: "):
            path = line[len("*** Delete File: "):].strip()
            ops.append({"kind": "delete", "path": path})
            i += 1
            continue
        if line.startswith("*** Update File: "):
            path = line[len("*** Update File: "):].strip()
            hunks = []
            current = []
            i += 1
            if i < len(lines) - 1 and lines[i].startswith("*** Move to: "):
                raise ValueError("move operations are not supported")
            while i < len(lines) - 1 and not lines[i].startswith("*** "):
                if lines[i].startswith("@@"):
                    if current:
                        hunks.append(current)
                        current = []
                elif lines[i].startswith((" ", "-", "+")):
                    current.append(lines[i])
                elif lines[i] == "":
                    current.append(" ")
                else:
                    raise ValueError(f"update file {path}: invalid patch line {lines[i]!r}")
                i += 1
            if current:
                hunks.append(current)
            if not hunks:
                raise ValueError(f"update file {path}: no hunks")
            ops.append({"kind": "update", "path": path, "hunks": hunks})
            continue
        raise ValueError(f"unexpected patch line: {line!r}")
    return ops

def _apply_patch_hunks(original: str, hunks: List[List[str]], label: str) -> str:
    updated = original
    for idx, hunk in enumerate(hunks, 1):
        old_lines = []
        new_lines = []
        for line in hunk:
            prefix, body = line[:1], line[1:]
            if prefix in (" ", "-"):
                old_lines.append(body)
            if prefix in (" ", "+"):
                new_lines.append(body)
        old_text = "\n".join(old_lines)
        new_text = "\n".join(new_lines)
        if old_text and old_text in updated:
            occurrences = updated.count(old_text)
            if occurrences != 1:
                raise ValueError(f"{label}: hunk {idx} context matched {occurrences} times")
            updated = updated.replace(old_text, new_text, 1)
        elif old_text + "\n" in updated:
            occurrences = updated.count(old_text + "\n")
            if occurrences != 1:
                raise ValueError(f"{label}: hunk {idx} context matched {occurrences} times")
            updated = updated.replace(old_text + "\n", new_text + "\n", 1)
        else:
            raise ValueError(f"{label}: hunk {idx} context not found")
    return updated

def _ls_args(content: str) -> str:
    """The directory an `ls` call names: a JSON object's `path`, or the first line."""
    raw_path = ""
    _s = (content or "").strip()
    if _s.startswith("{"):
        try:
            raw_path = str(json.loads(_s).get("path", "")).strip()
        except json.JSONDecodeError:
            raw_path = ""
    else:
        raw_path = _s.split("\n", 1)[0].strip()
    return raw_path


def _ls_text(root: str, rows: List[Tuple[bool, str, int]]) -> str:
    """`ls`'s listing of `(is_dir, name, size)` rows — directories first, then
    names without regard to case, dotfiles already left out by the caller."""
    rows.sort(key=lambda r: (not r[0], r[1].lower()))
    lines = [f"{root}:"]
    for is_dir, name, size in rows[:_CODENAV_MAX_HITS]:
        lines.append(f"  {name}/" if is_dir else f"  {name}  ({size} B)")
    if len(rows) > _CODENAV_MAX_HITS:
        lines.append(f"  ... [{len(rows) - _CODENAV_MAX_HITS} more]")
    if not rows:
        lines.append("  (empty)")
    return "\n".join(lines)


class LsTool:
    async def execute(self, content: str, ctx: dict) -> dict:
        from src.tool_execution import _resolve_tool_path, _resolve_search_root, _truncate
        raw_path = _ls_args(content)
        try:
            root = _resolve_search_root(raw_path)
        except ValueError as e:
            return {"error": f"ls: {e}", "exit_code": 1}

        def _ls():
            if not os.path.isdir(root):
                return None, f"ls: {root}: not a directory"
            rows = []
            try:
                with os.scandir(root) as it:
                    for entry in it:
                        if entry.name.startswith("."):
                            continue
                        try:
                            is_dir = entry.is_dir(follow_symlinks=False)
                            size = entry.stat(follow_symlinks=False).st_size if not is_dir else 0
                        except OSError:
                            continue
                        rows.append((is_dir, entry.name, size))
            except (PermissionError, OSError) as _e:
                return None, f"ls: {_e}"
            return _ls_text(root, rows), None

        out, err = await asyncio.to_thread(_ls)
        if err:
            return {"error": err, "exit_code": 1}
        return {"output": _truncate(out), "exit_code": 0}

def _codenav_json_args(content: str) -> Dict[str, Any]:
    """A `glob`/`grep` call's arguments: a JSON object, or the bare text as the pattern."""
    args = {}
    _s = (content or "").strip()
    if _s.startswith("{"):
        try:
            args = json.loads(_s)
        except json.JSONDecodeError:
            args = {}
    else:
        args = {"pattern": _s}
    return args


def _glob_result(paths: Optional[List[str]], err: Optional[str], pattern: str,
                 root: str) -> Dict[str, Any]:
    from src.tool_execution import _truncate
    if err:
        return {"error": err, "exit_code": 1}
    if not paths:
        return {"output": f"No files matching {pattern!r} under {root}", "exit_code": 0}
    out = "\n".join(paths)
    if len(paths) >= _CODENAV_MAX_HITS:
        out += f"\n... [capped at {_CODENAV_MAX_HITS} files]"
    return {"output": _truncate(out), "exit_code": 0}


def _grep_options(args: Dict[str, Any]) -> Tuple[bool, str, int]:
    """`(ignore_case, glob, max_hits)` for a `grep` call, read after its pattern
    was found non-empty (the order the tool has always checked them in)."""
    ignore_case = bool(args.get("ignore_case"))
    glob_pat = str(args.get("glob", "") or "").strip()
    try:
        max_hits = int(args.get("max_results") or _CODENAV_MAX_HITS)
    except (TypeError, ValueError):
        max_hits = _CODENAV_MAX_HITS
    max_hits = max(1, min(max_hits, _CODENAV_MAX_HITS))
    return ignore_case, glob_pat, max_hits


def _grep_result(lines: Optional[List[str]], err: Optional[str], pattern: str, root: str,
                 max_hits: int) -> Dict[str, Any]:
    from src.tool_execution import _truncate
    if err:
        return {"error": err, "exit_code": 1}
    if not lines:
        return {"output": f"No matches for {pattern!r} under {root}", "exit_code": 0}
    out = "\n".join(ln[:_CODENAV_MAX_LINE] for ln in lines)
    if len(lines) >= max_hits:
        out += f"\n... [capped at {max_hits} matches]"
    return {"output": _truncate(out), "exit_code": 0}


class GlobTool:
    async def execute(self, content: str, ctx: dict) -> dict:
        from src.tool_execution import (
            _SENSITIVE_BASENAMES,
            _is_sensitive_path,
            _resolve_tool_path,
            _resolve_search_root,
            _truncate,
        )
        args = _codenav_json_args(content)
        pattern = str(args.get("pattern", "")).strip()
        if not pattern:
            return {"error": "glob: pattern is required", "exit_code": 1}
        try:
            root = _resolve_search_root(str(args.get("path", "")))
        except ValueError as e:
            return {"error": f"glob: {e}", "exit_code": 1}

        # `P20-03`: the walk is `codenav_walk.glob_walk`, the text the
        # workstation runs too. The sensitive-path rule it applies here is
        # `_is_sensitive_path` itself.
        paths, err = await asyncio.to_thread(
            _codenav.glob_walk, root, pattern, _CODENAV_SKIP_DIRS, _SENSITIVE_BASENAMES,
            _is_sensitive_path, _CODENAV_MAX_HITS)
        return _glob_result(paths, err, pattern, root)

class GrepTool:
    async def execute(self, content: str, ctx: dict) -> dict:
        from src.tool_execution import (
            _SENSITIVE_FILE_PATTERNS,
            _is_sensitive_path,
            _resolve_tool_path,
            _resolve_search_root,
            _truncate,
        )
        args = _codenav_json_args(content)
        pattern = str(args.get("pattern", "")).strip()
        if not pattern:
            return {"error": "grep: pattern is required", "exit_code": 1}
        ignore_case, glob_pat, max_hits = _grep_options(args)
        try:
            root = _resolve_search_root(str(args.get("path", "")))
        except ValueError as e:
            return {"error": f"grep: {e}", "exit_code": 1}

        # `P20-03`: `codenav_walk.grep_walk` — ripgrep when it is on PATH,
        # Python's `re` over a pruned walk when not — shared with the
        # workstation, which runs the same text.
        lines, err = await asyncio.to_thread(
            _codenav.grep_walk, root, pattern, ignore_case, glob_pat, max_hits,
            _CODENAV_SKIP_DIRS, _SENSITIVE_FILE_PATTERNS, _is_sensitive_path, _CODENAV_MAX_LINE)
        return _grep_result(lines, err, pattern, root, max_hits)

class GetWorkspaceTool:
    """Report the active workspace folder (no args). File tools are confined to
    it; the shell starts there (cwd) but is NOT sandboxed."""
    async def execute(self, content: str, ctx: dict) -> dict:
        from src.tool_execution import get_active_workspace
        ws = get_active_workspace()
        if ws:
            return {
                "output": f"{ws}\n(File tools are confined to this folder; the shell starts "
                          f"here but is not sandboxed and can reach outside it.)",
                "exit_code": 0,
            }
        return {
            "output": "No workspace is set. File tools use the default allowed roots; "
                      "resolve paths from the user or use absolute paths.",
            "exit_code": 0,
        }
