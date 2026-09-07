# SPDX-License-Identifier: AGPL-3.0-or-later
"""Pyodide is served from this origin, and the CSP lets it actually run.

`P16-07`. The old arrangement was worse than it looked: `codeRunner.js` pulled
`pyodide.js` from cdn.jsdelivr.net, and the CSP that allowed the *script*
blocked the `.wasm` fetch it makes next. So the request left the machine AND the
feature failed. Fixing only the first half -- vendor the files, leave the policy
alone -- moves the failure rather than removing it, because a page with any
`script-src` cannot compile WebAssembly without `'wasm-unsafe-eval'`.

That trap is what most of these tests are about. "No CDN reference" and "Python
runs" are two claims, and it is entirely possible to pass the first while
breaking the second.
"""
import hashlib
import json
import re
import subprocess
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parent.parent
RUNNER = ROOT / "static" / "js" / "codeRunner.js"
MIDDLEWARE = ROOT / "core" / "middleware.py"
PYODIDE = ROOT / "static" / "lib" / "pyodide"

REQUIRED = ("pyodide.js", "pyodide.asm.js", "pyodide.asm.wasm",
            "python_stdlib.zip", "pyodide-lock.json")


def strip_comments(text: str, *, html: bool = False) -> str:
    """Remove comments so a note about a removed CDN is not read as a CDN load.

    Deliberately crude — it does not parse strings — which errs toward removing
    too little, and removing too little makes the tests that use it stricter
    rather than weaker.
    """
    if html:
        text = re.sub(r"<!--.*?-->", "", text, flags=re.S)
    text = re.sub(r"/\*.*?\*/", "", text, flags=re.S)
    text = re.sub(r"^\s*//.*$", "", text, flags=re.M)
    return text


def app_csp() -> str:
    """The policy served to the app, not the one served to report pages.

    Two blocks exist and they differ on purpose; asserting against 'whichever
    matched first' is how a change to one gets credited to the other.
    """
    text = MIDDLEWARE.read_text(encoding="utf-8")
    marker = "script-src 'self' 'nonce-{nonce}'"
    i = text.index(marker)
    start = text.rindex('response.headers["Content-Security-Policy"]', 0, i)
    end = text.index(")", text.index("frame-ancestors", i))
    block = text[start:end]
    # Comments explaining what the policy USED to allow name the host they no
    # longer allow. Strip them: the assertion is about the directives.
    return "\n".join(l for l in block.splitlines()
                      if not l.strip().startswith("#"))


def test_every_pyodide_file_is_vendored():
    missing = [n for n in REQUIRED if not (PYODIDE / n).is_file()]
    assert not missing, f"not vendored: {missing}"


def test_vendored_bytes_match_the_pinned_hashes():
    """The fetch script's own check, run as part of the suite.

    A vendored binary nobody re-hashes is a binary nobody would notice changing.
    """
    r = subprocess.run([sys.executable, str(ROOT / "scripts" / "fetch-pyodide.py"), "--check"],
                       cwd=ROOT, capture_output=True, text=True)
    assert r.returncode == 0, r.stdout + r.stderr


def test_manifest_records_what_is_on_disk():
    m = json.loads((PYODIDE / "MANIFEST.json").read_text(encoding="utf-8"))
    assert m["licence"] == "MPL-2.0"
    assert m["version"] == "0.27.5"
    for name in REQUIRED:
        want = m["files"][name]
        got = hashlib.sha256((PYODIDE / name).read_bytes()).hexdigest()
        assert got == want, f"{name}: manifest says {want}, disk has {got}"


def test_code_runner_references_no_cdn():
    """Both the script URL and indexURL — one is not enough.

    Pyodide resolves `pyodide.asm.wasm`, `python_stdlib.zip` and
    `pyodide-lock.json` against `indexURL`. Repointing only `script.src` leaves
    three of five files remote while every grep for 'jsdelivr' in the obvious
    place comes back clean.
    """
    code = strip_comments(RUNNER.read_text(encoding="utf-8"))
    assert "jsdelivr" not in code
    assert "cdn." not in code
    assert re.search(r"script\.src\s*=\s*['\"]/static/lib/pyodide/pyodide\.js['\"]", code)
    assert re.search(r"indexURL:\s*['\"]/static/lib/pyodide/['\"]", code)


def test_no_cdn_anywhere_in_served_frontend():
    """The whole surface, not just the file that had the problem."""
    offenders = []
    for path in list((ROOT / "static").rglob("*.js")) + list((ROOT / "static").rglob("*.html")):
        if "static/lib" in path.as_posix():
            continue  # vendored bundles carry their own upstream URLs internally
        code = strip_comments(path.read_text(encoding="utf-8", errors="replace"),
                              html=path.suffix == ".html")
        if "cdn.jsdelivr.net" in code:
            offenders.append(str(path.relative_to(ROOT)))
    assert not offenders, f"CDN loads still present: {offenders}"


