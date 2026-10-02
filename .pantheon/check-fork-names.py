#!/usr/bin/env python3
# SPDX-License-Identifier: AGPL-3.0-or-later
"""The fork's old short name, in code, with every survivor named.

`P0-31`. `P0-04` renamed 113 browser storage keys and reported *"no `ody-` /
`ody.` keys remain in static/"*, which was true and was not the whole question.
The abbreviated prefix survived in four other shapes, and each one cost
something different:

* **`ody_` on every API token this product minted** — the one string a person
  copies out of Pantheon and pastes into another machine. The row scoped to
  find the residue could not see it: its own regex was `(?i:ody)[-.]`, and the
  separator here is `_`.
* **`ody-agent-` on the tmux session behind the agent's shell** — a name that
  is how running state is *found*, so a bare rename abandons a live shell and
  leaks the process.
* **`html.ody-sidebar-off` in sixteen CSS selectors** whose writers had already
  been renamed, which killed the pre-paint sidebar guard (`B26`).
* **`ody-math-pending` and `ody-session-cost` in test fixtures**, which is how
  five suite failures stood for a fortnight looking like flake.

None of that was a missing rule. It was that nothing ever looked. This is the
looking, and it runs in CI so the next rename cannot half-finish quietly.

**Code, not prose.** A comment or a docstring that explains what the old name
was is worth keeping — deleting the history is how the next person rediscovers
the question from scratch (`Law 1`). So Python is read through `ast` and only
non-docstring string literals and identifiers are considered; JS, CSS and HTML
have their comments stripped first.

**Shipped examples are checked elsewhere and on purpose.** `.env.example`,
`docs/setup.md` and the two integration READMEs print a token prefix to a
first-time reader, and `tests/test_token_prefix_migration.py` fails if any of
them shows the old one — or loses its example rather than updating it, which is
the other way to make a naive grep pass.

Every hit that remains is in `ALLOWED` with a reason. That list is the row's
`Verify:` line, in a form that cannot go stale silently.
"""
import ast
import pathlib
import re
import subprocess
import sys

ROOT = pathlib.Path(__file__).resolve().parent.parent

# The old short name, with every separator it was ever spelled with. `_` is the
# one the row's original regex was missing, and it is where the token prefix
# and the tmux session name both hid.
PATTERN = re.compile(r"(?<![A-Za-z0-9])(?i:ody)[-._]")

# Extensions this reads. Everything else is prose, data, or vendored.
CODE_SUFFIXES = {".py", ".js", ".mjs", ".css", ".html", ".sh"}

SKIP_PREFIXES = (
    ".pantheon/",      # this tracker's own text, and the design mockup
    "static/lib/",     # vendored third-party builds
    "licenses/",       # other people's licence text
    "library/",        # bundled skills — other people's words
)

# path -> why the old name is still there. A migration path that reads the old
# name, or a test that asserts its absence. Nothing else belongs here.
ALLOWED = {
    "core/api_tokens.py":
        "`ACCEPTED_TOKEN_PREFIXES` still honours `ody_`. Every token minted "
        "before 2026-09-07 carries it — in an .env, in a paired phone, in a "
        "scrape config — and dropping it revokes all of them at once.",
    "tests/test_token_prefix_migration.py":
        "The migration's own tests. `LEGACY_PREFIX` is the subject.",
    "tests/test_api_token_routes.py":
        "Stored `token_prefix` values kept at the old spelling on purpose — "
        "they are what a pre-migration row looks like, and sweeping them would "
        "stop exercising the case the migration exists for.",
    "tests/test_root_class_wiring.py":
        "Asserts the old spelling is *absent* from the stylesheets (`B26`).",
    "scripts/pantheon-init.sh":
        "The rename tool itself. Its progress line names both spellings "
        "because naming both is what it does.",
}


def _tracked():
    out = subprocess.run(["git", "ls-files"], cwd=ROOT, capture_output=True,
                         text=True, check=True).stdout
    for rel in out.splitlines():
        if rel.startswith(SKIP_PREFIXES):
            continue
        if pathlib.Path(rel).suffix in CODE_SUFFIXES:
            yield rel


