# SPDX-License-Identifier: AGPL-3.0-or-later
"""`P5-08` (expand-all) and `P5-03` (the name a card keeps) — driven, not grepped.

Both halves here are about a reader who has never seen an agent thread before,
which is what `Law 15` asks of every row in this phase.

**`P5-08`.** A nine-tool round is nine folds. Reading what the agent actually
did meant nine clicks, then nine more to put it back, and nothing on the
surface said the cards opened at all. The control says "Expand all" and
"Collapse all" in words — a glyph here is a thing somebody has to be taught —
and it is drawn by one function called from one observer rather than by the
three places that build an `.agent-thread` (live stream, history replay,
compare mode), because three copies of a control is how this file's neighbour
came to need `P4-01`.

**`P5-03`, and its premise.** The row says finished cards show the **raw tool
id** — *"a node reading Running becomes bash; Searching becomes web_search. 21
tools affected, and history replay shows raw ids for all of them"* — and that
**compare mode already does it right**, which it offers as the proof it is a
bug and the place to take the fix from.

Re-measured 2026-09-18 against the source, and both halves of that are now
false:

  * `P4-01` landed the two-form label map and moved all three paths onto it.
    `chat.js`, `chatRenderer.js` and `compare/stream.js` each call
    `applyAgentThreadNode(..., state: 'done')`, which resolves through
    `toolLabel(tool, 'done')`. There is no raw id left to remove;
  * compare mode is not the donor implementation. It had **its own five-entry
    map of nouns, written out twice**, and `P4-01` deleted it. There is
    nothing there to copy from.

So this file does not implement `P5-03` — the row is corrected instead (`Law
3`). What it adds is the guard the row was really asking for and nobody had
written: `tests/test_agent_thread_card_is_one_builder.py` proves the *builder*
names a finished `bash` "Terminal", and nothing at all proved that **history
replay calls it that way**. That is `Law 20`'s own example — `B41` was green
while the handler two functions below raised on every call — so the assertion
here drives a real session reload through `chatRenderer.js` and reads the card
it produces.
"""

import json
import shutil
from pathlib import Path

import pytest

from test_tool_effect_surfaces_js import _CARD_SHIM, _CARD_STUBS, _make_sandbox, _run

ROOT = Path(__file__).resolve().parents[1]
CHAT_RENDERER = ROOT / "static" / "js" / "chatRenderer.js"

pytestmark = pytest.mark.skipif(not shutil.which("node"), reason="node binary not on PATH")


@pytest.fixture(scope="module")
def thread_sandbox(tmp_path_factory):
    return _make_sandbox(
        tmp_path_factory.mktemp("threadread"), CHAT_RENDERER, _CARD_SHIM, _CARD_STUBS
    )


_PREAMBLE = (
    "import { document, history, Node } from './shim.js';\n"
    "const { addMessage } = await import('./chatRenderer.js');\n"
    "const thread = await import('./agentThread.js');\n"
    # The shim stores `innerHTML` as a string and does not parse it — a
    # deliberate property of this harness, stated in
    # `test_the_workshop_surfaces_js.py`. The card shell is written with
    # `innerHTML`, so its header cannot be reached with `querySelector`. The
    # scope is still resolved first: `history.querySelectorAll` returns the
    # real card elements the replay created, and only then is the one span
    # inside one card read — by its shape, not by looking for a word anywhere
    # in the page (`Law 20`).
    "const cardLabel = (node) => {\n"
    "  const m = /<span class=\"agent-thread-tool\">([^<]*)<\\/span>/"
    ".exec(node.innerHTML || '');\n"
    "  return m ? m[1] : null;\n"
    "};\n"
)


def _drive(sandbox, script):
    return _run(sandbox, _PREAMBLE, script)


def _replay(events):
    """A session reload carrying these persisted tool events, all in round 1."""
    return (
        "history.childNodes = [];\n"
        "addMessage('assistant', 'Working on it.', 'test-model', "
        + json.dumps({"round_texts": ["Working on it."], "tool_events": events})
        + ");\n"
    )


# ── `P5-03` · the name a card is given, at the call site ────────────────────


@pytest.mark.parametrize("tool, noun", [
    ("bash", "Terminal"),
    ("web_search", "Web Search"),
    ("write_file", "Write File"),
    ("deep_research", "Deep Research"),
])
def test_a_reloaded_card_is_named_and_not_just_identified(thread_sandbox, tool, noun):
    """The row's own example, driven through the path the row names. A card
    that comes back from a reload saying `web_search` is the product telling a
    reader the wire format instead of telling them what happened."""
    out = _drive(thread_sandbox, _replay([
        {"round": 1, "tool": tool, "command": "x", "output": "done", "exit_code": 0},
    ]) + """
        const card = history.querySelector('.agent-thread-node');
        console.log(JSON.stringify({ label: card && cardLabel(card) }));
    """)
    assert out["label"] == noun, out


def test_a_reloaded_card_never_falls_back_to_the_wire_name(thread_sandbox):
    """Stated as the absence, across the whole of the 21-entry map at once —
    one tool regressing is one tool, and the row was about all of them."""
    out = _drive(thread_sandbox, """
        const ids = Object.keys(thread.TOOL_LABELS);
        const raw = [];
        for (const tool of ids) {
          history.childNodes = [];
          addMessage('assistant', 'x', 'm', { round_texts: ['x'], tool_events: [
            { round: 1, tool, command: 'x', output: 'done', exit_code: 0 },
          ]});
          const card = history.querySelector('.agent-thread-node');
          if (!card || cardLabel(card) === tool) raw.push(tool);
        }
        console.log(JSON.stringify({ count: ids.length, raw }));
    """)
    assert out["count"] == 21
    assert out["raw"] == [], out["raw"]


