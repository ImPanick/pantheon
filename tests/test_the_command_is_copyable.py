# SPDX-License-Identifier: AGPL-3.0-or-later
r"""`P5-07` — the most copy-worthy string in the product finally is one.

The row's charge, in full: *"`.agent-thread-cmd` has no highlight, no copy, and
no expansion, and it is the most copy-worthy string in the UI."* `P4-09` closed
the third of those and put the whole command on the card for the first time,
which is why this row waited on it — a copy button that hands back the first
eighty characters of a document write is worse than no button, because the
result *looks* complete.

So the button copies the **full** text when the card has one, and the visible
line when it does not. It is one delegated listener on `document.body`, like the
fold beside it, because a per-node listener on these cards is `B56`.

Highlighting is deliberately two languages. For `bash` and `python` the command
*is* code in that language. For everything else the "command" is a path, a
query or a JSON argument blob, and guessing paints a filename in string-literal
green — a wrong colour reads as a bug where no colour reads as a command.
"""

import json
import re
import shutil
import subprocess
import textwrap
from pathlib import Path

import pytest

from test_tool_effect_surfaces_js import _copy_unstubbed_imports  # noqa: E402

from tests.helpers.esc_stub import ui_default_stub  # B874

_REPO = Path(__file__).resolve().parent.parent
_MODULE = _REPO / "static" / "js" / "agentThread.js"

# `B874`. The shipped escaper, read out of `static/js/util/escapeHtml.js`
# at test time rather than restated here. Seven files held this same
# five-character copy and three more held one that escaped nothing.
_UI_STUB = ui_default_stub()


@pytest.fixture(scope="module")
def sandbox(tmp_path_factory):
    if not shutil.which("node"):
        pytest.skip("node binary not on PATH")
    d = tmp_path_factory.mktemp("copycmd")
    (d / "ui.js").write_text(_UI_STUB, encoding="utf-8")
    shutil.copy(_MODULE, d / "agentThread.js")
    # `P5-04` added an import to `agentThread.js`, and a sandbox that copies one
    # file cannot see one. `_copy_unstubbed_imports` was written for exactly this
    # ("adding one import to a sandboxed module breaks every sandbox that copies
    # it") and is borrowed rather than re-implemented here (`Law 14`): `ui.js` keeps
    # its stub, everything else comes in for real, transitively.
    _copy_unstubbed_imports(d, _MODULE, {"ui.js"})
    return d


def _node(sandbox: Path, script: str):
    entry = sandbox / "case.mjs"
    entry.write_text(
        "const m = await import('./agentThread.js');\n" + textwrap.dedent(script),
        encoding="utf-8",
    )
    proc = subprocess.run(["node", str(entry)], cwd=sandbox, capture_output=True,
                          text=True, timeout=30)
    assert proc.returncode == 0, proc.stderr
    lines = [ln for ln in proc.stdout.splitlines() if ln.strip()]
    assert lines, f"node produced no stdout\n{proc.stderr}"
    return json.loads(lines[-1])


def _card(sandbox: Path, opts: dict) -> str:
    return _node(sandbox, f"console.log(JSON.stringify(m.agentThreadNodeHtml({json.dumps(opts)})));")


# ── the button ────────────────────────────────────────────────────────────────


def test_a_command_card_offers_a_copy_button(sandbox):
    html = _card(sandbox, {"tool": "bash", "state": "done", "ok": True,
                           "command": "printf hi"})
    assert "agent-thread-cmd-copy" in html


def test_the_button_says_what_it_does_to_a_screen_reader(sandbox):
    # Law 15, and `P10` will want this anyway. An icon-only button with no
    # accessible name is a button nobody can name.
    html = _card(sandbox, {"tool": "bash", "state": "done", "ok": True,
                           "command": "printf hi"})
    assert 'aria-label="Copy command"' in html
    assert 'title="Copy command"' in html


def test_a_card_with_no_command_offers_no_button(sandbox):
    html = _card(sandbox, {"tool": "", "state": "running", "label": "Writing"})
    assert "agent-thread-cmd-copy" not in html


@pytest.mark.parametrize("extra", [{"diff": "<div>d</div>"}, {"todo": "<div>t</div>"}])
def test_a_suppressed_command_takes_its_button_with_it(sandbox, extra):
    # `P4-01`'s rule. The button must not survive the block it belongs to.
    html = _card(sandbox, {"tool": "edit_file", "state": "done", "ok": True,
                           "command": "{...}", **extra})
    assert "agent-thread-cmd-copy" not in html


