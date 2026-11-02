# SPDX-License-Identifier: AGPL-3.0-or-later
"""`B1728`. Kokoro on this server's own processor: a realistic voice with no GPU.

The owner, 2026-11-01: *"Need something for realistic voice synthesis for the
LLM's response back to the user (toggleable)"*, and on the card that followed,
*"Kokoro, plus Chatterbox for a GPU"*. Kokoro-82M (Apache-2.0, weights and
voices) was here already as the `local` provider, through PyTorch with CUDA,
which cannot install on the image's Python (3.14) and needs a GPU besides. This
runs the same model exported to ONNX (`kokoro-v1.0.onnx`, the export the
`kokoro-onnx` project publishes) on ONNX Runtime, which Piper already brings,
and turns text into Kokoro's phonemes with the espeak-ng Piper already carries.
So the image gains two files and no package.

Measured 2026-11-01 on a 4-core x86-64 container: 6.45 s of speech in 2.3 s
(about three times faster than it is spoken), and Whisper `base.en` heard six
test sentences back word for word, the same as the `kokoro-onnx` reference
pipeline on the same model and voice.

What is here:

- the model's phoneme vocabulary (`VOCAB`, from Kokoro-82M's `config.json`);
- the voices this can speak (`VOICES`): American and British English, Spanish,
  French, Hindi, Italian and Brazilian Portuguese. Kokoro's Japanese and
  Mandarin voices are left out: Kokoro learnt them from another phonemizer
  (`misaki`'s), and espeak's phonemes for those languages are not what they
  were trained on;
- where the model is found and how it is fetched (`find_kokoro_files`,
  `ensure_kokoro_files`), behind the same consent as every other model
  (`Law 16`), and checked against the hashes below either way;
- `KokoroEngine`, which speaks: text to phonemes per clause, clauses to batches
  of at most 510 tokens, each batch through the model, and the audio as one
  24 kHz WAV.
"""
from __future__ import annotations

import hashlib
import io
import logging
import os
import re
import tempfile
import threading
import wave
from pathlib import Path
from typing import Callable, Dict, List, NamedTuple, Optional, Tuple

logger = logging.getLogger(__name__)

# The model and its voices, as the `kokoro-onnx` project publishes them for
# Kokoro v1.0 (its GitHub release `model-files-v1.0`). Fetched, or baked into
# the image (`docker/bake_kokoro.py`), only when the bytes hash to these.
KOKORO_RELEASE = "https://github.com/thewh1teagle/kokoro-onnx/releases/download/model-files-v1.0/"
KOKORO_MODEL = "kokoro-v1.0.onnx"
KOKORO_VOICES = "voices-v1.0.bin"
KOKORO_FILES: Dict[str, Tuple[str, int]] = {
    # name: (sha256, size in bytes)
    KOKORO_VOICES: ("bca610b8308e8d99f32e6fe4197e7ec01679264efed0cac9140fe9c29f1fbf7d", 28214398),
    KOKORO_MODEL: ("7d5df8ecf7d4b1878015a32686053fd0eebe2bc377234608764cc0ef3636a6c5", 325532387),
}
# Smaller exports of the same model a person may put in the folder by hand,
# used when the full one is not there: half precision, then 8-bit. Neither is
# fetched or baked; the full model is the one that sounds as Kokoro sounds.
KOKORO_SMALLER = ("kokoro-v1.0.fp16.onnx", "kokoro-v1.0.int8.onnx")

SAMPLE_RATE = 24000
MAX_TOKENS = 510          # the model's context, less the two pad tokens
KOKORO_DEFAULT_VOICE = "af_heart"
_GAP = 0.08               # seconds of silence between two batches of one text

