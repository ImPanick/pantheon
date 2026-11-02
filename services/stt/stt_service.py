# SPDX-License-Identifier: AGPL-3.0-or-later
# services/stt/stt_service.py
"""Multi-provider Speech-to-Text service — dispatches to local Whisper, OpenAI-compatible API, or browser."""

import io
import logging
import os
import re
import httpx
import tempfile
import threading
from pathlib import Path
from typing import Optional, Dict, Any, Tuple

logger = logging.getLogger(__name__)


# `B1716`. The extension each container goes up as, by the names an
# OpenAI-compatible `/audio/transcriptions` reads the format from (flac, mp3,
# mp4, mpeg, mpga, m4a, ogg, wav, webm); a name outside that list is uploaded
# under the one inside it that is the same container.
_AUDIO_EXTENSIONS = {
    "wav": ("wav", "audio/wav"), "wave": ("wav", "audio/wav"),
    "ogg": ("ogg", "audio/ogg"), "oga": ("ogg", "audio/ogg"), "opus": ("ogg", "audio/ogg"),
    "flac": ("flac", "audio/flac"),
    "webm": ("webm", "audio/webm"), "weba": ("webm", "audio/webm"),
    "m4a": ("m4a", "audio/mp4"), "mp4": ("mp4", "audio/mp4"),
    "mp3": ("mp3", "audio/mpeg"), "mpga": ("mp3", "audio/mpeg"), "mpeg": ("mp3", "audio/mpeg"),
}


def sniff_audio_format(data: bytes, filename: str = "") -> Tuple[str, str]:
    """`B1716`. What a recording is, read from its first bytes: `(extension,
    mime)`. When the bytes say nothing, the name it came with is asked
    (`filename`), and then `("webm", "audio/webm")` — the format the chat's
    recorder made before it learned WAV, kept as the guess.

    An OpenAI-compatible `/audio/transcriptions` decides the format by the
    file's NAME, and every recording went up as `audio.webm`: the voice call's
    WAV, a Safari recording (MP4/AAC) and an attached MP3 voice note were each
    refused as *Invalid file format* by a server that reads all three. Local
    Whisper decodes by content (PyAV), so the name only has to be honest."""
    head = bytes(data[:16]) if data else b""
    if head[:4] == b"RIFF" and head[8:12] == b"WAVE":
        return "wav", "audio/wav"
    if head[:4] == b"OggS":
        return "ogg", "audio/ogg"
    if head[:4] == b"fLaC":
        return "flac", "audio/flac"
    if head[:4] == b"\x1aE\xdf\xa3":
        return "webm", "audio/webm"
    if head[4:8] == b"ftyp":
        return "m4a", "audio/mp4"
    # An MPEG audio frame: eleven sync bits, then a layer that is not `00`
    # (`00` is AAC's ADTS, which no endpoint takes by an MP3's name).
    if head[:3] == b"ID3" or (len(head) >= 2 and head[0] == 0xFF and (head[1] & 0xE0) == 0xE0
                              and (head[1] & 0x06) != 0):
        return "mp3", "audio/mpeg"
    ext = os.path.splitext(str(filename or ""))[1].lstrip(".").lower()
    return _AUDIO_EXTENSIONS.get(ext, ("webm", "audio/webm"))


def _installed(module: str) -> bool:
    """`B1716`. Whether `module` can be imported, asked without importing it:
    faster-whisper's import pulls in CTranslate2 and PyAV, seconds of work a
    status read should not do. A module already imported (a test's stand-in
    among them) is installed."""
    import importlib.util
    import sys
    if sys.modules.get(module) is not None:
        return True
    try:
        return importlib.util.find_spec(module) is not None
    except (ImportError, ValueError):
        return False


def _cuda_devices() -> int:
    """`B1716`. CUDA devices CTranslate2 (faster-whisper's engine) can use.

    It was asked of torch, which the image does not install, so a GPU passed
    into the container (`docker-compose.gpu-nvidia.yml`) was never used for
    speech; CTranslate2 answers for itself. Any failure is no GPU."""
    try:
        import ctranslate2
        return int(ctranslate2.get_cuda_device_count())
    except Exception:
        return 0


