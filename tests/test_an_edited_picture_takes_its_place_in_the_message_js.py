# SPDX-License-Identifier: AGPL-3.0-or-later
"""`B1293` — the image editor hands an edit back to the composer.

A sent picture's *Edit in image editor* and the Gallery's *Edit* both opened
`galleryEditor.openEditor`, whose saves went to the Gallery; nothing returned
an edit to a chat, so a picture waiting in the composer could not be edited and
sent, and the card menu left the editor out rather than edit a copy the message
never sends. Now `gallery.openInEditor(url, id, label, { onDone })` is the one
open sequence (both callers use it), the editor offers *Attach to chat* when it
was opened with `onDone`, and the card menu's *Edit in image editor* puts the
edit where the original was.

The row's `Verify:` — *a node case that edits a pending picture and finds the
edit, not the original, in `getPendingRaw()`* — runs on the real
`static/js/fileHandler.js` and `attachHand.js` in the context meter's sandbox,
with the Gallery stubbed at its one seam (`openInEditor`): the stub plays the
person pressing *Attach to chat* by calling `onDone` with an edited file. The
editor's own half (`attachToChat`, the menu entry it shows) is held by scope.
"""
import ast
import json
import re
import shutil
from pathlib import Path

import pytest

from test_context_meter_js import _SHIM, _STUBS, _PREAMBLE, FILE_HANDLER
from test_tool_effect_surfaces_js import _make_sandbox, _run
from tests.helpers.js_source import js_function

ROOT = Path(__file__).resolve().parents[1]
JS = ROOT / "static" / "js"

pytestmark = pytest.mark.skipif(not shutil.which("node"), reason="node binary not on PATH")

_GALLERY_STUB = """
// The Gallery's one seam (`openInEditor`). It records how it was asked and,
// when told to, answers as *Attach to chat* does: `onDone(editedFile)`.
export async function openInEditor(url, id, label, opts = {}) {
  globalThis.__opened = { url, id, label, name: opts.name || null, hasDone: typeof opts.onDone === 'function' };
  // Kept, so a case can press *Attach to chat* later — after the composer moved on.
  globalThis.__onDone = opts.onDone || null;
  if (globalThis.__attach && typeof opts.onDone === 'function') {
    await opts.onDone(new File([new Uint8Array([9, 9, 9])], 'holiday (edited).png', { type: 'image/png' }));
  }
}
export default { openInEditor };
"""


@pytest.fixture(scope="module")
def sandbox(tmp_path_factory):
    stubs = dict(_STUBS)
    stubs["gallery.js"] = _GALLERY_STUB
    return _make_sandbox(tmp_path_factory.mktemp("editpending"), FILE_HANDLER, _SHIM, stubs)


def _drive(sandbox, then):
    return _run(sandbox, _PREAMBLE, """
        serve({});
        fh.init('');
        await tick();
        const hand = await import('./attachHand.js');
        const original = new File([new Uint8Array([1, 2, 3])], 'holiday.png', { type: 'image/png' });
        await fh.addFiles([original], { skipCrop: true });
        await tick();
        const ids = () => hand.actionsFor(fh.getPendingRaw()[0]).map((a) => a.id);
        const offered = ids();
        %s
        const now = fh.getPendingRaw();
        console.log(JSON.stringify({ offered, opened: globalThis.__opened || null,
          names: now.map((f) => f.name), stillOriginal: now[0] === original,
          size: now[0] ? now[0].size : null }));
    """ % then)


def test_the_card_offers_the_editor_for_a_waiting_picture(sandbox):
    out = _drive(sandbox, "")
    assert "edit" in out["offered"], out
    assert out["offered"].index("edit") == out["offered"].index("crop") + 1


