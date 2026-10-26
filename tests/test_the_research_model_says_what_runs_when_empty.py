# SPDX-License-Identifier: AGPL-3.0-or-later
"""`B1504` — the Research Model card says what runs when it is left empty.

Its empty choice said *Same as chat*, and the line under it *Using chat
defaults*. An empty Research Model does not use the chat model first: the
resolver reads Research, then Utility, then the default chat model
(`endpoint_resolver._configured_entry("research")`, measured in
`tests/test_the_scheduled_task_model_line_says_who_reads_it.py::
test_a_research_task_reads_the_research_model_not_this`). Now the empty choice
reads *Same as utility* when a utility model is set, and the line names the
model that runs — and both follow a change made on the Utility card beside it.

Driven in headless Chromium (the `playwright` node package): the AI and Search
panels cut out of `static/index.html`, and the real `initResearchSettings`
with the real select fillers cut out of `static/js/settings.js`, over a stand-in
for `GET /api/auth/settings` and the endpoint list. The order itself is pinned
against the real resolver here too, so the card and the server cannot drift.
"""

from __future__ import annotations

import json
import subprocess
from pathlib import Path

import pytest

from tests.helpers.js_source import js_definition
from test_the_command_palette_in_a_browser import NODE, _SKIP  # noqa: E402

ROOT = Path(__file__).resolve().parents[1]
INDEX = (ROOT / "static" / "index.html").read_text(encoding="utf-8")
SETTINGS = (ROOT / "static" / "js" / "settings.js").read_text(encoding="utf-8")

_ENDPOINTS = [
    {"id": "ep-chat", "name": "Chat box", "is_enabled": True, "online": True, "models": ["org/chat-model"]},
    {"id": "ep-util", "name": "Util box", "is_enabled": True, "online": True, "models": ["util-model"]},
    {"id": "ep-res", "name": "Research box", "is_enabled": True, "online": True, "models": ["deep-model"]},
]


def _panel(name: str) -> str:
    start = INDEX.index(f'<div data-settings-panel="{name}"')
    depth, i = 0, start
    while True:
        o, c = INDEX.find("<div", i), INDEX.find("</div>", i)
        if o != -1 and o < c:
            depth, i = depth + 1, o + 4
        else:
            depth, i = depth - 1, c + 6
            if depth == 0:
                return INDEX[start:i]


def _cut(signature: str) -> str:
    return js_definition(SETTINGS, SETTINGS.index(signature))


def _harness(settings: dict) -> str:
    return (
        f"const ENDPOINTS = {json.dumps(_ENDPOINTS)};\n"
        f"const SETTINGS = {json.dumps(settings)};\n"
        "window.posted = [];\n"
        "const el = (id) => document.getElementById(id);\n"
        "const _syncEndpointLogo = () => {}, _syncModelLogo = () => {}, _appendUnlistedOption = () => {};\n"
        "const sortModelIds = (a) => (a || []).slice();\n"
        "const _registerAiEndpointRefresh = () => {};\n"
        "const _notSaved = () => 'Not saved';\n"
        "async function _fetchModelEndpoints() { return ENDPOINTS; }\n"
        "async function _postSettings(body) { window.posted.push(body); }\n"
        "window.fetch = async () => ({ ok: true, json: async () => SETTINGS });\n"
        + "\n".join(_cut(sig) for sig in ("function _endpointLabel(", "function _fillEndpointSelect(",
                                          "function _fillModelSelect(", "async function initResearchSettings("))
        + "\nwindow.ready = (async () => {\n"
          "  _fillEndpointSelect(el('set-defaultEpSelect'), ENDPOINTS, SETTINGS.default_endpoint_id || '', false);\n"
          "  _fillModelSelect(el('set-defaultModelSelect'), ['org/chat-model'], SETTINGS.default_model || '', false);\n"
          "  _fillEndpointSelect(el('set-utilityEpSelect'), ENDPOINTS, SETTINGS.utility_endpoint_id || '', true);\n"
          "  _fillModelSelect(el('set-utilityModelSelect'), SETTINGS.utility_endpoint_id ? ['util-model'] : [],"
          " SETTINGS.utility_model || '', true);\n"
          "  await initResearchSettings();\n"
          "})();\n"
    )


