# SPDX-License-Identifier: AGPL-3.0-or-later
"""`B1994`. A research report the server did not delete was taken off the screen anyway.

The Deep Research panel's card Delete sent `DELETE /api/research/{id}` and
never read the answer. A refusal (401 once the sign-in lapsed, 403 with Deep
research switched off, 404, 500) or a request that never arrived counted as a
success: the card left, `jobs.removeJob` wrote the id into
`pantheon-research-dismissed` so the panel never drew that report again, and
the report was still on disk and in the Library, after a confirm that said it
was permanently removed. The Library's Research tab did the same with its card
menu's Delete and with its bulk delete until the next load, and a dropped
request left the faded cards on the grid.

Now the panel's card leaves only after a 2xx, and otherwise the panel says why
and keeps the report. The Library's two deletes read every outcome with
`_researchTidyOutcomes`, the reader `P9-10` gave the research Tidy, so only the
reports the server deleted leave the grid; the rest come back, stay selected,
and `_researchTidyReport` says what happened.

Ported from upstream Odysseus c1f959ae (#7043), which fixed the panel's card
and its history select mode. Pantheon has no history select mode; the Library
half is Pantheon's own.

Driven (`Law 20`) under node: the card's Delete listener cut out of
`panel.js` with the panel functions it calls and the panel's own import of
`ui.js`, which resolves to a stub that records what the panel said (no page
global stands in for it, so a panel that stopped importing `ui.js` fails
here), against the real `jobs.js`; the Library's two deletes cut out of
`documentLibrary.js` and run in the destructive-preview sandbox with the real
`_readError`, `_researchTidyOutcomes` and `_researchTidyReport`.
"""
from __future__ import annotations

import json
import re
import shutil
import subprocess
from pathlib import Path

import pytest

from test_destructive_preview_js import DOCLIB_JS, _research, ui_sandbox  # noqa: E402,F401  (`ui_sandbox` is a fixture)
from tests.helpers.js_source import js_code, js_definition, js_function

ROOT = Path(__file__).resolve().parents[1]
PANEL_JS = ROOT / "static" / "js" / "research" / "panel.js"
JOBS_JS = ROOT / "static" / "js" / "research" / "jobs.js"

pytestmark = pytest.mark.skipif(not shutil.which("node"), reason="node binary not on PATH")

REFUSALS = [401, 403, 404, 500, "throw"]

#: How `panel.js` imports `ui.js`, for the case to import it the same way.
UI_IMPORT = re.compile(r"^import\s+\w+\s+from\s+'\.\./ui\.js';", re.M)

#: What `../ui.js` resolves to beside the case: the one call the listener makes.
UI_STUB = """
export const shown = [];
export default { showError: (message) => { shown.push(String(message)); } };
"""


# ── the research panel ──────────────────────────────────────────────────────

def _panel_delete_listener() -> str:
    """The card's Delete listener as it ships, after the panel's import of
    `ui.js` and each panel function the listener calls."""
    panel = PANEL_JS.read_text(encoding="utf-8")
    body = js_function(panel, "card.querySelector('[data-action=\"delete\"]').addEventListener")
    helpers = [m.group(0) for m in UI_IMPORT.finditer(panel)]
    for name in dict.fromkeys(re.findall(r"\b(_[A-Za-z]\w*)\(", js_code(body))):
        found = re.search(rf"^(?:async )?function {name}\(", panel, re.M)
        if found:
            helpers.append(js_definition(panel, found.start()))
    return "\n".join(helpers) + f"\nconst onDelete = async (e) => {body};\n"


