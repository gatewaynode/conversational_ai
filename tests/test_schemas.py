"""Tests for src/schemas.py — request validation and response shapes."""

from __future__ import annotations

import pytest
from pydantic import ValidationError

from src.schemas import (
    HealthResponse,
    ModelInfo,
    ModelsResponse,
    STTResponse,
    TTSRequest,
)


# ---------------------------------------------------------------------------
# TTSRequest
# ---------------------------------------------------------------------------


def test_tts_request_minimal() -> None:
    r = TTSRequest(text="Hello world")
    assert r.text == "Hello world"
    assert r.voice is None
    assert r.speed is None
    assert r.lang_code is None


def test_tts_request_all_fields() -> None:
    r = TTSRequest(text="Hi", voice="af_sky", speed=1.5, lang_code="a")
    assert r.voice == "af_sky"
    assert r.speed == 1.5
    assert r.lang_code == "a"


def test_tts_request_strips_whitespace() -> None:
    r = TTSRequest(text="  hello  ")
    assert r.text == "hello"


def test_tts_request_empty_text_raises() -> None:
    with pytest.raises(ValidationError, match="empty"):
        TTSRequest(text="")


def test_tts_request_whitespace_only_raises() -> None:
    with pytest.raises(ValidationError, match="empty"):
        TTSRequest(text="   ")


def test_tts_request_over_absolute_max_raises() -> None:
    with pytest.raises(ValidationError, match="absolute maximum"):
        TTSRequest(text="x" * 10_001)


def test_tts_request_at_absolute_max_ok() -> None:
    r = TTSRequest(text="x" * 10_000)
    assert len(r.text) == 10_000


def test_tts_request_speed_too_low_raises() -> None:
    with pytest.raises(ValidationError):
        TTSRequest(text="hi", speed=0.0)


def test_tts_request_speed_too_high_raises() -> None:
    with pytest.raises(ValidationError):
        TTSRequest(text="hi", speed=5.1)


def test_tts_request_speed_boundaries_ok() -> None:
    TTSRequest(text="hi", speed=0.1)
    TTSRequest(text="hi", speed=5.0)


# ---------------------------------------------------------------------------
# STTResponse
# ---------------------------------------------------------------------------


def test_stt_response_minimal() -> None:
    r = STTResponse(text="Hello!")
    assert r.text == "Hello!"
    assert r.segments is None
    assert r.language is None


def test_stt_response_full() -> None:
    segs = [{"start": 0.0, "end": 1.0, "text": "Hello!"}]
    r = STTResponse(text="Hello!", segments=segs, language="en")
    assert r.language == "en"
    assert len(r.segments) == 1


# ---------------------------------------------------------------------------
# ModelInfo / ModelsResponse
# ---------------------------------------------------------------------------


def test_model_info_loaded() -> None:
    m = ModelInfo(name="mlx-community/Kokoro-82M-bf16", loaded=True)
    assert m.loaded is True


def test_model_info_not_loaded() -> None:
    m = ModelInfo(name=None, loaded=False)
    assert m.name is None


def test_models_response_shape() -> None:
    r = ModelsResponse(
        tts=ModelInfo(name="tts-model", loaded=True),
        stt=ModelInfo(name="stt-model", loaded=False),
    )
    assert r.tts.loaded is True
    assert r.stt.loaded is False


# ---------------------------------------------------------------------------
# HealthResponse
# ---------------------------------------------------------------------------


def test_health_response() -> None:
    r = HealthResponse(status="ok", tts_loaded=True, stt_loaded=True)
    assert r.status == "ok"
    assert r.tts_loaded is True


def test_health_response_degraded() -> None:
    r = HealthResponse(status="degraded", tts_loaded=False, stt_loaded=True)
    assert r.status == "degraded"
    assert r.tts_loaded is False


# ---------------------------------------------------------------------------
# Voice and lang_code validation
# ---------------------------------------------------------------------------


def test_tts_request_valid_voice_formats() -> None:
    TTSRequest(text="hi", voice="af_heart")
    TTSRequest(text="hi", voice="en-us-male")
    TTSRequest(text="hi", voice="Speaker1")
    TTSRequest(text="hi", voice="a")


def test_tts_request_voice_with_invalid_chars_raises() -> None:
    with pytest.raises(ValidationError, match="voice"):
        TTSRequest(text="hi", voice="../../evil")


def test_tts_request_voice_too_long_raises() -> None:
    with pytest.raises(ValidationError, match="voice"):
        TTSRequest(text="hi", voice="a" * 65)


def test_tts_request_valid_lang_code_formats() -> None:
    TTSRequest(text="hi", lang_code="a")
    TTSRequest(text="hi", lang_code="en")
    TTSRequest(text="hi", lang_code="en-US")


def test_tts_request_lang_code_with_invalid_chars_raises() -> None:
    with pytest.raises(ValidationError, match="lang_code"):
        TTSRequest(text="hi", lang_code="en_US")  # underscore not allowed


def test_tts_request_lang_code_too_long_raises() -> None:
    with pytest.raises(ValidationError, match="lang_code"):
        TTSRequest(text="hi", lang_code="a" * 11)


def test_tts_request_none_voice_and_lang_code_ok() -> None:
    """None values must still pass — route falls back to config defaults."""
    r = TTSRequest(text="hi", voice=None, lang_code=None)
    assert r.voice is None
    assert r.lang_code is None
