# SPDX-License-Identifier: AGPL-3.0-or-later
"""`D-2026-10-07-02` §1 in the browser — the model menu, the composer and
Settings offer only what answered, and say so where something did not.

The owner, 2026-10-07: *"Pantheon will only ever show models successfully
enumerated."* and *"Started a chat with no model fails clearly, and states
why."*

Measured on `fcd559e` (the base):

  * an endpoint that was not answering kept its models in the menu, dimmed and
    clickable ("Click to try anyway") — `P23-04`'s CHAT-M-23 mark — and picking
    one failed in 0.2 s; there was no Retry;
  * a saved default the endpoint no longer listed opened the composer on it
    from the page's own copy (`pantheon-default-chat-cache`), and the boot
    check that found no default left that copy in place;
  * a refused send drew the raw body (`{"detail": …}`); with no model the
    composer said "No model yet." even to a member, whose door it is not;
  * Settings' model selects showed their first option when the saved model was
    not listed, as if that were the setting.

Driven (`Law 20`): each function cut out of the shipped module with the shared
extractor (`tests/helpers/js_source.js_definition`) and run in node against the
DOM shim (`tests/test_tool_effect_surfaces_js.py`).
"""
from __future__ import annotations

import shutil
from pathlib import Path

import pytest

from tests.helpers.js_source import js_definition
from tests.helpers.source_text import blank_text
from test_tool_effect_surfaces_js import _make_sandbox, _run

ROOT = Path(__file__).resolve().parents[1]
JS = ROOT / "static" / "js"

pytestmark = pytest.mark.skipif(not shutil.which("node"), reason="node binary not on PATH")

_SHIM = r"""
import { installDom, Node } from './dom.js';
export const document = installDom();
export { Node };
globalThis.window = globalThis;
globalThis.CustomEvent = class CustomEvent { constructor(type, init) { this.type = type; this.detail = (init || {}).detail; } };
globalThis.__events = [];
globalThis.dispatchEvent = (e) => { globalThis.__events.push({ type: e.type, detail: e.detail }); return true; };
document.dispatchEvent = (e) => { globalThis.__events.push({ type: e.type, detail: e.detail }); return true; };
const store = {};
globalThis.localStorage = {
  getItem: (k) => (k in store ? store[k] : null),
  setItem: (k, v) => { store[k] = String(v); },
  removeItem: (k) => { delete store[k]; },
};
"""

_PRE = "import { document, Node } from './shim.js';\n"


@pytest.fixture(scope="module")
def sandbox(tmp_path_factory):
    return _make_sandbox(tmp_path_factory.mktemp("modelmenu"), JS / "chatStreamErrors.js", _SHIM, {})


def _cut(path: Path, anchor: str) -> str:
    src = path.read_text(encoding="utf-8")
    code = blank_text(src, "js")
    assert code.count(anchor) == 1, anchor
    return js_definition(src, code.index(anchor)).replace("export function", "function", 1) \
        .replace("export async function", "async function", 1)


def _picker(anchor: str) -> str:
    return _cut(JS / "modelPicker.js", anchor)


# A node's words, its children's joined with `|` so a line and its button
# read as two things.
_TEXT = "(function t(n){ return n.childNodes.length ? n.childNodes.map(t).join('|') : (n.textContent || ''); })"

_ITEMS = """[
  { endpoint_id: 'live', endpoint_name: 'Office LLM', url: 'http://10.0.0.5:8000/v1/chat/completions',
    models: ['alpha-7b'], models_display: ['alpha-7b'], category: 'local' },
  { endpoint_id: 'gone', endpoint_name: 'Old box', url: 'http://10.0.0.6:8000/v1/chat/completions',
    models: [], offline: true, down_line: 'Old box is loading its model.', category: 'local' },
  { endpoint_id: 'probe', endpoint_name: 'GPU box', url: 'http://10.0.0.7:8000/v1/chat/completions',
    models: ['qwen-32b'], category: 'local' },
  { endpoint_id: 'sent', endpoint_name: 'Lab', url: 'http://10.0.0.8:8000/v1/chat/completions',
    models: ['lab-model'], category: 'local' },
]"""


