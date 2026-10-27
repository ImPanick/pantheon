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
deploy switches, the shared knowledge index, the data export, the danger zone,
usage and the eval builder — are `admin-only`. `admin.js` binds and loads the
operator's panels for an operator and nothing else.

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
    assert {"Webhooks", "Terminal Logs", "Storage cleanup", "Uploaded files"} <= set(system["cards"]), system
    assert {"Switches a deploy can also set", "Knowledge index", "Data Backup",
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
                  "GET /api/diagnostics/evals"):
        assert op["answered"].get(asked) == 200, (asked, op["answered"])
    for never in ("GET /api/auth/users", "GET /api/tokens", "GET /api/mcp/servers",
                  "GET /api/vault/config", "GET /api/personal", "GET /api/diagnostics/runs"):
        assert never not in op["answered"], never


def test_a_member_still_asks_for_nothing_only_an_admin_or_an_operator_may_have(walked):
    assert walked["member"]["refused"] == [], walked["member"]["refused"]
