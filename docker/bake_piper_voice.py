# SPDX-License-Identifier: AGPL-3.0-or-later
"""`B1717`. One Piper voice, baked into the image while it is built.

Fetches `<voice>.onnx`, its `<voice>.onnx.json` and, when the voice has one,
its model card (kept as `<voice>.MODEL_CARD`: where the voice came from and
under what terms) from `rhasspy/piper-voices` on Hugging Face, the place and
layout Piper's own downloader uses, into DEST. The Dockerfile runs it under
`BAKE_MODELS`; a running Pantheon fetches a voice only through
`services/tts/tts_service.py`'s `ensure_piper_voice`, behind the
model-download switch (`Law 16`).

    python bake_piper_voice.py en_US-ljspeech-medium /opt/pantheon/seed-models/piper

Each file is fetched into a scratch folder and moved in whole, the model
before its config: a voice is found only when both are there, so a build cut
off between the two leaves no voice rather than half of one.
"""
from __future__ import annotations

import os
import re
import shutil
import sys
import tempfile

REPO = "rhasspy/piper-voices"
VOICE = re.compile(
    r"^(?P<lang>(?P<family>[a-z]{2,3})_[A-Za-z0-9]{2,4})-(?P<speaker>[A-Za-z0-9_]+)-"
    r"(?P<quality>x_low|low|medium|high)$")


def bake(voice: str, dest: str, fetch=None) -> list[str]:
    """The files written into `dest`. `fetch(repo_id, filename, local_dir)`
    answers a local path; Hugging Face's `hf_hub_download` unless given."""
    named = VOICE.match(voice or "")
    if not named:
        raise ValueError(f"“{voice}” is not a Piper voice name (like en_US-ljspeech-medium).")
    if fetch is None:
        from huggingface_hub import hf_hub_download

        def fetch(repo_id, filename, local_dir):
            return hf_hub_download(repo_id=repo_id, filename=filename, local_dir=local_dir)
    folder = f"{named['family']}/{named['lang']}/{named['speaker']}/{named['quality']}"
    os.makedirs(dest, exist_ok=True)
    written = []
    with tempfile.TemporaryDirectory(dir=dest) as tmp:
        for name in (f"{voice}.onnx", f"{voice}.onnx.json"):
            got = fetch(REPO, f"{folder}/{name}", tmp)
            os.replace(got, os.path.join(dest, name))
            written.append(name)
        try:
            card = fetch(REPO, f"{folder}/MODEL_CARD", tmp)
        except Exception as e:  # a voice without a card is still the voice
            print(f"{voice} has no model card to keep: {e}", file=sys.stderr)
        else:
            shutil.move(card, os.path.join(dest, f"{voice}.MODEL_CARD"))
            written.append(f"{voice}.MODEL_CARD")
    return written


def main(argv: list[str]) -> int:
    if len(argv) != 2:
        print(__doc__, file=sys.stderr)
        return 2
    for name in bake(argv[0], argv[1]):
        print(f"baked {name}")
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
