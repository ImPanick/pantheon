# SPDX-License-Identifier: AGPL-3.0-or-later
"""`P0-29` — the product noun is Forge, and nothing a user reads still says Cookbook.

`D-2026-08-26-05`: *"It reads as a recipe box; it is a model-serving control
plane."* The decision renames the **name**, not the codebase. Those are
different things with different blast radii, and this file is where the line
between them is machine-checked.

**What moved: the word a person reads.** Labels, toasts, error bodies, tool
descriptions, help text, docs.

**What did not, and why each one is a decision rather than an omission:**

* **Route paths** — `/cookbook`, the seventeen `/api/cookbook/*`, and the codex
  and Claude agent surfaces. A path is a contract with an existing install, a
  saved `api_call`, and two shipped integration skills. `Law 1` says the old
  path has to keep answering, so a rename is *two* routes per endpoint, not
  one; it is its own row, not a side effect of a label change.
* **Persisted keys** — `data/cookbook_state.json`, the `cookbook-last-state` /
  `cookbook-tasks` / `cookbook_dl_tab_folded_v1` browser keys, the
  `cookbook:read` and `cookbook:launch` API-token scopes, the `open_cookbook`
  keybinding id. Every one of them is something a user's install already holds.
  Renaming without a read-old path resets data; with one, it is a migration
  that needs its own evidence.
* **`cookbook_serve`** — a built-in action key, stored in task rows.
  `FORBIDDEN` Part 1 forbids it outright.
* **Element ids, CSS classes and module filenames** — `cookbook-modal`,
  `.cookbook-tab`, `rail-cookbook`, `tool-cookbook-btn`,
  `static/js/cookbook*.js`. These are styling and wiring, they live in
  `static/index.html` and `static/style.css`, and `data-modal-id` is in
  `FORBIDDEN` Part 1.

**Two things were kept answerable rather than replaced** (`Law 1`): `/cookbook`
and `/cook` still open the panel beside the new `/forge`, and `open_panel
cookbook` still reaches the same switch as `open_panel forge` — a model quoting
an older conversation must not hit a dead branch.

**The rule is derived, not transcribed** (`Law 13`). One predicate — the
standalone capitalised word, which in this tree is the product noun and never an
identifier (`openCookbookDependencies`, `tool-cookbook-btn` and
`COOKBOOK_STATE_FILE` all fail the word boundary) — applied to every shipped
source file. A list of surfaces would be wrong by exactly one the day somebody
adds a panel.
"""

import ast
import json
import pathlib
import re
import shutil
import subprocess

import pytest

from tests.helpers.source_text import blank

_REPO = pathlib.Path(__file__).resolve().parents[1]
_HAS_NODE = shutil.which("node") is not None

# The product noun as a word. `Cookbook` preceded or followed by a word
# character is an identifier — camelCase (`openCookbookDependencies`), a hyphen
# or underscore spelling (`cookbook-modal`, `COOKBOOK_STATE_FILE`) — and those
# are deliberately not this row's business.
NOUN = re.compile(r"(?<![A-Za-z0-9_])Cookbook(?![A-Za-z0-9_])")

# What the app ships and serves. Not `tests/` (a test naming the old word is
# usually about it), not `.pantheon/` (the tracker records what was true when it
# was written and rewriting that is rewriting history), not `static/lib/` or
# `library/` (other people's bytes and words).
SOURCE_ROOTS = ("static", "src", "routes", "core", "services", "docs")
SOURCE_FILES = ("app.py", "launcher.py")
EXCLUDE_PREFIXES = ("static/lib/",)
READABLE = {".py", ".js", ".mjs", ".css", ".html", ".md"}

# Where the word survives inside those roots, and why. Each entry is a promise
# that something is coming, not permission for it to stay — see
# `test_the_register_holds_nothing_that_is_already_done`, which fails when one
# of these is finally clean so the entry comes out with the work.
RESIDUE = {
    "static/index.html":
        "Six user-visible strings — the route title map, the rail button "
        "`title`, the sidebar label, the modal `aria-label` and `<h4>`, and the "
        "visibility-toggle label. Another agent holds this file this wave "
        "(`P3-20`), and its element ids are in `FORBIDDEN` Part 1, so the "
        "labels and the ids have to move in one edit or not at all. Handed to "
        "the integrator with the exact lines. "
        "`tests/test_dialog_aria.py` asserts `aria-label=\"Cookbook\"` and has "
        "to change in the same commit.",
    "services/hwfit/image_models.py":
        "`Pantheon-Cookbook/1.0` is an outbound User-Agent, not a label. "
        "Nothing renders it and `FORBIDDEN` Part 1 treats the user-agents as "
        "already swept; changing a wire header to tidy a word is the wrong "
        "trade.",
}


