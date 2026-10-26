# SPDX-License-Identifier: AGPL-3.0-or-later
"""The Real-ESRGAN closure the image builds and CI audits, read where it is pinned.

`B373`. The Forge's *Install* button for Real-ESRGAN used to run a plain
`pip install realesrgan` on the user's machine, after CI had finished: an
unpinned resolve whose dependency tree no scanner ever saw, and the one path by
which a `basicsr` other than the audited 1.4.2 could land in a deployment. The
pins live in exactly one place — `docker/build-realesrgan-wheels.sh`, whose
`SPECS` line the image builds wheels from and `.pantheon/audit-dependencies.py`
audits — so this module *reads* them there (`Law 7`: no second copy to drift),
and the Forge installs the same closure.

Standard library only: `.pantheon/audit-dependencies.py` loads this file by
path in CI, where the app's dependencies are not installed.
"""

from __future__ import annotations

import re
from pathlib import Path

WHEEL_SCRIPT = Path(__file__).resolve().parent.parent / "docker" / "build-realesrgan-wheels.sh"


def _line(text: str, var: str) -> list[str]:
    m = re.search(rf'^{var}="([^"]+)"', text, re.M)
    if not m:
        return []
    return [s for s in m.group(1).split() if "==" in s]


def read_pins(path: Path | None = None) -> dict[str, list[str]]:
    """``{"runtime": [...], "wheels": [...]}`` out of the wheel build script.

    ``wheels`` is the `SPECS` line (basicsr, gfpgan, facexlib — built from
    patched sdists because their `setup.py` cannot run on Python 3.13+);
    ``runtime`` is `RUNTIME_SPEC`, the Real-ESRGAN release those pins are for.
    Both empty when the script cannot be read.
    """
    path = Path(path) if path is not None else WHEEL_SCRIPT
    try:
        text = path.read_text(encoding="utf-8")
    except OSError:
        return {"runtime": [], "wheels": []}
    return {"runtime": _line(text, "RUNTIME_SPEC"), "wheels": _line(text, "SPECS")}


def realesrgan_install_spec(path: Path | None = None) -> str | None:
    """The space-separated pip arguments the Forge installs Real-ESRGAN with.

    ``None`` when the pins cannot be read (a bundle that left the build script
    out): the caller says so rather than falling back to an unpinned resolve.
    """
    pins = read_pins(path)
    if not pins["runtime"] or not pins["wheels"]:
        return None
    return " ".join(pins["runtime"] + pins["wheels"])
