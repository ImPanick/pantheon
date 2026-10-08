# SPDX-License-Identifier: AGPL-3.0-or-later
"""P0-13 / B71 — Pantheon ships its own mark, everywhere it ships a picture of itself.

Until 2026-10-02 every picture of Pantheon was upstream's: a red sailing boat in
the favicon, on the login card and the welcome screen (nine inline copies of its
SVG), drawn again in polygons for the Windows tray, as the PWA and Windows icons,
and a screenshot of upstream's UI that `build-macos-app.sh` cropped into the macOS
app icon. `D-2026-10-02-03` §2: an agent makes a simple mark. It is in
`docs/brand/`, drawn by `scripts/branding/make_marks.py`.

What these tests hold, each by running the thing rather than reading it:

  * **every writer draws the mark** — `theme.js`'s `applyColors()` and both of
    `index.html`'s cold-load scripts are run in node and the favicon they write is
    decoded and compared, path for path, with `docs/brand/pantheon-mark.svg` and
    `docs/brand/routes/*.svg`. The two route registries (`index.html` and
    `theme.js`) are therefore held to one source, on all eight routes;
  * **every inline copy is the mark** — the `<link rel="icon">` of the app, the
    login page and the project page, and the `<svg>` inside the welcome title,
    the login heading and the project page's brand, each found by its element
    rather than by searching the file;
  * **every branding file something names exists and is what it claims** — the
    manifest's icons, the touch icons, the notification icons and the API docs'
    favicon are fetched through the real `/static` mount; the Windows build's
    `.ico` is read from `Pantheon.spec`; the macOS build's icon block is run;
  * **the tray draws the shipped icon**, not a third drawing;
  * **the committed files are what the script draws** (`--check`);
  * **upstream's artwork stays out** — `check-fork-names.py`'s pixel half passes
    on the tree, and each of its three detectors is shown to catch a planted copy
    and to pass the things it must not flag.
"""
import base64
import importlib.util
import json
import os
import re
import shutil
import subprocess
import sys
import textwrap
import xml.etree.ElementTree as ET
from html.parser import HTMLParser
from pathlib import Path
from urllib.parse import unquote, urljoin

import pytest

from test_tool_effect_surfaces_js import _make_sandbox  # noqa: E402
from test_accent_token_js import _inline_script  # noqa: E402
from test_advanced_key_mirrors_js import (  # noqa: E402
    _SHIM, _STUBS, _TEST_EXPORTS, _base_palette, _route_favicon_script, _run,
)

ROOT = Path(__file__).resolve().parents[1]
BRAND = ROOT / "docs" / "brand"
STATIC = ROOT / "static"
THEME = STATIC / "js" / "theme.js"
INDEX = STATIC / "index.html"
LOGIN = STATIC / "login.html"
PROJECT_PAGE = ROOT / "docs" / "index.html"
ROUTES = ("calendar", "notes", "cookbook", "email", "memory", "gallery", "tasks", "library")
SVG_NS = "{http://www.w3.org/2000/svg}"

node = pytest.mark.skipif(not shutil.which("node"), reason="node binary not on PATH")


def _load(name, path):
    spec = importlib.util.spec_from_file_location(name, path)
    mod = importlib.util.module_from_spec(spec)
    sys.modules[name] = mod  # @dataclass looks its module up here while it runs
    spec.loader.exec_module(mod)
    return mod


@pytest.fixture(scope="module")
def checker():
    return _load("check_fork_names", ROOT / ".pantheon" / "check-fork-names.py")


@pytest.fixture(scope="module")
def marks():
    sys.path.insert(0, str(ROOT / "scripts" / "branding"))
    try:
        return _load("make_marks", ROOT / "scripts" / "branding" / "make_marks.py")
    finally:
        sys.path.remove(str(ROOT / "scripts" / "branding"))


# ── What "the mark" is: read out of the SVGs the script writes ──────────────


def _paths(svg_text: str) -> list:
    """[(fill, fill-rule, d)] for every <path> in an SVG document."""
    root = ET.fromstring(svg_text)
    return [(p.get("fill"), p.get("fill-rule"), p.get("d")) for p in root.iter(f"{SVG_NS}path")]