def test_an_edited_pending_picture_is_the_one_in_the_message(sandbox):
    """The row's `Verify:`."""
    out = _drive(sandbox, """
        globalThis.__attach = true;
        await hand.actionsFor(fh.getPendingRaw()[0]).find((a) => a.id === 'edit').run();
        await tick();
    """)
    assert out["opened"]["hasDone"] is True and out["opened"]["label"] == "holiday.png"
    assert out["opened"]["url"], "the editor was opened on nothing"
    assert out["names"] == ["holiday (edited).png"]
    assert out["stillOriginal"] is False and out["size"] == 3


def test_leaving_the_editor_without_attaching_keeps_the_original(sandbox):
    out = _drive(sandbox, """
        globalThis.__attach = false;
        await hand.actionsFor(fh.getPendingRaw()[0]).find((a) => a.id === 'edit').run();
        await tick();
    """)
    assert out["names"] == ["holiday.png"] and out["stillOriginal"] is True


def test_an_edit_that_comes_back_after_the_picture_was_removed_goes_nowhere(sandbox):
    out = _run(sandbox, _PREAMBLE, """
        serve({});
        fh.init('');
        await tick();
        const hand = await import('./attachHand.js');
        const original = new File([new Uint8Array([1])], 'gone.png', { type: 'image/png' });
        await fh.addFiles([original], { skipCrop: true });
        globalThis.__attach = false;
        await hand.actionsFor(original).find((a) => a.id === 'edit').run();
        fh.removePending(0);
        const other = new File([new Uint8Array([2])], 'other.png', { type: 'image/png' });
        await fh.addFiles([other], { skipCrop: true });
        // *Attach to chat*, pressed after the picture it was opened for left.
        const took = await globalThis.__onDone(
          new File([new Uint8Array([9])], 'gone (edited).png', { type: 'image/png' }));
        await tick();
        console.log(JSON.stringify({ took, names: fh.getPendingRaw().map((f) => f.name) }));
    """)
    assert out["took"] is False
    assert out["names"] == ["other.png"], "the edit came back in place of a different picture"


# ── one open sequence, and the editor's half ───────────────────────────────

def test_the_gallery_and_a_sent_picture_open_the_editor_through_one_function():
    """Scoped by function (`Law 20` option 2): the Gallery's *Edit* handler and
    the chat card's *Edit in image editor* each call `openInEditor`, and
    neither spells the tab switch out itself any more."""
    gallery = (JS / "gallery.js").read_text(encoding="utf-8")
    assert re.search(r"^export async function openInEditor\(", gallery, re.M)
    opener = js_function(gallery, "export async function openInEditor(")
    assert 'data-tab="editor"' in opener and "gallery-editor-container" in opener
    handler = gallery[gallery.index("const _openInEditor = () => {"):]
    handler = handler[:handler.index("};") + 2]
    assert "openInEditor(img.url, img.id, label)" in handler
    assert 'data-tab="editor"' not in handler
    renderer = (JS / "chatRenderer.js").read_text(encoding="utf-8")
    edit = renderer[renderer.index("editBtn.title = 'Edit in image editor';"):]
    edit = edit[:edit.index("actions.appendChild(editBtn);")]
    assert "galleryMod.openInEditor(imageUrl, null, label)" in edit
    assert 'data-tab="editor"' not in edit


def test_the_editor_offers_attach_to_chat_only_when_it_was_opened_for_it():
    editor = (JS / "galleryEditor.js").read_text(encoding="utf-8")
    attach = js_function(editor, "export async function attachToChat(")
    assert "state.onDone" in attach and "new File(" in attach and "closeEditor()" in attach
    opener = js_function(editor, "export function openEditor(")
    assert "attachBtn.hidden = !state.onDone" in opener
    topbar = (JS / "editor" / "build" / "topbar.js").read_text(encoding="utf-8")
    assert re.search(r'id="ge-attach-chat"[^>]*\bhidden\b', topbar), "shown when nobody asked for it"
    wiring = (JS / "editor" / "wire-topbar.js").read_text(encoding="utf-8")
    assert "getElementById('ge-attach-chat')?.addEventListener('click', attachToChat)" in wiring
