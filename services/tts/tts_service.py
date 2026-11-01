# SPDX-License-Identifier: AGPL-3.0-or-later
# src/tts_service.py
"""Multi-provider TTS service — dispatches to Kokoro (CPU or GPU), Chatterbox, Piper,
an OpenAI-compatible API, or the browser."""

import io
import os
import re
import wave
import logging
import hashlib
import tempfile
import threading
import httpx
from pathlib import Path
from typing import Optional, Dict, Any, List

from src.constants import TTS_CACHE_DIR
from services.tts.chatterbox_client import CHATTERBOX_DEFAULT_VOICE, ChatterboxClient
from services.tts.kokoro_cpu import (
    ESPEAK_LOCK, KOKORO_DEFAULT_VOICE, KOKORO_MODEL, KOKORO_VOICES as KOKORO_VOICES_FILE,
    VOICES as KOKORO_VOICES, KokoroEngine, find_kokoro_files, kokoro_dirs, kokoro_voice)
from services.tts.personal_voice import PERSONAL_ENGINES

logger = logging.getLogger(__name__)

# `B1728`, `B1729`. What "Automatic" (`auto`, the server's voice as shipped)
# tries, in order: Chatterbox while its GPU sidecar answers, Kokoro on this
# server's processor, then Piper. Never the browser's voices on its own: in
# Chrome those are Google's online service, which a person chooses where it
# says so (`B1564`, `Law 16`).
AUTO_ORDER = ("chatterbox", "kokoro", "piper")
_SPEAKS_HERE = ("kokoro", "chatterbox", "piper", "local")


# `B1717`. Piper: the voice this server speaks with on its own CPU, no GPU and
# no service to link. Kokoro (`local`) needs PyTorch with CUDA and a Python
# below 3.13, so it cannot install in the image at all; a voice call needs a
# voice that works where Pantheon runs. The default is a voice trained on the
# LJ Speech recordings, which their authors put in the public domain, so the
# image carries nothing a person may not use. Voices are named as Piper names
# them (`en_US-ljspeech-medium`: language, speaker, quality) and live in
# `rhasspy/piper-voices` on Hugging Face as `<family>/<language>/<speaker>/
# <quality>/<name>.onnx` beside its `.onnx.json`.
PIPER_DEFAULT_VOICE = "en_US-ljspeech-medium"
PIPER_VOICE_REPO = "rhasspy/piper-voices"
_PIPER_VOICE = re.compile(
    r"^(?P<lang>(?P<family>[a-z]{2,3})_[A-Za-z0-9]{2,4})-(?P<speaker>[A-Za-z0-9_]+)-"
    r"(?P<quality>x_low|low|medium|high)$")


def _installed(module: str) -> bool:
    """Whether `module` can be imported, asked without importing it (a test's
    stand-in, already imported, is installed)."""
    import importlib.util
    import sys
    if sys.modules.get(module) is not None:
        return True
    try:
        return importlib.util.find_spec(module) is not None
    except (ImportError, ValueError):
        return False


def piper_voice_dirs() -> List[Path]:
    """Where Piper voices are looked for, in order: the data folder's
    `models/piper` (a voice fetched here, or one put there by hand), then the
    voices the image carries (`PANTHEON_SEED_MODELS`, baked by the
    Dockerfile; read where they are, never copied)."""
    from src.constants import DATA_DIR
    dirs = [Path(DATA_DIR) / "models" / "piper"]
    seed = os.getenv("PANTHEON_SEED_MODELS")
    if seed:
        dirs.append(Path(seed) / "piper")
    return dirs


def piper_voice_name(voice: str) -> str:
    """The Piper voice a stored `tts_voice` names. The one voice setting is
    shared with the endpoint provider (`alloy`) and Kokoro (`af_heart`), and
    neither of those is a Piper voice: then the default, or — when the default
    is not on disk and another voice is — the first voice that is, so a person
    who put one voice in the folder hears it rather than a refusal."""
    voice = str(voice or "").strip()
    if _PIPER_VOICE.match(voice):
        return voice
    if find_piper_voice(PIPER_DEFAULT_VOICE) is None:
        installed = installed_piper_voices()
        if installed:
            return installed[0]
    return PIPER_DEFAULT_VOICE


def find_piper_voice(voice: str) -> Optional[Path]:
    """The voice's `.onnx` on disk, when it is there with its `.onnx.json`."""
    if not _PIPER_VOICE.match(str(voice or "")):
        return None
    for folder in piper_voice_dirs():
        model = folder / f"{voice}.onnx"
        if model.is_file() and (folder / f"{voice}.onnx.json").is_file():
            return model
    return None


