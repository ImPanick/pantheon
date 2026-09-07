# SPDX-License-Identifier: AGPL-3.0-or-later
"""The licence paperwork matches what is actually on disk.

OpenMoji's artwork shipped for months under CC BY-SA 4.0, attributed in no file
in this repository, and nothing noticed. The gap was not a missing rule -- it was
that no rule compared the tree against CREDITS.md. `.pantheon/check-licences.py`
is that comparison; these tests are what keep the comparison honest, because a
checker that cannot fail is the same as no checker.

Each mutation test breaks exactly one thing in a temporary copy of the repo and
asserts the checker notices. If a rule is ever weakened into a tautology, the
test for it goes red.
"""
import shutil
import subprocess
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parent.parent
CHECKER = ROOT / ".pantheon" / "check-licences.py"


def run(cwd=ROOT):
    return subprocess.run(
        [sys.executable, str(cwd / ".pantheon" / "check-licences.py"), "--quiet"],
        cwd=cwd, capture_output=True, text=True,
    )


@pytest.fixture
def repo(tmp_path):
    """A copy of the parts the checker reads, as a git repo so `git ls-files` works."""
    dst = tmp_path / "repo"
    dst.mkdir()
    for rel in ("CREDITS.md", "NOTICE", "README.md"):
        src = ROOT / rel
        if src.is_file():
            shutil.copy2(src, dst / rel)
    for rel in ("licenses", ".pantheon", "static/lib", "static/fonts",
                "static/icons", "library"):
        src = ROOT / rel
        if not src.is_dir():
            continue
        # library/ecc/skills is 286 directories of prose; the checker only ever
        # stats paths, so empty stand-ins keep the fixture fast and honest.
        (dst / rel).parent.mkdir(parents=True, exist_ok=True)
        shutil.copytree(src, dst / rel,
                        ignore=shutil.ignore_patterns("*.woff2", "*.json", "*.min.js"))
        for f in src.rglob("*"):
            if f.is_file() and f.suffix in (".woff2", ".json") or f.name.endswith(".min.js"):
                out = dst / f.relative_to(ROOT)
                out.parent.mkdir(parents=True, exist_ok=True)
                if not out.exists():
                    out.write_bytes(b"")
    subprocess.run(["git", "init", "-q"], cwd=dst, check=True)
    subprocess.run(["git", "add", "-A"], cwd=dst, check=True)
    return dst


def test_clean_tree_passes(repo):
    """The baseline. Every mutation below is measured against this passing."""
    r = run(repo)
    assert r.returncode == 0, r.stdout + r.stderr


def test_the_real_repo_passes():
    """Not the fixture -- the actual tree, as CI sees it."""
    r = run()
    assert r.returncode == 0, r.stdout + r.stderr


def test_undeclared_vendored_file_fails(repo):
    """Rule 1 -- how OpenMoji arrived, and how the next one will."""
    (repo / "static" / "lib" / "newthing.min.js").write_text("x")
    subprocess.run(["git", "add", "-A"], cwd=repo, check=True)
    r = run(repo)
    assert r.returncode == 1
    assert "UNDECLARED" in r.stdout and "newthing.min.js" in r.stdout


def test_missing_licence_text_fails(repo):
    """Rule 2 -- the text a redistributor is owed is gone."""
    (repo / "licenses" / "Mermaid-MIT-LICENSE.txt").unlink()
    subprocess.run(["git", "add", "-A"], cwd=repo, check=True)
    r = run(repo)
    assert r.returncode == 1
    assert "MISSING" in r.stdout


def test_unlinked_licence_text_fails(repo):
    """Rule 3 -- present on disk, reachable from nothing."""
    c = repo / "CREDITS.md"
    c.write_text(c.read_text().replace("licenses/node-qrcode-MIT-LICENSE.txt",
                                       "licenses/Mermaid-MIT-LICENSE.txt"))
    r = run(repo)
    assert r.returncode == 1
    assert "UNLINKED" in r.stdout


def test_orphan_licence_text_fails(repo):
    """Rule 4 -- paperwork for a thing no entry claims."""
    (repo / "licenses" / "Something-MIT.txt").write_text("orphan")
    subprocess.run(["git", "add", "-A"], cwd=repo, check=True)
    r = run(repo)
    assert r.returncode == 1
    assert "ORPHAN" in r.stdout