def _brand_d(rel: str) -> str:
    paths = _paths((BRAND / rel).read_text(encoding="utf-8"))
    assert len(paths) == 1, f"{rel} should be one even-odd path, found {len(paths)}"
    return paths[0][2]


MARK_D = _brand_d("pantheon-mark.svg")


def _decode_data_uri(href: str) -> str:
    assert href.startswith("data:image/svg+xml"), href[:60]
    head, _, body = href.partition(",")
    return base64.b64decode(body).decode() if head.endswith(";base64") else unquote(body)


# ── 1. Every favicon writer draws the mark (driven in node) ─────────────────


@pytest.fixture(scope="module")
def sandbox(tmp_path_factory):
    box = _make_sandbox(tmp_path_factory.mktemp("pantheonmark"), THEME, _SHIM, _STUBS)
    with (box / THEME.name).open("a", encoding="utf-8") as handle:
        handle.write(_TEST_EXPORTS)
    (box / "index_paint.js").write_text(_inline_script(INDEX))
    (box / "index_route_favicon.js").write_text(_route_favicon_script())
    return box


ACCENT = "#123456"


def _expected(d):
    return [(ACCENT, "evenodd", d)]


@node
@pytest.mark.parametrize("path", ["/"] + [f"/{r}" for r in ROUTES])
def test_the_module_draws_the_mark_or_the_routes_own_glyph(sandbox, path):
    """`applyColors()` → `_updateFavicon()`, on the root and on all eight routes."""
    out = _run(sandbox, f"""
        import {{ favicon }} from './shim.js';
        globalThis.location.pathname = {json.dumps(path)};
        const tm = await import('./theme.js');
        tm.applyColors({{ ...tm.THEMES.dark, accent: {json.dumps(ACCENT)} }});
        console.log(JSON.stringify({{ href: favicon() }}));
        """)
    want = MARK_D if path == "/" else _brand_d(f"routes{path}.svg")
    assert _paths(_decode_data_uri(out["href"])) == _expected(want), out["href"][:200]


@node
def test_the_first_paint_script_draws_the_mark(sandbox):
    palette = dict(_base_palette("dark"), accent=ACCENT)
    out = _run(sandbox, f"""
        import {{ seed, favicon }} from './shim.js';
        globalThis.location.pathname = '/';
        seed({json.dumps({"name": "dark", "colors": palette})});
        await import('./index_paint.js');
        console.log(JSON.stringify({{ href: favicon() }}));
        """)
    assert _paths(_decode_data_uri(out["href"])) == _expected(MARK_D)


@node
@pytest.mark.parametrize("route", ROUTES)
def test_the_cold_load_route_script_draws_the_same_glyph_as_the_module(sandbox, route):
    """`index.html`'s per-route script runs before `theme.js` exists; if its
    registry and the module's drift, a bookmark shows one icon and swaps to
    another on boot. Both are held to `docs/brand/routes/<route>.svg`."""
    palette = dict(_base_palette("dark"), accent=ACCENT)
    out = _run(sandbox, f"""
        import {{ seed, favicon }} from './shim.js';
        globalThis.location.pathname = {json.dumps('/' + route)};
        seed({json.dumps({"name": "dark", "colors": palette})});
        await import('./index_route_favicon.js');
        console.log(JSON.stringify({{ href: favicon() }}));
        """)
    assert _paths(_decode_data_uri(out["href"])) == _expected(_brand_d(f"routes/{route}.svg"))


# ── 2. Every inline copy is the mark (scoped by element) ────────────────────


class _Collect(HTMLParser):
    """Icon links, and the <path>s inside each <svg>, with the classes of the
    elements that contain that <svg> — enough to say *which* svg a path is."""

    def __init__(self):
        super().__init__(convert_charrefs=True)
        self.links, self.svgs, self._stack, self._svg = [], [], [], None

    def handle_starttag(self, tag, attrs):
        a = dict(attrs)
        if tag == "link":
            self.links.append(a)
            return
        if tag == "svg":
            ctx = [(t, c) for t, c in self._stack]
            self._svg = {"attrs": a, "context": ctx, "paths": []}
        elif tag == "path" and self._svg is not None:
            self._svg["paths"].append((a.get("fill"), a.get("fill-rule"), a.get("d")))
        if tag not in ("path", "link", "meta", "br", "img", "input", "line", "rect", "circle", "polyline"):
            self._stack.append((tag, (a.get("class") or "")))

    def handle_endtag(self, tag):
        if tag == "svg" and self._svg is not None:
            self.svgs.append(self._svg)
            self._svg = None
        for i in range(len(self._stack) - 1, -1, -1):
            if self._stack[i][0] == tag:
                del self._stack[i:]
                break


