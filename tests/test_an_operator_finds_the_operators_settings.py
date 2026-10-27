# SPDX-License-Identifier: AGPL-3.0-or-later
"""`B1563` — an operator is shown Settings as an operator, not as a member.

`B683` gave the instance an operator: a person an admin lets run it
(`can_run_instance`, per person or through a role), let through by
`core.middleware.require_operator` on the model endpoints, the Forge's serving,
the embeddings, diagnostics and logs, webhooks and uploaded files. Settings knew
two viewers. `static/js/settings/registry.js` marked every panel holding those
routes `adminOnly`, and `settings.js` (`viewerIsAdmin`, `syncAdminVisibility`)
hid them from anyone not an admin — so the routes opened to an operator were
offered on no screen, and `admin.js` asked for none of them.

Now the registry knows three audiences (`panelAudience`): Add Models, Added
Models, Forge, Embeddings and System are the operator's too, and inside them
the cards whose writes are still an admin's — the model-hubs switch, the
deploy switches, the data export, the danger zone, usage and the eval builder —
are `admin-only` (the shared knowledge index was too, until `B1568`).
`admin.js` binds and loads the operator's panels for an operator and nothing
else.

Driven in Chromium against the real app (`Law 20`), the row's `Verify:`: an
admin defines an `operator` role granting `can_run_instance` and gives it to a
person; that person opens Settings and walks the panels; every `/api/` answer
is recorded. A member is walked beside them.
"""
from __future__ import annotations

import json
import os
import subprocess
from pathlib import Path

import pytest

from test_the_command_palette_in_a_browser import NODE, _SKIP, app_url  # noqa: F401,E402

pytestmark = pytest.mark.skipif(NODE is None, reason=_SKIP or "")

ROOT = Path(__file__).resolve().parents[1]

