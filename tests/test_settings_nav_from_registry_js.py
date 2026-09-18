# SPDX-License-Identifier: AGPL-3.0-or-later
"""`P9-02` — the Settings navigation, drawn from the registry that describes it.

Driven under node against the real modules, in the sandbox pattern
`tests/test_tool_effect_surfaces_js.py` owns — the shim, the sandbox builder and
the runner are imported from that file rather than copied (`Law 14`).

**The row's premise, re-measured 2026-09-18 — and the row told me how.** It says
*"two sources of truth for one information architecture … there is also a
`getSettingsRegistryIssues()` self-check that diffs registry against DOM — run it
while you work."* Running it on the shipped tree returns a finding:

    DOM tab missing from registry: networks
    DOM panel missing from registry: networks

**Fifteen tabs and fifteen panels in `static/index.html`; fourteen entries in the
registry.** The missing one is `P17-09`'s network allowlist — the panel `Law 16`
is enforced from — and because the registry is what Settings search reads, that
panel was **unfindable by any word, including its own name**. The self-check had
been saying so into `console.warn` on every init since it was written, which is
`Law 15` in the tooling rather than in the product: a check whose output nobody
reads is not a check.

So the divergence the row predicted had already happened, in the direction that
costs the most: the newest panel is the one that goes missing, because the
registry is the copy a new panel's author does not know about.

**What this pins, and why each is a defect if it breaks:**

  * **the nav is generated, and generated from the registry** — fifteen buttons
    in registry order, with the registry's labels;
  * **the class name and the data attribute did not move.** Five modules query
    them — `slashCommands.js` (nine selectors, for the tour), `calendar.js`
    (four), `admin.js`, `emailLibrary.js`, `settings.js` — and the stylesheet
    keys off both. This is the row's own stated constraint;
  * **`admin-only` still marks the admin tabs**, because `syncAdminVisibility()`
    hides by that class and nothing else;
  * **`networks` is admin-only and NOT admin-controlled.** Every other
    Administration panel is `controller: 'admin'`, which routes the click to
    `window.adminModule.open(tab)`; `admin.js` has no case for `networks` and
    `settings.js` draws it itself. Copying its neighbours would have sent the
    click somewhere that does not draw the panel — a control that looks right
    and does nothing;
  * **the nav is drawn at module evaluation, not in `initAll()`.** Five call
    sites open Settings without going through `settingsModule.open()`;
  * **the self-check now reports where a person can see it.**
"""

import json
import re
import shutil
from pathlib import Path

import pytest

from test_a_draft_skill_is_uncatalogued_not_inactive import js_function  # noqa: E402
from test_tool_effect_surfaces_js import _DOM, _run  # noqa: E402
from tests.helpers.source_text import blank_text  # B290

ROOT = Path(__file__).resolve().parents[1]
JS = ROOT / "static" / "js" / "settings"
REGISTRY = JS / "registry.js"
NAVIGATION = JS / "navigation.js"
SETTINGS_JS = ROOT / "static" / "js" / "settings.js"
INDEX = ROOT / "static" / "index.html"
STYLE = ROOT / "static" / "style.css"

pytestmark = pytest.mark.skipif(not shutil.which("node"), reason="node binary not on PATH")


_SHIM = r"""
import { installDom, Node } from './dom.js';
export const document = installDom();
export { Node };

/** The Settings modal, reduced to the parts the navigation needs. */
export function modal(panelIds) {
  const root = document.body.appendChild(new Node('div'));
  root.setAttribute('id', 'settings-modal');
  const sidebar = root.appendChild(new Node('div'));
  sidebar.className = 'settings-sidebar-content';
  const search = sidebar.appendChild(new Node('div'));
  search.className = 'settings-nav-search-wrap';
  const list = sidebar.appendChild(new Node('div'));
  list.className = 'settings-nav-list';
  const panels = root.appendChild(new Node('div'));
  for (const id of panelIds) {
    const panel = panels.appendChild(new Node('div'));
    panel.setAttribute('data-settings-panel', id);
    panel.dataset.settingsPanel = id;
  }
  return { root, sidebar, search, list };
}

/** The nav as a person reads it down the sidebar. */
export function readNav(list) {
  return list.childNodes.map((node) => {
    const classes = String(node.className || '').split(/\s+/).filter(Boolean);
    if (classes.includes('settings-sidebar-divider')) {
      return { rule: true, adminOnly: classes.includes('admin-only') };
    }
    if (classes.includes('settings-sidebar-label')) {
      return { heading: node.textContent, adminOnly: classes.includes('admin-only') };
    }
    return {
      tag: node.tagName,
      type: node.type,
      tab: node.dataset.settingsTab || null,
      attr: node.getAttribute('data-settings-tab'),
      label: node.querySelector('span:not(.settings-nav-item-icon)')
        ? node.childNodes[node.childNodes.length - 1].textContent
        : node.textContent,
      classes,
      hasIcon: !!node.querySelector('.settings-nav-item-icon'),
      active: classes.includes('active'),
    };
  });
}
"""

