# SPDX-License-Identifier: AGPL-3.0-or-later
"""`B1127` — every function `static/js/skills.js` declares is reached from code.

`Law 13`: a function nothing calls is not "kept", it is drift. The row named
three in `skills.js` — `_preloadVisibleMarkdown` (a background fetch of every
card's SKILL.md, reading only the window's `#skills-list`), `_isDraftsFilter`
(a one-line wrapper over `m.draftsOnly`, which its three readers read
directly) and `_showSkillSource` (a second SKILL.md editor, a modal of its own,
beside the card's in-place `.skill-md-editor` that posts to the same
`POST /{name}/markdown`). Measured across the whole module there were **four**:
`_modelShortName` too, since the audit pills say "audit" / "teacher-fixed" and
carry the full model id in their title. All four were removed, none wired.

The property is about the module's text — "is this name reached from code?" —
so the scan is of code, not of the file (`Law 20` option 2): the repository's
one JavaScript scanner (`tests/helpers/js_source.js_code`) blanks comments and
string bodies first, so a name quoted in a comment (this repo's comments quote
names constantly) or spelled inside a string is not a caller, while a call
inside a template literal's `${…}` is. An exported function may be reached from
another module, so every module under `static/js/` is read the same way — for
exported names only: a private function is reached from its own module or not
at all.
"""

from __future__ import annotations

import re
from pathlib import Path

from tests.helpers.js_source import js_code

ROOT = Path(__file__).resolve().parents[1]
SKILLS_JS = ROOT / "static" / "js" / "skills.js"

_DECLARATION = re.compile(r"(\bexport\s+(?:default\s+)?)?\b(?:async\s+)?function\s*\*?\s*([A-Za-z_$][\w$]*)\s*\(")


def _word(name: str) -> re.Pattern:
    # Not preceded by `.` either: `obj.name(` is a different binding.
    return re.compile(r"(?<![\w$.])" + re.escape(name) + r"(?![\w$])")


def _uncalled(source: str, other_modules: list) -> list:
    code = js_code(source)
    out = []
    for m in _DECLARATION.finditer(code):
        exported, name, at = bool(m.group(1)), m.group(2), m.start(2)
        if any(hit.start() != at for hit in _word(name).finditer(code)):
            continue
        # Only an exported function can be reached from another module; a
        # private one that shares its name with another module's identifier
        # (`_ghost` is a drag ghost elsewhere) is still uncalled.
        if exported and any(_word(name).search(other) for other in other_modules):
            continue
        out.append(name)
    return out


def _other_modules() -> list:
    return [js_code(p.read_text(encoding="utf-8"))
            for p in sorted((ROOT / "static" / "js").rglob("*.js")) if p != SKILLS_JS]


def test_every_function_skills_js_declares_is_reached_from_code():
    source = SKILLS_JS.read_text(encoding="utf-8")
    declared = [m.group(2) for m in _DECLARATION.finditer(js_code(source))]
    assert len(declared) > 100, "the scan found the module's functions"
    assert _uncalled(source, _other_modules()) == []


def test_the_scan_tells_a_caller_from_a_mention():
    """The scanner's own guard: a name only quoted in a comment, or spelled in
    a string, is uncalled; one called in a template literal's `${…}`, or only
    from another module, is not."""
    source = (
        "function _quoted() {}\n"
        "// _quoted() is mentioned here and nowhere else\n"
        "const s = '_quoted()';\n"
        "function _inTemplate() { return 1; }\n"
        "const t = `${_inTemplate()}`;\n"
        "export function elsewhere() {}\n"
        "function _method() {}\n"
        "obj._method();\n"
        "function _private() {}\n"
    )
    other = js_code("import { elsewhere } from './m.js'; elsewhere(); const _private = 1;")
    assert _uncalled(source, [other]) == ["_quoted", "_method", "_private"]
