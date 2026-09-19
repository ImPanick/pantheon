# SPDX-License-Identifier: AGPL-3.0-or-later
"""P3-12 — 24 ids in the markup that nothing reads, itemised, and one feature.

The row asked for *"delete the verified-dead elements and handlers"* and, under
`Law 9`, could not be ticked until somebody named them. Naming them is most of
the work, and it does not end where the row expected: **none of the 24 is a dead
element**. They are an id attribute on a live element, or an anchor for
something that was never built, or — once — markup superseded by a runtime
replacement that dropped one of its actions on the way.

`B51` is that one. `#memory-session-option` ("Memory / Extract memories from
this session") lives in a `.dropdown.hidden` in `index.html` that nothing opens;
`sessions.js` builds the session menu at runtime now and carried Rename,
Archive, Delete and Favorite across. `memoryModule.extractMemory(sessionId)` is
complete, backed by a live route, exported on `window.memoryModule` — and called
by nothing. The action is back in the menu.

**Two blind spots this measurement had, both corrected here**, because an
orphan list is only worth what its "nothing reads this" claim is worth:

* ids reached through a **prefix** lookup — `getElementById('adv-' + key)`
  covers `adv-brandMixTo` and `adv-hamburgerColor`, which a literal scan calls
  orphans. This is the shape that hid the discovery audit's worst finding.
* ids reached through a **suffix** lookup — `getElementById(selectEl.id +
  '-logo')` covers all six `set-…Select-logo` spans. `B52`: the first version of
  this file checked prefixes only, called those six orphans, and a row was
  filed asking someone to build a feature that already works. A suffix only
  counts when the base it is appended to is itself an id the page has, or a
  generic `-btn` would silence every id ending in it.
* ids read by an **inline script in `index.html` itself** rather than a `.js`
  file — `loader-wave` is read eleven lines below where it is declared.
"""
import functools
import pathlib
import re

from tests.helpers.source_text import blank  # B290

ROOT = pathlib.Path(__file__).resolve().parent.parent
INDEX = (ROOT / "static" / "index.html").read_text(encoding="utf-8")
# Comments blanked (`B290`). A stylesheet that documents its own
# corrections in place mentions ids in prose — `P5-12`'s chip rule names
# `#pinned-tools-bar` to say which row will build it — and a raw `#id`
# scan counts that sentence as a selector. `Law 20`: a source file is code
# and prose about code interleaved, and a substring search can tell you
# neither which of the two it found nor what scope it landed in. That is
# the wrong direction for this check: an id "reached" only by a comment is
# an orphan this file would stop reporting.
CSS = blank(ROOT / "static" / "style.css")
SESSIONS = (ROOT / "static" / "js" / "sessions.js").read_text(encoding="utf-8")
MEMORY = (ROOT / "static" / "js" / "memory.js").read_text(encoding="utf-8")


def _scripts(html):
    return "\n".join(re.findall(r"<script\b[^>]*>(.*?)</script>", html, re.S | re.I))


def strip_js_comments(src):
    """Drop comments without touching strings.

    A character scanner rather than a regex, for the reason `check-wiring.py`
    learned the hard way: `re.sub(r"/\\*.*?\\*/", "", src)` treats a `/*` inside a
    string literal as the start of a comment and eats thousands of lines.

    It matters here for a smaller reason and the same law: the comment this
    test's own subject carries names `#memory-session-option` in backticks, and
    a scan that reads comments concluded the id was reached — by the note
    explaining that it is not (`Law 20`)."""
    out, i, n = [], 0, len(src)
    while i < n:
        c = src[i]
        if c in "'\"`":
            quote, j = c, i + 1
            while j < n:
                if src[j] == "\\":
                    j += 2
                    continue
                if src[j] == quote:
                    break
                j += 1
            out.append(src[i:j + 1])
            i = j + 1
            continue
        if c == "/" and i + 1 < n and src[i + 1] == "/":
            j = src.find("\n", i)
            i = n if j == -1 else j
            continue
        if c == "/" and i + 1 < n and src[i + 1] == "*":
            j = src.find("*/", i + 2)
            i = n if j == -1 else j + 2
            out.append(" ")
            continue
        out.append(c)
        i += 1
    return "".join(out)


def _js():
    parts = [strip_js_comments(p.read_text(encoding="utf-8", errors="replace"))
             for p in sorted((ROOT / "static").rglob("*.js")) if "lib/" not in str(p)]
    for name in ("index.html", "login.html"):
        parts.append(strip_js_comments(
            _scripts((ROOT / "static" / name).read_text(encoding="utf-8"))))
    return "\n".join(parts)


JS = _js()

_PREFIX_PATTERNS = (
    r"""getElementById\(\s*['"]([^'"]+)['"]\s*\+""",
    r"""querySelector(?:All)?\(\s*['"]#([^'"${]+)\$?\{""",
    r"""getElementById\(\s*`([^`$]+)\$\{""",
    r"""['"]#([A-Za-z][\w-]*)['"]\s*\+""",
)

