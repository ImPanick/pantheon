# SPDX-License-Identifier: AGPL-3.0-or-later
"""`B1206` — the command palette names a Settings group only as the nav does.

A Settings row in Ctrl+K carried its group's `label` as a hint: *Models & AI*,
*Communications*, *Experience*, *Administration* (`SETTINGS_GROUPS`,
`static/js/settings/registry.js`). The Settings window's nav draws one heading
over its groups, *Admin*, and sets the other four apart with a rule
(`renderSettingsNav`) — so the palette named four groups a person never sees,
and the fifth by a word the nav does not use. The Settings window's own finder
did the same (`settings/search.js`, "Workstation · Administration").

Both now read `settingsGroupHeading`, the heading the nav draws or nothing,
named only to a viewer whose nav shows it (`SET-U-13`).

Driven under node (`Law 20`): the real palette in `P9-01`'s sandbox, with the
real `settings/registry.js`, and the real `settings/navigation.js` drawing the
nav into the Settings markup parsed out of `index.html`. Every panel is looked
up by its own name, as an admin and as a member, and every hint the palette
shows is a heading that viewer's nav draws — or none.
"""

import json
import shutil

import pytest

from test_the_search_box_is_the_command_palette_js import (  # noqa: E402
    JS, SEARCH_JS, _REAL, _SHIM, _STUBS, _markup, _preamble, _slash_stub)
from test_tool_effect_surfaces_js import _copy_unstubbed_imports, _make_sandbox, _run  # noqa: E402

pytestmark = pytest.mark.skipif(not shutil.which("node"), reason="node binary not on PATH")


@pytest.fixture(scope="module")
def box(tmp_path_factory):
    stubs = dict(_STUBS)
    stubs["slashCommands.js"] = _slash_stub()
    shim = _SHIM.replace("__MARKUP__", json.dumps(_markup()))
    sandbox = _make_sandbox(tmp_path_factory.mktemp("palette-b1206"), SEARCH_JS, shim, stubs)
    for rel in _REAL + ("settings/navigation.js",):
        (sandbox / rel).parent.mkdir(parents=True, exist_ok=True)
        shutil.copy(JS / rel, sandbox / rel)
        _copy_unstubbed_imports(sandbox, JS / rel, stubs)
    return sandbox


_SCRIPT = """
const R = await import('./settings/registry.js');
const N = await import('./settings/navigation.js');
N.renderSettingsNav($('settings-modal'));
const drawn = (admin) => $('settings-modal').querySelectorAll('.settings-sidebar-label')
  .filter((h) => admin || !h.classList.contains('admin-only')).map((h) => h.textContent);
const hints = (admin) => {
  // `viewerIsAdmin`: an admin is a page that said `_isAdmin`; a member's said nothing.
  if (admin) globalThis._isAdmin = true; else delete globalThis._isAdmin;
  const seen = {};
  for (const panel of R.SETTINGS_PANELS) {
    open(); type(panel.label);
    const group = read().groups.find((g) => g.label === 'Settings');
    for (const o of (group ? group.options : [])) seen[o.label] = o.detail;
    Search.closeSearch();
  }
  return seen;
};
const admin = hints(true);
const member = hints(false);
console.log(JSON.stringify({ admin, member, adminHeads: drawn(true), memberHeads: drawn(false),
  labels: R.SETTINGS_GROUPS.map((g) => g.label) }));
"""


def test_every_settings_hint_is_a_heading_the_nav_draws(box):
    out = _run(box, "globalThis._pantheonKeybinds = undefined;\n" + _preamble(), _SCRIPT)
    assert out["adminHeads"] == ["Admin"], "the nav's one heading moved"
    assert out["memberHeads"] == []
    assert len(out["admin"]) >= 10, "the admin was offered too few panels to say anything"
    for viewer, heads in (("admin", out["adminHeads"]), ("member", out["memberHeads"])):
        for panel, hint in out[viewer].items():
            assert hint in (None, *heads), f"{viewer}: '{panel}' was hinted '{hint}', which the nav never shows"
    # The four headings the nav never drew are named nowhere.
    shown = set(out["admin"].values()) | set(out["member"].values())
    assert not shown & {"Models & AI", "Communications", "Experience", "Administration"}
    # And the one it does draw is still said, to someone who sees it.
    assert out["admin"]["Networks"] == "Admin"
