"""GET /v1/health and GET /v1/models — server status endpoints."""

from __future__ import annotations

from fastapi import APIRouter, Request

from src.schemas import HealthResponse, ModelInfo, ModelsResponse

router = APIRouter()


@router.get("/health", response_model=HealthResponse)
async def health(request: Request) -> HealthResponse:
    """Return server health and model load status."""
    mm = request.app.state.model_manager
    tts_ok = mm.tts_loaded
    stt_ok = mm.stt_loaded

    if tts_ok and stt_ok:
        status = "ok"
    elif tts_ok or stt_ok:
        status = "degraded"
    else:
        status = "unavailable"

    return HealthResponse(status=status, tts_loaded=tts_ok, stt_loaded=stt_ok)


@router.get("/models", response_model=ModelsResponse)
async def models(request: Request) -> ModelsResponse:
    """Return the names and load status of the configured models."""
    mm = request.app.state.model_manager
    return ModelsResponse(
        tts=ModelInfo(name=mm.tts_model_name, loaded=mm.tts_loaded),
        stt=ModelInfo(name=mm.stt_model_name, loaded=mm.stt_loaded),
    )
