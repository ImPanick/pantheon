# SPDX-License-Identifier: AGPL-3.0-or-later
# services/stt/stt_service.py
"""Multi-provider Speech-to-Text service — dispatches to local Whisper, OpenAI-compatible API, or browser."""

import io
import logging
import os
import httpx
import tempfile
from pathlib import Path
from typing import Optional, Dict, Any

logger = logging.getLogger(__name__)


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
    if os.path.isdir(name) or model_download_allowed():
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

    # ── Settings ──

    def _load_settings(self) -> dict:
        from src.settings import load_settings
        saved = load_settings()
        return {
            "stt_enabled": saved.get("stt_enabled", False),
            "stt_provider": saved.get("stt_provider", "disabled"),
            "stt_model": saved.get("stt_model", "base"),
            "stt_language": saved.get("stt_language", ""),
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
            return self._get_whisper() is not None
        if provider.startswith("endpoint:"):
            return True  # assume reachable
        return False

    # ── Local Whisper ──

    def _get_whisper(self):
        if self._whisper_model is None:
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
            try:
                # faster-whisper runs on CTranslate2, not torch. torch is only
                # used (optionally) to detect a CUDA device for acceleration —
                # if it's missing or unusable we just run on CPU. Keeping this
                # probe separate (and tolerant of any failure, e.g. a broken
                # CUDA/torch install that raises OSError on import) means a
                # torch-less or torch-broken machine still does CPU
                # transcription instead of failing with a misleading
                # "faster-whisper not installed" error.
                try:
                    import torch
                    use_cuda = torch.cuda.is_available()
                except Exception:
                    use_cuda = False
                device = "cuda" if use_cuda else "cpu"
                compute_type = "float16" if device == "cuda" else "int8"
                self._whisper_model = WhisperModel(source, device=device, compute_type=compute_type)
                logger.info(f"faster-whisper model '{model_size}' loaded on {device}")
            except Exception as e:
                logger.error(f"Failed to load whisper model: {e}")
                self._whisper_failure = (
                    f"Local speech-to-text could not load the Whisper “{model_size}” model "
                    f"({_said(e)}). The server log has the detail.")
                return None
        return self._whisper_model

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

    def _transcribe_local(self, audio_bytes: bytes, language: str = "") -> Optional[str]:
        self._transcribe_failure = None
        model = self._get_whisper()
        if not model:
            return None
        tmp_path = None
        try:
            # Write to temp file (faster-whisper needs a file path or file-like)
            with tempfile.NamedTemporaryFile(suffix=".webm", delete=False) as tmp:
                tmp.write(audio_bytes)
                tmp_path = tmp.name

            kwargs = {}
            if language:
                kwargs["language"] = language

            segments, info = model.transcribe(tmp_path, **kwargs)
            text = " ".join(seg.text.strip() for seg in segments)

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

    def _transcribe_api(self, audio_bytes: bytes, endpoint_id: str, model: str, language: str = "") -> Optional[str]:
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

        files = {"file": ("audio.webm", io.BytesIO(audio_bytes), "audio/webm")}
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

    def transcribe(self, audio_bytes: bytes) -> Optional[str]:
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
            return self._transcribe_local(audio_bytes, language)
        elif provider.startswith("endpoint:"):
            endpoint_id = provider.split(":", 1)[1]
            return self._transcribe_api(audio_bytes, endpoint_id, model, language)
        else:
            logger.error(f"Unknown STT provider: {provider}")
            return None

    def get_stats(self) -> Dict[str, Any]:
        settings = self._load_settings()
        provider = settings["stt_provider"]
        stt_enabled = settings.get("stt_enabled", False)
        # If toggle is off, report as disabled
        effective_provider = provider if stt_enabled else "disabled"

        stats = {
            "available": self.available and stt_enabled,
            "provider": effective_provider,
            "model": settings["stt_model"],
            "language": settings.get("stt_language", ""),
        }

        if provider == "local":
            whisper = self._get_whisper()
            stats["model_loaded"] = whisper is not None
            if whisper is None and self.unavailable_reason():
                stats["unavailable_reason"] = self.unavailable_reason()
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