def _python_code(text):
    """Identifiers and non-docstring string literals. Comments and docstrings
    never reach the caller, which is the point."""
    try:
        tree = ast.parse(text)
    except SyntaxError:
        return text  # unparseable: fall back to the whole file rather than pass
    docstrings = set()
    for node in ast.walk(tree):
        body = getattr(node, "body", None)
        if isinstance(node, (ast.Module, ast.ClassDef, ast.FunctionDef, ast.AsyncFunctionDef)):
            if body and isinstance(body[0], ast.Expr) and isinstance(body[0].value, ast.Constant):
                docstrings.add(id(body[0].value))
    parts = []
    for node in ast.walk(tree):
        if isinstance(node, ast.Constant) and isinstance(node.value, str):
            if id(node) not in docstrings:
                parts.append(node.value)
        elif isinstance(node, ast.Name):
            parts.append(node.id)
        elif isinstance(node, ast.Attribute):
            parts.append(node.attr)
        elif isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef, ast.ClassDef)):
            parts.append(node.name)
        elif isinstance(node, ast.arg):
            parts.append(node.arg)
        elif isinstance(node, ast.keyword) and node.arg:
            parts.append(node.arg)
        elif isinstance(node, (ast.Import, ast.ImportFrom)):
            parts.extend(a.name for a in node.names)
            parts.extend(a.asname for a in node.names if a.asname)
            if isinstance(node, ast.ImportFrom) and node.module:
                parts.append(node.module)
    return "\n".join(parts)


def _strip_c_comments(text):
    return re.sub(r"(?m)//.*$", " ", re.sub(r"/\*.*?\*/", " ", text, flags=re.S))


def _code_text(rel, text):
    suffix = pathlib.Path(rel).suffix
    if suffix == ".py":
        return _python_code(text)
    if suffix in {".js", ".mjs"}:
        return _strip_c_comments(text)
    if suffix == ".css":
        return re.sub(r"/\*.*?\*/", " ", text, flags=re.S)
    if suffix == ".html":
        # HTML comments first, then the CSS and JS comments inside <style> and
        # <script>, which is where B26's dead selectors lived.
        return _strip_c_comments(re.sub(r"<!--.*?-->", " ", text, flags=re.S))
    if suffix == ".sh":
        return re.sub(r"(?m)#.*$", " ", text)
    return text


# ── Upstream's artwork, by content (`P0-13`, `B71`) ──────────────────────────
#
# Everything above reads text, and the rename's worst survivor was not text:
# `docs/pantheon.jpg`, `docs/pantheon-browser.jpg`, `docs/pantheon-wordmark.png`,
# `static/icon.ico` and the three PWA icons were upstream's pictures under this
# fork's filenames — a sailing boat, the word *Odysseus*, a screenshot of the
# other product — and the macOS build made its app icon out of one of them. A
# sweep for the old name reported zero while they sat in the tree, because a
# name scan cannot see pixels. So this looks at the pixels, three ways:
#
#   1. **Exact bytes** — the SHA-256 of each image as it shipped here, measured
#      2026-10-02 before `P0-13` replaced them. Catches a copy under any name.
#   2. **Look-alikes** — a 64-bit difference hash of each, flattened on white
#      and on black (a transparent icon's hash depends on what it is flattened
#      onto). A tracked image within `DHASH_MAX_BITS` of any of them fails.
#      Measured: resizing to half, to 256 px or to 512 px moves a hash 0–8 bits;
#      the nearest image actually in the tree on 2026-10-02 was 21 bits away
#      from any fingerprint. Crops and edits are NOT promised — this is a
#      tripwire for a copy, not a detector of derivatives.
#   3. **The inline boat** — upstream's SVG sail and wave were path data pasted
#      into nine places in HTML and JS. The two path signatures are looked for
#      in the RAW text of code and `.svg` files, comments included: the naive
#      blanker above (`B410`) reads `//` inside `'http://www.w3.org/2000/svg'`
#      as a comment and erases the rest of the line — which is exactly where the
#      boat's path data sat in every inline favicon. Measured: the old favicon
#      line passed a comment-stripped scan. Path data has no reason to be in a
#      comment either; a file that must carry it says why in VECTOR_ALLOWED.
#
# `docs/pantheon-wordmark.png` has no fingerprint: it was deleted (`B71`)
# before this existed, and the fork point is not in a shallow clone.

UPSTREAM_IMAGE_SHA256 = {
    "cd5e87b12f1e9e7baca6a6c5e95012130c9e26c6e31526e864eaf17096fcd05e":
        "docs/pantheon.jpg — upstream's UI with Odysseus in the sidebar; was the macOS icon's source",
    "96bc894113d3db1a8e19535047e85fef7bfe7e643d45973d6effb945dce667df":
        "docs/pantheon-browser.jpg — upstream's UI in a browser window",
    "e1bc94b890e95eb5d240b77bac71c287328dbc0d2bd495ae35b36b8293680fc3":
        "static/icon.ico — upstream's red sailing boat, 16 px",
    "d9f54e07d2a8dca6302125d84436176a26a056745c5adb29ef521345c161e359":
        "static/icons/icon-192.png — upstream's red sailing boat",
    "785872b140da58087f23539ed187fe0f69de6eb9690abf995b10c93b5b518388":
        "static/icons/icon-512.png — upstream's red sailing boat",
    "7ed567fe0de6b6b451eec35c8fb2b465d84a3b23945135c19c4fa388ac976449":
        "static/icons/icon-maskable-512.png — upstream's red sailing boat on slate",
}

