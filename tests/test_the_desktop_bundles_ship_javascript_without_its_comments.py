# SPDX-License-Identifier: AGPL-3.0-or-later
"""`B1666` — the desktop bundles ship Pantheon's JavaScript without its comments.

The owner's call (`D-2026-10-29-03` §4, "Strip them too"): the desktop builds
ship JavaScript through the same stripper the image does (`B1591`,
`scripts/strip-js-comments.mjs`). Measured on the tree before this row:

  * `Pantheon.spec` listed `('static', 'static')`, so every module went into
    the bundle as the repository has it, every comment included;
  * `build-windows-portable.ps1` did not build from the spec at all: it passed
    its own `--add-data` list (also `static;static`, and without the spec's
    `docker/build-realesrgan-wheels.sh`, `B373`) and named `launcher.py`, which
    makes PyInstaller write a new `Pantheon.spec` over the committed one;
  * `build-macos-app.sh` ships no JavaScript: its `.app` is a launcher that
    starts the server from the checkout it was built in (`INSTALL_DIR`, the
    repository), so what a browser fetches is that checkout's `static/`, the
    same files a source install serves.

Now the spec runs the stripper into `build/js-without-comments/` and lists
every file under `static/` from there when it was stripped and from the tree
when not, and the Windows script installs acorn from the lock and builds from
the spec. PyInstaller is not installed here, so the spec is run the way
PyInstaller runs it — executed with `SPECPATH` set, its build classes stood in
for — and what it hands `Analysis` is what is checked: every module it ships is
held token for token to the source by acorn on its own, with no comment left
but a notice (`tests/test_shipped_javascript_goes_out_without_its_comments.py`'s
own check, the stage's). The macOS script is run whole, `hdiutil` stood in for.
"""
from __future__ import annotations

import json
import os
import re
import shutil
import subprocess
from pathlib import Path

import pytest

from tests.test_shipped_javascript_goes_out_without_its_comments import (  # noqa: E402
    ACORN, NODE, _SKIP, _TOKENS, _node, _own_modules)

ROOT = Path(__file__).resolve().parents[1]
needs_acorn = pytest.mark.skipif(_SKIP is not None, reason=_SKIP or "")


class _Stub:
    """One of PyInstaller's build classes: it keeps what it was given."""

    made: list = []

    def __init__(self, *args, **kwargs):
        self.args, self.kwargs = args, kwargs
        self.pure, self.scripts, self.binaries, self.datas = [], [], [], []
        _Stub.made.append(self)


def _run_spec(root: Path, env_path: str | None = None) -> dict:
    """Execute `Pantheon.spec` as PyInstaller does — `SPECPATH` is its
    directory — with `root` standing as that directory. Returns the keyword
    arguments it gave `Analysis`."""
    _Stub.made = []
    namespace = {"SPECPATH": str(root), "__file__": str(root / "Pantheon.spec"),
                 **{name: type(name, (_Stub,), {}) for name in ("Analysis", "PYZ", "EXE", "COLLECT")}}
    code = compile((ROOT / "Pantheon.spec").read_text(encoding="utf-8"), "Pantheon.spec", "exec")
    saved = os.environ.get("PATH")
    if env_path is not None:
        os.environ["PATH"] = env_path
    try:
        exec(code, namespace)  # noqa: S102 — the repository's own build file
    finally:
        if env_path is not None:
            os.environ["PATH"] = saved or ""
    (analysis,) = [m for m in _Stub.made if type(m).__name__ == "Analysis"]
    return analysis.kwargs


def _root_like_the_repository(tmp: Path, static: Path | None = None) -> Path:
    """A directory standing as the repository's root for the spec: its
    `static/`, `scripts/` and `node_modules/` the real ones (read, never
    written), so the stripper's output lands under `tmp`, not in the tree."""
    root = tmp / "root"
    root.mkdir()
    (root / "static").symlink_to(static or ROOT / "static", target_is_directory=True)
    for name in ("scripts", "node_modules"):
        if (ROOT / name).exists():
            (root / name).symlink_to(ROOT / name, target_is_directory=True)
    return root


@pytest.fixture(scope="module")
def bundled(tmp_path_factory):
    if _SKIP:
        pytest.skip(_SKIP)
    tmp = tmp_path_factory.mktemp("b1666")
    root = _root_like_the_repository(tmp)
    kwargs = _run_spec(root)
    shipped = {}
    for source, dest in kwargs["datas"]:
        if Path(dest).parts[:1] == ("static",):
            rel = f"{Path(dest).as_posix()}/{Path(source).name}"
            assert rel not in shipped, f"{rel} is listed twice"
            shipped[rel] = Path(source)
    return {"tmp": tmp, "root": root, "kwargs": kwargs, "shipped": shipped,
            "out": root / "build" / "js-without-comments"}


