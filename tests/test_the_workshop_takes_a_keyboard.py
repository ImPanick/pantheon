# SPDX-License-Identifier: AGPL-3.0-or-later
"""`P10-06` — the Workshop, from a keyboard: its skills, its tasks, its MCP
servers.

**The row's claim was "the Workshop's own panels are clean", and it was
measured by grepping for `onclick` on a `<div>`.** A keyboard walk in Chromium
against the running app on 2026-09-27 found the opposite, surface by surface:

  * **Skills.** The "Built-in capabilities" section ships collapsed and its
    header was a click-only `<div>`, so every built-in capability (sixty on the
    install measured) and its Edit and Revert had no keyboard path. A skill card
    could not be opened to read its SKILL.md: Tab reached its kebab, and the
    kebab's menu was unreachable too (`test_a_menu_opened_from_the_keyboard_is_
    operable_js.py`).
  * **Automations.** A task card's detail — last run, what it does, Run and
    Edit — opened only on a click on its title row.
  * **MCP.** An existing server's page — its tools and `P8-48`'s wording and
    read-only editor — opened only on a click on its integration card, whose
    one keyboard stop was Remove. Measured again 2026-09-30 once reachable:
    Enter on "Save wording" and on "Read-only" dropped the focus to `<body>`,
    because both buttons disable themselves for the round trip.

`P9-06` has since moved Skills into a window of its own, with a sidebar of
native buttons whose menus go through `bindMenuDismiss`; walked again on
2026-09-30 on that window, every stop is reachable.

The fix is `P10-02`'s shape everywhere a card holds buttons of its own and so
cannot be one: **its name is the button**, and pressing it is a click on the
card, so every mouse behaviour (Select mode, the long press, the editor guard)
is the card's own and unchanged. A section header holds none, so it changed
tag. Driven under node: functions cut out of the real modules with
`tests/helpers/js_source`, over the DOM shim of
`tests/test_tool_effect_surfaces_js.py`. That shim does not parse `innerHTML`,
so a name written into a card's template is checked by parsing what the
builder returned — the builder is called, its output is read (`Law 20`) — and
the card's own click handler is driven with the name button standing in the
card, the way the parsed template puts it there.
"""

import json
import shutil
from html.parser import HTMLParser
from pathlib import Path

import pytest

from tests.helpers.esc_stub import ui_default_stub
from tests.helpers.js_source import js_binding, js_definition
from tests.helpers.source_text import blank_text
from test_tool_effect_surfaces_js import _make_sandbox, _run  # noqa: E402
from test_the_mcp_form_names_the_field_js import _SHIM as _MCP_SHIM  # noqa: E402

ROOT = Path(__file__).resolve().parents[1]
JS = ROOT / "static" / "js"

pytestmark = pytest.mark.skipif(not shutil.which("node"), reason="node binary not on PATH")

# Focus, `contains`, `closest` and `:not()` — patched in these sandboxes only.
_PATCHES = r"""
Node.prototype.focus = function () { document.activeElement = this; this.focused = true; };
Node.prototype.contains = function (n) {
  for (let x = n; x; x = x.parentNode) if (x === this) return true;
  return false;
};
Object.defineProperty(Node.prototype, 'isConnected', {
  get() { let n = this; while (n.parentNode) n = n.parentNode; return n === document; },
  configurable: true,
});
const _plain = Node.prototype.matches;
Node.prototype.matches = function (sel) {
  return String(sel).split(',').map((s) => s.trim()).filter(Boolean).some((part) => {
    const m = part.match(/^(.*):not\(([^()]*)\)$/);
    if (m) return _plain.call(this, m[1] || '*') && !_plain.call(this, m[2]);
    return _plain.call(this, part);
  });
};
Node.prototype.closest = function (sel) {
  for (let n = this; n && n !== document; n = n.parentNode) if (n.matches(sel)) return n;
  return null;
};
"""


class _Buttons(HTMLParser):
    """Every `<button>` in a fragment: its attributes and its text."""

    def __init__(self):
        super().__init__(convert_charrefs=True)
        self.found, self._open = [], []

    def handle_starttag(self, tag, attrs):
        if tag == "button":
            self._open.append({"attrs": dict(attrs), "text": ""})

    def handle_endtag(self, tag):
        if tag == "button" and self._open:
            self.found.append(self._open.pop())

    def handle_data(self, data):
        for b in self._open:
            b["text"] += data