def installed_piper_voices() -> List[str]:
    """Every Piper voice on disk, each named once, in the order found."""
    names: List[str] = []
    for folder in piper_voice_dirs():
        try:
            models = sorted(folder.glob("*.onnx"))
        except OSError:
            continue
        for model in models:
            name = model.name[: -len(".onnx")]
            if (_PIPER_VOICE.match(name) and name not in names
                    and (folder / f"{name}.onnx.json").is_file()):
                names.append(name)
    return names


def ensure_piper_voice(voice: str) -> Path:
    """The voice's model file, or `ModelDownloadNotPermitted`.

    `Law 16`, the same one consent local Whisper and FastEmbed ask
    (`model_download_allowed`): a voice on disk costs no network and is
    answered as it is; one that is not is fetched from Hugging Face only when
    someone allowed it, and otherwise refused with the sentence a person can
    act on. `tests/test_piper_asks_before_it_downloads.py` fails on a fetch
    made anywhere this is not asked."""
    from src.embedding_lanes import ModelDownloadNotPermitted, model_download_allowed

    found = find_piper_voice(voice)
    if found is not None:
        return found
    named = _PIPER_VOICE.match(str(voice or ""))
    if not named:
        raise ValueError(f"“{voice}” is not a Piper voice name (like {PIPER_DEFAULT_VOICE}).")
    dest = piper_voice_dirs()[0]
    if not model_download_allowed():
        raise ModelDownloadNotPermitted(
            f"Speaking needs the Piper voice “{voice}”, which is not downloaded, and Pantheon "
            "does not fetch models on its own. Turn on “Download models from the internet” "
            "(Settings → System) to fetch it from Hugging Face once, or put its .onnx and "
            f".onnx.json files in {dest}.")
    from huggingface_hub import hf_hub_download
    from src import paced_http

    prefix = (f"{named['family']}/{named['lang']}/{named['speaker']}/"
              f"{named['quality']}/{voice}")
    dest.mkdir(parents=True, exist_ok=True)
    with tempfile.TemporaryDirectory(dir=str(dest)) as tmp:
        for ext in (".onnx", ".onnx.json"):
            paced_http.call_sync("huggingface.co", hf_hub_download, repo_id=PIPER_VOICE_REPO,
                                 filename=prefix + ext, local_dir=tmp)
        # The model first and its config last: a voice is found only when
        # both are there, so a fetch cut off between the two is no voice.
        for ext in (".onnx", ".onnx.json"):
            os.replace(os.path.join(tmp, prefix + ext), str(dest / f"{voice}{ext}"))
    logger.info("Fetched the Piper voice %s into %s", voice, dest)
    return dest / f"{voice}.onnx"


def _safe_speed(value, default: float = 1.0) -> float:
    """Parse the stored tts_speed defensively. The settings layer tolerates
    corrupt/agent-written config, so a non-numeric or empty value (e.g. an agent
    setting "speech speed" = "fast", or a hand-edited settings.json) must not
    crash synthesis or the stats endpoint with a ValueError."""
    try:
        speed = float(value)
    except (TypeError, ValueError):
        return default
    return speed if speed > 0 else default


