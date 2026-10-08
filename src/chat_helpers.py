# SPDX-License-Identifier: AGPL-3.0-or-later
# src/chat_helpers.py
"""URL extraction, message validation, request parsing."""

import re
import json
import time
import ipaddress
import logging
import httpx
from urllib.parse import urlparse
from fastapi import HTTPException
from typing import List, Optional

logger = logging.getLogger(__name__)


def extract_urls(text: str) -> List[str]:
    """Extract URLs from text using regex pattern."""
    url_pattern = r'https?://[^\s<>"{}|\\^`\[\]]+'
    urls = re.findall(url_pattern, text)
    cleaned_urls = []
    for url in urls:
        # Strip trailing sentence punctuation, but keep a balanced ')' so URLs
        # that legitimately end in one are preserved, e.g. the Wikipedia link
        # ".../Python_(programming_language)". A ')' is only dropped when it is
        # unbalanced (more ')' than '('), which is the prose-glued case such as
        # "(see https://example.com)".
        url = re.sub(r'[.,;:!?]+$', '', url)
        while url.endswith(')') and url.count(')') > url.count('('):
            url = re.sub(r'[.,;:!?]+$', '', url[:-1])
        cleaned_urls.append(url)
    return cleaned_urls


# Model-name substrings that signal native image input. A missed match here
# silently drops the image from the chat request (it gets swapped for a text
# caption), so the model never sees it. Keep this broad, especially for local
# models (Ollama/llama.cpp) that ship under many names. See issue #124.
_VISION_MODEL_KEYWORDS = (
    # hosted
    "gpt-4o", "gpt-4.1", "gpt-4.5", "gpt-4-turbo", "gpt-4-vision",
    "claude-sonnet", "claude-opus", "claude-haiku", "gemini",
    # open / local
    "vision", "multimodal", "llava", "bakllava", "moondream", "pixtral", "minicpm",
    "internvl", "cogvlm", "qwen-vl", "qwen2-vl", "qwen3-vl", "qwen3vl",
    # multimodal families whose names don't contain "vision"/"vl" but DO accept
    # images — without these the image is silently dropped for common Ollama tags
    # like gemma3:4b or gemma4:12b (issue #1274). Gemma 3/4 (4b+), Llama 4 (all),
    # Mistral Small 3.1/3.2, and Phi-4 multimodal are vision-capable; per the
    # err-toward-True policy (#124) a rare text-only tag being treated as vision is
    # the safer failure than silently dropping a real image.
    "gemma-3", "gemma3", "gemma-4", "gemma4",
    "llama-4", "llama4",
    "mistral-small-3.1", "mistral-small3.1", "mistral-small-3.2", "mistral-small3.2",
    # Microsoft Phi-4 ships a dedicated multimodal variant ("phi-4-multimodal-instruct")
    # but users often load it under the bare "phi-4" or "phi4" Ollama tag.
    "phi-4", "phi4",
    # zhipu / glm (glm-4.5v, glm-4.6v, glm-5v-turbo, etc.)
    "glm-4.5v", "glm-4.6v", "glm-5v",
)
# Catches the "*-VL-*" / "*VL*" family not covered by a literal keyword above
# (e.g. Qwen2.5-VL and various tags): a standalone "vl" token, plus "vlm".
_VISION_VL_RE = re.compile(r'(?<![a-z])vl(?![a-z])|vlm')


def is_vision_model(model_name: str) -> bool:
    """Best-effort check of whether a model can natively accept images.

    Decides whether image attachments get passed through to the model or
    swapped for a separate caption. Err toward True, since a false negative
    drops the image entirely. See issue #124.
    """
    m = (model_name or "").lower()
    if any(kw in m for kw in _VISION_MODEL_KEYWORDS):
        return True
    return bool(_VISION_VL_RE.search(m))


_PROVIDER_FINGERPRINT_TTL = 60.0
# (host, port) -> (models_list | None, expiry); list = LM Studio, None = not LM Studio.
_lmstudio_models_cache: dict = {}


def _is_local_host(host: Optional[str]) -> bool:
    """True for loopback/LAN/Tailscale hosts (never public domains)."""
    host = (host or "").lower()
    if not host:
        return False
    if host in {"localhost", "host.docker.internal"} or host.endswith(".local"):
        return True
    try:
        ip = ipaddress.ip_address(host)
    except ValueError:
        return "." not in host
    if ip.is_loopback or ip.is_private or ip.is_link_local:
        return True
    return ip in ipaddress.ip_network("100.64.0.0/10")


