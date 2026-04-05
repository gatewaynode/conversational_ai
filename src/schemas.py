"""Pydantic request and response models for all API endpoints."""

from __future__ import annotations

from pydantic import BaseModel, Field, field_validator

# Hard upper cap regardless of config — prevents absurdly large payloads
# The route handler enforces the softer config-driven limit on top of this.
_ABSOLUTE_MAX_TEXT = 10_000


class TTSRequest(BaseModel):
    text: str = Field(..., description="Text to synthesise.")
    voice: str | None = Field(None, description="Voice name (e.g. 'af_heart').")
    speed: float | None = Field(None, ge=0.1, le=5.0, description="Playback speed.")
    lang_code: str | None = Field(None, description="Language code (e.g. 'a' for auto).")

    @field_validator("text")
    @classmethod
    def text_not_empty(cls, v: str) -> str:
        v = v.strip()
        if not v:
            raise ValueError("text must not be empty or whitespace.")
        if len(v) > _ABSOLUTE_MAX_TEXT:
            raise ValueError(
                f"text length {len(v)} exceeds the absolute maximum of "
                f"{_ABSOLUTE_MAX_TEXT} characters. "
                f"Check the X-Limit-Max-Text-Length response header for the "
                f"configured limit on this server."
            )
        return v


class STTResponse(BaseModel):
    text: str
    segments: list[dict] | None = None
    language: str | None = None


class ModelInfo(BaseModel):
    name: str | None
    loaded: bool


class ModelsResponse(BaseModel):
    tts: ModelInfo
    stt: ModelInfo


class HealthResponse(BaseModel):
    status: str
    tts_loaded: bool
    stt_loaded: bool