# Kokoro-82M's phoneme vocabulary (`config.json` → `vocab`, Apache-2.0): each
# symbol the model reads and its token. A phoneme outside it is dropped.
VOCAB: Dict[str, int] = {
    ";": 1, ":": 2, ",": 3, ".": 4, "!": 5, "?": 6, "—": 9, "…": 10,
    "\"": 11, "(": 12, ")": 13, "“": 14, "”": 15, " ": 16, "̃": 17, "ʣ": 18,
    "ʥ": 19, "ʦ": 20, "ʨ": 21, "ᵝ": 22, "ꭧ": 23, "A": 24, "I": 25, "O": 31,
    "Q": 33, "S": 35, "T": 36, "W": 39, "Y": 41, "ᵊ": 42, "a": 43, "b": 44,
    "c": 45, "d": 46, "e": 47, "f": 48, "h": 50, "i": 51, "j": 52, "k": 53,
    "l": 54, "m": 55, "n": 56, "o": 57, "p": 58, "q": 59, "r": 60, "s": 61,
    "t": 62, "u": 63, "v": 64, "w": 65, "x": 66, "y": 67, "z": 68, "ɑ": 69,
    "ɐ": 70, "ɒ": 71, "æ": 72, "β": 75, "ɔ": 76, "ɕ": 77, "ç": 78, "ɖ": 80,
    "ð": 81, "ʤ": 82, "ə": 83, "ɚ": 85, "ɛ": 86, "ɜ": 87, "ɟ": 90, "ɡ": 92,
    "ɥ": 99, "ɨ": 101, "ɪ": 102, "ʝ": 103, "ɯ": 110, "ɰ": 111, "ŋ": 112, "ɳ": 113,
    "ɲ": 114, "ɴ": 115, "ø": 116, "ɸ": 118, "θ": 119, "œ": 120, "ɹ": 123, "ɾ": 125,
    "ɻ": 126, "ʁ": 128, "ɽ": 129, "ʂ": 130, "ʃ": 131, "ʈ": 132, "ʧ": 133, "ʊ": 135,
    "ʋ": 136, "ʌ": 138, "ɣ": 139, "ɤ": 140, "χ": 142, "ʎ": 143, "ʒ": 147, "ʔ": 148,
    "ˈ": 156, "ˌ": 157, "ː": 158, "ʰ": 162, "ʲ": 164, "↓": 169, "→": 171, "↗": 172,
    "↘": 173, "ᵻ": 177,
}

# A voice's first letter is its language, and espeak-ng names each language so
# (as the espeak Piper carries spells them: it has no `en-gb` or `fr-fr`
# alias, and `en-gb-x-rp` and `fr` are those languages).
LANGUAGES: Dict[str, Tuple[str, str]] = {
    "a": ("en-us", "American English"),
    "b": ("en-gb-x-rp", "British English"),
    "e": ("es", "Spanish"),
    "f": ("fr", "French"),
    "h": ("hi", "Hindi"),
    "i": ("it", "Italian"),
    "p": ("pt-br", "Brazilian Portuguese"),
}


class KokoroVoice(NamedTuple):
    id: str
    name: str
    language: str
    gender: str

    @property
    def label(self) -> str:
        """How Settings offers it: "Heart · American English, woman"."""
        return f"{self.name} · {self.language}, {self.gender}"


def _voice(vid: str) -> KokoroVoice:
    lang = LANGUAGES[vid[0]][1]
    gender = "woman" if vid[1] == "f" else "man"
    return KokoroVoice(vid, vid.split("_", 1)[1].capitalize(), lang, gender)


# Every voice in `voices-v1.0.bin` this speaks, best first within each
# language as Kokoro's own voice list grades them (Heart and Bella at the top).
VOICES: Tuple[KokoroVoice, ...] = tuple(_voice(v) for v in (
    "af_heart", "af_bella", "af_nicole", "af_aoede", "af_kore", "af_sarah", "af_alloy",
    "af_nova", "af_sky", "af_jessica", "af_river",
    "am_michael", "am_fenrir", "am_puck", "am_echo", "am_eric", "am_liam", "am_onyx",
    "am_adam", "am_santa",
    "bf_emma", "bf_isabella", "bf_alice", "bf_lily",
    "bm_george", "bm_fable", "bm_lewis", "bm_daniel",
    "ef_dora", "em_alex", "em_santa",
    "ff_siwis",
    "hf_alpha", "hf_beta", "hm_omega", "hm_psi",
    "if_sara", "im_nicola",
    "pf_dora", "pm_alex", "pm_santa",
))
_VOICE_IDS = frozenset(v.id for v in VOICES)


def kokoro_voice(voice: str) -> str:
    """The Kokoro voice a stored name means: itself when this speaks it, and
    otherwise the default (the one voice setting is shared by every provider,
    and `alloy` or a Piper name is not a Kokoro voice)."""
    voice = str(voice or "").strip()
    return voice if voice in _VOICE_IDS else KOKORO_DEFAULT_VOICE


def kokoro_dirs() -> List[Path]:
    """Where the model is looked for, in order: the data folder's
    `models/kokoro` (fetched here, or put there by hand), then the image's
    (`PANTHEON_SEED_MODELS/kokoro`, baked by the Dockerfile, read where it
    is), as Piper's voices are found."""
    from src.constants import DATA_DIR
    dirs = [Path(DATA_DIR) / "models" / "kokoro"]
    seed = os.getenv("PANTHEON_SEED_MODELS")
    if seed:
        dirs.append(Path(seed) / "kokoro")
    return dirs


