"""Tests for all route handlers using FastAPI TestClient with a fake ModelManager."""

from __future__ import annotations

import io
import wave
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any
from unittest.mock import MagicMock

import numpy as np
import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from src.config import Settings
from src.middleware import LimitsHeaderMiddleware
from src.routes.stt import router as stt_router
from src.routes.system import router as system_router
from src.routes.tts import router as tts_router


# ---------------------------------------------------------------------------
# Fake model manager
# ---------------------------------------------------------------------------


@dataclass
class FakeGenerationResult:
    audio: Any
    samples: int
    sample_rate: int = 24_000
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


@dataclass
class FakeSTTOutput:
    text: str
    segments: list[dict] | None = None
    language: str | None = None


def _sine(duration: float = 0.5, sr: int = 24_000) -> np.ndarray:
    t = np.linspace(0, duration, int(duration * sr), endpoint=False)
    return np.sin(2 * np.pi * 440 * t).astype(np.float32)


class FakeModelManager:
    def __init__(
        self,
        tts_loaded: bool = True,
        stt_loaded: bool = True,
        tts_name: str = "fake-tts",
        stt_name: str = "fake-stt",
    ) -> None:
        self._tts_loaded = tts_loaded
        self._stt_loaded = stt_loaded
        self._tts_name = tts_name
        self._stt_name = stt_name

    @property
    def tts_loaded(self) -> bool:
        return self._tts_loaded

    @property
    def stt_loaded(self) -> bool:
        return self._stt_loaded

    @property
    def tts_model_name(self) -> str | None:
        return self._tts_name if self._tts_loaded else None

    @property
    def stt_model_name(self) -> str | None:
        return self._stt_name if self._stt_loaded else None

    def generate_tts(self, text, voice, speed, lang_code) -> list[FakeGenerationResult]:
        audio = _sine()
        return [FakeGenerationResult(audio=audio, samples=len(audio))]

    def generate_stt(self, audio_path) -> FakeSTTOutput:
        return FakeSTTOutput(text="Hello, can you hear me?", language="en")


# ---------------------------------------------------------------------------
# App factory
# ---------------------------------------------------------------------------


def _make_app(
    tts_loaded: bool = True,
    stt_loaded: bool = True,
    max_text: int = 5000,
    max_audio: int = 26_214_400,
) -> FastAPI:
    app = FastAPI()
    app.state.settings = Settings(
        limits={"max_text_length": max_text, "max_audio_file_size": max_audio}
    )
    app.state.model_manager = FakeModelManager(
        tts_loaded=tts_loaded, stt_loaded=stt_loaded
    )
    app.add_middleware(LimitsHeaderMiddleware)
    app.include_router(tts_router, prefix="/v1")
    app.include_router(stt_router, prefix="/v1")
    app.include_router(system_router, prefix="/v1")
    return app


def _minimal_wav() -> bytes:
    buf = io.BytesIO()
    with wave.open(buf, "wb") as wf:
        wf.setnchannels(1)
        wf.setsampwidth(2)
        wf.setframerate(24_000)
        wf.writeframes(b"\x00\x00" * 1000)
    return buf.getvalue()


# ---------------------------------------------------------------------------
# /v1/health
# ---------------------------------------------------------------------------


def test_health_both_loaded() -> None:
    resp = TestClient(_make_app()).get("/v1/health")
    assert resp.status_code == 200
    data = resp.json()
    assert data["status"] == "ok"
    assert data["tts_loaded"] is True
    assert data["stt_loaded"] is True


def test_health_degraded_tts_only() -> None:
    resp = TestClient(_make_app(stt_loaded=False)).get("/v1/health")
    assert resp.json()["status"] == "degraded"


def test_health_unavailable() -> None:
    resp = TestClient(_make_app(tts_loaded=False, stt_loaded=False)).get("/v1/health")
    assert resp.json()["status"] == "unavailable"


def test_health_has_limit_headers() -> None:
    resp = TestClient(_make_app()).get("/v1/health")
    assert "x-limit-max-text-length" in resp.headers


# ---------------------------------------------------------------------------
# /v1/models
# ---------------------------------------------------------------------------


