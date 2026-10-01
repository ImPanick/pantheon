# SPDX-License-Identifier: AGPL-3.0-or-later
"""What the showcase writes, how small it must be, and how it gets there.

**Budgets live here and nowhere else** (`Law 7`). `tests/test_the_showcase_pipeline.py`
imports them to check every image the README shows, so the number a reviewer
reads in this file is the number CI enforces.

**PNG.** A screenshot of this UI is flat colour and anti-aliased text, so a
256-colour palette usually holds it with no visible change. Each one is
quantised (median cut, no dither) and kept only if the palette version is still
within `PNG_MIN_PSNR` dB of the capture — measured across this pipeline's
screens: 42–57 dB, at about half the size. One that falls below stays lossless
(the light Theme window sits at the line, and has gone both ways between runs).

**GIF.** Frames are screenshots, one per GIF frame (`scenes.Recorder`), so a
scene that does the same thing makes the same frames. ffmpeg scales them to
`GIF_WIDTH` with Lanczos and makes the GIF in two passes — a palette built from
what changes between frames, then that palette applied with only the changed
rectangle re-encoded per frame — which is what keeps a mostly-still UI
recording small.

**Churn.** Regenerating must not rewrite a picture nobody would see change: the
clock in a footer moves every run. A new PNG that differs from the committed
one in fewer than `CHURN_PIXELS` of its pixels is not written, and a GIF with
the same frame count that opens and closes on the same picture is not either —
so a release-day run commits only what really moved. A GIF that waits
on the product (the live agent turn) makes a different number of frames each
run and is always rewritten. `--force` rewrites everything.
"""
from __future__ import annotations

import io
import math
import os
import shutil
import subprocess
import tempfile
from pathlib import Path
from typing import List, Optional, Sequence, Tuple

# ── budgets (the test reads these) ──────────────────────────────────────────
PNG_BUDGET = 400 * 1024            # bytes, per screenshot
GIF_BUDGET = 3 * 1024 * 1024       # bytes, per animation
TOTAL_BUDGET = 15 * 1024 * 1024    # bytes, everything in docs/media

# ── encoding ────────────────────────────────────────────────────────────────
PNG_MIN_PSNR = 42.0                # dB; below this the palette version is not kept
GIF_FPS = 12
GIF_WIDTH = 900
CHURN_PIXELS = 0.004               # fraction of pixels that may differ and still count as unchanged
# A GIF's palette is built from all its frames, so one changed frame shifts the
# colours of every other a little; a GIF pixel counts as changed past this.
GIF_LEVEL = 40


def _pil():
    try:
        from PIL import Image, ImageChops, ImageStat  # noqa: F401
        return Image, ImageChops, ImageStat
    except ImportError:  # the pipeline still runs; PNGs are written as captured
        return None


def psnr(a, b) -> float:
    Image, ImageChops, ImageStat = _pil()
    diff = ImageChops.difference(a.convert("RGB"), b.convert("RGB"))
    mse = sum(v * v for v in ImageStat.Stat(diff).rms) / 3
    return 99.0 if mse == 0 else 10 * math.log10(255 * 255 / mse)


def optimise_png(raw: bytes) -> Tuple[bytes, str]:
    """The smallest faithful PNG of `raw`, and how it was made."""
    pil = _pil()
    if pil is None:
        return raw, "as captured (Pillow missing)"
    Image = pil[0]
    src = Image.open(io.BytesIO(raw)).convert("RGB")
    lossless = io.BytesIO()
    src.save(lossless, "PNG", optimize=True)
    best, how = lossless.getvalue(), "lossless"
    q = src.quantize(colors=256, method=Image.Quantize.MEDIANCUT, dither=Image.Dither.NONE)
    score = psnr(src, q)
    if score >= PNG_MIN_PSNR:
        pal = io.BytesIO()
        q.save(pal, "PNG", optimize=True)
        if len(pal.getvalue()) < len(best):
            best, how = pal.getvalue(), f"256 colours, {score:.1f} dB"
    return best, how


def changed_fraction(old: Path, new_bytes: bytes, level: int = 8) -> Optional[float]:
    """Fraction of pixels that differ by more than `level` in some channel, or
    None if it cannot be compared."""
    pil = _pil()
    if pil is None or not old.exists():
        return None
    Image, ImageChops, _ = pil
    try:
        a = Image.open(old).convert("RGB")
        b = Image.open(io.BytesIO(new_bytes)).convert("RGB")
    except Exception:
        return None
    if a.size != b.size:
        return 1.0
    diff = ImageChops.difference(a, b).convert("L").point(lambda v: 255 if v > level else 0)
    hist = diff.histogram()
    return hist[255] / float(a.size[0] * a.size[1])