def _read_picker_script(body: str) -> str:
    return """
        let _localProbe = { probe: { alive: false, error: 'connection refused' } };
        const _unansweredBases = new Set(['http://10.0.0.8:8000/v1']);
        const sortModelObjects = (x) => x;
        let items = %s;
        globalThis.window.modelsModule = {
          getCachedItems: () => items,
          refreshModels: async (force, opts) => { globalThis.__refreshed = { force, opts }; items = items.map((i) => i.endpoint_id === 'gone' ? { ...i, offline: false, models: ['back-model'], models_display: ['back-model'] } : i); },
        };
        %s
        %s
        %s
    """ % (_ITEMS, _picker("function _unansweredFor("), _picker("function _readPicker("), body)


def test_an_endpoint_that_is_not_answering_is_one_line_and_none_of_its_names(sandbox):
    out = _run(sandbox, _PRE, _read_picker_script("""
        const { models, down } = _readPicker();
        console.log(JSON.stringify({ models: models.map((m) => m.mid), down: down.map((d) => [d.endpointId, d.line]) }));
    """))
    assert out["models"] == ["alpha-7b"], "a model of an endpoint that is not answering was offered"
    assert out["down"] == [
        ["gone", "Old box is loading its model."],      # the server's line
        ["probe", "GPU box isn't answering."],           # its probe failed
        ["sent", "Lab isn't answering."],                # a send to it went unanswered
    ]


def test_the_menu_draws_each_line_with_retry_and_retry_asks_that_endpoint(sandbox):
    out = _run(sandbox, _PRE, _read_picker_script("""
        const menu = document.createElement('div');
        const listEl = document.createElement('div');
        const search = document.createElement('input');
        const searchRow = document.createElement('div');
        const BROWSE_ALL_LIMIT = 12, RECENT_MAX = 5;
        const _pickerModelKey = (m) => `${m.endpointId}::${m.mid}`;
        const _loadFavorites = () => [];
        const _loadRecent = () => [];
        const providerLogo = () => '';
        const _openPickerShortcut = () => {};
        let picked = null; const _pick = (m) => { picked = m.mid; };
        let updated = 0; const updateModelPicker = () => { updated += 1; };
        %s
        %s
        _populate('');
        const downRows = listEl.childNodes.filter((n) => n.className === 'model-switch-down');
        const modelRows = listEl.childNodes.filter((n) => n.className === 'model-switch-item');
        const before = { down: downRows.map(%s), models: modelRows.length, placeholder: search.placeholder };
        const retry = downRows[0].childNodes.find((n) => n.className === 'model-switch-down-retry');
        retry.listeners.click[0]({ stopPropagation() {} });
        await new Promise((r) => setTimeout(r, 0));
        const after = listEl.childNodes.filter((n) => n.className === 'model-switch-item').map(%s);
        console.log(JSON.stringify({ before, refreshed: globalThis.__refreshed, after, updated }));
    """ % (_picker("function _populate("), _picker("async function _retryEndpoint("), _TEXT, _TEXT)))
    assert out["before"]["down"] == [
        "Old box is loading its model.|Retry", "GPU box isn't answering.|Retry", "Lab isn't answering.|Retry"]
    assert out["before"]["models"] == 1 and out["before"]["placeholder"] == "Search models…"
    assert out["refreshed"] == {"force": True, "opts": {"retry": "gone"}}
    assert any(r.startswith("back-model") for r in out["after"]), out["after"]
    assert out["updated"] == 1


def test_with_every_endpoint_down_the_menu_says_so_and_offers_no_door_to_add(sandbox):
    out = _run(sandbox, _PRE, """
        let _localProbe = {};
        const _unansweredBases = new Set();
        const sortModelObjects = (x) => x;
        const items = [{ endpoint_id: 'gone', endpoint_name: 'Old box', url: 'u', models: [], offline: true,
                         down_line: "Old box isn't answering." }];
        globalThis.window.modelsModule = { getCachedItems: () => items };
        const menu = document.createElement('div'), listEl = document.createElement('div');
        const search = document.createElement('input'), searchRow = document.createElement('div');
        const BROWSE_ALL_LIMIT = 12, RECENT_MAX = 5;
        const _pickerModelKey = (m) => m.mid, _loadFavorites = () => [], _loadRecent = () => [];
        const providerLogo = () => '', _openPickerShortcut = () => {}, _pick = () => {};
        %s
        %s
        %s
        _populate('');
        console.log(JSON.stringify({ rows: listEl.childNodes.map((n) => n.className), placeholder: search.placeholder }));
    """ % (_picker("function _unansweredFor("), _picker("function _readPicker("), _picker("function _populate(")))
    assert out == {"rows": ["model-switch-down"], "placeholder": "No model answering"}


