"""Configuration loading: XDG config file + CLI override merging."""

from __future__ import annotations

import logging
import tomllib
from pathlib import Path
from typing import Any

from pydantic import BaseModel, Field, field_validator

logger = logging.getLogger(__name__)

XDG_CONFIG_PATH = Path.home() / ".config" / "conversational_ai" / "config.toml"

_DEFAULT_TOML = """\
[server]
host = "127.0.0.1"
port = 4114

[tts]
model = "mlx-community/Kokoro-82M-bf16"
voice = "af_heart"
speed = 1.0
lang_code = "a"

[stt]
model = "mlx-community/whisper-large-v3-turbo-asr-fp16"

[limits]
max_text_length = 5000
max_audio_file_size = 26214400  # 25 MB

[log]
log_dir = "~/.local/state/conversational_ai"
max_age_days = 7
"""


class ServerSettings(BaseModel):
    host: str = "127.0.0.1"
    port: int = Field(default=4114, ge=1, le=65535)


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


class LogSettings(BaseModel):
    log_dir: str = str(Path.home() / ".local" / "state" / "conversational_ai")
    max_age_days: int = Field(default=7, ge=1)


class Settings(BaseModel):
    server: ServerSettings = Field(default_factory=ServerSettings)
    tts: TTSSettings = Field(default_factory=TTSSettings)
    stt: STTSettings = Field(default_factory=STTSettings)
    limits: LimitsSettings = Field(default_factory=LimitsSettings)
    log: LogSettings = Field(default_factory=LogSettings)

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
    def coerce_sst(cls, v: Any) -> Any:
        return v if isinstance(v, dict) else v

    @field_validator("limits", mode="before")
    @classmethod
    def coerce_limits(cls, v: Any) -> Any:
        return v if isinstance(v, dict) else v

    @field_validator("log", mode="before")
    @classmethod
    def coerce_log(cls, v: Any) -> Any:
        return v if isinstance(v, dict) else v


def ensure_xdg_config() -> Path:
    """Return the XDG config path, creating it with defaults if absent."""
    if not XDG_CONFIG_PATH.exists():
        XDG_CONFIG_PATH.parent.mkdir(parents=True, exist_ok=True)
        XDG_CONFIG_PATH.write_text(_DEFAULT_TOML, encoding="utf-8")
        logger.info("Created default config at %s", XDG_CONFIG_PATH)
    return XDG_CONFIG_PATH


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
    """Build Settings by layering: defaults < XDG config file < CLI overrides.

    When toml_path is None the XDG config (~/.config/conversational_ai/config.toml)
    is used, creating it with defaults if it does not yet exist.

    cli_overrides should use the nested structure:
        {"server": {"host": "0.0.0.0"}, "tts": {"voice": "af_sky"}}
    """
    merged: dict[str, Any] = {}

    resolved_path = toml_path if toml_path is not None else ensure_xdg_config()
    if resolved_path.exists():
        merged = load_config(resolved_path)

    if cli_overrides:
        merged = _deep_merge(merged, cli_overrides)

    return Settings(**merged)
