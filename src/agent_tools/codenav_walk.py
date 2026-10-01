# SPDX-License-Identifier: AGPL-3.0-or-later
"""The walks behind `glob` and `grep`, written once and run in two places — `P20-03`.

On Pantheon's own machine these are the functions `GlobTool` and `GrepTool`
call. With the workstation on (`D-2026-09-30-03`), the same text is sent to the
workstation and run there by its own `python3`, as the person, against their
home — so a pattern matches, a junk directory is pruned, a key file is skipped,
a hit is capped and a result is ordered in exactly one way, wherever it ran
(`Law 14`: the tools reuse the walk, they do not fork it).

**WHY A STRING, AND NOT A MODULE WHOSE SOURCE IS READ.** The workstation has
Python (its daemon is Python) and nothing of Pantheon, so the code has to travel
as text. Reading this file back with `inspect.getsource` fails in the frozen
desktop builds (`Pantheon.spec` compiles `src/` into the archive and ships no
`.py`), which would make workstation `glob`/`grep` work in Docker and fail on a
Mac. A string is present in every build, and executing the *same* string here is
what keeps the two sides one implementation rather than two that drift.

**WHY NOT THE PROTOCOL'S `list`, OR `find` AND `grep`.** Argued, because the row
asked for it:

  * `list` (recursive) walks without pruning and stops at 5,000 entries. Today's
    `glob` prunes `node_modules`, `.git`, `.venv` and friends *before*
    descending, so on a real project the listing is spent inside `.git` long
    before it reaches the files a pattern is after — a different answer, not a
    slower one. `grep` over `list` would be one request per file.
  * `find`/`grep` are different engines: `grep -E`/`-P` is not Python's `re`,
    `find -name` is not this `**` translation, and the caps, the ordering and
    the sensitive-file rule would all be re-expressed in shell. Every one of
    those is a place to disagree with the host.

Standard library only inside `SOURCE`: it runs where Pantheon is not installed.
"""
from __future__ import annotations

import linecache
from typing import Any, Dict

SOURCE = r'''
import fnmatch
import os
import re
import shutil
import subprocess


def glob_to_regex(pat):
    """Translate a forward-slash glob (**, *, ?) into a compiled regex.
    `**/` matches zero or more complete directories.
    `*` matches within a single path segment (does not cross /).
    """
    i, n, out = 0, len(pat), []
    while i < n:
        if pat[i : i + 3] == "**/":
            out.append("(?:[^/]+/)*")
            i += 3
        elif pat[i : i + 2] == "**":
            out.append(".*")
            i += 2
        elif pat[i] == "*":
            out.append("[^/]*")
            i += 1
        elif pat[i] == "?":
            out.append("[^/]")
            i += 1
        else:
            out.append(re.escape(pat[i]))
            i += 1
    return re.compile("".join(out))


def glob_walk(root, pattern, skip_dirs, sensitive_dirs, is_sensitive, max_hits):
    """`glob`'s walk: `(paths, None)`, newest first and capped, or `(None, error)`."""
    base = os.path.abspath(root)
    if not os.path.isdir(base):
        return None, f"glob: {root}: not a directory"
    rbase = os.path.realpath(base)
    norm_pat = pattern.replace("\\", "/")
    # Fast path: literal pattern (no wildcards) -> direct path lookup.
    if not any(c in norm_pat for c in "*?["):
        cand = os.path.realpath(os.path.join(base, norm_pat))
        # Keep the literal lookup inside the search root. os.path.join
        # lets an absolute pattern (or one containing ../) escape `base`,
        # which would turn glob into an existence/path oracle for
        # arbitrary host files — bypassing the workspace/allowlist
        # confinement that _resolve_search_root applies to the root.
        # An escaping literal falls through to the walk, which only ever
        # yields paths under base.
        nbase = os.path.normcase(rbase)
        try:
            inside = cand == rbase or os.path.commonpath(
                [os.path.normcase(cand), nbase]
            ) == nbase
        except ValueError:
            inside = False
        # A literal that names a deny-listed sensitive file (.env,
        # .ssh/id_rsa, …) falls through to the walk, which skips it —
        # otherwise glob would surface secret paths that read_file /
        # grep already refuse to touch.
        if inside and os.path.exists(cand) and not is_sensitive(cand):
            return [cand], None
        # Literal not at exact path — fall through to walk so
        # e.g. "foo.py" still matches at any depth (like rglob).
    # Compile glob to regex: * stays within one segment, **/ spans dirs.
    regex = glob_to_regex(norm_pat)
    matched = []
    cap = max_hits * 5
    try:
        for dp, dns, fns in os.walk(base):
            # Prune skipped dirs before descending (unlike rglob which
            # descends first then filters — fatal on large node_modules).
            # Sensitive dirs (.ssh, .gnupg, …) are pruned too so glob
            # never enumerates the keys/tokens inside them.
            dns[:] = [
                d for d in dns
                if d not in skip_dirs and d not in sensitive_dirs
            ]
            for name in fns + dns:
                full = os.path.join(dp, name)
                rel = os.path.relpath(full, base).replace(os.sep, "/")
                if regex.fullmatch(rel) or regex.fullmatch(name):
                    # Skip deny-listed sensitive files (.env, id_rsa,
                    # known_hosts, …) the same way grep does.
                    if is_sensitive(os.path.realpath(full)):
                        continue
                    try:
                        mtime = os.stat(full).st_mtime
                    except OSError:
                        mtime = 0
                    matched.append((mtime, full))
            if len(matched) > cap:
                break
    except OSError as _e:
        return None, f"glob: {_e}"
    matched.sort(key=lambda t: t[0], reverse=True)
    return [pth for _, pth in matched[:max_hits]], None


def grep_walk(root, pattern, ignore_case, glob_pat, max_hits, skip_dirs,
              sensitive_file_patterns, is_sensitive, max_line):
    """`grep`'s search: `(lines, None)` or `(None, error)`. ripgrep when it is
    on PATH, Python's `re` over a pruned walk when it is not."""
    rg = shutil.which("rg")
    if rg:
        cmd = [rg, "--line-number", "--no-heading", "--color=never",
               "--max-count", str(max_hits)]
        if ignore_case:
            cmd.append("--ignore-case")
        if glob_pat:
            cmd += ["--glob", glob_pat]
        # --iglob (not --glob) so the exclusion is case-insensitive:
        # on a case-insensitive filesystem "ID_RSA"/"Known_Hosts"
        # resolve to the same secret as their lowercase forms, and the
        # Python fallback below already folds case via _is_sensitive_path.
        for _pat in sensitive_file_patterns:
            cmd += ["--iglob", f"!*{_pat}*"]
        for _d in skip_dirs:
            cmd += ["--glob", f"!**/{_d}/**"]
        cmd += ["--regexp", pattern, root]
        try:
            p = subprocess.run(cmd, capture_output=True, text=True, timeout=20)
            lines = [ln for ln in (p.stdout or "").splitlines() if ln][:max_hits]
            return lines, None
        except subprocess.TimeoutExpired:
            return None, "grep: timed out"
        except Exception as _e:
            return None, f"grep: {_e}"
    try:
        rx = re.compile(pattern, re.IGNORECASE if ignore_case else 0)
    except re.error as _e:
        return None, f"grep: bad pattern: {_e}"
    hits = []
    if os.path.isfile(root):
        file_iter = [root]
    else:
        file_iter = []
        for dp, dns, fns in os.walk(root):
            dns[:] = [d for d in dns if d not in skip_dirs]
            for fn in fns:
                if glob_pat and not fnmatch.fnmatch(fn, glob_pat):
                    continue
                file_iter.append(os.path.join(dp, fn))
    for fp in file_iter:
        if len(hits) >= max_hits:
            break
        if is_sensitive(os.path.realpath(fp)):
            continue
        try:
            with open(fp, "r", encoding="utf-8", errors="strict") as f:
                for i, line in enumerate(f, 1):
                    if rx.search(line):
                        hits.append(f"{fp}:{i}:{line.rstrip()[:max_line]}")
                        if len(hits) >= max_hits:
                            break
        except (UnicodeDecodeError, OSError):
            continue
    return hits, None


def is_sensitive_path(resolved, basenames_cf, patterns_cf):
    """The sensitive-path rule, for the side of the wire that cannot import
    Pantheon. Pantheon's own copy is `src.tool_execution._is_sensitive_path`
    (`FORBIDDEN.md` Part 2) and is what the host passes as `is_sensitive`; this
    one is used only inside the workstation, and a test holds the two equal
    over a corpus of paths so neither can move without the other."""
    parts = [p.casefold() for p in resolved.split(os.sep)]
    filename = parts[-1] if parts else ""
    for part in parts:
        if part in basenames_cf:
            return True
    return filename in patterns_cf
'''

