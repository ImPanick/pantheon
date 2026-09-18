# SPDX-License-Identifier: AGPL-3.0-or-later
"""`B58` (absorbing `B09`) — four assets were reachable under two URLs each.

`check-specifiers.py` has enforced "one query string per module path" since
`P3-11`, at `--max 0`, and reported `FORKED 0` the whole time — because it read
four of the six places a URL is written in this tree. It had no pattern for
`<link rel="modulepreload">` and none for `static/sw.js`'s precache list, and
both defects lived exactly there.

  * `chat.js` was preloaded at `?v=20260815toolapproval4` and executed at
    `?v=20260829trustladder1`. The HTTP cache and the module map are keyed on
    the full URL, query included, so 372 KB was fetched twice on every cold
    load, both on the critical path. `git log -L` says the preload line had not
    been edited since the fork baseline while the script tag was bumped twice.
  * `admin.js`, `emailInbox.js` and `sidebar-layout.js` were precached bare and
    imported with a version. `sw.js` matches with `cache.match(e.request)` and
    no `ignoreSearch`, so those three were downloaded at install and could
    never answer a request.

These tests hold the *scope*, which is the thing that was wrong. The checker
cannot assert its own blind spots, and `--max 0` in CI proves nothing about a
place the regexes never look.
"""
import importlib.util
import re
import subprocess
import sys
from pathlib import Path

import pytest

_REPO = Path(__file__).resolve().parent.parent
_CHECKER = _REPO / ".pantheon" / "check-specifiers.py"

_spec = importlib.util.spec_from_file_location("check_specifiers", _CHECKER)
check_specifiers = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(check_specifiers)


def _hits(regex, text):
    return [m.group(1) for m in regex.finditer(text)]


def test_a_modulepreload_is_a_specifier():
    """The blind spot that hid `chat.js`. Both attribute orders, because HTML
    does not care and a regex does."""
    forward = '<link rel="modulepreload" href="/static/js/chat.js?v=abc">'
    reverse = '<link href="/static/js/chat.js?v=abc" rel="modulepreload">'
    plain = '<link rel="preload" href="/static/js/chat.js?v=abc" as="script">'
    assert _hits(check_specifiers.LINK_RE, forward) == ["/static/js/chat.js?v=abc"]
    assert _hits(check_specifiers.LINK_REV_RE, reverse) == ["/static/js/chat.js?v=abc"]
    assert _hits(check_specifiers.LINK_RE, plain) == ["/static/js/chat.js?v=abc"]


def test_a_precache_entry_is_a_specifier():
    """The blind spot that hid the three dead service-worker entries."""
    listed = "const PRECACHE = [\n  '/static/js/admin.js?v=abc',\n  '/static/js/notes.js',\n];"
    assert _hits(check_specifiers.PRECACHE_RE, listed) == [
        "/static/js/admin.js?v=abc", "/static/js/notes.js",
    ]


def test_a_stylesheet_link_is_not_mistaken_for_a_module():
    """The widened pattern must not start counting things that are not modules."""
    css = '<link rel="stylesheet" href="/static/style.css?v=abc">'
    icon = '<link rel="icon" href="/static/icons/favicon.js">'
    assert _hits(check_specifiers.LINK_RE, css) == []
    assert _hits(check_specifiers.LINK_RE, icon) == []


def test_no_module_in_this_tree_is_reachable_under_two_urls():
    """The property itself, computed rather than asserted about the source."""
    forked = {p: dict(q) for p, q in check_specifiers.scan().items() if len(q) > 1}
    assert not forked, forked


def test_the_checker_still_fails_when_something_forks():
    """`--max 0` has to still bite, or the scope widening bought nothing."""
    result = subprocess.run([sys.executable, str(_CHECKER), "--max", "0"],
                            cwd=str(_REPO), capture_output=True, text=True)
    assert result.returncode == 0, result.stdout
    assert "FORKED 0" in result.stdout


@pytest.mark.parametrize("asset", [
    "static/js/chat.js", "static/js/admin.js",
    "static/js/emailInbox.js", "static/js/sidebar-layout.js",
])
def test_the_four_that_were_forked_are_each_reached_under_one_query(asset):
    seen = check_specifiers.scan()
    assert asset in seen, f"{asset} is reached by nothing — did it get renamed?"
    assert len(seen[asset]) == 1, seen[asset]


# The two tests below exist because a mutation run walked straight past the
# first draft of this file. Patterns that exist and a tree that is clean both
# stay true if `scan()` stops CALLING the patterns — so these assert the wiring
# by naming the source each specifier has to be attributed to. Having the rule
# and reading the file are two different things, which is the whole of `B58`.

def test_scan_actually_reads_the_preload_links():
    importers = check_specifiers.scan()["static/js/chat.js"]
    (query,) = importers
    # index.html reaches chat.js twice: the <script> tag and the modulepreload.
    assert importers[query].count("static/index.html") == 2, importers


def test_scan_actually_reads_the_service_worker_precache_list():
    importers = check_specifiers.scan()["static/js/admin.js"]
    (query,) = importers
    assert "static/sw.js" in importers[query], importers


# --- `B84`: the checker was reading text, not code ---------------------------


