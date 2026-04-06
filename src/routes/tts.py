"""POST /v1/tts — text to WAV audio."""

from __future__ import annotations

import asyncio
import logging

from fastapi import APIRouter, HTTPException, Request, Response

from src.audio import tts_result_to_wav_bytes
from src.schemas import TTSRequest

router = APIRouter()
logger = logging.getLogger(__name__)


@router.post("/tts", response_class=Response)
async def synthesise(body: TTSRequest, request: Request) -> Response:
    """Accept text and return a WAV audio file.

    Voice, speed, and lang_code fall back to server defaults when omitted.
    Text length is checked against the configurable limit (softer than the
    schema's absolute cap) and the active limit is quoted in any error.
    """
    settings = request.app.state.settings
    model_manager = request.app.state.model_manager

    # Config-driven length check — more restrictive than the schema absolute max
    max_len = settings.limits.max_text_length
    if len(body.text) > max_len:
        raise HTTPException(
            status_code=422,
            detail=(
                f"text length {len(body.text)} exceeds the configured maximum of "
                f"{max_len} characters (X-Limit-Max-Text-Length: {max_len})."
            ),
        )

    if not model_manager.tts_loaded:
        raise HTTPException(status_code=503, detail="TTS model is not loaded.")

    voice = body.voice or settings.tts.voice
    speed = body.speed if body.speed is not None else settings.tts.speed
    lang_code = body.lang_code or settings.tts.lang_code

    try:
        results = await asyncio.to_thread(
            model_manager.generate_tts,
            body.text,
            voice,
            speed,
            lang_code,
        )
        wav_bytes = tts_result_to_wav_bytes(results)
    except HTTPException:
        raise
    except Exception as exc:
        logger.exception("TTS inference failed")
        raise HTTPException(status_code=500, detail="TTS inference failed.") from exc

    return Response(
        content=wav_bytes,
        media_type="audio/wav",
        headers={"Content-Disposition": 'attachment; filename="speech.wav"'},
    )
