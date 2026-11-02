# SPDX-License-Identifier: AGPL-3.0-or-later
# routes/stt_routes.py
"""STT API routes — multi-provider (local Whisper, API endpoint, browser)."""

from fastapi import APIRouter, HTTPException, Request, UploadFile, File
import asyncio
import logging

from src.upload_limits import read_upload_limited, resolve_byte_limit

logger = logging.getLogger(__name__)


def setup_stt_routes(stt_service):
    """Setup STT routes with the provided STT service"""
    router = APIRouter(prefix="/api/stt", tags=["stt"])

    @router.get("/stats")
    async def get_stt_stats():
        """Get STT service statistics.

        `B1716`. Off the event loop: asking whether local Whisper can start
        reads the model cache and the settings file, and every other request
        waited behind it (`STTService.get_stats` no longer loads the model
        here; it starts loading it in the background and says `loading`)."""
        try:
            return await asyncio.to_thread(stt_service.get_stats)
        except Exception as e:
            logger.error(f"Failed to get STT stats: {e}")
            raise HTTPException(status_code=500, detail=str(e))

    @router.post("/transcribe")
    async def transcribe_audio(request: Request, file: UploadFile = File(...)):
        """Transcribe uploaded audio file to text"""
        from src.auth_helpers import get_current_user
        try:
            # `B1716`. Asked off the event loop, like the transcription: for
            # local Whisper the answer reads the model cache.
            if not await asyncio.to_thread(lambda: stt_service.available):
                # `B1565`. When the download gate is why, say so: the voice
                # recorder shows `detail.message` as it is.
                reason = await asyncio.to_thread(getattr(stt_service, "unavailable_reason", lambda: None))
                raise HTTPException(
                    status_code=503,
                    detail={"message": reason or "STT service not available or set to browser mode"}
                )

            # `B932`. The cap is the caller's: `P12-01`'s chain asks the role
            # provider about the person uploading, and with no owner it asked
            # about nobody, so a role could never limit this route.
            audio_bytes = await read_upload_limited(
                file, resolve_byte_limit("stt_max_audio_bytes", get_current_user(request)),
                "Audio file")
            if not audio_bytes:
                raise HTTPException(status_code=400, detail={"message": "Empty audio file"})

            # `B1716`. In a worker thread. Whisper ran on the server's event
            # loop — the whole app stood still for every recording, the first
            # one also waiting for the model to load — and a voice call sends
            # one a turn. The name it came with goes along for the endpoint
            # (`sniff_audio_format`).
            text = await asyncio.to_thread(stt_service.transcribe, audio_bytes, file.filename or "")
            if text is None:
                # A model that would not start says so as it did before the
                # transcription was asked (`B1565`); a transcription that
                # failed says how (`B1579`'s sentence), not just that it did.
                reason = await asyncio.to_thread(getattr(stt_service, "unavailable_reason", lambda: None))
                if reason:
                    raise HTTPException(status_code=503, detail={"message": reason})
                said = await asyncio.to_thread(getattr(stt_service, "unheard_reason", lambda: None))
                raise HTTPException(
                    status_code=500,
                    detail={"message": said or "Transcription failed"}
                )

            return {"text": text}

        except HTTPException:
            raise
        except Exception as e:
            logger.error(f"Transcription error: {e}", exc_info=True)
            raise HTTPException(
                status_code=500,
                detail={"message": f"Transcription failed: {str(e)}"}
            )

    return router
