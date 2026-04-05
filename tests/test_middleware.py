"""Tests for LimitsHeaderMiddleware — headers appear on all responses."""

from __future__ import annotations

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from src.config import LimitsSettings, Settings
from src.middleware import LimitsHeaderMiddleware


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _make_app(max_text: int = 5000, max_audio: int = 26_214_400) -> FastAPI:
    """Build a minimal FastAPI app with the middleware and a test route."""
    app = FastAPI()

    settings = Settings(limits={"max_text_length": max_text, "max_audio_file_size": max_audio})
    app.state.settings = settings

    app.add_middleware(LimitsHeaderMiddleware)

    @app.get("/ping")
    async def ping():
        return {"pong": True}

    @app.get("/boom")
    async def boom():
        from fastapi import HTTPException
        raise HTTPException(status_code=400, detail="intentional error")

    return app


# ---------------------------------------------------------------------------
# Tests
# ---------------------------------------------------------------------------


def test_limit_headers_on_200() -> None:
    client = TestClient(_make_app())
    resp = client.get("/ping")
    assert resp.status_code == 200
    assert resp.headers["x-limit-max-text-length"] == "5000"
    assert resp.headers["x-limit-max-audio-file-size"] == "26214400"


def test_limit_headers_on_error_response() -> None:
    """Limits must be present even when the server returns an error."""
    client = TestClient(_make_app())
    resp = client.get("/boom")
    assert resp.status_code == 400
    assert "x-limit-max-text-length" in resp.headers
    assert "x-limit-max-audio-file-size" in resp.headers


def test_limit_headers_reflect_custom_config() -> None:
    client = TestClient(_make_app(max_text=1000, max_audio=1_048_576))
    resp = client.get("/ping")
    assert resp.headers["x-limit-max-text-length"] == "1000"
    assert resp.headers["x-limit-max-audio-file-size"] == "1048576"


def test_missing_app_state_does_not_crash() -> None:
    """Middleware must not crash if app.state.settings is absent."""
    app = FastAPI()
    app.add_middleware(LimitsHeaderMiddleware)

    @app.get("/ping")
    async def ping():
        return {"ok": True}

    client = TestClient(app)
    resp = client.get("/ping")
    assert resp.status_code == 200
    assert "x-limit-max-text-length" not in resp.headers
