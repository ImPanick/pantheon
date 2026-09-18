# SPDX-License-Identifier: AGPL-3.0-or-later
"""`P3-20` — the 120 unresolved ids were three different things counted as one.

The 2026-09-07 triage found that most of the inventory is guarded by
construction and concluded the number should therefore never move. The
conclusion that actually follows is that a guarded absence should be *said out
loud* rather than counted silently, because guardedness proves only that the
code will not throw. It proves nothing about whether the behaviour still
happens, and two of the 120 proved it:

  * `set-researchSearchMsg` was the one UNGUARDED lookup in the inventory and
    sat on a control a user touches. Changing the Deep Research search provider
    saved, then threw a TypeError writing "Saved" into an element that did not
    exist — and the `catch` assigned to the same null and threw again, uncaught.
  * `notes-panel` was dismissed by the triage as "a modal-registry key, not an
    element id". `_windowVisible` does `getElementById` on that key. The pane's
    id is `notes-pane`, so the Toggle Window shortcut has never been able to see
    Notes open.

So these tests come in two halves. The mechanism half drives
`check-wiring.py`'s new functions on synthetic input, because a declaration
that has stopped being true is worse than no declaration. The product half
drives the three defects, and every one of them fails on the tree as it stood
before this row.
"""
import importlib.util
import pathlib
import re

import pytest

ROOT = pathlib.Path(__file__).resolve().parent.parent


def _checker():
    spec = importlib.util.spec_from_file_location(
        "check_wiring", ROOT / ".pantheon" / "check-wiring.py")
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


CW = _checker()


# ── the mechanism: a concatenated lookup is a prefix, not an id ──

def test_a_lookup_ending_in_a_separator_is_not_an_id():
    where = {"adv-": {"static/js/theme.js"}, "cmp-history-": {"a.js"},
             "rail-research": {"b.js"}}
    assert CW.drop_lookup_prefixes(where) == ["adv-", "cmp-history-"]
    assert set(where) == {"rail-research"}


def test_a_short_stub_is_left_alone():
    """Same four-character gate `made_prefixes` uses. `a-` is not a prefix
    anyone writes, and treating it as one would silently resolve every id in
    the product — a ratchet that stops measuring without anyone editing it."""
    where = {"a-": {"x.js"}, "ab_": {"x.js"}}
    CW.drop_lookup_prefixes(where)
    assert set(where) == {"a-", "ab_"}


def test_the_theme_editor_colour_pickers_are_real_markup():
    """The product side of the same finding. `theme.js` reaches its fourteen
    advanced colour inputs as `getElementById('adv-' + key)`, and index.html
    provides every one of them — the checker was wrong, not the page."""
    theme = (ROOT / "static" / "js" / "theme.js").read_text(errors="replace")
    html = (ROOT / "static" / "index.html").read_text(errors="replace")
    keys = set(re.findall(r"'adv-([A-Za-z0-9]+)':", theme))
    assert len(keys) >= 10, "the ADV_KEYS table moved; this test no longer reads it"
    missing = sorted(k for k in keys if f'id="adv-{k}"' not in html)
    assert not missing, f"theme colour inputs with no markup: {missing}"


# ── the mechanism: declaring is not free ──

def _faults(entry, *, sources, html_ids, where):
    original = CW.ABSENT_BY_DESIGN
    CW.ABSENT_BY_DESIGN = [entry]
    try:
        return CW.declaration_faults(sources, html_ids, where)
    finally:
        CW.ABSENT_BY_DESIGN = original


ENTRY = {"where": "a.js", "guard": "if (!x) return;", "why": "gone",
         "ids": ("thing-one",)}


def test_a_healthy_declaration_reports_nothing():
    assert _faults(ENTRY, sources={"a.js": "if (!x) return;"}, html_ids=set(),
                   where={"thing-one": {"a.js"}}) == []


def test_a_guard_that_was_removed_fails():
    """The one that makes this more than an allowlist: without the early
    return the lookups underneath it are unguarded again, and an entry that
    still subtracts them from the count is hiding a live defect."""
    out = _faults(ENTRY, sources={"a.js": "x.value = 1;"}, html_ids=set(),
                  where={"thing-one": {"a.js"}})
    assert out and "guard" in out[0]


def test_a_guard_written_only_in_a_comment_does_not_count():
    """`Law 20`, and this file's own blind spot 2: documenting a guard is not
    having one. `sources` is comment-stripped before it gets here, so a
    sentence describing the early return cannot satisfy it."""
    commented = CW.code_only("// if (!x) return;  <- we used to do this\\nx.value = 1;")
    out = _faults(ENTRY, sources={"a.js": commented}, html_ids=set(),
                  where={"thing-one": {"a.js"}})
    assert out and "guard" in out[0]


def test_markup_that_came_back_fails():
    out = _faults(ENTRY, sources={"a.js": "if (!x) return;"},
                  html_ids={"thing-one"}, where={"thing-one": {"a.js"}})
    assert out and "markup provides it" in out[0]


def test_a_declaration_nothing_looks_up_any_more_fails():
    out = _faults(ENTRY, sources={"a.js": "if (!x) return;"}, html_ids=set(),
                  where={})
    assert out and "nothing looks it up" in out[0]