class TTSService:
    """Multi-provider TTS service.

    Reads provider config from data/settings.json on each call.
    Providers:
      "disabled"        — no TTS
      "browser"         — client-side Web Speech API (no server synthesis)
      "auto"            — Chatterbox when its GPU sidecar is up, else Kokoro on
                          this server, else Piper (`B1728`, `B1729`)
      "kokoro"          — Kokoro-82M on this server's CPU, through ONNX (`B1728`)
      "chatterbox"      — Chatterbox Turbo in its GPU sidecar (`B1729`)
      "piper"           — Piper on this server's CPU (`B1717`)
      "local"           — Kokoro-82M on GPU
      "endpoint:<id>"   — OpenAI-compatible /audio/speech via ModelEndpoint
    """

    def __init__(self, cache_dir: str = TTS_CACHE_DIR):
        self.cache_dir = Path(cache_dir)
        self.cache_dir.mkdir(parents=True, exist_ok=True)
        self._kokoro = None  # lazy-init
        self._piper = _PiperEngine()
        self._kokoro_cpu = KokoroEngine()     # `B1728`: loads on first use
        self._chatterbox = ChatterboxClient()  # `B1729`
        # `B1717`. Why the last synthesis gave no audio, in a person's words:
        # the voice call says it instead of going quiet. Each attempt
        # rewrites it.
        self._failure: Optional[str] = None
        
        try:
            self.max_cache_bytes = int(os.getenv("PANTHEON_TTS_CACHE_MAX_BYTES", 500 * 1024 * 1024))
        except ValueError:
            self.max_cache_bytes = 500 * 1024 * 1024

    # ── Settings ──

    def _load_settings(self) -> dict:
        from src.settings import load_settings
        saved = load_settings()
        return {
            "tts_enabled": saved.get("tts_enabled", True),
            "tts_provider": saved.get("tts_provider", "auto"),
            "tts_model": saved.get("tts_model", "tts-1"),
            "tts_voice": saved.get("tts_voice", "alloy"),
            "tts_speed": saved.get("tts_speed", "1"),
        }

    @property
    def available(self) -> bool:
        """Whether the server's own voice speaks (Settings → Voice). A
        person's own (`can_speak`) is asked with what they chose."""
        return self.can_speak(None)

    def can_speak(self, choice: Optional[dict] = None) -> bool:
        """`B1730`. Whether the voice this person hears speaks: theirs when
        they chose one that works here, else the server's."""
        settings = self._load_settings()
        if settings.get("tts_enabled") is False:
            return False
        provider, _model, voice, _speed, _why = self._resolve(settings, choice)
        if provider == "disabled":
            return False
        if provider == "browser":
            return True  # handled client-side
        if provider == "piper":
            return self._piper_blocker({"tts_voice": voice}) is None
        if provider == "kokoro":
            return self._kokoro_blocker() is None
        if provider == "chatterbox":
            return self._chatterbox.available()
        if provider == "local":
            kokoro = self._get_kokoro()
            return kokoro is not None and kokoro.available
        if isinstance(provider, str) and provider.startswith("endpoint:"):
            return True  # assume reachable; errors surface at synthesis time
        return False

    def _piper_blocker(self, settings: dict) -> Optional[str]:
        """`B1717`. Why Piper cannot speak here, found without loading a voice:
        the package is not installed, or the voice is not on disk and nobody
        allowed fetching it. `None` when it can."""
        if not _installed("piper"):
            return ("Piper is chosen in Settings, but it is not installed on this server "
                    "(pip install -r requirements-voice.txt).")
        voice = piper_voice_name(settings.get("tts_voice"))
        if find_piper_voice(voice) is not None:
            return None
        try:
            from src.embedding_lanes import model_download_allowed
            if model_download_allowed():
                return None
        except Exception:
            pass
        try:
            ensure_piper_voice(voice)
        except Exception as e:
            return str(e)
        return None

    def _kokoro_blocker(self) -> Optional[str]:
        """`B1728`. Why Kokoro cannot speak on this server's processor, found
        without loading it: ONNX Runtime or espeak (both Piper's) is not
        installed, or the model is not on disk and nobody allowed fetching it.
        `None` when it can. Nothing is fetched here."""
        if not (_installed("onnxruntime") and _installed("piper")):
            return ("Kokoro speaks through ONNX Runtime and the espeak-ng that Piper carries, and "
                    "they are not installed on this server (pip install -r requirements-voice.txt).")
        if find_kokoro_files() is not None:
            return None
        try:
            from src.embedding_lanes import model_download_allowed
            if model_download_allowed():
                return None
        except Exception:
            pass
        return (
            "Speaking with Kokoro needs its model (about 350 MB), which is not downloaded, and "
            "Pantheon does not fetch models on its own. Turn on “Download models from the "
            "internet” (Settings → System) to fetch it once from the kokoro-onnx release on "
            f"GitHub, or put {KOKORO_MODEL} and {KOKORO_VOICES_FILE} in {kokoro_dirs()[0]}.")

    def _engine(self, provider) -> str:
        """`B1728`, `B1729`. The provider that speaks for `provider`: itself,
        or for "auto" the first of `AUTO_ORDER` that can speak here; "auto"
        itself when none can (`_auto_reason` says why)."""
        if provider != "auto":
            return provider
        if self._chatterbox.available():
            return "chatterbox"
        if self._kokoro_blocker() is None:
            return "kokoro"
        if self._piper_blocker({"tts_voice": ""}) is None:
            return "piper"
        return "auto"

    def _auto_reason(self) -> str:
        """Why "Automatic" found no voice: Kokoro's reason, the one it would
        speak with on any server."""
        return self._kokoro_blocker() or "No voice can speak on this server."

    def _personal_blocker(self, engine: str, voice: str = "") -> Optional[str]:
        """`B1730`. Why the voice a person chose cannot speak here now, or
        `None` when it can (the page speaks the browser's)."""
        if engine == "kokoro":
            return self._kokoro_blocker()
        if engine == "chatterbox":
            return self._chatterbox.health().get("reason")
        if engine == "piper":
            return self._piper_blocker({"tts_voice": voice})
        if engine == "browser":
            return None
        return f"“{engine}” is not a voice this server has."

    def _resolve(self, settings: dict, choice: Optional[dict] = None):
        """`(provider, model, voice, speed, personal_reason)`: what speaks.

        `B1730`. The person's own choice (`services/tts/personal_voice.py`)
        when they made one and it can speak here, else the server's voice
        (`tts_provider`), with "auto" resolved (`_engine`). The voice is the
        one that engine will use, never the stored name of another engine's
        (`alloy` is no Kokoro voice). `personal_reason` says why their choice
        is not the one speaking, when it is not."""
        provider = settings.get("tts_provider")
        model = settings.get("tts_model") or "tts-1"
        voice = settings.get("tts_voice") or ""
        speed = _safe_speed(settings.get("tts_speed", "1"))
        personal_reason = None
        engine = str((choice or {}).get("engine") or "")
        if engine:
            personal_reason = self._personal_blocker(engine, (choice or {}).get("voice") or "")
            if personal_reason is None:
                provider, voice = engine, (choice or {}).get("voice") or ""
        if choice and choice.get("speed"):
            speed = _safe_speed(choice.get("speed"))
        provider = self._engine(provider)
        if provider == "kokoro":
            model, voice = "kokoro-v1.0", kokoro_voice(voice)
        elif provider == "chatterbox":
            model, voice = "chatterbox-turbo", self._chatterbox.voice(voice)
        elif provider == "piper":
            model, voice = "piper", piper_voice_name(voice)
        return provider, model, voice, speed, personal_reason

    def unavailable_reason(self, choice: Optional[dict] = None) -> Optional[str]:
        """`B1717`. The sentence for why this server cannot speak with the
        provider chosen now, or `None` when it can (or it is the browser's or
        off — those say nothing about this server)."""
        settings = self._load_settings()
        if settings.get("tts_enabled") is False:
            return None
        provider, _model, voice, _speed, _why = self._resolve(settings, choice)
        if provider == "auto":
            return self._auto_reason()
        if provider == "piper":
            return self._piper_blocker({"tts_voice": voice})
        if provider == "kokoro":
            return self._kokoro_blocker()
        if provider == "chatterbox":
            return self._chatterbox.health().get("reason")
        if provider == "local":
            kokoro = self._get_kokoro()
            if kokoro is None or not kokoro.available:
                return getattr(kokoro, "reason", None) or "Kokoro would not start on this server."
        return None

    def voice_for(self, choice: Optional[dict] = None) -> str:
        """`B1730`. "engine/voice", the voice this person hears."""
        provider, _model, voice, _speed, _why = self._resolve(self._load_settings(), choice)
        return f"{provider}/{voice}"

    def failure_reason(self) -> Optional[str]:
        """`B1717`. Why the last synthesis gave no audio, when it said."""
        return self._failure

    def warm(self, choice: Optional[dict] = None) -> bool:
        """`B1717`. Load the voice in the background — Piper two to seven
        seconds measured on one CPU, Kokoro about two — so the first reply
        said is not the one that waits. `True` when a load was started;
        nothing is fetched here (a model not on disk waits for the first
        sentence, and its `ensure_*` question)."""
        settings = self._load_settings()
        if settings.get("tts_enabled") is False:
            return False
        provider, _model, voice, _speed, _why = self._resolve(settings, choice)
        if provider == "kokoro":
            if self._kokoro_cpu.loaded() or find_kokoro_files() is None or self._kokoro_blocker():
                return False
            threading.Thread(target=self._kokoro_cpu.warm, name="tts-warm-kokoro",
                             daemon=True).start()
            return True
        if provider != "piper":
            return False
        name = voice
        if self._piper.loaded(name) or find_piper_voice(name) is None or not _installed("piper"):
            return False
        threading.Thread(target=self._piper.warm, args=(name,), name="tts-warm",
                         daemon=True).start()
        return True

    # ── Cache ──

    def _cache_key(self, text: str, provider: str, model: str, voice: str, speed: float = 1.0) -> str:
        raw = f"{provider}|{model}|{voice}|{speed}|{text}"
        return hashlib.sha256(raw.encode()).hexdigest()

    def _get_cached(self, key: str) -> Optional[bytes]:
        for ext in (".mp3", ".wav"):
            path = self.cache_dir / f"{key}{ext}"
            if path.exists():
                return path.read_bytes()
        return None

    def _put_cache(self, key: str, data: bytes):
        ext = ".mp3" if (len(data) >= 3 and (data[:3] == b'ID3' or (data[0] == 0xff and (data[1] & 0xe0) == 0xe0))) else ".wav"
        (self.cache_dir / f"{key}{ext}").write_bytes(data)

        self._enforce_cache_limit()

    def _cache_limit_bytes(self) -> int:
        """The live cache cap: role profile -> instance setting -> env -> this
        instance's own value.

        `P12-01` / `P12-03`. This was the only one of the ten byte caps read at
        instance init, so an operator who wanted a different TTS cache had to
        restart the process. `self.max_cache_bytes` stays exactly as `__init__`
        computed it and is the bottom layer, so `Law 1` holds and
        `tests/test_tts_service_enforce_cache_limit.py` — which sets the
        attribute directly — still decides when nothing above it is configured.

        The `ValueError` is `B63`'s: compose exports this variable as an empty
        string on installs that do not set it, and a value that will not parse
        must leave TTS running on its documented default rather than raising
        inside a cache eviction.
        """
        from src.upload_limits import resolve_byte_cap
        try:
            return resolve_byte_cap(
                "tts_cache_max_bytes", "PANTHEON_TTS_CACHE_MAX_BYTES",
                self.max_cache_bytes,
            )[0]
        except ValueError:
            return self.max_cache_bytes

    def _enforce_cache_limit(self):
            """Evicts oldest files if the cache exceeds the configured byte limit."""
            max_cache_bytes = self._cache_limit_bytes()
            if max_cache_bytes <= 0:
                return

            try:
                files = []
                total_size = 0

                # Safely scan files and sum sizes, ignoring files deleted mid-scan
                for f in self.cache_dir.iterdir():
                    try:
                        if f.is_file() and f.suffix.lower() in (".mp3", ".wav"):
                            files.append(f)
                            total_size += f.stat().st_size
                    except OSError:
                        continue

                if total_size > max_cache_bytes:
                    logger.info(
                        f"TTS cache ({total_size} bytes) exceeded limit ({max_cache_bytes} bytes). Evicting oldest files."
                    )

                    # Sort files by modification time (oldest first)
                    try:
                        files.sort(key=lambda f: f.stat().st_mtime)
                    except OSError as e:
                        logger.warning(f"Failed to sort cache files by mtime: {e}")

                    # Trim down to 80% of max capacity
                    target_size = max_cache_bytes * 0.8

                    while files and total_size > target_size:
                        f = files.pop(0)
                        try:
                            size = f.stat().st_size
                            f.unlink()
                            total_size -= size
                        except OSError as e:
                            logger.warning(f"Failed to evict cache file {f}: {e}")
                            continue

            except Exception as e:
                logger.warning(f"Error enforcing TTS cache limit: {e}", exc_info=True)

    def clear_cache(self):
        count = 0
        for f in self.cache_dir.glob("*.*"):
            f.unlink()
            count += 1
        logger.info(f"Cleared {count} cached TTS files")

    # ── Kokoro (local) ──

    def _get_kokoro(self):
        if self._kokoro is None:
            self._kokoro = _KokoroPipeline()
        return self._kokoro

    # ── API endpoint ──

    def _synthesize_api(self, text: str, endpoint_id: str, model: str, voice: str, speed: float = 1.0) -> Optional[bytes]:
        from src.database import SessionLocal, ModelEndpoint

        db = SessionLocal()
        try:
            ep = db.query(ModelEndpoint).filter(ModelEndpoint.id == endpoint_id).first()
            if not ep:
                logger.error(f"TTS endpoint {endpoint_id} not found")
                self._failure = ("The text-to-speech endpoint chosen in Settings no longer "
                                 "exists. Choose another in Settings.")
                return None
            base_url = ep.base_url.rstrip("/")
            api_key = ep.api_key
        finally:
            db.close()

        url = base_url + "/audio/speech"
        headers = {"Content-Type": "application/json"}
        if api_key:
            headers["Authorization"] = f"Bearer {api_key}"

        payload = {
            "model": model,
            "input": text,
            "voice": voice,
            "response_format": "mp3",
            "speed": speed,
        }

        try:
            # `B1022`: paced and routed (`paced_http`), as the STT call beside it.
            from src import paced_http
            r = paced_http.post_sync(url, json=payload, headers=headers, timeout=60,
                                     follow_redirects=False)
            r.raise_for_status()
            logger.info(f"API TTS: {len(r.content)} bytes from {base_url}")
            return r.content
        except Exception as e:
            logger.error(f"API TTS synthesis failed: {e}")
            # The address is not said, as the speech-to-text call beside it.
            status = getattr(getattr(e, "response", None), "status_code", None)
            self._failure = (
                "The text-to-speech endpoint failed "
                f"({f'it answered {status}' if status else type(e).__name__}). "
                "The server log has the detail.")
            return None

    # ── Public interface ──

    def synthesize(self, text: str, use_cache: bool = True,
                   choice: Optional[dict] = None) -> Optional[bytes]:
        """The audio for `text` in the voice this person hears (`_resolve`:
        `choice` is theirs, `services/tts/personal_voice.py`), or `None` with
        `failure_reason` saying why."""
        settings = self._load_settings()
        if settings.get("tts_enabled") is False:
            return None
        provider, model, voice, speed, _why = self._resolve(settings, choice)

        if provider in ("disabled", "browser"):
            if provider == "browser":
                self._failure = "This voice is the browser's own: the page speaks it, not this server."
            return None

        self._failure = None
        if provider == "auto":
            self._failure = self._auto_reason()
            return None
        if len(text) > 5000:
            text = text[:5000]

        if use_cache:
            key = self._cache_key(text, provider, model, voice, speed)
            cached = self._get_cached(key)
            if cached:
                logger.info(f"TTS cache hit ({len(text)} chars)")
                return cached

        audio_data = None

        if provider == "piper":
            try:
                audio_data = self._piper.synthesize(text, voice, speed)
            except Exception as e:
                from src.embedding_lanes import ModelDownloadNotPermitted
                logger.warning("Piper did not speak: %s", e)
                self._failure = str(e) if isinstance(e, ModelDownloadNotPermitted) else (
                    f"Piper could not speak it ({_said(e)}). The server log has the detail.")
                return None
            if not audio_data:
                self._failure = "Piper found nothing to say in it."
                return None
        elif provider == "kokoro":
            # `B1728`. On this server's processor; the model is fetched here,
            # behind the download switch, when it is not on disk.
            try:
                audio_data = self._kokoro_cpu.synthesize(text, voice, speed)
            except Exception as e:
                from src.embedding_lanes import ModelDownloadNotPermitted
                logger.warning("Kokoro did not speak: %s", e)
                self._failure = str(e) if isinstance(e, ModelDownloadNotPermitted) else (
                    f"Kokoro could not speak it ({_said(e)}). The server log has the detail.")
                return None
            if not audio_data:
                self._failure = "Kokoro found nothing to say in it."
                return None
        elif provider == "chatterbox":
            # `B1729`. In its GPU sidecar, over the compose network.
            try:
                audio_data = self._chatterbox.synthesize(text, voice, speed)
            except Exception as e:
                logger.warning("Chatterbox did not speak: %s", e)
                self._failure = f"Chatterbox could not speak it ({_said(e)})."
                return None
            if not audio_data:
                self._failure = "Chatterbox answered with no sound."
                return None
        elif provider == "local":
            kokoro = self._get_kokoro()
            if kokoro and kokoro.available:
                audio_data = kokoro.synthesize_raw(text, voice)
            else:
                logger.warning("Kokoro TTS not available")
                self._failure = getattr(kokoro, "reason", None) or "Kokoro would not start on this server."
                return None
        elif isinstance(provider, str) and provider.startswith("endpoint:"):
            endpoint_id = provider.split(":", 1)[1]
            audio_data = self._synthesize_api(text, endpoint_id, model, voice, speed)
        else:
            logger.error(f"Unknown TTS provider: {provider}")
            return None

        if audio_data and use_cache:
            key = self._cache_key(text, provider, model, voice, speed)
            self._put_cache(key, audio_data)

        return audio_data

    def synthesize_to_base64(self, text: str, choice: Optional[dict] = None) -> Optional[str]:
        import base64
        audio = self.synthesize(text, choice=choice) if choice else self.synthesize(text)
        if audio:
            return base64.b64encode(audio).decode("utf-8")
        return None

    def set_voice(self, voice: str):
        """Legacy no-op — voice is now managed via admin settings."""

    def get_stats(self, choice: Optional[dict] = None, warm: bool = False) -> Dict[str, Any]:
        """What this person will hear (`choice` is theirs): `provider` is the
        engine that speaks ("auto" resolved), `chosen` the server's setting.
        `warm` loads Kokoro now, for a page about to be spoken to (Piper's
        voice, small, is loaded whenever asked, as `B1717` did)."""
        settings = self._load_settings()
        chosen = settings["tts_provider"]
        tts_enabled = settings.get("tts_enabled", True)
        provider, model, voice, speed, personal_reason = self._resolve(settings, choice)

        cache_files = list(self.cache_dir.glob("*.wav")) + list(self.cache_dir.glob("*.mp3"))
        cache_size = sum(f.stat().st_size for f in cache_files)

        is_available = self.can_speak(choice) and tts_enabled
        reason = self.unavailable_reason(choice) if tts_enabled else None
        stats = {
            "available": is_available,
            "ready": is_available,
            "provider": provider,
            "chosen": chosen,
            "model": settings["tts_model"],
            "voice": settings["tts_voice"],
            "speed": speed,
            "cache_entries": len(cache_files),
            "cache_size_mb": round(cache_size / (1024 * 1024), 2),
        }
        if choice and choice.get("engine"):
            # `B1730`. Their own voice, and why it is not the one speaking.
            stats["personal"] = {"engine": choice.get("engine"), "voice": choice.get("voice") or "",
                                 "speed": choice.get("speed")}
            if personal_reason:
                stats["personal_reason"] = personal_reason

        if reason:
            stats["unavailable_reason"] = reason
        if provider == "piper":
            # `B1717`. The voice that will speak (the stored one may be another
            # provider's), and every voice on disk, for Settings to offer.
            stats["model"] = "Piper"
            stats["voice"] = voice
            stats["voices"] = installed_piper_voices()
            stats["default_voice"] = PIPER_DEFAULT_VOICE
            stats["voice_loaded"] = self._piper.loaded(stats["voice"])
            if is_available and not stats["voice_loaded"]:
                self.warm(choice)
        elif provider == "kokoro":
            # `B1728`. Every voice it speaks, with the words Settings shows.
            stats["model"] = "Kokoro"
            stats["voice"] = voice
            stats["voices"] = [v.id for v in KOKORO_VOICES]
            stats["labels"] = {v.id: v.label for v in KOKORO_VOICES}
            stats["default_voice"] = KOKORO_DEFAULT_VOICE
            stats["voice_loaded"] = self._kokoro_cpu.loaded()
            if warm and is_available and not stats["voice_loaded"]:
                self.warm(choice)
        elif provider == "chatterbox":
            # `B1729`. The sidecar's voices, and where it runs.
            health = self._chatterbox.health()
            stats["model"] = "Chatterbox Turbo"
            stats["voice"] = voice
            stats["voices"] = list(health.get("voices") or [])
            stats["labels"] = dict(health.get("labels") or {})
            stats["default_voice"] = CHATTERBOX_DEFAULT_VOICE
            stats["device"] = health.get("device") or ""
            stats["voice_loaded"] = bool(health.get("ok"))
        elif provider == "local":
            kokoro = self._get_kokoro()
            stats["model"] = "Kokoro-82M (GPU)" if (kokoro and kokoro.available) else "Kokoro (not loaded)"
        elif provider == "browser":
            stats["model"] = "Browser (Web Speech API)"
            if choice and choice.get("engine") == "browser" and not personal_reason:
                stats["voice"] = choice.get("voice") or ""
        elif isinstance(provider, str) and provider.startswith("endpoint:"):
            stats["endpoint_id"] = provider.split(":", 1)[1]

        return stats

    def personal_voices(self) -> Dict[str, Any]:
        """`B1730`. What a person may choose for their own voice (Settings →
        Conversation): each engine on this server, whether it can speak here
        now and why not, and its voices. Their device's own voices are the
        page's to list."""
        settings = self._load_settings()
        if settings.get("tts_enabled") is False:
            return {"off": True, "reason": (
                "Speech is turned off on this server: an admin chose “None” in Settings → Voice."),
                "engines": []}
        provider, _model, voice, _speed, _why = self._resolve(settings, None)
        server = {"chosen": settings.get("tts_provider"), "provider": provider, "voice": voice,
                  "label": _engine_label(provider, voice, self._chatterbox),
                  "available": self.can_speak(None)}
        if not server["available"]:
            server["reason"] = self.unavailable_reason(None)
        health = self._chatterbox.health()
        piper_reason = self._piper_blocker({"tts_voice": ""})
        engines = [
            {"id": "kokoro", "name": "Kokoro", "where": "on this server",
             "available": self._kokoro_blocker() is None, "reason": self._kokoro_blocker(),
             "default": KOKORO_DEFAULT_VOICE,
             "voices": [{"id": v.id, "label": v.label, "language": v.language, "gender": v.gender}
                        for v in KOKORO_VOICES]},
            {"id": "chatterbox", "name": "Chatterbox", "where": "on this server's GPU",
             "available": bool(health.get("ok")), "reason": health.get("reason"),
             "default": CHATTERBOX_DEFAULT_VOICE,
             "voices": [{"id": v, "label": (health.get("labels") or {}).get(v) or v.capitalize()}
                        for v in (health.get("voices") or [])]},
            {"id": "piper", "name": "Piper", "where": "on this server",
             "available": piper_reason is None, "reason": piper_reason,
             "default": PIPER_DEFAULT_VOICE,
             "voices": [{"id": v, "label": v} for v in installed_piper_voices()]},
        ]
        return {"off": False, "server": server, "engines": engines}


