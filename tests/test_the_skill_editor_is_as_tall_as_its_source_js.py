# SPDX-License-Identifier: AGPL-3.0-or-later
"""`B1973`. The raw SKILL.md editor opened two lines tall, whatever the file.

Edit on a skill card (the footer's, or the one in the ⋯ menu) swaps the card's
SKILL.md for a `<textarea class="skill-md-editor">`, and nothing gave that
textarea a height, so it kept a browser's default of two rows. On a phone the
card is pinned to the screen and the editor fills it, but on a desktop the card
and its preview size to their content, so a 200-line skill was edited through a
two-line slot. The built-in capability editor is the same textarea on the same
card, and did the same.

Now the editor has as many rows as its text has lines, and never fewer than
the two it had. The bounds were already there: the page's textarea rule stops
any textarea at thirty lines and scrolls inside it, and the card keeps its Save
footer in view.

Ported from upstream Odysseus 9a5a15e1 (#6932). Driven under node through the
real `skills.js` on the shipped markup, in the harness
`test_one_skills_module_two_places_js.py` owns. The shim's textareas are given a
browser's default of two rows, since that default is the height under test.
"""
from __future__ import annotations

import json
import shutil
import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parent))

from test_tool_effect_surfaces_js import _make_sandbox, _run  # noqa: E402
from test_one_skills_module_two_places_js import SHIM, STUBS, _markup  # noqa: E402

ROOT = Path(__file__).resolve().parents[1]
SKILLS_JS = ROOT / "static" / "js" / "skills.js"

pytestmark = pytest.mark.skipif(not shutil.which("node"), reason="node binary not on PATH")

# A browser's textarea has two rows until something says otherwise; the shim's
# has no `rows` at all.
TWO_ROWS = r"""
const _plainCreate = document.createElement;
document.createElement = (tag) => {
  const n = _plainCreate(tag);
  if (String(tag).toLowerCase() === 'textarea') n.rows = 2;
  return n;
};
"""

PREAMBLE = (
    "import { document, server, fire, tick, cards } from './shim.js';\n"
    "globalThis.addEventListener = globalThis.addEventListener || (() => {});\n"
    "globalThis.removeEventListener = globalThis.removeEventListener || (() => {});\n"
    "const LONG = Array.from({ length: 40 }, (_, i) => 'Line ' + (i + 1) + ' of the skill').join('\\n');\n"
    "const SOURCES = { 'alpha-logs': LONG, 'beta-print': 'name: beta-print',\n"
    "                  'gamma-crlf': 'one\\r\\ntwo\\r\\nthree\\r\\nfour\\r\\nfive' };\n"
    "const BUILTIN = Array.from({ length: 13 }, (_, i) => 'Rule ' + (i + 1)).join('\\n');\n"
    "server.skills.push({ name: 'gamma-crlf', description: 'windows line ends', status: 'draft',\n"
    "                     confidence: 0.8, version: '1.0.0' });\n"
    "const base = globalThis.fetch;\n"
    "globalThis.fetch = async (url, init = {}) => {\n"
    "  const u = String(url).replace('http://test.local', '');\n"
    "  const ok = (b) => ({ ok: true, status: 200, json: async () => JSON.parse(JSON.stringify(b)) });\n"
    "  const md = /^\\/api\\/skills\\/([^/]+)\\/markdown$/.exec(u);\n"
    "  if (md && (init.method || 'GET') === 'GET') return ok({ markdown: SOURCES[decodeURIComponent(md[1])] });\n"
    "  if (u === '/api/skills/builtin') return ok({ builtin: [{ name: 'read_file', description: 'Read a file',\n"
    "                                                         is_overridden: false }], count: 1 });\n"
    "  if (u === '/api/skills/builtin/read_file') return ok({ name: 'read_file', text: BUILTIN, default: BUILTIN });\n"
    "  return base(url, init);\n"
    "};\n"
    "await import('./skills.js');\n"
    "fire(document, 'DOMContentLoaded');\n"
    "await tick();\n"
    "const out = (o) => console.log(JSON.stringify(o));\n"
    "async function openFromTheMenu(name) {\n"
    "  const card = cards('skills-list').find((c) => c.dataset.skillName === name);\n"
    "  fire(card.querySelector('.skill-kebab-btn'), 'click');\n"
    "  const menu = document.body.querySelectorAll('.skill-kebab-menu').slice(-1)[0];\n"
    "  fire(menu.querySelectorAll('.skill-kebab-item').find((b) => b.textContent.trim() === 'Edit'), 'click');\n"
    "  await tick(20);\n"
    "  const ta = card.querySelector('.skill-md-editor');\n"
    "  return ta ? { rows: ta.rows, text: ta.value } : null;\n"
    "}\n"
)


@pytest.fixture(scope="module")
def box(tmp_path_factory):
    shim = SHIM.replace("__MARKUP__", json.dumps(_markup())) + TWO_ROWS
    return _make_sandbox(tmp_path_factory.mktemp("editorheight"), SKILLS_JS, shim, STUBS)


def test_the_editor_has_a_row_for_every_line_of_the_skill_and_never_fewer_than_two(box):
    o = _run(box, PREAMBLE, """
        out({ long: await openFromTheMenu('alpha-logs'), short: await openFromTheMenu('beta-print'),
              crlf: await openFromTheMenu('gamma-crlf') });
    """)
    assert o["long"]["text"].startswith("Line 1 of the skill"), "the editor did not hold the source"
    assert o["long"]["rows"] == 40, "a 40-line skill opened in a two-row editor"
    assert o["crlf"]["rows"] == 5, "Windows line ends are one line break each"
    assert o["short"]["rows"] == 2, "a one-line skill made the editor smaller than it was"


def test_the_built_in_capability_editor_has_a_row_for_every_line_too(box):
    o = _run(box, PREAMBLE, """
        const card = document.body.querySelectorAll('.skill-builtin-card')[0];
        fire(card, 'click');
        await tick(20);
        const edit = card.querySelectorAll('.doclib-card-action-btn').find((b) => b.textContent.trim() === 'Edit');
        fire(edit, 'click');
        await tick();
        const ta = card.querySelector('.skill-md-editor');
        out({ rows: ta ? ta.rows : null, text: ta ? ta.value : null });
    """)
    assert o["text"] and o["text"].startswith("Rule 1"), "the built-in editor did not hold its text"
    assert o["rows"] == 13, "a 13-line built-in capability opened in a two-row editor"