def test_a_tool_nobody_has_named_still_gets_a_header(thread_sandbox):
    """The deliberate exception, pinned so "never show the id" is not read as
    "show nothing". A name nobody chose beats a wrong one, and beats a blank."""
    out = _drive(thread_sandbox, _replay([
        {"round": 1, "tool": "some_new_tool", "command": "x", "output": "ok",
         "exit_code": 0},
    ]) + """
        const card = history.querySelector('.agent-thread-node');
        console.log(JSON.stringify({ label: card && cardLabel(card) }));
    """)
    assert out["label"] == "some_new_tool"


# ── `P5-08` · one click to read the whole round ─────────────────────────────


def test_a_thread_of_several_cards_offers_to_open_them_all(thread_sandbox):
    out = _drive(thread_sandbox, _replay([
        {"round": 1, "tool": "bash", "command": "ls", "output": "a", "exit_code": 0},
        {"round": 1, "tool": "read_file", "command": "/tmp/x", "output": "b",
         "exit_code": 0},
        {"round": 1, "tool": "web_search", "command": "cats", "output": "c",
         "exit_code": 0},
    ]) + """
        const el = history.querySelector('.agent-thread');
        thread.ensureThreadToggleAll(el);
        const btn = el.querySelector('.agent-thread-expand-all');
        console.log(JSON.stringify({
          label: btn && btn.textContent,
          expanded: btn && btn.getAttribute('aria-expanded'),
          // It goes above the cards, where a reader meets it before the wall
          // of folds it is offering to open.
          first: el.children[0] && el.children[0].className,
        }));
    """)
    assert out["label"] == "Expand all"
    assert out["expanded"] == "false"
    assert out["first"] == "agent-thread-toolbar"


def test_one_card_gets_no_control_because_there_is_nothing_to_expand_all_of(thread_sandbox):
    out = _drive(thread_sandbox, _replay([
        {"round": 1, "tool": "bash", "command": "ls", "output": "a", "exit_code": 0},
    ]) + """
        const el = history.querySelector('.agent-thread');
        thread.ensureThreadToggleAll(el);
        console.log(JSON.stringify({
          bar: !!el.querySelector('.agent-thread-expand-all'),
        }));
    """)
    assert out["bar"] is False


def test_the_control_opens_every_card_and_then_shuts_every_card(thread_sandbox):
    out = _drive(thread_sandbox, _replay([
        {"round": 1, "tool": "bash", "command": "ls", "output": "a", "exit_code": 0},
        {"round": 1, "tool": "python", "command": "print(1)", "output": "1",
         "exit_code": 0},
    ]) + """
        const el = history.querySelector('.agent-thread');
        thread.ensureThreadToggleAll(el);
        const open = () => el.querySelectorAll('.agent-thread-node')
          .filter(n => n.classList.contains('open')).length;
        const btn = () => el.querySelector('.agent-thread-expand-all').textContent;
        const before = { open: open(), label: btn() };
        thread.toggleThreadAll(el);
        const expanded = { open: open(), label: btn() };
        thread.toggleThreadAll(el);
        const collapsed = { open: open(), label: btn() };
        console.log(JSON.stringify({ before, expanded, collapsed }));
    """)
    assert out["before"] == {"open": 0, "label": "Expand all"}
    assert out["expanded"] == {"open": 2, "label": "Collapse all"}
    assert out["collapsed"] == {"open": 0, "label": "Expand all"}


def test_the_control_says_what_it_will_do_after_a_card_is_opened_by_hand(thread_sandbox):
    """The state that goes stale. Open the last shut card with its own chevron
    and a button still reading "Expand all" is lying about what it does — and
    that is exactly the click a reader makes next."""
    out = _drive(thread_sandbox, _replay([
        {"round": 1, "tool": "bash", "command": "ls", "output": "a", "exit_code": 0},
        {"round": 1, "tool": "python", "command": "print(1)", "output": "1",
         "exit_code": 0},
    ]) + """
        const el = history.querySelector('.agent-thread');
        thread.ensureThreadToggleAll(el);
        const nodes = el.querySelectorAll('.agent-thread-node');
        nodes.forEach(n => n.classList.add('open'));
        thread.syncThreadToggleAll(el);
        const all = el.querySelector('.agent-thread-expand-all').textContent;
        nodes[0].classList.remove('open');
        thread.syncThreadToggleAll(el);
        const some = el.querySelector('.agent-thread-expand-all').textContent;
        console.log(JSON.stringify({ all, some }));
    """)
    assert out["all"] == "Collapse all"
    assert out["some"] == "Expand all"


def test_the_control_is_built_in_exactly_one_place():
    """`Law 14`, stated as a property of the tree. Three modules create an
    `.agent-thread`; a control written into each of them is three controls that
    drift, which is the defect `P4-01` spent six copies of a tool card on."""
    hits = [
        str(path.relative_to(ROOT))
        for path in sorted((ROOT / "static").rglob("*.js"))
        if "/lib/" not in path.as_posix()
        and "agent-thread-expand-all" in path.read_text(encoding="utf-8")
    ]
    # The builder, and the one delegated click handler that serves it.
    assert hits == ["static/js/agentThread.js", "static/js/chat.js"], hits