def _parse(path: Path) -> _Collect:
    p = _Collect()
    p.feed(path.read_text(encoding="utf-8"))
    return p


@pytest.mark.parametrize("page", [INDEX, LOGIN, PROJECT_PAGE], ids=lambda p: str(p.relative_to(ROOT)))
def test_the_pages_static_favicon_is_the_mark(page):
    icons = [l for l in _parse(page).links if l.get("rel") == "icon"]
    assert len(icons) == 1, f"{page.name}: expected one <link rel=icon>, found {len(icons)}"
    paths = _paths(_decode_data_uri(icons[0]["href"]))
    assert [d for _, _, d in paths] == [MARK_D], paths


@pytest.mark.parametrize("page,container,klass", [
    (INDEX, "welcome-name", "welcome-boat"),
    (LOGIN, "logo", "logo-mark"),
    (PROJECT_PAGE, "brand", "mark"),
    (PROJECT_PAGE, "hero-logo", None),
], ids=["welcome-screen", "login-card", "project-nav", "project-hero"])
def test_the_title_beside_the_name_is_the_mark(page, container, klass):
    """The welcome screen and the login card — where the showcase saw the boat
    beside *Pantheon* — and the project page's two."""
    svgs = [s for s in _parse(page).svgs
            if any(container in c.split() for _, c in s["context"])]
    if klass:
        svgs = [s for s in svgs if klass in (s["attrs"].get("class") or "").split()]
    assert len(svgs) == 1, f"{page.name}: expected one svg in .{container}, found {len(svgs)}"
    svg = svgs[0]
    assert svg["attrs"].get("viewbox") == "0 0 32 32"
    assert svg["paths"] == [("currentColor", "evenodd", MARK_D)], svg["paths"]
    assert svg["attrs"].get("aria-hidden") == "true", "decorative: the name is the text beside it"


# ── 3. Every branding file something names exists and is what it claims ────


def _notification_icons() -> dict:
    """`icon:` inside each `new Notification(...)` argument list, by file."""
    found = {}
    for js in sorted((STATIC / "js").rglob("*.js")):
        text = js.read_text(encoding="utf-8")
        for m in re.finditer(r"new Notification\(", text):
            depth, i = 1, m.end()
            while depth and i < len(text):
                depth += {"(": 1, ")": -1}.get(text[i], 0)
                i += 1
            icon = re.search(r"\bicon:\s*'([^']+)'", text[m.end():i])
            if icon:
                found.setdefault(icon.group(1), []).append(js.name)
    return found


def _swagger_favicon() -> str:
    import ast

    tree = ast.parse((ROOT / "app.py").read_text(encoding="utf-8"))
    vals = [kw.value.value for node in ast.walk(tree) if isinstance(node, ast.Call)
            for kw in node.keywords if kw.arg == "swagger_favicon_url"]
    assert len(vals) == 1, vals
    return vals[0]


def _referenced_urls() -> dict:
    """URL → who names it."""
    urls = {}
    manifest = json.loads((STATIC / "manifest.json").read_text(encoding="utf-8"))
    for icon in manifest["icons"]:
        urls.setdefault(urljoin("/static/manifest.json", icon["src"]), []).append("manifest.json")
    for page, base in ((INDEX, "/"), (LOGIN, "/login")):
        for link in _parse(page).links:
            if link.get("rel") == "apple-touch-icon":
                urls.setdefault(urljoin(base, link["href"]), []).append(page.name)
    for url, files in _notification_icons().items():
        urls.setdefault(url, []).extend(files)
    urls.setdefault(_swagger_favicon(), []).append("app.py swagger_favicon_url")
    return urls