# `B1716`. Whisper built on the GPU and run on a second of silence, in a child
# process. CTranslate2 counts a CUDA device whenever the driver is passed into
# the container, and the image carries no cuBLAS or cuDNN: the model then
# loads, and the first recording either raises or — cuDNN missing — aborts the
# process it runs in. In the child, that abort costs the child.
_CUDA_PROBE = (
    "import sys\n"
    "import numpy\n"
    "from faster_whisper import WhisperModel\n"
    "model = WhisperModel(sys.argv[1], device='cuda', compute_type='float16')\n"
    "segments, _ = model.transcribe(numpy.zeros(16000, dtype=numpy.float32),"
    " beam_size=1, vad_filter=False)\n"
    "list(segments)\n"
)
_cuda_verdict: Optional[bool] = None


def _whisper_runs_on_cuda(source: str) -> bool:
    """`B1716`. Whether Whisper transcribes on this machine's GPU, asked once
    per process (`_CUDA_PROBE`). Any failure — an exception, an abort, two
    minutes without an answer — is *no*, and speech-to-text runs on the CPU."""
    global _cuda_verdict
    if _cuda_verdict is None:
        import subprocess
        import sys
        try:
            done = subprocess.run([sys.executable, "-c", _CUDA_PROBE, str(source)],
                                  capture_output=True, timeout=120)
            _cuda_verdict = done.returncode == 0
            if not _cuda_verdict:
                tail = (done.stderr or b"").decode("utf-8", "replace").strip().splitlines()[-3:]
                logger.warning("Whisper will not run on the GPU here (exit %s): %s",
                               done.returncode, " | ".join(tail) or "no output")
        except Exception as e:
            logger.warning("Whisper will not run on the GPU here: %s", e)
            _cuda_verdict = False
    return _cuda_verdict


def whisper_seed_dir(model_size: str) -> Optional[str]:
    """`B1716`. The Whisper model the image carries for `model_size`, when it
    carries one: `$PANTHEON_SEED_MODELS/whisper/<size>`, baked by the
    Dockerfile in CTranslate2's format (`model.bin` beside its config) and
    read where it is, never copied. `None` off the image, or for a size it
    was not baked with."""
    seed = os.getenv("PANTHEON_SEED_MODELS")
    name = str(model_size or "base")
    if not seed or not re.fullmatch(r"[A-Za-z0-9][A-Za-z0-9._-]*", name):
        return None
    folder = os.path.join(seed, "whisper", name)
    if os.path.isfile(os.path.join(folder, "model.bin")) and os.path.isfile(os.path.join(folder, "config.json")):
        return folder
    return None


def ensure_whisper_download_permitted(model_size: str) -> str:
    """What to build the local Whisper model from, or `ModelDownloadNotPermitted`.

    `B1565`. `WhisperModel("base")` resolves the name through Hugging Face —
    it fetches the model the first time, and asks the Hub again on later runs —
    and it was called with no question asked, while FastEmbed's construction of
    the same kind of thing asks `ensure_fastembed_download_permitted`. One
    consent (`model_download_allowed`, the `allow_model_download` switch and
    `PANTHEON_ALLOW_MODEL_DOWNLOAD`), two models it governs; `Law 16`.

    Answers the name itself when fetching is allowed, or when the name is
    already a folder on disk (a path costs no network). Otherwise it looks in
    the local cache *with the network off* (`local_files_only`) and answers
    the cached folder, so the constructor is handed a path and never reaches
    the Hub; with nothing cached it raises with the sentence a person can act
    on. `tests/test_the_model_download_gate_has_one_door.py` fails on a
    `WhisperModel(...)` built anywhere this is not asked.
    """
    from src.embedding_lanes import ModelDownloadNotPermitted, model_download_allowed

    name = str(model_size or "base")
    if os.path.isdir(name):
        return name
    # `B1716`. The model the image carries costs no network, allowed or not.
    seeded = whisper_seed_dir(name)
    if seeded:
        return seeded
    if model_download_allowed():
        return name
    try:
        from faster_whisper.utils import download_model
        return download_model(name, local_files_only=True)
    except Exception:
        raise ModelDownloadNotPermitted(
            f"Local speech-to-text needs the Whisper “{name}” model, which is not downloaded, "
            "and Pantheon does not fetch models on its own. Turn on “Download models from the "
            "internet” (Settings → System) to fetch it from Hugging Face once, or choose a "
            "speech-to-text endpoint in Settings instead."
        ) from None


