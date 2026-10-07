# SPDX-License-Identifier: AGPL-3.0-or-later
"""`P2-24` — a custom font is added from the theme panel, and only a font is.

The theme panel said: *"Drop `.woff2`, `.ttf`, or `.otf` files into
`static/fonts/custom/` and reload"* — a server path, which in Docker is inside
the image. Now it has **Add a font**, backed by `POST /api/fonts/custom`.

This is the one upload whose allowlist stays, because it is the one whose bytes
are handed to the browser rather than downloaded. Each test below answers one
adversary the route names (`Law 17`): a non-admin who would change what every
browser on the instance loads; a hostile page or SVG font handed to an admin as
"a font"; a crafted filename; and — measured, not assumed — the agent, which
cannot reach this route at all.

Also measured, and the reason the files are not where the row said they would
land: `static/` is not a volume in Docker and is PyInstaller's temporary
extraction directory in the desktop builds, so an upload is written under
`DATA_DIR` and served by a route with a fixed type — `static/` stays a directory
nothing writes into.

`Law 20`: every test posts real bytes through the real router and the real
`require_admin`. The fonts are real: the shipped `Inter-Regular.woff2`, and a
TrueType/WOFF pair built in `tests/helpers/font_fixtures.py` and checked by
FreeType before anything trusts it.
"""
import io
import json
import shutil
import subprocess
from pathlib import Path

import pytest
from fastapi import FastAPI, Request
from fastapi.testclient import TestClient
from PIL import Image, ImageDraw, ImageFont

import core.middleware as middleware
import routes.font_routes as font_routes
import src.settings as S
from tests.helpers.font_fixtures import FAMILY, truetype_font, woff_font
from tests.helpers.js_source import js_definition

ROOT = Path(__file__).resolve().parent.parent
INTER = (ROOT / "static" / "fonts" / "Inter-Regular.woff2").read_bytes()
TTF = truetype_font()
WOFF = woff_font(TTF)
THEME_JS = ROOT / "static" / "js" / "theme.js"


def test_the_built_fonts_are_fonts_to_freetype():
    """The fixture's premise, checked by a parser that is not ours."""
    for data in (TTF, WOFF):
        face = ImageFont.truetype(io.BytesIO(data), 48)
        assert face.getname() == (FAMILY, "Regular")
        canvas = Image.new("L", (160, 80), 0)
        ImageDraw.Draw(canvas).text((10, 10), "AB", font=face, fill=255)
        assert canvas.getbbox() is not None, "no glyph was drawn"
    assert INTER[:4] == b"wOF2"


# ── the route, for real ─────────────────────────────────────────────────────

class _Auth:
    is_configured = True

    @staticmethod
    def is_admin(user):
        return user == "admin"


@pytest.fixture
def env(tmp_path, monkeypatch):
    uploads = tmp_path / "data" / "fonts"
    legacy = tmp_path / "static" / "fonts" / "custom"
    legacy.mkdir(parents=True)
    monkeypatch.setattr(font_routes, "UPLOADED_FONTS_DIR", str(uploads))
    monkeypatch.setattr(font_routes, "CUSTOM_FONTS_DIR", str(legacy))
    monkeypatch.setattr(S, "SETTINGS_FILE", str(tmp_path / "settings.json"))
    S._invalidate_caches()
    monkeypatch.delenv("PANTHEON_FONT_UPLOAD_MAX_BYTES", raising=False)

    app = FastAPI()
    app.state.auth_manager = _Auth()

    @app.middleware("http")
    async def _who(request: Request, call_next):
        request.state.current_user = request.headers.get("x-test-user")
        return await call_next(request)

    app.include_router(font_routes.setup_font_routes())
    client = TestClient(app)
    client.uploads, client.legacy, client.tmp = uploads, legacy, tmp_path
    yield client
    S._invalidate_caches()


def _add(client, name, data, user="admin"):
    return client.post("/api/fonts/custom", files={"file": (name, data)},
                       headers={"x-test-user": user})


def _listing(client, user="admin"):
    return client.get("/api/fonts/custom", headers={"x-test-user": user}).json()


# ── a font goes in, and comes back as a font ────────────────────────────────

