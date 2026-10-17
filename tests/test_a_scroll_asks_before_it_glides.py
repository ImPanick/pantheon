# SPDX-License-Identifier: AGPL-3.0-or-later
"""`P1-15` — `prefers-reduced-motion` reaches the scrolls a script performs.

`P1-12` put one `!important` guard in `static/style.css` and it governs every
CSS animation and transition in the product, including the keyframes injected
into `document.head` at runtime. What it cannot touch is a behaviour named in a
*call*: `scrollIntoView({behavior: 'smooth'})` and `scrollTo({behavior:
'smooth'})` override `scroll-behavior` by design, which is the whole premise of
this row.

**Measured 2026-10-17, and the row's figures held.** 52 sites — the row said 52
— with its heaviest three exactly right: `slashCommands.js` **12**,
`document.js` **8**, `emailLibrary.js` **7**. One `element.animate()` call,
`compare/vote.js`'s confetti, exactly as the row says: the Web Animations API
is invisible to both the CSS guard and `scroll-behavior`.

**49 of the 52 import the helper that already existed.** `scrollBehavior()` in
`static/js/motion.js` returns `'auto'` or `'smooth'` and was dead code until
now, which is what the row meant by *"the fix already exists and is one
import"*.

**Three did not, and each refused for its own reason — which is the useful part
of this row.**

  * `static/style.css`'s one `scroll-behavior: smooth` needed nothing: it is
    declarative, so `P1-12`'s `scroll-behavior: auto !important` already
    outranks it. Counted by the row, fixed before the row was worked.

  * `static/login.html`'s site is in a **non-module** inline script, so it
    cannot import. The second copy of the media query that would go there is
    forbidden by `test_one_module_owns_the_media_query_string`, and rightly.

  * `static/js/cookbookSchedule.js` is the one script in the product loaded as
    a **classic** script, so an `import` in it is a runtime error — found that
    way, by `tests/test_reduced_motion_opens_every_window.py` reporting
    *"Cannot use import statement outside a module"* fourteen times.

Both of the last two scroll a thing that has **just appeared** into view — a
focused input after the on-screen keyboard covered it, a form that has just
opened. That is a correctness action, not a flourish: instantly is better, not
merely tolerable, and it is what the browser does when no `behavior` is given.
So those two sites are **removed** rather than guarded, which leaves one answer
in one place and no new mirrors (`Law 7`).

The confetti goes the same way for the opposite reason. *Animate it instantly*
would be 100 divs appearing and vanishing — worse than none — so under reduced
motion `spawnConfetti` returns before spawning anything. The whole effect is
the motion.
"""

from __future__ import annotations

import json
import re
import shutil
import subprocess
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(Path(__file__).resolve().parent))

STATIC = ROOT / "static"
MOTION = STATIC / "js" / "motion.js"

#: `behavior: 'smooth'` written as a literal. Scoped to what we ship, not to
#: `static/lib/`, which is vendored.
LITERAL = re.compile(r"behavior\s*:\s*(['\"])smooth\1")
CALL = re.compile(r"behavior\s*:\s*scrollBehavior\(\)")

#: Asking `matchMedia` about motion, which is what `P1-12` says one module
#: owns. NOT the bare string: every shipped page carries `@media
#: (prefers-reduced-motion: reduce)` in CSS and must, so matching that would
#: make the rule unsatisfiable — the first draft of this file did exactly that.
ASKS = re.compile(r"matchMedia\s*\(\s*['\"][^'\"]*prefers-reduced-motion")


def _ours():
    for path in sorted(STATIC.rglob("*")):
        if not path.is_file() or path.suffix not in {".js", ".html"}:
            continue
        rel = path.relative_to(ROOT).as_posix()
        if rel.startswith("static/lib/"):
            continue
        yield rel, path.read_text(encoding="utf-8", errors="ignore")