def _probe_auth_headers(url: str) -> dict:
    """Authorization header for a configured endpoint matching ``url``.

    Mirrors the chat-completions path: match an enabled ModelEndpoint by its
    stored base_url, resolve its runtime credentials the same way, and send
    ``Authorization: Bearer <key>`` only when a key is configured. Returns an
    empty dict when nothing matches or no key is set, so keyless local servers
    are still probed unauthenticated (and behavior is unchanged for them)."""
    raw = (url or "").strip()
    if not raw:
        return {}
    try:
        from core.database import SessionLocal, ModelEndpoint
        from src.endpoint_resolver import resolve_endpoint_runtime, normalize_base
    except Exception:
        return {}
    keys = []
    for base in (raw, normalize_base(raw) if raw else ""):
        for cand in (base, (base or "").rstrip("/"), (base or "").rstrip("/") + "/"):
            if cand and cand not in keys:
                keys.append(cand)
    try:
        db = SessionLocal()
    except Exception:
        return {}
    try:
        for key in keys:
            ep = db.query(ModelEndpoint).filter(ModelEndpoint.base_url == key).first()
            if ep is None:
                continue
            try:
                _base, api_key = resolve_endpoint_runtime(ep, owner=getattr(ep, "owner", None))
            except Exception:
                api_key = getattr(ep, "api_key", None)
            return {"Authorization": f"Bearer {api_key}"} if api_key else {}
    except Exception:
        return {}
    finally:
        db.close()
    return {}


def _probe_lmstudio_models(url: str) -> Optional[list]:
    """Return LM Studio's native /api/v1/models list, or None when the endpoint
    isn't LM Studio or is unreachable (short-TTL cached; transient errors uncached)."""
    parsed = urlparse(url)
    host = parsed.hostname or ""
    key = (host, parsed.port)
    now = time.time()
    cached = _lmstudio_models_cache.get(key)
    if cached is not None and cached[1] > now:
        return cached[0]
    authority = host if parsed.port is None else f"{host}:{parsed.port}"
    probe_url = f"{parsed.scheme or 'http'}://{authority}/api/v1/models"
    try:
        r = httpx.get(probe_url, timeout=1.0, headers=_probe_auth_headers(url) or None)
    except Exception:
        return None
    try:
        data = r.json() if r.is_success else {}
    except Exception:
        data = {}
    models = data.get("models")
    valid = (
        isinstance(models, list) and bool(models)
        and isinstance(models[0], dict)
        and "key" in models[0] and "architecture" in models[0]
    )
    models = models if valid else None
    _lmstudio_models_cache[key] = (models, now + _PROVIDER_FINGERPRINT_TTL)
    return models


def lmstudio_supports_vision(url: str, model: str) -> Optional[bool]:
    """Read `model`'s capabilities.vision flag from LM Studio, or None when the
    endpoint isn't LM Studio or doesn't report it (so callers fall back)."""
    if not model:
        return None
    # Never probe a remote provider; LM Studio is always a local/LAN host.
    if not _is_local_host(urlparse(url).hostname):
        return None
    models = _probe_lmstudio_models(url)
    if not models:
        return None
    want = model.strip().lower()
    for m in models:
        if not isinstance(m, dict):
            continue
        names = {str(m.get("key", "")).lower(), str(m.get("display_name", "")).lower()}
        if want in names:
            caps = m.get("capabilities")
            if isinstance(caps, dict) and "vision" in caps:
                return bool(caps.get("vision"))
            return None
    return None


# ── `B970`: the provider's own answer, read through the capability readers ──
#
# `src/model_capability_readers/` parse what a provider says about a model and
# had no production caller: `model_supports_vision` asked LM Studio, then the
# name list, so an Ollama model reporting `vision` or an OpenRouter model whose
# catalogue lists image input decided nothing. The readers do no network I/O by
# design (`base.py`); the fetching is here, beside the LM Studio probe it
# extends, and each answer is read by the vendor's reader and then by the one
# reading of "can it see" (`model_capabilities.vision_verdict`).
#
# Who is asked, and why only them (`Law 16` — every call goes to the endpoint
# the person configured, only when there is a picture to decide about, and
# through `paced_http`, so `OutboundHostLimiter` paces it):
#   * Ollama — `POST /api/show` on an endpoint the readers' own `detect_vendor`
#     calls Ollama (port 11434 or ollama.com). An Ollama too old to list
#     `capabilities` says nothing, and the name list decides as before.
#   * OpenRouter — its public catalogue (`/api/v1/models`, no key sent), cached
#     for an hour; a model it does not list says nothing.
# An answer is cached `_PROVIDER_FINGERPRINT_TTL`; a transport failure is not
# (the LM Studio probe's rule) except for the catalogue, whose failure is kept
# for that minute so an offline machine does not wait on it per picture.

