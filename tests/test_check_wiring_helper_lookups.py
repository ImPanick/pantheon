# SPDX-License-Identifier: AGPL-3.0-or-later
"""The wiring checker has to see the lookups this codebase actually writes.

For most of this project's life it did not. It matched literal
`getElementById('x')` only — and `static/js/settings.js`, `static/app.js` and
`static/js/admin.js` reach for elements through a one-line helper (`byId`, `el`)
at ~925 call sites against ~1,100 direct ones. **Nearly half the wiring in the
product was outside the measurement**, and the ratchet stood at `--max 9` over a
real backlog of 124. `VERIFY-2026-08-27.md` recorded the gap at the time
("2 ✔ literal-`getElementById`; 125 helper-aware") and the checker was never
changed, which is how five dead `set-carddav-*` ids sat in `settings.js` — a
loader filling nothing and a click handler on a button with no markup.

So these tests do not assert the checker passes on the real tree; that proves
nothing and would break on every legitimate change. They build a tiny tree with
a known answer and assert the checker gets it right, including the two false
positives that made the count untrustworthy before they were handled.
"""
import shutil
import subprocess
import sys
from pathlib import Path

import pytest

CHECKER = Path(__file__).resolve().parent.parent / ".pantheon" / "check-wiring.py"


def _tree(tmp_path: Path, files: dict) -> Path:
    """A git repo with `.pantheon/check-wiring.py` and the given files, so the
    checker's own `ROOT = __file__/../..` and `git ls-files` both resolve."""
    root = tmp_path / "repo"
    (root / ".pantheon").mkdir(parents=True)
    shutil.copy(CHECKER, root / ".pantheon" / "check-wiring.py")
    for rel, text in files.items():
        p = root / rel
        p.parent.mkdir(parents=True, exist_ok=True)
        p.write_text(text, encoding="utf-8")
    subprocess.run(["git", "init", "-q"], cwd=root, check=True)
    subprocess.run(["git", "add", "-A"], cwd=root, check=True)
    return root


def _run(root: Path, *args):
    return subprocess.run(
        [sys.executable, str(root / ".pantheon" / "check-wiring.py"), *args],
        capture_output=True, text=True, cwd=root)


def _unresolved(out: str) -> int:
    for line in out.splitlines():
        if "UNRESOLVED" in line:
            return int(line.split("UNRESOLVED")[1].strip())
    raise AssertionError(f"no UNRESOLVED line in:\n{out}")


def test_a_helper_lookup_with_no_markup_is_reported(tmp_path):
    """The defect in one file. `byId('ghost-button')` is a lookup for markup
    that does not exist, and before blind spot 4 the checker read this tree as
    perfectly wired."""
    root = _tree(tmp_path, {
        "static/index.html": '<div id="real-thing"></div>',
        "static/js/a.js": "byId('real-thing'); byId('ghost-button');",
    })
    r = _run(root)
    assert _unresolved(r.stdout) == 1
    assert "ghost-button" in r.stdout


def test_all_three_helper_names_are_seen(tmp_path):
    """`ui.el`, `admin.el` and `settings/dom.byId` are each
    `return document.getElementById(id)` and nothing else, so all three count."""
    root = _tree(tmp_path, {
        "static/index.html": "<div></div>",
        "static/js/a.js": ("getElementById('ghost-one');"
                           "el('ghost-two');"
                           "byId('ghost-three');"),
    })
    r = _run(root)
    assert _unresolved(r.stdout) == 3


def test_a_computed_helper_lookup_is_not_swept_in(tmp_path):
    """`el(someVar)` is an indirect lookup, handled by its own strict rule. If
    the helper pattern matched a bare identifier it would resurrect the
    511-false-positive version this checker was tuned away from."""
    root = _tree(tmp_path, {
        "static/index.html": "<div></div>",
        "static/js/a.js": ("const currentPanelId = 'x';"
                           "el(currentPanelId); byId(whicheverTabIsOpen);"),
    })
    assert _unresolved(_run(root).stdout) == 0, (
        "identifier names here are deliberately longer than the checker's own "
        "len > 3 floor — a one-character variable is filtered out by length and "
        "would hide a pattern that had stopped requiring quotes"
    )


def test_an_id_built_by_concatenation_is_not_a_false_positive(tmp_path):
    """`'<div id="row-' + i + '">'` creates `row-0`, but the literal `row-0`
    never appears in the source. A `made` entry ending in a separator is a
    prefix, not an id — without that rule this tree reported one dead id."""
    root = _tree(tmp_path, {
        "static/index.html": "<div></div>",
        "static/js/a.js": ("container.innerHTML = '<div id=\"row-' + i + '\"></div>';"
                           "el('row-0');"),
    })
    assert _unresolved(_run(root).stdout) == 0


def test_an_id_built_by_interpolation_is_not_a_false_positive(tmp_path):
    root = _tree(tmp_path, {
        "static/index.html": "<div></div>",
        "static/js/a.js": 'x.innerHTML = `<div id="row-${i}"></div>`; el("row-7");',
    })
    assert _unresolved(_run(root).stdout) == 0


def test_a_short_prefix_cannot_whitelist_the_whole_product(tmp_path):
    """The prefix rule is length-gated on purpose: a stray `id="a-"` must not
    make every id beginning `a-` resolve. Without the gate this is the way a
    ratchet quietly stops measuring."""
    root = _tree(tmp_path, {
        "static/index.html": "<div></div>",
        "static/js/a.js": ("x.innerHTML = '<div id=\"a-' + i + '\"></div>';"
                           "el('a-genuinely-dead-id');"),
    })
    assert _unresolved(_run(root).stdout) == 1


def test_the_max_budget_actually_fails(tmp_path):
    """A ratchet that reports and exits 0 is a log line, not a ratchet."""
    root = _tree(tmp_path, {
        "static/index.html": "<div></div>",
        "static/js/a.js": "el('ghost-one'); el('ghost-two');",
    })
    assert _run(root, "--max", "2").returncode == 0
    assert _run(root, "--max", "1").returncode != 0


def test_the_real_tree_is_measured_helper_aware(tmp_path):
    """A floor on the real repository, not a ceiling — `--max` is the ceiling.
    If a future edit narrows the scan back to literal `getElementById`, the
    lookup count collapses by roughly half and this goes red rather than the
    number quietly improving."""
    r = subprocess.run([sys.executable, str(CHECKER), "--max", "99999"],
                       capture_output=True, text=True, cwd=CHECKER.parent.parent)
    line = next(l for l in r.stdout.splitlines() if "lookups" in l)
    lookups = int(line.split("lookups")[1].split("·")[0].strip())
    assert lookups > 1200, (
        f"only {lookups} lookups found — the helper-aware scan has been narrowed"
    )
