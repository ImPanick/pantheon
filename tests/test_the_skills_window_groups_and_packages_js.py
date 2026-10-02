# SPDX-License-Identifier: AGPL-3.0-or-later
"""`P9-06`, `P8-49` … `P8-52`. The Skills window, driven under node.

The shipped `skills.js` functions, cut out of the file and run against the DOM
shim with `fetch` answered by the test (`Law 20`):

  * the sidebar lists the library, each package with its sections, and each
    group, with the counts the server's lists give;
  * choosing a package narrows the list to its skills, and the native tool
    capabilities — which belong to no package — leave with the rest;
  * a skill a switched-off package or group holds says so, and by what;
  * a package's switch and a group's switch send the call that decides
    injection, and nothing else;
  * an import that brought a package says so as a package and opens on it.

And the page's structure, read from the shipped markup: the window holds the
list and the import, the Brain's Skills tab is a door to it, and every id in
the window is declared once.
"""

import json
import re
import shutil
import subprocess
from pathlib import Path

import pytest

from test_a_skill_imports_from_what_skills_sh_shows import _DOM, _cut  # noqa: E402
from tests.helpers.esc_stub import esc_source  # noqa: E402

ROOT = Path(__file__).resolve().parents[1]
SKILLS_JS = ROOT / "static" / "js" / "skills.js"
INDEX = ROOT / "static" / "index.html"

pytestmark = pytest.mark.skipif(not shutil.which("node"), reason="node binary not on PATH")


# `B691`: the shim stores `innerHTML` as a string, so `renderSkillsList` cannot
# draw a skill card here — its first `header.querySelector` finds nothing. The
# sidebar is built with `createElement` and CAN be driven; the list's filter is
# a pure function of the store and is run as cut from the shipped file.
_UNITS = ("_readScope", "_makeMount", "_isBundled", "_packageOf", "_scopeNames", "_inScope", "_setScope", "_sameScope",
          "_sideHead", "_sideRow", "_renderSkillsSide", "_getFilteredSkills", "_getFilteredBuiltins",
          "_matches", "_sortSkills", "_offPill", "_skillsApi", "_switchPackage", "_switchGroup",
          "_fetchCollections")

STORE = {
    "packages": [
        {"id": "leonxlnx--taste-skill", "title": "taste-skill", "enabled": True, "mode": "full",
         "source": {"owner": "Leonxlnx", "repo": "taste-skill"},
         "sections": [{"id": "taste-skill", "title": "taste-skill", "skills": ["brandkit", "gpt-taste"]}],
         "skills": ["brandkit", "gpt-taste"]},
        {"id": "acme--agent-skills", "title": "agent-skills", "enabled": False, "mode": "full",
         "sections": [{"id": "document-skills", "title": "document-skills", "skills": ["pdf"]},
                      {"id": "example-skills", "title": "example-skills", "skills": ["frontend-design"]}],
         "skills": ["pdf", "frontend-design"]},
    ],
    "groups": [{"id": "design", "title": "Design", "enabled": False, "skills": ["brandkit", "house-style"]}],
    "off": {"brandkit": ["Design"], "pdf": ["agent-skills"], "frontend-design": ["agent-skills"]},
}
SKILLS = [
    {"name": "brandkit", "status": "draft"}, {"name": "gpt-taste", "status": "draft"},
    {"name": "pdf", "status": "draft"}, {"name": "frontend-design", "status": "draft"},
    {"name": "my-own", "status": "published"},
    {"name": "house-style", "status": "draft", "bundled": True, "source": "bundled"},
]