# The other half, and the half I got wrong first. An id can be built by
# appending as easily as by prefixing — `document.getElementById(selectEl.id +
# '-logo')` reaches all six `set-…Select-logo` spans, and a prefix-only scan
# calls every one of them an orphan. It did, and `P3-25` was filed against a
# feature that works (`B52`).
_SUFFIX_PATTERNS = (
    r"""getElementById\(\s*[^)'"]*\+\s*['"]([-\w]+)['"]\s*\)""",
    r"""querySelector(?:All)?\(\s*['"]#[^'"]*['"]\s*\+\s*['"]([-\w]+)['"]""",
    r"""getElementById\(\s*`[^`]*\$\{[^}]*\}([-\w]+)`""",
)


def lookup_prefixes():
    out = set()
    for pat in _PREFIX_PATTERNS:
        out.update(m.group(1) for m in re.finditer(pat, JS))
    return out


def lookup_suffixes():
    out = set()
    for pat in _SUFFIX_PATTERNS:
        out.update(m.group(1) for m in re.finditer(pat, JS))
    return out


@functools.lru_cache(maxsize=1)
def _reference_sets():
    """Every name any of the four sources could be naming, gathered once.

    Per-id regex over half a megabyte of script, 559 times, took 43 seconds and
    made mutation testing impractical — which matters, because a check nobody
    can afford to run against a broken tree is a check nobody has verified."""
    quoted = set(re.findall(r"""['"`][#\[]?([A-Za-z][\w-]*)['"`\]]""", JS))
    css_ids = set(re.findall(r"#([A-Za-z][\w-]*)(?![\w-])", CSS))
    html = INDEX + (ROOT / "static" / "login.html").read_text(encoding="utf-8")
    markup = set()
    for pat in (r'for="([^"]+)"', r'href="#([^"]+)"', r'list="([^"]+)"',
                r'form="([^"]+)"'):
        markup.update(re.findall(pat, html))
    for pat in (r'aria-(?:labelledby|controls|describedby|owns)="([^"]+)"',):
        for value in re.findall(pat, html):
            markup.update(value.split())
    py = "\n".join(p.read_text(encoding="utf-8", errors="replace")
                    for p in list(ROOT.glob("routes/**/*.py"))
                    + list(ROOT.glob("src/**/*.py")))
    python = set(re.findall(r"""['"]([A-Za-z][\w-]*)['"]""", py))
    return quoted, css_ids, markup, python


def unreached_ids():
    prefixes, suffixes = lookup_prefixes(), lookup_suffixes()
    quoted, css_ids, markup, python = _reference_sets()
    all_ids = set(re.findall(r'\bid="([^"]+)"', INDEX))
    out = []
    for i in sorted(all_ids):
        if i in quoted or i in css_ids or i in markup or i in python:
            continue
        if any(i.startswith(p) and i != p for p in prefixes):
            continue
        # A suffix constructor only reaches `<base><suffix>` if `<base>` is
        # itself something the page has — `set-defaultEpSelect-logo` minus
        # `-logo` is `set-defaultEpSelect`, a real select. Without that check a
        # generic suffix like `-btn` would silence every id ending in it, which
        # is a blind spot traded for a blind spot.
        if any(i.endswith(x) and i != x and i[:-len(x)] in all_ids for x in suffixes):
            continue
        out.append(i)
    return out


# The itemisation, as of 2026-09-08. Grouped by what each one actually is,
# because "24 orphan ids" is a number and this is the finding.
SUPERSEDED_MARKUP = {          # a runtime menu replaced this block
    "session-actions-dropdown", "rename-session-option", "delete-session-option",
    "memory-session-option",
}
NEVER_BUILT = {                # empty anchors for features that never shipped
    "pinned-tools-bar", "welcome-setup", "set-reminder-llm-persona-msg",
}
DEAD_ATTRIBUTE = {             # live element, dead id
    "adm-epApiKey-row", "agent-drafts-chevron", "auto-sort-sessions-row",
    "chats-section-label", "chats-section-title", "export-dropdown-wrap",
    "settings-2fa-card", "settings-system-logs-card", "sidebar-user-bar",
    "theme-frosted-group", "theme-save-row",
}
ITEMISED = SUPERSEDED_MARKUP | NEVER_BUILT | DEAD_ATTRIBUTE


def test_the_scan_sees_the_markup():
    assert len(re.findall(r'\bid="', INDEX)) > 400
    assert len(JS) > 500_000
    assert lookup_prefixes() >= {"adv-", "ge-", "preset-"}


def test_a_constructed_lookup_is_not_an_orphan():
    """`getElementById('adv-' + key)` reaches every `adv-*` id in the theme
    editor. A literal scan calls two of them orphans, and deleting either
    breaks a colour control. This is the shape that hid the discovery audit's
    highest-harm finding."""
    orphans = unreached_ids()
    for live in ("adv-brandMixTo", "adv-hamburgerColor"):
        assert f'id="{live}"' in INDEX, live
        assert live not in orphans, f"{live} is reached by a constructed lookup"


def test_an_id_read_by_an_inline_script_is_not_an_orphan():
    """`loader-wave` is read eleven lines below where it is declared, by a
    `<script>` in `index.html`. A scan over `static/**/*.js` cannot see it."""
    assert "getElementById('loader-wave')" in _scripts(INDEX)
    assert "loader-wave" not in unreached_ids()


