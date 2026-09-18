# SPDX-License-Identifier: AGPL-3.0-or-later
"""`P4-13` — the compaction notice says how much was summarised away.

Compaction is the one irreversible step in context shaping and it was the step
with no figures. `context_trimmed` has carried `messages_before` /
`messages_after` / `tokens_before` / `tokens_after` since before this wave and
`static/js/chat.js` has drawn them — *"Context trimmed for this model (9/12
messages sent)"*. Beside it, `compacted` emitted `{"type": "compacted",
"context_length": N}` and a toast reading *"older messages summarized"* with no
way to ask how many. `_compacted_event` (`routes/chat_routes.py`) now carries the
same four keys in a `data` block, deliberately shaped like its sibling so one
renderer can draw both. Nothing read it.

**How this is driven, and why not by a source grep.** `chat.js` is 8,000 lines
and imports most of the product, so a sandbox of the whole module would be
testing the import graph. Instead the `compacted` arm is **cut out of the real
file by its own delimiters and executed** — `Law 20`'s second preference (resolve
the scope, then assert inside it) feeding its first (call the thing). A mutation
that empties the branch, drops `json.data`, or reads the wrong key dies here; a
substring search for `messages_before` would survive all three, because the word
appears in the `context_trimmed` arm four lines below.

What is pinned:

  * **the notice carries the figures at all.** The row;
  * **it reads them out of `json.data`**, which is where the event puts them and
    where its sibling already reads its own — one nested and one flat is how two
    reports of one thing drift;
  * **it says it in the trim notice's words.** The `Verify:` line asks for *"the
    same words the trim notice uses"*, and the two arms sit four lines apart;
  * **an event with no figures still draws the sentence it always drew.** The
    flag is set independently of the figures on purpose — a compaction that
    happened is worth saying even when nothing measured it — so a `0/0` beside
    it would be a measurement rather than a silence;
  * **a background stream still says nothing.** `_isBg` guards both arms and a
    toast from a background chat is a toast about a window you are not looking
    at.
"""

import json
import shutil
import subprocess
import textwrap
from pathlib import Path

import pytest

from tests.helpers.source_text import blank  # B290

ROOT = Path(__file__).resolve().parents[1]
CHAT_JS = ROOT / "static" / "js" / "chat.js"

pytestmark = pytest.mark.skipif(not shutil.which("node"), reason="node binary not on PATH")

_COMPACTED = "} else if (json.type === 'compacted') {"
_TRIMMED = "} else if (json.type === 'context_trimmed') {"


def _arm(opening: str, closing: str) -> str:
    """One `else if` arm of the stream dispatcher, cut out by its delimiters.

    Comments are blanked first (`B290`'s one blanker), so a delimiter quoted in
    prose cannot be mistaken for the code — which is `Law 20`'s first incident
    in miniature.
    """
    src = blank(CHAT_JS)
    start = src.index(opening)
    end = src.index(closing, start + len(opening))
    assert src.count(opening) == 1, f"{opening!r} is no longer a unique anchor"
    # The chunk stops before the NEXT arm's `}`, so it is the opening line plus
    # the body; closing it makes a statement that runs on its own.
    return "if (false) {\n" + src[start:end] + "}\n"


def _run(arm: str, events: list) -> list:
    """Drive the arm over a list of `[json, isBg]` pairs; return the toasts."""
    script = textwrap.dedent("""
        const toasts = [];
        const uiModule = { showToast: (m) => { toasts.push(String(m)); } };
        function draw(json, _isBg) {
        %s
        }
        for (const [event, bg] of %s) draw(event, bg);
        console.log(JSON.stringify(toasts));
    """) % (textwrap.indent(arm, "          "), json.dumps(events))
    proc = subprocess.run(["node", "--input-type=module", "-e", script],
                          capture_output=True, text=True, timeout=30)
    assert proc.returncode == 0, proc.stderr
    return json.loads(proc.stdout.strip().splitlines()[-1])


@pytest.fixture(scope="module")
def compacted():
    return _arm(_COMPACTED, _TRIMMED)


@pytest.fixture(scope="module")
def trimmed():
    # The sibling's arm runs to whatever `else if` follows it.
    src = blank(CHAT_JS)
    start = src.index(_TRIMMED)
    end = src.index("} else if (", start + len(_TRIMMED))
    return "if (false) {\n" + src[start:end] + "}\n"


_FIGURES = {
    "type": "compacted",
    "context_length": 128000,
    "data": {
        "context_length": 128000,
        "messages_before": 42,
        "messages_after": 9,
        "tokens_before": 81400,
        "tokens_after": 12200,
    },
}


def test_the_notice_says_how_much_was_summarised_away(compacted):
    """The row. Before this the toast could say older messages were summarized
    and there was no way to ask how many."""
    [toast] = _run(compacted, [[_FIGURES, False]])
    assert "9/42 messages kept" in toast, toast
    assert "81,400" in toast and "12,200" in toast, toast
    assert "summarized" in toast, toast


def test_the_figures_are_read_out_of_the_events_data_block(compacted):
    """`data` is where `_compacted_event` puts them and where the sibling
    `context_trimmed` arm already reads its own. A renderer reading one nested
    and one flat is how two reports of one thing drift apart."""
    flat = {"type": "compacted", "context_length": 128000,
            "messages_before": 42, "messages_after": 9,
            "tokens_before": 81400, "tokens_after": 12200}
    [toast] = _run(compacted, [[flat, False]])
    assert "9/42" not in toast, (
        "the arm read the figures off the top level, so it will read the real "
        "event — which nests them — as having none"
    )


def test_it_speaks_in_the_trim_notices_words(compacted, trimmed):
    """The `Verify:` line asks for the same words, and the two arms are four
    lines apart in the same dispatcher. A count that reads `a/b` in one and
    `b→a` in the other is two vocabularies for one idea."""
    [compaction] = _run(compacted, [[_FIGURES, False]])
    [trim] = _run(trimmed, [[{
        "type": "context_trimmed",
        "data": {"messages_before": 12, "messages_after": 9},
    }, False]])
    assert "(9/12 messages sent)" in trim, trim
    assert "(9/42 messages kept" in compaction, compaction


def test_an_event_with_no_figures_still_draws_the_sentence_it_always_drew(compacted):
    """`context_compacted` is set independently of the figures, because a
    compaction that happened is worth saying even when nothing measured it. A
    `0/0` beside it would be a measurement rather than a silence."""
    bare = {"type": "compacted", "context_length": 128000}
    empty = {"type": "compacted", "context_length": 128000, "data": {}}
    zeroes = {"type": "compacted", "data": {"messages_before": 0, "messages_after": 0,
                                            "tokens_before": 0, "tokens_after": 0}}
    toasts = _run(compacted, [[bare, False], [empty, False], [zeroes, False]])
    assert len(toasts) == 3
    for toast in toasts:
        assert "Context compacted — older messages summarized" == toast, toast


def test_a_compaction_that_grew_the_history_is_not_reported_as_a_shrink(compacted):
    """`before > after` is the predicate the sibling already uses. Figures that
    fail it are a measurement that makes no sense, and printing them would put a
    nonsense on screen rather than a silence."""
    backwards = {"type": "compacted", "data": {"messages_before": 4, "messages_after": 9,
                                               "tokens_before": 100, "tokens_after": 900}}
    [toast] = _run(compacted, [[backwards, False]])
    assert toast == "Context compacted — older messages summarized", toast


def test_a_background_stream_still_says_nothing(compacted):
    """A toast about a chat you are not looking at is a toast about nothing."""
    assert _run(compacted, [[_FIGURES, True]]) == []
