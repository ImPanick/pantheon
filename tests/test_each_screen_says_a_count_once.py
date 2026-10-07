# SPDX-License-Identifier: AGPL-3.0-or-later
"""`B-NEW-5` (P23 round 2, `fx2-doors`) — a screen says a count once.

`P23-00`'s fourth sentence — *no screen says the same thing twice* — failed on
the merged tree (`a936b5c`, the acceptance drive's `s4-*` shots). Measured
there, at 1440 and 390, dark and light:

  * **Skills** — *All skills 8* in the library column and *SKILLS 8* on the
    list's section head;
  * **Tasks** — the tab *Tasks 19* and the first chip *all (19)*;
  * **Library** — *Documents 17 documents* beside the heading and the chip
    *all (17)* under it;
  * **Settings → Agent Tools** — the Agent card read its two fields back
    beneath them: *Unlimited tool calls · 20 steps/message*;
  * **Settings → Workstation** and **Workbench → Automations** — in
    `tests/test_the_workstation_is_admin_controlled.py` and
    `tests/test_the_automations_room_js.py`, beside the cases that already
    drive those screens.

The rule is the voice guide's third (Doc 2 § 5): the tab or the chip carries
the number, the header is bare, and a narrowed list says "3 of 17" — the
pattern `P23-02` gave the Skills header. Each function is cut out of its
module (`tests/helpers/js_source`) and run under node (`Law 20`).
"""
from __future__ import annotations

import json
import shutil
import subprocess
from pathlib import Path

import pytest

from tests.helpers.esc_stub import esc_source
from tests.helpers.js_source import js_function

ROOT = Path(__file__).resolve().parents[1]
JS = ROOT / "static" / "js"

pytestmark = pytest.mark.skipif(not shutil.which("node"), reason="node binary not on PATH")


def _body(rel: str, signature: str) -> str:
    return js_function((JS / rel).read_text(encoding="utf-8"), signature)


def _node(tmp_path: Path, script: str) -> dict:
    entry = tmp_path / "case.mjs"
    entry.write_text(script, encoding="utf-8")
    proc = subprocess.run(["node", str(entry)], capture_output=True, text=True, timeout=30)
    assert proc.returncode == 0, proc.stderr
    return json.loads(proc.stdout.strip().splitlines()[-1])


# A button the way `document.createElement` hands one back, as far as these
# functions use it: attributes, a dataset, a class, text or markup.
_ELEMENT = """
const mk = (tag) => ({
  tagName: String(tag).toUpperCase(), attrs: {}, dataset: {}, style: {}, className: '',
  innerHTML: '', textContent: '', listeners: {},
  setAttribute(k, v) { this.attrs[k] = String(v); }, getAttribute(k) { return this.attrs[k]; },
  addEventListener(t, f) { this.listeners[t] = f; },
});
"""


def test_the_skills_section_head_leaves_the_count_to_the_library_column(tmp_path):
    out = _node(tmp_path, _ELEMENT + """
        // `skills.js`' `esc` hands off to `uiModule.esc`: the shipped escaper,
        // under that name (`tests/helpers/esc_stub.py`).
        %s
        const document = { createElement: mk };
        const chevronIcon = () => '<svg></svg>';
        const _collapsedSections = new Set(['builtin']);
        const _saveCollapsedSections = () => {};
        const _applySectionCollapse = () => {};
        function _skillsSectionHeader(container, sectionId, title, count) %s
        console.log(JSON.stringify({
          user: _skillsSectionHeader({}, 'user', 'Skills', null).innerHTML,
          builtin: _skillsSectionHeader({}, 'builtin', 'Built-in capabilities', 60).innerHTML,
        }));
    """ % (esc_source("esc"), _body("skills.js", "function _skillsSectionHeader(")))
    assert "skills-section-count" not in out["user"], out["user"]
    assert "<span>Skills</span>" in out["user"]
    # Nothing else counts the built-in capabilities, and that section ships folded.
    assert '<span class="skills-section-count">60</span>' in out["builtin"]

    # The list's own call. `renderSkillsList` cannot be driven with a user card
    # in it (the shim stores `innerHTML` unparsed — see
    # `test_builtin_capabilities_are_admin_only.py`), so this is `Law 20`
    # option 2: the call, inside the function that makes it.
    body = _body("skills.js", "function renderSkillsList(")
    assert "_mkSectionHeader('user', 'Skills', null)" in body
    assert "_mkSectionHeader('builtin', 'Built-in capabilities', builtinCards.length)" in body