def test_models_response_shape() -> None:
    resp = TestClient(_make_app()).get("/v1/models")
    assert resp.status_code == 200
    data = resp.json()
    assert data["tts"]["loaded"] is True
    assert data["tts"]["name"] == "fake-tts"
    assert data["stt"]["loaded"] is True


def test_models_not_loaded() -> None:
    resp = TestClient(_make_app(tts_loaded=False, stt_loaded=False)).get("/v1/models")
    data = resp.json()
    assert data["tts"]["loaded"] is False
    assert data["tts"]["name"] is None


# ---------------------------------------------------------------------------
# POST /v1/tts
# ---------------------------------------------------------------------------


def test_tts_returns_wav() -> None:
    resp = TestClient(_make_app()).post("/v1/tts", json={"text": "Hello world"})
    assert resp.status_code == 200
    assert resp.headers["content-type"] == "audio/wav"
    assert resp.content[:4] == b"RIFF"


def test_tts_has_limit_headers() -> None:
    resp = TestClient(_make_app(max_text=1000)).post("/v1/tts", json={"text": "hi"})
    assert resp.headers["x-limit-max-text-length"] == "1000"


def test_tts_uses_request_voice() -> None:
    """Route must pass the request voice through, not the default."""
    captured: dict = {}

    class CapturingManager(FakeModelManager):
        def generate_tts(self, text, voice, speed, lang_code):
            captured.update({"voice": voice, "speed": speed, "lang_code": lang_code})
            return super().generate_tts(text, voice, speed, lang_code)

    app = _make_app()
    app.state.model_manager = CapturingManager()
    TestClient(app).post(
        "/v1/tts", json={"text": "hi", "voice": "af_sky", "speed": 1.5, "lang_code": "b"}
    )
    assert captured["voice"] == "af_sky"
    assert captured["speed"] == 1.5
    assert captured["lang_code"] == "b"


def test_tts_falls_back_to_settings_defaults() -> None:
    captured: dict = {}

    class CapturingManager(FakeModelManager):
        def generate_tts(self, text, voice, speed, lang_code):
            captured.update({"voice": voice, "speed": speed})
            return super().generate_tts(text, voice, speed, lang_code)

    app = _make_app()
    app.state.model_manager = CapturingManager()
    TestClient(app).post("/v1/tts", json={"text": "hi"})
    assert captured["voice"] == "af_heart"  # from default Settings
    assert captured["speed"] == 1.0


def test_tts_rejects_empty_text() -> None:
    resp = TestClient(_make_app()).post("/v1/tts", json={"text": "   "})
    assert resp.status_code == 422


def test_tts_rejects_text_over_config_limit() -> None:
    resp = TestClient(_make_app(max_text=10)).post(
        "/v1/tts", json={"text": "x" * 11}
    )
    assert resp.status_code == 422
    body = resp.json()
    assert "10" in body["detail"]
    assert "X-Limit-Max-Text-Length" in body["detail"]


def test_tts_503_when_model_not_loaded() -> None:
    resp = TestClient(_make_app(tts_loaded=False)).post(
        "/v1/tts", json={"text": "hello"}
    )
    assert resp.status_code == 503


# ---------------------------------------------------------------------------
# POST /v1/stt
# ---------------------------------------------------------------------------


def test_stt_returns_text() -> None:
    wav = _minimal_wav()
    resp = TestClient(_make_app()).post(
        "/v1/stt",
        files={"file": ("test.wav", wav, "audio/wav")},
    )
    assert resp.status_code == 200
    assert resp.json()["text"] == "Hello, can you hear me?"


def test_stt_has_limit_headers() -> None:
    wav = _minimal_wav()
    resp = TestClient(_make_app()).post(
        "/v1/stt",
        files={"file": ("test.wav", wav, "audio/wav")},
    )
    assert "x-limit-max-audio-file-size" in resp.headers


def test_stt_rejects_wrong_mime() -> None:
    resp = TestClient(_make_app()).post(
        "/v1/stt",
        files={"file": ("doc.txt", b"hello", "text/plain")},
    )
    assert resp.status_code == 415


def test_stt_rejects_oversized_file() -> None:
    resp = TestClient(_make_app(max_audio=100)).post(
        "/v1/stt",
        files={"file": ("big.wav", b"\x00" * 200, "audio/wav")},
    )
    assert resp.status_code == 413