def _live_literals():
    """Occurrences that are not on a comment line.

    Two comments name the literal on purpose — `motion.js`'s header, which
    explains what the helper is for, and `ui.js`'s, which records that `P1-15`'s
    sweep could not see its hand-rolled lerp. A scan that counted those would
    make the rule unstateable in prose.
    """
    out = []
    for rel, text in _ours():
        for match in LITERAL.finditer(text):
            start = text.rfind("\n", 0, match.start()) + 1
            if text[start:match.start()].lstrip().startswith(("//", "*", "/*")):
                continue
            out.append((rel, text[:match.start()].count("\n") + 1))
    return out


# ── the rule ───────────────────────────────────────────────────────────────


def test_no_scroll_names_smooth_in_a_call():
    """The row's `Verify:` line, first half."""
    assert _live_literals() == [], (
        "a scroll names `smooth` in the call, which overrides "
        "`scroll-behavior: auto !important`: " + repr(_live_literals()))


def test_the_sweep_actually_landed_somewhere():
    """Non-vacuity: deleting every call site would also pass the rule above."""
    sites = {rel: len(CALL.findall(text)) for rel, text in _ours()}
    total = sum(sites.values())
    assert total >= 45, f"only {total} `scrollBehavior()` call sites"
    assert sum(1 for n in sites.values() if n) >= 15
    # The row's own three heaviest files, so a file-by-file regression shows up
    # as that file rather than as a total that still looks large enough.
    for name, expected in (("slashCommands.js", 12), ("document.js", 8),
                           ("emailLibrary.js", 7)):
        got = sites.get(f"static/js/{name}", 0)
        assert got == expected, f"{name} has {got} call sites, the row measured {expected}"


def test_every_caller_imports_the_helper_rather_than_declaring_one():
    """A local `function scrollBehavior()` would satisfy the rule above and be
    a second copy of the answer — the defect `P1-12` exists to prevent."""
    for rel, text in _ours():
        if not CALL.search(text):
            continue
        assert re.search(r"^import \{[^}]*\bscrollBehavior\b[^}]*\} from "
                         r"'\.{1,2}/motion\.js'", text, re.M), (
            f"{rel} calls scrollBehavior() without importing it from motion.js")
        assert not ASKS.search(text), (
            f"{rel} asks matchMedia about motion itself; the import is the answer")


def test_the_two_sites_that_could_not_import_were_removed_not_mirrored():
    """Both are outside a module, and neither grew a copy of the query."""
    login = (STATIC / "login.html").read_text(encoding="utf-8")
    schedule = (STATIC / "js" / "cookbookSchedule.js").read_text(encoding="utf-8")
    for name, text in (("login.html", login), ("cookbookSchedule.js", schedule)):
        assert not ASKS.search(text), (
            f"{name} asks matchMedia about motion itself — a second copy of the "
            "query, which `test_one_module_owns_the_media_query_string` forbids")
        assert not LITERAL.search(text), f"{name} still names smooth in a call"
    # And the classic script is still classic, so the reason stays true.
    index = (STATIC / "index.html").read_text(encoding="utf-8")
    tag = re.search(r"<script([^>]*)src=\"/static/js/cookbookSchedule\.js\"", index)
    assert tag, "cookbookSchedule.js is no longer loaded from index.html"
    if "type=\"module\"" in tag.group(1):
        pytest.fail("cookbookSchedule.js is a module now — it can import "
                    "scrollBehavior(), so give it the helper back")
    # A *static* import statement, at the top level where one has to be — not
    # the word, which the comment explaining this very rule contains, and which
    # the first draft of this assertion matched. `await import(...)` is fine in
    # a classic script and the file uses it twice.
    assert not re.search(r"^import\s", schedule, re.M), (
        "a static import in a classic script is `Cannot use import statement "
        "outside a module` at runtime")


def test_the_declarative_scroll_is_covered_by_the_css_guard():
    """The one `scroll-behavior: smooth` in the stylesheet, and why it is left
    alone: `P1-12`'s guard is an `!important` author declaration, so it wins."""
    css = (STATIC / "style.css").read_text(encoding="utf-8")
    assert "scroll-behavior: smooth" in css, (
        "the declarative scroll is gone; re-derive this case")
    assert "scroll-behavior: auto !important" in css, (
        "P1-12's guard no longer overrides it, so the declarative scroll is live")