def test_the_notification_icons_are_found():
    """The collector above must see the four `new Notification` sites, or the
    served-asset test below is checking fewer files than it says."""
    icons = _notification_icons()
    assert sum(len(v) for v in icons.values()) == 4, icons
    assert "/static/favicon.ico" not in icons, "a file this app never had"


def test_every_branding_asset_anything_names_is_served(tmp_path):
    """Fetched through the real app's `/static` mount, out of process (importing
    `app` brings the whole application up — same shape as
    `test_offline_shell_manifest.py`)."""
    urls = _referenced_urls()
    env = os.environ.copy()
    env.update({
        "CHROMADB_CONNECT_TIMEOUT": "0.01",
        "CHROMADB_HOST": "127.0.0.1",
        "CHROMADB_PORT": "9",
        "DATABASE_URL": f"sqlite:///{tmp_path / 'app.db'}",
        "PANTHEON_DATA_DIR": str(tmp_path),
        "PANTHEON_DISABLE_MCP": "1",
        "PYTHONPATH": str(ROOT),
        "PYTHON_DOTENV_DISABLED": "1",
    })
    probe = textwrap.dedent("""
        import io, json, sys
        import app as app_module
        from tests.helpers.signed_in import sign_in
        from fastapi.testclient import TestClient
        from PIL import Image
        client = sign_in(app_module, TestClient(app_module.app))  # the install's admin (`D-2026-10-07-02` §2)
        out = {}
        for url in json.loads(sys.argv[1]):
            r = client.get(url)
            row = {"status": r.status_code, "type": r.headers.get("content-type", "")}
            if r.status_code == 200:
                im = Image.open(io.BytesIO(r.content))
                row["size"] = list(im.size)
            out[url] = row
        print("RESULT=" + json.dumps(out))
    """)
    result = subprocess.run([sys.executable, "-c", probe, json.dumps(sorted(urls))], cwd=str(ROOT),
                            env=env, capture_output=True, text=True, timeout=300, check=False)
    assert result.returncode == 0, result.stderr[-2000:]
    got = json.loads(next(l for l in result.stdout.splitlines() if l.startswith("RESULT="))[7:])
    manifest = {urljoin("/static/manifest.json", i["src"]): i
                for i in json.loads((STATIC / "manifest.json").read_text())["icons"]}
    for url, who in urls.items():
        row = got[url]
        assert row["status"] == 200, f"{url} (named by {who}) answers {row['status']}"
        assert row["type"].startswith("image/"), f"{url} is served as {row['type']}"
        if url in manifest:
            w, h = (int(v) for v in manifest[url]["sizes"].split("x"))
            assert row["size"] == [w, h], f"{url} says {w}x{h} and is {row['size']}"


def test_a_maskable_icon_is_full_bleed_and_an_any_icon_is_not_declared_maskable():
    """A platform crops a maskable icon to its own shape; transparent corners in
    one show through as holes. The rounded tile is `any`; the full-bleed one is
    `maskable`."""
    from PIL import Image

    for icon in json.loads((STATIC / "manifest.json").read_text())["icons"]:
        im = Image.open(STATIC / icon["src"]).convert("RGBA")
        corner = im.getpixel((0, 0))[3]
        if "maskable" in icon["purpose"].split():
            assert corner == 255, f"{icon['src']} is declared maskable and has a transparent corner"
        else:
            assert corner == 0, f"{icon['src']} is the rounded tile and should not fill its corners"


def test_the_windows_build_icon_is_the_multi_size_ico():
    import ast
    from PIL import Image

    spec = ast.parse((ROOT / "Pantheon.spec").read_text(encoding="utf-8"))
    icons = [elt.value for node in ast.walk(spec) if isinstance(node, ast.Call)
             and getattr(node.func, "id", "") == "EXE"
             for kw in node.keywords if kw.arg == "icon" for elt in kw.value.elts]
    ps1 = re.findall(r"--icon=(\S+)", (ROOT / "build-windows-portable.ps1").read_text(encoding="utf-8"))
    assert icons and ps1, (icons, ps1)
    for rel in icons + ps1:
        path = ROOT / rel.replace("\\", "/")
        im = Image.open(path)
        assert sorted(im.ico.sizes()) == [(s, s) for s in (16, 24, 32, 48, 64, 128, 256)], rel


