# SPDX-License-Identifier: AGPL-3.0-or-later
"""`B1251` (P23 acceptance, round 2) — a live step's fold says *Thinking…* beside
the turn's fold.

Measured on `299bd50` (`shots/r2-turn-live-mid.png`): a live agent turn after
*Allow for this task* draws, in its one reply, the turn's shut fold (the
earlier steps, carried in — `B1247`) and the live step's open fold under it
(*0.2s · 16 tok*), and both were headed *View thinking process*. They merge
when the step ends. The live one is not something to view yet, it is happening
— so once its thinking closes it keeps the *Thinking…* it opened with
(`liveFoldHeader`, `turnReasoning.js`), and a bubble that carries nothing reads
as it always did.

The row named `markdown.js`' `createCollapsible`; the live fold is not built
there — `chat.js` draws it — so the header is decided where the live stream
closes the thinking (`_finishLiveThinkingTransition`).

Driven (`Law 20`): that function cut out of `chat.js` and run over the shared
DOM shim with its HTML layer, the real `turnReasoning.js` deciding; the bubble
carries the turn's fold through the real `carryTurnReasoning`.
"""

import json
import shutil
import subprocess
from pathlib import Path

import pytest

from tests.helpers.js_source import js_definition
from tests.helpers.source_text import blank_text
from test_tool_effect_surfaces_js import _DOM

ROOT = Path(__file__).resolve().parents[1]
JS = ROOT / "static" / "js"
CHAT = (JS / "chat.js").read_text(encoding="utf-8")

pytestmark = pytest.mark.skipif(not shutil.which("node"), reason="node binary not on PATH")


@pytest.fixture(scope="module")
def box(tmp_path_factory):
    d = tmp_path_factory.mktemp("livefold")
    (d / "dom.js").write_text(_DOM)
    shutil.copy(JS / "turnReasoning.js", d / "turnReasoning.js")
    return d


_FOLD = ('<div class="thinking-section"><div class="thinking-header" data-thinking-id="f1">'
         '<div class="thinking-header-left"><span data-label="thinking process">View thinking process</span></div>'
         '<span class="thinking-toggle" id="f1-toggle"></span></div>'
         '<div class="thinking-content" id="f1"><div class="thinking-content-inner">%s</div></div></div>')

_LIVE = ('<div class="thinking-section"><div class="thinking-header" data-thinking-id="live-1">'
         '<div class="thinking-header-left"><span class="live-think-header-text">Thinking…</span></div>'
         '<span class="live-think-spinner-slot"></span><span class="live-think-timer"></span>'
         '<span class="thinking-toggle live-think-toggle expanded" id="live-1-toggle"></span></div>'
         '<div class="thinking-content expanded" id="live-1">'
         '<div class="thinking-content-inner live-think-inner">Now the unfiled ones, all of them.</div></div></div>')


def _run(box, carried: bool) -> dict:
    finish = js_definition(CHAT, blank_text(CHAT, "js").index("function _finishLiveThinkingTransition("))
    case = box / "case.mjs"
    case.write_text(
        "import { installDom, installHtmlParsing } from './dom.js';\n"
        "import * as TR from './turnReasoning.js';\n"
        "const { carryTurnReasoning, liveFoldHeader } = TR;\n"
        "const document = installDom();\ninstallHtmlParsing();\n"
        "const history = document.body.appendChild(document.createElement('div'));\n"
        "const bubble = (html, hidden) => { const b = history.appendChild(document.createElement('div'));"
        " b.className = 'msg msg-ai'; b.innerHTML = '<div class=\"role\">m</div><div class=\"body\">' + html + '</div>';"
        " if (hidden) b.style.display = ''; return b; };\n"
        + ("const step1 = bubble(%s);\n" % json.dumps(_FOLD % "Looking for the folders first.") if carried else "")
        + "const holder = bubble('');\n"
        + ("carryTurnReasoning(step1, holder);\n" if carried else "")
        + "const body = holder.querySelector('.body');\n"
        "const stream = body.appendChild(document.createElement('div'));\n"
        "stream.className = 'stream-content';\n"
        "stream.innerHTML = %s;\n" % json.dumps(_LIVE)
        + """
let isThinking = true, _thinkingMode = 'tag', thinkingStartTime = Date.now() - 200;
let roundText = '<think>Now the unfiled ones, all of them.</think>', accumulated = roundText;
let roundHolder = holder; const spinner = null;
const _cancelThinkingGrace = () => {}, _finalizeLiveThinking = () => {}, _renderStream = () => {},
  _scheduleThinkingSpinner = () => {}, _roundDisplayProjector = { current: () => '' };
const _closedThinkingText = () => 'Now the unfiled ones, all of them.';
const _formatThinkStats = (s, n) => s + 's \\u00b7 ' + n + ' tok';
let _liveThinkSection = stream.querySelector('.thinking-section');
let _liveThinkContent = stream.querySelector('.thinking-content');
let _liveThinkInner = stream.querySelector('.live-think-inner');
let _liveThinkHeader = stream.querySelector('.live-think-header-text');
let _liveThinkSpinnerSlot = stream.querySelector('.live-think-spinner-slot');
let _liveThinkTimerEl = stream.querySelector('.live-think-timer');
let _liveThinkToggle = stream.querySelector('.live-think-toggle');
let _liveThinkTokenCount = 16, _liveThinkDomId = 'live-1';
""" + finish + """
_finishLiveThinkingTransition();
const heads = body.querySelectorAll('.thinking-section').map((f) =>
  f.querySelector('.thinking-header-left').textContent.trim());
console.log(JSON.stringify({ heads }));
""")
    out = subprocess.run(["node", str(case)], capture_output=True, text=True, timeout=30, cwd=box)
    assert out.returncode == 0, out.stderr
    return json.loads(out.stdout.strip().splitlines()[-1])


def test_beside_the_turns_fold_the_live_step_says_thinking(box):
    out = _run(box, carried=True)
    assert out["heads"] == ["View thinking process", "Thinking…"], \
        "two folds in one reply both said View thinking process"


def test_a_reply_with_one_fold_reads_as_it_always_did(box):
    out = _run(box, carried=False)
    assert out["heads"] == ["View thinking process"]
