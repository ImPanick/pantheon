# SPDX-License-Identifier: AGPL-3.0-or-later
"""`B1940`. Reading a note on a phone and going back archived it.

On a window 768 px wide or less, Notes opens an existing note with its save
button in archive-mode: it says Archive until the form hears an edit, and
pressing it archives the note. The overlay's Back chevron is meant to save
whatever the form has and close, and it does that by pressing the same
button; closing or minimising Notes, Escape, and opening a document press it
too (`_closeMobileFullscreenEdit`), and so does closing Notes with a note
open in place on a narrow window without a touch screen
(`_commitOpenInPlaceEditor`). So the most common thing a person does on a
phone, open a note, read it and go back, took the note out of their list. A
note reopened with "Restored unsaved changes" also started as Archive, so
Back archived it and the restored changes were not saved.

Now leaving a note whose button is still in archive-mode only closes it: it
has heard no edit, so there is nothing to save. A note reopened with
restored changes starts as edited, so its button says Update and leaving
saves them. Pressing the Archive button itself still archives (`Law 1`), and
a note that was edited is still saved on the way out.

Pantheon's own finding, inherited from Odysseus v1.0 and still the same
upstream. `B1939` is the other half: it makes ticks and strokes count as
edits, so a note changed that way is not mistaken for one only read.

Driven (`Law 20`): the real `_openMobileFullscreenEdit`, `_editNote`,
`_closeMobileFullscreenEdit`, `_commitOpenInPlaceEditor` and
`_applyDraftToNote` run under node on the page
`tests/test_a_ticked_item_is_an_edit_on_a_phone_js.py` builds, with that
page's form (the archive-mode block, the head of the save press and the
draft autosave cut out of `_buildForm`) standing for `_buildForm`.
"""
import json
import re

import pytest

from tests.helpers.js_source import js_binding, js_definition
from tests.test_a_ticked_item_is_an_edit_on_a_phone_js import ARCHIVE, SRC, UPDATE, run, top

_FUNCTIONS = ("_applyDraftToNote", "_openMobileFullscreenEdit", "_editNote",
              "_closeMobileFullscreenEdit", "_commitOpenInPlaceEditor", "_addRowReadMode")

# What this page adds to that one: markup set through innerHTML (its tags and
# their classes), replaceWith and scrollIntoView, the card lookup `_editNote`
# makes by data-note-id, and stubs for what the lifted functions call around
# the form.
_EXTRA = r"""
Object.defineProperty(El.prototype, 'innerHTML', {
  set(html) {
    this.children = [];
    const open = [this];
    for (const m of String(html).matchAll(/<(\/?)([a-z]+)([^>]*)>/g)) {
      if (m[1]) { open.pop(); continue; }
      const cls = /class="([^"]*)"/.exec(m[3]);
      const el = open[open.length - 1].appendChild(new El(m[2], cls ? cls[1] : ''));
      if (!/^(input|img|br)$/.test(m[2]) && !m[3].trim().endsWith('/')) open.push(el);
    }
  },
  get() { return ''; },
});
El.prototype.replaceWith = function (fresh) { this.parentNode.replaceChild(fresh, this); };
El.prototype.scrollIntoView = function () {};
document.addEventListener = () => {};
const _plainQuery = document.querySelector;
document.querySelector = (sel) => {
  const card = /^\.note-card\[data-note-id="([^"]+)"\]$/.exec(sel);
  if (!card) return _plainQuery(sel);
  return body.querySelectorAll('.note-card').find((c) => c.dataset.noteId === card[1]) || null;
};
const toasts = [];
const uiModule = { showToast: (text) => toasts.push(String(text)), showError: () => {} };
const chevronIcon = () => '';
const scrollBehavior = () => 'auto';
const _applyMasonry = () => {};
const _wireChecklistTouchReorder = () => {};
const _fetchNotes = () => Promise.resolve();
function _renderNotes() {}
function _buildForm(n) { return phoneForm({ id: n.id }); }
// Around `closePanel` and `_forceCloseNotesPanel`.
document.removeEventListener = () => {};
const Modals = { isRegistered: () => true, unregister: () => {}, minimize: () => {} };
const _clearViewedReminderGlows = () => {};
const _ensureNotesChipRegistered = () => {};

// A narrow window without a touch screen edits in place, in the pane.
function paneWithCards(...ids) {
  const pane = body.appendChild(new El('div', 'notes-pane'));
  pane.id = 'notes-pane';
  const paneBody = pane.appendChild(new El('div', 'notes-pane-body'));
  for (const id of ids) paneBody.appendChild(new El('div', 'note-card')).dataset.noteId = id;
  return pane;
}
const todo = (id) => ({ id, title: 'Groceries', note_type: 'todo',
  items: [{ id: 'i0', text: 'milk', done: false }] });
"""


_STATE = ("_open", "_notes", "_editingId", "_reminderTimer", "_notesKeydownHandler",
          "_notesSelectEscHandler", "_mobileFsOverlay", "_mobileFsNoteId")


