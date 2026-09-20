# SPDX-License-Identifier: AGPL-3.0-or-later
r"""`B874` — one `esc` stub for the node sandboxes, lifted from the shipped one.

Eleven test files sandbox a `static/js` module under node and hand it a stub
`ui.js`, because the real one imports six others. Every one of them wrote its
own `esc`. Measured 2026-09-19 at `HEAD`, before this module existed:

  * **Four did not escape, or did not escape enough.**
    `test_context_meter_js.py:159`, `test_trust_ladder_js.py:318` and
    `test_tasks_activity_sources_js.py:43` answered `esc` with
    `(s) => String(s == null ? '' : s)` — the identity — and
    `test_trust_ladder_js.py:809` escaped `&`, `<` and `>` and left `"` and
    `'`, which is the exact shape of the defect `B866` found in the product.
  * **Seven hand-wrote the canonical five**, correctly, and each was a copy to
    drift.

**Why a non-escaping stub is worse than a non-escaping escaper.** It makes a
test that asserts escaping pass. `B611` — two escapers in `static/js/tasks.js`,
one of them wrong in exactly the attributes the file interpolates into — went a
fortnight unnoticed, and `tests/test_tasks_activity_sources_js.py` was green the
whole time *because its stub returned its input*: `tasks.js` happened to keep
its own `.replace` calls, so the output looked escaped no matter what the stub
did, and the day a builder started leaning on `uiModule.esc` the test would have
kept passing while the page broke. A stub that lies about the thing under test
is not a weaker test, it is a test pointing the wrong way.

The fix is not "write the five characters carefully". It is the same answer
`B866` gave the product: **there is one escaper and everybody uses it.** The
sandbox cannot import `static/js/ui.js`, so the sandbox gets the shipped
implementation as *text*, read out of `static/js/util/escapeHtml.js` at test
time by `tests/helpers/js_source.py`. Change the escaper and every sandbox
changes with it; delete a character from it and eleven files go red.

    from tests.helpers.esc_stub import ui_default_stub

    _UI_STUB = ui_default_stub("showToast: () => {}, showError: () => {},")

`tests/test_one_html_escaper_js.py` asserts that what this module produces is
byte-identical to what the product ships, and drives it against the same
hostile input as the real one.
"""
from pathlib import Path

from tests.helpers.js_source import js_binding, js_function

ROOT = Path(__file__).resolve().parents[2]

#: The canonical escaper, since `B866` moved it out of `ui.js` so that modules
#: which cannot afford `ui.js`'s six imports still get the real one.
ESCAPE_HTML_JS = ROOT / "static" / "js" / "util" / "escapeHtml.js"


def esc_source(name: str = "esc") -> str:
    """`ESC_MAP` and `esc`, as shipped, as JavaScript text.

    Read from the module rather than restated. `name` renames the function for
    a sandbox that wants it called something else; the table keeps its name
    because the body refers to it.
    """
    src = ESCAPE_HTML_JS.read_text(encoding="utf-8")
    table = js_binding(src, "ESC_MAP")
    body = js_function(src, "export function esc")
    return f"{table};\nfunction {name}(s) {body}\n"


def ui_default_stub(members: str = "", *, before: str = "",
                    exports: str = "") -> str:
    """A stub `ui.js` module whose default export carries the shipped `esc`.

    `members` is pasted into the default-export object after `esc`; `before`
    goes above the declarations (a `const` the members close over); `exports`
    goes below (named exports such as the recorded `toasts`/`errors` arrays
    several of these sandboxes read back).
    """
    lines = []
    if before:
        lines.append(before.strip("\n"))
    lines.append(esc_source().rstrip("\n"))
    if exports:
        lines.append(exports.strip("\n"))
    body = "  esc,"
    if members.strip():
        body += "\n  " + members.strip("\n").strip()
    lines.append("export default {\n%s\n};" % body)
    return "\n" + "\n".join(lines) + "\n"