@pytest.mark.parametrize("name, data, mime", [
    ("Inter-Regular.woff2", INTER, "font/woff2"),
    ("PantheonTest-Regular.ttf", TTF, "font/ttf"),
    ("PantheonTest-Regular.otf", TTF, "font/otf"),
    ("PantheonTest-Regular.woff", WOFF, "font/woff"),
], ids=["woff2", "ttf", "otf-truetype-outlines", "woff"])
def test_a_real_font_is_added_listed_and_served_as_a_font(env, name, data, mime):
    res = _add(env, name, data)
    assert res.status_code == 200, res.text
    body = res.json()
    assert body["file"] == name and body["url"] == f"/api/fonts/custom/{name}"
    assert (env.uploads / name).read_bytes() == data

    family = body["family"]
    # `B937` added `source`, so the panel can offer Remove on an upload.
    assert _listing(env)["fonts"][family] == [
        {"file": name, "url": f"/api/fonts/custom/{name}", "format": name.rsplit(".", 1)[1],
         "source": "upload"}]

    served = env.get(body["url"], headers={"x-test-user": "someone"})
    assert served.status_code == 200
    assert served.content == data
    assert served.headers["content-type"] == mime
    assert served.headers["x-content-type-options"] == "nosniff"
    assert served.headers["content-disposition"].startswith("attachment;")


def test_the_listing_hands_the_picker_the_same_allowlist(env):
    assert _listing(env)["accepted"] == [".otf", ".ttf", ".woff", ".woff2"]


def test_a_mislabelled_font_is_stored_as_what_it_is(env):
    """A WOFF2 named `.ttf` is a font, so it is kept — as WOFF2, so the type it
    is served with matches its bytes."""
    res = _add(env, "Inter-Regular.ttf", INTER)
    assert res.status_code == 200
    assert res.json()["file"] == "Inter-Regular.woff2"
    served = env.get("/api/fonts/custom/Inter-Regular.woff2", headers={"x-test-user": "admin"})
    assert served.headers["content-type"] == "font/woff2"


def test_a_hand_dropped_font_still_appears(env):
    """`Law 1`: a file somebody put in `static/fonts/custom/` keeps working,
    served by the `/static` mount as before."""
    (env.legacy / "JetBrainsMono-Regular.woff2").write_bytes(INTER)
    fonts = _listing(env)["fonts"]
    assert fonts["JetBrains Mono"][0]["url"] == "/static/fonts/custom/JetBrainsMono-Regular.woff2"


def test_the_hand_dropped_directory_is_anchored_to_static_dir():
    """`P2-CORRECTED` § B: it was relative to the process's working directory."""
    from src.constants import DATA_DIR, STATIC_DIR
    assert font_routes.CUSTOM_FONTS_DIR == str(Path(STATIC_DIR) / "fonts" / "custom")
    assert Path(font_routes.CUSTOM_FONTS_DIR).is_absolute()
    assert font_routes.UPLOADED_FONTS_DIR == str(Path(DATA_DIR) / "fonts")


def test_an_upload_writes_nothing_under_static(env):
    """The premise `app._RevalidatingStatic` hashes inline scripts on: no route
    writes into `static/`. Uploads go to `DATA_DIR`."""
    assert _add(env, "Inter-Regular.woff2", INTER).status_code == 200
    assert list(env.legacy.iterdir()) == []
    assert [p.name for p in env.uploads.iterdir()] == ["Inter-Regular.woff2"]


# ── what is not a font is refused, and nothing is written ────────────────────

_PAGE = b"<!doctype html><script>fetch('/api/auth/status')</script>"
_SVG_FONT = (b'<?xml version="1.0"?><svg xmlns="http://www.w3.org/2000/svg"><defs>'
             b'<font id="f" horiz-adv-x="500"><font-face font-family="X" units-per-em="1000"/>'
             b'<glyph unicode="A" d="M0 0L500 0L250 700Z"/></font></defs>'
             b'<script>alert(1)</script></svg>')


def _sfnt_shaped_page():
    """A page behind a well-formed one-table sfnt directory — every structural
    check but the last passes, so only "a font has a `head` table" refuses it."""
    import struct
    body = _PAGE
    return (struct.pack(">IHHHH", 0x00010000, 1, 16, 0, 0)
            + struct.pack(">4sIII", b"html", 0, 28, len(body)) + body)


