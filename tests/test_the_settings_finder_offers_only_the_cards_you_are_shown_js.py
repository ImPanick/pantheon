# SPDX-License-Identifier: AGPL-3.0-or-later
"""`B1570` — the Settings finder offers a viewer only the words of cards they are shown.

`B1563` gave Settings three audiences: a panel can be an operator's while cards
inside it stay an admin's (`admin-only` in the markup, hidden by
`syncAdminVisibility()`). `harvestSettingsControlText` (`settings/registry.js`)
read every control in a panel regardless, so an operator typing *export* or
*danger* was sent to System, where Data Backup and the Danger Zone are hidden.

Driven under node against the real `registry.js` and `search.js` (`Law 20`),
over a DOM stub whose elements carry the classes and parents the real markup
gives them; the operator's walk through the real app is in
`tests/test_an_operator_finds_the_operators_settings.py`.
"""

import json
import shutil
import subprocess
import textwrap
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
SETTINGS_DIR = ROOT / "static" / "js" / "settings"

pytestmark = pytest.mark.skipif(not shutil.which("node"), reason="node binary not on PATH")

# The System panel's shape: a card everyone it is shown to may use, a card
# only an admin is shown, a `<details>` inside an admin card, and an
# `operator-only` row in a panel everyone is shown.
_STUB = r"""
const node = (cls = [], parent = null, text = '') => ({
  classList: { contains: (c) => cls.includes(c) },
  parentElement: parent,
  textContent: text,
  getAttribute: () => null,
});
const system = node();
system.dataset = { settingsPanel: 'system' };
const webhooks = node(['admin-card'], system);
const backup = node(['admin-card', 'admin-only'], system);
const danger = node(['admin-card', 'admin-danger-card', 'admin-only'], system);
const usage = node(['usage-panel', 'admin-only'], node(['admin-card'], system));
const opInsideAdmin = node(['operator-only'], backup);
system.querySelectorAll = () => [
  node([], webhooks, 'Webhooks'),
  node([], backup, 'Data Backup'), node([], backup, 'Export Data'),
  node([], danger, 'Danger Zone'),
  node([], usage, 'Usage over time'),
  node([], opInsideAdmin, 'Restore archive'),
];
const appearance = node();
appearance.dataset = { settingsPanel: 'appearance' };
const spool = node(['operator-only'], appearance);
appearance.querySelectorAll = () => [
  node([], appearance, 'Chat header'),
  node([], spool, 'Spool depth'),
];
const modal = { querySelectorAll: (sel) => (sel.includes('data-settings-panel') ? [system, appearance] : []) };
const VIEWERS = {
  nobody: undefined,
  member: { isAdmin: false, runsInstance: false },
  operator: { isAdmin: false, runsInstance: true },
  admin: { isAdmin: true, runsInstance: false },
};
"""


def _run(tmp_path, script: str) -> dict:
    for name in ("registry.js", "search.js"):
        shutil.copy2(SETTINGS_DIR / name, tmp_path / name)
    entry = tmp_path / "case.mjs"
    entry.write_text(
        "import { harvestSettingsControlText, searchSettingsPanels } from './registry.js';\n"
        "import { controlTextFor } from './search.js';\n"
        + _STUB + textwrap.dedent(script), encoding="utf-8")
    proc = subprocess.run(["node", str(entry)], cwd=tmp_path, capture_output=True, text=True,
                          timeout=30)
    assert proc.returncode == 0, proc.stderr
    return json.loads(proc.stdout.strip().splitlines()[-1])


def _finds(tmp_path) -> dict:
    return _run(tmp_path, """
        const out = {};
        for (const [who, viewer] of Object.entries(VIEWERS)) {
          const controlText = controlTextFor(modal, viewer || {});
          out[who] = {};
          for (const q of ['export', 'danger', 'usage', 'restore', 'webhooks', 'spool', 'chat header']) {
            out[who][q] = searchSettingsPanels(q, { ...(viewer || {}), controlText }).map((p) => p.id);
          }
        }
        console.log(JSON.stringify(out));
    """)


def test_an_operator_is_not_sent_to_a_card_only_an_admin_is_shown(tmp_path):
    """The row's `Verify:` — an operator's search for *export* finds nothing
    (here: nothing on System, the panel whose Export lives in an admin card)."""
    op = _finds(tmp_path)["operator"]
    for q in ("export", "danger", "usage", "restore"):
        assert op[q] == [], (q, op)
    assert op["webhooks"] == ["system"], op
    assert op["spool"] == ["appearance"], op


def test_an_admin_still_finds_every_card(tmp_path):
    admin = _finds(tmp_path)["admin"]
    for q in ("export", "danger", "usage", "restore", "webhooks"):
        assert admin[q] == ["system"], (q, admin)
    assert admin["spool"] == ["appearance"], admin


def test_a_member_finds_only_what_everyone_is_shown(tmp_path):
    found = _finds(tmp_path)
    for who in ("member", "nobody"):
        assert found[who]["spool"] == [], (who, found[who])
        assert found[who]["chat header"] == ["appearance"], (who, found[who])
        assert found[who]["export"] == [], (who, found[who])


def test_the_harvest_with_no_viewer_is_the_least_one(tmp_path):
    """A caller that forgets to say who is asking finds less, never more."""
    out = _run(tmp_path, """
        console.log(JSON.stringify(harvestSettingsControlText(modal)));
    """)
    assert out["system"] == "webhooks", out
    assert out["appearance"] == "chat header", out


def test_one_modal_keeps_one_cache_per_viewer(tmp_path):
    """The palette and the finder share `controlTextFor`'s cache: an admin's
    harvest taken first is not what an operator searches afterwards."""
    out = _run(tmp_path, """
        const first = controlTextFor(modal, VIEWERS.admin).system;
        const then = controlTextFor(modal, VIEWERS.operator).system;
        console.log(JSON.stringify({ first, then }));
    """)
    assert "export data" in out["first"], out
    assert out["then"] == "webhooks", out