def test_stt_503_when_model_not_loaded() -> None:
    wav = _minimal_wav()
    resp = TestClient(_make_app(stt_loaded=False)).post(
        "/v1/stt",
        files={"file": ("test.wav", wav, "audio/wav")},
    )
    assert resp.status_code == 503


def test_stt_unknown_extension_falls_back_to_wav() -> None:
    """Files with non-audio extensions (.xyz) must use .wav as the temp suffix."""
    used_suffixes: list[str] = []
    original_save = __import__("src.audio", fromlist=["save_temp_audio"]).save_temp_audio

    def tracking_save(data: bytes, suffix: str = ".wav") -> Path:
        used_suffixes.append(suffix)
        return original_save(data, suffix)

    import src.routes.stt as stt_module
    original = stt_module.save_temp_audio
    stt_module.save_temp_audio = tracking_save
    try:
        TestClient(_make_app()).post(
            "/v1/stt",
            files={"file": ("payload.xyz", _minimal_wav(), "audio/wav")},
        )
    finally:
        stt_module.save_temp_audio = original

    assert used_suffixes == [".wav"], f"Expected .wav fallback, got {used_suffixes}"


def test_stt_known_extension_is_preserved() -> None:
    """Files with a known audio extension (.mp3) must keep that suffix."""
    used_suffixes: list[str] = []
    original_save = __import__("src.audio", fromlist=["save_temp_audio"]).save_temp_audio

    def tracking_save(data: bytes, suffix: str = ".wav") -> Path:
        used_suffixes.append(suffix)
        return original_save(data, suffix)

    import src.routes.stt as stt_module
    original = stt_module.save_temp_audio
    stt_module.save_temp_audio = tracking_save
    try:
        TestClient(_make_app()).post(
            "/v1/stt",
            files={"file": ("clip.mp3", _minimal_wav(), "audio/mpeg")},
        )
    finally:
        stt_module.save_temp_audio = original

    assert used_suffixes == [".mp3"], f"Expected .mp3, got {used_suffixes}"


def test_tts_inference_error_returns_500() -> None:
    """An unhandled exception from the model must return 500, not leak a traceback."""

    class BrokenTTSManager(FakeModelManager):
        def generate_tts(self, text, voice, speed, lang_code):
            raise RuntimeError("GPU out of memory")

    app = _make_app()
    app.state.model_manager = BrokenTTSManager()
    resp = TestClient(app).post("/v1/tts", json={"text": "hello"})
    assert resp.status_code == 500
    body = resp.json()
    assert "GPU" not in body.get("detail", "")  # internals must not leak
    assert "inference failed" in body["detail"].lower()


def test_stt_inference_error_returns_500() -> None:
    """An unhandled exception from the STT model must return 500."""

    class BrokenSTTManager(FakeModelManager):
        def generate_stt(self, audio_path):
            raise RuntimeError("Tokenizer not loaded")

    app = _make_app()
    app.state.model_manager = BrokenSTTManager()
    resp = TestClient(app).post(
        "/v1/stt",
        files={"file": ("test.wav", _minimal_wav(), "audio/wav")},
    )
    assert resp.status_code == 500
    body = resp.json()
    assert "Tokenizer" not in body.get("detail", "")  # internals must not leak
    assert "inference failed" in body["detail"].lower()


def test_stt_cleans_up_temp_file() -> None:
    """Temp file must be deleted after transcription completes."""
    created: list[Path] = []
    original_save = __import__("src.audio", fromlist=["save_temp_audio"]).save_temp_audio

    def tracking_save(data: bytes, suffix: str = ".wav") -> Path:
        p = original_save(data, suffix)
        created.append(p)
        return p

    import src.routes.stt as stt_module
    original = stt_module.save_temp_audio
    stt_module.save_temp_audio = tracking_save
    try:
        TestClient(_make_app()).post(
            "/v1/stt",
            files={"file": ("test.wav", _minimal_wav(), "audio/wav")},
        )
    finally:
        stt_module.save_temp_audio = original

    assert created, "save_temp_audio was never called"
    for p in created:
        assert not p.exists(), f"Temp file not cleaned up: {p}"