def _png():
    buf = io.BytesIO()
    Image.new("RGB", (32, 32), (9, 9, 9)).save(buf, "PNG")
    return buf.getvalue()


@pytest.mark.parametrize("name, data, why", [
    ("page.html", _PAGE, "Only WOFF2, WOFF, TTF and OTF"),
    ("font.svg", _SVG_FONT, "Only WOFF2, WOFF, TTF and OTF"),
    ("font.svgz", _SVG_FONT, "Only WOFF2, WOFF, TTF and OTF"),
    ("evil.woff2", _PAGE, "isn't a font file"),
    ("evil.ttf", _SVG_FONT, "isn't a font file"),
    ("evil.otf", b"", "isn't a font file"),
    ("photo.woff", _png(), "isn't a font file"),
    ("glued.woff2", b"wOF2" + _PAGE, "isn't a font file"),
    ("glued.ttf", b"\x00\x01\x00\x00" + _PAGE, "isn't a font file"),
    ("truncated.woff2", INTER[:4096], "isn't a font file"),
    ("truncated.ttf", TTF[:200], "isn't a font file"),
    ("directory.ttf", _sfnt_shaped_page(), "isn't a font file"),
], ids=["html-by-name", "svg-font-by-name", "svgz-by-name", "html-as-woff2",
        "svg-font-as-ttf", "empty", "png-as-woff", "woff2-magic-then-html",
        "sfnt-magic-then-html", "truncated-woff2", "truncated-ttf",
        "sfnt-directory-then-html"])
def test_what_is_not_a_font_is_refused(env, name, data, why):
    res = _add(env, name, data)
    assert res.status_code == 400
    assert why in res.json()["detail"]
    assert not env.uploads.exists() or list(env.uploads.iterdir()) == []


def test_only_an_admin_can_add_a_font(env):
    res = _add(env, "Inter-Regular.woff2", INTER, user="bob")
    assert res.status_code == 403
    assert not env.uploads.exists()
    # Reading the list and the files is for everyone signed in.
    assert _listing(env, user="bob")["accepted"]


def test_the_agent_cannot_reach_it(env):
    """`app_api` sends JSON bodies only. Measured with the admin identity the
    internal token would carry: a JSON body is refused before anything runs."""
    res = env.post("/api/fonts/custom", json={"file": "Inter-Regular.woff2"},
                   headers={"x-test-user": "admin"})
    assert res.status_code == 422
    assert not env.uploads.exists()


def test_a_crafted_filename_cannot_leave_the_directory_or_the_charset(env):
    """The name reaches the disk and, as the family, a `<style>` the theme
    writes. Neither sees a quote, a parenthesis, a slash or a dot."""
    res = _add(env, "../../x'); }body{background:url(//evil)} .y{a:(.woff2", INTER)
    assert res.status_code == 200, res.text
    stored = res.json()["file"]
    # Everything up to the last slash is a directory and is dropped first; what
    # is left is rebuilt in `[A-Za-z0-9_-]`.
    assert stored == "evil-y-a.woff2"
    assert (env.uploads / stored).exists()
    assert set(res.json()["family"]) <= set("abcdefghijklmnopqrstuvwxyz"
                                            "ABCDEFGHIJKLMNOPQRSTUVWXYZ0123456789 -_")


@pytest.mark.parametrize("path", [
    "..%2Fsettings.json", "notes.html", "Inter-Regular.woff2.html", ".part",
    "a" * 81 + ".woff2", "missing.woff2",
])
def test_the_serving_route_serves_uploaded_fonts_and_nothing_else(env, path):
    (env.uploads).mkdir(parents=True, exist_ok=True)
    (env.uploads / "notes.html").write_bytes(_PAGE)
    (env.tmp / "data" / "settings.json").write_text("{}")
    res = env.get(f"/api/fonts/custom/{path}", headers={"x-test-user": "admin"})
    assert res.status_code == 404


# ── size is capped through the `P12-01` chain ────────────────────────────────

def test_the_instance_setting_caps_the_upload(env):
    Path(S.SETTINGS_FILE).write_text(json.dumps({"font_upload_max_bytes": 4096}))
    S._invalidate_caches()
    res = _add(env, "Inter-Regular.woff2", INTER)
    assert res.status_code == 413
    assert res.json()["detail"] == "Font upload exceeds 4 KB limit"
    assert not env.uploads.exists()
    assert _add(env, "PantheonTest-Regular.ttf", TTF).status_code == 200


