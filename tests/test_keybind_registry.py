"""H19 / H20 — three copies of the keybind table, and a find bar with no door.

`H19`: `/shortcuts` was a third hardcoded copy of the keybinds. Seven rows
against a runtime twenty-one; it **invented two actions that do not exist**
(`star_session`, `admin_panel`, neither bound to anything anywhere); it omitted
fourteen real ones; and it printed `ctrl+b` for `toggle_sidebar` while the
dispatcher matches `ctrl+alt+b`. The Shortcuts panel had a second copy that
disagreed with the runtime in the same place. So a person could read the wrong
key in two places and be told about keys that do nothing in one of them.

`H20`: the document editor's find bar has match counts, prev/next and highlight
rectangles, and its only caller was a Ctrl+F handler on the editor pane.
`doc-find` appeared zero times in `index.html`: no button, no registry entry, no
mention in the Shortcuts panel or `/shortcuts`.

The two are one change because the second needs the first: naming Find in the
panel is only worth doing once there is one table to name it in.
"""
import pathlib
import re

import pytest

ROOT = pathlib.Path(__file__).resolve().parent.parent
KEYS = (ROOT / "static" / "js" / "keyboard-shortcuts.js").read_text(encoding="utf-8")
SETTINGS = (ROOT / "static" / "js" / "settings.js").read_text(encoding="utf-8")
SLASH = (ROOT / "static" / "js" / "slashCommands.js").read_text(encoding="utf-8")
STREAM = (ROOT / "static" / "js" / "chatStream.js").read_text(encoding="utf-8")
DOC = (ROOT / "static" / "js" / "document.js").read_text(encoding="utf-8")


def _object_literal(source, name):
    """The `{...}` of `const <name> = {` or `const <name> = Object.freeze({`,
    brace-matched. Both spellings, because one registry is frozen and the other
    is not, and a helper that only knows one shape fails with "substring not
    found" rather than saying which."""
    start = source.index(f"{name} = ")
    i = source.index("{", start)
    depth, j = 0, i
    while j < len(source):
        if source[j] == "{":
            depth += 1
        elif source[j] == "}":
            depth -= 1
            if depth == 0:
                return source[i:j + 1]
        j += 1
    raise AssertionError(f"unbalanced braces reading {name}")


def _keys_of(literal):
    return set(re.findall(r"^\s*([a-z_]+)\s*:", literal, re.M))


# ── one table ──

def test_there_is_one_registry_and_the_other_two_import_it():
    """`Law 14`. Three tables that must agree is three chances to disagree, and
    they were taking all three."""
    assert "export const KEYBIND_DEFAULTS = {" in KEYS
    assert "export const KEYBIND_LABELS = {" in KEYS
    assert "const SHORTCUT_DEFAULTS = KEYBIND_DEFAULTS;" in SETTINGS
    assert "const SHORTCUT_LABELS = KEYBIND_LABELS;" in SETTINGS
    assert "import { KEYBIND_DEFAULTS, KEYBIND_LABELS }" in SLASH


def test_no_file_keeps_a_second_copy_of_the_combos():
    """The specific regression: a literal combo string in a file that should be
    reading the registry. `ctrl+alt+n` is the one that appeared in all three."""
    for name, source in (("settings.js", SETTINGS), ("slashCommands.js", SLASH)):
        assert "'ctrl+alt+n'" not in source, f"{name} has its own copy of the combos again"


def test_the_panel_and_the_runtime_agree_about_toggle_sidebar():
    """The measured disagreement: the dispatcher matched `ctrl+alt+b` while the
    panel and `/shortcuts` both showed `ctrl+b`.

    Matched as a PROPERTY ASSIGNMENT, not as a word. The first version asserted
    the string was absent and failed on the comment that explains the bug —
    `Law 20`, fourth time this session, and the first time one of my own tests
    caught it before it shipped rather than after."""
    defaults = _object_literal(KEYS, "KEYBIND_DEFAULTS")
    assert "toggle_sidebar: 'ctrl+alt+b'" in defaults
    assignment = re.compile(r"^\s*toggle_sidebar\s*:\s*'ctrl\+b'", re.M)
    for name, source in (("settings.js", SETTINGS), ("slashCommands.js", SLASH)):
        assert not assignment.search(source), f"{name} assigns the wrong combo again"


def test_shortcuts_no_longer_invents_actions_that_do_not_exist():
    """`star_session` and `admin_panel` were printed as shortcuts. Neither is in
    the registry, neither is bound by the dispatcher, neither ever was.

    Matched as a READ of the name — `keybinds.star_session`, or a key in an
    object literal — rather than as a word, because the comment recording the
    defect necessarily contains both names."""
    registry = _keys_of(_object_literal(KEYS, "KEYBIND_DEFAULTS"))
    for invented in ("star_session", "admin_panel"):
        assert invented not in registry, f"{invented} appeared in the registry"
        used = re.compile(rf"(keybinds\.{invented}\b|^\s*{invented}\s*:)", re.M)
        assert not used.search(SLASH), f"/shortcuts still reads {invented}"
        assert not used.search(KEYS), f"the registry still defines {invented}"


def test_every_action_has_a_label():
    """A generated list falls back to the raw key when a label is missing, which
    is how `open_theme` would end up printed as `open_theme`."""
    defaults = _keys_of(_object_literal(KEYS, "KEYBIND_DEFAULTS"))
    labels = _keys_of(_object_literal(KEYS, "KEYBIND_LABELS"))
    assert defaults - labels == set(), f"no label for: {sorted(defaults - labels)}"