def test_broken_licence_link_fails(repo):
    """Rule 5 -- CREDITS.md points at a file that is not there."""
    c = repo / "CREDITS.md"
    c.write_text(c.read_text() + "\nSee [x](licenses/Does-Not-Exist.txt).\n")
    r = run(repo)
    assert r.returncode == 1
    assert "BROKEN LINK" in r.stdout


def test_copyleft_dropped_from_scope_summary_fails(repo):
    """Rule 6 -- the exact regression this audit found.

    The scope section said "the one copyleft dependency is optional" while
    CC BY-SA 4.0 artwork shipped by default two sections below it. A summary is
    read *instead of* the detail, so a summary that omits an obligation is the
    one place the omission does damage.
    """
    c = repo / "CREDITS.md"
    t = c.read_text()
    start = t.index("## Licence scope")
    end = t.index("\n## ", start + 1)
    c.write_text(t[:start] + t[start:end].replace("OpenMoji", "the emoji set") + t[end:])
    r = run(repo)
    assert r.returncode == 1
    assert "UNSUMMARISED" in r.stdout


def test_vendor_mark_credit_is_a_path_not_a_project_name(repo):
    """A project name matches incidentally; a path only matches deliberately.

    "Ollama" already appeared in CREDITS.md under *companion services*, a list
    that says outright those projects are "not distributed with this project" --
    so asserting on the bare word would have passed while the shipped mark stayed
    unattributed. The assertion is the file path for that reason.
    """
    checker = (repo / ".pantheon" / "check-licences.py").read_text()
    assert '"static/icons/ollama-mark"' in checker
    assert '"static/icons/sglang-mark"' in checker

    c = repo / "CREDITS.md"
    c.write_text(c.read_text().replace("static/icons/ollama-mark", "static/icons/x"))
    r = run(repo)
    assert r.returncode == 1
    assert "UNCREDITED" in r.stdout


def test_openmoji_is_attributed_and_still_shipped():
    """The owner asked for the emoji to stay. This asserts both halves."""
    credits = (ROOT / "CREDITS.md").read_text()
    assert "CC BY-SA 4.0" in credits
    assert (ROOT / "licenses" / "OpenMoji-CC-BY-SA-4.0.txt").is_file()
    # ... and it is still the thing the product draws with.
    assert (ROOT / "library" / "emoji" / "openmoji-black.json").is_file()
    assert (ROOT / "library" / "emoji" / "MANIFEST.json").is_file()


def test_a_bundle_shipping_undeclared_packages_fails(repo):
    """Rule 7, exercised. The fixture stubs every `.min.js` to an empty file for
    speed, so the two real bundles are invisible here — which means without this
    the rule could be deleted outright and this file would stay green. A tiny
    synthetic bundle is enough: three `node_modules/` paths is what makes a file
    a bundle, and none of these three is declared anywhere."""
    fake = repo / "static" / "lib" / "fake.bundle.min.js"
    fake.parent.mkdir(parents=True, exist_ok=True)
    fake.write_text(
        'var a="../node_modules/left-pad/index.js";'
        'var b="../node_modules/@scope/thing/lib.js";'
        'var c="../node_modules/is-odd/index.js";',
        encoding="utf-8",
    )
    subprocess.run(["git", "add", "-A"], cwd=repo, check=True)
    r = run(repo)
    assert r.returncode == 1, r.stdout + r.stderr
    out = r.stdout + r.stderr
    for pkg in ("left-pad", "@scope/thing", "is-odd"):
        assert pkg in out, (pkg, out)


def test_pnpms_store_directory_is_not_reported_as_a_package(repo):
    """`node_modules/.pnpm/<pkg>@<ver>/node_modules/<pkg>/` is how pnpm lays a
    store out, and the naive match reads `.pnpm` as a package name. Mermaid is
    built with pnpm, so this is not hypothetical."""
    fake = repo / "static" / "lib" / "pnpmish.bundle.min.js"
    fake.parent.mkdir(parents=True, exist_ok=True)
    fake.write_text(
        'var a="../node_modules/.pnpm/one@1.0.0/node_modules/one/i.js";'
        'var b="../node_modules/.pnpm/two@2.0.0/node_modules/two/i.js";'
        'var c="../node_modules/.pnpm/three@3.0.0/node_modules/three/i.js";',
        encoding="utf-8",
    )
    subprocess.run(["git", "add", "-A"], cwd=repo, check=True)
    out = run(repo).stdout + run(repo).stderr
    assert "UNBUNDLED   one" in out and "UNBUNDLED   three" in out, out
    assert ".pnpm" not in out, out
