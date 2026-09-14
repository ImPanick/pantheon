# SPDX-License-Identifier: AGPL-3.0-or-later
"""`B21` — what `create_theme` does with a key, as opposed to which keys it lists.

`tests/test_advanced_key_mirrors_js.py` holds the *set*: `src/` and the seven
front-end mirrors describe one theme. This file holds the three behaviours that
were wrong underneath it, and none of them is visible from the lists alone.

Measured 2026-09-14, one call showed all three at once::

    create_theme neon #000000 #ffffff #111111 #222222 #ff00ff \\
        accentPrimary=#123456 brandMixTo=#abcdef

    → colors.advanced == {'accentPrimary': '#123456'}
      results == "... created and applied with 1 advanced overrides"

  * `accentPrimary` is a key **no writer writes**. `P1-02` deleted it from
    `ADV_KEYS`, so `applyColors()` never sets `--accent-primary`; the value was
    validated, stored in the user's theme, and survived export and import,
    painting nothing;
  * the count said **1 advanced override** and one override is precisely what
    did not happen. The agent asserted an effect to the user that no code
    performed;
  * `brandMixTo` — the theme editor's *Logo Gradient End*, a real row a person
    can drag a colour onto — vanished. The parse loop's `if/elif` chain had no
    final `else`, so an unrecognised key fell out of the bottom with no error,
    no message and no trace.

The fixes and why they have the shape they do:

  * the accepted set is **derived** from `ADV_KEYS` in `static/js/theme.js`
    (`src/theme_advanced_keys.py`), because `create_theme` has no effect of its
    own — it emits a ui_event that `static/js/theme.js` applies. That makes the
    count honest as a consequence rather than as a second rule: every key that
    validates is a key `applyColors()` paints;
  * an unrecognised **key** errors. The model can act on it — the valid names
    are in the message — and one retry lands the colour the user asked for;
  * a bare word with no `=` is **reported in the result** instead. It is as
    likely to be a trailing comment as a mistyped option, and failing an
    otherwise complete call over one would lose a theme to punctuation. Either
    way it no longer vanishes, which was the defect.
"""

import asyncio
import importlib
import json

import pytest

from src import ai_interaction, constants, theme_advanced_keys, tool_schemas

BASE = "#000000 #ffffff #111111 #222222 #ff00ff"
MARK = "#0b0c0d"

# Real editor rows the tool could not reach. Named rather than derived: the
# point of these two is that they were *missing*, and deriving them from the
# same list the fix derives would make the assertion circular.
WAS_MISSING = ("brandMixTo", "hamburgerColor")

# Keys `P1-02` retired from every front-end writer and `src/` kept accepting.
WAS_PHANTOM = ("accentPrimary", "accentError", "sectionAccent", "toggleBg")


def _create(tail: str = "") -> dict:
    return asyncio.run(ai_interaction.do_ui_control(f"create_theme probe {BASE} {tail}".strip()))


def _native(colors: dict) -> dict:
    """The same call as a model function call, through the real converter."""
    block = tool_schemas.function_call_to_tool_block(
        "ui_control",
        json.dumps({"action": "create_theme", "name": "probe", "colors": colors}),
    )
    return asyncio.run(ai_interaction.do_ui_control(block.content))


# ── The silent drop ─────────────────────────────────────────────────────────


@pytest.mark.parametrize("key", WAS_MISSING)
def test_a_real_editor_key_reaches_the_stored_theme(key):
    """Both were dropped with no error: `create_theme` reported a theme created
    and the colour the user named was simply not in it."""
    out = _create(f"{key}={MARK}")
    assert "error" not in out, out
    assert out["colors"]["advanced"] == {key: MARK}, out


@pytest.mark.parametrize("key", WAS_MISSING)
def test_the_native_function_call_path_reaches_it_too(key):
    """The converter filtered against its own copy of the list before
    `do_ui_control` ever saw the key, so the text path being fixed alone would
    have left a model's function call still dropping it."""
    out = _native({"bg": "#000000", "fg": "#ffffff", "panel": "#111111",
                   "border": "#222222", "accent": "#ff00ff", key: MARK})
    assert "error" not in out, out
    assert out["colors"]["advanced"] == {key: MARK}, out


def test_an_unrecognised_key_errors_and_names_the_real_ones():
    out = _create(f"notAKeyAtAll={MARK}")
    assert "error" in out, f"an unknown key was swallowed again: {out}"
    assert "notAKeyAtAll" in out["error"], out["error"]
    assert "ui_event" not in out, f"a theme was created anyway: {out}"
    for key in theme_advanced_keys.ADVANCED_KEY_NAMES:
        assert key in out["error"], (
            f"the error does not name `{key}`, so the model cannot correct "
            f"itself from it: {out['error']}"
        )