def test_a_member_with_no_models_is_told_who_adds_them(sandbox):
    out = _run(sandbox, _PRE, """
        globalThis.window._isAdmin = false;
        let _localProbe = {};
        const _unansweredBases = new Set();
        const sortModelObjects = (x) => x;
        globalThis.window.modelsModule = { getCachedItems: () => [] };
        const menu = document.createElement('div'), listEl = document.createElement('div');
        const search = document.createElement('input'), searchRow = document.createElement('div');
        const _openPickerShortcut = () => {};
        %s
        %s
        %s
        _populate('');
        console.log(JSON.stringify({ rows: listEl.childNodes.map((n) => [n.className, n.textContent]) }));
    """ % (_picker("function _unansweredFor("), _picker("function _readPicker("), _picker("function _populate(")))
    assert out["rows"] == [["model-switch-empty", "An admin adds models in Settings → Added Models."]]


# ── the saved default ───────────────────────────────────────────────────────

def _update_script(items: str, body: str) -> str:
    return """
        const label = document.createElement('span'); label.id = 'model-picker-label'; document.body.appendChild(label);
        const wrap = document.createElement('div'); wrap.id = 'model-picker-wrap'; document.body.appendChild(wrap);
        let pending = null; let ensured = 0;
        const _deps = { getCurrentSessionId: () => null, getSessions: () => [],
                        getPendingChat: () => pending, setPendingChat: (v) => { pending = v; } };
        let _autoSelectingDefault = false;
        const providerLogo = () => '';
        const _ensureDefaultPendingChat = () => { ensured += 1; };
        globalThis.window.modelsModule = { getCachedItems: () => %s };
        %s
        %s
        %s
        %s
    """ % (items, _picker("function _modelExists("), _picker("function _forgetDefaultChat("),
           _picker("function updateModelPicker("), body)


def test_a_cached_default_the_loaded_list_does_not_offer_is_not_used(sandbox):
    out = _run(sandbox, _PRE, _update_script(
        "[{ endpoint_id: 'office', url: 'http://h/v1/chat/completions', models: ['alpha-7b'] }]", """
        localStorage.setItem('pantheon-default-chat-cache', JSON.stringify(
          { endpoint_id: 'office', endpoint_url: 'http://h/v1/chat/completions', model: 'gone-70b' }));
        updateModelPicker();
        console.log(JSON.stringify({ label: label.textContent, title: label.title, pending, ensured,
          cache: localStorage.getItem('pantheon-default-chat-cache') }));
    """))
    assert out["label"] == "Select model" and out["pending"] is None
    assert out["title"] == "gone-70b isn't answering. Pick another from the model menu."
    assert out["cache"] is None, "the page kept a default nothing lists"
    assert out["ensured"] == 0, "it went looking for another model in the default's place"


def test_a_cached_default_that_is_listed_is_used(sandbox):
    out = _run(sandbox, _PRE, _update_script(
        "[{ endpoint_id: 'office', url: 'http://h/v1/chat/completions', models: ['alpha-7b'] }]", """
        localStorage.setItem('pantheon-default-chat-cache', JSON.stringify(
          { endpoint_id: 'office', endpoint_url: 'http://h/v1/chat/completions', model: 'alpha-7b' }));
        updateModelPicker();
        console.log(JSON.stringify({ label: label.textContent, pending }));
    """))
    assert out["label"] == "alpha-7b" and out["pending"]["source"] == "default"


def test_the_boot_check_drops_the_pages_copy_when_the_server_says_the_default_is_not_listed(sandbox):
    out = _run(sandbox, _PRE, """
        let _defaultChat = null;
        localStorage.setItem('pantheon-default-chat-cache', JSON.stringify({ endpoint_url: 'u', model: 'gone-70b' }));
        globalThis.window.__pantheonDefaultChat = { endpoint_url: 'u', model: 'gone-70b' };
        globalThis.fetch = async () => ({ json: async () => ({ endpoint_id: 'office', endpoint_url: '', model: '',
          reason: "Office LLM isn't answering. Pick another from the model menu." }) });
        %s
        await _refreshDefaultChat();
        console.log(JSON.stringify({ cache: localStorage.getItem('pantheon-default-chat-cache'),
          dc: globalThis.window.__pantheonDefaultChat, reason: globalThis.window.__pantheonDefaultChatReason,
          events: globalThis.__events.map((e) => [e.type, e.detail && e.detail.reason]) }));
    """ % _cut(ROOT / "static" / "app.js", "async function _refreshDefaultChat("))
    assert out["cache"] is None and out["dc"] is None
    assert out["reason"] == "Office LLM isn't answering. Pick another from the model menu."
    assert out["events"] == [["pantheon:default-chat-unusable",
                              "Office LLM isn't answering. Pick another from the model menu."]]


