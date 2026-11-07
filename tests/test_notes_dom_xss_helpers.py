# SPDX-License-Identifier: AGPL-3.0-or-later
"""Regression guards for Notes DOM rendering helpers."""

import json
import re
import shutil
import subprocess
from pathlib import Path

import pytest

from tests.helpers.js_source import js_definition

_REPO = Path(__file__).resolve().parent.parent


def test_notes_image_src_guard_rejects_script_capable_data_images():
    src = (_REPO / "static" / "js" / "notes.js").read_text(encoding="utf-8")

    assert "function _safeImgSrc(s)" in src
    assert r"^data:image\/(?:png|jpe?g|gif|webp);base64," in src
    assert r"^data:image\/i.test(v)" not in src


def test_notes_linkify_escapes_href_attribute():
    src = (_REPO / "static" / "js" / "notes.js").read_text(encoding="utf-8")

    assert "function _attrEsc(s)" in src
    assert 'href="${_attrEsc(href)}"' in src
    assert 'href="${href}"' not in src


def test_notes_edit_form_uses_safe_image_src_guard():
    src = (_REPO / "static" / "js" / "notes.js").read_text(encoding="utf-8")

    assert "let currentImageUrl = _safeImgSrc(note?.image_url || '');" in src
    assert "let _stashedDrawUrl = (type === 'draw') ? (_safeImgSrc(note?.image_url) || null) : null;" in src
    assert "_wireCanvas(bodyEl, _stashedDrawUrl || currentImageUrl || _safeImgSrc(note?.image_url) || null)" in src
    assert "_wireCanvas(form.querySelector('.note-form-body'), _safeImgSrc(note?.image_url) || null)" in src
    assert "const safeInitialImageUrl = _safeImgSrc(initialImageUrl);" in src
    assert "img.src = safeInitialImageUrl;" in src
    assert "img.src = initialImageUrl;" not in src


# ── `B2003`: a reminder's stored values stay inside their attributes ──────────
#
# A note's `due_date` is stored as it was sent when the server cannot read it
# as a date (`manage_notes` falls back to the raw text), and the edit form wrote
# it, and `repeat`, into its two hidden inputs' `value="…"` unescaped: a stored
# `"><meta http-equiv="refresh" …>` closed the attribute and became an element
# in the page, which a browser acts on when it is inserted. The custom date
# picker then wrote the hidden input's decoded value into markup the same way.
# Both are run under node as they ship: the form's two lines cut out of
# `_buildForm`, and `_pickCustomDate` itself.
_SRC = (_REPO / "static" / "js" / "notes.js").read_text(encoding="utf-8")
_HOSTILE = '"><meta http-equiv="refresh" content="0;url=https://example.invalid/">&amp;'
_needs_node = pytest.mark.skipif(not shutil.which("node"), reason="node binary not on PATH")


def _cut(signature: str, within: str = _SRC) -> str:
    return js_definition(within, within.index(signature))


def _node(script: str) -> dict:
    proc = subprocess.run(["node", "--input-type=module"], input=script, capture_output=True,
                          text=True, cwd=str(_REPO), timeout=60)
    assert proc.returncode == 0, proc.stderr
    return json.loads([ln for ln in proc.stdout.splitlines() if ln.strip()][-1])


# The browser's half: tags in markup, and an attribute's text decoded.
_READ = r"""
const tagsOf = (html) => [...String(html).matchAll(/<([a-z]+)/gi)].map((m) => m[1].toLowerCase());
const decoded = (s) => s.replace(/&(quot|#39|lt|gt|#96|amp);/g,
  (m, e) => ({ quot: '"', '#39': "'", lt: '<', gt: '>', '#96': '`', amp: '&' })[e]);
const valuesOf = (html) => [...String(html).matchAll(/value="([^"]*)"/g)].map((m) => decoded(m[1]));
"""


@_needs_node
def test_a_reminder_stored_as_markup_stays_inside_the_edit_forms_inputs():
    """The form's two hidden reminder inputs, rendered with a stored `due_date`
    and `repeat` that each try to close the attribute: two inputs come out, and
    each value reads back exactly as it was stored."""
    form = _cut("function _buildForm(")
    lines = re.findall(r'^[ \t]*(<input type="hidden" class="note-form-(?:due|repeat)"[^\n]*)$', form, re.M)
    assert len(lines) == 2, lines
    out = _node("\n".join((_cut("function _attrEsc("), _cut("function _attrEscRaw("), _READ,
                           "const note = { due_date: %s, repeat: %s };" % (json.dumps(_HOSTILE), json.dumps(_HOSTILE)),
                           "const html = `%s`;" % "\n".join(lines),
                           "console.log(JSON.stringify({ tags: tagsOf(html), values: valuesOf(html) }));")))
    assert out == {"tags": ["input", "input"], "values": [_HOSTILE, _HOSTILE]}, (
        "a stored due date or repeat must come back as the input's value, not as markup")


@_needs_node
def test_the_custom_date_picker_takes_the_value_as_a_value_not_as_markup():
    """*Pick date and time* opens on the reminder the form holds. That value is
    the hidden input's, already decoded by the browser: it is handed to the date
    input as its value, and none of it becomes markup."""
    picker = _cut("function _pickCustomDate(")
    out = _node(_READ + r"""
const made = [];
class El {
  constructor(tag) { this.tag = tag; this.style = {}; this.kids = []; this.listeners = {}; this.html = ''; }
  set innerHTML(html) {
    this.html = html;
    this.kids = [...String(html).matchAll(/<([a-z]+)([^>]*)>/gi)].map((m) => {
      const kid = new El(m[1].toLowerCase());
      kid.className = (/class="([^"]*)"/.exec(m[2]) || [, ''])[1];
      const v = /value="([^"]*)"/.exec(m[2]);
      kid.value = v ? decoded(v[1]) : '';
      return kid;
    });
  }
  get innerHTML() { return this.html; }
  querySelector(sel) { return this.kids.find((k) => ('.' + k.className.split(' ').join('.')).includes(sel)) || null; }
  addEventListener(type, fn) { this.listeners[type] = fn; }
  getBoundingClientRect() { return { top: 100, bottom: 120, left: 40, right: 60 }; }
  focus() {}
  remove() {}
}
const document = {
  querySelectorAll: () => [],
  createElement: (tag) => { const el = new El(tag); made.push(el); return el; },
  body: { appendChild() {} },
};
const window = { innerWidth: 1280, innerHeight: 800 };
const dismissOrRemove = () => {};
const bindMenuDismiss = () => () => {};
const _setReminder = () => {};
const _toLocalDatetimeStr = () => '2030-01-01T08:00';
const _tomorrowDate = () => null;
const dueInput = { value: %s };
const remindBtn = new El('button');
const form = { querySelector: () => remindBtn };
""" % json.dumps(_HOSTILE) + picker + r"""
_pickCustomDate();
const menu = made[0];
const input = menu.querySelector('.note-reminder-date-input');
console.log(JSON.stringify({ tags: tagsOf(menu.innerHTML), value: input && input.value }));
""")
    assert "meta" not in out["tags"], "the picker wrote the stored value into its markup"
    assert out["value"] == _HOSTILE, "the picker must open on the stored value"