# ── driven, not read ───────────────────────────────────────────────────────


@pytest.mark.skipif(not shutil.which("node"), reason="node binary not on PATH")
@pytest.mark.parametrize("reduced,expected", [(True, "auto"), (False, "smooth")])
def test_the_helper_answers_from_matchmedia(tmp_path, reduced, expected):
    """`Law 20`. The real `motion.js`, with `matchMedia` stubbed either way."""
    (tmp_path / "motion.js").write_text(MOTION.read_text(encoding="utf-8"),
                                        encoding="utf-8")
    entry = tmp_path / "case.mjs"
    entry.write_text(
        f"globalThis.window = {{ matchMedia: (q) => ({{ matches: {str(reduced).lower()} }}) }};\n"
        "const m = await import('./motion.js');\n"
        "console.log(JSON.stringify({b: m.scrollBehavior(), r: m.prefersReducedMotion()}));\n"
    )
    proc = subprocess.run(["node", str(entry)], cwd=tmp_path,
                          capture_output=True, text=True, timeout=60)
    assert proc.returncode == 0, proc.stderr
    out = json.loads([ln for ln in proc.stdout.splitlines() if ln.strip()][-1])
    assert out["b"] == expected
    assert out["r"] is reduced


@pytest.mark.skipif(not shutil.which("node"), reason="node binary not on PATH")
@pytest.mark.parametrize("reduced,pieces", [(True, 0), (False, 12)])
def test_the_confetti_spawns_nothing_under_reduced_motion(tmp_path, reduced, pieces):
    """The one `element.animate()` in the product, driven through the real
    function rather than grepped for a guard — because a guard in the wrong
    place greps the same (`Law 20`)."""
    from test_tool_effect_surfaces_js import _DOM

    (tmp_path / "dom.js").write_text(_DOM)
    (tmp_path / "motion.js").write_text(MOTION.read_text(encoding="utf-8"),
                                        encoding="utf-8")
    source = (STATIC / "js" / "compare" / "vote.js").read_text(encoding="utf-8")
    # Only `spawnConfetti` and its one import are under test; the rest of the
    # module reaches storage, state and the scoreboard.
    body = source[source.index("/** Spawn confetti particles from a point. */"):
                  source.index("export { _saveVote")]
    (tmp_path / "confetti.mjs").write_text(
        "import { prefersReducedMotion } from './motion.js';\n" + body
        + "\nexport { spawnConfetti };\n", encoding="utf-8")
    entry = tmp_path / "case.mjs"
    entry.write_text(
        "import { installDom } from './dom.js';\n"
        "const document = installDom();\n"
        f"globalThis.window.matchMedia = () => ({{ matches: {str(reduced).lower()} }});\n"
        "let animated = 0;\n"
        "const made = [];\n"
        "const create = document.createElement.bind(document);\n"
        "document.createElement = (tag) => {\n"
        "  const el = create(tag);\n"
        "  el.animate = () => { animated += 1; return { finished: Promise.resolve() }; };\n"
        "  el.remove = () => {};\n"
        "  made.push(el);\n"
        "  return el;\n"
        "};\n"
        "globalThis.setTimeout = () => 0;\n"
        "const { spawnConfetti } = await import('./confetti.mjs');\n"
        "spawnConfetti(10, 10, 12);\n"
        "console.log(JSON.stringify({ animated, made: made.length }));\n"
    )
    proc = subprocess.run(["node", str(entry)], cwd=tmp_path,
                          capture_output=True, text=True, timeout=60)
    assert proc.returncode == 0, proc.stderr
    out = json.loads([ln for ln in proc.stdout.splitlines() if ln.strip()][-1])
    assert out["animated"] == pieces, out
    assert out["made"] == pieces, (
        "under reduced motion the pieces must not be created either — a "
        "teleporting burst of 100 divs is worse than none")
