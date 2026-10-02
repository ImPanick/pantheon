# SPDX-License-Identifier: AGPL-3.0-or-later
"""`P22-22` — one node sandbox for the MCP form's browser half.

The real modules in the tree's own layout — `settings/mcpFields.js`,
`settings/mcpPresets.js`, `settings/mcpBuild.js` and `workbench/argsForm.js`,
which reach each other through `../` — over the shared DOM shim with markup
parsing switched on (`installHtmlParsing`, `P22-03`'s opt-in), because
`settings.js:showMcpForm` builds its card with `innerHTML` and then finds its
fields by id. `fetch` is a recording fake whose answers each case scripts.

`show_mcp_form_module()` is `settings.js`'s own `showMcpForm`, cut out by
`tests/helpers/js_source.js_function` and run with the closure it lives in
(`formEl` — the element with id `unified-intg-form` —, `el`, the canonical
`esc`, a counting `renderList`), so a case drives the shipped function rather
than a copy of it (`Law 20`).
"""
from __future__ import annotations

import shutil
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
JS = ROOT / "static" / "js"
if str(ROOT / "tests") not in sys.path:
    sys.path.insert(0, str(ROOT / "tests"))

from tests.helpers.esc_stub import esc_source  # noqa: E402
from tests.helpers.js_source import js_function  # noqa: E402

MODULES = ("settings/mcpFields.js", "settings/mcpPresets.js", "settings/mcpBuild.js",
           "workbench/argsForm.js")

SHIM = r"""
import { installDom, installHtmlParsing, Node } from './dom.js';
export const document = installDom();
installHtmlParsing();
export { Node };

export const server = { calls: [], answer: () => [404, { detail: 'Not Found' }] };
globalThis.fetch = async (url, init = {}) => {
  url = String(url);
  const method = String(init.method || 'GET').toUpperCase();
  let body;
  if (init.body instanceof FormData) body = Object.fromEntries(init.body.entries());
  else if (typeof init.body === 'string') body = JSON.parse(init.body);
  server.calls.push({ url, method, body });
  const [status, json] = server.answer(url, method, body);
  return { ok: status >= 200 && status < 300, status,
           json: async () => JSON.parse(JSON.stringify(json)) };
};

export const settle = async (n = 30) => { for (let i = 0; i < n; i += 1) await new Promise((r) => setTimeout(r, 0)); };
export function click(node) {
  node.dispatchEvent({ type: 'click', preventDefault() {}, stopPropagation() {} });
}
export function type(node, value) {
  node.value = value;
  node.dispatchEvent({ type: 'input' });
}
/** Every element under `node` whose tag is `tag` — markup injected as text must make none. */
export const tags = (node, tag) => node._walk([]).filter((n) => n.tagName === tag.toUpperCase());
export const text = (node) => (node ? node.readable : null);
"""


def build(root: Path) -> Path:
    from test_tool_effect_surfaces_js import _DOM  # noqa: E402

    (root / "dom.js").write_text(_DOM, encoding="utf-8")
    (root / "shim.js").write_text(SHIM, encoding="utf-8")
    for rel in MODULES:
        (root / rel).parent.mkdir(parents=True, exist_ok=True)
        shutil.copy(JS / rel, root / rel)
    return root


def show_mcp_form_module() -> str:
    """`showMcpForm`, as shipped, inside the closure it expects."""
    body = js_function((JS / "settings.js").read_text(encoding="utf-8"),
                       "async function showMcpForm")
    return (
        "import { collectMcpStdioFields, createMcpFieldEditor, createMcpToolRow, describeMcpEdit,\n"
        "  describeServerRefusal, formatCommandLine } from './settings/mcpFields.js';\n"
        "import { createMcpPresetPicker } from './settings/mcpPresets.js';\n"
        "import { mountBuildsSent, mountMcpBuild, mountMcpBuildDoor, mountToolTry, sentNotice }\n"
        "  from './settings/mcpBuild.js';\n"
        + esc_source() + "\n"
        "export const formEl = document.createElement('div');\n"
        "formEl.id = 'unified-intg-form';\n"
        "document.body.appendChild(formEl);\n"
        "export const el = (id) => document.getElementById(id);\n"
        "export const renders = { count: 0 };\n"
        "const renderList = async () => { renders.count += 1; };\n"
        f"export async function showMcpForm(editId, options) {body}\n"
    )


def write_form_module(root: Path) -> None:
    (root / "form.js").write_text(
        "import { document } from './shim.js';\n" + show_mcp_form_module(), encoding="utf-8")