def test_unbound_actions_are_skipped_not_printed_blank():
    """Most open-tool shortcuts ship with an empty combo so people can assign
    their own. Printing them as a shortcut with no key is how a help screen
    starts lying again."""
    body = SLASH.split("async function _cmdShortcuts(", 1)[1].split("\n}", 1)[0]
    assert ".filter((action) => (keybinds[action] || '').trim())" in body


def test_the_list_is_generated_not_enumerated():
    body = SLASH.split("async function _cmdShortcuts(", 1)[1].split("\n}", 1)[0]
    assert "Object.keys(KEYBIND_DEFAULTS)" in body
    # Enter / Shift+Enter are not keybinds and nothing can rebind them.
    assert "'Send message'" in body and "'New line'" in body


# ── H20 ──

def test_find_is_in_the_registry():
    defaults = _object_literal(KEYS, "KEYBIND_DEFAULTS")
    assert "doc_find:" in defaults
    assert "doc_find: 'Find in document'" in _object_literal(KEYS, "KEYBIND_LABELS")


def test_find_is_not_bound_globally():
    """Ctrl+F outside a document belongs to the browser. The dispatcher is an
    explicit chain, so an entry is display-only unless someone writes a case for
    it — and `KEYBIND_LOCAL_ONLY` says so out loud rather than leaving it to be
    inferred from an absence."""
    assert "KEYBIND_LOCAL_ONLY" in KEYS
    assert "'doc_find'" in KEYS.split("KEYBIND_LOCAL_ONLY", 1)[1][:120]
    dispatcher = KEYS.split("export function initKeyboardShortcuts(", 1)[1]
    assert "kb.doc_find" not in dispatcher
    assert "_matchesCombo(e, kb['doc_find']" not in dispatcher


def test_the_editor_reads_the_registry_rather_than_hardcoding_the_combo():
    """A registry entry the editor ignored would be worse than no entry: the
    panel would offer to change a key and nothing would change."""
    handler = DOC.split("// Find, on the editor pane only. `H20`.", 1)[1].split("});", 1)[0]
    assert "window._pantheonKeybinds" in handler
    assert "doc_find" in handler
    assert "_matchesCombo" in handler
    assert "e.key === 'f'" not in handler, "the hardcoded key is gone"


def test_the_find_bar_has_a_button():
    assert 'id="doc-find-btn"' in DOC
    assert "#doc-find-btn" in DOC, "and something binds it"
    wiring = DOC.split("#doc-find-btn')?.addEventListener", 1)[1][:200]
    assert "_openFindBar()" in wiring


def test_the_button_and_the_key_reach_the_same_place():
    """Two entry points that drift are how this row happens twice."""
    assert DOC.count("_openFindBar();") >= 2


def test_the_shortcuts_panel_lists_find():
    assert "'doc_find'" in SETTINGS
    categories = SETTINGS.split("const SHORTCUT_CATEGORIES = [", 1)[1].split("];", 1)[0]
    assert "doc_find" in categories, "Find must appear in a category or the panel never draws it"


# ── H19, the other half: the toggle map, and the diagnostics ──

def test_there_is_one_toggle_map_and_it_has_every_toggle():
    """There were FOUR copies: one complete in `chatStream.js` and three in
    `slashCommands.js` that were missing `rag` and `incognito`. Same disease as
    the keybind table, in the same file, found while fixing it."""
    assert "export const TOGGLE_CHECKBOX_IDS" in STREAM
    assert "import { TOGGLE_CHECKBOX_IDS }" in SLASH
    literal = _object_literal(STREAM, "TOGGLE_CHECKBOX_IDS")
    for name in ("web", "bash", "rag", "research", "incognito"):
        assert f"{name}:" in literal, f"the one map is missing {name}"
    assert not re.search(r"const toggleMap = \{ web:", SLASH), \
        "slashCommands.js is keeping its own copy again"


def test_toggle_rag_exists_now():
    """`_cmdToggleRag` was defined at `:1220` with no registry entry, so
    `/toggle rag` did not exist — and it could not have worked if it had, since
    three of the four maps had no `rag` key: `getElementById(undefined)` is
    null and `_applyToggle` returned without doing anything or saying so."""
    subs = SLASH.split("'web':", 1)[1][:1400]
    assert "'rag':" in subs and "_cmdToggleRag" in subs
    assert 'id="rag-toggle"' in (ROOT / "static" / "index.html").read_text(encoding="utf-8"), \
        "the checkbox the map points at must exist, or this is wired to nothing"


@pytest.mark.parametrize("command", ["probe", "stats", "sh"])
def test_the_three_diagnostics_are_no_longer_hidden(command):
    """`hidden: true` filters a command from BOTH `/help` and the autocomplete,
    so these three had no door at all. `/probe` is the only way to learn an
    endpoint is up while half its models 404; `/sh` is the only general-purpose
    command runner a person can reach — and it is admin-gated server-side, so
    hiding it was obscurity rather than protection."""
    i = SLASH.index("\n  " + command + ":")
    tail = SLASH[i + 1:]
    # A command is either one line (`probe:   { ... },`) or a braced block.
    # Taking a fixed window spilled into the NEXT command, which is hidden —
    # so the test reported /probe as hidden while looking at /color.
    first_line = tail.split("\n", 1)[0]
    block = first_line if first_line.rstrip().endswith("},") else tail.split("\n  },", 1)[0]
    assert "hidden: true" not in block, f"/{command} is still hidden from /help"


def test_the_diagnostics_have_their_own_category():
    """Un-hiding three commands into `Utility` buries them among fifteen
    others. They are a surface, which is what the row asked for."""
    assert SLASH.count("category: 'Diagnostics'") >= 3


def test_help_still_filters_on_hidden():
    """The mechanism has to stay: `/help` is generated, and `hidden` is how a
    command opts out. Removing the filter would be a different bug."""
    assert "if (def.hidden) continue;" in SLASH
