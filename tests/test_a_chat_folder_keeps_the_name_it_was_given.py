# SPDX-License-Identifier: AGPL-3.0-or-later
"""`B998` — the Library's Chats tab shows a chat folder's name as it was typed.

Found by `P21-01`: the Chats tab draws chat folders as `.memory-cat-chip`s
(`_renderChatsChips` in `static/js/documentLibrary.js`), and that class sets
`text-transform: lowercase` for the Memory tab's category chips — so a folder
named "Clients" read "clients". The class is shared, so the fix is scoped: a
folder's chip also carries `doclib-chat-folder-chip`, which keeps the case, and
the Memory tab's chips (`buildCategoryChips` in `static/js/memory.js`) keep
theirs.

Driven twice, never grepped (`Law 20`): the two real renderers, cut out with
`js_function`, run under node to show which chips carry which class; and run
again in a real Chromium against the real `static/style.css`, where
`innerText` is the text a person actually sees — text-transform applied.
"""

import json
import shutil
import subprocess
import textwrap
from pathlib import Path

import pytest

from tests.helpers.js_source import js_function
from tests.test_document_folders_js import _js, sandbox  # noqa: F401

ROOT = Path(__file__).resolve().parents[1]
DOCLIB_JS = ROOT / "static" / "js" / "documentLibrary.js"
MEMORY_JS = ROOT / "static" / "js" / "memory.js"
STYLE_CSS = ROOT / "static" / "style.css"


def _renderers() -> str:
    chats = "function _renderChatsChips() " + js_function(
        DOCLIB_JS.read_text(encoding="utf-8"), "function _renderChatsChips(")
    memory = "function buildCategoryChips() " + js_function(
        MEMORY_JS.read_text(encoding="utf-8"), "function buildCategoryChips(")
    return chats + "\n" + memory


#: The state both renderers read: three chats in two folders (one typed in
#: capitals) and one unfiled, and two memories in categories of mixed case.
_STATE = """
    const _chatsSessions = [{ folder: 'Clients' }, { folder: 'Clients' }, { folder: 'ACME Ltd' },
                            { folder: null }];
    let _chatsModelFilter = '';
    function _renderChatsGrid() {}
    const memories = [{ category: 'Fact' }, { category: 'preference' }];
    let activeCategory = 'all';
    function renderMemoryList() {}
    function updateMemoryCount() {}
"""


def test_a_chat_folder_s_chip_carries_the_class_that_keeps_its_case(sandbox):  # noqa: F811
    out = _js(sandbox, _STATE + """
        const chats = document.body.appendChild(new Node('div'));
        chats.setAttribute('id', 'doclib-chats-chips');
        const mem = document.body.appendChild(new Node('div'));
        mem.setAttribute('id', 'memory-category-filters');
        """ + _renderers() + """
        _renderChatsChips();
        buildCategoryChips();
        const read = (host) => host.childNodes.map((b) => [b.textContent, b.className]);
        console.log(JSON.stringify({ chats: read(chats), memory: read(mem) }));
    """)
    assert out["chats"] == [
        ["all (4)", "memory-cat-chip active"],
        ["ACME Ltd (1)", "memory-cat-chip doclib-chat-folder-chip"],
        ["Clients (2)", "memory-cat-chip doclib-chat-folder-chip"],
    ]
    assert [c for _t, c in out["memory"]] == [
        "memory-cat-chip active", "memory-cat-chip", "memory-cat-chip"]


# ── in a real browser, against the real stylesheet ──────────────────────────

def _chromium():
    node = shutil.which("node")
    if not node:
        return None, "node binary not on PATH"
    probe = subprocess.run(
        [node, "-e", "const { chromium } = require('playwright');"
                     "process.stdout.write(require('fs').existsSync(chromium.executablePath()) ? 'y' : '')"],
        capture_output=True, text=True, timeout=60, cwd=ROOT)
    if probe.returncode != 0 or probe.stdout != "y":
        return None, "playwright or its Chromium is not installed"
    return node, None


NODE, _SKIP = _chromium()

_SCRIPT = r"""
const { chromium } = require('playwright');
const fs = require('fs');
const css = fs.readFileSync(process.argv[2], 'utf8');
const code = fs.readFileSync(process.argv[3], 'utf8');
(async () => {
  const browser = await chromium.launch({ args: ['--no-sandbox'] });
  try {
    const page = await browser.newPage();
    await page.setContent('<!doctype html><html><head></head><body>'
      + '<div id="doclib-chats-chips" class="doclib-lang-chips"></div>'
      + '<div id="memory-category-filters" class="memory-category-filters"></div></body></html>');
    await page.addStyleTag({ content: css });
    const out = await page.evaluate((src) => {
      // Direct eval, so the cut renderers see the state declared beside them.
      return eval(src + `
        _renderChatsChips();
        buildCategoryChips();
        const read = (sel) => [...document.querySelectorAll(sel + ' button')].map((b) => ({
          seen: b.innerText, transform: getComputedStyle(b).textTransform }));
        ({ chats: read('#doclib-chats-chips'), memory: read('#memory-category-filters') });`);
    }, code);
    console.log(JSON.stringify(out));
  } finally {
    await browser.close();
  }
})();
"""


@pytest.mark.skipif(NODE is None, reason=_SKIP or "")
def test_a_person_sees_the_folder_name_they_typed_and_the_memory_tab_is_unchanged(tmp_path):
    script = tmp_path / "chips.js"
    script.write_text(_SCRIPT, encoding="utf-8")
    code = tmp_path / "renderers.js"
    code.write_text(textwrap.dedent(_STATE) + "\n" + _renderers(), encoding="utf-8")
    proc = subprocess.run([NODE, str(script), str(STYLE_CSS), str(code)],
                          capture_output=True, text=True, timeout=120, cwd=ROOT)
    assert proc.returncode == 0, proc.stderr
    out = json.loads(proc.stdout.strip().splitlines()[-1])
    assert out["chats"] == [
        {"seen": "all (4)", "transform": "lowercase"},
        {"seen": "ACME Ltd (1)", "transform": "none"},
        {"seen": "Clients (2)", "transform": "none"},
    ]
    # The Memory tab shares the class and keeps its lowercase categories.
    assert out["memory"] == [
        {"seen": "all", "transform": "lowercase"},
        {"seen": "fact", "transform": "lowercase"},
        {"seen": "preference", "transform": "lowercase"},
    ]
