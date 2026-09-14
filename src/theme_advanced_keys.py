# SPDX-License-Identifier: AGPL-3.0-or-later
"""The advanced-colour keys a theme can carry, read out of the file that owns them.

`B21`. A theme's advanced colours are one list, and it was written out eleven
times: seven front-end sites agreeing at 14 keys, and four `src/` sites — an
`adv_keys` set and an error string in `ai_interaction.py`, an `adv_keys` list
and the `create_theme` JSON schema in `tool_schemas.py` — agreeing with each
other at 16 and with the front end at neither end. Measured 2026-09-14, the
four accepted `accentPrimary`, `accentError`, `sectionAccent` and `toggleBg`,
which no writer under `static/` writes, and lacked `brandMixTo` and
`hamburgerColor`, which the theme editor offers. So `create_theme` validated
four keys into the user's stored theme that nothing would ever paint, reported
them as *"with N advanced overrides"*, and dropped two real ones on the floor.

The list is not retyped here. `ADV_KEYS` in `static/js/theme.js` is the
authority — it is what `applyColors()` walks on every theme switch — and this
module parses it. The coupling looks fragile and is the opposite: `create_theme`
has no effect of its own, it emits a `create_theme` ui_event that
`static/js/theme.js` applies. Deriving the accepted keys from that exact file
makes the server accept precisely what the browser can paint, by construction.

That is also why there is **no hardcoded fallback list**. If `theme.js` cannot
be read or parsed, the front end that would apply the event is itself broken or
gone; a fallback would let `create_theme` keep claiming success for overrides
nothing can paint, which is the defect this module exists to remove. An
unreadable file yields an empty tuple, `create_theme` says so, and the base
colours still work.

`ADV_KEYS` is protected from renaming by `.pantheon/FORBIDDEN.md`, and
`tests/test_advanced_key_mirrors_js.py` holds this parse equal to the real
`ADV_KEYS` evaluated in node — so a reformat that defeats the parser fails
there rather than silently emptying the schema.
"""

from __future__ import annotations

import logging
import os
import re
from typing import NamedTuple

from src.constants import STATIC_DIR

logger = logging.getLogger(__name__)

THEME_JS = os.path.join(STATIC_DIR, "js", "theme.js")

# The five positional colours `create_theme` takes before any key=value pair.
# The JSON schema spells the accent `accent`; the wire format and the stored
# theme spell it `red`. Named here so the converter can tell a base colour from
# an advanced one without a second copy of either list.
BASE_COLOR_KEYS = ("bg", "fg", "panel", "border", "accent")


class ThemeAdvancedKey(NamedTuple):
    key: str      # the name in `theme.colors.advanced` and on the wire
    css: str      # the custom property `applyColors()` sets from it
    label: str    # the theme editor's own row label
    group: str    # the editor section that row sits in


def _parse_adv_keys(source: str) -> tuple[ThemeAdvancedKey, ...]:
    """Pull `ADV_KEYS` out of `theme.js` source.

    Bracket-matched rather than line- or regex-matched on the whole array: the
    entries carry labels with commas and apostrophes in them, and a flat
    pattern that works today stops at the first one that does not.

    Fields are read by name inside each entry, not by position, so reordering
    `key`/`css`/`label`/`group` — or adding a fifth field — parses unchanged.
    """
    anchor = source.find("const ADV_KEYS = [")
    if anchor < 0:
        return ()
    start = source.index("[", anchor)
    depth = 0
    body = None
    for i in range(start, len(source)):
        if source[i] == "[":
            depth += 1
        elif source[i] == "]":
            depth -= 1
            if depth == 0:
                body = source[start + 1 : i]
                break
    if body is None:
        return ()

    out = []
    for entry in re.findall(r"\{[^{}]*\}", body):
        fields = dict(re.findall(r"(\w+)\s*:\s*'([^']*)'", entry))
        if "key" in fields and "css" in fields:
            out.append(
                ThemeAdvancedKey(
                    fields["key"],
                    fields["css"],
                    fields.get("label", fields["key"]),
                    fields.get("group", ""),
                )
            )
    return tuple(out)


def _load() -> tuple[ThemeAdvancedKey, ...]:
    try:
        with open(THEME_JS, "r", encoding="utf-8") as handle:
            keys = _parse_adv_keys(handle.read())
    except OSError as exc:
        logger.error("theme advanced keys: cannot read %s (%s); create_theme "
                     "will accept base colours only", THEME_JS, exc)
        return ()
    if not keys:
        logger.error("theme advanced keys: no ADV_KEYS entries parsed from %s; "
                     "create_theme will accept base colours only", THEME_JS)
    return keys


ADVANCED_KEYS: tuple[ThemeAdvancedKey, ...] = _load()

# Editor order, not alphabetical — this is the order a person sees the rows in,
# and it is what the tool's error messages and the emitted key=value tail use.
ADVANCED_KEY_NAMES: tuple[str, ...] = tuple(e.key for e in ADVANCED_KEYS)
_ADVANCED_KEY_SET = frozenset(ADVANCED_KEY_NAMES)


def is_advanced_key(name: str) -> bool:
    return name in _ADVANCED_KEY_SET


def advanced_keys_prose() -> str:
    """The key names for an error message the model has to act on.

    The empty case names its own cause rather than reading as "this theme has
    no advanced colours" — that state means `theme.js` could not be parsed, and
    the browser cannot paint an override either way.
    """
    if not ADVANCED_KEY_NAMES:
        return f"none — {THEME_JS} could not be read, so only base colors are available"
    return ", ".join(ADVANCED_KEY_NAMES)


def advanced_schema_properties() -> dict:
    """The `colors` properties block for `create_theme`'s JSON schema.

    Descriptions come from the editor's own `label`/`group`, so the name the
    model is told and the name the user reads in the theme editor are the same
    string. They were hand-written prose and had drifted along with the keys.
    """
    return {
        entry.key: {
            "type": "string",
            "description": (
                f"{entry.group}: {entry.label} (hex, optional)"
                if entry.group
                else f"{entry.label} (hex, optional)"
            ),
        }
        for entry in ADVANCED_KEYS
    }