# ── Pantheon.spec ───────────────────────────────────────────────────────────

def test_the_spec_ships_every_file_under_static_once(bundled):
    """Nothing the bundle carried before is lost by listing the files one by
    one instead of the directory."""
    tree = sorted(Path(dirpath, name).relative_to(ROOT).as_posix()
                  for dirpath, _, names in os.walk(ROOT / "static") for name in names)
    assert sorted(bundled["shipped"]) == tree
    others = [d for _, d in bundled["kwargs"]["datas"] if Path(d).parts[:1] != ("static",)]
    for kept in ("scripts", "licenses", "docker"):
        assert kept in others, (kept, others)


def test_each_of_pantheons_modules_is_shipped_from_the_strippers_output(bundled):
    ours = _own_modules()
    assert len(ours) > 200
    shipped = bundled["shipped"]
    out = bundled["out"]
    from_tree = [rel for rel in ours if shipped[rel] != out / rel]
    assert from_tree == [], f"shipped as the repository has them: {from_tree[:10]}"
    # And nothing it did not write — `static/lib/` above all — is taken from it.
    vendored = [rel for rel, src in shipped.items() if rel not in ours and out in src.parents]
    assert vendored == []
    assert shipped["static/lib/jspdf.umd.min.js"] == bundled["root"] / "static/lib/jspdf.umd.min.js"


def test_every_module_the_bundle_ships_is_the_same_program_with_no_comment_but_a_notice(bundled):
    """The row's `Verify:` — the stage's token-stream check, on the bundle's
    files: every token where it was, under the same goal; no comment left but
    a notice; no line moved."""
    pairs = [[rel, str(ROOT / rel), str(bundled["shipped"][rel])] for rel in _own_modules()]
    (bundled["tmp"] / "pairs.json").write_text(json.dumps(pairs))
    got = json.loads(_node(_TOKENS, ACORN / "dist" / "acorn.js", bundled["tmp"] / "pairs.json",
                           tmp=bundled["tmp"], name="tokens.cjs"))
    assert got["problems"] == [], got["problems"][:10]
    assert got["files"] == len(pairs)
    assert got["before"] > 25_000 and got["after"] <= len(pairs) + 10, got


def test_the_strippers_output_is_never_written_over_the_source(bundled):
    assert bundled["out"].is_dir()
    assert ROOT / "static" not in bundled["out"].parents


@needs_acorn
def test_the_spec_stops_with_a_sentence_when_the_stripper_refuses_a_file(tmp_path, capfd):
    """A module the stripper cannot prove stops the build, as it stops the
    image's — the bundle never ships it half-done."""
    static = tmp_path / "fake-static"
    (static / "js").mkdir(parents=True)
    (static / "js" / "fine.js").write_text("// a comment\nexport const a = 1;\n")
    (static / "js" / "broken.js").write_text("export const = ;\n")
    root = _root_like_the_repository(tmp_path, static=static)
    with pytest.raises(SystemExit) as stopped:
        _run_spec(root)
    assert "strip-js-comments.mjs stopped the build" in str(stopped.value)
    assert "static/js/broken.js" in capfd.readouterr().err


def test_the_spec_stops_with_a_sentence_without_node(tmp_path):
    """No Node.js, no stripper: the build says what to install rather than
    shipping the commented files."""
    root = _root_like_the_repository(tmp_path)
    empty = tmp_path / "no-node"
    empty.mkdir()
    with pytest.raises(SystemExit) as stopped:
        _run_spec(root, env_path=str(empty))
    said = str(stopped.value)
    assert "Install Node.js" in said and "npm ci --omit=dev --ignore-scripts" in said, said


# ── build-windows-portable.ps1 ──────────────────────────────────────────────

def _ps1_commands() -> list[str]:
    """The script's lines that run, not its comments: `#` lines and the
    `<# … #>` block dropped (there is no PowerShell here to run it)."""
    text = (ROOT / "build-windows-portable.ps1").read_text(encoding="utf-8")
    text = re.sub(r"<#.*?#>", "", text, flags=re.S)
    return [ln.strip() for ln in text.splitlines() if ln.strip() and not ln.strip().startswith("#")]