@pytest.mark.parametrize("spelling", ["SIDEBARBG", "sidebarbg", "SidebarBg", "sidebar_bg"])
def test_a_near_miss_spelling_is_refused_rather_than_stored_under_itself(spelling):
    """The key is a property name in the stored theme, and `applyColors()` looks
    it up exactly. A lenient match would validate `sidebarbg`, store it, count
    it as an override and paint nothing — the same lie with better manners."""
    out = _create(f"{spelling}={MARK}")
    assert "error" in out, f"`{spelling}` was accepted: {out}"
    assert "advanced" not in out.get("colors", {}), out


def test_the_unknown_key_error_still_names_the_background_effect_keys():
    """`Law 1`. The background-effect options share this parse loop, and an
    error listing only colours would read as "those are the valid keys" and
    teach the model to stop sending `bgPattern`."""
    out = _create(f"notAKeyAtAll={MARK}")
    for key in ("bgPattern", "bgEffectColor", "bgEffectIntensity", "bgEffectSize", "frosted"):
        assert key in out["error"], out["error"]


@pytest.mark.parametrize("key", WAS_PHANTOM)
def test_a_key_no_writer_writes_is_refused_rather_than_stored(key):
    """They validated, persisted into the stored theme and survived an
    export/import round trip, and nothing has ever read the token they name."""
    out = _create(f"{key}={MARK}")
    assert "error" in out, f"`{key}` is still accepted: {out}"
    assert "colors" not in out, f"`{key}` still reached a stored theme: {out}"


# ── The count ───────────────────────────────────────────────────────────────


def test_the_override_count_counts_only_keys_that_landed():
    """"with N advanced overrides" is the sentence the user reads. Every key it
    counts has to be one `applyColors()` will paint — which, now that the
    accepted set is derived from `ADV_KEYS`, is every key that survives
    validation. The assertion is against the stored theme, not against the
    input, so an accepted-but-dropped key would still be caught."""
    keys = list(theme_advanced_keys.ADVANCED_KEY_NAMES)
    assert keys, "no advanced keys at all — this test would pass vacuously"

    for count in (1, 2, len(keys)):
        chosen = keys[:count]
        out = _create(" ".join(f"{k}={MARK}" for k in chosen))
        assert "error" not in out, out
        stored = out["colors"]["advanced"]
        assert set(stored) == set(chosen), out
        assert f"with {len(stored)} advanced overrides" in out["results"], out["results"]
        for key in stored:
            assert key in theme_advanced_keys.ADVANCED_KEY_NAMES, (
                f"`{key}` was counted as an override and no writer writes it"
            )


def test_no_override_count_is_claimed_when_nothing_was_overridden():
    out = _create()
    assert "advanced overrides" not in out["results"], out["results"]
    assert "advanced" not in out["colors"], out


def test_a_repeated_key_is_counted_once():
    out = _create(f"sidebarBg=#111111 sidebarBg={MARK}")
    assert out["colors"]["advanced"] == {"sidebarBg": MARK}, out
    assert "with 1 advanced overrides" in out["results"], out["results"]


# ── The bare word ───────────────────────────────────────────────────────────


def test_a_bare_word_is_reported_rather_than_dropped():
    out = _create("frosted")
    assert "error" not in out, f"a trailing word failed the whole call: {out}"
    assert "frosted" in out["results"], (
        f"`frosted` was ignored with no trace, which is the defect one key over: {out['results']}"
    )


def test_a_bare_word_does_not_become_an_override():
    out = _create(f"sidebarBg={MARK} frosted")
    assert out["colors"]["advanced"] == {"sidebarBg": MARK}, out
    assert "with 1 advanced overrides" in out["results"], out["results"]
    assert "frosted" in out["results"], out["results"]


# ── Law 1: everything that worked still works ───────────────────────────────


def test_the_base_colours_still_make_a_theme():
    out = _create()
    assert out["ui_event"] == "create_theme"
    assert out["colors"] == {"bg": "#000000", "fg": "#ffffff", "panel": "#111111",
                             "border": "#222222", "red": "#ff00ff"}


@pytest.mark.parametrize(
    "tail,expected",
    [
        ("bgPattern=rain", {"pattern": "rain"}),
        ("bgEffectColor=#abcdef", {"effectColor": "#abcdef"}),
        ("bgEffectIntensity=1.5", {"effectIntensity": 1.5}),
        ("bgEffectSize=2", {"effectSize": 2.0}),
        ("frosted=true", {"frosted": True}),
        ("frosted=off", {"frosted": False}),
    ],
)
def test_the_background_effect_keys_share_the_loop_and_still_work(tail, expected):
    out = _create(tail)
    assert "error" not in out, out
    assert out["bg"] == expected, out


@pytest.mark.parametrize(
    "tail,fragment",
    [
        ("sidebarBg=nothex", "Invalid hex color for advanced key sidebarBg"),
        ("bgPattern=spirals", "Invalid bgPattern"),
        ("bgEffectColor=nope", "Invalid hex color for bgEffectColor"),
        ("bgEffectIntensity=loud", "Invalid number for bgEffectIntensity"),
    ],
)
def test_the_existing_validation_errors_are_unchanged(tail, fragment):
    out = _create(tail)
    assert fragment in out.get("error", ""), out


