# SPDX-License-Identifier: AGPL-3.0-or-later
"""`B822` — a provider import says what it read, so the wrong file looks wrong.

`P13-06` returns `provider`, `conversations`, `messages`, `dropped_assistant`,
`truncated`, `already_known` and `below_floor` from `POST /api/memory/import`,
and the Brain's panel rendered none of them — measured on `ffaf6671`, `git grep
'dropped_assistant\\|already_known\\|below_floor' -- static/js` found nothing.
*"0 memories imported"* with no reason is the failure an importer actually has:
a misread file, one with none of your own turns in it, one already imported and
one cut short at the reading limit each need a different next step.

Now one line under the suggestions (`memory.js::describeImport`): *"ChatGPT
export · 412 conversations · 3,180 of your messages read · 4,102 assistant
replies skipped · 7 already known."* — and under the recognised-but-empty
export's own sentence too (*"No messages of yours found in this Claude
export"*, which `BRAIN-M-14` already drew). The provider's name is the server's
(`provider_import.PROVIDER_LABELS`).

Driven on the real `memory.js` under node: the pure line over the shapes the
route returns, and the real upload handler through the file input's `change`.

`Verify:` a cold reader who imports the wrong file can tell that it was the
wrong file, from the panel alone.
"""
from __future__ import annotations

import json
import shutil

import pytest

from test_the_brain_says_it_is_loading import _LOADING_STUBS, _PREAMBLE  # noqa: E402
from test_the_workshop_surfaces_js import _SHIM, _index_ids, MEMORY_JS  # noqa: E402
from test_tool_effect_surfaces_js import _make_sandbox, _run  # noqa: E402

pytestmark = pytest.mark.skipif(not shutil.which("node"), reason="node binary not on PATH")

#: The Brain sandbox's stubs, with the spinner the upload button draws.
_STUBS = dict(_LOADING_STUBS)
_STUBS["spinner.js"] = _LOADING_STUBS["spinner.js"].replace(
    "export default { createLoadingRow: row,",
    "const whirl = () => ({ element: globalThis.document.createElement('span'), destroy(){} });\n"
    "export function createWhirlpool(){ return whirl(); }\n"
    "export default { createLoadingRow: row, createWhirlpool: whirl,")
assert "createWhirlpool: whirl" in _STUBS["spinner.js"], "the spinner stub moved"

FULL = {"suggestions": [{"id": "a", "text": "Drives a Transit van", "category": "fact"}],
        "filename": "conversations.json", "provider": "chatgpt", "provider_label": "ChatGPT",
        "conversations": 412, "messages": 3180, "dropped_assistant": 4102,
        "truncated": False, "already_known": 7, "below_floor": 0}
#: Somebody's own assistant-only file: recognised, and nothing of theirs in it.
WRONG = {"suggestions": [], "provider": "claude", "provider_label": "Claude",
         "conversations": 3, "messages": 0, "dropped_assistant": 41, "truncated": False,
         "filename": "conversations.json",
         "message": "No messages of yours found in this Claude export"}
#: Everything in it was already known — not "nothing found".
AGAIN = {**FULL, "suggestions": [], "already_known": 58}
CUT = {**FULL, "truncated": True, "below_floor": 2}


@pytest.fixture(scope="module")
def brain(tmp_path_factory):
    shim = _SHIM.replace("__IDS__", json.dumps(_index_ids()))
    return _make_sandbox(tmp_path_factory.mktemp("importline"), MEMORY_JS, shim, _STUBS)


def test_the_line_over_the_shapes_the_route_returns(brain):
    out = _run(brain, _PREAMBLE, """
        const { describeImport } = await import('./memory.js');
        console.log(JSON.stringify(%s.map((d) => describeImport(d))));
    """ % json.dumps([FULL, WRONG, AGAIN, CUT, {"suggestions": [], "filename": "notes.txt"}]))
    full, wrong, again, cut, generic = out
    assert full == ("ChatGPT export · 412 conversations · 3,180 of your messages read · "
                    "4,102 assistant replies skipped · 7 already known.")
    assert wrong == ("Claude export · 3 conversations · 0 of your messages read · "
                     "41 assistant replies skipped.")
    assert "58 already known" in again
    assert "2 too uncertain to keep" in cut and "Only the start of it was read" in cut
    assert generic == "", "an ordinary upload is not a provider export"


def _upload(brain, answer):
    return _run(brain, _PREAMBLE, """
        mockFetch((url) => (/\\/api\\/memory\\/import$/.test(url) ? res(200, %s)
                          : /\\/api\\/memory$/.test(url) ? res(200, { memory: ROWS, style: STYLE })
                          : res(200, {})));
        ready(); await tick();
        const input = byId('memory-import-file');
        input.files = [{ name: 'conversations.json' }];
        input.dispatchEvent({ type: 'change', target: input, stopPropagation() {}, preventDefault() {} });
        await tick();
        const body = byId('memory-suggestions-body');
        console.log(JSON.stringify({
          text: body.readable,
          line: (body.querySelector('.memory-import-summary') || { textContent: '' }).textContent,
        }));
    """ % json.dumps(answer))


def test_the_panel_draws_the_line_under_the_suggestions(brain):
    out = _upload(brain, FULL)
    assert "Drives a Transit van" in out["text"]
    assert out["line"].startswith("ChatGPT export · 412 conversations")


def test_the_wrong_file_reads_as_the_wrong_file(brain):
    """A file of assistant turns: the server's sentence, and the numbers that
    show why — nothing of yours read, forty-one replies skipped."""
    out = _upload(brain, WRONG)
    assert "No messages of yours found in this Claude export" in out["text"]
    assert "0 of your messages read" in out["line"]
    assert "41 assistant replies skipped" in out["line"]