def find_kokoro_files() -> Optional[Tuple[Path, Path]]:
    """`(model, voices)` from the first folder that holds both, or `None`.
    Size is checked here, the hash where the files arrive (fetch or bake): a
    file cut short by a full disk is not a model."""
    for folder in kokoro_dirs():
        voices = folder / KOKORO_VOICES
        if not voices.is_file() or voices.stat().st_size != KOKORO_FILES[KOKORO_VOICES][1]:
            continue
        model = folder / KOKORO_MODEL
        if model.is_file() and model.stat().st_size == KOKORO_FILES[KOKORO_MODEL][1]:
            return model, voices
        for smaller in KOKORO_SMALLER:
            if (folder / smaller).is_file():
                return folder / smaller, voices
    return None


def _sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with open(path, "rb") as f:
        for block in iter(lambda: f.read(1 << 20), b""):
            digest.update(block)
    return digest.hexdigest()


def fetch_kokoro_file(name: str, dest: Path, download: Optional[Callable[[str, str], object]] = None) -> Path:
    """One of `KOKORO_FILES` into `dest`, whole and checked, or an error that
    says which. Fetched beside its place and moved in only once its hash is
    right, so a fetch cut off, or a file that is not the one named, leaves
    nothing behind. `download(url, path)` writes the file; urllib's unless
    given (the caller paces it: `ensure_kokoro_files`)."""
    sha, size = KOKORO_FILES[name]
    if download is None:
        from urllib.request import urlretrieve as download
    dest.mkdir(parents=True, exist_ok=True)
    with tempfile.TemporaryDirectory(dir=str(dest)) as tmp:
        part = Path(tmp) / name
        download(KOKORO_RELEASE + name, str(part))
        got = part.stat().st_size if part.is_file() else 0
        if got != size or _sha256(part) != sha:
            raise ValueError(
                f"The Kokoro file {name} that arrived is not the one Pantheon expects "
                f"({got} bytes, expected {size}); nothing was kept.")
        os.replace(part, dest / name)
    return dest / name


def ensure_kokoro_files() -> Tuple[Path, Path]:
    """`(model, voices)`, or `ModelDownloadNotPermitted` with the sentence a
    person can act on. `Law 16`, the consent Piper, Whisper and FastEmbed ask
    (`model_download_allowed`): the model on disk costs no network; one that
    is not is fetched from the `kokoro-onnx` release on GitHub only when
    someone allowed it. The voices first and the model last: the model is
    found only beside its voices, so a fetch cut off between the two is no
    model."""
    from src.embedding_lanes import ModelDownloadNotPermitted, model_download_allowed

    found = find_kokoro_files()
    if found is not None:
        return found
    dest = kokoro_dirs()[0]
    if not model_download_allowed():
        raise ModelDownloadNotPermitted(
            "Speaking with Kokoro needs its model (about 350 MB), which is not downloaded, "
            "and Pantheon does not fetch models on its own. Turn on “Download models from "
            "the internet” (Settings → System) to fetch it once from the kokoro-onnx "
            f"release on GitHub, or put {KOKORO_MODEL} and {KOKORO_VOICES} in {dest}.")
    from src import paced_http
    for name in (KOKORO_VOICES, KOKORO_MODEL):
        if not (dest / name).is_file() or (dest / name).stat().st_size != KOKORO_FILES[name][1]:
            paced_http.call_sync("github.com", fetch_kokoro_file, name, dest)
    logger.info("Fetched the Kokoro model into %s", dest)
    found = find_kokoro_files()
    if found is None:
        raise RuntimeError(f"The Kokoro model was fetched into {dest} but is not there.")
    return found


# espeak-ng keeps one voice and one state for the whole process, and Piper
# speaks through the same library: two phonemizations at once corrupt each
# other. `services/tts/tts_service.py` holds this lock around Piper too.
ESPEAK_LOCK = threading.Lock()
_espeak_ready = False

_LANG_SWITCH = re.compile(r"\([^)]+\)")


def phonemize(text: str, language: str = "en-us") -> List[str]:
    """Kokoro's phonemes for `text`, one string per clause, each ending in the
    punctuation that ended it. espeak-ng as Piper carries it; what `kokoro-onnx`
    reads from the `phonemizer` package's espeak, with two differences that
    matter to the model: a clause espeak ended with no mark (an ellipsis, a
    dash) is still kept apart from the next, and the palatal mark (ʲ) Piper's
    espeak adds after some vowels is left out, as Kokoro's own phonemizer
    (`misaki`) leaves it out. Symbols outside `VOCAB` are dropped."""
    text = str(text or "").strip()
    if not text:
        return []
    global _espeak_ready
    from piper import espeakbridge
    from piper.phonemize_espeak import ESPEAK_DATA_DIR

    with ESPEAK_LOCK:
        if not _espeak_ready:
            # Once a process, as Piper does it (`EspeakPhonemizer`); again
            # is harmless, and Piper may already have done it.
            espeakbridge.initialize(str(ESPEAK_DATA_DIR))
            _espeak_ready = True
        espeakbridge.set_voice(language)
        clauses = espeakbridge.get_phonemes(text)
    out = []
    for phonemes, terminator, _end in clauses:
        said = _LANG_SWITCH.sub("", phonemes).replace("ʲ", "") + (terminator or "")
        said = " ".join("".join(c for c in said if c in VOCAB).split())
        if said:
            out.append(said)
    return out