def test_a_lookup_that_moved_to_another_file_fails():
    """The declaration names one guard in one file. A second file reaching for
    the same id is not covered by it and must not ride along."""
    out = _faults(ENTRY, sources={"a.js": "if (!x) return;"}, html_ids=set(),
                  where={"thing-one": {"a.js", "b.js"}})
    assert out and "does not cover" in out[0]


def test_a_tree_that_holds_none_of_the_declared_files_is_not_stale():
    """The declarations are data about THIS repository. Pointed at a fixture
    that holds none of the files they name, they are not stale — they are not
    about it, and twenty faults would read as the algorithm being broken when
    only the subject changed. Some of the files present is a different story
    and stays a fault."""
    assert CW.declaration_faults({"nothing/at/all.js": ""}, set(), {}) == []
    partial = CW.declaration_faults(
        {CW.ABSENT_BY_DESIGN[0]["where"]: CW.ABSENT_BY_DESIGN[0]["guard"]},
        set(), {i: {CW.ABSENT_BY_DESIGN[0]["where"]}
                for i in CW.ABSENT_BY_DESIGN[0]["ids"]})
    assert any("is not scanned" in f for f in partial)


def test_every_shipped_declaration_says_why():
    for entry in CW.ABSENT_BY_DESIGN:
        assert entry["ids"], entry
        assert len(entry["why"].split()) >= 8, entry["guard"]


def test_the_shipped_declarations_are_true_of_this_tree():
    """`declaration_faults` on the real repository. This is the claim CI
    holds: every id subtracted from the count is still looked up, still
    guarded, still absent from markup and still where the entry says it is."""
    import subprocess
    out = subprocess.run(["python3", str(ROOT / ".pantheon" / "check-wiring.py")],
                         capture_output=True, text=True, cwd=ROOT)
    assert "STALE DECLARATIONS" not in out.stdout, out.stdout


# ── the product: three defects the count was carrying ──

def test_toggle_window_looks_up_the_notes_pane_by_its_real_id():
    """`_WINDOW_TRIGGERS`'s KEY is an element id — `_windowVisible` and the
    close branch both `getElementById` it. It said `notes-panel`, which is the
    modal-registry key `notes.js` registers under; the element is `notes-pane`.
    Toggle Window therefore never saw Notes open and fell through to "reopen
    the last window" with Notes filling the screen."""
    ks = (ROOT / "static" / "js" / "keyboard-shortcuts.js").read_text(errors="replace")
    notes = (ROOT / "static" / "js" / "notes.js").read_text(errors="replace")
    body = re.search(r"_WINDOW_TRIGGERS\s*=\s*\{(.*?)\}", ks, re.S)
    assert body, "the trigger table moved"
    keys = set(re.findall(r"'([a-z0-9-]+)':", body.group(1)))
    assert "notes-pane" in keys
    assert "notes-panel" not in keys
    assert "pane.id = 'notes-pane'" in notes, "the pane's own id moved"


def test_the_research_search_confirmation_has_somewhere_to_land():
    """`saveResearchSearch` assigns to this on every change of a live select,
    with no null check, and the catch clause assigns to the same null."""
    html = (ROOT / "static" / "index.html").read_text(errors="replace")
    settings = (ROOT / "static" / "js" / "settings.js").read_text(errors="replace")
    assert "el('set-researchSearchMsg')" in settings
    assert 'id="set-researchSearch"' in html
    assert 'id="set-researchSearchMsg"' in html


def test_losing_the_agent_privilege_hides_a_control_that_exists():
    """`can_use_agent: false` is enforced at `routes/chat_routes.py`, so this
    was never a hole — it was a button the user could press and be refused,
    which is `Law 15`. The branch reached for `#mode-toggle` and
    `.chat-input-toggle`; the control is `#mode-agent-btn` inside a `.mode-toggle`
    CLASS, and had been for long enough that nobody noticed."""
    app = (ROOT / "static" / "app.js").read_text(errors="replace")
    html = (ROOT / "static" / "index.html").read_text(errors="replace")
    branch = re.search(r"if \(!p\.can_use_agent\) \{(.*?)\n        \}", app, re.S)
    assert branch, "the privilege branch moved"
    targets = set(re.findall(r"getElementById\('([A-Za-z0-9_-]+)'\)", branch.group(1)))
    assert targets, "the branch stopped looking anything up"
    for t in targets:
        assert f'id="{t}"' in html, f"privilege branch targets absent markup: {t}"


def test_the_ratchet_matches_what_ci_asks_for():
    """One number, two files. They have disagreed before."""
    ci = (ROOT / ".github" / "workflows" / "ci.yml").read_text()
    maxes = set(re.findall(r"check-wiring\.py --max (\d+)", ci))
    assert len(maxes) == 1, f"ci.yml states more than one wiring ceiling: {maxes}"
    import subprocess
    run = subprocess.run(
        ["python3", str(ROOT / ".pantheon" / "check-wiring.py"),
         "--max", maxes.pop()], capture_output=True, text=True, cwd=ROOT)
    assert run.returncode == 0, run.stdout
    assert "Lower the ceiling" not in run.stdout, run.stdout
