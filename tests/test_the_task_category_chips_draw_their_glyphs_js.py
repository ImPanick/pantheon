# SPDX-License-Identifier: AGPL-3.0-or-later
"""`B610` — the Tasks window's category chips draw the glyph each category has.

**Measured before this file:** `_CATEGORY_ICONS` in `static/js/tasks.js` — a
glyph per category, eleven of them — was read by nothing in the product; its
one reader was `tests/harness/forge_labels.js`, checking the category names
agree across the wire, so the constant's only consumer was the check that it
agreed with something (`Law 13` with a green tick). The category chips
(`_renderTaskChips`) were text-only, beside the document library's chips,
which carry their icons.

Now each category's chip draws its glyph before its name, and "all" stays bare;
what a chip says (its text) is unchanged. Driven (`Law 20`): the real Tasks
window rendered under node from a served task list and the served palette, in
the parsing DOM shim of `tests/test_one_task_form_in_two_places_js.py`.
"""
from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))

from test_one_task_form_in_two_places_js import _case, sandbox  # noqa: E402,F401

_PALETTE = {
    "actions": [
        {"name": "tidy_documents", "description": "Tidy documents", "category": "Documents",
         "icon": "file", "model_backed": False, "admin_only": False, "params": []},
        {"name": "consolidate_memory", "description": "Tidy memory", "category": "Brain",
         "icon": "brain", "model_backed": True, "admin_only": False, "params": []},
    ],
    "categories": ["Forge", "Other", "Documents", "Brain"],
}


def _task(task_id, **kw):
    return {"id": task_id, "name": task_id, "status": "active", "trigger_type": "webhook",
            "edges": [], "run_count": 0, **kw}


def test_each_category_chip_draws_its_glyph_and_all_stays_bare(sandbox):
    tasks = [_task("docs", task_type="action", action="tidy_documents"),
             _task("mem", task_type="action", action="consolidate_memory"),
             _task("brief", task_type="llm", prompt="Summarise.")]
    out = _case(sandbox, {"tasks": tasks, "actions": _PALETTE}, """
        const { _fetchActions } = await import('./tasks/taskFields.js');
        await _fetchActions();
        await __t._fetchTasks();
        const modal = document.body.appendChild(new Node('div'));
        modal.setAttribute('id', 'tasks-modal');
        const body = modal.appendChild(new Node('div'));
        body.className = 'modal-body';
        __t._renderMainView();
        await tick();
        const chips = body.querySelector('#tasks-filter-chips').querySelectorAll('.memory-cat-chip');
        console.log(JSON.stringify(chips.map((c) => ({
          text: c.textContent,
          // The chip's own markup, when it holds a drawn glyph.
          glyph: c.querySelector('svg') ? c.innerHTML : null,
        }))));
    """)
    by_text = {c["text"]: c["glyph"] for c in out}
    assert set(by_text) == {"all", "Other (1)", "Documents (1)", "Brain (1)"}, out
    assert by_text["all"] is None, "the 'all' chip stays bare"
    assert by_text["Documents (1)"] and 'points="14 2 14 8 20 8"' in by_text["Documents (1)"], out
    assert by_text["Brain (1)"] and "a4 4 0 0 0-4 4v2" in by_text["Brain (1)"], out
    assert by_text["Other (1)"] and '<circle cx="12" cy="12" r="3"' in by_text["Other (1)"], out
