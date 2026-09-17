# SPDX-License-Identifier: AGPL-3.0-or-later
"""`B301` — the refused SVG preview was drawn, and not announced.

`B160` made a refusal a *picture* that says **"Preview blocked"** and which rule
fired, and put the slug on the response as `X-Preview-Refused` so anything that
can read a header does not have to re-derive it. The chip is
`<img src="/api/upload/{id}?thumb=1" alt="{filename}">`, and **an `<img>` can
read neither the header nor the `<title>` inside the SVG it draws** — so a
sighted person got the explanation and a person using a screen reader was told
*"diagram.svg"*, exactly as before the row that added the explanation. `Law 15`:
the affordance exists and one class of user cannot reach it.

Measured on the tree as it stood, by driving the real chip-render block under
node: the `<img>`'s accessible name was the filename, nothing else ever set it,
and no request was made that could have.

`Law 20`: both halves run the real code out of `static/js/chatRenderer.js` —
the helper itself, and the call site, because a helper nothing calls is the
shape of this defect rather than its fix.

**The `Caption` button is deliberately left alone, and that is a decision.** The
row suggests the same read should hide it on a refused chip. Measured, it should
not: `B163` reads an SVG's caption out of its own `<title>`, `<desc>` and
`<text>` runs with no model and no render, so it works perfectly well on a file
whose *preview* was refused — and on a refused chip it is the only control that
can say what the drawing contains. Hiding it would remove a working affordance
to tidy a different one (`Law 1`). `test_the_caption_button_still_works_on_a_refused_svg`
is that decision, driven rather than asserted in prose.
"""
import json
import shutil
import subprocess
from pathlib import Path

import pytest

import src.svg_runtime as svg_runtime

# `getattr` for the same reason the other files in this wave use it: the header
# and the one-sentence lookup are what this row adds, and a module-level
# ImportError would turn nine separate pieces of evidence into one.
SVG_REFUSAL_TEXT_HEADER = getattr(svg_runtime, "SVG_REFUSAL_TEXT_HEADER",
                                  "X-Preview-Refused-Text")
svg_refusal_sentence = getattr(
    svg_runtime, "svg_refusal_sentence",
    lambda reason: svg_runtime.SVG_REFUSAL_TEXT.get(
        reason, "It did not pass the safety check."))

ROOT = Path(__file__).resolve().parent.parent
H_ALT = ROOT / "tests" / "harness" / "svg_refusal_alt.js"

pytestmark = pytest.mark.skipif(not shutil.which("node"),
                                reason="node binary not on PATH")


def _run(*argv: str) -> dict:
    proc = subprocess.run(["node", str(H_ALT), *argv],
                          capture_output=True, text=True)
    assert proc.returncode == 0, f"{H_ALT.name} {argv}: {proc.stderr}"
    return json.loads(proc.stdout)


def test_a_refused_chips_accessible_name_says_it_was_blocked_and_why():
    """`B301`'s `Verify:` verbatim, driven through the renderer.

    Three things have to be in it and each is there for a reason: the filename,
    because that is what the person is looking for in a strip of chips; the
    reason, because that is the thing they could not previously reach; and the
    reassurance the drawn placeholder already makes, because the most common
    cause of a refusal is a file that is perfectly fine and still downloads.
    """
    out = _run("refused")
    assert out["missing"] is False, (
        "_announceRefusedPreview is not in chatRenderer.js — on the tree as it "
        "stood the accessible name was the filename and nothing set it")
    alt = out["alt"]
    assert "diagram.svg" in alt
    assert "preview blocked" in alt.lower()
    assert svg_runtime.SVG_REFUSAL_TEXT[
        svg_runtime.SVG_REFUSAL_ACTIVE_CONTENT] in alt
    assert "The file itself is unchanged." in alt
    # A `title` as well as an `alt`: the hover tooltip is how a sighted person
    # who is *not* using a screen reader reads a 150x150 chip's small print.
    assert out["title"] == alt


def test_the_renderer_actually_calls_it():
    """The call site, run rather than read.

    A helper nothing invokes is precisely what this row found in the other
    direction — a header nothing read. On the tree as it stood this recorded
    zero calls.
    """
    out = _run("wiring")
    assert out["calls"], "the chip <img> block never announces the refusal"
    assert out["calls"][0]["name"] == "diagram.svg"
    # Called with the img whose alt is still the bare filename, which is the
    # value it exists to replace.
    assert out["calls"][0]["alt"] == "diagram.svg"


