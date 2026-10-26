# SPDX-License-Identifier: AGPL-3.0-or-later
"""`B820` — the Brain shows how you write: read it, correct a line, delete it.

`P13-17` … `P13-20` landed the whole server half — a `kind: "style"` record in
the store, `GET /api/memory`'s `style` block (`profile`, `observed`, `needed`)
on every fetch the Brain already makes, and `PUT` / `DELETE /api/memory/{id}`
that already set `style_edited` and write the event — and `static/js/memory.js`
drew none of it but the formed record as an ordinary memory card (premise
corrected 2026-10-01 in the row). Measured on `ffaf6671`: before a profile forms
nothing in the Brain said the style was being learned; once formed it was a
card among the memories, editable as one blob, deletable through a bin whose
confirmation said *"Delete this memory?"* and nothing about the counters.

Now a *How you write* panel at the top of the list (`renderStylePanel`): before
a profile forms, *"18 of 20 messages seen"*; once formed, its lines, each
editable where it is printed and saved through the record's own `PUT`; and a
*Forget how I write* control whose confirmation says the counts go too and
learning starts over. The formed record is no longer a memory card.

Driven on the real `memory.js` under node, in the sandbox
`tests/test_the_brain_says_it_is_loading.py` builds, with a `ui.js` that
records what it is asked to confirm.

`Verify:` a cold reader opens the Brain, reads what the assistant thinks about
how they write, changes a sentence that is wrong, and deletes the lot — without
being told how.
"""
from __future__ import annotations

import json
import shutil

import pytest

from test_the_brain_says_it_is_loading import _LOADING_STUBS, _PREAMBLE  # noqa: E402
from test_the_workshop_surfaces_js import _SHIM, _index_ids, MEMORY_JS, INDEX  # noqa: E402
from test_tool_effect_surfaces_js import _make_sandbox, _run  # noqa: E402
from tests.helpers.esc_stub import ui_default_stub

pytestmark = pytest.mark.skipif(not shutil.which("node"), reason="node binary not on PATH")

_STUBS = dict(_LOADING_STUBS)
_STUBS["ui.js"] = ui_default_stub(
    "showToast: (m) => { globalThis.__said.toasts.push(String(m)); },"
    " showError: (m) => { globalThis.__said.errors.push(String(m)); },"
    " styledConfirm: async (m) => { globalThis.__said.confirms.push(String(m)); return true; },"
    " copyToClipboard: () => {}, el: (id) => document.getElementById(id),"
    " debounce: (f) => f, emptyStateIcon: () => '',",
    before="globalThis.__said = { toasts: [], errors: [], confirms: [] };")

_CASE = """
const sent = [];
const FORMED_TEXT = 'You write in short sentences.\\nYou rarely use exclamation marks.';
const RECORD = { id: 'sty', text: FORMED_TEXT, kind: 'style', category: 'style', source: 'auto',
                 timestamp: 9, status: 'committed' };
let style = { profile: null, observed: 18, needed: 20 };
let rows = [...ROWS];
globalThis.fetch = async (url, opts = {}) => {
  sent.push({ url: String(url), method: opts.method || 'GET',
              body: opts.body == null ? null : String(opts.body) });
  if (/\\/api\\/memory$/.test(url)) {
    return { ok: true, status: 200, json: async () => ({ memory: rows, style }) };
  }
  return { ok: true, status: 200, json: async () => ({ ok: true }) };
};
const panel = () => byId('memory-style-panel');
const inputs = () => panel().querySelectorAll('input');
const cards = () => byId('memory-list').querySelectorAll('.memory-item')
  .map((el) => (el.querySelector('.memory-item-text') || {}).textContent);
"""


@pytest.fixture(scope="module")
def brain(tmp_path_factory):
    shim = _SHIM.replace("__IDS__", json.dumps(_index_ids()))
    return _make_sandbox(tmp_path_factory.mktemp("stylepanel"), MEMORY_JS, shim, _STUBS)