def _shipped_files():
    tracked = subprocess.run(["git", "ls-files"], cwd=_REPO,
                             capture_output=True, text=True, check=True).stdout.split()
    for rel in tracked:
        if rel.startswith(EXCLUDE_PREFIXES):
            continue
        if not (rel.startswith(tuple(r + "/" for r in SOURCE_ROOTS)) or rel in SOURCE_FILES):
            continue
        if pathlib.Path(rel).suffix in READABLE:
            yield rel


def _readable_text(rel: str) -> str:
    """The part of a file a user could end up reading.

    Python is walked with `ast` so a docstring or a `#` comment explaining what
    the old name was never counts — deleting that history is how the next
    person rediscovers the question from scratch (`Law 1`). Everything else goes
    through the repository's one comment blanker (`tests/helpers/source_text`,
    `B290`), never a hand-rolled `/\\*.*?\\*/` (`Law 14`, `Law 20`).
    """
    path = _REPO / rel
    text = path.read_text(encoding="utf-8", errors="replace")
    if path.suffix == ".py":
        try:
            tree = ast.parse(text)
        except SyntaxError:
            return text
        docstrings = set()
        for node in ast.walk(tree):
            body = getattr(node, "body", None)
            if isinstance(node, (ast.Module, ast.ClassDef, ast.FunctionDef,
                                 ast.AsyncFunctionDef)) and body:
                first = body[0]
                if isinstance(first, ast.Expr) and isinstance(first.value, ast.Constant):
                    docstrings.add(id(first.value))
        return "\n".join(
            n.value for n in ast.walk(tree)
            if isinstance(n, ast.Constant) and isinstance(n.value, str)
            and id(n) not in docstrings
        )
    if path.suffix == ".md":
        # Prose in `docs/` is the thing a reader reads. There is nothing to
        # strip.
        return text
    return blank(path, text)


def _offenders():
    out = {}
    for rel in _shipped_files():
        hits = NOUN.findall(_readable_text(rel))
        if hits:
            out[rel] = len(hits)
    return out


# ── the derivation, checked before anything is concluded from it ──────────────


def test_the_scan_reads_the_files_it_claims_to_read():
    # A scan that quietly matched nothing would make the row's `Verify` line
    # vacuous — the way a rename passes without happening.
    files = set(_shipped_files())
    for expected in ("static/js/slashCommands.js", "src/tool_index.py",
                     "routes/cookbook_routes.py", "docs/setup.md",
                     "static/index.html"):
        assert expected in files, f"{expected} is not being scanned"


def test_the_rule_separates_the_noun_from_the_identifier():
    assert NOUN.search("Open Cookbook")
    assert NOUN.search("the Cookbook.")
    assert not NOUN.search("openCookbookDependencies")
    assert not NOUN.search("_normalizeCookbookModelDir")
    assert not NOUN.search("CookbookServe")
    assert not NOUN.search("cookbook-modal")
    assert not NOUN.search("COOKBOOK_STATE_FILE")


# ── the row's Verify line ─────────────────────────────────────────────────────


def test_no_user_visible_string_says_cookbook():
    unexpected = {rel: n for rel, n in _offenders().items() if rel not in RESIDUE}
    assert not unexpected, (
        "The old product noun is in a shipped surface (`P0-29`, "
        "`D-2026-08-26-05`):\n  "
        + "\n  ".join(f"{n:>3}  {rel}" for rel, n in sorted(unexpected.items()))
        + "\n\nRename it, or — if it is a persisted key, a route path, an "
          "element id or a wire header — add it to RESIDUE here with the "
          "reason, because that is a different row."
    )


def test_the_register_holds_nothing_that_is_already_done():
    """A hand-off that outlives its hand-off is an excuse.

    When `static/index.html` is renamed by whoever holds it, this fails and the
    entry comes out in the same commit — which is also the moment `P0-29` can
    be ticked.
    """
    live = _offenders()
    settled = sorted(set(RESIDUE) - set(live))
    assert not settled, (
        "These no longer carry the old noun, so their RESIDUE entry is now an "
        "excuse for nothing: " + ", ".join(settled)
        + ". Remove the entry (and re-read `P0-29`'s `Verify:` line — this may "
          "be the last thing it was waiting on)."
    )


def test_the_hand_off_is_exact_about_what_is_left():
    # The integrator is being asked to apply six lines in a file this wave does
    # not own. A number that has drifted is a hand-off nobody can act on.
    assert _offenders() == {"static/index.html": 6, "services/hwfit/image_models.py": 1}