@pytest.mark.skipif(not shutil.which("bash"), reason="bash not on PATH")
def test_the_macos_build_copies_pantheons_icns(tmp_path):
    """Runs the icon block of `build-macos-app.sh` itself (cut at its own section
    markers) against a scratch bundle. It used to crop `docs/pantheon.jpg` — a
    screenshot of upstream's UI — into the app icon (`B71`)."""
    script = (ROOT / "build-macos-app.sh").read_text(encoding="utf-8")
    start, end = script.index("# ── Icon"), script.index("# ── Info.plist ──")
    block = script[start:end]
    app = tmp_path / "Pantheon.app"
    (app / "Contents" / "Resources").mkdir(parents=True)
    run = subprocess.run(["bash", "-c", "set -e\n" + block], capture_output=True, text=True,
                         env={**os.environ, "REPO_DIR": str(ROOT), "APP": str(app)}, timeout=30)
    assert run.returncode == 0, run.stderr
    assert "icon:        pantheon.icns" in run.stdout, run.stdout
    copied = app / "Contents" / "Resources" / "pantheon.icns"
    assert copied.read_bytes() == (BRAND / "pantheon.icns").read_bytes()
    from PIL import Image
    sizes = {s[0] * s[2] for s in Image.open(copied).info["sizes"]}
    assert {32, 64, 128, 256, 512, 1024} <= sizes, sizes


def test_the_tray_draws_the_shipped_icon_not_a_third_drawing():
    from PIL import Image
    from launcher import create_tray_image

    tray = create_tray_image()
    frame = Image.open(STATIC / "icon.ico").ico.getimage((64, 64)).convert("RGBA")
    assert tray.size == (64, 64)
    assert tray.tobytes() == frame.tobytes()


# ── 4. The committed files are what the script draws ────────────────────────


def test_the_brand_files_are_what_make_marks_draws(marks, capsys):
    assert marks.main(["--check"]) == 0, capsys.readouterr().out


def test_check_notices_a_drawing_that_moved(marks, monkeypatch, capsys):
    """`--check` is only evidence if it can fail: move one colour of the tile and
    every file drawn with it must be reported."""
    monkeypatch.setattr(marks, "TILE_FG", "#9cdef3")
    assert marks.main(["--check", "--only", "static/,docs/brand/pantheon-app-icon"]) == 1
    out = capsys.readouterr().out
    for rel in ("static/icon.ico", "static/icons/icon-192.png", "static/icons/icon-512.png",
                "static/icons/icon-maskable-512.png", "docs/brand/pantheon-app-icon.svg"):
        assert rel in out, f"{rel} was drawn with the moved colour and --check missed it"


# ── 5. Upstream's artwork stays out (check-fork-names.py's pixel half) ──────


def test_the_tree_carries_none_of_upstreams_artwork(checker):
    rc, lines = checker.artwork_report()
    assert rc == 0, "\n".join(lines)
    assert "none within" in lines[-1], "the look-alike half must have run here: " + lines[-1]


def test_upstreams_files_are_gone_from_their_shipped_paths(checker):
    gone = ("docs/pantheon.jpg", "docs/pantheon-browser.jpg", "docs/pantheon-wordmark.png")
    assert not [p for p in gone if (ROOT / p).exists()]
    # and the ones replaced in place no longer carry upstream's bytes
    import hashlib
    for rel in ("static/icon.ico", "static/icons/icon-192.png", "static/icons/icon-512.png",
                "static/icons/icon-maskable-512.png"):
        assert hashlib.sha256((ROOT / rel).read_bytes()).hexdigest() not in checker.UPSTREAM_IMAGE_SHA256


@pytest.fixture
def planted(checker, tmp_path, monkeypatch):
    """A scratch tree the checker reads instead of the repository."""
    monkeypatch.setattr(checker, "ROOT", tmp_path)
    return tmp_path