_SCRIPT = r"""
const { chromium } = require('playwright');
const BASE = process.argv[2];
(async () => {
  const browser = await chromium.launch({ args: ['--no-sandbox'] });
  const out = { errors: [] };
  const admin = { username: 'boss', password: 'boss-pass-123' };
  const people = { operator: { username: 'olga', password: 'olga-pass-123' },
                   member: { username: 'mona', password: 'mona-pass-123' } };
  const setup = await browser.newContext();
  const r = setup.request;
  await r.post(BASE + '/api/auth/setup', { data: admin });
  await r.post(BASE + '/api/auth/login', { data: { ...admin, remember: true } });
  out.made = [];
  for (const p of Object.values(people)) {
    out.made.push((await r.post(BASE + '/api/auth/users', { data: { ...p, is_admin: false } })).status());
  }
  // The row's words: an `operator`-role user.
  out.role = (await r.put(BASE + '/api/auth/roles/operator', { data: { overrides: { can_run_instance: true } } })).status();
  out.assigned = (await r.put(BASE + '/api/auth/users/olga/role', { data: { role: 'operator' } })).status();
  await setup.close();

  const walk = async (who) => {
    const seen = { refused: [], answered: {}, nav: [], cards: {} };
    const context = await browser.newContext({ viewport: { width: 1440, height: 900 } });
    await context.addInitScript(() => {
      try { localStorage.setItem('pantheon-ui-visibility', JSON.stringify({ 'first-run-tours': false })); } catch (_) {}
    });
    const page = await context.newPage();
    page.on('pageerror', (e) => out.errors.push(who + ': ' + String((e && e.message) || e)));
    page.on('response', (res) => {
      const u = new URL(res.url());
      if (!u.pathname.startsWith('/api/')) return;
      const key = res.request().method() + ' ' + u.pathname;
      seen.answered[key] = res.status();
      if (res.status() === 403) seen.refused.push(key);
    });
    await page.request.post(BASE + '/api/auth/login', { data: { ...people[who], remember: true } });
    await page.goto(BASE + '/', { waitUntil: 'load' });
    await page.waitForFunction(() => window.__pantheonAppStarted === true, null, { timeout: 90000 });
    // `B1521`'s way: wait on each condition, by name, never on a quiet
    // network — a lazy panel's request can start after the network went idle.
    const until = async (key, ms = 20000) => {
      const t0 = Date.now();
      while (!(key in seen.answered) && Date.now() - t0 < ms) await page.waitForTimeout(100);
      if (!(key in seen.answered)) out.errors.push(`${who}: never asked ${key}`);
    };
    // The status names the viewer before anything is judged by it.
    await until('GET /api/auth/status');
    await page.click('#user-bar-settings');
    // Account is everyone's, so it is the row every viewer's nav shows.
    await page.waitForSelector('#settings-modal .settings-nav-item[data-settings-tab="account"]', { state: 'visible', timeout: 30000 });
    const shown = (sel) => page.evaluate((s) => [...document.querySelectorAll(s)]
      .filter((n) => n.offsetParent !== null && getComputedStyle(n).display !== 'none')
      .map((n) => (n.dataset.settingsTab || n.textContent || '').trim()), sel);
    seen.nav = await shown('#settings-modal .settings-nav-item');
    seen.headings = await shown('#settings-modal .settings-sidebar-label');
    // `B1570`. The Settings finder, typed into as a person types: what each
    // word offers this viewer, and the line it says when it offers nothing.
    seen.search = {};
    for (const q of ['export', 'danger', 'webhook']) {
      await page.fill('#settings-nav-search', q);
      seen.search[q] = await page.evaluate(() => {
        const box = document.getElementById('settings-nav-search-results');
        return { found: [...box.querySelectorAll('[data-settings-search-result]')].map((b) => b.dataset.settingsSearchResult),
                 said: ((box.querySelector('.settings-search-empty') || {}).textContent || '') };
      });
    }
    await page.fill('#settings-nav-search', '');
    // Each panel, and the answer that says its loader ran.
    const loads = { services: 'GET /api/model-endpoints', 'added-models': 'GET /api/model-endpoints',
                    forge: 'GET /api/auth/settings', embeddings: 'GET /api/embeddings/endpoint',
                    system: 'GET /api/diagnostics/logs' };
    for (const [tab, key] of Object.entries(loads)) {
      const button = page.locator(`#settings-modal .settings-nav-item[data-settings-tab="${tab}"]`);
      if (!(await button.isVisible())) continue;
      await button.click();
      await page.waitForSelector(`[data-settings-panel="${tab}"]:not(.hidden)`, { timeout: 10000 });
      await until(key);
      seen.cards[tab] = await page.evaluate((t) => {
        const panel = document.querySelector(`[data-settings-panel="${t}"]`);
        const visible = (n) => { for (let x = n; x && x !== panel; x = x.parentElement) {
          if (getComputedStyle(x).display === 'none') return false; } return true; };
        return {
          cards: [...panel.querySelectorAll('.admin-card > h2')].filter(visible)
            .map((h) => h.textContent.trim().replace(/\s+/g, ' ')),
          hidden: [...panel.querySelectorAll('.admin-card > h2')].filter((h) => !visible(h))
            .map((h) => h.textContent.trim().replace(/\s+/g, ' ')),
          details: [...panel.querySelectorAll('details > summary')].filter(visible)
            .map((s) => s.textContent.trim()),
          doors: [...panel.querySelectorAll('[data-forge-door]')].filter(visible)
            .map((b) => b.dataset.forgeDoor),
        };
      }, tab);
    }
    // `B1568`. The Knowledge index card, used as an operator uses it:
    // Reload, Add Directory, and Remove on a directory the list draws.
    if (seen.cards.system && seen.cards.system.cards.includes('Knowledge index')) {
      const reloadKey = 'POST /api/personal/reload';
      await page.click('#adm-ragReloadBtn');
      await until(reloadKey);
      await page.fill('#adm-ragDirInput', 'notes');
      await page.click('#adm-ragAddDirBtn');
      await until('POST /api/personal/add_directory');
      seen.rag = await page.evaluate(() => ({
        dirs: [...document.querySelectorAll('#adm-ragDirList [data-adm-rag-dir]')].map((b) => b.dataset.admRagDir),
        files: [...document.querySelectorAll('#adm-ragFileList [data-adm-rag-file]')].map((b) => b.dataset.admRagFile),
        status: (document.getElementById('adm-ragStatus') || {}).textContent || '',
      }));
      const removable = page.locator('#adm-ragDirList [data-adm-rag-dir]').first();
      if (await removable.count()) {
        await removable.click();
        await page.click('#styled-confirm-ok');
        await until('DELETE /api/personal/remove_directory');
      }
    }
    // Diagnostics' own panels, opened as a person opens them.
    if (seen.cards.system) {
      for (const [id, key] of [['evals-panel', 'GET /api/diagnostics/evals'],
                               ['auth-audit-panel', 'GET /api/diagnostics/auth-events']]) {
        await page.click(`#${id} > summary`);
        await until(key);
      }
    }
    // The MCP & Integrations room, which mounts the admin's lists. What is
    // asserted is an absence, which no condition can wait for: the room's own
    // first answer, and a beat after it for anything it would have asked next.
    await page.evaluate(() => { try { window.settingsModule && window.settingsModule.open('integrations'); } catch (_) {} });
    await page.waitForTimeout(2500);
    await context.close();
    return seen;
  };
  out.operator = await walk('operator');
  out.member = await walk('member');
  console.log(JSON.stringify(out));
  await browser.close();
})().catch((e) => { console.error(e); process.exit(1); });
"""


@pytest.fixture(scope="module")
def file_database(tmp_path_factory):
    before = os.environ.get("DATABASE_URL")
    os.environ["DATABASE_URL"] = "sqlite:///" + str(tmp_path_factory.mktemp("operator-db") / "app.db")
    yield
    if before is None:
        os.environ.pop("DATABASE_URL", None)
    else:
        os.environ["DATABASE_URL"] = before


@pytest.fixture(scope="module")
def walked(file_database, app_url, tmp_path_factory):  # noqa: F811
    script = tmp_path_factory.mktemp("operator-pw") / "operator.cjs"
    script.write_text(_SCRIPT, encoding="utf-8")
    proc = subprocess.run([NODE, str(script), app_url], capture_output=True, text=True,
                          timeout=600, cwd=str(ROOT))
    assert proc.returncode == 0, proc.stderr[-4000:]
    return json.loads(proc.stdout.strip().splitlines()[-1])