def write_png(path: Path, raw: bytes, force: bool = False) -> str:
    """Optimise and write, unless the committed file already shows the same."""
    data, how = optimise_png(raw)
    frac = changed_fraction(path, data)
    if not force and frac is not None and frac < CHURN_PIXELS:
        return f"kept (changed {frac:.2%} of pixels)"
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_bytes(data)
    moved = "" if frac is None else f", {frac:.2%} of pixels changed"
    return f"{how}, {len(data) // 1024} KB{moved}"


# ── GIFs ────────────────────────────────────────────────────────────────────

def _ffmpeg() -> str:
    exe = shutil.which("ffmpeg")
    if not exe:
        raise RuntimeError("ffmpeg is not on PATH; it makes the GIFs (any 4.x or later)")
    return exe


def encode_gif(frames: Sequence[Tuple[float, bytes]], out: Path, *, fps: int = GIF_FPS,
               width: int = GIF_WIDTH, colors: int = 192, tail: float = 1.2,
               force: bool = False) -> str:
    """`frames` is `[(seconds since start, png bytes), …]`."""
    if len(frames) < 2:
        raise ValueError("a GIF needs at least two frames")
    ff = _ffmpeg()
    with tempfile.TemporaryDirectory(prefix="showcase-gif-") as tmp:
        tmpd = Path(tmp)
        lines: List[str] = []
        for i, (t, png) in enumerate(frames):
            name = f"f{i:05d}.png"
            (tmpd / name).write_bytes(png)
            nxt = frames[i + 1][0] if i + 1 < len(frames) else t + tail
            lines.append(f"file '{name}'")
            lines.append(f"duration {max(nxt - t, 0.001):.4f}")
        lines.append(f"file 'f{len(frames) - 1:05d}.png'")  # concat needs the last one twice
        (tmpd / "list.txt").write_text("\n".join(lines) + "\n")
        scale = f"fps={fps},scale={width}:-2:flags=lanczos"
        palette = tmpd / "palette.png"
        subprocess.run([ff, "-y", "-loglevel", "error", "-f", "concat", "-safe", "0",
                        "-i", str(tmpd / "list.txt"),
                        "-vf", f"{scale},palettegen=max_colors={colors}:stats_mode=diff",
                        str(palette)], check=True)
        gif = tmpd / "out.gif"
        subprocess.run([ff, "-y", "-loglevel", "error", "-f", "concat", "-safe", "0",
                        "-i", str(tmpd / "list.txt"), "-i", str(palette),
                        "-lavfi", f"{scale}[x];[x][1:v]paletteuse=dither=bayer:bayer_scale=5:diff_mode=rectangle",
                        "-loop", "0", str(gif)], check=True)
        data = gif.read_bytes()
    why = _gif_difference(out, data)
    if not force and why is None:
        return "kept (same frames, same first and last picture)"
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_bytes(data)
    return f"{len(frames)} frames, {len(data) // 1024} KB ({why or 'forced'})"


def _gif_difference(old: Path, new: bytes) -> Optional[str]:
    """None when the GIF has as many frames and opens and closes on the same
    picture; otherwise what differs.

    Not every frame: a step the product animates (a window sliding in, an
    arrow redrawn) lands a frame earlier or later from run to run, and that
    jitter is not a change anybody would see in the loop. What a person
    would see — a different label, a moved control — is on the screen the
    GIF opens and closes on, where every scene holds still.
    """
    pil = _pil()
    if pil is None or not old.exists():
        return "no committed GIF to compare"
    Image = pil[0]
    try:
        a, b = Image.open(old), Image.open(io.BytesIO(new))
        if a.n_frames != b.n_frames or a.size != b.size:
            return f"{a.n_frames} → {b.n_frames} frames"
        for label, i in (("first", 0), ("last", a.n_frames - 1)):
            a.seek(i)
            b.seek(i)
            buf = io.BytesIO()
            b.convert("RGB").save(buf, "PNG")
            fd, name = tempfile.mkstemp(suffix=".png")
            os.close(fd)
            try:
                a.convert("RGB").save(name)
                frac = changed_fraction(Path(name), buf.getvalue(), level=GIF_LEVEL)
            finally:
                os.unlink(name)
            if frac is None or frac >= CHURN_PIXELS:
                return f"{label} frame changed {frac:.2%}" if frac is not None else f"{label} frame unreadable"
        return None
    except Exception as e:  # a GIF that cannot be read is a GIF to rewrite
        return f"unreadable ({e.__class__.__name__})"


def sizes(directory: Path) -> List[Tuple[str, int]]:
    return sorted((p.name, p.stat().st_size) for p in directory.iterdir()
                  if p.is_file() and p.suffix in (".png", ".gif"))