def test_the_tasks_all_chip_leaves_the_count_to_the_tab(tmp_path):
    out = _node(tmp_path, _ELEMENT + """
        const bar = { kids: [], style: {}, set innerHTML(v) { this.kids = []; }, appendChild(c) { this.kids.push(c); return c; } };
        const document = { getElementById: (id) => (id === 'tasks-filter-chips' ? bar : null), createElement: mk };
        let _tasks = [{ c: 'email' }, { c: 'email' }, { c: 'calendar' }];
        let _taskFilter = null;
        const _categoryFor = (t) => t.c;
        const _categoryOrder = () => ['calendar', 'email'];
        const _renderList = () => {};
        function _renderTaskChips() %s
        _renderTaskChips();
        console.log(JSON.stringify({ chips: bar.kids.map((c) => c.textContent) }));
    """ % _body("tasks.js", "function _renderTaskChips("))
    assert out["chips"] == ["all", "calendar (1)", "email (2)"]


def test_the_library_heading_is_bare_until_something_narrows_the_list(tmp_path):
    out = _node(tmp_path, _ELEMENT + """
        let _libraryLanguages = { markdown: 10, csv: 4, text: 2, html: 1 };
        let _libraryTotal = 17, _librarySearch = '', _libraryActiveLanguage = null;
        let _libraryFolderView = { kind: 'all' }, _librarySelectMode = false;
        const stats = { textContent: 'stale' };
        const wrap = { kids: [], querySelectorAll: () => [], appendChild(c) { this.kids.push(c); return c; } };
        const document = {
          getElementById: (id) => ({ 'doclib-stats': stats, 'doclib-chips': wrap })[id] || null,
          createElement: mk,
        };
        const libraryFetch = () => {};
        function libraryRenderStats() %s
        function libraryRenderLangChips() %s
        libraryRenderStats();
        libraryRenderLangChips();
        const bare = stats.textContent, chips = wrap.kids.map((c) => c.textContent);
        _librarySearch = 'invoice'; _libraryTotal = 3;
        libraryRenderStats();
        const searched = stats.textContent;
        _librarySearch = ''; _libraryFolderView = { kind: 'folder', path: 'Finance' }; _libraryTotal = 2;
        libraryRenderStats();
        const folder = stats.textContent;
        _libraryLanguages = {}; _libraryTotal = 0; _librarySearch = 'invoice';
        libraryRenderStats();
        console.log(JSON.stringify({ bare, chips, searched, folder, empty: stats.textContent }));
    """ % (_body("documentLibrary.js", "function libraryRenderStats("),
           _body("documentLibrary.js", "function libraryRenderLangChips(")))
    assert out["bare"] == "", "the heading said the total the 'all' chip says"
    assert out["chips"][0] == "all (17)"
    assert out["searched"] == "3 of 17"
    assert out["folder"] == "2 of 17"
    assert out["empty"] == "", "an empty Library searched said '0 of 0'"


def test_the_agent_card_says_saved_and_does_not_read_its_fields_back(tmp_path):
    out = _node(tmp_path, """
        const field = (value) => ({
          value, checked: false, listeners: {},
          addEventListener(t, f) { this.listeners[t] = f; }, fire(t) { return this.listeners[t](); },
        });
        const msg = { textContent: 'stale', style: {} };
        const fields = {
          'set-agentMaxTools': field(''), 'set-agentMaxRounds': field(''), 'set-agentVerifier': field(''),
          'set-localMaxTokens': field(''), 'set-agentMsg': msg,
        };
        const el = (id) => fields[id] || null;
        const fetch = async () => ({ json: async () => ({ agent_max_tool_calls: 0, agent_max_rounds: 20 }) });
        const posted = [];
        const _postSettings = async (body) => { posted.push(body); };
        const _notSaved = () => 'Not saved.';
        const setTimeout = () => 0;
        globalThis.document = { dispatchEvent() {} };
        globalThis.CustomEvent = class { constructor(type) { this.type = type; } };
        async function initAgentSettings() %s
        await initAgentSettings();
        const onLoad = msg.textContent;
        fields['set-agentMaxRounds'].value = '30';
        await fields['set-agentMaxRounds'].fire('change');
        console.log(JSON.stringify({ onLoad, onSave: msg.textContent, posted }));
    """ % _body("settings.js", "async function initAgentSettings("))
    assert out["onLoad"] == "", f"the card read its fields back on load: {out['onLoad']!r}"
    assert out["onSave"] == "Saved"
    assert out["posted"] and out["posted"][0]["agent_max_rounds"] == 30