def _engine_label(provider: str, voice: str, chatterbox: Optional[ChatterboxClient] = None) -> str:
    """The server's voice in the words Settings → Conversation shows."""
    if provider == "kokoro":
        named = next((v for v in KOKORO_VOICES if v.id == voice), None)
        return f"Kokoro, {named.label}" if named else "Kokoro"
    if provider == "chatterbox":
        return "Chatterbox" if voice == CHATTERBOX_DEFAULT_VOICE else f"Chatterbox, {voice}"
    if provider == "piper":
        return f"Piper, {voice}"
    if provider == "browser":
        return "the browser's own"
    if provider == "local":
        return "Kokoro on the GPU"
    if isinstance(provider, str) and provider.startswith("endpoint:"):
        return "an endpoint under Added Models"
    if provider == "auto":
        return "none yet"
    return "none"


def _said(error: BaseException) -> str:
    """An exception as a clause in a sentence: its first line, trimmed, or its
    type when it has no words of its own (as `services/stt` says one)."""
    text = str(error).strip().splitlines()[0].strip() if str(error).strip() else ""
    text = text.rstrip(".")
    if len(text) > 160:
        text = text[:157].rstrip() + "…"
    return text or type(error).__name__


class _PiperEngine:
    """`B1717`. Piper voices, each loaded once and kept; two at most, so a
    person trying voices in Settings does not hold every one in memory."""

    _KEEP = 2

    def __init__(self):
        self._voices: Dict[str, Any] = {}
        self._lock = threading.Lock()

    def loaded(self, name: str) -> bool:
        return name in self._voices

    def warm(self, name: str) -> None:
        try:
            self.voice(name)
        except Exception as e:  # the first sentence asks again and says why
            logger.info("Piper voice %s not warmed: %s", name, e)

    def voice(self, name: str):
        with self._lock:
            loaded = self._voices.get(name)
            if loaded is None:
                path = ensure_piper_voice(name)
                from piper import PiperVoice
                # `download_dir` is where Piper puts what a Chinese voice
                # needs; it defaulted to the server's working directory.
                loaded = PiperVoice.load(str(path), download_dir=str(path.parent))
                while len(self._voices) >= self._KEEP:
                    self._voices.pop(next(iter(self._voices)))
                self._voices[name] = loaded
            return loaded

    def synthesize(self, text: str, name: str, speed: float = 1.0) -> Optional[bytes]:
        """WAV bytes, or `None` when the text holds nothing to say."""
        if not str(text or "").strip():
            return None
        voice = self.voice(name)
        from piper import SynthesisConfig
        # Piper's speed is a length scale (above 1 is slower), from the
        # voice's own; Settings' speed is a rate (above 1 is faster).
        base = float(getattr(voice.config, "length_scale", 1.0) or 1.0)
        # `B1728`. espeak-ng keeps one voice for the whole process, and Kokoro
        # phonemizes through the same library: one at a time (the load above
        # is outside it, so a voice loading never holds Kokoro up).
        with ESPEAK_LOCK:
            chunks = list(voice.synthesize(text, syn_config=SynthesisConfig(
                length_scale=base / (speed if speed > 0 else 1.0))))
        if not chunks:
            return None
        buf = io.BytesIO()
        with wave.open(buf, "wb") as wf:
            wf.setnchannels(chunks[0].sample_channels)
            wf.setsampwidth(chunks[0].sample_width)
            wf.setframerate(chunks[0].sample_rate)
            for chunk in chunks:
                wf.writeframes(chunk.audio_int16_bytes)
        return buf.getvalue()