_SCRIPT = r"""
const { chromium } = require('playwright');
const fs = require('fs');
const [MARKUP, HARNESS] = process.argv.slice(2).map((p) => fs.readFileSync(p, 'utf8'));
(async () => {
  const browser = await chromium.launch({ args: ['--no-sandbox'] });
  const page = await browser.newPage();
  const errors = [];
  page.on('pageerror', (e) => errors.push(String(e.message || e)));
  await page.setContent('<!doctype html><html><body>' + MARKUP + '</body></html>');
  await page.addScriptTag({ content: HARNESS });
  await page.evaluate(() => window.ready);
  const read = () => page.evaluate(() => ({
    said: document.getElementById('set-researchMsg').textContent,
    option: document.getElementById('set-researchModel').options[0].textContent,
    epOption: document.getElementById('set-researchEndpoint').options[0].textContent,
  }));
  const out = { first: await read() };
  // The Utility card emptied, as a person does it there.
  await page.evaluate(() => {
    const ep = document.getElementById('set-utilityEpSelect');
    ep.value = '';
    ep.dispatchEvent(new Event('change'));
  });
  await page.waitForTimeout(50);
  out.afterUtilityCleared = await read();
  out.errors = errors;
  console.log(JSON.stringify(out));
  await browser.close();
})().catch((e) => { console.error(e); process.exit(1); });
"""


def _card(tmp_path, settings: dict) -> dict:
    (tmp_path / "markup.html").write_text(_panel("ai") + _panel("search"), encoding="utf-8")
    (tmp_path / "harness.js").write_text(_harness(settings), encoding="utf-8")
    (tmp_path / "run.cjs").write_text(_SCRIPT, encoding="utf-8")
    proc = subprocess.run([NODE, str(tmp_path / "run.cjs"), str(tmp_path / "markup.html"),
                           str(tmp_path / "harness.js")], capture_output=True, text=True, timeout=180)
    assert proc.returncode == 0, proc.stderr[-3000:]
    out = json.loads(proc.stdout.strip().splitlines()[-1])
    assert out["errors"] == [], out["errors"]
    return out


_BOTH = {"default_endpoint_id": "ep-chat", "default_model": "org/chat-model",
         "utility_endpoint_id": "ep-util", "utility_model": "util-model",
         "research_endpoint_id": "", "research_model": ""}


@pytest.mark.skipif(NODE is None, reason=_SKIP or "")
def test_with_utility_set_and_research_empty_the_card_names_the_utility_model(tmp_path):
    """The row's `Verify:`."""
    out = _card(tmp_path, _BOTH)
    assert out["first"]["said"] == "Runs on the utility model: Util box / util-model."
    assert out["first"]["option"] == "Same as utility" == out["first"]["epOption"]


@pytest.mark.skipif(NODE is None, reason=_SKIP or "")
def test_with_utility_empty_it_says_the_chat_model_and_follows_the_utility_card(tmp_path):
    out = _card(tmp_path, {**_BOTH, "utility_endpoint_id": "", "utility_model": ""})
    assert out["first"]["said"] == "Runs on the chat model: Chat box / chat-model."
    assert out["first"]["option"] == "Same as chat"
    # And live: set, the Utility card's change is read without a reload.
    live = _card(tmp_path, _BOTH)["afterUtilityCleared"]
    assert live["said"] == "Runs on the chat model: Chat box / chat-model.", live
    assert live["option"] == "Same as chat"


def test_the_order_the_card_says_is_the_resolvers(monkeypatch):
    """Research, then Utility, then the default chat model — the real
    `_configured_entry`, so the card's words and the server cannot drift."""
    import src.endpoint_resolver as er
    import src.settings as settings_mod

    store = dict(_BOTH)
    monkeypatch.setattr(settings_mod, "load_settings", lambda: store)
    monkeypatch.setattr(settings_mod, "get_user_setting_pair",
                        lambda ek, mk, owner="", settings=None: ((settings or store).get(ek, ""),
                                                                 (settings or store).get(mk, "")),
                        raising=False)
    assert er._configured_entry("research") == ("ep-util", "util-model")
    store.update(utility_endpoint_id="", utility_model="")
    assert er._configured_entry("research") == ("ep-chat", "org/chat-model")
    store.update(research_endpoint_id="ep-res", research_model="deep-model")
    assert er._configured_entry("research") == ("ep-res", "deep-model")