def _exported(name: str) -> str:
    """`export function name(…)` of `notes.js`, as a plain declaration."""
    found = re.search(r"^export function %s\(" % re.escape(name), SRC, re.M)
    assert found, f"no exported function {name} in notes.js"
    return js_definition(SRC, found.start() + len("export "))


def _run(script: str, *functions: str) -> dict:
    """`script` on that page, with these functions' text and Notes' own state."""
    state = "\n".join(js_binding(SRC, name) for name in _STATE)
    return run("\n".join((state, _EXTRA, *functions, script)), *_FUNCTIONS)


def test_back_on_a_note_you_only_read_closes_it_and_archives_nothing():
    """Open, read, press Back: the overlay closes and the note is still in the
    list. The Archive press itself still archives, and an edited note is
    still saved by Back."""
    out = _run("""
        _notes = [todo('N1'), todo('N2'), todo('N3')];
        _openMobileFullscreenEdit('N1', null);
        const overlay = _mobileFsOverlay;
        const opened = state(overlay.querySelector('.note-form'));
        overlay.querySelector('.note-fullscreen-back').click();
        const read = { pressed: pressed.splice(0), closed: !body.contains(overlay) && _mobileFsOverlay === null };

        _openMobileFullscreenEdit('N2', null);
        const archivePress = press(_mobileFsOverlay.querySelector('.note-form'));
        pressed.splice(0);

        _openMobileFullscreenEdit('N3', null);
        _mobileFsOverlay.querySelector('.note-cl-dot').click();
        _mobileFsOverlay.querySelector('.note-fullscreen-back').click();
        console.log(JSON.stringify({ opened, read, archivePress, edited: pressed.splice(0) }));
    """)
    assert out["opened"] == ARCHIVE
    assert out["read"] == {"pressed": [], "closed": True}, (
        "Back on a note that was only read must close it, not archive it")
    assert out["archivePress"] == ["archive N2"], "the Archive press itself still archives"
    assert out["edited"] == ["save N3"], "Back still saves a note that was edited"


@pytest.mark.parametrize("how", ["closed", "minimised", "closed for a document"])
def test_leaving_notes_with_a_note_you_only_read_archives_nothing(how):
    """`closePanel` (close, and minimise to the dock) and
    `_forceCloseNotesPanel` (Escape, the dock, a document opening) commit the
    note open in place and close the phone overlay with a save. Neither may
    archive a note nobody edited; a note edited in place is still saved."""
    out = _run("""
        const leave = { closed: () => closePanel(), minimised: () => closePanel('down'),
                        'closed for a document': () => _forceCloseNotesPanel() }[%s];
        _notes = [todo('N1'), todo('N2'), todo('N3')];
        _open = true;
        paneWithCards('N1');
        _editNote('N1');
        const inPlace = state(document.querySelector('#notes-pane .note-form'));
        leave();
        const readInPlace = pressed.splice(0);

        _open = true;
        _openMobileFullscreenEdit('N2', null);
        leave();
        const readOnPhone = pressed.splice(0);

        _open = true;
        paneWithCards('N3');
        _editNote('N3');
        document.querySelector('#notes-pane .note-cl-dot').click();
        leave();
        console.log(JSON.stringify({ inPlace, readInPlace, readOnPhone, edited: pressed.splice(0),
          left: document.getElementById('notes-pane') === null && _mobileFsOverlay === null }));
    """ % json.dumps(how), _exported("closePanel"), top("_forceCloseNotesPanel"))
    assert out["inPlace"] == ARCHIVE
    assert out["readInPlace"] == [], f"Notes {how} must not archive the note open in place"
    assert out["readOnPhone"] == [], f"Notes {how} must not archive the note open on a phone"
    assert out["edited"] == ["save N3"], "a note edited in place is still saved"
    assert out["left"] is True


@pytest.mark.parametrize("where", ["on a phone", "in place"])
def test_a_note_reopened_with_unsaved_changes_is_saved_on_the_way_out(where):
    """The draft autosave keeps an edit the page lost before Save; reopening
    the note restores it and says so. Those changes are unsaved, so the
    button says Update and leaving saves them rather than archiving."""
    out = _run("""
        const where = %s;
        localStorage.setItem(_draftKey('N1'), JSON.stringify({ note_type: 'todo', title: 'Groceries',
          items: [{ id: 'i0', text: 'milk', done: true }] }));
        _notes = [todo('N1')];
        let form;
        if (where === 'on a phone') {
          _openMobileFullscreenEdit('N1', null);
          form = _mobileFsOverlay.querySelector('.note-form');
        } else {
          paneWithCards('N1');
          _editNote('N1');
          form = document.querySelector('#notes-pane .note-form');
        }
        const reopened = state(form);
        if (where === 'on a phone') _mobileFsOverlay.querySelector('.note-fullscreen-back').click();
        else _commitOpenInPlaceEditor();
        console.log(JSON.stringify({ toasts, reopened, pressed }));
    """ % json.dumps(where))
    assert out["toasts"] == ["Restored unsaved changes"]
    assert out["reopened"] == UPDATE, "restored changes are unsaved: the button must offer to save them"
    assert out["pressed"] == ["save N1"]
