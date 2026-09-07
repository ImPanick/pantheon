# SPDX-License-Identifier: AGPL-3.0-or-later
"""H13 — the gallery could move images into albums and nothing offered it.

`POST /api/gallery/albums/{id}/add` and `/remove` take a bulk `image_ids` list,
ownership-scoped, and had no caller in `static/`. Creating albums, listing them,
uploading *into* them and filtering by them were all already here — the one
missing verb was the one a person reaches for first.

The row's own correction is what made it cheap: the handle is the **image** bulk
bar, `_selectMode` / `_selectedIds()`, which already returns exactly the array
the endpoint wants and already drives a live action list. (The album multi-select
next to it holds *album* ids and exists to bulk-delete albums; the endpoint could
never have taken it.) So the work is one more entry in that array, plus somewhere
to choose which album.

Per `Law 20`, the assertions here resolve a scope before matching: the bulk menu
block, or one function's body. The first draft of the `H11` tests greped a whole
file and passed against the wrong function.
"""
import pathlib
import re

import pytest

ROOT = pathlib.Path(__file__).resolve().parent.parent
GALLERY = (ROOT / "static" / "js" / "gallery.js").read_text(encoding="utf-8")


def _fn(name):
    """One function's body from gallery.js, brace-matched. `Law 20`: a
    file-wide substring cannot say which function it landed in."""
    start = GALLERY.index(f"function {name}(")
    i = GALLERY.index("{", start)
    depth, j = 0, i
    while j < len(GALLERY):
        if GALLERY[j] == "{":
            depth += 1
        elif GALLERY[j] == "}":
            depth -= 1
            if depth == 0:
                return GALLERY[start:j + 1]
        j += 1
    raise AssertionError(f"unbalanced braces reading {name}")


def _bulk_menu():
    return _fn("_showGalleryBulkMenu")


# ── the door ──

def test_the_bulk_menu_offers_albums():
    menu = _bulk_menu()
    assert "'Album…'" in menu
    assert "_selectedIds()" in menu


def test_it_calls_the_two_routes_that_had_no_caller():
    body = _fn("_postAlbumMembership")
    assert "/api/gallery/albums/" in body
    assert "image_ids" in body, "the endpoint takes a bulk list, not one id"
    for verb in ("add", "remove"):
        assert f"'{verb}'" in GALLERY, f"nothing ever calls the {verb} endpoint"


def test_the_selection_is_the_image_bulk_bar_not_the_album_one():
    """The row cited the wrong selection state and its correction is the whole
    reason this was cheap. `_albumSelected` holds ALBUM ids and drives
    bulk-delete-albums; passing it here would delete-or-move the wrong things."""
    menu = _bulk_menu()
    assert "_albumSelected" not in menu
    assert menu.count("_selectedIds()") >= 4


# ── behaviour the endpoint cannot enforce for us ──

def test_remove_is_only_offered_inside_an_album():
    """"Remove from album" has no meaning in the all-photos view — the endpoint
    needs an album to remove from, and guessing one is worse than not offering
    the verb."""
    menu = _bulk_menu()
    assert "if (_activeAlbum)" in menu
    assert "_bulkRemoveFromAlbum(_selectedIds(), _activeAlbum)" in menu


def test_remove_asks_first_and_says_the_photos_survive():
    body = _fn("_bulkRemoveFromAlbum")
    assert "styledConfirm" in body
    assert "stay in your library" in body, \
        "removing from an album is not deleting, and the dialog has to say so"
    confirm_at = body.index("styledConfirm")
    post_at = body.index("_postAlbumMembership")
    assert confirm_at < post_at


def test_adding_does_not_ask_because_it_is_reversible():
    """A confirm on every action teaches people to dismiss confirms. Adding to
    an album is undone by removing from it."""
    body = _fn("_bulkAddToAlbum")
    assert "styledConfirm" not in body


def test_a_new_album_reuses_one_of_the_same_name():
    """Matching what the drag-and-drop import path already does. Two albums
    called "Holiday" is a worse outcome than reusing the one the person
    obviously means."""
    body = _fn("_bulkAddToNewAlbum")
    assert ".toLowerCase() === name.toLowerCase()" in body
    assert "_albums.find(" in body


def test_the_local_copy_is_corrected_after_the_server_moves_them():
    """The grid keeps rendering from `_items`. Without this the photos stay
    visible under the old album until a reload, which reads as a failed move."""
    for name, expected in (("_bulkAddToAlbum", "item.album_id = albumId"),
                           ("_bulkRemoveFromAlbum", "item.album_id = null")):
        assert expected in _fn(name), f"{name} does not correct the local copy"


def test_a_failed_call_does_not_pretend_it_worked():
    for name in ("_bulkAddToAlbum", "_bulkRemoveFromAlbum"):
        body = _fn(name)
        assert "showError" in body
        assert "return;" in body.split("showError", 1)[1][:120], \
            f"{name} carries on after reporting a failure"


def test_album_names_are_rendered_as_text_not_markup():
    """Album names are user-supplied and this menu is the first place they are
    rendered into one. The icons beside them are fixed SVG literals defined in
    the same function, which is why those may use innerHTML and the label may
    not."""
    menu = _bulk_menu()
    fill = menu.split("function fill(items)", 1)[1]
    assert "label.textContent = a.label;" in fill
    assert not re.search(r"label\.innerHTML", fill)


def test_the_submenu_does_not_build_a_second_dropdown():
    """`Law 14`. One dropdown with two pages, not a second popup anchored to
    the same button."""
    menu = _bulk_menu()
    assert menu.count("document.createElement('div')") <= 3, \
        "a second dropdown container has appeared"
    assert "keepOpen: true" in menu
    assert "if (!a.keepOpen) close();" in menu
