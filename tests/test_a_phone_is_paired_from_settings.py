# SPDX-License-Identifier: AGPL-3.0-or-later
"""`B1713` — a phone is paired from Settings, not from a typed URL.

`companion/routes.py` mints a pairing code (`POST /api/companion/pair`) and
its `?format=json` answer was written "for an in-app pairing screen" — and no
screen called it. The only door was typing `/api/companion/pair` into the
address bar. MCP & Integrations' *Add* menu now has *Phone, paired with a QR
code*, whose form posts for the JSON and shows the QR and the address, port
and token the companion app needs, once.

Checked against `settings.js` as shipped; the route's JSON is
`tests/test_companion_pairing.py`'s, and the room was driven in Chromium
against the real app when this landed (the QR drawn, the token listed as an
API token to revoke).
"""
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
JS = (ROOT / "static" / "js" / "settings.js").read_text(encoding="utf-8")


def _form() -> str:
    start = JS.index("function showPhonePairForm()")
    return JS[start:JS.index("\n  }\n", start)]


def test_the_add_menu_offers_a_phone():
    options = JS[JS.index("const _typeOptions = ["):]
    options = options[:options.index("];")]
    assert "['phone', 'Phone, paired with a QR code']" in options
    assert "phone:   { label: 'Phone'" in JS
    assert "else if (type === 'phone') showPhonePairForm();" in JS


def test_the_form_asks_the_pairing_route_for_its_json():
    form = _form()
    assert "fetch('/api/companion/pair?format=json', { method: 'POST'" in form
    assert "readRefusal(r," in form


def test_only_a_png_data_uri_becomes_the_image():
    form = _form()
    assert "d.qr.startsWith('data:image/png;base64,')" in form
    assert "qr.src = d.qr" in form


def test_every_detail_is_escaped_and_the_list_redrawn():
    form = _form()
    assert "esc(String(v ?? ''))" in form and "esc(k)" in form
    for key in ("d.host", "d.port", "d.token"):
        assert key in form
    assert "await renderList();" in form