def _boat_like(px=256):
    """A stand-in for upstream's icon (the real bytes are, by design, nowhere in
    the tree): a sail and a hull, drawn here so the test can own its fingerprint."""
    from PIL import Image, ImageDraw

    im = Image.new("RGBA", (px, px), (0, 0, 0, 0))
    d = ImageDraw.Draw(im)
    k = px / 64
    d.polygon([(32 * k, 10 * k), (32 * k, 45 * k), (12 * k, 45 * k)], fill=(224, 108, 117, 255))
    d.polygon([(32 * k, 18 * k), (32 * k, 45 * k), (48 * k, 45 * k)], fill=(224, 108, 117, 150))
    d.polygon([(8 * k, 48 * k), (56 * k, 48 * k), (44 * k, 56 * k), (20 * k, 56 * k)], fill=(224, 108, 117, 255))
    return im


def test_an_exact_copy_under_any_name_is_caught(checker, planted, monkeypatch):
    import hashlib

    (planted / "static").mkdir()
    blob = b"\x89PNG upstream bytes, renamed"
    (planted / "static" / "totally-ours.png").write_bytes(blob)
    (planted / "static" / "ours.png").write_bytes(b"\x89PNG something else")
    monkeypatch.setattr(checker, "UPSTREAM_IMAGE_SHA256", {hashlib.sha256(blob).hexdigest(): "the boat"})
    assert checker.image_offenders(["static/totally-ours.png", "static/ours.png"]) == {
        "static/totally-ours.png": "the boat"}


@pytest.mark.parametrize("how", ["resized", "flattened-on-white-jpeg", "flattened-on-slate-jpeg"])
def test_a_near_copy_is_caught_and_pantheons_mark_is_not(checker, marks, planted, monkeypatch, how):
    from PIL import Image

    original = _boat_like()
    monkeypatch.setattr(checker, "UPSTREAM_IMAGE_DHASH", {
        "boat": tuple(format(h, "016x") for h in checker.dhash(original))})
    if how == "resized":
        original.resize((192, 192), Image.Resampling.LANCZOS).save(planted / "copy.png")
        name = "copy.png"
    else:
        bg = (255, 255, 255, 255) if "white" in how else (40, 44, 52, 255)
        flat = Image.new("RGBA", original.size, bg)
        flat.alpha_composite(original)
        flat.convert("RGB").save(planted / "copy.jpg", quality=60)
        name = "copy.jpg"
    marks.render_tile(512).save(planted / "tile.png")
    marks.render_mark(256, "#e06c75").save(planted / "mark.png")
    found, skipped = checker.image_lookalikes([name, "tile.png", "mark.png"])
    assert skipped is None
    assert set(found) == {name}, found
    assert found[name][0] <= checker.DHASH_MAX_BITS


def test_the_boat_in_code_is_caught_in_the_shape_it_shipped_in(checker, planted):
    """The sail after `'http://www.w3.org/2000/svg'` on one line is how all nine
    copies shipped — and the line a `//`-comment blanker erases from `//www…`
    on. Read raw, so it is seen; spaced path data is seen too."""
    sail = "M16 4L16 22L6 22Z"
    (planted / "a.js").write_text(
        f"fav.href = encodeURIComponent(\"<svg xmlns='http://www.w3.org/2000/svg'><path d='{sail}'/></svg>\");\n")
    (planted / "b.html").write_text('<svg viewBox="0 0 32 32"><path d="M16 4 L16 22 L6 22 Z"/></svg>\n')
    (planted / "c.svg").write_text('<svg><path d="M4 24 Q10 20 16 24"/></svg>')
    (planted / "d.js").write_text(f"const mark = '{MARK_D}';\n")
    found = checker.vector_offenders(["a.js", "b.html", "c.svg", "d.js"])
    assert found == {"a.js": ["upstream's sail"], "b.html": ["upstream's sail"],
                     "c.svg": ["upstream's wave"]}, found


def test_a_file_allowed_to_carry_the_boat_must_still_carry_it(checker, planted, monkeypatch):
    """`VECTOR_ALLOWED` works like the name scan's `ALLOWED`: an excuse for a
    file that no longer needs one fails the run."""
    monkeypatch.setattr(checker, "_tracked_all", lambda: ["gone.js"])
    (planted / "gone.js").write_text("const nothing = 1;\n")
    monkeypatch.setattr(checker, "VECTOR_ALLOWED", {"gone.js": "it used to"})
    rc, lines = checker.artwork_report()
    assert rc == 1 and any("no longer carry" in ln for ln in lines), lines