def _buttons(html: str) -> list:
    p = _Buttons()
    p.feed(html)
    return p.found


def _cut(path: Path, *names: str, bindings=()) -> str:
    src = path.read_text(encoding="utf-8")
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


# ── Skills ─────────────────────────────────────────────────────────────────

_SKILLS_SHIM = r"""
import { installDom, Node } from './dom.js';
export const document = installDom();
export { Node };
""" + _PATCHES


def _skills_preamble() -> str:
    return (
        "import { document, Node } from './shim.js';\n"
        "import uiModule from './ui.js';\n"
        "const chevronIcon = () => '<svg></svg>';\n"
        "const API = '';\n"
        "const calls = { revert: 0, edit: 0 };\n"
        "function _revertBuiltin() { calls.revert += 1; }\n"
        "function _toggleBuiltinEdit() { calls.edit += 1; }\n"
        + _cut(JS / "skills.js", "esc", "_saveCollapsedSections", "_applySectionCollapse",
               "_skillsSectionHeader", "_syncCardToggle", "_buildBuiltinCards",
               "_expandBuiltinCard", "_collapseSkillCardEl",
               bindings=("_collapsedSections", "_CARD_OWN"))
        + "\nconst tick = (ms = 5) => new Promise((r) => setTimeout(r, ms));\n"
    )


@pytest.fixture(scope="module")
def skills_sandbox(tmp_path_factory):
    return _make_sandbox(tmp_path_factory.mktemp("shopskills"), JS / "icons.js", _SKILLS_SHIM,
                         {"ui.js": ui_default_stub()})


def _skills(script: str, sandbox: Path) -> dict:
    return _run(sandbox, _skills_preamble(), script)


def test_a_section_header_is_a_button_that_says_whether_it_is_open(skills_sandbox):
    out = _skills(
        """
        localStorage.removeItem('skillsSectionsCollapsed');
        const grid = document.body.appendChild(new Node('div'));
        const hdr = _skillsSectionHeader(grid, 'builtin', 'Built-in capabilities', 60);
        grid.appendChild(hdr);
        const before = [hdr.tagName, hdr.type, hdr.getAttribute('aria-expanded'),
                        hdr.className.includes('collapsed')];
        hdr.dispatchEvent({ type: 'click', target: hdr });
        const after = [hdr.getAttribute('aria-expanded'), hdr.className.includes('collapsed')];
        hdr.dispatchEvent({ type: 'click', target: hdr });
        const again = [hdr.getAttribute('aria-expanded'), hdr.className.includes('collapsed')];
        console.log(JSON.stringify({ before, after, again }));
        """,
        skills_sandbox,
    )
    assert out["before"] == ["BUTTON", "button", "false", True], (
        "the Built-in section ships collapsed, and its header has to be a real "
        f"button saying so: {out['before']}"
    )
    assert out["after"] == ["true", False], out["after"]
    assert out["again"] == ["false", True], out["again"]


def test_the_built_in_card_names_itself_as_a_button(skills_sandbox):
    out = _skills(
        """
        const [card] = _buildBuiltinCards([{ name: 'bash<x>', description: 'Run a command' }]);
        const header = card.querySelector('.skill-card-header');
        console.log(JSON.stringify({ html: header.innerHTML, cardTag: card.tagName,
          cardRole: card.getAttribute('role') }));
        """,
        skills_sandbox,
    )
    toggles = [b for b in _buttons(out["html"]) if "skill-card-toggle" in b["attrs"].get("class", "")]
    assert len(toggles) == 1, f"no name button in the built-in card: {out['html'][:300]}"
    t = toggles[0]
    assert t["attrs"].get("type") == "button" and t["attrs"].get("aria-expanded") == "false", t
    assert t["text"].strip() == "bash<x>", (
        "the name inside the button must be the escaped name, read back as text: "
        f"{t['text']!r}"
    )
    assert out["cardTag"] == "DIV" and out["cardRole"] is None, (
        "the card holds Edit and Revert; it cannot be a button itself (`P10-02`)"
    )


