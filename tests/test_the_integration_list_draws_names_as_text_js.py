# SPDX-License-Identifier: AGPL-3.0-or-later
"""`B951` — Settings' integration list draws what the server says as text.

`renderCard` (`static/js/settings.js`) wrote `${item.name}` and
`${item.detail}` into an `innerHTML` template unescaped, and `fetchAll` fills
them from four places nobody in the browser controls: `/api/auth/integrations`
(`name`, `base_url`), the CalDAV and mail accounts (labels, URLs, hosts) and
`/api/mcp/servers` — where a server's name can be set by the agent through
`manage_mcp add`. The CSP stops an inline script; it does not stop a fake link
or a form drawn into Settings, which is the adversary here (`Law 17`): text a
model or a remote server chose, shown to an admin inside the one window where
they type secrets.

Driven, not grepped (`Law 20`): `fetchAll` and `renderCard` are cut out of the
shipped module with `tests/helpers/js_source`, beside the module's own `esc`
(which forwards to the canonical escaper through
`tests/helpers/esc_stub.ui_default_stub`), and run under node against a
`fetch` that answers every source with hostile text. What they return is parsed
by Python's HTML parser — element by element — and, where Chromium is present,
by a real browser with no CSP at all, which is the strict reading of "nothing
executes". The same treatment is checked on the module's siblings with the same
shape: the admin integration list, the reminder's mail-account menu and the
Shortcuts panel's key caps.
"""

import json
import shutil
import subprocess
from html.parser import HTMLParser
from pathlib import Path

import pytest

from tests.helpers.esc_stub import ui_default_stub
from tests.helpers.js_source import js_binding, js_definition
from tests.helpers.source_text import blank_text
from test_tool_effect_surfaces_js import _make_sandbox, _run  # noqa: E402

ROOT = Path(__file__).resolve().parents[1]
SETTINGS = ROOT / "static" / "js" / "settings.js"

pytestmark = pytest.mark.skipif(not shutil.which("node"), reason="node binary not on PATH")

# `&amp;` as typed: the old Remove button escaped `"` alone, so a name holding an
# entity came back from `dataset` as a different name in its confirmation.
HOSTILE_NAME = '<b>x</b><img src=x onerror="globalThis.__pwned=1"> R&amp;D'
HOSTILE_URL = 'https://h.example/"><a href="https://evil.example/">Sign in again</a>'
HOSTILE_ID = 'x"><form action="https://evil.example/"><input name="password"></form>'

_SHIM = r"""
import { installDom, Node } from './dom.js';
export const document = installDom();
export { Node };
"""


def _cut(*names: str, bindings=()) -> str:
    src = SETTINGS.read_text(encoding="utf-8")
    code = blank_text(src, "js")
    parts = []
    for name in names:
        at = code.find(f"async function {name}(")
        if at < 0:
            at = code.index(f"function {name}(")
        parts.append(js_definition(src, at))
    for name in bindings:
        parts.append(js_binding(src, name) + ";")
    return "\n".join(parts)


@pytest.fixture(scope="module")
def sandbox(tmp_path_factory):
    return _make_sandbox(tmp_path_factory.mktemp("intglist"), ROOT / "static" / "js" / "icons.js",
                         _SHIM, {"ui.js": ui_default_stub()})


class _Tree(HTMLParser):
    """Every element in a fragment: its tag, its attributes and its own text."""

    def __init__(self):
        super().__init__(convert_charrefs=True)
        self.elements, self._open = [], []

    def handle_starttag(self, tag, attrs):
        node = {"tag": tag, "attrs": dict(attrs), "text": ""}
        self.elements.append(node)
        if tag not in ("img", "input", "br", "hr", "polyline", "path", "line", "circle", "rect"):
            self._open.append(node)

    def handle_startendtag(self, tag, attrs):
        self.elements.append({"tag": tag, "attrs": dict(attrs), "text": ""})

    def handle_endtag(self, tag):
        for i in range(len(self._open) - 1, -1, -1):
            if self._open[i]["tag"] == tag:
                del self._open[i:]
                break

    def handle_data(self, data):
        if self._open:
            self._open[-1]["text"] += data


def _tree(html: str) -> list:
    p = _Tree()
    p.feed(html)
    return p.elements