_PANEL_CASE = r"""
import { shown as errors } from '../ui.js';   // what the panel said, as the stub heard it
const store = {};
globalThis.localStorage = {
  getItem: (k) => (k in store ? store[k] : null),
  setItem: (k, v) => { store[k] = String(v); },
};
globalThis.document = { visibilityState: 'visible', addEventListener() {} };
globalThis.window = globalThis;
window.styledConfirm = async () => true;
const answers = __ANSWERS__;   // the server's answer to each press of Delete
let answer = null;
const deletes = [];
const onDisk = new Set(['r1']);
globalThis.fetch = async (url, opts = {}) => {
  if (opts.method === 'DELETE') {
    deletes.push({ url: String(url), credentials: opts.credentials });
    if (answer === 'throw') throw new TypeError('Failed to fetch');
    const ok = answer >= 200 && answer < 300;
    if (ok) onDisk.delete(String(url).split('/').pop());
    return { ok, status: answer, statusText: ok ? 'OK' : 'Refused', json: async () => ({}) };
  }
  // The panel's past reports are the Library's, as after a reload.
  const rows = [...onDisk].map((id) => ({ id, query: 'ferry times to the island', status: 'done', source_count: 3 }));
  return { ok: true, status: 200, json: async () => ({ research: rows, total: rows.length }) };
};
const jobs = await import('./jobs.js');
await jobs.refreshLibrary({ force: true });
const job = jobs.getJobs().find((j) => j.id === 'r1');
const card = { style: {} };
const _apiBase = '';
__LISTENER__
const presses = [];
for (answer of answers) {
  await onDelete({ stopPropagation() {} });
  await new Promise((r) => setTimeout(r, 400));   // the card's exit takes 320 ms
  const afterDelete = jobs.getJobs().map((j) => j.id);
  await jobs.refreshLibrary({ force: true });     // the panel's next look at the Library
  presses.push({
    errors: [...errors], afterDelete,
    cardFaded: card.style.opacity === '0',
    afterNextSync: jobs.getJobs().map((j) => j.id),
    dismissed: JSON.parse(store['pantheon-research-dismissed'] || '[]'),
  });
}
console.log(JSON.stringify({ deletes, presses }));
"""


def _delete_from_the_panel(tmp_path: Path, answers: list) -> dict:
    box = tmp_path / "box"
    (box / "research").mkdir(parents=True)
    shutil.copy(JOBS_JS, box / "research" / "jobs.js")
    (box / "modalManager.js").write_text("export function setBackgroundWork() {}\n", encoding="utf-8")
    (box / "ui.js").write_text(UI_STUB, encoding="utf-8")
    case = _PANEL_CASE.replace("__ANSWERS__", json.dumps(answers))
    (box / "research" / "case.mjs").write_text(case.replace("__LISTENER__", _panel_delete_listener()),
                                               encoding="utf-8")
    proc = subprocess.run(["node", "research/case.mjs"], cwd=box, capture_output=True, text=True,
                          timeout=60)
    assert proc.returncode == 0, proc.stderr
    return json.loads(proc.stdout.strip().splitlines()[-1])


@pytest.mark.parametrize("answer", REFUSALS)
def test_a_report_the_server_kept_stays_on_the_research_panel(tmp_path, answer):
    out = _delete_from_the_panel(tmp_path, [answer, 200])
    assert out["deletes"] == [{"url": "/api/research/r1", "credentials": "same-origin"}] * 2
    kept, deleted = out["presses"]
    assert kept["dismissed"] == [], "a report still on disk was hidden from the panel for good"
    assert kept["afterDelete"] == ["r1"] and kept["afterNextSync"] == ["r1"]
    assert not kept["cardFaded"], "the card left as if the report were gone"
    assert len(kept["errors"]) == 1, kept["errors"]
    said = kept["errors"][0]
    assert said.startswith("Could not delete this research report") and "still in the Library" in said
    assert (str(answer) if answer != "throw" else "Failed to fetch") in said, said
    # Delete pressed again, and this time the server deletes it: now the card leaves.
    assert deleted["errors"] == kept["errors"]
    assert deleted["cardFaded"]
    assert deleted["afterDelete"] == [] and deleted["afterNextSync"] == []
    assert deleted["dismissed"] == ["r1"]


# ── the Library's Research tab ──────────────────────────────────────────────

_GRID = """
    const errors = [];
    uiModule.showError = (m) => errors.push(String(m));
    window.styledConfirm = async () => true;
    let drawn = 0;
    const _renderResearchGrid = () => { drawn += 1; };
    const _updateResearchCount = () => {};
    const grid = document.body.appendChild(new Node('div'));
    grid.setAttribute('id', 'doclib-research-grid');
    const cards = {};
    for (const r of _researchItems) {
      const card = grid.appendChild(new Node('div'));
      card.className = 'doclib-research-card';
      card.dataset.researchId = r.id;
      cards[r.id] = card;
    }
    const bar = document.body.appendChild(new Node('div'));
    bar.setAttribute('id', 'doclib-research-bulk');
    let threw = null;
"""