def _drive(tmp_path, script: str) -> dict:
    (tmp_path / "dom.js").write_text(_DOM)
    case = """
import { installDom } from './dom.js';
const document = installDom();
globalThis.document = document;
const API = '';
const writes = [];
globalThis.fetch = async (url, init) => {
  if (url.endsWith('/api/skills/collections')) return { ok: true, status: 200, json: async () => (%(store)s) };
  writes.push({ url, method: (init && init.method) || 'GET', body: init && init.body ? JSON.parse(init.body) : null });
  return { ok: true, status: 200, json: async () => ({ ok: true }) };
};
const side = document.body.appendChild(document.createElement('nav'));
side.setAttribute('id', 'skills-side');
%(esc)s
const uiModule = { showToast: () => {}, showError: (m) => { throw new Error(m); } };
const _ICON = { update: '', del: '', rename: '', group: '' };
const _SCOPE_KEY = 'skillsScope';
let skills = %(skills)s;
let builtinSkills = [{ name: 'read_file', description: 'r' }];
let _collections = { packages: [], groups: [], off: {} };
let renders = 0;
function renderSkillsList() { renders += 1; }
function updateCount() {}
function _popMenu() {}
function _newGroup() {}
async function _refreshAfterCollections() { await _fetchCollections(); _renderSkillsSide(m); }
%(defs)s
// `P22-21`. The scope, sort and filters are a mount's now — the window's,
// made by the shipped `_makeMount`, whose ids are the page's own.
const m = _makeMount(document.body);
m.sort = 'alpha';
const kids = (n) => (n && n.children) ? [...n.children] : [];
const rows = () => kids(side).filter(n => String(n.className).includes('skills-side-row'));
const rowText = (r) => kids(kids(r)[0]).map(n => n.textContent).join(' ');
const pick = (title) => {
  const r = rows().find(x => rowText(x).startsWith(title + ' '));
  if (!r) throw new Error('no row ' + title + ' in ' + rows().map(rowText).join(' | '));
  return r;
};
const shown = () => _getFilteredSkills(m).map(s => s.name);
const tick = () => new Promise((r) => setTimeout(r, 0));
await _fetchCollections();
_renderSkillsSide(m);
%(script)s
""" % {"store": json.dumps(STORE), "skills": json.dumps(SKILLS), "script": script,
       "esc": esc_source(), "defs": "\n".join(_cut(n) for n in _UNITS)}
    (tmp_path / "case.mjs").write_text(case)
    proc = subprocess.run(["node", str(tmp_path / "case.mjs")], capture_output=True, text=True, timeout=30)
    assert proc.returncode == 0, proc.stderr
    return json.loads(proc.stdout.strip().splitlines()[-1])


def test_the_sidebar_lists_the_library_the_packages_their_sections_and_the_groups(tmp_path):
    out = _drive(tmp_path, "console.log(JSON.stringify({ rows: rows().map(rowText) }));")
    assert out["rows"] == [
        "All skills 6", "Yours 1", "Built-in 1",
        "taste-skill 2", "agent-skills 2", "document-skills 1", "example-skills 1",
        "Design 2",
    ]


def test_choosing_a_package_narrows_the_list_and_the_tools_leave_with_the_rest(tmp_path):
    out = _drive(tmp_path, """
        const before = { list: shown(), builtins: _getFilteredBuiltins(m).length };
        const choose = (t) => kids(pick(t))[0].dispatchEvent({ type: 'click' });
        choose('taste-skill');
        const inPackage = shown(), builtinsAfter = _getFilteredBuiltins(m).length;
        choose('document-skills'); const inSection = shown();
        choose('Yours'); const yours = shown();
        choose('Design'); const group = shown();
        console.log(JSON.stringify({ before, inPackage, builtinsAfter, inSection, yours, group, renders,
          active: rows().filter(r => String(r.className).includes('is-active')).map(rowText) }));
    """)
    assert len(out["before"]["list"]) == 6 and out["before"]["builtins"] == 1
    assert out["inPackage"] == ["brandkit", "gpt-taste"]
    assert out["builtinsAfter"] == 0, "the native tool capabilities stayed in a package's list"
    assert out["inSection"] == ["pdf"]
    assert out["yours"] == ["my-own"], "a package's skill or a built-in one counted as the person's own"
    assert out["group"] == ["brandkit", "house-style"], "a group of a bundled skill lost it"
    assert out["active"] == ["Design 2"] and out["renders"] == 4


def test_a_skill_held_off_says_so_and_by_what(tmp_path):
    out = _drive(tmp_path, """
        console.log(JSON.stringify({
          brandkit: _offPill({ name: 'brandkit' }), pdf: _offPill({ name: 'pdf' }),
          gpt: _offPill({ name: 'gpt-taste' }),
          offRows: rows().filter(r => String(r.className).includes('is-off')).map(rowText) }));
    """)
    assert "skill-off-pill" in out["brandkit"] and "switched off with Design" in out["brandkit"]
    assert "switched off with agent-skills" in out["pdf"]
    assert out["gpt"] == ""
    assert out["offRows"] == ["agent-skills 2", "Design 2"]


