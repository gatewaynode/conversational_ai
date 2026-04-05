"""Tests for src/audio.py — WAV encoding, upload validation, temp files."""

from __future__ import annotations

import io
import wave
from dataclasses import dataclass, field
from pathlib import Path
from unittest.mock import AsyncMock

import numpy as np
import pytest
from fastapi import HTTPException, UploadFile

from src.audio import save_temp_audio, tts_result_to_wav_bytes, validate_audio_upload


# ---------------------------------------------------------------------------
# Helpers / fake dataclasses
# ---------------------------------------------------------------------------


@dataclass
class FakeGenerationResult:
    """Minimal stand-in for mlx_audio.tts.models.base.GenerationResult."""

    audio: object  # numpy array (avoids mlx dependency in tests)
    samples: int
    sample_rate: int
    segment_idx: int = 0
    token_count: int = 0
    audio_duration: str = "00:00:01.000"
    real_time_factor: float = 1.0
    prompt: dict = field(default_factory=dict)
    audio_samples: dict = field(default_factory=dict)
    processing_time_seconds: float = 0.0
    peak_memory_usage: float = 0.0
    is_streaming_chunk: bool = False
    is_final_chunk: bool = False


def _sine_array(duration: float = 0.5, sample_rate: int = 24_000) -> np.ndarray:
    """Generate a simple sine-wave as a float32 numpy array."""
    t = np.linspace(0, duration, int(duration * sample_rate), endpoint=False)
    return (np.sin(2 * np.pi * 440 * t)).astype(np.float32)


def _fake_result(
    duration: float = 0.5, sample_rate: int = 24_000
) -> FakeGenerationResult:
    audio = _sine_array(duration, sample_rate)
    return FakeGenerationResult(
        audio=audio,
        samples=len(audio),
        sample_rate=sample_rate,
    )


def _parse_wav(data: bytes) -> tuple[int, int, int]:
    """Return (nchannels, sample_rate, nframes) from WAV bytes."""
    with wave.open(io.BytesIO(data)) as wf:
        return wf.getnchannels(), wf.getframerate(), wf.getnframes()


def _make_upload_file(data: bytes, content_type: str = "audio/wav") -> UploadFile:
    """Build a minimal UploadFile-like object for testing."""
    mock = AsyncMock(spec=UploadFile)
    mock.content_type = content_type
    mock.read = AsyncMock(return_value=data)
    return mock


# ---------------------------------------------------------------------------
# tts_result_to_wav_bytes
# ---------------------------------------------------------------------------


def test_single_chunk_produces_valid_wav() -> None:
    result = _fake_result(duration=0.5)
    wav = tts_result_to_wav_bytes([result])

    assert wav[:4] == b"RIFF", "WAV must start with RIFF header"
    channels, rate, frames = _parse_wav(wav)
    assert rate == 24_000
    assert channels == 1
    assert frames > 0


def test_multiple_chunks_concatenated() -> None:
    r1 = _fake_result(duration=0.25)
    r2 = _fake_result(duration=0.25)
    single = _fake_result(duration=0.5)

    wav_two = tts_result_to_wav_bytes([r1, r2])
    wav_one = tts_result_to_wav_bytes([single])

    _, _, frames_two = _parse_wav(wav_two)
    _, _, frames_one = _parse_wav(wav_one)

    # Two 0.25s chunks should produce roughly the same frame count as one 0.5s chunk
    assert abs(frames_two - frames_one) <= 10


def test_empty_results_raises() -> None:
    with pytest.raises(ValueError, match="No TTS results"):
        tts_result_to_wav_bytes([])


def test_all_empty_audio_raises() -> None:
    result = FakeGenerationResult(
        audio=np.array([], dtype=np.float32),
        samples=0,
        sample_rate=24_000,
    )
    with pytest.raises(ValueError, match="empty"):
        tts_result_to_wav_bytes([result])


def test_different_sample_rate_respected() -> None:
    audio = _sine_array(0.5, sample_rate=22_050)
    result = FakeGenerationResult(audio=audio, samples=len(audio), sample_rate=22_050)
    wav = tts_result_to_wav_bytes([result])
    _, rate, _ = _parse_wav(wav)
    assert rate == 22_050


# ---------------------------------------------------------------------------
# validate_audio_upload
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_valid_wav_upload_returns_bytes() -> None:
    # Build a real minimal WAV
    buf = io.BytesIO()
    with wave.open(buf, "wb") as wf:
        wf.setnchannels(1)
        wf.setsampwidth(2)
        wf.setframerate(24_000)
        wf.writeframes(b"\x00\x00" * 100)
    data = buf.getvalue()

    upload = _make_upload_file(data, "audio/wav")
    result = await validate_audio_upload(upload, max_size=1_000_000)
    assert result == data


@pytest.mark.asyncio
async def test_rejects_unsupported_mime() -> None:
    upload = _make_upload_file(b"fake data", content_type="text/plain")
    with pytest.raises(HTTPException) as exc_info:
        await validate_audio_upload(upload, max_size=1_000_000)
    assert exc_info.value.status_code == 415


@pytest.mark.asyncio
async def test_rejects_oversized_file() -> None:
    big_data = b"\x00" * 1001
    upload = _make_upload_file(big_data, content_type="audio/wav")
    with pytest.raises(HTTPException) as exc_info:
        await validate_audio_upload(upload, max_size=1000)
    assert exc_info.value.status_code == 413


@pytest.mark.asyncio
async def test_rejects_empty_file() -> None:
    upload = _make_upload_file(b"", content_type="audio/wav")
    with pytest.raises(HTTPException) as exc_info:
        await validate_audio_upload(upload, max_size=1_000_000)
    assert exc_info.value.status_code == 400


@pytest.mark.asyncio
async def test_accepts_octet_stream() -> None:
    """Some browsers send application/octet-stream for .wav files."""
    data = b"\x00" * 100
    upload = _make_upload_file(data, content_type="application/octet-stream")
    result = await validate_audio_upload(upload, max_size=1_000_000)
    assert result == data


# ---------------------------------------------------------------------------
# save_temp_audio
# ---------------------------------------------------------------------------


def test_save_temp_audio_creates_file() -> None:
    data = b"fake audio bytes"
    path = save_temp_audio(data)
    try:
        assert path.exists()
        assert path.read_bytes() == data
        assert path.suffix == ".wav"
    finally:
        path.unlink(missing_ok=True)


def test_save_temp_audio_custom_suffix() -> None:
    path = save_temp_audio(b"data", suffix=".mp3")
    try:
        assert path.suffix == ".mp3"
    finally:
        path.unlink(missing_ok=True)


def test_save_temp_audio_returns_path_object() -> None:
    path = save_temp_audio(b"x")
    try:
        assert isinstance(path, Path)
    finally:
        path.unlink(missing_ok=True)
