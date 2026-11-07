# SPDX-License-Identifier: AGPL-3.0-or-later
"""`B1936`. A message sent right after a mode switch carried the other mode's Shell and Web.

Web and Shell are remembered per mode (`web_agent`, `bash_chat`, …), and
`setMode` in `static/app.js` saved the new mode at once but set the two
switches for it half a second later ("a staggered effect"). The send reads
the mode from storage and Web and Shell from the switches, so for that half
second a message went out as the new mode with the old mode's tools. Nobody
has to be fast for it: a queued message with its own mode (`P6-04`) and the
plan's Execute both switch the mode in code and send a moment later. An
Execute from Chat began its Agent turn with Shell refused while its chip said
on, and an Agent turn ran Web after the person had switched Agent's Web off,
against `P7-01`'s rule that the switch you see is the switch that is sent.

Now the switches change with the mode, in the same step. What goes is the
half-second pause before the chips light up, which was decoration. A chip the
feature table hides stays hidden through a switch, as `SET-M-4` wants.

Upstream Odysseus made the same change in 84aa9a91.

Driven (`Law 20`): the mode toggle and the tool switches are cut out of
`static/app.js` with `tests/helpers/js_source`, and the send's form-building
block out of `static/js/chat.js` (the slice
`tests/test_the_shell_toggle_you_set_is_sent_js.py` runs), and run together
under node on the shared DOM shim with real timers; the send runs in a
`setTimeout` of 0, as `_setComposerAndSend` runs it.
"""

import shutil
import sys
from pathlib import Path

import pytest

from tests.helpers.js_source import js_binding, js_code, js_definition, js_function

sys.path.insert(0, str(Path(__file__).resolve().parent))
from test_tool_effect_surfaces_js import _DOM, _run  # noqa: E402

pytestmark = pytest.mark.skipif(not shutil.which("node"), reason="node binary not on PATH")

ROOT = Path(__file__).resolve().parents[1]
APP = (ROOT / "static" / "app.js").read_text(encoding="utf-8")
APPCODE = js_code(APP)
CHAT = (ROOT / "static" / "js" / "chat.js").read_text(encoding="utf-8")


def _app(*signatures: str) -> str:
    return "\n".join(js_definition(APP, APPCODE.index(sig)) + ";" for sig in signatures)


def _form_block() -> str:
    start = CHAT.index("const toggleState = Storage.loadToggleState();")
    end = CHAT.index("// Superseded during preflight", start)
    return CHAT[start:end]


_HARNESS = r"""
let stored = {};
const Storage = {
  loadToggleState: () => JSON.parse(JSON.stringify(stored)),
  saveToggleState: (s) => { stored = JSON.parse(JSON.stringify(s)); },
  KEYS: { WORKSPACE: 'ws' }, get: () => '',
};
const el = (id) => document.getElementById(id);
for (const id of ['mode-agent-btn', 'mode-chat-btn', 'web-toggle-btn', 'bash-toggle-btn']) {
  const b = document.createElement('button'); b.id = id; document.body.appendChild(b);
}
for (const id of ['web-toggle', 'bash-toggle', 'research-toggle', 'rag-toggle']) {
  const c = document.createElement('input'); c.id = id; c.checked = id === 'rag-toggle';
  document.body.appendChild(c);
}
const noop = () => {};
const workspaceModule = { applyMode: noop }, composerMenuModule = { applyMode: noop };
const summonModule = { applyMode: noop, getSummoned: () => null };
const presetsModule = { getSelectedPreset: () => null };
const onToolVisibilityApplied = noop, _syncResearchIndicator = noop, showToolToggleToast = noop;
const planWindow = { isExecuting: () => false }, _getStoredPlan = () => '';
const documentModule = null, activeDocIdForSend = null, approvalForSend = null, isIncognitoForSend = false;
const msg = 'run the tests';
// What leaves the page, built by the send's own block.
function formBlock(fd) {
FORM_BLOCK
}
const send = () => new Promise((resolve) => setTimeout(() => {
  const fd = new FormData();
  formBlock(fd);
  const sent = {};
  for (const [k, v] of fd.entries()) if (['mode', 'use_web', 'allow_web_search', 'allow_bash'].includes(k)) sent[k] = v;
  resolve(sent);
}, 0));
const later = (ms = 600) => new Promise((r) => setTimeout(r, ms));
const chips = () => ({
  web: el('web-toggle-btn').classList.contains('active'), bash: el('bash-toggle-btn').classList.contains('active'),
  webShown: el('web-toggle-btn').style.display !== 'none', bashShown: el('bash-toggle-btn').style.display !== 'none',
});
// The page as it boots: the mode toggle, then the two tool switches.
async function boot(state) {
  stored = state;
  (function initModeToggle() INIT_MODE_TOGGLE)();
  setupToggle('web-toggle-btn', 'web-toggle', 'web');
  setupToggle('bash-toggle-btn', 'bash-toggle', 'bash');
  await later();
}
""".replace("FORM_BLOCK", _form_block()).replace(
    "INIT_MODE_TOGGLE", js_function(APP, "function initModeToggle"))