def test_the_itemisation_is_complete_and_current():
    """The row's `Law 9` requirement. If the list moves, this says which way —
    a new orphan is markup someone added and nothing reads, and a departure
    means someone wired one up and the entry should go."""
    found = set(unreached_ids())
    assert found == ITEMISED, {
        "newly unreached": sorted(found - ITEMISED),
        "now reached (remove from the itemisation)": sorted(ITEMISED - found),
    }


def test_nothing_in_the_itemisation_was_deleted():
    """Law 1, and the row's own history: `P3-10` would have deleted the RAG
    module four days after another row brought it to life. Every one of these is
    a live element, an anchor for something unbuilt, or superseded markup whose
    replacement lost an action — none is a dead element to remove."""
    for i in sorted(ITEMISED):
        assert f'id="{i}"' in INDEX, f"{i} was deleted rather than recorded"


# --- B51 -------------------------------------------------------------------


def test_extract_memory_has_a_door_again():
    """The implementation, the route and the export all existed; the only markup
    that pointed at them sits in a dropdown nothing opens."""
    assert "export async function extractMemory(sessionId)" in MEMORY
    assert "/api/memory/extract" in MEMORY
    assert "extractMemory," in MEMORY, "it left the module's export surface"
    handler = SESSIONS.split("memoryItem.addEventListener", 1)[1][:600]
    assert "window.memoryModule.extractMemory(s.id)" in handler, (
        "the Memory item does not call extractMemory — a mutation that pointed "
        "it at `loadMemories()` passed a check for the name appearing in the "
        "guard beside it"
    )
    menu = SESSIONS.split("const dropdown = document.createElement('div');", 1)[1]
    menu = menu.split("\nfunction ", 1)[0]
    assert "dropdown.appendChild(memoryItem)" in menu, "built but never appended"
    assert "<span>Memory</span>" in menu


def test_the_menu_item_survives_memory_js_not_being_ready():
    """`memory.js` imports `sessions.js`, so this goes through
    `window.memoryModule` like the call at `:2147` — and a guard that silently
    does nothing is worse than one that says so."""
    block = SESSIONS.split("memoryItem.addEventListener", 1)[1][:600]
    assert "window.memoryModule && window.memoryModule.extractMemory" in block
    assert "showError" in block, "a missing module fails silently"
    assert "import" not in block.split("});", 1)[0]


def test_the_runtime_menu_still_offers_what_it_carried_across():
    """Adding one item must not have displaced the four the static markup's
    replacement already had."""
    for label in ("<span>Rename</span>", "<span>Archive</span>",
                  "<span>Delete</span>", "<span>Copy Chat</span>"):
        assert label in SESSIONS, label


def test_a_suffix_lookup_is_not_an_orphan():
    """B52. `_syncModelLogo` / `_syncEndpointLogo` in `settings.js` reach
    `<selectId>-logo` by appending, and both are called from the two functions
    that fill every one of those selects. The logos work. A prefix-only scan
    said otherwise and a row was filed against it."""
    settings = (ROOT / "static" / "js" / "settings.js").read_text(encoding="utf-8")
    # Each helper's own body. Checking the file as a whole passed with one of
    # the two broken, because the other still carried the string — the same
    # "appears somewhere" weakness `B51`'s guard had.
    for fn in ("_syncModelLogo", "_syncEndpointLogo"):
        body = settings.split(f"function {fn}(selectEl) {{", 1)[1].split("\n}\n", 1)[0]
        assert "selectEl.id + '-logo'" in body, f"{fn} no longer finds its span"
        assert "logoEl.innerHTML" in body, f"{fn} no longer writes one"
    assert "_syncModelLogo(selectEl);" in settings and "_syncEndpointLogo(selectEl);" in settings
    orphans = set(unreached_ids())
    for live in ("set-defaultEpSelect-logo", "set-defaultModelSelect-logo",
                 "set-researchModel-logo", "set-utilityEpSelect-logo",
                 "set-utilityModelSelect-logo", "set-vlModelSelect-logo"):
        assert f'id="{live}"' in INDEX, live
        assert live not in orphans, f"{live} is filled by a suffix lookup"
        assert live[: -len("-logo")] in INDEX, "its base select is gone"


def test_a_generic_suffix_does_not_silence_everything_that_ends_with_it():
    """`-btn` and `-toggle` are among the suffixes appended somewhere in this
    codebase. Excluding every id that merely ends in one would trade a blind
    spot for a bigger blind spot, so the base has to exist too."""
    suffixes = lookup_suffixes()
    assert "-btn" in suffixes, "the suffix scan stopped finding the generic ones"
    ids = set(re.findall(r'\bid="([^"]+)"', INDEX))
    ends_in_btn = {i for i in ids if i.endswith("-btn")}
    assert len(ends_in_btn) > 20, len(ends_in_btn)
    without_base = {i for i in ends_in_btn if i[: -len("-btn")] not in ids}
    assert without_base, (
        "no id ends in `-btn` without a matching base, so this test proves "
        "nothing about the rule it is checking"
    )
