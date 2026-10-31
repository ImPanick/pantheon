# SPDX-License-Identifier: AGPL-3.0-or-later
r"""`B1718` — what a voice chat says of a reply is what a person reading it
out would say, and the first sentence is said before the reply is finished.

`speakableText` (`static/js/speechText.js`) keeps the words of a Markdown
reply and drops what is written for the eye: thinking, code, tables, link
addresses, emphasis marks, emoji. `SpeechChunker` is fed the text so far, as
the chat's stream holds it, and answers the sentences that are finished and
not yet said; a construct still open at the end (a code fence, a link whose
address is still arriving, a `<think>`) is held back until it closes, so a
sentence is never said and then turned into something else.

No DOM, ever: the read-aloud this replaces gave model output to `innerHTML`,
where an `<img onerror>` runs. `tts-ai.js` now asks this module too.

Driven (`Law 20`): the real module under node.
"""
from __future__ import annotations

import shutil

import pytest

from tests.helpers.voice_call_sandbox import build, run

pytestmark = pytest.mark.skipif(not shutil.which("node"), reason="node binary not on PATH")

REPLY = r"""<think>Let me think about it.</think>Sure! Here's what I found about **Pantheon**.

## Setup
1. Install it with `pip install pantheon`.
2. Read the [docs](https://docs.example.com/setup) or https://www.github.com/ImPanick/pantheon for more.

```python
print("hello")
```

| a | b |
|---|---|
| 1 | 2 |

Dr. Smith said the U.S. version is 3.14 → stable 🚀. That's it… really. Done"""


@pytest.fixture(scope="module")
def box(tmp_path_factory):
    return build(tmp_path_factory.mktemp("speechtext"))


def test_a_reply_is_said_as_its_words(box):
    o = run(box, f"out.said = ST.speakableText({REPLY!r});")
    assert o["said"] == (
        "Sure! Here's what I found about Pantheon.\nSetup\nInstall it with pip install pantheon.\n"
        "Read the docs or github.com for more.\n"
        "Dr. Smith said the U.S. version is 3.14 to stable. That's it… really. Done"
    )


def test_a_reply_streamed_a_few_characters_at_a_time_is_said_once_in_order(box):
    o = run(box, f"""
        const reply = {REPLY!r};
        const ch = new ST.SpeechChunker();
        out.pieces = [];
        for (let i = 1; i <= reply.length; i += 7) for (const p of ch.push(reply.slice(0, i))) out.pieces.push([i, p]);
        for (const p of ch.finish(reply)) out.pieces.push(['end', p]);
    """)
    said = [p for _, p in o["pieces"]]
    assert said == [
        "Sure!", "Here's what I found about Pantheon.", "Setup", "Install it with pip install pantheon.",
        "Read the docs or github.com for more.", "Dr. Smith said the U.S. version is 3.14 to stable.",
        "That's it… really.", "Done",
    ]
    # The first words go while most of the reply is still to come.
    assert o["pieces"][0][0] < 60
    # The code block is never read, and the sentence after it waits for it to close.
    assert all("print" not in p and "hello" not in p for p in said)


@pytest.mark.parametrize("text, held", [
    ("Run this:\n```bash\nrm -rf build", "Run this:"),
    ("See the [guide](https://exa", "See the"),
    ("<think>I should check the tests", ""),
    ("Use `pip ins", "Use"),
])
def test_what_is_still_open_is_not_said_yet(box, text, held):
    o = run(box, f"out.settled = ST.settledText({text!r}).trim();")
    assert o["settled"] == held


def test_dots_that_do_not_end_a_sentence_do_not_end_one(box):
    o = run(box, """
        out.pieces = ST.speechPieces('Mr. Jones met Dr. Lee at 3.30 p.m. on Jan. 5 near St. Paul. They talked about e.g. pricing, i.e. the costs. Then they left.',
          { joinUnder: 0 });
    """)
    assert o["pieces"] == [
        "Mr. Jones met Dr. Lee at 3.30 p.m. on Jan. 5 near St. Paul.",
        "They talked about e.g. pricing, i.e. the costs.",
        "Then they left.",
    ]


def test_a_long_sentence_is_broken_at_a_clause_not_mid_phrase(box):
    o = run(box, """
        const long = 'One long sentence without any stop at all that keeps going and going, with a comma here and more words after it until it is far too long to send as one piece to any voice that has a limit on what one request may hold and so it must be cut somewhere sensible and then it goes on even further past every limit there is, because nothing stops it';
        out.pieces = ST.speechPieces(long);
    """)
    assert all(len(p) <= 260 for p in o["pieces"])
    assert all(p.endswith(",") for p in o["pieces"][:-1])
    assert " ".join(o["pieces"]) == (
        "One long sentence without any stop at all that keeps going and going, with a comma here and more "
        "words after it until it is far too long to send as one piece to any voice that has a limit on what "
        "one request may hold and so it must be cut somewhere sensible and then it goes on even further past "
        "every limit there is, because nothing stops it")


def test_markup_in_a_reply_is_never_markup(box):
    """The text is never parsed as HTML: a tag is dropped as text, and
    nothing in it can run."""
    o = run(box, """
        globalThis.ran = false;
        out.said = ST.speakableText('Look <img src=x onerror="globalThis.ran = true"> here.<br>Next line.');
        out.ran = globalThis.ran;
    """)
    assert o["said"] == "Look here.\nNext line."
    assert o["ran"] is False


def test_an_entity_is_read_once(box):
    """Each entity in a reply is read once: `&amp;lt;` is the text `&lt;`.
    Read twice, as chained replaces did, it became a `<` the reply never had
    (CodeQL `js/double-escaping`; `markdown.js` decodes maths the same way)."""
    o = run(box, """
        out.said = ['Fish &amp; chips', 'Write &amp;lt;b&amp;gt; for bold', '5 &lt; 6 &amp;&amp; 7 &gt; 6',
                    'She said &quot;hi&quot; &amp; it&#39;s done', 'one&nbsp;two'].map((t) => ST.speakableText(t));
    """)
    assert o["said"] == [
        "Fish and chips", "Write &lt;b&gt; for bold", "5 < 6 && 7 > 6",
        "She said \"hi\" and it's done", "one two",
    ]


def test_short_sentences_are_joined_and_lone_symbols_dropped(box):
    o = run(box, "out.pieces = ST.speechPieces('Yes. Done. — 🎉 Here is the longer explanation of the rest.');")
    assert o["pieces"] == ["Yes. Done. Here is the longer explanation of the rest."]
