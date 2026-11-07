# SPDX-License-Identifier: AGPL-3.0-or-later
"""Regression: PDF-form markdown export must not drop values whose label
contains an asterisk.

`parse_markdown_to_values` is the read-back path for GET .../export-pdf, the
export preview, and prepare-signed-reply. Its bullet regexes matched the bold
label with `[^*]+`, so they could not match a label like "Email *" / "State *"
/ "Signature *" — the near-universal required-field marker. The value then
stayed empty and the exported PDF (and signed-reply attachment) came out blank
for that field, with no error.

`B1792`. A field whose name is not ASCII was never filled either.
`_encode_name` kept every character `str.isalnum()` accepts, so `Prénom`,
`Straße` and `氏名` went into the bullet's marker as they were, and
`_FIELD_BULLET_RE` read only `[A-Za-z0-9_.%-]` there: the bullet did not
match, its value was skipped, and the exported PDF kept the field as it was,
with no error. The PDF overlay's own encoder (`_encodeFieldName` in
`static/js/document.js`) already percent-encoded those letters, so it never
found the marker and dropped what was typed on the page. Now the encoder keeps
ASCII letters and digits only, as the overlay's does, and the parser still
reads the literal markers saved by documents imported before. Ported from
upstream Odysseus 12fcddef (#6891); the first three `B1792` tests are its own.
"""
import json
import shutil
import subprocess
from pathlib import Path

import pytest

from src.pdf_form_doc import _encode_name, render_form_as_markdown, parse_markdown_to_values
from tests.helpers.js_source import js_function

DOCUMENT_JS = Path(__file__).resolve().parents[1] / "static" / "js" / "document.js"


def test_asterisk_label_value_survives_export_roundtrip():
    fields = [
        {"name": "email", "label": "Email Address *", "type": "text",
         "value": "me@x.com", "page": 1},
        {"name": "state", "label": "State *", "type": "choice",
         "options": ["CA", "NY"], "value": "NY", "page": 1},
        {"name": "sign", "label": "Signature *", "type": "signature",
         "value": "signature:s1", "page": 1},
    ]
    md = render_form_as_markdown(fields, "u", "F")
    vals = parse_markdown_to_values(md)
    assert vals["email"] == "me@x.com"
    assert vals["state"] == "NY"
    assert vals["sign"] == "signature:s1"


def test_plain_labels_and_colon_values_unaffected():
    fields = [
        {"name": "name", "label": "Full Name", "type": "text",
         "value": "Alice", "page": 1},
        {"name": "time", "label": "Start Time", "type": "text",
         "value": "9:00 sharp", "page": 1},
    ]
    md = render_form_as_markdown(fields, "u", "F")
    vals = parse_markdown_to_values(md)
    assert vals["name"] == "Alice"
    assert vals["time"] == "9:00 sharp"


# `B1792`: names outside ASCII. Combining marks (`Cafe\u0301`) were always
# encoded; the others went into the marker literally.
UNICODE_NAMES = ["Prénom", "Año", "İsim", "氏名", "اسم", "n²", "Cafe\u0301"]


@pytest.mark.parametrize("name", UNICODE_NAMES)
@pytest.mark.parametrize("field_type, value", [
    ("text", "Alice"), ("checkbox", True), ("choice", "Yes"),
])
def test_a_field_named_outside_ascii_survives_the_export_roundtrip(name, field_type, value):
    fields = [{"name": name, "label": "Field *", "type": field_type,
               "value": value, "options": ["Yes", "No"], "page": 1}]
    markdown = render_form_as_markdown(fields, "upload", "Form")
    marker_name = markdown.split("<!-- field=", 1)[1].split(" type=", 1)[0]
    assert marker_name.isascii()
    assert parse_markdown_to_values(markdown) == {name: value}


def test_a_marker_saved_before_the_fix_still_exports():
    """A document imported before `B1792` holds the old encoder's literal
    letters; it exports without importing the PDF again."""
    markdown = (
        "- **First name:** Alice <!-- field=Prénom type=text -->\n"
        "- [x] **Consent** <!-- field=同意 type=checkbox -->\n"
        "- **Year** [2025 / 2026]: 2026 <!-- field=Año type=choice -->\n"
    )
    assert parse_markdown_to_values(markdown) == {
        "Prénom": "Alice", "同意": True, "Año": "2026",
    }


def test_an_encoded_name_never_collides_with_a_literal_percent_or_an_ascii_name():
    names = ["Prénom", "Pr%C3%A9nom", "Prenom", "Section.1_name-2"]
    fields = [{"name": name, "type": "text", "value": str(i), "page": 1}
              for i, name in enumerate(names)]
    markdown = render_form_as_markdown(fields, "upload", "Form")
    assert "field=Section.1_name-2 " in markdown
    assert parse_markdown_to_values(markdown) == {name: str(i) for i, name in enumerate(names)}


@pytest.mark.skipif(not shutil.which("node"), reason="node binary not on PATH")
def test_the_marker_is_the_name_the_pdf_overlay_looks_for():
    """The overlay saves a field typed on the page into the bullet whose marker
    is `_encodeFieldName(name)`, its mirror of `_encode_name`. The shipped
    function, cut out of `document.js` and run under node, writes the same
    marker for every name."""
    names = UNICODE_NAMES + ["Straße", "Pr%C3%A9nom", "Section.1_name-2", "a b (c), d?"]
    source = DOCUMENT_JS.read_text(encoding="utf-8")
    script = ("function _encodeFieldName(name) "
              + js_function(source, "function _encodeFieldName")
              + f"\nconsole.log(JSON.stringify({json.dumps(names)}.map(_encodeFieldName)));\n")
    done = subprocess.run(["node", "--input-type=module", "-e", script],
                          capture_output=True, text=True, timeout=30)
    assert done.returncode == 0, done.stderr
    overlay = json.loads(done.stdout.strip().splitlines()[-1])
    assert [_encode_name(name) for name in names] == overlay