# ── the composer ────────────────────────────────────────────────────────────

def _say(body: str) -> str:
    return """
        const box = document.createElement('div'); box.id = 'chat-history'; document.body.appendChild(box);
        const add = document.createElement('button'); add.id = 'model-picker-add-models-btn'; document.body.appendChild(add);
        const btn = document.createElement('button'); btn.id = 'model-picker-btn'; document.body.appendChild(btn);
        let opened = []; add.click = () => opened.push('add'); btn.click = () => opened.push('menu');
        const hideWelcomeScreen = () => {};
        const uiModule = { scrollHistory() {} };
        %s
        %s
    """ % (_cut(JS / "chat.js", "export function _sayNoModel("), body)


def test_a_default_that_is_not_listed_says_why_and_opens_the_menu(sandbox):
    out = _run(sandbox, _PRE, _say("""
        _sayNoModel(document, { reason: "Office LLM isn't answering. Pick another from the model menu." });
        const note = box.querySelector('.no-model-note');
        note.querySelector('.no-model-add').listeners.click[0]();
        console.log(JSON.stringify({ text: %s(note), opened }));
    """ % _TEXT))
    assert out["text"] == "Office LLM isn't answering. Pick another from the model menu.|Pick a model"
    assert out["opened"] == ["menu"]


def test_with_no_model_a_member_is_told_who_adds_one_and_given_no_door(sandbox):
    out = _run(sandbox, _PRE, _say("""
        globalThis.window._isAdmin = false;
        _sayNoModel(document);
        const note = box.querySelector('.no-model-note');
        console.log(JSON.stringify({ text: %s(note), buttons: note.querySelectorAll('.no-model-add').length }));
    """ % _TEXT))
    assert out == {"text": "No model yet. An admin adds models in Settings → Added Models.", "buttons": 0}


def test_with_no_model_an_admin_still_gets_the_door(sandbox):
    out = _run(sandbox, _PRE, _say("""
        globalThis.window._isAdmin = true;
        _sayNoModel(document);
        const note = box.querySelector('.no-model-note');
        note.querySelector('.no-model-add').listeners.click[0]();
        console.log(JSON.stringify({ text: %s(note), opened }));
    """ % _TEXT))
    assert out == {"text": "No model yet.|Add a model", "opened": ["add"]}


# ── Settings ────────────────────────────────────────────────────────────────

_SELECT = """
    function makeSelect(id) {
      const options = [];
      const sel = { id, options, _value: '',
        appendChild(o) { options.push(o); if (!this._value && !options.some((x) => x.value === '')) this._value = options[0].value; return o; },
        remove(i) { options.splice(i, 1); },
        get value() { return this._value; },
        set value(v) { this._value = options.some((o) => o.value === v) ? v : (options[0] ? options[0].value : ''); },
      };
      return sel;
    }
    globalThis.document.getElementById = () => null;
    const sortModelIds = (x) => x;
"""


def test_a_saved_model_that_is_not_listed_is_shown_as_such_where_it_is_set(sandbox):
    settings = JS / "settings.js"
    out = _run(sandbox, _PRE, _SELECT + """
        %s
        %s
        %s
        const sel = makeSelect('set-defaultModelSelect');
        _fillModelSelect(sel, ['alpha-7b', 'beta-13b'], 'gone-70b', false);
        const listed = makeSelect('set-taskModel');
        _fillModelSelect(listed, ['alpha-7b', 'beta-13b'], 'beta-13b', false);
        console.log(JSON.stringify({
          value: sel.value, labels: sel.options.map((o) => o.textContent),
          listedValue: listed.value, listedLabels: listed.options.map((o) => o.textContent) }));
    """ % (_cut(settings, "function _syncModelLogo("), _cut(settings, "function _appendUnlistedOption("),
           _cut(settings, "function _fillModelSelect(")))
    assert out["value"] == "gone-70b", "the select fell to another model and looked like the setting"
    assert out["labels"] == ["alpha-7b", "beta-13b", "gone-70b (not listed now)"]
    assert out["listedValue"] == "beta-13b" and out["listedLabels"] == ["alpha-7b", "beta-13b"]