_OPENROUTER_CATALOGUE_TTL = 3600.0
# (host, port, model) -> (answer, expiry)
_ollama_show_cache: dict = {}
# catalogue url -> ({model id: answer} | None, expiry)
_openrouter_catalogue_cache: dict = {}


def _vendor_of(url: str) -> str:
    from src.model_capability_readers import detect_vendor
    return detect_vendor(url)


def _authority(parsed) -> str:
    host = parsed.hostname or ""
    if ":" in host:          # an IPv6 literal
        host = f"[{host}]"
    return host if parsed.port is None else f"{host}:{parsed.port}"


def ollama_supports_vision(url: str, model: str) -> Optional[bool]:
    """What Ollama's `/api/show` says about `model`'s `vision` capability, read
    by the Ollama capability reader — or None when the endpoint is not Ollama,
    is unreachable, or does not list capabilities."""
    from src.model_capability_readers import VENDOR_OLLAMA
    if not model or _vendor_of(url) != VENDOR_OLLAMA:
        return None
    parsed = urlparse(url)
    key = (parsed.hostname, parsed.port, model.strip())
    now = time.time()
    cached = _ollama_show_cache.get(key)
    if cached is not None and cached[1] > now:
        return cached[0]
    from src import paced_http
    show_url = f"{parsed.scheme or 'http'}://{_authority(parsed)}/api/show"
    try:
        r = paced_http.post_sync(show_url, json={"model": model.strip()}, timeout=2.0,
                                 headers=_probe_auth_headers(url) or None)
    except Exception:
        return None
    try:
        payload = r.json() if r.is_success else {}
    except Exception:
        payload = {}
    answer = None
    if isinstance(payload, dict):
        # The reader is the one parser (`Law 14`): a payload with no
        # `capabilities` list is an unknown family to it, so None.
        from src.model_capabilities import vision_verdict
        from src.model_capability_readers import ollama as ollama_reader
        record = ollama_reader.record_from_show_payload(model.strip(), payload)
        answer = vision_verdict(record.capability) if record else None
    _ollama_show_cache[key] = (answer, now + _PROVIDER_FINGERPRINT_TTL)
    return answer


def _openrouter_answers(url: str) -> Optional[dict]:
    """`{model id (lower case): answer}` from OpenRouter's catalogue, or None."""
    parsed = urlparse(url)
    catalogue = f"{parsed.scheme or 'https'}://{_authority(parsed)}/api/v1/models"
    now = time.time()
    cached = _openrouter_catalogue_cache.get(catalogue)
    if cached is not None and cached[1] > now:
        return cached[0]
    from src import paced_http
    answers = None
    try:
        r = paced_http.get_sync(catalogue, timeout=5.0)
        payload = r.json() if r.is_success else None
    except Exception:
        payload = None
    if isinstance(payload, dict):
        from src.model_capabilities import vision_verdict
        from src.model_capability_readers import openrouter as openrouter_reader
        answers = {
            rec.model_id.lower(): vision_verdict(rec.capability)
            for rec in openrouter_reader.records_from_payload(payload)
        }
    ttl = _OPENROUTER_CATALOGUE_TTL if answers is not None else _PROVIDER_FINGERPRINT_TTL
    _openrouter_catalogue_cache[catalogue] = (answers, now + ttl)
    return answers


def openrouter_supports_vision(url: str, model: str) -> Optional[bool]:
    """Whether OpenRouter's catalogue lists image input for `model` (read by
    the OpenRouter capability reader), or None when the endpoint is not
    OpenRouter or the catalogue does not name the model. A variant id
    (`…:free`, `…:online`) is answered by its base model's entry when the
    catalogue has no entry of its own."""
    from src.model_capability_readers import VENDOR_OPENROUTER
    if not model or _vendor_of(url) != VENDOR_OPENROUTER:
        return None
    answers = _openrouter_answers(url)
    if not answers:
        return None
    want = model.strip().lower()
    if want in answers:
        return answers[want]
    return answers.get(want.split(":", 1)[0])


