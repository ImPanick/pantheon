# SPDX-License-Identifier: AGPL-3.0-or-later
# routes/tts_routes.py
"""
TTS API routes — multi-provider (Kokoro, Chatterbox, Piper, local Kokoro on a
GPU, API endpoint, browser), in the voice each person chose for themselves.
"""

from typing import Optional

from fastapi import APIRouter, HTTPException, Request
from fastapi.responses import Response
from pydantic import BaseModel
import asyncio
import logging

from core.middleware import require_operator
from src.auth_helpers import get_current_user
from src.env_flags import request_flag

logger = logging.getLogger(__name__)

class TTSRequest(BaseModel):
    text: str
    format: str = "audio"  # "audio" or "base64"
    # `B1730`. A voice to hear instead of the person's own, for Settings →
    # Conversation's "Hear it" before they keep it. All three or none.
    engine: Optional[str] = None
    voice: Optional[str] = None
    speed: Optional[float] = None

def setup_tts_routes(tts_service):
    """Setup TTS routes with the provided TTS service"""
    router = APIRouter(prefix="/api/tts", tags=["tts"])

    # `B1730`. A service that speaks in each person's own voice; a stand-in
    # without it (a test's) is asked as before.
    personal = callable(getattr(tts_service, "personal_voices", None))

    def _choice_of(request: Request, asked: Optional[TTSRequest] = None):
        """The voice this person hears: the one a preview asks for, else the
        one they chose (`services/tts/personal_voice.py`), else `None`, the
        server's."""
        from services.tts import personal_voice
        if asked is not None and (asked.engine is not None or asked.voice is not None
                                  or asked.speed is not None):
            return personal_voice.checked_voice(
                {"engine": asked.engine or "", "voice": asked.voice or "", "speed": asked.speed})
        return personal_voice.choice_for(get_current_user(request))

    @router.get("/stats")
    async def get_tts_stats(request: Request):
        """Get TTS service statistics: what this person will hear. `?for=server`
        is the server's own voice (Settings → Voice); `?warm=1` loads the
        voice now, for a page about to be spoken to (a voice call, or the
        Conversation switch turned on)."""
        try:
            # `B1717`. Off the event loop: asking about Kokoro builds its
            # pipeline, and asking about Piper reads the voice folders.
            if not personal:
                return await asyncio.to_thread(tts_service.get_stats)
            server = request.query_params.get("for") == "server"
            warm = request_flag(request.query_params.get("warm"))

            def _stats():
                from services.tts import personal_voice
                user = get_current_user(request)
                choice = None if server else personal_voice.choice_for(user)
                warmed = warm or (not server and personal_voice.conversation_on(user))
                return tts_service.get_stats(choice=choice, warm=warmed)

            return await asyncio.to_thread(_stats)
        except Exception as e:
            logger.error(f"Failed to get TTS stats: {e}")
            raise HTTPException(status_code=500, detail=str(e))

    @router.get("/voices")
    async def get_tts_voices():
        """`B1730`. The voices a person may choose for their own (Settings →
        Conversation): each engine on this server, whether it speaks here now
        and why not, and the server's voice they hear when they choose none."""
        if not personal:
            raise HTTPException(status_code=404, detail="This server has no voices to choose.")
        try:
            return await asyncio.to_thread(tts_service.personal_voices)
        except Exception as e:
            logger.error(f"Failed to list TTS voices: {e}")
            raise HTTPException(status_code=500, detail=str(e))

    @router.post("/synthesize")
    async def synthesize_speech(request: TTSRequest, http: Request):
        """Synthesize speech from text"""
        # `B1717`. What this server says when it cannot speak: why, when it
        # knows (the voice call shows it rather than going quiet).
        def _said(default: str) -> str:
            ask = getattr(tts_service, "failure_reason", None)
            return (ask() if callable(ask) else None) or default

        try:
            choice = None
            if personal:
                choice = await asyncio.to_thread(_choice_of, http, request)
                if choice and choice.get("engine") == "browser" and request.engine:
                    raise HTTPException(status_code=400, detail={
                        "message": "The browser's own voices speak in the browser, not on this server."})
            # `B1717`. Asked, and spoken, in a worker thread: synthesis ran on
            # the server's event loop, so every sentence a voice call spoke
            # stopped every other request for as long as it took.
            speaks = ((lambda: tts_service.can_speak(choice)) if personal
                      else (lambda: tts_service.available))
            if not await asyncio.to_thread(speaks):
                ask = getattr(tts_service, "unavailable_reason", None)
                if callable(ask):
                    reason = await asyncio.to_thread(ask, choice) if personal else await asyncio.to_thread(ask)
                else:
                    reason = None
                raise HTTPException(
                    status_code=503,
                    detail={"message": reason or "TTS service not available"}
                )

            if request.format == "base64":
                audio_b64 = await asyncio.to_thread(
                    (lambda: tts_service.synthesize_to_base64(request.text, choice=choice)) if choice
                    else (lambda: tts_service.synthesize_to_base64(request.text)))
                if not audio_b64:
                    raise HTTPException(
                        status_code=500,
                        detail={"message": _said("Synthesis failed")}
                    )
                return {"audio": audio_b64}
            
            else:  # audio format
                audio_data = await asyncio.to_thread(
                    (lambda: tts_service.synthesize(request.text, choice=choice)) if choice
                    else (lambda: tts_service.synthesize(request.text)))
                if not audio_data:
                    raise HTTPException(
                        status_code=500,
                        detail={"message": _said("Synthesis failed")}
                    )
                
                # Detect format from magic bytes (MP3: ID3 tag or sync word ff e0+)
                is_mp3 = audio_data[:3] == b'ID3' or (len(audio_data) >= 2 and audio_data[0] == 0xff and (audio_data[1] & 0xe0) == 0xe0)
                mime = "audio/mpeg" if is_mp3 else "audio/wav"
                headers = {
                    "Content-Disposition": "inline; filename=speech.mp3" if "mpeg" in mime else "inline; filename=speech.wav"
                }
                spoke = getattr(tts_service, "voice_for", None)
                if callable(spoke):
                    # `B1730`. Which voice spoke (engine/voice), for the page
                    # and for anyone checking which one they hear.
                    try:
                        headers["X-Pantheon-Voice"] = (await asyncio.to_thread(spoke, choice)).encode(
                            "ascii", "replace").decode("ascii")
                    except Exception:
                        pass
                return Response(
                    content=audio_data,
                    media_type=mime,
                    headers=headers,
                )
        
        except HTTPException:
            raise
        except Exception as e:
            logger.error(f"Synthesis error: {e}", exc_info=True)
            raise HTTPException(
                status_code=500,
                detail={"message": f"Synthesis failed: {str(e)}"}
            )

    @router.post("/clear-cache")
    async def clear_tts_cache(request: Request):
        """Clear TTS cache"""
        # `B540`. The cache is one directory for the whole instance — a clip
        # is keyed by text, provider, model, voice and speed
        # (`TTSService._cache_key`), never by person — so clearing it discards
        # every user's audio at once. Measured 2026-10-02 against the real app
        # with `AUTH_ENABLED=true`: a signed-in non-admin got 200 and the
        # cache was emptied, while the same act on uploads
        # (`POST /api/upload/cleanup`) is `require_admin`. An owner scope is
        # not available instead: nothing records whose clip is whose. The one
        # caller in the product clears it after a change of model, voice or
        # speed has made the old clips unreachable — `saveAndClearCache` in
        # `static/js/settings.js`, which first writes `POST /api/auth/settings`,
        # an admin write. So whoever may change the voice may throw away the
        # clips made with the old one, and nobody else. `B683`: the operator
        # tier's gate, `require_operator` — an admin, or a person an admin let
        # run the instance.
        require_operator(request)
        try:
            tts_service.clear_cache()
            return {"success": True, "message": "Cache cleared"}
        except Exception as e:
            logger.error(f"Failed to clear cache: {e}")
            raise HTTPException(status_code=500, detail=str(e))

    return router