# name -> difference hashes, hex: one for an opaque image, two (flattened on
# white, on black) for one with transparency. Computed by `dhash()` below.
UPSTREAM_IMAGE_DHASH = {
    "docs/pantheon.jpg": ("0488a68688110100",),
    "docs/pantheon-browser.jpg": ("050105878b343403",),
    "static/icon.ico": ("0872b2e060e4e468", "040d4d1f9e1b1b96"),
    "static/icons/icon-192.png": ("0074b46260e2bc04", "000a4a9d1e1d4302"),
    "static/icons/icon-512.png": ("0074b46260e2bc04", "000a4a9d1e1d4302"),
    "static/icons/icon-maskable-512.png": ("08144a489d0f6618",),
}
DHASH_MAX_BITS = 10

IMAGE_SUFFIXES = {".png", ".jpg", ".jpeg", ".gif", ".ico", ".icns", ".webp", ".bmp"}

# The boat's sail and wave, spaced or not.
UPSTREAM_VECTOR = {
    "upstream's sail": re.compile(r"M\s*16[\s,]+4\s*L\s*16[\s,]+22\s*L\s*6[\s,]+22\s*Z"),
    "upstream's wave": re.compile(r"M\s*4[\s,]+24\s*Q\s*10[\s,]+20[\s,]+16[\s,]+24"),
}


# path -> why it carries upstream's path data. Like ALLOWED above: nothing else.
VECTOR_ALLOWED = {
    "tests/test_pantheon_has_its_own_mark.py":
        "Plants the sail in a scratch tree to prove this scan catches it.",
}

VECTOR_SUFFIXES = CODE_SUFFIXES | {".svg"}


def _tracked_all():
    out = subprocess.run(["git", "ls-files"], cwd=ROOT, capture_output=True,
                         text=True, check=True).stdout
    return [rel for rel in out.splitlines() if rel]


def image_frames(path):
    """Every picture in an image file: each size of an .ico/.icns, else one.
    Read from memory, so no file handle outlives the call."""
    import io
    from PIL import Image

    data = path.read_bytes()
    im = Image.open(io.BytesIO(data))
    if path.suffix.lower() == ".ico":
        return [im.ico.getimage(s) for s in sorted(im.ico.sizes())]
    if path.suffix.lower() == ".icns":
        frames = []
        for s in sorted(im.info.get("sizes", [])):
            one = Image.open(io.BytesIO(data))
            one.size = (s[0] * s[2], s[1] * s[2])
            one.best_size = s
            one.load()
            frames.append(one)
        return frames
    im.load()
    return [im]


def dhash(im):
    """64-bit difference hash: luminance at 9×8, one bit per left>right pair.
    Opaque images hash as they are; anything with alpha is hashed twice, on
    white and on black, because the background decides its luminance."""
    from PIL import Image

    def one(flat):
        g = flat.convert("L").resize((9, 8), Image.Resampling.LANCZOS)
        px = g.tobytes()
        bits = 0
        for r in range(8):
            for c in range(8):
                bits = (bits << 1) | (px[r * 9 + c] > px[r * 9 + c + 1])
        return bits

    rgba = im.convert("RGBA")
    if rgba.getextrema()[3][0] == 255:
        return (one(rgba),)
    out = []
    for bg in ((255, 255, 255, 255), (0, 0, 0, 255)):
        base = Image.new("RGBA", rgba.size, bg)
        base.alpha_composite(rgba)
        out.append(one(base))
    return tuple(out)


def image_offenders(rels):
    """Tracked images that ARE upstream's (exact bytes): {rel: what it is}."""
    import hashlib

    found = {}
    for rel in rels:
        if pathlib.Path(rel).suffix.lower() not in IMAGE_SUFFIXES:
            continue
        try:
            digest = hashlib.sha256((ROOT / rel).read_bytes()).hexdigest()
        except OSError:
            continue
        if digest in UPSTREAM_IMAGE_SHA256:
            found[rel] = UPSTREAM_IMAGE_SHA256[digest]
    return found


def image_lookalikes(rels):
    """Tracked images whose pixels are within DHASH_MAX_BITS of upstream's.

    Returns ({rel: (bits, upstream name)}, None), or ({}, reason) when it could
    not look — Pillow missing — so the caller can say so instead of passing."""
    try:
        import PIL  # noqa: F401
    except ImportError:
        return {}, "Pillow is not installed, so the look-alike half did not run"
    known = [(name, int(h, 16)) for name, pair in UPSTREAM_IMAGE_DHASH.items() for h in pair]
    found = {}
    for rel in rels:
        if pathlib.Path(rel).suffix.lower() not in IMAGE_SUFFIXES:
            continue
        try:
            frames = image_frames(ROOT / rel)
        except Exception as exc:  # an image Pillow cannot open is a finding, not a pass
            found[rel] = (-1, f"unreadable: {exc}")
            continue
        best = None
        for frame in frames:
            for h in dhash(frame):
                for name, ref in known:
                    bits = bin(h ^ ref).count("1")
                    if best is None or bits < best[0]:
                        best = (bits, name)
        if best and best[0] <= DHASH_MAX_BITS:
            found[rel] = best
    return found, None