#: Every tag a card is built from. Anything else in the output was drawn by data.
_CARD_TAGS = {"div", "span", "button", "svg", "polyline", "path", "rect", "line", "circle",
              "polygon", "ellipse", "g"}


_FETCH = r"""
const HOSTILE_NAME = %(name)s, HOSTILE_URL = %(url)s, HOSTILE_ID = %(id)s;
const answers = {
  '/api/auth/integrations': { integrations: [{ id: HOSTILE_ID, name: HOSTILE_NAME, base_url: HOSTILE_URL }] },
  '/api/calendar/config/accounts': { accounts: [{ id: 'c1', label: HOSTILE_NAME, url: HOSTILE_URL }] },
  '/api/contacts/config': { url: HOSTILE_URL },
  '/api/contacts/list': { contacts: [], count: 0 },
  '/api/email/accounts': { accounts: [{ id: 'e1', name: HOSTILE_NAME, from_address: HOSTILE_URL,
                                        imap_host: HOSTILE_NAME }] },
  '/api/mcp/servers': [{ id: 'm1', name: HOSTILE_NAME, status: 'error', error: HOSTILE_URL }],
  '/api/vault/config': {},
  '/api/tokens': [{ id: 't1', name: 'Codex Agent ' + HOSTILE_NAME, token_prefix: HOSTILE_NAME,
                    scopes: ['todos:read'] }],
  '/api/calendar/calendars': { calendars: [] },
};
globalThis.fetch = async (url) => ({ ok: true, json: async () => answers[url] });
""" % {"name": json.dumps(HOSTILE_NAME), "url": json.dumps(HOSTILE_URL), "id": json.dumps(HOSTILE_ID)}


def _cards(sandbox) -> list:
    out = _run(sandbox, "import uiModule from './ui.js';\n" + _FETCH
               + _cut("esc", "fetchAll", "renderCard", bindings=("INTG_TYPES",)) + "\n", """
        const items = await fetchAll();
        console.log(JSON.stringify({ cards: items.map((item) => ({ item, html: renderCard(item) })) }));
        """)
    return out["cards"]


def test_every_source_s_card_draws_its_name_and_detail_as_text(sandbox):
    """The row's `Verify`, widened to every source `fetchAll` reads: an MCP
    server — or an integration, a calendar, a mailbox, an agent token — named
    `<b>x</b>…` is listed as those characters, and its URL is a line of text,
    not a link."""
    cards = _cards(sandbox)
    kinds = sorted({c["item"]["type"] for c in cards})
    assert kinds == ["api", "caldav", "carddav", "codex", "email", "mcp"], kinds
    for card in cards:
        item, elements = card["item"], _tree(card["html"])
        drawn = sorted({e["tag"] for e in elements} - _CARD_TAGS)
        assert not drawn, f"the {item['type']} card drew {drawn} out of its data"
        [name] = [e for e in elements if e["attrs"].get("class") == "intg-card-open"]
        assert name["text"] == item["name"], (item["type"], name["text"])
        details = [e for e in elements if e["tag"] == "div" and e["text"] == (item["detail"] or "")]
        assert details, f"the {item['type']} card's detail is not its text: {card['html'][:400]}"


def test_the_card_s_attributes_hold_the_values_and_nothing_else(sandbox):
    """The id and the name ride in attributes (`data-intg-id`, `data-intg-name`)
    that the click and Remove handlers read back through `dataset`; an id that
    closes its quote must not open a form."""
    [api] = [c for c in _cards(sandbox) if c["item"]["type"] == "api"]
    elements = _tree(api["html"])
    assert not [e for e in elements if e["tag"] in ("form", "input", "a", "img", "b")]
    [card] = [e for e in elements if e["attrs"].get("class") == "intg-card"]
    assert card["attrs"]["data-intg-id"] == HOSTILE_ID
    assert card["attrs"]["data-intg-type"] == "api"
    [remove] = [e for e in elements if "intg-del-btn" in e["attrs"].get("class", "")]
    assert remove["attrs"]["data-intg-id"] == HOSTILE_ID
    assert remove["attrs"]["data-intg-name"] == HOSTILE_NAME