def test_the_button_binds_no_listener_of_its_own(sandbox):
    # `B56`. Two handlers for one click is how clicking a compare-mode card
    # came to do nothing at all.
    html = _card(sandbox, {"tool": "bash", "state": "done", "ok": True,
                           "command": "printf hi"})
    assert "onclick" not in html.lower()


def test_the_button_is_a_button_and_not_a_submit(sandbox):
    # These cards can render inside a form surface; a default-type <button>
    # submits it.
    html = _card(sandbox, {"tool": "bash", "state": "done", "ok": True,
                           "command": "printf hi"})
    assert 'type="button"' in html


# ── the highlight ─────────────────────────────────────────────────────────────


@pytest.mark.parametrize("tool, lang", [("bash", "bash"), ("python", "python")])
def test_a_command_that_is_code_is_marked_as_that_language(sandbox, tool, lang):
    html = _card(sandbox, {"tool": tool, "state": "done", "ok": True,
                           "command": "print(1)"})
    assert f'<code class="language-{lang}">' in html


@pytest.mark.parametrize("tool", ["read_file", "web_search", "create_document",
                                  "edit_file", "some_new_tool"])
def test_a_command_that_is_not_code_is_not_guessed_at(sandbox, tool):
    # The decision. A path coloured as a string literal reads as a bug; plain is
    # what every one of these cards showed before this row, and it is correct.
    html = _card(sandbox, {"tool": tool, "state": "done", "ok": True,
                           "command": "notes/q3.md"})
    assert "<code" not in html
    assert "agent-thread-cmd" in html


def test_the_expansion_is_highlighted_the_same_way_as_the_line_above_it(sandbox):
    html = _card(sandbox, {"tool": "bash", "state": "done", "ok": True,
                           "command": "echo one", "fullCommand": "echo one\necho two"})
    assert html.count('<code class="language-bash">') == 2


def test_highlighting_without_a_page_is_a_no_op(sandbox):
    # The builder runs in tests and could run server-side; there is no `window`
    # there and this module does not import one.
    out = _node(sandbox, """
        m.highlightCommandBlocks(null);
        m.highlightCommandBlocks({ querySelectorAll: () => [] });
        console.log(JSON.stringify({ ok: true }));
    """)
    assert out["ok"] is True


def test_a_page_that_never_loaded_highlight_js_is_a_no_op(sandbox):
    # `hljs` is a page-level global that arrives from a separate <script>. It is
    # absent on a cold offline load until the bundle lands, and every card built
    # in that window must still render.
    out = _node(sandbox, """
        globalThis.window = {};
        let touched = 0;
        m.highlightCommandBlocks({ querySelectorAll: () => { touched += 1; return []; } });
        console.log(JSON.stringify({ ok: true, touched }));
    """)
    assert out["ok"] is True
    assert out["touched"] == 0, "the card was searched before hljs was known to exist"


def test_a_card_with_no_dom_behind_it_is_a_no_op(sandbox):
    # `applyAgentThreadNode` is driven by hand-built nodes in this suite and by
    # anything else that only implements the three properties it writes.
    out = _node(sandbox, """
        globalThis.window = { hljs: { highlightElement() {} } };
        m.highlightCommandBlocks(null);
        m.highlightCommandBlocks({});
        m.highlightCommandBlocks({ querySelectorAll: 'not a function' });
        console.log(JSON.stringify({ ok: true }));
    """)
    assert out["ok"] is True


def test_building_a_card_highlights_it(sandbox):
    # The call site, not just the function. A highlighter nothing invokes is a
    # feature that exists only in its own tests.
    out = _node(sandbox, """
        globalThis.window = { hljs: { highlightElement() {} } };
        const seen = [];
        const node = { className: '', innerHTML: '',
                       classList: { contains: () => false },
                       querySelectorAll: (sel) => { seen.push(sel); return []; } };
        m.applyAgentThreadNode(node, { tool: 'bash', state: 'done', ok: true,
                                       command: 'printf hi' });
        console.log(JSON.stringify({ seen }));
    """)
    assert out["seen"] == [".agent-thread-cmd code:not(.hljs)"], (
        "applying a card no longer highlights the command in it"
    )