def batches(clauses: List[str], limit: int = MAX_TOKENS) -> List[str]:
    """The clauses joined into as few runs of at most `limit` symbols as keep
    each clause whole; a clause longer than that alone is cut at its spaces
    (and a word longer than that, which is not a word, at the limit)."""
    out: List[str] = []
    run = ""
    for clause in clauses:
        pieces = [clause]
        if len(clause) > limit:
            pieces, piece = [], ""
            for word in clause.split(" "):
                while len(word) > limit:
                    if piece:
                        pieces.append(piece)
                        piece = ""
                    pieces.append(word[:limit])
                    word = word[limit:]
                joined = f"{piece} {word}" if piece else word
                if len(joined) > limit:
                    pieces.append(piece)
                    piece = word
                else:
                    piece = joined
            if piece:
                pieces.append(piece)
        for piece in pieces:
            joined = f"{run} {piece}" if run else piece
            if len(joined) > limit:
                if run:
                    out.append(run)
                run = piece
            else:
                run = joined
    if run:
        out.append(run)
    return out


def _wav(audio) -> bytes:
    import numpy as np
    pcm = (np.clip(audio, -1.0, 1.0) * 32767).astype("<i2")
    buf = io.BytesIO()
    with wave.open(buf, "wb") as wf:
        wf.setnchannels(1)
        wf.setsampwidth(2)
        wf.setframerate(SAMPLE_RATE)
        wf.writeframes(pcm.tobytes())
    return buf.getvalue()


class KokoroEngine:
    """The model, loaded once on first use and kept (about 330 MB of memory),
    and its voices. `session_factory(path)` builds the ONNX Runtime session;
    a test's stand-in, or ONNX Runtime on the CPU."""

    def __init__(self, session_factory: Optional[Callable[[str], object]] = None,
                 files: Optional[Callable[[], Tuple[Path, Path]]] = None):
        self._factory = session_factory
        self._files = files or ensure_kokoro_files
        self._session = None
        self._voices = None
        self._inputs: Dict[str, str] = {}
        self._lock = threading.Lock()

    def loaded(self) -> bool:
        return self._session is not None

    def load(self) -> None:
        with self._lock:
            if self._session is not None:
                return
            model, voices = self._files()
            import numpy as np
            if self._factory is not None:
                session = self._factory(str(model))
            else:
                import onnxruntime as rt
                opts = rt.SessionOptions()
                opts.log_severity_level = 3
                session = rt.InferenceSession(str(model), opts, providers=["CPUExecutionProvider"])
            # `allow_pickle=False`: the voices are arrays, and a file that is
            # anything else is refused rather than run.
            self._voices = np.load(str(voices), allow_pickle=False)
            self._inputs = {i.name: i.type for i in session.get_inputs()}
            self._session = session
            logger.info("Kokoro loaded from %s", model)

    def warm(self) -> None:
        try:
            self.load()
        except Exception as e:  # the first sentence asks again and says why
            logger.info("Kokoro not warmed: %s", e)

    def synthesize(self, text: str, voice: str = KOKORO_DEFAULT_VOICE, speed: float = 1.0) -> Optional[bytes]:
        """WAV bytes, or `None` when the text holds nothing to say."""
        import numpy as np
        voice = kokoro_voice(voice)
        language = LANGUAGES[voice[0]][0]
        runs = batches(phonemize(text, language))
        if not runs:
            return None
        self.load()
        style_table = self._voices[voice]
        speed = min(2.0, max(0.5, float(speed or 1.0)))
        tokens_input = "input_ids" if "input_ids" in self._inputs else "tokens"
        gap = np.zeros(int(SAMPLE_RATE * _GAP), dtype=np.float32)
        parts = []
        for run in runs:
            tokens = [VOCAB[c] for c in run if c in VOCAB]
            if not tokens:
                continue
            # One style per length: a run of n tokens reads row n - 1.
            style = np.asarray(style_table[min(len(tokens), len(style_table)) - 1], dtype=np.float32)
            feed = {
                tokens_input: np.array([[0, *tokens, 0]], dtype=np.int64),
                "style": style.reshape(1, -1),
                "speed": np.array([speed], dtype=np.float32),
            }
            audio = np.asarray(self._session.run(None, feed)[0], dtype=np.float32).ravel()
            if parts:
                parts.append(gap)
            parts.append(audio)
        if not parts:
            return None
        return _wav(np.concatenate(parts))
