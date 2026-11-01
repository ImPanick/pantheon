# SPDX-License-Identifier: AGPL-3.0-or-later
"""`B1728`. Kokoro's model and voices, baked into the image while it is built.

Fetches `kokoro-v1.0.onnx` (Kokoro-82M exported to ONNX) and `voices-v1.0.bin`
(its voices) from the `kokoro-onnx` project's GitHub release, the files
`services/tts/kokoro_cpu.py` speaks with, into DEST. Each is checked against
the size and SHA-256 that module expects (`KOKORO_FILES`, the one place they
are written) and moved in only when it matches, so a build that fetched
anything else fails rather than baking it. The Dockerfile copies that module
beside this script and runs it under `BAKE_MODELS`; a running Pantheon
fetches the model only through `ensure_kokoro_files`, behind the
model-download switch (`Law 16`).

    python bake_kokoro.py /opt/pantheon/seed-models/kokoro

Kokoro-82M is Apache-2.0, weights and voices (hexgrad/Kokoro-82M);
CREDITS.md says so beside the other voices.
"""
from __future__ import annotations

import sys
from pathlib import Path


def bake(dest: str, fetch=None) -> list[str]:
    """The files written into `dest`, the voices first: the model is found
    only beside them. `fetch(name, folder)` is `kokoro_cpu.fetch_kokoro_file`
    unless given."""
    import kokoro_cpu

    if fetch is None:
        fetch = kokoro_cpu.fetch_kokoro_file
    folder = Path(dest)
    written = []
    for name in (kokoro_cpu.KOKORO_VOICES, kokoro_cpu.KOKORO_MODEL):
        fetch(name, folder)
        written.append(name)
    return written


def main(argv: list[str]) -> int:
    if len(argv) != 1:
        print(__doc__, file=sys.stderr)
        return 2
    for name in bake(argv[0]):
        print(f"baked {name}")
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
