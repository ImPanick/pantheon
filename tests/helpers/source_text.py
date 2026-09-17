# SPDX-License-Identifier: AGPL-3.0-or-later
r"""The one comment blanker, loaded from the checker that owns it.

`B290`. About twenty test files each carried their own copy of

    re.sub(r"/\*.*?\*/", "", src, flags=re.S)

followed by a `//` line substitution, and the first of those cannot tell a
comment from a string. `input.accept = 'image/*,video/*'` at
`static/js/gallery.js:1202` opens a "comment" that the next `*/` anywhere in
the file closes; measured across `static/js/**`, that substitution blanks
**7,277 lines that hold live code in 15 modules** — 1,739 of `calendar.js`,
1,724 of `notes.js`, 1,232 of `document.js`, 1,112 of `settings.js`, 1,102 of
`gallery.js`. Every census built on it was counting a smaller tree than it
claimed to measure, which is how `B83` closed on a false `Verify` with twelve
icon literals invisible to it.

There is exactly one correct implementation in this repository and it is
`strip_comments` in `.pantheon/check-specifiers.py`, written for this in `B84`
and taught about regex literals, CSS and HTML in `B290`. This module loads it
rather than reimplementing it (`Law 14`). `tests/test_one_comment_blanker.py`
fails if a new copy appears.

Use `blank(path)` when you have a file, `blank_text(text, mode)` when you have
a fragment. `mode` is `js`, `css` or `html`; `blank` picks it from the name.
"""
import importlib.util
from pathlib import Path

_ROOT = Path(__file__).resolve().parents[2]
CHECKER = _ROOT / ".pantheon" / "check-specifiers.py"


def _load():
    spec = importlib.util.spec_from_file_location("_pantheon_check_specifiers",
                                                  CHECKER)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


_impl = _load()

strip_comments = _impl.strip_comments
mode_for = _impl.mode_for


def blank_text(text: str, mode: str = "js", *, embedded: bool = True) -> str:
    """`text` with its comments replaced by spaces, newlines kept.

    Offsets and line numbers do not move, so a line number a test reports is
    the line number in the file. `embedded=False` leaves `<script>`/`<style>`
    bodies byte-identical in `html` mode — see `strip_comments`.
    """
    return strip_comments(text, mode=mode, embedded=embedded)


def blank(path, text: str = None, *, embedded: bool = True) -> str:
    """Read `path` (or blank the `text` given) in the mode its name implies."""
    path = Path(path)
    if text is None:
        text = path.read_text(encoding="utf-8", errors="replace")
    return strip_comments(text, mode=mode_for(path), embedded=embedded)
