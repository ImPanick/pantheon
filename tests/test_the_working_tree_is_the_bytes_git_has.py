# SPDX-License-Identifier: AGPL-3.0-or-later
"""`B361` — a file can differ from its own git blob while every tool says clean.

`B360` found three files under `static/lib/` whose bytes on disk disagreed with
their blobs — `docx.umd.min.js` was **762,974 bytes on disk against 742,858 in
`HEAD`** — while `git diff HEAD` reported them unmodified and `git status`
listed nothing. `B362` then found twelve of them on the Windows deployment host
and named the cause: `.gitattributes` set `static/lib/** -whitespace` without
`-text`, so those files resolved to `text: auto` and git rewrote LF to CRLF on
checkout. The working tree is the Docker build context, so the image was built
from bytes this repository does not contain.

Both of those rows looked only at `static/lib/`, because that is what
`check-vendored-versions.py` fingerprints. **This is the measurement they
deferred**: every tracked file, against `git cat-file -p HEAD:<path>`.

**Measured 2026-09-16 on this worktree: 2,165 tracked blobs, and exactly three
disagree with their blob** —

    build-windows-portable.ps1   +80 bytes   (80 CRLF)
    launch-windows.ps1          +174 bytes  (174 CRLF)
    update_windows.bat           +59 bytes   (59 CRLF)

— and all three are **declared**. `.gitattributes` says `*.ps1 text eol=crlf`
and `*.bat text eol=crlf`, because those are run by PowerShell and cmd. Strip
the carriage returns and each reproduces its blob hash exactly. So the answer
to *"three files or three hundred"* is: **three, all of them on purpose, and
none outside `static/lib/` that is not**. That narrows `B360`'s cause to
`git apply` on minified single-line files plus the missing `-text`, and makes
the residual risk a merge-procedure question rather than a checker.

What is worth keeping is the rule, because the failure mode is silence. This
test compares **raw bytes** to the index, applying only the end-of-line
conversion `.gitattributes` declares for that path — so a declared CRLF file
passes and an undeclared drift fails, whatever `git status` says.

Files git already reports as modified are excluded: an agent's uncommitted work
is not drift, it is work. What this looks for is the file git thinks is clean
and is not.
"""
import hashlib
import subprocess
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parent.parent


def _git(*args: str) -> str:
    return subprocess.run(["git", *args], cwd=str(ROOT), capture_output=True,
                          text=True, check=True).stdout


def _index() -> dict:
    """`path -> blob oid` from the index, which is what `git status` compares to."""
    out = {}
    for line in _git("ls-files", "-s").splitlines():
        meta, _, path = line.partition("\t")
        parts = meta.split()
        if len(parts) >= 2 and parts[0] != "160000":  # skip submodules
            out[path] = parts[1]
    return out


def _reported_dirty() -> set:
    dirty = set()
    for line in _git("status", "--porcelain", "-z").split("\0"):
        if len(line) > 3:
            dirty.add(line[3:])
    return dirty


def _declared_eol(paths) -> dict:
    """`path -> 'crlf' | 'lf' | 'unset'`, straight from `git check-attr`."""
    if not paths:
        return {}
    proc = subprocess.run(["git", "check-attr", "--stdin", "-z", "eol"],
                          cwd=str(ROOT), input="\0".join(paths),
                          capture_output=True, text=True, check=True)
    fields = proc.stdout.split("\0")
    out = {}
    for i in range(0, len(fields) - 2, 3):
        out[fields[i]] = fields[i + 2]
    return out


def _blob_id(data: bytes) -> str:
    return hashlib.sha1(b"blob %d\0" % len(data) + data).hexdigest()


@pytest.fixture(scope="module")
def survey():
    index = _index()
    dirty = _reported_dirty()
    clean = [p for p in index if p not in dirty]
    eol = _declared_eol(clean)
    drifted, declared_crlf = [], []
    for path in clean:
        full = ROOT / path
        try:
            raw = full.read_bytes()
        except (OSError, ValueError):
            continue
        if _blob_id(raw) == index[path]:
            continue
        if eol.get(path) == "crlf" and _blob_id(raw.replace(b"\r\n", b"\n")) == index[path]:
            declared_crlf.append(path)
            continue
        drifted.append((path, len(raw)))
    return {"index": index, "clean": clean, "drifted": drifted,
            "declared_crlf": declared_crlf}


def test_the_survey_actually_surveyed_the_tree():
    """A census that scans nothing reports nothing, which is the failure mode
    `B360` was caught by rather than the one it was looking for."""
    index = _index()
    assert len(index) > 1500, f"only {len(index)} tracked blobs — this is not the tree"


def test_no_file_git_calls_clean_disagrees_with_its_blob(survey):
    """The `B360` class, tree-wide.

    `git status` cannot see this: it compares through the same end-of-line and
    filter machinery that produced the difference, so a CRLF-translated file
    round-trips to its own blob and reports clean. Hashing the bytes on disk is
    the only thing that does not.
    """
    drifted = survey["drifted"]
    assert not drifted, (
        "these files differ from their git blob while `git status` reports them "
        "clean, and it is not a declared end-of-line conversion:\n  "
        + "\n  ".join(f"{p} ({n:,} bytes on disk)" for p, n in drifted)
        + "\n\nThe working tree is the Docker build context (B360, B362).")


def test_the_only_declared_conversions_are_the_windows_scripts(survey):
    """`.gitattributes` may convert, and this records which paths do.

    Held as a description rather than a rule: if a new extension starts
    converting, this fails and somebody decides on purpose whether it should —
    which is exactly the decision `static/lib/**` never got.
    """
    unexpected = [p for p in survey["declared_crlf"]
                  if not p.endswith((".ps1", ".bat", ".cmd"))]
    assert not unexpected, (
        f"{unexpected} are checked out with CRLF by `.gitattributes`. Only the "
        f"Windows-native scripts were. Decide whether that is intended (B361).")


def test_static_lib_carries_the_attribute_that_kept_it_from_converting(survey):
    """`B362`'s fix, asserted where a future `.gitattributes` edit meets it.

    Not a text search of `.gitattributes` — `git check-attr` is what git itself
    resolves, which is the thing that matters and the thing a reordered or
    negated rule changes.
    """
    vendored = [p for p in survey["index"] if p.startswith("static/lib/")][:40]
    assert vendored, "static/lib/ has no tracked files — check the path"
    proc = subprocess.run(["git", "check-attr", "--stdin", "-z", "text"],
                          cwd=str(ROOT), input="\0".join(vendored),
                          capture_output=True, text=True, check=True)
    fields = proc.stdout.split("\0")
    for i in range(0, len(fields) - 2, 3):
        assert fields[i + 2] == "unset", (
            f"{fields[i]} resolves `text: {fields[i + 2]}`. `static/lib/**` needs "
            f"`-text` or a Windows checkout rewrites every vendored bundle's line "
            f"endings and the image is built from bytes this repo does not have "
            f"(B362).")