def _library_action(name: str) -> str:
    """One of the Research tab's two deletes, as it ships."""
    source = DOCLIB_JS.read_text(encoding="utf-8")
    if name == "card":
        menu = js_function(source, "grid.querySelectorAll('.doclib-research-delete').forEach")
        return js_function(menu, "{ label: 'Delete', danger: true, action: async () =>")
    return js_function(source, "document.getElementById('doclib-research-bulk-delete')?.addEventListener")


def _delete_from_the_library(sandbox, name: str, presses: list, selected=()) -> dict:
    """Presses one delete once for each entry of `presses`: the server's verdict
    on each report that press asks it to delete."""
    script = f"""
        let _researchItems = [{{ id: 'a' }}, {{ id: 'b' }}, {{ id: 'c' }}, {{ id: 'kept' }}];
        let _researchSelectMode = {json.dumps(bool(selected))};
        const _researchSelected = new Set({json.dumps(list(selected))});
        {_GRID}
        const rid = 'a';
        const btn = {{ closest: () => cards[rid] }};
        const run = async () => {_library_action(name)};
        const presses = [];
        for (const verdicts of {json.dumps(presses)}) {{
          globalThis.__DELETE__ = verdicts;
          threw = null;
          try {{ await run(); }} catch (err) {{ threw = String((err && err.message) || err); }}
          presses.push({{
            items: _researchItems.map((r) => r.id),
            selected: [..._researchSelected],
            selectMode: _researchSelectMode,
            barHidden: bar.classList.contains('hidden'),
            cardA: {{ opacity: cards.a.style.opacity, transform: cards.a.style.transform }},
            drawn, errors: [...errors], threw,
          }});
        }}
        console.log(JSON.stringify({{ deletes: calls.filter((c) => c.startsWith('DELETE ')), presses }}));
    """
    return _research(sandbox, script)


@pytest.mark.parametrize("verdict", [False, "throw"], ids=["refused", "unanswered"])
def test_a_library_card_the_server_kept_comes_back_and_says_why(ui_sandbox, verdict):
    out = _delete_from_the_library(ui_sandbox, "card", [{"a": verdict}, {}])
    assert out["deletes"] == ["DELETE /api/research/a"] * 2
    kept, deleted = out["presses"]
    assert kept["threw"] is None, kept["threw"]
    assert kept["items"] == ["a", "b", "c", "kept"] and kept["drawn"] == 0
    assert kept["cardA"] == {"opacity": "", "transform": ""}, "the card stayed faded out"
    assert len(kept["errors"]) == 1, kept["errors"]
    said = kept["errors"][0]
    assert said.startswith("Could not delete this research report — ")
    assert ("row is locked" if verdict is False else "network down") in said, said
    # Delete chosen again, and this time the server deletes it: now the card leaves.
    assert deleted["threw"] is None and deleted["errors"] == kept["errors"]
    assert deleted["items"] == ["b", "c", "kept"] and deleted["drawn"] == 1


def test_a_bulk_delete_takes_off_only_what_the_server_deleted(ui_sandbox):
    out = _delete_from_the_library(ui_sandbox, "bulk", [{"b": False, "c": "throw"}, {}],
                                   selected=("a", "b", "c"))
    first, again = out["presses"]
    assert first["threw"] is None, first["threw"]
    assert first["items"] == ["b", "c", "kept"]
    assert sorted(first["selected"]) == ["b", "c"], "what failed stays selected, to press Delete again"
    assert first["selectMode"] is True and first["barHidden"] is False
    assert len(first["errors"]) == 1, first["errors"]
    assert first["errors"][0].startswith("Deleted 1; 2 could not be deleted — "), first["errors"][0]
    # Delete pressed again, and this time the server deletes the rest: select mode ends.
    assert again["threw"] is None and again["errors"] == first["errors"]
    assert again["items"] == ["kept"]
    assert again["selected"] == [] and again["selectMode"] is False and again["barHidden"] is True
    assert sorted(out["deletes"]) == sorted(f"DELETE /api/research/{i}" for i in "abcbc")