def test_the_cdn_scan_actually_looks_at_code():
    """Guards the test above from passing because strip_comments ate everything.

    A comment-stripper is exactly the kind of helper that can quietly return ""
    and turn its caller into a tautology.
    """
    js = strip_comments("// cdn.jsdelivr.net\nvar a = 'cdn.jsdelivr.net';\n")
    assert "var a" in js and js.count("cdn.jsdelivr.net") == 1
    html = strip_comments("<!-- cdn.jsdelivr.net -->\n<script src=cdn.jsdelivr.net>",
                          html=True)
    assert html.count("cdn.jsdelivr.net") == 1
    real = strip_comments(RUNNER.read_text(encoding="utf-8"))
    assert "loadPyodide" in real and len(real) > 500


def test_csp_no_longer_allows_jsdelivr():
    """All three directives — it was in script-src, style-src and font-src."""
    csp = app_csp()
    assert "jsdelivr" not in csp, "the CSP still names jsDelivr"
    assert "cdn." not in csp


def test_csp_permits_webassembly():
    """Without this the vendoring is cosmetic: no request leaves, Python still
    does not run. Chrome refuses `WebAssembly.instantiate` under any
    `script-src` that lacks 'wasm-unsafe-eval'."""
    assert "'wasm-unsafe-eval'" in app_csp()


def test_csp_did_not_get_looser_while_being_tightened():
    """'wasm-unsafe-eval' is narrow. 'unsafe-eval' is not, and is the easy
    mistake — it also makes wasm work, and it re-enables eval()."""
    csp = app_csp()
    assert "'unsafe-eval'" not in csp.replace("'wasm-unsafe-eval'", "")
    assert "script-src 'self' 'nonce-" in csp
    assert "'unsafe-inline'" not in csp.split("style-src")[0]


def test_report_csp_is_untouched_and_still_has_no_wasm():
    """Report pages do not run Python. A wasm allowance there would be range
    creep from a change that had nothing to do with them."""
    text = MIDDLEWARE.read_text(encoding="utf-8")
    i = text.index("if is_report:")
    block = text[i:text.index("elif is_tool_render:", i)]
    assert "wasm-unsafe-eval" not in block
    assert "jsdelivr" not in block


def test_failure_message_names_the_fix():
    """Vendored means a missing file, not a network problem. Nobody guesses
    `scripts/fetch-pyodide.py` from 'Failed to load Pyodide'."""
    src = RUNNER.read_text(encoding="utf-8")
    assert "fetch-pyodide.py" in src
    assert "Failed to load Pyodide" not in src


def test_no_packages_were_vendored_by_accident():
    """The runtime and the stdlib. Not 250 wheels.

    `full/` is hundreds of MB and `codeRunner.js` never calls `loadPackage`, so
    nothing beyond these five was ever being fetched.
    """
    on_disk = {p.name for p in PYODIDE.iterdir() if p.is_file()}
    assert on_disk == set(REQUIRED) | {"MANIFEST.json"}, sorted(on_disk)
    assert not (PYODIDE / "numpy").exists()
    total = sum((PYODIDE / n).stat().st_size for n in REQUIRED)
    assert total < 20 * 1024 * 1024, f"{total:,} bytes — a package set got in"


def test_fetch_script_verifies_before_it_writes():
    """The archive is checked against the registry's own hash before tarfile
    opens it. Verifying after extraction verifies nothing: extraction is the
    part that parses attacker-controlled bytes."""
    src = (ROOT / "scripts" / "fetch-pyodide.py").read_text(encoding="utf-8")
    integrity_at = src.index("dist.integrity" if "dist.integrity" in src else "integrity")
    open_at = src.index("tarfile.open")
    assert integrity_at < open_at, "integrity check must precede tarfile.open"
    write_at = src.index("write_bytes")
    assert open_at < write_at
    assert "shutil.rmtree" in src  # a partial directory is the worse failure


def test_licence_paperwork_shipped_with_the_bytes():
    assert (ROOT / "licenses" / "Pyodide-MPL-2.0.txt").is_file()
    credits = (ROOT / "CREDITS.md").read_text(encoding="utf-8")
    assert "static/lib/pyodide" in credits
    assert "MPL-2.0" in credits
    # and the checker agrees, which is the part that keeps agreeing later
    r = subprocess.run([sys.executable, str(ROOT / ".pantheon" / "check-licences.py"), "--quiet"],
                       cwd=ROOT, capture_output=True, text=True)
    assert r.returncode == 0, r.stdout


def test_cdn_section_of_credits_is_empty_and_says_so():
    """The claim 'we removed the CDN loads' needs somewhere to be falsified."""
    credits = (ROOT / "CREDITS.md").read_text(encoding="utf-8")
    i = credits.index("## Loaded at runtime from a CDN")
    section = credits[i:credits.index("\n## ", i + 1)]
    assert "Nothing" in section
    assert "jsdelivr.net" not in section.replace("cdn.jsdelivr.net` allowance", "")


def test_manifest_is_written_with_lf_on_every_platform():
    """`write_text` translates \\n to os.linesep, so the same script produced a
    different MANIFEST.json on Windows than on Linux — 16 bytes apart.

    It went unnoticed because `.gitattributes` normalises text in the index,
    which is git covering for the script rather than the script being correct.
    This file's entire job is recording exact bytes.
    """
    raw = (PYODIDE / "MANIFEST.json").read_bytes()
    assert b"\r\n" not in raw
    src = (ROOT / "scripts" / "fetch-pyodide.py").read_text(encoding="utf-8")
    assert 'newline="\\n"' in src
    assert "MANIFEST.json\").write_text(" not in src