def test_pressing_the_name_opens_the_card_and_its_own_buttons_do_not(skills_sandbox):
    out = _skills(
        """
        const grid = document.body.appendChild(new Node('div'));
        grid.className = 'doclib-grid';
        const [card] = _buildBuiltinCards([{ name: 'bash', description: 'Run a command' }]);
        grid.appendChild(card);
        // Where the parsed template puts it: the name button, inside the card.
        const toggle = card.appendChild(new Node('button'));
        toggle.className = 'skill-card-toggle';
        toggle.setAttribute('aria-expanded', 'false');
        const edit = card.querySelector('.doclib-card-action-btn');
        card.dispatchEvent({ type: 'click', target: edit });
        const afterEdit = card.className.includes('doclib-card-expanded');
        card.dispatchEvent({ type: 'click', target: toggle });
        await tick();
        const opened = [card.className.includes('doclib-card-expanded'), toggle.getAttribute('aria-expanded')];
        card.dispatchEvent({ type: 'click', target: toggle });
        await tick();
        const shut = [card.className.includes('doclib-card-expanded'), toggle.getAttribute('aria-expanded')];
        console.log(JSON.stringify({ afterEdit, opened, shut }));
        """,
        skills_sandbox,
    )
    assert out["afterEdit"] is False, "a click on the card's own Edit button also opened the card"
    assert out["opened"] == [True, "true"], (
        "pressing the name did not open the card: the card's handler still "
        f"ignores every button, the name included — {out['opened']}"
    )
    assert out["shut"] == [False, "false"], out["shut"]


def test_opening_one_card_closes_the_other_and_says_so(skills_sandbox):
    out = _skills(
        """
        const grid = document.body.appendChild(new Node('div'));
        grid.className = 'doclib-grid';
        const cards = _buildBuiltinCards([{ name: 'a' }, { name: 'b' }]);
        const toggles = cards.map((c) => {
          grid.appendChild(c);
          const t = c.appendChild(new Node('button'));
          t.className = 'skill-card-toggle';
          return t;
        });
        await _expandBuiltinCard(cards[0], 'a');
        await _expandBuiltinCard(cards[1], 'b');
        console.log(JSON.stringify({ a: toggles[0].getAttribute('aria-expanded'),
          b: toggles[1].getAttribute('aria-expanded') }));
        """,
        skills_sandbox,
    )
    assert out == {"a": "false", "b": "true"}, out


def test_a_card_shut_from_inside_gives_the_focus_to_its_name(skills_sandbox):
    """Escape on an open card, with the focus on its Edit button: the body
    hides, and without this the focus drops to <body> — measured in Chromium."""
    out = _skills(
        """
        const card = document.body.appendChild(new Node('div'));
        card.className = 'doclib-card skill-card doclib-card-expanded';
        const toggle = card.appendChild(new Node('button'));
        toggle.className = 'skill-card-toggle';
        const body = card.appendChild(new Node('div'));
        body.className = 'doclib-card-preview';
        const edit = body.appendChild(new Node('button'));
        edit.focus();
        _collapseSkillCardEl(card);
        const fromBody = document.activeElement === toggle;
        const other = document.body.appendChild(new Node('button'));
        card.classList.add('doclib-card-expanded');
        other.focus();
        _collapseSkillCardEl(card);
        console.log(JSON.stringify({ fromBody, kept: document.activeElement === other,
          expanded: toggle.getAttribute('aria-expanded') }));
        """,
        skills_sandbox,
    )
    assert out == {"fromBody": True, "kept": True, "expanded": "false"}, out


# ── Automations ────────────────────────────────────────────────────────────


def test_a_task_card_names_itself_as_a_button(tmp_path):
    d = _make_sandbox(tmp_path, JS / "icons.js", _SKILLS_SHIM, {"ui.js": ui_default_stub()})
    out = _run(d, "import uiModule from './ui.js';\n"
               + _cut(JS / "tasks.js", "_escHtml", "_taskNameButton") + "\n", """
        console.log(JSON.stringify({ html: _taskNameButton({ name: 'Email <Summary>' }) }));
        """)
    [b] = _buttons(out["html"])
    assert b["attrs"].get("type") == "button"
    assert set(b["attrs"]["class"].split()) == {"memory-item-title", "task-card-toggle"}, (
        "the name keeps `.memory-item-title` — its size, weight and ellipsis — "
        "and changes only its tag"
    )
    assert b["attrs"].get("aria-expanded") == "false"
    assert b["text"] == "Email <Summary>"


# ── MCP ────────────────────────────────────────────────────────────────────


