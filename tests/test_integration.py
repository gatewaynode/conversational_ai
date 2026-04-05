"""Integration tests: full app assembled via create_app() with a fake ModelManager."""

from __future__ import annotations

import io
import wave
from contextlib import asynccontextmanager
from dataclasses import dataclass, field
from typing import AsyncIterator

import numpy as np
import pytest
from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from fastapi.testclient import TestClient

from src.config import Settings
from src.middleware import LimitsHeaderMiddleware
from src.routes.stt import router as stt_router
from src.routes.system import router as system_router
from src.routes.tts import router as tts_router


# ---------------------------------------------------------------------------
# Fake models
# ---------------------------------------------------------------------------


@dataclass
class FakeGenerationResult:
    audio: object
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
    language: str | None = "en"


class FakeModelManager:
    tts_loaded = True
    stt_loaded = True
    tts_model_name = "fake-tts"
    stt_model_name = "fake-stt"

    def generate_tts(self, text, voice, speed, lang_code):
        t = np.linspace(0, 0.5, 12_000, endpoint=False)
        audio = np.sin(2 * np.pi * 440 * t).astype(np.float32)
        return [FakeGenerationResult(audio=audio, samples=len(audio))]

    def generate_stt(self, audio_path):
        return FakeSTTOutput(text="integration test transcription")


# ---------------------------------------------------------------------------
# App + fixture helpers
# ---------------------------------------------------------------------------


def _build_app(settings: Settings | None = None) -> FastAPI:
    """Build the real app stack but inject a FakeModelManager via lifespan."""
    if settings is None:
        settings = Settings()

    @asynccontextmanager
    async def fake_lifespan(app: FastAPI) -> AsyncIterator[None]:
        app.state.model_manager = FakeModelManager()
        app.state.settings = settings
        yield

    app = FastAPI(title="test", lifespan=fake_lifespan)
    app.add_middleware(
        CORSMiddleware,
        allow_origin_regex=r"https?://(localhost|127\.0\.0\.1)(:\d+)?",
        allow_methods=["GET", "POST"],
        allow_headers=["Content-Type"],
    )
    app.add_middleware(LimitsHeaderMiddleware)
    app.include_router(tts_router, prefix="/v1")
    app.include_router(stt_router, prefix="/v1")
    app.include_router(system_router, prefix="/v1")
    return app


@pytest.fixture()
def client():
    with TestClient(_build_app()) as c:
        yield c


def _wav_bytes() -> bytes:
    buf = io.BytesIO()
    with wave.open(buf, "wb") as wf:
        wf.setnchannels(1)
        wf.setsampwidth(2)
        wf.setframerate(24_000)
        wf.writeframes(b"\x00\x00" * 2400)
    return buf.getvalue()


# ---------------------------------------------------------------------------
# Health + Models
# ---------------------------------------------------------------------------


def test_health_endpoint(client: TestClient) -> None:
    resp = client.get("/v1/health")
    assert resp.status_code == 200
    assert resp.json()["status"] == "ok"


def test_models_endpoint(client: TestClient) -> None:
    resp = client.get("/v1/models")
    data = resp.json()
    assert data["tts"]["loaded"] is True
    assert data["stt"]["loaded"] is True


# ---------------------------------------------------------------------------
# TTS end-to-end
# ---------------------------------------------------------------------------


def test_tts_full_request(client: TestClient) -> None:
    resp = client.post("/v1/tts", json={"text": "Hello, can you hear me?"})
    assert resp.status_code == 200
    assert resp.headers["content-type"] == "audio/wav"
    assert resp.content[:4] == b"RIFF"


def test_tts_with_all_params(client: TestClient) -> None:
    resp = client.post(
        "/v1/tts",
        json={"text": "Testing voice params", "voice": "af_sky", "speed": 1.2, "lang_code": "a"},
    )
    assert resp.status_code == 200


def test_tts_limit_header_present(client: TestClient) -> None:
    resp = client.post("/v1/tts", json={"text": "hi"})
    assert "x-limit-max-text-length" in resp.headers


def test_tts_limit_quoted_in_error() -> None:
    settings = Settings(limits={"max_text_length": 5, "max_audio_file_size": 26_214_400})
    with TestClient(_build_app(settings)) as c:
        resp = c.post("/v1/tts", json={"text": "too long text"})
    assert resp.status_code == 422
    detail = resp.json()["detail"]
    assert "5" in detail
    assert "X-Limit-Max-Text-Length" in detail


def test_tts_content_disposition_header(client: TestClient) -> None:
    resp = client.post("/v1/tts", json={"text": "hi"})
    assert "speech.wav" in resp.headers.get("content-disposition", "")


# ---------------------------------------------------------------------------
# STT end-to-end
# ---------------------------------------------------------------------------


def test_stt_full_request(client: TestClient) -> None:
    resp = client.post(
        "/v1/stt",
        files={"file": ("speech.wav", _wav_bytes(), "audio/wav")},
    )
    assert resp.status_code == 200
    assert resp.json()["text"] == "integration test transcription"


def test_stt_limit_header_present(client: TestClient) -> None:
    resp = client.post(
        "/v1/stt",
        files={"file": ("speech.wav", _wav_bytes(), "audio/wav")},
    )
    assert "x-limit-max-audio-file-size" in resp.headers


def test_stt_bad_mime_type(client: TestClient) -> None:
    resp = client.post(
        "/v1/stt",
        files={"file": ("note.txt", b"hello world", "text/plain")},
    )
    assert resp.status_code == 415


# ---------------------------------------------------------------------------
# CORS
# ---------------------------------------------------------------------------


def test_cors_allows_localhost(client: TestClient) -> None:
    resp = client.get("/v1/health", headers={"Origin": "http://localhost:3000"})
    assert "access-control-allow-origin" in resp.headers


def test_cors_blocks_external_origin(client: TestClient) -> None:
    resp = client.get("/v1/health", headers={"Origin": "https://evil.example.com"})
    assert "access-control-allow-origin" not in resp.headers


# ---------------------------------------------------------------------------
# CLI arg parsing (pure unit — no server started)
# ---------------------------------------------------------------------------


def test_cli_defaults() -> None:
    from main import _build_parser, _cli_overrides
    args = _build_parser().parse_args([])
    assert _cli_overrides(args) == {}


def test_cli_overrides_port_and_voice() -> None:
    from main import _build_parser, _cli_overrides
    args = _build_parser().parse_args(["--port", "9000", "--voice", "af_sky"])
    overrides = _cli_overrides(args)
    assert overrides["server"]["port"] == 9000
    assert overrides["tts"]["voice"] == "af_sky"


def test_cli_overrides_all_flags() -> None:
    from main import _build_parser, _cli_overrides
    args = _build_parser().parse_args([
        "--host", "0.0.0.0", "--port", "8080",
        "--tts-model", "my/tts", "--stt-model", "my/stt",
        "--voice", "af_sky", "--speed", "1.5", "--lang-code", "b",
        "--max-text-length", "2000", "--max-audio-file-size", "1048576",
    ])
    overrides = _cli_overrides(args)
    assert overrides["server"]["host"] == "0.0.0.0"
    assert overrides["tts"]["model"] == "my/tts"
    assert overrides["stt"]["model"] == "my/stt"
    assert overrides["tts"]["speed"] == 1.5
    assert overrides["limits"]["max_text_length"] == 2000