_PREAMBLE = (
    "import { document, Node, modal, readNav } from './shim.js';\n"
    "import { renderSettingsNav } from './navigation.js';\n"
    "import { SETTINGS_PANELS, SETTINGS_GROUPS, getSettingsRegistryIssues,"
    " isAdminManagedSettingsTab, isAdminOnlySettingsTab } from './registry.js';\n"
)


@pytest.fixture(scope="module")
def sandbox(tmp_path_factory):
    directory = tmp_path_factory.mktemp("settingsnav")
    (directory / "dom.js").write_text(_DOM)
    (directory / "shim.js").write_text(_SHIM)
    for name in ("registry.js", "navigation.js"):
        (directory / name).write_text((JS / name).read_text(encoding="utf-8"))
    return directory


def _nav(sandbox, script):
    return _run(sandbox, _PREAMBLE, script)


def _index_panel_ids() -> list:
    """Every `data-settings-panel` the shipped page declares, in order."""
    return re.findall(r'data-settings-panel="([^"]+)"', INDEX.read_text(encoding="utf-8"))


# ── the divergence the row predicted, and that had already happened ─────────

def test_the_registry_knows_every_panel_the_page_declares(sandbox):
    """The finding this row was re-measured on. Fifteen panels in the markup,
    fourteen in the registry, and the one that was missing is the network
    allowlist — so it could not be found in Settings search by any word."""
    panels = _index_panel_ids()
    assert "networks" in panels, "the networks panel moved; re-check this row"
    out = _nav(sandbox, """
        const { root } = modal(%s);
        renderSettingsNav(root);
        console.log(JSON.stringify({
          issues: getSettingsRegistryIssues(root),
          registry: SETTINGS_PANELS.map(p => p.id),
        }));
    """ % json.dumps(panels))
    assert out["issues"] == [], f"registry and page disagree: {out['issues']}"
    assert sorted(out["registry"]) == sorted(panels)


def test_the_network_allowlist_is_findable_by_what_a_person_would_type(sandbox):
    """`Law 15`, and the reason the missing entry mattered rather than being
    untidy. Someone whose agent cannot reach a host types the symptom."""
    out = _nav(sandbox, """
        const entry = SETTINGS_PANELS.find(p => p.id === 'networks');
        console.log(JSON.stringify({ keywords: entry ? entry.keywords : null, label: entry && entry.label }));
    """)
    assert out["label"] == "Networks"
    for word in ("allowlist", "egress", "outbound", "firewall", "host", "offline"):
        assert word in out["keywords"], f"the allowlist is not findable by {word!r}"


def test_networks_is_admin_only_but_not_admin_controlled(sandbox):
    """Every other Administration panel routes through
    `openAdminTab` -> `window.adminModule.open(tab)`. `admin.js` has no case for
    this one — `settings.js` activates it and lazy-imports `networks.js` — so an
    entry copied from its neighbours is a tab that highlights and draws
    nothing."""
    out = _nav(sandbox, """
        console.log(JSON.stringify({
          only: isAdminOnlySettingsTab('networks'),
          managed: isAdminManagedSettingsTab('networks'),
          others: ['tools','users','embeddings','system'].map(isAdminManagedSettingsTab),
        }));
    """)
    assert out["only"] is True
    assert out["managed"] is False
    assert out["others"] == [True, True, True, True]
    # And the branch that actually draws it is where the test says it is.
    code = blank_text(SETTINGS_JS.read_text(encoding="utf-8"))
    branch = code[code.index("tab === 'networks'"):]
    assert "./networks.js" in branch[: branch.index("}") + 40]


# ── the nav itself ─────────────────────────────────────────────────────────