def test_a_role_caps_the_admin_it_belongs_to(env, monkeypatch):
    monkeypatch.setattr(S, "_role_limit_provider",
                        lambda key, owner: 1024 if (key == "font_upload_max_bytes"
                                                    and owner == "admin") else None)
    assert _add(env, "Inter-Regular.woff2", INTER).status_code == 413


def test_the_environment_caps_it_when_nothing_above_does(env, monkeypatch):
    monkeypatch.setenv("PANTHEON_FONT_UPLOAD_MAX_BYTES", "2048")
    assert _add(env, "Inter-Regular.woff2", INTER).status_code == 413


def test_the_built_in_default_is_25_mb():
    from src.upload_limits import BYTE_LIMITS
    assert BYTE_LIMITS["font_upload_max_bytes"] == (
        "PANTHEON_FONT_UPLOAD_MAX_BYTES", 25 * 1024 * 1024)


# ── the panel ───────────────────────────────────────────────────────────────

@pytest.mark.skipif(not shutil.which("node"), reason="node not on PATH")
@pytest.mark.parametrize("outcome", ["added", "refused", "forbidden"])
def test_the_panel_adds_the_font_or_says_why_not(env, outcome):
    """The shipped `addCustomFont` + `loadCustomFonts`, answered by the real
    route's own responses: on success the new family is in the Font menu and
    selected through the menu's change handler (which applies and saves it);
    otherwise the person reads the server's reason."""
    if outcome == "added":
        post = _add(env, "Inter-Regular.woff2", INTER)
    elif outcome == "refused":
        post = _add(env, "evil.woff2", _PAGE)
    else:
        post = _add(env, "Inter-Regular.woff2", INTER, user="bob")
    listing = _listing(env)
    source = THEME_JS.read_text(encoding="utf-8")
    fns = "\n".join(
        js_definition(source, source.index(sig)).replace("export ", "", 1)
        for sig in ("export function loadCustomFonts(", "export async function addCustomFont("))
    script = """
let _customFonts = {};
const changes = [];
const make = (id) => ({ id, value: '', accept: '', textContent: '', dataset: {}, options: [],
  querySelectorAll(sel) { return this.options.filter(o => o.dataset.customFont); },
  appendChild(o) { this.options.push(o); o.remove = () => { this.options = this.options.filter(x => x !== o); }; },
  dispatchEvent(e) { changes.push([e.type, this.value]); } });
const elements = { 'theme-font-select': make('theme-font-select'),
                   'theme-font-upload-input': make('theme-font-upload-input'),
                   'theme-font-upload-status': make('theme-font-upload-status') };
const document = { getElementById: (id) => elements[id] || null,
                   createElement: () => ({ dataset: {} }) };
class Event { constructor(type) { this.type = type; } }
class FormData { append() {} }
const console = { warn() {}, log() {}, error() {} };
const post = %s, listing = %s;
const fetch = async (url, opts) => (opts && opts.method === 'POST')
  ? { ok: post.status < 400, status: post.status, json: async () => post.body }
  : { ok: true, status: 200, json: async () => listing };
%s
addCustomFont({ name: 'Inter-Regular.woff2' }).then((out) => {
  const sel = elements['theme-font-select'];
  process.stdout.write(JSON.stringify({ out, status: elements['theme-font-upload-status'].textContent,
    options: sel.options.map(o => o.value), value: sel.value, changes,
    accept: elements['theme-font-upload-input'].accept }));
});
""" % (json.dumps({"status": post.status_code, "body": post.json()}), json.dumps(listing), fns)
    proc = subprocess.run(["node", "-e", script], capture_output=True, text=True)
    assert proc.returncode == 0, proc.stderr
    out = json.loads(proc.stdout)
    if outcome == "added":
        assert out["options"] == ["Inter"] and out["value"] == "Inter"
        assert out["changes"] == [["change", "Inter"]]
        assert out["status"] == "Added Inter."
        assert out["accept"] == ".otf,.ttf,.woff,.woff2"
    elif outcome == "refused":
        assert out["out"] is None and out["changes"] == []
        assert out["status"] == "evil.woff2 isn't a font file."
    else:
        assert out["status"] == "Only an admin can add fonts."