@pytest.mark.parametrize("source,html,label", [
    ("// import './x.js?v=1';\nimport y from './y.js';", False, "line comment"),
    ("/* import './x.js?v=1'; */\nimport y from './y.js';", False, "block comment"),
    ("<!-- <script src='/static/js/x.js'></script> -->\n"
     "<script src='/static/js/y.js'></script>", True, "html comment"),
])
def test_a_sentence_about_an_import_is_not_an_import(source, html, label):
    """A docstring in `runStatus.js` explaining why a module is loaded as
    `import('./tasks.js?v=…')` was counted as a second specifier for
    `tasks.js` — a literal ellipsis reported as a forked module.

    That is `Law 20` in the checker itself. The same law bit
    `test_offline_shell_manifest.py` two days earlier, when a comment
    explaining why there is no `ignoreSearch` failed a grep for
    `ignoreSearch`. A rule about code has to read code.
    """
    stripped = check_specifiers.strip_comments(source, html=html)
    found = ([m.group(1) for m in check_specifiers.IMPORT_RE.finditer(stripped)]
             + [m.group(1) for m in check_specifiers.SCRIPT_RE.finditer(stripped)])
    assert len(found) == 1, (label, found)
    assert "x.js" not in found[0], (label, found)


@pytest.mark.parametrize("source", [
    "const u = 'https://a.example/b';\nimport y from './y.js';",
    'const u = "https://a.example/b";\nimport y from "./y.js";',
    "const t = `http://x//y`;\nimport y from './y.js';",
])
def test_a_double_slash_inside_a_string_is_not_a_comment(source):
    """The failure this guards against is silent: blanking from a `//` inside a
    URL would delete the rest of that line, and a checker that quietly stops
    looking is worse than one that over-reports.

    **The assertion is that the string SURVIVES, not that the import is still
    found.** The first draft put the URL and the import on separate lines, so
    eating the rest of the URL's line left the import untouched and a mutation
    removing string tracking walked straight past. What the rule is actually
    about is how much of the file the scanner can still see.
    """
    stripped = check_specifiers.strip_comments(source, html=False)
    assert "a.example" in stripped or "x//y" in stripped, stripped
    assert stripped.split("\n")[0] == source.split("\n")[0], (
        "the line holding the string was truncated — a // inside it was read "
        "as a comment"
    )
    found = [m.group(1) for m in check_specifiers.IMPORT_RE.finditer(stripped)]
    assert found == ["./y.js"], found


def test_an_import_after_a_url_on_the_same_line_is_still_found():
    """The same rule from the side that actually loses a specifier."""
    source = "const u = 'https://a.example/b'; import('./y.js?v=2');\n"
    stripped = check_specifiers.strip_comments(source, html=False)
    found = [m.group(1) for m in check_specifiers.IMPORT_RE.finditer(stripped)]
    assert found == ["./y.js?v=2"], (found, stripped)


def test_stripping_preserves_every_offset():
    """Comments are blanked, not deleted, so line numbers in any message the
    checker prints still point at the real line."""
    source = "// hidden\nimport y from './y.js';\n/* also\nhidden */\n"
    stripped = check_specifiers.strip_comments(source, html=False)
    assert len(stripped) == len(source)
    assert stripped.count("\n") == source.count("\n")


def test_an_escaped_quote_does_not_end_the_string_early():
    """Written as a raw string so the backslash count is unambiguous.

    An earlier draft of this case used two backslashes, which in JS is an
    escaped BACKSLASH — the string closes and what follows really is a comment.
    The stripper was right and the test was wrong, which is worth a sentence
    because it is the failure a test like this exists to avoid making.
    """
    source = r"const e = 'a\'//b'; import('./y.js?v=3');" + "\n"
    stripped = check_specifiers.strip_comments(source, html=False)
    found = [m.group(1) for m in check_specifiers.IMPORT_RE.finditer(stripped)]
    assert found == ["./y.js?v=3"], (found, stripped)


# ── the same defect, one asset type down ────────────────────────────────────

_CSS_URL = re.compile(r"""["'](/static/[^"']+\.css)(\?[^"']*)?["']""")


def _css_urls():
    """(published path -> {query strings}) for every stylesheet URL written in
    a tracked `static/` file. Same scope statement as the checker's: every
    `<link href>`, every service-worker precache entry, every dynamic
    `import`-adjacent string — excluding `static/lib/`."""
    found = {}
    for rel in check_specifiers.tracked():
        text = (_REPO / rel).read_text(encoding="utf-8")
        for path, query in _CSS_URL.findall(text):
            found.setdefault(path, {}).setdefault(query, []).append(rel)
    return found


def test_a_stylesheet_is_reachable_under_one_url_too():
    """`B630`. `check-specifiers.py` is deliberately about **modules** — its
    patterns end in `.js`, and a test above pins that a stylesheet link is not
    mistaken for one. That is correct for what it measures and it leaves
    `style.css` with two version sites and nothing holding them equal: the
    `<link>` in `index.html` and the precache entry in `static/sw.js`.

    Bumping one and not the other is silent and costs exactly what `B58` cost
    for `admin.js` — `sw.js` matches with `cache.match(e.request)` and **no**
    `ignoreSearch`, so the precached stylesheet is downloaded at install and
    can never answer a request, while the page fetches the other URL over the
    network on every cold load. Found 2026-09-18 by mutating `P5-01`'s own
    buster bump and watching nothing notice.
    """
    forked = {path: {q: files for q, files in queries.items()}
              for path, queries in _css_urls().items() if len(queries) > 1}
    assert not forked, forked


def test_the_stylesheet_scan_is_actually_finding_the_sites():
    """A scan that quietly stops matching passes the test above by being empty.
    `style.css` is written in at least the page and the service worker."""
    urls = _css_urls()
    assert "/static/style.css" in urls, sorted(urls)
    files = sorted({f for q in urls["/static/style.css"].values() for f in q})
    assert "static/index.html" in files and "static/sw.js" in files, files