# ── what the rename must NOT have done ────────────────────────────────────────


def test_the_persisted_surfaces_kept_their_names():
    """`Law 1`. Each of these is something an existing install already holds;
    a rename here resets a user's data or breaks their saved call."""
    kept = {
        "src/constants.py": "cookbook_state.json",
        "src/builtin_actions.py": '"cookbook_serve"',
        "static/js/cookbook.js": "'cookbook-last-state'",
        "static/js/cookbookServe.js": "'cookbook-tasks'",
        "static/js/keyboard-shortcuts.js": "open_cookbook:",
        "static/js/settings.js": "'cookbook:read'",
        "routes/cookbook_routes.py": '"/api/cookbook/state"',
        "app.py": '"/cookbook"',
    }
    for rel, needle in kept.items():
        assert needle in (_REPO / rel).read_text(encoding="utf-8"), (
            f"{needle} vanished from {rel} — that is a stored key, a route or a "
            f"scope, and renaming it without a migration breaks an install")


def test_the_old_words_still_open_the_panel():
    """A user with `/cookbook` in their fingers, and a model quoting an older
    conversation, both still land somewhere."""
    slash = blank(_REPO / "static" / "js" / "slashCommands.js")
    assert "target === 'forge' || target === 'cookbook' || target === 'cook'" in slash
    assert "alias: ['cookbook', 'cook']" in slash
    stream = blank(_REPO / "static" / "js" / "chatStream.js")
    assert "panel === 'forge' || panel === 'cookbook'" in stream


def test_the_calendar_a_user_already_has_is_still_theirs():
    # The schedule mirror creates a calendar by NAME. Writing `Forge` while
    # looking only for `cookbook` gives an existing install two calendars with
    # half its serves in each.
    js = blank(_REPO / "static" / "js" / "cookbookSchedule.js")
    assert '"forge", "cookbook"' in js
    assert "name=Forge&color" in js


# ── the new noun actually arrived, in the three places that must agree ────────


@pytest.mark.skipif(not _HAS_NODE, reason="node binary not on PATH")
def test_the_task_category_agrees_with_itself():
    """`Law 13`. The category name joins a map, an order and an icon table, and
    a rename that reaches two of the three loses the section's icon or its
    place at the top with nothing to see.

    **Rewritten 2026-09-18 (`P8-22`), and the check got longer rather than
    weaker.** Two of the three — the action→category map and the group order —
    were client-side copies of what `src/builtin_actions.py` already held, and
    they are on the wire now (`/meta/actions`'s `category` and `categories`).
    So the join this asserts on now **spans the wire**: the map and the order
    come out of the Python registry and the glyph table out of the shipped
    `static/js/tasks.js`, and a rename has to reach both sides or this fails.
    """
    from src.builtin_actions import ACTION_CATEGORY_ORDER, build_action_palette

    out = json.loads(subprocess.run(
        ["node", str(_REPO / "tests" / "harness" / "forge_labels.js")],
        capture_output=True, text=True, check=True, timeout=30).stdout)
    palette = {n["name"]: n for n in build_action_palette(include_admin_only=True)}

    assert palette["cookbook_serve"]["category"] == "Forge", (
        "the action key is stored in task rows and does not move; its label does")
    assert ACTION_CATEGORY_ORDER[0] == "Forge", "Forge serves are listed first on purpose"
    assert "Forge" in out["icons"]
    assert "Cookbook" not in ACTION_CATEGORY_ORDER and "Cookbook" not in out["icons"]

    # Every category the registry names has a glyph, and every icon a node
    # names has a path — the two joins the browser makes on this data. Neither
    # could be checked at all while the client kept its own table, because the
    # client's table WAS the answer it was being checked against.
    missing_cat = sorted(set(ACTION_CATEGORY_ORDER) - set(out["icons"]))
    assert not missing_cat, f"categories with no glyph: {missing_cat}"
    missing_icon = sorted({n["icon"] for n in palette.values()} - set(out["actionIcons"]))
    assert not missing_icon, f"action icons with no path: {missing_icon}"


def test_the_panel_the_user_clicks_is_called_forge():
    modal = blank(_REPO / "static" / "js" / "modalManager.js")
    assert "'cookbook-modal':" in modal, "the element id does not move"
    assert re.search(r"'cookbook-modal':\s*\{\s*label:\s*'Forge'", modal)
    app = blank(_REPO / "static" / "app.js")
    assert "'rail-cookbook': 'Forge'" in app
