"""Configuration loading: XDG config file + CLI override merging."""

from __future__ import annotations

import logging
import tomllib
from pathlib import Path
from typing import Any

from pydantic import BaseModel, Field

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

[models]
models_dir = "~/.lmstudio/models"

[dialogue]
speak_file = "~/.local/share/conversational_ai/speak.txt"
listen_file = "~/.local/share/conversational_ai/listen.txt"
barge_in = true
full_duplex = true

[mic]
# RMS energy above which a chunk is considered speech. 0.01 is a reasonable
# default on a quiet room; noisier environments should calibrate instead of
# guessing.
rms_threshold = 0.01
# Trailing silence required to end an utterance.
silence_seconds = 1.5
# Minimum sustained speech (above threshold) required to latch a recording.
# Filters single-chunk transients like keyboard clacks and door slams.
min_speech_seconds = 0.15
# If true, sample room tone at startup and raise the effective threshold to
# max(rms_threshold, measured_floor * calibration_multiplier). Opt-in because
# it adds ~1s of startup latency.
calibrate_noise = false
calibration_seconds = 1.0
calibration_multiplier = 3.0

[wake_word]
# Require the user to say a trigger word before STT output passes through to
# the sink file. Reuses the already-loaded Whisper model on short utterances
# — no extra wake-word model is loaded.
enabled = false
# Trigger must be followed by punctuation or end-of-utterance to match.
# "Computer, hello" → passes "hello"; "Computer science is cool" → no match.
# Pick a word you don't normally start sentences with.
word = "computer"
# When true, the trigger stays in the emitted line; when false (default) it
# is stripped along with the trailing punctuation and leading whitespace.
include_trigger = false
# Seconds of silence after the last passed utterance before the gate
# re-arms and requires the trigger again.
timeout_seconds = 30.0
# Play a short two-tone chime on trigger activation. stderr echo fires
# regardless.
alert_sound = true

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


class ModelsSettings(BaseModel):
    models_dir: str = str(Path.home() / ".lmstudio" / "models")


class DialogueSettings(BaseModel):
    speak_file: str = str(Path.home() / ".local" / "share" / "conversational_ai" / "speak.txt")
    listen_file: str = str(Path.home() / ".local" / "share" / "conversational_ai" / "listen.txt")
    barge_in: bool = True
    full_duplex: bool = True


class MicSettings(BaseModel):
    rms_threshold: float = Field(default=0.01, ge=0.0, le=1.0)
    silence_seconds: float = Field(default=1.5, gt=0.0, le=30.0)
    min_speech_seconds: float = Field(default=0.15, ge=0.0, le=5.0)
    calibrate_noise: bool = False
    calibration_seconds: float = Field(default=1.0, gt=0.0, le=10.0)
    calibration_multiplier: float = Field(default=3.0, ge=1.0, le=20.0)


class WakeWordSettings(BaseModel):
    enabled: bool = False
    word: str = "computer"
    include_trigger: bool = False
    timeout_seconds: float = Field(default=30.0, gt=0.0, le=600.0)
    alert_sound: bool = True


class Settings(BaseModel):
    server: ServerSettings = Field(default_factory=ServerSettings)
    tts: TTSSettings = Field(default_factory=TTSSettings)
    stt: STTSettings = Field(default_factory=STTSettings)
    models: ModelsSettings = Field(default_factory=ModelsSettings)
    dialogue: DialogueSettings = Field(default_factory=DialogueSettings)
    mic: MicSettings = Field(default_factory=MicSettings)
    wake_word: WakeWordSettings = Field(default_factory=WakeWordSettings)
    limits: LimitsSettings = Field(default_factory=LimitsSettings)
    log: LogSettings = Field(default_factory=LogSettings)


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
