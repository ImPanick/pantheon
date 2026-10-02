# SPDX-License-Identifier: AGPL-3.0-or-later
# routes/tts_routes.py
"""
TTS API routes — multi-provider (local Kokoro, API endpoint, browser).
"""

from fastapi import APIRouter, HTTPException, Request
from fastapi.responses import Response
from pydantic import BaseModel
import logging

from core.middleware import require_admin

logger = logging.getLogger(__name__)

class TTSRequest(BaseModel):
    text: str
    format: str = "audio"  # "audio" or "base64"

def setup_tts_routes(tts_service):
    """Setup TTS routes with the provided TTS service"""
    router = APIRouter(prefix="/api/tts", tags=["tts"])

    @router.get("/stats")
    async def get_tts_stats():
        """Get TTS service statistics"""
        try:
            return tts_service.get_stats()
        except Exception as e:
            logger.error(f"Failed to get TTS stats: {e}")
            raise HTTPException(status_code=500, detail=str(e))

    @router.post("/synthesize")
    async def synthesize_speech(request: TTSRequest):
        """Synthesize speech from text"""
        try:
            if not tts_service.available:
                raise HTTPException(
                    status_code=503,
                    detail={"message": "TTS service not available"}
                )
            
            if request.format == "base64":
                audio_b64 = tts_service.synthesize_to_base64(request.text)
                if not audio_b64:
                    raise HTTPException(
                        status_code=500,
                        detail={"message": "Synthesis failed"}
                    )
                return {"audio": audio_b64}
            
            else:  # audio format
                audio_data = tts_service.synthesize(request.text)
                if not audio_data:
                    raise HTTPException(
                        status_code=500,
                        detail={"message": "Synthesis failed"}
                    )
                
                # Detect format from magic bytes (MP3: ID3 tag or sync word ff e0+)
                is_mp3 = audio_data[:3] == b'ID3' or (len(audio_data) >= 2 and audio_data[0] == 0xff and (audio_data[1] & 0xe0) == 0xe0)
                mime = "audio/mpeg" if is_mp3 else "audio/wav"
                return Response(
                    content=audio_data,
                    media_type=mime,
                    headers={
                        "Content-Disposition": "inline; filename=speech.mp3" if "mpeg" in mime else "inline; filename=speech.wav"
                    }
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
        # clips made with the old one, and nobody else. A no-login install
        # keeps it: `require_admin` returns when auth is off.
        require_admin(request)
        try:
            tts_service.clear_cache()
            return {"success": True, "message": "Cache cleared"}
        except Exception as e:
            logger.error(f"Failed to clear cache: {e}")
            raise HTTPException(status_code=500, detail=str(e))

    return router
