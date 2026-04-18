"""Tests for src/config.py — config loading, merging, and defaults."""

import tomllib
from pathlib import Path

import pytest

from src.config import Settings, build_settings, load_config


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------


@pytest.fixture()
def toml_file(tmp_path: Path) -> Path:
    """Write a minimal TOML config and return its path."""
    cfg = tmp_path / "config.toml"
    cfg.write_text(
        "[server]\n"
        'host = "0.0.0.0"\n'
        "port = 9000\n"
        "[tts]\n"
        'model = "mlx-community/Kokoro-82M-bf16"\n'
        'voice = "af_sky"\n'
        "speed = 1.5\n"
        'lang_code = "a"\n'
        "[stt]\n"
        'model = "mlx-community/whisper-tiny-asr-fp16"\n'
        "[limits]\n"
        "max_text_length = 1000\n"
        "max_audio_file_size = 1048576\n",
        encoding="utf-8",
    )
    return cfg


@pytest.fixture()
def project_config() -> Path:
    """Return the real project config.toml (if present)."""
    return Path(__file__).parent.parent / "config.toml"


# ---------------------------------------------------------------------------
# load_config
# ---------------------------------------------------------------------------


def test_load_config_reads_toml(toml_file: Path) -> None:
    data = load_config(toml_file)
    assert isinstance(data, dict)
    assert data["server"]["host"] == "0.0.0.0"
    assert data["server"]["port"] == 9000
    assert data["tts"]["voice"] == "af_sky"
    assert data["stt"]["model"] == "mlx-community/whisper-tiny-asr-fp16"


def test_load_config_project_file(project_config: Path) -> None:
    """The real config.toml must be valid TOML and parse without error."""
    if not project_config.exists():
        pytest.skip("config.toml not present")
    data = load_config(project_config)
    assert "server" in data
    assert "tts" in data
    assert "stt" in data


# ---------------------------------------------------------------------------
# build_settings — defaults
# ---------------------------------------------------------------------------


def test_defaults_when_no_file() -> None:
    s = build_settings(toml_path=None)
    assert s.server.host == "127.0.0.1"
    assert s.server.port == 4114
    assert s.tts.voice == "af_heart"
    assert s.tts.speed == 1.0
    assert s.stt.model == "mlx-community/whisper-large-v3-turbo-asr-fp16"
    assert s.limits.max_text_length == 5000
    assert s.limits.max_audio_file_size == 26_214_400


def test_defaults_when_file_missing(tmp_path: Path) -> None:
    missing = tmp_path / "nonexistent.toml"
    s = build_settings(toml_path=missing)
    assert s.server.host == "127.0.0.1"


# ---------------------------------------------------------------------------
# build_settings — TOML overrides defaults
# ---------------------------------------------------------------------------


def test_toml_overrides_defaults(toml_file: Path) -> None:
    s = build_settings(toml_path=toml_file)
    assert s.server.host == "0.0.0.0"
    assert s.server.port == 9000
    assert s.tts.voice == "af_sky"
    assert s.tts.speed == 1.5
    assert s.limits.max_text_length == 1000


# ---------------------------------------------------------------------------
# build_settings — CLI overrides TOML
# ---------------------------------------------------------------------------


def test_cli_overrides_toml(toml_file: Path) -> None:
    overrides = {"server": {"port": 7777}, "tts": {"voice": "af_heart"}}
    s = build_settings(toml_path=toml_file, cli_overrides=overrides)
    # CLI wins
    assert s.server.port == 7777
    assert s.tts.voice == "af_heart"
    # Other TOML values unchanged
    assert s.server.host == "0.0.0.0"
    assert s.tts.speed == 1.5


def test_cli_overrides_without_toml() -> None:
    overrides = {"server": {"host": "192.168.1.1", "port": 8888}}
    s = build_settings(toml_path=None, cli_overrides=overrides)
    assert s.server.host == "192.168.1.1"
    assert s.server.port == 8888
    # Non-overridden defaults preserved
    assert s.tts.voice == "af_heart"


def test_none_values_in_cli_not_applied(toml_file: Path) -> None:
    """CLI dict values that are None should not overwrite TOML values."""
    overrides = {"server": {"port": None}}
    s = build_settings(toml_path=toml_file, cli_overrides=overrides)
    assert s.server.port == 9000  # TOML value preserved


# ---------------------------------------------------------------------------
# Settings validation
# ---------------------------------------------------------------------------


def test_invalid_port_raises() -> None:
    with pytest.raises(Exception):
        Settings(server={"port": 99999})


def test_invalid_speed_raises() -> None:
    with pytest.raises(Exception):
        Settings(tts={"speed": 0.0})


def test_speed_upper_bound_raises() -> None:
    with pytest.raises(Exception):
        Settings(tts={"speed": 10.0})


# ---------------------------------------------------------------------------
# [mic] section — Feature 1 noise floor controls
# ---------------------------------------------------------------------------


def test_mic_defaults() -> None:
    s = build_settings(toml_path=None)
    assert s.mic.rms_threshold == 0.01
    assert s.mic.silence_seconds == 1.5
    assert s.mic.min_speech_seconds == 0.15
    assert s.mic.calibrate_noise is False
    assert s.mic.calibration_seconds == 1.0
    assert s.mic.calibration_multiplier == 3.0


def test_mic_toml_overrides(tmp_path: Path) -> None:
    cfg = tmp_path / "config.toml"
    cfg.write_text(
        "[mic]\n"
        "rms_threshold = 0.05\n"
        "silence_seconds = 2.5\n"
        "min_speech_seconds = 0.3\n"
        "calibrate_noise = true\n"
        "calibration_seconds = 2.0\n"
        "calibration_multiplier = 5.0\n",
        encoding="utf-8",
    )
    s = build_settings(toml_path=cfg)
    assert s.mic.rms_threshold == 0.05
    assert s.mic.silence_seconds == 2.5
    assert s.mic.min_speech_seconds == 0.3
    assert s.mic.calibrate_noise is True
    assert s.mic.calibration_seconds == 2.0
    assert s.mic.calibration_multiplier == 5.0


def test_mic_cli_overrides_toml(tmp_path: Path) -> None:
    cfg = tmp_path / "config.toml"
    cfg.write_text(
        "[mic]\nrms_threshold = 0.05\nmin_speech_seconds = 0.3\n",
        encoding="utf-8",
    )
    overrides = {"mic": {"rms_threshold": 0.1}}
    s = build_settings(toml_path=cfg, cli_overrides=overrides)
    assert s.mic.rms_threshold == 0.1
    assert s.mic.min_speech_seconds == 0.3  # TOML preserved


def test_mic_rejects_negative_threshold() -> None:
    with pytest.raises(Exception):
        Settings(mic={"rms_threshold": -0.1})


def test_mic_rejects_multiplier_below_one() -> None:
    with pytest.raises(Exception):
        Settings(mic={"calibration_multiplier": 0.5})
