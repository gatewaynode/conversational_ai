"""POST /v1/stt — audio file to transcribed text."""

from __future__ import annotations

import asyncio
import logging
from pathlib import Path

from fastapi import APIRouter, HTTPException, Request, UploadFile

from src.audio import save_temp_audio, validate_audio_upload
from src.schemas import STTResponse

router = APIRouter()
logger = logging.getLogger(__name__)

# Allowlist of extensions accepted for temp file creation.
# Derived from the same set as _ALLOWED_AUDIO_MIMES in src/audio.py.
_AUDIO_SUFFIXES = {".wav", ".mp3", ".mp4", ".ogg", ".flac", ".webm", ".aac", ".m4a"}


@router.post("/stt", response_model=STTResponse)
async def transcribe(file: UploadFile, request: Request) -> STTResponse:
    """Accept an audio file and return the transcribed text.

    The file size limit is checked against the configurable maximum and
    quoted in any rejection error.
    """
    settings = request.app.state.settings
    model_manager = request.app.state.model_manager

    if not model_manager.stt_loaded:
        raise HTTPException(status_code=503, detail="STT model is not loaded.")

    max_size = settings.limits.max_audio_file_size
    audio_bytes = await validate_audio_upload(file, max_size)

    # Derive suffix from the upload filename only if it is a known audio extension;
    # otherwise default to .wav.  This prevents arbitrary extensions (e.g. .php, .py)
    # from being used as the temp-file suffix.
    suffix = ".wav"
    if file.filename:
        candidate = Path(file.filename).suffix.lower()
        if candidate in _AUDIO_SUFFIXES:
            suffix = candidate

    temp_path = save_temp_audio(audio_bytes, suffix=suffix)
    try:
        output = await asyncio.to_thread(model_manager.generate_stt, temp_path)
    except Exception as exc:
        logger.exception("STT inference failed")
        raise HTTPException(status_code=500, detail="STT inference failed.") from exc
    finally:
        temp_path.unlink(missing_ok=True)

    return STTResponse(
        text=output.text,
        segments=output.segments or None,
        language=output.language or None,
    )
