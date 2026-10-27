# SPDX-License-Identifier: AGPL-3.0-or-later
"""`B1167` — every recording in `docs/` is one a page shows, and none is
upstream's interface.

Eight clips — `docs/bg.webm`, `chat.webm`, `compare.webm`, `document.webm`,
`gallery.webm`, `notes.webm`, `research.webm`, `theme.webm`, ≈6.4 MB — were the
old landing page's previews, recorded in Odysseus: a frame of `chat.webm` at 2 s
(looked at again on 2026-10-27) shows *Odysseus* in the sidebar and *Message
Odysseus…* in the composer. The rewritten page (`B1150`) shows `docs/media/`
instead, so nothing referenced them but `scripts/encode_previews.sh`, the
encoder that made them into `docs/`. `D-2026-10-02-03` §2 covers upstream's
artwork wherever it ships, and `check-fork-names.py`'s pixel half reads images,
not video, so it never saw these. Deleted, with the encoder; their fingerprints
are below so the next person can tell them if they come back.
"""
import hashlib
import re
import subprocess
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
MOVING = {".webm", ".mp4", ".mov", ".gif", ".apng"}

# sha256 of each deleted clip, as it stood at `9297d85a`.
UPSTREAM_RECORDINGS = {
    "157f732539a6072d55164da23d65afa9423782728dd067154867fcebb176fb35": "docs/bg.webm",
    "d69f319192cec2cac1831e08ee99ae902398f1b163021e42b3fda05a0d7ab4d5": "docs/chat.webm",
    "90d8c68dbc2ac3029b258598a7e2c2c5c8f5d6d702b9d31f0c729e5517093f51": "docs/compare.webm",
    "754e4ae071e9def5151749a03ad284cd41385354620fc8afea3c5c4f50f64a0d": "docs/document.webm",
    "b3bbe99c55b5cd1de32cb8e84fa31044761b7724a76a4bae4d4b0acaed7f3500": "docs/gallery.webm",
    "2a82b501271c4b60927e575bb22f8c986e3d1a4089a5518f84b46e534dea37d7": "docs/notes.webm",
    "2495a1a6cc1ea037f7460d065e3af6aacf091b240edebc436ce4bca5e83dab87": "docs/research.webm",
    "6bd5a4140e9eeb9e06bee217319d331e9c8c873763fcb9040425fb38878b8410": "docs/theme.webm",
}


def _tracked() -> list:
    out = subprocess.run(["git", "ls-files"], cwd=ROOT, capture_output=True, text=True).stdout.split()
    return out or [p.relative_to(ROOT).as_posix() for p in ROOT.rglob("*")
                   if p.is_file() and "venv" not in p.parts and ".git" not in p.parts]


def _moving_pictures() -> list:
    return [rel for rel in _tracked()
            if rel.startswith("docs/") and Path(rel).suffix.lower() in MOVING]


def _pages() -> str:
    """Every page that can show a picture: the docs site and the markdown."""
    texts = []
    for rel in _tracked():
        if rel.startswith(("tests/", ".pantheon/")) or Path(rel).suffix.lower() not in {".html", ".md"}:
            continue
        try:
            texts.append((rel, (ROOT / rel).read_text(encoding="utf-8")))
        except (OSError, UnicodeDecodeError):
            continue
    return texts


def test_every_moving_picture_in_docs_is_shown_by_a_page():
    pages = _pages()
    unshown = []
    for rel in _moving_pictures():
        under_docs = rel[len("docs/"):]
        shown = any(re.search(rf"(?<![\w/.-])(?:docs/)?{re.escape(under_docs)}\b", text)
                    for page, text in pages)
        if not shown:
            unshown.append(rel)
    assert _moving_pictures(), "the scan found no moving picture at all — it is reading nothing"
    assert unshown == [], unshown


def test_no_upstream_recording_is_shipped_again():
    found = {}
    for rel in _tracked():
        path = ROOT / rel
        if Path(rel).suffix.lower() not in MOVING or not path.is_file():
            continue
        digest = hashlib.sha256(path.read_bytes()).hexdigest()
        if digest in UPSTREAM_RECORDINGS:
            found[rel] = UPSTREAM_RECORDINGS[digest]
    assert found == {}, found


def test_the_encoder_that_wrote_them_is_gone_too():
    """It wrote `docs/<name>.webm` and `.mp4` — the place the landing page no
    longer reads; the pictures it shows are `scripts/showcase/capture.py`'s."""
    assert not (ROOT / "scripts" / "encode_previews.sh").exists()