# ── `B991`: llama.cpp's own answer, from `/props` ─────────────────────────────
#
# llama-server started with a projector (`--mmproj`) says so on `GET /props`:
# `modalities: {"vision": true, "audio": …}`. A server older than that field
# (before libmtmd, 2025) says nothing about pictures, and the `llamacpp` reader
# reads a payload without it as text-only — so the probe answers ONLY when
# `modalities.vision` is there and is a boolean, and leaves everything else to
# the name list, which is what decided before (`B970`'s rule: *nothing said*
# falls back). Three more conditions, each a way the answer would be about
# something else:
#   * a local host only (`_is_local_host`, the LM Studio probe's rule) — a
#     llama-server is the operator's own machine, and `Law 16` says a cloud
#     endpoint is asked nothing it was not asked before;
#   * an endpoint the readers' `detect_vendor` calls llama.cpp or a generic
#     OpenAI-compatible server — llama-server's default port (8080) is not one
#     it knows, and Ollama, LM Studio, vLLM and SGLang have their own ports and
#     no `/props`;
#   * the model the answer describes is the one asked about (`model_alias`, or
#     `model_path` whole, by file name or by file name without `.gguf`): a
#     router or a proxy in front of several models answers `/props` for one of
#     them, and that answer is not about this one.
# Through `paced_http` (the limiter), with the endpoint's own key as the Ollama
# probe sends it; an answer — a `404` from a server that is not llama.cpp
# included — is cached `_PROVIDER_FINGERPRINT_TTL`, a transport failure is not.

# (host, port, model) -> (answer, expiry)
_llamacpp_props_cache: dict = {}


def _llamacpp_names(payload: dict) -> set:
    """The names a `/props` answer goes by, lower case."""
    from pathlib import PurePosixPath
    names = set()
    alias = str(payload.get("model_alias") or "").strip()
    if alias:
        names.add(alias.lower())
    path = str(payload.get("model_path") or "").strip()
    if path:
        name = PurePosixPath(path.replace("\\", "/")).name
        names.update({path.lower(), name.lower()})
        if name.lower().endswith(".gguf"):
            names.add(name[:-5].lower())
    return names


def llamacpp_supports_vision(url: str, model: str) -> Optional[bool]:
    """What llama-server's `/props` says about `model`'s pictures, read by the
    llama.cpp capability reader — or None when the endpoint is not a local
    llama-server, describes another model, or does not report `modalities`."""
    from src.model_capability_readers import VENDOR_GENERIC_OPENAI, VENDOR_LLAMACPP
    if not model:
        return None
    parsed = urlparse(url)
    if not _is_local_host(parsed.hostname):
        return None
    if _vendor_of(url) not in (VENDOR_LLAMACPP, VENDOR_GENERIC_OPENAI):
        return None
    want = model.strip()
    key = (parsed.hostname, parsed.port, want)
    now = time.time()
    cached = _llamacpp_props_cache.get(key)
    if cached is not None and cached[1] > now:
        return cached[0]
    from src import paced_http
    props_url = f"{parsed.scheme or 'http'}://{_authority(parsed)}/props"
    try:
        r = paced_http.get_sync(props_url, timeout=2.0,
                                headers=_probe_auth_headers(url) or None)
    except Exception:
        return None
    try:
        payload = r.json() if r.is_success else None
    except Exception:
        payload = None
    answer = None
    if isinstance(payload, dict) and want.lower() in _llamacpp_names(payload):
        modalities = payload.get("modalities")
        if isinstance(modalities, dict) and isinstance(modalities.get("vision"), bool):
            from src.model_capabilities import vision_verdict
            from src.model_capability_readers import llamacpp as llamacpp_reader
            record = llamacpp_reader.record_from_props_payload(payload)
            answer = vision_verdict(record.capability) if record else None
    _llamacpp_props_cache[key] = (answer, now + _PROVIDER_FINGERPRINT_TTL)
    return answer


def endpoint_supports_vision(endpoint_url: str, model_name: str) -> Optional[bool]:
    """The endpoint's own answer to "can this model see", or None when it gives
    none: LM Studio's model list, Ollama's `/api/show`, OpenRouter's catalogue,
    asked in that order (`B970`), then llama-server's `/props` (`B991`)."""
    for ask in (lmstudio_supports_vision, ollama_supports_vision, openrouter_supports_vision,
                llamacpp_supports_vision):
        try:
            answer = ask(endpoint_url, model_name or "")
        except Exception:
            answer = None
        if answer is not None:
            return answer
    return None


