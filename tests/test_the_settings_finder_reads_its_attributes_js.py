# SPDX-License-Identifier: AGPL-3.0-or-later
"""`B944` — the Settings finder harvests the three attributes it says it reads.

`harvestSettingsControlText` (`static/js/settings/registry.js`, `H15`) looped
`for (const attr of ('placeholder', 'title', 'data-search-text'))` — a comma
expression, which is the string `'data-search-text'`, so the loop asked every
control for attributes named `d`, `a`, `t`, `a`, `-`, `s`, … and harvested none
of the three. A control findable only by its placeholder or its tooltip was
unfindable in the Settings finder and in the command palette, which reads the
same harvest (`controlTextFor`, `P9-01`).

Measured on the shipped markup: the Networks panel's allow-list box has
`ipconfig` in its placeholder and nowhere else in the panel; the Workstation
panel's pin field has `fingerprint` in its placeholder and only in prose a
person would not search for. Both words now find their panel.

Driven under node against the real `registry.js` and `search.js` (`Law 20`),
over an element stub that records which attribute names were asked for.
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

# A panel whose only words are in the three attributes. Each element answers
# `getAttribute` from its own table and records what it was asked.
_STUB = r"""
const asked = new Set();
const el = (text, attrs) => ({
  textContent: text,
  getAttribute(name) { asked.add(name); return Object.prototype.hasOwnProperty.call(attrs, name) ? attrs[name] : null; },
});
const PANELS = {
  networks: [
    el('', { placeholder: 'docker\ngit\nipconfig' }),
    el('', { title: 'Paste the certificate fingerprint' }),
    el('', { 'data-search-text': 'loopback lan tailnet' }),
  ],
  appearance: [el('Incognito Mode', {})],
};
const modal = {
  querySelectorAll(sel) {
    if (!sel.includes('data-settings-panel')) return [];
    return Object.entries(PANELS).map(([id, els]) => ({
      dataset: { settingsPanel: id },
      querySelectorAll: () => els,
    }));
  },
};
"""


def _run(tmp_path, script: str) -> dict:
    for name in ("registry.js", "search.js"):
        shutil.copy2(SETTINGS_DIR / name, tmp_path / name)
    entry = tmp_path / "case.mjs"
    entry.write_text(
        "import { harvestSettingsControlText, searchSettingsPanels } from './registry.js';\n"
        + _STUB + textwrap.dedent(script), encoding="utf-8")
    proc = subprocess.run(["node", str(entry)], cwd=tmp_path, capture_output=True, text=True,
                          timeout=30)
    assert proc.returncode == 0, proc.stderr
    return json.loads(proc.stdout.strip().splitlines()[-1])


def test_the_harvest_asks_for_the_three_attributes_by_name(tmp_path):
    out = _run(tmp_path, """
        harvestSettingsControlText(modal);
        console.log(JSON.stringify({ asked: [...asked].sort() }));
    """)
    assert out["asked"] == ["data-search-text", "placeholder", "title"], (
        f"asked for {out['asked']} — a comma expression iterates the last "
        "string's characters"
    )


def test_a_word_only_in_an_attribute_is_harvested(tmp_path):
    out = _run(tmp_path, """
        console.log(JSON.stringify(harvestSettingsControlText(modal)));
    """)
    for word in ("ipconfig", "fingerprint", "tailnet"):
        assert word in out["networks"], (word, out["networks"])
    assert out["appearance"] == "incognito mode"


def test_the_finder_finds_the_panel_by_a_placeholder_or_a_tooltip(tmp_path):
    """The row's `Verify`: a word that appears only in a field's placeholder
    brings its panel back — through `searchSettingsPanels`, the one search the
    Settings finder and the palette both run."""
    out = _run(tmp_path, """
        const controlText = harvestSettingsControlText(modal);
        const hits = {};
        for (const q of ['ipconfig', 'fingerprint', 'tailnet']) {
          hits[q] = searchSettingsPanels(q, { isAdmin: true, controlText }).map((p) => p.id);
        }
        console.log(JSON.stringify(hits));
    """)
    assert out == {"ipconfig": ["networks"], "fingerprint": ["networks"], "tailnet": ["networks"]}


def test_the_palette_s_cache_carries_the_attribute_words(tmp_path):
    """`controlTextFor` (`search.js`) is what the palette reads; it is the same
    harvest, cached per modal."""
    out = _run(tmp_path, """
        const { controlTextFor } = await import('./search.js');
        console.log(JSON.stringify(controlTextFor(modal)));
    """)
    assert "ipconfig" in out["networks"]