def test_an_advanced_key_and_a_background_effect_coexist():
    out = _create(f"sidebarBg={MARK} bgPattern=embers frosted=true")
    assert out["colors"]["advanced"] == {"sidebarBg": MARK}, out
    assert out["bg"] == {"pattern": "embers", "frosted": True}, out
    assert "with 1 advanced overrides" in out["results"], out["results"]
    assert "background effect (embers)" in out["results"], out["results"]


# ── The parser, and the absence of a fallback ───────────────────────────────


def test_the_parser_reads_fields_by_name_not_by_position():
    """`ADV_KEYS` entries are `{ key, css, label, group }` today. A parser that
    depends on that order turns a tidy-up of the JS into an empty schema."""
    source = """
const ADV_KEYS = [
  { css: '--b-a', key: 'alpha', group: 'G', label: 'A, with a comma' },
  { key: 'beta', css: '--b-b', label: 'B', group: 'G', extra: 'ignored' },
];
"""
    parsed = theme_advanced_keys._parse_adv_keys(source)
    assert [e.key for e in parsed] == ["alpha", "beta"]
    assert [e.css for e in parsed] == ["--b-a", "--b-b"]
    assert parsed[0].label == "A, with a comma"


def test_an_entry_with_no_css_variable_is_skipped_rather_than_raising():
    """`css` is the custom property `applyColors()` sets; an entry without one
    is a key nothing could paint. Skipping it keeps a malformed `theme.js` from
    raising at import — which would take the whole app down — and the
    equality in `test_advanced_key_mirrors_js.py` is what makes it loud."""
    source = """
const ADV_KEYS = [
  { key: 'alpha', css: '--b-a', label: 'A', group: 'G' },
  { key: 'halfWritten', label: 'H', group: 'G' },
];
"""
    assert [e.key for e in theme_advanced_keys._parse_adv_keys(source)] == ["alpha"]


def test_the_parser_stops_at_the_end_of_the_array():
    """`theme.js` carries `THEMES`, `_THEME_ZONE_MAP` and several other object
    literals; a parser that runs past `];` collects palette names as keys."""
    source = """
const ADV_KEYS = [
  { key: 'alpha', css: '--b-a', label: 'A', group: 'G' },
];
const OTHER = [ { key: 'notAnAdvancedKey', css: '--nope', label: 'N', group: 'G' } ];
"""
    assert [e.key for e in theme_advanced_keys._parse_adv_keys(source)] == ["alpha"]


@pytest.mark.parametrize("source", ["", "const OTHER = [];", "const ADV_KEYS = ["])
def test_an_unparseable_source_yields_nothing_rather_than_a_guess(source):
    assert theme_advanced_keys._parse_adv_keys(source) == ()


@pytest.mark.parametrize("contents", [None, "// theme.js, but nothing this parser understands\n"])
def test_an_unreadable_theme_js_refuses_overrides_instead_of_inventing_them(
    monkeypatch, tmp_path, caplog, contents
):
    """There is deliberately no hardcoded fallback list behind the parse.

    If `static/js/theme.js` cannot be read, the front end that would apply the
    `create_theme` ui_event is broken or absent, so a fallback would only let
    the tool go on claiming overrides that nothing can paint — the exact defect
    `B21` is about, surviving in the one case it would fire. The base colours
    still work, and the refusal names the file.

    Both halves of "cannot be read" are exercised, because they are separate
    branches and only one of them is an exception: the file missing, and the
    file present with no `ADV_KEYS` the parser can find — a reformat or a
    rename. The second is the quieter one and the one that needs its own log.
    """
    real = tuple(theme_advanced_keys.ADVANCED_KEY_NAMES)
    assert real, "the module parsed nothing to begin with"
    if contents is not None:
        (tmp_path / "js").mkdir()
        (tmp_path / "js" / "theme.js").write_text(contents, encoding="utf-8")
    monkeypatch.setattr(constants, "STATIC_DIR", str(tmp_path))
    try:
        with caplog.at_level("ERROR"):
            importlib.reload(theme_advanced_keys)
        assert theme_advanced_keys.ADVANCED_KEYS == (), theme_advanced_keys.ADVANCED_KEYS
        assert any("theme.js" in r.getMessage() for r in caplog.records), caplog.text

        out = _create(f"sidebarBg={MARK}")
        assert "error" in out, f"an override was accepted with no theme.js to paint it: {out}"
        assert "theme.js" in out["error"], out["error"]

        base = _create()
        assert base["ui_event"] == "create_theme", base
    finally:
        monkeypatch.undo()
        importlib.reload(theme_advanced_keys)
    assert tuple(theme_advanced_keys.ADVANCED_KEY_NAMES) == real