def test_the_switches_send_the_call_that_decides_injection(tmp_path):
    out = _drive(tmp_path, """
        const sw = (t) => kids(kids(pick(t)).find(n => String(n.className).includes('admin-switch')))[0];
        const pkg = sw('taste-skill'); pkg.checked = false; pkg.dispatchEvent({ type: 'change' });
        await tick(); await tick();
        const grp = sw('Design'); grp.checked = true; grp.dispatchEvent({ type: 'change' });
        await tick(); await tick();
        console.log(JSON.stringify({ writes, states: [sw('taste-skill').checked, sw('Design').checked] }));
    """)
    assert out["writes"] == [
        {"url": "/api/skills/packages/leonxlnx--taste-skill", "method": "PATCH", "body": {"enabled": False}},
        {"url": "/api/skills/groups/design", "method": "PATCH", "body": {"enabled": True}},
    ]


def test_an_import_that_brought_a_package_says_so_and_opens_on_it(tmp_path):
    (tmp_path / "dom.js").write_text(_DOM)
    answer = {"ok": True, "skill": {"name": "design-taste-frontend"}, "files": 14, "notes": [],
              "package": {"id": "leonxlnx--taste-skill", "title": "taste-skill"},
              "installed": ["a", "b", "c"], "updated": ["design-taste-frontend"]}
    case = """
import { installDom } from './dom.js';
const document = installDom();
if (!Node.prototype.removeAttribute) Node.prototype.removeAttribute = function (k) { delete this.attrs[k]; };
const API = '';
const seen = { toasts: [], opened: [] };
const uiModule = { showToast: (m) => seen.toasts.push(m), showError: () => {} };
async function loadSkills() {}
function openSkill(n, opts) { seen.opened.push([n, opts || null]); }
globalThis.fetch = async () => ({ ok: true, status: 200, json: async () => (%(answer)s) });
const input = document.body.appendChild(document.createElement('input'));
input.setAttribute('id', 'skill-import-url'); input.value = 'npx skills add Leonxlnx/taste-skill --skill design-taste-frontend';
const btn = document.body.appendChild(document.createElement('button'));
btn.setAttribute('id', 'skill-import-url-btn');
const statusEl = document.body.appendChild(document.createElement('p'));
statusEl.setAttribute('id', 'skill-import-status');
%(defs)s
const m = _makeMount(document.body);
await importSkillFromUrl(m);
console.log(JSON.stringify({ ...seen, status: statusEl.textContent }));
""" % {"answer": json.dumps(answer),
       "defs": "const _SCOPE_KEY = 'skillsScope';\n" + "\n".join(
           _cut(n) for n in ("_readScope", "_makeMount", "_importStatus", "_importInFlight",
                             "importSkillFromUrl"))}
    (tmp_path / "case.mjs").write_text(case)
    proc = subprocess.run(["node", str(tmp_path / "case.mjs")], capture_output=True, text=True, timeout=30)
    assert proc.returncode == 0, proc.stderr
    out = json.loads(proc.stdout.strip().splitlines()[-1])
    assert out["status"].startswith("Imported taste-skill — 4 skills (3 new, 1 refreshed).")
    assert out["toasts"] == ["Imported taste-skill (4 skills)"]
    assert out["opened"] == [["design-taste-frontend",
                              {"scope": {"kind": "package", "id": "leonxlnx--taste-skill"}}]]


# ── the markup ──────────────────────────────────────────────────────────────

def _window(html, modal_id):
    start = html.index(f'<div id="{modal_id}"')
    end = re.compile(r'\n  <div id="[^"]+" class="modal').search(html, start).start()
    return html[start:end]


def test_the_window_holds_the_list_and_the_import_and_the_brain_holds_the_doors():
    html = INDEX.read_text(encoding="utf-8")
    skills, brain = _window(html, "skills-modal"), _window(html, "memory-modal")
    for control in ("skills-list", "skills-search", "skills-select-btn", "skills-bulk-group",
                    "skill-import-url", "skill-import-url-btn", "add-skill-btn", "skills-side",
                    "skills-enabled-header-toggle", "close-skills-modal"):
        assert f'id="{control}"' in skills, control
        assert f'id="{control}"' not in brain, f"{control} is in two windows"
    assert 'data-open-skills="browse"' in brain and 'data-open-skills="add"' in brain
    assert 'data-memory-tab="skills"' in brain, "the Brain lost the tab that opens the window"
    for control in re.findall(r'\bid="([^"]+)"', skills):
        assert html.count(f'id="{control}"') == 1, f"id {control} is declared twice"