def vision_answer(model_name: str, endpoint_url: str = "") -> Optional[bool]:
    """Whether a model accepts images, as far as anything that knows has said:
    the endpoint's own answer where it gives one (`endpoint_supports_vision` —
    LM Studio, Ollama, OpenRouter, llama.cpp), True where the name list names a
    family that sees, and None — unknown — otherwise.

    fx5-vision (`B-NEW-2`). A name the list does not know is not a model that
    cannot see: `D-2026-10-07-02` §1 rules out deciding what a model is from a
    list written in the code, and a person's picture was swapped for the line
    *"[No vision model configured — set one in Settings → Vision]"* on exactly
    that guess (measured on `0345288`: a model listed as `text-box-7b` on a
    server that says nothing about pictures was sent none)."""
    if endpoint_url:
        advertised = endpoint_supports_vision(endpoint_url, model_name or "")
        if advertised is not None:
            return advertised
    return True if is_vision_model(model_name) else None


def model_supports_vision(model_name: str, endpoint_url: str = "") -> bool:
    """Whether a model accepts images: the endpoint's own answer where it gives
    one (`endpoint_supports_vision` — LM Studio, Ollama, OpenRouter, llama.cpp),
    the name list otherwise. The question a tool's picture asks
    (`src/tool_result_images.py`); a person's own attachment asks
    `vision_answer`, which sends the picture when nothing knows (fx5-vision)."""
    return bool(vision_answer(model_name, endpoint_url))


def validate_message(message: str) -> str:
    """Validate message input."""
    if not message:
        raise HTTPException(status_code=400, detail="Message is required")

    message = message.strip()
    if len(message) == 0:
        raise HTTPException(status_code=400, detail="Message cannot be empty")

    if len(message) > 50000:
        raise HTTPException(status_code=400, detail="Message too long.")

    return message


# NOTE (P2-04): `validate_file_upload(file)` used to live here. It advertised a
# 19-extension allowlist and an "UNSUPPORTED_FILE_TYPE" error shape that no route
# ever enforced — the live chat upload path is routes/upload_routes.py, which calls
# UploadHandler.save_upload directly. Its only two references in the whole tree were
# an import and a call inside tests/test_chat_upload_limit_config.py, so it validated
# nothing but itself. Deleted rather than wired in: the checks that actually run are
# UploadHandler.save_upload's empty-file check and the PANTHEON_CHAT_UPLOAD_MAX_BYTES
# cap (src/upload_limits.py), which that test still pins through the live path.


def coerce_message_and_session(req_json: dict | None, message: str | None,
                               session: str | None, session_manager,
                               allow_empty: bool = False):
    """Extract message and session from request, with validation.

    If allow_empty=True (e.g. attachment-only sends), the message-required
    check is skipped and an empty/whitespace message is normalized to "".
    """
    try:
        if message is None or session is None:
            if req_json is None:
                raise HTTPException(
                    status_code=400,
                    detail={
                        "error": "MISSING_PARAMETERS",
                        "message": "Missing 'message' and/or 'session' in request"
                    }
                )
            message = message or req_json.get("message")
            session = session or req_json.get("session")

        if allow_empty and (message is None or not str(message).strip()):
            message = ""
        else:
            message = validate_message(message)

        if not session:
            raise HTTPException(
                status_code=400,
                detail={
                    "error": "VALIDATION_ERROR",
                    "message": "Session ID is required"
                }
            )
        try:
            session_manager.get_session(session)
        except KeyError:
            raise HTTPException(
                status_code=404,
                detail={
                    "error": "SESSION_NOT_FOUND",
                    "message": "That chat no longer exists."
                }
            )

        return message, session
    except HTTPException:
        raise
    except json.JSONDecodeError as e:
        logger.error(f"JSON decode error: {e}")
        raise HTTPException(
            status_code=400,
            detail={
                "error": "INVALID_JSON",
                "message": "Invalid JSON in request body"
            }
        )
    except Exception as e:
        logger.error(f"Unexpected error in coerce_message_and_session: {e}")
        raise HTTPException(
            status_code=400,
            detail={
                "error": "REQUEST_PROCESSING_ERROR",
                "message": "Error processing request"
            }
        )