def test_a_highlighter_that_throws_does_not_take_the_card_down(sandbox):
    # A plain <pre> is the correct fallback and is what the card showed before
    # this row. Losing the whole tool card to a colouring failure is not.
    out = _node(sandbox, """
        globalThis.window = { hljs: { highlightElement() { throw new Error('boom'); } } };
        let warned = 0;
        const realWarn = console.warn;
        console.warn = () => { warned += 1; };
        const seen = [];
        m.highlightCommandBlocks({ querySelectorAll: (sel) => { seen.push(sel); return [{}, {}]; } });
        console.warn = realWarn;
        console.log(JSON.stringify({ warned, seen }));
    """)
    assert out["warned"] == 2, "a failure was swallowed without a word"
    assert out["seen"] == [".agent-thread-cmd code:not(.hljs)"]


def test_highlighting_skips_what_is_already_highlighted(sandbox):
    # `hljs.highlightElement` on an already-highlighted node re-escapes its own
    # markup; the `:not(.hljs)` guard is the rest of the app's idiom and this is
    # the assertion that it did not get dropped.
    out = _node(sandbox, """
        globalThis.window = { hljs: { highlightElement() {} } };
        const seen = [];
        m.highlightCommandBlocks({ querySelectorAll: (sel) => { seen.push(sel); return []; } });
        console.log(JSON.stringify({ seen }));
    """)
    assert ":not(.hljs)" in out["seen"][0]


# ── the handler ───────────────────────────────────────────────────────────────


def _copy_handler_source() -> str:
    text = (_REPO / "static" / "js" / "chat.js").read_text(encoding="utf-8")
    start = text.index("__pantheon_thread_copy_bound")
    end = text.index("__pantheon_thread_copy_bound = true", start)
    return text[start:end]


def test_the_copy_handler_is_delegated_and_bound_once():
    # `B56`, and the same guard the fold handler uses so a second import of
    # chat.js cannot bind it twice.
    body = _copy_handler_source()
    assert body.count("addEventListener") == 1
    assert "document.body.addEventListener('click'" in body
    text = (_REPO / "static" / "js" / "chat.js").read_text(encoding="utf-8")
    assert text.count("__pantheon_thread_copy_bound") == 2, (
        "the bind guard is set without being read, or read without being set"
    )


def test_the_handler_prefers_the_full_command_over_the_visible_line():
    # The whole reason this row depended on `P4-09`. Copying what is shown hands
    # back a truncated command that looks complete.
    body = _copy_handler_source()
    full_at = body.index("agent-thread-cmd-full")
    block_at = body.index("agent-thread-cmd-block")
    assert full_at < block_at, "the visible line is consulted before the full one"
    assert re.search(r"\(\s*full\s*\|\|\s*shown\s*\)", body), (
        "the fallback from the full command to the visible line is gone"
    )


def test_every_selector_the_handler_reaches_for_is_one_the_builder_writes(sandbox):
    # The handler and the markup are in different files and nothing made them
    # agree. A renamed or mistyped class here is a copy button that silently
    # copies nothing, which is the worst failure this feature has.
    # The whole card, not just its inner markup: `.agent-thread-node` is the
    # class `applyAgentThreadNode` puts on the element itself, and the handler
    # walks up to it.
    built = _node(sandbox, """
        const node = { className: '', innerHTML: '',
                       classList: { contains: (c) => node.className.split(' ').includes(c) } };
        m.applyAgentThreadNode(node, { tool: 'bash', state: 'done', ok: true,
                                       command: 'echo one', fullCommand: 'echo one\\necho two' });
        console.log(JSON.stringify({ html: `<div class="${node.className}">${node.innerHTML}</div>` }));
    """)
    html = built["html"]
    selectors = set(re.findall(r"['\"]\.((?:agent-thread-[a-z-]+ ?\.?)+)['\"]",
                               _copy_handler_source()))
    assert selectors, "no selectors found — the extraction broke, not the code"
    for selector in selectors:
        for cls in selector.replace(".", " ").split():
            assert re.search(rf'class="[^"]*\b{re.escape(cls)}\b[^"]*"', html), (
                f"the copy handler looks for `.{cls}` and no card ever has it"
            )
