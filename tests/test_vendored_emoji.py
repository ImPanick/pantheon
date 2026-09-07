# SPDX-License-Identifier: AGPL-3.0-or-later
"""Emoji render with no network, and OpenMoji is credited.

Two findings in one row.

**The egress.** `/api/emoji/<code>.svg` fetched from the OpenMoji CDN on first
use. Same-origin from the browser's side — the design was careful about that —
but the *server* reached a third party on roughly the first assistant reply,
because models emit emoji constantly. Under `Law 16` that is an outbound call
nobody asked for, and the codepoint sequence is a weak side-channel about what a
message contained.

**The licence.** OpenMoji is **CC BY-SA 4.0** and appeared nowhere in
`CREDITS.md`, `NOTICE` or `licenses/`. The product had been serving its artwork
since before the fork. Attribution is required whether the bytes are proxied or
bundled; vendoring only made the omission easier to see. Given how carefully
`P0` handled the AGPL and MIT obligations, this one being absent is the finding.
"""
import json
import pathlib

import pytest

from routes import emoji_routes as er

REPO = pathlib.Path(__file__).resolve().parent.parent
LIB = REPO / "library" / "emoji"


def test_the_set_ships_with_the_product():
    assert (LIB / "openmoji-black.json").is_file()
    assert (LIB / "MANIFEST.json").is_file()
    assert (LIB / "LICENSE.txt").is_file()


def test_every_glyph_is_available_offline():
    glyphs = er._glyphs()
    assert len(glyphs) > 4000, f"only {len(glyphs)} glyphs vendored"


def test_common_emoji_are_present():
    """A vendored set missing the emoji people actually use is not vendored."""
    glyphs = er._glyphs()
    for code in ("1f600", "1f44d", "2764", "1f389", "1f680", "26a0"):
        assert code in glyphs, f"{code} missing from the vendored set"


def test_the_route_no_longer_reaches_a_cdn():
    """The whole point.

    Two separate checks, because the first version required `httpx` and a call
    on the *same line* and a mutation that split them across two lines
    (`import httpx as _h`, then `_h.get(...)`) walked straight through it.
    """
    src = (REPO / "routes/emoji_routes.py").read_text(encoding="utf-8")
    live = [ln for ln in src.splitlines() if not ln.strip().startswith("#")]
    body = "\n".join(live)

    assert "httpx" not in body, "the emoji route still imports or uses an HTTP client"
    assert "cdn.jsdelivr" not in body, "the CDN base URL is still live in the module"
    for marker in ("AsyncClient", "requests.get", "urlopen"):
        assert marker not in body, f"the emoji route still reaches out via {marker}"


def test_a_rebuilt_glyph_is_well_formed():
    body = er._glyphs()["1f600"]
    svg = (er._SVG_OPEN + body + er._SVG_CLOSE).encode("utf-8")
    assert er._is_safe_svg(svg)
    assert svg.startswith(b"<svg")
    assert svg.endswith(b"</svg>")


def test_the_route_actually_runs_the_sanitiser(monkeypatch):
    """Calling `_is_safe_svg` in a test proves the sanitiser works, not that the
    handler uses it — a mutation that ignored its result sailed past the first
    version of this. So: make the sanitiser reject everything and check the
    handler blanks rather than serving."""
    import asyncio

    router = er.setup_emoji_routes()
    handler = next(r.endpoint for r in router.routes if "{code}" in r.path)

    # `asyncio.run`, not `get_event_loop().run_until_complete`. The latter passed
    # this test alone and failed it in a full sweep, because by then another test
    # had closed the loop it reached for — the exact test-order pollution this
    # project has paid for before.
    good = asyncio.run(handler("1f600"))
    assert b"<g" in bytes(good.body), "a known glyph did not render"

    monkeypatch.setattr(er, "_is_safe_svg", lambda _c: False)
    blanked = asyncio.run(handler("1f600"))
    assert bytes(blanked.body) == er._BLANK_SVG, (
        "the handler served bytes the sanitiser had rejected"
    )


def test_the_hoisted_attributes_are_put_back():
    """Stripped at vendoring time to save 2.6MB; if they are not restored the
    glyphs render as invisible unfilled paths."""
    assert 'stroke="#000000"' in er._SVG_OPEN
    assert 'fill="none"' in er._SVG_OPEN
    assert 'stroke-width="2"' in er._SVG_OPEN
    assert "viewBox" in er._SVG_OPEN


def test_no_glyph_carries_script():
    """Sampled rather than exhaustive — 4,147 regex passes is not worth the
    suite time, and the per-request sanitiser is the real guard."""
    glyphs = er._glyphs()
    for code in list(glyphs)[:400]:
        body = glyphs[code].lower()
        assert "<script" not in body
        assert "onload" not in body
        assert "javascript:" not in body


def test_a_missing_library_degrades_rather_than_raising(monkeypatch, tmp_path):
    monkeypatch.setattr(er, "_GLYPHS", None)
    monkeypatch.setattr(er, "_library_path", lambda: tmp_path / "nope.json")
    assert er._glyphs() == {}
    monkeypatch.setattr(er, "_GLYPHS", None)


# ── the licence half ─────────────────────────────────────────────────────

def test_openmoji_is_attributed():
    """CC BY-SA 4.0's one obligation, and it was unmet for the life of the fork."""
    credits = (REPO / "CREDITS.md").read_text(encoding="utf-8")
    # Both places, and by link rather than by substring: `OpenMoji` appears
    # inside `OpenMojiX` too, so a row replaced with a lookalike passed the
    # first version of this test.
    assert "https://openmoji.org" in credits, "OpenMoji is used and still not credited"
    assert credits.count("https://openmoji.org") >= 2, (
        "OpenMoji is credited in only one of the table and the prose entry"
    )
    assert "CC BY-SA 4.0" in credits, "the licence is not named"
    assert (REPO / "licenses" / "OpenMoji-CC-BY-SA-4.0.txt").is_file()


def test_the_licence_text_travels_with_the_artwork():
    text = (LIB / "LICENSE.txt").read_text(encoding="utf-8")
    assert "Attribution-ShareAlike 4.0" in text


def test_the_manifest_records_the_adaptation():
    """Share-alike applies to what we did to them, not only to the originals."""
    m = json.loads((LIB / "MANIFEST.json").read_text(encoding="utf-8"))
    assert m["licence"] == "CC-BY-SA-4.0"
    assert m["version"]
    assert m["glyphs"] > 4000
    assert "adapted" in m and m["adapted"], "the stripping is not disclosed"
