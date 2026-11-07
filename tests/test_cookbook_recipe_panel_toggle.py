# SPDX-License-Identifier: AGPL-3.0-or-later
"""`B1969`. Nothing could open a Dependencies recipe panel.

A Dependencies row for a backend with recipes (vLLM, SGLang, llama.cpp, the
MLX and Diffusers rows) renders its recipe panel hidden: a model picker, the
Pip and Docker commands, Copy and Run. Only the row's caret showed it, and a
commit from before the fork took the caret out, saying the action had moved
into the Installed ▾ menu. It had not: that menu has no recipe item, and it is
drawn only for installed rows. The panel's toggle handler stayed, bound to
nothing, and so did the two deep links that open it, HW Fit's not-installed
preflight (whose toast says to pick the model and click Run) and the serve
card's "Install in Dependencies", which click the caret and found none.

The caret is back, drawn by `icons.js`'s chevronIcon, because the chevron
exists once, in the icon table (`B230`). Upstream Odysseus brought it back in
93c93bf0 (#6747) with a hand-written chevron, which this tree does not allow.

Driven where it can be (`Law 20`): node evaluates the row's own `recipeCaret`
expression with the real chevronIcon, and the handler and the deep link are
read inside the block that holds each.
"""
from __future__ import annotations

import json
import re
import shutil
import subprocess
from pathlib import Path

import pytest

from tests.helpers.esc_stub import esc_source

ROOT = Path(__file__).resolve().parent.parent
JS = ROOT / "static" / "js"
COOKBOOK_JS = JS / "cookbook.js"
DIAGNOSIS_JS = JS / "cookbook-diagnosis.js"

pytestmark = pytest.mark.skipif(not shutil.which("node"), reason="node binary not on PATH")


def _between(src: str, start: str, end: str) -> str:
    i = src.index(start)
    return src[i:src.index(end, i)]


def _row_renderer() -> str:
    return _between(COOKBOOK_JS.read_text(encoding="utf-8"),
                    "const hasRecipe = RECIPE_BACKENDS.has(pkg.name);", "+ recipePanel;")


def _carets(rows: list) -> dict:
    """What the row's `recipeCaret` statement emits for each
    (package name, has a recipe), evaluated with the real chevronIcon."""
    statement = _between(_row_renderer(), "const recipeCaret =", "const recipePanel =")
    script = (
        f"import {{ chevronIcon }} from {json.dumps((JS / 'icons.js').as_uri())};\n"
        # The shipped escaper, as text (`B874`): the row escapes the package
        # name with it, and a hand-written copy here could drift from it.
        f"{esc_source()}"
        "const out = {};\n"
        f"for (const [name, hasRecipe] of {json.dumps(rows)}) {{\n"
        "  const pkg = { name };\n"
        f"{statement}\n"
        "  out[name] = recipeCaret;\n"
        "}\n"
        "console.log(JSON.stringify(out));\n"
    )
    proc = subprocess.run(["node", "--input-type=module", "--eval", script],
                          capture_output=True, text=True, timeout=60)
    assert proc.returncode == 0, proc.stderr
    return json.loads(proc.stdout)


def test_a_recipe_row_draws_the_caret_that_its_toggle_and_both_deep_links_click():
    carets = _carets([["vllm", True], ["tmux", False]])
    assert carets["tmux"] == "", "a row with no recipe panel has nothing to open"
    caret = carets["vllm"]
    tag = re.match(r"<button\b[^>]*>", caret)
    assert tag, f"recipe rows must render a caret, or the panel cannot be opened: {caret!r}"
    attrs = dict(re.findall(r'([a-z-]+)="([^"]*)"', tag.group(0)))
    assert attrs.get("type") == "button"
    assert attrs.get("data-dep-recipe-toggle") == "vllm"
    assert attrs.get("aria-expanded") == "false"
    assert attrs.get("aria-label"), "the caret's only content is an icon"
    # The toggle turns the caret by rotating its svg, which the table draws.
    assert re.search(r'<svg\b[^>]*aria-hidden="true"[^>]*><polyline ', caret), caret
    assert "+ recipeCaret" in _row_renderer()

    cookbook = COOKBOOK_JS.read_text(encoding="utf-8")
    wiring = _between(cookbook, "// ── Recipe panel wiring", "function _refreshRecipePre")
    assert "list.querySelectorAll('[data-dep-recipe-toggle]')" in wiring
    assert "btn.querySelector('svg')" in wiring
    deep_link = _between(DIAGNOSIS_JS.read_text(encoding="utf-8"),
                         "function _openCookbookDependencies", "\n}\n")
    assert "row.querySelector('[data-dep-recipe-toggle]')" in deep_link
