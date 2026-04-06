"""Audio utilities: WAV encoding, upload validation, temp file management."""

from __future__ import annotations

import io
import tempfile
from pathlib import Path
from typing import TYPE_CHECKING

import numpy as np
from fastapi import HTTPException, UploadFile

if TYPE_CHECKING:
    from mlx_audio.tts.models.base import GenerationResult

# MIME types accepted for audio uploads
_ALLOWED_AUDIO_MIMES = {
    "audio/wav",
    "audio/wave",
    "audio/x-wav",
    "audio/mpeg",
    "audio/mp3",
    "audio/mp4",
    "audio/ogg",
    "audio/flac",
    "audio/x-flac",
    "audio/webm",
    "audio/aac",
}


def tts_result_to_wav_bytes(results: list[GenerationResult]) -> bytes:
    """Concatenate TTS GenerationResult chunks and encode as WAV bytes.

    Args:
        results: List of GenerationResult objects from model.generate().

    Returns:
        WAV-encoded audio as bytes.

    Raises:
        ValueError: If results is empty or all audio chunks are empty.
    """
    from mlx_audio.audio_io import write as audio_write

    if not results:
        raise ValueError("No TTS results to encode")

    # Collect non-empty audio chunks; GenerationResult.audio is an mx.array
    chunks: list[np.ndarray] = []
    sample_rate: int = 24_000  # sensible default; overwritten from results

    for result in results:
        if result.audio is None or result.samples == 0:
            continue
        sample_rate = result.sample_rate
        # mx.array -> numpy: audio_write handles this, but we need numpy for concat
        arr = np.asarray(result.audio.tolist(), dtype=np.float32)
        if arr.ndim > 1:
            arr = arr.flatten()
        chunks.append(arr)

    if not chunks:
        raise ValueError("All TTS audio chunks were empty")

    audio_data = np.concatenate(chunks) if len(chunks) > 1 else chunks[0]

    buf = io.BytesIO()
    audio_write(buf, audio_data, samplerate=sample_rate, format="wav")
    return buf.getvalue()


async def validate_audio_upload(file: UploadFile, max_size: int) -> bytes:
    """Read and validate an uploaded audio file.

    Checks content type and file size, then returns the raw bytes.

    Args:
        file: FastAPI UploadFile from a multipart POST.
        max_size: Maximum allowed file size in bytes.

    Returns:
        The raw file bytes.

    Raises:
        HTTPException 415: If the content type is not an allowed audio type.
        HTTPException 413: If the file exceeds max_size.
    """
    content_type = (file.content_type or "").lower().split(";")[0].strip()
    if content_type not in _ALLOWED_AUDIO_MIMES:
        raise HTTPException(
            status_code=415,
            detail=f"Unsupported media type '{content_type}'. Expected audio/*.",
        )

    data = await file.read()

    if len(data) > max_size:
        raise HTTPException(
            status_code=413,
            detail=f"File too large: {len(data)} bytes (max {max_size}).",
        )

    if len(data) == 0:
        raise HTTPException(status_code=400, detail="Uploaded file is empty.")

    return data


def save_temp_audio(data: bytes, suffix: str = ".wav") -> Path:
    """Write audio bytes to a named temp file and return its path.

    The caller is responsible for deleting the file (use a try/finally block).

    Args:
        data: Raw audio bytes.
        suffix: File extension including the dot (default: ".wav").

    Returns:
        Path to the temporary file.
    """
    with tempfile.NamedTemporaryFile(
        suffix=suffix, delete=False, prefix="stt_upload_"
    ) as tmp:
        tmp.write(data)
        return Path(tmp.name)