class _KokoroPipeline:
    """Encapsulates the Kokoro-82M local GPU pipeline."""

    def __init__(self):
        self.pipeline = None
        self.available = False
        self.device = None
        # `B1717`. Why it did not start, in a person's words (Settings and the
        # voice call say it); `None` once it has.
        self.reason: Optional[str] = None
        self._init()

    def _init(self):
        try:
            import torch
            from kokoro import KPipeline

            if not torch.cuda.is_available():
                logger.warning("CUDA not available for Kokoro TTS")
                self.reason = ("Kokoro needs a CUDA GPU, and this server has none it can use. "
                               "Piper speaks on the CPU.")
                return

            self.device = torch.device("cuda:0")
            with torch.cuda.device(0):
                self.pipeline = KPipeline(lang_code="a")
                if hasattr(self.pipeline, "model"):
                    self.pipeline.model = self.pipeline.model.to(self.device)
            self.available = True
            logger.info("Kokoro-82M TTS pipeline loaded")
        except ImportError as e:
            logger.warning(f"Kokoro TTS not available: {e}")
            logger.warning("Install with: pip install kokoro soundfile")
            self.reason = ("Kokoro is not installed on this server; it needs PyTorch with CUDA "
                           "and Python below 3.13 (requirements-optional.txt). Piper speaks on "
                           "the CPU.")
        except Exception as e:
            logger.error(f"Kokoro init failed: {e}", exc_info=True)
            self.reason = f"Kokoro would not start ({_said(e)}). The server log has the detail."

    def synthesize_raw(self, text: str, voice: str = "af_heart") -> Optional[bytes]:
        if not self.available:
            return None
        try:
            import torch
            import numpy as np

            with torch.cuda.device(self.device):
                chunks = []
                for _, _, audio in self.pipeline(text, voice=voice):
                    chunks.append(audio)

            if not chunks:
                return None

            full = np.concatenate(chunks)
            buf = io.BytesIO()
            with wave.open(buf, "wb") as wf:
                wf.setnchannels(1)
                wf.setsampwidth(2)
                wf.setframerate(24000)
                wf.writeframes((full * 32767).astype(np.int16).tobytes())
            return buf.getvalue()
        except Exception as e:
            logger.error(f"Kokoro synthesis failed: {e}", exc_info=True)
            return None


# Module-level singleton
_tts_service = None

def get_tts_service() -> TTSService:
    global _tts_service
    if _tts_service is None:
        _tts_service = TTSService()
    return _tts_service
