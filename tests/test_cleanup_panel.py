"""H10 — session cleanup, with a dry run, had no door.

`GET /api/cleanup/preview` and `POST /api/cleanup` are live, owner-scoped, and
`grep "api/cleanup" static/` returned nothing. The dry run is why this belongs in
the product rather than in the Danger Zone: it returns the sessions it would
archive, the ones it would delete, **and the ones it is sparing with the
reason** — "part of last 10 sessions", "has 20+ messages", "contains keyword:
important". Someone deciding whether to free 340 MB wants to see what survives.

These tests cover the two things a frontend row can actually be wrong about: the
contract it reads (asserted against the real service, so a change to either side
shows up here) and the wiring (asserted against the markup and the init list, so
the panel cannot go the way `initRag` and `initWebhookForm` did — both defined in
`admin.js`, both dropped from the init list, both still there).
"""
import pathlib
import re

import pytest

ROOT = pathlib.Path(__file__).resolve().parent.parent
INDEX = (ROOT / "static" / "index.html").read_text(encoding="utf-8")
ADMIN = (ROOT / "static" / "js" / "admin.js").read_text(encoding="utf-8")


# ── the contract the panel reads ──

def test_the_preview_payload_still_has_the_four_keys_the_panel_renders():
    """Read from the service rather than trusted from the row. If a key is
    renamed, the panel renders an empty group and says nothing is wrong."""
    import inspect
    from src.cleanup_service import get_cleanup_preview
    src = inspect.getsource(get_cleanup_preview)
    for key in ("sessions_to_archive", "sessions_to_delete",
                "preserved_sessions", "estimated_space_freed_mb"):
        assert f'"{key}"' in src, f"preview no longer returns {key}"


def test_preserved_sessions_still_carry_a_reason():
    """The reason is the whole argument for showing the 'Kept' group. Without
    it that group is a list of names with no information in it."""
    import inspect
    from src.cleanup_service import get_cleanup_preview
    assert '"reason":' in inspect.getsource(get_cleanup_preview)


def test_the_documented_thresholds_match_the_code():
    """The panel tells the operator the rules in prose. Prose drifts from
    constants silently, and a wrong number here is worse than none — it is a
    promise about what will not be deleted."""
    from src.cleanup_service import CleanupConfig
    assert CleanupConfig.ARCHIVE_AFTER_DAYS == 7
    assert CleanupConfig.DELETE_AFTER_DAYS == 14
    assert CleanupConfig.MIN_MESSAGES_TO_KEEP == 20
    assert CleanupConfig.PRESERVE_RECENT_COUNT == 10
    for word in ("important", "remember", "save this", "keep", "bookmark"):
        assert word in CleanupConfig.PROTECTED_KEYWORDS

    for phrase in ("untouched for 7 days", "after 14 more",
                   "fewer than 20", "10 most recent"):
        assert phrase in INDEX, f"the panel's prose no longer says: {phrase}"


def test_both_routes_are_actually_mounted():
    """Checked because a flat `app.routes` walk says they are not — this
    FastAPI wraps included routers, so the flat view misses them, and that
    false alarm has now cost two people time. The checker's own traversal is
    the one that tells the truth."""
    import importlib.util
    spec = importlib.util.spec_from_file_location(
        "cu", str(ROOT / ".pantheon" / "check-unreachable.py"))
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    paths = {(p, tuple(sorted(m))) for p, m in mod.app_routes()}
    assert ("/api/cleanup/preview", ("GET",)) in paths
    assert ("/api/cleanup", ("POST",)) in paths


# ── the wiring ──

def test_the_panel_exists_in_markup():
    for element_id in ("adm-cleanupPreviewBtn", "adm-cleanupRunBtn",
                       "adm-cleanupMsg", "adm-cleanupPreview"):
        assert f'id="{element_id}"' in INDEX, f"no markup for {element_id}"


def test_the_panel_is_in_the_admin_init_list():
    """`initRag` and `initWebhookForm` are both defined in this file, both
    reference markup that no longer exists, and both were dropped from `inits`
    rather than removed — so the code is still there and has not run in a long
    time. A new panel is one edit away from the same fate."""
    inits = re.search(r"const inits = \[(.*?)\];", ADMIN, re.S)
    assert inits, "the init list has moved"
    assert "initCleanup" in inits.group(1)
    assert re.search(r"function initCleanup\(", ADMIN)


def test_the_panel_calls_both_halves_of_the_backend():
    assert "'/api/cleanup/preview'" in ADMIN
    assert "'/api/cleanup'" in ADMIN


def test_nothing_is_deleted_without_a_confirm():
    """The POST is irreversible for the delete half. It must sit behind the
    styled confirm, and the confirm must be `danger` when something will
    actually be deleted."""
    run = ADMIN.split("runBtn.addEventListener", 1)[1].split("function ", 1)[0]
    assert "styledConfirm" in run
    assert "danger: Boolean(remove)" in run
    confirm_at = run.index("styledConfirm")
    post_at = run.index("method: 'POST'")
    assert confirm_at < post_at, "the confirm must precede the POST"


def test_the_preview_is_rendered_without_innerhtml():
    """Session names are user-supplied and go straight into this list. This is
    the same discipline `H01` applied to the drafts panel; a chat title is a
    perfectly good XSS payload."""
    panel = ADMIN.split("/* ── Storage cleanup (H10) ──", 1)[1].split(
        "/* ── Data Backup", 1)[0]
    # A PROPERTY ACCESS, not the word. The first version of this test asserted
    # `"innerHTML" not in panel` and failed on the comment above the panel
    # explaining why it does not use innerHTML — the same shape as the `H02`
    # test that fired on its own quoted correction, which is twice now that a
    # substring check has mistaken an explanation for the thing explained.
    assert not re.search(r"\.innerHTML\b", panel), "innerHTML used in the panel"
    assert "textContent" in panel


def test_the_kept_group_renders_the_reason_and_not_just_the_name():
    """A mutation replacing the reason with an empty string survived every
    other test here, which is the ingredient-not-the-recipe family again: the
    service was asserted to *return* a reason and nothing asserted the panel
    *shows* it. Without it the group is a list of names carrying no
    information, and the argument for having a 'Kept' group at all is that it
    answers "why is this one safe"."""
    panel = ADMIN.split("/* ── Storage cleanup (H10) ──", 1)[1].split(
        "/* ── Data Backup", 1)[0]
    kept = re.search(r"_cleanupGroup\('Kept',[^\n]*", panel)
    assert kept, "the Kept group has moved"
    assert "reason" in kept.group(0), (
        f"the Kept group no longer renders the reason: {kept.group(0)}"
    )


def test_run_is_not_offered_before_a_preview():
    """The button starts hidden in markup and is only revealed by a preview
    that found something — the row's Verify is that the list comes first."""
    card = INDEX.split('id="adm-cleanupPreviewBtn"', 1)[1].split("</div>", 3)[0]
    assert 'id="adm-cleanupRunBtn"' in card
    assert "hidden" in card.split('id="adm-cleanupRunBtn"', 1)[1][:80]
    assert "runBtn.hidden = total === 0;" in ADMIN