def test_an_integration_card_names_itself_as_a_button(tmp_path):
    d = _make_sandbox(tmp_path, JS / "icons.js", _SKILLS_SHIM, {})
    out = _run(d, "const INTG_TYPES = { mcp: { icon: '', label: 'MCP' }, api: { icon: '', label: 'API' } };\n"
               + _cut(JS / "settings.js", "renderCard") + "\n", """
        console.log(JSON.stringify({ html: renderCard({ type: 'mcp', id: 's1', name: 'Probe memory',
          detail: 'Connected', enabled: true }) }));
        """)
    buttons = _buttons(out["html"])
    opens = [b for b in buttons if b["attrs"].get("class") == "intg-card-open"]
    assert len(opens) == 1, out["html"][:300]
    assert opens[0]["attrs"].get("type") == "button"
    assert opens[0]["text"].strip() == "Probe memory"
    assert any("intg-del-btn" in b["attrs"].get("class", "") for b in buttons), (
        "Remove is still on the card, which is why the card cannot be the button"
    )


_MCP_FOCUS_SHIM = _MCP_SHIM + _PATCHES


@pytest.fixture(scope="module")
def mcp_sandbox(tmp_path_factory):
    return _make_sandbox(tmp_path_factory.mktemp("shopmcp"), JS / "settings" / "mcpFields.js",
                         _MCP_FOCUS_SHIM, {})


_TOOL = {"name": "manage_memory", "description": "Store a memory", "description_source": "server",
         "server_description": "Store a memory", "description_max": 400,
         "input_schema": {"type": "object", "properties": {}}, "is_readonly": False,
         "readonly_source": "heuristic", "annotations": None}

_MCP_PREAMBLE = (
    "import { document, Node, click } from './shim.js';\n"
    "const F = await import('./mcpFields.js');\n"
    "const tick = (ms = 5) => new Promise((r) => setTimeout(r, ms));\n"
    f"const TOOL = {json.dumps(_TOOL)};\n"
    "function row() {\n"
    "  const r = F.createMcpToolRow(TOOL, {\n"
    "    onDescription: (n, v) => tick(20).then(() => Object.assign({}, TOOL, { description: v || TOOL.description, description_source: v ? 'override' : 'server' })),\n"
    "    onOverride: (n, v) => tick(20).then(() => Object.assign({}, TOOL, { is_readonly: v === true, readonly_source: 'override' })),\n"
    "  });\n"
    "  document.body.appendChild(r);\n"
    "  click(r.querySelector('.mcp-tool-more'));\n"
    "  return r;\n"
    "}\n"
)


def _mcp(script: str, sandbox: Path) -> dict:
    return _run(sandbox, _MCP_PREAMBLE, script)


def test_saving_the_wording_keeps_the_focus_in_the_editor(mcp_sandbox):
    out = _mcp(
        """
        const r = row();
        const input = r.querySelector('[data-mcp-description-input]');
        const save = r.querySelector('[data-mcp-description="save"]');
        input.value = 'Store one memory about the user';
        input.dispatchEvent({ type: 'input' });
        save.focus();
        click(save);
        document.activeElement = document.body;     // the disabled button lost it
        await tick(60);
        console.log(JSON.stringify({
          focusedInput: document.activeElement === input, saveDisabled: save.disabled,
          status: r.querySelector('.mcp-tool-description-status').textContent,
        }));
        """,
        mcp_sandbox,
    )
    assert out["status"] == "Saved."
    assert out["saveDisabled"] is True, "nothing left to save, so Save stays disabled"
    assert out["focusedInput"] is True, (
        "after Enter on Save wording the focus was left on <body> — measured in "
        "Chromium — instead of going to the box the person was editing"
    )


def test_answering_read_only_keeps_the_focus_on_the_answer(mcp_sandbox):
    out = _mcp(
        """
        const r = row();
        const read = r.querySelector('[data-mcp-override="read"]');
        read.focus();
        click(read);
        document.activeElement = document.body;
        await tick(60);
        console.log(JSON.stringify({ focused: document.activeElement === read,
          pressed: read.getAttribute('aria-pressed') }));
        """,
        mcp_sandbox,
    )
    assert out == {"focused": True, "pressed": "true"}, out


def test_a_focus_moved_elsewhere_mid_save_is_left_there(mcp_sandbox):
    out = _mcp(
        """
        const r = row();
        const read = r.querySelector('[data-mcp-override="read"]');
        const other = document.body.appendChild(new Node('button'));
        read.focus();
        click(read);
        other.focus();                                // the person moved on
        await tick(60);
        console.log(JSON.stringify({ kept: document.activeElement === other }));
        """,
        mcp_sandbox,
    )
    assert out["kept"] is True