def _brain(sandbox, script):
    return _run(sandbox, _PREAMBLE + _CASE, script)


def test_the_panel_is_on_the_page_where_the_list_is():
    html = INDEX.read_text(encoding="utf-8")
    assert html.index('id="memory-style-panel"') < html.index('id="memory-list"')


def test_before_a_profile_forms_it_says_how_far_along_it_is(brain):
    out = _brain(brain, """
        ready(); await tick();
        await openBrain();
        console.log(JSON.stringify({ hidden: !!panel().hidden, text: panel().readable,
                                     inputs: inputs().length }));
    """)
    assert out["hidden"] is False
    assert "How you write" in out["text"]
    assert "18 of 20 messages seen" in out["text"]
    assert out["inputs"] == 0


def test_once_formed_each_line_is_printed_editable_and_not_a_memory_card(brain):
    out = _brain(brain, """
        style = { profile: { id: 'sty', text: FORMED_TEXT, sentences: ['derived one'] },
                  observed: 24, needed: 20 };
        rows = [RECORD, ...ROWS];
        ready(); await tick();
        await openBrain();
        console.log(JSON.stringify({ values: inputs().map((i) => i.value),
                                     labels: inputs().map((i) => i.getAttribute('aria-label')),
                                     text: panel().readable, cards: cards(), count: count() }));
    """)
    # The stored text — the person's own wording once they have edited it.
    assert out["values"] == ["You write in short sentences.", "You rarely use exclamation marks."]
    assert out["labels"] == ["How you write, line 1", "How you write, line 2"]
    assert "Change a line that is wrong" in out["text"]
    assert "Forget how I write" in out["text"]
    assert not [c for c in out["cards"] if c and "short sentences" in c], \
        "the profile is still drawn as a memory card"
    assert sorted(out["cards"]) == sorted(["Rowan prefers tea to coffee", "The launch is on the 14th"])
    assert out["count"] == "2"


def test_changing_a_line_saves_the_joined_lines_through_the_records_put(brain):
    out = _brain(brain, """
        style = { profile: { id: 'sty', text: FORMED_TEXT, sentences: [] }, observed: 24, needed: 20 };
        rows = [RECORD, ...ROWS];
        ready(); await tick();
        await openBrain();
        const second = inputs()[1];
        second.value = 'You use exclamation marks when you are pleased!';
        fire(second, 'change');
        await tick();
        const put = sent.find((c) => c.method === 'PUT');
        console.log(JSON.stringify({ put, toasts: globalThis.__said.toasts }));
    """)
    assert out["put"]["url"].endswith("/api/memory/sty")
    body = dict(pair.split("=", 1) for pair in out["put"]["body"].split("&"))
    from urllib.parse import unquote_plus
    assert unquote_plus(body["text"]) == ("You write in short sentences.\n"
                                          "You use exclamation marks when you are pleased!")
    assert out["toasts"], "the save said nothing"


def test_forgetting_it_says_what_it_takes_and_deletes_the_record(brain):
    out = _brain(brain, """
        style = { profile: { id: 'sty', text: FORMED_TEXT, sentences: [] }, observed: 24, needed: 20 };
        rows = [RECORD, ...ROWS];
        ready(); await tick();
        await openBrain();
        const forget = panel().querySelectorAll('button').find((b) => /Forget/.test(b.textContent));
        fire(forget, 'click');
        await tick();
        console.log(JSON.stringify({ confirms: globalThis.__said.confirms,
                                     del: sent.find((c) => c.method === 'DELETE') }));
    """)
    assert len(out["confirms"]) == 1
    confirm = out["confirms"][0]
    assert "counts" in confirm and "starts learning again" in confirm and "from nothing" in confirm
    assert out["del"]["url"].endswith("/api/memory/sty")


def test_an_answer_without_the_style_block_hides_the_panel(brain):
    out = _brain(brain, """
        style = undefined;
        ready(); await tick();
        await openBrain();
        console.log(JSON.stringify({ hidden: !!panel().hidden }));
    """)
    assert out["hidden"] is True