# What the workstation runs: `SOURCE`, then this. Its arguments arrive on stdin
# as one JSON object and its answer leaves on stdout as one — no argument is
# ever spliced into the program text.
RUNNER = r'''

def _main():
    import json
    import sys
    a = json.loads(sys.stdin.read())
    basenames = frozenset(a["sensitive_basenames_cf"])
    patterns = frozenset(a["sensitive_patterns_cf"])

    def sensitive(resolved):
        return is_sensitive_path(resolved, basenames, patterns)

    if a["op"] == "glob":
        paths, err = glob_walk(a["root"], a["pattern"], frozenset(a["skip_dirs"]),
                               frozenset(a["sensitive_dirs"]), sensitive, a["max_hits"])
        out = {"paths": paths, "err": err}
    else:
        lines, err = grep_walk(a["root"], a["pattern"], a["ignore_case"], a["glob"],
                               a["max_hits"], frozenset(a["skip_dirs"]),
                               a["sensitive_file_patterns"], sensitive, a["max_line"])
        # Each line is cut where the card cuts it anyway (`_CODENAV_MAX_LINE`),
        # so one minified file cannot push the answer past what the daemon
        # keeps of a stream.
        if lines is not None:
            lines = [ln[:a["max_line"]] for ln in lines]
        out = {"lines": lines, "err": err}
    sys.stdout.write(json.dumps(out))


_main()
'''

_FILENAME = "<src/agent_tools/codenav_walk.py:SOURCE>"
# Registered so a traceback out of the walk shows its lines, as a file would.
linecache.cache[_FILENAME] = (len(SOURCE), None, SOURCE.splitlines(True), _FILENAME)
_NAMESPACE: Dict[str, Any] = {"__name__": __name__ + ".SOURCE"}
exec(compile(SOURCE, _FILENAME, "exec"), _NAMESPACE)  # noqa: S102 — our own constant, see above

glob_to_regex = _NAMESPACE["glob_to_regex"]
glob_walk = _NAMESPACE["glob_walk"]
grep_walk = _NAMESPACE["grep_walk"]
is_sensitive_path = _NAMESPACE["is_sensitive_path"]


def workstation_program() -> str:
    """The text the workstation's `python3` runs: the walk, then the runner."""
    return SOURCE + RUNNER


__all__ = ["RUNNER", "SOURCE", "glob_to_regex", "glob_walk", "grep_walk", "is_sensitive_path",
           "workstation_program"]