def test_every_tab_is_drawn_from_the_registry_in_the_registrys_order(sandbox):
    """One source of truth, which is the row. A second list anywhere is a fork
    in the maintenance path where one side goes stale — and it did."""
    out = _nav(sandbox, """
        const { root, list } = modal(%s);
        renderSettingsNav(root);
        console.log(JSON.stringify({
          nav: readNav(list),
          registry: SETTINGS_PANELS.map(p => ({ id: p.id, label: p.label })),
        }));
    """ % json.dumps(_index_panel_ids()))
    buttons = [row for row in out["nav"] if row.get("tab")]
    assert [b["tab"] for b in buttons] == [p["id"] for p in out["registry"]]
    assert [b["label"] for b in buttons] == [p["label"] for p in out["registry"]]
    assert len(buttons) == 15, f"expected fifteen tabs, drew {len(buttons)}"
    assert all(b["hasIcon"] for b in buttons), "a tab lost its glyph"


def test_the_class_name_and_the_data_attribute_did_not_move(sandbox):
    """The row's own constraint, and it is not decoration: five modules query
    these and the stylesheet keys off both. The attribute *and* the dataset are
    written, because the readers are split between them."""
    out = _nav(sandbox, """
        const { root, list } = modal(%s);
        renderSettingsNav(root);
        console.log(JSON.stringify({ nav: readNav(list) }));
    """ % json.dumps(_index_panel_ids()))
    buttons = [row for row in out["nav"] if row.get("tab")]
    for b in buttons:
        assert "settings-nav-item" in b["classes"]
        assert b["attr"] == b["tab"], "the [data-settings-tab] selector would not match"
        assert b["tag"] == "BUTTON" and b["type"] == "button"
    # Every selector the rest of the app uses, resolved against what was drawn.
    drawn = {b["tab"] for b in buttons}
    source = "\n".join(
        blank_text((ROOT / "static" / "js" / name).read_text(encoding="utf-8"))
        for name in ("slashCommands.js", "calendar.js", "admin.js", "emailLibrary.js", "settings.js")
    )
    wanted = set(re.findall(r'data-settings-tab="([a-z-]+)"', source))
    assert wanted, "no module queries the nav any more — re-check this constraint"
    assert wanted <= drawn, f"these modules ask for tabs that are not drawn: {sorted(wanted - drawn)}"


def test_the_admin_tabs_still_carry_the_class_that_hides_them(sandbox):
    """`syncAdminVisibility()` hides by `.admin-only` and by nothing else. A
    generated nav that forgets it shows every administrator control to every
    user — which is a permission leak wearing a layout bug's clothes."""
    out = _nav(sandbox, """
        const { root, list } = modal(%s);
        renderSettingsNav(root);
        console.log(JSON.stringify({ nav: readNav(list), panels: SETTINGS_PANELS.map(p => ({ id: p.id, adminOnly: p.adminOnly })) }));
    """ % json.dumps(_index_panel_ids()))
    admin_only = {p["id"] for p in out["panels"] if p["adminOnly"]}
    assert admin_only == {"tools", "users", "embeddings", "networks", "system"}
    for row in out["nav"]:
        if row.get("tab"):
            assert ("admin-only" in row["classes"]) == (row["tab"] in admin_only), row
    # The divider and the heading above the admin block are hidden with it, or
    # a non-admin sees a rule and the word "Admin" over nothing.
    heading = [row for row in out["nav"] if row.get("heading")]
    assert [h["heading"] for h in heading] == ["Admin"]
    assert heading[0]["adminOnly"] is True
    rules = [row for row in out["nav"] if row.get("rule")]
    assert len(rules) == 4, "the four group rules the markup drew by hand"
    assert rules[-1]["adminOnly"] is True


def test_no_rule_is_drawn_above_the_first_group(sandbox):
    """A separator with nothing above it reads as a truncated list."""
    out = _nav(sandbox, """
        const { root, list } = modal(%s);
        renderSettingsNav(root);
        console.log(JSON.stringify({ nav: readNav(list) }));
    """ % json.dumps(_index_panel_ids()))
    assert out["nav"][0].get("tab") == "services"


def test_redrawing_the_nav_keeps_the_tab_you_were_on(sandbox):
    """`initAll()` draws it a second time, lazily, after the module-load draw.
    A redraw that resets to the default would throw a person out of the panel
    they had open."""
    out = _nav(sandbox, """
        const { root, list } = modal(%s);
        renderSettingsNav(root);
        for (const b of list.querySelectorAll('.settings-nav-item')) b.classList.remove('active');
        list.querySelector('[data-settings-tab="appearance"]').classList.add('active');
        renderSettingsNav(root);
        const nav = readNav(list);
        console.log(JSON.stringify({
          active: nav.filter(r => r.active).map(r => r.tab),
          count: nav.filter(r => r.tab).length,
        }));
    """ % json.dumps(_index_panel_ids()))
    assert out["active"] == ["appearance"]
    assert out["count"] == 15, "a redraw duplicated the nav"


