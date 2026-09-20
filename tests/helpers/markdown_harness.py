# SPDX-License-Identifier: AGPL-3.0-or-later
r"""`B882` — the Python spelling of the one `markdown.js` loader.

The loader itself is `tests/helpers/markdownHarness.mjs`, and it is JavaScript
because what it does is JavaScript: read `static/js/markdown.js`, replace its
relative imports with the modules they name, and `import()` the result from a
`data:` URL. A Python transcription of that would be the row again in a second
language.

**The part that made this a row rather than a refactor** is that the helper has
to be reachable from two kinds of caller. `tests/streaming/*.test.mjs` runs
under node's own test runner and simply `import`s it. The three Python tests
build a script and run it with `node --input-type=module -e`, where a *relative*
specifier has no base to resolve against — which is the same
`ERR_UNSUPPORTED_RESOLVE_REQUEST` the four copies existed to dodge. The answer
is an absolute `file://` URL, which resolves from anywhere, computed here once:

    from tests.helpers.markdown_harness import harness_import

    script = harness_import("importMarkdown") + '''
        …the caller's own DOM stub…
        const mod = await importMarkdown();
    '''

One implementation, two spellings of the same `import`. Adding an import to
`static/js/markdown.js` now requires no edit to any test file;
`tests/test_one_markdown_harness.py` proves it by adding one.
"""
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]

#: The one loader. An absolute `file://` URL because `node --input-type=module
#: -e` has no base URL to resolve a relative specifier against.
HARNESS_MJS = ROOT / "tests" / "helpers" / "markdownHarness.mjs"
HARNESS_URL = HARNESS_MJS.as_uri()


def harness_import(*names: str) -> str:
    """An `import { … } from '<file url>';` line for a node `-e` script.

    Names available: `importMarkdown`, `installMarkdownDom`, `loadMarkdown`,
    `bundle`, `bundleUrl`, `stripExports`, `importStatements`, `REPO`,
    `MARKDOWN_JS`.
    """
    assert names, "name at least one export"
    return "import { %s } from '%s';\n" % (", ".join(names), HARNESS_URL)