def vector_offenders(rels):
    """Code and SVG files that carry the boat's path data, read raw: {rel: [names]}.
    Files in VECTOR_ALLOWED are skipped; the caller reports a stale entry."""
    found = {}
    for rel in rels:
        if rel.startswith(SKIP_PREFIXES) or pathlib.Path(rel).suffix not in VECTOR_SUFFIXES:
            continue
        try:
            text = (ROOT / rel).read_text(encoding="utf-8")
        except (OSError, UnicodeDecodeError):
            continue
        hits = [name for name, rx in UPSTREAM_VECTOR.items() if rx.search(text)]
        if hits:
            found[rel] = hits
    return found


def artwork_report():
    """(exit code, lines) for the pixel half."""
    rels = _tracked_all()
    images = [r for r in rels if pathlib.Path(r).suffix.lower() in IMAGE_SUFFIXES]
    exact = image_offenders(rels)
    alike, skipped = image_lookalikes(rels)
    vectors = vector_offenders(rels)
    stale_vec = sorted(set(VECTOR_ALLOWED) - set(vectors))
    vectors = {r: v for r, v in vectors.items() if r not in VECTOR_ALLOWED}
    lines, bad = [], False
    if exact:
        bad = True
        lines.append("Upstream's artwork is in the tree, byte for byte:")
        lines += [f"  {rel}  — {what}" for rel, what in sorted(exact.items())]
    alike = {r: v for r, v in alike.items() if r not in exact}
    if alike:
        bad = True
        lines.append(f"Images within {DHASH_MAX_BITS} bits of upstream's artwork:")
        lines += [f"  {rel}  — {bits} bits from {name}" for rel, (bits, name) in sorted(alike.items())]
    if vectors:
        bad = True
        lines.append("Upstream's boat, as SVG path data in code:")
        lines += [f"  {rel}  — {', '.join(names)}" for rel, names in sorted(vectors.items())]
    if stale_vec:
        bad = True
        lines.append("VECTOR_ALLOWED names files that no longer carry the boat:")
        lines += [f"  {rel}" for rel in stale_vec]
    if bad:
        lines.append("\nP0-13: Pantheon's mark is docs/brand/ (scripts/branding/make_marks.py). "
                     "Use it; do not ship upstream's.")
        return 1, lines
    similarity = (f"none within {DHASH_MAX_BITS} bits of {len(UPSTREAM_IMAGE_DHASH)} fingerprints"
                  if skipped is None else f"NOT CHECKED — {skipped}")
    lines.append(f"upstream artwork OK — {len(images)} tracked images: none is upstream's by "
                 f"hash; look-alikes: {similarity}; no boat path data in code")
    return 0, lines


def _names_main():
    offenders, allowed_hits = {}, {}
    for rel in _tracked():
        try:
            text = (ROOT / rel).read_text(encoding="utf-8")
        except (OSError, UnicodeDecodeError):
            continue
        hits = PATTERN.findall(_code_text(rel, text))
        if not hits:
            continue
        (allowed_hits if rel in ALLOWED else offenders)[rel] = len(hits)

    stale = sorted(set(ALLOWED) - set(allowed_hits))
    if offenders:
        print("The fork's old short name survives in code:\n")
        for rel, n in sorted(offenders.items()):
            print(f"  {n:>3}  {rel}")
        print(
            "\nRename it, or — if it is a migration path that has to read the "
            "old name, or a test asserting its absence — add the file to "
            "ALLOWED in .pantheon/check-fork-names.py with the reason."
        )
        return 1
    if stale:
        print("ALLOWED names files that no longer carry the old name:\n")
        for rel in stale:
            print(f"  {rel}")
        print("\nRemove the entry; an excuse for something that is gone is noise.")
        return 1
    total = sum(allowed_hits.values())
    print(f"fork names OK — {total} deliberate hits across "
          f"{len(allowed_hits)} files, each named")
    for rel, n in sorted(allowed_hits.items()):
        print(f"  {n:>3}  {rel}")
    return 0


def main():
    """Both halves, every run: the old short name in code, then upstream's
    artwork in the tree. One failing does not hide the other's report."""
    rc = _names_main()
    art_rc, art_lines = artwork_report()
    print("\n".join(art_lines))
    return max(rc, art_rc)


if __name__ == "__main__":
    sys.exit(main())