def test_the_windows_build_builds_from_the_spec():
    """One list of what is in the bundle. Naming `launcher.py` with its own
    `--add-data` list made PyInstaller write a new `Pantheon.spec` over the
    committed one, and that list had already lost `B373`'s file."""
    lines = _ps1_commands()
    runs = [ln for ln in lines if "PyInstaller" in ln and ln.startswith("&")]
    assert len(runs) == 1, runs
    assert runs[0].split()[-1] == "Pantheon.spec" and "launcher.py" not in runs[0], runs[0]
    assert not [ln for ln in lines if "--add-data" in ln or "--icon" in ln], (
        "a second list of what the bundle holds, beside Pantheon.spec's")


def test_the_windows_build_installs_acorn_from_the_lock_first():
    lines = _ps1_commands()
    npm = [i for i, ln in enumerate(lines)
           if ln.startswith("&") and "npm" in ln.lower() and re.search(r"\sci\s", ln)]
    build = [i for i, ln in enumerate(lines) if "PyInstaller" in ln and ln.startswith("&")]
    assert len(npm) == 1 and npm[0] < build[0], (npm, build)
    assert "--omit=dev" in lines[npm[0]] and "--ignore-scripts" in lines[npm[0]], lines[npm[0]]
    refusal = [ln for ln in lines if ln.startswith("Fail ") and "Node.js" in ln]
    assert refusal, "no sentence for a machine without Node.js"


# ── build-macos-app.sh ──────────────────────────────────────────────────────

@pytest.mark.skipif(not shutil.which("bash"), reason="bash not on PATH")
def test_the_macos_app_carries_no_javascript_and_serves_its_checkout(tmp_path):
    """The macOS build is a launcher, not a bundle: its `.app` holds a script,
    a plist and an icon, and starts the server from the checkout it was built
    in — whose `static/` is the repository's, as a source install's is. So
    there is nothing in it to strip; this fails, saying so, the day it starts
    carrying `static/`."""
    checkout = tmp_path / "checkout"
    (checkout / "docs" / "brand").mkdir(parents=True)
    shutil.copy2(ROOT / "build-macos-app.sh", checkout / "build-macos-app.sh")
    shutil.copy2(ROOT / "docs/brand/pantheon.icns", checkout / "docs/brand/pantheon.icns")
    stubs = tmp_path / "bin"
    stubs.mkdir()
    (stubs / "hdiutil").write_text("#!/bin/sh\nexit 0\n")
    (stubs / "hdiutil").chmod(0o755)
    run = subprocess.run(["bash", str(checkout / "build-macos-app.sh")], cwd=checkout,
                         env={**os.environ, "PATH": f"{stubs}:{os.environ.get('PATH', '')}",
                              "TMPDIR": str(tmp_path)},
                         capture_output=True, text=True, timeout=60)
    assert run.returncode == 0, run.stderr
    app = checkout / "dist" / "Pantheon.app"
    files = sorted(p.relative_to(app).as_posix() for p in app.rglob("*") if p.is_file())
    assert files == ["Contents/Info.plist", "Contents/MacOS/Pantheon",
                     "Contents/Resources/pantheon.icns"], files
    assert not [f for f in files if f.endswith((".js", ".mjs"))]
    launcher = (app / "Contents/MacOS/Pantheon").read_text(encoding="utf-8")
    assert f'INSTALL_DIR="{checkout}"' in launcher
    assert 'cd "$INSTALL_DIR"' in launcher


# ── The stripper, reached through a symlink ─────────────────────────────────

@needs_acorn
def test_the_stripper_runs_when_reached_through_a_symlink(tmp_path):
    """Found doing this row: `node <a symlink to strip-js-comments.mjs>` —
    a symlinked checkout, macOS's `/tmp` — exited 0 having written nothing,
    because node runs the module at its real path and the script compared
    that with the path it was given. A build reads that as success, and the
    spec's fallback would have shipped every file as the repository has it."""
    static = tmp_path / "app" / "static" / "js"
    static.mkdir(parents=True)
    (static / "a.js").write_text("// gone\nexport const a = 1; /* gone too */\n")
    (tmp_path / "linked").symlink_to(ROOT / "scripts", target_is_directory=True)
    run = subprocess.run([NODE, str(tmp_path / "linked" / "strip-js-comments.mjs"),
                          str(tmp_path / "app"), str(tmp_path / "out")],
                         capture_output=True, text=True, timeout=60)
    assert run.returncode == 0, run.stderr
    assert "1 modules" in run.stdout, run.stdout
    assert (tmp_path / "out/static/js/a.js").read_text() == "\nexport const a = 1;\n"