_FUNCTIONS = "\n".join([
    _app("function loadToggleState(", "function saveToggleState("),
    js_binding(APP, "MODE_TOOLS") + ";",
    _app("function _modeKey(", "function loadToolPref(", "function saveToolPref(",
         "function applyModeToToggles(", "function setupToggle("),
])


@pytest.fixture(scope="module")
def page(tmp_path_factory):
    d = tmp_path_factory.mktemp("b1936")
    (d / "dom.js").write_text(_DOM)
    return d


def run(page, script: str) -> dict:
    preamble = "import { installDom } from './dom.js';\nconst document = installDom();\n"
    return _run(page, preamble, _FUNCTIONS + _HARNESS + script)


def test_a_click_on_agent_sends_agents_web_and_shell(page):
    """The person uses Web in Chat and switched it off for Agent; Shell has
    Agent's default, on. Agent, then a message straight away."""
    out = run(page, """
        await boot({ mode: 'chat', web_chat: true, web_agent: false });
        el('mode-agent-btn').click();
        const sent = await send();
        await later();
        console.log(JSON.stringify({ sent, chips: chips() }));
    """)
    assert out["sent"] == {"mode": "agent", "allow_web_search": "false", "allow_bash": "true"}
    assert out["chips"]["web"] is False and out["chips"]["bash"] is True, (
        "what was sent is what the chips say")


def test_a_queued_message_or_an_executed_plan_sends_the_mode_it_switched_to(page):
    """`_applyQueueItemRoute` and `_executeStoredPlan` call
    `__pantheonSetChatMode` and send a moment later."""
    out = run(page, """
        await boot({ mode: 'chat', web_chat: true, web_agent: false });
        window.__pantheonSetChatMode('agent');
        console.log(JSON.stringify({ sent: await send() }));
    """)
    assert out["sent"] == {"mode": "agent", "allow_web_search": "false", "allow_bash": "true"}


def test_a_click_on_chat_sends_without_agents_web(page):
    out = run(page, """
        await boot({ mode: 'agent', web_chat: false, web_agent: true });
        el('mode-chat-btn').click();
        const sent = await send();
        await later();
        console.log(JSON.stringify({ sent, chips: chips() }));
    """)
    assert out["sent"]["mode"] == "chat"
    assert "use_web" not in out["sent"], "a Chat turn searched the web with Chat's Web off"
    assert out["chips"]["web"] is False and out["chips"]["bashShown"] is False


def test_a_chip_the_feature_table_hides_stays_hidden_through_a_switch(page):
    """`SET-M-4`: the guard inside `applyModeToToggles` still holds, now that
    it runs at once."""
    out = run(page, """
        await boot({ mode: 'chat' });
        el('web-toggle-btn').style.display = 'none';
        window.__pantheonFeatureHiddenIds = new Set(['web-toggle-btn']);
        el('mode-agent-btn').click();
        await later();
        console.log(JSON.stringify({ chips: chips() }));
    """)
    assert out["chips"]["webShown"] is False and out["chips"]["bashShown"] is True
