# SPDX-License-Identifier: AGPL-3.0-or-later
# services/tts/__init__.py
"""TTS service — text-to-speech."""

from .tts_service import (
    TTSService,
    get_tts_service,
)

__all__ = ["TTSService", "get_tts_service"]
