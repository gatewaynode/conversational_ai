"""POST /v1/stt — audio file to transcribed text."""

from __future__ import annotations

import asyncio

from fastapi import APIRouter, HTTPException, Request, UploadFile

from src.audio import save_temp_audio, validate_audio_upload
from src.schemas import STTResponse

router = APIRouter()


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

    # Detect suffix from upload filename; fall back to .wav
    suffix = ".wav"
    if file.filename:
        from pathlib import Path
        suffix = Path(file.filename).suffix or ".wav"

    temp_path = save_temp_audio(audio_bytes, suffix=suffix)
    try:
        output = await asyncio.to_thread(model_manager.generate_stt, temp_path)
    finally:
        temp_path.unlink(missing_ok=True)

    return STTResponse(
        text=output.text,
        segments=output.segments or None,
        language=output.language or None,
    )