def test_the_admin_integration_list_escapes_its_ids(sandbox):
    """A sibling with the same shape: the admin panel's own integration list
    escaped the name and URL and left the id raw in two attributes."""
    out = _run(sandbox, "import uiModule from './ui.js';\n" + _FETCH + r"""
const drawn = [];
const listEl = { set innerHTML(v) { drawn.push(v); }, get innerHTML() { return drawn.at(-1) || ''; },
                 querySelectorAll: () => [] };
function startEdit() {} function doDelete() {}
""" + _cut("esc", "renderList") + "\n", """
        await renderList();
        console.log(JSON.stringify({ html: drawn.at(-1) }));
        """)
    elements = _tree(out["html"])
    assert not [e for e in elements if e["tag"] in ("form", "input", "a", "img", "b")], out["html"]
    ids = [e["attrs"]["data-id"] for e in elements if "data-id" in e["attrs"]]
    assert ids == [HOSTILE_ID, HOSTILE_ID]


def test_the_reminder_s_mail_menu_escapes_its_account_ids(sandbox):
    out = _run(sandbox, "import uiModule from './ui.js';\n" + r"""
const emailAcctSel = { innerHTML: '', value: '' };
const emailAccounts = [{ id: %s, name: 'Work', is_default: true }];
""" % json.dumps(HOSTILE_ID) + _cut("esc", "populateReminderEmailAccounts") + "\n", """
        populateReminderEmailAccounts();
        console.log(JSON.stringify({ html: emailAcctSel.innerHTML }));
        """)
    elements = _tree(out["html"])
    assert [e["tag"] for e in elements] == ["option"], out["html"]
    assert elements[0]["attrs"]["value"] == HOSTILE_ID


def test_a_stored_key_combo_is_drawn_as_key_caps_and_nothing_else(sandbox):
    out = _run(sandbox, "import uiModule from './ui.js';\n" + _cut("esc", "_formatKeyCaps") + "\n", """
        console.log(JSON.stringify({ ok: _formatKeyCaps('ctrl+k'),
                                     bad: _formatKeyCaps('ctrl+<img src=x onerror=alert(1)>') }));
        """)
    assert out["ok"] == "<kbd>Ctrl</kbd><kbd>K</kbd>"
    assert [e["tag"] for e in _tree(out["bad"])] == ["kbd", "kbd"], out["bad"]


# ── in a browser, with no CSP: nothing executes ─────────────────────────────


def _chromium():
    node = shutil.which("node")
    probe = subprocess.run(
        [node, "-e", "const { chromium } = require('playwright'); const fs = require('fs');"
                     "process.stdout.write(fs.existsSync(chromium.executablePath()) ? 'yes' : '');"],
        capture_output=True, text=True, timeout=60)
    return probe.returncode == 0 and probe.stdout == "yes"


@pytest.mark.skipif(not shutil.which("node") or not _chromium(),
                    reason="playwright or its Chromium is not installed")
def test_in_a_browser_without_a_csp_the_hostile_names_run_nothing(sandbox, tmp_path):
    """The strict reading of the row: every card `fetchAll` builds, written into
    a page that has no Content-Security-Policy, draws no element out of its data
    and runs no handler."""
    cards = _cards(sandbox)
    script = tmp_path / "probe.js"
    script.write_text(r"""
const { chromium } = require('playwright');
(async () => {
  const browser = await chromium.launch({ args: ['--no-sandbox'] });
  const page = await browser.newPage();
  await page.setContent('<!doctype html><div id="list"></div>');
  const out = await page.evaluate(async (cards) => {
    const list = document.getElementById('list');
    list.innerHTML = cards.join('');
    await new Promise((r) => setTimeout(r, 300));
    return {
      pwned: globalThis.__pwned || 0,
      drawn: list.querySelectorAll('img, a, form, input, b, script').length,
      names: [...list.querySelectorAll('.intg-card-open')].map((b) => b.textContent),
    };
  }, %s);
  await browser.close();
  process.stdout.write(JSON.stringify(out));
})().catch((e) => { console.error(e); process.exit(1); });
""" % json.dumps([c["html"] for c in cards]))
    proc = subprocess.run(["node", str(script)], capture_output=True, text=True, timeout=120)
    assert proc.returncode == 0, proc.stderr
    out = json.loads(proc.stdout)
    assert out["pwned"] == 0, "a hostile name ran its handler"
    assert out["drawn"] == 0
    assert out["names"] == [c["item"]["name"] for c in cards]
