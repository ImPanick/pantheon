# SPDX-License-Identifier: AGPL-3.0-or-later
"""Screen grounding: every screenshot the agent is shown carries numbered
marks on the things it can click, and the agent clicks a number.
`D-2026-11-01-04`, Phase 1 of the frontier game plan (`G1`–`G4`).

The owner (2026-11-01): *"Those top 3 you selected should be first up"* —
the first being this. A model told "the screen is 1280×800, click at pixels"
has to read coordinates off a picture, which small local models (the owner
drives a 12B) do badly: they see the button and miss it by forty pixels. Shown
the same picture with a box and a number on each control, and a list
`[7] push button “Terminal Emulator” at (568, 776)`, they pick the number —
which they do well — and the click lands in the middle of the control.

**Where marks come from, best first.**

1. `G1` — a page in the agent's browser: the page's own elements, the same
   numbers `agent_browser read` gives (`workstation/browser.py` `READ_FN`), so
   a mark *is* a `ref`.
2. `G2` — the desktop: its accessibility tree, which the apps fill in
   themselves (`workstation/a11y_marks.py`, `ROUTES["marks"]`).
3. `G3` — what neither describes (an app that tells the tree nothing, the
   desktop's icons, a daemon older than the route): read from the picture
   here — text found by Tesseract where the image has it (`apt
   tesseract-ocr`: its English model is the package's own, nothing is
   fetched, `Law 16`) and compact, edge-dense shapes (icons, buttons) found
   with NumPy alone. No neural detector: OmniParser's YOLO weights need
   Torch, which this image does not carry. It is the fallback, and says so —
   its marks are "seen", not described.

**`G4` — what the model is handed.** The screenshot with the marks drawn on
it, and the list in words, so a model that cannot see images at all still
learns what is on the screen and can click by number. `computer` then takes
`"mark": N` wherever it takes a point; the number is looked up in the marks
of the last screenshot *this person's* agent was shown (`remember` /
`resolve`), never another's.

**Off switch.** `ENABLED`, read each call: the grounding evaluation
(`scripts/grounding_eval.py`) turns it off for its "before" runs, so the same
tasks run on the same model with and without marks.
"""
from __future__ import annotations

import base64
import io
import logging
import shutil
import subprocess
import threading
import time
from typing import Any, Dict, List, Optional, Sequence, Tuple

logger = logging.getLogger(__name__)

#: Read each call. Off: screenshots are plain and `mark` is refused.
ENABLED = True

MAX_MARKS = 80
#: The most the picture-reading fallback adds to one screen.
MAX_SEEN = 45
#: How long a screenshot's marks stay clickable by number.
MARKS_TTL_S = 900.0
OCR_TIMEOUT_S = 6.0
NAME_MAX = 60

# Marks' colours: strong, distinct on light and dark, a white number on each.
_PALETTE = ((214, 39, 40), (31, 119, 180), (44, 160, 44), (148, 103, 189), (255, 127, 14),
            (23, 190, 207), (227, 119, 194), (140, 86, 75), (188, 189, 34), (127, 127, 127))

_ROLE_WORDS = {"push button": "button", "toggle button": "button", "tool bar button": "button",
               "page tab": "tab", "menu": "menu", "menu item": "menu item", "check box": "checkbox",
               "radio button": "radio button", "combo box": "dropdown", "text": "text field",
               "entry": "text field", "password text": "password field", "link": "link",
               "list item": "list item", "table cell": "row", "tree item": "tree row",
               "icon": "icon", "spin button": "number field", "slider": "slider",
               "terminal": "terminal", "heading": "heading", "seen-text": "text",
               "seen-shape": "icon or button"}


# ── the marks themselves ─────────────────────────────────────────────────────

def _box_ok(box: Any, width: int, height: int) -> Optional[List[int]]:
    if not isinstance(box, (list, tuple)) or len(box) != 4:
        return None
    try:
        x, y, w, h = (int(round(float(v))) for v in box)
    except (TypeError, ValueError):
        return None
    x, y = max(0, x), max(0, y)
    w, h = min(w, width - x), min(h, height - y)
    if w < 3 or h < 3:
        return None
    return [x, y, w, h]


def normalise(raw: Sequence[Dict[str, Any]], width: int, height: int, source: str) -> List[Dict[str, Any]]:
    """Marks of one shape whatever made them: role, name, box, source."""
    out = []
    for m in raw or []:
        if not isinstance(m, dict):
            continue
        box = _box_ok(m.get("box"), width, height)
        if box is None:
            continue
        mark = {"role": str(m.get("role") or "")[:40],
                "name": " ".join(str(m.get("name") or m.get("label") or "").split())[:NAME_MAX],
                "box": box, "source": source}
        for key in ("app", "ref", "editable", "href", "tag", "type"):
            if m.get(key) not in (None, ""):
                mark[key] = m[key]
        out.append(mark)
    return out