OPERATORS = ["services", "added-models", "forge", "embeddings", "system"]
ADMINS = ["ai", "search", "reminders", "tools", "users", "networks", "agents"]


def test_the_premise_an_operator_role_was_made_and_given(walked):
    assert walked["made"] == [200, 200] and walked["role"] == 200 and walked["assigned"] == 200, walked
    assert walked["errors"] == [], walked["errors"]


def test_an_operator_finds_the_operators_panels_and_none_of_the_admins(walked):
    """The row's `Verify:`, first half — Added Models, Embeddings, the Forge's
    serving and Diagnostics are in an operator's Settings."""
    nav = walked["operator"]["nav"]
    assert set(OPERATORS) <= set(nav), nav
    assert not set(ADMINS) & set(nav), nav
    assert walked["operator"]["headings"] == ["Admin"], walked["operator"]["headings"]


def test_a_member_is_shown_what_a_member_was_shown(walked):
    nav = walked["member"]["nav"]
    assert not (set(OPERATORS) | set(ADMINS)) & set(nav), nav
    assert walked["member"]["headings"] == [], walked["member"]["headings"]


def test_inside_the_operators_panels_only_the_admins_cards_are_hidden(walked):
    cards = walked["operator"]["cards"]
    forge = cards["forge"]
    assert forge["hidden"] == ["Hugging Face and Ollama"], forge
    assert "forge:Serve" in forge["doors"] and "settings:tools" not in forge["doors"], forge
    system = cards["system"]
    # `B1568`: the Knowledge index is the operator's — its list asked
    # `require_admin` while every write on it asked `require_operator`.
    assert {"Webhooks", "Terminal Logs", "Storage cleanup", "Uploaded files",
            "Knowledge index"} <= set(system["cards"]), system
    assert {"Switches a deploy can also set", "Data Backup",
            "Danger Zone", "How long records are kept"} <= set(system["hidden"]), system
    assert "Usage over time" not in system["details"] and "Add a case" not in system["details"], system
    assert "Evals — did that change help?" in system["details"], system


def test_an_operator_is_refused_nothing_and_answered_what_they_were_given(walked):
    """The row's `Verify:`, second half: none of Users, Tokens, MCP or Vault —
    the admin's lists are not asked for, so nothing is refused — and the
    operator's routes answer."""
    op = walked["operator"]
    assert op["refused"] == [], op["refused"]
    for asked in ("GET /api/model-endpoints", "GET /api/embeddings/endpoint",
                  "GET /api/diagnostics/logs", "GET /api/webhooks", "GET /api/upload/stats",
                  "GET /api/diagnostics/evals", "GET /api/personal"):
        assert op["answered"].get(asked) == 200, (asked, op["answered"])
    # `B1568` moved `GET /api/personal` from this list to the one above.
    for never in ("GET /api/auth/users", "GET /api/tokens", "GET /api/mcp/servers",
                  "GET /api/vault/config", "GET /api/diagnostics/runs"):
        assert never not in op["answered"], never


def test_an_operator_lists_the_knowledge_index_and_works_it(walked):
    """`B1568`'s `Verify:` — an operator opens System, sees the indexed files
    listed, and Reload and Add Directory answer them rather than refuse.
    Remove is asked when the list draws a directory; whatever the index can do
    on this machine (no embedder in a test install), the gate is not the
    answer."""
    op = walked["operator"]
    assert op["answered"].get("GET /api/personal") == 200, op["answered"]
    assert op["answered"].get("POST /api/personal/reload") == 200, op["answered"]
    added = op["answered"].get("POST /api/personal/add_directory")
    assert added is not None and added not in (401, 403), op["answered"]
    removed = op["answered"].get("DELETE /api/personal/remove_directory")
    assert removed not in (401, 403), op["answered"]
    assert "rag" in op and op["rag"]["status"], op.get("rag")


def test_a_member_still_asks_for_nothing_only_an_admin_or_an_operator_may_have(walked):
    assert walked["member"]["refused"] == [], walked["member"]["refused"]


def test_an_operators_settings_search_finds_no_card_they_are_not_shown(walked):
    """`B1570`'s `Verify:` — the harvest read every control in a panel, the
    admin's cards inside an operator's panel included, so *export* (Data
    Backup) and *danger* (the Danger Zone) sent an operator to System, where
    both cards are hidden. Webhooks, a card of theirs on the same panel, still
    finds it.

    The row said *finds nothing*; measured, *export* is also the hint under
    Appearance's *Chat header* toggle (*Model name & export above chat*), a
    control everyone is shown, so the operator is offered exactly what a
    member is offered for it — Appearance, and not System."""
    search = walked["operator"]["search"]
    member = walked["member"]["search"]
    assert "system" not in search["export"]["found"], search
    assert search["export"]["found"] == member["export"]["found"] == ["appearance"], (search, member)
    assert search["danger"] == {"found": [], "said": "No settings found"}, search
    assert search["webhook"]["found"] == ["system"], search
    assert member["webhook"]["found"] == [], member
