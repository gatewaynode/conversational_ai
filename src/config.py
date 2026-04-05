"""Configuration loading: TOML file + CLI override merging."""

from __future__ import annotations

import tomllib
from pathlib import Path
from typing import Any

from pydantic import BaseModel, Field, field_validator


class ServerSettings(BaseModel):
    host: str = "127.0.0.1"
    port: int = Field(default=8000, ge=1, le=65535)


class TTSSettings(BaseModel):
    model: str = "mlx-community/Kokoro-82M-bf16"
    voice: str = "af_heart"
    speed: float = Field(default=1.0, ge=0.1, le=5.0)
    lang_code: str = "a"


class STTSettings(BaseModel):
    model: str = "mlx-community/whisper-large-v3-turbo-asr-fp16"


class LimitsSettings(BaseModel):
    max_text_length: int = Field(default=5000, ge=1)
    max_audio_file_size: int = Field(default=26_214_400, ge=1)  # 25 MB


class Settings(BaseModel):
    server: ServerSettings = Field(default_factory=ServerSettings)
    tts: TTSSettings = Field(default_factory=TTSSettings)
    stt: STTSettings = Field(default_factory=STTSettings)
    limits: LimitsSettings = Field(default_factory=LimitsSettings)

    @field_validator("server", mode="before")
    @classmethod
    def coerce_server(cls, v: Any) -> Any:
        return v if isinstance(v, dict) else v

    @field_validator("tts", mode="before")
    @classmethod
    def coerce_tts(cls, v: Any) -> Any:
        return v if isinstance(v, dict) else v

    @field_validator("stt", mode="before")
    @classmethod
    def coerce_stt(cls, v: Any) -> Any:
        return v if isinstance(v, dict) else v

    @field_validator("limits", mode="before")
    @classmethod
    def coerce_limits(cls, v: Any) -> Any:
        return v if isinstance(v, dict) else v


def load_config(path: Path) -> dict[str, Any]:
    """Read a TOML config file and return its contents as a dict."""
    with open(path, "rb") as f:
        return tomllib.load(f)


def _deep_merge(base: dict[str, Any], overrides: dict[str, Any]) -> dict[str, Any]:
    """Recursively merge overrides into base. Overrides win on conflict."""
    result = dict(base)
    for key, value in overrides.items():
        if key in result and isinstance(result[key], dict) and isinstance(value, dict):
            result[key] = _deep_merge(result[key], value)
        elif value is not None:
            result[key] = value
    return result


def build_settings(
    toml_path: Path | None = None,
    cli_overrides: dict[str, Any] | None = None,
) -> Settings:
    """Build Settings by layering: defaults < TOML file < CLI overrides.

    cli_overrides should use the nested structure:
        {"server": {"host": "0.0.0.0"}, "tts": {"voice": "af_sky"}}
    """
    merged: dict[str, Any] = {}

    if toml_path is not None and toml_path.exists():
        merged = load_config(toml_path)

    if cli_overrides:
        merged = _deep_merge(merged, cli_overrides)

    return Settings(**merged)