def center(mark: Dict[str, Any]) -> Tuple[int, int]:
    x, y, w, h = mark["box"]
    return x + w // 2, y + h // 2


def _inside(point: Tuple[int, int], box: Sequence[int]) -> bool:
    x, y, w, h = box
    return x <= point[0] < x + w and y <= point[1] < y + h


def _overlap(a: Sequence[int], b: Sequence[int]) -> float:
    """How much of the smaller box the two share, 0 to 1."""
    ax, ay, aw, ah = a
    bx, by, bw, bh = b
    ix = max(0, min(ax + aw, bx + bw) - max(ax, bx))
    iy = max(0, min(ay + ah, by + bh) - max(ay, by))
    small = min(aw * ah, bw * bh) or 1
    return ix * iy / small


def merge(described: List[Dict[str, Any]], seen: List[Dict[str, Any]],
          windows: Sequence[Dict[str, Any]] = ()) -> List[Dict[str, Any]]:
    """Described marks, plus the seen ones that add something: not on top of
    a described mark, nor holding one. A seen mark inside a window the tree
    describes is kept — trees leave things out (Thunar's files in its icon
    view) — so the picture fills the gaps. Numbered in reading order, top to
    bottom and left to right. `windows` is kept for callers that pass it."""
    kept = list(described)
    added = 0
    for s in seen:
        if added >= MAX_SEEN:
            break
        if any(_overlap(s["box"], d["box"]) > 0.4 or _inside(center(d), s["box"])
               for d in kept):
            continue
        kept.append(s)
        added += 1
    kept.sort(key=lambda m: (m["box"][1] // 12, m["box"][0]))
    kept = kept[:MAX_MARKS]
    for n, m in enumerate(kept, 1):
        m["n"] = n
    return kept


# ── `G3`: reading the picture ────────────────────────────────────────────────

def _runs(row) -> List[Tuple[int, int]]:
    import numpy as np
    padded = np.concatenate(([False], row, [False]))
    d = np.diff(padded.astype(np.int8))
    starts = np.flatnonzero(d == 1)
    ends = np.flatnonzero(d == -1)
    return list(zip(starts.tolist(), ends.tolist()))


def _components(mask) -> List[Tuple[int, int, int, int, int]]:
    """Connected parts of a boolean mask, as `(x, y, w, h, pixels)`: runs per
    row joined where they touch the row above (NumPy has no labeller of its
    own and SciPy is not in the image)."""
    parent: List[int] = []

    def find(i: int) -> int:
        while parent[i] != i:
            parent[i] = parent[parent[i]]
            i = parent[i]
        return i

    runs: List[Tuple[int, int, int]] = []  # (row, start, end)
    prev: List[Tuple[int, int, int]] = []  # (start, end, id)
    for y in range(mask.shape[0]):
        cur = []
        for s, e in _runs(mask[y]):
            rid = len(runs)
            runs.append((y, s, e))
            parent.append(rid)
            for ps, pe, pid in prev:
                if ps < e and s < pe:
                    a, b = find(rid), find(pid)
                    if a != b:
                        parent[a] = b
            cur.append((s, e, rid))
        prev = cur
    boxes: Dict[int, List[int]] = {}
    for rid, (y, s, e) in enumerate(runs):
        root = find(rid)
        b = boxes.get(root)
        if b is None:
            boxes[root] = [s, y, e, y + 1, e - s]
        else:
            b[0] = min(b[0], s)
            b[1] = min(b[1], y)
            b[2] = max(b[2], e)
            b[3] = max(b[3], y + 1)
            b[4] += e - s
    return [(x1, y1, x2 - x1, y2 - y1, n) for x1, y1, x2, y2, n in boxes.values()]


def shapes(gray) -> List[Dict[str, Any]]:
    """Compact, edge-dense shapes — icons, buttons, small controls. Long
    thin lines and big outlines (a wallpaper's pattern, a window's border)
    are left out by their size and by how little of their box they fill."""
    import numpy as np
    a = gray.astype(np.int16)
    gx = np.zeros_like(a, dtype=bool)
    gy = np.zeros_like(a, dtype=bool)
    gx[:, 1:] = np.abs(np.diff(a, axis=1)) > 48
    gy[1:, :] = np.abs(np.diff(a, axis=0)) > 48
    edges = gx | gy
    # Close small gaps so an icon's strokes are one part.
    grown = edges.copy()
    for dx in (1, 2):
        grown[:, dx:] |= edges[:, :-dx]
        grown[:, :-dx] |= edges[:, dx:]
    grown2 = grown.copy()
    grown2[1:, :] |= grown[:-1, :]
    grown2[:-1, :] |= grown[1:, :]
    h, w = gray.shape
    out = []
    for x, y, bw, bh, n in _components(grown2):
        if bw < 10 or bh < 10 or bw > 220 or bh > 120:
            continue
        if bw > 6 * bh or bh > 4 * bw:
            continue
        fill = n / float(bw * bh)
        if fill < 0.28:
            continue
        # Edge pixels themselves, not the grown ones: a flat box is not a control.
        own = int(edges[y:y + bh, x:x + bw].sum())
        if own < 0.08 * bw * bh:
            continue
        # A control sits on a quiet ground — a panel, a toolbar, a window's
        # face. A piece of a busy pattern (a wallpaper's lines) does not: the
        # ring around its box is as busy as the box.
        r = 6
        x1, y1 = max(0, x - r), max(0, y - r)
        x2, y2 = min(w, x + bw + r), min(h, y + bh + r)
        ring = int(edges[y1:y2, x1:x2].sum()) - own
        ring_area = (x2 - x1) * (y2 - y1) - bw * bh
        if ring_area > 0 and ring / ring_area > 0.04:
            continue
        out.append({"role": "seen-shape", "name": "", "box": [int(x), int(y), int(bw), int(bh)]})
    return out


def text_lines(png: bytes) -> List[Dict[str, Any]]:
    """Words Tesseract reads on the picture, joined into lines; [] where it is
    not installed or does not answer in time."""
    exe = shutil.which("tesseract")
    if not exe:
        return []
    try:
        done = subprocess.run([exe, "stdin", "stdout", "--psm", "11", "tsv"], input=png,
                              stdout=subprocess.PIPE, stderr=subprocess.DEVNULL,
                              timeout=OCR_TIMEOUT_S, env={"OMP_THREAD_LIMIT": "2", "PATH": "/usr/bin:/bin"})
    except (OSError, subprocess.TimeoutExpired) as e:
        logger.info("screen text not read: %s", type(e).__name__)
        return []
    words = []
    for line in done.stdout.decode("utf-8", "replace").splitlines()[1:]:
        cols = line.split("\t")
        if len(cols) < 12:
            continue
        text = cols[11].strip()
        try:
            conf = float(cols[10])
            x, y, w, h = (int(c) for c in cols[6:10])
        except ValueError:
            continue
        if not text or conf < 60 or not any(ch.isalnum() for ch in text):
            continue
        if len(text) < 3 and conf < 80:
            continue
        if h < 6 or h > 60:
            continue
        words.append([x, y, w, h, text])
    words.sort(key=lambda t: (t[1], t[0]))
    lines: List[List[Any]] = []
    for x, y, w, h, text in words:
        for ln in lines:
            lx, ly, lw, lh, lt = ln
            same_row = abs((y + h / 2) - (ly + lh / 2)) < max(h, lh) * 0.5
            gap = x - (lx + lw)
            if same_row and -2 <= gap <= max(h, lh) * 1.6:
                nx, ny = min(lx, x), min(ly, y)
                ln[:] = [nx, ny, max(lx + lw, x + w) - nx, max(ly + lh, y + h) - ny, f"{lt} {text}"]
                break
        else:
            lines.append([x, y, w, h, text])
    return [{"role": "seen-text", "name": t[:NAME_MAX], "box": [x - 2, y - 2, w + 4, h + 4]}
            for x, y, w, h, t in lines]


def seen(png: bytes) -> List[Dict[str, Any]]:
    """`G3`. What the picture shows that can be clicked: its text lines, and
    the shapes that are not text."""
    try:
        from PIL import Image
        import numpy as np
        img = Image.open(io.BytesIO(png))
        width, height = img.size
        gray = np.asarray(img.convert("L"))
    except Exception as e:  # noqa: BLE001 — a picture that will not open has no marks
        logger.info("screen not read for marks: %s", type(e).__name__)
        return []
    lines = text_lines(png)
    found = list(lines)
    for s in shapes(gray):
        if any(_overlap(s["box"], t["box"]) > 0.3 for t in lines):
            continue
        found.append(s)
    return normalise(found, width, height, "seen")


# ── `G4`: drawing them, and saying them ──────────────────────────────────────

def _font(size: int):
    from PIL import ImageFont
    for path in ("/usr/share/fonts/truetype/dejavu/DejaVuSans-Bold.ttf",
                 "/usr/share/fonts/dejavu/DejaVuSans-Bold.ttf"):
        try:
            return ImageFont.truetype(path, size)
        except OSError:
            continue
    try:
        return ImageFont.load_default(size=size)
    except TypeError:  # an older Pillow
        return ImageFont.load_default()


def draw(png: bytes, marks: Sequence[Dict[str, Any]]) -> Tuple[bytes, str]:
    """The picture with each mark's box outlined and its number on a tag at
    its corner — outside the box where there is room, so the control itself
    stays readable. PNG back; the original on any failure."""
    if not marks:
        return png, "image/png"
    try:
        from PIL import Image, ImageDraw
        img = Image.open(io.BytesIO(png)).convert("RGB")
        overlay = Image.new("RGBA", img.size, (0, 0, 0, 0))
        d = ImageDraw.Draw(overlay)
        font = _font(12)
        width, height = img.size
        for m in marks:
            x, y, w, h = m["box"]
            colour = _PALETTE[(m["n"] - 1) % len(_PALETTE)]
            d.rectangle([x, y, x + w - 1, y + h - 1], outline=colour + (255,), width=2)
            label = str(m["n"])
            tb = d.textbbox((0, 0), label, font=font)
            tw, th = tb[2] - tb[0] + 6, tb[3] - tb[1] + 4
            tx = min(max(0, x), width - tw)
            ty = y - th if y - th >= 0 else min(y + h, height - th)
            if ty + th > height:
                ty = y
            d.rectangle([tx, ty, tx + tw, ty + th], fill=colour + (235,))
            d.text((tx + 3 - tb[0], ty + 2 - tb[1]), label, font=font, fill=(255, 255, 255, 255))
        img = Image.alpha_composite(img.convert("RGBA"), overlay).convert("RGB")
        out = io.BytesIO()
        img.save(out, format="PNG", optimize=False, compress_level=3)
        return out.getvalue(), "image/png"
    except Exception as e:  # noqa: BLE001 — marks not drawn leave the plain picture, and the list
        logger.warning("marks not drawn: %s", e)
        return png, "image/png"


def describe(mark: Dict[str, Any]) -> str:
    role = _ROLE_WORDS.get(mark.get("role") or "", mark.get("role") or "element")
    if mark.get("tag") and not mark.get("role"):
        tag = mark["tag"]
        role = (f"input {mark.get('type') or 'text'}" if tag == "input" else
                {"a": "link", "select": "dropdown", "textarea": "text area",
                 "summary": "toggle"}.get(tag, tag))
    name = f" “{mark['name']}”" if mark.get("name") else ""
    where = f" in {mark['app']}" if mark.get("app") and mark.get("source") == "a11y" else ""
    cx, cy = center(mark)
    seen_note = " (seen)" if mark.get("source") == "seen" else ""
    return f"[{mark['n']}] {role}{name}{where} at ({cx}, {cy}){seen_note}"


def listing(marks: Sequence[Dict[str, Any]], *, verb: str = '"mark": N') -> str:
    if not marks:
        return ""
    lines = [f"Numbered marks on the screenshot (use {verb} instead of x and y):"]
    lines += [describe(m) for m in marks]
    if any(m.get("source") == "seen" for m in marks):
        lines.append("(seen) marks were read from the picture, not described by the app: check the "
                     "screenshot when one matters.")
    return "\n".join(lines)


# ── the last screenshot's marks, per person ─────────────────────────────────

_store: Dict[Tuple[str, str], Dict[str, Any]] = {}
_lock = threading.Lock()


def remember(owner: Optional[str], surface: str, marks: Sequence[Dict[str, Any]]) -> None:
    with _lock:
        _store[(str(owner or ""), surface)] = {"marks": list(marks), "at": time.monotonic()}


def forget(owner: Optional[str], surface: str) -> None:
    with _lock:
        _store.pop((str(owner or ""), surface), None)


def resolve(owner: Optional[str], surface: str, n: Any) -> Tuple[Optional[Dict[str, Any]], Optional[str]]:
    """`(mark, None)`, or `(None, a sentence for the model)`."""
    if isinstance(n, bool) or not isinstance(n, int) or n < 1:
        return None, "“mark” is the number of a mark on the last screenshot, such as 3."
    with _lock:
        held = _store.get((str(owner or ""), surface))
    if not held or time.monotonic() - held["at"] > MARKS_TTL_S:
        return None, "There are no marks to click by number yet: take a screenshot first."
    for m in held["marks"]:
        if m.get("n") == n:
            return m, None
    top = len(held["marks"])
    return None, (f"There is no mark {n} on the last screenshot (it has {top}). Take a screenshot "
                  "and use a number on it." if top else
                  "The last screenshot had no marks: use x and y from it.")


def picture(shot: Dict[str, Any]) -> Optional[bytes]:
    try:
        return base64.b64decode(shot.get("data_b64") or "")
    except (ValueError, TypeError):
        return None


__all__ = ["ENABLED", "MAX_MARKS", "center", "describe", "draw", "forget", "listing", "merge",
           "normalise", "picture", "remember", "resolve", "seen", "shapes", "text_lines"]