def _said(error: BaseException) -> str:
    """`B1579`. An exception as a clause in a sentence: its first line,
    trimmed, or its type when it has no words of its own."""
    text = str(error).strip().splitlines()[0].strip() if str(error).strip() else ""
    text = text.rstrip(".")
    if len(text) > 160:
        text = text[:157].rstrip() + "…"
    return text or type(error).__name__


class STTService:
    """Multi-provider STT service.

    Reads provider config from data/settings.json on each call.
    Providers:
      "disabled"        — no STT
      "browser"         — client-side Web Speech API (no server transcription)
      "local"           — faster-whisper on CPU/GPU
      "endpoint:<id>"   — OpenAI-compatible /audio/transcriptions via ModelEndpoint
    """

    def __init__(self):
        self._whisper_model = None  # lazy-init
        # `B1565`. Why local Whisper is not available, in a person's words —
        # the download gate's refusal. Cleared on the next attempt, so turning
        # the switch on is enough; nothing is remembered as refused.
        self._whisper_refusal: Optional[str] = None
        # `B1579`. Why the last attempt turned a recording into no words, past
        # the download gate: Whisper not installed or would not load, or the
        # last transcription raised (`_transcribe_local`, `_transcribe_api`).
        # Each attempt rewrites it, so it is about the last recording asked.
        self._whisper_failure: Optional[str] = None
        self._transcribe_failure: Optional[str] = None
        # `B1716`. One load at a time: a voice call's warm-up and its first
        # recording can both ask for the model, and two `WhisperModel`s of the
        # same size were built side by side, each holding the RAM of one.
        self._load_lock = threading.Lock()
        self._loading = False
        self._device: Optional[str] = None
        # The size the loaded model was built for. A size changed in Settings
        # kept the first one until a restart; now the next use loads the new.
        self._loaded_size: Optional[str] = None
        # The size whose load failed (`_whisper_failure`), so a status read
        # does not try it again on every poll; a recording still does.
        self._failed_size: Optional[str] = None

    # ── Settings ──

    def _load_settings(self) -> dict:
        from src.settings import load_settings
        saved = load_settings()
        return {
            "stt_enabled": saved.get("stt_enabled", False),
            "stt_provider": saved.get("stt_provider", "disabled"),
            "stt_model": saved.get("stt_model", "base"),
            "stt_language": saved.get("stt_language", ""),
            "voice_chat_enabled": saved.get("voice_chat_enabled", True),
            "voice_chat_pause": saved.get("voice_chat_pause", "normal"),
            "voice_chat_barge_in": saved.get("voice_chat_barge_in", True),
        }

    @property
    def available(self) -> bool:
        settings = self._load_settings()
        if settings.get("stt_enabled") is False:
            return False
        provider = settings["stt_provider"]
        if provider == "disabled":
            return False
        if provider == "browser":
            return True  # handled client-side
        if provider == "local":
            # `B1716`. Asked without loading the model: this was read on the
            # server's event loop, and the first read loaded Whisper there —
            # seconds, or a download's minutes, with every other request
            # waiting behind it. A load that failed before is tried again
            # by the recording that asks (`_local_blocker`'s `remembered`).
            return self._whisper_model is not None or self._local_blocker(remembered=False) is None
        if provider.startswith("endpoint:"):
            return True  # assume reachable
        return False

    # ── Local Whisper ──

    def _wanted_size(self) -> str:
        return str(self._load_settings().get("stt_model") or "base")

    def _get_whisper(self):
        size = self._wanted_size()
        if self._whisper_model is not None and self._loaded_size == size:
            return self._whisper_model
        with self._load_lock:
            if self._whisper_model is not None and self._loaded_size == size:
                return self._whisper_model
            # A model of another size is let go before the new one is built,
            # so the two are never held at once.
            self._whisper_model = None
            self._loaded_size = None
            self._device = None
            self._loading = True
            try:
                return self._load_whisper()
            finally:
                self._loading = False

    def _local_blocker(self, remembered: bool = True) -> Optional[str]:
        """`B1716`. Why local Whisper cannot start, found without starting it:
        faster-whisper not installed, or the download gate's refusal (asked
        with the network off, as `ensure_whisper_download_permitted` asks),
        or — `remembered` — the failure the last load of this size recorded,
        which the status says instead of loading again on every poll, and a
        recording does not take as an answer: it tries the load again. `None`
        when a load can be tried. Each answer is recorded where
        `unavailable_reason` reads it."""
        if not _installed("faster_whisper"):
            self._whisper_failure = (
                "Local speech-to-text is chosen in Settings, but faster-whisper is not "
                "installed on this server (pip install faster-whisper).")
            return self._whisper_failure
        if self._loading:
            return None
        try:
            ensure_whisper_download_permitted(self._wanted_size())
            self._whisper_refusal = None
        except Exception as e:
            self._whisper_refusal = str(e)
            return self._whisper_refusal
        if remembered and self._whisper_failure and self._failed_size == self._wanted_size():
            return self._whisper_failure
        return None

    def _load_whisper(self):
        self._whisper_failure = None
        try:
            from faster_whisper import WhisperModel
        except ImportError:
            logger.warning("faster-whisper not installed. Install with: pip install faster-whisper")
            self._whisper_failure = (
                "Local speech-to-text is chosen in Settings, but faster-whisper is not "
                "installed on this server (pip install faster-whisper).")
            return None
        settings = self._load_settings()
        model_size = settings.get("stt_model", "base")
        self._whisper_refusal = None
        try:
            source = ensure_whisper_download_permitted(model_size)
        except Exception as e:
            self._whisper_refusal = str(e)
            logger.warning("Local speech-to-text not started: %s", e)
            return None
        # faster-whisper runs on CTranslate2, which says itself whether it has
        # a CUDA device (`_cuda_devices`, `B1716`: torch was asked, and the
        # image has no torch). A GPU that will not take the model — no cuDNN
        # in the container, too little memory — falls back to the CPU, where
        # int8 is the fast type, instead of leaving speech-to-text off; one
        # that would crash on the first recording is found out in a child
        # process first (`_whisper_runs_on_cuda`).
        devices = ["cuda", "cpu"] if _cuda_devices() > 0 else ["cpu"]
        last_error: Optional[Exception] = None
        for device in devices:
            if device == "cuda" and not _whisper_runs_on_cuda(source):
                continue
            compute_type = "float16" if device == "cuda" else "int8"
            try:
                self._whisper_model = WhisperModel(source, device=device, compute_type=compute_type)
                self._device = device
                self._loaded_size = str(model_size or "base")
                logger.info(f"faster-whisper model '{model_size}' loaded on {device}")
                return self._whisper_model
            except Exception as e:
                last_error = e
                logger.error(f"Failed to load whisper model on {device}: {e}")
        self._whisper_failure = (
            f"Local speech-to-text could not load the Whisper “{model_size}” model "
            f"({_said(last_error)}). The server log has the detail.")
        self._failed_size = str(model_size or "base")
        return None

    def warm(self) -> bool:
        """`B1716`. Start loading local Whisper in the background, so the first
        thing a person says is not spent waiting for the model. `True` when a
        load was started; nothing happens when it is loaded, loading, not the
        provider, or would need a download nobody allowed — that refusal is
        the gate's, asked inside `_get_whisper` like every other load."""
        settings = self._load_settings()
        if settings.get("stt_enabled") is False or settings.get("stt_provider") != "local":
            return False
        if self._loading or (self._whisper_model is not None
                             and self._loaded_size == self._wanted_size()):
            return False
        threading.Thread(target=self._get_whisper, name="stt-warm", daemon=True).start()
        return True

    def unavailable_reason(self) -> Optional[str]:
        """`B1565`. The sentence for why local Whisper is not running, when
        the download gate is the reason; `None` otherwise.

        `B1564`: or when faster-whisper is not installed or would not load
        (`B1579`'s sentence) — the Settings card says it under the choice,
        and a recording sent to `/api/stt/transcribe` is told it rather than
        *not available or set to browser mode*. Asked against the settings
        as they are now, as `unheard_reason` is: a reason left from before
        the provider changed is about local Whisper and nothing else."""
        settings = self._load_settings()
        if settings.get("stt_enabled") is False or settings.get("stt_provider") != "local":
            return None
        return self._whisper_refusal or self._whisper_failure

    def unheard_reason(self) -> Optional[str]:
        """`B1571`. Why this server turned a recording into no text, when it
        can say more than that it has no speech-to-text: local Whisper is the
        provider, no model is loaded, and the download gate refused the one it
        needs (`B1565`'s sentence). `B1579`: or Whisper is not installed or
        would not load, or the transcription itself failed or gave no words —
        on an endpoint provider too. `None` only when speech-to-text is off or
        the browser's own, so the caller says what it always said.

        Read, not asked: the refusal is the one the last attempt to start
        Whisper recorded, and every path that writes the not-heard note has
        just asked this service to transcribe. Asked against the settings as
        they are now, so a refusal left from before the provider changed is
        never said about a provider it is not about."""
        settings = self._load_settings()
        provider = settings.get("stt_provider") or ""
        if settings.get("stt_enabled") is False:
            return None
        # `B1579`. Past the gate, speech-to-text *is* set up, so *no
        # speech-to-text set up* is never the sentence: Whisper not installed or
        # not loadable, the transcription raised, or it ran and gave no words.
        # The last is said without a cause because the cause is not known —
        # several recordings in one turn are transcribed before any note is
        # written, and only the last attempt's failure is kept.
        if provider == "local":
            if self._whisper_model is None:
                return self._whisper_refusal or self._whisper_failure
            return self._transcribe_failure or (
                "Local speech-to-text (Whisper) gave no words for it. If it has speech "
                "in it, the server log says why.")
        if provider.startswith("endpoint:"):
            return self._transcribe_failure or (
                "The speech-to-text endpoint gave no words for it. If it has speech "
                "in it, the server log says why.")
        return None

    def _transcribe_local(self, audio_bytes: bytes, language: str = "",
                          filename: str = "") -> Optional[str]:
        self._transcribe_failure = None
        model = self._get_whisper()
        if not model:
            return None
        tmp_path = None
        try:
            # Write to temp file (faster-whisper needs a file path or file-like).
            # Its decoder reads the content; the suffix is kept honest
            # (`sniff_audio_format`) for anything that reads the name.
            ext, _mime = sniff_audio_format(audio_bytes, filename)
            with tempfile.NamedTemporaryFile(suffix="." + ext, delete=False) as tmp:
                tmp.write(audio_bytes)
                tmp_path = tmp.name

            # `B1716`. Whisper writes words over silence — a voice call's
            # pause came back as *"Thank you."* — and faster-whisper's own
            # voice-activity filter (Silero, shipped inside the package, so
            # nothing is fetched) cuts the silence out before Whisper hears
            # it. A recording is one turn, so no earlier text conditions it:
            # conditioning is what lets one misheard phrase repeat to the end.
            kwargs = {"vad_filter": True, "condition_on_previous_text": False}
            if language:
                kwargs["language"] = language

            segments, info = model.transcribe(tmp_path, **kwargs)
            text = " ".join(t for t in (seg.text.strip() for seg in segments) if t)

            logger.info(f"Local STT: {len(text)} chars, lang={info.language}, prob={info.language_probability:.2f}")
            return text
        except Exception as e:
            logger.error(f"Local STT transcription failed: {e}", exc_info=True)
            self._transcribe_failure = (
                f"Local speech-to-text (Whisper) failed on it: {_said(e)}.")
            return None
        finally:
            if tmp_path:
                Path(tmp_path).unlink(missing_ok=True)

    # ── API endpoint ──

    def _transcribe_api(self, audio_bytes: bytes, endpoint_id: str, model: str, language: str = "",
                        filename: str = "") -> Optional[str]:
        from src.database import SessionLocal, ModelEndpoint

        self._transcribe_failure = None

        db = SessionLocal()
        try:
            ep = db.query(ModelEndpoint).filter(ModelEndpoint.id == endpoint_id).first()
            if not ep:
                logger.error(f"STT endpoint {endpoint_id} not found")
                self._transcribe_failure = (
                    "The speech-to-text endpoint chosen in Settings no longer exists. "
                    "Choose another in Settings.")
                return None
            base_url = ep.base_url.rstrip("/")
            api_key = ep.api_key
        finally:
            db.close()

        url = base_url + "/audio/transcriptions"
        headers = {}
        if api_key:
            headers["Authorization"] = f"Bearer {api_key}"

        # `B1716`. Named for what it is: the endpoint reads the format from the
        # name, and every recording was called `audio.webm`.
        ext, mime = sniff_audio_format(audio_bytes, filename)
        files = {"file": (f"audio.{ext}", io.BytesIO(audio_bytes), mime)}
        data = {"model": model or "whisper-1"}
        if language:
            data["language"] = language

        try:
            # `B1022`: paced and routed (`paced_http`) — a hosted STT API is a
            # third party the limiter keeps polite; a local one costs nothing.
            from src import paced_http
            r = paced_http.post_sync(url, headers=headers, files=files, data=data, timeout=60,
                                     follow_redirects=False)
            r.raise_for_status()
            result = r.json()
            text = result.get("text", "")
            logger.info(f"API STT: {len(text)} chars from {base_url}")
            return text
        except Exception as e:
            logger.error(f"API STT transcription failed: {e}")
            # The address is not said: the note is read in a chat, and an
            # endpoint's URL is the admin's to show.
            status = getattr(getattr(e, "response", None), "status_code", None)
            self._transcribe_failure = (
                "The speech-to-text endpoint failed on it "
                f"({f'it answered {status}' if status else type(e).__name__}). "
                "The server log has the detail.")
            return None

    # ── Public interface ──

    def transcribe(self, audio_bytes: bytes, filename: str = "") -> Optional[str]:
        """The words in a recording, `""` when it holds none, or `None` when
        nothing on this server heard it (`unavailable_reason`,
        `unheard_reason` say why). `filename` is the name it came with, asked
        only when its bytes do not say what it is (`sniff_audio_format`)."""
        settings = self._load_settings()
        if settings.get("stt_enabled") is False:
            return None
        provider = settings["stt_provider"]
        model = settings["stt_model"]
        # `B1564`. Settings' one language field reaches the browser's own
        # recognition too, which takes a BCP 47 tag (`en-GB`); Whisper and an
        # OpenAI-compatible endpoint take the ISO 639-1 code (`en`) and refuse
        # the tag, so a language set for the browser would have failed every
        # recording sent here after the provider changed.
        language = str(settings.get("stt_language") or "").split("-")[0].strip().lower()

        if provider in ("disabled", "browser"):
            return None

        if provider == "local":
            return self._transcribe_local(audio_bytes, language, filename)
        elif provider.startswith("endpoint:"):
            endpoint_id = provider.split(":", 1)[1]
            return self._transcribe_api(audio_bytes, endpoint_id, model, language, filename)
        else:
            logger.error(f"Unknown STT provider: {provider}")
            return None

    def get_stats(self) -> Dict[str, Any]:
        """What Settings and the voice call read about speech-to-text.

        `B1716`. Never loads a model: the first read loaded local Whisper on
        the request (a download's minutes, when one was allowed), and the
        Settings page and a call that asked waited the whole time. A model
        that can be loaded is started in the background (`warm`) and said to
        be `loading`; the reader asks again until it is `model_loaded`, or an
        `unavailable_reason` says why it will not be."""
        settings = self._load_settings()
        provider = settings["stt_provider"]
        stt_enabled = settings.get("stt_enabled", False)
        # If toggle is off, report as disabled
        effective_provider = provider if stt_enabled else "disabled"

        stats = {
            "available": bool(stt_enabled) and provider != "local" and self.available,
            "provider": effective_provider,
            "model": settings["stt_model"],
            "language": settings.get("stt_language", ""),
            # `B1718`. What a voice chat reads as it starts, beside what it is
            # heard by: whether it is on, the pause that ends a turn, and
            # whether talking over the agent interrupts it.
            "voice_chat": {
                "enabled": settings.get("voice_chat_enabled") is not False,
                "pause": settings.get("voice_chat_pause") if settings.get("voice_chat_pause") in ("short", "normal", "relaxed") else "normal",
                "barge_in": settings.get("voice_chat_barge_in") is not False,
            },
        }

        if provider == "local":
            loaded = self._whisper_model is not None and self._loaded_size == self._wanted_size()
            reason = None if loaded else self._local_blocker()
            stats["available"] = bool(stt_enabled) and reason is None
            stats["model_loaded"] = loaded
            stats["loading"] = False
            if loaded:
                stats["device"] = self._device
            elif reason:
                stats["unavailable_reason"] = reason
            elif stt_enabled:
                self.warm()
                stats["loading"] = True
        elif provider == "browser":
            stats["model"] = "Browser (Web Speech API)"
        elif provider.startswith("endpoint:"):
            stats["endpoint_id"] = provider.split(":", 1)[1]

        return stats


# Module-level singleton
_stt_service = None

def get_stt_service() -> STTService:
    global _stt_service
    if _stt_service is None:
        _stt_service = STTService()
    return _stt_service