def test_a_preview_that_was_not_refused_keeps_its_name():
    """No header means nothing happened, and the alt must be untouched: a chip
    that says "preview blocked" about a drawing that rendered is the same defect
    pointing the other way."""
    out = _run("allowed")
    assert out["alt"] == "diagram.svg"
    assert out["title"] is None


def test_no_request_is_made_for_an_attachment_that_is_not_an_svg():
    """Cost, bounded. Every other image type has nothing to say here, and a
    request per photo in a long conversation is a cost for nothing."""
    out = _run("raster")
    assert out["requests"] == []
    assert out["alt"] == "photo.png"


def test_the_request_is_a_head_and_reads_two_headers():
    """One round trip and zero bytes: `FileResponse`/`Response` answer HEAD, so
    the verdict costs a header read rather than a second download of a
    placeholder."""
    out = _run("refused")
    assert [r["method"] for r in out["requests"]] == ["HEAD"]
    assert out["requests"][0]["url"].endswith("?thumb=1")


def test_a_failed_request_leaves_the_name_exactly_as_it_was():
    """Best-effort, in the direction that cannot make anything worse. A network
    that refuses the HEAD must not leave the chip with a half-written name."""
    out = _run("offline")
    assert out["alt"] == "diagram.svg"
    assert out["title"] is None


def test_the_sentence_comes_from_the_server_and_not_a_copy_in_the_browser():
    """`Law 14`. `svg_runtime.SVG_REFUSAL_TEXT` is the vocabulary; the header
    carries it. A second table in `chatRenderer.js` is the defect this product
    keeps finding, and the header is what makes one unnecessary."""
    assert SVG_REFUSAL_TEXT_HEADER == "X-Preview-Refused-Text"
    for reason, sentence in svg_runtime.SVG_REFUSAL_TEXT.items():
        assert svg_refusal_sentence(reason) == sentence
        # Header-safe by construction: seven fixed ASCII sentences, none of
        # which ever quotes the file.
        assert sentence.isascii()
        assert "\n" not in sentence and "\r" not in sentence
    assert svg_refusal_sentence("not-a-real-slug") == \
        "It did not pass the safety check."


def test_the_route_puts_both_headers_on_a_refusal(tmp_path, monkeypatch):
    """The server half, at the route, over a real file."""
    from tests.test_svg_preview_knows_which_element import _serve
    from tests.test_svg_preview_explains_refusals import HOSTILE

    response, _ = _serve(tmp_path, monkeypatch, HOSTILE["script"])
    headers = {k.lower(): v for k, v in response.headers.items()}
    assert headers["x-preview-refused"] == svg_runtime.SVG_REFUSAL_ACTIVE_CONTENT
    assert headers["x-preview-refused-text"] == \
        svg_runtime.SVG_REFUSAL_TEXT[svg_runtime.SVG_REFUSAL_ACTIVE_CONTENT]
    # And the drawn half is unchanged — the header is additive.
    assert b"Preview blocked" in response.body


def test_the_caption_button_still_works_on_a_refused_svg():
    """The decision the row's last sentence invites and the measurement declines.

    `B163` reads the caption out of the file's own words, with no model and no
    render, so a drawing whose preview was refused for carrying a `<script>`
    still has a perfectly good caption — and on a chip with no picture it is the
    only thing that can say what the drawing is. Removing it would be a
    subtraction (`Law 1`).
    """
    refused = (b'<svg xmlns="http://www.w3.org/2000/svg">'
               b'<title>Deployment topology</title>'
               b'<script>fetch("/api/settings")</script>'
               b'<text>edge</text><text>origin</text></svg>')
    assert svg_runtime.svg_refusal_reason(
        refused, svg_runtime.MAX_PREVIEW_SVG_BYTES, allow_data_images=True,
        allow_hyperlinks=True) == svg_runtime.SVG_REFUSAL_ACTIVE_CONTENT
    caption = svg_runtime.svg_caption_text(refused)
    assert "Deployment topology" in caption
    assert "edge origin" in caption