def test_a_missing_container_is_not_an_exception(sandbox):
    """The renderer runs at module evaluation against whatever page is loaded.
    `login.html` and the tests' own fixtures have no settings modal, and a throw
    there takes the whole module down with it."""
    out = _nav(sandbox, """
        const got = [];
        for (const arg of [null, undefined, {}, document.body]) {
          try { got.push(renderSettingsNav(arg)); } catch (e) { got.push('THREW: ' + e.message); }
        }
        console.log(JSON.stringify({ got }));
    """)
    assert all(row is None for row in out["got"]), out["got"]


# ── where it is called from, and what the page now carries ─────────────────

def test_the_nav_is_drawn_when_the_module_loads_not_when_settings_first_opens():
    """`initAll()` runs lazily on the first `settingsModule.open()`. Five call
    sites never use that API — they un-hide `#settings-modal` themselves and
    click a tab — so a nav built inside `initAll` does not exist for any of
    them, and opening Settings from the calendar shows an empty sidebar."""
    code = blank_text(SETTINGS_JS.read_text(encoding="utf-8"))
    at_module_scope = re.search(r"^renderSettingsNav\(el\('settings-modal'\)\);", code, re.M)
    assert at_module_scope, "the nav is not drawn at module evaluation"
    assert at_module_scope.start() < code.index("function initAll()"), (
        "the module-load draw must not be inside or after initAll's definition"
    )
    # The call sites this is for, counted rather than described.
    reachers = 0
    for name in ("calendar.js", "emailLibrary.js"):
        source = blank_text((ROOT / "static" / "js" / name).read_text(encoding="utf-8"))
        reachers += len(re.findall(r'\[data-settings-tab=', source))
    assert reachers >= 5, (
        f"only {reachers} call sites bypass settingsModule.open() now — if that "
        "is zero, the module-load draw can move into initAll"
    )


def test_the_page_carries_the_container_and_no_hand_written_tab():
    """A leftover button in the markup is the second source of truth coming
    back, and it would out-live the registry entry it duplicates."""
    raw = INDEX.read_text(encoding="utf-8")
    # Comments blanked first: the container carries a paragraph explaining why
    # the buttons left, and it names the attribute (`Law 20` — a file is code
    # and prose about code interleaved, and a substring search cannot tell which
    # of the two it found).
    html = blank_text(raw, mode="html", embedded=False)
    assert '<div class="settings-nav-list"></div>' in html
    assert 'class="settings-nav-item' not in html, "a nav button is still hand-written"
    assert 'data-settings-tab=' not in html, "a tab is still declared in the markup"
    # The panels are still markup, deliberately — that is the half the
    # self-check still has something to compare.
    assert len(_index_panel_ids()) == 15


def test_the_generated_nav_has_the_css_it_needs():
    """The glyph moved into a span, so the flex row needs one rule or every
    icon drops to a text baseline. Asserted as values, not property names."""
    sheet = blank_text(STYLE.read_text(encoding="utf-8"), mode="css")
    block = sheet[sheet.index(".settings-nav-item-icon {"):]
    block = block[: block.index("}") + 1]
    assert "inline-flex" in block and "flex-shrink: 0" in block
    assert ".settings-nav-list {" in sheet
    # The rule that was already there still reaches the glyph.
    assert ".settings-nav-item svg {" in sheet


def test_a_registry_mismatch_is_reported_where_someone_will_see_it():
    """`Law 15` applied to the tooling. This check has been right and invisible
    since it was written: it reported `networks` into `console.warn` on every
    init and the panel stayed unfindable for as long as nobody looked."""
    code = blank_text(SETTINGS_JS.read_text(encoding="utf-8"))
    assert "_reportSettingsRegistryIssues" in code
    # Called, and called from the place that runs the check — asserted inside
    # `initAll`'s own braces rather than anywhere in the file (`Law 20`), because
    # a reporter nobody calls is exactly the `console.warn` this replaces.
    init = js_function(SETTINGS_JS.read_text(encoding="utf-8"), "function initAll(")
    init = blank_text(init)
    assert "getSettingsRegistryIssues" in init
    assert "_reportSettingsRegistryIssues(" in init, (
        "the reporter is defined and never called"
    )
    body = code[code.index("function _reportSettingsRegistryIssues("):]
    body = body[: body.index("\n}") + 2]
    assert "renderEmptyState" in body, (
        "a sixteenth way of saying something went wrong is a Law 14 defect"
    )
    assert "settings-nav-list" in body, "the report is not beside the nav it is about"
    assert "issues.join" in body, "the report does not say which entry is missing"
